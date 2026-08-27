from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.db.models import Account, User
from bot.keyboards.menus import REPORT_CURRENT, REPORT_RECONCILED
from bot.utils import actor_label, format_amount


def currency_picker() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="RUB", callback_data="currency:RUB"),
                InlineKeyboardButton(text="USD", callback_data="currency:USD"),
                InlineKeyboardButton(text="EUR", callback_data="currency:EUR"),
            ]
        ]
    )


def account_picker(accounts: list[Account], prefix: str = "acc", include_all: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if include_all:
        rows.append([InlineKeyboardButton(text="По всем счетам", callback_data=f"{prefix}:all")])
    rows += [
        [
            InlineKeyboardButton(
                text=f"{a.label} ({format_amount(a.balance)})", callback_data=f"{prefix}:{a.id}"
            )
        ]
        for a in accounts
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def period_picker() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Сегодня", callback_data="period:today"),
                InlineKeyboardButton(text="Неделя", callback_data="period:week"),
            ],
            [
                InlineKeyboardButton(text="Месяц", callback_data="period:month"),
                InlineKeyboardButton(text="Всё время", callback_data="period:all"),
            ],
        ]
    )


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Сохранить", callback_data="confirm"),
                InlineKeyboardButton(text="Отмена", callback_data="cancel"),
            ]
        ]
    )


def rollback_keyboard(tx_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Откатить", callback_data=f"rollback:{tx_id}")]]
    )


def rollback_confirm_keyboard(tx_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Подтвердить", callback_data=f"rollback_confirm:{tx_id}"),
                InlineKeyboardButton(text="Отмена", callback_data=f"rollback_cancel:{tx_id}"),
            ]
        ]
    )


def report_type_picker() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=REPORT_CURRENT, callback_data="report_type:current"),
                InlineKeyboardButton(text=REPORT_RECONCILED, callback_data="report_type:reconciled"),
            ]
        ]
    )


def current_report_export_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Excel", callback_data="export:current:xlsx"),
                InlineKeyboardButton(text="CSV", callback_data="export:current:csv"),
            ]
        ]
    )


def report_format_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Excel", callback_data="format:xlsx"),
                InlineKeyboardButton(text="CSV", callback_data="format:csv"),
            ]
        ]
    )


def employee_picker(employees: list[User]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=actor_label(e), callback_data=f"emp:{e.id}")] for e in employees
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
