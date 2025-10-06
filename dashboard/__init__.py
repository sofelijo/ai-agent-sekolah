from __future__ import annotations

import os
import atexit
from datetime import timedelta

from flask import Flask

from .auth import auth_bp, current_user
from .routes import main_bp
from .db_access import shutdown_pool


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

    @app.context_processor
    def inject_user() -> dict:
        return {"current_user": current_user()}

    atexit.register(shutdown_pool)

    return app

