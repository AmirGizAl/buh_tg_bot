"""Reliable delivery of what the user and the group are told *after* the database has
already been changed.

The incident this exists for (2026-10-19): a transaction was committed, then the
confirmation message to the author hung on a Telegram request until the 60 s timeout.
The exception aborted the handler, so the group notification was never sent, the
confirmation card never reached the author, and the generic "an error occurred" notice
made them believe nothing was saved — they entered the record again and it was booked
twice.

The rules these helpers enforce:
- every step after the commit is independent: a failure of one must not skip the rest;
- transient network trouble (timeouts, resets) and flood control are retried;
- a failure is never allowed to escape as an exception that reads as "nothing happened":
  it is logged, and the user is told plainly what *did* get saved.

Caveat of retrying after a timeout: the first attempt may actually have been delivered
(only the reply got lost), so a message can very rarely appear twice. That is harmless
for the author's card (its "Откатить" button is bound to the transaction id, not to the
message) and a far smaller evil than a silently missing notification.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramRetryAfter
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.services.notify import post_to_group

logger = logging.getLogger(__name__)

T = TypeVar("T")

_ATTEMPTS = 3
_RETRY_DELAY = 1.0  # seconds, multiplied by the attempt number

GROUP_NOT_NOTIFIED = "Действие выполнено, но уведомление в группу не доставлено — сообщите команде вручную."
SAVED_NOT_CONFIRMED = (
    "Запись сохранена, но подтверждение не доставлено. "
    "Не вводите её повторно — проверьте «Отчёт → Текущий»."
)


async def with_retry(call: Callable[[], Awaitable[T]], *, attempts: int = _ATTEMPTS) -> T:
    """Run `call()`, retrying network errors/timeouts and flood control. Any other
    Telegram error (bad request, forbidden, ...) is not transient and is raised at once."""
    for attempt in range(1, attempts + 1):
        try:
            return await call()
        except TelegramRetryAfter as exc:
            if attempt == attempts:
                raise
            await asyncio.sleep(exc.retry_after + 1)
        except TelegramNetworkError as exc:
            if attempt == attempts:
                raise
            logger.warning("Telegram request failed (attempt %s/%s): %s", attempt, attempts, exc)
            await asyncio.sleep(_RETRY_DELAY * attempt)
    raise AssertionError("unreachable")  # pragma: no cover


async def answer_reliably(message: Message, text: str, **kwargs) -> Message | None:
    """message.answer() with retries. Returns the sent message, or None — after logging —
    if it could not be delivered. Never raises."""
    try:
        return await with_retry(lambda: message.answer(text, **kwargs))
    except Exception:
        logger.exception("Could not deliver message to chat %s", message.chat.id)
        return None


async def answer_callback_safely(callback: CallbackQuery, text: str | None = None, **kwargs) -> None:
    """callback.answer() that can't fail the handler (the query may be expired or already
    answered, or the network may be down)."""
    try:
        await callback.answer(text, **kwargs)
    except TelegramAPIError:
        pass


async def notify_group(bot: Bot, config: Config, text: str, *, reply_to: Message) -> bool:
    """Post to the shared group chat with retries. If it still fails, say so in the user's
    own chat (`reply_to`) so the team can be told by hand. Never raises."""
    try:
        await with_retry(lambda: post_to_group(bot, config, text))
        return True
    except Exception:
        logger.exception("Group notification failed")
        await answer_reliably(reply_to, GROUP_NOT_NOTIFIED)
        return False
