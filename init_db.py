import os
import sys
import traceback

# Add the project root to the path to allow importing from 'dashboard'
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def initialize_main_schemas():
    """Initializes schemas from the root db.py module."""
    print("1. Memulai inisialisasi skema utama (dari db.py)...")
    try:
        # Importing the 'db' module executes its top-level schema creation
        import db
        print("   -> Sukses: Skema utama telah diperiksa/dibuat.")
        print("      - chat_logs, bullying_reports, psych_reports, web_users, corruption_reports, twitter_worker_logs")
    except Exception as e:
        print(f"   -> Gagal menginisialisasi skema utama: {e}", file=sys.stderr)
        traceback.print_exc()
        raise

def initialize_dashboard_schemas():
    """Initializes schemas required by the dashboard application."""
    print("\n2. Memulai inisialisasi skema dashboard (dari dashboard/schema.py)...")
    try:
        from dashboard.schema import ensure_dashboard_schema
        from dashboard.db_access import get_cursor, shutdown_pool

        print("   - Menjalankan `ensure_dashboard_schema()`...")
        ensure_dashboard_schema()
        
        # Close connections
        shutdown_pool()

        print("   -> Sukses: Skema dashboard telah diperiksa/dibuat.")
        print("      - dashboard_users, bullying_report_events, notifications")
        print("      - Memperbarui tabel 'bullying_reports' dengan kolom dan constraint terbaru.")

    except ImportError as e:
        print(f"   -> Gagal: Tidak dapat mengimpor modul dashboard. Pastikan struktur direktori benar.", file=sys.stderr)
        print(f"      Detail: {e}", file=sys.stderr)
        traceback.print_exc()
        raise
    except Exception as e:
        print(f"   -> Gagal menginisialisasi skema dashboard: {e}", file=sys.stderr)
        traceback.print_exc()
        raise

if __name__ == "__main__":
    print("========================================")
    print("INISIALISASI DATABASE LENGKAP")
    print("========================================")
    print("Skrip ini akan memeriksa dan membuat semua tabel, kolom, dan indeks yang diperlukan untuk proyek.\n")
    
    try:
        # Check for .env file
        if not os.path.exists('.env'):
             print("PERINGATAN: File .env tidak ditemukan. Koneksi database mungkin gagal.", file=sys.stderr)
             print("Pastikan Anda telah menyalin .env.template ke .env dan mengisinya.\n", file=sys.stderr)

        initialize_main_schemas()
        initialize_dashboard_schemas()
        
        print("\n========================================")
        print("Inisialisasi Selesai!")
        print("Semua skema database telah berhasil disiapkan.")
        print("========================================")
        sys.exit(0)

    except Exception:
        print("\n========================================", file=sys.stderr)
        print("INISIALISASI GAGAL", file=sys.stderr)
        print("Satu atau lebih langkah inisialisasi database gagal. Silakan periksa log error di atas.", file=sys.stderr)
        print("========================================", file=sys.stderr)
        sys.exit(1)