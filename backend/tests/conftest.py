"""Test defaults: run Celery tasks in-process so Redis is not required."""

import pytest

from app.celery_app import celery_app


@pytest.fixture(scope="session", autouse=True)
def _celery_eager_for_tests() -> None:
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    yield
    celery_app.conf.task_always_eager = False
    celery_app.conf.task_eager_propagates = False
