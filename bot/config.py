import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

MSK = ZoneInfo("Europe/Moscow")


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
