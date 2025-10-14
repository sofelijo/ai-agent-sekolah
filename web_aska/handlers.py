# web_aska/handlers.py
import asyncio
import time
from typing import Optional

from dotenv import load_dotenv
# from openai import OpenAI  # not used in web handler

from ai_core import build_qa_chain
from db import save_chat, get_chat_history
from responses import ASKA_NO_DATA_RESPONSE, ASKA_TECHNICAL_ISSUE_RESPONSE
from utils import (
    normalize_input,
    strip_markdown,
    now_str,
    format_history_for_chain,
    coerce_to_text,
    rewrite_schedule_query,
    replace_bot_mentions,
)
from flows.safety_flow import handle_bullying
from flows.corruption_flow import handle_corruption
from flows.psych_flow import handle_psych
from flows.teacher_flow import handle_teacher
from flows.smalltalk_flow import handle_smalltalk

# --- Mock Telegram Objects ---
class MockBot:
    def __init__(self, username="ASKA_WEB"):
        self.username = username

    async def send_chat_action(self, chat_id, action):
        # No-op for web environment
        return None

class MockUser:
    def __init__(self, user_id, first_name="WebUser", username=None):
        self.id = user_id
        self.first_name = first_name
        self.username = username if username else first_name

class MockMessage:
    def __init__(self, user, text):
        self.from_user = user
        self.text = text

    # Adapter to capture replies from flow modules
    def _init_capture(self):
        self._last_reply: Optional[str] = None

    async def reply_text(self, text, parse_mode=None):
        # Store stripped markdown to keep web output clean
        self._last_reply = strip_markdown(text)
        return None

class MockUpdate:
    def __init__(self, message):
        self.message = message
        self.effective_user = message.from_user
        self.effective_chat = self # Simplified for web
        self.id = id(self)

class MockContext:
    def __init__(self, chat_data):
        self._chat_data = chat_data
        self.bot = MockBot()

    @property
    def chat_data(self):
        return self._chat_data

# --- Session Management ---
web_sessions = {}

load_dotenv()
qa_chain = build_qa_chain()

TEACHER_CONVERSATION_LIMIT = 10
TEACHER_TIMEOUT_SECONDS = 600
PSYCH_TIMEOUT_SECONDS = 600

TEACHER_TIMEOUT_MESSAGE = (
    "Latihan kita ke-pause lumayan lama nih, ASKA pamit dulu ya. "
    "Kalau mau lanjut tinggal panggil ASKA lagi. Sampai jumpa! 😄✨"
)

PSYCH_TIMEOUT_MESSAGE = (
    "Obrolan laporan konselingnya udah sunyi lama, ASKA pamit sementara ya. "
    "Kapan pun butuh cerita lagi langsung chat ASKA. Sampai jumpa! 🤗💖"
)

# Psych severity rank handled inside shared flows (responses/psychologist)

async def process_web_request(user_id: int, user_input: str, username: str = "WebUser") -> str:
    """Main function to handle a chat request from the web API."""
    
    session_data = web_sessions.setdefault(user_id, {})

    user = MockUser(user_id, first_name=username)
    message = MockMessage(user, user_input)
    update = MockUpdate(message)
    context = MockContext(session_data)

    response_text = ASKA_TECHNICAL_ISSUE_RESPONSE

    try:
        raw_input = user_input or ""
        bot_username = getattr(context.bot, "username", None)
        raw_input = replace_bot_mentions(raw_input, bot_username)
        normalized_input = normalize_input(raw_input)

        user_obj = user
        # This username is now correctly set from the function parameter
        username = user.username

        print(
            f"[{now_str()}] WEB HANDLER CALLED - FROM {username}: {normalized_input}"
        )

        storage_key = user_id

        recent_messages_root = context.chat_data.setdefault("recent_messages_by_user", {})
        recent_messages = recent_messages_root.setdefault(storage_key, {})
        now_ts = time.time()
        for msg_text, ts in list(recent_messages.items()):
            if (now_ts - ts) > 600:
                del recent_messages[msg_text]
        last_ts = recent_messages.get(normalized_input)
        if last_ts is not None and (now_ts - last_ts) < 60:
            print(f"[{now_str()}] DUPLICATE MESSAGE RECEIVED WITHIN 60s - SKIPPING")
            return "..."
        recent_messages[normalized_input] = now_ts

        print(f"[{now_str()}] SAVING USER MESSAGE")
        chat_log_id = save_chat(user_id, username, normalized_input, role="user", topic="web")

        # 1) Bullying / Safety (reuse shared flow)
        reply_target = MockMessage(user, "")
        reply_target._init_capture()
        handled = await handle_bullying(
            update=update,
            context=context,
            reply_message=reply_target,
            raw_input=raw_input,
            normalized_input=normalized_input,
            user_id=user_id,
            username=username,
            chat_log_id=chat_log_id,
            source="web",
            mark_responded=lambda: None,
        )
        if handled:
            print(f"[{now_str()}] WEB FLOW HANDLED: bullying")
            return reply_target._last_reply or ""

        # 2) Corruption Reporting Flow (reuse shared flow)
        reply_target = MockMessage(user, "")
        reply_target._init_capture()
        handled = await handle_corruption(
            update=update,
            context=context,
            reply_message=reply_target,
            raw_input=raw_input,
            normalized_input=normalized_input,
            user_id=user_id,
            username=username,
            storage_key=storage_key,
            source="web",
            mark_responded=lambda: None,
        )
        if handled:
            print(f"[{now_str()}] WEB FLOW HANDLED: corruption")
            return reply_target._last_reply or ""

        # 3) Psych / counseling (reuse shared flow)
        reply_target = MockMessage(user, "")
        reply_target._init_capture()
        handled = await handle_psych(
            update=update,
            context=context,
            reply_message=reply_target,
            raw_input=raw_input,
            normalized_input=normalized_input,
            user_id=user_id,
            username=username,
            storage_key=storage_key,
            chat_log_id=chat_log_id,
            source="web",
            mark_responded=lambda: None,
            timeout_seconds=PSYCH_TIMEOUT_SECONDS,
            timeout_message=PSYCH_TIMEOUT_MESSAGE,
            now_ts=now_ts,
        )
        if handled:
            print(f"[{now_str()}] WEB FLOW HANDLED: psych")
            return reply_target._last_reply or ""

        teacher_sessions = context.chat_data.setdefault("teacher_sessions", {})
        teacher_session = teacher_sessions.get(storage_key)

        if teacher_session:
            last_bot_time = teacher_session.get("last_bot_time")
            if last_bot_time and (now_ts - last_bot_time) > TEACHER_TIMEOUT_SECONDS:
                response = TEACHER_TIMEOUT_MESSAGE
                save_chat(user_id, "ASKA", response, role="aska")
                teacher_sessions.pop(storage_key, None)
                return response

        if is_teacher_stop(normalized_input):
            if teacher_session:
                teacher_sessions.pop(storage_key, None)
                farewell = (
                    "Sesi belajar bersama ASKA selesai. Kapan pun mau latihan lagi, ketik saja "
                    "'kasih soal' atau 'mode guru', ya!"
                )
                save_chat(user_id, "ASKA", farewell, role="aska")
                return farewell

        if is_teacher_start(normalized_input):
            grade_hint = extract_grade_hint(raw_input)
            subject_hint = extract_subject_hint(raw_input)
            question = pick_question(grade_hint, subject_hint, raw_input)
            session_data = {
                "question": question,
                "grade_hint": grade_hint,
                "subject_hint": subject_hint or question.subject,
                "attempt": 1,
                "conversation": [],
            }
            teacher_sessions[storage_key] = session_data
            intro = format_question_intro(question)
            save_chat(user_id, "ASKA", intro, role="aska")
            session_data["conversation"].append({"role": "assistant", "content": intro})
            session_data["last_bot_time"] = time.time()
            return intro

        if not teacher_session and is_teacher_next(normalized_input):
            reminder = (
                "Belum ada sesi guru yang aktif. Ketik 'kasih soal' atau 'mode guru' dulu ya."
            )
            save_chat(user_id, "ASKA", reminder, role="aska")
            return reminder

        if teacher_session and is_teacher_next(normalized_input):
            grade_hint_override = extract_grade_hint(raw_input)
            if grade_hint_override:
                teacher_session["grade_hint"] = grade_hint_override
            subject_hint_override = extract_subject_hint(raw_input) or teacher_session.get("subject_hint")
            question = pick_question(
                teacher_session.get("grade_hint"),
                subject_hint_override,
                raw_input,
            )
            teacher_session["question"] = question
            teacher_session["attempt"] = 1
            teacher_session["subject_hint"] = subject_hint_override or question.subject
            teacher_session["conversation"] = []
            intro = format_question_intro(question, attempt_number=1)
            save_chat(user_id, "ASKA", intro, role="aska")
            teacher_session["conversation"].append({"role": "assistant", "content": intro})
            teacher_session["last_bot_time"] = time.time()
            return intro

        # 4) Teacher mode (reuse shared flow)
        reply_target = MockMessage(user, "")
        reply_target._init_capture()
        handled = await handle_teacher(
            update=update,
            context=context,
            reply_message=reply_target,
            raw_input=raw_input,
            normalized_input=normalized_input,
            user_id=user_id,
            storage_key=storage_key,
            mark_responded=lambda: None,
            timeout_seconds=TEACHER_TIMEOUT_SECONDS,
            timeout_message=TEACHER_TIMEOUT_MESSAGE,
        )
        if handled:
            print(f"[{now_str()}] WEB FLOW HANDLED: teacher")
            return reply_target._last_reply or ""

        # 5) Smalltalk / canned (reuse shared flow)
        reply_target = MockMessage(user, "")
        reply_target._init_capture()
        handled = await handle_smalltalk(
            update=update,
            context=context,
            reply_message=reply_target,
            normalized_input=normalized_input,
            user_id=user_id,
            username=username,
            mark_responded=lambda: None,
        )
        if handled:
            print(f"[{now_str()}] WEB FLOW HANDLED: smalltalk")
            return reply_target._last_reply or ""

        normalized_input = rewrite_schedule_query(normalized_input)

        print(f"[{now_str()}] ASKA sedang berpikir...")

        history_from_db = get_chat_history(user_id, limit=5, offset=0)
        chat_history = format_history_for_chain(history_from_db)

        start_time = time.perf_counter()

        result = await asyncio.to_thread(qa_chain.invoke, {"input": normalized_input, "chat_history": chat_history})

        print(f"[{now_str()}] ?? ASKA AMBIL {len(result['context'])} KONTEN:")
        for i, doc in enumerate(result["context"], 1):
            print(f"  {i}. {doc.page_content[:200]}...")

        response = coerce_to_text(result)

        if not response.strip():
            response = ASKA_NO_DATA_RESPONSE

        duration_ms = (time.perf_counter() - start_time) * 1000
        print(f"[{now_str()}] ASKA : {response} ?? {duration_ms:.2f} ms")
        save_chat(
            user_id,
            "ASKA",
            strip_markdown(response),
            role="aska",
            topic="web",
            response_time_ms=int(duration_ms),
        )

        return response

    except Exception as e:
        print(f"[{now_str()}] [ERROR] {e}")
        return ASKA_TECHNICAL_ISSUE_RESPONSE
