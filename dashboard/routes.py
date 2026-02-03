from __future__ import annotations

import base64
import io
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
from PIL import Image

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
    fetch_feedback_summary,
    fetch_feedback_list,
    fetch_feedback_trend,
    fetch_landingpage_content,
    upsert_landingpage_content,
    fetch_landingpage_teachers,
    create_landingpage_teacher,
    update_landingpage_teacher,
    delete_landingpage_teacher,
    seed_landingpage_teachers_if_empty,
    update_landingpage_teacher_photo,
    update_landingpage_teacher_order,
    log_landingpage_activity,
    fetch_landingpage_audit_logs,
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


LANDINGPAGE_ICON_CHOICES = [
    "telegram",
    "whatsapp",
    "tiktok",
    "instagram",
    "youtube",
    "map",
    "link",
]


def _parse_collection(form: MultiDict, prefix: str, fields: List[str]) -> List[Dict[str, str]]:
    items: Dict[int, Dict[str, str]] = {}
    for key in form.keys():
        if not key.startswith(f"{prefix}-"):
            continue
        rest = key[len(prefix) + 1 :]
        if "-" not in rest:
            continue
        raw_index, field = rest.split("-", 1)
        if not raw_index.isdigit() or field not in fields:
            continue
        idx = int(raw_index)
        items.setdefault(idx, {})[field] = (form.get(key) or "").strip()
    results: List[Dict[str, str]] = []
    for idx in sorted(items.keys()):
        payload = {field: (items[idx].get(field) or "").strip() for field in fields}
        if any(value for value in payload.values()):
            results.append(payload)
    return results


def _decode_photo_payload(photo_data: str | None, photo_file) -> Optional[bytes]:
    if photo_data:
        raw = photo_data.strip()
        if "," in raw:
            raw = raw.split(",", 1)[1]
        try:
            return base64.b64decode(raw)
        except Exception:
            return None
    if photo_file:
        try:
            return photo_file.read()
        except Exception:
            return None
    return None


def _save_teacher_photo(site_key: str, teacher_id: int, photo_data: str | None, photo_file) -> Optional[str]:
    payload = _decode_photo_payload(photo_data, photo_file)
    if not payload:
        return None
    try:
        image = Image.open(io.BytesIO(payload))
    except Exception:
        return None
    image = image.convert("RGB")
    width, height = image.size
    side = min(width, height)
    left = max(0, (width - side) // 2)
    top = max(0, (height - side) // 2)
    image = image.crop((left, top, left + side, top + side))
    target_size = 512
    if image.size != (target_size, target_size):
        image = image.resize((target_size, target_size), Image.LANCZOS)

    safe_site = re.sub(r"[^a-z0-9_-]", "-", site_key.lower()) or "default"
    filename = f"teacher_{teacher_id}_{secrets.token_hex(6)}.jpg"
    relative = f"landingpage/uploads/teachers/{safe_site}/{filename}"
    output_path = PROJECT_ROOT / "landingpage" / "static" / relative
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        image.save(output_path, format="JPEG", quality=85, optimize=True)
    except Exception:
        return None
    return relative



@main_bp.before_request
def restrict_teacher_access():
    user = current_user()
    if user and user.get("role") == "staff":
        return redirect(url_for("attendance.dashboard"))
    if user and user.get("role") == "ekskul":
        return redirect(url_for("attendance.ekskul_dashboard"))


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


def _render_aska_dashboard() -> Response:
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


@main_bp.route("/")
@login_required
def dashboard() -> Response:
    return render_template("app_hub.html")


@main_bp.route("/apps")
@login_required
def app_hub() -> Response:
    return render_template("app_hub.html")


@main_bp.route("/aska")
@login_required
@role_required("admin")
def aska_dashboard() -> Response:
    return _render_aska_dashboard()


@main_bp.route("/settings/landingpage", methods=["GET", "POST"])
@role_required("admin")
def landingpage_settings() -> Response:
    user = current_user()
    site_key = (request.args.get("site_key") or os.getenv("LANDINGPAGE_SITE_KEY") or "default").strip().lower()
    content = fetch_landingpage_content(site_key=site_key)
    try:
        seed_landingpage_teachers_if_empty(site_key=site_key)
        teachers = fetch_landingpage_teachers(site_key=site_key, active_only=False)
    except Exception:
        teachers = []
        flash("Data guru belum siap. Jalankan init_db.py untuk membuat tabel.", "warning")

    if request.method == "POST":
        form = request.form
        site_name = (form.get("site_name") or "").strip()
        city = (form.get("city") or "").strip()
        hero_title = (form.get("hero_title") or "").strip()
        hero_subtitle = (form.get("hero_subtitle") or "").strip()
        hero_description = (form.get("hero_description") or "").strip()
        hero_background = (form.get("hero_background") or "").strip()
        hero_cta_label = (form.get("hero_cta_label") or "").strip()
        hero_cta_url = (form.get("hero_cta_url") or "").strip()
        documentation_title = (form.get("documentation_title") or "").strip()
        profile_title = (form.get("profile_title") or "").strip()
        vision_title = (form.get("vision_title") or "").strip()
        vision_text = (form.get("vision_text") or "").strip()
        activities_title = (form.get("activities_title") or "").strip()
        extracurricular_title = (form.get("extracurricular_title") or "").strip()
        footer_text = (form.get("footer_text") or "").strip()
        seo_meta_title = (form.get("seo_meta_title") or "").strip()
        seo_meta_description = (form.get("seo_meta_description") or "").strip()
        seo_meta_keywords = (form.get("seo_meta_keywords") or "").strip()
        seo_og_title = (form.get("seo_og_title") or "").strip()
        seo_og_description = (form.get("seo_og_description") or "").strip()
        seo_og_image = (form.get("seo_og_image") or "").strip()
        seo_twitter_card = (form.get("seo_twitter_card") or "").strip()
        seo_favicon = (form.get("seo_favicon") or "").strip()

        social_links = _parse_collection(form, "social_links", ["label", "url", "icon"])
        for link in social_links:
            icon = (link.get("icon") or "link").strip().lower()
            link["icon"] = icon if icon in LANDINGPAGE_ICON_CHOICES else "link"

        leaders = _parse_collection(form, "leaders", ["role", "name", "education", "image"])
        documentation_videos = _parse_collection(form, "documentation", ["title", "embed_url"])
        activities_items = _parse_collection(form, "activities", ["title", "description", "image"])
        extracurricular_items = _parse_collection(form, "extracurricular", ["title", "description", "image"])
        mission_items = _parse_collection(form, "missions", ["text"])
        missions = [item.get("text", "").strip() for item in mission_items if item.get("text")]

        payload = {
            "site_name": site_name,
            "city": city,
            "hero": {
                "title": hero_title,
                "subtitle": hero_subtitle,
                "description": hero_description,
                "background_image": hero_background,
                "primary_cta": {"label": hero_cta_label, "url": hero_cta_url},
                "social_links": social_links,
            },
            "documentation": {
                "title": documentation_title,
                "videos": documentation_videos,
            },
            "profile": {
                "title": profile_title,
                "leaders": leaders,
                "vision_title": vision_title,
                "vision": vision_text,
                "missions": missions,
            },
            "activities": {
                "title": activities_title,
                "items": activities_items,
            },
            "extracurricular": {
                "title": extracurricular_title,
                "items": extracurricular_items,
            },
            "footer": {
                "text": footer_text,
            },
            "seo": {
                "meta_title": seo_meta_title,
                "meta_description": seo_meta_description,
                "meta_keywords": seo_meta_keywords,
                "og_title": seo_og_title,
                "og_description": seo_og_description,
                "og_image": seo_og_image,
                "twitter_card": seo_twitter_card,
                "favicon": seo_favicon,
            },
        }

        updated = upsert_landingpage_content(site_key, payload, updated_by=(user or {}).get("id"))
        if updated:
            log_landingpage_activity(
                site_key,
                (user or {}).get("id"),
                action="content_update",
                entity_type="landingpage",
                metadata={"sections": ["hero", "profile", "activities", "extracurricular", "documentation", "seo"]},
            )
            flash("Konten landing page berhasil disimpan.", "success")
        else:
            flash("Gagal menyimpan konten landing page.", "danger")
        return redirect(url_for("main.landingpage_settings", site_key=site_key))

    logs = fetch_landingpage_audit_logs(site_key=site_key, limit=30)

    return render_template(
        "landingpage_settings.html",
        content=content,
        site_key=site_key,
        icon_choices=LANDINGPAGE_ICON_CHOICES,
        teachers=teachers,
        logs=logs,
    )


@main_bp.route("/settings/landingpage/teachers", methods=["POST"])
@role_required("admin")
def landingpage_teacher_create() -> Response:
    site_key = (request.form.get("site_key") or "default").strip().lower()
    photo_data = request.form.get("photo_data")
    photo_file = request.files.get("photo_file")
    payload = {
        "nama": request.form.get("nama") or "",
        "gelar": request.form.get("gelar") or "",
        "jabatan": request.form.get("jabatan") or "",
        "jenis_kelamin": request.form.get("jenis_kelamin") or "",
        "tempat_lahir": request.form.get("tempat_lahir") or "",
        "tanggal_lahir": request.form.get("tanggal_lahir") or None,
        "email": request.form.get("email") or "",
        "nip": request.form.get("nip") or "",
        "nuptk": request.form.get("nuptk") or "",
        "foto": request.form.get("foto") or "",
        "is_active": request.form.get("is_active") == "on",
    }
    if not payload["nama"].strip():
        flash("Nama guru/pegawai wajib diisi.", "warning")
        return redirect(url_for("main.landingpage_settings", site_key=site_key))

    created_id = create_landingpage_teacher(site_key, payload)
    if created_id:
        photo_url = _save_teacher_photo(site_key, created_id, photo_data, photo_file)
        if photo_url:
            update_landingpage_teacher_photo(created_id, site_key, photo_url)
            payload["foto"] = photo_url
        log_landingpage_activity(
            site_key,
            (current_user() or {}).get("id"),
            action="teacher_create",
            entity_type="teacher",
            entity_id=created_id,
            metadata={"nama": payload.get("nama")},
        )
        flash("Data guru berhasil ditambahkan.", "success")
    else:
        flash("Gagal menambahkan data guru.", "danger")
    return redirect(url_for("main.landingpage_settings", site_key=site_key))


@main_bp.route("/settings/landingpage/teachers/<int:teacher_id>/update", methods=["POST"])
@role_required("admin")
def landingpage_teacher_update(teacher_id: int) -> Response:
    site_key = (request.form.get("site_key") or "default").strip().lower()
    photo_data = request.form.get("photo_data")
    photo_file = request.files.get("photo_file")
    payload = {
        "nama": request.form.get("nama") or "",
        "gelar": request.form.get("gelar") or "",
        "jabatan": request.form.get("jabatan") or "",
        "jenis_kelamin": request.form.get("jenis_kelamin") or "",
        "tempat_lahir": request.form.get("tempat_lahir") or "",
        "tanggal_lahir": request.form.get("tanggal_lahir") or None,
        "email": request.form.get("email") or "",
        "nip": request.form.get("nip") or "",
        "nuptk": request.form.get("nuptk") or "",
        "foto": request.form.get("foto") or "",
        "is_active": request.form.get("is_active") == "on",
    }
    if not payload["nama"].strip():
        flash("Nama guru/pegawai wajib diisi.", "warning")
        return redirect(url_for("main.landingpage_settings", site_key=site_key))

    updated = update_landingpage_teacher(teacher_id, site_key, payload)
    if updated:
        photo_url = _save_teacher_photo(site_key, teacher_id, photo_data, photo_file)
        if photo_url:
            update_landingpage_teacher_photo(teacher_id, site_key, photo_url)
            payload["foto"] = photo_url
        log_landingpage_activity(
            site_key,
            (current_user() or {}).get("id"),
            action="teacher_update",
            entity_type="teacher",
            entity_id=teacher_id,
            metadata={"nama": payload.get("nama")},
        )
        flash("Data guru berhasil diperbarui.", "success")
    else:
        flash("Data guru tidak ditemukan atau gagal diperbarui.", "warning")
    return redirect(url_for("main.landingpage_settings", site_key=site_key))


@main_bp.route("/settings/landingpage/teachers/<int:teacher_id>/delete", methods=["POST"])
@role_required("admin")
def landingpage_teacher_delete(teacher_id: int) -> Response:
    site_key = (request.form.get("site_key") or "default").strip().lower()
    deleted = delete_landingpage_teacher(teacher_id, site_key)
    if deleted:
        log_landingpage_activity(
            site_key,
            (current_user() or {}).get("id"),
            action="teacher_delete",
            entity_type="teacher",
            entity_id=teacher_id,
        )
        flash("Data guru berhasil dihapus.", "success")
    else:
        flash("Data guru tidak ditemukan.", "warning")
    return redirect(url_for("main.landingpage_settings", site_key=site_key))


@main_bp.route("/settings/landingpage/teachers/reorder", methods=["POST"])
@role_required("admin")
def landingpage_teacher_reorder() -> Response:
    payload = request.get_json(silent=True) or {}
    site_key = (payload.get("site_key") or "default").strip().lower()
    order = payload.get("order") or []
    if not isinstance(order, list):
        return jsonify({"success": False, "message": "Format order tidak valid"}), 400
    try:
        ordered_ids = [int(item) for item in order]
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "ID tidak valid"}), 400
    updated = update_landingpage_teacher_order(site_key, ordered_ids)
    if updated:
        log_landingpage_activity(
            site_key,
            (current_user() or {}).get("id"),
            action="teacher_reorder",
            entity_type="teacher",
            metadata={"count": len(ordered_ids)},
        )
    return jsonify({"success": True, "updated": updated})


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


@main_bp.route("/feedback")
@login_required
def feedback() -> Response:
    """Dashboard page for viewing and analyzing chat feedback."""
    args: MultiDict = request.args
    page = max(1, int(args.get("page", 1)))
    
    # Parse filter parameters
    feedback_type = args.get("feedback_type") or None
    if feedback_type and feedback_type not in ('like', 'dislike'):
        feedback_type = None
    
    start_date = _parse_date(args.get("start_date"))
    end_date = _parse_date(args.get("end_date"))
    
    # Default to last 30 days if no dates specified
    if not start_date and not end_date:
        end_date = current_jakarta_time()
        start_date = end_date - timedelta(days=30)
    
    # Fetch summary statistics
    summary = fetch_feedback_summary(start_date=start_date, end_date=end_date)
    
    # Fetch paginated feedback list
    limit = REPORT_PAGE_SIZE
    offset = (page - 1) * limit
    records, total = fetch_feedback_list(
        filter_type=feedback_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset
    )
    
    # Convert timestamps to Jakarta timezone for display
    for record in records:
        if record.get("created_at"):
            record["created_at"] = to_jakarta(record["created_at"])
        if record.get("message_created_at"):
            record["message_created_at"] = to_jakarta(record["message_created_at"])
    
    # Fetch trend data for chart (last 30 days from end_date)
    trend_start = (end_date or current_jakarta_time()) - timedelta(days=30)
    trend_data = fetch_feedback_trend(start_date=trend_start, days=30)
    
    # Prepare chart data
    chart_days: list[str] = []
    chart_likes: list[int] = []
    chart_dislikes: list[int] = []
    
    for row in trend_data:
        day = row.get("day")
        if hasattr(day, "isoformat"):
            day_str = day.isoformat()
        else:
            day_str = str(day)
        chart_days.append(day_str)
        chart_likes.append(row.get("likes", 0))
        chart_dislikes.append(row.get("dislikes", 0))
    
    # Calculate pagination
    total_pages = max(1, ceil(total / limit))
    
    return render_template(
        "feedback.html",
        summary=summary,
        records=records,
        total=total,
        page=page,
        total_pages=total_pages,
        per_page=limit,
        filter_type=feedback_type,
        start_date=start_date,
        end_date=end_date,
        chart_days=chart_days,
        chart_likes=chart_likes,
        chart_dislikes=chart_dislikes,
        generated_at=current_jakarta_time(),
    )


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


