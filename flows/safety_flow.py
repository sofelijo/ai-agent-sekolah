import asyncio
from typing import Optional

from telegram.error import NetworkError

from db import save_chat, record_bullying_report
from responses import (
    CATEGORY_PHYSICAL,
    CATEGORY_SEXUAL,
    detect_bullying_category,
    get_bullying_ack_response,
)
from utils import now_str, send_typing_once, strip_markdown


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
    mark_responded,
) -> bool:
    """Detect and record bullying report; reply with acknowledgement.

    Returns True if handled.
    """
    bullying_category = detect_bullying_category(normalized_input)
    if not bullying_category:
        return False

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

    # Defensive send with retries (mirror style in handlers.py)
    sent_successfully = False
    for i in range(3):
        try:
            await reply_message.reply_text(response)
            save_chat(user_id, "ASKA", response, role="aska")
            sent_successfully = True
            break
        except NetworkError as e:  # pragma: no cover - network flakiness
            print(f"[{now_str()}] Network error sending bullying ack (attempt {i+1}/3): {e}")
            if i < 2:
                await asyncio.sleep(2)

    if not sent_successfully:
        # Last resort, try without markdown and shortened text
        try:
            text = strip_markdown(response)
            await reply_message.reply_text(text)
            save_chat(user_id, "ASKA", text, role="aska")
        except Exception:
            pass

    mark_responded()
    return True

