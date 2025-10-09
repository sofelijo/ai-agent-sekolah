import os
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone

import psycopg2
from psycopg2.extras import Json, RealDictCursor
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
    conn_args["sslmode"] = DB_SSLMODE

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
    conn.commit()

def _ensure_psych_schema() -> None:
    """Pastikan tabel laporan konseling psikologis tersedia."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS psych_reports (
                id SERIAL PRIMARY KEY,
                chat_log_id INTEGER REFERENCES chat_logs(id) ON DELETE SET NULL,
                user_id BIGINT,
                username TEXT,
                message TEXT NOT NULL,
                summary TEXT,
                severity TEXT NOT NULL DEFAULT 'general',
                status TEXT NOT NULL DEFAULT 'open',
                metadata JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CHECK (status IN ('open', 'in_progress', 'resolved', 'archived'))
            );
            """
        )
    conn.commit()


def _ensure_user_schema() -> None:
    """Pastikan tabel untuk pengguna web (web_users) tersedia."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS web_users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                full_name TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    conn.commit()

def _calculate_due_at(category: str) -> datetime:
    base = datetime.now(timezone.utc)
    category = (category or "general").lower()
    if category == "sexual":
        return base + timedelta(hours=12)
    if category == "physical":
        return base + timedelta(hours=24)
    return base + timedelta(hours=48)

def record_psych_report(
    chat_log_id: Optional[int],
    user_id: Optional[int],
    username: Optional[str],
    message: str,
    *,
    severity: str = "general",
    status: str = "open",
    summary: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> Optional[int]:
    """Simpan laporan konseling psikologis ke tabel khusus."""
    if not message:
        return None

    payload = Json(metadata) if metadata else None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO psych_reports (
                chat_log_id,
                user_id,
                username,
                message,
                summary,
                severity,
                status,
                metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                chat_log_id,
                user_id,
                username,
                message,
                summary,
                severity,
                status,
                payload,
            ),
        )
        row = cur.fetchone()
    conn.commit()
    return int(row[0]) if row else None

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

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bullying_reports (chat_log_id, user_id, username, description, priority, category, severity, metadata, assigned_to, due_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (chat_log_id) DO NOTHING
            RETURNING id
            """,
            (
                chat_log_id,
                user_id,
                username,
                cleaned_description,
                priority,
                category,
                severity,
                Json(metadata) if metadata else None,
                assigned_to,
                _calculate_due_at(category),
            ),
        )
        row = cur.fetchone()
        if not row:
            conn.commit()
            return None
        report_id = int(row[0])
    conn.commit()
    return report_id

def save_chat(
    user_id: Optional[int],
    username: Optional[str],
    message: Optional[str],
    role: str,
    topic: Optional[str] = None,
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

def get_chat_history(user_id: int, limit: int, offset: int = 0) -> List[Dict[str, Any]]:
    """
    Ambil riwayat chat dengan paginasi, mengembalikan list of dictionaries.
    Urutan: Terbaru di atas (DESC).
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT role, text, created_at FROM chat_logs
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            (user_id, limit, offset),
        )
        return cur.fetchall()

def get_or_create_web_user(email: str, full_name: str) -> dict:
    """Ambil user berdasarkan email, atau buat jika belum ada."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, email, full_name FROM web_users WHERE email = %s", (email,))
        user = cur.fetchone()
        if user:
            return user

        cur.execute(
            "INSERT INTO web_users (email, full_name) VALUES (%s, %s) RETURNING id, email, full_name",
            (email, full_name),
        )
        new_user = cur.fetchone()
        conn.commit()
        return new_user

# Call schema functions on startup
_ensure_bullying_schema()
_ensure_psych_schema()
_ensure_user_schema()
