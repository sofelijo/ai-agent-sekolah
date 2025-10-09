from __future__ import annotations

import os
import asyncio
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, flash
from authlib.integrations.flask_client import OAuth

# Import from within the project
from .handlers import process_web_request
from db import get_or_create_web_user, get_chat_history

def create_app() -> Flask:
    """Create and configure an instance of the Flask application."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder=None
    )

    # Secret key for session management
    app.config["SECRET_KEY"] = os.getenv("APP_SECRET_KEY", "a-very-secret-key-that-you-should-change")
    
    # Initialize OAuth
    oauth = OAuth(app)

    # Configure Google OAuth client
    oauth.register(
        name='google',
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile'
        }
    )

    @app.route("/")
    def index():
        user = session.get('user')
        if not user:
            return redirect(url_for('login_page'))
        
        # Load initial chat history
        user_id = user.get('id')
        initial_chats = get_chat_history(user_id, limit=10, offset=0)
        
        return render_template("chat.html", user=user, initial_chats=initial_chats)

    @app.route("/auth/login")
    def login_page():
        return render_template("login.html")

    @app.route('/login')
    def login():
        redirect_uri = url_for('authorize', _external=True)
        return oauth.google.authorize_redirect(redirect_uri)

    @app.route('/authorize')
    def authorize():
        token = oauth.google.authorize_access_token()
        userinfo = oauth.google.parse_id_token(token, nonce=session.get('nonce'))

        # Validate email domain
        email = userinfo.get('email')
        if not email:
            flash("Gagal mendapatkan informasi email dari Google.", "error")
            return redirect(url_for('login_page'))

        domain = email.split('@')[-1]
        if not (domain == 'belajar.id' or domain.endswith('.belajar.id')):
            flash("Login harus menggunakan email dengan domain @belajar.id atau subdomainnya.", "error")
            return redirect(url_for('login_page'))

        # Get or create user in the database
        user = get_or_create_web_user(email=email, full_name=userinfo.get('name'))
        
        # Add profile picture from userinfo to the user dictionary
        if user and userinfo.get('picture'):
            user['picture'] = userinfo.get('picture')

        # Save user in session
        session['user'] = user
        return redirect(url_for('index'))

    @app.route('/logout')
    def logout():
        session.pop('user', None)
        flash("You have been logged out.", "info")
        return redirect(url_for('login_page'))

    @app.route("/api/chat", methods=["POST"])
    def chat():
        if 'user' not in session:
            return jsonify({"error": "Unauthorized"}), 401

        data = request.json
        user_id = session['user'].get("id")
        full_name = session['user'].get("full_name", "WebUser")
        message = data.get("message")

        if not message:
            return jsonify({"error": "Message is required"}), 400

        # Run the async function in a managed event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # 'get_running_loop' fails if no loop is running
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        response = loop.run_until_complete(process_web_request(user_id, message, username=full_name))
        
        return jsonify({"response": response})

    @app.route("/api/history")
    def chat_history():
        if 'user' not in session:
            return jsonify({"error": "Unauthorized"}), 401
        
        user_id = session['user'].get('id')
        offset = request.args.get('offset', 0, type=int)
        
        history = get_chat_history(user_id, limit=10, offset=offset)
        
        # Convert datetime objects to string representation
        for item in history:
            if 'created_at' in item and hasattr(item['created_at'], 'isoformat'):
                item['created_at'] = item['created_at'].isoformat()

        return jsonify(history)

    return app