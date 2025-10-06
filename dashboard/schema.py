"""Database schema helpers for the dashboard application."""

from __future__ import annotations

from typing import Iterable

from .db_access import get_cursor

_DASHBOARD_USERS_SQL = """
CREATE TABLE IF NOT EXISTS dashboard_users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ
);
"""


def ensure_dashboard_schema() -> None:
    """Create core dashboard tables when they do not yet exist."""
    statements: Iterable[str] = (
        _DASHBOARD_USERS_SQL,
    )
    with get_cursor(commit=True) as cur:
        for statement in statements:
            cur.execute(statement)


__all__ = ["ensure_dashboard_schema"]
