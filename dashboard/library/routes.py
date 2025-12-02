from flask import render_template, request, flash, redirect, url_for, jsonify
from ..auth import login_required, current_user
from . import library_bp
from .queries import (
    get_all_books, add_book, get_book_by_code, search_students, 
    borrow_book, return_book, get_student_by_id,
    get_next_book_code, get_book_items, get_item_by_qr
)

@library_bp.route("/")
@login_required
def index():
    return redirect(url_for("library.borrow"))

@library_bp.route("/borrow", methods=["GET", "POST"])
@login_required
def borrow():
    student_id = request.args.get("student_id")
    student = None
    borrowings = []
    
    if student_id:
        try:
            student_id_int = int(student_id)
            student = get_student_by_id(student_id_int)

            if student:
                from .queries import get_borrowings
                borrowings = get_borrowings(student_id=student_id_int)
        except ValueError:
            pass
    
    if request.method == "POST":
        item_qr_code = request.form.get("item_qr_code")
        student_id = request.form.get("student_id")
        
        if not item_qr_code or not student_id:
            flash("Data tidak lengkap", "error")
        else:
            user = current_user()
            result = borrow_book(int(student_id), item_qr_code, user["id"])
            if result == 'success':
                flash("Buku berhasil dipinjam", "success")
            elif result == 'item_not_found':
                flash("Item buku tidak ditemukan", "error")
            elif result == 'item_not_available':
                flash("Item buku sedang dipinjam atau tidak tersedia", "error")
            elif result == 'already_borrowed':
                flash("Siswa sedang meminjam buku ini", "warning")
            
            return redirect(url_for("library.borrow", student_id=student_id))

    return render_template("library/borrow.html", student_id=student_id, student=student, borrowings=borrowings)

@library_bp.route("/books", methods=["GET", "POST"])
@login_required
def books():
    if request.method == "POST":
        title = request.form.get("title")
        author = request.form.get("author")
        publisher = request.form.get("publisher")
        year = request.form.get("year")
        code = request.form.get("code")
        stock = request.form.get("stock")
        location = request.form.get("location")
        
        if not code:
            code = get_next_book_code()
        
        try:
            add_book(title, author, publisher, int(year) if year else None, code, int(stock) if stock else 1, location)
            flash("Buku berhasil ditambahkan", "success")
        except Exception as e:
            flash(f"Gagal menambahkan buku: {e}", "error")
        
        return redirect(url_for("library.books"))
    
    search_query = request.args.get("q", "")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    if per_page not in [10, 20, 50]:
        per_page = 10
        
    all_books, total_items = get_all_books(search_query, page, per_page)
    total_pages = (total_items + per_page - 1) // per_page
    next_code = get_next_book_code()
    
    return render_template(
        "library/books.html", 
        books=all_books, 
        next_code=next_code, 
        search_query=search_query,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_items=total_items
    )

@library_bp.route("/books/update/<int:book_id>", methods=["POST"])
@login_required
def update_book_route(book_id):
    title = request.form.get("title")
    author = request.form.get("author")
    publisher = request.form.get("publisher")
    year = request.form.get("year")
    stock = request.form.get("stock")
    location = request.form.get("location")
    
    try:
        from .queries import update_book
        update_book(book_id, title, author, publisher, int(year) if year else None, int(stock) if stock else 1, location)
        flash("Buku berhasil diperbarui", "success")
    except Exception as e:
        flash(f"Gagal memperbarui buku: {e}", "error")
        
    return redirect(url_for("library.books"))

@library_bp.route("/books/delete/<int:book_id>", methods=["POST"])
@login_required
def delete_book_route(book_id):
    try:
        from .queries import delete_book
        delete_book(book_id)
        flash("Buku berhasil dihapus", "success")
    except Exception as e:
        # Check for foreign key constraint (if book is borrowed)
        if "foreign key constraint" in str(e).lower():
             flash("Buku tidak bisa dihapus karena sedang dipinjam atau ada riwayat peminjaman.", "error")
        else:
             flash(f"Gagal menghapus buku: {e}", "error")
        
    return redirect(url_for("library.books"))

@library_bp.route("/items/<int:book_id>")
@login_required
def book_items(book_id):
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    if per_page not in [10, 20, 50]:
        per_page = 10
    
    items, total_items = get_book_items(book_id, page, per_page)
    total_pages = (total_items + per_page - 1) // per_page
    
    # Get book details for title
    from .queries import get_cursor
    with get_cursor() as cur:
        cur.execute("SELECT * FROM books WHERE id = %s", (book_id,))
        columns = [desc[0] for desc in cur.description]
        book = dict(zip(columns, cur.fetchone()))
        
    return render_template(
        "library/items.html", 
        book=book, 
        items=items,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_items=total_items
    )

@library_bp.route("/api/students/search")
@login_required
def api_search_students():
    query = request.args.get("q", "")
    if len(query) < 3:
        return jsonify([])
    students = search_students(query)
    return jsonify(students)

@library_bp.route("/api/borrowings")
@login_required
def api_borrowings():
    student_id = request.args.get("student_id")
    search_query = request.args.get("q", "")
    
    student_id_int = int(student_id) if student_id and student_id.isdigit() else None
    
    from .queries import get_borrowings
    borrowings = get_borrowings(student_id=student_id_int, search_query=search_query)
    return jsonify(borrowings)

@library_bp.route("/api/items/check")
@login_required
def api_check_item():
    qr_code = request.args.get("qr_code")
    if not qr_code:
        return jsonify({"error": "No QR code provided"}), 400
        
    item = get_item_by_qr(qr_code)
    if item:
        return jsonify(item)
    else:
        return jsonify({"error": "Item not found"}), 404

@library_bp.route("/return/<int:borrow_id>", methods=["POST"])
@login_required
def return_item(borrow_id):
    return_book(borrow_id)
    flash("Buku berhasil dikembalikan", "success")
    return redirect(request.referrer or url_for("library.borrow"))

@library_bp.route("/cancel_return/<int:borrow_id>", methods=["POST"])
@login_required
def cancel_return_item(borrow_id):
    from .queries import cancel_return_book
    cancel_return_book(borrow_id)
    flash("Status buku dikembalikan ke 'Dipinjam'", "success")
    return redirect(request.referrer or url_for("library.borrow"))

@library_bp.route("/all_items")
@login_required
def all_items():
    search_query = request.args.get("q", "")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    if per_page not in [10, 20, 50]:
        per_page = 10
    
    from .queries import get_all_items
    items, total_items = get_all_items(search_query, page, per_page)
    total_pages = (total_items + per_page - 1) // per_page
    
    return render_template(
        "library/all_items.html", 
        items=items, 
        search_query=search_query,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_items=total_items
    )

@library_bp.route("/items/update/<int:item_id>", methods=["POST"])
@login_required
def update_item_route(item_id):
    status = request.form.get("status")
    qr_code = request.form.get("qr_code")
    
    try:
        from .queries import update_item
        update_item(item_id, status, qr_code)
        flash("Item buku berhasil diperbarui", "success")
    except Exception as e:
        flash(f"Gagal memperbarui item: {e}", "error")
        
    return redirect(request.referrer or url_for("library.all_items"))

@library_bp.route("/items/delete/<int:item_id>", methods=["POST"])
@login_required
def delete_item_route(item_id):
    try:
        from .queries import delete_item
        delete_item(item_id)
        flash("Item buku berhasil dihapus", "success")
    except Exception as e:
        if "foreign key constraint" in str(e).lower():
             flash("Item tidak bisa dihapus karena sedang dipinjam atau ada riwayat peminjaman.", "error")
        else:
             flash(f"Gagal menghapus item: {e}", "error")
        
    return redirect(request.referrer or url_for("library.all_items"))

@library_bp.route("/items/smart_add", methods=["POST"])
@login_required
def smart_add_item():
    code = request.form.get("code")
    title = request.form.get("title")
    author = request.form.get("author")
    publisher = request.form.get("publisher")
    year = request.form.get("year")
    location = request.form.get("location")
    
    if not code or not title:
        flash("Kode dan Judul buku wajib diisi", "error")
        return redirect(url_for("library.all_items"))
        
    try:
        from .queries import get_book_by_code, add_item_to_book, add_book
        
        book = get_book_by_code(code)
        
        if book:
            # Book exists, add new item
            add_item_to_book(book['id'])
            flash(f"Item baru berhasil ditambahkan ke buku '{book['title']}'", "success")
        else:
            # Book doesn't exist, create new book with stock 1
            try:
                year_int = int(year) if year else 0
            except ValueError:
                year_int = 0
                
            add_book(title, author, publisher, year_int, code, 1, location)
            flash(f"Buku baru '{title}' berhasil dibuat dengan 1 item", "success")
            
    except Exception as e:
        flash(f"Terjadi kesalahan: {e}", "error")
        
    return redirect(url_for("library.all_items"))

@library_bp.route("/api/books/search")
@login_required
def api_search_books():
    query = request.args.get("q", "")
    if len(query) < 1:
        return jsonify([])
        
    from .queries import get_all_books
    # Reuse get_all_books which already handles search by title/code
    books = get_all_books(query)
    # Limit results for autocomplete
    return jsonify(books[:10])

@library_bp.route("/api/items/toggle_label/<int:item_id>", methods=["POST"])
@login_required
def toggle_item_label(item_id):
    data = request.get_json()
    is_labeled = data.get("is_labeled", False)
    
    try:
        from .queries import update_item_label_status
        update_item_label_status(item_id, is_labeled)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@library_bp.route("/api/items/bulk_label", methods=["POST"])
@login_required
def bulk_label_items():
    data = request.get_json()
    item_ids = data.get("item_ids", [])
    is_labeled = data.get("is_labeled", True)
    
    if not item_ids:
        return jsonify({"error": "No items provided"}), 400
        
    try:
        from .queries import bulk_update_item_labels
        bulk_update_item_labels(item_ids, is_labeled)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
