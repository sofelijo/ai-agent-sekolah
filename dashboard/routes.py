from __future__ import annotations

import base64
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Optional, Dict, List
from pathlib import Path

from flask import (
    Blueprint,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
    session,
    current_app,
)
from werkzeug.datastructures import MultiDict

from .auth import current_user, login_required, role_required
from utils import current_jakarta_time, to_jakarta
from .queries import (
    BULLYING_STATUSES,
    PSYCH_STATUSES,
    CORRUPTION_STATUSES,
    ChatFilters,
    fetch_all_chat_users,
    fetch_bullying_reports,
    fetch_bullying_summary,
    fetch_bullying_report_detail,
    fetch_bullying_report_basic,
    fetch_chat_logs,
    fetch_conversation_thread,
    fetch_daily_activity,
    fetch_overview_metrics,
    fetch_recent_questions,
    fetch_top_keywords,
    fetch_top_users,
    update_bullying_report_status,
    bulk_update_bullying_report_status,
    fetch_psych_reports,
    fetch_psych_summary,
    fetch_psych_group_reports,
    update_psych_report_status,
    bulk_update_psych_report_status,
    fetch_corruption_reports,
    fetch_corruption_summary,
    fetch_corruption_report_detail,
    bulk_update_corruption_report_status,
    update_corruption_report_status,
    fetch_twitter_overview,
    fetch_twitter_activity,
    fetch_twitter_top_users,
    chat_topic_available,
    fetch_twitter_worker_logs,
    update_no_tester_preference,
)

main_bp = Blueprint("main", __name__)
PAGE_SIZE = 50
REPORT_PAGE_SIZE = 25
TWITTER_PAGE_SIZE = 25
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _env_flag(name: str, default: str = "false") -> bool:
    value = os.getenv(name, default)
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_runtime_path(value: Optional[str], default: str) -> Path:
    path = Path(value or default)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return path


def _load_twitter_runtime() -> dict:
    """Kumpulkan info real-time worker Twitter dari env, state file, dan autopost list."""
    state_path = _resolve_runtime_path(os.getenv("TWITTER_STATE_PATH"), "twitter_state.json")
    autopost_path = _resolve_runtime_path(os.getenv("TWITTER_AUTOPOST_MESSAGES_PATH"), "twitter_posts.txt")
    raw_bot_user_id = os.getenv("TWITTER_USER_ID")
    bot_user_id: Optional[int]
    if raw_bot_user_id:
        try:
            bot_user_id = int(str(raw_bot_user_id).strip())
        except (TypeError, ValueError):
            bot_user_id = None
    else:
        bot_user_id = None
    raw_bot_username = (os.getenv("TWITTER_USERNAME") or "").strip()
    if raw_bot_username.startswith("@"):
        raw_bot_username = raw_bot_username[1:]
    bot_username = raw_bot_username or None

    runtime: dict = {
        "state_path": str(state_path),
        "autopost_path": str(autopost_path),
        "state_exists": state_path.exists(),
        "autopost_exists": autopost_path.exists(),
        "state_error": None,
        "autopost_error": None,
        "state": {},
        "last_seen_id": None,
        "autopost_state": {},
        "last_autopost": None,
        "autopost_entries": [],
        "autopost_total": 0,
        "autopost_rag_total": 0,
        "autopost_preview": [],
        "bot_user_id": bot_user_id,
        "bot_username": bot_username,
        "settings": {
            "mentions_enabled": _env_flag("TWITTER_MENTIONS_ENABLED", "true"),
            "autopost_enabled": _env_flag("TWITTER_AUTOPOST_ENABLED", "false"),
            "poll_interval": int(os.getenv("TWITTER_POLL_INTERVAL", "180") or 180),
            "mentions_cooldown": int(os.getenv("TWITTER_MENTIONS_COOLDOWN", "180") or 180),
            "mentions_max_results": int(os.getenv("TWITTER_MENTIONS_MAX_RESULTS", "5") or 5),
            "autopost_interval": int(os.getenv("TWITTER_AUTOPOST_INTERVAL", "3600") or 3600),
            "autopost_recent_limit": int(os.getenv("TWITTER_AUTOPOST_RECENT_LIMIT", "8") or 8),
            "max_tweet_len": int(os.getenv("TWITTER_MAX_TWEET_LEN", "280") or 280),
        },
    }

    if runtime["state_exists"]:
        try:
            with state_path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            if isinstance(payload, dict):
                runtime["state"] = payload
                runtime["last_seen_id"] = payload.get("last_seen_id")
                autopost_state = payload.get("autopost")
                if isinstance(autopost_state, dict):
                    runtime["autopost_state"] = autopost_state
                    last_ts = autopost_state.get("last_timestamp")
                    if isinstance(last_ts, (int, float)) and last_ts > 0:
                        runtime["last_autopost"] = datetime.fromtimestamp(last_ts, tz=timezone.utc)
            else:
                runtime["state_error"] = "Format state file tidak dikenal."
        except Exception as exc:
            runtime["state_error"] = str(exc)
    else:
        runtime["state_error"] = "File state belum dibuat oleh worker."

    entries: list[dict] = []
    if runtime["autopost_exists"]:
        try:
            text = autopost_path.read_text(encoding="utf-8")
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                is_rag = line.upper().startswith("RAG:")
                display = line[4:].strip() if is_rag else line
                entry = {
                    "raw": line,
                    "display": display,
                    "is_rag": is_rag,
                    "has_placeholders": "{{" in line and "}}" in line,
                }
                entries.append(entry)
        except Exception as exc:
            runtime["autopost_error"] = str(exc)
    else:
        runtime["autopost_error"] = "File daftar autopost belum tersedia."

    runtime["autopost_entries"] = entries
    runtime["autopost_total"] = len(entries)
    runtime["autopost_rag_total"] = sum(1 for item in entries if item.get("is_rag"))
    runtime["autopost_preview"] = entries[:8]
    if runtime.get("last_autopost"):
        runtime["last_autopost_local"] = to_jakarta(runtime["last_autopost"])
    else:
        runtime["last_autopost_local"] = None

    return runtime



@main_bp.before_request
def restrict_teacher_access():
    user = current_user()
    if user and user.get("role") == "staff":
        return redirect(url_for("attendance.dashboard"))


@main_bp.route("/profile/no-tester", methods=["POST"])
@login_required
def toggle_no_tester() -> Response:
    user = current_user()
    if not user:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    raw_enabled = payload.get("enabled")
    if isinstance(raw_enabled, str):
        enabled = raw_enabled.strip().lower() in {"1", "true", "yes", "on"}
    else:
        enabled = bool(raw_enabled)

    try:
        success = update_no_tester_preference(user["id"], enabled)
    except Exception as exc:  # pragma: no cover - surfaces to UI
        return jsonify({"success": False, "message": str(exc)}), 500

    if not success:
        return jsonify({"success": False, "message": "User preference not updated"}), 400

    session_user = session.get("user") or {}
    session_user["no_tester_enabled"] = enabled
    session["user"] = session_user

    return jsonify({"success": True, "enabled": enabled})


@main_bp.route("/")
@login_required
def dashboard() -> Response:
    metrics = fetch_overview_metrics(window_days=7)
    chart_default_days = 30
    activity_default = fetch_daily_activity(days=chart_default_days)
    activity_long = fetch_daily_activity(days=365)
    incoming_activity_long = fetch_daily_activity(days=365, role="user")
    recent_questions = fetch_recent_questions(limit=8)
    top_users = fetch_top_users(limit=5)
    top_keywords = fetch_top_keywords(limit=10, days=30)

    chart_days: list[str] = []
    chart_values: list[int] = []
    for row in activity_default:
        day = row.get("day")
        if hasattr(day, "isoformat"):
            day_str = day.isoformat()
        else:
            day_str = str(day)
        chart_days.append(day_str)
        chart_values.append(int(row.get("messages") or 0))
    keyword_labels = [item["keyword"] for item in top_keywords]
    keyword_counts = [item["count"] for item in top_keywords]

    today_date = current_jakarta_time().date()

    def sum_period(activity_data, days: int) -> int:
        if not activity_data:
            return 0
        cutoff = today_date - timedelta(days=days - 1) if days > 1 else today_date
        total = 0
        for row in activity_data:
            day_value = row.get("day")
            if isinstance(day_value, datetime):
                day_value = day_value.date()
            elif isinstance(day_value, str):
                try:
                    day_value = datetime.fromisoformat(day_value).date()
                except ValueError:
                    continue
            if day_value and day_value >= cutoff:
                total += int(row.get("messages") or 0)
        return total

    messages_counts = {
        "today": sum_period(activity_long, 1),
        "week": sum_period(activity_long, 7),
        "month": sum_period(activity_long, 30),
        "year": sum_period(activity_long, 365),
        "all": metrics["total_messages"],
    }

    requests_counts = {
        "today": sum_period(incoming_activity_long, 1),
        "week": sum_period(incoming_activity_long, 7),
        "month": sum_period(incoming_activity_long, 30),
        "year": sum_period(incoming_activity_long, 365),
        "all": metrics["total_incoming_messages"],
    }

    aska_links = {
        "tele": os.getenv("ASKA_TELEGRAM_URL", "https://t.me/tanyaaska_bot"),
        "web": os.getenv("ASKA_WEB_URL", "https://aska.sdnsembar01.sch.id/"),
        "twitter": os.getenv("ASKA_TWITTER_URL", "https://twitter.com/tanyaaska_ai"),
    }

    return render_template(
        "dashboard.html",
        generated_at=current_jakarta_time(),
        metrics=metrics,
        recent_questions=recent_questions,
        top_users=top_users,
        chart_days=chart_days,
        chart_values=chart_values,
        chart_default_days=chart_default_days,
        keyword_labels=keyword_labels,
        keyword_counts=keyword_counts,
        requests_counts=requests_counts,
        messages_counts=messages_counts,
        aska_links=aska_links,
    )


@main_bp.route("/twitter/logs")
@login_required
def twitter_logs() -> Response:
    args: MultiDict = request.args
    page = max(1, int(args.get("page", 1)))
    range_key = args.get("range")

    start = _parse_date(args.get("start"))
    end = _parse_date(args.get("end"))
    now = current_jakarta_time()

    if range_key:
        key = range_key.lower()
        if key == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
        elif key == "24h":
            start = now - timedelta(hours=24)
            end = now
        elif key == "7d":
            start = now - timedelta(days=7)
            end = now
        elif key == "30d":
            start = now - timedelta(days=30)
            end = now
        elif key == "90d":
            start = now - timedelta(days=90)
            end = now
        elif key == "all":
            start = None
            end = None

    role = args.get("role") or None
    if role not in {"user", "aska"}:
        role = None
    search = args.get("search") or None
    user_id = args.get("user_id")
    user_id = int(user_id) if user_id else None

    filters = ChatFilters(
        start=start,
        end=end,
        role=role,
        search=search,
        user_id=user_id,
        topic="twitter",
    )

    topic_supported = chat_topic_available()

    offset = (page - 1) * TWITTER_PAGE_SIZE
    if topic_supported:
        records, total = fetch_chat_logs(filters=filters, limit=TWITTER_PAGE_SIZE, offset=offset)
    else:
        records, total = [], 0
    total_pages = max(1, ceil(total / TWITTER_PAGE_SIZE)) if total else 1

    runtime = _load_twitter_runtime()
    bot_user_id = runtime.get("bot_user_id")
    overview = fetch_twitter_overview(window_days=7, bot_user_id=bot_user_id)
    activity_rows = fetch_twitter_activity(days=45)
    activity_days: list[str] = []
    activity_mentions: list[int] = []
    activity_replies: list[int] = []
    for row in activity_rows:
        day_value = row.get("day")
        if isinstance(day_value, datetime):
            label = day_value.date().isoformat()
        elif hasattr(day_value, "isoformat"):
            label = day_value.isoformat()
        else:
            label = str(day_value)
        activity_days.append(label)
        activity_mentions.append(int(row.get("mentions") or 0))
        activity_replies.append(int(row.get("replies") or 0))

    top_users = fetch_twitter_top_users(limit=8)
    worker_logs = fetch_twitter_worker_logs(limit=120)

    autopost_page_total = 0
    for row in records:
        is_autopost = bool(bot_user_id and row.get("role") == "aska" and row.get("user_id") == bot_user_id)
        row["is_autopost"] = is_autopost
        row["is_reply"] = row.get("role") == "aska" and not is_autopost
        row["is_mention"] = row.get("role") == "user"
        if is_autopost:
            autopost_page_total += 1

    export_url = None
    if topic_supported:
        export_params: dict = {"topic": "twitter"}
        if start:
            try:
                export_params["start"] = start.strftime("%Y-%m-%d")
            except Exception:
                export_params["start"] = str(start)
        if end:
            try:
                export_params["end"] = end.strftime("%Y-%m-%d")
            except Exception:
                export_params["end"] = str(end)
        if role:
            export_params["role"] = role
        if search:
            export_params["search"] = search
        if user_id:
            export_params["user_id"] = user_id
        export_url = url_for("main.export_chats", **export_params)

    if not range_key and not start and not end:
        range_key = "all"

    return render_template(
        "twitter_logs.html",
        overview=overview,
        records=records,
        total=total,
        page=page,
        total_pages=total_pages,
        filters=filters,
        selected_range=range_key,
        activity_days=activity_days,
        activity_mentions=activity_mentions,
        activity_replies=activity_replies,
        top_users=top_users,
        runtime=runtime,
        export_url=export_url,
        topic_supported=topic_supported,
        worker_logs=worker_logs,
        page_autopost_total=autopost_page_total,
    )


@main_bp.route("/chats")
@login_required
def chats() -> Response:
    args: MultiDict = request.args
    page = max(1, int(args.get("page", 1)))
    start = _parse_date(args.get("start"))
    end = _parse_date(args.get("end"))
    role = args.get("role") or None
    search = args.get("search") or None
    user_id = args.get("user_id")
    user_id = int(user_id) if user_id else None

    filters = ChatFilters(start=start, end=end, role=role, search=search, user_id=user_id)
    offset = (page - 1) * PAGE_SIZE

    records, total = fetch_chat_logs(filters=filters, limit=PAGE_SIZE, offset=offset)
    total_pages = max(1, ceil(total / PAGE_SIZE))

    export_params = {}
    if start:
        export_params["start"] = start.strftime("%Y-%m-%d")
    if end:
        export_params["end"] = end.strftime("%Y-%m-%d")
    if role:
        export_params["role"] = role
    if search:
        export_params["search"] = search
    if user_id:
        export_params["user_id"] = user_id

    export_url = url_for("main.export_chats", **export_params)

    return render_template(
        "chats.html",
        records=records,
        total=total,
        page=page,
        total_pages=total_pages,
        filters=filters,
        export_url=export_url,
    )


@main_bp.route("/chats/thread/")
@login_required
def chat_thread_empty() -> Response:
    users_list = fetch_all_chat_users()
    if users_list:
        return redirect(url_for("main.chat_thread", user_id=users_list[0]["user_id"]))
    flash("No chats found.", "info")
    return redirect(url_for("main.chats"))


@main_bp.route("/chats/thread/<user_id>")
@login_required
def chat_thread(user_id: str) -> Response:
    try:
        user_id_int = int(user_id)
    except ValueError:
        flash("User ID tidak valid.", "danger")
        return redirect(url_for("main.chats"))

    messages = fetch_conversation_thread(user_id=user_id_int, limit=400)
    users_list = fetch_all_chat_users()

    # If user has no messages, but other chats exist, redirect to the first user
    if not messages and users_list:
        flash("Pengguna ini belum memiliki riwayat percakapan.", "info")
        return redirect(url_for("main.chat_thread", user_id=users_list[0]["user_id"]))
    
    # If no messages and no other users, redirect to chat list
    if not messages:
        return redirect(url_for("main.chats"))

    user = {
        "user_id": user_id_int,
        "username": messages[0].get("username") or "Unknown",
    }
    return render_template(
        "chat_thread.html", messages=messages, user=user, users_list=users_list
    )



@main_bp.route("/bullying-reports")
@login_required
def bullying_reports() -> Response:
    args: MultiDict = request.args
    raw_status = (args.get("status") or "").strip().lower() or None
    if raw_status and raw_status not in BULLYING_STATUSES:
        flash("Status filter tidak dikenal.", "warning")
        return redirect(url_for("main.bullying_reports"))

    highlight_param = args.get("highlight")
    highlight_id = None
    if highlight_param:
        try:
            highlight_id = int(highlight_param)
        except ValueError:
            highlight_id = None

    page = max(1, int(args.get("page", 1)))
    limit = REPORT_PAGE_SIZE
    offset = (page - 1) * limit

    try:
        records, total = fetch_bullying_reports(status=raw_status, limit=limit, offset=offset)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("main.bullying_reports"))

    summary = fetch_bullying_summary()
    total_pages = max(1, ceil(total / limit))

    return render_template(
        "bullying_reports.html",
        records=records,
        summary=summary,
        filter_status=raw_status,
        page=page,
        total_pages=total_pages,
        total=total,
        per_page=limit,
        highlight_id=highlight_id,
    )


@main_bp.route("/bullying-reports/<int:report_id>")
@login_required
def bullying_report_detail(report_id: int) -> Response:
    report = fetch_bullying_report_detail(report_id)
    if not report:
        flash("Laporan tidak ditemukan.", "warning")
        return redirect(url_for("main.bullying_reports"))
    return render_template("bullying_report_detail.html", report=report)


@main_bp.route("/bullying-reports/bulk-status", methods=["POST"])
@role_required("admin", "staff")
def bulk_update_bullying_status() -> Response:
    data = request.get_json()
    report_ids = data.get("report_ids")
    status = data.get("status")
    user = current_user()
    updated_by = user.get("full_name") or user.get("email") if user else None

    if not report_ids or not isinstance(report_ids, list):
        return jsonify({"success": False, "message": "Invalid report IDs"}), 400

    if status not in BULLYING_STATUSES and status != "undo":
        return jsonify({"success": False, "message": "Invalid status"}), 400

    try:
        if status == "undo":
            bulk_update_bullying_report_status(report_ids, "pending", updated_by)
        else:
            bulk_update_bullying_report_status(report_ids, status, updated_by)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@main_bp.route("/bullying-reports/<int:report_id>/status", methods=["POST"])
@role_required("admin", "staff")
def update_bullying_status(report_id: int) -> Response:
    action = (request.form.get("action") or "save").strip().lower()
    status_value = request.form.get("status")
    notes = request.form.get("notes") or ""
    assigned_to = request.form.get("assigned_to")
    due_at_raw = request.form.get("due_at")
    escalate_values = request.form.getlist("escalate")
    next_url = request.form.get("next") or url_for("main.bullying_reports")

    user = current_user()
    updated_by = None
    if user:
        updated_by = user.get("full_name") or user.get("email")

    existing = fetch_bullying_report_basic(report_id)
    if not existing:
        flash("Laporan tidak ditemukan atau sudah dihapus.", "warning")
        return redirect(next_url)

    if action == "reopen":
        status_value = "pending"
    elif status_value:
        status_value = status_value.strip().lower()

    escalated_param = None
    if escalate_values:
        escalated_param = escalate_values[-1].lower() in {"on", "1", "true"}

    due_at_param = due_at_raw if due_at_raw is not None else None

    if status_value == "spam":
        escalated_param = False
        due_at_param = ""
        assigned_to = ""

    try:
        updated = update_bullying_report_status(
            report_id,
            status=status_value,
            notes=notes,
            updated_by=updated_by,
            assigned_to=assigned_to,
            due_at=due_at_param,
            escalated=escalated_param,
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(next_url)

    if updated:
        message = "Status laporan berhasil diperbarui."
        if action == "reopen":
            message = "Laporan dibuka kembali dan siap ditindaklanjuti."
        flash(message, "success")
    else:
        flash("Tidak ada perubahan yang disimpan.", "info")

    return redirect(next_url)


@main_bp.route("/corruption-reports")
@login_required
def corruption_reports() -> Response:
    args: MultiDict = request.args
    raw_status = (args.get("status") or "").strip().lower() or None
    if raw_status and raw_status not in CORRUPTION_STATUSES:
        flash("Status filter tidak dikenal.", "warning")
        return redirect(url_for("main.corruption_reports"))

    page = max(1, int(args.get("page", 1)))
    limit = REPORT_PAGE_SIZE
    offset = (page - 1) * limit

    try:
        records, total = fetch_corruption_reports(status=raw_status, limit=limit, offset=offset)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("main.corruption_reports"))

    summary = fetch_corruption_summary()
    total_pages = max(1, ceil(total / limit))

    return render_template(
        "corruption_reports.html",
        records=records,
        summary=summary,
        filter_status=raw_status,
        page=page,
        total_pages=total_pages,
        total=total,
        per_page=limit,
    )


@main_bp.route("/corruption-reports/<int:report_id>")
@login_required
def corruption_report_detail(report_id: int) -> Response:
    report = fetch_corruption_report_detail(report_id)
    if not report:
        flash("Laporan korupsi tidak ditemukan.", "warning")
        return redirect(url_for("main.corruption_reports"))
    return render_template("corruption_report_detail.html", report=report)


@main_bp.route("/corruption-reports/bulk-status", methods=["POST"])
@role_required("admin", "staff")
def bulk_update_corruption_status() -> Response:
    data = request.get_json()
    report_ids = data.get("report_ids")
    status = data.get("status")
    user = current_user()
    updated_by = user.get("full_name") or user.get("email") if user else None

    if not report_ids or not isinstance(report_ids, list):
        return jsonify({"success": False, "message": "Invalid report IDs"}), 400

    if status not in CORRUPTION_STATUSES and status != "undo":
        return jsonify({"success": False, "message": "Invalid status"}), 400

    try:
        if status == "undo":
            bulk_update_corruption_report_status(report_ids, "open", updated_by)
        else:
            bulk_update_corruption_report_status(report_ids, status, updated_by)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@main_bp.route("/corruption-reports/<int:report_id>/status", methods=["POST"])
@role_required("admin", "staff")
def update_corruption_status(report_id: int) -> Response:
    action = (request.form.get("action") or "save").strip().lower()
    status_value = request.form.get("status")
    next_url = request.form.get("next") or url_for("main.corruption_reports")

    user = current_user()
    updated_by = user.get("full_name") or user.get("email") if user else None

    if action == "reopen":
        status_value = "open"
    
    if not status_value:
        flash("Tidak ada status yang dipilih.", "warning")
        return redirect(next_url)

    try:
        updated = update_corruption_report_status(
            report_id,
            status=status_value,
            updated_by=updated_by,
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(next_url)

    if updated:
        flash("Status laporan korupsi berhasil diperbarui.", "success")
    else:
        flash("Gagal memperbarui status laporan korupsi.", "danger")

    return redirect(next_url)


@main_bp.route("/psych-reports")
@login_required
def psych_reports() -> Response:
    args: MultiDict = request.args
    raw_status = (args.get("status") or "").strip().lower() or None
    raw_severity = (args.get("severity") or "").strip().lower() or None

    if raw_status and raw_status not in PSYCH_STATUSES:
        flash("Status filter tidak dikenal.", "warning")
        return redirect(url_for("main.psych_reports"))

    if raw_severity and raw_severity not in ('general', 'elevated', 'critical'):
        flash("Severity filter tidak dikenal.", "warning")
        return redirect(url_for("main.psych_reports"))

    page = max(1, int(args.get("page", 1)))
    limit = REPORT_PAGE_SIZE
    offset = (page - 1) * limit

    try:
        records, total = fetch_psych_reports(
            status=raw_status,
            severity=raw_severity,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("main.psych_reports"))

    summary = fetch_psych_summary()
    total_pages = max(1, ceil(total / limit))
    severity_counts = summary.get("severity", {})

    return render_template(
        "psych_reports.html",
        records=records,
        summary=summary,
        severity_counts=severity_counts,
        filter_status=raw_status,
        filter_severity=raw_severity,
        page=page,
        total_pages=total_pages,
        total=total,
        per_page=limit,
    )


@main_bp.route("/psych-reports/user/<int:user_id>")
@login_required
def psych_report_user_detail(user_id: int) -> Response:
    records = fetch_psych_group_reports(user_id=user_id)
    if not records:
        flash("Tidak ada laporan konseling yang ditemukan untuk siswa ini.", "warning")
        return redirect(url_for("main.psych_reports"))

    return render_template(
        "psych_report_detail.html",
        records=records,
        user={
            "user_id": user_id,
            "username": records[0].get("username") or "Anon",
        },
    )


@main_bp.route("/psych-reports/report/<int:report_id>")
@login_required
def psych_report_single_detail(report_id: int) -> Response:
    records = fetch_psych_group_reports(report_id=report_id)
    if not records:
        flash("Laporan konseling tidak ditemukan atau sudah dihapus.", "warning")
        return redirect(url_for("main.psych_reports"))

    user_id = records[0].get("user_id")
    if user_id:
        return redirect(url_for("main.psych_report_user_detail", user_id=user_id))

    return render_template(
        "psych_report_detail.html",
        records=records,
        user={
            "user_id": None,
            "username": records[0].get("username") or "Anon",
        },
    )


@main_bp.route("/psych-reports/bulk-status", methods=["POST"])
@role_required("admin", "editor")
def bulk_update_psych_status() -> Response:
    data = request.get_json()
    report_ids = data.get("report_ids")
    status = data.get("status")
    user = current_user()
    updated_by = user.get("full_name") or user.get("email") if user else None

    if not report_ids or not isinstance(report_ids, list):
        return jsonify({"success": False, "message": "Invalid report IDs"}), 400

    if status not in PSYCH_STATUSES and status != "undo":
        return jsonify({"success": False, "message": "Invalid status"}), 400

    try:
        if status == "undo":
            bulk_update_psych_report_status(report_ids, "open", updated_by)
        else:
            bulk_update_psych_report_status(report_ids, status, updated_by)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@main_bp.route("/psych-reports/<int:report_id>/status", methods=["POST"])
@role_required("admin", "editor")
def update_psych_status(report_id: int) -> Response:
    status_value = (request.form.get("status") or "").strip().lower()
    next_url = request.form.get("next") or url_for("main.psych_reports")

    if status_value not in PSYCH_STATUSES:
        flash("Status laporan konseling tidak dikenal.", "warning")
        return redirect(next_url)

    user = current_user()
    updated_by = None
    if user:
        updated_by = user.get("full_name") or user.get("email")

    try:
        updated = update_psych_report_status(
            report_id,
            status_value,
            updated_by=updated_by,
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(next_url)

    if updated:
        flash("Status laporan konseling berhasil diubah.", "success")
    else:
        flash("Laporan konseling tidak ditemukan atau tidak ada perubahan.", "info")

    return redirect(next_url)


@main_bp.route("/api/activity")
@login_required
def activity_api() -> Response:
    days = int(request.args.get("days", 14))
    activity = fetch_daily_activity(days=days)
    payload = [
        {
            "day": (row["day"].isoformat() if hasattr(row.get("day"), "isoformat") else str(row.get("day"))),
            "messages": int(row.get("messages") or 0),
        }
        for row in activity
    ]
    return jsonify(payload)


@main_bp.route("/chats/export")
@login_required
def export_chats() -> Response:
    args: MultiDict = request.args
    start = _parse_date(args.get("start"))
    end = _parse_date(args.get("end"))
    role = args.get("role") or None
    search = args.get("search") or None
    user_id = args.get("user_id")
    user_id = int(user_id) if user_id else None
    topic = args.get("topic") or None

    filters = ChatFilters(start=start, end=end, role=role, search=search, user_id=user_id, topic=topic)

    records, _ = fetch_chat_logs(filters=filters, limit=5000, offset=0)

    from io import StringIO
    import csv

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "created_at", "user_id", "username", "role", "topic", "response_time_ms", "text"])
    for row in records:
        created_at = row.get("created_at")
        if created_at:
            created_at = to_jakarta(created_at)
            try:
                created_at = created_at.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                created_at = str(created_at)
        writer.writerow(
            [
                row.get("id"),
                created_at,
                row.get("user_id"),
                row.get("username"),
                row.get("role"),
                row.get("topic"),
                row.get("response_time_ms"),
                (row.get("text") or "").replace("\n", " "),
            ]
        )

    buffer.seek(0)
    filename = f"chat_logs_export_{current_jakarta_time():%Y%m%d_%H%M%S}.csv"
    response = Response(buffer.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


