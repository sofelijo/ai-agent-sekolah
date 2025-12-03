# web_aska/feedback_routes.py
"""
API endpoints untuk feedback chat (like/dislike).
"""

from flask import Blueprint, request, jsonify, session
from typing import Optional, Dict, Any
import psycopg2

from db import (
    save_feedback,
    delete_feedback,
    get_feedback_status,
    get_chat_history,
)

feedback_bp = Blueprint('feedback', __name__, url_prefix='/api/feedback')


def _get_current_user() -> Optional[Dict[str, Any]]:
    """Helper untuk mendapatkan user dari session."""
    return session.get('user')


def _get_user_id() -> Optional[int]:
    """Helper untuk mendapatkan user_id dari session."""
    user = _get_current_user()
    return user.get('id') if user else None


def _get_username() -> Optional[str]:
    """Helper untuk mendapatkan username dari session."""
    user = _get_current_user()
    return user.get('full_name') or user.get('email') if user else None


def _is_user_message_author(chat_log_id: int, user_id: int) -> bool:
    """
    Cek apakah user adalah penulis pesan tersebut.
    Untuk mencegah self-feedback.
    """
    # Ambil chat log untuk cek author
    history = get_chat_history(user_id, limit=1000, offset=0)
    
    for msg in history:
        # Cari message dengan id yang sesuai
        # Note: get_chat_history tidak return id, jadi kita perlu query langsung
        pass
    
    # Untuk sementara, kita asumsikan user tidak bisa feedback pesan sendiri
    # jika role-nya adalah 'user'. Kita perlu query chat_logs untuk cek ini.
    from db import conn
    from psycopg2.extras import RealDictCursor
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT user_id, role
            FROM chat_logs
            WHERE id = %s
            """,
            (chat_log_id,)
        )
        row = cur.fetchone()
    
    if not row:
        return False
    
    # Jika pesan adalah dari ASKA (role='aska'), user boleh feedback
    if row.get('role') == 'aska':
        return False
    
    # Jika pesan dari user dan user_id sama, berarti self-feedback
    return row.get('user_id') == user_id


@feedback_bp.route('', methods=['POST'])
def submit_feedback():
    """
    POST /api/feedback
    Submit atau update feedback untuk chat message.
    
    Request body:
    {
        "chat_log_id": 12345,
        "feedback_type": "like" | "dislike"
    }
    
    Response:
    {
        "success": true,
        "feedback": {
            "chat_log_id": 12345,
            "feedback_type": "like",
            "created_at": "2024-12-02T10:30:00Z"
        }
    }
    """
    # 1. Validasi authentication
    user_id = _get_user_id()
    if not user_id:
        return jsonify({
            "success": False,
            "error": "User not authenticated"
        }), 401
    
    # 2. Validasi input
    data = request.get_json()
    if not data:
        return jsonify({
            "success": False,
            "error": "Request body is required"
        }), 400
    
    chat_log_id = data.get('chat_log_id')
    feedback_type = data.get('feedback_type')
    
    if not chat_log_id:
        return jsonify({
            "success": False,
            "error": "chat_log_id is required"
        }), 400
    
    if not feedback_type:
        return jsonify({
            "success": False,
            "error": "feedback_type is required"
        }), 400
    
    # Validasi feedback_type value
    if feedback_type not in ('like', 'dislike'):
        return jsonify({
            "success": False,
            "error": "feedback_type must be 'like' or 'dislike'"
        }), 400
    
    # 3. Validasi authorization - prevent self-feedback
    try:
        if _is_user_message_author(chat_log_id, user_id):
            return jsonify({
                "success": False,
                "error": "Cannot provide feedback on your own message"
            }), 403
    except Exception as e:
        # Jika terjadi error saat cek authorization, log dan lanjutkan
        # (lebih baik allow daripada block semua)
        print(f"Error checking message author: {e}")
    
    # 4. Simpan feedback
    username = _get_username()
    
    try:
        feedback = save_feedback(
            chat_log_id=chat_log_id,
            user_id=user_id,
            username=username,
            feedback_type=feedback_type
        )
        
        if not feedback:
            return jsonify({
                "success": False,
                "error": "Failed to save feedback"
            }), 500
        
        # Format response
        return jsonify({
            "success": True,
            "feedback": {
                "chat_log_id": feedback['chat_log_id'],
                "feedback_type": feedback['feedback_type'],
                "created_at": feedback['created_at'].isoformat() if hasattr(feedback['created_at'], 'isoformat') else str(feedback['created_at'])
            }
        }), 200
        
    except ValueError as e:
        # chat_log_id tidak ada
        error_msg = str(e)
        if 'does not exist' in error_msg:
            return jsonify({
                "success": False,
                "error": "Chat message not found"
            }), 404
        return jsonify({
            "success": False,
            "error": error_msg
        }), 400
        
    except psycopg2.IntegrityError as e:
        return jsonify({
            "success": False,
            "error": "Invalid chat_log_id"
        }), 400
        
    except Exception as e:
        print(f"Error saving feedback: {e}")
        return jsonify({
            "success": False,
            "error": "An error occurred while processing your request"
        }), 500


@feedback_bp.route('/<int:chat_log_id>', methods=['DELETE'])
def remove_feedback(chat_log_id: int):
    """
    DELETE /api/feedback/<chat_log_id>
    Hapus feedback untuk chat message tertentu.
    
    Response:
    {
        "success": true,
        "message": "Feedback removed"
    }
    """
    # 1. Validasi authentication
    user_id = _get_user_id()
    if not user_id:
        return jsonify({
            "success": False,
            "error": "User not authenticated"
        }), 401
    
    # 2. Hapus feedback
    try:
        deleted = delete_feedback(chat_log_id, user_id)
        
        if not deleted:
            return jsonify({
                "success": False,
                "error": "Feedback not found"
            }), 404
        
        return jsonify({
            "success": True,
            "message": "Feedback removed"
        }), 200
        
    except Exception as e:
        print(f"Error deleting feedback: {e}")
        return jsonify({
            "success": False,
            "error": "An error occurred while processing your request"
        }), 500


@feedback_bp.route('/status', methods=['GET'])
def get_feedback_statuses():
    """
    GET /api/feedback/status?chat_log_ids=123,456,789
    Ambil status feedback untuk multiple chat messages.
    
    Response:
    {
        "success": true,
        "feedbacks": {
            "123": {"feedback_type": "like", "created_at": "2024-12-02T10:30:00Z"},
            "456": null
        }
    }
    """
    # 1. Validasi authentication
    user_id = _get_user_id()
    if not user_id:
        return jsonify({
            "success": False,
            "error": "User not authenticated"
        }), 401
    
    # 2. Parse chat_log_ids dari query parameter
    chat_log_ids_str = request.args.get('chat_log_ids', '')
    if not chat_log_ids_str:
        return jsonify({
            "success": False,
            "error": "chat_log_ids parameter is required"
        }), 400
    
    try:
        chat_log_ids = [int(id_str.strip()) for id_str in chat_log_ids_str.split(',') if id_str.strip()]
    except ValueError:
        return jsonify({
            "success": False,
            "error": "Invalid chat_log_ids format"
        }), 400
    
    if not chat_log_ids:
        return jsonify({
            "success": True,
            "feedbacks": {}
        }), 200
    
    # 3. Ambil feedback status
    try:
        feedbacks = get_feedback_status(chat_log_ids, user_id)
        
        # Format response - convert datetime to ISO string
        formatted_feedbacks = {}
        for chat_log_id, feedback in feedbacks.items():
            if feedback:
                formatted_feedbacks[str(chat_log_id)] = {
                    "feedback_type": feedback['feedback_type'],
                    "created_at": feedback['created_at'].isoformat() if hasattr(feedback['created_at'], 'isoformat') else str(feedback['created_at']),
                    "updated_at": feedback['updated_at'].isoformat() if hasattr(feedback['updated_at'], 'isoformat') else str(feedback['updated_at'])
                }
            else:
                formatted_feedbacks[str(chat_log_id)] = None
        
        return jsonify({
            "success": True,
            "feedbacks": formatted_feedbacks
        }), 200
        
    except Exception as e:
        print(f"Error getting feedback status: {e}")
        return jsonify({
            "success": False,
            "error": "An error occurred while processing your request"
        }), 500
