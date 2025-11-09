from __future__ import annotations

import atexit
import os
from datetime import timedelta

from flask import Flask

from dashboard.auth import auth_bp, current_user, init_oauth
from dashboard.attendance import attendance_bp
from dashboard.db_access import shutdown_pool
from dashboard.queries import (
    fetch_pending_bullying_count,
    fetch_pending_corruption_count,
    fetch_pending_psych_count,
)
from dashboard.schema import ensure_dashboard_schema
from utils import to_jakarta


def create_app() -> Flask:
    """Factory khusus attendance-only (auth + absensi)."""

    app = Flask(
        "aska_attendance",
        template_folder="dashboard/templates",
        static_folder="dashboard/static",
    )

    app.config["SECRET_KEY"] = os.getenv("DASHBOARD_SECRET_KEY", "change-me")
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
        days=int(os.getenv("DASHBOARD_SESSION_DAYS", "14"))
    )

    app.register_blueprint(auth_bp)
    app.register_blueprint(attendance_bp)
    init_oauth(app)

    try:
        ensure_dashboard_schema()
    except Exception:
        # Biarkan app tetap jalan; error akan muncul di log server
        pass

    @app.context_processor
    def inject_globals() -> dict:
        user = current_user()
        pending_bullying = pending_psych = pending_corruption = 0
        if user:
            try:
                pending_bullying = fetch_pending_bullying_count()
            except Exception:
                pass
            try:
                pending_psych = fetch_pending_psych_count()
            except Exception:
                pass
            try:
                pending_corruption = fetch_pending_corruption_count()
            except Exception:
                pass
        return {
            "current_user": user,
            "pending_bullying_count": pending_bullying,
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


app = create_app()
