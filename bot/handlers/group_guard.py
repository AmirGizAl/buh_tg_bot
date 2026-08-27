import logging

from aiogram import Bot, Router
from aiogram.types import ChatMemberUpdated

from bot.config import Config

router = Router()
logger = logging.getLogger(__name__)


@router.my_chat_member()
async def guard_group_membership(event: ChatMemberUpdated, bot: Bot, config: Config) -> None:
    """Closed contour: the bot only ever serves the one pre-configured group chat.
    If it's added anywhere else, it leaves immediately."""
    chat = event.chat
    new_status = event.new_chat_member.status
    if (
        chat.type in ("group", "supergroup")
        and new_status in ("member", "administrator")
        and chat.id != config.group_chat_id
    ):
        logger.warning("Bot added to foreign chat %s (%s), leaving", chat.id, chat.title)
        await bot.leave_chat(chat.id)
