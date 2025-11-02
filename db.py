import os
from typing import Optional, List, Dict, Any, Tuple
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

_CHAT_TOPIC_AVAILABLE: Optional[bool] = None
MAX_TWITTER_LOG_ROWS = max(0, int(os.getenv("TWITTER_LOG_MAX_ROWS", "100") or 100))
DEFAULT_LIMITED_QUOTA = 3
LIMIT_COOLDOWN_HOURS = 24
DEFAULT_LIMITED_REASON = (
    "Akses Gmail: maksimal 3 chat per 24 jam. "
    "Kalau mau unlimited, pakai akun belajar.id atau Telegram."
)


def _chat_logs_has_topic_column(force_refresh: bool = False) -> bool:
    """
    Periksa sekali apakah tabel chat_logs memiliki kolom 'topic'.
    Hasil dicegah supaya query berikutnya lebih cepat dan stabil.
    """
    global _CHAT_TOPIC_AVAILABLE
    if _CHAT_TOPIC_AVAILABLE is not None and not force_refresh:
        return _CHAT_TOPIC_AVAILABLE

    query = """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'chat_logs'
          AND column_name = 'topic'
        LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(query)
        _CHAT_TOPIC_AVAILABLE = cur.fetchone() is not None
    return _CHAT_TOPIC_AVAILABLE

def _ensure_chat_logs_schema() -> None:
    """Pastikan tabel chat_logs dan semua kolomnya tersedia."""
    global _CHAT_TOPIC_AVAILABLE
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_logs (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                username TEXT,
                text TEXT,
                role TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                response_time_ms INTEGER
            );
            """
        )
        # Tambahkan kolom 'topic' jika belum ada, untuk menjaga kompatibilitas
        if not _chat_logs_has_topic_column(force_refresh=True):
            cur.execute("ALTER TABLE chat_logs ADD COLUMN topic TEXT")
            _CHAT_TOPIC_AVAILABLE = True  # Update cache
    conn.commit()

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


def _column_exists(table: str, column: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = %s
              AND column_name = %s
            LIMIT 1
            """,
            (table, column),
        )
        return cur.fetchone() is not None


def _ensure_column(table: str, column: str, ddl: str) -> bool:
    if _column_exists(table, column):
        return False
    with conn.cursor() as cur:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
    conn.commit()
    return True


def _ensure_user_schema() -> None:
    """Pastikan tabel untuk pengguna web (web_users) tersedia."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS web_users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                full_name TEXT,
                photo_url TEXT,
                last_login TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                auth_provider TEXT,
                access_tier TEXT NOT NULL DEFAULT 'full',
                quota_limit INTEGER,
                quota_remaining INTEGER,
                quota_reset_at TIMESTAMPTZ,
                limited_reason TEXT
            );
            """
        )
    conn.commit()
    # Tambahkan kolom baru jika belum ada (untuk versi lama)
    altered = False
    altered |= _ensure_column(
        "web_users",
        "auth_provider",
        "auth_provider TEXT",
    )
    altered |= _ensure_column(
        "web_users",
        "access_tier",
        "access_tier TEXT NOT NULL DEFAULT 'full'",
    )
    altered |= _ensure_column(
        "web_users",
        "quota_limit",
        "quota_limit INTEGER",
    )
    altered |= _ensure_column(
        "web_users",
        "quota_remaining",
        "quota_remaining INTEGER",
    )
    altered |= _ensure_column(
        "web_users",
        "quota_reset_at",
        "quota_reset_at TIMESTAMPTZ",
    )
    altered |= _ensure_column(
        "web_users",
        "limited_reason",
        "limited_reason TEXT",
    )
    if altered:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE web_users
                SET access_tier = COALESCE(access_tier, 'full')
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
    normalized_topic: Optional[str] = None
    if topic is not None:
        clean_topic = str(topic).strip().lower()
        normalized_topic = clean_topic or None

    use_topic = _chat_logs_has_topic_column()
    inserted_id: Optional[int] = None

    with conn.cursor() as cur:
        if use_topic:
            cur.execute(
                """
                INSERT INTO chat_logs (user_id, username, text, role, topic, created_at, response_time_ms)
                VALUES (%s, %s, %s, %s, %s, NOW(), %s)
                RETURNING id
                """,
                (user_id, username, message, role, normalized_topic, response_time_ms),
            )
        else:
            cur.execute(
                """
                INSERT INTO chat_logs (user_id, username, text, role, created_at, response_time_ms)
                VALUES (%s, %s, %s, %s, NOW(), %s)
                RETURNING id
                """,
                (user_id, username, message, role, response_time_ms),
            )
        row = cur.fetchone()
        if row:
            inserted_id = int(row[0])

        if normalized_topic and inserted_id and not use_topic:
            topic_supported = _chat_logs_has_topic_column(force_refresh=True)
            if not topic_supported:
                try:
                    _ensure_chat_logs_schema()
                except Exception:
                    topic_supported = False
                else:
                    topic_supported = _chat_logs_has_topic_column(force_refresh=True)
            if topic_supported:
                cur.execute(
                    "UPDATE chat_logs SET topic = %s WHERE id = %s",
                    (normalized_topic, inserted_id),
                )
    conn.commit()
    return inserted_id

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

def get_or_create_web_user(
    email: str,
    full_name: Optional[str],
    photo_url: Optional[str] = None,
    *,
    access_tier: str = "full",
    auth_provider: Optional[str] = None,
    quota_limit: Optional[int] = None,
    limited_reason: Optional[str] = None,
) -> dict:
    """Ambil user berdasarkan email, atau buat jika belum ada, lalu perbarui informasi login."""
    _ensure_user_schema()
    now_utc = datetime.now(timezone.utc)
    normalized_tier = (access_tier or "full").strip().lower()
    if normalized_tier not in {"full", "limited"}:
        normalized_tier = "full"

    is_limited = normalized_tier == "limited"
    desired_quota_limit = (
        quota_limit
        if quota_limit is not None
        else (DEFAULT_LIMITED_QUOTA if is_limited else None)
    )
    effective_reason = (
        limited_reason
        if (limited_reason and is_limited)
        else (DEFAULT_LIMITED_REASON if is_limited else None)
    )

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                id, email, full_name, photo_url, last_login,
                auth_provider, access_tier, quota_limit,
                quota_remaining, quota_reset_at, limited_reason
            FROM web_users
            WHERE email = %s
            """,
            (email,),
        )
        existing_user = cur.fetchone()
        if existing_user:
            update_clauses = [
                "full_name = COALESCE(%s, full_name)",
                "photo_url = COALESCE(%s, photo_url)",
                "last_login = %s",
            ]
            params: List[Any] = [full_name, photo_url, now_utc]

            if auth_provider:
                update_clauses.append("auth_provider = COALESCE(%s, auth_provider)")
                params.append(auth_provider)

            if existing_user.get("access_tier") != normalized_tier:
                update_clauses.append("access_tier = %s")
                params.append(normalized_tier)

            if is_limited:
                limit_value = desired_quota_limit or DEFAULT_LIMITED_QUOTA
                if existing_user.get("quota_limit") != limit_value:
                    update_clauses.append("quota_limit = %s")
                    params.append(limit_value)
                if (
                    existing_user.get("quota_remaining") is None
                    or existing_user.get("access_tier") != "limited"
                ):
                    update_clauses.append("quota_remaining = %s")
                    params.append(limit_value)
                    update_clauses.append("quota_reset_at = NULL")
                if effective_reason:
                    update_clauses.append("limited_reason = %s")
                    params.append(effective_reason)
            else:
                update_clauses.extend(
                    [
                        "quota_limit = NULL",
                        "quota_remaining = NULL",
                        "quota_reset_at = NULL",
                        "limited_reason = NULL",
                    ]
                )

            query = f"""
                UPDATE web_users
                SET {', '.join(update_clauses)}
                WHERE email = %s
                RETURNING
                    id, email, full_name, photo_url, last_login,
                    auth_provider, access_tier, quota_limit,
                    quota_remaining, quota_reset_at, limited_reason
            """
            params.append(email)
            cur.execute(query, params)
            updated_user = cur.fetchone()
            conn.commit()
            return updated_user or existing_user

        cur.execute(
            """
            INSERT INTO web_users (
                email,
                full_name,
                photo_url,
                last_login,
                auth_provider,
                access_tier,
                quota_limit,
                quota_remaining,
                quota_reset_at,
                limited_reason
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING
                id, email, full_name, photo_url, last_login,
                auth_provider, access_tier, quota_limit,
                quota_remaining, quota_reset_at, limited_reason
            """,
            (
                email,
                full_name,
                photo_url,
                now_utc,
                auth_provider,
                normalized_tier,
                desired_quota_limit,
                desired_quota_limit if is_limited else None,
                None,
                effective_reason,
            ),
        )
        new_user = cur.fetchone()
    conn.commit()
    return new_user

def _maybe_reset_quota(
    cur,
    user_id: int,
    row: Dict[str, Any],
    now: datetime,
) -> Tuple[Dict[str, Any], bool]:
    """Reset kuota user terbatas jika cooldown sudah lewat."""
    updated = False
    if (row.get("access_tier") or "full") != "limited":
        return row, updated

    limit_value = row.get("quota_limit") or DEFAULT_LIMITED_QUOTA
    if row.get("quota_limit") != limit_value:
        cur.execute(
            "UPDATE web_users SET quota_limit = %s WHERE id = %s",
            (limit_value, user_id),
        )
        row["quota_limit"] = limit_value
        updated = True

    quota_remaining = row.get("quota_remaining")
    reset_at = row.get("quota_reset_at")

    if quota_remaining is None:
        cur.execute(
            """
            UPDATE web_users
            SET quota_remaining = %s,
                quota_reset_at = NULL
            WHERE id = %s
            """,
            (limit_value, user_id),
        )
        row["quota_remaining"] = limit_value
        row["quota_reset_at"] = None
        updated = True
        return row, updated

    if reset_at and reset_at <= now:
        cur.execute(
            """
            UPDATE web_users
            SET quota_remaining = %s,
                quota_reset_at = NULL
            WHERE id = %s
            """,
            (limit_value, user_id),
        )
        row["quota_remaining"] = limit_value
        row["quota_reset_at"] = None
        updated = True

    return row, updated


def get_chat_quota_status(user_id: int) -> Dict[str, Any]:
    """Ambil status kuota chat user web, sekaligus reset jika cooldown selesai."""
    _ensure_user_schema()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                id, access_tier, quota_limit,
                quota_remaining, quota_reset_at, limited_reason
            FROM web_users
            WHERE id = %s
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return {
                "access_tier": "full",
                "quota_limit": None,
                "quota_remaining": None,
                "quota_reset_at": None,
                "limited_reason": None,
            }

        now = datetime.now(timezone.utc)
        row, updated = _maybe_reset_quota(cur, user_id, row, now)
        if updated:
            conn.commit()
        return {
            "access_tier": row.get("access_tier") or "full",
            "quota_limit": row.get("quota_limit"),
            "quota_remaining": row.get("quota_remaining"),
            "quota_reset_at": row.get("quota_reset_at"),
            "limited_reason": row.get("limited_reason"),
        }


def consume_chat_quota(user_id: int) -> Dict[str, Any]:
    """
    Kurangi kuota chat user terbatas sebanyak 1.
    Mengembalikan detail status kuota serta flag apakah request boleh dilanjut.
    """
    _ensure_user_schema()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                id, access_tier, quota_limit,
                quota_remaining, quota_reset_at, limited_reason
            FROM web_users
            WHERE id = %s
            FOR UPDATE
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            conn.commit()
            return {
                "allowed": False,
                "access_tier": None,
                "quota_limit": None,
                "quota_remaining": None,
                "quota_reset_at": None,
                "limited_reason": None,
                "error": "user_not_found",
            }

        now = datetime.now(timezone.utc)
        row, updated = _maybe_reset_quota(cur, user_id, row, now)
        access_tier = row.get("access_tier") or "full"

        if access_tier != "limited":
            conn.commit()
            return {
                "allowed": True,
                "access_tier": access_tier,
                "quota_limit": row.get("quota_limit"),
                "quota_remaining": row.get("quota_remaining"),
                "quota_reset_at": row.get("quota_reset_at"),
                "limited_reason": row.get("limited_reason"),
            }

        limit_value = row.get("quota_limit") or DEFAULT_LIMITED_QUOTA
        quota_remaining = row.get("quota_remaining")
        reset_at = row.get("quota_reset_at")

        if quota_remaining is None:
            quota_remaining = limit_value
            cur.execute(
                """
                UPDATE web_users
                SET quota_remaining = %s,
                    quota_reset_at = NULL
                WHERE id = %s
                """,
                (quota_remaining, user_id),
            )
            updated = True

        if quota_remaining <= 0:
            if not reset_at:
                reset_at = now + timedelta(hours=LIMIT_COOLDOWN_HOURS)
                cur.execute(
                    "UPDATE web_users SET quota_reset_at = %s WHERE id = %s",
                    (reset_at, user_id),
                )
                updated = True
            conn.commit()
            return {
                "allowed": False,
                "access_tier": access_tier,
                "quota_limit": limit_value,
                "quota_remaining": 0,
                "quota_reset_at": reset_at,
                "limited_reason": row.get("limited_reason") or DEFAULT_LIMITED_REASON,
            }

        new_remaining = max(0, quota_remaining - 1)
        new_reset_at = reset_at
        if new_remaining == 0:
            new_reset_at = now + timedelta(hours=LIMIT_COOLDOWN_HOURS)

        cur.execute(
            """
            UPDATE web_users
            SET quota_remaining = %s,
                quota_reset_at = %s
            WHERE id = %s
            """,
            (new_remaining, new_reset_at, user_id),
        )
        conn.commit()
        return {
            "allowed": True,
            "access_tier": access_tier,
            "quota_limit": limit_value,
            "quota_remaining": new_remaining,
            "quota_reset_at": new_reset_at,
            "limited_reason": row.get("limited_reason") or DEFAULT_LIMITED_REASON,
        }

def _ensure_corruption_schema() -> None:
    """Pastikan tabel untuk laporan korupsi (corruption_reports) tersedia."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS corruption_reports (
                id SERIAL PRIMARY KEY,
                ticket_id TEXT UNIQUE NOT NULL,
                user_id BIGINT,
                status TEXT NOT NULL DEFAULT 'open',
                involved TEXT,
                location TEXT,
                time TEXT,
                chronology TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CHECK (status IN ('open', 'in_progress', 'resolved', 'archived'))
            );
            """
        )
    conn.commit()

def record_corruption_report(data: Dict[str, Any]) -> Optional[int]:
    """Simpan laporan korupsi ke tabel khusus."""
    if not data or not data.get("ticket_id"):
        return None

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO corruption_reports (
                ticket_id, user_id, status, involved, location, time, chronology
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                data.get("ticket_id"),
                data.get("user_id"),
                data.get("status", "open"),
                data.get("involved"),
                data.get("location"),
                data.get("time"),
                data.get("chronology"),
            ),
        )
        row = cur.fetchone()
    conn.commit()
    return int(row[0]) if row else None

def get_corruption_report(ticket_id: str) -> Optional[Dict[str, Any]]:
    """Ambil detail laporan korupsi berdasarkan tiket."""
    if not ticket_id:
        return None

    normalized_ticket = ticket_id.strip().upper()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                ticket_id,
                status,
                involved,
                location,
                time,
                chronology,
                created_at,
                updated_at
            FROM corruption_reports
            WHERE ticket_id = %s
            """,
            (normalized_ticket,),
        )
        report = cur.fetchone()

    return report

def _ensure_twitter_log_schema() -> None:
    """Pastikan tabel penyimpanan log worker Twitter tersedia."""
    with conn.cursor() as cur:
        cur.execute(
            """
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
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_twitter_worker_logs_created
            ON twitter_worker_logs (created_at DESC);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_twitter_worker_logs_level
            ON twitter_worker_logs (level);
            """
        )
    conn.commit()

def record_twitter_log(
    level: str,
    message: str,
    *,
    tweet_id: Optional[int] = None,
    twitter_user_id: Optional[int] = None,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """Simpan log worker Twitter ke database untuk dipantau via dashboard."""
    if not message:
        return
    clean_level = (level or "INFO").strip().upper()
    clean_message = message.strip()
    if not clean_message:
        return
    if len(clean_message) > 4000:
        clean_message = clean_message[:4000]

    context_payload: Optional[Dict[str, Any]] = None
    if context:
        context_payload = {}
        for key, value in context.items():
            if value is None:
                continue
            if isinstance(value, (str, int, float, bool, dict, list)):
                context_payload[key] = value
            else:
                context_payload[key] = str(value)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO twitter_worker_logs (level, message, context, tweet_id, twitter_user_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                clean_level,
                clean_message,
                Json(context_payload) if context_payload else None,
                tweet_id,
                twitter_user_id,
            ),
        )
        if MAX_TWITTER_LOG_ROWS > 0:
            cur.execute(
                """
                DELETE FROM twitter_worker_logs
                WHERE id NOT IN (
                    SELECT id
                    FROM twitter_worker_logs
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                )
                """,
                (MAX_TWITTER_LOG_ROWS,),
            )
    conn.commit()

# Call schema functions on startup
_ensure_chat_logs_schema()
_ensure_bullying_schema()
_ensure_psych_schema()
_ensure_user_schema()
_ensure_corruption_schema()
_ensure_twitter_log_schema()
