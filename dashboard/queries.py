from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from psycopg2.extras import DictRow, Json

from .db_access import get_cursor

TOKEN_PATTERN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
STOPWORDS = {
    "dan",
    "yang",
    "atau",
    "untuk",
    "dengan",
    "pada",
    "dari",
    "kami",
    "kita",
    "kamu",
    "anda",
    "saya",
    "aku",
    "dia",
    "itu",
    "ini",
    "jadi",
    "apa",
    "berapa",
    "bagaimana",
    "kapan",
    "dimana",
    "mengapa",
    "apakah",
    "sudah",
    "belum",
    "akan",
    "bisa",
    "mohon",
    "tolong",
    "terima",
    "kasih",
    "ya",
    "tidak",
    "iya",
    "oke",
    "ok",
    "hai",
    "halo",
    "selamat",
    "malam",
    "pagi",
    "siang",
    "sore",
    "bot",
    "aska",
}

_CHAT_TOPIC_AVAILABLE: Optional[bool] = None


def chat_topic_available() -> bool:
    """Check once whether chat_logs table has topic column."""
    global _CHAT_TOPIC_AVAILABLE
    if _CHAT_TOPIC_AVAILABLE is not None:
        return _CHAT_TOPIC_AVAILABLE
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'chat_logs'
              AND column_name = 'topic'
            LIMIT 1
            """
        )
        _CHAT_TOPIC_AVAILABLE = cur.fetchone() is not None
    return _CHAT_TOPIC_AVAILABLE
BULLYING_STATUSES = (
    'pending',
    'in_progress',
    'resolved',
    'spam',
)

CORRUPTION_STATUSES = (
    'open',
    'in_progress',
    'resolved',
    'archived',
)

PSYCH_STATUSES = (
    'open',
    'in_progress',
    'resolved',
    'archived',
)

PSYCH_SEVERITIES = (
    'general',
    'elevated',
    'critical',
)

@dataclass
class ChatFilters:
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    role: Optional[str] = None
    search: Optional[str] = None
    user_id: Optional[int] = None
    topic: Optional[str] = None

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
    if filters.topic and chat_topic_available():
        conditions.append("topic = %s")
        params.append(filters.topic)

def fetch_overview_metrics(window_days: int = 7) -> Dict[str, Any]:
    """Aggregate key performance indicators for the dashboard landing page."""
    window_days = max(1, window_days)
    interval = timedelta(days=window_days)

    bullying_rows: List[Dict[str, Any]] = []
    escalated_total = 0

    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total_messages FROM chat_logs")
        total_messages = cur.fetchone()["total_messages"]

        cur.execute(
            """
            SELECT COUNT(*) AS total_incoming_messages
            FROM chat_logs
            WHERE role = 'user'
            """
        )
        total_incoming_messages = cur.fetchone()["total_incoming_messages"]

        cur.execute(
            """
            SELECT COUNT(DISTINCT user_id) AS unique_users
            FROM chat_logs
            WHERE role = 'user'
            """
        )
        unique_users_all = cur.fetchone()["unique_users"]

        cur.execute(
            """
            SELECT COUNT(DISTINCT user_id) AS unique_users_today
            FROM chat_logs
            WHERE role = 'user'
              AND DATE(created_at) = CURRENT_DATE
            """
        )
        unique_users_today = cur.fetchone()["unique_users_today"]

        cur.execute(
            """
            SELECT COUNT(DISTINCT user_id) AS unique_users_7d
            FROM chat_logs
            WHERE role = 'user'
              AND created_at >= NOW() - INTERVAL '7 days'
            """
        )
        unique_users_7d = cur.fetchone()["unique_users_7d"]

        cur.execute(
            """
            SELECT COUNT(DISTINCT user_id) AS unique_users_30d
            FROM chat_logs
            WHERE role = 'user'
              AND created_at >= NOW() - INTERVAL '30 days'
            """
        )
        unique_users_30d = cur.fetchone()["unique_users_30d"]

        cur.execute(
            """
            SELECT COUNT(DISTINCT user_id) AS unique_users_365d
            FROM chat_logs
            WHERE role = 'user'
              AND created_at >= NOW() - INTERVAL '365 days'
            """
        )
        unique_users_365d = cur.fetchone()["unique_users_365d"]

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

        active_today = unique_users_today

        cur.execute(
            """
            SELECT status, COUNT(*) AS total
            FROM bullying_reports
            GROUP BY status
            """
        )
        bullying_rows = cur.fetchall()
        cur.execute(
            """
            SELECT COUNT(*) AS escalated_total
            FROM bullying_reports
            WHERE escalated = TRUE
            """
        )
        escalated_total = cur.fetchone()["escalated_total"] or 0

    avg_response = response_stats["avg_response"] or 0.0
    p90_response = response_stats["p90_response"] or 0.0

    bullying_summary = {status: 0 for status in BULLYING_STATUSES}
    bullying_total = 0
    for row in bullying_rows:
        status = (row.get("status") or "").lower()
        count = int(row.get("total") or 0)
        if status in bullying_summary:
            bullying_summary[status] = count
            bullying_total += count
    bullying_summary["total"] = bullying_total
    bullying_summary["escalated"] = int(escalated_total or 0)

    corruption_summary = fetch_corruption_summary()
    psych_summary = fetch_psych_summary()
    corruption_active_total = int(
        (corruption_summary.get("total", 0) - corruption_summary.get("archived", 0))
        if corruption_summary
        else 0
    )
    bullying_active_total = int(bullying_total - bullying_summary.get("spam", 0))
    psych_active_total = int(psych_summary.get("total", 0)) if psych_summary else 0

    return {
        "total_messages": int(total_messages or 0),
        "total_incoming_messages": int(total_incoming_messages or 0),
        "unique_users": int(unique_users_all or 0),
        "unique_users_all": int(unique_users_all or 0),
        "unique_users_today": int(unique_users_today or 0),
        "unique_users_7d": int(unique_users_7d or 0),
        "unique_users_30d": int(unique_users_30d or 0),
        "unique_users_365d": int(unique_users_365d or 0),
        "window_days": window_days,
        "avg_response_ms": round(avg_response, 2),
        "p90_response_ms": round(p90_response, 2),
        "active_today": int(active_today or 0),
        "bullying_total": bullying_total,
        "bullying_pending": bullying_summary['pending'],
        "bullying_in_progress": bullying_summary['in_progress'],
        "bullying_resolved": bullying_summary['resolved'],
        "bullying_spam": bullying_summary['spam'],
        "bullying_summary": bullying_summary,
        "bullying_active_total": bullying_active_total,
        "corruption_summary": corruption_summary,
        "corruption_active_total": corruption_active_total,
        "psych_summary": psych_summary,
        "psych_active_total": psych_active_total,
    }

def fetch_daily_activity(days: int = 14, role: Optional[str] = None) -> List[Dict[str, Any]]:
    days = max(1, days)
    params: List[Any] = [f"{days} days"]
    query = [
        "SELECT DATE(created_at) AS day, COUNT(*) AS messages",
        "FROM chat_logs",
        "WHERE created_at >= NOW() - %s::interval",
    ]
    if role:
        query.append("AND role = %s")
        params.append(role)
    query.extend(
        [
            "GROUP BY day",
            "ORDER BY day ASC",
        ]
    )
    with get_cursor() as cur:
        cur.execute("\n".join(query), tuple(params))
        rows = cur.fetchall()
    result: List[Dict[str, Any]] = []
    for row in rows:
        count = int(row.get("messages") or 0)
        if count <= 0:
            continue
        result.append({"day": row.get("day"), "messages": count})
    return result

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

def fetch_top_keywords(limit: int = 10, days: int = 14, min_length: int = 3) -> List[Dict[str, Any]]:
    """Return most frequent keywords from user messages within the given time window."""
    days = max(1, days)
    limit = max(1, limit)
    min_length = max(1, min_length)

    with get_cursor() as cur:
        cur.execute(
            """
            SELECT text
            FROM chat_logs
            WHERE role = 'user'
              AND text IS NOT NULL
              AND text <> ''
              AND created_at >= NOW() - %s::interval
            """,
            (f"{days} days",),
        )
        rows = cur.fetchall()

    counter: Counter[str] = Counter()
    for row in rows:
        text_value = (row["text"] or "").lower()
        for token in TOKEN_PATTERN.findall(text_value):
            if len(token) < min_length or token.isdigit() or token in STOPWORDS:
                continue
            counter[token] += 1

    return [
        {"keyword": keyword, "count": count}
        for keyword, count in counter.most_common(limit)
    ]

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

    select_columns = "id, user_id, username, text, role, created_at, response_time_ms"
    if chat_topic_available():
        select_columns = "id, user_id, username, text, role, topic, created_at, response_time_ms"

    query = (
        f"SELECT {select_columns} "
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
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        rows = [dict(row) for row in cur.fetchall()]
    rows.reverse()
    return rows


def fetch_all_chat_users() -> List[Dict[str, Any]]:
    """Fetches all users who have sent messages, with their message counts."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                user_id,
                COALESCE(username, 'Unknown') AS username,
                COUNT(*) AS message_count
            FROM chat_logs
            WHERE role = 'user'
            GROUP BY user_id, username
            ORDER BY MAX(created_at) DESC
            """
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def fetch_twitter_overview(window_days: int = 7) -> Dict[str, Any]:
    """Aggregate metrik penting untuk operasional Twitter/X."""
    if not chat_topic_available():
        return {
            "window_days": window_days,
            "total_mentions": 0,
            "total_replies": 0,
            "total_users": 0,
            "mentions_window": 0,
            "replies_window": 0,
            "users_window": 0,
            "mentions_24h": 0,
            "replies_24h": 0,
            "mentions_today": 0,
            "replies_today": 0,
            "avg_response_ms": None,
            "p90_response_ms": None,
            "backlog": 0,
            "reply_rate": 0.0,
            "last_mention": None,
            "last_reply": None,
        }

    window_days = max(1, window_days)
    window_interval = f"{window_days} days"

    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE role = 'user') AS mentions_total,
                COUNT(*) FILTER (WHERE role = 'aska') AS replies_total,
                COUNT(DISTINCT user_id) FILTER (WHERE role = 'user') AS users_total,
                COUNT(*) FILTER (WHERE role = 'user' AND created_at >= NOW() - %s::interval) AS mentions_window,
                COUNT(*) FILTER (WHERE role = 'aska' AND created_at >= NOW() - %s::interval) AS replies_window,
                COUNT(DISTINCT user_id) FILTER (WHERE role = 'user' AND created_at >= NOW() - %s::interval) AS users_window,
                COUNT(*) FILTER (WHERE role = 'user' AND created_at >= NOW() - INTERVAL '1 day') AS mentions_24h,
                COUNT(*) FILTER (WHERE role = 'aska' AND created_at >= NOW() - INTERVAL '1 day') AS replies_24h,
                COUNT(*) FILTER (WHERE role = 'user' AND DATE(created_at) = CURRENT_DATE) AS mentions_today,
                COUNT(*) FILTER (WHERE role = 'aska' AND DATE(created_at) = CURRENT_DATE) AS replies_today,
                AVG(response_time_ms) FILTER (WHERE role = 'aska' AND response_time_ms IS NOT NULL) AS avg_response_ms,
                percentile_cont(0.9) WITHIN GROUP (ORDER BY response_time_ms)
                    FILTER (WHERE role = 'aska' AND response_time_ms IS NOT NULL) AS p90_response_ms
            FROM chat_logs
            WHERE topic = 'twitter'
            """,
            (window_interval, window_interval, window_interval),
        )
        overview_row = cur.fetchone() or {}

        cur.execute(
            """
            SELECT id, user_id, username, text, created_at
            FROM chat_logs
            WHERE topic = 'twitter' AND role = 'user'
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        last_mention = cur.fetchone()

        cur.execute(
            """
            SELECT id, user_id, username, text, created_at, response_time_ms
            FROM chat_logs
            WHERE topic = 'twitter' AND role = 'aska'
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        last_reply = cur.fetchone()

    def _coerce_int(value) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    avg_response = overview_row.get("avg_response_ms")
    p90_response = overview_row.get("p90_response_ms")

    total_mentions = _coerce_int(overview_row.get("mentions_total"))
    total_replies = _coerce_int(overview_row.get("replies_total"))
    backlog = max(0, total_mentions - total_replies)
    reply_rate = 0.0
    if total_mentions:
        reply_rate = round(min(1.0, total_replies / total_mentions), 3)

    return {
        "window_days": window_days,
        "total_mentions": total_mentions,
        "total_replies": total_replies,
        "total_users": _coerce_int(overview_row.get("users_total")),
        "mentions_window": _coerce_int(overview_row.get("mentions_window")),
        "replies_window": _coerce_int(overview_row.get("replies_window")),
        "users_window": _coerce_int(overview_row.get("users_window")),
        "mentions_24h": _coerce_int(overview_row.get("mentions_24h")),
        "replies_24h": _coerce_int(overview_row.get("replies_24h")),
        "mentions_today": _coerce_int(overview_row.get("mentions_today")),
        "replies_today": _coerce_int(overview_row.get("replies_today")),
        "avg_response_ms": float(avg_response) if avg_response is not None else None,
        "p90_response_ms": float(p90_response) if p90_response is not None else None,
        "backlog": backlog,
        "reply_rate": reply_rate,
        "last_mention": dict(last_mention) if last_mention else None,
        "last_reply": dict(last_reply) if last_reply else None,
    }


def fetch_twitter_activity(days: int = 30) -> List[Dict[str, Any]]:
    """Ambil aktivitas harian mention dan balasan untuk topik Twitter."""
    if not chat_topic_available():
        return []
    days = max(1, days)
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                DATE(created_at) AS day,
                COUNT(*) FILTER (WHERE role = 'user') AS mentions,
                COUNT(*) FILTER (WHERE role = 'aska') AS replies
            FROM chat_logs
            WHERE topic = 'twitter'
              AND created_at >= NOW() - %s::interval
            GROUP BY day
            ORDER BY day ASC
            """,
            (f"{days} days",),
        )
        rows = cur.fetchall()
    return [
        {
            "day": row.get("day"),
            "mentions": int(row.get("mentions") or 0),
            "replies": int(row.get("replies") or 0),
        }
        for row in rows
    ]


def fetch_twitter_top_users(limit: int = 8) -> List[Dict[str, Any]]:
    """Pengguna Twitter yang paling sering menyebut bot."""
    if not chat_topic_available():
        return []
    limit = max(1, limit)
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                user_id,
                COALESCE(NULLIF(username, ''), 'Unknown') AS username,
                COUNT(*) AS mentions,
                MAX(created_at) AS last_seen
            FROM chat_logs
            WHERE topic = 'twitter'
              AND role = 'user'
            GROUP BY user_id, username
            ORDER BY mentions DESC, last_seen DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def fetch_twitter_worker_logs(limit: int = 100) -> List[Dict[str, Any]]:
    """Ambil log terbaru dari worker Twitter yang tersimpan di database."""
    limit = max(1, min(int(limit or 100), 500))
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, level, message, context, tweet_id, twitter_user_id, created_at
            FROM twitter_worker_logs
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

    result: List[Dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        context = payload.get("context")
        if isinstance(context, dict):
            payload["context"] = dict(context)
        else:
            payload["context"] = None
        result.append(payload)
    return result



def fetch_bullying_summary() -> Dict[str, int]:
    """Return aggregated counts of bullying reports by status."""
    summary = {status: 0 for status in BULLYING_STATUSES}
    total = 0
    escalated_total = 0
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT status, COUNT(*) AS total
            FROM bullying_reports
            GROUP BY status
            """
        )
        rows = cur.fetchall()
        cur.execute(
            "SELECT COUNT(*) FROM bullying_reports WHERE escalated = TRUE"
        )
        escalated_total = cur.fetchone()[0]
    for row in rows:
        status = (row.get('status') or '').lower()
        count = int(row.get('total') or 0)
        if status in summary:
            summary[status] = count
            total += count
    summary['total'] = total
    summary['escalated'] = int(escalated_total or 0)
    return summary


def fetch_pending_bullying_count() -> int:
    """Shortcut to obtain the number of pending bullying reports."""
    return fetch_bullying_summary().get('pending', 0)


def fetch_psych_summary() -> Dict[str, Any]:
    """Return aggregated counts of psychological reports by status and severity."""
    summary = {status: 0 for status in PSYCH_STATUSES}
    severity_counts = {severity: 0 for severity in PSYCH_SEVERITIES}
    total = 0

    with get_cursor() as cur:
        cur.execute(
            """
            SELECT status, COUNT(*) AS total
            FROM psych_reports
            GROUP BY status
            """
        )
        status_rows = cur.fetchall()

        cur.execute(
            """
            SELECT severity, COUNT(*) AS total
            FROM psych_reports
            WHERE status IS NULL OR status <> 'archived'
            GROUP BY severity
            """
        )
        severity_rows = cur.fetchall()

    for row in status_rows:
        status = (row.get('status') or '').lower()
        count = int(row.get('total') or 0)
        if status in summary:
            summary[status] = count
            if status != "archived":
                total += count

    for row in severity_rows:
        severity = (row.get('severity') or '').lower()
        count = int(row.get('total') or 0)
        if severity in severity_counts:
            severity_counts[severity] = count

    summary['total'] = total
    summary['severity'] = severity_counts
    summary['critical'] = severity_counts.get('critical', 0)
    summary['elevated'] = severity_counts.get('elevated', 0)
    summary['general'] = severity_counts.get('general', 0)
    return summary


def fetch_pending_psych_count() -> int:
    """Return number of open psychological reports."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM psych_reports WHERE status = 'open'"
        )
        row = cur.fetchone()
    return int(row[0] if row else 0)


def fetch_bullying_reports(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """Return paginated bullying reports ordered by priority and recency."""
    status_filter = None
    if status:
        normalized = status.lower()
        if normalized not in BULLYING_STATUSES:
            raise ValueError(f"Status bullying tidak dikenal: {status}")
        status_filter = normalized

    conditions: List[str] = []
    params: List[Any] = []
    if status_filter:
        conditions.append('br.status = %s')
        params.append(status_filter)

    where_clause = ''
    if conditions:
        where_clause = ' WHERE ' + ' AND '.join(conditions)

    query = (
        """
        SELECT
            br.id,
            br.chat_log_id,
            br.user_id,
            br.username,
            br.description,
            br.status,
            br.priority,
            br.notes,
            br.created_at,
            br.updated_at,
            br.last_updated_by,
            br.category,
            br.severity,
            br.metadata,
            br.assigned_to,
            br.due_at,
            br.resolved_at,
            br.escalated,
            cl.created_at AS chat_created_at
        FROM bullying_reports br
        LEFT JOIN chat_logs cl ON cl.id = br.chat_log_id
        """
        + where_clause
        + " ORDER BY br.escalated DESC, br.priority DESC, br.created_at DESC LIMIT %s OFFSET %s"
    )

    with get_cursor() as cur:
        cur.execute(query, (*params, limit, offset))
        rows = cur.fetchall()
        cur.execute(
            "SELECT COUNT(*) FROM bullying_reports br" + where_clause,
            params,
        )
        total = cur.fetchone()[0]

    records: List[Dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        description = record.get("description") or ""
        if description:
            preview = description.split("\n\n", 1)[0].strip()
        else:
            preview = ""
        record["description_preview"] = preview
        records.append(record)

    return records, int(total or 0)


def fetch_psych_reports(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    *,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """Return paginated psychological reports ordered by severity and recency."""
    conditions: List[str] = []
    params: List[Any] = []
    group_expr = "COALESCE(CAST(pr.user_id AS TEXT), CONCAT('report-', pr.id))"

    if status:
        normalized_status = status.lower()
        if normalized_status not in PSYCH_STATUSES:
            raise ValueError(f"Status laporan psikolog tidak dikenal: {status}")
        conditions.append("pr.status = %s")
        params.append(normalized_status)

    if severity:
        normalized_severity = severity.lower()
        if normalized_severity not in PSYCH_SEVERITIES:
            raise ValueError(f"Tingkat keparahan tidak dikenal: {severity}")
        conditions.append("pr.severity = %s")
        params.append(normalized_severity)

    where_clause = ""
    if conditions:
        where_clause = " WHERE " + " AND ".join(conditions)

    filtered_cte = (
        """
        WITH filtered AS (
            SELECT
                pr.*,
                cl.created_at AS chat_created_at,
                {group_expr} AS group_key,
                ROW_NUMBER() OVER (
                    PARTITION BY {group_expr}
                    ORDER BY pr.created_at DESC
                ) AS row_no
            FROM psych_reports pr
            LEFT JOIN chat_logs cl ON cl.id = pr.chat_log_id
            {where_clause}
        )
        """
    ).format(group_expr=group_expr, where_clause=where_clause)

    query = (
        filtered_cte
        + """
        SELECT
            id,
            chat_log_id,
            user_id,
            username,
            message,
            summary,
            severity,
            status,
            metadata,
            created_at,
            updated_at,
            chat_created_at,
            group_key
        FROM filtered
        WHERE row_no = 1
        ORDER BY CASE WHEN severity = 'critical' THEN 2 WHEN severity = 'elevated' THEN 1 ELSE 0 END DESC, created_at DESC
        LIMIT %s OFFSET %s
        """
    )

    with get_cursor() as cur:
        cur.execute(query, (*params, limit, offset))
        rows = cur.fetchall()
        count_query = (
            filtered_cte
            + "SELECT COUNT(DISTINCT group_key) FROM filtered"
        )
        cur.execute(count_query, params)
        total = cur.fetchone()[0] if cur.rowcount else 0

    records: List[Dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        message_text = record.get("message") or ""
        if message_text:
            message_preview = message_text.split("\n\n", 1)[0].strip()
        else:
            message_preview = ""
        summary_text = record.get("summary") or ""
        if summary_text:
            summary_preview = summary_text.split("\n\n", 1)[0].strip()
        else:
            summary_preview = message_preview
        record["message_preview"] = message_preview
        record["summary_preview"] = summary_preview or message_preview
        records.append(record)

    return records, int(total or 0)


def fetch_psych_group_reports(
    *,
    user_id: Optional[int] = None,
    report_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return all reports belonging to a user (or fallback single report)."""
    if user_id is None and report_id is None:
        raise ValueError("Either user_id or report_id must be provided")

    with get_cursor() as cur:
        if user_id is not None:
            cur.execute(
                """
                SELECT
                    pr.id,
                    pr.chat_log_id,
                    pr.user_id,
                    pr.username,
                    pr.message,
                    pr.summary,
                    pr.severity,
                    pr.status,
                    pr.metadata,
                    pr.created_at,
                    pr.updated_at,
                    cl.created_at AS chat_created_at
                FROM psych_reports pr
                LEFT JOIN chat_logs cl ON cl.id = pr.chat_log_id
                WHERE pr.user_id = %s
                ORDER BY pr.created_at DESC
                """,
                (user_id,),
            )
        else:
            cur.execute(
                """
                SELECT
                    pr.id,
                    pr.chat_log_id,
                    pr.user_id,
                    pr.username,
                    pr.message,
                    pr.summary,
                    pr.severity,
                    pr.status,
                    pr.metadata,
                    pr.created_at,
                    pr.updated_at,
                    cl.created_at AS chat_created_at
                FROM psych_reports pr
                LEFT JOIN chat_logs cl ON cl.id = pr.chat_log_id
                WHERE pr.id = %s
                ORDER BY pr.created_at DESC
                """,
                (report_id,),
            )
        rows = cur.fetchall()

    records: List[Dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        metadata = record.get("metadata")
        if metadata and isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (ValueError, TypeError):
                metadata = {}
            record["metadata"] = metadata
        if not metadata:
            metadata = {}
        message_chunks = metadata.get("message_chunks")
        if isinstance(message_chunks, list) and message_chunks:
            formatted = "\n\n".join(
                chunk.strip()
                for chunk in message_chunks
                if isinstance(chunk, str) and chunk.strip()
            )
            if formatted:
                record["message"] = formatted
        else:
            message_text = record.get("message")
            if isinstance(message_text, str) and message_text:
                record["message"] = (
                    message_text.replace("\r\n", "\n").replace("\r", "\n")
                )
        summary_text = record.get("summary")
        if isinstance(summary_text, str) and summary_text:
            record["summary"] = summary_text.replace("\r\n", "\n").replace("\r", "\n")
        records.append(record)

    return records


def update_psych_report_status(
    report_id: int,
    status: str,
    *,
    updated_by: Optional[str] = None,
) -> bool:
    """Update status (and optionally last_updated_by inside metadata) for a psych report."""
    normalized = (status or "").strip().lower()
    if normalized not in PSYCH_STATUSES:
        raise ValueError(f"Status laporan konseling tidak dikenal: {status}")

    with get_cursor(commit=True) as cur:
        cur.execute(
            "SELECT metadata FROM psych_reports WHERE id = %s FOR UPDATE",
            (report_id,),
        )
        row = cur.fetchone()
        if not row:
            return False
        metadata = dict(row["metadata"] or {})
        metadata_changed = False
        if updated_by:
            if metadata.get("last_updated_by") != updated_by:
                metadata["last_updated_by"] = updated_by
                metadata_changed = True

        metadata_param = Json(metadata) if metadata_changed else row["metadata"]

        cur.execute(
            """
            UPDATE psych_reports
            SET status = %s,
                metadata = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (normalized, metadata_param, report_id),
        )
        return cur.rowcount > 0

def bulk_update_psych_report_status(
    report_ids: List[int],
    status: str,
    updated_by: Optional[str] = None,
) -> bool:
    """Update the status for a list of psych reports, archiving all reports from the same user if one is archived."""
    if not report_ids:
        return False

    normalized_status = status.lower()
    if normalized_status not in PSYCH_STATUSES and normalized_status != "undo":
        raise ValueError(f"Invalid psych report status: {status}")

    target_status = "open" if normalized_status == "undo" else normalized_status

    with get_cursor(commit=True) as cur:
        # Get the user_ids for the given report_ids
        cur.execute(
            "SELECT DISTINCT user_id FROM psych_reports WHERE id = ANY(%s::int[]) AND user_id IS NOT NULL",
            (report_ids,),
        )
        user_ids = [row[0] for row in cur.fetchall()]

        if not user_ids:
            # If no user_ids are found, just update the selected reports
            cur.execute(
                """
                UPDATE psych_reports
                SET status = %s,
                    updated_at = NOW()
                WHERE id = ANY(%s::int[])
                """,
                (target_status, report_ids),
            )
            return cur.rowcount > 0

        # Update all reports for the found user_ids
        cur.execute(
            """
            UPDATE psych_reports
            SET status = %s,
                updated_at = NOW()
            WHERE user_id = ANY(%s::int[])
            """,
            (target_status, user_ids),
        )
        return cur.rowcount > 0


def update_bullying_report_status(
    report_id: int,
    status: Optional[str] = None,
    *,
    notes: Optional[str] = None,
    updated_by: Optional[str] = None,
    assigned_to: Optional[str] = None,
    due_at: Optional[datetime] = None,
    escalated: Optional[bool] = None,
) -> bool:
    """Update bullying report fields and append an audit trail entry."""
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            SELECT status, notes, assigned_to, due_at, escalated
            FROM bullying_reports
            WHERE id = %s
            FOR UPDATE
            """,
            (report_id,),
        )
        row = cur.fetchone()
        if not row:
            return False

        current = dict(row)
        updates: List[str] = []
        params: List[Any] = []
        changes: Dict[str, Any] = {}

        new_status = current.get("status")
        if status is not None:
            normalized = status.lower()
            if normalized not in BULLYING_STATUSES:
                raise ValueError(f"Status bullying tidak dikenal: {status}")
            if normalized != current.get("status"):
                new_status = normalized
                updates.append("status = %s")
                params.append(normalized)
                if normalized == "resolved":
                    updates.append("resolved_at = NOW()")
                else:
                    updates.append("resolved_at = NULL")
                changes["status"] = {"from": current.get("status"), "to": normalized}

        trimmed_notes = None
        if notes is not None:
            trimmed_notes = notes.strip() or None
            if trimmed_notes != current.get("notes"):
                updates.append("notes = %s")
                params.append(trimmed_notes)
                changes["notes"] = {"from": current.get("notes"), "to": trimmed_notes}

        assigned_clean = (assigned_to or '').strip() or None
        if assigned_to is not None and assigned_clean != current.get("assigned_to"):
            updates.append("assigned_to = %s")
            params.append(assigned_clean)
            changes["assigned_to"] = {"from": current.get("assigned_to"), "to": assigned_clean}

        due_value = None
        if due_at is not None:
            due_value = due_at
            if isinstance(due_at, str):
                due_at_str = due_at.strip()
                due_value = datetime.fromisoformat(due_at_str) if due_at_str else None
            if due_value != current.get("due_at"):
                updates.append("due_at = %s")
                params.append(due_value)
                changes["due_at"] = {
                    "from": current.get("due_at").isoformat() if current.get("due_at") else None,
                    "to": due_value.isoformat() if due_value else None,
                }

        if escalated is not None:
            escalated_bool = bool(escalated)
            if escalated_bool != bool(current.get("escalated")):
                updates.append("escalated = %s")
                params.append(escalated_bool)
                changes["escalated"] = {
                    "from": bool(current.get("escalated")),
                    "to": escalated_bool,
                }
                if escalated_bool:
                    updates.append("priority = TRUE")

        if updated_by is not None:
            updates.append("last_updated_by = %s")
            params.append(updated_by)

        if not updates:
            return False

        updates.append("updated_at = NOW()")
        query = "UPDATE bullying_reports SET " + ", ".join(updates) + " WHERE id = %s"
        cur.execute(query, (*params, report_id))
        if cur.rowcount == 0:
            return False

        event_type = "update"
        if "status" in changes:
            new_state = changes["status"]["to"]
            old_state = changes["status"]["from"]
            if new_state == "resolved":
                event_type = "resolved"
            elif new_state == "pending" and old_state and old_state != "pending":
                event_type = "reopened"
            else:
                event_type = "status_changed"
        elif "escalated" in changes and changes["escalated"]["to"]:
            event_type = "escalated"

        payload: Dict[str, Any] = {"changes": changes}
        if trimmed_notes is not None:
            payload["notes"] = trimmed_notes
        _insert_event = """
            INSERT INTO bullying_report_events (report_id, event_type, actor, payload)
            VALUES (%s, %s, %s, %s)
        """
        cur.execute(_insert_event, (report_id, event_type, updated_by, Json(payload)))
    return True

def bulk_update_bullying_report_status(
    report_ids: List[int],
    status: str,
    updated_by: Optional[str] = None,
) -> bool:
    """Update the status for a list of bullying reports."""
    if not report_ids:
        return False

    normalized_status = status.lower()
    if normalized_status not in BULLYING_STATUSES and normalized_status != "undo":
        raise ValueError(f"Invalid bullying report status: {status}")

    target_status = "pending" if normalized_status == "undo" else normalized_status

    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE bullying_reports
            SET status = %s,
                last_updated_by = %s,
                updated_at = NOW()
            WHERE id = ANY(%s::int[])
            """,
            (target_status, updated_by, report_ids),
        )
        return cur.rowcount > 0


def fetch_bullying_report_detail(report_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                br.id,
                br.chat_log_id,
                br.user_id,
                br.username,
                br.description,
                br.status,
                br.priority,
                br.notes,
                br.created_at,
                br.updated_at,
                br.last_updated_by,
                br.category,
                br.severity,
                br.metadata,
                br.assigned_to,
                br.due_at,
                br.resolved_at,
                br.escalated,
                cl.created_at AS chat_created_at
            FROM bullying_reports br
            LEFT JOIN chat_logs cl ON cl.id = br.chat_log_id
            WHERE br.id = %s
            LIMIT 1
            """,
            (report_id,)
        )
        report_row = cur.fetchone()
        if not report_row:
            return None
        report = dict(report_row)

        cur.execute(
            """
            SELECT id, event_type, actor, payload, created_at
            FROM bullying_report_events
            WHERE report_id = %s
            ORDER BY created_at ASC
            """,
            (report_id,)
        )
        events = [dict(evt) for evt in cur.fetchall()]
        report["events"] = events
    return report


def fetch_bullying_report_basic(report_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, status, notes, assigned_to, due_at, escalated
            FROM bullying_reports
            WHERE id = %s
            LIMIT 1
            """,
            (report_id,)
        )
        row = cur.fetchone()
    return dict(row) if row else None


def fetch_corruption_summary() -> Dict[str, int]:
    """Return aggregated counts of corruption reports by status."""
    summary = {status: 0 for status in CORRUPTION_STATUSES}
    total = 0
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT status, COUNT(*) AS total
            FROM corruption_reports
            GROUP BY status
            """
        )
        rows = cur.fetchall()
    for row in rows:
        status = (row.get('status') or '').lower()
        count = int(row.get('total') or 0)
        if status in summary:
            summary[status] = count
            total += count
    summary['total'] = total
    return summary


def fetch_pending_corruption_count() -> int:
    """Shortcut to obtain the number of open corruption reports."""
    return fetch_corruption_summary().get('open', 0)


def fetch_corruption_reports(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """Return paginated corruption reports ordered by recency."""
    status_filter = None
    if status:
        normalized = status.lower()
        if normalized not in CORRUPTION_STATUSES:
            raise ValueError(f"Status korupsi tidak dikenal: {status}")
        status_filter = normalized

    conditions: List[str] = []
    params: List[Any] = []
    if status_filter:
        conditions.append('status = %s')
        params.append(status_filter)

    where_clause = ''
    if conditions:
        where_clause = ' WHERE ' + ' AND '.join(conditions)

    query = (
        """
        SELECT
            id,
            ticket_id,
            user_id,
            status,
            involved,
            location,
            time,
            chronology,
            created_at,
            updated_at
        FROM corruption_reports
        """
        + where_clause
        + " ORDER BY created_at DESC LIMIT %s OFFSET %s"
    )

    with get_cursor() as cur:
        cur.execute(query, (*params, limit, offset))
        rows = cur.fetchall()
        cur.execute(
            "SELECT COUNT(*) FROM corruption_reports" + where_clause,
            params,
        )
        total = cur.fetchone()[0]

    return [dict(row) for row in rows], int(total or 0)


def fetch_corruption_report_detail(report_id: int) -> Optional[Dict[str, Any]]:
    """Fetches all details for a single corruption report."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                id,
                ticket_id,
                user_id,
                status,
                involved,
                location,
                time,
                chronology,
                created_at,
                updated_at
            FROM corruption_reports
            WHERE id = %s
            LIMIT 1
            """,
            (report_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        
        report = dict(row)
        username = None

        if report.get('user_id'):
            cur.execute(
                "SELECT username FROM chat_logs WHERE user_id = %s ORDER BY created_at DESC LIMIT 1",
                (report['user_id'],)
            )
            user_row = cur.fetchone()
            if user_row:
                username = user_row['username']
        
        report['username'] = username
        report['notes'] = None
        report['assigned_to'] = None
        report['due_at'] = None
        report['resolved_at'] = None
        report['escalated'] = False
        report['last_updated_by'] = None
        report['events'] = []

    return report


def bulk_update_corruption_report_status(
    report_ids: List[int],
    status: str,
    updated_by: Optional[str] = None,
) -> bool:
    """Update the status for a list of corruption reports."""
    if not report_ids:
        return False

    normalized_status = status.lower()
    if normalized_status not in CORRUPTION_STATUSES and normalized_status != "undo":
        raise ValueError(f"Invalid corruption report status: {status}")

    target_status = "open" if normalized_status == "undo" else normalized_status

    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE corruption_reports
            SET status = %s,
                updated_at = NOW()
            WHERE id = ANY(%s::int[])
            """,
            (target_status, report_ids),
        )
        return cur.rowcount > 0


def update_corruption_report_status(
    report_id: int,
    status: Optional[str] = None,
    *,
    updated_by: Optional[str] = None,
) -> bool:
    """Update corruption report status."""
    if status is None:
        return False
        
    normalized = status.lower()
    if normalized not in CORRUPTION_STATUSES:
        raise ValueError(f"Status korupsi tidak dikenal: {status}")

    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE corruption_reports 
            SET status = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (normalized, report_id)
        )
        return cur.rowcount > 0


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
