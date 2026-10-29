import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.db.engine import get_session
from bot.keyboards.inline import cancel_keyboard
from bot.keyboards.menus import CMD_DELETE_RECORDS, DELETE_RECORDS, menu_for_role
from bot.services import reports as report_service
from bot.services import transactions as tx_service
from bot.services import users as user_service
from bot.services.delivery import answer_callback_safely, answer_reliably, notify_group
from bot.services.ui import strip_buttons_in_background, strip_markup
from bot.utils import actor_label, esc

logger = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type == "private")

CONFIRM_WORD = "УДАЛИТЬ"


class DeleteRecordsStates(StatesGroup):
    entering_word = State()


@router.message(F.text == DELETE_RECORDS)
@router.message(Command(CMD_DELETE_RECORDS))
async def start_delete_records(message: Message, role: str | None, state: FSMContext, bot: Bot) -> None:
    if role != "owner":
        return
    await report_service.clear_report_buttons(bot, state)

    async with get_session() as session:
        summary = await tx_service.summarize_all_transactions(session)
    if summary.total == 0:
        await state.clear()
        await message.answer("Записей для удаления нет.")
        return

    per_account = "\n".join(f"• {esc(label)}: {count}" for label, count in summary.per_account)
    sent = await message.answer(
        "<b>Удалить записи</b>\n"
        f"Будут безвозвратно удалены ВСЕ записи транзакций: {summary.total}, "
        f"из них несверенных: {summary.unreconciled}.\n\n"
        f"По счетам:\n{per_account}\n\n"
        "Счета и их балансы останутся без изменений. Отменить удаление будет невозможно.\n\n"
        f"Чтобы подтвердить, отправьте слово «{CONFIRM_WORD}». "
        "Любое другое сообщение отменит удаление.",
        reply_markup=cancel_keyboard(),
    )
    # set_data (not update_data): leftovers of any abandoned earlier flow must not leak in
    await state.set_data({"max_id": summary.max_id, "total": summary.total, "summary_message_id": sent.message_id})
    await state.set_state(DeleteRecordsStates.entering_word)


@router.callback_query(DeleteRecordsStates.entering_word, F.data == "cancel")
async def cancel_delete_records(callback: CallbackQuery, state: FSMContext, role: str) -> None:
    await state.clear()
    await strip_markup(callback)
    await answer_reliably(callback.message, "Отменено.", reply_markup=menu_for_role(role))
    await answer_callback_safely(callback)


@router.message(DeleteRecordsStates.entering_word)
async def confirm_delete_records(
    message: Message, role: str | None, state: FSMContext, bot: Bot, config: Config
) -> None:
    data = await state.get_data()
    await state.clear()  # claim first: whatever happens below, this confirmation is used up
    if role != "owner":
        return

    # the summary message's "Отмена" button is dead from here on, whatever the outcome
    strip_targets = []
    if data.get("summary_message_id"):
        strip_targets.append((message.chat.id, data["summary_message_id"]))

    if (message.text or "").strip().casefold() != CONFIRM_WORD.casefold():
        strip_buttons_in_background(bot, strip_targets)
        await answer_reliably(
            message, "Слово не совпало — удаление отменено, ничего не удалено.", reply_markup=menu_for_role(role)
        )
        return
    if "max_id" not in data or "total" not in data:
        strip_buttons_in_background(bot, strip_targets)
        await answer_reliably(
            message, "Запрос на удаление устарел. Запустите функцию заново.", reply_markup=menu_for_role(role)
        )
        return

    async with get_session() as session:
        actor = await user_service.get_active_user(session, message.from_user.id)
        try:
            deleted = await tx_service.delete_all_transactions(
                session, max_id=data["max_id"], expected_total=data["total"]
            )
        except tx_service.RecordsChangedError as exc:
            strip_buttons_in_background(bot, strip_targets)
            if exc.found == 0:
                text = "Записей для удаления уже нет — возможно, они уже удалены."
            else:
                text = (
                    "Список записей изменился, пока шло подтверждение, поэтому ничего не удалено. "
                    "Запустите функцию заново."
                )
            await answer_reliably(message, text, reply_markup=menu_for_role(role))
            return

    # Deleted and committed. Same rules as every other post-commit step: independent,
    # retried, never raising (see bot/services/delivery.py).
    strip_buttons_in_background(bot, strip_targets + deleted.card_targets)
    await answer_reliably(
        message,
        f"Удалено записей: {deleted.count}. Счета и их балансы не изменены.",
        reply_markup=menu_for_role(role),
    )
    await notify_group(
        bot,
        config,
        f"<b>Записи удалены</b>\nУдалено транзакций: {deleted.count}\nВыполнил: {esc(actor_label(actor))}",
        reply_to=message,
    )
