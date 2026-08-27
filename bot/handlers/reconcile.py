from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.db.engine import get_session
from bot.keyboards.inline import account_picker, confirm_keyboard
from bot.keyboards.menus import CMD_RECONCILE, RECONCILE, menu_for_role
from bot.services import accounts as account_service
from bot.services import reports as report_service
from bot.services import transactions as tx_service
from bot.services.notify import post_to_group
from bot.utils import esc, format_amount

router = Router()
router.message.filter(F.chat.type == "private")


class ReconcileStates(StatesGroup):
    choosing_account = State()
    confirming = State()


@router.message(F.text == RECONCILE)
@router.message(Command(CMD_RECONCILE))
async def start_reconcile(message: Message, role: str | None, state: FSMContext, bot: Bot) -> None:
    if role not in ("owner", "employee"):
        return
    await report_service.clear_report_buttons(bot, state)
    async with get_session() as session:
        accounts = await account_service.list_accounts(session)
    if not accounts:
        await message.answer("Нет ни одного счёта.")
        return
    await state.set_state(ReconcileStates.choosing_account)
    await message.answer(
        "Выберите счёт для сверки:", reply_markup=account_picker(accounts, prefix="racc", include_all=True)
    )


@router.callback_query(ReconcileStates.choosing_account, F.data.startswith("racc:"))
async def choose_reconcile_target(callback: CallbackQuery, state: FSMContext) -> None:
    raw = callback.data.split(":", 1)[1]
    account_id = None if raw == "all" else int(raw)

    async with get_session() as session:
        pending = await report_service.fetch_transactions(session, reconciled=False, account_id=account_id)
        label = "По всем счетам"
        if account_id is not None:
            account = await account_service.get_account(session, account_id)
            label = account.label

    totals: dict[str, Decimal] = {}
    for tx in pending:
        cur = tx.account.currency.value
        totals[cur] = totals.get(cur, Decimal("0")) + Decimal(str(tx.amount))
    totals_text = "\n".join(f"{cur}: {format_amount(v, force_sign=True)}" for cur, v in totals.items())

    await state.update_data(account_id=account_id)
    await state.set_state(ReconcileStates.confirming)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"<b>Сверка</b>\n{esc(label)}\nНесверенных транзакций: {len(pending)}"
        + (f"\n{esc(totals_text)}" if totals_text else ""),
        reply_markup=confirm_keyboard(),
    )
    await callback.answer()


@router.callback_query(ReconcileStates.confirming, F.data == "cancel")
async def cancel_reconcile(callback: CallbackQuery, state: FSMContext, role: str) -> None:
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Отменено.", reply_markup=menu_for_role(role))
    await callback.answer()


@router.callback_query(ReconcileStates.confirming, F.data == "confirm")
async def confirm_reconcile(
    callback: CallbackQuery, state: FSMContext, role: str, bot: Bot, config: Config
) -> None:
    data = await state.get_data()
    account_id = data.get("account_id")
    async with get_session() as session:
        txs = await tx_service.reconcile(session, account_id=account_id)

    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"Сверено транзакций: {len(txs)}", reply_markup=menu_for_role(role))

    for tx in txs:
        if tx.origin_message_id and tx.created_by.telegram_user_id:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=tx.created_by.telegram_user_id,
                    message_id=tx.origin_message_id,
                    reply_markup=None,
                )
            except TelegramBadRequest:
                pass

    await post_to_group(bot, config, f"<b>Сверка выполнена</b>\nТранзакций: {len(txs)}")
    await callback.answer()
