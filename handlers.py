# handlers.py
import logging
import asyncio
import os


import tempfile
import time
from typing import List, Optional, Set

from telegram import Message, Update
from telegram.error import NetworkError
from telegram.ext import ContextTypes

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
    is_corruption_report_intent,
    CorruptionResponse,
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
    send_typing_once,
    keep_typing_indicator,
    send_thinking_bubble,
    reply_with_markdown,
    replace_bot_mentions,
    should_respond,
    resolve_target_message,
    prepare_group_query,
)

load_dotenv()
qa_chain = build_qa_chain()
audio_client = OpenAI()

STT_MODELS: list[str] = []
_env_model = os.getenv("OPENAI_STT_MODEL")
if _env_model:
    STT_MODELS.append(_env_model)
if "gpt-4o-mini-transcribe" not in STT_MODELS:
    STT_MODELS.append("gpt-4o-mini-transcribe")
if "whisper-1" not in STT_MODELS:
    STT_MODELS.append("whisper-1")

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


def transcribe_audio(path: str) -> str:
    last_error: Optional[Exception] = None
    for model in STT_MODELS:
        try:
            with open(path, "rb") as audio_file:
                result = audio_client.audio.transcriptions.create(
                    model=model,
                    file=audio_file,
                    response_format="text",
                )
            if isinstance(result, str):
                text = result
            else:
                text = getattr(result, "text", None)
                if text is None and isinstance(result, dict):
                    text = result.get("text")
            if text:
                return text
        except Exception as exc:  # pragma: no cover - network / API errors
            last_error = exc
            continue
    if last_error:
        raise last_error
    return ""


async def handle_user_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_input: str,
    *,
    source: str = "text",
    reply_target: Optional[Message] = None,
    target_user=None,
    responded_store: Optional[Set] = None,
    responded_key=None,
) -> bool:
    reply_message = reply_target or update.message
    if reply_message is None:
        return False

    try:
        raw_input = user_input or ""
        bot_username = getattr(context.bot, "username", None)
        raw_input = replace_bot_mentions(raw_input, bot_username)
        normalized_input = normalize_input(raw_input)

        user_obj = target_user or getattr(reply_message, "from_user", None) or update.effective_user
        user_id = getattr(user_obj, "id", None) or update.effective_user.id
        username = (
            getattr(user_obj, "username", None)
            or getattr(user_obj, "first_name", None)
            or "anon"
        )

        def log_response(module_name: str):
            logging.info(
                f'User "{username}" triggered response from "{module_name}" with message: "{normalized_input}"'
            )

        print(
            f"[{now_str()}] HANDLER CALLED ({source.upper()}) - FROM {username}: {normalized_input}"
        )

        storage_key = user_id if user_id is not None else f"anon:{username}"

        recent_messages_root = context.chat_data.setdefault("recent_messages_by_user", {})
        recent_messages = recent_messages_root.setdefault(storage_key, {})
        now_ts = time.time()
        for msg_text, ts in list(recent_messages.items()):
            if (now_ts - ts) > 600:
                del recent_messages[msg_text]
        last_ts = recent_messages.get(normalized_input)
        if last_ts is not None and (now_ts - last_ts) < 60:
            print(f"[{now_str()}] DUPLICATE MESSAGE RECEIVED WITHIN 60s - SKIPPING")
            return False
        recent_messages[normalized_input] = now_ts

        print(f"[{now_str()}] SAVING USER MESSAGE")
        topic = source if source != "text" else None
        chat_log_id = save_chat(user_id, username, normalized_input, role="user", topic=topic)

        def mark_responded():
            if responded_store is not None and responded_key is not None:
                responded_store.add(responded_key)

        bullying_category = detect_bullying_category(normalized_input)
        if bullying_category:
            log_response("bullying.py")
            print(f"[{now_str()}]BULLYING REPORT DETECTED ({bullying_category.upper()}) - FLAGGING CHAT")
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
                        metadata={"source": source},
                    )
                except Exception as exc:
                    print(f"[{now_str()}] [ERROR] Failed to record bullying report: {exc}")
            else:
                print(f"[{now_str()}] [WARN] Could not persist bullying report because chat_log_id missing")
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            response = get_bullying_ack_response(bullying_category)
            await reply_message.reply_text(response)
            save_chat(user_id, "ASKA", response, role="aska")
            mark_responded()
            return True

        # Handle corruption reporting session
        corruption_sessions = context.chat_data.setdefault("corruption_sessions", {})
        corruption_session = corruption_sessions.get(storage_key)

        if corruption_session:
            # User is in a corruption reporting flow
            response = corruption_session.handle_response(raw_input)
            if response:
                await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
                await reply_message.reply_text(response)
                save_chat(user_id, "ASKA", response, role="aska")
                # If the report is finalized, clear the session
                if corruption_session.state == "idle":
                    corruption_sessions.pop(storage_key, None)
                mark_responded()
                return True

        if is_corruption_report_intent(normalized_input):
            print(f"[{now_str()}] CORRUPTION REPORT INTENT DETECTED - STARTING FLOW")
            session = CorruptionResponse(user_id)
            response = session.start_report()
            corruption_sessions[storage_key] = session
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            await reply_message.reply_text(response)
            save_chat(user_id, "ASKA", response, role="aska")
            mark_responded()
            return True

        psych_sessions = context.chat_data.setdefault("psych_sessions", {})
        psych_session = psych_sessions.get(storage_key)

        if psych_session:
            last_bot_time = psych_session.get("last_bot_time")
            if last_bot_time and (now_ts - last_bot_time) > PSYCH_TIMEOUT_SECONDS:
                await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
                await reply_message.reply_text(PSYCH_TIMEOUT_MESSAGE)
                save_chat(user_id, "ASKA", PSYCH_TIMEOUT_MESSAGE, role="aska")
                psych_sessions.pop(storage_key, None)
                psych_session = None

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
                        "source": source,
                    },
                )
            except Exception as exc:
                print(f"[{now_str()}] [ERROR] Failed to record psych report: {exc}")

        if psych_session and psych_session.get("state") == "awaiting_confirmation":
            if is_psych_positive_confirmation(raw_input):
                log_response("psychologist.py")
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
                await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
                await reply_message.reply_text(reply_text)
                save_chat(user_id, "ASKA", reply_text, role="aska")
                if storage_key in psych_sessions:
                    psych_sessions[storage_key]["last_bot_time"] = time.time()
                mark_responded()
                return True
            if is_psych_negative_confirmation(raw_input):
                log_response("psychologist.py")
                severity_value = psych_session.get("severity", SEVERITY_GENERAL)
                response = (
                    "Oke, tidak apa-apa. Kalau nanti butuh teman cerita lagi, ASKA siap standby 😊"
                )
                if severity_value == SEVERITY_CRITICAL:
                    response = (
                        f"{response}\n\n{get_psych_critical_message()}"
                    )
                await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
                await reply_message.reply_text(response)
                save_chat(user_id, "ASKA", response, role="aska")
                psych_sessions.pop(storage_key, None)
                mark_responded()
                return True
            reminder = "Kalau mau lanjut laporan konseling, tinggal jawab 'iya'. Kalau enggak, bilang aja 'nggak' ya."
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            await reply_message.reply_text(reminder)
            save_chat(user_id, "ASKA", reminder, role="aska")
            psych_session["last_bot_time"] = time.time()
            mark_responded()
            return True

        if psych_session and psych_session.get("state") == "ongoing":
            if is_psych_stop_request(raw_input):
                log_response("psychologist.py")
                closing = get_psych_closing_message()
                if psych_session.get("severity") == SEVERITY_CRITICAL:
                    closing = f"{closing}\n\n{get_psych_critical_message()}"
                await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
                await reply_message.reply_text(closing)
                save_chat(user_id, "ASKA", closing, role="aska")
                psych_sessions.pop(storage_key, None)
                mark_responded()
                return True

            log_response("psychologist.py")
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
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            await reply_message.reply_text(reply_text)
            save_chat(user_id, "ASKA", reply_text, role="aska")
            if storage_key in psych_sessions:
                psych_sessions[storage_key]["last_bot_time"] = time.time()
            mark_responded()
            return True

        if not psych_session:
            psych_severity = detect_psych_intent(raw_input)
            if psych_severity:
                log_response("psychologist.py")
                confirmation = get_psych_confirmation_prompt(psych_severity)
                psych_sessions[storage_key] = {
                    "state": "awaiting_confirmation",
                    "severity": psych_severity,
                    "stage": None,
                    "initial_message": raw_input,
                    "initial_chat_log_id": chat_log_id,
                }
                await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
                await reply_message.reply_text(confirmation)
                save_chat(user_id, "ASKA", confirmation, role="aska")
                psych_sessions[storage_key]["last_bot_time"] = time.time()
                mark_responded()
                return True

        teacher_sessions = context.chat_data.setdefault("teacher_sessions", {})
        teacher_session = teacher_sessions.get(storage_key)

        if teacher_session:
            last_bot_time = teacher_session.get("last_bot_time")
            if last_bot_time and (now_ts - last_bot_time) > TEACHER_TIMEOUT_SECONDS:
                await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
                await reply_message.reply_text(TEACHER_TIMEOUT_MESSAGE)
                save_chat(user_id, "ASKA", TEACHER_TIMEOUT_MESSAGE, role="aska")
                teacher_sessions.pop(storage_key, None)
                teacher_session = None

        if is_teacher_stop(normalized_input):
            if teacher_session:
                log_response("teacher.py")
                teacher_sessions.pop(storage_key, None)
                farewell = (
                    "Sesi belajar bersama ASKA selesai. Kapan pun mau latihan lagi, ketik saja "
                    "'kasih soal' atau 'mode guru', ya!"
                )
                await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
                await reply_message.reply_text(farewell)
                save_chat(user_id, "ASKA", farewell, role="aska")
                mark_responded()
                return True

        if is_teacher_start(normalized_input):
            log_response("teacher.py")
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
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            await reply_message.reply_text(intro)
            save_chat(user_id, "ASKA", intro, role="aska")
            session_data["conversation"].append({"role": "assistant", "content": intro})
            session_data["last_bot_time"] = time.time()
            mark_responded()
            return True

        if not teacher_session and is_teacher_next(normalized_input):
            log_response("teacher.py")
            reminder = (
                "Belum ada sesi guru yang aktif. Ketik 'kasih soal' atau 'mode guru' dulu ya."
            )
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            await reply_message.reply_text(reminder)
            save_chat(user_id, "ASKA", reminder, role="aska")
            mark_responded()
            return True

        if teacher_session and is_teacher_next(normalized_input):
            log_response("teacher.py")
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
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            await reply_message.reply_text(intro)
            save_chat(user_id, "ASKA", intro, role="aska")
            teacher_session["conversation"].append({"role": "assistant", "content": intro})
            teacher_session["last_bot_time"] = time.time()
            mark_responded()
            return True

        if teacher_session and teacher_session.get("question"):
            question = teacher_session["question"]
            conversation: List[dict[str, str]] = teacher_session.setdefault("conversation", [])

            if is_teacher_discussion_request(raw_input):
                log_response("teacher.py")
                response_text = generate_discussion_reply(question, conversation, raw_input)
                conversation.append({"role": "user", "content": raw_input})
                conversation.append({"role": "assistant", "content": response_text})
                if len(conversation) > TEACHER_CONVERSATION_LIMIT * 2:
                    conversation[:] = conversation[-TEACHER_CONVERSATION_LIMIT * 2 :]
                await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
                await reply_message.reply_text(response_text)
                save_chat(user_id, "ASKA", response_text, role="aska")
                mark_responded()
                return True

            log_response("teacher.py")
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

            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            await reply_message.reply_text(feedback)
            save_chat(user_id, "ASKA", feedback, role="aska")
            if storage_key in teacher_sessions:
                teacher_sessions[storage_key]["last_bot_time"] = time.time()
            mark_responded()
            return True

        if contains_inappropriate_language(normalized_input):
            log_response("advice.py")
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            response = get_advice_response()
            await reply_message.reply_text(response)
            save_chat(user_id, "ASKA", response, role="aska")
            mark_responded()
            return True

        if is_relationship_question(normalized_input):
            log_response("relationship.py")
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            response = get_relationship_advice_response()
            await reply_message.reply_text(response)
            save_chat(user_id, "ASKA", response, role="aska")
            mark_responded()
            return True

        if is_greeting_message(normalized_input):
            log_response("greeting.py")
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            response = get_time_based_greeting_response(normalized_input) or get_greeting_response()
            await reply_message.reply_text(response, parse_mode="Markdown")
            save_chat(user_id, "ASKA", response, role="aska")
            mark_responded()
            return True

        if is_thank_you_message(normalized_input):
            log_response("thank_you.py")
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            response = get_thank_you_response()
            await reply_message.reply_text(response, parse_mode="Markdown")
            save_chat(user_id, "ASKA", response, role="aska")
            mark_responded()
            return True

        if is_acknowledgement_message(normalized_input):
            log_response("acknowledgement.py")
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            response = get_acknowledgement_response()
            await reply_message.reply_text(response)
            save_chat(user_id, "ASKA", response, role="aska")
            mark_responded()
            return True

        if is_farewell_message(normalized_input):
            log_response("farewell.py")
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            response = get_farewell_response()
            await reply_message.reply_text(response)
            save_chat(user_id, "ASKA", response, role="aska")
            mark_responded()
            return True

        if is_self_intro_message(normalized_input):
            log_response("self_intro.py")
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            response = get_self_intro_response()
            await reply_message.reply_text(response)
            save_chat(user_id, "ASKA", response, role="aska")
            mark_responded()
            return True

        if is_status_message(normalized_input):
            log_response("status.py")
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            response = get_status_response()
            await reply_message.reply_text(response)
            save_chat(user_id, "ASKA", response, role="aska")
            mark_responded()
            return True

        normalized_input = rewrite_schedule_query(normalized_input)

        await send_typing_once(context.bot, update.effective_chat.id, delay=0)
        print(f"[{now_str()}] ASKA sedang mengetik...")

        history_from_db = get_chat_history(user_id, limit=5, offset=0)
        chat_history = format_history_for_chain(history_from_db)

        start_time = time.perf_counter()

        typing_task = asyncio.create_task(
            keep_typing_indicator(context.bot, update.effective_chat.id)
        )

        thinking_message = None
        try:
            thinking_message = await send_thinking_bubble(reply_message)
            await asyncio.sleep(1.0)
            result = qa_chain.invoke({"input": normalized_input, "chat_history": chat_history})
        finally:
            typing_task.cancel()

        print(f"[{now_str()}] ?? ASKA AMBIL {len(result['context'])} KONTEN:")
        for i, doc in enumerate(result["context"], 1):
            print(f"  {i}. {doc.page_content[:200]}...")

        response = coerce_to_text(result)

        if not response.strip():
            response = ASKA_NO_DATA_RESPONSE

        try:
            if thinking_message:
                await thinking_message.delete()
                print(f"[{now_str()}] Thinking bubble deleted")
        except Exception as e:
            print(f"[{now_str()}] Failed to delete thinking bubble: {e}")

        match = IMG_MD.search(response)
        if match:
            img_url = match.group(1)
            caption = IMG_MD.sub("", response).strip()[:1024]
            caption = strip_markdown(caption)
            await reply_message.reply_photo(photo=img_url, caption=caption)
        else:
            await reply_with_markdown(reply_message, response)

        duration_ms = (time.perf_counter() - start_time) * 1000
        print(f"[{now_str()}] ASKA : {response} ?? {duration_ms:.2f} ms")
        save_chat(
            user_id,
            "ASKA",
            strip_markdown(response),
            role="aska",
            topic=source if source != "text" else None,
            response_time_ms=int(duration_ms),
        )

        mark_responded()
        return True

    except Exception as e:
        print(f"[{now_str()}] [ERROR] {e}")

        try:
            if "thinking_message" in locals() and thinking_message:
                await thinking_message.delete()
        except Exception:
            pass

        target_for_error = reply_message or update.message
        if target_for_error:
            if isinstance(e, NetworkError):
                print(f"[{now_str()}] [WARN] Skipping error reply due to network issue: {e}")
            else:
                try:
                    await target_for_error.reply_text(
                        ASKA_TECHNICAL_ISSUE_RESPONSE,
                        parse_mode="Markdown",
                    )
                except NetworkError as send_exc:
                    print(f"[{now_str()}] [WARN] Failed to send technical issue notice: {send_exc}")
                except Exception as send_exc:
                    print(f"[{now_str()}] [WARN] Unexpected error while sending technical issue notice: {send_exc}")

    return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_typing_once(context.bot, update.effective_chat.id)

    user = update.effective_user
    name = user.first_name or user.username or "bestie"
    response = (
        f"Yoo, {name}! ??\n"
        f"Aku *ASKA*, bestie AI kamu ???\n"
        f"Mau tanya apa aja soal sekolah? Gaskeun~ ??"
    )
    await update.message.reply_text(response, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not should_respond(update, context.bot):
        return

    trigger_message, target_message = resolve_target_message(update, context.bot)
    bot_username = getattr(context.bot, "username", None)
    user_text, reply_target, target_user, responded_key = prepare_group_query(
        trigger_message, target_message, bot_username
    )

    if not reply_target or not user_text or not user_text.strip():
        return

    responded_store = context.chat_data.setdefault("responded_messages", set())
    dedup_key = responded_key or getattr(reply_target, "message_id", None)
    if dedup_key is not None and dedup_key in responded_store:
        return

    await handle_user_query(
        update,
        context,
        user_text,
        source="text",
        reply_target=reply_target,
        target_user=target_user,
        responded_store=responded_store,
        responded_key=dedup_key,
    )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    if not should_respond(update, context.bot):
        return
    voice = message.voice or message.audio
    if not voice:
        await message.reply_text("Oops, suaranya belum kebaca. Coba kirim ulang ya! ??")
        return

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_file:
        temp_path = tmp_file.name

    try:
        telegram_file = await context.bot.get_file(voice.file_id)
        await telegram_file.download_to_drive(custom_path=temp_path)
        transcription = await asyncio.to_thread(transcribe_audio, temp_path)
    except Exception as exc:
        print(f"[{now_str()}] [VOICE ERROR] {exc}")
        await message.reply_text(
            "ASKA belum bisa dengerin pesan suara kamu nih. Boleh dicoba lagi atau ketik aja ya!"
        )
        return
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass

    if not transcription or not transcription.strip():
        await message.reply_text(
            "ASKA nggak nangkep isi pesan suaranya. Coba rekam ulang dengan suara lebih jelas ya!"
        )
        return

    await handle_user_query(
        update,
        context,
        transcription.strip(),
        source="voice",
        reply_target=message,
        target_user=getattr(message, "from_user", None),
    )
