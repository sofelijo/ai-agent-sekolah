from __future__ import annotations
import os
import atexit
from datetime import timedelta
from flask import Blueprint, Flask

from .auth import auth_bp
from .routes import main_bp
from .db_access import shutdown_pool
from .queries import fetch_pending_bullying_count, fetch_pending_psych_count
from .schema import ensure_dashboard_schema
from .auth import current_user

def create_admin_blueprint() -> Blueprint:
    """Creates and configures the admin blueprint."""
    admin_bp = Blueprint(
        'admin',
        __name__,
        template_folder='templates',
        static_folder='static',
        url_prefix='/admin'
    )

    # Register nested blueprints
    admin_bp.register_blueprint(auth_bp)
    admin_bp.register_blueprint(main_bp)

    # This function will be called once when the blueprint is registered
    @admin_bp.record_once
    def on_blueprint_register(state):
        app = state.app
        app.config["SECRET_KEY"] = os.getenv("DASHBOARD_SECRET_KEY", "change-me")
        app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
            days=int(os.getenv("DASHBOARD_SESSION_DAYS", "14"))
        )
        
        with app.app_context():
            try:
                ensure_dashboard_schema()
            except Exception:
                pass

        # Register shutdown hook
        atexit.register(shutdown_pool)

    @admin_bp.context_processor
    def inject_globals() -> dict:
        user = current_user()
        pending_count = 0
        pending_psych = 0

        if user:
            try:
                pending_count = fetch_pending_bullying_count()
            except Exception:
                pending_count = 0
            try:
                pending_psych = fetch_pending_psych_count()
            except Exception:
                pending_psych = 0

        return {
            "current_user": user,
            "pending_bullying_count": pending_count,
            "pending_psych_count": pending_psych,
        }

    return admin_bp
