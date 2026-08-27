from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

INCOME = "Приход"
EXPENSE = "Расход"
RECONCILE = "Сверить"
REPORT = "Отчёт"
# Labels for the two report-type buttons shown after pressing "Отчёт" (inline keyboard,
# not part of the persistent reply menu — see bot/keyboards/inline.py:report_type_picker).
REPORT_CURRENT = "Текущий"
REPORT_RECONCILED = "Сверено"
CREATE_ACCOUNT = "Создать счёт"
DELETE_ACCOUNT = "Удалить счёт"
ADD_EMPLOYEE = "Допустить сотрудника"
REMOVE_EMPLOYEE = "Удалить сотрудника"
TEAM_MEMBERS = "Члены команды"

# Slash-command equivalents, registered in Telegram's "/" commands menu (bot/main.py) as a
# fallback entry point that doesn't depend on the reply keyboard being visible.
CMD_INCOME = "income"
CMD_EXPENSE = "expense"
CMD_RECONCILE = "reconcile"
CMD_REPORT = "report"
CMD_CREATE_ACCOUNT = "create_account"
CMD_DELETE_ACCOUNT = "delete_account"
CMD_ADD_EMPLOYEE = "add_employee"
CMD_REMOVE_EMPLOYEE = "remove_employee"
CMD_TEAM_MEMBERS = "team_members"


def owner_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=INCOME), KeyboardButton(text=EXPENSE)],
            [KeyboardButton(text=RECONCILE), KeyboardButton(text=REPORT)],
            [KeyboardButton(text=CREATE_ACCOUNT), KeyboardButton(text=DELETE_ACCOUNT)],
            [KeyboardButton(text=ADD_EMPLOYEE), KeyboardButton(text=REMOVE_EMPLOYEE)],
            [KeyboardButton(text=TEAM_MEMBERS)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def employee_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=INCOME), KeyboardButton(text=EXPENSE)],
            [KeyboardButton(text=RECONCILE), KeyboardButton(text=REPORT)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def menu_for_role(role: str) -> ReplyKeyboardMarkup:
    return owner_menu() if role == "owner" else employee_menu()
