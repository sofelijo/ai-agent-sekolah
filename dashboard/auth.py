import os
import secrets
from functools import wraps
from typing import Callable, Optional

from authlib.integrations.flask_client import OAuth
from flask import (
    Blueprint,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
    current_app,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .queries import (
    create_dashboard_user,
    get_user_by_email,
    list_dashboard_users,
    update_last_login,
    fetch_aska_users,
    summarize_aska_users,
    update_web_user_status,
    update_telegram_user_status,
)
from account_status import (
    ACCOUNT_STATUS_CHOICES,
    ACCOUNT_STATUS_LABELS,
    ACCOUNT_STATUS_BADGES,
)

auth_bp = Blueprint("auth", __name__)
oauth = OAuth()

GMAIL_ALLOWED_DOMAINS = {"gmail.com", "googlemail.com"}
_OAUTH_REGISTERED = False


def init_oauth(app) -> None:
    """Initialize Google OAuth for the dashboard app."""
    global _OAUTH_REGISTERED
    oauth.init_app(app)
    if _OAUTH_REGISTERED:
        return

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        return

    oauth.register(
        name="google",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    _OAUTH_REGISTERED = True


def current_user() -> Optional[dict]:
    return session.get("user")


def login_required(view: Callable) -> Callable:
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user():
            flash("Silakan login terlebih dahulu.", "warning")
            return redirect(url_for("auth.login", next=request.path))
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
            role = user.get("role")
            if role not in roles:
                flash("Anda tidak memiliki akses ke fitur ini.", "danger")
                if role == "guru":
                    return redirect(url_for("attendance.dashboard"))
                return redirect(url_for("main.dashboard"))
            return view(*args, **kwargs)

        return wrapper

    return decorator


def _establish_session(user: dict, *, remember: bool = False, email_override: Optional[str] = None) -> None:
    """Populate the Flask session with the logged-in dashboard user."""
    raw_assigned_class = user.get("assigned_class_id")
    assigned_class_id = None
    if raw_assigned_class is not None:
        try:
            assigned_class_id = int(raw_assigned_class)
        except (TypeError, ValueError):
            assigned_class_id = None

    email_value = (email_override or user.get("email") or "").strip().lower()

    session["user"] = {
        "id": user["id"],
        "email": email_value,
        "full_name": user.get("full_name"),
        "role": user.get("role"),
        "no_tester_enabled": bool(user.get("no_tester_enabled")),
        "assigned_class_id": assigned_class_id,
    }
    session.permanent = remember
    update_last_login(user["id"])


def _redirect_after_login(user: dict, fallback: Optional[str] = None) -> str:
    """Determine the appropriate redirect destination after login."""
    if user.get("role") == "guru":
        return url_for("attendance.dashboard")
    return fallback or url_for("main.dashboard")


@auth_bp.route("/login", methods=["GET", "POST"])
def login() -> Response:
    existing = current_user()
    if existing:
        if existing.get("role") == "guru":
            return redirect(url_for("attendance.dashboard"))
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        remember = request.form.get("remember") == "on"

        user = get_user_by_email(email)
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Email atau password tidak valid.", "danger")
            return render_template("login.html", email=email)

        _establish_session(user, remember=remember, email_override=email)
        flash("Selamat datang kembali!", "success")
        return redirect(_redirect_after_login(user, request.args.get("next")))

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout() -> Response:
    session.clear()
    flash("Anda telah logout.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/login/google/<provider>")
def google_login(provider: str) -> Response:
    normalized_provider = (provider or "belajar").strip().lower()
    if normalized_provider not in {"belajar", "gmail"}:
        normalized_provider = "belajar"

    oauth_client = oauth.create_client("google")
    if not oauth_client:
        flash("Login Google belum dikonfigurasi oleh admin.", "danger")
        return redirect(url_for("auth.login"))

    session.pop("post_login_redirect", None)
    next_url = request.args.get("next")
    if next_url:
        session["post_login_redirect"] = next_url
    session["dashboard_oauth_provider"] = normalized_provider
    nonce = secrets.token_urlsafe(24)
    session["dashboard_oauth_nonce"] = nonce
    redirect_uri = url_for("auth.google_callback", _external=True)
    return oauth_client.authorize_redirect(redirect_uri, prompt="select_account", nonce=nonce)


@auth_bp.route("/login/google/callback")
def google_callback() -> Response:
    oauth_client = oauth.create_client("google")
    if not oauth_client:
        flash("Login Google belum dikonfigurasi oleh admin.", "danger")
        return redirect(url_for("auth.login"))

    try:
        token = oauth_client.authorize_access_token()
        nonce = session.get("dashboard_oauth_nonce")
        userinfo = oauth_client.parse_id_token(token, nonce=nonce)
    except Exception:
        current_app.logger.exception("Google OAuth callback gagal diproses.")
        flash("Gagal memproses respons Google. Silakan coba lagi.", "danger")
        return redirect(url_for("auth.login"))
    finally:
        session.pop("dashboard_oauth_nonce", None)

    email = (userinfo or {}).get("email")
    if not email:
        flash("Google tidak mengirimkan email pengguna.", "danger")
        return redirect(url_for("auth.login"))

    email = email.strip().lower()
    provider = session.pop("dashboard_oauth_provider", "belajar")
    domain = email.split("@")[-1].lower()

    if provider == "belajar":
        valid_domain = domain == "belajar.id" or domain.endswith(".belajar.id")
        error_message = "Login belajar.id memerlukan email dengan domain @belajar.id."
    else:
        valid_domain = domain in GMAIL_ALLOWED_DOMAINS
        error_message = "Login Gmail hanya menerima alamat @gmail.com."

    if not valid_domain:
        flash(error_message, "danger")
        return redirect(url_for("auth.login"))

    user = get_user_by_email(email)
    if not user:
        flash("Email tersebut belum terdaftar pada dashboard. Hubungi admin untuk mendapatkan akses.", "danger")
        return redirect(url_for("auth.login"))

    _establish_session(user, remember=True, email_override=email)
    flash("Autentikasi Google berhasil.", "success")
    next_url = session.pop("post_login_redirect", None)
    return redirect(_redirect_after_login(user, next_url))


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


@auth_bp.route("/settings/aska-users")
@role_required("admin")
def manage_aska_users() -> Response:
    source = (request.args.get("source") or "web").strip().lower()
    if source not in {"web", "telegram", "all"}:
        source = "web"
    status_filter = (request.args.get("status") or "all").strip().lower()
    normalized_status = status_filter if status_filter in ACCOUNT_STATUS_CHOICES else None
    search = (request.args.get("q") or "").strip()

    users = fetch_aska_users(source, normalized_status, search or None)
    stats = summarize_aska_users()

    return render_template(
        "aska_users.html",
        users=users,
        filter_source=source,
        status_filter=status_filter,
        search_query=search,
        status_choices=ACCOUNT_STATUS_CHOICES,
        status_labels=ACCOUNT_STATUS_LABELS,
        status_badges=ACCOUNT_STATUS_BADGES,
        stats=stats,
    )


@auth_bp.route("/settings/aska-users/status", methods=["POST"])
@role_required("admin")
def update_aska_user_status() -> Response:
    payload = request.get_json(silent=True) or {}
    channel = (payload.get("channel") or "").strip().lower()
    status = (payload.get("status") or "").strip().lower()
    user_id = payload.get("userId")
    if user_id is None:
        return jsonify({"success": False, "message": "ID user wajib diisi."}), 400
    reason = payload.get("reason")
    normalized_status = status if status in ACCOUNT_STATUS_CHOICES else None
    if not normalized_status:
        return jsonify({"success": False, "message": "Status tidak dikenal."}), 400
    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "ID user tidak valid."}), 400

    admin = current_user() or {}
    actor = admin.get("email") or admin.get("full_name") or "dashboard"
    try:
        if channel == "web":
            updated = update_web_user_status(user_id_int, normalized_status, reason, changed_by=actor)
        elif channel == "telegram":
            updated = update_telegram_user_status(user_id_int, normalized_status, reason, changed_by=actor)
        else:
            return jsonify({"success": False, "message": "Channel tidak dikenal."}), 400
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400

    if not updated:
        return jsonify({"success": False, "message": "User tidak ditemukan."}), 404
    return jsonify({"success": True})
