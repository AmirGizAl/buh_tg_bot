"""Cosmetic Telegram follow-ups (removing stale inline keyboards) that must never be
able to break the real work around them.

Two things went wrong in production when these were plain `await edit_reply_markup()`
calls inside the handlers:

1. Telegram answers a redundant edit with "message is not modified". Raised *after* a
   transaction was already committed, it aborted the handler mid-flow.
2. After a reconcile (or an account deletion) the old code stripped the "Откатить"
   button of every affected transaction in a tight loop, one API call each. Telegram's
   flood control (429, "retry in N") kicked in, the uncaught TelegramRetryAfter killed
   the handler halfway, and the group notification that came after the loop was never
   sent.

So: a single edit is wrapped (strip_markup), and bulk edits run as a paced background
task that waits out flood control instead of failing (strip_buttons_in_background).
"""

import asyncio
import logging
from collections.abc import Iterable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import CallbackQuery

logger = logging.getLogger(__name__)

_PACE_SECONDS = 0.3  # stay comfortably under Telegram's per-chat edit rate
_MAX_RETRIES = 3

# asyncio only keeps weak references to running tasks — hold on to them ourselves.
_background_tasks: set[asyncio.Task] = set()


async def strip_markup(callback: CallbackQuery) -> None:
    """Best-effort removal of the inline keyboard of the message a callback came from."""
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass


async def _strip_one(bot: Bot, chat_id: int, message_id: int) -> None:
    for attempt in range(_MAX_RETRIES + 1):
        try:
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
            return
        except TelegramRetryAfter as exc:
            if attempt == _MAX_RETRIES:
                logger.warning("Giving up stripping buttons of message %s in chat %s: flood control", message_id, chat_id)
                return
            await asyncio.sleep(exc.retry_after + 1)
        except TelegramAPIError:
            # message too old / already edited / deleted / chat unreachable — purely cosmetic
            return


async def _strip_all(bot: Bot, targets: list[tuple[int, int]]) -> None:
    try:
        for chat_id, message_id in targets:
            await _strip_one(bot, chat_id, message_id)
            await asyncio.sleep(_PACE_SECONDS)
    except Exception:
        logger.exception("Background button cleanup failed")


def strip_buttons_in_background(bot: Bot, targets: Iterable[tuple[int, int]]) -> None:
    """Remove inline keyboards from many messages without blocking (or ever failing) the
    calling handler. `targets` is (chat_id, message_id) pairs."""
    pairs = list(targets)
    if not pairs:
        return
    task = asyncio.create_task(_strip_all(bot, pairs))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
