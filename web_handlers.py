# web_handlers.py
import asyncio
import os
import tempfile
import time
from typing import List, Optional, Set

# Remove telegram imports, we will mock them
# from telegram import Message, Update
# from telegram.error import NetworkError
# from telegram.ext import ContextTypes

from dotenv import load_dotenv
from openai import OpenAI

from ai_core import build_qa_chain
from db import save_chat, get_chat_history, record_bullying_report, record_psych_report
from responses import (
    ASKA_NO_DATA_RESPONSE,
    ASKA_TECHNICAL_ISSUE_RESPONSE,
    contains_inappropriate_language,
    get_advice_response,
    CATEGORY_PHYSICAL,
    CATEGORY_SEXUAL,
    detect_bullying_category,
    get_bullying_ack_response,
    get_relationship_advice_response,
    get_acknowledgement_response,
    get_farewell_response,
    get_greeting_response,
    get_time_based_greeting_response,
    get_self_intro_response,
    get_status_response,
    get_thank_you_response,
    is_acknowledgement_message,
    is_farewell_message,
    is_greeting_message,
    is_relationship_question,
    is_self_intro_message,
    is_status_message,
    is_thank_you_message,
    extract_grade_hint,
    extract_subject_hint,
    format_question_intro,
    grade_response,
    generate_discussion_reply,
    is_teacher_discussion_request,
    is_teacher_next,
    is_teacher_start,
    is_teacher_stop,
    pick_question,
    SEVERITY_CRITICAL,
    SEVERITY_ELEVATED,
    SEVERITY_GENERAL,
    classify_message_severity,
    detect_psych_intent,
    get_psych_closing_message,
    get_psych_confirmation_prompt,
    get_psych_critical_message,
    get_psych_stage_prompt,
    get_psych_validation,
    get_psych_support_message,
    is_psych_negative_confirmation,
    is_psych_positive_confirmation,
    is_psych_stop_request,
    psych_next_stage,
    psych_stage_exists,
    summarize_psych_message,
)
from utils import (
    IMG_MD,
    normalize_input,
    strip_markdown,
    now_str,
    format_history_for_chain,
    coerce_to_text,
    rewrite_schedule_query,
    # send_typing_once,
    # keep_typing_indicator,
    # send_thinking_bubble,
    # reply_with_markdown,
    replace_bot_mentions,
    # should_respond,
    # resolve_target_message,
    # prepare_group_query,
)

# --- Mock Telegram Objects ---
class MockBot:
    def __init__(self, username="ASKA_WEB"):
        self.username = username

class MockUser:
    def __init__(self, user_id, first_name="WebUser", username=None):
        self.id = user_id
        self.first_name = first_name
        self.username = username if username else first_name

class MockMessage:
    def __init__(self, user, text):
        self.from_user = user
        self.text = text

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

# We don't need audio transcription for the web version for now
# audio_client = OpenAI()

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

PSYCH_SEVERITY_RANK = {
    SEVERITY_GENERAL: 0,
    SEVERITY_ELEVATED: 1,
    SEVERITY_CRITICAL: 2,
}

async def process_web_request(user_id: str, user_input: str) -> str:
    """Main function to handle a chat request from the web API."""
    
    # Get or create session for the user
    session_data = web_sessions.setdefault(user_id, {})

    # Create mock Telegram-like objects
    user = MockUser(user_id)
    message = MockMessage(user, user_input)
    update = MockUpdate(message)
    context = MockContext(session_data)

    # This will hold the bot's response
    response_text = ASKA_TECHNICAL_ISSUE_RESPONSE

    try:
        raw_input = user_input or ""
        bot_username = getattr(context.bot, "username", None)
        raw_input = replace_bot_mentions(raw_input, bot_username)
        normalized_input = normalize_input(raw_input)

        user_obj = user
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

        bullying_category = detect_bullying_category(normalized_input)
        if bullying_category:
            print(f"[{now_str()}] BULLYING REPORT DETECTED ({bullying_category.upper()}) - FLAGGING CHAT")
            severity = "critical" if bullying_category == CATEGORY_SEXUAL else (
                "high" if bullying_category == CATEGORY_PHYSICAL else "medium"
            )
            if chat_log_id is not None:
                try:
                    record_bullying_report(
                        chat_log_id,
                        user_id,
                        username,
                        normalized_input,
                        category=bullying_category,
                        severity=severity,
                        metadata={"source": "web"},
                    )
                except Exception as exc:
                    print(f"[{now_str()}] [ERROR] Failed to record bullying report: {exc}")
            else:
                print(f"[{now_str()}] [WARN] Could not persist bullying report because chat_log_id missing")
            response = get_bullying_ack_response(bullying_category)
            save_chat(user_id, "ASKA", response, role="aska")
            return response

        psych_sessions = context.chat_data.setdefault("psych_sessions", {})
        psych_session = psych_sessions.get(storage_key)

        if psych_session:
            last_bot_time = psych_session.get("last_bot_time")
            if last_bot_time and (now_ts - last_bot_time) > PSYCH_TIMEOUT_SECONDS:
                response = PSYCH_TIMEOUT_MESSAGE
                save_chat(user_id, "ASKA", response, role="aska")
                psych_sessions.pop(storage_key, None)
                psych_session = None
                return response

        def _persist_psych_report(
            message_text: str,
            *,
            severity_value: str,
            stage_label: Optional[str],
            status_value: str = "open",
            base_chat_log_id: Optional[int] = None,
        ) -> None:
            if not message_text:
                return
            target_chat_log_id = base_chat_log_id if base_chat_log_id is not None else chat_log_id
            try:
                record_psych_report(
                    target_chat_log_id,
                    user_id,
                    username,
                    message_text,
                    severity=severity_value,
                    status=status_value,
                    summary=summarize_psych_message(message_text),
                    metadata={
                        "stage": stage_label,
                        "source": "web",
                    },
                )
            except Exception as exc:
                print(f"[{now_str()}] [ERROR] Failed to record psych report: {exc}")

        if psych_session and psych_session.get("state") == "awaiting_confirmation":
            if is_psych_positive_confirmation(raw_input):
                severity_value = psych_session.get("severity", SEVERITY_GENERAL)
                first_stage = psych_next_stage(None)
                psych_session["state"] = "ongoing"
                psych_session["stage"] = first_stage
                validation = get_psych_validation()
                response_parts = [validation]
                if severity_value == SEVERITY_CRITICAL:
                    response_parts.append(get_psych_critical_message())
                if first_stage and psych_stage_exists(first_stage):
                    support_text = get_psych_support_message(
                        psych_session.get("initial_message", ""),
                        stage=first_stage,
                        severity=severity_value,
                    )
                    if support_text:
                        response_parts.append(support_text)
                    response_parts.append(get_psych_stage_prompt(first_stage))
                else:
                    response_parts.append(get_psych_closing_message())
                    psych_sessions.pop(storage_key, None)
                if initial_message := psych_session.get("initial_message"):
                    initial_chat_log_id = psych_session.get("initial_chat_log_id")
                    _persist_psych_report(
                        initial_message,
                        severity_value=severity_value,
                        stage_label="initial",
                        base_chat_log_id=initial_chat_log_id,
                    )
                    psych_session.pop("initial_message", None)
                    psych_session.pop("initial_chat_log_id", None)
                reply_text = "\n\n".join(response_parts)
                save_chat(user_id, "ASKA", reply_text, role="aska")
                if storage_key in psych_sessions:
                    psych_sessions[storage_key]["last_bot_time"] = time.time()
                return reply_text

            if is_psych_negative_confirmation(raw_input):
                severity_value = psych_session.get("severity", SEVERITY_GENERAL)
                response = (
                    "Oke, tidak apa-apa. Kalau nanti butuh teman cerita lagi, ASKA siap standby 😊"
                )
                if severity_value == SEVERITY_CRITICAL:
                    response = (
                        f"{response}\n\n{get_psych_critical_message()}"
                    )
                save_chat(user_id, "ASKA", response, role="aska")
                psych_sessions.pop(storage_key, None)
                return response

            reminder = "Kalau mau lanjut laporan konseling, tinggal jawab 'iya'. Kalau enggak, bilang aja 'nggak' ya."
            save_chat(user_id, "ASKA", reminder, role="aska")
            psych_session["last_bot_time"] = time.time()
            return reminder

        if psych_session and psych_session.get("state") == "ongoing":
            if is_psych_stop_request(raw_input):
                closing = get_psych_closing_message()
                if psych_session.get("severity") == SEVERITY_CRITICAL:
                    closing = f"{closing}\n\n{get_psych_critical_message()}"
                save_chat(user_id, "ASKA", closing, role="aska")
                psych_sessions.pop(storage_key, None)
                return closing

            current_severity = psych_session.get("severity", SEVERITY_GENERAL)
            message_severity = classify_message_severity(raw_input, default=current_severity)
            if PSYCH_SEVERITY_RANK.get(message_severity, 0) > PSYCH_SEVERITY_RANK.get(current_severity, 0):
                psych_session["severity"] = message_severity
                current_severity = message_severity

            current_stage = psych_session.get("stage")
            if not current_stage or not psych_stage_exists(current_stage):
                current_stage = psych_next_stage(None)
                psych_session["stage"] = current_stage

            _persist_psych_report(
                raw_input,
                severity_value=current_severity,
                stage_label=current_stage,
            )

            response_parts = [get_psych_validation()]
            if current_severity == SEVERITY_CRITICAL:
                response_parts.append(get_psych_critical_message())

            support_stage = current_stage
            support_text = get_psych_support_message(
                raw_input,
                stage=support_stage,
                severity=current_severity,
            )
            if support_text:
                response_parts.append(support_text)

            next_stage_value = psych_next_stage(current_stage) if current_stage else None
            if next_stage_value and psych_stage_exists(next_stage_value):
                psych_session["stage"] = next_stage_value
                response_parts.append(get_psych_stage_prompt(next_stage_value))
            else:
                response_parts.append(get_psych_closing_message())
                psych_sessions.pop(storage_key, None)

            reply_text = "\n\n".join(response_parts)
            save_chat(user_id, "ASKA", reply_text, role="aska")
            if storage_key in psych_sessions:
                psych_sessions[storage_key]["last_bot_time"] = time.time()
            return reply_text

        if not psych_session:
            psych_severity = detect_psych_intent(raw_input)
            if psych_severity:
                confirmation = get_psych_confirmation_prompt(psych_severity)
                psych_sessions[storage_key] = {
                    "state": "awaiting_confirmation",
                    "severity": psych_severity,
                    "stage": None,
                    "initial_message": raw_input,
                    "initial_chat_log_id": chat_log_id,
                }
                save_chat(user_id, "ASKA", confirmation, role="aska")
                psych_sessions[storage_key]["last_bot_time"] = time.time()
                return confirmation

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

        if teacher_session and teacher_session.get("question"):
            question = teacher_session["question"]
            conversation: List[dict[str, str]] = teacher_session.setdefault("conversation", [])

            if is_teacher_discussion_request(raw_input):
                response_text = generate_discussion_reply(question, conversation, raw_input)
                conversation.append({"role": "user", "content": raw_input})
                conversation.append({"role": "assistant", "content": response_text})
                if len(conversation) > TEACHER_CONVERSATION_LIMIT * 2:
                    conversation[:] = conversation[-TEACHER_CONVERSATION_LIMIT * 2 :]
                save_chat(user_id, "ASKA", response_text, role="aska")
                return response_text

            grade_hint = teacher_session.get("grade_hint")
            subject_hint = teacher_session.get("subject_hint")
            teacher_session["attempt"] = teacher_session.get("attempt", 1) + 1

            conversation.append({"role": "user", "content": raw_input})

            correct, feedback = grade_response(question, raw_input)

            if correct:
                next_question = pick_question(grade_hint, subject_hint, raw_input)
                teacher_session["question"] = next_question
                teacher_session["attempt"] = 1
                teacher_session["subject_hint"] = subject_hint or next_question.subject
                next_intro = format_question_intro(next_question, attempt_number=2)
                feedback = f"{feedback}\n\nSoal berikutnya:\n{next_intro}"
            else:
                feedback = (
                    f"{feedback}\n\nBoleh coba lagi atau ketik 'lanjut soal' untuk ganti pertanyaan."
                )

            conversation.append({"role": "assistant", "content": feedback})
            if len(conversation) > TEACHER_CONVERSATION_LIMIT * 2:
                conversation[:] = conversation[-TEACHER_CONVERSATION_LIMIT * 2 :]
            teacher_session["conversation"] = conversation

            save_chat(user_id, "ASKA", feedback, role="aska")
            if storage_key in teacher_sessions:
                teacher_sessions[storage_key]["last_bot_time"] = time.time()
            return feedback

        if contains_inappropriate_language(normalized_input):
            response = get_advice_response()
            save_chat(user_id, "ASKA", response, role="aska")
            return response

        if is_relationship_question(normalized_input):
            response = get_relationship_advice_response()
            save_chat(user_id, "ASKA", response, role="aska")
            return response

        if is_greeting_message(normalized_input):
            response = get_time_based_greeting_response(normalized_input) or get_greeting_response()
            save_chat(user_id, "ASKA", response, role="aska")
            return response

        if is_thank_you_message(normalized_input):
            response = get_thank_you_response()
            save_chat(user_id, "ASKA", response, role="aska")
            return response

        if is_acknowledgement_message(normalized_input):
            response = get_acknowledgement_response()
            save_chat(user_id, "ASKA", response, role="aska")
            return response

        if is_farewell_message(normalized_input):
            response = get_farewell_response()
            save_chat(user_id, "ASKA", response, role="aska")
            return response

        if is_self_intro_message(normalized_input):
            response = get_self_intro_response()
            save_chat(user_id, "ASKA", response, role="aska")
            return response

        if is_status_message(normalized_input):
            response = get_status_response()
            save_chat(user_id, "ASKA", response, role="aska")
            return response

        normalized_input = rewrite_schedule_query(normalized_input)

        print(f"[{now_str()}] ASKA sedang berpikir...")

        history_from_db = get_chat_history(user_id, limit=5)
        chat_history = format_history_for_chain(history_from_db)

        start_time = time.perf_counter()

        result = await asyncio.to_thread(qa_chain.invoke, {"input": normalized_input, "chat_history": chat_history})

        print(f"[{now_str()}] ?? ASKA AMBIL {len(result['context'])} KONTEN:")
        for i, doc in enumerate(result["context"], 1):
            print(f"  {i}. {doc.page_content[:200]}...")

        response = coerce_to_text(result)

        if not response.strip():
            response = ASKA_NO_DATA_RESPONSE

        # Image response handling is removed for simplicity in web version

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
        # In web, we just return the technical issue response
        return ASKA_TECHNICAL_ISSUE_RESPONSE
