from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.db.engine import get_session
from bot.keyboards.inline import current_report_export_keyboard, period_picker, report_format_keyboard
from bot.keyboards.menus import CMD_REPORT_CURRENT, CMD_REPORT_RECONCILED, REPORT_CURRENT, REPORT_RECONCILED
from bot.services import reports as report_service

router = Router()
router.message.filter(F.chat.type == "private")


class ReconciledReportStates(StatesGroup):
    choosing_period = State()


@router.message(F.text == REPORT_CURRENT)
@router.message(Command(CMD_REPORT_CURRENT))
async def show_current_report(message: Message, role: str | None, state: FSMContext, bot: Bot) -> None:
    if role not in ("owner", "employee"):
        return
    await report_service.clear_report_buttons(bot, state)
    async with get_session() as session:
        pending = await report_service.fetch_transactions(session, reconciled=False)
    preview = report_service.render_current_preview(pending)
    sent = await message.answer(preview, reply_markup=current_report_export_keyboard())
    await report_service.remember_report_buttons(state, sent.chat.id, sent.message_id)


@router.callback_query(F.data.in_({"export:current:xlsx", "export:current:csv"}))
async def export_current_report(callback: CallbackQuery) -> None:
    fmt = callback.data.rsplit(":", 1)[-1]
    async with get_session() as session:
        pending = await report_service.fetch_transactions(session, reconciled=False)
    rows = [report_service.to_full_row(tx) for tx in pending]
    if fmt == "xlsx":
        buffer = report_service.build_xlsx(rows, report_service.FULL_HEADERS)
        filename = "report_current.xlsx"
    else:
        buffer = report_service.build_csv(rows, report_service.FULL_HEADERS)
        filename = "report_current.csv"
    await callback.message.answer_document(BufferedInputFile(buffer.read(), filename=filename))
    await callback.answer()


@router.message(F.text == REPORT_RECONCILED)
@router.message(Command(CMD_REPORT_RECONCILED))
async def start_reconciled_report(message: Message, role: str | None, state: FSMContext, bot: Bot) -> None:
    if role not in ("owner", "employee"):
        return
    await report_service.clear_report_buttons(bot, state)
    await state.set_state(ReconciledReportStates.choosing_period)
    await message.answer("Выберите период:", reply_markup=period_picker())


@router.callback_query(ReconciledReportStates.choosing_period, F.data.startswith("period:"))
async def choose_reconciled_period(callback: CallbackQuery, state: FSMContext) -> None:
    period = callback.data.split(":", 1)[1]
    await state.update_data(period=period)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Выберите формат:", reply_markup=report_format_keyboard())
    await callback.answer()


@router.callback_query(F.data.in_({"format:xlsx", "format:csv"}))
async def send_reconciled_report(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    period = data.get("period", "all")
    fmt = callback.data.split(":", 1)[1]
    since = report_service.period_start(period)

    async with get_session() as session:
        txs = await report_service.fetch_transactions(session, reconciled=True, since=since)
    rows = [report_service.to_full_row(tx) for tx in txs]
    if fmt == "xlsx":
        buffer = report_service.build_xlsx(rows, report_service.FULL_HEADERS)
        filename = f"report_reconciled_{period}.xlsx"
    else:
        buffer = report_service.build_csv(rows, report_service.FULL_HEADERS)
        filename = f"report_reconciled_{period}.csv"

    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer_document(BufferedInputFile(buffer.read(), filename=filename))
    await callback.answer()
