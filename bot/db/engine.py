import os
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.db.models import Base

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(db_path: str) -> None:
    global _engine, _session_factory
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    _engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def init_db() -> None:
    assert _engine is not None, "call init_engine() first"
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_session():
    assert _session_factory is not None, "call init_engine() first"
    async with _session_factory() as session:
        yield session
