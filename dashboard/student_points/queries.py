from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from psycopg2.extras import DictRow

from ..db_access import get_cursor


def list_classes() -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, name, academic_year
            FROM school_classes
            WHERE active IS TRUE
            ORDER BY name
            """
        )
        return [dict(row) for row in cur.fetchall()]


def list_students(*, class_id: Optional[int] = None, active_only: bool = True) -> List[Dict[str, Any]]:
    conditions = ["s.active IS TRUE"] if active_only else []
    params: List[Any] = []
    if class_id is not None:
        conditions.append("s.class_id = %s")
        params.append(class_id)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT s.id, s.full_name, s.student_number, s.nisn, s.class_id, sc.name AS class_name
            FROM students s
            JOIN school_classes sc ON sc.id = s.class_id
            {where_clause}
            ORDER BY sc.name, COALESCE(s.sequence, 999999), s.full_name
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]


def get_student(student_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT s.id, s.full_name, s.student_number, s.nisn, s.gender,
                   s.class_id, sc.name AS class_name, sc.academic_year
            FROM students s
            JOIN school_classes sc ON sc.id = s.class_id
            WHERE s.id = %s
            """,
            (student_id,),
        )
        row: Optional[DictRow] = cur.fetchone()
    return dict(row) if row else None


def list_violation_types(*, include_inactive: bool = False) -> List[Dict[str, Any]]:
    condition = "" if include_inactive else "WHERE active IS TRUE"
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, code, name, category, points, description, recommended_action,
                   active, sort_order, created_at, updated_at
            FROM student_violation_types
            {condition}
            ORDER BY category, sort_order, points, name
            """
        )
        return [dict(row) for row in cur.fetchall()]


def list_violation_categories(*, include_inactive: bool = False) -> List[Dict[str, Any]]:
    condition = "" if include_inactive else "WHERE active IS TRUE"
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, name, description, active, sort_order, created_at, updated_at
            FROM student_violation_categories
            {condition}
            ORDER BY sort_order, name
            """
        )
        return [dict(row) for row in cur.fetchall()]


def create_violation_category(
    *, name: str, description: Optional[str], sort_order: int, user_id: Optional[int],
) -> int:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO student_violation_categories
                (name, description, sort_order, created_by, updated_by)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (name, description, sort_order, user_id, user_id),
        )
        return int(cur.fetchone()[0])


def update_violation_category(
    category_id: int, *, name: str, description: Optional[str], sort_order: int,
    active: bool, user_id: Optional[int],
) -> bool:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "SELECT name FROM student_violation_categories WHERE id = %s FOR UPDATE",
            (category_id,),
        )
        row = cur.fetchone()
        if not row:
            return False
        old_name = row[0]
        cur.execute(
            """
            UPDATE student_violation_categories
            SET name = %s, description = %s, sort_order = %s, active = %s,
                updated_by = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (name, description, sort_order, active, user_id, category_id),
        )
        if old_name != name:
            cur.execute(
                """
                UPDATE student_violation_types
                SET category = %s, updated_by = %s, updated_at = NOW()
                WHERE category = %s
                """,
                (name, user_id, old_name),
            )
        return True


def get_violation_type(violation_type_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, code, name, category, points, description, recommended_action, active, sort_order
            FROM student_violation_types
            WHERE id = %s
            """,
            (violation_type_id,),
        )
        row: Optional[DictRow] = cur.fetchone()
    return dict(row) if row else None


def create_violation_type(
    *, code: str, name: str, category: str, points: int,
    description: Optional[str], recommended_action: Optional[str],
    sort_order: int, user_id: Optional[int],
) -> int:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO student_violation_types
                (code, name, category, points, description, recommended_action,
                 sort_order, created_by, updated_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (code, name, category, points, description, recommended_action,
             sort_order, user_id, user_id),
        )
        return int(cur.fetchone()[0])


def update_violation_type(
    violation_type_id: int, *, code: str, name: str, category: str, points: int,
    description: Optional[str], recommended_action: Optional[str],
    sort_order: int, active: bool, user_id: Optional[int],
) -> bool:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE student_violation_types
            SET code = %s, name = %s, category = %s, points = %s,
                description = %s, recommended_action = %s, sort_order = %s,
                active = %s, updated_by = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (code, name, category, points, description, recommended_action,
             sort_order, active, user_id, violation_type_id),
        )
        return cur.rowcount > 0


def list_thresholds(*, include_inactive: bool = False) -> List[Dict[str, Any]]:
    condition = "" if include_inactive else "WHERE active IS TRUE"
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, min_points, label, color, recommended_action, active, created_at, updated_at
            FROM student_point_thresholds
            {condition}
            ORDER BY min_points
            """
        )
        return [dict(row) for row in cur.fetchall()]


def create_threshold(
    *, min_points: int, label: str, color: str,
    recommended_action: Optional[str], user_id: Optional[int],
) -> int:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO student_point_thresholds
                (min_points, label, color, recommended_action, created_by, updated_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (min_points, label, color, recommended_action, user_id, user_id),
        )
        return int(cur.fetchone()[0])


def update_threshold(
    threshold_id: int, *, min_points: int, label: str, color: str,
    recommended_action: Optional[str], active: bool, user_id: Optional[int],
) -> bool:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE student_point_thresholds
            SET min_points = %s, label = %s, color = %s, recommended_action = %s,
                active = %s, updated_by = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (min_points, label, color, recommended_action, active, user_id, threshold_id),
        )
        return cur.rowcount > 0


def create_point_record(
    *, student_id: int, violation: Dict[str, Any], occurred_at: datetime,
    location: Optional[str], note: Optional[str], action_taken: Optional[str],
    parent_notified: bool, recorded_by: Optional[int],
) -> int:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO student_point_records (
                student_id, violation_type_id, violation_code, violation_name,
                category, points, occurred_at, location, note, action_taken,
                parent_notified, recorded_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                student_id, violation["id"], violation["code"], violation["name"],
                violation["category"], violation["points"], occurred_at, location,
                note, action_taken, parent_notified, recorded_by,
            ),
        )
        return int(cur.fetchone()[0])


def void_point_record(record_id: int, *, reason: str, user_id: Optional[int]) -> bool:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE student_point_records
            SET status = 'void', voided_by = %s, voided_at = NOW(),
                void_reason = %s, updated_at = NOW()
            WHERE id = %s AND status = 'active'
            """,
            (user_id, reason, record_id),
        )
        return cur.rowcount > 0


def fetch_overview() -> Dict[str, Any]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'active') AS total_records,
                COALESCE(SUM(points) FILTER (WHERE status = 'active'), 0) AS total_points,
                COUNT(DISTINCT student_id) FILTER (WHERE status = 'active') AS affected_students,
                COUNT(*) FILTER (
                    WHERE status = 'active' AND occurred_at::date = CURRENT_DATE
                ) AS records_today,
                COALESCE(SUM(points) FILTER (
                    WHERE status = 'active' AND occurred_at >= DATE_TRUNC('month', CURRENT_DATE)
                ), 0) AS points_this_month
            FROM student_point_records
            """
        )
        return dict(cur.fetchone())


def fetch_student_summaries(
    *, class_id: Optional[int] = None, search: Optional[str] = None,
    include_zero: bool = False, limit: int = 100,
) -> List[Dict[str, Any]]:
    conditions = ["s.active IS TRUE"]
    params: List[Any] = []
    if class_id is not None:
        conditions.append("s.class_id = %s")
        params.append(class_id)
    if search:
        conditions.append(
            "(s.full_name ILIKE %s OR COALESCE(s.student_number, '') ILIKE %s OR COALESCE(s.nisn, '') ILIKE %s)"
        )
        pattern = f"%{search}%"
        params.extend([pattern, pattern, pattern])
    if not include_zero:
        conditions.append("t.record_count IS NOT NULL")
    params.append(limit)
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                s.id, s.full_name, s.student_number, s.nisn, sc.name AS class_name,
                COALESCE(t.total_points, 0) AS total_points,
                COALESCE(t.record_count, 0) AS record_count,
                t.last_violation_at,
                COALESCE(level.label, 'Terpantau') AS level_label,
                COALESCE(level.color, 'success') AS level_color,
                level.recommended_action AS level_action
            FROM students s
            JOIN school_classes sc ON sc.id = s.class_id
            LEFT JOIN (
                SELECT student_id, SUM(points) AS total_points, COUNT(*) AS record_count,
                       MAX(occurred_at) AS last_violation_at
                FROM student_point_records
                WHERE status = 'active'
                GROUP BY student_id
            ) t ON t.student_id = s.id
            LEFT JOIN LATERAL (
                SELECT label, color, recommended_action
                FROM student_point_thresholds
                WHERE active IS TRUE AND min_points <= COALESCE(t.total_points, 0)
                ORDER BY min_points DESC
                LIMIT 1
            ) level ON TRUE
            WHERE {' AND '.join(conditions)}
            ORDER BY COALESCE(t.total_points, 0) DESC, sc.name, s.full_name
            LIMIT %s
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]


def fetch_records(
    *, student_id: Optional[int] = None, class_id: Optional[int] = None,
    category: Optional[str] = None, status: Optional[str] = None,
    start_date: Optional[date] = None, end_date: Optional[date] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    conditions: List[str] = []
    params: List[Any] = []
    if student_id is not None:
        conditions.append("r.student_id = %s")
        params.append(student_id)
    if class_id is not None:
        conditions.append("s.class_id = %s")
        params.append(class_id)
    if category:
        conditions.append("r.category = %s")
        params.append(category)
    if status in {"active", "void"}:
        conditions.append("r.status = %s")
        params.append(status)
    if start_date:
        conditions.append("r.occurred_at::date >= %s")
        params.append(start_date)
    if end_date:
        conditions.append("r.occurred_at::date <= %s")
        params.append(end_date)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                r.id, r.student_id, r.violation_type_id, r.violation_code,
                r.violation_name, r.category, r.points, r.occurred_at,
                r.location, r.note, r.action_taken, r.parent_notified, r.status,
                r.voided_at, r.void_reason, r.created_at,
                s.full_name AS student_name, s.student_number, s.nisn,
                sc.name AS class_name,
                recorder.full_name AS recorded_by_name,
                voider.full_name AS voided_by_name
            FROM student_point_records r
            JOIN students s ON s.id = r.student_id
            JOIN school_classes sc ON sc.id = s.class_id
            LEFT JOIN dashboard_users recorder ON recorder.id = r.recorded_by
            LEFT JOIN dashboard_users voider ON voider.id = r.voided_by
            {where_clause}
            ORDER BY r.occurred_at DESC, r.id DESC
            LIMIT %s
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]


def fetch_student_total(student_id: int) -> Dict[str, Any]:
    with get_cursor() as cur:
        cur.execute(
            """
            WITH total AS (
                SELECT COALESCE(SUM(points), 0)::INTEGER AS total_points,
                       COUNT(*)::INTEGER AS record_count
                FROM student_point_records
                WHERE student_id = %s AND status = 'active'
            )
            SELECT total.total_points, total.record_count,
                   COALESCE(level.label, 'Terpantau') AS level_label,
                   COALESCE(level.color, 'success') AS level_color,
                   level.recommended_action AS level_action
            FROM total
            LEFT JOIN LATERAL (
                SELECT label, color, recommended_action
                FROM student_point_thresholds
                WHERE active IS TRUE AND min_points <= total.total_points
                ORDER BY min_points DESC LIMIT 1
            ) level ON TRUE
            """,
            (student_id,),
        )
        return dict(cur.fetchone())
