"""Enqueue Celery work without breaking HTTP requests when Redis is down."""

from collections.abc import Callable
from typing import Any


def enqueue_task(task: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    try:
        task.apply_async(args=args, kwargs=kwargs, ignore_result=True)
    except Exception:
        return
