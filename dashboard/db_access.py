import os
from contextlib import contextmanager
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

_POOL: pool.SimpleConnectionPool = pool.SimpleConnectionPool(
    minconn=1,
    maxconn=int(os.getenv("DASHBOARD_DB_MAX_CONN", "8")),
    **conn_kwargs,
)


@contextmanager
def get_cursor(commit: bool = False) -> Generator[DictCursor, None, None]:
    """Yield a DictCursor from the shared connection pool."""
    connection = _POOL.getconn()
    try:
        cursor = connection.cursor(cursor_factory=DictCursor)
        yield cursor
        if commit:
            connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        _POOL.putconn(connection)


def shutdown_pool() -> None:
    """Close all pooled connections. Call from application teardown."""
    if _POOL:
        _POOL.closeall()
