from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.db.engine import get_session
from bot.db.models import Currency
from bot.keyboards.inline import account_picker, confirm_keyboard, currency_picker
from bot.keyboards.menus import (
    CMD_CREATE_ACCOUNT,
    CMD_DELETE_ACCOUNT,
    CREATE_ACCOUNT,
    DELETE_ACCOUNT,
    menu_for_role,
)
from bot.services import accounts as account_service
from bot.services import reports as report_service
from bot.services.notify import post_to_group
from bot.utils import esc, format_amount

router = Router()
router.message.filter(F.chat.type == "private")


class CreateAccountStates(StatesGroup):
    choosing_currency = State()
    entering_name = State()
    confirming = State()


class DeleteAccountStates(StatesGroup):
    choosing_account = State()
    confirming = State()


@router.message(F.text == CREATE_ACCOUNT)
@router.message(Command(CMD_CREATE_ACCOUNT))
async def start_create_account(message: Message, role: str | None, state: FSMContext, bot: Bot) -> None:
    if role != "owner":
        return
    await report_service.clear_report_buttons(bot, state)
    await state.set_state(CreateAccountStates.choosing_currency)
    await message.answer("Выберите валюту счёта:", reply_markup=currency_picker())


@router.callback_query(CreateAccountStates.choosing_currency, F.data.startswith("currency:"))
async def choose_currency(callback: CallbackQuery, state: FSMContext) -> None:
    currency = callback.data.split(":", 1)[1]
    await state.update_data(currency=currency)
    await state.set_state(CreateAccountStates.entering_name)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Название счёта:")
    await callback.answer()


@router.message(CreateAccountStates.entering_name)
async def enter_account_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Пожалуйста, укажите название счёта.")
        return
    data = await state.update_data(name=name)
    summary = f"<b>Новый счёт</b>\n{esc(data['currency'])} {esc(name)}"
    await state.set_state(CreateAccountStates.confirming)
    await message.answer(summary, reply_markup=confirm_keyboard())


@router.callback_query(CreateAccountStates.confirming, F.data == "cancel")
async def cancel_create_account(callback: CallbackQuery, state: FSMContext, role: str) -> None:
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Отменено.", reply_markup=menu_for_role(role))
    await callback.answer()


@router.callback_query(CreateAccountStates.confirming, F.data == "confirm")
async def confirm_create_account(
    callback: CallbackQuery, state: FSMContext, role: str, bot: Bot, config: Config
) -> None:
    data = await state.get_data()
    async with get_session() as session:
        account = await account_service.create_account(session, Currency(data["currency"]), data["name"])

    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"Счёт создан: {esc(account.label)}", reply_markup=menu_for_role(role))
    await post_to_group(bot, config, f"<b>Новый счёт</b>\n{esc(account.label)}")
    await callback.answer()


@router.message(F.text == DELETE_ACCOUNT)
@router.message(Command(CMD_DELETE_ACCOUNT))
async def start_delete_account(message: Message, role: str | None, state: FSMContext, bot: Bot) -> None:
    if role != "owner":
        return
    await report_service.clear_report_buttons(bot, state)
    async with get_session() as session:
        accounts = await account_service.list_accounts(session)
    if not accounts:
        await message.answer("Нет ни одного счёта.")
        return
    await state.set_state(DeleteAccountStates.choosing_account)
    await message.answer("Выберите счёт для удаления:", reply_markup=account_picker(accounts))


@router.callback_query(DeleteAccountStates.choosing_account, F.data.startswith("acc:"))
async def choose_account_to_delete(callback: CallbackQuery, state: FSMContext) -> None:
    account_id = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        account = await account_service.get_account(session, account_id)
    await state.update_data(account_id=account_id)
    await state.set_state(DeleteAccountStates.confirming)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"<b>Удалить счёт</b>\n{esc(account.label)}\nБаланс: {format_amount(account.balance)}\n\n"
        "Все несверенные транзакции по этому счёту будут автоматически откатаны.",
        reply_markup=confirm_keyboard(),
    )
    await callback.answer()


@router.callback_query(DeleteAccountStates.confirming, F.data == "cancel")
async def cancel_delete_account(callback: CallbackQuery, state: FSMContext, role: str) -> None:
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Отменено.", reply_markup=menu_for_role(role))
    await callback.answer()


@router.callback_query(DeleteAccountStates.confirming, F.data == "confirm")
async def confirm_delete_account(
    callback: CallbackQuery, state: FSMContext, role: str, bot: Bot, config: Config
) -> None:
    data = await state.get_data()
    async with get_session() as session:
        account, rolled_back = await account_service.delete_account(session, data["account_id"])

    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"Счёт удалён: {esc(account.label)}", reply_markup=menu_for_role(role))

    # The "Откатить" button on each auto-rolled-back transaction's own DM message must
    # stop being clickable — same best-effort strip as a manual "Сверить".
    for rolled in rolled_back:
        if rolled.origin_message_id and rolled.author_telegram_id:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=rolled.author_telegram_id,
                    message_id=rolled.origin_message_id,
                    reply_markup=None,
                )
            except TelegramBadRequest:
                pass

    note = f"<b>Счёт удалён</b>\n{esc(account.label)}"
    if rolled_back:
        note += f"\nАвтоматически откатано транзакций: {len(rolled_back)}"
    await post_to_group(bot, config, note)
    await callback.answer()
