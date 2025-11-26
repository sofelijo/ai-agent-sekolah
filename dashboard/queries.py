from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from flask import has_request_context, session
from psycopg2.extras import DictRow, Json

from .db_access import get_cursor
from db import (
    DEFAULT_TKA_PRESETS,
    DEFAULT_TKA_PRESET_KEY,
    DEFAULT_TKA_COMPOSITE_DURATION,
    TKA_SECTION_TEMPLATES,
    TKA_SECTION_KEY_ORDER,
    TKA_METADATA_SECTION_CONFIG_KEY,
)
from account_status import ACCOUNT_STATUS_CHOICES

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

VALID_GRADE_LEVELS = {"sd6", "smp3", "sma"}
DEFAULT_GRADE_LEVEL = "sd6"
VALID_TEST_FORMATS = {"multiple_choice", "true_false"}


def _normalize_mix_value(value: Any, fallback: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return fallback


def _coerce_mix_local(raw: Optional[Dict[str, Any]], fallback: Optional[Dict[str, int]] = None) -> Dict[str, int]:
    base = {
        "easy": fallback.get("easy") if fallback else 0,
        "medium": fallback.get("medium") if fallback else 0,
        "hard": fallback.get("hard") if fallback else 0,
    }
    if isinstance(raw, dict):
        for key in base.keys():
            base[key] = _normalize_mix_value(raw.get(key), base[key])
    total = sum(base.values())
    if total <= 0 and fallback:
        return dict(fallback)
    if total <= 0:
        return dict(DEFAULT_TKA_PRESETS.get(DEFAULT_TKA_PRESET_KEY, {"easy": 10, "medium": 5, "hard": 5}))
    return base


def _default_presets_payload_local() -> Dict[str, Dict[str, int]]:
    return {key: dict(value) for key, value in DEFAULT_TKA_PRESETS.items()}


def _prepare_presets_payload(stored: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    presets = _default_presets_payload_local()
    if isinstance(stored, dict):
        for key, mix in stored.items():
            if not key:
                continue
            presets[str(key).strip().lower()] = _coerce_mix_local(mix, presets.get(key))
    return presets


def _normalize_preset_name_local(value: Optional[str]) -> str:
    if not value:
        return DEFAULT_TKA_PRESET_KEY
    return str(value).strip().lower()


def _determine_stimulus_type_local(has_text: bool, has_image: bool) -> str:
    if has_text and has_image:
        return "mixed"
    if has_image:
        return "image"
    return "text"


def _resolve_question_stimulus(
    cur,
    subject_id: int,
    payload: Optional[Dict[str, Any]],
    created_by: Optional[int],
    bundle_cache: Dict[str, int],
) -> Optional[int]:
    if not payload or not isinstance(payload, dict):
        return None
    bundle_key = payload.get("bundle_key")
    if bundle_key and bundle_key in bundle_cache:
        return bundle_cache[bundle_key]
    existing_id = payload.get("id") or payload.get("stimulus_id")
    if existing_id:
        if bundle_key:
            bundle_cache[bundle_key] = int(existing_id)
        return int(existing_id)
    narrative = (payload.get("narrative") or payload.get("text") or "").strip()
    image_value = payload.get("image_url") or payload.get("image_data") or payload.get("image")
    if not narrative and not image_value:
        return None
    title = (payload.get("title") or payload.get("name") or "Stimulus").strip()
    metadata_payload = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None
    stimulus_type = payload.get("type") or _determine_stimulus_type_local(bool(narrative), bool(image_value))
    table_name = _get_stimulus_table_name(cur)
    # Cegah duplikasi: pakai stimulus yang sama jika judul + narasi identik pada mapel ini
    cur.execute(
        f"""
        SELECT id FROM {table_name}
        WHERE subject_id = %s
          AND LOWER(TRIM(title)) = LOWER(%s)
          AND LOWER(COALESCE(TRIM(narrative), '')) = LOWER(%s)
        LIMIT 1
        """,
        (subject_id, title, narrative or ""),
    )
    row = cur.fetchone()
    if row and row[0]:
        existing_id = int(row[0])
        if bundle_key:
            bundle_cache[bundle_key] = existing_id
        return existing_id
    cur.execute(
        f"""
        INSERT INTO {table_name} (
            subject_id,
            title,
            type,
            narrative,
            image_url,
            image_prompt,
            ai_prompt,
            metadata,
            created_by,
            updated_at
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        RETURNING id
        """,
        (
            subject_id,
            title or None,
            stimulus_type,
            narrative or None,
            image_value,
            (payload.get("image_prompt") or payload.get("imagePrompt") or payload.get("image_description")),
            payload.get("ai_prompt"),
            Json(metadata_payload) if metadata_payload else None,
            created_by,
        ),
    )
    row = cur.fetchone()
    stimulus_id = row["id"] if row else None
    if stimulus_id and bundle_key:
        bundle_cache[bundle_key] = stimulus_id
    return stimulus_id


def _rebalance_mix_to_total_local(mix: Dict[str, int], target_total: int) -> Dict[str, int]:
    order = ["easy", "medium", "hard"]
    total = sum(mix.values())
    if target_total <= 0:
        return {key: 0 for key in order}
    if total <= 0:
        base = max(0, target_total // len(order))
        result = {key: base for key in order}
        remainder = target_total - base * len(order)
        idx = 0
        while remainder > 0:
            key = order[idx % len(order)]
            result[key] += 1
            remainder -= 1
            idx += 1
        return result
    result = {key: max(0, int(value)) for key, value in mix.items() if key in order}
    for key in order:
        result.setdefault(key, 0)
    diff = target_total - total
    guard = max(30, target_total * 3)
    while diff != 0 and guard > 0:
        changed = False
        keys = order if diff > 0 else list(reversed(order))
        for key in keys:
            if diff > 0:
                result[key] += 1
                diff -= 1
                changed = True
                if diff == 0:
                    break
            else:
                if result[key] <= 0:
                    continue
                result[key] -= 1
                diff += 1
                changed = True
                if diff == 0:
                    break
        if not changed:
            break
        guard -= 1
    return result


def _default_section_mix_local(question_count: int) -> Dict[str, int]:
    if question_count <= 0:
        question_count = 1
    base = {
        "easy": int(round(question_count * 0.4)),
        "medium": int(round(question_count * 0.4)),
        "hard": int(round(question_count * 0.2)),
    }
    return _rebalance_mix_to_total_local(base, question_count)


def _normalize_section_entry_local(entry: Dict[str, Any], fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    fallback = fallback or {}
    raw_key = entry.get("key") or fallback.get("key") or "section"
    key = str(raw_key).strip().lower() or "section"
    label = (entry.get("label") or fallback.get("label") or key.title()).strip()
    subject_area = (entry.get("subject_area") or fallback.get("subject_area") or key).strip().lower()
    question_format = (entry.get("question_format") or fallback.get("question_format") or "multiple_choice").strip().lower()
    desired_total = entry.get("question_count") or fallback.get("question_count") or 0
    try:
        desired_total = max(0, int(desired_total))
    except (TypeError, ValueError):
        desired_total = 0
    raw_mix = entry.get("difficulty") or entry.get("difficulty_mix")
    fallback_mix = fallback.get("difficulty") or fallback.get("difficulty_mix")
    if fallback_mix is None:
        fallback_mix = _default_section_mix_local(desired_total)
    mix = _coerce_mix_local(raw_mix or fallback_mix, fallback_mix)
    mix = _rebalance_mix_to_total_local(mix, desired_total or sum(mix.values()))
    return {
        "key": key,
        "label": label,
        "subject_area": subject_area,
        "question_format": question_format,
        "question_count": sum(mix.values()),
        "difficulty": mix,
    }


def _normalize_section_config_local(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    raw_config: Dict[str, Any] = {}
    if isinstance(metadata, dict):
        raw = metadata.get(TKA_METADATA_SECTION_CONFIG_KEY)
        if isinstance(raw, dict):
            raw_config = raw
    duration_value = raw_config.get("duration_minutes")
    try:
        duration_minutes = int(duration_value) if duration_value is not None else DEFAULT_TKA_COMPOSITE_DURATION
    except (TypeError, ValueError):
        duration_minutes = DEFAULT_TKA_COMPOSITE_DURATION
    duration_minutes = max(30, duration_minutes)
    template_map = {template["key"]: template for template in TKA_SECTION_TEMPLATES}
    sections_payload = raw_config.get("sections") if isinstance(raw_config.get("sections"), list) else []
    normalized_sections: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for entry in sections_payload:
        if not isinstance(entry, dict):
            continue
        normalized = _normalize_section_entry_local(entry, template_map.get(entry.get("key")))
        normalized_sections.append(normalized)
        seen.add(normalized["key"])
    for template in TKA_SECTION_TEMPLATES:
        if template["key"] in seen:
            continue
        normalized_sections.append(_normalize_section_entry_local(template, template))
    normalized_sections.sort(key=lambda item: TKA_SECTION_KEY_ORDER.index(item["key"]) if item["key"] in TKA_SECTION_KEY_ORDER else item["key"])
    return {
        "duration_minutes": duration_minutes,
        "sections": normalized_sections,
    }


def _aggregate_section_mix_local(sections: List[Dict[str, Any]]) -> Dict[str, int]:
    totals = {"easy": 0, "medium": 0, "hard": 0}
    for section in sections:
        mix = section.get("difficulty") or {}
        for key in totals.keys():
            try:
                totals[key] += int(mix.get(key) or 0)
            except (TypeError, ValueError):
                continue
    return totals

_CHAT_TOPIC_AVAILABLE: Optional[bool] = None
_TESTER_IDS_CACHE: Optional[List[int]] = None


def _load_tester_ids() -> List[int]:
    """Parse tester user_id list from environment."""
    global _TESTER_IDS_CACHE
    if _TESTER_IDS_CACHE is not None:
        return _TESTER_IDS_CACHE

    raw_value = os.getenv("DASHBOARD_TESTER_IDS", "") or ""
    candidates = re.split(r"[,\s;]+", raw_value.strip())
    parsed: List[int] = []
    for item in candidates:
        if not item:
            continue
        try:
            parsed.append(int(item))
        except ValueError:
            continue
    _TESTER_IDS_CACHE = parsed
    return parsed


def _no_tester_active() -> bool:
    """Return True when the current request should hide tester data."""
    if not has_request_context():
        return False
    user = session.get("user") or {}
    return bool(user.get("no_tester_enabled"))


def _tester_condition(column: str = "user_id") -> Tuple[str, List[Any]]:
    """
    Build a SQL condition snippet (without prefix) to exclude tester user_ids.
    Returns the condition string and parameter list (single list of ids) when active.
    """
    if not _no_tester_active():
        return "", []
    tester_ids = _load_tester_ids()
    if not tester_ids:
        return "", []
    return f"({column} IS NULL OR {column} <> ALL(%s))", [tester_ids]


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
        clause, params = _tester_condition("user_id")
        tester_param = params[0] if params else None

        query = "SELECT COUNT(*) AS total_messages FROM chat_logs"
        if clause:
            query += f" WHERE {clause}"
        cur.execute(query, (tester_param,) if tester_param is not None else ())
        total_messages = cur.fetchone()["total_messages"]

        query = (
            "SELECT COUNT(*) AS total_incoming_messages "
            "FROM chat_logs WHERE role = 'user'"
        )
        query_params: List[Any] = []
        if clause:
            query += f" AND {clause}"
            query_params = [tester_param]
        cur.execute(query, tuple(query_params))
        total_incoming_messages = cur.fetchone()["total_incoming_messages"]

        def _distinct_users(interval_clause: str) -> int:
            base_query = (
                "SELECT COUNT(DISTINCT user_id) AS unique_users "
                "FROM chat_logs WHERE role = 'user'"
            )
            query_params: List[Any] = []
            if interval_clause:
                base_query += f" AND {interval_clause}"
            if clause:
                base_query += f" AND {clause}"
                query_params.append(tester_param)
            cur.execute(base_query, tuple(query_params))
            return cur.fetchone()["unique_users"]

        unique_users_all = _distinct_users("")
        unique_users_today = _distinct_users("DATE(created_at) = CURRENT_DATE")
        unique_users_7d = _distinct_users("created_at >= NOW() - INTERVAL '7 days'")
        unique_users_30d = _distinct_users("created_at >= NOW() - INTERVAL '30 days'")
        unique_users_365d = _distinct_users("created_at >= NOW() - INTERVAL '365 days'")

        query = (
            "SELECT "
            "    AVG(response_time_ms)::float AS avg_response, "
            "    percentile_cont(0.9) WITHIN GROUP (ORDER BY response_time_ms) AS p90_response "
            "FROM chat_logs "
            "WHERE response_time_ms IS NOT NULL"
        )
        query_params = []
        if clause:
            query += f" AND {clause}"
            query_params = [tester_param]
        cur.execute(query, tuple(query_params))
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
    clause, clause_params = _tester_condition("user_id")
    if clause:
        query.append(f"AND {clause}")
        params.extend(clause_params)
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
        clause, clause_params = _tester_condition("user_id")
        query_parts = [
            "SELECT id, user_id, username, text, created_at",
            "FROM chat_logs",
            "WHERE role = 'user'",
        ]
        if clause:
            query_parts.append(f"AND {clause}")
        query_parts.extend(
            [
                "ORDER BY created_at DESC",
                "LIMIT %s",
            ]
        )
        params: List[Any] = [*clause_params, limit]
        cur.execute("\n".join(query_parts), tuple(params))
        rows = cur.fetchall()
    return [dict(row) for row in rows]

def fetch_top_users(limit: int = 5) -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        clause, clause_params = _tester_condition("user_id")
        query_parts = [
            "SELECT user_id, COALESCE(username, 'Unknown') AS username, COUNT(*) AS messages",
            "FROM chat_logs",
            "WHERE role = 'user'",
        ]
        if clause:
            query_parts.append(f"AND {clause}")
        query_parts.extend(
            [
                "GROUP BY user_id, username",
                "ORDER BY messages DESC",
                "LIMIT %s",
            ]
        )
        params: List[Any] = [*clause_params, limit]
        cur.execute("\n".join(query_parts), tuple(params))
        rows = cur.fetchall()
    return [dict(row) for row in rows]

def fetch_top_keywords(limit: int = 10, days: int = 14, min_length: int = 3) -> List[Dict[str, Any]]:
    """Return most frequent keywords from user messages within the given time window."""
    days = max(1, days)
    limit = max(1, limit)
    min_length = max(1, min_length)

    with get_cursor() as cur:
        clause, clause_params = _tester_condition("user_id")
        query_parts = [
            "SELECT text",
            "FROM chat_logs",
            "WHERE role = 'user'",
            "  AND text IS NOT NULL",
            "  AND text <> ''",
            "  AND created_at >= NOW() - %s::interval",
        ]
        if clause:
            query_parts.append(f"  AND {clause}")
        params: List[Any] = [f"{days} days", *clause_params]
        cur.execute("\n".join(query_parts), tuple(params))
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

    tester_clause, tester_params = _tester_condition("user_id")
    if tester_clause:
        conditions.append(tester_clause)
        params.extend(tester_params)

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
    if _no_tester_active() and user_id in set(_load_tester_ids()):
        return []
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
        clause, clause_params = _tester_condition("user_id")
        query_parts = [
            "SELECT",
            "    user_id,",
            "    COALESCE(username, 'Unknown') AS username,",
            "    COUNT(*) AS message_count",
            "FROM chat_logs",
            "WHERE role = 'user'",
        ]
        if clause:
            query_parts.append(f"AND {clause}")
        query_parts.extend(
            [
                "GROUP BY user_id, username",
                "ORDER BY MAX(created_at) DESC",
            ]
        )
        cur.execute("\n".join(query_parts), tuple(clause_params))
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def fetch_twitter_overview(window_days: int = 7, bot_user_id: Optional[int] = None) -> Dict[str, Any]:
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
            "autopost_total": 0,
            "autopost_window": 0,
            "autopost_24h": 0,
            "autopost_today": 0,
            "last_autopost": None,
        }

    window_days = max(1, window_days)
    window_interval = f"{window_days} days"

    with get_cursor() as cur:
        clause, clause_params = _tester_condition("user_id")
        overview_query = """
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
        """.strip()
        params: List[Any] = [window_interval, window_interval, window_interval]
        if clause:
            overview_query += f" AND {clause}"
            params.extend(clause_params)
        cur.execute(overview_query, tuple(params))
        overview_row = cur.fetchone() or {}

        mention_query = [
            "SELECT id, user_id, username, text, created_at",
            "FROM chat_logs",
            "WHERE topic = 'twitter' AND role = 'user'",
        ]
        mention_params: List[Any] = []
        if clause:
            mention_query.append(f"AND {clause}")
            mention_params.extend(clause_params)
        mention_query.extend(["ORDER BY created_at DESC", "LIMIT 1"])
        cur.execute("\n".join(mention_query), tuple(mention_params))
        last_mention = cur.fetchone()

        reply_query = [
            "SELECT id, user_id, username, text, created_at, response_time_ms",
            "FROM chat_logs",
            "WHERE topic = 'twitter' AND role = 'aska'",
        ]
        reply_params: List[Any] = []
        if bot_user_id:
            reply_query.append("AND (user_id IS NULL OR user_id <> %s)")
            reply_params.append(bot_user_id)
        if clause:
            reply_query.append(f"AND {clause}")
            reply_params.extend(clause_params)
        reply_query.extend(["ORDER BY created_at DESC", "LIMIT 1"])
        cur.execute("\n".join(reply_query), tuple(reply_params))
        last_reply = cur.fetchone()

        autopost_total = autopost_window = autopost_24h = autopost_today = 0
        last_autopost = None
        if bot_user_id:
            autopost_query = [
                "SELECT",
                "    COUNT(*) AS total,",
                "    COUNT(*) FILTER (WHERE created_at >= NOW() - %s::interval) AS window,",
                "    COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '1 day') AS day_24h,",
                "    COUNT(*) FILTER (WHERE DATE(created_at) = CURRENT_DATE) AS today",
                "FROM chat_logs",
                "WHERE topic = 'twitter'",
                "  AND role = 'aska'",
                "  AND user_id = %s",
            ]
            autopost_params: List[Any] = [window_interval, bot_user_id]
            if clause:
                autopost_query.append(f"  AND {clause}")
                autopost_params.extend(clause_params)
            cur.execute("\n".join(autopost_query), tuple(autopost_params))
            autopost_row = cur.fetchone() or {}

            autopost_last_query = [
                "SELECT id, user_id, username, text, created_at",
                "FROM chat_logs",
                "WHERE topic = 'twitter'",
                "  AND role = 'aska'",
                "  AND user_id = %s",
            ]
            autopost_last_params: List[Any] = [bot_user_id]
            if clause:
                autopost_last_query.append(f"  AND {clause}")
                autopost_last_params.extend(clause_params)
            autopost_last_query.extend(["ORDER BY created_at DESC", "LIMIT 1"])
            cur.execute("\n".join(autopost_last_query), tuple(autopost_last_params))
            last_autopost = cur.fetchone()
        else:
            autopost_row = {}

    def _coerce_int(value) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    avg_response = overview_row.get("avg_response_ms")
    p90_response = overview_row.get("p90_response_ms")

    total_mentions = _coerce_int(overview_row.get("mentions_total"))
    total_replies_raw = _coerce_int(overview_row.get("replies_total"))
    replies_window_raw = _coerce_int(overview_row.get("replies_window"))
    replies_24h_raw = _coerce_int(overview_row.get("replies_24h"))
    replies_today_raw = _coerce_int(overview_row.get("replies_today"))

    autopost_total = _coerce_int(autopost_row.get("total"))
    autopost_window = _coerce_int(autopost_row.get("window"))
    autopost_24h = _coerce_int(autopost_row.get("day_24h"))
    autopost_today = _coerce_int(autopost_row.get("today"))

    total_replies = max(0, total_replies_raw - autopost_total)
    replies_window = max(0, replies_window_raw - autopost_window)
    replies_24h = max(0, replies_24h_raw - autopost_24h)
    replies_today = max(0, replies_today_raw - autopost_today)

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
        "replies_window": replies_window,
        "users_window": _coerce_int(overview_row.get("users_window")),
        "mentions_24h": _coerce_int(overview_row.get("mentions_24h")),
        "replies_24h": replies_24h,
        "mentions_today": _coerce_int(overview_row.get("mentions_today")),
        "replies_today": replies_today,
        "avg_response_ms": float(avg_response) if avg_response is not None else None,
        "p90_response_ms": float(p90_response) if p90_response is not None else None,
        "backlog": backlog,
        "reply_rate": reply_rate,
        "last_mention": dict(last_mention) if last_mention else None,
        "last_reply": dict(last_reply) if last_reply else None,
        "autopost_total": autopost_total,
        "autopost_window": autopost_window,
        "autopost_24h": autopost_24h,
        "autopost_today": autopost_today,
        "last_autopost": dict(last_autopost) if last_autopost else None,
    }


def fetch_twitter_activity(days: int = 30) -> List[Dict[str, Any]]:
    """Ambil aktivitas harian mention dan balasan untuk topik Twitter."""
    if not chat_topic_available():
        return []
    days = max(1, days)
    with get_cursor() as cur:
        clause, clause_params = _tester_condition("user_id")
        query_parts = [
            "SELECT",
            "    DATE(created_at) AS day,",
            "    COUNT(*) FILTER (WHERE role = 'user') AS mentions,",
            "    COUNT(*) FILTER (WHERE role = 'aska') AS replies",
            "FROM chat_logs",
            "WHERE topic = 'twitter'",
            "  AND created_at >= NOW() - %s::interval",
        ]
        if clause:
            query_parts.append(f"  AND {clause}")
        query_parts.extend(["GROUP BY day", "ORDER BY day ASC"])
        params: List[Any] = [f"{days} days", *clause_params]
        cur.execute("\n".join(query_parts), tuple(params))
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
        clause, clause_params = _tester_condition("user_id")
        query_parts = [
            "SELECT",
            "    user_id,",
            "    COALESCE(NULLIF(username, ''), 'Unknown') AS username,",
            "    COUNT(*) AS mentions,",
            "    MAX(created_at) AS last_seen",
            "FROM chat_logs",
            "WHERE topic = 'twitter'",
            "  AND role = 'user'",
        ]
        if clause:
            query_parts.append(f"  AND {clause}")
        query_parts.extend(
            [
                "GROUP BY user_id, username",
                "ORDER BY mentions DESC, last_seen DESC",
                "LIMIT %s",
            ]
        )
        params: List[Any] = [*clause_params, limit]
        cur.execute("\n".join(query_parts), tuple(params))
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
        clause, clause_params = _tester_condition("user_id")
        query = [
            "SELECT status, COUNT(*) AS total",
            "FROM bullying_reports",
        ]
        if clause:
            query.append(f"WHERE {clause}")
        query.append("GROUP BY status")
        cur.execute("\n".join(query), tuple(clause_params))
        rows = cur.fetchall()
        esc_query = "SELECT COUNT(*) FROM bullying_reports WHERE escalated = TRUE"
        esc_params: List[Any] = []
        if clause:
            esc_query += f" AND {clause}"
            esc_params.extend(clause_params)
        cur.execute(esc_query, tuple(esc_params))
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
    clause, clause_params = _tester_condition("user_id")

    with get_cursor() as cur:
        status_query = [
            "SELECT status, COUNT(*) AS total",
            "FROM psych_reports",
        ]
        if clause:
            status_query.append(f"WHERE {clause}")
        status_query.append("GROUP BY status")
        cur.execute("\n".join(status_query), tuple(clause_params))
        status_rows = cur.fetchall()

        severity_query = [
            "SELECT severity, COUNT(*) AS total",
            "FROM psych_reports",
            "WHERE status IS NULL OR status <> 'archived'",
        ]
        severity_params: List[Any] = []
        if clause:
            severity_query.append(f"  AND {clause}")
            severity_params.extend(clause_params)
        severity_query.append("GROUP BY severity")
        cur.execute("\n".join(severity_query), tuple(severity_params))
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
    clause, clause_params = _tester_condition("user_id")
    query = "SELECT COUNT(*) FROM psych_reports WHERE status = 'open'"
    params: List[Any] = []
    if clause:
        query += f" AND {clause}"
        params.extend(clause_params)
    with get_cursor() as cur:
        cur.execute(query, tuple(params))
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
    tester_clause, tester_params = _tester_condition("br.user_id")
    if tester_clause:
        conditions.append(tester_clause)
        params.extend(tester_params)

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
    tester_clause, tester_params = _tester_condition("pr.user_id")
    if tester_clause:
        conditions.append(tester_clause)
        params.extend(tester_params)

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

    tester_clause, tester_params = _tester_condition("pr.user_id")

    with get_cursor() as cur:
        if user_id is not None:
            query_parts = [
                "SELECT",
                "    pr.id,",
                "    pr.chat_log_id,",
                "    pr.user_id,",
                "    pr.username,",
                "    pr.message,",
                "    pr.summary,",
                "    pr.severity,",
                "    pr.status,",
                "    pr.metadata,",
                "    pr.created_at,",
                "    pr.updated_at,",
                "    cl.created_at AS chat_created_at",
                "FROM psych_reports pr",
                "LEFT JOIN chat_logs cl ON cl.id = pr.chat_log_id",
                "WHERE pr.user_id = %s",
            ]
            params: List[Any] = [user_id]
            if tester_clause:
                query_parts.append(f"  AND {tester_clause}")
                params.extend(tester_params)
            query_parts.append("ORDER BY pr.created_at DESC")
            cur.execute("\n".join(query_parts), tuple(params))
        else:
            query_parts = [
                "SELECT",
                "    pr.id,",
                "    pr.chat_log_id,",
                "    pr.user_id,",
                "    pr.username,",
                "    pr.message,",
                "    pr.summary,",
                "    pr.severity,",
                "    pr.status,",
                "    pr.metadata,",
                "    pr.created_at,",
                "    pr.updated_at,",
                "    cl.created_at AS chat_created_at",
                "FROM psych_reports pr",
                "LEFT JOIN chat_logs cl ON cl.id = pr.chat_log_id",
                "WHERE pr.id = %s",
            ]
            params = [report_id]
            if tester_clause:
                query_parts.append(f"  AND {tester_clause}")
                params.extend(tester_params)
            query_parts.append("ORDER BY pr.created_at DESC")
            cur.execute("\n".join(query_parts), tuple(params))
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
    tester_clause, tester_params = _tester_condition("br.user_id")
    with get_cursor() as cur:
        query_parts = [
            "SELECT",
            "    br.id,",
            "    br.chat_log_id,",
            "    br.user_id,",
            "    br.username,",
            "    br.description,",
            "    br.status,",
            "    br.priority,",
            "    br.notes,",
            "    br.created_at,",
            "    br.updated_at,",
            "    br.last_updated_by,",
            "    br.category,",
            "    br.severity,",
            "    br.metadata,",
            "    br.assigned_to,",
            "    br.due_at,",
            "    br.resolved_at,",
            "    br.escalated,",
            "    cl.created_at AS chat_created_at",
            "FROM bullying_reports br",
            "LEFT JOIN chat_logs cl ON cl.id = br.chat_log_id",
            "WHERE br.id = %s",
        ]
        params: List[Any] = [report_id]
        if tester_clause:
            query_parts.append(f"  AND {tester_clause}")
            params.extend(tester_params)
        query_parts.append("LIMIT 1")
        cur.execute("\n".join(query_parts), tuple(params))
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
    clause, clause_params = _tester_condition("user_id")
    query = [
        "SELECT id, status, notes, assigned_to, due_at, escalated",
        "FROM bullying_reports",
        "WHERE id = %s",
    ]
    params: List[Any] = [report_id]
    if clause:
        query.append(f"  AND {clause}")
        params.extend(clause_params)
    query.append("LIMIT 1")
    with get_cursor() as cur:
        cur.execute("\n".join(query), tuple(params))
        row = cur.fetchone()
    return dict(row) if row else None


def fetch_corruption_summary() -> Dict[str, int]:
    """Return aggregated counts of corruption reports by status."""
    summary = {status: 0 for status in CORRUPTION_STATUSES}
    total = 0
    clause, clause_params = _tester_condition("user_id")
    with get_cursor() as cur:
        query_parts = [
            "SELECT status, COUNT(*) AS total",
            "FROM corruption_reports",
        ]
        if clause:
            query_parts.append(f"WHERE {clause}")
        query_parts.append("GROUP BY status")
        cur.execute("\n".join(query_parts), tuple(clause_params))
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
    tester_clause, tester_params = _tester_condition("user_id")
    if tester_clause:
        conditions.append(tester_clause)
        params.extend(tester_params)

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
    clause, clause_params = _tester_condition("user_id")
    with get_cursor() as cur:
        query_parts = [
            "SELECT",
            "    id,",
            "    ticket_id,",
            "    user_id,",
            "    status,",
            "    involved,",
            "    location,",
            "    time,",
            "    chronology,",
            "    created_at,",
            "    updated_at",
            "FROM corruption_reports",
            "WHERE id = %s",
        ]
        params: List[Any] = [report_id]
        if clause:
            query_parts.append(f"  AND {clause}")
            params.extend(clause_params)
        query_parts.append("LIMIT 1")
        cur.execute("\n".join(query_parts), tuple(params))
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
            SELECT
                id,
                email,
                password_hash,
                full_name,
                role,
                nrk,
                nip,
                jabatan,
                degree_prefix,
                degree_suffix,
                no_tester_enabled,
                assigned_class_id,
                last_login_at
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
            SELECT
                id,
                email,
                full_name,
                role,
                nrk,
                nip,
                jabatan,
                degree_prefix,
                degree_suffix,
                no_tester_enabled,
                assigned_class_id,
                created_at,
                last_login_at
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
    *,
    nrk: Optional[str] = None,
    nip: Optional[str] = None,
    jabatan: Optional[str] = None,
    degree_prefix: Optional[str] = None,
    degree_suffix: Optional[str] = None,
) -> int:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO dashboard_users (email, full_name, password_hash, role, nrk, nip, jabatan, degree_prefix, degree_suffix)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (email, full_name, password_hash, role, nrk, nip, jabatan, degree_prefix, degree_suffix),
        )
        new_id = cur.fetchone()[0]
    return int(new_id)


def upsert_dashboard_user(
    email: str,
    full_name: str,
    password_hash: str,
    role: str,
    *,
    nrk: Optional[str] = None,
    nip: Optional[str] = None,
    jabatan: Optional[str] = None,
    degree_prefix: Optional[str] = None,
    degree_suffix: Optional[str] = None,
) -> int:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO dashboard_users (email, full_name, password_hash, role, nrk, nip, jabatan, degree_prefix, degree_suffix)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (email) DO UPDATE
                SET full_name = EXCLUDED.full_name,
                    password_hash = EXCLUDED.password_hash,
                    role = EXCLUDED.role,
                    nrk = EXCLUDED.nrk,
                    nip = EXCLUDED.nip,
                    jabatan = EXCLUDED.jabatan,
                    degree_prefix = EXCLUDED.degree_prefix,
                    degree_suffix = EXCLUDED.degree_suffix,
                    last_login_at = dashboard_users.last_login_at
            RETURNING id
            """,
            (email, full_name, password_hash, role, nrk, nip, jabatan, degree_prefix, degree_suffix),
        )
        row = cur.fetchone()
    return int(row[0])

def update_last_login(user_id: int) -> None:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE dashboard_users SET last_login_at = NOW() WHERE id = %s",
            (user_id,),
        )


def update_no_tester_preference(user_id: int, enabled: bool) -> bool:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE dashboard_users SET no_tester_enabled = %s WHERE id = %s",
            (enabled, user_id),
        )
        return cur.rowcount > 0


def _normalize_status_filter(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = value.strip().lower()
    return normalized if normalized in ACCOUNT_STATUS_CHOICES else None


def fetch_aska_users(source: str, status: Optional[str], search: Optional[str], *, limit: int = 200) -> List[Dict[str, Any]]:
    """Gabungkan daftar user web & Telegram sesuai filter."""
    normalized_source = (source or "web").strip().lower()
    normalized_status = _normalize_status_filter(status)
    normalized_search = (search or "").strip()

    rows: List[Dict[str, Any]] = []
    fetch_web = normalized_source in {"web", "all"}
    fetch_telegram = normalized_source in {"telegram", "all"}

    if fetch_web:
        conditions: List[str] = []
        params: List[Any] = []
        if normalized_status:
            conditions.append("status = %s")
            params.append(normalized_status)
        if normalized_search:
            conditions.append("(email ILIKE %s OR full_name ILIKE %s)")
            term = f"%{normalized_search}%"
            params.extend([term, term])
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            SELECT
                id,
                full_name,
                email,
                access_tier,
                last_login,
                created_at,
                status,
                status_reason,
                status_changed_at,
                status_changed_by
            FROM web_users
            {where_clause}
            ORDER BY COALESCE(last_login, created_at) DESC
            LIMIT %s
        """
        params.append(limit)
        with get_cursor() as cur:
            cur.execute(query, params)
            for row in cur.fetchall():
                rows.append(
                    {
                        "channel": "web",
                        "id": row["id"],
                        "display_name": row["full_name"],
                        "identifier": row["email"],
                        "status": row["status"],
                        "status_reason": row["status_reason"],
                        "status_changed_at": row["status_changed_at"],
                        "status_changed_by": row["status_changed_by"],
                        "last_activity": row["last_login"] or row["created_at"],
                        "created_at": row["created_at"],
                        "extra": {"access_tier": row["access_tier"]},
                    }
                )

    if fetch_telegram:
        conditions = []
        params = []
        if normalized_status:
            conditions.append("status = %s")
            params.append(normalized_status)
        if normalized_search:
            conditions.append("(username ILIKE %s OR CAST(telegram_user_id AS TEXT) ILIKE %s)")
            term = f"%{normalized_search}%"
            params.extend([term, term])
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            SELECT
                telegram_user_id,
                username,
                first_seen_at,
                last_seen_at,
                status,
                status_reason,
                status_changed_at,
                status_changed_by,
                last_message_preview
            FROM telegram_users
            {where_clause}
            ORDER BY COALESCE(last_seen_at, first_seen_at) DESC
            LIMIT %s
        """
        params.append(limit)
        with get_cursor() as cur:
            cur.execute(query, params)
            for row in cur.fetchall():
                rows.append(
                    {
                        "channel": "telegram",
                        "id": row["telegram_user_id"],
                        "display_name": row["username"] or f"ID {row['telegram_user_id']}",
                        "identifier": f"@{row['username']}" if row["username"] else row["telegram_user_id"],
                        "status": row["status"],
                        "status_reason": row["status_reason"],
                        "status_changed_at": row["status_changed_at"],
                        "status_changed_by": row["status_changed_by"],
                        "last_activity": row["last_seen_at"] or row["first_seen_at"],
                        "created_at": row["first_seen_at"],
                        "extra": {"last_message_preview": row["last_message_preview"]},
                    }
                )

    rows.sort(key=lambda item: item.get("last_activity") or item.get("created_at") or datetime.min, reverse=True)
    return rows[:limit]


def summarize_aska_users() -> Dict[str, Dict[str, int]]:
    """Hitung total user per status untuk web dan Telegram."""
    summary = {
        "web": {status: 0 for status in ACCOUNT_STATUS_CHOICES},
        "telegram": {status: 0 for status in ACCOUNT_STATUS_CHOICES},
    }
    with get_cursor() as cur:
        cur.execute("SELECT status, COUNT(*) FROM web_users GROUP BY status")
        for status, total in cur.fetchall():
            summary["web"][status] = int(total)
        cur.execute("SELECT status, COUNT(*) FROM telegram_users GROUP BY status")
        for status, total in cur.fetchall():
            summary["telegram"][status] = int(total)
    for scope in summary.values():
        scope["total"] = sum(scope.get(status, 0) for status in ACCOUNT_STATUS_CHOICES)
    summary["combined"] = {
        status: summary["web"].get(status, 0) + summary["telegram"].get(status, 0)
        for status in ACCOUNT_STATUS_CHOICES
    }
    summary["combined"]["total"] = summary["web"].get("total", 0) + summary["telegram"].get("total", 0)
    return summary


def update_web_user_status(user_id: int, status: str, reason: Optional[str], *, changed_by: str) -> bool:
    normalized = _normalize_status_filter(status)
    if normalized is None:
        raise ValueError("Status tidak valid.")
    cleaned_reason = (reason or "").strip() or None
    if cleaned_reason:
        cleaned_reason = cleaned_reason[:500]
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE web_users
            SET status = %s,
                status_reason = %s,
                status_changed_at = NOW(),
                status_changed_by = %s
            WHERE id = %s
            """,
            (normalized, cleaned_reason, changed_by, user_id),
        )
        return cur.rowcount > 0


def update_telegram_user_status(user_id: int, status: str, reason: Optional[str], *, changed_by: str) -> bool:
    normalized = _normalize_status_filter(status)
    if normalized is None:
        raise ValueError("Status tidak valid.")
    cleaned_reason = (reason or "").strip() or None
    if cleaned_reason:
        cleaned_reason = cleaned_reason[:500]
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE telegram_users
            SET status = %s,
                status_reason = %s,
                status_changed_at = NOW(),
                status_changed_by = %s
            WHERE telegram_user_id = %s
            """,
            (normalized, cleaned_reason, changed_by, user_id),
        )
        return cur.rowcount > 0


# --- Latihan TKA helpers ----------------------------------------------------


def _slugify_subject(cur, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "mapel"
    candidate = base
    suffix = 2
    while True:
        cur.execute("SELECT 1 FROM tka_subjects WHERE slug = %s LIMIT 1", (candidate,))
        if not cur.fetchone():
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


def fetch_tka_subjects(include_inactive: bool = True) -> List[Dict[str, Any]]:
    """Ambil daftar mapel Latihan TKA."""
    query = """
        SELECT id, slug, name, description, question_count, time_limit_minutes,
               difficulty_mix, difficulty_presets, default_preset, grade_level,
               is_active, created_at, updated_at, metadata
        FROM tka_subjects
    """
    params: List[Any] = []
    clauses: List[str] = []
    if not include_inactive:
        clauses.append("is_active = TRUE")
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY name ASC"
    subjects: List[Dict[str, Any]] = []
    with get_cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
        for row in rows:
            subject = dict(row)
            presets = _prepare_presets_payload(subject.get("difficulty_presets"))
            subject["difficulty_presets"] = presets
            subject["default_preset"] = _normalize_preset_name_local(subject.get("default_preset"))
            subject["difficulty_mix"] = _coerce_mix_local(subject.get("difficulty_mix"), presets.get(subject["default_preset"]))
            subject["active_mix"] = subject["difficulty_mix"]
            subject["grade_level"] = (subject.get("grade_level") or DEFAULT_GRADE_LEVEL).strip().lower()
            metadata = subject.get("metadata") if isinstance(subject.get("metadata"), dict) else {}
            subject["metadata"] = metadata or {}
            section_config = _normalize_section_config_local(metadata)
            if section_config:
                section_mix = _aggregate_section_mix_local(section_config.get("sections") or [])
                subject["advanced_config"] = section_config
                subject["difficulty_mix"] = section_mix
                subject["active_mix"] = section_mix
                subject["difficulty_presets"][subject["default_preset"]] = section_mix
                subject["question_count"] = sum(section.get("question_count", 0) for section in section_config.get("sections") or [])
                subject["time_limit_minutes"] = section_config.get("duration_minutes", subject.get("time_limit_minutes") or DEFAULT_TKA_COMPOSITE_DURATION)
            subjects.append(subject)
    return subjects


def fetch_tka_subject(subject_id: int) -> Optional[Dict[str, Any]]:
    if not subject_id:
        return None
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, slug, name, description, question_count, time_limit_minutes,
                   difficulty_mix, difficulty_presets, default_preset, grade_level,
                   is_active, metadata
            FROM tka_subjects
            WHERE id = %s
            """,
            (subject_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        subject = dict(row)
        presets = _prepare_presets_payload(subject.get("difficulty_presets"))
        subject["difficulty_presets"] = presets
        subject["default_preset"] = _normalize_preset_name_local(subject.get("default_preset"))
        subject["difficulty_mix"] = _coerce_mix_local(subject.get("difficulty_mix"), presets.get(subject["default_preset"]))
        subject["active_mix"] = subject["difficulty_mix"]
        subject["grade_level"] = (subject.get("grade_level") or DEFAULT_GRADE_LEVEL).strip().lower()
        metadata = subject.get("metadata") if isinstance(subject.get("metadata"), dict) else {}
        subject["metadata"] = metadata or {}
        section_config = _normalize_section_config_local(metadata)
        if section_config:
            section_mix = _aggregate_section_mix_local(section_config.get("sections") or [])
            subject["advanced_config"] = section_config
            subject["difficulty_mix"] = section_mix
            subject["active_mix"] = section_mix
            subject["difficulty_presets"][subject["default_preset"]] = section_mix
            subject["question_count"] = sum(section.get("question_count", 0) for section in section_config.get("sections") or [])
            subject["time_limit_minutes"] = section_config.get("duration_minutes", subject.get("time_limit_minutes") or DEFAULT_TKA_COMPOSITE_DURATION)
        return subject


def update_tka_subject_sections(
    subject_id: int,
    *,
    duration_minutes: int,
    sections: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    if not subject_id:
        raise ValueError("subject_id wajib diisi.")
    try:
        duration_value = int(duration_minutes)
    except (TypeError, ValueError):
        duration_value = DEFAULT_TKA_COMPOSITE_DURATION
    duration_value = max(30, duration_value)
    payload_metadata = {
        TKA_METADATA_SECTION_CONFIG_KEY: {
            "duration_minutes": duration_value,
            "sections": sections or [],
        }
    }
    normalized = _normalize_section_config_local(payload_metadata)
    normalized_sections = normalized.get("sections") or []
    normalized_duration = normalized.get("duration_minutes", duration_value)
    aggregated_mix = _aggregate_section_mix_local(normalized_sections)
    total_questions = sum(section.get("question_count", 0) for section in normalized_sections)
    metadata_payload: Dict[str, Any]
    with get_cursor() as cur:
        cur.execute("SELECT metadata FROM tka_subjects WHERE id = %s", (subject_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError("Mapel belum tersedia.")
        metadata_value = dict(row[0] or {})
        metadata_value[TKA_METADATA_SECTION_CONFIG_KEY] = normalized
        metadata_payload = metadata_value
    preset_payload = {DEFAULT_TKA_PRESET_KEY: aggregated_mix}
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE tka_subjects
            SET metadata = %s,
                question_count = %s,
                time_limit_minutes = %s,
                difficulty_mix = %s,
                difficulty_presets = %s,
                default_preset = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING id
            """,
            (
                Json(metadata_payload),
                total_questions,
                normalized_duration,
                Json(aggregated_mix),
                Json(preset_payload),
                DEFAULT_TKA_PRESET_KEY,
                subject_id,
            ),
        )
        if not cur.fetchone():
            raise ValueError("Mapel belum tersedia.")
    return fetch_tka_subject(subject_id)


# --- TKA Tests (tes berisi mapel + topik + format) --------------------------


def fetch_tka_tests() -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, name, grade_level, duration_minutes, is_active, created_at, updated_at
            FROM tka_tests
            ORDER BY created_at DESC
            """
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows or []]


def fetch_tka_test(test_id: int) -> Optional[Dict[str, Any]]:
    if not test_id:
        return None
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, name, grade_level, duration_minutes, is_active, created_at, updated_at
            FROM tka_tests
            WHERE id = %s
            """,
            (test_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def create_tka_test(name: str, grade_level: str, duration_minutes: int, is_active: bool = True) -> Dict[str, Any]:
    if not name:
        raise ValueError("Nama tes wajib diisi.")
    grade: Optional[str]
    if grade_level:
        normalized = str(grade_level).strip().lower()
        grade = normalized if normalized in VALID_GRADE_LEVELS else None
    else:
        grade = None
    try:
        duration = max(30, int(duration_minutes))
    except (TypeError, ValueError):
        duration = DEFAULT_TKA_COMPOSITE_DURATION
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO tka_tests (name, grade_level, duration_minutes, is_active)
            VALUES (%s,%s,%s,%s)
            RETURNING id, name, grade_level, duration_minutes, is_active, created_at, updated_at
            """,
            (name.strip(), grade, duration, bool(is_active)),
        )
        row = cur.fetchone()
    return dict(row) if row else {}


def set_tka_test_grade_level(test_id: int, grade_level: Optional[str]) -> Optional[Dict[str, Any]]:
    if not test_id or not grade_level:
        return None
    grade = str(grade_level).strip().lower()
    if grade not in VALID_GRADE_LEVELS:
        return None
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE tka_tests
            SET grade_level = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING id, name, grade_level, duration_minutes, is_active, created_at, updated_at
            """,
            (grade, test_id),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def fetch_tka_test_subject_formats(test_subject_id: int) -> List[Dict[str, Any]]:
    if not test_subject_id:
        return []
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, question_type, question_count_target
            FROM tka_test_question_formats
            WHERE test_subject_id = %s
            ORDER BY id ASC
            """,
            (test_subject_id,),
        )
        return [dict(row) for row in cur.fetchall() or []]


def fetch_tka_test_subject_topics(test_subject_id: int) -> List[Dict[str, Any]]:
    if not test_subject_id:
        return []
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT tt.id,
                   tt.topic,
                   tt.question_count_target,
                   tt.order_index,
                   COALESCE(qt.total_questions, 0) AS question_count_actual
            FROM tka_test_topics tt
            JOIN tka_test_subjects tts ON tts.id = tt.test_subject_id
            LEFT JOIN (
                SELECT
                    test_subject_id,
                    mapel_id,
                    LOWER(COALESCE(topic, '')) AS topic_key,
                    COUNT(*) AS total_questions
                FROM tka_questions
                GROUP BY test_subject_id, mapel_id, LOWER(COALESCE(topic, ''))
            ) qt ON (
                (qt.test_subject_id IS NOT NULL AND qt.test_subject_id = tt.test_subject_id)
                OR (qt.test_subject_id IS NULL AND qt.mapel_id = tts.mapel_id)
            )
            AND qt.topic_key = LOWER(COALESCE(tt.topic, ''))
            WHERE tt.test_subject_id = %s
            ORDER BY tt.order_index ASC, tt.id ASC
            """,
            (test_subject_id,),
        )
        return [dict(row) for row in cur.fetchall() or []]


def fetch_tka_test_subjects(test_id: int) -> List[Dict[str, Any]]:
    if not test_id:
        return []
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT ts.id,
                   ts.test_id,
                   ts.mapel_id,
                   mp.name AS mapel_name,
                   mp.grade_level AS mapel_grade_level,
                   ts.question_count_target,
                   ts.order_index,
                   COALESCE(qs.total_questions, 0) AS question_count_actual,
                   COALESCE(qs.total_pg, 0) AS question_count_pg_actual,
                   COALESCE(qs.total_tf, 0) AS question_count_tf_actual
            FROM tka_test_subjects ts
            LEFT JOIN tka_mata_pelajaran mp ON mp.id = ts.mapel_id
            LEFT JOIN (
                SELECT
                    test_subject_id,
                    mapel_id,
                    COUNT(*) AS total_questions,
                    SUM(CASE WHEN answer_format = 'true_false' THEN 1 ELSE 0 END) AS total_tf,
                    SUM(CASE WHEN answer_format <> 'true_false' OR answer_format IS NULL THEN 1 ELSE 0 END) AS total_pg
                FROM tka_questions
                GROUP BY test_subject_id, mapel_id
            ) qs ON (
                (qs.test_subject_id IS NOT NULL AND qs.test_subject_id = ts.id)
                OR (qs.test_subject_id IS NULL AND qs.mapel_id = ts.mapel_id)
            )
            WHERE ts.test_id = %s
            ORDER BY ts.order_index ASC, ts.id ASC
            """,
            (test_id,),
        )
        subjects = [dict(row) for row in cur.fetchall() or []]
    for item in subjects:
        item["subject_name"] = item.get("mapel_name")
        item["grade_level"] = item.get("mapel_grade_level") or item.get("grade_level")
        item["subject_id"] = item.get("subject_id") or item.get("mapel_id")
        item["formats"] = fetch_tka_test_subject_formats(item["id"])
        item["topics"] = fetch_tka_test_subject_topics(item["id"])
        item["question_count_actual"] = item.get("question_count_actual") or item.get("total_questions") or 0
        item["question_count_pg_actual"] = item.get("question_count_pg_actual") or item.get("total_pg") or 0
        item["question_count_tf_actual"] = item.get("question_count_tf_actual") or item.get("total_tf") or 0
    return subjects


def fetch_tka_test_subject(test_subject_id: int) -> Optional[Dict[str, Any]]:
    if not test_subject_id:
        return None
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT ts.id,
                   ts.test_id,
                   ts.mapel_id,
                   mp.name AS mapel_name,
                   mp.grade_level AS mapel_grade_level,
                   ts.question_count_target,
                   ts.order_index,
                   COALESCE(qs.total_questions, 0) AS question_count_actual,
                   COALESCE(qs.total_pg, 0) AS question_count_pg_actual,
                   COALESCE(qs.total_tf, 0) AS question_count_tf_actual
            FROM tka_test_subjects ts
            LEFT JOIN tka_mata_pelajaran mp ON mp.id = ts.mapel_id
            LEFT JOIN (
                SELECT
                    test_subject_id,
                    mapel_id,
                    COUNT(*) AS total_questions,
                    SUM(CASE WHEN answer_format = 'true_false' THEN 1 ELSE 0 END) AS total_tf,
                    SUM(CASE WHEN answer_format <> 'true_false' OR answer_format IS NULL THEN 1 ELSE 0 END) AS total_pg
                FROM tka_questions
                GROUP BY test_subject_id, mapel_id
            ) qs ON (
                (qs.test_subject_id IS NOT NULL AND qs.test_subject_id = ts.id)
                OR (qs.test_subject_id IS NULL AND qs.mapel_id = ts.mapel_id)
            )
            WHERE ts.id = %s
            """,
            (test_subject_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        subject = dict(row)
        subject["subject_id"] = subject.get("subject_id") or subject.get("mapel_id")
        subject["subject_name"] = subject.get("mapel_name")
        subject["grade_level"] = subject.get("mapel_grade_level") or subject.get("grade_level")
        subject["formats"] = fetch_tka_test_subject_formats(subject["id"])
        subject["topics"] = fetch_tka_test_subject_topics(subject["id"])
        subject["question_count_actual"] = subject.get("question_count_actual") or subject.get("total_questions") or 0
        subject["question_count_pg_actual"] = subject.get("total_pg") or 0
        subject["question_count_tf_actual"] = subject.get("total_tf") or 0
        return subject


def create_tka_test_subject(
    test_id: int,
    total: int,
    *,
    mapel_id: Optional[int] = None,
    formats: Optional[List[Dict[str, Any]]] = None,
    topics: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not test_id:
        raise ValueError("test_id wajib diisi.")
    if not mapel_id:
        raise ValueError("mapel_id wajib diisi.")
    try:
        total_questions = max(1, int(total))
    except (TypeError, ValueError):
        total_questions = 1
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO tka_test_subjects (test_id, mapel_id, question_count_target, order_index)
            VALUES (%s,%s,%s, COALESCE((SELECT COALESCE(MAX(order_index),0)+1 FROM tka_test_subjects WHERE test_id=%s),1))
            RETURNING id, test_id, mapel_id, question_count_target, order_index
            """,
            (test_id, mapel_id, total_questions, test_id),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("Gagal menyimpan mapel tes.")
        ts_id = row["id"]
        # Simpan formats
        if formats:
            for fmt in formats:
                qtype = (fmt.get("question_type") or "").strip().lower()
                if qtype not in VALID_TEST_FORMATS:
                    continue
                try:
                    qc = max(0, int(fmt.get("question_count_target") or 0))
                except (TypeError, ValueError):
                    qc = 0
                cur.execute(
                    """
                    INSERT INTO tka_test_question_formats (test_subject_id, question_type, question_count_target)
                    VALUES (%s,%s,%s)
                    """,
                    (ts_id, qtype, qc),
                )
        # Simpan topics
        order_idx = 1
        for topic in topics or []:
            name = (topic.get("name") or topic.get("topic") or "").strip()
            if not name:
                continue
            try:
                qc = max(0, int(topic.get("count") or topic.get("question_count_target") or 0))
            except (TypeError, ValueError):
                qc = 0
            cur.execute(
                """
                INSERT INTO tka_test_topics (test_subject_id, topic, question_count_target, order_index)
                VALUES (%s,%s,%s,%s)
                """,
                (ts_id, name, qc, order_idx),
            )
            order_idx += 1
    return dict(row) if row else {}


def delete_tka_test_subject(test_id: int, test_subject_id: int) -> bool:
    if not test_id or not test_subject_id:
        return False
    with get_cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM tka_test_subjects WHERE id = %s AND test_id = %s",
            (test_subject_id, test_id),
        )
        return cur.rowcount > 0


def delete_tka_test(test_id: int) -> bool:
    if not test_id:
        return False
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM tka_tests WHERE id = %s", (test_id,))
        return cur.rowcount > 0


def update_tka_test_subject_topics(test_subject_id: int, topics: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    if not test_subject_id:
        raise ValueError("test_subject_id wajib diisi.")
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM tka_test_topics WHERE test_subject_id = %s", (test_subject_id,))
        order_idx = 1
        for topic in topics or []:
            name = (topic.get("name") or topic.get("topic") or "").strip()
            if not name:
                continue
            try:
                count_value = max(0, int(topic.get("count") or topic.get("question_count_target") or topic.get("question_count") or 0))
            except (TypeError, ValueError):
                count_value = 0
            cur.execute(
                """
                INSERT INTO tka_test_topics (test_subject_id, topic, question_count_target, order_index)
                VALUES (%s,%s,%s,%s)
                """,
                (test_subject_id, name, count_value, order_idx),
            )
            order_idx += 1
    updated = fetch_tka_test_subject(test_subject_id)
    if not updated:
        raise ValueError("Mapel tes tidak ditemukan.")
    return updated


def fetch_tka_mapel_formats(mapel_id: int) -> List[Dict[str, Any]]:
    if not mapel_id:
        return []
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, mapel_id, question_type, question_count
            FROM tka_mapel_formats
            WHERE mapel_id = %s
            ORDER BY question_type
            """,
            (mapel_id,),
        )
        return [dict(row) for row in cur.fetchall() or []]


def fetch_tka_mapel_topics(mapel_id: int) -> List[Dict[str, Any]]:
    if not mapel_id:
        return []
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, mapel_id, topic, question_count, order_index
            FROM tka_mapel_topics
            WHERE mapel_id = %s
            ORDER BY order_index ASC, id ASC
            """,
            (mapel_id,),
        )
        return [dict(row) for row in cur.fetchall() or []]


def fetch_tka_mapel(mapel_id: int) -> Optional[Dict[str, Any]]:
    if not mapel_id:
        return None
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, name, grade_level, description, is_active, created_at, updated_at
            FROM tka_mata_pelajaran
            WHERE id = %s
            """,
            (mapel_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    record = dict(row)
    record["formats"] = fetch_tka_mapel_formats(record["id"])
    record["topics"] = fetch_tka_mapel_topics(record["id"])
    return record


def fetch_tka_mapel_list(include_inactive: bool = True) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    if not include_inactive:
        clauses.append("is_active = TRUE")
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, name, grade_level, description, is_active, created_at, updated_at
            FROM tka_mata_pelajaran
            {where_clause}
            ORDER BY name ASC
            """
        )
        rows = cur.fetchall() or []
    result: List[Dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        record["formats"] = fetch_tka_mapel_formats(record["id"])
        record["topics"] = fetch_tka_mapel_topics(record["id"])
        result.append(record)
    return result


def create_tka_mapel(
    name: str,
    grade_level: str,
    *,
    description: Optional[str] = None,
    is_active: bool = True,
    formats: Optional[List[Dict[str, Any]]] = None,
    topics: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not name:
        raise ValueError("Nama mapel wajib diisi.")
    grade = (grade_level or DEFAULT_GRADE_LEVEL).strip().lower()
    if grade not in VALID_GRADE_LEVELS:
        grade = DEFAULT_GRADE_LEVEL
    formats_payload = formats or [
        {"question_type": "multiple_choice", "question_count": 0},
        {"question_type": "true_false", "question_count": 0},
    ]
    normalized_description = (description or "").strip() or None
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO tka_mata_pelajaran (name, grade_level, description, is_active)
            VALUES (%s,%s,%s,%s)
            RETURNING id, name, grade_level, description, is_active, created_at, updated_at
            """,
            (name.strip(), grade, normalized_description, bool(is_active)),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("Gagal menyimpan mapel.")
        mapel_id = row["id"]
        for entry in formats_payload:
            qtype = (entry.get("question_type") or "").strip().lower()
            if qtype not in {"multiple_choice", "true_false"}:
                continue
            try:
                count_value = max(0, int(entry.get("question_count")))
            except (TypeError, ValueError):
                count_value = 0
            cur.execute(
                """
                INSERT INTO tka_mapel_formats (mapel_id, question_type, question_count)
                VALUES (%s,%s,%s)
                """,
                (mapel_id, qtype, count_value),
            )
        order_idx = 1
        for topic in topics or []:
            topic_name = (topic.get("topic") or topic.get("name") or "").strip()
            if not topic_name:
                continue
            try:
                count_value = max(0, int(topic.get("question_count") or topic.get("count") or 0))
            except (TypeError, ValueError):
                count_value = 0
            cur.execute(
                """
                INSERT INTO tka_mapel_topics (mapel_id, topic, question_count, order_index)
                VALUES (%s,%s,%s,%s)
                """,
                (mapel_id, topic_name, count_value, order_idx),
            )
            order_idx += 1
    record = dict(row)
    record["formats"] = fetch_tka_mapel_formats(mapel_id)
    record["topics"] = fetch_tka_mapel_topics(mapel_id)
    return record


def ensure_tka_subject_from_mapel(mapel_id: int) -> Optional[int]:
    if not mapel_id:
        return None
    mapel = fetch_tka_mapel(mapel_id)
    if not mapel:
        return None
    with get_cursor(commit=True) as cur:
        cur.execute(
            "SELECT id FROM tka_subjects WHERE metadata->>'mapel_id' = %s LIMIT 1",
            (str(mapel_id),),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        slug = _slugify_subject(cur, mapel["name"])
        metadata_payload = {"mapel_id": mapel_id}
        cur.execute(
            """
            INSERT INTO tka_subjects (slug, name, description, grade_level, is_active, metadata, created_at, updated_at)
            VALUES (%s,%s,%s,%s,TRUE,%s,NOW(),NOW())
            RETURNING id
            """,
            (
                slug,
                mapel["name"],
                mapel.get("description"),
                (mapel.get("grade_level") or DEFAULT_TKA_GRADE_LEVEL).strip().lower(),
                Json(metadata_payload),
            ),
        )
        new_id = cur.fetchone()[0]
        return new_id


def delete_tka_mapel(mapel_id: int) -> bool:
    if not mapel_id:
        return False
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM tka_mata_pelajaran WHERE id = %s", (mapel_id,))
        return cur.rowcount > 0


def create_tka_subject(
    name: str,
    description: Optional[str],
    *,
    time_limit_minutes: int = 15,
    difficulty_mix: Optional[Dict[str, int]] = None,
    is_active: bool = True,
    grade_level: Optional[str] = None,
) -> Dict[str, Any]:
    if not name:
        raise ValueError("Nama mapel wajib diisi.")
    mix = _coerce_mix_local(difficulty_mix, DEFAULT_TKA_PRESETS.get(DEFAULT_TKA_PRESET_KEY))
    total_questions = max(1, sum(mix.values()))
    normalized_description = (description or "").strip() or None
    presets_payload = _default_presets_payload_local()
    default_preset = DEFAULT_TKA_PRESET_KEY
    if mix != presets_payload.get(DEFAULT_TKA_PRESET_KEY):
        presets_payload["custom"] = mix
        default_preset = "custom"
    else:
        presets_payload[DEFAULT_TKA_PRESET_KEY] = mix
    normalized_grade = (grade_level or DEFAULT_GRADE_LEVEL).strip().lower()
    if normalized_grade not in VALID_GRADE_LEVELS:
        normalized_grade = DEFAULT_GRADE_LEVEL
    with get_cursor(commit=True) as cur:
        slug = _slugify_subject(cur, name)
        cur.execute(
            """
            INSERT INTO tka_subjects (
                slug, name, description, question_count,
                time_limit_minutes, difficulty_mix, difficulty_presets,
                default_preset, grade_level, is_active
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                slug,
                name.strip(),
                normalized_description,
                total_questions,
                max(5, time_limit_minutes or 15),
                Json(mix),
                Json(presets_payload),
                default_preset,
                normalized_grade,
                bool(is_active),
            ),
        )
        row = cur.fetchone()
        subject = dict(row) if row else {}
    if subject:
        subject["difficulty_presets"] = _prepare_presets_payload(subject.get("difficulty_presets"))
        subject["default_preset"] = _normalize_preset_name_local(subject.get("default_preset"))
        subject["difficulty_mix"] = _coerce_mix_local(subject.get("difficulty_mix"), subject["difficulty_presets"].get(subject["default_preset"]))
    return subject


def update_tka_subject_difficulty(
    subject_id: int,
    preset: str,
    *,
    custom_mix: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    normalized = _normalize_preset_name_local(preset)
    with get_cursor(commit=True) as cur:
        cur.execute(
            "SELECT difficulty_presets, difficulty_mix, default_preset FROM tka_subjects WHERE id = %s",
            (subject_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        presets = _prepare_presets_payload(row["difficulty_presets"])
        if custom_mix and normalized == "custom":
            presets["custom"] = _coerce_mix_local(custom_mix)
        elif normalized not in presets:
            normalized = DEFAULT_TKA_PRESET_KEY
        selected_mix = presets.get(normalized) or presets.get(DEFAULT_TKA_PRESET_KEY)
        if not selected_mix:
            selected_mix = _coerce_mix_local(None)
        cur.execute(
            """
            UPDATE tka_subjects
            SET difficulty_mix = %s,
                difficulty_presets = %s,
                default_preset = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (
                Json(selected_mix),
                Json(presets),
                normalized,
                subject_id,
            ),
        )
        updated = cur.fetchone()
    if not updated:
        return None
    subject = dict(updated)
    subject["difficulty_presets"] = _prepare_presets_payload(subject.get("difficulty_presets"))
    subject["default_preset"] = _normalize_preset_name_local(subject.get("default_preset"))
    subject["difficulty_mix"] = _coerce_mix_local(subject.get("difficulty_mix"), subject["difficulty_presets"].get(subject["default_preset"]))
    subject["active_mix"] = subject["difficulty_mix"]
    return subject


def _normalize_options_for_insert(options: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    fallback = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for idx, option in enumerate(options or []):
        if isinstance(option, dict):
            raw_key = option.get("key") or option.get("label") or option.get("value")
            text = option.get("text") or option.get("label") or option.get("value") or ""
        else:
            raw_key = None
            text = str(option)
        base_key = raw_key or (fallback[idx] if idx < len(fallback) else f"OPS{idx+1}")
        normalized.append(
            {
                "key": str(base_key).strip().upper(),
                "text": text.strip(),
            }
        )
    if len(normalized) < 2:
        raise ValueError("Minimal butuh 2 opsi jawaban.")
    return normalized[:6]


def fetch_tka_questions(
    subject_id: Optional[int] = None,
    *,
    question_id: Optional[int] = None,
    test_subject_id: Optional[int] = None,
    test_id: Optional[int] = None,
    mapel_id: Optional[int] = None,
    difficulty: Optional[str] = None,
    topic: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    if not subject_id and not test_subject_id and not mapel_id and not test_id and not question_id:
        return []
    clauses = []
    params: List[Any] = []
    if question_id:
        clauses.append("q.id = %s")
        params.append(question_id)
    if subject_id:
        clauses.append("q.subject_id = %s")
        params.append(subject_id)
    if test_subject_id:
        clauses.append("q.test_subject_id = %s")
        params.append(test_subject_id)
    if test_id:
        clauses.append("q.test_id = %s")
        params.append(test_id)
    if mapel_id:
        clauses.append("q.mapel_id = %s")
        params.append(mapel_id)
    if difficulty:
        clauses.append("q.difficulty = %s")
        params.append(difficulty)
    if topic:
        clauses.append("q.topic ILIKE %s")
        params.append(f"%{topic}%")
    where_clause = " AND ".join(clauses)
    with get_cursor() as cur:
        stim_table = _get_stimulus_table_name(cur)
        cur.execute(
            f"""
            SELECT
                q.id,
                q.subject_id,
                q.mapel_id,
                q.topic,
                q.difficulty,
                q.prompt,
                q.options,
                q.correct_key,
                q.explanation,
                q.source,
                q.ai_prompt,
                q.metadata,
                q.created_at,
                q.created_by,
                creator.full_name AS creator_name,
                creator.email AS creator_email,
                q.stimulus_id,
                s.title AS stimulus_title,
                s.type AS stimulus_type,
                s.narrative AS stimulus_narrative,
                s.image_url AS stimulus_image_url,
                s.image_prompt AS stimulus_image_prompt,
                q.answer_format,
                mp.name AS mapel_name
            FROM tka_questions q
            LEFT JOIN {stim_table} s ON s.id = q.stimulus_id
            LEFT JOIN dashboard_users creator ON creator.id = q.created_by
            LEFT JOIN tka_mata_pelajaran mp ON mp.id = q.mapel_id
            WHERE {where_clause}
            ORDER BY q.created_at DESC, q.id DESC
            LIMIT %s
            """,
            (*params, limit),
        )
        rows = []
        for row in cur.fetchall():
            record = dict(row)
            record["created_by_name"] = record.pop("creator_name", None)
            record["created_by_email"] = record.pop("creator_email", None)
            stimulus_id = record.pop("stimulus_id", None)
            if stimulus_id:
                record["stimulus"] = {
                    "id": stimulus_id,
                    "title": record.pop("stimulus_title", None),
                    "type": record.pop("stimulus_type", None),
                    "narrative": record.pop("stimulus_narrative", None),
                    "image_url": record.pop("stimulus_image_url", None),
                    "image_prompt": record.pop("stimulus_image_prompt", None),
                }
            else:
                record.pop("stimulus_title", None)
                record.pop("stimulus_type", None)
                record.pop("stimulus_narrative", None)
                record.pop("stimulus_image_url", None)
                record.pop("stimulus_image_prompt", None)
            rows.append(record)
        return rows


def fetch_tka_stimulus_list(mapel_id: Optional[int] = None, test_id: Optional[int] = None) -> List[Dict[str, Any]]:
    if not mapel_id and not test_id:
        return []
    with get_cursor() as cur:
        table_name = _get_stimulus_table_name(cur)
        conditions = []
        values: list[Any] = []
        if mapel_id:
            conditions.append("mapel_id = %s")
            values.append(mapel_id)
        if test_id:
            conditions.append("test_id = %s")
            values.append(test_id)
        where_clause = " AND ".join(conditions) if conditions else "TRUE"
        cur.execute(
            f"""
            SELECT id, subject_id, mapel_id, test_id, title, type, narrative, image_url, image_prompt, metadata, updated_at
            FROM {table_name}
            WHERE {where_clause}
            ORDER BY updated_at DESC, id DESC
            LIMIT 200
            """,
            tuple(values),
        )
        rows = []
        for row in cur.fetchall():
            record = dict(row)
            metadata = record.get("metadata")
            if isinstance(metadata, dict):
                record["metadata"] = metadata
            else:
                record["metadata"] = {}
            rows.append(record)
        return rows


def fetch_tka_stimulus(stimulus_id: int) -> Optional[Dict[str, Any]]:
    if not stimulus_id:
        return None
    with get_cursor() as cur:
        table_name = _get_stimulus_table_name(cur)
        cur.execute(
            f"""
            SELECT id, subject_id, title, type, narrative, image_url, image_prompt, metadata
            FROM {table_name}
            WHERE id = %s
            """,
            (stimulus_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    record = dict(row)
    metadata = record.get("metadata")
    record["metadata"] = metadata if isinstance(metadata, dict) else {}
    return record


def create_tka_stimulus(
    *,
    mapel_id: int,
    test_id: Optional[int] = None,
    subject_id: Optional[int] = None,
    title: str,
    narrative: Optional[str] = None,
    image_data: Optional[str] = None,
    image_prompt: Optional[str] = None,
    created_by: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not mapel_id:
        raise ValueError("mapel_id wajib diisi.")
    title = (title or "").strip()
    if not title:
        raise ValueError("Judul stimulus wajib diisi.")
    narrative_value = (narrative or "").strip() or None
    image_value = image_data or None
    stimulus_type = _determine_stimulus_type_local(bool(narrative_value), bool(image_value))
    normalized_metadata = metadata if isinstance(metadata, dict) else None
    with get_cursor(commit=True) as cur:
        table_name = _get_stimulus_table_name(cur)
        cur.execute(
            f"""
            INSERT INTO {table_name} (
                subject_id,
                mapel_id,
                test_id,
                title,
                type,
                narrative,
                image_url,
                image_prompt,
                metadata,
                created_by
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id, subject_id, mapel_id, test_id, title, type, narrative, image_url, image_prompt, metadata, updated_at
            """,
            (
                subject_id,
                mapel_id,
                test_id,
                title,
                stimulus_type,
                narrative_value,
                image_value,
                image_prompt or None,
                Json(normalized_metadata) if normalized_metadata else None,
                created_by,
            ),
        )
        row = cur.fetchone()
    if not row:
        raise ValueError("Stimulus gagal disimpan.")
    record = dict(row)
    meta_payload = record.get("metadata")
    if isinstance(meta_payload, dict):
        record["metadata"] = meta_payload
    else:
        record["metadata"] = {}
    return record


def update_tka_stimulus(
    stimulus_id: int,
    *,
    mapel_id: Optional[int] = None,
    test_id: Optional[int] = None,
    title: Optional[str] = None,
    narrative: Optional[str] = None,
    image_data: Optional[str] = None,
    image_prompt: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    if not stimulus_id:
        raise ValueError("stimulus_id wajib diisi.")
    fields: list[str] = []
    values: list[Any] = []
    if mapel_id is not None:
        fields.append("mapel_id = %s")
        values.append(mapel_id)
    if test_id is not None:
        fields.append("test_id = %s")
        values.append(test_id)
    if title is not None:
        fields.append("title = %s")
        values.append(title.strip())
    if narrative is not None:
        fields.append("narrative = %s")
        values.append(narrative.strip() or None)
    if image_data is not None:
        fields.append("image_url = %s")
        values.append(image_data or None)
    if image_prompt is not None:
        fields.append("image_prompt = %s")
        values.append(image_prompt.strip() or None)
    if metadata is not None:
        fields.append("metadata = %s")
        values.append(Json(metadata))
    if not fields:
        return None
    set_clause = ", ".join(fields) + ", updated_at = NOW()"
    values.append(stimulus_id)
    with get_cursor(commit=True) as cur:
        table_name = _get_stimulus_table_name(cur)
        cur.execute(
            f"""
            UPDATE {table_name}
            SET {set_clause}
            WHERE id = %s
            RETURNING id, subject_id, mapel_id, test_id, title, type, narrative, image_url, image_prompt, metadata, updated_at
            """,
            tuple(values),
        )
        row = cur.fetchone()
    if not row:
        return None
    record = dict(row)
    meta_payload = record.get("metadata")
    if isinstance(meta_payload, dict):
        record["metadata"] = meta_payload
    else:
        record["metadata"] = {}
    return record


def _get_stimulus_table_name(cur) -> str:
    """
    Deteksi tabel stimulus yang dipakai oleh FK tka_questions.stimulus_id.
    Setelah migrasi, hanya gunakan `tka_stimulus`.
    """
    return "tka_stimulus"


def delete_tka_stimulus(stimulus_id: int) -> bool:
    if not stimulus_id:
        return False
    with get_cursor(commit=True) as cur:
        table_name = _get_stimulus_table_name(cur)
        cur.execute(f"DELETE FROM {table_name} WHERE id = %s", (stimulus_id,))
        return cur.rowcount > 0


def create_tka_questions(
    subject_id: Optional[int],
    questions: Iterable[Dict[str, Any]],
    *,
    created_by: Optional[int] = None,
    test_id: Optional[int] = None,
    test_subject_id: Optional[int] = None,
    mapel_id: Optional[int] = None,
) -> int:
    subject_id = subject_id or None
    key_for_uniqueness = subject_id or mapel_id or test_subject_id
    if not key_for_uniqueness:
        raise ValueError("subject_id atau mapel_id atau test_subject_id wajib diisi.")

    question_records: List[Dict[str, Any]] = []
    for question in questions or []:
        prompt = (question.get("prompt") or "").strip()
        if not prompt:
            continue
        difficulty = (question.get("difficulty") or "easy").strip().lower()
        if difficulty not in {"easy", "medium", "hard"}:
            difficulty = "easy"
        options = _normalize_options_for_insert(question.get("options") or [])
        correct_key = (question.get("correct_key") or options[0]["key"]).strip().upper()
        if correct_key not in {opt["key"] for opt in options}:
            correct_key = options[0]["key"]
        metadata = question.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            metadata = None
        question_type = (
            question.get("answer_format")
            or question.get("question_type")
            or (metadata.get("question_type") if metadata else "")
        )
        question_type = (question_type or "").strip().lower()
        if question_type not in {"multiple_choice", "true_false"}:
            question_type = "multiple_choice"
        question_records.append(
            {
                "topic": (question.get("topic") or "").strip() or None,
                "difficulty": difficulty,
                "prompt": prompt,
                "options": options,
                "correct_key": correct_key,
                "explanation": (question.get("explanation") or "").strip() or None,
                "metadata": metadata,
                "source": (question.get("source") or "manual").strip(),
                "ai_prompt": question.get("ai_prompt"),
                "stimulus": question.get("stimulus"),
                "test_id": question.get("test_id") or test_id,
                "test_subject_id": question.get("test_subject_id") or test_subject_id,
                "mapel_id": question.get("mapel_id") or mapel_id,
                "answer_format": question_type,
            }
        )
    if not question_records:
        return 0
    with get_cursor(commit=True) as cur:
        stimulus_cache: Dict[str, int] = {}
        inserted = 0
        for record in question_records:
            resolved_subject_id = subject_id or None
            if not resolved_subject_id and record.get("mapel_id"):
                try:
                    resolved_subject_id = ensure_tka_subject_from_mapel(record.get("mapel_id"))
                except Exception:
                    resolved_subject_id = None
            stimulus_id = _resolve_question_stimulus(
                cur,
                resolved_subject_id,
                record.get("stimulus"),
                created_by,
                stimulus_cache,
            )
            # subject_id disimpan NULL; resolved_subject_id hanya untuk kebutuhan stimulus/dedup
            cur.execute(
                """
                INSERT INTO tka_questions (
                    subject_id,
                    mapel_id,
                    test_id,
                    test_subject_id,
                    stimulus_id,
                    topic,
                    difficulty,
                    prompt,
                    options,
                    correct_key,
                    explanation,
                    created_by,
                    source,
                    metadata,
                    ai_prompt,
                    answer_format
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    None,
                    record.get("mapel_id"),
                    record.get("test_id"),
                    record.get("test_subject_id"),
                    stimulus_id,
                    record["topic"],
                    record["difficulty"],
                    record["prompt"],
                    Json(record["options"]),
                    record["correct_key"],
                    record["explanation"],
                    created_by,
                    record["source"],
                    Json(record["metadata"]) if record["metadata"] else None,
                    record["ai_prompt"],
                    record.get("answer_format") or "multiple_choice",
                ),
            )
            inserted += cur.rowcount or 0
        if subject_id:
            cur.execute(
                """
                UPDATE tka_subjects
                SET question_revision = question_revision + 1,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (subject_id,),
            )
    return inserted


def has_tka_question_with_prompt(subject_id: Optional[int], prompt: str, *, test_subject_id: Optional[int] = None) -> bool:
    if (not subject_id and not test_subject_id) or not prompt:
        return False
    normalized = prompt.strip().lower()
    if not normalized:
        return False
    clauses: List[str] = []
    params: List[Any] = [normalized]
    if subject_id:
        clauses.append("subject_id = %s")
        params.append(subject_id)
    if test_subject_id:
        clauses.append("test_subject_id = %s")
        params.append(test_subject_id)
    if not clauses:
        return False
    with get_cursor() as cur:
        where_clause = " AND ".join(clauses)
        query = f"""
            SELECT 1
            FROM tka_questions
            WHERE LOWER(TRIM(prompt)) = %s
              AND {where_clause}
            LIMIT 1
        """
        cur.execute(query, tuple(params))
        return cur.fetchone() is not None


def delete_tka_question(question_id: int) -> bool:
    if not question_id:
        return False
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM tka_questions WHERE id = %s", (question_id,))
        return cur.rowcount > 0


def update_tka_question(question_id: int, payload: Dict[str, Any]) -> bool:
    if not question_id:
        return False
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("Teks soal wajib diisi.")
    topic = (payload.get("topic") or "").strip() or None
    difficulty = (payload.get("difficulty") or "easy").strip().lower()
    if difficulty not in {"easy", "medium", "hard"}:
        difficulty = "easy"
    options = _normalize_options_for_insert(payload.get("options") or [])
    correct_key = (payload.get("correct_key") or options[0]["key"]).strip().upper()
    if correct_key not in {opt["key"] for opt in options}:
        correct_key = options[0]["key"]
    explanation = (payload.get("explanation") or "").strip() or None
    stimulus_payload = payload.get("stimulus")

    with get_cursor(commit=True) as cur:
        cur.execute("SELECT subject_id, metadata, stimulus_id FROM tka_questions WHERE id = %s", (question_id,))
        row = cur.fetchone()
        if not row:
            return False
        subject_id = row[0]
        existing_metadata = dict(row[1] or {})
        current_stimulus_id = row[2]
        metadata_payload = payload.get("metadata")
        if metadata_payload is not None:
            if not isinstance(metadata_payload, dict):
                raise ValueError("Metadata harus berupa objek.")
            existing_metadata.update({k: v for k, v in metadata_payload.items() if v is not None})
        stimulus_specified = "stimulus" in payload
        stimulus_payload = payload.get("stimulus")
        stimulus_id = current_stimulus_id
        if stimulus_specified:
            if stimulus_payload is None:
                stimulus_id = None
            else:
                stimulus_cache: Dict[str, int] = {}
                stimulus_id = _resolve_question_stimulus(cur, subject_id, stimulus_payload, None, stimulus_cache)
        cur.execute(
            """
            UPDATE tka_questions
            SET prompt = %s,
                topic = %s,
                difficulty = %s,
                options = %s,
                correct_key = %s,
                explanation = %s,
                stimulus_id = %s,
                metadata = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                prompt,
                topic,
                difficulty,
                Json(options),
                correct_key,
                explanation,
                stimulus_id,
                Json(existing_metadata) if existing_metadata else None,
                question_id,
            ),
        )
        if cur.rowcount <= 0:
            return False
        cur.execute(
            """
            UPDATE tka_subjects
            SET question_revision = question_revision + 1,
                updated_at = NOW()
            WHERE id = %s
            """,
            (subject_id,),
        )
    return True


def fetch_tka_attempts(
    *,
    subject_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    params: List[Any] = []
    if subject_id:
        clauses.append("a.subject_id = %s")
        params.append(subject_id)
    normalized_status = (status or "").strip().lower()
    if normalized_status in {"in_progress", "completed", "expired", "cancelled"}:
        clauses.append("a.status = %s")
        params.append(normalized_status)
    elif normalized_status == "repeat":
        clauses.append("a.is_repeat = TRUE")
    if search:
        clauses.append("(w.full_name ILIKE %s OR w.email ILIKE %s)")
        params.extend([f"%{search.strip()}%", f"%{search.strip()}%"])
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""
        SELECT
            a.id,
            a.subject_id,
            s.name AS subject_name,
            s.grade_level,
            a.web_user_id,
            w.full_name,
            w.email,
            a.status,
            a.started_at,
            a.completed_at,
            a.time_limit_minutes,
            a.question_count,
            a.correct_count,
            a.score,
            a.duration_seconds,
            a.is_repeat,
            a.repeat_iteration,
            a.difficulty_breakdown,
            a.difficulty_preset,
            a.revision_snapshot,
            a.analysis_sent_at,
            a.updated_at
        FROM tka_quiz_attempts a
        JOIN tka_subjects s ON s.id = a.subject_id
        LEFT JOIN web_users w ON w.id = a.web_user_id
        {where_clause}
        ORDER BY COALESCE(a.completed_at, a.started_at) DESC
        LIMIT %s
    """
    params.append(limit)
    with get_cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    return [dict(row) for row in rows]
