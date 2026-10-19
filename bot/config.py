import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

MSK = ZoneInfo("Europe/Moscow")

# Seconds to wait for a Telegram API response before giving up (aiogram's default is 60).
# A minute of silence after pressing "Сохранить" pushed a user to enter the same record
# again; 20 s plus the retries in bot/services/delivery.py recovers from a one-off stall
# quickly. Long polling is unaffected: aiogram adds its polling timeout on top of this.
TELEGRAM_REQUEST_TIMEOUT = 20


@dataclass(frozen=True)
class Config:
    bot_token: str
    owner_id: int
    group_chat_id: int
    db_path: str
    proxy_url: str | None


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Environment variable {name} is not set")
    return value


def load_config() -> Config:
    return Config(
        bot_token=_require("BOT_TOKEN"),
        owner_id=int(_require("OWNER_ID")),
        group_chat_id=int(_require("GROUP_CHAT_ID")),
        db_path=os.getenv("DB_PATH", "data/bot.db"),
        proxy_url=os.getenv("PROXY_URL") or None,
    )
