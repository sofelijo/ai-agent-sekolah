from functools import wraps
from typing import Callable, Optional

from flask import (
    Blueprint,
    Response,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .queries import (
    create_dashboard_user,
    get_user_by_email,
    list_dashboard_users,
    update_last_login,
)

auth_bp = Blueprint("auth", __name__)


def current_user() -> Optional[dict]:
    return session.get("user")


def login_required(view: Callable) -> Callable:
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user():
            flash("Silakan login terlebih dahulu.", "warning")
            return redirect(url_for("admin.auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapper


def role_required(*roles: str) -> Callable:
    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                flash("Silakan login terlebih dahulu.", "warning")
                return redirect(url_for("auth.login", next=request.path))
            if user.get("role") not in roles:
                flash("Anda tidak memiliki akses ke fitur ini.", "danger")
                return redirect(url_for("admin.main.dashboard"))
            return view(*args, **kwargs)

        return wrapper

    return decorator


@auth_bp.route("/login", methods=["GET", "POST"])
def login() -> Response:
    if current_user():
        return redirect(url_for("admin.main.dashboard"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        remember = request.form.get("remember") == "on"

        user = get_user_by_email(email)
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Email atau password tidak valid.", "danger")
            return render_template("login.html", email=email)

        session["user"] = {
            "id": user["id"],
            "email": email,
            "full_name": user["full_name"],
            "role": user["role"],
        }
        session.permanent = remember
        update_last_login(user["id"])
        flash("Selamat datang kembali!", "success")
        redirect_target = request.args.get("next") or url_for("admin.main.dashboard")
        return redirect(redirect_target)

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout() -> Response:
    session.clear()
    flash("Anda telah logout.", "info")
    return redirect(url_for("admin.auth.login"))


@auth_bp.route("/settings/users", methods=["GET", "POST"])
@role_required("admin")
def manage_users() -> Response:
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        full_name = (request.form.get("full_name") or "").strip()
        password = request.form.get("password") or ""
        role = (request.form.get("role") or "viewer").strip()

        if not all([email, full_name, password]):
            flash("Semua field wajib diisi.", "warning")
        else:
            password_hash = generate_password_hash(password, method="pbkdf2:sha256", salt_length=12)
            try:
                create_dashboard_user(email=email, full_name=full_name, password_hash=password_hash, role=role)
                flash(f"User {full_name} berhasil dibuat.", "success")
            except Exception as exc:  # pragma: no cover - surfaces to UI
                flash(f"Gagal membuat user baru: {exc}", "danger")

    users = list_dashboard_users()
    return render_template("manage_users.html", users=users)

