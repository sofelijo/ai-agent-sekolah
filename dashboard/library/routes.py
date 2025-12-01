from flask import render_template, request, flash, redirect, url_for, jsonify
from ..auth import login_required, current_user
from . import library_bp
from .queries import (
    get_all_books, add_book, get_book_by_code, search_students, 
    borrow_book, return_book, get_student_by_id,
    get_next_book_code
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
        book_code = request.form.get("book_code")
        student_id = request.form.get("student_id")
        
        if not book_code or not student_id:
            flash("Data tidak lengkap", "error")
        else:
            user = current_user()
            result = borrow_book(int(student_id), book_code, user["id"])
            if result == 'success':
                flash("Buku berhasil dipinjam", "success")
            elif result == 'book_not_found':
                flash("Buku tidak ditemukan", "error")
            elif result == 'out_of_stock':
                flash("Stok buku habis", "error")
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
    all_books = get_all_books(search_query)
    next_code = get_next_book_code()
    return render_template("library/books.html", books=all_books, next_code=next_code, search_query=search_query)

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
