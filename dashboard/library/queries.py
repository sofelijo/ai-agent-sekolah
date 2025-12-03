from typing import List, Optional, Dict, Any, Tuple
from ..db_access import get_cursor

def get_all_books(search_query: str = "", page: int = 1, per_page: int = 10) -> Tuple[List[Dict[str, Any]], int]:
    offset = (page - 1) * per_page
    with get_cursor() as cur:
        # Base query parts
        base_query = "FROM books b"
        where_clause = ""
        params = []
        
        if search_query:
            where_clause = "WHERE b.title ILIKE %s OR b.author ILIKE %s OR b.code ILIKE %s"
            search_term = f"%{search_query}%"
            params.extend([search_term, search_term, search_term])

        # Get total count
        count_query = f"SELECT COUNT(*) {base_query} {where_clause}"
        cur.execute(count_query, tuple(params))
        total_items = cur.fetchone()[0]

        # Get paginated books
        # Stock is now calculated from available items
        query = f"""
            SELECT b.id, b.title, b.author, b.publisher, b.year, b.code, 
                   (SELECT COUNT(*) FROM book_items bi WHERE bi.book_id = b.id AND bi.status = 'available') as stock,
                   b.location,
                   (SELECT COUNT(*) FROM borrowing_records br WHERE br.book_id = b.id AND br.status = 'borrowed') as borrowed_count,
                   (SELECT COUNT(*) FROM book_items bi WHERE bi.book_id = b.id) as total_items
            {base_query}
            {where_clause}
            ORDER BY b.created_at DESC
            LIMIT %s OFFSET %s
        """
        params.extend([per_page, offset])
        
        cur.execute(query, tuple(params))
        columns = [desc[0] for desc in cur.description]
        books = [dict(zip(columns, row)) for row in cur.fetchall()]
        
        return books, total_items

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
        # Insert book
        cur.execute("""
            INSERT INTO books (title, author, publisher, year, code, stock, location)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (title, author, publisher, year, code, stock, location))
        book_id = cur.fetchone()[0]
        
        # Create items
        for i in range(stock):
            qr_code = f"{code}-{i+1}"
            cur.execute("""
                INSERT INTO book_items (book_id, qr_code, status)
                VALUES (%s, %s, 'available')
            """, (book_id, qr_code))

def update_book(book_id: int, title: str, author: str, publisher: str, year: int, stock: int, location: str) -> None:
    # Note: 'stock' argument here is treated as "target total stock". 
    
    with get_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE books 
            SET title = %s, author = %s, publisher = %s, year = %s, location = %s
            WHERE id = %s
        """, (title, author, publisher, year, location, book_id))
        
        # Check current total items
        cur.execute("SELECT COUNT(*) FROM book_items WHERE book_id = %s", (book_id,))
        current_total = cur.fetchone()[0]
        
        if stock > current_total:
            # Add more items
            to_add = stock - current_total
            
            # Get book code to generate QR
            cur.execute("SELECT code FROM books WHERE id = %s", (book_id,))
            code = cur.fetchone()[0]
            
            # Find max sequence number
            # Assuming format code-seq
            cur.execute("""
                SELECT qr_code FROM book_items WHERE book_id = %s
            """, (book_id,))
            existing_qrs = [row[0] for row in cur.fetchall()]
            
            max_seq = 0
            for qr in existing_qrs:
                try:
                    parts = qr.split('-')
                    if len(parts) > 1:
                        seq = int(parts[-1])
                        if seq > max_seq:
                            max_seq = seq
                except ValueError:
                    pass
            
            for i in range(to_add):
                max_seq += 1
                qr_code = f"{code}-{max_seq}"
                cur.execute("""
                    INSERT INTO book_items (book_id, qr_code, status)
                    VALUES (%s, %s, 'available')
                """, (book_id, qr_code))
        
        elif stock < current_total:
            # Reduce items (only available ones)
            to_remove = current_total - stock
            
            # Get available items, ordered by sequence number descending (try to remove newest first)
            # We rely on ID or QR code to guess "newest". ID is safer.
            cur.execute("""
                SELECT id FROM book_items 
                WHERE book_id = %s AND status = 'available'
                ORDER BY id DESC
                LIMIT %s
            """, (book_id, to_remove))
            
            items_to_delete = [row[0] for row in cur.fetchall()]
            
            if items_to_delete:
                cur.execute("""
                    DELETE FROM book_items WHERE id = ANY(%s)
                """, (items_to_delete,))

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

def borrow_book(student_id: int, item_qr_code: str, user_id: int) -> str:
    """
    Returns 'success', 'item_not_found', 'item_not_available', 'already_borrowed'
    """
    with get_cursor(commit=True) as cur:
        # Check item availability
        cur.execute("""
            SELECT bi.id, bi.book_id, bi.status, b.title 
            FROM book_items bi
            JOIN books b ON bi.book_id = b.id
            WHERE bi.qr_code = %s FOR UPDATE
        """, (item_qr_code,))
        item = cur.fetchone()
        
        if not item:
            return 'item_not_found'
        
        item_id, book_id, status, title = item
        
        if status != 'available':
            return 'item_not_available'

        # Check if student already borrowing THIS specific item (unlikely if status is available, but good check)
        # Or check if student borrowing ANY copy of this book? Maybe we allow multiple copies?
        # Let's restrict: Student cannot borrow the SAME book title twice if not returned?
        # For now, let's just check if they are borrowing this specific item (which is covered by status check)
        # But let's check if they have unreturned book of same title?
        # The user didn't specify, but usually library rules prevent borrowing same title twice.
        # Let's stick to simple: can borrow if item is available.
        
        # Record borrowing
        cur.execute("""
            INSERT INTO borrowing_records (student_id, book_id, book_item_id, recorded_by, status)
            VALUES (%s, %s, %s, %s, 'borrowed')
        """, (student_id, book_id, item_id, user_id))

        # Update item status
        cur.execute("UPDATE book_items SET status = 'borrowed' WHERE id = %s", (item_id,))
        
        # Update book stock cache (optional, but we are moving away from it)
        # cur.execute("UPDATE books SET stock = stock - 1 WHERE id = %s", (book_id,))
        
        return 'success'

def get_borrowings(student_id: Optional[int] = None, search_query: str = "") -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        query = """
            SELECT br.id, b.title, b.code as book_code, bi.qr_code as item_qr_code,
                   TO_CHAR(br.borrow_date, 'YYYY-MM-DD') as borrow_date, 
                   TO_CHAR(br.due_date, 'YYYY-MM-DD') as due_date, 
                   br.status,
                   s.full_name as student_name,
                   c.name as class_name,
                   u.full_name as recorded_by_name
            FROM borrowing_records br
            LEFT JOIN books b ON br.book_id = b.id
            LEFT JOIN book_items bi ON br.book_item_id = bi.id
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
            query += " AND (b.title ILIKE %s OR s.full_name ILIKE %s OR bi.qr_code ILIKE %s)"
            search_term = f"%{search_query}%"
            params.extend([search_term, search_term, search_term])
            
        query += " ORDER BY br.updated_at DESC LIMIT 50"
        
        cur.execute(query, tuple(params))
        columns = [desc[0] for desc in cur.description]
        results = [dict(zip(columns, row)) for row in cur.fetchall()]
        return results

def return_book(borrow_id: int) -> None:
    with get_cursor(commit=True) as cur:
        # Get book_item_id and current status
        cur.execute("SELECT book_item_id, status FROM borrowing_records WHERE id = %s", (borrow_id,))
        row = cur.fetchone()
        if not row:
            return
        book_item_id, status = row
        
        if status == 'returned':
            return # Already returned

        # Update record
        cur.execute("""
            UPDATE borrowing_records 
            SET status = 'returned', return_date = CURRENT_DATE, updated_at = NOW()
            WHERE id = %s
        """, (borrow_id,))

        # Update item status
        if book_item_id:
            cur.execute("UPDATE book_items SET status = 'available' WHERE id = %s", (book_item_id,))

def cancel_return_book(borrow_id: int) -> None:
    with get_cursor(commit=True) as cur:
        # Get book_item_id and current status
        cur.execute("SELECT book_item_id, status FROM borrowing_records WHERE id = %s", (borrow_id,))
        row = cur.fetchone()
        if not row:
            return
        book_item_id, status = row
        
        if status == 'borrowed':
            return # Already borrowed

        # Update record
        cur.execute("""
            UPDATE borrowing_records 
            SET status = 'borrowed', return_date = NULL, updated_at = NOW()
            WHERE id = %s
        """, (borrow_id,))

        # Update item status
        if book_item_id:
            cur.execute("UPDATE book_items SET status = 'borrowed' WHERE id = %s", (book_item_id,))

def get_book_items(book_id: int, page: int = 1, per_page: int = 20) -> Tuple[List[Dict[str, Any]], int]:
    offset = (page - 1) * per_page
    with get_cursor() as cur:
        # Get total count
        cur.execute("SELECT COUNT(*) FROM book_items WHERE book_id = %s", (book_id,))
        total_items = cur.fetchone()[0]

        # Get paginated items
        cur.execute("""
            SELECT id, qr_code, status, created_at, is_labeled
            FROM book_items
            WHERE book_id = %s
            ORDER BY id ASC
            LIMIT %s OFFSET %s
        """, (book_id, per_page, offset))
        
        columns = [desc[0] for desc in cur.description]
        items = [dict(zip(columns, row)) for row in cur.fetchall()]
        
        return items, total_items

def get_item_by_qr(qr_code: str) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute("""
            SELECT bi.id, bi.qr_code, bi.status, b.title, b.author, b.code as book_code, bi.is_labeled
            FROM book_items bi
            JOIN books b ON bi.book_id = b.id
            WHERE bi.qr_code = %s
        """, (qr_code,))
        row = cur.fetchone()
        if row:
            columns = [desc[0] for desc in cur.description]
            return dict(zip(columns, row))
        return None

def get_all_items(search_query: str = "", page: int = 1, per_page: int = 20) -> Tuple[List[Dict[str, Any]], int]:
    offset = (page - 1) * per_page
    with get_cursor() as cur:
        base_query = """
            FROM book_items bi
            JOIN books b ON bi.book_id = b.id
        """
        where_clause = ""
        params = []
        
        if search_query:
            where_clause = "WHERE bi.qr_code ILIKE %s OR b.title ILIKE %s"
            params = [f"%{search_query}%", f"%{search_query}%"]

        # Get total count
        count_query = f"SELECT COUNT(*) {base_query} {where_clause}"
        cur.execute(count_query, tuple(params))
        total_items = cur.fetchone()[0]

        # Get paginated items
        query = f"""
            SELECT bi.id, bi.qr_code, bi.status, bi.created_at, b.title, b.code as book_code, bi.is_labeled
            {base_query}
            {where_clause}
            ORDER BY bi.created_at DESC
            LIMIT %s OFFSET %s
        """
        params.extend([per_page, offset])
        
        cur.execute(query, tuple(params))
        columns = [desc[0] for desc in cur.description]
        items = [dict(zip(columns, row)) for row in cur.fetchall()]
        
        return items, total_items

def update_item(item_id: int, status: str, qr_code: str) -> None:
    with get_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE book_items 
            SET status = %s, qr_code = %s
            WHERE id = %s
        """, (status, qr_code, item_id))

def delete_item(item_id: int) -> None:
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM book_items WHERE id = %s", (item_id,))

def get_book_by_code(code: str) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM books WHERE code = %s", (code,))
        row = cur.fetchone()
        if row:
            columns = [desc[0] for desc in cur.description]
            return dict(zip(columns, row))
        return None

def add_item_to_book(book_id: int) -> None:
    with get_cursor(commit=True) as cur:
        # Get book code
        cur.execute("SELECT code FROM books WHERE id = %s", (book_id,))
        res = cur.fetchone()
        if not res:
            return
        code = res[0]
        
        # Find max sequence
        cur.execute("SELECT qr_code FROM book_items WHERE book_id = %s", (book_id,))
        existing_qrs = [row[0] for row in cur.fetchall()]
        
        max_seq = 0
        for qr in existing_qrs:
            try:
                parts = qr.split('-')
                if len(parts) > 1:
                    seq = int(parts[-1])
                    if seq > max_seq:
                        max_seq = seq
            except ValueError:
                pass
        
        new_qr = f"{code}-{max_seq + 1}"
        
        cur.execute("""
            INSERT INTO book_items (book_id, qr_code, status)
            VALUES (%s, %s, 'available')
        """, (book_id, new_qr))
        
        # Update stock count in books table (optional, but good for consistency if we still use it)
        cur.execute("UPDATE books SET stock = stock + 1 WHERE id = %s", (book_id,))

def update_item_label_status(item_id: int, is_labeled: bool) -> None:
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE book_items SET is_labeled = %s WHERE id = %s", (is_labeled, item_id))

def bulk_update_item_labels(item_ids: List[int], is_labeled: bool) -> None:
    if not item_ids:
        return
    # Ensure all IDs are integers
    item_ids = [int(id) for id in item_ids]
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE book_items SET is_labeled = %s WHERE id = ANY(%s)", (is_labeled, item_ids))
