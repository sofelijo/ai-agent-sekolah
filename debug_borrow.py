from dashboard.db_access import get_cursor
from dashboard.library.queries import get_borrowings

def debug_borrowings():
    with get_cursor() as cur:
        print("--- Checking borrowing_records ---")
        cur.execute("SELECT * FROM borrowing_records")
        records = cur.fetchall()
        for r in records:
            print(r)
            
        print("\n--- Checking students ---")
        cur.execute("SELECT id, full_name, class_id FROM students LIMIT 5")
        for r in cur.fetchall():
            print(r)

        print("\n--- Checking school_classes ---")
        cur.execute("SELECT * FROM school_classes LIMIT 5")
        for r in cur.fetchall():
            print(r)
            
        print("\n--- Testing get_borrowings() ---")
        try:
            results = get_borrowings()
            print(f"Found {len(results)} records")
            for r in results:
                print(r)
        except Exception as e:
            print(f"Error in get_borrowings: {e}")

if __name__ == "__main__":
    debug_borrowings()
