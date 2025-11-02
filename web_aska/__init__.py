from __future__ import annotations

import os
import asyncio
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, flash
from authlib.integrations.flask_client import OAuth

# Import from within the project
from .handlers import process_web_request, web_sessions
from db import (
    get_or_create_web_user,
    get_chat_history,
    get_corruption_report,
    get_chat_quota_status,
    consume_chat_quota,
    DEFAULT_LIMITED_QUOTA,
    DEFAULT_LIMITED_REASON,
)
from responses import detect_bullying_category, is_corruption_report_intent
from utils import normalize_input, replace_bot_mentions

LIMIT_BLOCK_MESSAGE = (
    "Ups! Kuota 3 chat untuk akses Gmail sudah habis. "
    "Tunggu hitung mundur selesai atau login pakai akun belajar.id / Telegram biar bebas limit ya! 🚀"
)
GMAIL_ALLOWED_DOMAINS = {"gmail.com", "googlemail.com"}
WEB_BOT_USERNAME = "ASKA_WEB"

def create_app() -> Flask:
    """Create and configure an instance of the Flask application."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static"
    )

    # Secret key for session management
    app.config["SECRET_KEY"] = os.getenv("APP_SECRET_KEY", "a-very-secret-key-that-you-should-change")
    
    # Initialize OAuth
    oauth = OAuth(app)

    # Configure Google OAuth client
    oauth.register(
        name='google',
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile'
        }
    )

    def _serialize_quota_payload(quota_state: dict | None) -> dict:
        quota_state = quota_state or {}
        reset_at = quota_state.get("quota_reset_at")
        if hasattr(reset_at, "isoformat"):
            reset_at = reset_at.isoformat()
        access_tier = quota_state.get("access_tier") or "full"
        limited_reason = quota_state.get("limited_reason")
        if access_tier == "limited" and not limited_reason:
            limited_reason = DEFAULT_LIMITED_REASON
        return {
            "accessTier": access_tier,
            "quotaLimit": quota_state.get("quota_limit"),
            "quotaRemaining": quota_state.get("quota_remaining"),
            "quotaResetAt": reset_at,
            "limitedReason": limited_reason,
        }

    def _sync_session_quota(quota_state: dict | None) -> None:
        if "user" not in session or not quota_state:
            return
        user_data = dict(session["user"])
        access_tier = quota_state.get("access_tier") or "full"
        user_data["access_tier"] = access_tier
        user_data["quota_limit"] = quota_state.get("quota_limit")
        user_data["quota_remaining"] = quota_state.get("quota_remaining")
        reset_at = quota_state.get("quota_reset_at")
        if hasattr(reset_at, "isoformat"):
            reset_at = reset_at.isoformat()
        user_data["quota_reset_at"] = reset_at
        user_data["limited_reason"] = quota_state.get("limited_reason")
        session["user"] = user_data
        session.modified = True

    def _is_quota_exempt_message(user_id: int, message: str) -> bool:
        if not message:
            return False

        session_data = web_sessions.get(user_id) or {}

        bullying_sessions = session_data.get("bullying_sessions") or {}
        if bullying_sessions.get(user_id):
            return True

        corruption_sessions = session_data.get("corruption_sessions") or {}
        if corruption_sessions.get(user_id):
            return True

        cleaned = normalize_input(replace_bot_mentions(message, WEB_BOT_USERNAME))
        if detect_bullying_category(cleaned):
            return True

        if is_corruption_report_intent(cleaned):
            return True

        return False

    @app.route("/")
    def index():
        user = session.get('user')
        if not user:
            return redirect(url_for('login_page'))

        # Load initial chat history
        user_id = user.get('id')
        quota_status = get_chat_quota_status(user_id)
        _sync_session_quota(quota_status)
        initial_chats = get_chat_history(user_id, limit=10, offset=0)

        return render_template(
            "chat.html",
            user=session.get("user"),
            initial_chats=initial_chats,
            quota=_serialize_quota_payload(quota_status),
            server_time=datetime.now(timezone.utc).isoformat(),
        )

    @app.route("/auth/login")
    def login_page():
        return render_template("login.html")

    @app.route('/login')
    def login_belajar():
        session['login_mode'] = 'belajar'
        redirect_uri = url_for('authorize', _external=True)
        return oauth.google.authorize_redirect(redirect_uri)

    @app.route('/login/gmail')
    def login_gmail():
        session['login_mode'] = 'gmail'
        redirect_uri = url_for('authorize', _external=True)
        return oauth.google.authorize_redirect(redirect_uri)

    @app.route('/authorize')
    def authorize():
        token = oauth.google.authorize_access_token()
        userinfo = oauth.google.parse_id_token(token, nonce=session.get('nonce'))

        # Validate email domain
        email = userinfo.get('email')
        if not email:
            flash("Gagal mendapatkan informasi email dari Google.", "error")
            return redirect(url_for('login_page'))

        login_mode = session.pop('login_mode', 'belajar')
        domain = email.split('@')[-1].lower()
        is_belajar_domain = domain == 'belajar.id' or domain.endswith('.belajar.id')
        is_gmail_domain = domain in GMAIL_ALLOWED_DOMAINS

        if login_mode != 'belajar' and is_belajar_domain:
            # User clicked Gmail but actually has belajar.id, promote to full access.
            login_mode = 'belajar'

        if login_mode == 'belajar':
            if not is_belajar_domain:
                flash(
                    "Login harus menggunakan email dengan domain @belajar.id atau subdomainnya.",
                    "error",
                )
                return redirect(url_for('login_page'))
            access_tier = 'full'
            quota_limit = None
            auth_provider = 'google_oauth_belajar'
            limited_reason = None
        else:
            if not is_gmail_domain:
                flash(
                    "Login Gmail hanya menerima alamat @gmail.com. "
                    "Kalau kamu punya akun belajar.id silakan pilih opsi itu biar tanpa limit ya!",
                    "error",
                )
                return redirect(url_for('login_page'))
            access_tier = 'limited'
            quota_limit = DEFAULT_LIMITED_QUOTA
            auth_provider = 'google_oauth_gmail'
            limited_reason = DEFAULT_LIMITED_REASON

        # Get or create user in the database, update photo URL and last login timestamp
        user = get_or_create_web_user(
            email=email,
            full_name=userinfo.get('name'),
            photo_url=userinfo.get('picture'),
            access_tier=access_tier,
            auth_provider=auth_provider,
            quota_limit=quota_limit,
            limited_reason=limited_reason,
        )

        user_dict = dict(user) if user else {}
        if user:
            # Ensure datetime is serializable in the session
            last_login = user_dict.get('last_login')
            if hasattr(last_login, 'isoformat'):
                user_dict['last_login'] = last_login.isoformat()
            reset_at = user_dict.get('quota_reset_at')
            if hasattr(reset_at, 'isoformat'):
                user_dict['quota_reset_at'] = reset_at.isoformat()
            # Maintain compatibility with templates expecting `user.picture`
            user_dict['picture'] = user_dict.get('photo_url') or userinfo.get('picture')

        # Save user in session
        session['user'] = user_dict
        quota_status = None
        if user_dict.get('id'):
            quota_status = get_chat_quota_status(user_dict['id'])
            _sync_session_quota(quota_status)

        return redirect(url_for('index'))

    @app.route('/logout')
    def logout():
        session.pop('user', None)
        flash("You have been logged out.", "info")
        return redirect(url_for('login_page'))

    @app.route("/api/chat", methods=["POST"])
    def chat():
        if 'user' not in session:
            return jsonify({"error": "Unauthorized"}), 401

        data = request.json
        user_id = session['user'].get("id")
        full_name = session['user'].get("full_name", "WebUser")
        message = data.get("message")

        if not message:
            return jsonify({"error": "Message is required"}), 400

        is_exempt = _is_quota_exempt_message(user_id, message)
        if is_exempt:
            quota_state = get_chat_quota_status(user_id)
        else:
            quota_state = consume_chat_quota(user_id)

        _sync_session_quota(quota_state)

        if quota_state.get("error") == "user_not_found":
            session.pop('user', None)
            return jsonify({"error": "Unauthorized"}), 401

        quota_payload = _serialize_quota_payload(quota_state)
        if not is_exempt and not quota_state.get("allowed", False):
            server_now = datetime.now(timezone.utc).isoformat()
            return jsonify({
                "response": LIMIT_BLOCK_MESSAGE,
                "blocked": True,
                "exempt": False,
                "quota": quota_payload,
                "serverTime": server_now,
            })

        # Run the async function in a managed event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # 'get_running_loop' fails if no loop is running
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        response = loop.run_until_complete(process_web_request(user_id, message, username=full_name))
        server_now = datetime.now(timezone.utc).isoformat()
        return jsonify({
            "response": response,
            "blocked": False,
            "exempt": is_exempt,
            "quota": quota_payload,
            "serverTime": server_now,
        })

    @app.route("/api/history")
    def chat_history():
        if 'user' not in session:
            return jsonify({"error": "Unauthorized"}), 401
        
        user_id = session['user'].get('id')
        offset = request.args.get('offset', 0, type=int)
        
        history = get_chat_history(user_id, limit=10, offset=offset)
        
        # Convert datetime objects to string representation
        for item in history:
            if 'created_at' in item and hasattr(item['created_at'], 'isoformat'):
                item['created_at'] = item['created_at'].isoformat()

        return jsonify(history)

    @app.route("/api/quota")
    def quota_status_api():
        if 'user' not in session:
            return jsonify({"error": "Unauthorized"}), 401

        user_id = session['user'].get('id')
        quota_status = get_chat_quota_status(user_id)
        _sync_session_quota(quota_status)
        return jsonify({
            "quota": _serialize_quota_payload(quota_status),
            "serverTime": datetime.now(timezone.utc).isoformat(),
        })

    @app.route("/cek-laporan", methods=["GET"])
    def cek_laporan():
        ticket = request.args.get("ticket", "").strip()
        report = None
        error = None

        if ticket:
            report = get_corruption_report(ticket)
            if not report:
                error = "Nomor tiketnya belum ketemu nih. Coba pastiin lagi atau cek huruf kapitalnya ya!"

        return render_template("cek_laporan.html", ticket=ticket, report=report, error=error)

    @app.route("/cek-laporan/<ticket_id>")
    def cek_laporan_detail(ticket_id: str):
        return redirect(url_for("cek_laporan", ticket=ticket_id, _anchor="hasil"))

    return app
