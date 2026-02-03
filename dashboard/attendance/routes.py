from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import base64
import binascii
import calendar
import io
import secrets
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import (
    Response,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    send_file,
    url_for,
)
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
from PIL import Image, ImageDraw

from utils import (
    INDONESIAN_DAY_NAMES,
    INDONESIAN_MONTH_NAMES,
    current_jakarta_time,
    to_jakarta,
)

from ..auth import current_user, login_required, role_required
from . import attendance_bp
from .duk_degrees import resolve_degree_from_duk
from .queries import (
    ATTENDANCE_STATUSES,
    DEFAULT_ATTENDANCE_STATUS,
    create_school_class,
    create_student,
    deactivate_student,
    create_teacher_user,
    fetch_active_teachers,
    fetch_all_students,
    fetch_attendance_for_date,
    fetch_attendance_totals_for_date,
    fetch_class_attendance_breakdown,
    fetch_class_submission_status_for_date,
    fetch_daily_attendance,
    fetch_master_data_overview,
    fetch_most_missing_attendance_classes,
    fetch_monthly_attendance_overview,
    fetch_class_month_attendance_entries,
    fetch_recent_attendance,
    fetch_extracurricular_attendance_for_date,
    fetch_extracurricular_attendance_detail,
    fetch_extracurricular_attendance_totals_for_date_all,
    fetch_extracurricular_daily_totals,
    fetch_extracurricular_members,
    fetch_extracurricular_overview,
    fetch_extracurricular_recent_attendance,
    fetch_extracurricular_evidence_sessions,
    fetch_extracurricular_evidence_for_date,
    fetch_extracurricular_photo_options,
    fetch_extracurricular_coaches,
    search_extracurricular_students,
    fetch_school_identity,
    fetch_students_for_class,
    fetch_late_students_for_date,
    fetch_teacher_absence_for_date,
    fetch_teacher_assigned_class,
    fetch_teacher_attendance_for_date,
    fetch_teacher_profile,
    fetch_teacher_master_data,
    get_school_class,
    list_attendance_months,
    list_school_classes,
    list_extracurriculars,
    update_student_record,
    update_student_sequences,
    update_teacher_assigned_class,
    update_teacher_user,
    create_extracurricular,
    get_extracurricular,
    set_extracurricular_active,
    update_extracurricular,
    upsert_attendance_entries,
    replace_late_students_for_date,
    upsert_teacher_attendance_entries,
    upsert_extracurricular_attendance_entries,
    upsert_extracurricular_members,
    set_extracurricular_member_active,
    set_extracurricular_members_active,
    update_extracurricular_member,
    delete_extracurricular_member,
    delete_extracurricular_members,
)
from ..queries import fetch_landingpage_content
from .semester_exporter import (
    SEMESTER_2_2025_2026_MONTHS,
    generate_semester_excel,
)

STATUS_LABELS: Dict[str, str] = {
    "masuk": "Masuk",
    "alpa": "Alpa",
    "izin": "Izin",
    "sakit": "Sakit",
}

STATUS_BADGES: Dict[str, str] = {
    "masuk": "success",
    "alpa": "danger",
    "izin": "warning",
    "sakit": "info",
}

ACADEMIC_MONTH_SEQUENCE: Tuple[int, ...] = (7, 8, 9, 10, 11, 12, 1, 2, 3, 4, 5, 6)


def _resolve_attendance_date(raw_value: Optional[str]) -> date:
    if raw_value:
        try:
            return date.fromisoformat(raw_value)
        except ValueError:
            pass
    return current_jakarta_time().date()


def _normalize_status(value: Optional[str]) -> str:
    if not value:
        return DEFAULT_ATTENDANCE_STATUS
    normalized = value.strip().lower()
    return normalized if normalized in ATTENDANCE_STATUSES else DEFAULT_ATTENDANCE_STATUS


def _format_indonesian_date(value: date) -> str:
    day_label = INDONESIAN_DAY_NAMES.get(value.weekday(), value.strftime("%A"))
    month_label = INDONESIAN_MONTH_NAMES.get(value.month, value.strftime("%B"))
    return f"{day_label}, {value.day:02d} {month_label} {value.year}"


def _parse_birth_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            parsed = datetime.strptime(normalized, fmt)
            return parsed.date()
        except ValueError:
            continue
    return None


def _parse_optional_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("Tanggal tidak valid.") from exc


def _parse_optional_int(value: Optional[str], *, field_label: str) -> Optional[int]:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return int(normalized)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_label} harus berupa angka.") from exc


def _parse_optional_float(value: Optional[str], *, field_label: str) -> Optional[float]:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return float(normalized)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_label} tidak valid.") from exc


def _parse_optional_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("Timestamp foto tidak valid.") from exc


def _decode_data_url(data_url: str) -> Tuple[bytes, str]:
    if not data_url:
        raise ValueError("Foto bukti wajib diisi.")
    if "," not in data_url:
        raise ValueError("Format foto bukti tidak valid.")
    header, encoded = data_url.split(",", 1)
    if not header.startswith("data:image/"):
        raise ValueError("Format foto bukti tidak valid.")
    mime = header.split(";")[0].split(":")[-1].lower()
    if mime not in {"image/jpeg", "image/jpg", "image/png"}:
        raise ValueError("Format foto bukti harus JPEG atau PNG.")
    try:
        payload = base64.b64decode(encoded)
    except binascii.Error as exc:
        raise ValueError("Foto bukti tidak dapat dibaca.") from exc
    extension = "jpg" if mime in {"image/jpeg", "image/jpg"} else "png"
    return payload, extension


_REQUIRED_EKSKUL_CONFIG_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("schedule_day", "Hari"),
    ("start_time", "Jam Mulai"),
    ("end_time", "Jam Selesai"),
    ("description", "Deskripsi"),
)


def _find_incomplete_extracurricular(activities: List[Dict[str, Any]]) -> Optional[Tuple[Dict[str, Any], List[str]]]:
    for activity in activities:
        missing: List[str] = []
        for key, label in _REQUIRED_EKSKUL_CONFIG_FIELDS:
            value = activity.get(key)
            if value is None or not str(value).strip():
                missing.append(label)
        if missing:
            return activity, missing
    return None


@attendance_bp.before_request
def _ensure_extracurricular_config_complete() -> Optional[Response]:
    user = current_user()
    if not user or user.get("role") != "ekskul":
        return None
    endpoint = request.endpoint or ""
    if not endpoint.startswith("attendance.ekskul"):
        return None

    activities = list_extracurriculars(include_inactive=True, coach_user_id=user.get("id"))
    allowed_ids = {int(item["id"]) for item in activities if item.get("id")}

    raw_activity_id = request.values.get("activity_id")
    if raw_activity_id:
        try:
            activity_id = int(raw_activity_id)
        except (TypeError, ValueError):
            activity_id = None
        if activity_id is None or activity_id not in allowed_ids:
            if endpoint == "attendance.ekskul_member_search":
                return jsonify({"items": [], "error": "Tidak memiliki akses."}), 403
            flash("Anda tidak memiliki akses ke ekskul ini.", "danger")
            return redirect(url_for("attendance.ekskul_dashboard"))

    if endpoint == "attendance.ekskul_config":
        return None
    if not activities:
        return None
    incomplete = _find_incomplete_extracurricular(activities)
    if not incomplete:
        return None
    activity, missing_fields = incomplete
    missing_label = ", ".join(missing_fields)
    flash(
        f"Lengkapi konfigurasi ekskul '{activity.get('name')}' terlebih dahulu. Data wajib: {missing_label}.",
        "warning",
    )
    return redirect(url_for("attendance.ekskul_config"))


def _save_extracurricular_photo(
    photo_data: str,
    *,
    activity_id: int,
    attendance_date: date,
    captured_at: Optional[datetime],
) -> str:
    payload, _extension = _decode_data_url(photo_data)
    try:
        image = Image.open(io.BytesIO(payload))
        image = image.convert("RGB")
    except Exception as exc:
        raise ValueError("Foto bukti tidak dapat diproses.") from exc

    max_side = 1600
    width, height = image.size
    if max(width, height) > max_side:
        image.thumbnail((max_side, max_side))

    timestamp = captured_at or current_jakarta_time()
    safe_date = attendance_date.isoformat()
    filename = f"ekskul_{activity_id}_{timestamp:%Y%m%d_%H%M%S}_{secrets.token_hex(4)}.jpg"
    relative = f"uploads/ekskul/{activity_id}/{safe_date}/{filename}"
    output_path = Path(current_app.root_path) / "static" / relative
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="JPEG", quality=85, optimize=True)
    return relative


def _save_extracurricular_lp_photo(file_storage, *, activity_id: int) -> str:
    if not file_storage or not getattr(file_storage, "filename", None):
        raise ValueError("File foto tidak ditemukan.")
    try:
        file_storage.stream.seek(0)
        image = Image.open(file_storage.stream)
        image = image.convert("RGB")
    except Exception as exc:
        raise ValueError("Foto landing page tidak dapat diproses.") from exc

    max_side = 1600
    width, height = image.size
    if max(width, height) > max_side:
        image.thumbnail((max_side, max_side))

    max_bytes = 100 * 1024
    quality = 85
    scale = 1.0
    last_buffer = None
    for _ in range(12):
        working = image
        if scale < 1:
            new_w = max(1, int(image.width * scale))
            new_h = max(1, int(image.height * scale))
            working = image.resize((new_w, new_h), Image.LANCZOS)

        buffer = io.BytesIO()
        working.save(buffer, format="JPEG", quality=quality, optimize=True)
        size = buffer.tell()
        last_buffer = buffer

        if size <= max_bytes:
            break
        if quality > 50:
            quality -= 10
        elif scale > 0.5:
            scale = max(0.5, scale - 0.1)
            quality = 85
        else:
            quality = max(40, quality - 5)

    if not last_buffer:
        raise ValueError("Gagal menyimpan foto.")

    timestamp = current_jakarta_time()
    filename = f"lp_{activity_id}_{timestamp:%Y%m%d_%H%M%S}_{secrets.token_hex(4)}.jpg"
    relative = f"uploads/ekskul/{activity_id}/lp/{filename}"
    output_path = Path(current_app.root_path) / "static" / relative
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(last_buffer.getvalue())
    return relative


def _resolve_month_reference(raw_value: Optional[str], fallback: date) -> date:
    if raw_value:
        try:
            parsed = datetime.strptime(raw_value, "%Y-%m")
            return parsed.date().replace(day=1)
        except ValueError:
            pass
    return fallback.replace(day=1)


def _format_month_label(value: date) -> str:
    month_label = INDONESIAN_MONTH_NAMES.get(value.month, value.strftime("%B"))
    return f"{month_label} {value.year}"


def _compose_teacher_display_name(profile: Optional[Dict[str, Any]], fallback_name: Optional[str]) -> Optional[str]:
    if not profile:
        return fallback_name
    prefix = (profile.get("degree_prefix") or "").strip()
    suffix = (profile.get("degree_suffix") or "").strip()
    full_name = (profile.get("full_name") or fallback_name or "").strip()
    parts = [part for part in (prefix, full_name, suffix) if part]
    return " ".join(parts) if parts else None


def _build_month_options(available_months: List[date], selected_month: date) -> List[Dict[str, str]]:
    options: List[Dict[str, str]] = []
    observed: set[str] = set()
    for month_date in available_months:
        if not isinstance(month_date, date):
            try:
                month_date = date.fromisoformat(str(month_date))
            except Exception:
                continue
        key = month_date.strftime("%Y-%m")
        if key in observed:
            continue
        observed.add(key)
        options.append(
            {
                "value": key,
                "label": _format_month_label(month_date),
            }
        )
    selected_key = selected_month.strftime("%Y-%m")
    if selected_key not in observed:
        options.append(
            {
                "value": selected_key,
                "label": _format_month_label(selected_month),
            }
        )
    return options


def _resolve_academic_year_key(month_value: date) -> Tuple[str, int]:
    start_year = month_value.year if month_value.month >= 7 else month_value.year - 1
    return f"{start_year}-{start_year + 1}", start_year


def _build_academic_year_labels(start_year: int) -> List[str]:
    labels: List[str] = []
    for month in ACADEMIC_MONTH_SEQUENCE:
        year_value = start_year if month >= 7 else start_year + 1
        month_label = INDONESIAN_MONTH_NAMES.get(month, calendar.month_name[month])
        labels.append(f"{month_label} {year_value}")
    return labels


def _extract_student_form_payload(form_data) -> Dict[str, Any]:
    raw_class_id = form_data.get("student_class_id")
    if not raw_class_id:
        raise ValueError("Silakan pilih kelas untuk siswa.")
    try:
        class_id = int(raw_class_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Kelas siswa tidak valid.") from exc
    full_name = (form_data.get("student_name") or "").strip()
    if not full_name:
        raise ValueError("Nama siswa wajib diisi.")
    payload: Dict[str, Any] = {
        "class_id": class_id,
        "full_name": full_name,
        "student_number": (form_data.get("student_number") or "").strip() or None,
        "nisn": (form_data.get("student_nisn") or "").strip() or None,
        "gender": (form_data.get("student_gender") or "").strip() or None,
        "birth_place": (form_data.get("student_birth_place") or "").strip() or None,
        "birth_date": _parse_birth_date(form_data.get("student_birth_date")),
        "religion": (form_data.get("student_religion") or "").strip() or None,
        "address_line": (form_data.get("student_address") or "").strip() or None,
        "rt": (form_data.get("student_rt") or "").strip() or None,
        "rw": (form_data.get("student_rw") or "").strip() or None,
        "kelurahan": (form_data.get("student_kelurahan") or "").strip() or None,
        "kecamatan": (form_data.get("student_kecamatan") or "").strip() or None,
        "father_name": (form_data.get("student_father") or "").strip() or None,
        "mother_name": (form_data.get("student_mother") or "").strip() or None,
        "nik": (form_data.get("student_nik") or "").strip() or None,
        "kk_number": (form_data.get("student_kk") or "").strip() or None,
    }
    return payload


@attendance_bp.route("/absen", methods=["GET"])
@login_required
@role_required("staff", "admin")
def dashboard() -> str:
    now = current_jakarta_time()
    today = now.date()
    missing_range_end = today
    missing_range_start = today - timedelta(days=30)
    overview = fetch_master_data_overview()
    today_totals = fetch_attendance_totals_for_date(today)
    daily_rows = fetch_daily_attendance(days=7)

    chart_labels: List[str] = []
    chart_masuk: List[int] = []
    chart_alpa: List[int] = []
    chart_izin: List[int] = []
    chart_sakit: List[int] = []
    chart_zero_totals: List[bool] = []
    for row in daily_rows:
        day_value = row.get("attendance_date")
        if isinstance(day_value, date):
            label = day_value.strftime("%d/%m")
        else:
            try:
                label = date.fromisoformat(str(day_value)).strftime("%d/%m")
            except Exception:
                label = str(day_value)
        chart_labels.append(label)
        present = int(row.get("masuk") or 0)
        alpa = int(row.get("alpa") or 0)
        izin = int(row.get("izin") or 0)
        sakit = int(row.get("sakit") or 0)
        chart_masuk.append(present)
        chart_alpa.append(alpa)
        chart_izin.append(izin)
        chart_sakit.append(sakit)
        total_entries = present + alpa + izin + sakit
        chart_zero_totals.append(total_entries == 0)

    monthly_source_months = list_attendance_months(limit=18)
    normalized_months: List[date] = []
    observed_month_keys: set[str] = set()
    for month_entry in monthly_source_months:
        if not isinstance(month_entry, date):
            try:
                month_entry = date.fromisoformat(str(month_entry))
            except Exception:
                continue
        month_key = month_entry.strftime("%Y-%m")
        if month_key in observed_month_keys:
            continue
        observed_month_keys.add(month_key)
        normalized_months.append(month_entry)
    if not normalized_months:
        normalized_months.append(today.replace(day=1))

    monthly_chart_options: List[Dict[str, str]] = []
    monthly_chart_data: Dict[str, Any] = {}
    month_totals_info: List[Dict[str, Any]] = []
    for month_date in normalized_months:
        month_key = month_date.strftime("%Y-%m")
        monthly_chart_options.append(
            {
                "value": month_key,
                "label": _format_month_label(month_date),
            }
        )
        month_rows = fetch_monthly_attendance_overview(month_date.year, month_date.month)
        rows_map: Dict[date, Dict[str, Any]] = {}
        for row in month_rows:
            day_value = row.get("attendance_date")
            if isinstance(day_value, date):
                row_key = day_value
            else:
                try:
                    row_key = date.fromisoformat(str(day_value))
                except Exception:
                    continue
            rows_map[row_key] = row
        days_in_month = calendar.monthrange(month_date.year, month_date.month)[1]
        labels: List[str] = []
        zero_mask: List[bool] = []
        series_map: Dict[str, List[int]] = {status: [] for status in ATTENDANCE_STATUSES}
        month_totals = {status: 0 for status in ATTENDANCE_STATUSES}
        for day in range(1, days_in_month + 1):
            day_date = date(month_date.year, month_date.month, day)
            row = rows_map.get(day_date)
            labels.append(day_date.strftime("%d/%m"))
            day_total = 0
            for status in ATTENDANCE_STATUSES:
                value = int(row.get(status) or 0) if row else 0
                series_map[status].append(value)
                month_totals[status] += value
                day_total += value
            zero_mask.append(day_total == 0)
        monthly_chart_data[month_key] = {
            "labels": labels,
            "series": series_map,
            "zero_mask": zero_mask,
        }
        month_totals_info.append(
            {
                "key": month_key,
                "date": month_date,
                "totals": month_totals,
            }
        )
    monthly_chart_default_key = monthly_chart_options[0]["value"] if monthly_chart_options else None

    academic_year_buckets: Dict[str, Dict[str, Any]] = {}
    for entry in month_totals_info:
        month_date = entry["date"]
        year_key, start_year = _resolve_academic_year_key(month_date)
        bucket = academic_year_buckets.setdefault(
            year_key,
            {
                "label": f"{start_year}/{start_year + 1}",
                "start_year": start_year,
                "labels": _build_academic_year_labels(start_year),
                "series": {status: [0] * len(ACADEMIC_MONTH_SEQUENCE) for status in ATTENDANCE_STATUSES},
            },
        )
        month_index = ACADEMIC_MONTH_SEQUENCE.index(month_date.month)
        for status in ATTENDANCE_STATUSES:
            bucket["series"][status][month_index] = entry["totals"][status]

    current_month_anchor = today.replace(day=1)
    current_year_key, current_start_year = _resolve_academic_year_key(current_month_anchor)
    if current_year_key not in academic_year_buckets:
        academic_year_buckets[current_year_key] = {
            "label": f"{current_start_year}/{current_start_year + 1}",
            "start_year": current_start_year,
            "labels": _build_academic_year_labels(current_start_year),
            "series": {status: [0] * len(ACADEMIC_MONTH_SEQUENCE) for status in ATTENDANCE_STATUSES},
        }

    academic_year_options_raw = sorted(
        (
            {"value": key, "label": bucket["label"], "start_year": bucket["start_year"]}
            for key, bucket in academic_year_buckets.items()
        ),
        key=lambda item: item["start_year"],
        reverse=True,
    )
    academic_year_options: List[Dict[str, str]] = [
        {"value": item["value"], "label": item["label"]} for item in academic_year_options_raw
    ]
    academic_year_chart_data = {
        key: {"labels": bucket["labels"], "series": bucket["series"]}
        for key, bucket in academic_year_buckets.items()
    }
    academic_year_default_key = (
        current_year_key if current_year_key in academic_year_chart_data else (
            academic_year_options[0]["value"] if academic_year_options else None
        )
    )

    recent_records = fetch_recent_attendance(limit=8)
    class_submission_status = fetch_class_submission_status_for_date(today)
    class_attendance_rows = fetch_class_attendance_breakdown(today)
    class_attendance_map: Dict[int, Dict[str, Any]] = {}
    for row in class_attendance_rows:
        try:
            class_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        class_attendance_map[class_id] = {
            "name": row.get("name"),
            "academic_year": row.get("academic_year"),
            "masuk": int(row.get("masuk") or 0),
            "alpa": int(row.get("alpa") or 0),
            "izin": int(row.get("izin") or 0),
            "sakit": int(row.get("sakit") or 0),
            "total_students": int(row.get("total_students") or 0),
        }

    most_missing_classes = fetch_most_missing_attendance_classes(
        missing_range_start,
        missing_range_end,
        limit=6,
        exclude_weekends=True,
    )

    return render_template(
        "attendance/stats.html",
        attendance_active_tab="stats",
        overview=overview,
        totals_today=today_totals,
        chart_labels=chart_labels,
        chart_series={
            "masuk": chart_masuk,
            "alpa": chart_alpa,
            "izin": chart_izin,
            "sakit": chart_sakit,
        },
        chart_zero_totals=chart_zero_totals,
        trend_weekly_payload={
            "labels": chart_labels,
            "series": {
                "masuk": chart_masuk,
                "alpa": chart_alpa,
                "izin": chart_izin,
                "sakit": chart_sakit,
            },
            "zero_mask": chart_zero_totals,
        },
        trend_monthly_payload={
            "default": monthly_chart_default_key,
            "options": monthly_chart_options,
            "datasets": monthly_chart_data,
        },
        trend_academic_payload={
            "default": academic_year_default_key,
            "options": academic_year_options,
            "datasets": academic_year_chart_data,
        },
        monthly_chart_options=monthly_chart_options,
        monthly_chart_default_key=monthly_chart_default_key,
        academic_year_options=academic_year_options,
        academic_year_default_key=academic_year_default_key,
        class_attendance_map=class_attendance_map,
        daily_rows=daily_rows,
        recent_records=recent_records,
        class_submission_status=class_submission_status,
        most_missing_classes=most_missing_classes,
        missing_range_start=missing_range_start,
        missing_range_end=missing_range_end,
        generated_at=now,
        today_label=_format_indonesian_date(today),
        status_labels=STATUS_LABELS,
        status_badges=STATUS_BADGES,
    )


@attendance_bp.route("/absen/kelas", methods=["GET"], endpoint="kelas")
@login_required
@role_required("staff", "admin")
def absen() -> str:
    user = current_user()
    if not user:
        return redirect(url_for("auth.login"))

    selected_date = _resolve_attendance_date(request.args.get("date"))
    selected_date_label = _format_indonesian_date(selected_date)
    class_options = list_school_classes()
    teacher_class = fetch_teacher_assigned_class(user["id"]) or {}
    assigned_class_id = teacher_class.get("assigned_class_id")
    selected_class_id: Optional[int] = int(assigned_class_id) if assigned_class_id else None
    available_class_ids = {int(item["id"]) for item in class_options}
    if selected_class_id and selected_class_id not in available_class_ids:
        selected_class_id = None
        teacher_class = {}

    students_view: List[Dict[str, Any]] = []
    status_counts: Dict[str, int] = {status: 0 for status in ATTENDANCE_STATUSES}
    latest_submission_at: Optional[datetime] = None

    if selected_class_id:
        students = fetch_students_for_class(selected_class_id)
        attendance_map = fetch_attendance_for_date(selected_class_id, selected_date)
        for student in students:
            student_id = int(student["id"])
            record = attendance_map.get(student_id)
            status = _normalize_status(record.get("status") if record else None)
            status_counts[status] = status_counts.get(status, 0) + 1
            submitted_at_raw = record.get("updated_at") if record else None
            if submitted_at_raw is None and record:
                submitted_at_raw = record.get("recorded_at")
            if submitted_at_raw:
                try:
                    submitted_at = to_jakarta(submitted_at_raw)
                except Exception:
                    submitted_at = submitted_at_raw
                if isinstance(submitted_at, datetime):
                    if latest_submission_at is None or submitted_at > latest_submission_at:
                        latest_submission_at = submitted_at

            students_view.append(
                {
                    "id": student_id,
                    "name": student.get("full_name"),
                    "student_number": student.get("student_number"),
                    "status": status,
                    "has_record": bool(record),
                }
            )
    else:
        students_view = []

    total_students = len(students_view)
    if total_students and not any(status_counts.values()):
        status_counts[DEFAULT_ATTENDANCE_STATUS] = total_students

    return render_template(
        "attendance/absen.html",
        attendance_active_tab="kelas",
        selected_date=selected_date,
        class_options=class_options,
        teacher_class=teacher_class,
        selected_class_id=selected_class_id,
        students=students_view,
        status_labels=STATUS_LABELS,
        status_badges=STATUS_BADGES,
        attendance_statuses=ATTENDANCE_STATUSES,
        total_students=total_students,
        status_counts=status_counts,
        latest_submission_at=latest_submission_at,
        today=current_jakarta_time(),
        selected_date_label=selected_date_label,
    )


@attendance_bp.route("/absen/kelas/generate-semester-2", methods=["GET"], endpoint="generate_semester_2")
@login_required
@role_required("staff", "admin")
def generate_semester_2() -> Any:
    user = current_user()
    if not user:
        return redirect(url_for("auth.login"))

    role = user.get("role")
    selected_class_id: Optional[int] = None
    teacher_class: Dict[str, Any] = {}
    if role == "admin":
        raw_class_id = request.args.get("class_id")
        if raw_class_id:
            try:
                selected_class_id = int(raw_class_id)
            except (TypeError, ValueError):
                selected_class_id = None

    if selected_class_id is None:
        teacher_class = fetch_teacher_assigned_class(user["id"]) or {}
        selected_class_id = int(teacher_class.get("assigned_class_id") or 0) or None
    if not selected_class_id:
        flash("Silakan pilih kelas terlebih dahulu.", "warning")
        return redirect(url_for("attendance.kelas"))

    class_detail = get_school_class(selected_class_id) or {}
    if not class_detail:
        flash("Kelas tidak ditemukan.", "warning")
        return redirect(url_for("attendance.kelas"))
    students = fetch_students_for_class(selected_class_id)
    if not students:
        flash("Belum ada data siswa untuk kelas ini.", "warning")
        return redirect(url_for("attendance.kelas"))

    school_identity = fetch_school_identity()
    academic_year = (
        class_detail.get("academic_year")
        or school_identity.get("academic_year")
        or "2025/2026"
    )
    class_label = class_detail.get("name") or teacher_class.get("class_name")
    school_name = school_identity.get("school_name")

    teacher_profile = fetch_teacher_profile(user["id"]) or {}
    teacher_name = _compose_teacher_display_name(teacher_profile, user.get("full_name"))
    teacher_nip = teacher_profile.get("nip")
    headmaster_name = school_identity.get("headmaster_display_name") or _compose_teacher_display_name(
        {
            "degree_prefix": school_identity.get("headmaster_degree_prefix"),
            "full_name": school_identity.get("headmaster_name"),
            "degree_suffix": school_identity.get("headmaster_degree_suffix"),
        },
        None,
    )
    headmaster_nip = school_identity.get("headmaster_nip")

    student_rows: List[Dict[str, Any]] = []
    for idx, student in enumerate(students, start=1):
        seq_value = student.get("sequence")
        try:
            seq = int(seq_value) if seq_value is not None else idx
        except (TypeError, ValueError):
            seq = idx
        gender_raw = (student.get("gender") or "").strip().upper()
        if gender_raw.startswith("L"):
            gender = "L"
        elif gender_raw.startswith("P"):
            gender = "P"
        else:
            gender = ""
        student_rows.append(
            {
                "no": seq,
                "id": int(student.get("id")),
                "name": student.get("full_name"),
                "gender": gender,
            }
        )

    attendance_data: Dict[Tuple[int, int], Dict[Tuple[int, int], str]] = {}
    for year, month in SEMESTER_2_2025_2026_MONTHS:
        entries = fetch_class_month_attendance_entries(selected_class_id, year, month)
        month_map: Dict[Tuple[int, int], str] = {}
        for row in entries:
            try:
                sid = int(row.get("student_id"))
            except (TypeError, ValueError):
                continue
            dt_val = row.get("attendance_date")
            if isinstance(dt_val, date):
                day_num = dt_val.day
            else:
                try:
                    day_num = date.fromisoformat(str(dt_val)).day
                except Exception:
                    continue
            status = (row.get("status") or "").strip().lower()
            if status:
                month_map[(sid, int(day_num))] = status
        attendance_data[(year, month)] = month_map

    template_path = Path(__file__).resolve().parent / "contoh" / "contoh format.xlsx"
    if not template_path.exists():
        flash("Template Excel belum tersedia. Hubungi admin.", "danger")
        return redirect(url_for("attendance.kelas"))

    try:
        stream = generate_semester_excel(
            template_path,
            months=SEMESTER_2_2025_2026_MONTHS,
            students=student_rows,
            attendance_data=attendance_data,
            school_name=school_name,
            academic_year=academic_year,
            class_label=class_label,
            teacher_name=teacher_name,
            teacher_nip=teacher_nip,
            headmaster_name=headmaster_name,
            headmaster_nip=headmaster_nip,
        )
    except RuntimeError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("attendance.kelas"))
    except Exception as exc:
        current_app.logger.exception("Gagal generate absen semester: %s", exc)
        flash("Gagal membuat file absen semester. Silakan coba lagi.", "danger")
        return redirect(url_for("attendance.kelas"))

    safe_class = class_label or "kelas"
    filename = secure_filename(f"absen-semester2-2025-2026-{safe_class}.xlsx")
    if not filename:
        filename = "absen-semester2-2025-2026.xlsx"

    return send_file(
        stream,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@attendance_bp.route("/absen/staff", methods=["GET", "POST"])
@login_required
@role_required("admin")
def staff() -> str:
    user = current_user()
    if not user:
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        selected_date = _resolve_attendance_date(request.form.get("attendance_date"))
    else:
        selected_date = _resolve_attendance_date(request.args.get("date"))

    selected_date_label = _format_indonesian_date(selected_date)
    teachers = fetch_active_teachers()

    if request.method == "POST" and teachers:
        entries: List[Dict[str, Any]] = []
        for teacher in teachers:
            teacher_id = int(teacher["id"])
            status = _normalize_status(request.form.get(f"status_{teacher_id}"))
            entries.append({"teacher_id": teacher_id, "status": status})
        try:
            upsert_teacher_attendance_entries(
                attendance_date=selected_date,
                recorded_by=user["id"],
                entries=entries,
            )
            flash("Absensi staff berhasil disimpan.", "success")
            return redirect(url_for("attendance.staff", date=selected_date.isoformat()))
        except ValueError as exc:
            flash(str(exc), "danger")

    attendance_map = fetch_teacher_attendance_for_date(selected_date)
    status_counts: Dict[str, int] = {status: 0 for status in ATTENDANCE_STATUSES}
    latest_submission_at: Optional[datetime] = None
    teachers_view: List[Dict[str, Any]] = []

    for teacher in teachers:
        teacher_id = int(teacher["id"])
        record = attendance_map.get(teacher_id)
        status = _normalize_status(record.get("status") if record else None)
        status_counts[status] = status_counts.get(status, 0) + 1

        timestamp = record.get("updated_at") if record else None
        if timestamp is None and record:
            timestamp = record.get("recorded_at")
        if timestamp:
            try:
                timestamp_local = to_jakarta(timestamp)
            except Exception:
                timestamp_local = timestamp
            if isinstance(timestamp_local, datetime):
                if latest_submission_at is None or timestamp_local > latest_submission_at:
                    latest_submission_at = timestamp_local

        teachers_view.append(
            {
                "id": teacher_id,
                "name": teacher.get("full_name"),
                "email": teacher.get("email"),
                "jabatan": teacher.get("jabatan"),
                "nrk": teacher.get("nrk"),
                "nip": teacher.get("nip"),
                "status": status,
            }
        )

    total_staff = len(teachers_view)
    if total_staff and not any(status_counts.values()):
        status_counts[DEFAULT_ATTENDANCE_STATUS] = total_staff

    return render_template(
        "attendance/absen_staff.html",
        attendance_active_tab="staff",
        selected_date=selected_date,
        selected_date_label=selected_date_label,
        teachers=teachers_view,
        status_labels=STATUS_LABELS,
        status_badges=STATUS_BADGES,
        attendance_statuses=ATTENDANCE_STATUSES,
        status_counts=status_counts,
        total_staff=total_staff,
        latest_submission_at=latest_submission_at,
        today=current_jakarta_time(),
    )


@attendance_bp.route("/absen/laporan-harian", methods=["GET", "POST"])
@login_required
@role_required("staff", "admin")
def laporan_harian() -> str:
    user = current_user()
    if not user:
        return redirect(url_for("auth.login"))

    raw_date = request.args.get("date") or request.form.get("date")
    selected_date = _resolve_attendance_date(raw_date)
    selected_date_label = _format_indonesian_date(selected_date)

    raw_month = request.args.get("month") or request.form.get("month")
    month_reference = _resolve_month_reference(raw_month, selected_date)

    class_rows = fetch_class_attendance_breakdown(selected_date)
    class_lookup = {}
    for row in class_rows:
        try:
            cls_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        class_lookup[cls_id] = (row.get("name") or "").strip()
    student_options = fetch_all_students()
    if request.method == "POST":
        late_names = request.form.getlist("late_name[]")
        late_class_ids = request.form.getlist("late_class_id[]")
        late_class_labels = request.form.getlist("late_class_label[]")
        late_times = request.form.getlist("late_time[]")
        late_reasons = request.form.getlist("late_reason[]")
        field_counts = [
            len(late_names),
            len(late_class_ids),
            len(late_class_labels),
            len(late_times),
            len(late_reasons),
        ]
        max_rows = max(field_counts) if field_counts else 0
        late_entries_payload: List[Dict[str, Any]] = []
        for idx in range(max_rows):
            student_name = (late_names[idx] if idx < len(late_names) else "").strip()
            if not student_name:
                continue
            class_id_raw = late_class_ids[idx] if idx < len(late_class_ids) else ""
            class_id_value: Optional[int]
            if class_id_raw:
                try:
                    class_id_value = int(class_id_raw)
                except (TypeError, ValueError):
                    class_id_value = None
            else:
                class_id_value = None
            class_label = (late_class_labels[idx] if idx < len(late_class_labels) else "").strip()
            if not class_label:
                class_label = class_lookup.get(class_id_value, "")
            arrival_time = (late_times[idx] if idx < len(late_times) else "").strip()
            reason = (late_reasons[idx] if idx < len(late_reasons) else "").strip()
            late_entries_payload.append(
                {
                    "student_name": student_name,
                    "class_id": class_id_value,
                    "class_label": class_label or None,
                    "arrival_time": arrival_time or None,
                    "reason": reason or None,
                }
            )
        try:
            replace_late_students_for_date(
                attendance_date=selected_date,
                entries=late_entries_payload,
                recorded_by=user["id"],
            )
            flash("Catatan siswa terlambat berhasil diperbarui.", "success")
        except Exception as exc:
            flash(f"Gagal menyimpan catatan terlambat: {exc}", "danger")
        redirect_month = request.form.get("month") or month_reference.strftime("%Y-%m")
        return redirect(
            url_for(
                "attendance.laporan_harian",
                date=selected_date.isoformat(),
                month=redirect_month,
            )
        )
    teacher_absences = fetch_teacher_absence_for_date(selected_date)
    late_students = fetch_late_students_for_date(selected_date)
    school_identity = fetch_school_identity()
    def _compose_with_degree(name: Optional[str], prefix: Optional[str], suffix: Optional[str]) -> Optional[str]:
        parts: List[str] = []
        for v in (prefix, name):
            vv = (v or "").strip()
            if vv and vv != "-":
                parts.append(vv)
        display = " ".join(parts)
        suffix_clean = (suffix or "").strip()
        if suffix_clean and suffix_clean != "-":
            display = (display + ", " if display else "") + suffix_clean
        return display or None
    school_identity["headmaster_display_name"] = _compose_with_degree(
        school_identity.get("headmaster_name"),
        school_identity.get("headmaster_degree_prefix"),
        school_identity.get("headmaster_degree_suffix"),
    ) or school_identity.get("headmaster_name")
    duk_source_path = current_app.config.get("ATTENDANCE_DUK_PATH")
    monthly_overview = fetch_monthly_attendance_overview(month_reference.year, month_reference.month)
    available_month_dates = list_attendance_months(limit=12)

    def _compose_with_degree(name: Optional[str], prefix: Optional[str], suffix: Optional[str]) -> Optional[str]:
        parts: List[str] = []
        for value in (prefix, name):
            cleaned = (value or "").strip()
            if cleaned and cleaned != "-":
                parts.append(cleaned)
        display = " ".join(parts)
        suffix_clean = (suffix or "").strip()
        if suffix_clean and suffix_clean != "-":
            if display:
                display = f"{display}, {suffix_clean}"
            else:
                display = suffix_clean
        return display or None

    if school_identity.get("headmaster_name"):
        head_prefix_missing = not school_identity.get("headmaster_degree_prefix")
        head_suffix_missing = not school_identity.get("headmaster_degree_suffix")
        if head_prefix_missing or head_suffix_missing:
            duk_prefix, duk_suffix = resolve_degree_from_duk(
                school_identity.get("headmaster_name"),
                source_path=duk_source_path,
            )
            if duk_prefix and head_prefix_missing:
                school_identity["headmaster_degree_prefix"] = duk_prefix
            if duk_suffix and head_suffix_missing:
                school_identity["headmaster_degree_suffix"] = duk_suffix

    for entry in teacher_absences:
        if entry.get("full_name"):
            prefix_missing = not entry.get("degree_prefix")
            suffix_missing = not entry.get("degree_suffix")
            if prefix_missing or suffix_missing:
                duk_prefix, duk_suffix = resolve_degree_from_duk(
                    entry.get("full_name"),
                    source_path=duk_source_path,
                )
                if duk_prefix and prefix_missing:
                    entry["degree_prefix"] = duk_prefix
                if duk_suffix and suffix_missing:
                    entry["degree_suffix"] = duk_suffix
        entry["display_name"] = _compose_with_degree(
            entry.get("full_name"),
            entry.get("degree_prefix"),
            entry.get("degree_suffix"),
        ) or entry.get("full_name")

    school_identity["headmaster_display_name"] = _compose_with_degree(
        school_identity.get("headmaster_name"),
        school_identity.get("headmaster_degree_prefix"),
        school_identity.get("headmaster_degree_suffix"),
    ) or school_identity.get("headmaster_name")

    def _class_sort_key(item: Dict[str, Any]) -> tuple[int, str]:
        raw_name = (item.get("name") or "").strip()
        normalized = "".join(raw_name.split()).upper()
        numeric = "".join(ch for ch in normalized if ch.isdigit())
        alpha = "".join(ch for ch in normalized if ch.isalpha())
        grade = int(numeric) if numeric else 0
        return (grade, alpha)

    class_rows_sorted = sorted(class_rows, key=_class_sort_key)
    status_totals = {"sakit": 0, "izin": 0, "alpa": 0, "masuk": 0}
    class_columns: List[str] = []
    class_stats = {"s": {}, "i": {}, "a": {}}

    for row in class_rows_sorted:
        for key in status_totals:
            status_totals[key] += int(row.get(key) or 0)
        display_name = "".join((row.get("name") or "").split()).upper()
        if not display_name:
            continue
        class_columns.append(display_name)
        class_stats["s"][display_name] = int(row.get("sakit") or 0)
        class_stats["i"][display_name] = int(row.get("izin") or 0)
        class_stats["a"][display_name] = int(row.get("alpa") or 0)

    preferred_order = [
        "1A", "1B", "1C", "1D",
        "2A", "2B", "2C", "2D",
        "3A", "3B", "3C", "3D",
        "4A", "4B", "4C", "4D",
        "5A", "5B", "5C", "5D",
        "6A", "6B", "6C", "6D",
    ]
    class_columns = preferred_order

    for status_code in ("s", "i", "a"):
        for column in class_columns:
            class_stats[status_code].setdefault(column, 0)

    selected_month_label = _format_month_label(month_reference)
    available_months = _build_month_options(available_month_dates, month_reference)

    monthly_totals = {"sakit": 0, "izin": 0, "alpa": 0, "masuk": 0}
    monthly_rows = []
    for row in monthly_overview:
        day_value = row.get("attendance_date")
        if not isinstance(day_value, date):
            try:
                day_value = date.fromisoformat(str(day_value))
            except Exception:
                continue
        monthly_rows.append(
            {
                "date": day_value,
                "label": _format_indonesian_date(day_value),
                "sakit": int(row.get("sakit") or 0),
                "izin": int(row.get("izin") or 0),
                "alpa": int(row.get("alpa") or 0),
                "masuk": int(row.get("masuk") or 0),
            }
        )
        for key in monthly_totals:
            monthly_totals[key] += int(row.get(key) or 0)

    monthly_rows.sort(key=lambda item: item["date"])

    default_academic_year = f"{month_reference.year}/{month_reference.year + 1}"

    return render_template(
        "attendance/report_daily.html",
        attendance_active_tab="laporan_harian",
        selected_date=selected_date,
        selected_date_label=selected_date_label,
        selected_month=month_reference,
        selected_month_label=selected_month_label,
        class_columns=class_columns,
        class_grid=class_stats,
        status_totals=status_totals,
        teacher_absences=teacher_absences,
        school_identity=school_identity,
        available_months=available_months,
        monthly_rows=monthly_rows,
        monthly_totals=monthly_totals,
        available_classes=class_rows_sorted,
        student_options=student_options,
        status_labels=STATUS_LABELS,
        default_academic_year=default_academic_year,
        today=current_jakarta_time(),
        late_students=late_students,
    )


@attendance_bp.route("/absen/laporan-bulanan", methods=["GET"])
@login_required
@role_required("staff", "admin")
def laporan_bulanan() -> str:
    user = current_user()
    if not user:
        return redirect(url_for("auth.login"))

    today = current_jakarta_time()
    month_reference = _resolve_month_reference(request.args.get("month"), today.date())
    selected_month_label = _format_month_label(month_reference)
    monthly_overview = fetch_monthly_attendance_overview(month_reference.year, month_reference.month)
    available_month_dates = list_attendance_months(limit=12)
    monthly_totals = {"sakit": 0, "izin": 0, "alpa": 0, "masuk": 0}
    monthly_rows: List[Dict[str, Any]] = []

    for row in monthly_overview:
        day_value = row.get("attendance_date")
        if not isinstance(day_value, date):
            try:
                day_value = date.fromisoformat(str(day_value))
            except Exception:
                continue
        entry = {
            "date": day_value,
            "label": _format_indonesian_date(day_value),
            "sakit": int(row.get("sakit") or 0),
            "izin": int(row.get("izin") or 0),
            "alpa": int(row.get("alpa") or 0),
            "masuk": int(row.get("masuk") or 0),
        }
        monthly_rows.append(entry)
        for key in monthly_totals:
            monthly_totals[key] += entry[key]

    monthly_rows.sort(key=lambda item: item["date"])
    available_months = _build_month_options(available_month_dates, month_reference)
    total_hari_tercatat = len(monthly_rows)
    total_absen = sum(monthly_totals.values())
    school_identity = fetch_school_identity()

    return render_template(
        "attendance/report_monthly.html",
        attendance_active_tab="laporan_bulanan",
        selected_month=month_reference,
        selected_month_label=selected_month_label,
        monthly_rows=monthly_rows,
        monthly_totals=monthly_totals,
        total_hari_tercatat=total_hari_tercatat,
        total_absen=total_absen,
        available_months=available_months,
        school_identity=school_identity,
        status_labels=STATUS_LABELS,
        today=today,
    )


@attendance_bp.route("/absen/lembar-bulanan", methods=["GET"], endpoint="lembar_bulanan")
@login_required
@role_required("staff", "admin")
def lembar_bulanan() -> str:
    """Cetak lembar absensi bulanan per kelas (tiap siswa per hari)."""
    user = current_user()
    if not user:
        return redirect(url_for("auth.login"))

    today = current_jakarta_time()
    month_reference = _resolve_month_reference(request.args.get("month"), today.date())
    selected_month_label = _format_month_label(month_reference)

    # Resolve class selection
    class_options = list_school_classes()
    class_lookup = {int(c["id"]): c for c in class_options}
    raw_class_id = request.args.get("class_id")
    selected_class_id: Optional[int] = None
    if raw_class_id:
        try:
            selected_class_id = int(raw_class_id)
        except (TypeError, ValueError):
            selected_class_id = None
    if selected_class_id is None:
        teacher_class = fetch_teacher_assigned_class(user["id"]) or {}
        selected_class_id = int(teacher_class.get("assigned_class_id") or 0) or None

    students = fetch_students_for_class(selected_class_id) if selected_class_id else []
    school_identity = fetch_school_identity()

    # Build matrix only if class selected
    days_in_month = calendar.monthrange(month_reference.year, month_reference.month)[1]
    day_list = [date(month_reference.year, month_reference.month, d) for d in range(1, days_in_month + 1)]
    weekday_flags = [d.weekday() >= 5 for d in day_list]  # True if weekend

    entries = (
        fetch_class_month_attendance_entries(selected_class_id, month_reference.year, month_reference.month)
        if selected_class_id
        else []
    )
    # Build quick lookup: (student_id, day) -> status
    entry_map: Dict[tuple[int, int], str] = {}
    for row in entries:
        try:
            sid = int(row.get("student_id"))
        except (TypeError, ValueError):
            continue
        day_num = None
        dt_val = row.get("attendance_date")
        if isinstance(dt_val, date):
            day_num = dt_val.day
        else:
            try:
                day_num = date.fromisoformat(str(dt_val)).day
            except Exception:
                day_num = None
        if day_num is None:
            continue
        status = _normalize_status(row.get("status"))
        entry_map[(sid, int(day_num))] = status

    # Daily recap counters
    daily_recap = {d: {"masuk": 0, "sakit": 0, "izin": 0, "alpa": 0} for d in range(1, days_in_month + 1)}

    students_view: List[Dict[str, Any]] = []
    male_count = 0
    female_count = 0
    for idx, student in enumerate(students, start=1):
        gender = (student.get("gender") or "").strip().upper()
        if gender.startswith("L"):
            male_count += 1
        elif gender.startswith("P"):
            female_count += 1

        day_cells: List[str] = []
        counters = {"masuk": 0, "sakit": 0, "izin": 0, "alpa": 0}
        for d in range(1, days_in_month + 1):
            status = entry_map.get((int(student["id"]), d))
            symbol = ""
            if status == "masuk":
                symbol = "✓"
            elif status == "sakit":
                symbol = "S"
            elif status == "izin":
                symbol = "I"
            elif status == "alpa":
                symbol = "A"
            if status:
                counters[status] += 1
                daily_recap[d][status] += 1
            day_cells.append(symbol)

        students_view.append(
            {
                "no": idx,
                "id": int(student["id"]),
                "name": student.get("full_name"),
                "gender": (student.get("gender") or "").strip().upper(),
                "days": day_cells,
                "totals": counters,
            }
        )

    # Effective days are days with any record (any status) for the class
    effective_days = 0
    hadir_per_hari = []
    for d in range(1, days_in_month + 1):
        rec = daily_recap[d]
        day_total = rec["masuk"] + rec["sakit"] + rec["izin"] + rec["alpa"]
        if day_total > 0:
            effective_days += 1
        hadir_per_hari.append(rec["masuk"])

    # Add percentage to students_view based on effective days
    for student in students_view:
        hadir = student["totals"]["masuk"]
        student["present_percent"] = round((hadir / effective_days) * 100) if effective_days else 0

    available_month_dates = list_attendance_months(limit=12)
    available_months = _build_month_options(available_month_dates, month_reference)

    return render_template(
        "attendance/report_class_monthly.html",
        attendance_active_tab="lembar_bulanan",
        selected_month=month_reference,
        selected_month_label=selected_month_label,
        class_options=class_options,
        selected_class_id=selected_class_id,
        class_detail=class_lookup.get(selected_class_id) if selected_class_id else None,
        students=students_view,
        days_in_month=days_in_month,
        day_list=day_list,
        weekday_flags=weekday_flags,
        daily_recap=daily_recap,
        hadir_per_hari=hadir_per_hari,
        effective_days=effective_days,
        male_count=male_count,
        female_count=female_count,
        total_students=len(students_view),
        available_months=available_months,
        school_identity=school_identity,
        today=today,
    )


@attendance_bp.route("/absen/pilih-kelas", methods=["POST"])
@login_required
@role_required("staff", "admin")
def pilih_kelas() -> str:
    user = current_user()
    if not user:
        return redirect(url_for("auth.login"))

    raw_class_id = request.form.get("class_id")
    if not raw_class_id:
        flash("Silakan pilih kelas terlebih dahulu.", "warning")
        return redirect(url_for("attendance.kelas"))

    try:
        class_id = int(raw_class_id)
    except (TypeError, ValueError):
        flash("Pilihan kelas tidak valid.", "danger")
        return redirect(url_for("attendance.kelas"))

    available_ids = {int(item["id"]) for item in list_school_classes()}
    if class_id not in available_ids:
        flash("Kelas tersebut tidak ditemukan.", "danger")
        return redirect(url_for("attendance.kelas"))

    update_teacher_assigned_class(user["id"], class_id)
    class_detail = get_school_class(class_id)

    session_user = session.get("user") or {}
    session_user["assigned_class_id"] = class_id
    session["user"] = session_user

    if class_detail:
        class_name = class_detail.get("name") or f"ID {class_id}"
        flash(f"Kelas {class_name} berhasil disetel untuk akun Anda.", "success")
    else:
        flash("Kelas berhasil diperbarui.", "success")

    return redirect(url_for("attendance.kelas"))


@attendance_bp.route("/absen/simpan", methods=["POST"])
@login_required
@role_required("staff", "admin")
def simpan_absen() -> str:
    user = current_user()
    if not user:
        return redirect(url_for("auth.login"))

    teacher_class = fetch_teacher_assigned_class(user["id"]) or {}
    assigned_class_id = teacher_class.get("assigned_class_id")
    if not assigned_class_id:
        flash("Silakan pilih kelas terlebih dahulu sebelum menyimpan absensi.", "warning")
        return redirect(url_for("attendance.kelas"))

    try:
        class_id = int(assigned_class_id)
    except (TypeError, ValueError):
        flash("Terjadi kesalahan pada data kelas Anda. Hubungi admin.", "danger")
        return redirect(url_for("attendance.kelas"))

    selected_date = _resolve_attendance_date(request.form.get("attendance_date"))
    students = fetch_students_for_class(class_id)
    if not students:
        flash("Belum ada data siswa untuk kelas ini.", "warning")
        return redirect(url_for("attendance.kelas"))

    student_map = {int(student["id"]): student for student in students}
    entries: List[Dict[str, Any]] = []

    for student_id in student_map:
        status = _normalize_status(request.form.get(f"status_{student_id}"))
        entries.append({"student_id": student_id, "status": status})

    try:
        upsert_attendance_entries(
            class_id=class_id,
            teacher_id=user["id"],
            attendance_date=selected_date,
            entries=entries,
        )
    except ValueError as exc:
        # User input error
        flash(str(exc), "danger")
        return redirect(url_for("attendance.kelas"))
    except Exception as exc:
        # Unexpected system error (e.g., DB constraints)
        # Added explicit error handling to prevent 500 crashes
        current_app.logger.exception("Error saving attendance")
        flash(f"Terjadi kesalahan sistem saat menyimpan absensi: {exc}", "danger")
        return redirect(url_for("attendance.kelas"))

    flash("Absensi berhasil disimpan.", "success")
    return redirect(url_for("attendance.kelas", date=selected_date.isoformat()))


@attendance_bp.route("/absen/master", methods=["GET", "POST"])
@login_required
@role_required("staff", "admin")
def master_data() -> str:
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        try:
            if action == "create_class":
                class_name = request.form.get("class_name")
                academic_year = request.form.get("academic_year")
                create_school_class(name=class_name or "", academic_year=academic_year)
                flash("Kelas baru berhasil disimpan.", "success")
            elif action == "create_student":
                student_payload = _extract_student_form_payload(request.form)
                create_student(
                    student_payload["class_id"],
                    student_payload["full_name"],
                    student_number=student_payload["student_number"],
                    nisn=student_payload["nisn"],
                    gender=student_payload["gender"],
                    birth_place=student_payload["birth_place"],
                    birth_date=student_payload["birth_date"],
                    religion=student_payload["religion"],
                    address_line=student_payload["address_line"],
                    rt=student_payload["rt"],
                    rw=student_payload["rw"],
                    kelurahan=student_payload["kelurahan"],
                    kecamatan=student_payload["kecamatan"],
                    father_name=student_payload["father_name"],
                    mother_name=student_payload["mother_name"],
                    nik=student_payload["nik"],
                    kk_number=student_payload["kk_number"],
                )
                flash("Data siswa berhasil disimpan.", "success")
            elif action == "update_student":
                raw_student_id = request.form.get("student_id")
                if not raw_student_id:
                    raise ValueError("ID siswa tidak ditemukan.")
                try:
                    student_id = int(raw_student_id)
                except (TypeError, ValueError) as exc:
                    raise ValueError("ID siswa tidak valid.") from exc
                student_payload = _extract_student_form_payload(request.form)
                updated = update_student_record(student_id=student_id, **student_payload)
                if not updated:
                    flash("Data siswa tidak ditemukan.", "warning")
                else:
                    flash("Data siswa berhasil diperbarui.", "success")
            elif action == "delete_student":
                raw_student_id = request.form.get("student_id")
                if not raw_student_id:
                    raise ValueError("ID siswa tidak ditemukan.")
                try:
                    student_id = int(raw_student_id)
                except (TypeError, ValueError) as exc:
                    raise ValueError("ID siswa tidak valid.") from exc
                removed = deactivate_student(student_id)
                if not removed:
                    flash("Data siswa tidak ditemukan atau sudah dihapus.", "warning")
                else:
                    flash("Data siswa berhasil dihapus.", "success")
            else:
                flash("Aksi tidak dikenal.", "warning")
        except ValueError as exc:
            flash(str(exc), "danger")
        except Exception as exc:
            flash(f"Gagal menyimpan data: {exc}", "danger")
        return redirect(url_for("attendance.master_data"))

    classes = list_school_classes()
    students = fetch_all_students()
    class_lookup = {int(c["id"]): c for c in classes}

    students_by_class: Dict[int, List[Dict[str, Any]]] = {int(c["id"]): [] for c in classes}
    for student in students:
        class_id = int(student["class_id"])
        students_by_class.setdefault(class_id, []).append(student)

    for entries in students_by_class.values():
        entries.sort(key=lambda item: ((item.get("sequence") or 9999), item.get("full_name") or ""))

    return render_template(
        "attendance/master_data.html",
        attendance_active_tab="master_siswa",
        classes=classes,
        students_by_class=students_by_class,
        class_lookup=class_lookup,
    )


@attendance_bp.route("/absen/master/students/order", methods=["POST"])
@login_required
@role_required("admin")
def update_student_order() -> Any:
    payload = request.get_json(silent=True) or {}
    raw_class_id = payload.get("classId")
    ordered_ids = payload.get("orderedIds")

    if raw_class_id is None:
        return jsonify({"success": False, "message": "ID kelas wajib diisi."}), 400
    try:
        class_id = int(raw_class_id)
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "ID kelas tidak valid."}), 400

    if not isinstance(ordered_ids, list) or not ordered_ids:
        return jsonify({"success": False, "message": "Urutan siswa wajib diisi."}), 400

    ordered: List[int] = []
    for raw_id in ordered_ids:
        try:
            ordered.append(int(raw_id))
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "ID siswa tidak valid."}), 400

    if len(set(ordered)) != len(ordered):
        return jsonify({"success": False, "message": "Urutan siswa mengandung duplikasi."}), 400

    try:
        updated = update_student_sequences(class_id, ordered)
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except Exception as exc:  # pragma: no cover - surfaces to UI
        current_app.logger.exception("Gagal memperbarui urutan siswa.")
        return jsonify({"success": False, "message": f"Gagal memperbarui urutan siswa: {exc}"}), 500

    if updated != len(ordered):
        return jsonify({"success": False, "message": "Sebagian siswa tidak ditemukan."}), 400

    return jsonify({"success": True, "updated": updated})


@attendance_bp.route("/absen/master/staff", methods=["GET", "POST"])
@login_required
@role_required("admin")
def master_staff() -> str:
    classes = list_school_classes()
    class_lookup = {int(c["id"]): c for c in classes}

    def _resolve_class_id(raw_value: Optional[str]) -> Optional[int]:
        if not raw_value:
            return None
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Pilihan kelas binaan tidak valid.") from exc
        if value not in class_lookup:
            raise ValueError("Kelas binaan tidak ditemukan.")
        return value

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        try:
            if action == "create_teacher":
                password = request.form.get("teacher_password")
                if not password:
                    raise ValueError("Password awal staff wajib diisi.")
                assigned_class_id = _resolve_class_id(request.form.get("teacher_assigned_class"))
                create_teacher_user(
                    email=request.form.get("teacher_email"),
                    full_name=request.form.get("teacher_name"),
                    password_hash=generate_password_hash(password, method="pbkdf2:sha256", salt_length=12),
                    nrk=request.form.get("teacher_nrk"),
                    nip=request.form.get("teacher_nip"),
                    jabatan=request.form.get("teacher_jabatan"),
                    degree_prefix=request.form.get("teacher_degree_prefix"),
                    degree_suffix=request.form.get("teacher_degree_suffix"),
                    assigned_class_id=assigned_class_id,
                )
                flash("Data staff baru berhasil disimpan.", "success")
            elif action == "update_teacher":
                raw_teacher_id = request.form.get("teacher_id")
                if not raw_teacher_id:
                    raise ValueError("ID staff tidak ditemukan.")
                try:
                    teacher_id = int(raw_teacher_id)
                except (TypeError, ValueError) as exc:
                    raise ValueError("ID staff tidak valid.") from exc
                assigned_class_id = _resolve_class_id(request.form.get("teacher_assigned_class"))
                password = request.form.get("teacher_password") or None
                password_hash = (
                    generate_password_hash(password, method="pbkdf2:sha256", salt_length=12)
                    if password
                    else None
                )
                updated = update_teacher_user(
                    teacher_id=teacher_id,
                    email=request.form.get("teacher_email"),
                    full_name=request.form.get("teacher_name"),
                    nrk=request.form.get("teacher_nrk"),
                    nip=request.form.get("teacher_nip"),
                    jabatan=request.form.get("teacher_jabatan"),
                    degree_prefix=request.form.get("teacher_degree_prefix"),
                    degree_suffix=request.form.get("teacher_degree_suffix"),
                    assigned_class_id=assigned_class_id,
                    password_hash=password_hash,
                )
                if not updated:
                    flash("Data staff tidak ditemukan.", "warning")
                else:
                    flash("Data staff berhasil diperbarui.", "success")
            else:
                flash("Aksi tidak dikenal.", "warning")
        except ValueError as exc:
            flash(str(exc), "danger")
        except Exception as exc:
            flash(f"Gagal menyimpan data staff: {exc}", "danger")
        return redirect(url_for("attendance.master_staff"))

    teachers = fetch_teacher_master_data()
    for teacher in teachers:
        assigned_class_id = teacher.get("assigned_class_id")
        if assigned_class_id:
            try:
                assigned_id_int = int(assigned_class_id)
            except (TypeError, ValueError):
                assigned_id_int = None
            teacher["assigned_class_id"] = assigned_id_int
            teacher["assigned_class_name"] = class_lookup.get(assigned_id_int, {}).get("name")
        else:
            teacher["assigned_class_id"] = None
            teacher["assigned_class_name"] = None

    return render_template(
        "attendance/master_data_staff.html",
        attendance_active_tab="master_staff",
        teachers=teachers,
        classes=classes,
        class_lookup=class_lookup,
    )


@attendance_bp.route("/absen/ekskul/map", methods=["GET"], endpoint="ekskul_map")
@login_required
@role_required("admin", "ekskul")
def ekskul_map() -> Response:
    raw_lat = request.args.get("lat")
    raw_lon = request.args.get("lon")
    if raw_lat is None or raw_lon is None:
        return jsonify({"error": "Lat/Lon wajib diisi."}), 400
    try:
        lat = float(raw_lat)
        lon = float(raw_lon)
    except (TypeError, ValueError):
        return jsonify({"error": "Lat/Lon tidak valid."}), 400
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return jsonify({"error": "Lat/Lon di luar rentang."}), 400

    try:
        zoom = int(request.args.get("zoom", 16))
    except (TypeError, ValueError):
        zoom = 16
    zoom = max(12, min(18, zoom))

    try:
        size = int(request.args.get("size", 200))
    except (TypeError, ValueError):
        size = 200
    size = max(120, min(320, size))

    query = urlencode(
        {
            "center": f"{lat},{lon}",
            "zoom": zoom,
            "size": f"{size}x{size}",
            "maptype": "mapnik",
            "markers": f"{lat},{lon},red-pushpin",
        }
    )
    mapbox_token = os.getenv("MAPBOX_ACCESS_TOKEN") or os.getenv("MAPBOX_TOKEN")
    if mapbox_token:
        marker = f"pin-s+ff0000({lon},{lat})"
        map_url = (
            "https://api.mapbox.com/styles/v1/mapbox/streets-v12/static/"
            f"{marker}/{lon},{lat},{zoom},0/{size}x{size}"
            f"?access_token={mapbox_token}"
        )
    else:
        map_url = f"https://staticmap.openstreetmap.de/staticmap.php?{query}"
    try:
        req = Request(map_url, headers={"User-Agent": "ASKA Attendance"})
        with urlopen(req, timeout=6) as response:
            payload = response.read()
        output = current_app.response_class(payload, mimetype="image/png")
        output.headers["Cache-Control"] = "public, max-age=300"
        return output
    except Exception as exc:
        current_app.logger.warning("Gagal mengambil peta ekskul: %s", exc)
        image = Image.new("RGB", (size, size), (232, 236, 243))
        draw = ImageDraw.Draw(image)
        step = max(18, size // 6)
        grid_color = (188, 197, 210)
        for x in range(0, size, step):
            draw.line((x, 0, x, size), fill=grid_color, width=2)
        for y in range(0, size, step):
            draw.line((0, y, size, y), fill=grid_color, width=2)
        draw.rectangle((2, 2, size - 2, size - 2), outline=(140, 150, 165), width=2)
        center = size // 2
        draw.line((center, 0, center, size), fill=(210, 60, 60), width=3)
        draw.line((0, center, size, center), fill=(210, 60, 60), width=3)
        dot_radius = max(4, size // 30)
        draw.ellipse(
            (center - dot_radius, center - dot_radius, center + dot_radius, center + dot_radius),
            fill=(220, 40, 40),
            outline=None,
        )
        label = "PETA OFFLINE"
        coords = f"{lat:.5f}, {lon:.5f}"
        draw.rectangle((4, 4, size - 4, 22), fill=(255, 255, 255))
        draw.text((8, 8), label, fill=(30, 30, 30))
        text_y = size - 28
        draw.rectangle((4, text_y - 4, size - 4, size - 4), fill=(255, 255, 255))
        draw.text((8, text_y), coords, fill=(30, 30, 30))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        output = current_app.response_class(buffer.getvalue(), mimetype="image/png")
        output.headers["Cache-Control"] = "no-store"
        output.headers["X-Map-Source"] = "offline"
        return output


@attendance_bp.route("/absen/ekskul", methods=["GET"], endpoint="ekskul_dashboard")
@login_required
@role_required("admin", "ekskul")
def ekskul_dashboard() -> str:
    user = current_user() or {}
    is_admin = user.get("role") == "admin"
    coach_user_id = None if is_admin else user.get("id")
    now = current_jakarta_time()
    today = now.date()
    overview = fetch_extracurricular_overview(include_inactive=False, coach_user_id=coach_user_id)
    activity_ids = [int(item["id"]) for item in overview if item.get("id")]
    totals_today_raw = fetch_extracurricular_attendance_totals_for_date_all(
        today,
        activity_ids=activity_ids if not is_admin else None,
    )
    totals_today = {status: int(totals_today_raw.get(status, 0)) for status in ATTENDANCE_STATUSES}

    start_date = today - timedelta(days=6)
    daily_rows = fetch_extracurricular_daily_totals(
        start_date=start_date,
        activity_ids=activity_ids if not is_admin else None,
    )
    rows_map: Dict[date, Dict[str, Any]] = {}
    for row in daily_rows:
        day_value = row.get("attendance_date")
        if isinstance(day_value, date):
            key = day_value
        else:
            try:
                key = date.fromisoformat(str(day_value))
            except Exception:
                continue
        rows_map[key] = row

    chart_labels: List[str] = []
    chart_series: Dict[str, List[int]] = {status: [] for status in ATTENDANCE_STATUSES}
    chart_zero_mask: List[bool] = []
    for offset in range(7):
        day_date = start_date + timedelta(days=offset)
        row = rows_map.get(day_date, {})
        chart_labels.append(day_date.strftime("%d/%m"))
        day_total = 0
        for status in ATTENDANCE_STATUSES:
            value = int(row.get(status) or 0)
            chart_series[status].append(value)
            day_total += value
        chart_zero_mask.append(day_total == 0)

    recent_records = fetch_extracurricular_recent_attendance(
        limit=8,
        activity_ids=activity_ids if not is_admin else None,
    )
    evidence_sessions = fetch_extracurricular_evidence_sessions(
        limit=6,
        activity_ids=activity_ids if not is_admin else None,
    )
    total_activities = len(overview)
    total_members = sum(int(item.get("total_members") or 0) for item in overview)
    active_members = sum(int(item.get("active_members") or 0) for item in overview)

    return render_template(
        "attendance/ekskul/dashboard.html",
        attendance_active_tab="ekskul_dashboard",
        overview=overview,
        totals_today=totals_today,
        total_activities=total_activities,
        total_members=total_members,
        active_members=active_members,
        chart_labels=chart_labels,
        chart_series=chart_series,
        chart_zero_totals=chart_zero_mask,
        trend_weekly_payload={
            "labels": chart_labels,
            "series": chart_series,
            "zero_mask": chart_zero_mask,
        },
        recent_records=recent_records,
        evidence_sessions=evidence_sessions,
        today_label=_format_indonesian_date(today),
        generated_at=now,
        status_labels=STATUS_LABELS,
        status_badges=STATUS_BADGES,
        landingpage_base_url=os.getenv("LANDINGPAGE_PUBLIC_URL")
        or os.getenv("LANDINGPAGE_URL")
        or "http://127.0.0.1:5003",
    )


@attendance_bp.route("/absen/ekskul/recent-detail", methods=["GET"], endpoint="ekskul_recent_detail")
@login_required
@role_required("admin", "ekskul")
def ekskul_recent_detail() -> Response:
    user = current_user()
    if not user:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    activity_id_raw = request.args.get("activity_id")
    date_raw = request.args.get("date")
    if not activity_id_raw or not date_raw:
        return jsonify({"success": False, "message": "Parameter tidak lengkap."}), 400
    try:
        activity_id = int(activity_id_raw)
        attendance_date = date.fromisoformat(date_raw)
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Parameter tidak valid."}), 400

    if user.get("role") != "admin":
        allowed = list_extracurriculars(include_inactive=True, coach_user_id=user.get("id"))
        allowed_ids = {int(item["id"]) for item in allowed if item.get("id")}
        if activity_id not in allowed_ids:
            return jsonify({"success": False, "message": "Tidak memiliki akses."}), 403

    rows = fetch_extracurricular_attendance_detail(activity_id, attendance_date)
    grouped = {status: [] for status in ATTENDANCE_STATUSES}
    for row in rows:
        status = (row.get("status") or "").strip().lower()
        if status not in grouped:
            continue
        grouped[status].append(
            {
                "name": row.get("full_name"),
                "class_name": row.get("class_name"),
            }
        )
    return jsonify({"success": True, "groups": grouped})


@attendance_bp.route("/absen/ekskul/absen", methods=["GET", "POST"], endpoint="ekskul_absen")
@login_required
@role_required("admin", "ekskul")
def ekskul_absen() -> str:
    user = current_user()
    if not user:
        return redirect(url_for("auth.login"))
    is_admin = user.get("role") == "admin"
    coach_user_id = None if is_admin else user.get("id")
    activity_options = list_extracurriculars(include_inactive=False, coach_user_id=coach_user_id)
    available_ids = {int(item["id"]) for item in activity_options}
    show_activity_picker = is_admin

    selected_date = _resolve_attendance_date(
        request.form.get("attendance_date") if request.method == "POST" else request.args.get("date")
    )
    edit_mode = (request.form.get("edit") if request.method == "POST" else request.args.get("edit")) == "1"
    selected_activity_id: Optional[int] = None
    raw_activity_id = (
        request.form.get("activity_id") if request.method == "POST" else request.args.get("activity_id")
    )
    if raw_activity_id:
        try:
            candidate_id = int(raw_activity_id)
        except (TypeError, ValueError):
            candidate_id = None
        if candidate_id in available_ids:
            selected_activity_id = candidate_id
    if not is_admin and selected_activity_id is None:
        last_activity_id = session.get("ekskul_last_activity_id")
        try:
            last_activity_id = int(last_activity_id) if last_activity_id is not None else None
        except (TypeError, ValueError):
            last_activity_id = None
        if last_activity_id in available_ids:
            selected_activity_id = last_activity_id
    if not is_admin and selected_activity_id is None and len(available_ids) == 1:
        selected_activity_id = next(iter(available_ids))
    if not is_admin and selected_activity_id is not None:
        session["ekskul_last_activity_id"] = selected_activity_id

    if request.method == "POST":
        if not selected_activity_id:
            flash("Silakan pilih ekskul terlebih dahulu.", "warning")
            return redirect(url_for("attendance.ekskul_absen"))
        existing_records = fetch_extracurricular_attendance_for_date(selected_activity_id, selected_date)
        if existing_records and not edit_mode:
            flash("Absensi hari ini sudah selesai. Gunakan tombol Edit untuk memperbarui.", "warning")
            return redirect(
                url_for(
                    "attendance.ekskul_absen",
                    activity_id=selected_activity_id,
                    date=selected_date.isoformat(),
                    edit="1",
                )
            )
        members = fetch_extracurricular_members(selected_activity_id, include_inactive=False)
        if not members:
            flash("Belum ada anggota aktif untuk ekskul ini.", "warning")
            return redirect(
                url_for(
                    "attendance.ekskul_absen",
                    activity_id=selected_activity_id,
                    date=selected_date.isoformat(),
                )
            )
        photo_data = request.form.get("photo_data") or ""
        try:
            captured_at = _parse_optional_datetime(request.form.get("photo_captured_at"))
            latitude = _parse_optional_float(request.form.get("latitude"), field_label="Latitude")
            longitude = _parse_optional_float(request.form.get("longitude"), field_label="Longitude")
            accuracy = _parse_optional_float(request.form.get("accuracy_meters"), field_label="Akurasi GPS")
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(
                url_for(
                    "attendance.ekskul_absen",
                    activity_id=selected_activity_id,
                    date=selected_date.isoformat(),
                )
            )
        address = (request.form.get("address") or "").strip() or None
        photo_path: Optional[str] = None
        if photo_data:
            old_photo_path: Optional[str] = None
            if edit_mode:
                existing_evidence = fetch_extracurricular_evidence_for_date(selected_activity_id, selected_date)
                if existing_evidence and existing_evidence.get("photo_path"):
                    old_photo_path = existing_evidence.get("photo_path")
            if latitude is None or longitude is None:
                flash("Foto bukti dengan lokasi GPS wajib diisi sebelum menyimpan.", "danger")
                return redirect(
                    url_for(
                        "attendance.ekskul_absen",
                        activity_id=selected_activity_id,
                        date=selected_date.isoformat(),
                    )
                )
            try:
                photo_path = _save_extracurricular_photo(
                    photo_data,
                    activity_id=selected_activity_id,
                    attendance_date=selected_date,
                    captured_at=captured_at,
                )
                if old_photo_path and old_photo_path != photo_path and old_photo_path.startswith("uploads/"):
                    old_path = Path(current_app.root_path) / "static" / old_photo_path
                    try:
                        if old_path.exists():
                            old_path.unlink()
                    except Exception:
                        current_app.logger.warning("Gagal menghapus foto lama ekskul: %s", old_photo_path)
            except ValueError as exc:
                flash(str(exc), "danger")
                return redirect(
                    url_for(
                        "attendance.ekskul_absen",
                        activity_id=selected_activity_id,
                        date=selected_date.isoformat(),
                    )
                )
        else:
            existing_evidence = fetch_extracurricular_evidence_for_date(selected_activity_id, selected_date)
            if edit_mode and existing_evidence and existing_evidence.get("photo_path"):
                photo_path = existing_evidence.get("photo_path")
                captured_at = existing_evidence.get("captured_at")
                latitude = existing_evidence.get("latitude")
                longitude = existing_evidence.get("longitude")
                accuracy = existing_evidence.get("accuracy_meters")
                address = existing_evidence.get("address")
            else:
                flash("Foto bukti dengan lokasi GPS wajib diisi sebelum menyimpan.", "danger")
                return redirect(
                    url_for(
                        "attendance.ekskul_absen",
                        activity_id=selected_activity_id,
                        date=selected_date.isoformat(),
                    )
                )

        entries: List[Dict[str, Any]] = []
        for member in members:
            student_id = int(member["student_id"])
            status = _normalize_status(request.form.get(f"status_{student_id}"))
            note = (request.form.get(f"note_{student_id}") or "").strip() or None
            entries.append(
                {
                    "student_id": student_id,
                    "status": status,
                    "note": note,
                }
            )
        try:
            upsert_extracurricular_attendance_entries(
                activity_id=selected_activity_id,
                recorded_by=user["id"],
                attendance_date=selected_date,
                entries=entries,
                photo_path=photo_path,
                captured_at=captured_at,
                latitude=latitude,
                longitude=longitude,
                accuracy_meters=accuracy,
                address=address,
            )
            flash("Absensi ekskul berhasil disimpan.", "success")
        except Exception as exc:
            current_app.logger.exception("Error saving extracurricular attendance")
            flash(f"Gagal menyimpan absensi ekskul: {exc}", "danger")
        return redirect(
            url_for(
                "attendance.ekskul_absen",
                activity_id=selected_activity_id,
                date=selected_date.isoformat(),
            )
        )

    selected_activity = get_extracurricular(selected_activity_id) if selected_activity_id else None
    members_view: List[Dict[str, Any]] = []
    status_counts: Dict[str, int] = {status: 0 for status in ATTENDANCE_STATUSES}
    latest_submission_at: Optional[datetime] = None
    total_members = 0
    has_existing = False
    existing_evidence: Optional[Dict[str, Any]] = None
    if selected_activity_id:
        members = fetch_extracurricular_members(selected_activity_id, include_inactive=False)
        attendance_map = fetch_extracurricular_attendance_for_date(selected_activity_id, selected_date)
        has_existing = bool(attendance_map)
        existing_evidence = fetch_extracurricular_evidence_for_date(selected_activity_id, selected_date)
        total_members = len(members)
        for member in members:
            student_id = int(member["student_id"])
            record = attendance_map.get(student_id)
            status = _normalize_status(record.get("status") if record else None)
            status_counts[status] = status_counts.get(status, 0) + 1
            submitted_at_raw = record.get("updated_at") if record else None
            if submitted_at_raw is None and record:
                submitted_at_raw = record.get("recorded_at")
            if submitted_at_raw:
                try:
                    submitted_at = to_jakarta(submitted_at_raw)
                except Exception:
                    submitted_at = submitted_at_raw
                if isinstance(submitted_at, datetime):
                    if latest_submission_at is None or submitted_at > latest_submission_at:
                        latest_submission_at = submitted_at
            members_view.append(
                {
                    "id": student_id,
                    "name": member.get("full_name"),
                    "student_number": member.get("student_number"),
                    "class_name": member.get("class_name"),
                    "status": status,
                    "note": record.get("note") if record else None,
                }
            )

    if total_members and not any(status_counts.values()):
        status_counts[DEFAULT_ATTENDANCE_STATUS] = total_members

    return render_template(
        "attendance/ekskul/absen.html",
        attendance_active_tab="ekskul_absen",
        selected_date=selected_date,
        selected_date_label=_format_indonesian_date(selected_date),
        today=current_jakarta_time(),
        activity_options=activity_options,
        show_activity_picker=show_activity_picker,
        selected_activity_id=selected_activity_id,
        selected_activity=selected_activity,
        members=members_view,
        total_members=total_members,
        status_counts=status_counts,
        latest_submission_at=latest_submission_at,
        attendance_statuses=ATTENDANCE_STATUSES,
        status_labels=STATUS_LABELS,
        has_existing=has_existing,
        edit_mode=edit_mode,
        existing_evidence=existing_evidence,
        mapbox_token=os.getenv("MAPBOX_ACCESS_TOKEN") or os.getenv("MAPBOX_TOKEN") or "",
    )


@attendance_bp.route("/absen/ekskul/anggota/search", methods=["GET"], endpoint="ekskul_member_search")
@login_required
@role_required("admin", "ekskul")
def ekskul_member_search() -> Response:
    raw_query = (request.args.get("q") or "").strip()
    raw_activity_id = request.args.get("activity_id")
    if not raw_activity_id:
        return jsonify({"items": [], "error": "activity_id wajib diisi."}), 400
    try:
        activity_id = int(raw_activity_id)
    except (TypeError, ValueError):
        return jsonify({"items": [], "error": "activity_id tidak valid."}), 400
    user = current_user() or {}
    is_admin = user.get("role") == "admin"
    if not is_admin:
        allowed = list_extracurriculars(include_inactive=True, coach_user_id=user.get("id"))
        allowed_ids = {int(item["id"]) for item in allowed}
        if activity_id not in allowed_ids:
            return jsonify({"items": [], "error": "Tidak memiliki akses."}), 403
    if len(raw_query) < 3:
        return jsonify({"items": []})
    results = search_extracurricular_students(
        activity_id=activity_id,
        query=raw_query,
        limit=12,
    )
    return jsonify({"items": results})


@attendance_bp.route("/absen/ekskul/anggota", methods=["GET", "POST"], endpoint="ekskul_members")
@login_required
@role_required("admin", "ekskul")
def ekskul_members() -> str:
    user = current_user() or {}
    is_admin = user.get("role") == "admin"
    coach_user_id = None if is_admin else user.get("id")
    activities = list_extracurriculars(include_inactive=True, coach_user_id=coach_user_id)
    available_ids = {int(item["id"]) for item in activities}
    show_activity_picker = is_admin

    raw_activity_id = request.form.get("activity_id") if request.method == "POST" else request.args.get("activity_id")
    selected_activity_id: Optional[int] = None
    if raw_activity_id:
        try:
            candidate_id = int(raw_activity_id)
        except (TypeError, ValueError):
            candidate_id = None
        if candidate_id in available_ids:
            selected_activity_id = candidate_id
    if not is_admin and selected_activity_id is None:
        last_activity_id = session.get("ekskul_last_activity_id")
        try:
            last_activity_id = int(last_activity_id) if last_activity_id is not None else None
        except (TypeError, ValueError):
            last_activity_id = None
        if last_activity_id in available_ids:
            selected_activity_id = last_activity_id
    if not is_admin and selected_activity_id is None and len(available_ids) == 1:
        selected_activity_id = next(iter(available_ids))
    if not is_admin and selected_activity_id is not None:
        session["ekskul_last_activity_id"] = selected_activity_id

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        try:
            if not selected_activity_id:
                raise ValueError("Anda tidak memiliki akses ke ekskul ini.")
            if action == "add_members":
                student_ids = request.form.getlist("student_ids")
                if not student_ids:
                    raise ValueError("Pilih minimal satu siswa untuk ditambahkan.")
                joined_at = _parse_optional_date(request.form.get("member_joined_at"))
                role = (request.form.get("member_role") or "").strip() or None
                note = (request.form.get("member_note") or "").strip() or None
                upsert_extracurricular_members(
                    activity_id=selected_activity_id,
                    student_ids=student_ids,
                    role=role,
                    joined_at=joined_at,
                    note=note,
                    active=True,
                )
                flash("Anggota ekskul berhasil ditambahkan.", "success")
            elif action == "quick_add_member":
                raw_student_id = request.form.get("student_id")
                if not raw_student_id:
                    raise ValueError("ID siswa tidak ditemukan.")
                upsert_extracurricular_members(
                    activity_id=selected_activity_id,
                    student_ids=[raw_student_id],
                    active=True,
                )
                flash("Anggota ekskul berhasil ditambahkan.", "success")
            elif action == "update_member":
                raw_member_id = request.form.get("member_id")
                if not raw_member_id:
                    raise ValueError("ID anggota tidak ditemukan.")
                try:
                    member_id = int(raw_member_id)
                except (TypeError, ValueError) as exc:
                    raise ValueError("ID anggota tidak valid.") from exc
                role = (request.form.get("member_role") or "").strip() or None
                note = (request.form.get("member_note") or "").strip() or None
                joined_at = _parse_optional_date(request.form.get("member_joined_at"))
                updated = update_extracurricular_member(
                    member_id=member_id,
                    activity_id=selected_activity_id,
                    role=role,
                    joined_at=joined_at,
                    note=note,
                )
                if updated:
                    flash("Data anggota berhasil diperbarui.", "success")
                else:
                    flash("Data anggota tidak ditemukan.", "warning")
            elif action == "toggle_member":
                raw_member_id = request.form.get("member_id")
                if not raw_member_id:
                    raise ValueError("ID anggota tidak ditemukan.")
                try:
                    member_id = int(raw_member_id)
                except (TypeError, ValueError) as exc:
                    raise ValueError("ID anggota tidak valid.") from exc
                active_value = request.form.get("member_active") == "1"
                updated = set_extracurricular_member_active(
                    member_id,
                    active_value,
                    activity_id=selected_activity_id,
                )
                if updated:
                    flash("Status anggota diperbarui.", "success")
                else:
                    flash("Data anggota tidak ditemukan.", "warning")
            elif action == "delete_member":
                raw_member_id = request.form.get("member_id")
                if not raw_member_id:
                    raise ValueError("ID anggota tidak ditemukan.")
                try:
                    member_id = int(raw_member_id)
                except (TypeError, ValueError) as exc:
                    raise ValueError("ID anggota tidak valid.") from exc
                deleted = delete_extracurricular_member(
                    member_id=member_id,
                    activity_id=selected_activity_id,
                )
                if deleted:
                    flash("Anggota berhasil dihapus permanen.", "success")
                else:
                    flash("Data anggota tidak ditemukan.", "warning")
            elif action in {"bulk_activate", "bulk_deactivate", "bulk_delete"}:
                member_ids = request.form.getlist("member_ids")
                if not member_ids:
                    raise ValueError("Pilih minimal satu anggota.")
                if action == "bulk_delete":
                    deleted = delete_extracurricular_members(
                        member_ids=member_ids,
                        activity_id=selected_activity_id,
                    )
                    flash(f"{deleted} anggota berhasil dihapus permanen.", "success")
                else:
                    active_value = action == "bulk_activate"
                    updated = set_extracurricular_members_active(
                        member_ids=member_ids,
                        activity_id=selected_activity_id,
                        active=active_value,
                    )
                    flash(f"{updated} anggota berhasil diperbarui.", "success")
            else:
                flash("Aksi tidak dikenal.", "warning")
        except ValueError as exc:
            flash(str(exc), "danger")
        except Exception as exc:
            current_app.logger.exception("Error updating extracurricular members")
            flash(f"Gagal memperbarui anggota: {exc}", "danger")

        class_id = request.form.get("class_id")
        return redirect(
            url_for(
                "attendance.ekskul_members",
                activity_id=selected_activity_id,
                class_id=class_id or None,
            )
        )

    selected_activity = get_extracurricular(selected_activity_id) if selected_activity_id else None
    members = fetch_extracurricular_members(selected_activity_id, include_inactive=True) if selected_activity_id else []
    active_member_count = sum(1 for member in members if member.get("member_active"))
    total_member_count = len(members)
    member_student_ids = {int(member["student_id"]) for member in members}
    member_student_ids_list = sorted(member_student_ids)

    class_options = []
    students: List[Dict[str, Any]] = []
    return render_template(
        "attendance/ekskul/members.html",
        attendance_active_tab="ekskul_members",
        activities=activities,
        show_activity_picker=show_activity_picker,
        selected_activity_id=selected_activity_id,
        selected_activity=selected_activity,
        members=members,
        active_member_count=active_member_count,
        total_member_count=total_member_count,
        member_student_ids=member_student_ids_list,
        class_options=class_options,
        selected_class_id=None,
        students=students,
    )


@attendance_bp.route("/absen/ekskul/master", methods=["GET", "POST"], endpoint="ekskul_master")
@login_required
@role_required("admin")
def ekskul_master() -> str:
    user = current_user()
    if request.method == "POST":
        coach_lookup = {coach["id"]: coach["full_name"] for coach in fetch_extracurricular_coaches()}
        action = (request.form.get("action") or "").strip()
        try:
            if action == "create":
                coach_user_id = _parse_optional_int(request.form.get("coach_user_id"), field_label="Pembina")
                if coach_user_id is None:
                    raise ValueError("Pembina ekskul wajib dipilih.")
                coach_name = coach_lookup.get(coach_user_id)
                create_extracurricular(
                    name=request.form.get("name") or "",
                    coach_name=coach_name,
                    coach_user_id=coach_user_id,
                    schedule_day=None,
                    start_time=None,
                    end_time=None,
                    location=None,
                    capacity=None,
                    description=None,
                    created_by=(user or {}).get("id"),
                )
                flash("Ekskul baru berhasil ditambahkan.", "success")
            elif action == "update":
                raw_activity_id = request.form.get("activity_id")
                if not raw_activity_id:
                    raise ValueError("ID ekskul tidak ditemukan.")
                try:
                    activity_id = int(raw_activity_id)
                except (TypeError, ValueError) as exc:
                    raise ValueError("ID ekskul tidak valid.") from exc
                coach_user_id = _parse_optional_int(request.form.get("coach_user_id"), field_label="Pembina")
                if coach_user_id is None:
                    raise ValueError("Pembina ekskul wajib dipilih.")
                coach_name = coach_lookup.get(coach_user_id)
                current_activity = get_extracurricular(activity_id)
                if not current_activity:
                    raise ValueError("Ekskul tidak ditemukan.")
                update_extracurricular(
                    activity_id=activity_id,
                    name=request.form.get("name") or "",
                    coach_name=coach_name,
                    coach_user_id=coach_user_id,
                    schedule_day=current_activity.get("schedule_day"),
                    start_time=current_activity.get("start_time"),
                    end_time=current_activity.get("end_time"),
                    location=current_activity.get("location"),
                    capacity=current_activity.get("capacity"),
                    description=current_activity.get("description"),
                    updated_by=(user or {}).get("id"),
                )
                flash("Ekskul berhasil diperbarui.", "success")
            elif action == "toggle":
                raw_activity_id = request.form.get("activity_id")
                if not raw_activity_id:
                    raise ValueError("ID ekskul tidak ditemukan.")
                try:
                    activity_id = int(raw_activity_id)
                except (TypeError, ValueError) as exc:
                    raise ValueError("ID ekskul tidak valid.") from exc
                active_value = request.form.get("active") == "1"
                updated = set_extracurricular_active(activity_id, active_value, (user or {}).get("id"))
                if updated:
                    flash("Status ekskul diperbarui.", "success")
                else:
                    flash("Ekskul tidak ditemukan.", "warning")
            else:
                flash("Aksi tidak dikenal.", "warning")
        except ValueError as exc:
            flash(str(exc), "danger")
        except Exception as exc:
            current_app.logger.exception("Error updating extracurricular master data")
            flash(f"Gagal memproses data ekskul: {exc}", "danger")
        return redirect(url_for("attendance.ekskul_master"))

    activities = fetch_extracurricular_overview(include_inactive=True)
    coaches = fetch_extracurricular_coaches()
    site_key = (os.getenv("LANDINGPAGE_SITE_KEY") or "default").strip().lower()
    try:
        lp_content = fetch_landingpage_content(site_key=site_key)
    except Exception:
        lp_content = {}
    lp_items = []
    if isinstance(lp_content, dict):
        lp_items = lp_content.get("extracurricular", {}).get("items", []) or []

    existing_names = {str(activity.get("name")).strip().lower() for activity in activities if activity.get("name")}
    seeded = False
    for item in lp_items:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or item.get("name") or "").strip()
        if not title:
            continue
        title_key = title.lower()
        if title_key in existing_names:
            continue
        description = (item.get("description") or "").strip() or None
        image = (item.get("image") or "").strip() or None
        metadata = {"lp_main_photo": image} if image else None
        try:
            create_extracurricular(
                name=title,
                coach_name=None,
                coach_user_id=None,
                schedule_day=None,
                start_time=None,
                end_time=None,
                location=None,
                capacity=None,
                description=description,
                metadata=metadata,
                created_by=(user or {}).get("id"),
            )
            seeded = True
            existing_names.add(title_key)
        except Exception:
            continue
    if seeded:
        activities = fetch_extracurricular_overview(include_inactive=True)

    lp_names: List[str] = []
    for item in lp_items:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("name")
        if isinstance(title, str) and title.strip():
            lp_names.append(title.strip())
    activity_names = [activity.get("name") for activity in activities if activity.get("name")]
    name_choices = sorted({*lp_names, *activity_names}, key=lambda value: value.lower())
    return render_template(
        "attendance/ekskul/master.html",
        attendance_active_tab="ekskul_master",
        activities=activities,
        coaches=coaches,
        name_choices=name_choices,
    )


@attendance_bp.route("/absen/ekskul/konfigurasi", methods=["GET", "POST"], endpoint="ekskul_config")
@login_required
@role_required("admin", "ekskul")
def ekskul_config() -> str:
    user = current_user() or {}
    is_admin = user.get("role") == "admin"
    coach_user_id = None if is_admin else user.get("id")

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        if action != "update":
            flash("Aksi tidak dikenal.", "warning")
            return redirect(url_for("attendance.ekskul_config"))

        raw_activity_id = request.form.get("activity_id")
        if not raw_activity_id:
            flash("ID ekskul tidak ditemukan.", "warning")
            return redirect(url_for("attendance.ekskul_config"))
        try:
            activity_id = int(raw_activity_id)
        except (TypeError, ValueError):
            flash("ID ekskul tidak valid.", "warning")
            return redirect(url_for("attendance.ekskul_config"))

        allowed = list_extracurriculars(include_inactive=True, coach_user_id=coach_user_id)
        allowed_ids = {int(item["id"]) for item in allowed if item.get("id")}
        if activity_id not in allowed_ids:
            flash("Anda tidak memiliki akses untuk mengubah ekskul ini.", "danger")
            return redirect(url_for("attendance.ekskul_config"))

        current_activity = get_extracurricular(activity_id)
        if not current_activity:
            flash("Ekskul tidak ditemukan.", "warning")
            return redirect(url_for("attendance.ekskul_config"))

        try:
            schedule_day = (request.form.get("schedule_day") or "").strip() or None
            if not schedule_day:
                raise ValueError("Hari wajib dipilih minimal 1.")
            photo_order_raw = (request.form.get("lp_photo_order") or "").strip()
            photo_order: List[str] = []
            if photo_order_raw:
                try:
                    parsed = json.loads(photo_order_raw)
                    if isinstance(parsed, list):
                        photo_order = [str(item) for item in parsed if item]
                except json.JSONDecodeError:
                    photo_order = [item.strip() for item in photo_order_raw.split(",") if item.strip()]
            available_paths: set[str] = set()

            metadata = current_activity.get("metadata") or {}
            if not isinstance(metadata, dict):
                metadata = {}
            existing_main = metadata.get("lp_main_photo")
            if not isinstance(existing_main, str):
                existing_main = None
            existing_gallery = metadata.get("lp_gallery_photos")
            if not isinstance(existing_gallery, list):
                existing_gallery = []

            stored_uploads = metadata.get("lp_uploaded_photos")
            if not isinstance(stored_uploads, list):
                stored_uploads = []

            delete_paths = [
                value
                for value in request.form.getlist("lp_delete_photos")
                if value and value in stored_uploads
            ]
            if delete_paths:
                stored_uploads = [path for path in stored_uploads if path not in delete_paths]
                existing_gallery = [path for path in existing_gallery if path not in delete_paths]
                if existing_main in delete_paths:
                    existing_main = None
                static_root = Path(current_app.root_path) / "static"
                for path in delete_paths:
                    file_path = static_root / path
                    try:
                        if file_path.exists():
                            file_path.unlink()
                    except Exception:
                        current_app.logger.warning("Gagal menghapus foto LP %s", path)

            uploaded_paths = []
            for file_item in request.files.getlist("lp_uploads"):
                if not file_item or not getattr(file_item, "filename", None):
                    continue
                try:
                    uploaded_paths.append(_save_extracurricular_lp_photo(file_item, activity_id=activity_id))
                except ValueError as exc:
                    flash(str(exc), "warning")

            if uploaded_paths:
                stored_uploads = list(dict.fromkeys(stored_uploads + uploaded_paths))

            if stored_uploads:
                metadata["lp_uploaded_photos"] = stored_uploads
            else:
                metadata.pop("lp_uploaded_photos", None)

            for path in stored_uploads + uploaded_paths:
                if path:
                    available_paths.add(path)

            if not available_paths:
                raise ValueError("Unggah minimal 1 foto untuk landing page.")

            ordered_paths: List[str] = []
            legacy_paths: List[str] = []
            if existing_main:
                legacy_paths.append(existing_main)
            if isinstance(existing_gallery, list):
                legacy_paths.extend(existing_gallery)
            for path in photo_order + legacy_paths + uploaded_paths + stored_uploads:
                if not path:
                    continue
                if path not in available_paths:
                    continue
                if path not in ordered_paths:
                    ordered_paths.append(path)

            lp_main_photo = ordered_paths[0] if ordered_paths else None
            if not lp_main_photo and existing_main in available_paths:
                lp_main_photo = existing_main
            if not lp_main_photo and uploaded_paths:
                lp_main_photo = uploaded_paths[0]
            if not lp_main_photo:
                raise ValueError("Foto utama landing page wajib diunggah.")

            gallery: List[str] = []
            for photo in ordered_paths:
                if photo == lp_main_photo:
                    continue
                if photo not in gallery:
                    gallery.append(photo)
                if len(gallery) >= 10:
                    break
            if len(gallery) < 5 and len(available_paths) >= 6:
                raise ValueError("Minimal pilih 5 foto galeri tambahan.")
            if len(gallery) < 5:
                flash("Tambahkan minimal 5 foto galeri tambahan agar tampil optimal.", "warning")

            metadata["lp_main_photo"] = lp_main_photo
            metadata["lp_gallery_photos"] = gallery
            update_extracurricular(
                activity_id=activity_id,
                name=(request.form.get("name") or "").strip() or (current_activity.get("name") or ""),
                coach_name=current_activity.get("coach_name"),
                coach_user_id=current_activity.get("coach_user_id"),
                schedule_day=schedule_day,
                start_time=(request.form.get("start_time") or "").strip() or None,
                end_time=(request.form.get("end_time") or "").strip() or None,
                location=current_activity.get("location"),
                capacity=current_activity.get("capacity"),
                description=(request.form.get("description") or "").strip() or None,
                active=bool(current_activity.get("active")),
                metadata=metadata,
                updated_by=user.get("id"),
            )
            flash("Konfigurasi ekskul berhasil disimpan.", "success")
        except Exception as exc:
            current_app.logger.exception("Error updating extracurricular config")
            flash(f"Gagal menyimpan konfigurasi: {exc}", "danger")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            activities = list_extracurriculars(include_inactive=True, coach_user_id=coach_user_id)
            for activity in activities:
                metadata = activity.get("metadata") or {}
                if not isinstance(metadata, dict):
                    metadata = {}
                activity["metadata"] = metadata
                activity["lp_main_photo"] = metadata.get("lp_main_photo")
                gallery = metadata.get("lp_gallery_photos") or []
                activity["lp_gallery_photos"] = gallery if isinstance(gallery, list) else []
                uploaded_photos = metadata.get("lp_uploaded_photos") or []
                activity["lp_uploaded_photos"] = uploaded_photos if isinstance(uploaded_photos, list) else []
                photo_order: List[str] = []
                for path in [activity.get("lp_main_photo")] + (activity.get("lp_gallery_photos") or []):
                    if path and path in uploaded_photos and path not in photo_order:
                        photo_order.append(path)
                for path in uploaded_photos:
                    if path and path not in photo_order:
                        photo_order.append(path)
                activity["photo_options"] = [
                    {"photo_path": path, "is_uploaded": True} for path in photo_order
                ]
            day_options = [
                INDONESIAN_DAY_NAMES.get(i, name)
                for i, name in enumerate(["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"])
            ]
            landingpage_base_url = os.getenv("LANDINGPAGE_PUBLIC_URL") or os.getenv("LANDINGPAGE_URL") or "http://127.0.0.1:5003"
            return jsonify(
                {
                    "success": True,
                    "activity_id": activity_id,
                    "form_html": render_template(
                        "attendance/ekskul/config_form.html",
                        activity=next((a for a in activities if a.get("id") == activity_id), None),
                        day_options=day_options,
                        landingpage_base_url=landingpage_base_url,
                    ),
                }
            )
        return redirect(url_for("attendance.ekskul_dashboard"))

    activities = list_extracurriculars(include_inactive=True, coach_user_id=coach_user_id)
    for activity in activities:
        metadata = activity.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        activity["metadata"] = metadata
        activity["lp_main_photo"] = metadata.get("lp_main_photo")
        gallery = metadata.get("lp_gallery_photos") or []
        activity["lp_gallery_photos"] = gallery if isinstance(gallery, list) else []
        uploaded_photos = metadata.get("lp_uploaded_photos") or []
        activity["lp_uploaded_photos"] = uploaded_photos if isinstance(uploaded_photos, list) else []
        photo_order: List[str] = []
        for path in [activity.get("lp_main_photo")] + (activity.get("lp_gallery_photos") or []):
            if path and path in uploaded_photos and path not in photo_order:
                photo_order.append(path)
        for path in uploaded_photos:
            if path and path not in photo_order:
                photo_order.append(path)
        activity["photo_options"] = [
            {"photo_path": path, "is_uploaded": True} for path in photo_order
        ]
    day_options = [
        INDONESIAN_DAY_NAMES.get(i, name)
        for i, name in enumerate(["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"])
    ]
    landingpage_base_url = os.getenv("LANDINGPAGE_PUBLIC_URL") or os.getenv("LANDINGPAGE_URL") or "http://127.0.0.1:5003"

    return render_template(
        "attendance/ekskul/config.html",
        attendance_active_tab="ekskul_config",
        activities=activities,
        day_options=day_options,
        landingpage_base_url=landingpage_base_url,
    )
