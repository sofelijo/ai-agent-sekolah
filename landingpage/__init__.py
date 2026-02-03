from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Flask, render_template, Response, request, send_file, abort, jsonify, url_for

from dashboard.queries import fetch_landingpage_content, fetch_landingpage_teachers
from dashboard.attendance.queries import (
    list_extracurriculars,
    get_extracurricular,
    fetch_extracurricular_photo_options,
    fetch_extracurricular_attendance_history,
)
from utils import INDONESIAN_MONTH_NAMES


def _resolve_site_key() -> str:
    override = (os.getenv("LANDINGPAGE_SITE_KEY") or "").strip()
    if override:
        return override
    return "default"


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    data_path = Path(__file__).resolve().parent / "static" / "landingpage" / "data" / "guru_full.json"
    dashboard_static = Path(__file__).resolve().parent.parent / "dashboard" / "static"
    default_ekskul_image = "landingpage/images/ekstra-pramuka.jpg"

    def _normalize_guru_photo(item: dict) -> dict:
        foto = (item.get("foto") or "").strip()
        if foto.startswith("/"):
            foto = f"landingpage/images{foto}"
        elif foto and not foto.startswith("http") and not foto.startswith("landingpage/"):
            foto = f"landingpage/images/{foto.lstrip('/')}"
        return {**item, "foto": foto}

    def _load_guru_data(site_key: str):
        try:
            data = fetch_landingpage_teachers(site_key=site_key, active_only=True)
            if data:
                return [_normalize_guru_photo(item) for item in data]
        except Exception:
            pass
        if not data_path.exists():
            return []
        try:
            payload = json.loads(data_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        normalized = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            normalized.append(_normalize_guru_photo(item))
        return normalized

    def _normalize_metadata(raw) -> dict:
        if isinstance(raw, dict):
            return raw
        return {}

    def _asset_url(value: str) -> str:
        if not value:
            return ""
        if value.startswith("http") or value.startswith("/static/"):
            return value
        if value.startswith("uploads/"):
            return url_for("landing_assets", filename=value.lstrip("/"))
        if value.startswith("static/"):
            return f"/{value}"
        return url_for("static", filename=value.lstrip("/"))

    def _format_date(value) -> str:
        if not value:
            return ""
        try:
            day = value.day
            month_name = INDONESIAN_MONTH_NAMES.get(value.month, value.strftime("%B"))
            return f"{day} {month_name} {value.year}"
        except Exception:
            return str(value)

    def _legacy_extracurricular_map(content: dict) -> dict:
        legacy_items = content.get("extracurricular", {}).get("items", []) if content else []
        lookup = {}
        for item in legacy_items:
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "").strip()
            if title:
                lookup[title.lower()] = item
        return lookup

    def _resolve_extracurricular_photos(activity_id: int, metadata: dict, legacy_item):
        selected_main = (metadata.get("lp_main_photo") or "").strip()
        selected_gallery = metadata.get("lp_gallery_photos") if isinstance(metadata.get("lp_gallery_photos"), list) else []
        selected_gallery = [item for item in selected_gallery if isinstance(item, str) and item.strip()]
        uploaded_photos = metadata.get("lp_uploaded_photos") if isinstance(metadata.get("lp_uploaded_photos"), list) else []
        uploaded_photos = [item for item in uploaded_photos if isinstance(item, str) and item.strip()]
        max_gallery = 10

        has_uploads = bool(selected_main or selected_gallery or uploaded_photos)
        legacy_image = None
        if legacy_item:
            legacy_image = (legacy_item.get("image") or "").strip() or None

        if has_uploads:
            ordered: List[str] = []
            for path in [selected_main] + selected_gallery + uploaded_photos:
                if not path:
                    continue
                if path not in ordered:
                    ordered.append(path)
            main_photo = ordered[0] if ordered else None
            if not main_photo:
                main_photo = default_ekskul_image
            gallery: List[str] = []
            if main_photo:
                gallery.append(main_photo)
            for photo in ordered:
                if photo == main_photo:
                    continue
                gallery.append(photo)
                if len(gallery) >= max_gallery:
                    break
            return main_photo, gallery

        fallback_rows = fetch_extracurricular_photo_options(activity_id, limit=max_gallery)
        fallback_photos = [row.get("photo_path") for row in fallback_rows if row.get("photo_path")]
        main_photo = selected_main or (fallback_photos[0] if fallback_photos else legacy_image) or default_ekskul_image
        gallery: List[str] = []
        if main_photo:
            gallery.append(main_photo)
        for photo in fallback_photos:
            if photo == main_photo:
                continue
            gallery.append(photo)
            if len(gallery) >= max_gallery:
                break
        return main_photo, gallery

    def _build_extracurricular_list(content: dict):
        legacy_lookup = _legacy_extracurricular_map(content)
        activities = list_extracurriculars(include_inactive=False)
        items = []
        for activity in activities:
            metadata = _normalize_metadata(activity.get("metadata"))
            name = (activity.get("name") or "").strip()
            legacy_item = legacy_lookup.get(name.lower()) if name else None
            description = (activity.get("description") or "").strip()
            if not description and legacy_item:
                description = (legacy_item.get("description") or "").strip()
            main_photo, gallery = _resolve_extracurricular_photos(activity.get("id"), metadata, legacy_item)
            items.append(
                {
                    "id": activity.get("id"),
                    "name": name or (legacy_item.get("title") if legacy_item else "Ekskul"),
                    "description": description,
                    "main_photo": main_photo,
                    "gallery_photos": gallery,
                }
            )
        return items

    def _build_extracurricular_history(activity_id: int, main_photo: str, limit: int, offset: int):
        rows = fetch_extracurricular_attendance_history(activity_id, limit=limit, offset=offset)
        items = []
        for row in rows:
            photo_path = row.get("photo_path") or main_photo
            items.append(
                {
                    "attendance_date": row.get("attendance_date"),
                    "date_label": _format_date(row.get("attendance_date")),
                    "photo_path": photo_path,
                    "photo_url": _asset_url(photo_path),
                    "total_students": int(row.get("total_students") or 0),
                }
            )
        return items

    @app.route("/")
    def landing_home():
        site_key = _resolve_site_key()
        content = fetch_landingpage_content(site_key=site_key)
        extracurriculars = _build_extracurricular_list(content)
        return render_template(
            "landingpage.html",
            content=content,
            site_key=site_key,
            extracurriculars=extracurriculars,
        )

    @app.route("/ekskul/<int:activity_id>")
    def landing_extracurricular_detail(activity_id: int):
        site_key = _resolve_site_key()
        content = fetch_landingpage_content(site_key=site_key)
        activity = get_extracurricular(activity_id)
        if not activity:
            abort(404)
        metadata = _normalize_metadata(activity.get("metadata"))
        legacy_lookup = _legacy_extracurricular_map(content)
        legacy_item = legacy_lookup.get((activity.get("name") or "").strip().lower())
        main_photo, gallery = _resolve_extracurricular_photos(activity_id, metadata, legacy_item)
        description = (activity.get("description") or "").strip()
        if not description and legacy_item:
            description = (legacy_item.get("description") or "").strip()
        history_items = _build_extracurricular_history(activity_id, main_photo, limit=10, offset=0)
        history_has_more = len(history_items) == 10
        return render_template(
            "ekskul_detail.html",
            activity=activity,
            description=description,
            main_photo=main_photo,
            gallery_photos=gallery,
            history_items=history_items,
            history_has_more=history_has_more,
            history_offset=len(history_items),
            content=content,
        )

    @app.route("/ekskul/<int:activity_id>/history")
    def landing_extracurricular_history(activity_id: int):
        activity = get_extracurricular(activity_id)
        if not activity:
            abort(404)
        limit = request.args.get("limit", default=10, type=int)
        offset = request.args.get("offset", default=0, type=int)
        if limit < 1:
            limit = 10
        if limit > 20:
            limit = 20
        if offset < 0:
            offset = 0
        metadata = _normalize_metadata(activity.get("metadata"))
        content = fetch_landingpage_content(site_key=_resolve_site_key())
        legacy_lookup = _legacy_extracurricular_map(content)
        legacy_item = legacy_lookup.get((activity.get("name") or "").strip().lower())
        main_photo, _gallery = _resolve_extracurricular_photos(activity_id, metadata, legacy_item)
        items = _build_extracurricular_history(activity_id, main_photo, limit=limit, offset=offset)
        next_offset = offset + len(items)
        has_more = len(items) == limit
        return jsonify({"items": items, "next_offset": next_offset, "has_more": has_more})

    @app.route("/assets/<path:filename>")
    def landing_assets(filename: str):
        if ".." in filename or filename.startswith("/"):
            abort(404)
        file_path = (dashboard_static / filename).resolve()
        if not str(file_path).startswith(str(dashboard_static.resolve())):
            abort(404)
        if not file_path.exists():
            abort(404)
        return send_file(file_path)

    @app.route("/guru")
    def landing_guru():
        site_key = _resolve_site_key()
        guru_data = _load_guru_data(site_key)
        category_order = [
            "Semua",
            "Guru",
            "Kepala Sekolah",
            "Wakil Kepala Sekolah",
            "Tenaga Administrasi",
            "Tenaga Kebersihan",
            "PKSTI",
        ]
        categories = list(category_order)
        extra = []
        for item in guru_data:
            jabatan = (item.get("jabatan") or "").strip()
            if not jabatan:
                continue
            for value in category_order:
                if value != "Semua" and value.lower() in jabatan.lower():
                    break
            else:
                if jabatan not in extra:
                    extra.append(jabatan)
        categories.extend(extra)
        return render_template("guru.html", guru_list=guru_data, categories=categories)

    @app.route("/sitemap.xml")
    def sitemap() -> Response:
        base = request.url_root.rstrip("/")
        urls = [f"{base}/", f"{base}/guru"]
        try:
            content = fetch_landingpage_content(site_key=_resolve_site_key())
            for item in _build_extracurricular_list(content):
                if item.get("id"):
                    urls.append(f"{base}/ekskul/{item['id']}")
        except Exception:
            pass
        body = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>", "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"]
        for url in urls:
            body.append("  <url>")
            body.append(f"    <loc>{url}</loc>")
            body.append("  </url>")
        body.append("</urlset>")
        return Response("\n".join(body), mimetype="application/xml")

    @app.route("/robots.txt")
    def robots() -> Response:
        base = request.url_root.rstrip("/")
        content = f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n"
        return Response(content, mimetype="text/plain")

    return app
