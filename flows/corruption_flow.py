import asyncio
from typing import Optional

from telegram.error import NetworkError

from db import save_chat
from responses import (
    CorruptionResponse,
    get_corruption_howto_response,
    is_corruption_howto_request,
    is_corruption_report_intent,
    mentions_corruption_only,
)
from utils import now_str, send_typing_once, strip_markdown
from utils import send_and_update_thinking_bubble


async def handle_corruption(
    *,
    update,
    context,
    reply_message,
    raw_input: str,
    normalized_input: str,
    user_id,
    username: str,
    storage_key,
    source: str,
    mark_responded,
) -> bool:
    """Handle corruption report flow and related intents.

    Returns True if handled.
    """
    # Corruption flow session management
    corruption_sessions = context.chat_data.setdefault("corruption_sessions", {})
    corruption_session: Optional[CorruptionResponse] = corruption_sessions.get(storage_key)

    if corruption_session:
        # User is in an ongoing corruption flow
        response = corruption_session.handle_response(raw_input)
        if response:
            sent_successfully = False
            for i in range(10):  # Retry up to 10 times as in original
                try:
                    await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
                    await reply_message.reply_text(response, parse_mode="Markdown")
                    save_chat(user_id, "ASKA", strip_markdown(response), role="aska")
                    sent_successfully = True
                    print(f"[{now_str()}] Successfully sent corruption flow message on attempt {i+1}.")
                    break
                except NetworkError as e:  # pragma: no cover
                    print(f"[{now_str()}] Network error sending corruption flow message (attempt {i+1}/10): {e}")
                    if i < 9:
                        await asyncio.sleep(5)

            if not sent_successfully:
                print(f"[{now_str()}] Failed to send corruption flow message after retries.")

            if getattr(corruption_session, "state", "") == "idle":
                corruption_sessions.pop(storage_key, None)
            mark_responded()
            return True

    # How-to guidance
    if is_corruption_howto_request(normalized_input):
        howto_text = get_corruption_howto_response()
        await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
        await reply_message.reply_text(howto_text)
        save_chat(user_id, "ASKA", howto_text, role="aska")
        mark_responded()
        return True

    # Mention only, give CTA suggestion
    if mentions_corruption_only(normalized_input):
        suggestion = (
            "Kalau mau lapor resmi lewat ASKA, ketik aja 'lapor korupsi' ya. "
            "ASKA bakal pandu step-by-step dan kamu dapat tiket pelacakan. 🔒"
        )
        await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
        await reply_message.reply_text(suggestion)
        save_chat(user_id, "ASKA", suggestion, role="aska")
        mark_responded()
        return True

    # Start flow intent
    if is_corruption_report_intent(normalized_input):
        stop_thinking_event = asyncio.Event()
        thinking_task = asyncio.create_task(
            send_and_update_thinking_bubble(reply_message, stop_thinking_event)
        )

        session = CorruptionResponse(user_id)
        response = session.start_report()
        corruption_sessions[storage_key] = session

        stop_thinking_event.set()
        try:
            thinking_message = await thinking_task
            if thinking_message:
                await thinking_message.delete()
        except Exception as e:
            print(f"[{now_str()}] Error managing thinking bubble: {e}")

        await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
        await reply_message.reply_text(response)
        save_chat(user_id, "ASKA", response, role="aska")
        mark_responded()
        return True

    return False

