import os
from contextlib import contextmanager
from threading import Lock
from typing import Generator, Optional

from psycopg2 import pool
from psycopg2.extras import DictCursor
from dotenv import load_dotenv

load_dotenv()

REQUIRED_KEYS = [
    "DB_NAME",
    "DB_USER",
    "DB_PASS",
    "DB_HOST",
    "DB_PORT",
]

_DB_CONFIG = {key: os.getenv(key) for key in REQUIRED_KEYS}
_missing = [key for key, value in _DB_CONFIG.items() if not value]
if _missing:
    missing_keys = ", ".join(_missing)
    raise RuntimeError(
        f"Missing database environment variables: {missing_keys}. "
        "Please update your .env or deployment configuration."
    )

optional_sslmode: Optional[str] = os.getenv("DB_SSLMODE")
conn_kwargs = dict(
    dbname=_DB_CONFIG["DB_NAME"],
    user=_DB_CONFIG["DB_USER"],
    password=_DB_CONFIG["DB_PASS"],
    host=_DB_CONFIG["DB_HOST"],
    port=_DB_CONFIG["DB_PORT"],
)
if optional_sslmode:
    conn_kwargs["sslmode"] = optional_sslmode

_POOL = pool.ThreadedConnectionPool(
    minconn=1,
    maxconn=int(os.getenv("DASHBOARD_DB_MAX_CONN", "8")),
    **conn_kwargs,
)


_DEMO_POOL = None


def demo_pool():
    """Create only an explicitly configured, separate demo database connection."""
    global _DEMO_POOL
    # The module-level lock also protects concurrent first requests under gthread.
    with _DEMO_POOL_LOCK:
        if _DEMO_POOL is None:
            demo_name = os.getenv("DASHBOARD_DEMO_DB_NAME", "").strip()
            if not demo_name or demo_name == conn_kwargs["dbname"]:
                raise RuntimeError("Database dummy terpisah belum dikonfigurasi.")
            args = dict(conn_kwargs, dbname=demo_name)
            args["user"] = os.environ["DASHBOARD_DEMO_DB_USER"]
            args["password"] = os.environ["DASHBOARD_DEMO_DB_PASS"]
            args["options"] = "-c default_transaction_read_only=on -c statement_timeout=15000"
            args["connect_timeout"] = 5
            _DEMO_POOL = pool.ThreadedConnectionPool(1, 4, **args)
        return _DEMO_POOL


_DEMO_POOL_LOCK = Lock()


@contextmanager
def _cursor_from_pool(selected_pool, commit=False):
    connection = selected_pool.getconn()
    cursor = None
    try:
        cursor = connection.cursor(cursor_factory=DictCursor)
        yield cursor
        if commit:
            connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        if cursor is not None:
            cursor.close()
        # SELECTs also open transactions: never return one to the shared pool.
        try:
            connection.rollback()
        finally:
            selected_pool.putconn(connection)


@contextmanager
def original_cursor():
    """Original database for verifying the real identity behind a session."""
    with _cursor_from_pool(_POOL) as cursor:
        yield cursor


@contextmanager
def original_write_cursor():
    with _cursor_from_pool(_POOL, commit=True) as cursor:
        yield cursor


@contextmanager
def get_cursor(commit: bool = False) -> Generator[DictCursor, None, None]:
    from .data_mode import dummy_requested
    selected_pool = _POOL
    if dummy_requested():
        from flask import abort
        if commit:
            abort(403, description="Mode dummy hanya untuk melihat data.")
        # Failure to connect must never silently fall back to original data.
        selected_pool = demo_pool()
    with _cursor_from_pool(selected_pool, commit=commit) as cursor:
        yield cursor


def shutdown_pool() -> None:
    """Close all pooled connections. Call from application teardown."""
    if _POOL:
        _POOL.closeall()
    if _DEMO_POOL:
        _DEMO_POOL.closeall()
