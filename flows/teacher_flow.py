import time
from typing import List, Optional

from db import save_chat
from responses import (
    extract_grade_hint,
    extract_subject_hint,
    format_question_intro,
    generate_discussion_reply,
    grade_response,
    is_teacher_discussion_request,
    is_teacher_next,
    is_teacher_start,
    is_teacher_stop,
    pick_question,
)
from utils import send_typing_once


async def handle_teacher(
    *,
    update,
    context,
    reply_message,
    raw_input: str,
    normalized_input: str,
    user_id,
    storage_key,
    mark_responded,
    timeout_seconds: int,
    timeout_message: str,
) -> bool:
    """Handle teacher practice session flow.

    Returns True if handled.
    """
    now_ts = time.time()
    teacher_sessions = context.chat_data.setdefault("teacher_sessions", {})
    teacher_session = teacher_sessions.get(storage_key)

    if teacher_session:
        last_bot_time = teacher_session.get("last_bot_time")
        if last_bot_time and (now_ts - last_bot_time) > timeout_seconds:
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            await reply_message.reply_text(timeout_message)
            save_chat(user_id, "ASKA", timeout_message, role="aska")
            teacher_sessions.pop(storage_key, None)
            teacher_session = None

    if is_teacher_stop(normalized_input):
        if teacher_session:
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
        reminder = (
            "Belum ada sesi guru yang aktif. Ketik 'kasih soal' atau 'mode guru' dulu ya."
        )
        await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
        await reply_message.reply_text(reminder)
        save_chat(user_id, "ASKA", reminder, role="aska")
        mark_responded()
        return True

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
            response_text = generate_discussion_reply(question, conversation, raw_input)
            conversation.append({"role": "user", "content": raw_input})
            conversation.append({"role": "assistant", "content": response_text})
            if len(conversation) > 20:
                conversation.pop(0)
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            await reply_message.reply_text(response_text)
            save_chat(user_id, "ASKA", response_text, role="aska")
            teacher_session["last_bot_time"] = time.time()
            mark_responded()
            return True

        # Grading branch
        await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
        correct, feedback = grade_response(question, raw_input)
        conversation.append({"role": "user", "content": raw_input})
        conversation.append({"role": "assistant", "content": feedback})

        if correct:
            next_question = pick_question(teacher_session.get("grade_hint"), teacher_session.get("subject_hint"), raw_input)
            teacher_session["question"] = next_question
            teacher_session["attempt"] = 1
            subject_hint = teacher_session.get("subject_hint")
            teacher_session["subject_hint"] = subject_hint or next_question.subject
            intro_next = format_question_intro(next_question)
            response_text = f"{feedback}\n\n{intro_next}"
        else:
            attempt = teacher_session.get("attempt", 1) + 1
            teacher_session["attempt"] = attempt
            intro_retry = format_question_intro(question, attempt_number=attempt)
            response_text = f"{feedback}\n\n{intro_retry}"

        await reply_message.reply_text(response_text)
        save_chat(user_id, "ASKA", response_text, role="aska")
        teacher_session["conversation"] = conversation
        if storage_key in teacher_sessions:
            teacher_sessions[storage_key]["last_bot_time"] = time.time()
        mark_responded()
        return True

    return False

