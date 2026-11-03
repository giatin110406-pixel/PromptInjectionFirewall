"""Cooperative wall-clock budget for one interactive Agent turn."""
import time
from contextlib import contextmanager
from contextvars import ContextVar

_deadline = ContextVar("agent_turn_deadline", default=None)


class DeadlineExceeded(TimeoutError):
    pass


def remaining_timeout(default):
    limit = _deadline.get()
    if limit is None:
        return default
    remaining = limit - time.monotonic()
    if remaining <= 0:
        raise DeadlineExceeded("Agent turn deadline exceeded")
    return min(default, remaining)


def check_deadline():
    remaining_timeout(float("inf"))


@contextmanager
def turn_deadline(seconds):
    parent = _deadline.get()
    limit = time.monotonic() + seconds
    token = _deadline.set(min(parent, limit) if parent is not None else limit)
    try:
        yield
    finally:
        _deadline.reset(token)


@contextmanager
def deadline_lock(lock):
    timeout = remaining_timeout(float("inf"))
    acquired = lock.acquire() if timeout == float("inf") else lock.acquire(timeout=timeout)
    if not acquired:
        raise DeadlineExceeded("Timed out waiting for detector")
    try:
        check_deadline()
        yield
    finally:
        lock.release()
