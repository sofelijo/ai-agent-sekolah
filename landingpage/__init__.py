from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Flask, render_template, Response, request

from dashboard.queries import fetch_landingpage_content, fetch_landingpage_teachers


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

    @app.route("/")
    def landing_home():
        site_key = _resolve_site_key()
        content = fetch_landingpage_content(site_key=site_key)
        return render_template("landingpage.html", content=content, site_key=site_key)

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
        urls = [
            f"{base}/",
            f"{base}/guru",
        ]
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
