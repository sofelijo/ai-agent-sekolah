from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional

from psycopg2.extras import Json

from dashboard.db_access import get_cursor
from db import (
    DEFAULT_TKA_PRESETS,
    DEFAULT_TKA_PRESET_KEY,
    DEFAULT_TKA_COMPOSITE_DURATION,
    TKA_SECTION_TEMPLATES,
    TKA_SECTION_KEY_ORDER,
    TKA_METADATA_SECTION_CONFIG_KEY,
)

# Constants
VALID_GRADE_LEVELS = {"sd6", "smp3", "sma"}
DEFAULT_GRADE_LEVEL = "sd6"
VALID_TEST_FORMATS = {"multiple_choice", "true_false"}
DEFAULT_TKA_GRADE_LEVEL = "sd6"

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
    subject_id: Optional[int],
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
        WHERE subject_id IS NULL
          AND LOWER(TRIM(title)) = LOWER(%s)
          AND LOWER(COALESCE(TRIM(narrative), '')) = LOWER(%s)
        LIMIT 1
        """,
        (title, narrative or ""),
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
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        RETURNING id
        """,
        (

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
        raw_subjects = [dict(row) for row in cur.fetchall() or []]
    # Pastikan tidak ada mapel ganda (kadang tersimpan dua baris untuk mapel yang sama)
    subjects: list[dict] = []
    seen_mapel: set[str] = set()
    for entry in raw_subjects:
        key_parts = [
            str(entry.get("mapel_id") or "none"),
            str(entry.get("subject_id") or entry.get("id") or "none"),
        ]
        key = "|".join(key_parts)
        if key in seen_mapel:
            continue
        seen_mapel.add(key)
        subjects.append(entry)
    for item in subjects:
        item["subject_name"] = item.get("mapel_name")
        item["grade_level"] = item.get("mapel_grade_level") or item.get("grade_level")

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





def delete_tka_mapel(mapel_id: int) -> bool:
    if not mapel_id:
        return False
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM tka_mata_pelajaran WHERE id = %s", (mapel_id,))
        return cur.rowcount > 0








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
        clauses.append("q.subject_id IS NULL")
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
            SELECT id, mapel_id, test_id, title, type, narrative, image_url, image_prompt, metadata, updated_at
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
            SELECT id, title, type, narrative, image_url, image_prompt, metadata
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
            RETURNING id, mapel_id, test_id, title, type, narrative, image_url, image_prompt, metadata, updated_at
            """,
            (

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
            RETURNING id, mapel_id, test_id, title, type, narrative, image_url, image_prompt, metadata, updated_at
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
    questions: Iterable[Dict[str, Any]],
    *,
    created_by: Optional[int] = None,
    test_id: Optional[int] = None,
    test_subject_id: Optional[int] = None,
    mapel_id: Optional[int] = None,
) -> int:
    key_for_uniqueness = mapel_id or test_subject_id
    if not key_for_uniqueness:
        raise ValueError("mapel_id atau test_subject_id wajib diisi.")

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

            stimulus_id = _resolve_question_stimulus(
                cur,
                None,
                record.get("stimulus"),
                created_by,
                stimulus_cache,
            )
            # subject_id disimpan NULL; resolved_subject_id hanya untuk kebutuhan stimulus/dedup
            cur.execute(
                """
                INSERT INTO tka_questions (

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
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (

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

    return inserted


def has_tka_question_with_prompt(prompt: str, *, test_subject_id: Optional[int] = None) -> bool:
    if not test_subject_id or not prompt:
        return False
    normalized = prompt.strip().lower()
    if not normalized:
        return False
    clauses: List[str] = []
    params: List[Any] = [normalized]

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
    mapel_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    params: List[Any] = []
    if mapel_id:
        clauses.append("a.mapel_id = %s")
        params.append(mapel_id)
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
            a.mapel_id,
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
        LEFT JOIN tka_mata_pelajaran s ON s.id = a.mapel_id
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
