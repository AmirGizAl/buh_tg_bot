import csv
import io
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.config import MSK
from bot.db.models import Transaction
from bot.utils import actor_label, esc, fmt_date, fmt_time, format_amount

FULL_HEADERS = ["дата", "время", "счёт", "сумма", "комментарий", "сверено", "пользователь"]
CURRENT_PREVIEW_HEADERS = ["сумма", "счёт", "комментарий", "пользователь"]

PERIODS = ("today", "week", "month", "all")


def period_start(period: str) -> datetime | None:
    now_utc = datetime.now(timezone.utc)
    if period == "today":
        start_msk = now_utc.astimezone(MSK).replace(hour=0, minute=0, second=0, microsecond=0)
        return start_msk.astimezone(timezone.utc)
    if period == "week":
        return now_utc - timedelta(days=7)
    if period == "month":
        return now_utc - timedelta(days=30)
    if period == "all":
        return None
    raise ValueError(f"Unknown period: {period}")


async def fetch_transactions(
    session: AsyncSession,
    *,
    reconciled: bool | None = None,
    account_id: int | None = None,
    since: datetime | None = None,
) -> list[Transaction]:
    query = select(Transaction).options(
        selectinload(Transaction.account), selectinload(Transaction.created_by)
    )
    if reconciled is not None:
        query = query.where(Transaction.reconciled.is_(reconciled))
    if account_id is not None:
        query = query.where(Transaction.account_id == account_id)
    if since is not None:
        query = query.where(Transaction.created_at >= since)
    query = query.order_by(Transaction.created_at)
    result = await session.execute(query)
    return list(result.scalars())


def to_full_row(tx: Transaction) -> tuple[str, str, str, str, str, str, str]:
    return (
        fmt_date(tx.created_at),
        fmt_time(tx.created_at),
        tx.account.label,
        format_amount(tx.amount, force_sign=True),
        tx.comment or "",
        "Да" if tx.reconciled else "Нет",
        actor_label(tx.created_by),
    )


def render_current_preview(transactions: list[Transaction]) -> str:
    if not transactions:
        return "Нет несверенных транзакций."
    lines = ["   ".join(CURRENT_PREVIEW_HEADERS)]
    for tx in transactions:
        lines.append(
            "   ".join(
                [
                    format_amount(tx.amount, force_sign=True),
                    esc(tx.account.label),
                    esc(tx.comment or ""),
                    esc(actor_label(tx.created_by)),
                ]
            )
        )
    return "<blockquote>" + "\n".join(lines) + "</blockquote>"


def build_xlsx(rows: list[tuple], headers: list[str]) -> io.BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "Отчёт"
    ws.append(headers)
    for row in rows:
        ws.append(list(row))
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def build_csv(rows: list[tuple], headers: list[str]) -> io.BytesIO:
    text_buffer = io.StringIO()
    writer = csv.writer(text_buffer, delimiter=";")
    writer.writerow(headers)
    for row in rows:
        writer.writerow(list(row))
    buffer = io.BytesIO(text_buffer.getvalue().encode("utf-8-sig"))
    buffer.seek(0)
    return buffer


async def remember_report_buttons(state: FSMContext, chat_id: int, message_id: int) -> None:
    await state.update_data(report_chat_id=chat_id, report_message_id=message_id)


async def clear_report_buttons(bot: Bot, state: FSMContext) -> None:
    """The Excel/CSV buttons under a "Текущий" report preview must disappear once the
    user starts a new action from the menu — call this at the top of every top-level
    menu-entry handler. FSMContext.get_data/update_data work regardless of the
    current state, so this is independent of whatever flow is starting."""
    data = await state.get_data()
    chat_id = data.get("report_chat_id")
    message_id = data.get("report_message_id")
    if not chat_id or not message_id:
        return
    try:
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
    except TelegramBadRequest:
        pass
    await state.update_data(report_chat_id=None, report_message_id=None)
