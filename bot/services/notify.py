from aiogram import Bot

from bot.config import Config


async def post_to_group(bot: Bot, config: Config, text: str, reply_markup=None) -> int:
    message = await bot.send_message(config.group_chat_id, text, reply_markup=reply_markup)
    return message.message_id
