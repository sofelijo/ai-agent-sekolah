import os
import sys
import traceback
from dashboard.db_access import get_cursor

# Add the project root to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def add_is_labeled_column():
    """Adds is_labeled column to book_items table."""
    print("Adding 'is_labeled' column to 'book_items'...")
    try:
        with get_cursor(commit=True) as cur:
            cur.execute("""
                ALTER TABLE book_items 
                ADD COLUMN IF NOT EXISTS is_labeled BOOLEAN DEFAULT FALSE
            """)
            print("   -> Success: Column 'is_labeled' added.")
            
    except Exception as e:
        print(f"   -> Failed: {e}", file=sys.stderr)
        traceback.print_exc()
        raise

if __name__ == "__main__":
    add_is_labeled_column()
