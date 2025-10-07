from __future__ import annotations

from datetime import datetime
from math import ceil
from typing import Optional

from flask import (
    Blueprint,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.datastructures import MultiDict

from .auth import login_required
from .queries import (
    ChatFilters,
    fetch_chat_logs,
    fetch_conversation_thread,
    fetch_daily_activity,
    fetch_overview_metrics,
    fetch_recent_questions,
    fetch_top_keywords,
    fetch_top_users,
)

main_bp = Blueprint("main", __name__)
PAGE_SIZE = 50


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


@main_bp.route("/")
@login_required
def dashboard() -> Response:
    metrics = fetch_overview_metrics(window_days=7)
    activity = fetch_daily_activity(days=14)
    recent_questions = fetch_recent_questions(limit=8)
    top_users = fetch_top_users(limit=5)
    top_keywords = fetch_top_keywords(limit=8, days=14)

    chart_labels = [row["day"].strftime("%d %b") for row in activity]
    chart_values = [row["messages"] for row in activity]
    keyword_labels = [item["keyword"] for item in top_keywords]
    keyword_counts = [item["count"] for item in top_keywords]

    return render_template(
        "dashboard.html",
        generated_at=datetime.utcnow(),
        metrics=metrics,
        recent_questions=recent_questions,
        top_users=top_users,
        chart_labels=chart_labels,
        chart_values=chart_values,
        keyword_labels=keyword_labels,
        keyword_counts=keyword_counts,
    )


@main_bp.route("/chats")
@login_required
def chats() -> Response:
    args: MultiDict = request.args
    page = max(1, int(args.get("page", 1)))
    start = _parse_date(args.get("start"))
    end = _parse_date(args.get("end"))
    role = args.get("role") or None
    search = args.get("search") or None
    user_id = args.get("user_id")
    user_id = int(user_id) if user_id else None

    filters = ChatFilters(start=start, end=end, role=role, search=search, user_id=user_id)
    offset = (page - 1) * PAGE_SIZE

    records, total = fetch_chat_logs(filters=filters, limit=PAGE_SIZE, offset=offset)
    total_pages = max(1, ceil(total / PAGE_SIZE))

    export_params = {}
    if start:
        export_params["start"] = start.strftime("%Y-%m-%d")
    if end:
        export_params["end"] = end.strftime("%Y-%m-%d")
    if role:
        export_params["role"] = role
    if search:
        export_params["search"] = search
    if user_id:
        export_params["user_id"] = user_id

    export_url = url_for("main.export_chats", **export_params)

    return render_template(
        "chats.html",
        records=records,
        total=total,
        page=page,
        total_pages=total_pages,
        filters=filters,
        export_url=export_url,
    )


@main_bp.route("/chats/thread/<int:user_id>")
@login_required
def chat_thread(user_id: int) -> Response:
    messages = fetch_conversation_thread(user_id=user_id, limit=400)
    if not messages:
        return redirect(url_for("main.chats"))

    user = {
        "user_id": user_id,
        "username": messages[0].get("username") or "Unknown",
    }
    return render_template("chat_thread.html", messages=messages, user=user)


@main_bp.route("/api/activity")
@login_required
def activity_api() -> Response:
    days = int(request.args.get("days", 14))
    activity = fetch_daily_activity(days=days)
    return jsonify(activity)


@main_bp.route("/chats/export")
@login_required
def export_chats() -> Response:
    args: MultiDict = request.args
    start = _parse_date(args.get("start"))
    end = _parse_date(args.get("end"))
    role = args.get("role") or None
    search = args.get("search") or None
    user_id = args.get("user_id")
    user_id = int(user_id) if user_id else None

    filters = ChatFilters(start=start, end=end, role=role, search=search, user_id=user_id)

    records, _ = fetch_chat_logs(filters=filters, limit=5000, offset=0)

    from io import StringIO
    import csv

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "created_at", "user_id", "username", "role", "response_time_ms", "text"])
    for row in records:
        writer.writerow(
            [
                row.get("id"),
                row.get("created_at"),
                row.get("user_id"),
                row.get("username"),
                row.get("role"),
                row.get("response_time_ms"),
                (row.get("text") or "").replace("\n", " "),
            ]
        )

    buffer.seek(0)
    filename = f"chat_logs_export_{datetime.utcnow():%Y%m%d_%H%M%S}.csv"
    response = Response(buffer.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response

