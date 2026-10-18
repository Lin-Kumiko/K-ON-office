"""Alembic environment. URL priority: -x url=... > DOE_DATABASE_URL > settings default (data/dev.sqlite3)."""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import load_settings  # noqa: E402
from app.models import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    x = context.get_x_argument(as_dictionary=True)
    if x.get("url"):
        return x["url"]
    settings = load_settings()
    settings.ensure_dirs()
    return settings.database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")  # batch migrations rebuild tables
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
