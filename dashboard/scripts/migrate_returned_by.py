
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard.db_access import get_cursor

def migrate():
    print("Running migration: Adding returned_by to borrowing_records...")
    with get_cursor(commit=True) as cur:
        try:
            cur.execute("""
                ALTER TABLE borrowing_records 
                ADD COLUMN IF NOT EXISTS returned_by INTEGER REFERENCES dashboard_users(id) ON DELETE SET NULL
            """)
            print("Migration successful: returned_by column added.")
        except Exception as e:
            print(f"Migration failed: {e}")

if __name__ == "__main__":
    migrate()
