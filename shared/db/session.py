"""Async SQLAlchemy session factories for service.db and research.db."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SERVICE_DB_PATH = Path("data/service.db")
DEFAULT_RESEARCH_DB_PATH = Path("data/research.db")


def _resolve_db_path(env_name: str, default: Path) -> Path:
    raw_path = Path(os.getenv(env_name, str(default))).expanduser()
    if raw_path.is_absolute():
        return raw_path
    return PROJECT_ROOT / raw_path


def _sqlite_async_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path}"


def _build_engine(path: Path) -> AsyncEngine:
    path.parent.mkdir(parents=True, exist_ok=True)
    busy_timeout_seconds = float(os.getenv("SQLITE_BUSY_TIMEOUT_SECONDS", "60"))
    engine = create_async_engine(
        _sqlite_async_url(path),
        future=True,
        connect_args={"timeout": busy_timeout_seconds},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute(f"PRAGMA busy_timeout={int(busy_timeout_seconds * 1000)}")
        cursor.close()

    return engine


service_db_path = _resolve_db_path("SERVICE_DB_PATH", DEFAULT_SERVICE_DB_PATH)
research_db_path = _resolve_db_path("RESEARCH_DB_PATH", DEFAULT_RESEARCH_DB_PATH)

service_engine = _build_engine(service_db_path)
research_engine = _build_engine(research_db_path)

ServiceSessionLocal = async_sessionmaker(
    service_engine, expire_on_commit=False, class_=AsyncSession
)
ResearchSessionLocal = async_sessionmaker(
    research_engine, expire_on_commit=False, class_=AsyncSession
)

service_session = ServiceSessionLocal
research_session = ResearchSessionLocal


async def get_service_session() -> AsyncGenerator[AsyncSession, None]:
    async with ServiceSessionLocal() as session:
        yield session


async def get_research_session() -> AsyncGenerator[AsyncSession, None]:
    async with ResearchSessionLocal() as session:
        yield session
