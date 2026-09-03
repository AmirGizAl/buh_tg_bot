from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.db.engine import get_session
from bot.keyboards.inline import account_picker, draft_keyboard, rollback_confirm_keyboard, rollback_keyboard
from bot.keyboards.menus import CMD_EXPENSE, CMD_INCOME, EXPENSE, INCOME
from bot.services import accounts as account_service
from bot.services import drafts as draft_service
from bot.services import reports as report_service
from bot.services import transactions as tx_service
from bot.services import users as user_service
from bot.services.notify import post_to_group
from bot.services.transactions import AlreadyReconciledError, InsufficientFundsError, NotAuthorError
from bot.utils import esc, format_amount, parse_amount_and_comment

router = Router()
router.message.filter(F.chat.type == "private")

DIRECTION_LABEL = {"income": INCOME, "expense": EXPENSE}


class TransactionStates(StatesGroup):
    choosing_account = State()
    entering_amount = State()


async def _start(message: Message, role: str | None, state: FSMContext, bot: Bot, direction: str) -> None:
    if role not in ("owner", "employee"):
        return
    await report_service.clear_report_buttons(bot, state)
    async with get_session() as session:
        accounts = await account_service.list_accounts(session)
    if not accounts:
        await message.answer("Нет ни одного счёта. Сначала создайте счёт.")
        return
    await state.update_data(direction=direction)
    await state.set_state(TransactionStates.choosing_account)
    await message.answer(f"{DIRECTION_LABEL[direction]}. Выберите счёт:", reply_markup=account_picker(accounts))


@router.message(F.text == INCOME)
@router.message(Command(CMD_INCOME))
async def start_income(message: Message, role: str | None, state: FSMContext, bot: Bot) -> None:
    await _start(message, role, state, bot, "income")


@router.message(F.text == EXPENSE)
@router.message(Command(CMD_EXPENSE))
async def start_expense(message: Message, role: str | None, state: FSMContext, bot: Bot) -> None:
    await _start(message, role, state, bot, "expense")


@router.callback_query(TransactionStates.choosing_account, F.data.startswith("acc:"))
async def choose_account(callback: CallbackQuery, state: FSMContext) -> None:
    account_id = int(callback.data.split(":", 1)[1])
    await state.update_data(account_id=account_id)
    await state.set_state(TransactionStates.entering_amount)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Сумма и комментарий (например: 25+5*3-15/5 зарплата):")
    await callback.answer()


@router.message(TransactionStates.entering_amount)
async def enter_amount(message: Message, state: FSMContext) -> None:
    try:
        amount, comment = parse_amount_and_comment(message.text or "")
    except ValueError:
        await message.answer("Не удалось разобрать сумму. Введите число или выражение, например 25+5*3-15/5.")
        return

    data = await state.get_data()
    async with get_session() as session:
        account = await account_service.get_account(session, data["account_id"])

    direction = data["direction"]
    # The draft is now self-contained (see bot/services/drafts.py) — release the FSM
    # state immediately so starting any other action doesn't strand this draft's
    # buttons: they're addressed by draft id in their own callback_data from here on,
    # not by the user's current FSM state.
    await state.clear()
    draft_id = draft_service.create_draft(
        account_id=data["account_id"],
        direction=direction,
        amount=amount,
        comment=comment,
        actor_telegram_id=message.from_user.id,
    )

    signed = amount if direction == "income" else -amount
    summary = (
        f"<b>{DIRECTION_LABEL[direction]}</b>\n"
        f"Счёт: {esc(account.label)}\n"
        f"Сумма: {format_amount(signed, force_sign=True)}\n"
        f"Комментарий: {esc(comment) if comment else '—'}"
    )
    await message.answer(summary, reply_markup=draft_keyboard(draft_id))


@router.callback_query(F.data.startswith("draft_cancel:"))
async def cancel_draft(callback: CallbackQuery) -> None:
    draft_id = callback.data.split(":", 1)[1]
    draft = draft_service.get_draft(draft_id)
    if draft is None:
        await callback.answer(
            "Черновик недоступен: уже обработан или истёк срок ожидания (48 ч).", show_alert=True
        )
        return
    if draft.actor_telegram_id != callback.from_user.id:
        await callback.answer("Это не ваш черновик.", show_alert=True)
        return
    draft_service.pop_draft(draft_id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Черновик отменён.")
    await callback.answer()


@router.callback_query(F.data.startswith("draft_confirm:"))
async def confirm_draft(callback: CallbackQuery, bot: Bot, config: Config) -> None:
    draft_id = callback.data.split(":", 1)[1]
    draft = draft_service.get_draft(draft_id)
    if draft is None:
        await callback.answer(
            "Черновик недоступен: уже обработан или истёк срок ожидания (48 ч).", show_alert=True
        )
        return
    if draft.actor_telegram_id != callback.from_user.id:
        await callback.answer("Это не ваш черновик.", show_alert=True)
        return

    async with get_session() as session:
        actor = await user_service.get_active_user(session, callback.from_user.id)
        try:
            tx, account = await tx_service.create_transaction(
                session,
                account_id=draft.account_id,
                direction=draft.direction,
                amount=draft.amount,
                comment=draft.comment,
                actor=actor,
            )
        except InsufficientFundsError:
            draft_service.pop_draft(draft_id)
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer("На счету недостаточно средств.")
            await callback.answer()
            return
        except LookupError:
            draft_service.pop_draft(draft_id)
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer("Счёт был удалён, черновик недействителен.")
            await callback.answer()
            return

    draft_service.pop_draft(draft_id)
    await callback.message.edit_reply_markup(reply_markup=None)

    comment = draft.comment
    record = (
        f"<b>{DIRECTION_LABEL[draft.direction]}</b>\n"
        f"Счёт: {esc(account.label)}\n"
        f"Сумма: {format_amount(tx.amount, force_sign=True)}\n"
        f"Комментарий: {esc(comment) if comment else '—'}\n"
        f"Баланс счёта: {format_amount(account.balance)}"
    )
    record_message = await callback.message.answer(record, reply_markup=rollback_keyboard(tx.id))
    async with get_session() as session:
        await tx_service.set_origin_message(session, tx.id, record_message.message_id)

    await post_to_group(
        bot,
        config,
        f"<b>{DIRECTION_LABEL[draft.direction]}</b>\n"
        f"Счёт: {esc(account.label)}\n"
        f"Сумма: {format_amount(tx.amount, force_sign=True)}\n"
        f"Комментарий: {esc(comment) if comment else '—'}\n"
        f"Баланс счёта: {format_amount(account.balance)}\n"
        f"Пользователь: {esc(actor.username_display or actor.full_name or callback.from_user.id)}",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rollback:"))
async def start_rollback(callback: CallbackQuery) -> None:
    tx_id = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        tx = await tx_service.get_transaction(session, tx_id)
    if tx is None:
        await callback.answer("Транзакция не найдена.", show_alert=True)
        return
    if tx.reconciled:
        await callback.answer("Транзакция уже сверена, откат недоступен.", show_alert=True)
        return
    await callback.message.answer("Откатить транзакцию?", reply_markup=rollback_confirm_keyboard(tx_id))
    await callback.answer()


@router.callback_query(F.data.startswith("rollback_cancel:"))
async def cancel_rollback(callback: CallbackQuery) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Отменено")


@router.callback_query(F.data.startswith("rollback_confirm:"))
async def confirm_rollback(callback: CallbackQuery, bot: Bot, config: Config) -> None:
    tx_id = int(callback.data.split(":", 1)[1])
    async with get_session() as session:
        try:
            snapshot = await tx_service.rollback_transaction(session, tx_id, callback.from_user.id)
        except LookupError:
            await callback.answer("Транзакция не найдена.", show_alert=True)
            return
        except AlreadyReconciledError:
            await callback.answer("Транзакция уже сверена, откат недоступен.", show_alert=True)
            return
        except NotAuthorError:
            await callback.answer("Откатить может только автор транзакции.", show_alert=True)
            return

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Транзакция откатана.")

    if snapshot.origin_message_id:
        try:
            await bot.edit_message_reply_markup(
                chat_id=callback.from_user.id, message_id=snapshot.origin_message_id, reply_markup=None
            )
        except TelegramBadRequest:
            pass

    await post_to_group(
        bot,
        config,
        f"<b>Откат транзакции</b>\n"
        f"Счёт: {esc(snapshot.account_label)}\n"
        f"Сумма: {format_amount(snapshot.amount, force_sign=True)}\n"
        f"Баланс счёта: {format_amount(snapshot.account_balance)}\n"
        f"Автор: {esc(snapshot.actor_label)}",
    )
    await callback.answer()
