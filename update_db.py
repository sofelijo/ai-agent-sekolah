
import os
import sys
import traceback

# Add the project root to the path to allow importing from 'dashboard'
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def update_web_users_table():
    """Updates the web_users table with photo_url and last_login columns."""
    print("Memulai pembaruan tabel 'web_users'...")
    try:
        import db
        print("   - Koneksi ke database berhasil.")
        
        with db.conn.cursor() as cur:
            print("   - Menambahkan kolom 'photo_url'...")
            cur.execute("ALTER TABLE web_users ADD COLUMN IF NOT EXISTS photo_url TEXT;")
            
            print("   - Menambahkan kolom 'last_login'...")
            cur.execute("ALTER TABLE web_users ADD COLUMN IF NOT EXISTS last_login TIMESTAMPTZ;")
            
            print("   - Mengisi nilai default untuk 'last_login' pada baris yang ada...")
            cur.execute("UPDATE web_users SET last_login = NOW() WHERE last_login IS NULL;")
            
            print("   - Mengatur 'last_login' agar NOT NULL dan memiliki nilai default...")
            cur.execute("ALTER TABLE web_users ALTER COLUMN last_login SET NOT NULL;")
            cur.execute("ALTER TABLE web_users ALTER COLUMN last_login SET DEFAULT NOW();")

        db.conn.commit()
        print("   -> Sukses: Tabel 'web_users' telah berhasil diperbarui.")
        
    except Exception as e:
        print(f"   -> Gagal memperbarui tabel 'web_users': {e}", file=sys.stderr)
        if 'db' in locals():
            db.conn.rollback()
        traceback.print_exc()
        raise

if __name__ == "__main__":
    print("========================================")
    print("PEMBARUAN SKEMA DATABASE")
    print("========================================")
    
    try:
        if not os.path.exists('.env'):
             print("PERINGATAN: File .env tidak ditemukan. Koneksi database mungkin gagal.", file=sys.stderr)
             print("Pastikan Anda telah menyalin .env.template ke .env dan mengisinya.\n", file=sys.stderr)

        update_web_users_table()
        
        print("\n========================================")
        print("Pembaruan Selesai!")
        print("Skema database telah berhasil diperbarui.")
        print("========================================")
        sys.exit(0)

    except Exception:
        print("\n========================================", file=sys.stderr)
        print("PEMBARUAN GAGAL", file=sys.stderr)
        print("Satu atau lebih langkah pembaruan database gagal. Silakan periksa log error di atas.", file=sys.stderr)
        print("========================================", file=sys.stderr)
        sys.exit(1)
