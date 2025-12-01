from typing import List, Optional, Dict, Any
from ..db_access import get_cursor

def get_all_books(search_query: str = "") -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        query = """
            SELECT b.id, b.title, b.author, b.publisher, b.year, b.code, b.stock, b.location,
                   (SELECT COUNT(*) FROM borrowing_records br WHERE br.book_id = b.id AND br.status = 'borrowed') as borrowed_count
            FROM books b
        """
        params = []
        
        if search_query:
            query += " WHERE b.title ILIKE %s OR b.author ILIKE %s OR b.code ILIKE %s"
            search_term = f"%{search_query}%"
            params.extend([search_term, search_term, search_term])
            
        query += " ORDER BY b.created_at DESC"
        
        cur.execute(query, tuple(params))
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

def get_next_book_code() -> str:
    with get_cursor() as cur:
        # Try to find the max integer code. 
        # We use a regex to match only codes that are purely digits to avoid issues with alphanumeric codes.
        cur.execute("""
            SELECT MAX(CAST(code AS INTEGER)) 
            FROM books 
            WHERE code ~ '^[0-9]+$'
        """)
        row = cur.fetchone()
        max_code = row[0] if row and row[0] is not None else 0
        return str(max_code + 1)

def add_book(title: str, author: str, publisher: str, year: int, code: str, stock: int, location: str) -> None:
    with get_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO books (title, author, publisher, year, code, stock, location)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (title, author, publisher, year, code, stock, location))

def update_book(book_id: int, title: str, author: str, publisher: str, year: int, stock: int, location: str) -> None:
    with get_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE books 
            SET title = %s, author = %s, publisher = %s, year = %s, stock = %s, location = %s
            WHERE id = %s
        """, (title, author, publisher, year, stock, location, book_id))

def delete_book(book_id: int) -> None:
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM books WHERE id = %s", (book_id,))

def get_book_by_code(code: str) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute("""
            SELECT id, title, author, publisher, year, code, stock, location
            FROM books
            WHERE code = %s
        """, (code,))
        row = cur.fetchone()
        if row:
            columns = [desc[0] for desc in cur.description]
            return dict(zip(columns, row))
        return None

def get_student_by_id(student_id: int) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute("""
            SELECT s.id, s.full_name, c.name as class_name
            FROM students s
            JOIN school_classes c ON s.class_id = c.id
            WHERE s.id = %s
        """, (student_id,))
        row = cur.fetchone()
        if row:
            columns = [desc[0] for desc in cur.description]
            return dict(zip(columns, row))
        return None

def search_students(query: str) -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute("""
            SELECT s.id, s.full_name, c.name as class_name
            FROM students s
            JOIN school_classes c ON s.class_id = c.id
            WHERE s.full_name ILIKE %s OR s.nisn ILIKE %s
            LIMIT 10
        """, (f"%{query}%", f"%{query}%"))
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

def borrow_book(student_id: int, book_code: str, user_id: int) -> str:
    """
    Returns 'success', 'book_not_found', 'out_of_stock', or 'already_borrowed'
    """
    with get_cursor(commit=True) as cur:
        # Check book availability
        cur.execute("SELECT id, stock FROM books WHERE code = %s FOR UPDATE", (book_code,))
        book = cur.fetchone()
        if not book:
            return 'book_not_found'
        
        book_id, stock = book
        if stock <= 0:
            return 'out_of_stock'

        # Check if already borrowed (and not returned)
        cur.execute("""
            SELECT id FROM borrowing_records 
            WHERE student_id = %s AND book_id = %s AND status = 'borrowed'
        """, (student_id, book_id))
        if cur.fetchone():
            return 'already_borrowed'

        # Record borrowing
        cur.execute("""
            INSERT INTO borrowing_records (student_id, book_id, recorded_by, status)
            VALUES (%s, %s, %s, 'borrowed')
        """, (student_id, book_id, user_id))

        # Decrease stock
        cur.execute("UPDATE books SET stock = stock - 1 WHERE id = %s", (book_id,))
        
        return 'success'

def get_borrowings(student_id: Optional[int] = None, search_query: str = "") -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        query = """
            SELECT br.id, b.title, b.code, 
                   TO_CHAR(br.borrow_date, 'YYYY-MM-DD') as borrow_date, 
                   TO_CHAR(br.due_date, 'YYYY-MM-DD') as due_date, 
                   br.status,
                   s.full_name as student_name,
                   c.name as class_name,
                   u.full_name as recorded_by_name
            FROM borrowing_records br
            LEFT JOIN books b ON br.book_id = b.id
            LEFT JOIN students s ON br.student_id = s.id
            LEFT JOIN school_classes c ON s.class_id = c.id
            LEFT JOIN dashboard_users u ON br.recorded_by = u.id
            WHERE br.status IN ('borrowed', 'returned')
        """
        params = []
        
        if student_id:
            query += " AND br.student_id = %s"
            params.append(student_id)
            
        if search_query:
            query += " AND (b.title ILIKE %s OR s.full_name ILIKE %s)"
            search_term = f"%{search_query}%"
            params.extend([search_term, search_term])
            
        query += " ORDER BY br.updated_at DESC LIMIT 50"
        
        cur.execute(query, tuple(params))
        columns = [desc[0] for desc in cur.description]
        results = [dict(zip(columns, row)) for row in cur.fetchall()]
        print(f"DEBUG: get_borrowings(student_id={student_id}, search={search_query}) found {len(results)} records")
        return results

def return_book(borrow_id: int) -> None:
    with get_cursor(commit=True) as cur:
        # Get book_id and current status
        cur.execute("SELECT book_id, status FROM borrowing_records WHERE id = %s", (borrow_id,))
        row = cur.fetchone()
        if not row:
            return
        book_id, status = row
        
        if status == 'returned':
            return # Already returned

        # Update record
        cur.execute("""
            UPDATE borrowing_records 
            SET status = 'returned', return_date = CURRENT_DATE, updated_at = NOW()
            WHERE id = %s
        """, (borrow_id,))

        # Increase stock
        cur.execute("UPDATE books SET stock = stock + 1 WHERE id = %s", (book_id,))

def cancel_return_book(borrow_id: int) -> None:
    with get_cursor(commit=True) as cur:
        # Get book_id and current status
        cur.execute("SELECT book_id, status FROM borrowing_records WHERE id = %s", (borrow_id,))
        row = cur.fetchone()
        if not row:
            return
        book_id, status = row
        
        if status == 'borrowed':
            return # Already borrowed

        # Update record
        cur.execute("""
            UPDATE borrowing_records 
            SET status = 'borrowed', return_date = NULL, updated_at = NOW()
            WHERE id = %s
        """, (borrow_id,))

        # Decrease stock
        cur.execute("UPDATE books SET stock = stock - 1 WHERE id = %s", (book_id,))
