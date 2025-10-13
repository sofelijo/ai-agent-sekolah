from __future__ import annotations

import os
import atexit
from datetime import timedelta

from flask import Flask

from .auth import auth_bp, current_user
from .routes import main_bp
from .db_access import shutdown_pool
from .queries import fetch_pending_bullying_count, fetch_pending_psych_count, fetch_pending_corruption_count
from .schema import ensure_dashboard_schema
from utils import to_jakarta


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    app.config["SECRET_KEY"] = os.getenv("DASHBOARD_SECRET_KEY", "change-me")
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
        days=int(os.getenv("DASHBOARD_SESSION_DAYS", "14"))
    )

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    try:
        ensure_dashboard_schema()
    except Exception:
        pass

    @app.context_processor
    def inject_globals() -> dict:
        user = current_user()
        pending_count = 0
        pending_psych = 0
        pending_corruption = 0

        if user:
            try:
                pending_count = fetch_pending_bullying_count()
            except Exception:
                pending_count = 0
            try:
                pending_psych = fetch_pending_psych_count()
            except Exception:
                pending_psych = 0
            try:
                pending_corruption = fetch_pending_corruption_count()
            except Exception:
                pending_corruption = 0

        return {
            "current_user": user,
            "pending_bullying_count": pending_count,
            "pending_psych_count": pending_psych,
            "pending_corruption_count": pending_corruption,
        }

    @app.template_filter("jakarta")
    def format_jakarta(value, fmt="%d %b %Y %H:%M"):
        if value is None:
            return ""
        dt = to_jakarta(value)
        try:
            return dt.strftime(fmt)
        except Exception:
            return ""

    atexit.register(shutdown_pool)

    return app
