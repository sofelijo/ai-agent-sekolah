from __future__ import annotations

import os
import asyncio
from datetime import datetime, timezone, timedelta
import random
from typing import Any
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
    get_web_user_status,
    DEFAULT_LIMITED_QUOTA,
    DEFAULT_LIMITED_REASON,
    list_tka_subjects,
    get_tka_subject,
    create_tka_attempt,
    get_tka_attempt,
    submit_tka_attempt,
    get_tka_result,
    get_tka_analysis_job,
    mark_tka_analysis_sent,
    get_tka_subject_availability,
)
from account_status import (
    BLOCKING_STATUSES,
    build_status_notice,
    ACCOUNT_STATUS_ACTIVE,
)
from responses import detect_bullying_category, is_corruption_report_intent
from utils import normalize_input, replace_bot_mentions

LIMIT_BLOCK_MESSAGE = (
    "Ups! Kuota 3 chat untuk akses Gmail sudah habis. "
    "Tunggu hitung mundur selesai atau login pakai akun belajar.id / Telegram biar bebas limit ya! 🚀"
)
GMAIL_ALLOWED_DOMAINS = {"gmail.com", "googlemail.com"}
WEB_BOT_USERNAME = "ASKA_WEB"
PRESET_LABELS = {
    "mudah": "Mudah",
    "sedang": "Sedang",
    "susah": "Susah",
    "custom": "Kustom",
}
GRADE_LABELS = {
    "sd6": "Kelas 6 SD",
    "smp3": "Kelas 3 SMP",
    "sma": "Kelas 3 SMA",
}
SIMULATION_LOGIN = {
    "username": os.getenv("TKA_SIMULATION_USERNAME", "P130100230"),
    "password": os.getenv("TKA_SIMULATION_PASSWORD", "ASKA2024"),
}
SIMULATION_STATE_KEY = "tka_simulasi_state"


def _format_preset_label(value: str | None) -> str:
    if not value:
        return "-"
    normalized = str(value).strip().lower()
    return PRESET_LABELS.get(normalized, value.title())


def _format_grade_label(value: str | None) -> str:
    if not value:
        return GRADE_LABELS["sd6"]
    normalized = str(value).strip().lower()
    return GRADE_LABELS.get(normalized, GRADE_LABELS["sd6"])


def _generate_simulation_token(length: int = 6) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(alphabet) for _ in range(length))


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

    def _sync_session_status(status_state: dict | None) -> None:
        if "user" not in session or not status_state:
            return
        user_data = dict(session["user"])
        status_value = status_state.get("status") or ACCOUNT_STATUS_ACTIVE
        user_data["status"] = status_value
        user_data["status_reason"] = status_state.get("status_reason")
        changed_at = status_state.get("status_changed_at")
        if hasattr(changed_at, "isoformat"):
            changed_at = changed_at.isoformat()
        user_data["status_changed_at"] = changed_at
        user_data["status_changed_by"] = status_state.get("status_changed_by")
        session["user"] = user_data
        session.modified = True

    def _prepare_status_notice(user_id: int):
        status_state = get_web_user_status(user_id)
        _sync_session_status(status_state)
        status_value = (status_state or {}).get("status")
        notice = None
        if status_value in BLOCKING_STATUSES:
            notice = build_status_notice(
                status_value,
                reason=(status_state or {}).get("status_reason"),
                channel="web",
            )
        return notice, status_state

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

    def _normalize_question_options(raw_options):
        fallback_keys = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        normalized = []
        if not raw_options:
            return normalized
        for idx, option in enumerate(raw_options):
            if isinstance(option, dict):
                raw_key = option.get("key") or option.get("label") or option.get("value")
                text = option.get("text") or option.get("label") or option.get("value") or ""
            else:
                raw_key = None
                text = str(option)
            base_key = raw_key or (fallback_keys[idx] if idx < len(fallback_keys) else f"OPT{idx+1}")
            key = str(base_key).strip().upper() or (fallback_keys[idx] if idx < len(fallback_keys) else f"OP{idx+1}")
            normalized.append({"key": key, "text": text})
        return normalized

    def _prepare_question_payloads(rows):
        prepared = []
        for row in rows or []:
            item = dict(row)
            item["options"] = _normalize_question_options(item.get("options"))
            raw_meta = item.pop("metadata", None)
            source_meta = item.pop("source_metadata", None)
            merged_meta = {}
            if isinstance(source_meta, dict):
                merged_meta.update(source_meta)
            if isinstance(raw_meta, dict):
                merged_meta.update(raw_meta)
            image_url = (
                merged_meta.get("stimulus_image_url")
                or merged_meta.get("image_url")
                or merged_meta.get("imageUrl")
                or merged_meta.get("image")
                or merged_meta.get("gambar")
            )
            item["image_url"] = image_url
            item["section_key"] = merged_meta.get("section_key")
            item["section_label"] = merged_meta.get("section_label")
            item["subject_area"] = merged_meta.get("subject_area")
            item["question_format"] = merged_meta.get("question_format")
            item["true_false_statements"] = merged_meta.get("true_false_statements") or merged_meta.get("statements")
            stimulus_payload = None
            if merged_meta.get("stimulus_id") or merged_meta.get("stimulus_title") or merged_meta.get("stimulus_text"):
                stimulus_payload = {
                    "id": merged_meta.get("stimulus_id"),
                    "title": merged_meta.get("stimulus_title"),
                    "type": merged_meta.get("stimulus_type"),
                    "text": merged_meta.get("stimulus_text"),
                    "image_url": image_url,
                    "image_prompt": merged_meta.get("stimulus_image_prompt"),
                }
            item["stimulus"] = stimulus_payload
            if stimulus_payload:
                stim_key = stimulus_payload.get("id") or stimulus_payload.get("title")
                item["stimulus_key"] = str(stim_key) if stim_key else f"stim-{item.get('id')}"
            else:
                item["stimulus_key"] = f"solo-{item.get('id')}"
            prepared.append(item)
        return prepared

    def _group_questions_by_stimulus(rows):
        packages = []
        groups: dict[str, dict] = {}
        counter = 1
        for row in rows or []:
            key = row.get("stimulus_key") or f"solo-{row.get('id')}"
            if key not in groups:
                groups[key] = {
                    "key": key,
                    "stimulus": row.get("stimulus"),
                    "questions": [],
                }
                packages.append(groups[key])
            entry = dict(row)
            entry["global_index"] = counter
            groups[key]["questions"].append(entry)
            counter += 1
        return packages

    def _clear_simulation_state():
        if SIMULATION_STATE_KEY in session:
            session.pop(SIMULATION_STATE_KEY, None)
            session.modified = True

    def _get_simulation_state():
        return session.get(SIMULATION_STATE_KEY) or None

    def _set_simulation_state(value: dict | None):
        if value is None:
            _clear_simulation_state()
            return
        session[SIMULATION_STATE_KEY] = value
        session.modified = True

    def _initiate_tka_attempt(subject_id: int, user: dict | None, requested_preset: str | None, allow_repeat: bool = False, flash_ready: bool = True):
        if not user:
            flash("Silakan login ulang sebelum mulai latihan.", "warning")
            return redirect(url_for("login_page")), False
        user_id = user.get("id")
        if not user_id:
            flash("Akun web kamu belum lengkap. Coba login ulang ya.", "error")
            return redirect(url_for("login_page")), False
        preset_value = (requested_preset or "").strip().lower() or None
        availability = get_tka_subject_availability(subject_id, user_id, preset_name=preset_value)
        if not availability:
            flash("Mapel latihan tidak ditemukan.", "error")
            return redirect(url_for("latihan_tka_home")), False
        subject = availability["subject"]
        selected_preset = availability.get("selectedPreset") or preset_value
        preset_label = _format_preset_label(selected_preset)
        if not availability.get("bank_ready"):
            label_text = preset_label if selected_preset else "yang dipilih"
            flash(f"Bank soal untuk preset {label_text} belum memenuhi komposisi minimal.", "warning")
            return redirect(url_for("latihan_tka_home")), False

        def render_repeat_prompt():
            return render_template(
                "latihan_tka_repeat.html",
                user=user,
                subject=subject,
                availability=availability,
                selected_preset=selected_preset,
                preset_label=preset_label,
                grade_label=_format_grade_label(subject.get("grade_level")),
            ), False

        if availability.get("needs_repeat") and not allow_repeat:
            return render_repeat_prompt()
        try:
            attempt_info = create_tka_attempt(
                subject_id,
                user_id,
                allow_repeat=allow_repeat,
                preset_name=selected_preset or preset_value,
            )
        except ValueError as exc:
            error_code = str(exc)
            if error_code == "repeat_required":
                return render_repeat_prompt()
            if error_code == "bank_insufficient":
                label_text = preset_label if selected_preset else "yang dipilih"
                flash(f"Bank soal preset {label_text} belum memenuhi komposisi minimal. Hubungi admin ya.", "warning")
                return redirect(url_for("latihan_tka_home")), False
            flash(str(exc), "error")
            return redirect(url_for("latihan_tka_home")), False
        except Exception as exc:
            app.logger.error("Gagal membuat sesi TKA baru: %s", exc)
            flash("Sesi latihan belum bisa dibuat. Coba lagi sebentar lagi ya!", "error")
            return redirect(url_for("latihan_tka_home")), False
        if flash_ready:
            flash("Sesi latihan sudah siap. Semangat mengerjakan! 💪", "info")
        return redirect(url_for("latihan_tka_session", attempt_id=attempt_info["attempt_id"])), True

    def _trigger_tka_analysis(attempt_id: int, user: dict | None) -> None:
        if not attempt_id or not user:
            return
        user_id = user.get("id")
        if not user_id:
            return
        job = get_tka_analysis_job(attempt_id)
        if not job or job.get("analysis_sent_at"):
            return
        prompt = job.get("analysis_prompt")
        if not prompt:
            return
        username = user.get("full_name") or "WebUser"
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                process_web_request(user_id, prompt, username=username)
            )
            mark_tka_analysis_sent(attempt_id)
        except Exception as exc:
            app.logger.error("Gagal menjalankan analisa Latihan TKA (%s): %s", attempt_id, exc)

    @app.route("/")
    def index():
        user = session.get('user')
        if not user:
            return redirect(url_for('login_page'))

        # Load initial chat history
        user_id = user.get('id')
        quota_status = get_chat_quota_status(user_id)
        _sync_session_quota(quota_status)
        status_notice, _ = _prepare_status_notice(user_id)
        initial_chats = get_chat_history(user_id, limit=10, offset=0)

        status_payload = status_notice.__dict__ if status_notice else None
        return render_template(
            "chat.html",
            user=session.get("user"),
            initial_chats=initial_chats,
            quota=_serialize_quota_payload(quota_status),
             status_notice=status_payload,
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
            status_changed_at = user_dict.get('status_changed_at')
            if hasattr(status_changed_at, 'isoformat'):
                user_dict['status_changed_at'] = status_changed_at.isoformat()

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

        status_notice, status_state = _prepare_status_notice(user_id)
        status_payload = status_notice.__dict__ if status_notice else None
        if status_notice:
            quota_state = get_chat_quota_status(user_id)
            _sync_session_quota(quota_state)
            server_now = datetime.now(timezone.utc).isoformat()
            return jsonify({
                "response": status_notice.message,
                "blocked": True,
                "blockType": "status",
                "statusBlock": status_payload,
                "exempt": False,
                "quota": _serialize_quota_payload(quota_state),
                "serverTime": server_now,
            })

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
                "blockType": "quota",
                "exempt": False,
                "quota": quota_payload,
                "statusBlock": None,
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
            "blockType": None,
            "statusBlock": status_payload,
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

    @app.route("/latihan-tka")
    def latihan_tka_home():
        user = session.get("user")
        if not user:
            flash("Silakan login terlebih dahulu untuk mengakses Latihan TKA.", "warning")
            return redirect(url_for("login_page"))
        try:
            subjects = list_tka_subjects(active_only=True)
        except Exception as exc:
            app.logger.error("Gagal memuat daftar mapel TKA: %s", exc)
            subjects = []
            flash("Daftar mapel belum bisa dimuat. Coba lagi beberapa saat lagi ya!", "error")
        return render_template(
            "latihan_tka_home.html",
            user=user,
            subjects=subjects,
            preset_labels=PRESET_LABELS,
            grade_labels=GRADE_LABELS,
        )

    @app.route("/latihan-tka/simulasi/setup", methods=["POST"])
    def latihan_tka_simulasi_setup():
        user = session.get("user")
        if not user:
            flash("Silakan login terlebih dahulu sebelum mencoba simulasi.", "warning")
            return redirect(url_for("login_page"))
        try:
            subject_id = int(request.form.get("subject_id"))
        except (TypeError, ValueError):
            subject_id = None
        if not subject_id:
            flash("Pilihan mapel simulasi tidak valid.", "error")
            return redirect(url_for("latihan_tka_home"))
        preset_value = (request.form.get("preset") or "").strip().lower() or None
        subject = get_tka_subject(subject_id)
        if not subject:
            flash("Mapel latihan tidak ditemukan.", "error")
            return redirect(url_for("latihan_tka_home"))
        sim_state = {
            "subject_id": subject_id,
            "preset": preset_value,
            "stage": "login",
            "token": _generate_simulation_token(),
            "subject_name": subject.get("name"),
        }
        _set_simulation_state(sim_state)
        return redirect(url_for("latihan_tka_simulasi_login"))

    @app.route("/latihan-tka/simulasi", methods=["GET", "POST"])
    @app.route("/latihan-tka/simulasi/login", methods=["GET", "POST"])
    def latihan_tka_simulasi_login():
        user = session.get("user")
        if not user:
            flash("Silakan login terlebih dahulu sebelum mencoba simulasi.", "warning")
            return redirect(url_for("login_page"))
        sim_state = _get_simulation_state()
        if not sim_state:
            flash("Pilih mapel lalu klik Coba Simulasi terlebih dahulu ya.", "warning")
            return redirect(url_for("latihan_tka_home"))
        stage = sim_state.get("stage") or "login"
        if stage == "confirm" and request.method == "GET":
            return redirect(url_for("latihan_tka_simulasi_confirm"))
        if stage == "review" and request.method == "GET":
            return redirect(url_for("latihan_tka_simulasi_review"))
        subject = get_tka_subject(sim_state.get("subject_id"))
        if not subject:
            flash("Mapel simulasi tidak tersedia.", "error")
            _clear_simulation_state()
            return redirect(url_for("latihan_tka_home"))
        if request.method == "POST" and stage == "login":
            sim_state["stage"] = "confirm"
            _set_simulation_state(sim_state)
            return redirect(url_for("latihan_tka_simulasi_confirm"))
        return render_template(
            "latihan_tka_simulasi_login.html",
            user=user,
            subject=subject,
            simulasi_credentials=SIMULATION_LOGIN,
        )

    @app.route("/latihan-tka/simulasi/konfirmasi", methods=["GET", "POST"])
    def latihan_tka_simulasi_confirm():
        user = session.get("user")
        if not user:
            flash("Silakan login terlebih dahulu sebelum melanjutkan simulasi.", "warning")
            return redirect(url_for("login_page"))
        sim_state = _get_simulation_state()
        if not sim_state:
            flash("Mulai simulasi dari halaman Latihan TKA ya.", "warning")
            return redirect(url_for("latihan_tka_home"))
        if sim_state.get("stage") == "login":
            return redirect(url_for("latihan_tka_simulasi_login"))
        if sim_state.get("stage") == "review" and request.method == "GET":
            return redirect(url_for("latihan_tka_simulasi_review"))
        subject = get_tka_subject(sim_state.get("subject_id"))
        if not subject:
            flash("Mapel simulasi tidak ditemukan.", "error")
            _clear_simulation_state()
            return redirect(url_for("latihan_tka_home"))
        if not sim_state.get("token"):
            sim_state["token"] = _generate_simulation_token()
            _set_simulation_state(sim_state)
        if request.method == "POST":
            sim_state["stage"] = "review"
            sim_state["participant_form"] = {
                "participant_name": (request.form.get("participant_name") or "").strip(),
                "dob_day": request.form.get("dob_day"),
                "dob_month": request.form.get("dob_month"),
                "dob_year": request.form.get("dob_year"),
                "token": (request.form.get("token") or "").strip().upper(),
                "gender": request.form.get("gender") or "L",
            }
            sim_state["review_at"] = datetime.now(timezone.utc).isoformat()
            _set_simulation_state(sim_state)
            return redirect(url_for("latihan_tka_simulasi_review"))
        return render_template(
            "latihan_tka_simulasi_confirm.html",
            user=user,
            subject=subject,
            grade_label=_format_grade_label(subject.get("grade_level")),
            simulasi_credentials=SIMULATION_LOGIN,
            simulation_state=sim_state,
        )

    @app.route("/latihan-tka/simulasi/tes", methods=["GET", "POST"])
    def latihan_tka_simulasi_review():
        user = session.get("user")
        if not user:
            flash("Silakan login terlebih dahulu sebelum melanjutkan simulasi.", "warning")
            return redirect(url_for("login_page"))
        sim_state = _get_simulation_state()
        if not sim_state:
            flash("Mulai simulasi dari halaman Latihan TKA ya.", "warning")
            return redirect(url_for("latihan_tka_home"))
        stage = sim_state.get("stage")
        if stage == "login":
            return redirect(url_for("latihan_tka_simulasi_login"))
        if stage == "confirm" and request.method == "GET":
            return redirect(url_for("latihan_tka_simulasi_confirm"))
        subject = get_tka_subject(sim_state.get("subject_id"))
        if not subject:
            flash("Mapel simulasi tidak ditemukan.", "error")
            _clear_simulation_state()
            return redirect(url_for("latihan_tka_home"))
        review_iso = sim_state.get("review_at")
        try:
            if review_iso:
                review_dt = datetime.fromisoformat(review_iso)
            else:
                review_dt = datetime.now(timezone.utc)
            if review_dt.tzinfo is None:
                review_dt = review_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            review_dt = datetime.now(timezone.utc)
        review_display_time = review_dt.astimezone(timezone(timedelta(hours=7))).strftime("%d/%m/%Y %H:%M")
        if request.method == "POST":
            response, success = _initiate_tka_attempt(
                subject["id"],
                user,
                sim_state.get("preset"),
                allow_repeat=False,
            )
            if success:
                _clear_simulation_state()
            return response
        return render_template(
            "latihan_tka_simulasi_review.html",
            user=user,
            subject=subject,
            review_display_time=review_display_time,
            duration_minutes=subject.get("time_limit_minutes") or 15,
            simulasi_credentials=SIMULATION_LOGIN,
        )

    @app.route("/latihan-tka/mulai/<int:subject_id>", methods=["POST"])
    def latihan_tka_mulai(subject_id: int):
        user = session.get("user")
        allow_repeat = request.form.get("allow_repeat") == "1"
        requested_preset = request.form.get("preset")
        response, _ = _initiate_tka_attempt(subject_id, user, requested_preset, allow_repeat=allow_repeat)
        return response

    @app.route("/latihan-tka/sesi/<int:attempt_id>", methods=["GET"])
    def latihan_tka_session(attempt_id: int):
        user = session.get("user")
        if not user:
            return redirect(url_for("login_page"))
        user_id = user.get("id")
        attempt_bundle = get_tka_attempt(attempt_id, user_id)
        if not attempt_bundle:
            flash("Sesi latihan tidak ditemukan.", "error")
            return redirect(url_for("latihan_tka_home"))
        attempt = attempt_bundle["attempt"]
        if attempt.get("status") != "in_progress":
            return redirect(url_for("latihan_tka_result", attempt_id=attempt_id))
        questions = _prepare_question_payloads(attempt_bundle["questions"])
        question_packages = _group_questions_by_stimulus(questions)
        started_at = attempt.get("started_at") or datetime.now(timezone.utc)
        time_limit = attempt.get("time_limit_minutes") or 15
        deadline = started_at + timedelta(minutes=time_limit)
        server_now = datetime.now(timezone.utc)
        repeat_label = None
        if attempt.get("is_repeat"):
            iteration = attempt.get("repeat_iteration") or 1
            repeat_label = f"Mengulang ({iteration} kali)"
        preset_label = _format_preset_label(attempt.get("difficulty_preset"))
        grade_label = _format_grade_label(attempt.get("subject_grade_level"))
        subject_detail = get_tka_subject(attempt.get("subject_id")) if attempt.get("subject_id") else None
        section_config = (subject_detail or {}).get("advanced_config") or {}
        return render_template(
            "latihan_tka_session.html",
            user=user,
            attempt=attempt,
            questions=questions,
            question_packages=question_packages,
            question_total=len(questions),
            deadline_iso=deadline.isoformat(),
            server_time=server_now.isoformat(),
            repeat_label=repeat_label,
            preset_label=preset_label,
            grade_label=grade_label,
            sections=section_config.get("sections") or [],
        )

    @app.route("/latihan-tka/sesi/<int:attempt_id>", methods=["POST"])
    def latihan_tka_submit(attempt_id: int):
        user = session.get("user")
        if not user:
            return redirect(url_for("login_page"))
        user_id = user.get("id")
        answers: dict[int, str] = {}
        for key, value in request.form.items():
            if not key.startswith("answer-"):
                continue
            raw_id = key.split("-", 1)[1]
            try:
                question_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            answers[question_id] = value
        try:
            result = submit_tka_attempt(attempt_id, user_id, answers)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("latihan_tka_session", attempt_id=attempt_id))
        except Exception as exc:
            app.logger.error("Gagal menyimpan jawaban TKA %s: %s", attempt_id, exc)
            flash("Jawabanmu belum tersimpan. Coba kirim lagi ya!", "error")
            return redirect(url_for("latihan_tka_session", attempt_id=attempt_id))
        if not result:
            flash("Sesi latihan tidak ditemukan.", "error")
            return redirect(url_for("latihan_tka_home"))
        attempt = result.get("attempt")
        if attempt:
            _trigger_tka_analysis(attempt.get("id"), user)
        return redirect(url_for("latihan_tka_result", attempt_id=attempt_id))

    @app.route("/latihan-tka/hasil/<int:attempt_id>")
    def latihan_tka_result(attempt_id: int):
        user = session.get("user")
        if not user:
            return redirect(url_for("login_page"))
        user_id = user.get("id")
        attempt_bundle = get_tka_result(attempt_id, user_id)
        if not attempt_bundle:
            flash("Hasil latihan tidak ditemukan.", "error")
            return redirect(url_for("latihan_tka_home"))
        attempt = attempt_bundle["attempt"]
        if attempt.get("status") != "completed":
            flash("Sesi ini belum selesai. Lanjutkan latihan dulu ya!", "warning")
            return redirect(url_for("latihan_tka_session", attempt_id=attempt_id))
        difficulty_breakdown = attempt.get("difficulty_breakdown") or {}
        labels = {"easy": "Mudah", "medium": "Sedang", "hard": "Susah"}
        summary = []
        for key in ("easy", "medium", "hard"):
            stats = difficulty_breakdown.get(key) or {}
            summary.append(
                {
                    "key": key,
                    "label": labels.get(key, key.title()),
                    "total": stats.get("total", 0),
                    "correct": stats.get("correct", 0),
                }
            )
        section_breakdown = (attempt.get("metadata") or {}).get("section_breakdown") or {}
        section_summary = []
        for section_key, stats in section_breakdown.items():
            section_summary.append(
                {
                    "key": section_key,
                    "label": stats.get("label") or section_key.title(),
                    "total": stats.get("total", 0),
                    "correct": stats.get("correct", 0),
                    "format": stats.get("question_format"),
                    "subject_area": stats.get("subject_area"),
                }
            )
        format_summary_map: dict[str, dict[str, Any]] = {}
        for section in section_summary:
            fmt_key = section.get("format") or "multiple_choice"
            entry = format_summary_map.setdefault(
                fmt_key,
                {
                    "format": fmt_key,
                    "label": "Benar/Salah" if fmt_key == "true_false" else "Pilihan Ganda",
                    "total": 0,
                    "correct": 0,
                },
            )
            entry["total"] += section.get("total", 0)
            entry["correct"] += section.get("correct", 0)
        format_summary = list(format_summary_map.values())
        stimulus_breakdown = (attempt.get("metadata") or {}).get("stimulus_breakdown") or {}
        stimulus_summary = []
        for stim_key, stats in stimulus_breakdown.items():
            stimulus_summary.append(
                {
                    "key": stim_key,
                    "label": stats.get("label") or f"Stimulus {stim_key}",
                    "total": stats.get("total", 0),
                    "correct": stats.get("correct", 0),
                    "type": stats.get("type"),
                }
            )
        questions = _prepare_question_payloads(attempt_bundle["questions"])
        if attempt.get("analysis_sent_at") is None:
            _trigger_tka_analysis(attempt_id, user)
        repeat_label = None
        if attempt.get("is_repeat"):
            iteration = attempt.get("repeat_iteration") or 1
            repeat_label = f"Mengulang ({iteration} kali)"
        preset_label = _format_preset_label(attempt.get("difficulty_preset"))
        grade_label = _format_grade_label(attempt.get("subject_grade_level"))
        return render_template(
            "latihan_tka_result.html",
            user=user,
            attempt=attempt,
            questions=questions,
            difficulty_summary=summary,
            section_summary=section_summary,
            format_summary=format_summary,
            stimulus_summary=stimulus_summary,
            analysis_pending=attempt.get("analysis_sent_at") is None,
            server_time=datetime.now(timezone.utc).isoformat(),
            repeat_label=repeat_label,
            preset_label=preset_label,
            grade_label=grade_label,
        )

    return app
