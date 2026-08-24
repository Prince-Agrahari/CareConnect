"""Apply Alembic migrations using the same DATABASE_URL as the app."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db.session import engine

# Arbitrary lock key so concurrent web workers do not race upgrade on startup.
_MIGRATION_LOCK_KEY = 829177401


def _alembic_config() -> Config:
    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    return config


def run_alembic_upgrade() -> None:
    with engine.connect() as lock_connection:
        lock_connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _MIGRATION_LOCK_KEY})
        lock_connection.commit()
        try:
            command.upgrade(_alembic_config(), "head")
        finally:
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(:key)"),
                {"key": _MIGRATION_LOCK_KEY},
            )
            lock_connection.commit()
