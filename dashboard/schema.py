"""Database schema helpers for the dashboard application."""

from __future__ import annotations

from typing import Iterable

from .db_access import get_cursor
from tka_schema import ensure_tka_schema as ensure_tka_schema_tables

_DASHBOARD_USERS_SQL = """
CREATE TABLE IF NOT EXISTS dashboard_users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer',
    nrk TEXT,
    nip TEXT,
    jabatan TEXT,
    degree_prefix TEXT,
    degree_suffix TEXT,
    no_tester_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ
);
"""

_SCHOOL_CLASSES_SQL = """
CREATE TABLE IF NOT EXISTS school_classes (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    academic_year TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_STUDENTS_SQL = """
CREATE TABLE IF NOT EXISTS students (
    id SERIAL PRIMARY KEY,
    class_id INTEGER NOT NULL REFERENCES school_classes(id) ON DELETE CASCADE,
    full_name TEXT NOT NULL,
    student_number TEXT,
    sequence INTEGER,
    nisn TEXT,
    gender TEXT,
    birth_place TEXT,
    birth_date DATE,
    religion TEXT,
    address_line TEXT,
    rt TEXT,
    rw TEXT,
    kelurahan TEXT,
    kecamatan TEXT,
    father_name TEXT,
    mother_name TEXT,
    nik TEXT,
    kk_number TEXT,
    metadata JSONB,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (class_id, full_name)
);
"""

_STUDENTS_CLASS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_students_class_id
ON students (class_id);
"""

_ATTENDANCE_RECORDS_SQL = """
CREATE TABLE IF NOT EXISTS attendance_records (
    id SERIAL PRIMARY KEY,
    attendance_date DATE NOT NULL,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    class_id INTEGER NOT NULL REFERENCES school_classes(id) ON DELETE CASCADE,
    teacher_id INTEGER REFERENCES dashboard_users(id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    note TEXT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (attendance_date, student_id),
    CONSTRAINT attendance_records_status_check CHECK (status IN ('masuk', 'alpa', 'izin', 'sakit'))
);
"""

_ATTENDANCE_CLASS_DATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_attendance_records_class_date
ON attendance_records (class_id, attendance_date);
"""

_TEACHER_ATTENDANCE_SQL = """
CREATE TABLE IF NOT EXISTS teacher_attendance_records (
    id SERIAL PRIMARY KEY,
    attendance_date DATE NOT NULL,
    teacher_id INTEGER NOT NULL REFERENCES dashboard_users(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    note TEXT,
    recorded_by INTEGER REFERENCES dashboard_users(id) ON DELETE SET NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (attendance_date, teacher_id),
    CONSTRAINT teacher_attendance_records_status_check CHECK (status IN ('masuk', 'alpa', 'izin', 'sakit'))
);
"""

_TEACHER_ATTENDANCE_DATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_teacher_attendance_records_date
ON teacher_attendance_records (attendance_date);
"""

_ATTENDANCE_LATE_STUDENTS_SQL = """
CREATE TABLE IF NOT EXISTS attendance_late_students (
    id SERIAL PRIMARY KEY,
    attendance_date DATE NOT NULL,
    class_id INTEGER REFERENCES school_classes(id) ON DELETE SET NULL,
    student_name TEXT NOT NULL,
    class_label TEXT,
    arrival_time TEXT,
    reason TEXT,
    recorded_by INTEGER REFERENCES dashboard_users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_ATTENDANCE_LATE_DATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_attendance_late_date
ON attendance_late_students (attendance_date);
"""

_ATTENDANCE_LATE_CLASS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_attendance_late_class
ON attendance_late_students (class_id);
"""

_BULLYING_REPORTS_SQL = """
CREATE TABLE IF NOT EXISTS bullying_reports (
    id SERIAL PRIMARY KEY,
    chat_log_id INTEGER UNIQUE REFERENCES chat_logs(id) ON DELETE CASCADE,
    user_id BIGINT,
    username TEXT,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    priority BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT,
    last_updated_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    category TEXT NOT NULL DEFAULT 'general',
    severity TEXT,
    metadata JSONB,
    assigned_to TEXT,
    due_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    escalated BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT bullying_reports_status_check CHECK (status IN ('pending', 'in_progress', 'resolved', 'spam'))
);
"""

_BULLYING_STATUS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_bullying_reports_status
ON bullying_reports (status);
"""

_BULLYING_EVENTS_SQL = """
CREATE TABLE IF NOT EXISTS bullying_report_events (
    id SERIAL PRIMARY KEY,
    report_id INTEGER REFERENCES bullying_reports(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    actor TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_BULLYING_EVENTS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_bullying_report_events_report
ON bullying_report_events (report_id);
"""

_NOTIFICATIONS_SQL = """
CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT,
    status TEXT NOT NULL DEFAULT 'unread' CHECK (status IN ('unread', 'read', 'archived')),
    link TEXT,
    reference_table TEXT,
    reference_id INTEGER,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at TIMESTAMPTZ
);
"""

_NOTIFICATIONS_INDEX_STATUS = """
CREATE INDEX IF NOT EXISTS idx_notifications_status
ON notifications (status);
"""

_NOTIFICATIONS_INDEX_CREATED = """
CREATE INDEX IF NOT EXISTS idx_notifications_created_at
ON notifications (created_at DESC);
"""

_TWITTER_LOGS_SQL = """
CREATE TABLE IF NOT EXISTS twitter_worker_logs (
    id SERIAL PRIMARY KEY,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    context JSONB,
    tweet_id BIGINT,
    twitter_user_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_TWITTER_LOGS_INDEX_CREATED = """
CREATE INDEX IF NOT EXISTS idx_twitter_worker_logs_created
ON twitter_worker_logs (created_at DESC);
"""

_TWITTER_LOGS_INDEX_LEVEL = """
CREATE INDEX IF NOT EXISTS idx_twitter_worker_logs_level
ON twitter_worker_logs (level);
"""

_TELEGRAM_USERS_SQL = """
CREATE TABLE IF NOT EXISTS telegram_users (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT UNIQUE NOT NULL,
    username TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_message_preview TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','under_review')),
    status_reason TEXT,
    status_changed_at TIMESTAMPTZ,
    status_changed_by TEXT,
    metadata JSONB
);
"""

_TELEGRAM_USERS_INDEX_STATUS = """
CREATE INDEX IF NOT EXISTS idx_telegram_users_status ON telegram_users (status);
"""


def ensure_dashboard_schema() -> None:
    """Create core dashboard tables when they do not yet exist."""
    statements: Iterable[str] = (
        _DASHBOARD_USERS_SQL,
        _SCHOOL_CLASSES_SQL,
        _STUDENTS_SQL,
        _STUDENTS_CLASS_INDEX_SQL,
        _ATTENDANCE_RECORDS_SQL,
        _ATTENDANCE_CLASS_DATE_INDEX_SQL,
        _TEACHER_ATTENDANCE_SQL,
        _TEACHER_ATTENDANCE_DATE_INDEX_SQL,
        _ATTENDANCE_LATE_STUDENTS_SQL,
        _ATTENDANCE_LATE_DATE_INDEX_SQL,
        _ATTENDANCE_LATE_CLASS_INDEX_SQL,
        _BULLYING_REPORTS_SQL,
        _BULLYING_STATUS_INDEX_SQL,
        _BULLYING_EVENTS_SQL,
        _BULLYING_EVENTS_INDEX_SQL,
        _NOTIFICATIONS_SQL,
        _NOTIFICATIONS_INDEX_STATUS,
        _NOTIFICATIONS_INDEX_CREATED,
        _TWITTER_LOGS_SQL,
        _TWITTER_LOGS_INDEX_CREATED,
        _TWITTER_LOGS_INDEX_LEVEL,
        _TELEGRAM_USERS_SQL,
        _TELEGRAM_USERS_INDEX_STATUS,
        "ALTER TABLE dashboard_users ADD COLUMN IF NOT EXISTS no_tester_enabled BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE dashboard_users ADD COLUMN IF NOT EXISTS nrk TEXT",
        "ALTER TABLE dashboard_users ADD COLUMN IF NOT EXISTS nip TEXT",
        "ALTER TABLE dashboard_users ADD COLUMN IF NOT EXISTS jabatan TEXT",
        "ALTER TABLE dashboard_users ADD COLUMN IF NOT EXISTS degree_prefix TEXT",
        "ALTER TABLE dashboard_users ADD COLUMN IF NOT EXISTS degree_suffix TEXT",
        "ALTER TABLE bullying_reports ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'general'",
        "ALTER TABLE bullying_reports ADD COLUMN IF NOT EXISTS severity TEXT",
        "ALTER TABLE bullying_reports ADD COLUMN IF NOT EXISTS metadata JSONB",
        "ALTER TABLE bullying_reports ADD COLUMN IF NOT EXISTS assigned_to TEXT",
        "ALTER TABLE bullying_reports ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ",
        "ALTER TABLE bullying_reports ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ",
        "ALTER TABLE bullying_reports ADD COLUMN IF NOT EXISTS escalated BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE bullying_reports DROP CONSTRAINT IF EXISTS bullying_reports_status_check",
        "ALTER TABLE bullying_reports ADD CONSTRAINT bullying_reports_status_check CHECK (status IN ('pending', 'in_progress', 'resolved', 'spam'))",
        "ALTER TABLE dashboard_users ADD COLUMN IF NOT EXISTS assigned_class_id INTEGER REFERENCES school_classes(id) ON DELETE SET NULL",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS nisn TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS sequence INTEGER",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS gender TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS birth_place TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS birth_date DATE",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS religion TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS address_line TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS rt TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS rw TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS kelurahan TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS kecamatan TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS father_name TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS mother_name TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS nik TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS kk_number TEXT",
    )
    with get_cursor(commit=True) as cur:
        for statement in statements:
            cur.execute(statement)
        ensure_tka_schema_tables(cur)


__all__ = ["ensure_dashboard_schema"]
