from dashboard.db_access import get_cursor

def verify_import():
    with get_cursor() as cur:
        # 1. Total books
        cur.execute("SELECT COUNT(*) FROM books")
        total_books = cur.fetchone()[0]
        print(f"Total Books: {total_books}")
        
        # 2. Total items
        cur.execute("SELECT COUNT(*) FROM book_items")
        total_items = cur.fetchone()[0]
        print(f"Total Items: {total_items}")
        
        # 3. Sample by location
        print("\n--- Sample by Location ---")
        cur.execute("""
            SELECT location, COUNT(*) 
            FROM books 
            GROUP BY location 
            ORDER BY location
        """)
        for loc, count in cur.fetchall():
            print(f"{loc}: {count} books")
            
        # 4. Check a few specific books
        print("\n--- Sample Books ---")
        cur.execute("""
            SELECT title, year, publisher, stock, location, code
            FROM books 
            ORDER BY id DESC 
            LIMIT 5
        """)
        for row in cur.fetchall():
            print(f"Title: {row[0]}, Year: {row[1]}, Pub: {row[2]}, Stock: {row[3]}, Loc: {row[4]}, Code: {row[5]}")

if __name__ == "__main__":
    verify_import()
