from __future__ import annotations

from datetime import date, datetime
import calendar
from typing import Any, Dict, List, Optional, Tuple

from flask import current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash

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
    fetch_monthly_attendance_overview,
    fetch_class_month_attendance_entries,
    fetch_recent_attendance,
    fetch_school_identity,
    fetch_students_for_class,
    fetch_teacher_absence_for_date,
    fetch_teacher_assigned_class,
    fetch_teacher_attendance_for_date,
    fetch_teacher_master_data,
    get_school_class,
    list_attendance_months,
    list_school_classes,
    update_student_record,
    update_teacher_assigned_class,
    update_teacher_user,
    upsert_attendance_entries,
    upsert_teacher_attendance_entries,
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


@attendance_bp.route("/absen/laporan-harian", methods=["GET"])
@login_required
@role_required("staff", "admin")
def laporan_harian() -> str:
    user = current_user()
    if not user:
        return redirect(url_for("auth.login"))

    selected_date = _resolve_attendance_date(request.args.get("date"))
    selected_date_label = _format_indonesian_date(selected_date)

    month_reference = _resolve_month_reference(request.args.get("month"), selected_date)

    class_rows = fetch_class_attendance_breakdown(selected_date)
    teacher_absences = fetch_teacher_absence_for_date(selected_date)
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
        status_labels=STATUS_LABELS,
        default_academic_year=default_academic_year,
        today=current_jakarta_time(),
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
        flash(str(exc), "danger")
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
