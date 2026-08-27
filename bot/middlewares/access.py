from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.config import Config
from bot.db.engine import get_session
from bot.services import commands as command_service
from bot.services import users as user_service

DENIAL_TEXT = "Доступ запрещён. Этот бот доступен только участникам команды."


class AccessMiddleware(BaseMiddleware):
    def __init__(self, config: Config):
        self.config = config

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        chat = data.get("event_chat")

        role: str | None = None
        if tg_user is not None and not tg_user.is_bot:
            async with get_session() as session:
                # Runs for every sender in every observable chat (DM and the shared
                # group), regardless of access, so a pending employee invite gets
                # matched by username the moment that person shows up anywhere.
                activated = await user_service.observe_user(
                    session, tg_user.id, tg_user.username, tg_user.full_name
                )
                role = await user_service.resolve_role(session, tg_user.id)

            if activated is not None:
                bot = data.get("bot")
                if bot is not None:
                    await command_service.set_commands_for(
                        bot, activated.telegram_user_id, activated.role.value
                    )

        # Closed contour: only the user's own private chat or the one configured
        # group chat ever grant a role, no matter what the DB says.
        allowed_chat = chat is not None and (
            chat.type == "private" or chat.id == self.config.group_chat_id
        )
        if not allowed_chat:
            role = None

        data["role"] = role
        data["config"] = self.config

        if chat is not None and chat.type == "private" and role is None:
            if isinstance(event, Message):
                await event.answer(DENIAL_TEXT)
            elif isinstance(event, CallbackQuery):
                await event.answer(DENIAL_TEXT, show_alert=True)
            return None

        if chat is not None and chat.type != "private" and role is None:
            # Group chat, but sender isn't on the allow-list (or this isn't the
            # configured group at all) — total silence, no reply of any kind.
            return None

        return await handler(event, data)
