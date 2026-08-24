"""Injectable clock so availability tests can freeze the current time."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)
