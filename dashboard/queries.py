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


# --- Chat Feedback queries --------------------------------------------------

def fetch_feedback_summary(start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> Dict[str, Any]:
    """Get feedback summary statistics for a given date range."""
    conditions: List[str] = []
    params: List[Any] = []
    
    if start_date:
        conditions.append("created_at >= %s")
        params.append(start_date)
    if end_date:
        conditions.append("created_at <= %s")
        params.append(end_date)
    
    where_clause = ""
    if conditions:
        where_clause = " WHERE " + " AND ".join(conditions)
    
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT 
                COUNT(*) FILTER (WHERE feedback_type = 'like') as total_likes,
                COUNT(*) FILTER (WHERE feedback_type = 'dislike') as total_dislikes,
                COUNT(*) as total_feedback,
                ROUND(100.0 * COUNT(*) FILTER (WHERE feedback_type = 'like') / NULLIF(COUNT(*), 0), 2) as positive_rate
            FROM chat_feedback
            {where_clause}
            """,
            tuple(params)
        )
        row = cur.fetchone()
    
    return {
        "total_likes": int(row["total_likes"] or 0),
        "total_dislikes": int(row["total_dislikes"] or 0),
        "total_feedback": int(row["total_feedback"] or 0),
        "positive_rate": float(row["positive_rate"] or 0.0),
        "period_start": start_date,
        "period_end": end_date,
    }


def fetch_feedback_list(
    filter_type: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 25,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """Get paginated list of feedback with message context."""
    conditions: List[str] = []
    params: List[Any] = []
    
    if filter_type and filter_type in ('like', 'dislike'):
        conditions.append("cf.feedback_type = %s")
        params.append(filter_type)
    if start_date:
        conditions.append("cf.created_at >= %s")
        params.append(start_date)
    if end_date:
        conditions.append("cf.created_at <= %s")
        params.append(end_date)
    
    where_clause = ""
    if conditions:
        where_clause = " WHERE " + " AND ".join(conditions)
    
    with get_cursor() as cur:
        # Get paginated list
        cur.execute(
            f"""
            SELECT 
                cf.id,
                cf.chat_log_id,
                cf.user_id,
                cf.username,
                cf.feedback_type,
                cf.created_at,
                cl.text as message_text,
                cl.created_at as message_created_at
            FROM chat_feedback cf
            JOIN chat_logs cl ON cf.chat_log_id = cl.id
            {where_clause}
            ORDER BY cf.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (*params, limit, offset)
        )
        rows = cur.fetchall()
        
        # Get total count
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM chat_feedback cf
            {where_clause}
            """,
            tuple(params)
        )
        total = cur.fetchone()[0]
    
    return [dict(row) for row in rows], int(total or 0)


def fetch_feedback_trend(start_date: datetime, days: int = 30) -> List[Dict[str, Any]]:
    """Get daily feedback trend for chart visualization."""
    days = max(1, days)
    
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT 
                DATE(created_at) as day,
                COUNT(*) FILTER (WHERE feedback_type = 'like') as likes,
                COUNT(*) FILTER (WHERE feedback_type = 'dislike') as dislikes
            FROM chat_feedback
            WHERE created_at >= %s
            GROUP BY DATE(created_at)
            ORDER BY day ASC
            """,
            (start_date,)
        )
        rows = cur.fetchall()
    
    return [
        {
            "day": row["day"],
            "likes": int(row["likes"] or 0),
            "dislikes": int(row["dislikes"] or 0),
            "total": int(row["likes"] or 0) + int(row["dislikes"] or 0),
        }
        for row in rows
    ]


def fetch_feedback_by_message(chat_log_id: int) -> Optional[Dict[str, Any]]:
    """Get feedback details for a specific message."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT 
                cf.id,
                cf.chat_log_id,
                cf.user_id,
                cf.username,
                cf.feedback_type,
                cf.created_at,
                cf.updated_at,
                cl.text as message_text,
                cl.created_at as message_created_at,
                cl.user_id as message_user_id,
                cl.username as message_username
            FROM chat_feedback cf
            JOIN chat_logs cl ON cf.chat_log_id = cl.id
            WHERE cf.chat_log_id = %s
            LIMIT 1
            """,
            (chat_log_id,)
        )
        row = cur.fetchone()
    
    return dict(row) if row else None


# --- Latihan TKA helpers ----------------------------------------------------


