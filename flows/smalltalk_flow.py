from typing import Optional

from db import save_chat
from responses import (
    contains_inappropriate_language,
    get_advice_response,
    get_acknowledgement_response,
    get_farewell_response,
    get_greeting_response,
    get_time_based_greeting_response,
    get_relationship_advice_response,
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
)
from utils import send_typing_once


async def handle_smalltalk(
    *,
    update,
    context,
    reply_message,
    normalized_input: str,
    user_id,
    username: str,
    mark_responded,
    topic: Optional[str] = None,
) -> bool:
    # Advice for inappropriate language
    if contains_inappropriate_language(normalized_input):
        await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
        response = get_advice_response()
        await reply_message.reply_text(response)
        save_chat(user_id, "ASKA", response, role="aska", topic=topic)
        mark_responded()
        return True

    # Relationship advice
    if is_relationship_question(normalized_input):
        await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
        response = get_relationship_advice_response()
        await reply_message.reply_text(response)
        save_chat(user_id, "ASKA", response, role="aska", topic=topic)
        mark_responded()
        return True

    # Greeting
    if is_greeting_message(normalized_input):
        await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
        response = (
            get_time_based_greeting_response(normalized_input, user_name=username)
            or get_greeting_response(user_name=username)
        )
        await reply_message.reply_text(response, parse_mode="Markdown")
        save_chat(user_id, "ASKA", response, role="aska", topic=topic)
        mark_responded()
        return True

    # Thank you
    if is_thank_you_message(normalized_input):
        await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
        response = get_thank_you_response()
        await reply_message.reply_text(response, parse_mode="Markdown")
        save_chat(user_id, "ASKA", response, role="aska", topic=topic)
        mark_responded()
        return True

    # Acknowledgement
    if is_acknowledgement_message(normalized_input):
        await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
        response = get_acknowledgement_response()
        await reply_message.reply_text(response)
        save_chat(user_id, "ASKA", response, role="aska", topic=topic)
        mark_responded()
        return True

    # Farewell
    if is_farewell_message(normalized_input):
        await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
        response = get_farewell_response()
        await reply_message.reply_text(response)
        save_chat(user_id, "ASKA", response, role="aska", topic=topic)
        mark_responded()
        return True

    # Self intro
    if is_self_intro_message(normalized_input):
        await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
        response = get_self_intro_response()
        await reply_message.reply_text(response)
        save_chat(user_id, "ASKA", response, role="aska", topic=topic)
        mark_responded()
        return True

    # Status
    if is_status_message(normalized_input):
        await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
        response = get_status_response()
        await reply_message.reply_text(response)
        save_chat(user_id, "ASKA", response, role="aska", topic=topic)
        mark_responded()
        return True

    return False
