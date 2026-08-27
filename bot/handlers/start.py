from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards.menus import menu_for_role
from bot.services import commands as command_service
from bot.services import reports as report_service

router = Router()
router.message.filter(F.chat.type == "private")

ROLE_LABEL = {"owner": "владелец", "employee": "сотрудник"}


@router.message(CommandStart())
async def cmd_start(message: Message, role: str | None, state: FSMContext, bot: Bot) -> None:
    # role is only None here in theory — AccessMiddleware already denies unauthorized
    # DM messages before they ever reach a handler.
    if role is None:
        return
    await report_service.clear_report_buttons(bot, state)

    # The chat with this user is now guaranteed to exist from Telegram's point of
    # view, so this is the reliable place to (re)push their "/" command scope — it
    # covers the owner's very first /start (seeded ACTIVE at boot, so it's never
    # "newly activated" the way an invited employee is) and heals any user whose
    # commands failed to register at startup because Telegram didn't know their chat
    # yet (see bot/main.py:_set_commands).
    try:
        await command_service.set_commands_for(bot, message.from_user.id, role)
    except TelegramBadRequest:
        pass

    await message.answer(
        f"Добро пожаловать! Ваша роль: {ROLE_LABEL[role]}. Выберите действие:",
        reply_markup=menu_for_role(role),
    )
