"""Standalone NISN graduation lookup and session-bound SKL downloads."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re

from flask import Blueprint, abort, redirect, render_template, request, send_file, session, url_for
from werkzeug.utils import secure_filename

WIB = timezone(timedelta(hours=7))
ANNOUNCEMENT_TIME = datetime(2026, 6, 2, 10, 0, tzinfo=WIB)
ACCESS_SECONDS = 15 * 60
DOCUMENT_PREFIX = "landingpage/uploads/graduations/"
STATUS_LABELS = {"lulus": "LULUS", "belum_lulus": "BELUM LULUS", "ditunda": "DITUNDA"}


def current_wib():
    return datetime.now(WIB)


def released(record, now):
    announcement = record.get("tanggal_pengumuman")
    return bool(record.get("is_active") and now >= ANNOUNCEMENT_TIME
                and (announcement is None or announcement <= now.date()))


def document_path(record, static_root):
    metadata = record.get("metadata") or {}
    document = metadata.get("document") if isinstance(metadata, dict) else None
    if not isinstance(document, dict):
        return None
    relative = str(document.get("relative_path") or "").strip().replace("\\", "/").lstrip("/")
    if (not relative.startswith(DOCUMENT_PREFIX) or not relative.lower().endswith(".pdf")
            or any(part in {".", ".."} for part in relative.split("/"))):
        return None
    root = Path(static_root).resolve()
    path = (root / relative).resolve()
    if root not in path.parents or not path.is_file():
        return None
    return path


def register_graduation(app, *, fetch_content, lookup_by_nisn, lookup_by_id, resolve_site_key):
    if not app.secret_key:
        app.secret_key = os.getenv("LANDINGPAGE_SECRET_KEY") or os.getenv("DASHBOARD_SECRET_KEY")
    if not app.secret_key:
        raise RuntimeError("Set LANDINGPAGE_SECRET_KEY or DASHBOARD_SECRET_KEY for graduation document access")
    app.config.update(SESSION_COOKIE_NAME="landingpage_session", SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SECURE=True, SESSION_COOKIE_SAMESITE="Lax")
    bp = Blueprint("graduation", __name__)

    @bp.after_request
    def private_response(response):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.method == "POST" or request.endpoint != "graduation.check":
            response.headers["X-Robots-Tag"] = "noindex, noarchive"
        return response

    @bp.route("/kelulusan", methods=["GET", "POST"])
    def check():
        now = current_wib()
        if now < ANNOUNCEMENT_TIME:
            return render_template("countdown.html", graduation_url=url_for("graduation.check"),
                announcement_iso=ANNOUNCEMENT_TIME.isoformat())
        site_key = resolve_site_key()
        nisn, student, error, has_document = "", None, None, False
        if request.method == "POST":
            session.pop("graduation_access", None)
            nisn = (request.form.get("nisn") or "").strip()
            if not re.fullmatch(r"[0-9]{10}", nisn):
                error = "Masukkan NISN yang terdiri dari tepat 10 digit angka."
            else:
                record = lookup_by_nisn(site_key, nisn, active_only=True)
                if not record:
                    error = "Data kelulusan tidak ditemukan. Periksa kembali NISN yang dimasukkan."
                elif not released(record, now):
                    error = "Pengumuman kelulusan untuk siswa ini belum dibuka."
                else:
                    student = {"name": record.get("nama_siswa"), "class_name": record.get("kelas"),
                        "year": record.get("tahun_lulus"), "status": record.get("status"),
                        "status_label": STATUS_LABELS.get(record.get("status"), "BELUM TERSEDIA"),
                        "announcement_date": record.get("tanggal_pengumuman"),
                        "message": record.get("pesan_aska"), "masked_nisn": "******" + nisn[-4:]}
                    has_document = document_path(record, app.static_folder) is not None
                    session["graduation_access"] = {"record_id": record["id"], "site_key": site_key,
                                                    "verified_at": int(now.timestamp())}
        return render_template("cek_kelulusan.html", content=fetch_content(site_key=site_key),
                               nisn=nisn, student=student, error=error, has_document=has_document)

    def verified_document():
        access = session.get("graduation_access") or {}
        now = current_wib()
        verified_at = access.get("verified_at")
        if not isinstance(verified_at, int) or not 0 <= now.timestamp() - verified_at <= ACCESS_SECONDS:
            abort(403, description="Silakan cek NISN kembali sebelum membuka Surat Keterangan Lulus.")
        site_key = resolve_site_key()
        if access.get("site_key") != site_key or not isinstance(access.get("record_id"), int):
            abort(403)
        record = lookup_by_id(access["record_id"], site_key)
        if not record or not released(record, now):
            abort(403)
        path = document_path(record, app.static_folder)
        if path is None:
            abort(404, description="Surat Keterangan Lulus belum tersedia. Silakan menghubungi sekolah.")
        original_name = (record.get("metadata") or {}).get("document", {}).get("original_name")
        name = secure_filename(str(original_name or "surat-keterangan-lulus.pdf"))
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        return path, name

    @bp.get("/kelulusan/surat")
    def document_download():
        path, name = verified_document()
        return send_file(path, mimetype="application/pdf", as_attachment=True, download_name=name)

    @bp.get("/kelulusan/surat/lihat")
    def document_preview():
        path, name = verified_document()
        response = send_file(path, mimetype="application/pdf", as_attachment=False, download_name=name)
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        return response

    @bp.route("/cek-kelulusan", methods=["GET", "POST"])
    @bp.route("/lp/kelulusan", methods=["GET", "POST"])
    def legacy_alias():
        return redirect(url_for("graduation.check"), code=307 if request.method == "POST" else 301)

    app.register_blueprint(bp)
