from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from flask import (
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from utils import (
    INDONESIAN_DAY_NAMES,
    INDONESIAN_MONTH_NAMES,
    current_jakarta_time,
    to_jakarta,
)

from ..auth import current_user, login_required, role_required
from . import attendance_bp
from .queries import (
    ATTENDANCE_STATUSES,
    DEFAULT_ATTENDANCE_STATUS,
    create_school_class,
    create_student,
    fetch_attendance_for_date,
    fetch_attendance_totals_for_date,
    fetch_daily_attendance,
    fetch_all_students,
    fetch_master_data_overview,
    fetch_recent_attendance,
    fetch_students_for_class,
    fetch_teacher_assigned_class,
    get_school_class,
    list_school_classes,
    update_teacher_assigned_class,
    upsert_attendance_entries,
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


@attendance_bp.route("/absen", methods=["GET"])
@login_required
@role_required("guru", "admin")
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
        chart_masuk.append(int(row.get("masuk") or 0))
        chart_alpa.append(int(row.get("alpa") or 0))
        chart_izin.append(int(row.get("izin") or 0))
        chart_sakit.append(int(row.get("sakit") or 0))

    recent_records = fetch_recent_attendance(limit=8)

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
        daily_rows=daily_rows,
        recent_records=recent_records,
        generated_at=now,
        today_label=_format_indonesian_date(today),
        status_labels=STATUS_LABELS,
        status_badges=STATUS_BADGES,
    )


@attendance_bp.route("/absen/kelas", methods=["GET"], endpoint="kelas")
@login_required
@role_required("guru", "admin")
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


@attendance_bp.route("/absen/pilih-kelas", methods=["POST"])
@login_required
@role_required("guru", "admin")
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
@role_required("guru", "admin")
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
@role_required("guru", "admin")
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
                raw_class_id = request.form.get("student_class_id")
                full_name = request.form.get("student_name")
                student_number = request.form.get("student_number")
                if not raw_class_id:
                    raise ValueError("Silakan pilih kelas untuk siswa baru.")
                class_id = int(raw_class_id)
                create_student(
                    class_id,
                    full_name or "",
                    student_number=student_number,
                    nisn=request.form.get("student_nisn"),
                    gender=request.form.get("student_gender"),
                    birth_place=request.form.get("student_birth_place"),
                    birth_date=_parse_birth_date(request.form.get("student_birth_date")),
                    religion=request.form.get("student_religion"),
                    address_line=request.form.get("student_address"),
                    rt=request.form.get("student_rt"),
                    rw=request.form.get("student_rw"),
                    kelurahan=request.form.get("student_kelurahan"),
                    kecamatan=request.form.get("student_kecamatan"),
                    father_name=request.form.get("student_father"),
                    mother_name=request.form.get("student_mother"),
                    nik=request.form.get("student_nik"),
                    kk_number=request.form.get("student_kk"),
                )
                flash("Data siswa berhasil disimpan.", "success")
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
        attendance_active_tab="master",
        classes=classes,
        students_by_class=students_by_class,
        class_lookup=class_lookup,
    )
