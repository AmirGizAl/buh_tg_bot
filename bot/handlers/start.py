from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards.menus import menu_for_role
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
    await message.answer(
        f"Добро пожаловать! Ваша роль: {ROLE_LABEL[role]}. Выберите действие:",
        reply_markup=menu_for_role(role),
    )
