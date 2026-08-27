from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from bot.keyboards.menus import (
    CMD_ADD_EMPLOYEE,
    CMD_CREATE_ACCOUNT,
    CMD_DELETE_ACCOUNT,
    CMD_EXPENSE,
    CMD_INCOME,
    CMD_RECONCILE,
    CMD_REMOVE_EMPLOYEE,
    CMD_REPORT,
    CMD_TEAM_MEMBERS,
)

START_COMMAND = BotCommand(command="start", description="Показать меню")

EMPLOYEE_COMMANDS = [
    START_COMMAND,
    BotCommand(command=CMD_INCOME, description="Приход"),
    BotCommand(command=CMD_EXPENSE, description="Расход"),
    BotCommand(command=CMD_RECONCILE, description="Сверить"),
    BotCommand(command=CMD_REPORT, description="Отчёт"),
]

OWNER_COMMANDS = EMPLOYEE_COMMANDS + [
    BotCommand(command=CMD_CREATE_ACCOUNT, description="Создать счёт"),
    BotCommand(command=CMD_DELETE_ACCOUNT, description="Удалить счёт"),
    BotCommand(command=CMD_ADD_EMPLOYEE, description="Допустить сотрудника"),
    BotCommand(command=CMD_REMOVE_EMPLOYEE, description="Удалить сотрудника"),
    BotCommand(command=CMD_TEAM_MEMBERS, description="Члены команды"),
]


async def set_default_commands(bot: Bot) -> None:
    await bot.set_my_commands([START_COMMAND], scope=BotCommandScopeDefault())


async def set_commands_for(bot: Bot, telegram_user_id: int, role: str) -> None:
    commands = OWNER_COMMANDS if role == "owner" else EMPLOYEE_COMMANDS
    await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=telegram_user_id))


async def reset_commands_for(bot: Bot, telegram_user_id: int) -> None:
    await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=telegram_user_id))
