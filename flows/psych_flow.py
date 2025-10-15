import asyncio
from typing import Optional

from db import save_chat, record_psych_report
from telegram.error import NetworkError
from responses import (
    SEVERITY_CRITICAL,
    SEVERITY_ELEVATED,
    SEVERITY_GENERAL,
    classify_message_severity,
    detect_psych_intent,
    get_psych_closing_message,
    get_psych_conversation_reply,
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
from utils import now_str, send_typing_once, strip_markdown


PSYCH_SEVERITY_RANK = {
    SEVERITY_GENERAL: 0,
    SEVERITY_ELEVATED: 1,
    SEVERITY_CRITICAL: 2,
}


def _aggregate_messages(messages):
    chunks = [item["text"] for item in messages if item.get("text")]
    return "\n\n".join(chunks).strip()


def _summarize_snippet(text: Optional[str], limit: int = 80) -> str:
    if not text:
        return ""
    cleaned = " ".join(text.strip().split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1].rstrip()}…"


def _store_psych_session(session_data: dict, *, reason: str, aggregated_text: Optional[str] = None) -> None:
    messages = session_data.get("messages") or []
    if aggregated_text is None:
        aggregated_text = _aggregate_messages(messages)
    if not aggregated_text:
        return
    severity_value = session_data.get("severity", SEVERITY_GENERAL)
    stage_label = session_data.get("stage") or "completed"
    base_chat_log_id = session_data.get("base_chat_log_id")
    if base_chat_log_id is None:
        for item in messages:
            chat_id = item.get("chat_log_id")
            if chat_id is not None:
                base_chat_log_id = chat_id
                break
    chat_log_id = messages[-1].get("chat_log_id") if messages else session_data.get("base_chat_log_id")
    metadata_extra = {
        "message_count": len(messages),
        "severity_history": session_data.get("severity_history"),
        "stage_history": session_data.get("stage_history"),
        "ended_by": reason,
        "chat_log_ids": [msg.get("chat_log_id") for msg in messages if msg.get("chat_log_id") is not None],
        "timeout_seconds": session_data.get("timeout_seconds"),
    }
    _persist_psych_report(
        message_text=aggregated_text,
        severity_value=severity_value,
        stage_label=stage_label,
        base_chat_log_id=base_chat_log_id,
        chat_log_id=chat_log_id,
        user_id=session_data.get("user_id"),
        username=session_data.get("username"),
        source=session_data.get("source", "text"),
        metadata_extra=metadata_extra,
    )


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
    metadata_extra: Optional[dict] = None,
) -> None:
    if not message_text:
        return
    target_chat_log_id = base_chat_log_id if base_chat_log_id is not None else chat_log_id
    metadata = {
        "stage": stage_label,
        "source": source,
    }
    if metadata_extra:
        for key, value in metadata_extra.items():
            if value not in (None, "", [], {}):
                metadata[key] = value
    try:
        record_psych_report(
            target_chat_log_id,
            user_id,
            username,
            message_text,
            severity=severity_value,
            status=status_value,
            summary=summarize_psych_message(message_text),
            metadata=metadata,
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

    async def _send_message(text: str) -> None:
        if not text:
            return
        await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
        sent_successfully = False
        for attempt in range(10):
            try:
                await reply_message.reply_text(text)
                save_chat(user_id, "ASKA", text, role="aska")
                sent_successfully = True
                break
            except NetworkError as exc:  # pragma: no cover - network flakiness
                print(f"[{now_str()}] Network error sending psych reply (attempt {attempt+1}/10): {exc}")
                if attempt < 9:
                    await asyncio.sleep(5)
        if not sent_successfully:
            try:
                fallback = strip_markdown(text)
                await reply_message.reply_text(fallback)
                save_chat(user_id, "ASKA", fallback, role="aska")
            except Exception:
                pass

    if psych_session:
        last_bot_time = psych_session.get("last_bot_time")
        if last_bot_time and (now_ts - last_bot_time) > timeout_seconds:
            _store_psych_session(psych_session, reason="timeout")
            await _send_message(timeout_message)
            psych_sessions.pop(storage_key, None)
            psych_session = None

    if psych_session and psych_session.get("state") == "awaiting_confirmation":
        if is_psych_positive_confirmation(raw_input):
            severity_value = psych_session.get("severity", SEVERITY_GENERAL)
            first_stage = psych_next_stage(None)
            psych_session["state"] = "ongoing"
            psych_session["stage"] = first_stage
            session_messages = psych_session.setdefault("messages", [])
            if not session_messages and psych_session.get("initial_message"):
                session_messages.append(
                    {
                        "text": psych_session.get("initial_message"),
                        "chat_log_id": psych_session.get("initial_chat_log_id"),
                    }
                )
            if psych_session.get("base_chat_log_id") is None:
                for item in session_messages:
                    chat_id = item.get("chat_log_id")
                    if chat_id is not None:
                        psych_session["base_chat_log_id"] = chat_id
                        break
            psych_session.setdefault("user_id", user_id)
            psych_session.setdefault("username", username)
            psych_session.setdefault("source", source)
            psych_session.setdefault("timeout_seconds", timeout_seconds)
            severity_history = psych_session.setdefault("severity_history", [])
            if not severity_history:
                severity_history.append(severity_value)
            stage_history = psych_session.setdefault("stage_history", [])
            if first_stage and (not stage_history or stage_history[-1] != first_stage):
                stage_history.append(first_stage)
            psych_session["last_user_time"] = now_ts
            aggregated_text = _aggregate_messages(session_messages)
            latest_text = (
                session_messages[-1]["text"]
                if session_messages
                else psych_session.get("initial_message", "") or raw_input
            )
            llm_reply = get_psych_conversation_reply(
                aggregated_text=aggregated_text,
                latest_message=latest_text,
                stage=first_stage,
                next_stage=None,
                severity=severity_value,
                message_index=len(session_messages) or 1,
            )
            psych_session.pop("initial_message", None)
            psych_session.pop("initial_chat_log_id", None)
            if llm_reply:
                await _send_message(llm_reply)
            else:
                validation = get_psych_validation(_summarize_snippet(latest_text))
                response_parts = [validation]
                if severity_value == SEVERITY_CRITICAL:
                    response_parts.append(get_psych_critical_message())
                if first_stage and psych_stage_exists(first_stage):
                    support_text = get_psych_support_message(
                        latest_text,
                        stage=first_stage,
                        severity=severity_value,
                        aggregated_text=aggregated_text,
                        message_index=len(session_messages) or 1,
                    )
                    if support_text:
                        response_parts.append(support_text)
                    response_parts.append(get_psych_stage_prompt(first_stage))
                else:
                    _store_psych_session(
                        psych_session,
                        reason="initial_stage_missing",
                        aggregated_text=aggregated_text,
                    )
                    response_parts.append(
                        get_psych_closing_message(
                            aggregated_text=aggregated_text,
                            severity=severity_value,
                        )
                    )
                    psych_sessions.pop(storage_key, None)
                reply_text = "\n\n".join(part for part in response_parts if part)
                await _send_message(reply_text)
            if storage_key in psych_sessions:
                psych_sessions[storage_key]["last_bot_time"] = now_ts
                psych_sessions[storage_key]["last_user_time"] = now_ts
            mark_responded()
            return True
        if is_psych_negative_confirmation(raw_input):
            severity_value = psych_session.get("severity", SEVERITY_GENERAL)
            response = (
                "Oke, tidak apa-apa. Kalau nanti butuh teman cerita lagi, ASKA siap standby 😊"
            )
            if severity_value == SEVERITY_CRITICAL:
                response = f"{response}\n\n{get_psych_critical_message()}"
            aggregated_text = _aggregate_messages(psych_session.get("messages", []))
            _store_psych_session(psych_session, reason="declined_confirmation", aggregated_text=aggregated_text)
            await _send_message(response)
            psych_sessions.pop(storage_key, None)
            mark_responded()
            return True
        reminder = "Kalau mau lanjut laporan konseling, tinggal jawab 'iya'. Kalau enggak, bilang aja 'nggak' ya."
        await _send_message(reminder)
        psych_session["last_bot_time"] = now_ts
        mark_responded()
        return True

    if psych_session and psych_session.get("state") == "ongoing":
        if is_psych_stop_request(raw_input):
            aggregated_text = _aggregate_messages(psych_session.get("messages", []))
            severity_value = psych_session.get("severity", SEVERITY_GENERAL)
            _store_psych_session(psych_session, reason="user_stop", aggregated_text=aggregated_text)
            closing = get_psych_closing_message(
                aggregated_text=aggregated_text,
                severity=severity_value,
            )
            if severity_value == SEVERITY_CRITICAL:
                closing = f"{closing}\n\n{get_psych_critical_message()}"
            await _send_message(closing)
            psych_sessions.pop(storage_key, None)
            mark_responded()
            return True

        session_messages = psych_session.setdefault("messages", [])
        psych_session.setdefault("user_id", user_id)
        psych_session.setdefault("username", username)
        psych_session.setdefault("source", source)
        psych_session.setdefault("timeout_seconds", timeout_seconds)
        session_messages.append({"text": raw_input, "chat_log_id": chat_log_id})
        if psych_session.get("base_chat_log_id") is None and chat_log_id is not None:
            psych_session["base_chat_log_id"] = chat_log_id
        psych_session["last_user_time"] = now_ts
        aggregated_text = _aggregate_messages(session_messages)

        current_severity = psych_session.get("severity", SEVERITY_GENERAL)
        message_severity = classify_message_severity(raw_input, default=current_severity)
        if PSYCH_SEVERITY_RANK.get(message_severity, 0) > PSYCH_SEVERITY_RANK.get(current_severity, 0):
            psych_session["severity"] = message_severity
            current_severity = message_severity
        severity_history = psych_session.setdefault("severity_history", [])
        if not severity_history or severity_history[-1] != current_severity:
            severity_history.append(current_severity)

        current_stage = psych_session.get("stage")
        if not current_stage or not psych_stage_exists(current_stage):
            current_stage = psych_next_stage(None)
            psych_session["stage"] = current_stage
        stage_history = psych_session.setdefault("stage_history", [])
        if current_stage and (not stage_history or stage_history[-1] != current_stage):
            stage_history.append(current_stage)

        next_stage_value = psych_next_stage(current_stage) if current_stage else None
        llm_reply = get_psych_conversation_reply(
            aggregated_text=aggregated_text,
            latest_message=raw_input,
            stage=current_stage,
            next_stage=next_stage_value if next_stage_value and psych_stage_exists(next_stage_value) else None,
            severity=current_severity,
            message_index=len(session_messages),
        )
        if llm_reply:
            await _send_message(llm_reply)
            if next_stage_value and psych_stage_exists(next_stage_value):
                psych_session["stage"] = next_stage_value
                stage_history = psych_session.setdefault("stage_history", [])
                if next_stage_value and (not stage_history or stage_history[-1] != next_stage_value):
                    stage_history.append(next_stage_value)
            else:
                _store_psych_session(
                    psych_session,
                    reason="stage_complete",
                    aggregated_text=aggregated_text,
                )
                psych_sessions.pop(storage_key, None)
        else:
            last_snippet = _summarize_snippet(raw_input)
            response_parts = [get_psych_validation(last_snippet)]
            if current_severity == SEVERITY_CRITICAL:
                response_parts.append(get_psych_critical_message())

            support_text = get_psych_support_message(
                raw_input,
                stage=current_stage,
                severity=current_severity,
                aggregated_text=aggregated_text,
                message_index=len(session_messages),
            )
            if support_text:
                response_parts.append(support_text)

            if next_stage_value and psych_stage_exists(next_stage_value):
                psych_session["stage"] = next_stage_value
                stage_history = psych_session.setdefault("stage_history", [])
                if next_stage_value and (not stage_history or stage_history[-1] != next_stage_value):
                    stage_history.append(next_stage_value)
                response_parts.append(get_psych_stage_prompt(next_stage_value))
            else:
                _store_psych_session(
                    psych_session,
                    reason="stage_complete",
                    aggregated_text=aggregated_text,
                )
                response_parts.append(
                    get_psych_closing_message(
                        aggregated_text=aggregated_text,
                        severity=current_severity,
                    )
                )
                psych_sessions.pop(storage_key, None)

            reply_text = "\n\n".join(part for part in response_parts if part)
            await _send_message(reply_text)

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
                "messages": [{"text": raw_input, "chat_log_id": chat_log_id}],
                "base_chat_log_id": chat_log_id,
                "user_id": user_id,
                "username": username,
                "source": source,
                "severity_history": [psych_severity],
                "stage_history": [],
                "last_user_time": now_ts,
                "timeout_seconds": timeout_seconds,
            }
            await _send_message(confirmation)
            psych_sessions[storage_key]["last_bot_time"] = now_ts
            mark_responded()
            return True

    return False
