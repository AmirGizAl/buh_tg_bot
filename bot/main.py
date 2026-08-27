import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
from sqlalchemy import select

from bot.config import MSK, load_config
from bot.db.engine import get_session, init_db, init_engine
from bot.db.models import User, UserStatus
from bot.fsm_storage import storage
from bot.handlers import access, accounts, group_guard, reconcile, reports, start, transactions
from bot.middlewares.access import AccessMiddleware
from bot.services import commands as command_service
from bot.services import users as user_service

logger = logging.getLogger(__name__)


class MskFormatter(logging.Formatter):
    """Formats log timestamps in MSK (UTC+3), regardless of the host/container timezone."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created, tz=MSK)
        return dt.strftime(datefmt or "%Y-%m-%d %H:%M:%S %Z")


async def _delete_webhook_with_retry(bot: Bot, attempts: int = 10, delay: float = 5.0) -> None:
    for attempt in range(1, attempts + 1):
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            return
        except TelegramNetworkError as exc:
            logger.warning("Cannot reach Telegram yet (attempt %s/%s): %s", attempt, attempts, exc)
            if attempt == attempts:
                logger.warning("Giving up on delete_webhook, proceeding to polling anyway")
                return
            await asyncio.sleep(delay)


async def _set_commands(bot: Bot) -> None:
    """Registers the "/" commands menu for every currently-active user (owner +
    employees). Unlike a fixed two-actor setup, this list changes at runtime as
    employees are added/removed — see AccessMiddleware and bot/handlers/access.py for
    the incremental updates that keep it in sync after startup."""
    try:
        await command_service.set_default_commands(bot)
        async with get_session() as session:
            result = await session.execute(select(User).where(User.status == UserStatus.ACTIVE))
            active_users = list(result.scalars())
        for user in active_users:
            if user.telegram_user_id is not None:
                await command_service.set_commands_for(bot, user.telegram_user_id, user.role.value)
    except TelegramNetworkError as exc:
        logger.warning("Could not register bot commands (will retry on next restart): %s", exc)


async def main() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(MskFormatter("%(asctime)s %(levelname)s:%(name)s:%(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    config = load_config()

    init_engine(config.db_path)
    await init_db()

    async with get_session() as session:
        await user_service.get_or_seed_owner(session, config.owner_id)

    session_ = AiohttpSession(proxy=config.proxy_url) if config.proxy_url else None

    async with Bot(
        token=config.bot_token,
        session=session_,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    ) as bot:
        dp = Dispatcher(storage=storage)
        dp["config"] = config

        access_middleware = AccessMiddleware(config)
        dp.message.middleware(access_middleware)
        dp.callback_query.middleware(access_middleware)

        dp.include_router(group_guard.router)
        dp.include_router(start.router)
        dp.include_router(accounts.router)
        dp.include_router(transactions.router)
        dp.include_router(reconcile.router)
        dp.include_router(reports.router)
        dp.include_router(access.router)

        await _delete_webhook_with_retry(bot)
        await _set_commands(bot)
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
