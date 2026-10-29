"""Dedicated PostgreSQL connection for session-scoped scheduler advisory locks.

A scheduler may hold this connection for hours; it must never occupy a
connection from the application's request/worker QueuePool.
"""
from contextlib import contextmanager
from threading import Lock
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from backend.database import engine

_lock_engine = None
_init_lock = Lock()


def _get_lock_engine():
    global _lock_engine
    if _lock_engine is None:
        with _init_lock:
            if _lock_engine is None:
                # Separate, non-pooling engine, sharing the application's DB URL.
                _lock_engine = create_engine(engine.url, poolclass=NullPool, pool_pre_ping=True)
    return _lock_engine


@contextmanager
def lock_connection():
    """Keep one physical session until the scheduler releases its lock."""
    with _get_lock_engine().connect() as conn:
        yield conn
