from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import Any, Dict, Optional

from flask import Response, flash, redirect, render_template, request, url_for

from utils import current_jakarta_time

from ..auth import current_user, login_required, role_required
from . import student_points_bp
from .queries import (
    create_point_record,
    create_threshold,
    create_violation_category,
    create_violation_type,
    fetch_overview,
    fetch_records,
    fetch_student_summaries,
    fetch_student_total,
    get_student,
    get_violation_type,
    list_classes,
    list_students,
    list_thresholds,
    list_violation_categories,
    list_violation_types,
    update_threshold,
    update_violation_category,
    update_violation_type,
    void_point_record,
)

_ALLOWED_COLORS = {"primary", "secondary", "success", "danger", "warning", "info", "dark"}


def _optional_int(value: Optional[str], label: str) -> Optional[int]:
    if value is None or not str(value).strip():
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} tidak valid.") from exc


def _required_int(value: Optional[str], label: str, *, minimum: Optional[int] = None) -> int:
    parsed = _optional_int(value, label)
    if parsed is None:
        raise ValueError(f"{label} wajib diisi.")
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{label} minimal {minimum}.")
    return parsed


def _optional_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Format tanggal tidak valid.") from exc


def _occurred_at(value: Optional[str]) -> datetime:
    if not value:
        return current_jakarta_time()
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Tanggal dan waktu kejadian tidak valid.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=current_jakarta_time().tzinfo)
    if parsed > current_jakarta_time():
        raise ValueError("Waktu kejadian tidak boleh berada di masa depan.")
    return parsed


def _clean_code(value: Optional[str]) -> str:
    code = re.sub(r"[^A-Z0-9]+", "_", (value or "").strip().upper()).strip("_")
    if not code:
        raise ValueError("Kode pelanggaran wajib diisi.")
    return code


def _text(value: Optional[str], *, required: bool = False, label: str = "Data") -> Optional[str]:
    cleaned = (value or "").strip()
    if required and not cleaned:
        raise ValueError(f"{label} wajib diisi.")
    return cleaned or None


def _common_context() -> Dict[str, Any]:
    violation_types = list_violation_types()
    return {
        "classes": list_classes(),
        "students": list_students(),
        "violation_types": violation_types,
        "categories": sorted({item["category"] for item in violation_types}),
    }


@student_points_bp.route("/", methods=["GET"])
@login_required
@role_required("admin", "staff")
def index() -> str:
    try:
        class_id = _optional_int(request.args.get("class_id"), "Kelas")
        student_id = _optional_int(request.args.get("student_id"), "Siswa")
        start_date = _optional_date(request.args.get("start_date"))
        end_date = _optional_date(request.args.get("end_date"))
    except ValueError as exc:
        flash(str(exc), "warning")
        class_id = student_id = None
        start_date = end_date = None

    category = (request.args.get("category") or "").strip() or None
    status = (request.args.get("status") or "active").strip()
    search = (request.args.get("q") or "").strip() or None
    context = _common_context()
    records = fetch_records(
        student_id=student_id,
        class_id=class_id,
        category=category,
        status=status,
        start_date=start_date,
        end_date=end_date,
        limit=250,
    )
    summaries = fetch_student_summaries(
        class_id=class_id, search=search, include_zero=bool(search), limit=100
    )
    return render_template(
        "student_points/index.html",
        attendance_active_tab="student_points",
        overview=fetch_overview(),
        records=records,
        summaries=summaries,
        now_local=current_jakarta_time(),
        filters={
            "class_id": class_id,
            "student_id": student_id,
            "category": category,
            "status": status,
            "start_date": start_date,
            "end_date": end_date,
            "q": search or "",
        },
        **context,
    )


@student_points_bp.route("/catat", methods=["POST"])
@login_required
@role_required("admin", "staff")
def record() -> Response:
    try:
        student_id = _required_int(request.form.get("student_id"), "Siswa", minimum=1)
        violation_type_id = _required_int(
            request.form.get("violation_type_id"), "Jenis pelanggaran", minimum=1
        )
        student = get_student(student_id)
        violation = get_violation_type(violation_type_id)
        if not student:
            raise ValueError("Siswa tidak ditemukan.")
        if not violation or not violation.get("active"):
            raise ValueError("Jenis pelanggaran tidak ditemukan atau sedang nonaktif.")
        create_point_record(
            student_id=student_id,
            violation=violation,
            occurred_at=_occurred_at(request.form.get("occurred_at")),
            location=_text(request.form.get("location")),
            note=_text(request.form.get("note")),
            action_taken=_text(request.form.get("action_taken")),
            parent_notified=request.form.get("parent_notified") == "on",
            recorded_by=(current_user() or {}).get("id"),
        )
        flash(
            f"Pelanggaran {student['full_name']} berhasil dicatat (+{violation['points']} poin).",
            "success",
        )
    except ValueError as exc:
        flash(str(exc), "danger")
    except Exception as exc:
        flash(f"Gagal mencatat pelanggaran: {exc}", "danger")
    return redirect(url_for("student_points.index"))


@student_points_bp.route("/catatan/<int:record_id>/batalkan", methods=["POST"])
@login_required
@role_required("admin", "staff")
def void_record(record_id: int) -> Response:
    try:
        reason = _text(request.form.get("reason"), required=True, label="Alasan pembatalan")
        updated = void_point_record(
            record_id,
            reason=reason or "",
            user_id=(current_user() or {}).get("id"),
        )
        flash(
            "Catatan berhasil dibatalkan dan tidak lagi dihitung."
            if updated else "Catatan tidak ditemukan atau sudah dibatalkan.",
            "success" if updated else "warning",
        )
    except ValueError as exc:
        flash(str(exc), "danger")
    except Exception as exc:
        flash(f"Gagal membatalkan catatan: {exc}", "danger")
    next_url = request.form.get("next") or url_for("student_points.index")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = url_for("student_points.index")
    return redirect(next_url)


@student_points_bp.route("/siswa/<int:student_id>", methods=["GET"])
@login_required
@role_required("admin", "staff")
def student_detail(student_id: int) -> Response:
    student = get_student(student_id)
    if not student:
        flash("Siswa tidak ditemukan.", "warning")
        return redirect(url_for("student_points.index"))
    return render_template(
        "student_points/student_detail.html",
        attendance_active_tab="student_points",
        student=student,
        total=fetch_student_total(student_id),
        records=fetch_records(student_id=student_id, limit=1000),
    )


@student_points_bp.route("/konfigurasi", methods=["GET"])
@login_required
@role_required("admin", "staff")
def config() -> str:
    violation_types = list_violation_types(include_inactive=True)
    category_records = list_violation_categories(include_inactive=True)
    return render_template(
        "student_points/config.html",
        attendance_active_tab="student_points_config",
        violation_types=violation_types,
        category_records=category_records,
        categories=[item["name"] for item in category_records],
        active_categories=[item["name"] for item in category_records if item["active"]],
        thresholds=list_thresholds(include_inactive=True),
        allowed_colors=sorted(_ALLOWED_COLORS),
    )


@student_points_bp.route("/konfigurasi/pelanggaran", methods=["POST"])
@login_required
@role_required("admin", "staff")
def save_violation_type() -> Response:
    action = (request.form.get("action") or "create").strip()
    try:
        category = _text(request.form.get("category"), required=True, label="Kategori") or ""
        active_categories = {item["name"] for item in list_violation_categories()}
        current_violation = None
        if action == "update":
            current_id = _required_int(request.form.get("id"), "ID pelanggaran", minimum=1)
            current_violation = get_violation_type(current_id)
        category_allowed = category in active_categories or (
            current_violation and current_violation.get("category") == category
        )
        if not category_allowed:
            raise ValueError("Kategori tidak terdaftar. Pilih kategori dari daftar yang tersedia.")
        payload = {
            "code": _clean_code(request.form.get("code")),
            "name": _text(request.form.get("name"), required=True, label="Nama pelanggaran") or "",
            "category": category,
            "points": _required_int(request.form.get("points"), "Poin", minimum=1),
            "description": _text(request.form.get("description")),
            "recommended_action": _text(request.form.get("recommended_action")),
            "sort_order": _required_int(request.form.get("sort_order") or "0", "Urutan", minimum=0),
            "user_id": (current_user() or {}).get("id"),
        }
        if action == "update":
            violation_type_id = current_id
            updated = update_violation_type(
                violation_type_id,
                active=request.form.get("active") == "on",
                **payload,
            )
            if not updated:
                raise ValueError("Jenis pelanggaran tidak ditemukan.")
            flash("Konfigurasi pelanggaran berhasil diperbarui.", "success")
        else:
            create_violation_type(**payload)
            flash("Jenis pelanggaran baru berhasil ditambahkan.", "success")
    except ValueError as exc:
        flash(str(exc), "danger")
    except Exception as exc:
        flash(f"Gagal menyimpan jenis pelanggaran. Pastikan kode belum digunakan. ({exc})", "danger")
    return redirect(url_for("student_points.config"))


@student_points_bp.route("/konfigurasi/kategori", methods=["POST"])
@login_required
@role_required("admin", "staff")
def save_category() -> Response:
    action = (request.form.get("action") or "create").strip()
    try:
        payload = {
            "name": _text(request.form.get("name"), required=True, label="Nama kategori") or "",
            "description": _text(request.form.get("description")),
            "sort_order": _required_int(request.form.get("sort_order") or "0", "Urutan", minimum=0),
            "user_id": (current_user() or {}).get("id"),
        }
        if action == "update":
            category_id = _required_int(request.form.get("id"), "ID kategori", minimum=1)
            updated = update_violation_category(
                category_id,
                active=request.form.get("active") == "on",
                **payload,
            )
            if not updated:
                raise ValueError("Kategori tidak ditemukan.")
            flash("Kategori berhasil diperbarui.", "success")
        else:
            create_violation_category(**payload)
            flash("Kategori baru berhasil ditambahkan.", "success")
    except ValueError as exc:
        flash(str(exc), "danger")
    except Exception as exc:
        flash(f"Gagal menyimpan kategori. Pastikan namanya belum digunakan. ({exc})", "danger")
    return redirect(url_for("student_points.config"))


@student_points_bp.route("/konfigurasi/level", methods=["POST"])
@login_required
@role_required("admin", "staff")
def save_threshold() -> Response:
    action = (request.form.get("action") or "create").strip()
    try:
        color = (request.form.get("color") or "secondary").strip()
        if color not in _ALLOWED_COLORS:
            raise ValueError("Warna level tidak valid.")
        payload = {
            "min_points": _required_int(request.form.get("min_points"), "Batas poin", minimum=0),
            "label": _text(request.form.get("label"), required=True, label="Nama level") or "",
            "color": color,
            "recommended_action": _text(request.form.get("recommended_action")),
            "user_id": (current_user() or {}).get("id"),
        }
        if action == "update":
            threshold_id = _required_int(request.form.get("id"), "ID level", minimum=1)
            updated = update_threshold(
                threshold_id,
                active=request.form.get("active") == "on",
                **payload,
            )
            if not updated:
                raise ValueError("Level tindak lanjut tidak ditemukan.")
            flash("Level tindak lanjut berhasil diperbarui.", "success")
        else:
            create_threshold(**payload)
            flash("Level tindak lanjut baru berhasil ditambahkan.", "success")
    except ValueError as exc:
        flash(str(exc), "danger")
    except Exception as exc:
        flash(f"Gagal menyimpan level. Pastikan batas poin belum digunakan. ({exc})", "danger")
    return redirect(url_for("student_points.config"))


@student_points_bp.route("/export.csv", methods=["GET"])
@login_required
@role_required("admin", "staff")
def export_csv() -> Response:
    try:
        records = fetch_records(
            class_id=_optional_int(request.args.get("class_id"), "Kelas"),
            category=(request.args.get("category") or "").strip() or None,
            status=(request.args.get("status") or "active").strip(),
            start_date=_optional_date(request.args.get("start_date")),
            end_date=_optional_date(request.args.get("end_date")),
            limit=10000,
        )
    except ValueError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("student_points.index"))

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Tanggal", "Waktu", "Nama Siswa", "Kelas", "NIS/NISN", "Kategori",
        "Pelanggaran", "Poin", "Lokasi", "Catatan", "Tindak Lanjut",
        "Orang Tua Dihubungi", "Status", "Dicatat Oleh", "Alasan Pembatalan",
    ])
    for item in records:
        occurred = item.get("occurred_at")
        writer.writerow([
            occurred.strftime("%Y-%m-%d") if occurred else "",
            occurred.strftime("%H:%M") if occurred else "",
            item.get("student_name"), item.get("class_name"),
            item.get("student_number") or item.get("nisn") or "",
            item.get("category"), item.get("violation_name"), item.get("points"),
            item.get("location") or "", item.get("note") or "",
            item.get("action_taken") or "", "Ya" if item.get("parent_notified") else "Tidak",
            "Aktif" if item.get("status") == "active" else "Dibatalkan",
            item.get("recorded_by_name") or "", item.get("void_reason") or "",
        ])
    filename = f"poin-siswa-{current_jakarta_time():%Y%m%d-%H%M%S}.csv"
    return Response(
        "\ufeff" + output.getvalue(),
        content_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
