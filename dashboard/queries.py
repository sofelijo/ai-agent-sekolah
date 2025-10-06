from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from psycopg2.extras import DictRow

from .db_access import get_cursor


@dataclass
class ChatFilters:
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    role: Optional[str] = None
    search: Optional[str] = None
    user_id: Optional[int] = None


def _apply_filters(conditions: List[str], params: List[Any], filters: ChatFilters) -> None:
    if filters.start:
        conditions.append("created_at >= %s")
        params.append(filters.start)
    if filters.end:
        conditions.append("created_at <= %s")
        params.append(filters.end)
    if filters.role:
        conditions.append("role = %s")
        params.append(filters.role)
    if filters.user_id:
        conditions.append("user_id = %s")
        params.append(filters.user_id)
    if filters.search:
        conditions.append("text ILIKE %s")
        params.append(f"%{filters.search}%")


def fetch_overview_metrics(window_days: int = 7) -> Dict[str, Any]:
    """Aggregate key performance indicators for the dashboard landing page."""
    window_days = max(1, window_days)
    interval = timedelta(days=window_days)

    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total_messages FROM chat_logs")
        total_messages = cur.fetchone()["total_messages"]

        cur.execute("""
            SELECT COUNT(DISTINCT user_id) AS unique_users
            FROM chat_logs
            WHERE role = 'user'
        """)
        unique_users = cur.fetchone()["unique_users"]

        cur.execute(
            """
            SELECT COUNT(*) AS messages_window
            FROM chat_logs
            WHERE created_at >= NOW() - %s::interval
            """,
            (f"{window_days} days",),
        )
        messages_window = cur.fetchone()["messages_window"]

        cur.execute(
            """
            SELECT
                AVG(response_time_ms)::float AS avg_response,
                percentile_cont(0.9) WITHIN GROUP (ORDER BY response_time_ms) AS p90_response
            FROM chat_logs
            WHERE response_time_ms IS NOT NULL
        """
        )
        response_stats = cur.fetchone()

        cur.execute(
            """
            SELECT COUNT(DISTINCT user_id) AS active_today
            FROM chat_logs
            WHERE DATE(created_at) = CURRENT_DATE
              AND role = 'user'
        """
        )
        active_today = cur.fetchone()["active_today"]

    avg_response = response_stats["avg_response"] or 0.0
    p90_response = response_stats["p90_response"] or 0.0

    return {
        "total_messages": int(total_messages or 0),
        "unique_users": int(unique_users or 0),
        "messages_window": int(messages_window or 0),
        "window_days": window_days,
        "avg_response_ms": round(avg_response, 2),
        "p90_response_ms": round(p90_response, 2),
        "active_today": int(active_today or 0),
    }


def fetch_daily_activity(days: int = 14) -> List[Dict[str, Any]]:
    days = max(1, days)
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT DATE(created_at) AS day, COUNT(*) AS messages
            FROM chat_logs
            WHERE created_at >= NOW() - %s::interval
            GROUP BY day
            ORDER BY day ASC
            """,
            (f"{days} days",),
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def fetch_recent_questions(limit: int = 10) -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, username, text, created_at
            FROM chat_logs
            WHERE role = 'user'
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def fetch_top_users(limit: int = 5) -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT user_id, COALESCE(username, 'Unknown') AS username, COUNT(*) AS messages
            FROM chat_logs
            WHERE role = 'user'
            GROUP BY user_id, username
            ORDER BY messages DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def fetch_chat_logs(
    filters: ChatFilters,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    conditions: List[str] = []
    params: List[Any] = []
    _apply_filters(conditions, params, filters)

    where_clause = ""
    if conditions:
        where_clause = " WHERE " + " AND ".join(conditions)

    query = (
        "SELECT id, user_id, username, text, role, created_at, response_time_ms "
        "FROM chat_logs"
        f"{where_clause} "
        "ORDER BY created_at DESC "
        "LIMIT %s OFFSET %s"
    )
    with get_cursor() as cur:
        cur.execute(query, (*params, limit, offset))
        rows = cur.fetchall()

        cur.execute(f"SELECT COUNT(*) FROM chat_logs{where_clause}", params)
        total = cur.fetchone()[0]

    return [dict(row) for row in rows], int(total or 0)


def fetch_conversation_thread(user_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, username, text, role, created_at, response_time_ms
            FROM chat_logs
            WHERE user_id = %s
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (user_id, limit),
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def get_user_by_email(email: str) -> Optional[DictRow]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, email, password_hash, full_name, role, last_login_at
            FROM dashboard_users
            WHERE email = %s
            LIMIT 1
            """,
            (email,)
        )
        row = cur.fetchone()
    return row


def list_dashboard_users() -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, email, full_name, role, created_at, last_login_at
            FROM dashboard_users
            ORDER BY created_at ASC
            """
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def create_dashboard_user(
    email: str,
    full_name: str,
    password_hash: str,
    role: str = "viewer",
) -> int:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO dashboard_users (email, full_name, password_hash, role)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (email, full_name, password_hash, role),
        )
        new_id = cur.fetchone()[0]
    return int(new_id)


def update_last_login(user_id: int) -> None:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE dashboard_users SET last_login_at = NOW() WHERE id = %s",
            (user_id,),
        )

