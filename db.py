import os
from typing import Optional
from datetime import datetime, timedelta, timezone

import psycopg2
from psycopg2.extras import Json
from dotenv import load_dotenv

# Muat variabel dari file .env
load_dotenv()

# Ambil variabel koneksi dari environment
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_SSLMODE = os.getenv("DB_SSLMODE")  # Optional: hanya dipakai jika ada

# Validasi agar semua variabel penting ada
required_vars = {
    "DB_NAME": DB_NAME,
    "DB_USER": DB_USER,
    "DB_PASS": DB_PASS,
    "DB_HOST": DB_HOST,
    "DB_PORT": DB_PORT,
}
for key, value in required_vars.items():
    if not value:
        raise ValueError(
            f"Environment variable '{key}' is not set! Silakan isi di file .env Anda."
        )

# Siapkan argumen koneksi
conn_args = dict(
    dbname=DB_NAME,
    user=DB_USER,
    password=DB_PASS,
    host=DB_HOST,
    port=DB_PORT,
)

# Tambahkan sslmode jika diset di .env
if DB_SSLMODE:
    conn_args["sslmode"] = DB_SSLMODE  # bisa 'require', 'prefer', 'disable', dll

# Koneksi ke PostgreSQL
conn = psycopg2.connect(**conn_args)


def _ensure_bullying_schema() -> None:
    """Pastikan tabel dan kolom pendukung pelaporan bullying tersedia."""
    with conn.cursor() as cur:
        cur.execute(
            """
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
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_bullying_reports_status
            ON bullying_reports (status);
            """
        )
        cur.execute(
            "ALTER TABLE bullying_reports DROP CONSTRAINT IF EXISTS bullying_reports_status_check"
        )
        cur.execute(
            "ALTER TABLE bullying_reports ADD CONSTRAINT bullying_reports_status_check CHECK (status IN ('pending', 'in_progress', 'resolved', 'spam'))"
        )
        cur.execute(
            "ALTER TABLE bullying_reports ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'general'"
        )
        cur.execute("ALTER TABLE bullying_reports ADD COLUMN IF NOT EXISTS severity TEXT")
        cur.execute("ALTER TABLE bullying_reports ADD COLUMN IF NOT EXISTS metadata JSONB")
        cur.execute("ALTER TABLE bullying_reports ADD COLUMN IF NOT EXISTS assigned_to TEXT")
        cur.execute("ALTER TABLE bullying_reports ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ")
        cur.execute("ALTER TABLE bullying_reports ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ")
        cur.execute("ALTER TABLE bullying_reports ADD COLUMN IF NOT EXISTS escalated BOOLEAN NOT NULL DEFAULT FALSE")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bullying_report_events (
                id SERIAL PRIMARY KEY,
                report_id INTEGER REFERENCES bullying_reports(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                actor TEXT,
                payload JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_bullying_report_events_report
            ON bullying_report_events (report_id);
            """
        )

        cur.execute(
            """
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
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_notifications_status
            ON notifications (status);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_notifications_created_at
            ON notifications (created_at DESC);
            """
        )
    conn.commit()


_ensure_bullying_schema()



def _calculate_due_at(category: str) -> datetime:
    base = datetime.now(timezone.utc)
    category = (category or "general").lower()
    if category == "sexual":
        return base + timedelta(hours=12)
    if category == "physical":
        return base + timedelta(hours=24)
    return base + timedelta(hours=48)


def _insert_report_event(cursor, report_id: int, event_type: str, *, actor: Optional[str] = None, payload: Optional[dict] = None) -> None:
    cursor.execute(
        """
        INSERT INTO bullying_report_events (report_id, event_type, actor, payload)
        VALUES (%s, %s, %s, %s)
        """,
        (report_id, event_type, actor, Json(payload) if payload else None),
    )



def create_notification(
    category: str,
    title: str,
    message: Optional[str] = None,
    *,
    status: str = "unread",
    link: Optional[str] = None,
    reference_table: Optional[str] = None,
    reference_id: Optional[int] = None,
    metadata: Optional[dict] = None,
    cursor=None,
    commit: bool = True,
) -> Optional[int]:
    """Simpan notifikasi baru dan kembalikan id-nya."""
    payload = Json(metadata) if metadata else None
    if cursor is not None:
        cursor.execute(
            """
            INSERT INTO notifications (category, title, message, status, link, reference_table, reference_id, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (category, title, message, status, link, reference_table, reference_id, payload),
        )
        row = cursor.fetchone()
        return int(row[0]) if row else None

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO notifications (category, title, message, status, link, reference_table, reference_id, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (category, title, message, status, link, reference_table, reference_id, payload),
        )
        row = cur.fetchone()
    if commit:
        conn.commit()
    return int(row[0]) if row else None


def save_chat(
    user_id: Optional[int],
    username: Optional[str],
    message: Optional[str],
    role: str,
    topic: Optional[str] = None,  # dipertahankan untuk kompatibilitas
    response_time_ms: Optional[int] = None,
) -> Optional[int]:
    """Simpan chat ke tabel chat_logs dan kembalikan id baris yang dibuat."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chat_logs (user_id, username, text, role, created_at, response_time_ms)
            VALUES (%s, %s, %s, %s, NOW(), %s)
            RETURNING id
            """,
            (user_id, username, message, role, response_time_ms),
        )
        row = cur.fetchone()
    conn.commit()
    return int(row[0]) if row else None


def get_chat_history(user_id, limit=3):
    """
    Ambil n chat terakhir untuk user_id tertentu.
    Return dalam urutan lama -> baru.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT role, text FROM chat_logs
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        rows = cur.fetchall()
        return rows[::-1]  # Balik urutan agar kronologis


def record_bullying_report(
    chat_log_id: int,
    user_id: Optional[int],
    username: Optional[str],
    description: str,
    *,
    priority: bool = True,
    category: str = "general",
    severity: Optional[str] = None,
    metadata: Optional[dict] = None,
    assigned_to: Optional[str] = None,
) -> Optional[int]:
    """Catat laporan bullying baru dengan status awal 'pending' dan buat notifikasi."""
    if chat_log_id is None:
        raise ValueError("chat_log_id wajib diisi untuk laporan bullying")

    cleaned_description = (description or "").strip()
    if not cleaned_description:
        return None

    merged_metadata = dict(metadata or {})
    merged_metadata.setdefault("category", category)
    if severity:
        merged_metadata["severity"] = severity
    merged_metadata["chat_log_id"] = chat_log_id

    due_at = _calculate_due_at(category)
    merged_metadata.setdefault("due_at", due_at.isoformat())

    effective_priority = priority or category != "general"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bullying_reports (
                chat_log_id,
                user_id,
                username,
                description,
                priority,
                category,
                severity,
                metadata,
                assigned_to,
                due_at,
                resolved_at,
                escalated
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (chat_log_id) DO NOTHING
            RETURNING id
            """,
            (
                chat_log_id,
                user_id,
                username,
                cleaned_description,
                effective_priority,
                category,
                severity,
                Json(merged_metadata) if merged_metadata else None,
                assigned_to,
                due_at,
                None,
                False,
            ),
        )
        row = cur.fetchone()
        if not row:
            conn.commit()
            return None

        report_id = int(row[0])

        title_map = {
            "sexual": "Laporan Pelecehan Seksual",
            "physical": "Laporan Kekerasan Fisik",
            "general": "Laporan Bullying Baru",
        }
        title = title_map.get(category, title_map["general"])
        snippet = (cleaned_description[:160] + "...") if len(cleaned_description) > 160 else cleaned_description
        link = f"/bullying-reports?highlight={report_id}"
        create_notification(
            category="bullying",
            title=title,
            message=snippet,
            link=link,
            reference_table="bullying_reports",
            reference_id=report_id,
            metadata={"report_id": report_id, "category": category},
            cursor=cur,
            commit=False,
        )
        _insert_report_event(
            cur,
            report_id,
            "created",
            actor=username,
            payload={
                "category": category,
                "severity": severity,
                "due_at": due_at.isoformat(),
                "assigned_to": assigned_to,
            },
        )

    conn.commit()
    return report_id
