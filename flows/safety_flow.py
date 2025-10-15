import asyncio
from typing import Optional

from telegram.error import NetworkError

from db import save_chat, record_bullying_report
from responses import (
    CATEGORY_GENERAL,
    CATEGORY_PHYSICAL,
    CATEGORY_SEXUAL,
    bullying_next_stage,
    bullying_stage_exists,
    detect_bullying_category,
    get_bullying_ack_response,
    get_bullying_followup_response,
    get_bullying_opening_prompt,
    get_bullying_timeout_message,
    is_bullying_stop_request,
)
from utils import now_str, send_typing_once, strip_markdown


BULLY_CATEGORY_RANK = {
    CATEGORY_GENERAL: 0,
    CATEGORY_PHYSICAL: 1,
    CATEGORY_SEXUAL: 2,
}

_CLOSING_FOLLOWUP = (
    "Kalau nanti ada hal baru atau mau lanjut spill, tinggal panggil ASKA lagi ya 💛"
)


async def handle_bullying(
    *,
    update,
    context,
    reply_message,
    raw_input: str,
    normalized_input: str,
    user_id,
    username: str,
    chat_log_id: Optional[int],
    source: str,
    storage_key,
    now_ts: float,
    timeout_seconds: int,
    mark_responded,
) -> bool:
    """Kelola sesi curhat bullying dengan gaya percakapan natural."""

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
                print(
                    f"[{now_str()}] Network error sending bullying reply (attempt {attempt+1}/10): {exc}"
                )
                if attempt < 9:
                    await asyncio.sleep(5)
        if not sent_successfully:
            try:
                fallback = strip_markdown(text)
                await reply_message.reply_text(fallback)
                save_chat(user_id, "ASKA", fallback, role="aska")
            except Exception:
                pass

    def _aggregate_messages(messages) -> str:
        chunks = [item["text"] for item in messages if item.get("text")]
        combined = "\n\n".join(chunks).strip()
        return combined

    def _calc_severity(category: str) -> str:
        if category == CATEGORY_SEXUAL:
            return "critical"
        if category == CATEGORY_PHYSICAL:
            return "high"
        return "medium"

    async def _finalize_session(session_data: dict, *, reason: str) -> None:
        messages = session_data.get("messages") or []
        aggregated_text = _aggregate_messages(messages)
        if not aggregated_text:
            return

        category = session_data.get("category") or CATEGORY_GENERAL
        severity = session_data.get("severity") or _calc_severity(category)
        base_chat_log_id = session_data.get("base_chat_log_id")
        if base_chat_log_id is None:
            for item in messages:
                candidate = item.get("chat_log_id")
                if candidate is not None:
                    base_chat_log_id = candidate
                    break

        metadata = {
            "source": session_data.get("source"),
            "message_count": len(messages),
            "category_history": session_data.get("category_history", []),
            "stage_history": session_data.get("stage_history", []),
            "severity_history": session_data.get("severity_history", []),
            "current_stage": session_data.get("stage"),
            "final_severity": severity,
            "ended_by": reason,
            "timeout_seconds": timeout_seconds if reason == "timeout" else None,
            "chat_log_ids": [msg.get("chat_log_id") for msg in messages if msg.get("chat_log_id") is not None],
        }
        # Bersihkan metadata dari nilai None agar JSON rapi.
        metadata = {k: v for k, v in metadata.items() if v is not None}

        if base_chat_log_id is not None:
            try:
                record_bullying_report(
                    base_chat_log_id,
                    session_data.get("user_id"),
                    session_data.get("username"),
                    aggregated_text,
                    category=category,
                    severity=severity,
                    metadata=metadata,
                )
            except Exception as exc:  # pragma: no cover - db issues
                print(f"[{now_str()}] [ERROR] Failed to record bullying report: {exc}")
        else:
            print(f"[{now_str()}] [WARN] Bullying session ended without chat_log_id to persist")

        response = get_bullying_ack_response(category, report_text=aggregated_text)
        parts = [response]
        if reason == "timeout":
            parts.append(get_bullying_timeout_message())
        else:
            parts.append(_CLOSING_FOLLOWUP)
        reply_text = "\n\n".join(part for part in parts if part)
        await _send_message(reply_text)
        session_data["last_bot_time"] = now_ts

    bullying_sessions = context.chat_data.setdefault("bullying_sessions", {})
    session = bullying_sessions.get(storage_key)

    # Tutup sesi yang sudah idle terlalu lama sebelum memproses pesan baru.
    if session:
        last_user_time = session.get("last_user_time")
        if last_user_time and (now_ts - last_user_time) > timeout_seconds and session.get("messages"):
            await _finalize_session(session, reason="timeout")
            bullying_sessions.pop(storage_key, None)
            session = None

    # Jika sudah ada sesi berjalan, tambahkan pesan ini ke sesi yang sama.
    if session:
        session.setdefault("timeout_seconds", timeout_seconds)
        session_messages = session.setdefault("messages", [])
        session_messages.append({"text": raw_input, "chat_log_id": chat_log_id})
        session["last_user_time"] = now_ts
        aggregated_text = _aggregate_messages(session_messages)

        current_category = session.get("category", CATEGORY_GENERAL)
        detected_category = detect_bullying_category(normalized_input)
        if detected_category and BULLY_CATEGORY_RANK.get(detected_category, 0) > BULLY_CATEGORY_RANK.get(current_category, 0):
            session["category"] = detected_category
            history = session.setdefault("category_history", [])
            history.append(detected_category)
            new_severity = _calc_severity(detected_category)
            session["severity"] = new_severity
            severity_history = session.setdefault("severity_history", [])
            if not severity_history or severity_history[-1] != new_severity:
                severity_history.append(new_severity)
            current_category = detected_category

        current_severity = session.get("severity")
        if current_severity is None:
            current_severity = _calc_severity(current_category)
            session["severity"] = current_severity
        severity_history = session.setdefault("severity_history", [])
        if not severity_history:
            severity_history.append(current_severity)

        current_stage = session.get("stage")
        if not bullying_stage_exists(current_stage):
            current_stage = "feelings"
            session["stage"] = current_stage
        stage_history = session.setdefault("stage_history", [])
        if not stage_history or stage_history[-1] != current_stage:
            stage_history.append(current_stage)

        if is_bullying_stop_request(raw_input):
            await _finalize_session(session, reason="user_stop")
            bullying_sessions.pop(storage_key, None)
            mark_responded()
            return True

        next_stage_value = bullying_next_stage(current_stage)
        followup = get_bullying_followup_response(
            session.get("category", CATEGORY_GENERAL),
            latest_message=raw_input,
            aggregated_text=aggregated_text,
            message_index=len(session_messages),
            stage=current_stage,
            next_stage=next_stage_value,
            severity=current_severity,
        )
        await _send_message(followup)
        if next_stage_value and bullying_stage_exists(next_stage_value):
            session["stage"] = next_stage_value
            stage_history = session.setdefault("stage_history", [])
            if not stage_history or stage_history[-1] != next_stage_value:
                stage_history.append(next_stage_value)

        session["last_bot_time"] = now_ts
        mark_responded()
        return True

    # Belum ada sesi: cek apakah pesan ini memicu laporan bullying baru.
    bullying_category = detect_bullying_category(normalized_input)
    if not bullying_category:
        return False

    print(f"[{now_str()}]BULLYING REPORT DETECTED ({bullying_category.upper()}) - FLAGGING CHAT")

    session_messages = [{"text": raw_input, "chat_log_id": chat_log_id}]
    severity_value = _calc_severity(bullying_category)
    initial_stage = "feelings"
    bullying_sessions[storage_key] = {
        "state": "collecting",
        "category": bullying_category,
        "category_history": [bullying_category],
        "messages": session_messages,
        "base_chat_log_id": chat_log_id,
        "user_id": user_id,
        "username": username,
        "source": source,
        "severity": severity_value,
        "severity_history": [severity_value],
        "stage": initial_stage,
        "stage_history": [initial_stage],
        "timeout_seconds": timeout_seconds,
        "last_user_time": now_ts,
        "last_bot_time": None,
    }

    opening = get_bullying_opening_prompt(bullying_category, initial_stage)
    if not opening:
        opening = (
            "Makasih banget udah mau cerita. Ceritain aja pelan-pelan ya, aku dengerin. "
            "Kalau udah selesai tinggal bilang 'udah ya'. 💛"
        )

    await _send_message(opening)
    bullying_sessions[storage_key]["last_bot_time"] = now_ts
    mark_responded()
    return True
