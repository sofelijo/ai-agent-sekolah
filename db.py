# db.py

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()  # kalau kamu pakai .env

# Koneksi ke PostgreSQL
conn = psycopg2.connect(
    dbname=os.getenv("DB_NAME", "aska_db"),
    user=os.getenv("DB_USER", "postgres"),
    password=os.getenv("DB_PASS", "Perbarui1!"),
    host=os.getenv("DB_HOST", "localhost"),
    port=os.getenv("DB_PORT", "5432")
)

def save_chat(user_id, username, message, role, topic=None):
    """Simpan chat ke tabel chat_logs."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chat_logs (user_id, username, text, role, topic)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, username, message, role, topic)
        )
    conn.commit()   

def get_chat_history(user_id, limit=3):
    """Ambil n chat terakhir untuk user_id tertentu."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT role, text FROM chat_logs
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (user_id, limit))
        rows = cur.fetchall()
        # balik urutan supaya yang lama duluan
        return rows[::-1]
