from __future__ import annotations

import os
from flask import Flask, request, jsonify, render_template
import asyncio

# Import from within the package
from .handlers import process_web_request
from dashboard import create_admin_blueprint

def create_app() -> Flask:
    """Create and configure an instance of the Flask application."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder=None  # No static folder in this simple case
    )

    app.config["SECRET_KEY"] = os.getenv("APP_SECRET_KEY", "a-default-secret-key-for-web-aska")

    # Create and register the admin blueprint
    admin_bp = create_admin_blueprint()
    app.register_blueprint(admin_bp)

    @app.route("/")
    def index():
        return render_template("chat.html")

    @app.route("/api/chat", methods=["POST"])
    def chat():
        data = request.json
        user_id = data.get("user_id", "web_user")
        message = data.get("message")

        if not message:
            return jsonify({"error": "Message is required"}), 400

        # Run the async function in a managed event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # 'get_running_loop' fails if no loop is running
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        response = loop.run_until_complete(process_web_request(user_id, message))
        
        return jsonify({"response": response})

    return app
