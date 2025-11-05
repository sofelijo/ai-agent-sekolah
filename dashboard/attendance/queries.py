from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple

from psycopg2.extras import DictRow

from ..db_access import get_cursor

ATTENDANCE_STATUSES: Tuple[str, ...] = ("masuk", "alpa", "izin", "sakit")
DEFAULT_ATTENDANCE_STATUS = "masuk"


def list_school_classes() -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, name, academic_year, metadata
            FROM school_classes
            ORDER BY name ASC
            """
        )
        return [dict(row) for row in cur.fetchall()]


def get_school_class(class_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, name, academic_year, metadata
            FROM school_classes
            WHERE id = %s
            LIMIT 1
            """,
            (class_id,),
        )
        row: Optional[DictRow] = cur.fetchone()
    return dict(row) if row else None


def update_teacher_assigned_class(user_id: int, class_id: Optional[int]) -> bool:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE dashboard_users SET assigned_class_id = %s WHERE id = %s",
            (class_id, user_id),
        )
        return cur.rowcount > 0


def fetch_teacher_assigned_class(user_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                du.assigned_class_id,
                sc.name AS class_name,
                sc.academic_year
            FROM dashboard_users du
            LEFT JOIN school_classes sc ON sc.id = du.assigned_class_id
            WHERE du.id = %s
            LIMIT 1
            """,
            (user_id,),
        )
        row: Optional[DictRow] = cur.fetchone()
    return dict(row) if row else None


def fetch_students_for_class(class_id: int, *, include_inactive: bool = False) -> List[Dict[str, Any]]:
    conditions: List[str] = ["class_id = %s"]
    params: List[Any] = [class_id]
    if not include_inactive:
        conditions.append("active IS TRUE")
    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT
            id,
            full_name,
            student_number,
            sequence,
            nisn,
            gender,
            birth_place,
            birth_date,
            religion,
            address_line,
            rt,
            rw,
            kelurahan,
            kecamatan,
            father_name,
            mother_name,
            nik,
            kk_number,
            active
        FROM students
        WHERE {where_clause}
        ORDER BY COALESCE(sequence, 9999) ASC, full_name ASC
    """
    with get_cursor() as cur:
        cur.execute(query, params)
        return [dict(row) for row in cur.fetchall()]


def fetch_attendance_for_date(class_id: int, attendance_date: date) -> Dict[int, Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT student_id, status, note, teacher_id, recorded_at, updated_at
            FROM attendance_records
            WHERE class_id = %s
              AND attendance_date = %s
            """,
            (class_id, attendance_date),
        )
        rows = cur.fetchall()
    return {int(row["student_id"]): dict(row) for row in rows}


def create_school_class(name: str, academic_year: Optional[str] = None) -> int:
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Nama kelas wajib diisi.")
    clean_year = (academic_year or "").strip() or None
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO school_classes (name, academic_year)
            VALUES (%s, %s)
            ON CONFLICT (name) DO UPDATE
                SET academic_year = EXCLUDED.academic_year,
                    updated_at = NOW()
            RETURNING id
            """,
            (clean_name, clean_year),
        )
        new_id = cur.fetchone()[0]
    return int(new_id)


def create_student(
    class_id: int,
    full_name: str,
    *,
    sequence: Optional[int] = None,
    student_number: Optional[str] = None,
    nisn: Optional[str] = None,
    gender: Optional[str] = None,
    birth_place: Optional[str] = None,
    birth_date: Optional[date] = None,
    religion: Optional[str] = None,
    address_line: Optional[str] = None,
    rt: Optional[str] = None,
    rw: Optional[str] = None,
    kelurahan: Optional[str] = None,
    kecamatan: Optional[str] = None,
    father_name: Optional[str] = None,
    mother_name: Optional[str] = None,
    nik: Optional[str] = None,
    kk_number: Optional[str] = None,
) -> int:
    if not full_name or not full_name.strip():
        raise ValueError("Nama siswa wajib diisi.")
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO students (
                class_id,
                full_name,
                student_number,
                sequence,
                nisn,
                gender,
                birth_place,
                birth_date,
                religion,
                address_line,
                rt,
                rw,
                kelurahan,
                kecamatan,
                father_name,
                mother_name,
                nik,
                kk_number
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (class_id, full_name) DO UPDATE
                SET student_number = EXCLUDED.student_number,
                    sequence = EXCLUDED.sequence,
                    nisn = EXCLUDED.nisn,
                    gender = EXCLUDED.gender,
                    birth_place = EXCLUDED.birth_place,
                    birth_date = EXCLUDED.birth_date,
                    religion = EXCLUDED.religion,
                    address_line = EXCLUDED.address_line,
                    rt = EXCLUDED.rt,
                    rw = EXCLUDED.rw,
                    kelurahan = EXCLUDED.kelurahan,
                    kecamatan = EXCLUDED.kecamatan,
                    father_name = EXCLUDED.father_name,
                    mother_name = EXCLUDED.mother_name,
                    nik = EXCLUDED.nik,
                    kk_number = EXCLUDED.kk_number,
                    updated_at = NOW()
            RETURNING id
            """,
            (
                class_id,
                full_name.strip(),
                (student_number or "").strip() or None,
                sequence,
                (nisn or "").strip() or None,
                (gender or "").strip() or None,
                (birth_place or "").strip() or None,
                birth_date,
                (religion or "").strip() or None,
                (address_line or "").strip() or None,
                (rt or "").strip() or None,
                (rw or "").strip() or None,
                (kelurahan or "").strip() or None,
                (kecamatan or "").strip() or None,
                (father_name or "").strip() or None,
                (mother_name or "").strip() or None,
                (nik or "").strip() or None,
                (kk_number or "").strip() or None,
            ),
        )
        new_id = cur.fetchone()[0]
    return int(new_id)


def fetch_master_data_overview() -> Dict[str, Any]:
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total_classes FROM school_classes")
        total_classes = int(cur.fetchone()["total_classes"])

        cur.execute("SELECT COUNT(*) AS total_students FROM students WHERE active IS TRUE")
        total_students = int(cur.fetchone()["total_students"])

        cur.execute(
            """
            SELECT COUNT(*) AS total_guru
            FROM dashboard_users
            WHERE role = 'guru'
            """
        )
        total_guru = int(cur.fetchone()["total_guru"])

        cur.execute(
            """
            SELECT COUNT(*) AS total_assigned
            FROM dashboard_users
            WHERE role = 'guru' AND assigned_class_id IS NOT NULL
            """
        )
        total_assigned = int(cur.fetchone()["total_assigned"])

    return {
        "total_classes": total_classes,
        "total_students": total_students,
        "total_guru": total_guru,
        "total_assigned_guru": total_assigned,
    }


def fetch_daily_attendance(days: int = 7) -> List[Dict[str, Any]]:
    days = max(1, days)
    with get_cursor() as cur:
        cur.execute(
            """
            WITH date_series AS (
                SELECT generate_series(
                    (CURRENT_DATE - (%s - 1)::int),
                    CURRENT_DATE,
                    INTERVAL '1 day'
                )::date AS attendance_date
            )
            SELECT
                ds.attendance_date,
                COALESCE(SUM(CASE WHEN ar.status = 'masuk' THEN 1 ELSE 0 END), 0) AS masuk,
                COALESCE(SUM(CASE WHEN ar.status = 'alpa' THEN 1 ELSE 0 END), 0) AS alpa,
                COALESCE(SUM(CASE WHEN ar.status = 'izin' THEN 1 ELSE 0 END), 0) AS izin,
                COALESCE(SUM(CASE WHEN ar.status = 'sakit' THEN 1 ELSE 0 END), 0) AS sakit
            FROM date_series ds
            LEFT JOIN attendance_records ar ON ar.attendance_date = ds.attendance_date
            GROUP BY ds.attendance_date
            ORDER BY ds.attendance_date ASC
            """,
            (days,),
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def fetch_attendance_totals_for_date(target_date: date) -> Dict[str, int]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'masuk' THEN 1 ELSE 0 END) AS masuk,
                SUM(CASE WHEN status = 'alpa' THEN 1 ELSE 0 END) AS alpa,
                SUM(CASE WHEN status = 'izin' THEN 1 ELSE 0 END) AS izin,
                SUM(CASE WHEN status = 'sakit' THEN 1 ELSE 0 END) AS sakit
            FROM attendance_records
            WHERE attendance_date = %s
            """,
            (target_date,),
        )
        row = cur.fetchone()
    if not row:
        return {status: 0 for status in ATTENDANCE_STATUSES}
    return {status: int(row[status] or 0) for status in ATTENDANCE_STATUSES}


def fetch_recent_attendance(limit: int = 10) -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                ar.class_id,
                sc.name AS class_name,
                COUNT(*) AS total_records,
                MAX(ar.updated_at) AS updated_at,
                MAX(du.full_name) FILTER (WHERE ar.teacher_id = du.id) AS teacher_name,
                MAX(du.email) FILTER (WHERE ar.teacher_id = du.id) AS teacher_email,
                MAX(ar.attendance_date) AS last_date
            FROM attendance_records ar
            JOIN school_classes sc ON sc.id = ar.class_id
            LEFT JOIN dashboard_users du ON du.id = ar.teacher_id
            GROUP BY ar.class_id, sc.name
            ORDER BY COALESCE(MAX(ar.updated_at), MAX(ar.recorded_at)) DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def fetch_all_students() -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                s.id,
                s.full_name,
                s.student_number,
                s.sequence,
                s.nisn,
                s.gender,
                s.birth_place,
                s.birth_date,
                s.religion,
                s.address_line,
                s.rt,
                s.rw,
                s.kelurahan,
                s.kecamatan,
                s.father_name,
                s.mother_name,
                s.nik,
                s.kk_number,
                s.active,
                s.class_id,
                sc.name AS class_name
            FROM students s
            JOIN school_classes sc ON sc.id = s.class_id
            ORDER BY sc.name ASC, COALESCE(s.sequence, 9999) ASC, s.full_name ASC
            """
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def upsert_attendance_entries(
    *,
    class_id: int,
    teacher_id: int,
    attendance_date: date,
    entries: Iterable[Dict[str, Any]],
) -> None:
    normalized_date = attendance_date
    with get_cursor(commit=True) as cur:
        for entry in entries:
            student_id = entry.get("student_id")
            if student_id is None:
                raise ValueError("student_id wajib diisi untuk setiap entri absensi.")
            try:
                student_id_int = int(student_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("student_id harus berupa integer.") from exc

            raw_status = (entry.get("status") or DEFAULT_ATTENDANCE_STATUS).strip().lower()
            if raw_status not in ATTENDANCE_STATUSES:
                raise ValueError(f"Status absensi tidak dikenal: {raw_status}")

            note = entry.get("note")

            cur.execute(
                """
                INSERT INTO attendance_records (
                    attendance_date,
                    student_id,
                    class_id,
                    teacher_id,
                    status,
                    note
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (attendance_date, student_id)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    note = EXCLUDED.note,
                    class_id = EXCLUDED.class_id,
                    teacher_id = EXCLUDED.teacher_id,
                    updated_at = NOW()
                """,
                (
                    normalized_date,
                    student_id_int,
                    class_id,
                    teacher_id,
                    raw_status,
                    note,
                ),
            )
