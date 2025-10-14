from typing import Optional

from db import save_chat, record_psych_report
from responses import (
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
from utils import now_str, send_typing_once


PSYCH_SEVERITY_RANK = {
    SEVERITY_GENERAL: 0,
    SEVERITY_ELEVATED: 1,
    SEVERITY_CRITICAL: 2,
}


def _persist_psych_report(
    *,
    message_text: str,
    severity_value: str,
    stage_label: Optional[str],
    status_value: str = "open",
    base_chat_log_id: Optional[int] = None,
    chat_log_id: Optional[int],
    user_id,
    username: str,
    source: str,
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
    except Exception as exc:  # pragma: no cover - db/network errors
        print(f"[{now_str()}] [ERROR] Failed to record psych report: {exc}")


async def handle_psych(
    *,
    update,
    context,
    reply_message,
    raw_input: str,
    normalized_input: str,
    user_id,
    username: str,
    storage_key,
    chat_log_id: Optional[int],
    source: str,
    mark_responded,
    timeout_seconds: int,
    timeout_message: str,
    now_ts: float,
) -> bool:
    """Handle psychological counseling conversation flow.

    Returns True if handled.
    """
    psych_sessions = context.chat_data.setdefault("psych_sessions", {})
    psych_session = psych_sessions.get(storage_key)

    if psych_session:
        last_bot_time = psych_session.get("last_bot_time")
        if last_bot_time and (now_ts - last_bot_time) > timeout_seconds:
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            await reply_message.reply_text(timeout_message)
            save_chat(user_id, "ASKA", timeout_message, role="aska")
            psych_sessions.pop(storage_key, None)
            psych_session = None

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
                    message_text=initial_message,
                    severity_value=severity_value,
                    stage_label="initial",
                    base_chat_log_id=initial_chat_log_id,
                    chat_log_id=chat_log_id,
                    user_id=user_id,
                    username=username,
                    source=source,
                )
                psych_session.pop("initial_message", None)
                psych_session.pop("initial_chat_log_id", None)
            reply_text = "\n\n".join(response_parts)
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            await reply_message.reply_text(reply_text)
            save_chat(user_id, "ASKA", reply_text, role="aska")
            if storage_key in psych_sessions:
                psych_sessions[storage_key]["last_bot_time"] = now_ts
            mark_responded()
            return True
        if is_psych_negative_confirmation(raw_input):
            severity_value = psych_session.get("severity", SEVERITY_GENERAL)
            response = (
                "Oke, tidak apa-apa. Kalau nanti butuh teman cerita lagi, ASKA siap standby 😊"
            )
            if severity_value == SEVERITY_CRITICAL:
                response = f"{response}\n\n{get_psych_critical_message()}"
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
        psych_session["last_bot_time"] = now_ts
        mark_responded()
        return True

    if psych_session and psych_session.get("state") == "ongoing":
        if is_psych_stop_request(raw_input):
            closing = get_psych_closing_message()
            if psych_session.get("severity") == SEVERITY_CRITICAL:
                closing = f"{closing}\n\n{get_psych_critical_message()}"
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            await reply_message.reply_text(closing)
            save_chat(user_id, "ASKA", closing, role="aska")
            psych_sessions.pop(storage_key, None)
            mark_responded()
            return True

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
            message_text=raw_input,
            severity_value=current_severity,
            stage_label=current_stage,
            chat_log_id=chat_log_id,
            user_id=user_id,
            username=username,
            source=source,
        )

        response_parts = [get_psych_validation()]
        if current_severity == SEVERITY_CRITICAL:
            response_parts.append(get_psych_critical_message())

        support_text = get_psych_support_message(
            raw_input,
            stage=current_stage,
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
            psych_sessions[storage_key]["last_bot_time"] = now_ts
        mark_responded()
        return True

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
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            await reply_message.reply_text(confirmation)
            save_chat(user_id, "ASKA", confirmation, role="aska")
            psych_sessions[storage_key]["last_bot_time"] = now_ts
            mark_responded()
            return True

    return False
