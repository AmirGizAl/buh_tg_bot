import os
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.db.models import Base

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(db_path: str) -> None:
    global _engine, _session_factory
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    _engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def _heal_stale_removed_telegram_ids(conn) -> None:
    """One-time self-heal for databases created before remove_employee() started
    clearing telegram_user_id on removal: a removed user whose row still holds its
    telegram_user_id blocks that same person from ever being re-invited and
    reactivated (UNIQUE constraint on users.telegram_user_id). Safe to run on every
    startup — role resolution already only honors status == ACTIVE, so a removed
    row's telegram_user_id was never load-bearing for access."""
    # SQLAlchemy's Enum column stores the Python enum member's *name* ("REMOVED"),
    # not its .value ("removed") — match that on-disk representation here.
    await conn.execute(
        text("UPDATE users SET telegram_user_id = NULL WHERE status = 'REMOVED' AND telegram_user_id IS NOT NULL")
    )


async def init_db() -> None:
    assert _engine is not None, "call init_engine() first"
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _heal_stale_removed_telegram_ids(conn)


@asynccontextmanager
async def get_session():
    assert _session_factory is not None, "call init_engine() first"
    async with _session_factory() as session:
        yield session
