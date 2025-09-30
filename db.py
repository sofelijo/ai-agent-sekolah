import psycopg2
import os
from dotenv import load_dotenv

# ⬇️ Muat variabel dari file .env
load_dotenv()

# ⬇️ Ambil variabel koneksi dari environment
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_SSLMODE = os.getenv("DB_SSLMODE", "require")  # ← Tambahan: default SSL untuk Neon

# ⬇️ Validasi agar semua variabel ada
required_vars = {
    "DB_NAME": DB_NAME,
    "DB_USER": DB_USER,
    "DB_PASS": DB_PASS,
    "DB_HOST": DB_HOST,
    "DB_PORT": DB_PORT,
}
for key, value in required_vars.items():
    if not value:
        raise ValueError(f"Environment variable '{key}' is not set! "
                         f"Silakan isi di file .env Anda.")

# ⬇️ Koneksi ke Neon PostgreSQL (dengan SSL)
conn = psycopg2.connect(
    dbname=DB_NAME,
    user=DB_USER,
    password=DB_PASS,
    host=DB_HOST,
    port=DB_PORT,
    sslmode=DB_SSLMODE  # Wajib untuk Neon
)

def save_chat(user_id, username, message, role, topic=None, response_time_ms=None):
    """
    Simpan chat ke tabel chat_logs.
    Pastikan tabel chat_logs sudah memiliki kolom:
      user_id, username, text, role, created_at, response_time_ms
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chat_logs (user_id, username, text, role, created_at, response_time_ms)
            VALUES (%s, %s, %s, %s, NOW(), %s)
            """,
            (user_id, username, message, role, response_time_ms),
        )
    conn.commit()

def get_chat_history(user_id, limit=3):
    """
    Ambil n chat terakhir untuk user_id tertentu.
    Return dalam urutan lama → baru.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT role, text FROM chat_logs
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (user_id, limit)
        )
        rows = cur.fetchall()
        return rows[::-1]  # Balik urutan agar kronologis
