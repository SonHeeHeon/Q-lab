"""Alembic environment for the service and research SQLite databases."""

from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

from shared.db.models import ResearchBase, ServiceBase

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _sqlite_url_from_env(env_name: str) -> str | None:
    raw_path = os.getenv(env_name)
    if not raw_path:
        return None

    db_path = Path(raw_path).expanduser()
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    return f"sqlite:///{db_path}"


def _active_database() -> tuple[str, str, object]:
    section = config.config_ini_section
    if section == "service":
        url = _sqlite_url_from_env("SERVICE_DB_PATH")
        return section, url or config.get_main_option("sqlalchemy.url"), ServiceBase.metadata
    if section == "research":
        url = _sqlite_url_from_env("RESEARCH_DB_PATH")
        return section, url or config.get_main_option("sqlalchemy.url"), ResearchBase.metadata

    raise RuntimeError(
        "Run Alembic with '--name service' or '--name research' so the correct "
        "database metadata is selected."
    )


database_name, database_url, target_metadata = _active_database()
config.set_main_option("sqlalchemy.url", database_url)


def _ensure_sqlite_parent_exists(url: str) -> None:
    if not url.startswith("sqlite:///"):
        return

    raw_path = url.removeprefix("sqlite:///")
    db_path = Path(raw_path)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    _ensure_sqlite_parent_exists(database_url)

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.commit()

        with connection.begin():
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                render_as_batch=True,
            )

            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
