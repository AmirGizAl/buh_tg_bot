from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.db.engine import get_session
from bot.keyboards.inline import confirm_keyboard, employee_picker
from bot.keyboards.menus import (
    ADD_EMPLOYEE,
    CMD_ADD_EMPLOYEE,
    CMD_REMOVE_EMPLOYEE,
    CMD_TEAM_MEMBERS,
    REMOVE_EMPLOYEE,
    TEAM_MEMBERS,
    menu_for_role,
)
from bot.services import commands as command_service
from bot.services import reports as report_service
from bot.services import users as user_service
from bot.services.notify import post_to_group
from bot.utils import actor_label, esc

router = Router()
router.message.filter(F.chat.type == "private")


class AddEmployeeStates(StatesGroup):
    entering_username = State()
    confirming = State()


class RemoveEmployeeStates(StatesGroup):
    choosing_employee = State()
    confirming = State()


@router.message(F.text == ADD_EMPLOYEE)
@router.message(Command(CMD_ADD_EMPLOYEE))
async def start_add_employee(message: Message, role: str | None, state: FSMContext, bot: Bot) -> None:
    if role != "owner":
        return
    await report_service.clear_report_buttons(bot, state)
    await state.set_state(AddEmployeeStates.entering_username)
    await message.answer("Введите @username сотрудника в Telegram:")


@router.message(AddEmployeeStates.entering_username)
async def enter_employee_username(message: Message, state: FSMContext) -> None:
    username = (message.text or "").strip()
    if not username.lstrip("@"):
        await message.answer("Пожалуйста, укажите корректный username.")
        return
    await state.update_data(username=username)
    await state.set_state(AddEmployeeStates.confirming)
    await message.answer(
        f"Допустить сотрудника @{esc(username.lstrip('@'))}?", reply_markup=confirm_keyboard()
    )


@router.callback_query(AddEmployeeStates.confirming, F.data == "cancel")
async def cancel_add_employee(callback: CallbackQuery, state: FSMContext, role: str) -> None:
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Отменено.", reply_markup=menu_for_role(role))
    await callback.answer()


@router.callback_query(AddEmployeeStates.confirming, F.data == "confirm")
async def confirm_add_employee(
    callback: CallbackQuery, state: FSMContext, role: str, bot: Bot, config: Config
) -> None:
    data = await state.get_data()
    async with get_session() as session:
        try:
            user = await user_service.invite_employee(session, data["username"])
        except user_service.AlreadyInvitedError:
            await state.clear()
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(
                "Этот пользователь уже приглашён или уже сотрудник.", reply_markup=menu_for_role(role)
            )
            await callback.answer()
            return

    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"Сотрудник @{esc(user.username_display)} приглашён. Доступ откроется, как только он "
        "напишет боту или что-нибудь в общем чате.",
        reply_markup=menu_for_role(role),
    )
    await post_to_group(bot, config, f"<b>Приглашён новый сотрудник</b>\n@{esc(user.username_display)}")
    await callback.answer()


@router.message(F.text == REMOVE_EMPLOYEE)
@router.message(Command(CMD_REMOVE_EMPLOYEE))
async def start_remove_employee(message: Message, role: str | None, state: FSMContext, bot: Bot) -> None:
    if role != "owner":
        return
    await report_service.clear_report_buttons(bot, state)
    async with get_session() as session:
        employees = await user_service.list_active_employees(session)
    if not employees:
        await message.answer("Нет активных сотрудников.")
        return
    await state.set_state(RemoveEmployeeStates.choosing_employee)
    await message.answer("Выберите сотрудника для удаления:", reply_markup=employee_picker(employees))


@router.callback_query(RemoveEmployeeStates.choosing_employee, F.data.startswith("emp:"))
async def choose_employee_to_remove(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        employee = await user_service.get_employee(session, user_id)
    if employee is None:
        await callback.answer("Сотрудник не найден.", show_alert=True)
        return
    await state.update_data(user_id=user_id)
    await state.set_state(RemoveEmployeeStates.confirming)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"Удалить сотрудника {esc(actor_label(employee))}?", reply_markup=confirm_keyboard()
    )
    await callback.answer()


@router.callback_query(RemoveEmployeeStates.confirming, F.data == "cancel")
async def cancel_remove_employee(callback: CallbackQuery, state: FSMContext, role: str) -> None:
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Отменено.", reply_markup=menu_for_role(role))
    await callback.answer()


@router.callback_query(RemoveEmployeeStates.confirming, F.data == "confirm")
async def confirm_remove_employee(
    callback: CallbackQuery, state: FSMContext, role: str, bot: Bot, config: Config
) -> None:
    data = await state.get_data()
    async with get_session() as session:
        employee = await user_service.remove_employee(session, data["user_id"])

    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"Сотрудник удалён: {esc(actor_label(employee))}", reply_markup=menu_for_role(role)
    )

    if employee.telegram_user_id:
        try:
            await command_service.reset_commands_for(bot, employee.telegram_user_id)
        except TelegramBadRequest:
            pass

    await post_to_group(bot, config, f"<b>Сотрудник удалён</b>\n{esc(actor_label(employee))}")
    await callback.answer()


@router.message(F.text == TEAM_MEMBERS)
@router.message(Command(CMD_TEAM_MEMBERS))
async def show_team_members(message: Message, role: str | None, state: FSMContext, bot: Bot) -> None:
    if role != "owner":
        return
    await report_service.clear_report_buttons(bot, state)
    async with get_session() as session:
        active = await user_service.list_active_employees(session)
        pending = await user_service.list_pending_invites(session)

    lines = ["<b>Члены команды</b>"]
    if active:
        lines.append("\n<b>Активные:</b>")
        lines += [f"— {esc(actor_label(e))}" for e in active]
    if pending:
        lines.append("\n<b>Ожидают первого сообщения боту:</b>")
        lines += [f"— @{esc(e.username_display)}" for e in pending]
    if not active and not pending:
        lines.append("Пока нет ни одного сотрудника.")
    await message.answer("\n".join(lines))
