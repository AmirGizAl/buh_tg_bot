import logging

from aiogram import Bot, Router
from aiogram.types import ErrorEvent

router = Router()
logger = logging.getLogger(__name__)

ERROR_TEXT = "Произошла ошибка, обратитесь к разработчику"


@router.error()
async def on_unhandled_error(event: ErrorEvent, bot: Bot) -> bool:
    """Last line of defence: any exception that escapes a handler or middleware ends up
    here instead of leaving the user staring at a button that silently did nothing.

    The full traceback still goes to the log (a handled error is not logged by aiogram
    itself, so it has to be done here). The user is told only in a private chat — in
    the shared group the bot stays silent, same as it does for everything else there."""
    update = event.update
    logger.error(
        "Unhandled error while processing update %s", update.update_id, exc_info=event.exception
    )

    callback = update.callback_query
    message = update.message or (callback.message if callback else None)
    chat = message.chat if message else None

    if callback:
        try:
            await callback.answer()  # stop the button's loading spinner
        except Exception:
            pass  # already answered, or too old — irrelevant here

    if chat is not None and chat.type == "private":
        try:
            await bot.send_message(chat.id, ERROR_TEXT)
        except Exception:
            logger.exception("Could not deliver the error notice to chat %s", chat.id)
    return True
