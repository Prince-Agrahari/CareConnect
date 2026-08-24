"""Verify 0002 is transaction-safe when the exclusion constraint already exists."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text

from app.core.config import settings

CONSTRAINT_NAME = "ex_doctor_working_hours_no_overlap"
MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0002_working_hours_overlap.py"
)


def postgres_available() -> bool:
    try:
        engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not postgres_available(),
    reason="PostgreSQL is not available",
)


def _load_0002():
    spec = importlib.util.spec_from_file_location(
        "migration_0002_working_hours_overlap",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _constraint_exists(connection) -> bool:
    return bool(
        connection.scalar(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = :constraint_name
                )
                """
            ),
            {"constraint_name": CONSTRAINT_NAME},
        )
    )


def _run_0002_upgrade(connection) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        _load_0002().upgrade()


def test_0002_skips_when_constraint_already_exists() -> None:
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    with engine.connect() as connection:
        trans = connection.begin()
        try:
            assert _constraint_exists(connection)
            _run_0002_upgrade(connection)
            assert _constraint_exists(connection)
        finally:
            trans.rollback()
    engine.dispose()


def test_0002_creates_constraint_when_absent() -> None:
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    with engine.connect() as connection:
        trans = connection.begin()
        try:
            assert _constraint_exists(connection)
            connection.execute(
                text(
                    "ALTER TABLE doctor_working_hours "
                    f"DROP CONSTRAINT {CONSTRAINT_NAME}"
                )
            )
            assert not _constraint_exists(connection)
            _run_0002_upgrade(connection)
            assert _constraint_exists(connection)
        finally:
            trans.rollback()
        assert _constraint_exists(connection)
    engine.dispose()
