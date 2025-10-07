from __future__ import annotations

import os
import atexit
from datetime import timedelta

from flask import Flask

from .auth import auth_bp, current_user
from .routes import main_bp
from .db_access import shutdown_pool
from .queries import fetch_pending_bullying_count
from .schema import ensure_dashboard_schema


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

        if user:
            try:
                pending_count = fetch_pending_bullying_count()
            except Exception:
                pending_count = 0

        return {
            "current_user": user,
            "pending_bullying_count": pending_count,
        }

    atexit.register(shutdown_pool)

    return app

