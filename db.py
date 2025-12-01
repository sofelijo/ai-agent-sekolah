import os
import random
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta, timezone

import psycopg2
from psycopg2 import extensions, InterfaceError, OperationalError, ProgrammingError
from psycopg2.extras import Json, RealDictCursor
from dotenv import load_dotenv
from account_status import ACCOUNT_STATUS_CHOICES, ACCOUNT_STATUS_ACTIVE
from tka_schema import ensure_tka_schema as ensure_tka_schema_tables

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
_CHAT_CHANNEL_AVAILABLE: Optional[bool] = None
MAX_TWITTER_LOG_ROWS = max(0, int(os.getenv("TWITTER_LOG_MAX_ROWS", "100") or 100))
DEFAULT_LIMITED_QUOTA = 3
LIMIT_COOLDOWN_HOURS = 24
DEFAULT_LIMITED_REASON = (
    "Akses Gmail: maksimal 3 chat per 24 jam. "
    "Kalau mau unlimited, pakai akun belajar.id atau Telegram."
)
STATUS_ENUM_SQL = ", ".join(f"'{status}'" for status in ACCOUNT_STATUS_CHOICES)
CHAT_CHANNEL_EXPRESSION = (
    "COALESCE(channel, CASE WHEN topic = 'web' THEN 'web' "
    "WHEN topic = 'twitter' THEN 'twitter' ELSE 'telegram' END)"
)
VALID_TKA_DIFFICULTIES = {"easy", "medium", "hard"}
DEFAULT_TKA_DIFFICULTY_MIX = {"easy": 10, "medium": 5, "hard": 5}
DEFAULT_TKA_TIME_LIMIT = 15
DEFAULT_TKA_QUESTION_COUNT = 20
VALID_TKA_OPTION_KEYS = ("A", "B", "C", "D", "E", "F", "T", "F")
DEFAULT_TKA_PRESETS = {
    "mudah": {"easy": 10, "medium": 5, "hard": 5},
    "sedang": {"easy": 5, "medium": 10, "hard": 5},
    "susah": {"easy": 5, "medium": 5, "hard": 10},
}
DEFAULT_TKA_PRESET_KEY = "mudah"
VALID_TKA_GRADE_LEVELS = {"sd6", "smp3", "sma"}
DEFAULT_TKA_GRADE_LEVEL = "sd6"
GRADE_LABELS = {
    "sd6": "SD Kelas 6",
    "smp3": "SMP Kelas 3",
    "sma": "SMA",
}
DEFAULT_TKA_COMPOSITE_DURATION = 120
TKA_SECTION_TEMPLATES = [
    {
        "key": "matematika",
        "label": "Matematika",
        "subject_area": "matematika",
        "question_format": "multiple_choice",
        "question_count": 40,
    },
    {
        "key": "bahasa_pg",
        "label": "Bahasa Indonesia · Pilihan Ganda",
        "subject_area": "bahasa_indonesia",
        "question_format": "multiple_choice",
        "question_count": 40,
    },
    {
        "key": "bahasa_tf",
        "label": "Bahasa Indonesia · Benar/Salah",
        "subject_area": "bahasa_indonesia",
        "question_format": "true_false",
        "question_count": 10,
    },
]
TKA_SECTION_KEY_ORDER = [template["key"] for template in TKA_SECTION_TEMPLATES]
TKA_METADATA_SECTION_CONFIG_KEY = "section_config"
MAX_STIMULUS_QUESTIONS = 5
MIN_STIMULUS_QUESTIONS = 3
_TKA_SCHEMA_READY: Optional[bool] = None


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


def _chat_logs_has_channel_column(force_refresh: bool = False) -> bool:
    """Cek keberadaan kolom channel pada chat_logs."""
    global _CHAT_CHANNEL_AVAILABLE
    if _CHAT_CHANNEL_AVAILABLE is not None and not force_refresh:
        return _CHAT_CHANNEL_AVAILABLE

    query = """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'chat_logs'
          AND column_name = 'channel'
        LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(query)
        _CHAT_CHANNEL_AVAILABLE = cur.fetchone() is not None
    return _CHAT_CHANNEL_AVAILABLE

def _ensure_chat_logs_schema() -> None:
    """Pastikan tabel chat_logs dan semua kolomnya tersedia."""
    global _CHAT_TOPIC_AVAILABLE, _CHAT_CHANNEL_AVAILABLE
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
        if not _chat_logs_has_channel_column(force_refresh=True):
            cur.execute("ALTER TABLE chat_logs ADD COLUMN channel TEXT")
            cur.execute(
                """
                UPDATE chat_logs
                SET channel = CASE
                    WHEN topic = 'web' THEN 'web'
                    WHEN topic = 'twitter' THEN 'twitter'
                    ELSE 'telegram'
                END
                WHERE channel IS NULL
                """
            )
            cur.execute("ALTER TABLE chat_logs ALTER COLUMN channel SET DEFAULT 'telegram'")
            _CHAT_CHANNEL_AVAILABLE = True
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


def _ensure_tka_schema(force_refresh: bool = False) -> None:
    """Pastikan tabel pendukung Latihan TKA tersedia."""
    global _TKA_SCHEMA_READY
    if _TKA_SCHEMA_READY and not force_refresh:
        return
    with conn.cursor() as cur:
        ensure_tka_schema_tables(cur)
    conn.commit()
    _TKA_SCHEMA_READY = True


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


def _constraint_exists(table: str, constraint: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.table_constraints
            WHERE table_schema = current_schema()
              AND table_name = %s
              AND constraint_name = %s
            LIMIT 1
            """,
            (table, constraint),
        )
        return cur.fetchone() is not None


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
                limited_reason TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                status_reason TEXT,
                status_changed_at TIMESTAMPTZ,
                status_changed_by TEXT,
                metadata JSONB,
                CONSTRAINT web_users_status_check CHECK (status IN (%s))
            );
            """
            % STATUS_ENUM_SQL
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
    altered |= _ensure_column(
        "web_users",
        "status",
        f"status TEXT NOT NULL DEFAULT '{ACCOUNT_STATUS_ACTIVE}'",
    )
    altered |= _ensure_column(
        "web_users",
        "status_reason",
        "status_reason TEXT",
    )
    altered |= _ensure_column(
        "web_users",
        "status_changed_at",
        "status_changed_at TIMESTAMPTZ",
    )
    altered |= _ensure_column(
        "web_users",
        "status_changed_by",
        "status_changed_by TEXT",
    )
    altered |= _ensure_column(
        "web_users",
        "metadata",
        "metadata JSONB",
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
    if not _constraint_exists("web_users", "web_users_status_check"):
        with conn.cursor() as cur:
            cur.execute(
                f"""
                ALTER TABLE web_users
                ADD CONSTRAINT web_users_status_check
                CHECK (status IN ({STATUS_ENUM_SQL}))
                """
            )
        conn.commit()


def _backfill_telegram_users() -> None:
    """Buat data user Telegram dari chat_logs jika table kosong/belum lengkap."""
    _ensure_chat_logs_schema()
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO telegram_users (
                telegram_user_id,
                username,
                first_seen_at,
                last_seen_at
            )
            SELECT
                user_id,
                MAX(username) FILTER (WHERE username IS NOT NULL),
                MIN(created_at),
                MAX(created_at)
            FROM chat_logs
            WHERE user_id IS NOT NULL
              AND {CHAT_CHANNEL_EXPRESSION} = 'telegram'
            GROUP BY user_id
            ON CONFLICT (telegram_user_id) DO NOTHING
            """
        )
    conn.commit()


def _ensure_telegram_user_schema() -> None:
    """Pastikan tabel telegram_users tersedia dan terisi dari chat_logs."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS telegram_users (
                id SERIAL PRIMARY KEY,
                telegram_user_id BIGINT UNIQUE NOT NULL,
                username TEXT,
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_message_preview TEXT,
                status TEXT NOT NULL DEFAULT '{ACCOUNT_STATUS_ACTIVE}',
                status_reason TEXT,
                status_changed_at TIMESTAMPTZ,
                status_changed_by TEXT,
                metadata JSONB,
                CONSTRAINT telegram_users_status_check CHECK (status IN ({STATUS_ENUM_SQL}))
            );
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_telegram_users_user
            ON telegram_users (telegram_user_id)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_telegram_users_status
            ON telegram_users (status)
            """
        )
    conn.commit()
    _backfill_telegram_users()


def _sync_telegram_user_profile(
    telegram_user_id: Optional[int],
    username: Optional[str],
    last_message: Optional[str],
) -> None:
    """Upsert profil telegram berdasarkan chat terbaru."""
    if not telegram_user_id:
        return
    _ensure_telegram_user_schema()
    clean_username = (username or "").strip() or None
    preview = (last_message or "").strip()
    if preview:
        preview = preview[:280]
    else:
        preview = None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO telegram_users (
                telegram_user_id,
                username,
                last_message_preview
            )
            VALUES (%s, %s, %s)
            ON CONFLICT (telegram_user_id) DO UPDATE
            SET
                username = COALESCE(EXCLUDED.username, telegram_users.username),
                last_seen_at = NOW(),
                last_message_preview = COALESCE(
                    EXCLUDED.last_message_preview,
                    telegram_users.last_message_preview
                )
            """,
            (telegram_user_id, clean_username, preview),
        )

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


def _resolve_channel(topic: Optional[str]) -> str:
    value = (topic or "").strip().lower()
    if value == "web":
        return "web"
    if value == "twitter":
        return "twitter"
    return "telegram"


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
    use_channel = _chat_logs_has_channel_column()
    channel_value = _resolve_channel(normalized_topic)
    inserted_id: Optional[int] = None

    with conn.cursor() as cur:
        if use_topic and use_channel:
            cur.execute(
                """
                INSERT INTO chat_logs (
                    user_id,
                    username,
                    text,
                    role,
                    topic,
                    channel,
                    created_at,
                    response_time_ms
                )
                VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)
                RETURNING id
                """,
                (
                    user_id,
                    username,
                    message,
                    role,
                    normalized_topic,
                    channel_value,
                    response_time_ms,
                ),
            )
        elif use_topic:
            cur.execute(
                """
                INSERT INTO chat_logs (user_id, username, text, role, topic, created_at, response_time_ms)
                VALUES (%s, %s, %s, %s, %s, NOW(), %s)
                RETURNING id
                """,
                (
                    user_id,
                    username,
                    message,
                    role,
                    normalized_topic,
                    response_time_ms,
                ),
            )
        elif use_channel:
            cur.execute(
                """
                INSERT INTO chat_logs (user_id, username, text, role, channel, created_at, response_time_ms)
                VALUES (%s, %s, %s, %s, %s, NOW(), %s)
                RETURNING id
                """,
                (
                    user_id,
                    username,
                    message,
                    role,
                    channel_value,
                    response_time_ms,
                ),
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
    if channel_value == "telegram" and role == "user" and user_id is not None:
        _sync_telegram_user_profile(user_id, username, message)

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
                quota_remaining, quota_reset_at, limited_reason,
                status, status_reason, status_changed_at,
                status_changed_by, metadata
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
                    quota_remaining, quota_reset_at, limited_reason,
                    status, status_reason, status_changed_at,
                    status_changed_by, metadata
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
                quota_remaining, quota_reset_at, limited_reason,
                status, status_reason, status_changed_at,
                status_changed_by, metadata
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


def get_web_user_status(user_id: int) -> Dict[str, Any]:
    """Ambil status akun web terbaru."""
    _ensure_user_schema()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                id,
                email,
                full_name,
                status,
                status_reason,
                status_changed_at,
                status_changed_by
            FROM web_users
            WHERE id = %s
            """,
            (user_id,),
        )
        row = cur.fetchone()
    if not row:
        return {
            "id": user_id,
            "status": ACCOUNT_STATUS_ACTIVE,
            "status_reason": None,
            "status_changed_at": None,
            "status_changed_by": None,
        }
    return dict(row)


def get_telegram_user_status(user_id: int) -> Dict[str, Any]:
    """Ambil status akun Telegram berdasarkan telegram_user_id."""
    _ensure_telegram_user_schema()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                telegram_user_id,
                username,
                status,
                status_reason,
                status_changed_at,
                status_changed_by
            FROM telegram_users
            WHERE telegram_user_id = %s
            """,
            (user_id,),
        )
        row = cur.fetchone()
    if not row:
        return {
            "telegram_user_id": user_id,
            "status": ACCOUNT_STATUS_ACTIVE,
            "status_reason": None,
            "status_changed_at": None,
            "status_changed_by": None,
        }
    return dict(row)


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

# --- Latihan TKA helpers ----------------------------------------------------


def _coerce_difficulty_mix(raw_mix: Optional[Dict[str, Any]]) -> Dict[str, int]:
    mix = {key: DEFAULT_TKA_DIFFICULTY_MIX.get(key, 0) for key in VALID_TKA_DIFFICULTIES}
    if isinstance(raw_mix, dict):
        for key, value in raw_mix.items():
            if key not in VALID_TKA_DIFFICULTIES:
                continue
            try:
                mix[key] = max(0, int(value))
            except (TypeError, ValueError):
                continue
    total = sum(mix.values())
    if total <= 0:
        mix = DEFAULT_TKA_DIFFICULTY_MIX.copy()
    return mix


def _rebalance_mix_to_total(mix: Dict[str, int], target_total: int) -> Dict[str, int]:
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
    safety = target_total * 3 if target_total > 0 else 30
    while diff != 0 and safety > 0:
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
        safety -= 1
    return result


def _default_section_mix(question_count: int) -> Dict[str, int]:
    if question_count <= 0:
        question_count = sum(DEFAULT_TKA_DIFFICULTY_MIX.values())
    base = {
        "easy": int(round(question_count * 0.4)),
        "medium": int(round(question_count * 0.4)),
        "hard": int(round(question_count * 0.2)),
    }
    return _rebalance_mix_to_total(base, question_count)


def _normalize_section_entry(entry: Dict[str, Any], fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    fallback = fallback or {}
    raw_key = entry.get("key") or fallback.get("key") or "section"
    key = str(raw_key).strip().lower() or "section"
    label = (entry.get("label") or fallback.get("label") or key.title()).strip()
    subject_area = (entry.get("subject_area") or fallback.get("subject_area") or key).strip().lower()
    question_format = (entry.get("question_format") or fallback.get("question_format") or "multiple_choice").strip().lower()
    desired_total = entry.get("question_count") or fallback.get("question_count") or DEFAULT_TKA_QUESTION_COUNT
    try:
        desired_total = max(0, int(desired_total))
    except (TypeError, ValueError):
        desired_total = DEFAULT_TKA_QUESTION_COUNT
    raw_mix = entry.get("difficulty") or entry.get("difficulty_mix")
    fallback_mix = fallback.get("difficulty") or fallback.get("difficulty_mix")
    if fallback_mix is None:
        fallback_mix = _default_section_mix(desired_total)
    mix = _coerce_difficulty_mix(raw_mix or fallback_mix)
    mix = _rebalance_mix_to_total(mix, desired_total or sum(mix.values()))
    return {
        "key": key,
        "label": label,
        "subject_area": subject_area,
        "question_format": question_format,
        "question_count": sum(mix.values()),
        "difficulty": mix,
    }


def _normalize_section_config(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
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
    normalized_sections: List[Dict[str, Any]] = []
    seen_keys: set[str] = set()
    sections_payload = raw_config.get("sections") if isinstance(raw_config.get("sections"), list) else []
    for entry in sections_payload:
        if not isinstance(entry, dict):
            continue
        normalized = _normalize_section_entry(entry, template_map.get(entry.get("key")))
        seen_keys.add(normalized["key"])
        normalized_sections.append(normalized)
    for template in TKA_SECTION_TEMPLATES:
        if template["key"] in seen_keys:
            continue
        normalized_sections.append(_normalize_section_entry(template, template))
    normalized_sections.sort(key=lambda item: TKA_SECTION_KEY_ORDER.index(item["key"]) if item["key"] in TKA_SECTION_KEY_ORDER else item["key"])
    return {
        "duration_minutes": duration_minutes,
        "sections": normalized_sections,
    }


def _aggregate_section_mix(sections: List[Dict[str, Any]]) -> Dict[str, int]:
    totals = {key: 0 for key in VALID_TKA_DIFFICULTIES}
    for section in sections:
        mix = section.get("difficulty") or {}
        for key in VALID_TKA_DIFFICULTIES:
            try:
                totals[key] += int(mix.get(key) or 0)
            except (TypeError, ValueError):
                continue
    return totals


def _normalize_grade_level(raw_value: Optional[str]) -> str:
    if not raw_value:
        return DEFAULT_TKA_GRADE_LEVEL
    value = str(raw_value).strip().lower()
    if value not in VALID_TKA_GRADE_LEVELS:
        return DEFAULT_TKA_GRADE_LEVEL
    return value


def _truncate_for_prompt(value: Optional[str], limit: int = 320) -> str:
    if not value:
        return ""
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _refresh_conn(force: bool = False) -> None:
    """Pastikan koneksi terbuka; re-open saat closed/broken."""
    global conn
    try:
        if force or conn.closed or conn.status == extensions.STATUS_CLOSED:
            conn = psycopg2.connect(**conn_args)
            return
        status = conn.get_transaction_status()
        if status == extensions.TRANSACTION_STATUS_UNKNOWN:
            conn.close()
            conn = psycopg2.connect(**conn_args)
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        conn = psycopg2.connect(**conn_args)


def _reset_conn_if_error() -> None:
    """Rollback jika dalam error; refresh jika koneksi bermasalah."""
    global conn
    try:
        _refresh_conn()
        if conn.get_transaction_status() == extensions.TRANSACTION_STATUS_INERROR:
            conn.rollback()
    except Exception:
        _refresh_conn(force=True)


def _default_preset_payload() -> Dict[str, Dict[str, int]]:
    return {key: dict(value) for key, value in DEFAULT_TKA_PRESETS.items()}


def _normalize_preset_name(value: Optional[str]) -> str:
    if not value:
        return DEFAULT_TKA_PRESET_KEY
    return str(value).strip().lower()


def _prepare_subject_presets(stored: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    presets = _default_preset_payload()
    if isinstance(stored, dict):
        for key, mix in stored.items():
            if not key:
                continue
            normalized = _normalize_preset_name(key)
            presets[normalized] = _coerce_difficulty_mix(mix)
    return presets


def _resolve_preset_mix_for_subject(
    subject: Dict[str, Any],
    preset_name: Optional[str] = None,
) -> Tuple[Dict[str, int], str, Dict[str, Dict[str, int]]]:
    presets = _prepare_subject_presets(subject.get("difficulty_presets"))
    requested = _normalize_preset_name(preset_name or subject.get("default_preset"))
    mix = presets.get(requested)
    if not mix:
        requested = _normalize_preset_name(subject.get("default_preset"))
        mix = presets.get(requested)
    if not mix:
        requested = DEFAULT_TKA_PRESET_KEY
        mix = presets.get(requested) or _coerce_difficulty_mix(None)
    return mix, requested, presets


def _enrich_subject_row(row: Dict[str, Any]) -> Dict[str, Any]:
    subject = dict(row)
    mix, preset, presets = _resolve_preset_mix_for_subject(subject)
    subject["difficulty_presets"] = presets
    subject["default_preset"] = preset
    subject["difficulty_mix"] = mix
    subject.setdefault("question_count", sum(mix.values()))
    subject["active_mix"] = mix
    subject["grade_level"] = _normalize_grade_level(subject.get("grade_level"))
    metadata = subject.get("metadata") if isinstance(subject.get("metadata"), dict) else {}
    subject["metadata"] = metadata or {}
    section_config = _normalize_section_config(metadata)
    if section_config:
        aggregated_mix = _aggregate_section_mix(section_config.get("sections") or [])
        subject["advanced_config"] = section_config
        subject["difficulty_mix"] = aggregated_mix
    subject["active_mix"] = aggregated_mix
    subject["difficulty_presets"][subject["default_preset"]] = aggregated_mix
    subject["question_count"] = sum(section.get("question_count", 0) for section in section_config.get("sections") or [])
    subject["time_limit_minutes"] = section_config.get("duration_minutes", subject.get("time_limit_minutes") or DEFAULT_TKA_TIME_LIMIT)
    name_value = (subject.get("name") or "").strip()
    if name_value.lower() == "matematika":
        subject["name"] = "Latihan TKA"
    return subject


def list_tka_subjects(active_only: bool = True) -> List[Dict[str, Any]]:
    """Ambil daftar mapel Latihan TKA."""
    _ensure_tka_schema()
    query = """
        SELECT
            id,
            slug,
            name,
            description,
            question_count,
            time_limit_minutes,
            difficulty_mix,
            difficulty_presets,
            default_preset,
            question_revision,
            grade_level,
            is_active,
            metadata
        FROM tka_subjects
    """
    params: Tuple[Any, ...] = ()
    if active_only:
        query += " WHERE is_active = TRUE"
    query += " ORDER BY name ASC"

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    return [_enrich_subject_row(row) for row in rows]


def get_tka_subject(subject_id: int) -> Optional[Dict[str, Any]]:
    """Ambil detail mapel Latihan TKA."""
    if not subject_id:
        return None
    _ensure_tka_schema()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                id,
                slug,
                name,
                description,
                question_count,
                time_limit_minutes,
                difficulty_mix,
                difficulty_presets,
                default_preset,
                grade_level,
                question_revision,
                is_active,
                metadata
            FROM tka_subjects
            WHERE id = %s
            """,
            (subject_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return _enrich_subject_row(row)


def list_tka_tests(active_only: bool = True) -> List[Dict[str, Any]]:
    """Ambil daftar tes TKA beserta status aktifnya."""
    _ensure_tka_schema()
    query = """
        SELECT id, name, grade_level, duration_minutes, is_active, created_at, updated_at
        FROM tka_tests
    """
    params: Tuple[Any, ...] = ()
    if active_only:
        query += " WHERE is_active = TRUE"
    query += " ORDER BY created_at DESC"
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    return [dict(row) for row in rows or []]


def get_tka_test(test_id: int) -> Optional[Dict[str, Any]]:
    """Ambil detail tes TKA."""
    if not test_id:
        return None
    _ensure_tka_schema()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
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


def _fetch_test_subject_formats(test_subject_id: int) -> List[Dict[str, Any]]:
    if not test_subject_id:
        return []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
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


def _fetch_test_subject_topics(test_subject_id: int) -> List[Dict[str, Any]]:
    if not test_subject_id:
        return []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT tt.id, tt.topic, tt.question_count_target, tt.order_index
            FROM tka_test_topics tt
            WHERE tt.test_subject_id = %s
            ORDER BY tt.order_index ASC, tt.id ASC
            """,
            (test_subject_id,),
        )
        return [dict(row) for row in cur.fetchall() or []]


def fetch_tka_test_subjects(test_id: int) -> List[Dict[str, Any]]:
    """Ambil daftar mapel untuk tes tertentu beserta format & topik."""
    if not test_id:
        return []
    _ensure_tka_schema()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
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

    subjects: list[dict] = []
    seen_keys: set[str] = set()
    for entry in raw_subjects:
        key = f"{entry.get('mapel_id') or 'mapel-none'}|{entry.get('id') or 'id-none'}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        subjects.append(entry)

    for item in subjects:
        item["formats"] = _fetch_test_subject_formats(item["id"])
        item["topics"] = _fetch_test_subject_topics(item["id"])
        item["subject_name"] = item.get("mapel_name")
        item["grade_level"] = _normalize_grade_level(item.get("mapel_grade_level"))
        item["question_count_actual"] = item.get("question_count_actual") or 0
        item["question_count_pg_actual"] = item.get("question_count_pg_actual") or 0
        item["question_count_tf_actual"] = item.get("question_count_tf_actual") or 0
    return subjects


def get_tka_test_detail(test_id: int) -> Optional[Dict[str, Any]]:
    """Ambil tes beserta daftar mapel dan komposisi targetnya."""
    test = get_tka_test(test_id)
    if not test:
        return None
    test["subjects"] = fetch_tka_test_subjects(test_id)
    return test


def _load_tka_question_bank(subject_id: int) -> tuple[dict[str, list], dict[str, int]]:
    """Return grouped question rows per difficulty plus totals."""
    buckets: dict[str, list] = {key: [] for key in VALID_TKA_DIFFICULTIES}
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                q.id,
                q.prompt,
                q.options,
                q.correct_key,
                q.explanation,
                q.difficulty,
                q.topic,
                q.metadata,
                q.answer_format,
                q.stimulus_id,
                s.title AS stimulus_title,
                s.type AS stimulus_type,
                s.narrative AS stimulus_narrative,
                s.image_url AS stimulus_image_url,
                s.image_prompt AS stimulus_image_prompt,
                s.metadata AS stimulus_metadata
            FROM tka_questions q
            LEFT JOIN tka_stimulus s ON s.id = q.stimulus_id
            WHERE q.subject_id = %s
            """,
            (subject_id,),
        )
        for row in cur.fetchall():
            difficulty = (row.get("difficulty") or "easy").strip().lower()
            if difficulty not in VALID_TKA_DIFFICULTIES:
                difficulty = "easy"
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            row["metadata"] = metadata or {}
            section_key = metadata.get("section_key") or metadata.get("section")
            if not section_key:
                raw_topic = (row.get("topic") or "").lower()
                if "bahasa" in raw_topic:
                    section_key = "bahasa_pg"
                else:
                    section_key = "matematika"
            row["section_key"] = section_key
            row["subject_area"] = metadata.get("subject_area") or ("bahasa_indonesia" if section_key and section_key.startswith("bahasa") else "matematika")
            answer_format = (row.get("answer_format") or "").strip().lower()
            if answer_format not in {"multiple_choice", "true_false"}:
                answer_format = "multiple_choice"
            row["answer_format"] = answer_format
            stimulus_meta = None
            stimulus_id = row.get("stimulus_id")
            if stimulus_id:
                stimulus_meta = {
                    "id": stimulus_id,
                    "title": row.get("stimulus_title") or metadata.get("stimulus_title"),
                    "type": row.get("stimulus_type") or metadata.get("stimulus_type") or "text",
                    "narrative": row.get("stimulus_narrative") or metadata.get("stimulus_text"),
                    "image_url": row.get("stimulus_image_url") or metadata.get("image_url"),
                    "image_prompt": row.get("stimulus_image_prompt") or metadata.get("image_prompt"),
                    "metadata": row.get("stimulus_metadata") or {},
                }
            row["stimulus"] = stimulus_meta
            buckets.setdefault(difficulty, []).append(row)
    totals = {key: len(rows) for key, rows in buckets.items()}
    return buckets, totals


def _resolve_subject_area(raw: Optional[str], mapel_name: Optional[str]) -> str:
    if raw:
        value = raw.strip().lower()
        if "bahasa" in value:
            return "bahasa_indonesia"
        if "matematika" in value:
            return "matematika"
    if mapel_name and "bahasa" in mapel_name.lower():
        return "bahasa_indonesia"
    return "matematika"


def _resolve_subject_id_for_question(subjects: List[Dict[str, Any]], mapel_id: Optional[int]) -> Optional[int]:
    if mapel_id is None:
        return None
    for item in subjects:
        if item.get("mapel_id") == mapel_id:
            return item.get("id")
    return None


def _load_test_question_bank(test_id: int, subjects: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    """Kelompokkan bank soal per mapel (test_subject)."""
    buckets: Dict[int, List[Dict[str, Any]]] = {}
    if not test_id:
        return buckets
    subject_ids = [s["id"] for s in subjects if s.get("id")]
    mapel_ids = [s["mapel_id"] for s in subjects if s.get("mapel_id")]
    if not subject_ids and not mapel_ids:
        return buckets
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                q.id,
                q.test_subject_id,
                q.test_id,
                q.mapel_id,
                q.prompt,
                q.options,
                q.correct_key,
                q.explanation,
                q.difficulty,
                q.topic,
                q.metadata,
                q.answer_format,
                s.title AS stimulus_title,
                s.type AS stimulus_type,
                s.narrative AS stimulus_narrative,
                s.image_url AS stimulus_image_url,
                s.image_prompt AS stimulus_image_prompt,
                s.metadata AS stimulus_metadata,
                mp.name AS mapel_name
            FROM tka_questions q
            LEFT JOIN tka_stimulus s ON s.id = q.stimulus_id
            LEFT JOIN tka_mata_pelajaran mp ON mp.id = q.mapel_id
            WHERE (q.test_id = %s)
               OR (q.test_subject_id = ANY(%s))
               OR (q.mapel_id = ANY(%s))
            """,
            (test_id, subject_ids or [-1], mapel_ids or [-1]),
        )
        rows = cur.fetchall()
    # Hindari duplikasi soal jika memenuhi lebih dari satu kondisi WHERE (test_id & mapel/test_subject)
    unique_rows = {}
    for row in rows or []:
        qid = row.get("id")
        if qid in unique_rows:
            continue
        unique_rows[qid] = row

    for row in unique_rows.values():
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        difficulty = (row.get("difficulty") or "easy").strip().lower()
        if difficulty not in VALID_TKA_DIFFICULTIES:
            difficulty = "easy"
        answer_format = (row.get("answer_format") or "").strip().lower()
        if answer_format not in {"multiple_choice", "true_false"}:
            answer_format = "multiple_choice"
        topic = (row.get("topic") or "").strip()
        subject_area = _resolve_subject_area(metadata.get("subject_area"), row.get("mapel_name"))
        bucket_id = row.get("test_subject_id") or _resolve_subject_id_for_question(subjects, row.get("mapel_id"))
        if not bucket_id:
            continue
        stimulus_meta = None
        if row.get("stimulus_title") or row.get("stimulus_narrative") or row.get("stimulus_image_url"):
            stimulus_meta = {
                "id": row.get("stimulus_id"),
                "title": row.get("stimulus_title") or metadata.get("stimulus_title"),
                "type": row.get("stimulus_type") or metadata.get("stimulus_type") or "text",
                "narrative": row.get("stimulus_narrative") or metadata.get("stimulus_text"),
                "image_url": row.get("stimulus_image_url") or metadata.get("image_url"),
                "image_prompt": row.get("stimulus_image_prompt") or metadata.get("image_prompt"),
            }
        normalized = {
            "id": row["id"],
            "prompt": row.get("prompt"),
            "options": row.get("options"),
            "correct_key": row.get("correct_key"),
            "explanation": row.get("explanation"),
            "difficulty": difficulty,
            "topic": topic,
            "metadata": metadata or {},
            "answer_format": answer_format,
            "section_key": metadata.get("section_key"),
            "subject_area": subject_area,
            "test_subject_id": bucket_id,
            "test_id": row.get("test_id"),
            "mapel_id": row.get("mapel_id"),
            "mapel_name": row.get("mapel_name"),
            "stimulus": stimulus_meta,
        }
        buckets.setdefault(bucket_id, []).append(normalized)
    return buckets


def _difficulty_order(choice: Optional[str]) -> List[str]:
    if not choice:
        return ["easy", "medium", "hard"]
    normalized = str(choice).strip().lower()
    if normalized == "mudah" or normalized == "easy":
        return ["easy", "medium", "hard"]
    if normalized == "sedang" or normalized == "medium":
        return ["medium", "easy", "hard"]
    return ["hard", "medium", "easy"]


def _allowed_difficulties(choice: Optional[str]) -> set[str]:
    if not choice:
        return set(VALID_TKA_DIFFICULTIES)
    normalized = str(choice).strip().lower()
    if normalized in {"mudah", "easy"}:
        return {"easy"}
    if normalized in {"sedang", "medium"}:
        return {"medium", "easy", "hard"}
    return {"hard", "medium", "easy"}


def _shuffle_pool_by_topic_stimulus(pool: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Acak urutan soal per topik, menjaga soal dengan stimulus sama tetap berdekatan."""
    topic_groups: Dict[str, Dict[str, Dict[str, Any]]] = {}
    topic_sequence: List[str] = []
    for row in pool or []:
        topic_key = (row.get("topic") or "").strip().lower()
        if topic_key not in topic_sequence:
            topic_sequence.append(topic_key)
        stim_key = row.get("stimulus_key") or f"solo-{row.get('id')}"
        bucket = topic_groups.setdefault(topic_key, {})
        group = bucket.setdefault(stim_key, {"rows": []})
        group["rows"].append(row)
    shuffled: List[Dict[str, Any]] = []
    for topic_key in topic_sequence:
        groups = list((topic_groups.get(topic_key) or {}).values())
        random.shuffle(groups)
        for group in groups:
            shuffled.extend(group.get("rows") or [])
    return shuffled


def _select_questions_for_subject(
    subject: Dict[str, Any],
    pool: List[Dict[str, Any]],
    difficulty_choice: Optional[str],
) -> List[Dict[str, Any]]:
    """Pilih soal per mapel dengan toleransi komposisi format dan topik."""
    allowed_diffs = _allowed_difficulties(difficulty_choice)
    pool_filtered = [row for row in pool if (row.get("difficulty") or "easy") in allowed_diffs]
    if not pool_filtered:
        return []
    pool_filtered = _shuffle_pool_by_topic_stimulus(pool_filtered)
    order = _difficulty_order(difficulty_choice)
    pool_sorted = sorted(
        pool_filtered,
        key=lambda item: order.index(item.get("difficulty")) if item.get("difficulty") in order else len(order),
    )
    topic_targets: Dict[str, int] = {}
    for entry in subject.get("topics") or []:
        name = (entry.get("topic") or entry.get("name") or "").strip()
        if not name:
            continue
        try:
            topic_targets[name.lower()] = max(0, int(entry.get("question_count_target") or entry.get("count") or 0))
        except (TypeError, ValueError):
            topic_targets[name.lower()] = 0
    fmt_map = {fmt.get("question_type"): int(fmt.get("question_count_target") or 0) for fmt in subject.get("formats") or []}
    pg_target = fmt_map.get("multiple_choice", 0)
    tf_target = fmt_map.get("true_false", 0)
    total_target = int(subject.get("question_count_target") or 0)
    if pg_target + tf_target == 0 and total_target > 0:
        pg_target = total_target
    elif pg_target + tf_target > 0 and total_target == 0:
        total_target = pg_target + tf_target
    elif pg_target + tf_target == 0 and total_target == 0:
        total_target = len(pool_sorted)
        pg_target = total_target
    format_targets = {
        "multiple_choice": pg_target,
        "true_false": tf_target,
    }
    if len(pool_sorted) < total_target:
        raise ValueError("bank_insufficient")
    allowed_total = total_target
    selected: List[Dict[str, Any]] = []
    used_ids: set[int] = set()
    format_counts = {"multiple_choice": 0, "true_false": 0}
    topic_counts: Dict[str, int] = {}

    def _row_stimulus_id(question: Dict[str, Any]) -> Optional[Any]:
        stim = question.get("stimulus")
        if isinstance(stim, dict):
            return stim.get("id")
        return None

    def can_take(question: Dict[str, Any]) -> bool:
        fmt = question.get("answer_format") or "multiple_choice"
        max_allowed = format_targets.get(fmt, 0) + 2
        if len(selected) >= allowed_total:
            return False
        return format_counts.get(fmt, 0) < max_allowed and question.get("id") not in used_ids

    # Alternasikan toleransi: mulai plus jika kuota cukup, minus jika kuota sempit
    sum_targets = sum(topic_targets.values()) if topic_targets else 0
    prefer_plus = allowed_total >= sum_targets
    has_surplus = allowed_total >= sum_targets

    for topic_name, target in topic_targets.items():
        # Batasi toleransi distribusi per topik agar tidak terlalu melebar
        if has_surplus:
            min_take = max(target, 0)
            max_take = min(target, allowed_total - len(selected))
        else:
            min_take = max(target - 1, 0)
            offset = 1 if prefer_plus else -1
            max_take = max(min(target + offset, allowed_total - len(selected)), 0)
            prefer_plus = not prefer_plus
        if max_take < min_take:
            max_take = min_take
        if max_take <= 0:
            continue
        candidates = [row for row in pool_sorted if row.get("topic", "").strip().lower() == topic_name and can_take(row)]
        for idx, row in enumerate(candidates):
            current_topic_count = topic_counts.get(topic_name, 0)
            # Jika stimulus punya lebih dari satu soal berurutan, beri 1 slot ekstra agar tidak terpotong
            allow_extra = False
            current_stim_id = _row_stimulus_id(row)
            if current_stim_id is not None and idx + 1 < len(candidates):
                next_stim_id = _row_stimulus_id(candidates[idx + 1])
                if next_stim_id == current_stim_id:
                    allow_extra = True
            max_for_topic = max_take + (1 if allow_extra else 0)
            if len(selected) >= allowed_total or current_topic_count >= max_for_topic:
                break
            selected.append(row)
            used_ids.add(row["id"])
            fmt = row.get("answer_format") or "multiple_choice"
            format_counts[fmt] = format_counts.get(fmt, 0) + 1
            topic_counts[topic_name] = topic_counts.get(topic_name, 0) + 1
        # Pastikan batas bawah terpenuhi jika memungkinkan
        if topic_counts.get(topic_name, 0) < min_take:
            extra_needed = min_take - topic_counts.get(topic_name, 0)
            filler = [row for row in pool_sorted if row.get("id") not in used_ids and row.get("topic", "").strip().lower() == topic_name]
            for row in filler:
                if extra_needed <= 0 or len(selected) >= allowed_total:
                    break
                fmt = row.get("answer_format") or "multiple_choice"
                if not can_take(row):
                    continue
                selected.append(row)
                used_ids.add(row["id"])
                format_counts[fmt] = format_counts.get(fmt, 0) + 1
                topic_counts[topic_name] = topic_counts.get(topic_name, 0) + 1
                extra_needed -= 1

    pool_remaining = [row for row in pool_sorted if row.get("id") not in used_ids]
    for row in pool_remaining:
        if len(selected) >= allowed_total:
            break
        fmt = row.get("answer_format") or "multiple_choice"
        target_fmt = format_targets.get(fmt, 0)
        if format_counts.get(fmt, 0) >= target_fmt + 2:
            continue
        selected.append(row)
        used_ids.add(row["id"])
        format_counts[fmt] = format_counts.get(fmt, 0) + 1
        topic_key = (row.get("topic") or "").strip().lower()
        if topic_key:
            topic_counts[topic_key] = topic_counts.get(topic_key, 0) + 1

    if len(selected) < min(total_target, len(pool_sorted)):
        filler_pool = [row for row in pool_sorted if row.get("id") not in used_ids]
        for row in filler_pool:
            if len(selected) >= allowed_total:
                break
            selected.append(row)
            used_ids.add(row["id"])
            fmt = row.get("answer_format") or "multiple_choice"
            format_counts[fmt] = format_counts.get(fmt, 0) + 1
            topic_key = (row.get("topic") or "").strip().lower()
            if topic_key:
                topic_counts[topic_key] = topic_counts.get(topic_key, 0) + 1
    if len(selected) < total_target:
        raise ValueError("bank_insufficient")
    return selected


def _stimulus_group_key(row: dict) -> str:
    stimulus_id = row.get("stimulus_id")
    if stimulus_id:
        return f"stim-{stimulus_id}"
    return f"solo-{row['id']}"


def _select_question_packages(
    pool_rows: list[dict],
    amount: int,
    allow_repeat: bool,
    used_ids: set[int],
    used_stimulus_keys: set[str],
    stimulus_usage: dict[str, int],
) -> list[dict]:
    if amount <= 0:
        return []
    if not pool_rows:
        raise ValueError("bank_insufficient")
    group_map: dict[str, dict] = {}
    for row in pool_rows:
        group_key = _stimulus_group_key(row)
        entry = group_map.setdefault(
            group_key,
            {
                "key": group_key,
                "stimulus_id": row.get("stimulus_id"),
                "stimulus_meta": row.get("stimulus") or {},
                "rows": [],
                "unused": [],
                "fresh": group_key not in used_stimulus_keys,
            },
        )
        entry["rows"].append(row)
        if row["id"] not in used_ids and group_key not in used_stimulus_keys:
            entry["unused"].append(row)
    groups = list(group_map.values())
    if not groups:
        raise ValueError("bank_insufficient")
    unused_total = sum(len(group["unused"]) for group in groups)
    if not allow_repeat and unused_total < amount:
        raise ValueError("repeat_required")
    available_total = sum(len(group["rows"]) for group in groups)
    if available_total < amount:
        raise ValueError("bank_insufficient")
    random.shuffle(groups)
    groups.sort(key=lambda item: item.get("fresh", True), reverse=True)
    selections: list[dict] = []
    remaining = amount
    for group in groups:
        if remaining <= 0:
            break
        group_key = group["key"]
        limit = MAX_STIMULUS_QUESTIONS - stimulus_usage.get(group_key, 0)
        if limit <= 0:
            continue
        candidates = group["unused"] if group["unused"] else (group["rows"] if allow_repeat else [])
        if not candidates:
            continue
        available_count = len(candidates)
        if group.get("fresh") and available_count < MIN_STIMULUS_QUESTIONS and remaining >= MIN_STIMULUS_QUESTIONS:
            # Skip fresh stimulus that belum lengkap
            continue
        take = min(remaining, limit, available_count)
        if group.get("fresh") and remaining >= MIN_STIMULUS_QUESTIONS and available_count >= MIN_STIMULUS_QUESTIONS and take < MIN_STIMULUS_QUESTIONS:
            take = min(available_count, MIN_STIMULUS_QUESTIONS)
        if take <= 0:
            continue
        chosen = random.sample(candidates, take)
        selections.append(
            {
                "rows": chosen,
                "stimulus_meta": group["stimulus_meta"],
                "stimulus_id": group["stimulus_id"],
                "key": group_key,
            }
        )
        stimulus_usage[group_key] = stimulus_usage.get(group_key, 0) + len(chosen)
        remaining -= len(chosen)
    if remaining > 0:
        raise ValueError("repeat_required" if not allow_repeat else "bank_insufficient")
    return selections


def _fetch_user_used_question_ids(subject_id: int, web_user_id: int, revision: int) -> set[int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT aq.question_id
            FROM tka_attempt_questions aq
            JOIN tka_quiz_attempts a ON a.id = aq.attempt_id
            WHERE a.subject_id = %s
              AND a.web_user_id = %s
              AND a.revision_snapshot = %s
              AND aq.question_id IS NOT NULL
            """,
            (subject_id, web_user_id, revision),
        )
        return {int(row[0]) for row in cur.fetchall() if row and row[0]}


def _compute_repeat_iteration(subject_id: int, web_user_id: int, revision: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(MAX(repeat_iteration), 0)
            FROM tka_quiz_attempts
            WHERE subject_id = %s
              AND web_user_id = %s
              AND revision_snapshot = %s
              AND is_repeat = TRUE
            """,
            (subject_id, web_user_id, revision),
        )
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


def get_tka_subject_availability(
    subject_id: int,
    web_user_id: Optional[int],
    preset_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Hitung kesiapan bank soal dan progres user terhadap subject tertentu."""
    subject = get_tka_subject(subject_id)
    if not subject:
        return None
    mix, preset_used, presets = _resolve_preset_mix_for_subject(subject, preset_name)
    bank, totals = _load_tka_question_bank(subject_id)
    section_config = (subject.get("advanced_config") or {})
    sections = section_config.get("sections") or []
    if sections:
        bank_ready = True
    else:
        bank_ready = all(totals.get(diff, 0) >= mix.get(diff, 0) for diff in mix)
    availability: Dict[str, Any] = {
        "subject": subject,
        "required": mix,
        "selectedPreset": preset_used,
        "presets": presets,
        "totals": totals,
        "bank_ready": bank_ready,
        "needs_repeat": False,
        "unused": {},
    }
    section_details: list[dict] = []
    if not bank_ready or not web_user_id:
        if sections:
            availability["section_details"] = section_details
        return availability
    revision = subject.get("question_revision") or 1
    used_ids = _fetch_user_used_question_ids(subject_id, web_user_id, revision)
    if sections:
        needs_repeat = False
        for section in sections:
            section_key = section.get("key")
            section_status = {
                "key": section_key,
                "label": section.get("label"),
                "requirements": {},
            }
            for difficulty, required in (section.get("difficulty") or {}).items():
                if required <= 0:
                    continue
                eligible = [row for row in bank.get(difficulty, []) if row.get("section_key") == section_key]
                available_total = len(eligible)
                unused_total = len([row for row in eligible if row["id"] not in used_ids])
                section_status["requirements"][difficulty] = {
                    "required": required,
                    "available": available_total,
                    "unused": unused_total,
                }
                if available_total < required:
                    availability["bank_ready"] = False
                if unused_total < required:
                    needs_repeat = True
            section_details.append(section_status)
        availability["section_details"] = section_details
        availability["needs_repeat"] = needs_repeat
        availability["unused"] = {
            diff: sum(
                detail["requirements"].get(diff, {}).get("unused", 0)
                for detail in section_details
            )
            for diff in VALID_TKA_DIFFICULTIES
        }
    else:
        unused_counts: Dict[str, int] = {}
        for diff, rows in bank.items():
            unused_counts[diff] = len([row for row in rows if row["id"] not in used_ids])
        needs_repeat = any(unused_counts.get(diff, 0) < mix.get(diff, 0) for diff in mix)
        availability["unused"] = unused_counts
        availability["needs_repeat"] = needs_repeat
    availability["used_total"] = len(used_ids)
    return availability


def create_tka_attempt(
    test_id: int,
    web_user_id: int,
    *,
    allow_repeat: bool = False,
    preset_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Buat sesi latihan baru berdasarkan konfigurasi tes (tka_tests)."""
    if not test_id or not web_user_id:
        raise ValueError("test_id dan web_user_id wajib diisi.")

    _ensure_tka_schema()
    _reset_conn_if_error()
    test = get_tka_test_detail(test_id)
    if not test or not test.get("is_active"):
        raise ValueError("Tes Latihan TKA tidak ditemukan atau tidak aktif.")
    subjects = test.get("subjects") or []
    if not subjects:
        raise ValueError("Tes ini belum memiliki mapel.")

    question_bank = _load_test_question_bank(test_id, subjects)
    selected_rows: List[Dict[str, Any]] = []
    selection_summary: List[Dict[str, Any]] = []
    difficulty_choice = preset_name

    for idx, subject in enumerate(subjects):
        pool = question_bank.get(subject["id"], [])
        chosen = _select_questions_for_subject(subject, pool, difficulty_choice)
        if not chosen:
            continue
        mapel_order_value = subject.get("order_index") if subject.get("order_index") is not None else (idx + 1)
        for row in chosen:
            row["test_subject_id"] = subject["id"]
            row["mapel_id"] = row.get("mapel_id") or subject.get("mapel_id")
            row["mapel_name"] = row.get("mapel_name") or subject.get("mapel_name")
            row["mapel_order"] = mapel_order_value
        selected_rows.extend(chosen)
        selection_summary.append(
            {
                "test_subject_id": subject["id"],
                "mapel_id": subject.get("mapel_id"),
                "mapel_name": subject.get("mapel_name"),
                "selected": len(chosen),
                "target": subject.get("question_count_target") or 0,
            }
        )

    if not selected_rows:
        raise ValueError("Belum ada soal yang siap untuk tes ini.")

    random.shuffle(selected_rows)
    total_questions = len(selected_rows)
    time_limit = test.get("duration_minutes") or DEFAULT_TKA_COMPOSITE_DURATION
    is_repeat = bool(allow_repeat)
    repeat_iteration = 1 if is_repeat else 0
    metadata_payload = {
        "test_id": test_id,
        "test_name": test.get("name"),
        "grade_level": _normalize_grade_level(test.get("grade_level")),
        "selection": selection_summary,
    }
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO tka_quiz_attempts (
                subject_id,
                test_id,
                web_user_id,
                status,
                time_limit_minutes,
                question_count,
                metadata,
                revision_snapshot,
                is_repeat,
                repeat_iteration,
                difficulty_preset
            )
            VALUES (NULL, %s, %s, 'in_progress', %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, started_at
            """,
            (
                test_id,
                web_user_id,
                time_limit,
                total_questions,
                Json(metadata_payload),
                1,
                is_repeat,
                repeat_iteration,
                preset_name or "",
            ),
        )
        attempt_row = cur.fetchone()
        attempt_id = attempt_row["id"]
        insert_rows: List[Tuple[Any, ...]] = []
        order_index = 1
        for row in selected_rows:
            answer_format = row.get("answer_format") or "multiple_choice"
            meta_payload = dict(row.get("metadata") or {})
            meta_payload.update(
                {
                    "section_key": meta_payload.get("section_key") or row.get("section_key"),
                    "section_label": meta_payload.get("section_label") or (row.get("section_key") or "").title(),
                    "subject_area": row.get("subject_area") or "matematika",
                    "question_format": answer_format,
                    "mapel_id": row.get("mapel_id"),
                    "mapel_name": row.get("mapel_name"),
                    "test_subject_id": row.get("test_subject_id"),
                    "mapel_order": row.get("mapel_order"),
                    "true_false_statements": meta_payload.get("true_false_statements") or row.get("true_false_statements"),
                }
            )
            stimulus_meta = row.get("stimulus") or {}
            if stimulus_meta:
                meta_payload.update(
                    {
                        "stimulus_id": stimulus_meta.get("id"),
                        "stimulus_title": stimulus_meta.get("title"),
                        "stimulus_type": stimulus_meta.get("type"),
                        "stimulus_text": stimulus_meta.get("narrative"),
                        "stimulus_image_url": stimulus_meta.get("image_url"),
                        "stimulus_image_prompt": stimulus_meta.get("image_prompt"),
                    }
                )
            insert_rows.append(
                (
                    attempt_id,
                    row["id"],
                    row.get("prompt"),
                    Json(row.get("options") or []),
                    row.get("correct_key"),
                    row.get("explanation"),
                    row.get("difficulty"),
                    row.get("topic"),
                    Json(meta_payload),
                    order_index,
                    answer_format,
                    row.get("test_subject_id"),
                    row.get("mapel_id"),
                )
            )
            order_index += 1

        cur.executemany(
            """
            INSERT INTO tka_attempt_questions (
                attempt_id,
                question_id,
                prompt,
                options,
                correct_key,
                explanation,
                difficulty,
                topic,
                metadata,
                order_index,
                answer_format,
                test_subject_id,
                mapel_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            insert_rows,
        )
    conn.commit()

    started_at = attempt_row["started_at"]
    expires_at = started_at + timedelta(minutes=time_limit)
    return {
        "attempt_id": attempt_id,
        "test": test,
        "question_count": total_questions,
        "time_limit_minutes": time_limit,
        "started_at": started_at,
        "expires_at": expires_at,
        "is_repeat": is_repeat,
        "repeat_iteration": repeat_iteration,
        "revision_snapshot": 1,
        "difficulty_preset": preset_name or "",
    }


def get_tka_attempt(attempt_id: int, web_user_id: int) -> Optional[Dict[str, Any]]:
    """Ambil sesi latihan yang sedang berjalan berikut daftar soalnya."""
    if not attempt_id or not web_user_id:
        return None
    _ensure_tka_schema()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                a.*,
                s.name AS subject_name,
                s.description AS subject_description,
                s.grade_level AS subject_grade_level,
                t.name AS test_name,
                t.grade_level AS test_grade_level,
                t.duration_minutes AS test_duration_minutes
            FROM tka_quiz_attempts a
            LEFT JOIN tka_subjects s ON s.id = a.subject_id
            LEFT JOIN tka_tests t ON t.id = a.test_id
            WHERE a.id = %s
              AND a.web_user_id = %s
            """,
            (attempt_id, web_user_id),
        )
        attempt = cur.fetchone()
        if not attempt:
            return None

        cur.execute(
            """
            SELECT
                aq.id,
                aq.question_id,
                aq.prompt,
                aq.options,
                aq.difficulty,
                aq.topic,
                aq.order_index,
                aq.metadata,
                COALESCE(aq.answer_format, q.answer_format, 'multiple_choice') AS answer_format,
                q.metadata AS source_metadata
            FROM tka_attempt_questions aq
            LEFT JOIN tka_questions q ON q.id = aq.question_id
            WHERE aq.attempt_id = %s
            ORDER BY aq.order_index ASC
            """,
            (attempt_id,),
        )
        questions = cur.fetchall()

    return {"attempt": attempt, "questions": questions}


def _build_tka_analysis_prompt(
    test_label: str,
    score: int,
    correct_count: int,
    total_questions: int,
    difficulty_stats: Dict[str, Dict[str, int]],
    topic_stats: Dict[str, Dict[str, Any]],
) -> str:
    lines = [
        "ASKA, ini ringkasan otomatis setelah siswa menyelesaikan latihan TKA.",
        f"- Tes: {test_label}",
        f"- Skor akhir: {score} (benar {correct_count} dari {total_questions} soal).",
    ]
    if topic_stats:
        lines.append("Urutkan fokus dari topik dengan persentase salah terbesar:")
        ranked_topics = sorted(
            topic_stats.items(),
            key=lambda item: (
                (item[1].get("wrong", item[1].get("total", 0) - item[1].get("correct", 0)))
                / max(item[1].get("total", 0), 1),
                item[1].get("wrong", 0),
            ),
            reverse=True,
        )
        for topic, stats in ranked_topics:
            total = stats.get("total", 0) or 1
            wrong = stats.get("wrong", total - stats.get("correct", 0))
            wrong_pct = round((wrong / total) * 100)
            lines.append(f"- {topic}: salah {wrong}/{total} soal ({wrong_pct}%).")
    lines.append("Berikan saran singkat (2-3 paragraf) dengan penekanan pada topik yang salahnya paling banyak, sertakan tips belajar cepat per topik.")
    return "\n".join(lines)


def submit_tka_attempt(
    attempt_id: int,
    web_user_id: int,
    answers: Dict[int, Optional[str]],
) -> Optional[Dict[str, Any]]:
    """Nilai jawaban siswa dan kunci skor."""
    if not attempt_id or not web_user_id:
        return None

    _reset_conn_if_error()
    _ensure_tka_schema()
    normalized_answers: Dict[int, Optional[str]] = {}
    for key, value in (answers or {}).items():
        try:
            question_key = int(key)
        except (TypeError, ValueError):
            continue
        if value is None:
            normalized_answers[question_key] = None
            continue
        clean_value = str(value).strip().upper()
        if not clean_value:
            normalized_answers[question_key] = None
            continue
        if clean_value in VALID_TKA_OPTION_KEYS:
            normalized_answers[question_key] = clean_value
            continue
        # Izinkan kombinasi TF (untuk soal BS multi pernyataan)
        if all(ch in {"T", "F"} for ch in clean_value):
            normalized_answers[question_key] = clean_value
            continue
        normalized_answers[question_key] = None

    now_utc = datetime.now(timezone.utc)
    attempt_retry = 0
    while attempt_retry < 2:
        try:
            _refresh_conn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM tka_quiz_attempts
                    WHERE id = %s
                      AND web_user_id = %s
                    FOR UPDATE
                    """,
                    (attempt_id, web_user_id),
                )
                attempt = cur.fetchone()
                if not attempt:
                    return None
                if attempt.get("status") != "in_progress":
                    return {"attempt": attempt, "questions": []}
                # Ambil label tes/mapel tanpa join FOR UPDATE untuk menghindari error
                subject_row = None
                test_row = None
                if attempt.get("subject_id"):
                    cur.execute(
                        "SELECT name, grade_level FROM tka_subjects WHERE id = %s",
                        (attempt.get("subject_id"),),
                    )
                    subject_row = cur.fetchone()
                if attempt.get("test_id"):
                    cur.execute(
                        "SELECT name, grade_level FROM tka_tests WHERE id = %s",
                        (attempt.get("test_id"),),
                    )
                    test_row = cur.fetchone()
                if subject_row:
                    attempt["subject_name"] = subject_row.get("name")
                    attempt["subject_grade_level"] = subject_row.get("grade_level")
                if test_row:
                    attempt["test_name"] = test_row.get("name")
                    attempt["test_grade_level"] = test_row.get("grade_level")
                raw_metadata = attempt.get("metadata")
                metadata_state = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}

                cur.execute(
                    """
                    SELECT
                        id,
                        question_id,
                        prompt,
                        options,
                        correct_key,
                        difficulty,
                        topic,
                        explanation,
                        metadata,
                        COALESCE(answer_format, (metadata->>'question_format'), 'multiple_choice') AS answer_format
                    FROM tka_attempt_questions
                    WHERE attempt_id = %s
                    ORDER BY order_index ASC
                    """,
                    (attempt_id,),
                )
                question_rows = cur.fetchall()

                if not question_rows:
                    raise ValueError("Soal untuk sesi ini belum tersedia.")

                difficulty_stats: Dict[str, Dict[str, int]] = {}
                section_stats: Dict[str, Dict[str, Any]] = {}
                stimulus_stats: Dict[str, Dict[str, Any]] = {}
                topic_stats: Dict[str, Dict[str, Any]] = {}
                updates: List[Tuple[Optional[str], bool, int]] = []
                detailed_rows: List[Dict[str, Any]] = []
                total_points = 0.0
                earned_points = 0.0
                for row in question_rows:
                    difficulty = row.get("difficulty") or "easy"
                    stats = difficulty_stats.setdefault(
                        difficulty, {"total": 0, "correct": 0}
                    )
                    stats["total"] += 1
                    selected_key = normalized_answers.get(row["id"])
                    row_meta = row.get("metadata") or {}
                    is_correct = False
                    if row.get("answer_format") == "true_false" and isinstance(row_meta.get("true_false_statements"), list):
                        statements = row_meta.get("true_false_statements") or []
                        expected = "".join(
                            "T"
                            if str(stmt.get("answer") or stmt.get("value") or "").lower() in {"t", "true", "benar", "ya", "y"}
                            else "F"
                            for stmt in statements
                        )
                        user_value = selected_key or ""
                        if isinstance(user_value, str):
                            user_value = user_value.strip().upper()
                        is_correct = bool(expected) and str(user_value) == expected
                    else:
                        is_correct = bool(
                            selected_key and row.get("correct_key") and selected_key == row["correct_key"]
                        )
                    if is_correct:
                        stats["correct"] += 1
                    section_key = row_meta.get("section_key") or "matematika"
                    subject_area = (row_meta.get("subject_area") or ("bahasa_indonesia" if section_key.startswith("bahasa") else "matematika")).strip().lower()
                    weight = 1.25 if subject_area == "matematika" else 1.0
                    total_points += weight
                    if is_correct:
                        earned_points += weight
                    section_entry = section_stats.setdefault(
                        section_key,
                        {
                            "label": row_meta.get("section_label") or section_key.title(),
                            "subject_area": subject_area,
                            "question_format": row.get("answer_format") or "multiple_choice",
                            "total": 0,
                            "correct": 0,
                        },
                    )
                    section_entry["total"] += 1
                    if is_correct:
                        section_entry["correct"] += 1
                    topic_key = (row.get("topic") or "-").strip() or "-"
                    topic_entry = topic_stats.setdefault(
                        topic_key,
                        {"total": 0, "correct": 0, "wrong": 0, "section_key": section_key},
                    )
                    topic_entry["total"] += 1
                    if is_correct:
                        topic_entry["correct"] += 1
                    else:
                        topic_entry["wrong"] += 1
                    stimulus_key = row_meta.get("stimulus_id") or row_meta.get("stimulus_title")
                    if stimulus_key:
                        stim_entry = stimulus_stats.setdefault(
                            str(stimulus_key),
                            {
                                "label": row_meta.get("stimulus_title") or f"Stimulus {stimulus_key}",
                                "type": row_meta.get("stimulus_type") or "text",
                                "total": 0,
                                "correct": 0,
                            },
                        )
                        stim_entry["total"] += 1
                        if is_correct:
                            stim_entry["correct"] += 1
                    updates.append((selected_key, is_correct, row["id"]))
                    detailed = dict(row)
                    detailed["selected_key"] = selected_key
                    detailed["is_correct"] = is_correct
                    detailed["subject_area"] = subject_area
                    detailed_rows.append(detailed)

                cur.executemany(
                    """
                    UPDATE tka_attempt_questions
                    SET selected_key = %s,
                        is_correct = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    updates,
                )

                total_questions = len(question_rows)
                correct_count = sum(stats["correct"] for stats in difficulty_stats.values())
                score = int(round((earned_points / total_points) * 100)) if total_points else 0
                duration_seconds = max(
                    0, int((now_utc - (attempt.get("started_at") or now_utc)).total_seconds())
                )
                analysis_prompt = _build_tka_analysis_prompt(
                    attempt.get("test_name") or attempt.get("subject_name") or "TKA",
                    score,
                    correct_count,
                    total_questions,
                    difficulty_stats,
                    topic_stats,
                )

                if section_stats or stimulus_stats or topic_stats:
                    metadata_state = dict(metadata_state)
                    if section_stats:
                        metadata_state["section_breakdown"] = section_stats
                    if stimulus_stats:
                        metadata_state["stimulus_breakdown"] = stimulus_stats
                    if topic_stats:
                        # Kelompokkan topik per mapel (label disimpan di metadata mapel_name)
                        grouped_topics: Dict[str, list] = {}
                        for topic_name, stats in topic_stats.items():
                            mapel_label = (section_stats.get(stats.get("section_key", "")) or {}).get("label") if isinstance(stats, dict) else None
                            bucket = grouped_topics.setdefault(mapel_label or "Mapel", [])
                            entry = dict(stats)
                            entry["topic"] = topic_name
                            bucket.append(entry)
                        metadata_state["topic_breakdown"] = grouped_topics
                    cur.execute(
                        """
                        UPDATE tka_quiz_attempts
                        SET status = 'completed',
                            completed_at = %s,
                            correct_count = %s,
                            score = %s,
                            duration_seconds = %s,
                            difficulty_breakdown = %s,
                            analysis_prompt = %s,
                            metadata = %s,
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING *
                        """,
                        (
                            now_utc,
                            correct_count,
                            score,
                            duration_seconds,
                            Json(difficulty_stats),
                            analysis_prompt,
                            Json(metadata_state),
                            attempt_id,
                        ),
                    )
                    updated_attempt = cur.fetchone()
                conn.commit()
                break
        except (InterfaceError, OperationalError, ProgrammingError) as exc:
            conn.rollback()
            attempt_retry += 1
            # Retry sekali jika cursor/connection bermasalah
            if attempt_retry >= 2 or "cursor already closed" not in str(exc).lower():
                raise
            _refresh_conn(force=True)
            continue
        except Exception:
            conn.rollback()
            raise

    return {
        "attempt": updated_attempt,
        "questions": detailed_rows,
        "difficulty": difficulty_stats,
        "topic_breakdown": topic_stats,
        "score": score,
        "correct_count": correct_count,
        "total_questions": total_questions,
        "analysis_prompt": analysis_prompt,
    }


def get_tka_result(attempt_id: int, web_user_id: int) -> Optional[Dict[str, Any]]:
    """Ambil hasil lengkap untuk ditampilkan pada halaman skor."""
    if not attempt_id or not web_user_id:
        return None
    _ensure_tka_schema()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                a.*,
                s.name AS subject_name,
                s.description AS subject_description,
                s.grade_level AS subject_grade_level,
                t.name AS test_name,
                t.grade_level AS test_grade_level,
                t.duration_minutes AS test_duration_minutes
            FROM tka_quiz_attempts a
            LEFT JOIN tka_subjects s ON s.id = a.subject_id
            LEFT JOIN tka_tests t ON t.id = a.test_id
            WHERE a.id = %s
              AND a.web_user_id = %s
            """,
            (attempt_id, web_user_id),
        )
        attempt = cur.fetchone()
        if not attempt:
            return None

        cur.execute(
            """
            SELECT
                id,
                question_id,
                prompt,
                options,
                correct_key,
                selected_key,
                is_correct,
                difficulty,
                topic,
                explanation,
                metadata,
                order_index,
                COALESCE(answer_format, (metadata->>'question_format'), 'multiple_choice') AS answer_format
            FROM tka_attempt_questions
            WHERE attempt_id = %s
            ORDER BY order_index ASC
            """,
            (attempt_id,),
        )
        questions = cur.fetchall()

    return {"attempt": attempt, "questions": questions}


def get_tka_analysis_job(attempt_id: int) -> Optional[Dict[str, Any]]:
    """Ambil data untuk memicu analisa otomatis oleh ASKA."""
    if not attempt_id:
        return None
    _ensure_tka_schema()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                id,
                web_user_id,
                analysis_prompt,
                analysis_sent_at,
                subject_id
            FROM tka_quiz_attempts
            WHERE id = %s
            """,
            (attempt_id,),
        )
        return cur.fetchone()


def mark_tka_analysis_sent(attempt_id: int) -> None:
    """Tandai bahwa analisa otomatis sudah dikirimkan lewat chat."""
    if not attempt_id:
        return
    _ensure_tka_schema()
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE tka_quiz_attempts
            SET analysis_sent_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
            """,
            (attempt_id,),
        )
    conn.commit()


# Call schema functions on startup
_ensure_chat_logs_schema()
_ensure_bullying_schema()
_ensure_psych_schema()
_ensure_user_schema()
_ensure_telegram_user_schema()
_ensure_corruption_schema()
_ensure_twitter_log_schema()
_ensure_tka_schema()
