from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from psycopg2 import errors

from psycopg2.extras import DictRow, Json

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
    conditions: List[str] = ["s.class_id = %s"]
    params: List[Any] = [class_id]
    if not include_inactive:
        conditions.append("s.active IS TRUE")
    where_clause = " AND ".join(conditions)
    query = f"""
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
            sc.name AS class_name
        FROM students s
        JOIN school_classes sc ON sc.id = s.class_id
        WHERE {where_clause}
        ORDER BY COALESCE(s.sequence, 9999) ASC, s.full_name ASC
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


def fetch_active_teachers() -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                id,
                full_name,
                email,
                jabatan,
                nrk,
                nip,
                degree_prefix,
                degree_suffix
            FROM dashboard_users
            WHERE role = 'staff'
            ORDER BY full_name ASC
            """
        )
        return [dict(row) for row in cur.fetchall()]


def fetch_teacher_master_data() -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                id,
                full_name,
                email,
                nrk,
                nip,
                jabatan,
                degree_prefix,
                degree_suffix,
                assigned_class_id
            FROM dashboard_users
            WHERE role = 'staff'
            ORDER BY full_name ASC
            """
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def fetch_teacher_profile(user_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                id,
                full_name,
                nip,
                degree_prefix,
                degree_suffix
            FROM dashboard_users
            WHERE id = %s
            LIMIT 1
            """,
            (user_id,),
        )
        row: Optional[DictRow] = cur.fetchone()
    return dict(row) if row else None


def fetch_extracurricular_coaches() -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, full_name, email
            FROM dashboard_users
            WHERE role = 'ekskul'
            ORDER BY full_name ASC
            """
        )
        return [dict(row) for row in cur.fetchall()]


def create_teacher_user(
    email: str,
    full_name: str,
    password_hash: str,
    *,
    nrk: Optional[str] = None,
    nip: Optional[str] = None,
    jabatan: Optional[str] = None,
    degree_prefix: Optional[str] = None,
    degree_suffix: Optional[str] = None,
    assigned_class_id: Optional[int] = None,
) -> int:
    clean_email = (email or "").strip().lower()
    clean_name = (full_name or "").strip()
    if not clean_email:
        raise ValueError("Email staff wajib diisi.")
    if not clean_name:
        raise ValueError("Nama staff wajib diisi.")
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO dashboard_users (
                email,
                full_name,
                password_hash,
                role,
                nrk,
                nip,
                jabatan,
                degree_prefix,
                degree_suffix,
                assigned_class_id
            )
            VALUES (%s, %s, %s, 'staff', %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                clean_email,
                clean_name,
                password_hash,
                (nrk or "").strip() or None,
                (nip or "").strip() or None,
                (jabatan or "").strip() or None,
                (degree_prefix or "").strip() or None,
                (degree_suffix or "").strip() or None,
                assigned_class_id,
            ),
        )
        new_id = cur.fetchone()[0]
    return int(new_id)


def update_teacher_user(
    teacher_id: int,
    *,
    email: str,
    full_name: str,
    nrk: Optional[str] = None,
    nip: Optional[str] = None,
    jabatan: Optional[str] = None,
    degree_prefix: Optional[str] = None,
    degree_suffix: Optional[str] = None,
    assigned_class_id: Optional[int] = None,
    password_hash: Optional[str] = None,
) -> bool:
    if teacher_id <= 0:
        raise ValueError("ID staff tidak valid.")
    clean_email = (email or "").strip().lower()
    clean_name = (full_name or "").strip()
    if not clean_email:
        raise ValueError("Email staff wajib diisi.")
    if not clean_name:
        raise ValueError("Nama staff wajib diisi.")
    assignments = [
        ("email", clean_email),
        ("full_name", clean_name),
        ("nrk", (nrk or "").strip() or None),
        ("nip", (nip or "").strip() or None),
        ("jabatan", (jabatan or "").strip() or None),
        ("degree_prefix", (degree_prefix or "").strip() or None),
        ("degree_suffix", (degree_suffix or "").strip() or None),
        ("assigned_class_id", assigned_class_id),
    ]
    if password_hash:
        assignments.append(("password_hash", password_hash))
    set_clause = ", ".join(f"{column} = %s" for column, _ in assignments)
    params = [value for _, value in assignments]
    params.append(teacher_id)
    query = f"""
        UPDATE dashboard_users
        SET {set_clause}
        WHERE id = %s AND role = 'staff'
    """
    with get_cursor(commit=True) as cur:
        cur.execute(query, params)
        return cur.rowcount > 0


def fetch_teacher_attendance_for_date(attendance_date: date) -> Dict[int, Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                teacher_id,
                status,
                note,
                recorded_by,
                recorded_at,
                updated_at
            FROM teacher_attendance_records
            WHERE attendance_date = %s
            """,
            (attendance_date,),
        )
        rows = cur.fetchall()
    return {int(row["teacher_id"]): dict(row) for row in rows}


def fetch_teacher_absence_for_date(attendance_date: date) -> List[Dict[str, Any]]:
    """Ambil daftar staff yang tidak berstatus 'masuk' pada tanggal tertentu."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                tar.teacher_id,
                du.full_name,
                du.jabatan,
                du.nip,
                du.nrk,
                du.degree_prefix,
                du.degree_suffix,
                tar.status,
                tar.note
            FROM teacher_attendance_records tar
            JOIN dashboard_users du ON du.id = tar.teacher_id
            WHERE tar.attendance_date = %s
              AND tar.status <> 'masuk'
            ORDER BY du.full_name ASC
            """,
            (attendance_date,),
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def fetch_late_students_for_date(attendance_date: date, *, class_id: Optional[int] = None) -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        params = [attendance_date]
        where_clause = "WHERE als.attendance_date = %s"
        if class_id is not None:
            where_clause += " AND als.class_id = %s"
            params.append(class_id)
        cur.execute(
            f"""
            SELECT
                als.id,
                als.class_id,
                als.student_name,
                COALESCE(NULLIF(als.class_label, ''), cls.name) AS class_label,
                als.arrival_time,
                als.reason
            FROM attendance_late_students als
            LEFT JOIN school_classes cls ON cls.id = als.class_id
            {where_clause}
            ORDER BY als.created_at ASC, als.id ASC
            """,
            tuple(params),
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def replace_late_students_for_date(
    *,
    attendance_date: date,
    entries: Iterable[Dict[str, Any]],
    recorded_by: Optional[int] = None,
) -> None:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM attendance_late_students WHERE attendance_date = %s",
            (attendance_date,),
        )
        for entry in entries:
            student_name = (entry.get("student_name") or "").strip()
            if not student_name:
                continue
            class_id = entry.get("class_id")
            resolved_class_id: Optional[int]
            if class_id is None or (isinstance(class_id, str) and not class_id.strip()):
                resolved_class_id = None
            else:
                try:
                    resolved_class_id = int(class_id)
                except (TypeError, ValueError):
                    resolved_class_id = None
            class_label = (entry.get("class_label") or "").strip() or None
            arrival_time = (entry.get("arrival_time") or "").strip() or None
            reason = (entry.get("reason") or "").strip() or None
            cur.execute(
                """
                INSERT INTO attendance_late_students (
                    attendance_date,
                    class_id,
                    student_name,
                    class_label,
                    arrival_time,
                    reason,
                    recorded_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    attendance_date,
                    resolved_class_id,
                    student_name,
                    class_label,
                    arrival_time,
                    reason,
                    recorded_by,
                ),
            )


def upsert_teacher_attendance_entries(
    *,
    attendance_date: date,
    recorded_by: int,
    entries: Iterable[Dict[str, Any]],
) -> None:
    with get_cursor(commit=True) as cur:
        for entry in entries:
            teacher_id = entry.get("teacher_id")
            if teacher_id is None:
                raise ValueError("teacher_id wajib diisi untuk setiap entri absensi staff.")
            try:
                teacher_id_int = int(teacher_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("teacher_id harus berupa integer.") from exc

            raw_status = (entry.get("status") or DEFAULT_ATTENDANCE_STATUS).strip().lower()
            if raw_status not in ATTENDANCE_STATUSES:
                raise ValueError(f"Status absensi tidak dikenal: {raw_status}")

            note = entry.get("note")

            cur.execute(
                """
                INSERT INTO teacher_attendance_records (
                    attendance_date,
                    teacher_id,
                    status,
                    note,
                    recorded_by
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (attendance_date, teacher_id)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    note = EXCLUDED.note,
                    recorded_by = EXCLUDED.recorded_by,
                    updated_at = NOW()
                """,
                (
                    attendance_date,
                    teacher_id_int,
                    raw_status,
                    note,
                    recorded_by,
                ),
            )


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


def fetch_student_by_id(student_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                id,
                class_id,
                full_name,
                student_number,
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
            FROM students
            WHERE id = %s
            LIMIT 1
            """,
            (student_id,),
        )
        row: Optional[DictRow] = cur.fetchone()
    return dict(row) if row else None


def update_student_record(
    student_id: int,
    *,
    class_id: int,
    full_name: str,
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
) -> bool:
    if not full_name or not full_name.strip():
        raise ValueError("Nama siswa wajib diisi.")
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE students
            SET
                class_id = %s,
                full_name = %s,
                student_number = %s,
                nisn = %s,
                gender = %s,
                birth_place = %s,
                birth_date = %s,
                religion = %s,
                address_line = %s,
                rt = %s,
                rw = %s,
                kelurahan = %s,
                kecamatan = %s,
                father_name = %s,
                mother_name = %s,
                nik = %s,
                kk_number = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                class_id,
                full_name.strip(),
                (student_number or "").strip() or None,
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
                student_id,
            ),
        )
        return cur.rowcount > 0


def update_student_sequences(class_id: int, ordered_ids: List[int]) -> int:
    if not ordered_ids:
        raise ValueError("Daftar siswa kosong.")

    seen: set[int] = set()
    ordered: List[int] = []
    for raw_id in ordered_ids:
        if raw_id in seen:
            raise ValueError("Daftar siswa mengandung duplikasi.")
        seen.add(raw_id)
        ordered.append(raw_id)

    case_clauses: List[str] = []
    values: List[Any] = []
    for index, student_id in enumerate(ordered, start=1):
        case_clauses.append("WHEN %s THEN %s")
        values.extend([student_id, index])

    ids_placeholders = ", ".join(["%s"] * len(ordered))
    values.append(class_id)
    values.extend(ordered)

    query = f"""
        UPDATE students
        SET
            sequence = CASE id
                {' '.join(case_clauses)}
                ELSE sequence
            END,
            updated_at = NOW()
        WHERE class_id = %s
          AND id IN ({ids_placeholders})
        """
    with get_cursor(commit=True) as cur:
        cur.execute(query, values)
        return cur.rowcount


def deactivate_student(student_id: int) -> bool:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE students
            SET
                active = FALSE,
                updated_at = NOW()
            WHERE id = %s
              AND active IS TRUE
            """,
            (student_id,),
        )
        return cur.rowcount > 0


def fetch_master_data_overview() -> Dict[str, Any]:
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total_classes FROM school_classes")
        total_classes = int(cur.fetchone()["total_classes"])

        cur.execute("SELECT COUNT(*) AS total_students FROM students WHERE active IS TRUE")
        total_students = int(cur.fetchone()["total_students"])

        cur.execute(
            """
            SELECT COUNT(*) AS total_staff
            FROM dashboard_users
            WHERE role = 'staff'
            """
        )
        total_staff = int(cur.fetchone()["total_staff"])

        cur.execute(
            """
            SELECT COUNT(*) AS total_assigned
            FROM dashboard_users
            WHERE role = 'staff' AND assigned_class_id IS NOT NULL
            """
        )
        total_assigned = int(cur.fetchone()["total_assigned"])

        cur.execute(
            """
            SELECT
                CASE
                    WHEN COALESCE(jabatan, '') ILIKE '%%guru%%'
                         OR COALESCE(jabatan, '') ILIKE '%%kepala%%'
                    THEN 'Guru'
                    ELSE 'Tenaga Pendidikan'
                END AS category,
                COUNT(*) AS total
            FROM dashboard_users
            WHERE role = 'staff'
            GROUP BY category
            ORDER BY category ASC
            """
        )
        staff_breakdown = [
            {
                "jabatan": row["category"],
                "total": int(row["total"] or 0),
            }
            for row in cur.fetchall()
        ]

    return {
        "total_classes": total_classes,
        "total_students": total_students,
        "total_staff": total_staff,
        "total_assigned_staff": total_assigned,
        "staff_breakdown": staff_breakdown,
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


def fetch_class_submission_status_for_date(target_date: date) -> Dict[str, List[Dict[str, Any]]]:
    """Daftar kelas yang sudah/belum mengisi absensi pada tanggal tertentu."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                sc.id,
                sc.name,
                COUNT(ar.id) AS total_entries,
                MAX(ar.updated_at) AS last_updated_at,
                MAX(ar.recorded_at) AS last_recorded_at
            FROM school_classes sc
            LEFT JOIN attendance_records ar
              ON ar.class_id = sc.id
             AND ar.attendance_date = %s
            GROUP BY sc.id, sc.name
            ORDER BY sc.name ASC
            """,
            (target_date,),
        )
        rows = cur.fetchall()

    submitted: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []
    for raw in rows:
        entries = int(raw["total_entries"] or 0)
        item = {
            "id": int(raw["id"]),
            "name": raw["name"],
            "entries": entries,
            "last_activity": raw["last_updated_at"] or raw["last_recorded_at"],
        }
        if entries > 0:
            submitted.append(item)
        else:
            pending.append(item)
    return {"submitted": submitted, "pending": pending}


def fetch_most_missing_attendance_classes(
    start_date: date,
    end_date: date,
    limit: int = 5,
    exclude_weekends: bool = True,
) -> List[Dict[str, Any]]:
    """Ambil kelas dengan hari terbanyak tanpa absen pada rentang tanggal."""
    weekend_filter = "AND EXTRACT(DOW FROM d) NOT IN (0, 6)" if exclude_weekends else ""
    with get_cursor() as cur:
        cur.execute(
            f"""
            WITH date_series AS (
                SELECT d::date AS attendance_date
                FROM generate_series(%s::date, %s::date, interval '1 day') AS d
                WHERE 1=1
                {weekend_filter}
            ),
            class_dates AS (
                SELECT sc.id, sc.name, ds.attendance_date
                FROM school_classes sc
                CROSS JOIN date_series ds
            ),
            class_entries AS (
                SELECT ar.class_id, ar.attendance_date, COUNT(*) AS total_entries
                FROM attendance_records ar
                WHERE ar.attendance_date BETWEEN %s AND %s
                GROUP BY ar.class_id, ar.attendance_date
            )
            SELECT
                cd.id,
                cd.name,
                SUM(CASE WHEN COALESCE(ce.total_entries, 0) = 0 THEN 1 ELSE 0 END) AS missing_days,
                COUNT(*) AS total_days
            FROM class_dates cd
            LEFT JOIN class_entries ce
              ON ce.class_id = cd.id
             AND ce.attendance_date = cd.attendance_date
            GROUP BY cd.id, cd.name
            ORDER BY missing_days DESC, cd.name ASC
            LIMIT %s
            """,
            (start_date, end_date, start_date, end_date, limit),
        )
        rows = cur.fetchall()
    return [
        {
            "id": int(row["id"]),
            "name": row["name"],
            "missing_days": int(row["missing_days"] or 0),
            "total_days": int(row["total_days"] or 0),
        }
        for row in rows
    ]


def fetch_class_attendance_breakdown(attendance_date: date) -> List[Dict[str, Any]]:
    """Berikan rekap jumlah status per kelas untuk tanggal tertentu."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                sc.id,
                sc.name,
                sc.academic_year,
                COALESCE(SUM(CASE WHEN ar.status = 'sakit' THEN 1 ELSE 0 END), 0) AS sakit,
                COALESCE(SUM(CASE WHEN ar.status = 'izin' THEN 1 ELSE 0 END), 0) AS izin,
                COALESCE(SUM(CASE WHEN ar.status = 'alpa' THEN 1 ELSE 0 END), 0) AS alpa,
                COALESCE(SUM(CASE WHEN ar.status = 'masuk' THEN 1 ELSE 0 END), 0) AS masuk,
                COUNT(s.id) FILTER (WHERE s.active IS TRUE) AS total_students
            FROM school_classes sc
            LEFT JOIN students s ON s.class_id = sc.id AND s.active IS TRUE
            LEFT JOIN attendance_records ar
                ON ar.class_id = sc.id
               AND ar.attendance_date = %s
               AND ar.student_id = s.id
            GROUP BY sc.id, sc.name, sc.academic_year
            ORDER BY sc.name ASC
            """,
            (attendance_date,),
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def fetch_monthly_attendance_overview(year: int, month: int) -> List[Dict[str, Any]]:
    """Rekap absensi per hari dalam satu bulan (total semua kelas)."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                ar.attendance_date,
                SUM(CASE WHEN ar.status = 'sakit' THEN 1 ELSE 0 END) AS sakit,
                SUM(CASE WHEN ar.status = 'izin' THEN 1 ELSE 0 END) AS izin,
                SUM(CASE WHEN ar.status = 'alpa' THEN 1 ELSE 0 END) AS alpa,
                SUM(CASE WHEN ar.status = 'masuk' THEN 1 ELSE 0 END) AS masuk,
                COUNT(*) AS total
            FROM attendance_records ar
            WHERE EXTRACT(YEAR FROM ar.attendance_date) = %s
              AND EXTRACT(MONTH FROM ar.attendance_date) = %s
            GROUP BY ar.attendance_date
            ORDER BY ar.attendance_date ASC
            """,
            (year, month),
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def fetch_class_month_attendance_entries(class_id: int, year: int, month: int) -> List[Dict[str, Any]]:
    """Ambil seluruh entri absensi untuk satu kelas pada bulan tertentu.

    Mengembalikan list dict dengan kolom: attendance_date, student_id, status.
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                attendance_date,
                student_id,
                status
            FROM attendance_records
            WHERE class_id = %s
              AND EXTRACT(YEAR FROM attendance_date) = %s
              AND EXTRACT(MONTH FROM attendance_date) = %s
            ORDER BY attendance_date ASC
            """,
            (class_id, year, month),
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def fetch_school_identity() -> Dict[str, Optional[str]]:
    """
    Ambil identitas sekolah dan kepala sekolah bila tersedia.
    Mengembalikan nilai None bila data tidak ditemukan.
    """
    identity: Dict[str, Optional[str]] = {
        "school_name": None,
        "academic_year": None,
        "headmaster_name": None,
        "headmaster_nip": None,
        "headmaster_degree_prefix": None,
        "headmaster_degree_suffix": None,
    }

    with get_cursor() as cur:
        try:
            cur.execute(
                """
                SELECT
                    school_name,
                    academic_year,
                    headmaster_name,
                    headmaster_nip,
                    headmaster_degree_prefix,
                    headmaster_degree_suffix
                FROM school_profile
                LIMIT 1
                """
            )
            row = cur.fetchone()
        except (errors.UndefinedTable, errors.UndefinedColumn):
            row = None
    if row:
        identity.update({key: row.get(key) for key in identity.keys() if key in row})

    needs_headmaster_detail = not identity.get("headmaster_name") or not identity.get("headmaster_nip") or not identity.get("headmaster_degree_prefix") or not identity.get("headmaster_degree_suffix")
    if needs_headmaster_detail:
        with get_cursor() as cur:
            try:
                cur.execute(
                    """
                    SELECT
                        full_name,
                        nip,
                        jabatan,
                        degree_prefix,
                        degree_suffix
                    FROM dashboard_users
                    WHERE role IN ('admin', 'staff')
                    ORDER BY
                        CASE
                            WHEN jabatan ILIKE '%%kepala%%' THEN 0
                            ELSE 1
                        END,
                        created_at ASC,
                        full_name ASC
                    LIMIT 1
                    """
                )
            except errors.UndefinedColumn:
                cur.execute(
                    """
                    SELECT
                        full_name,
                        nip,
                        jabatan,
                        NULL AS degree_prefix,
                        NULL AS degree_suffix
                    FROM dashboard_users
                    WHERE role IN ('admin', 'staff')
                    ORDER BY
                        CASE
                            WHEN jabatan ILIKE '%%kepala%%' THEN 0
                            ELSE 1
                        END,
                        created_at ASC,
                        full_name ASC
                    LIMIT 1
                    """
                )
            head_row = cur.fetchone()
        if head_row:
            if not identity.get("headmaster_name"):
                identity["headmaster_name"] = head_row.get("full_name")
            if not identity.get("headmaster_nip"):
                identity["headmaster_nip"] = head_row.get("nip")
            if not identity.get("headmaster_degree_prefix"):
                identity["headmaster_degree_prefix"] = head_row.get("degree_prefix")
            if not identity.get("headmaster_degree_suffix"):
                identity["headmaster_degree_suffix"] = head_row.get("degree_suffix")

    return identity


def list_attendance_months(limit: int = 12) -> List[date]:
    """Daftar bulan yang memiliki data absensi (untuk pilihan filter)."""
    limit = max(1, limit)
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT DATE_TRUNC('month', attendance_date)::date AS month_start
            FROM attendance_records
            ORDER BY month_start DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [row["month_start"] for row in rows]


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
            WHERE s.active IS TRUE
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


def list_extracurriculars(
    *,
    include_inactive: bool = False,
    coach_user_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    conditions: List[str] = []
    params: List[Any] = []
    if not include_inactive:
        conditions.append("e.active IS TRUE")
    if coach_user_id is not None:
        conditions.append("e.coach_user_id = %s")
        params.append(coach_user_id)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""
        SELECT
            e.id,
            e.name,
            e.coach_name,
            e.coach_user_id,
            COALESCE(du.full_name, e.coach_name) AS coach_display,
            du.email AS coach_email,
            e.schedule_day,
            e.start_time,
            e.end_time,
            e.location,
            e.capacity,
            e.description,
            e.active,
            e.metadata,
            e.created_at,
            e.updated_at
        FROM extracurriculars e
        LEFT JOIN dashboard_users du ON du.id = e.coach_user_id
        {where_clause}
        ORDER BY e.name ASC
    """
    with get_cursor() as cur:
        cur.execute(query, params)
        return [dict(row) for row in cur.fetchall()]


def fetch_extracurricular_overview(
    *,
    include_inactive: bool = False,
    coach_user_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    conditions: List[str] = []
    params: List[Any] = []
    if not include_inactive:
        conditions.append("e.active IS TRUE")
    if coach_user_id is not None:
        conditions.append("e.coach_user_id = %s")
        params.append(coach_user_id)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""
        SELECT
            e.id,
            e.name,
            e.coach_name,
            e.coach_user_id,
            COALESCE(du.full_name, e.coach_name) AS coach_display,
            du.email AS coach_email,
            e.schedule_day,
            e.start_time,
            e.end_time,
            e.location,
            e.capacity,
            e.description,
            e.active,
            e.metadata,
            e.created_at,
            e.updated_at,
            COALESCE(member_stats.total_members, 0) AS total_members,
            COALESCE(member_stats.active_members, 0) AS active_members,
            last_att.last_attendance_date
        FROM extracurriculars e
        LEFT JOIN dashboard_users du ON du.id = e.coach_user_id
        LEFT JOIN (
            SELECT
                extracurricular_id,
                COUNT(*) AS total_members,
                COUNT(*) FILTER (WHERE active IS TRUE) AS active_members
            FROM extracurricular_members
            GROUP BY extracurricular_id
        ) AS member_stats ON member_stats.extracurricular_id = e.id
        LEFT JOIN (
            SELECT
                extracurricular_id,
                MAX(attendance_date) AS last_attendance_date
            FROM extracurricular_attendance_records
            GROUP BY extracurricular_id
        ) AS last_att ON last_att.extracurricular_id = e.id
        {where_clause}
        ORDER BY e.name ASC
    """
    with get_cursor() as cur:
        cur.execute(query, params)
        return [dict(row) for row in cur.fetchall()]


def get_extracurricular(activity_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                e.id,
                e.name,
                e.coach_name,
                e.coach_user_id,
                COALESCE(du.full_name, e.coach_name) AS coach_display,
                du.email AS coach_email,
                e.schedule_day,
                e.start_time,
                e.end_time,
                e.location,
                e.capacity,
                e.description,
                e.active,
                e.metadata,
                e.created_at,
                e.updated_at
            FROM extracurriculars e
            LEFT JOIN dashboard_users du ON du.id = e.coach_user_id
            WHERE e.id = %s
            LIMIT 1
            """,
            (activity_id,),
        )
        row: Optional[DictRow] = cur.fetchone()
    return dict(row) if row else None


def create_extracurricular(
    *,
    name: str,
    coach_name: Optional[str] = None,
    coach_user_id: Optional[int] = None,
    schedule_day: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    location: Optional[str] = None,
    capacity: Optional[int] = None,
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    created_by: Optional[int] = None,
) -> int:
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Nama ekskul wajib diisi.")
    metadata_payload = Json(metadata) if metadata is not None else None
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO extracurriculars (
                name,
                coach_name,
                coach_user_id,
                schedule_day,
                start_time,
                end_time,
                location,
                capacity,
                description,
                metadata,
                created_by,
                updated_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                clean_name,
                coach_name,
                coach_user_id,
                schedule_day,
                start_time,
                end_time,
                location,
                capacity,
                description,
                metadata_payload,
                created_by,
                created_by,
            ),
        )
        new_id = cur.fetchone()[0]
    return int(new_id)


def update_extracurricular(
    *,
    activity_id: int,
    name: str,
    coach_name: Optional[str] = None,
    coach_user_id: Optional[int] = None,
    schedule_day: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    location: Optional[str] = None,
    capacity: Optional[int] = None,
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    active: Optional[bool] = None,
    updated_by: Optional[int] = None,
) -> bool:
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Nama ekskul wajib diisi.")
    fields = [
        "name = %s",
        "coach_name = %s",
        "coach_user_id = %s",
        "schedule_day = %s",
        "start_time = %s",
        "end_time = %s",
        "location = %s",
        "capacity = %s",
        "description = %s",
        "updated_by = %s",
        "updated_at = NOW()",
    ]
    values: List[Any] = [
        clean_name,
        coach_name,
        coach_user_id,
        schedule_day,
        start_time,
        end_time,
        location,
        capacity,
        description,
        updated_by,
    ]
    if metadata is not None:
        fields.insert(-2, "metadata = %s")
        values.insert(-1, Json(metadata))
    if active is not None:
        fields.append("active = %s")
        values.append(active)
    values.append(activity_id)
    query = f"""
        UPDATE extracurriculars
        SET {", ".join(fields)}
        WHERE id = %s
        """
    with get_cursor(commit=True) as cur:
        cur.execute(query, values)
        return cur.rowcount > 0


def set_extracurricular_active(activity_id: int, active: bool, updated_by: Optional[int] = None) -> bool:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE extracurriculars
            SET active = %s,
                updated_by = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (active, updated_by, activity_id),
        )
        return cur.rowcount > 0


def fetch_extracurricular_members(
    activity_id: int,
    *,
    include_inactive: bool = False,
) -> List[Dict[str, Any]]:
    conditions = ["em.extracurricular_id = %s"]
    params: List[Any] = [activity_id]
    if not include_inactive:
        conditions.append("em.active IS TRUE")
    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT
            em.id AS member_id,
            em.active AS member_active,
            em.role AS member_role,
            em.joined_at,
            em.note AS member_note,
            s.id AS student_id,
            s.full_name,
            s.student_number,
            s.gender,
            s.class_id,
            sc.name AS class_name,
            s.active AS student_active
        FROM extracurricular_members em
        JOIN students s ON s.id = em.student_id
        JOIN school_classes sc ON sc.id = s.class_id
        WHERE {where_clause}
        ORDER BY sc.name ASC, COALESCE(s.sequence, 9999) ASC, s.full_name ASC
    """
    with get_cursor() as cur:
        cur.execute(query, params)
        return [dict(row) for row in cur.fetchall()]


def upsert_extracurricular_members(
    *,
    activity_id: int,
    student_ids: Iterable[int],
    role: Optional[str] = None,
    joined_at: Optional[date] = None,
    note: Optional[str] = None,
    active: bool = True,
) -> None:
    with get_cursor(commit=True) as cur:
        for student_id in student_ids:
            try:
                student_id_int = int(student_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("student_id harus berupa integer.") from exc
            cur.execute(
                """
                INSERT INTO extracurricular_members (
                    extracurricular_id,
                    student_id,
                    role,
                    joined_at,
                    note,
                    active
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (extracurricular_id, student_id)
                DO UPDATE SET
                    role = COALESCE(EXCLUDED.role, extracurricular_members.role),
                    joined_at = COALESCE(EXCLUDED.joined_at, extracurricular_members.joined_at),
                    note = COALESCE(EXCLUDED.note, extracurricular_members.note),
                    active = EXCLUDED.active,
                    updated_at = NOW()
                """,
                (
                    activity_id,
                    student_id_int,
                    role,
                    joined_at,
                    note,
                    active,
                ),
            )


def set_extracurricular_member_active(
    member_id: int,
    active: bool,
    *,
    activity_id: Optional[int] = None,
) -> bool:
    extra_condition = ""
    params: List[Any] = [active, member_id]
    if activity_id is not None:
        extra_condition = " AND extracurricular_id = %s"
        params.append(activity_id)
    with get_cursor(commit=True) as cur:
        cur.execute(
            f"""
            UPDATE extracurricular_members
            SET active = %s,
                updated_at = NOW()
            WHERE id = %s{extra_condition}
            """,
            params,
        )
        return cur.rowcount > 0


def update_extracurricular_member(
    *,
    member_id: int,
    activity_id: int,
    role: Optional[str] = None,
    joined_at: Optional[date] = None,
    note: Optional[str] = None,
) -> bool:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE extracurricular_members
            SET role = %s,
                joined_at = %s,
                note = %s,
                updated_at = NOW()
            WHERE id = %s
              AND extracurricular_id = %s
            """,
            (role, joined_at, note, member_id, activity_id),
        )
        return cur.rowcount > 0


def delete_extracurricular_member(*, member_id: int, activity_id: int) -> bool:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            DELETE FROM extracurricular_members
            WHERE id = %s
              AND extracurricular_id = %s
            """,
            (member_id, activity_id),
        )
        return cur.rowcount > 0


def set_extracurricular_members_active(
    *,
    member_ids: Iterable[int],
    activity_id: int,
    active: bool,
) -> int:
    ids = [int(item) for item in member_ids]
    if not ids:
        return 0
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE extracurricular_members
            SET active = %s,
                updated_at = NOW()
            WHERE extracurricular_id = %s
              AND id = ANY(%s)
            """,
            (active, activity_id, ids),
        )
        return int(cur.rowcount or 0)


def delete_extracurricular_members(*, member_ids: Iterable[int], activity_id: int) -> int:
    ids = [int(item) for item in member_ids]
    if not ids:
        return 0
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            DELETE FROM extracurricular_members
            WHERE extracurricular_id = %s
              AND id = ANY(%s)
            """,
            (activity_id, ids),
        )
        return int(cur.rowcount or 0)


def search_extracurricular_students(
    *,
    activity_id: int,
    query: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    term = (query or "").strip()
    if not term:
        return []
    like_term = f"%{term}%"
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                s.id AS student_id,
                s.full_name,
                s.student_number,
                s.nisn,
                sc.id AS class_id,
                sc.name AS class_name,
                em.id AS member_id,
                em.active AS member_active
            FROM students s
            JOIN school_classes sc ON sc.id = s.class_id
            LEFT JOIN extracurricular_members em
                ON em.student_id = s.id
               AND em.extracurricular_id = %s
            WHERE s.active IS TRUE
              AND (
                s.full_name ILIKE %s
                OR s.student_number ILIKE %s
                OR s.nisn ILIKE %s
              )
            ORDER BY sc.name ASC, s.full_name ASC
            LIMIT %s
            """,
            (activity_id, like_term, like_term, like_term, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def fetch_extracurricular_attendance_for_date(
    activity_id: int,
    attendance_date: date,
) -> Dict[int, Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT student_id, status, note, recorded_by, recorded_at, updated_at
            FROM extracurricular_attendance_records
            WHERE extracurricular_id = %s
              AND attendance_date = %s
            """,
            (activity_id, attendance_date),
        )
        rows = cur.fetchall()
    return {int(row["student_id"]): dict(row) for row in rows}


def fetch_extracurricular_attendance_detail(
    activity_id: int,
    attendance_date: date,
) -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                s.full_name,
                sc.name AS class_name,
                ear.status
            FROM extracurricular_attendance_records ear
            JOIN students s ON s.id = ear.student_id
            LEFT JOIN school_classes sc ON sc.id = s.class_id
            WHERE ear.extracurricular_id = %s
              AND ear.attendance_date = %s
            ORDER BY sc.name ASC NULLS LAST, s.full_name ASC
            """,
            (activity_id, attendance_date),
        )
        return [dict(row) for row in cur.fetchall()]


def fetch_extracurricular_evidence_for_date(
    activity_id: int,
    attendance_date: date,
) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                photo_path,
                captured_at,
                latitude,
                longitude,
                accuracy_meters,
                address,
                recorded_at,
                updated_at
            FROM extracurricular_attendance_records
            WHERE extracurricular_id = %s
              AND attendance_date = %s
              AND photo_path IS NOT NULL
            ORDER BY COALESCE(updated_at, recorded_at) DESC
            LIMIT 1
            """,
            (activity_id, attendance_date),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def fetch_extracurricular_photo_options(
    activity_id: int,
    *,
    limit: int = 12,
) -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                photo_path,
                attendance_date,
                MAX(captured_at) AS captured_at
            FROM extracurricular_attendance_records
            WHERE extracurricular_id = %s
              AND photo_path IS NOT NULL
            GROUP BY photo_path, attendance_date
            ORDER BY MAX(captured_at) DESC NULLS LAST, attendance_date DESC
            LIMIT %s
            """,
            (activity_id, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def fetch_extracurricular_attendance_totals_for_date(
    activity_id: int,
    attendance_date: date,
) -> Dict[str, int]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT status, COUNT(*) AS total
            FROM extracurricular_attendance_records
            WHERE extracurricular_id = %s
              AND attendance_date = %s
            GROUP BY status
            """,
            (activity_id, attendance_date),
        )
        rows = cur.fetchall()
    return {row["status"]: int(row["total"] or 0) for row in rows}


def fetch_extracurricular_attendance_totals_for_date_all(
    attendance_date: date,
    *,
    activity_ids: Optional[List[int]] = None,
) -> Dict[str, int]:
    if activity_ids is not None and not activity_ids:
        return {}
    conditions = ["attendance_date = %s"]
    params: List[Any] = [attendance_date]
    if activity_ids is not None:
        conditions.append("extracurricular_id = ANY(%s)")
        params.append(activity_ids)
    where_clause = " AND ".join(conditions)
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT status, COUNT(*) AS total
            FROM extracurricular_attendance_records
            WHERE {where_clause}
            GROUP BY status
            """,
            params,
        )
        rows = cur.fetchall()
    return {row["status"]: int(row["total"] or 0) for row in rows}


def upsert_extracurricular_attendance_entries(
    *,
    activity_id: int,
    recorded_by: int,
    attendance_date: date,
    entries: Iterable[Dict[str, Any]],
    photo_path: Optional[str] = None,
    captured_at: Optional[datetime] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    accuracy_meters: Optional[float] = None,
    address: Optional[str] = None,
) -> None:
    normalized_date = attendance_date
    with get_cursor(commit=True) as cur:
        for entry in entries:
            student_id = entry.get("student_id")
            if student_id is None:
                raise ValueError("student_id wajib diisi untuk setiap entri absensi ekskul.")
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
                INSERT INTO extracurricular_attendance_records (
                    attendance_date,
                    extracurricular_id,
                    student_id,
                    status,
                    note,
                    recorded_by,
                    photo_path,
                    captured_at,
                    latitude,
                    longitude,
                    accuracy_meters,
                    address
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (attendance_date, extracurricular_id, student_id)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    note = EXCLUDED.note,
                    recorded_by = EXCLUDED.recorded_by,
                    photo_path = EXCLUDED.photo_path,
                    captured_at = EXCLUDED.captured_at,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    accuracy_meters = EXCLUDED.accuracy_meters,
                    address = EXCLUDED.address,
                    updated_at = NOW()
                """,
                (
                    normalized_date,
                    activity_id,
                    student_id_int,
                    raw_status,
                    note,
                    recorded_by,
                    photo_path,
                    captured_at,
                    latitude,
                    longitude,
                    accuracy_meters,
                    address,
                ),
            )


def fetch_extracurricular_daily_totals(
    *,
    days: int = 7,
    start_date: Optional[date] = None,
    activity_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    if start_date is None:
        if days < 1:
            return []
        start_date = date.today() - timedelta(days=days - 1)
    if activity_ids is not None and not activity_ids:
        return []
    conditions = ["attendance_date >= %s"]
    params: List[Any] = [start_date]
    if activity_ids is not None:
        conditions.append("extracurricular_id = ANY(%s)")
        params.append(activity_ids)
    where_clause = " AND ".join(conditions)
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                attendance_date,
                COUNT(*) FILTER (WHERE status = 'masuk') AS masuk,
                COUNT(*) FILTER (WHERE status = 'alpa') AS alpa,
                COUNT(*) FILTER (WHERE status = 'izin') AS izin,
                COUNT(*) FILTER (WHERE status = 'sakit') AS sakit
            FROM extracurricular_attendance_records
            WHERE {where_clause}
            GROUP BY attendance_date
            ORDER BY attendance_date ASC
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]


def fetch_extracurricular_recent_attendance(
    limit: int = 8,
    *,
    activity_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    if activity_ids is not None and not activity_ids:
        return []
    conditions = []
    params: List[Any] = []
    if activity_ids is not None:
        conditions.append("ear.extracurricular_id = ANY(%s)")
        params.append(activity_ids)
    where_clause = f"AND {' AND '.join(conditions)}" if conditions else ""
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                ear.attendance_date,
                ear.extracurricular_id,
                e.name AS extracurricular_name,
                COUNT(*) FILTER (WHERE ear.status = 'masuk') AS masuk,
                COUNT(*) FILTER (WHERE ear.status = 'alpa') AS alpa,
                COUNT(*) FILTER (WHERE ear.status = 'izin') AS izin,
                COUNT(*) FILTER (WHERE ear.status = 'sakit') AS sakit,
                MAX(COALESCE(ear.updated_at, ear.recorded_at)) AS last_updated
            FROM extracurricular_attendance_records ear
            JOIN extracurriculars e ON e.id = ear.extracurricular_id
            {where_clause}
            GROUP BY ear.attendance_date, ear.extracurricular_id, e.name
            ORDER BY MAX(COALESCE(ear.updated_at, ear.recorded_at)) DESC
            LIMIT %s
            """,
            (*params, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def fetch_extracurricular_evidence_sessions(
    limit: int = 8,
    *,
    activity_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    if activity_ids is not None and not activity_ids:
        return []
    conditions = ["ear.photo_path IS NOT NULL"]
    params: List[Any] = []
    if activity_ids is not None:
        conditions.append("ear.extracurricular_id = ANY(%s)")
        params.append(activity_ids)
    where_clause = " AND ".join(conditions)
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                ear.attendance_date,
                ear.extracurricular_id,
                e.name AS extracurricular_name,
                MAX(ear.captured_at) AS captured_at,
                MAX(ear.photo_path) AS photo_path,
                MAX(ear.latitude) AS latitude,
                MAX(ear.longitude) AS longitude,
                MAX(ear.accuracy_meters) AS accuracy_meters,
                MAX(ear.address) AS address,
                COUNT(*) AS total_entries,
                COUNT(*) FILTER (WHERE ear.status = 'masuk') AS masuk,
                COUNT(*) FILTER (WHERE ear.status = 'alpa') AS alpa,
                COUNT(*) FILTER (WHERE ear.status = 'izin') AS izin,
                COUNT(*) FILTER (WHERE ear.status = 'sakit') AS sakit,
                MAX(COALESCE(ear.captured_at, ear.recorded_at)) AS last_activity_at
            FROM extracurricular_attendance_records ear
            JOIN extracurriculars e ON e.id = ear.extracurricular_id
            WHERE {where_clause}
            GROUP BY ear.attendance_date, ear.extracurricular_id, e.name
            ORDER BY last_activity_at DESC
            LIMIT %s
            """,
            (*params, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def fetch_extracurricular_attendance_history(
    activity_id: int,
    *,
    limit: int = 10,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            WITH daily AS (
                SELECT
                    attendance_date,
                    COUNT(*) AS total_students,
                    MAX(COALESCE(captured_at, recorded_at)) AS last_activity_at
                FROM extracurricular_attendance_records
                WHERE extracurricular_id = %s
                GROUP BY attendance_date
            )
            SELECT
                d.attendance_date,
                d.total_students,
                (
                    SELECT ear.photo_path
                    FROM extracurricular_attendance_records ear
                    WHERE ear.extracurricular_id = %s
                      AND ear.attendance_date = d.attendance_date
                      AND ear.photo_path IS NOT NULL
                    ORDER BY COALESCE(ear.captured_at, ear.recorded_at) DESC
                    LIMIT 1
                ) AS photo_path,
                d.last_activity_at
            FROM daily d
            ORDER BY d.attendance_date DESC, d.last_activity_at DESC
            LIMIT %s OFFSET %s
            """,
            (activity_id, activity_id, limit, offset),
        )
        return [dict(row) for row in cur.fetchall()]
