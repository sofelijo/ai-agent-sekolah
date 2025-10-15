"""Telegram handlers router for ASKA bot (lean version)."""

import asyncio
import time
from typing import Optional, Set

from telegram import Message, Update
from telegram.error import NetworkError
from telegram.ext import ContextTypes

from dotenv import load_dotenv

from ai_core import build_qa_chain
from db import save_chat, get_chat_history
from responses import ASKA_NO_DATA_RESPONSE, ASKA_TECHNICAL_ISSUE_RESPONSE
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
from flows.safety_flow import handle_bullying
from flows.corruption_flow import handle_corruption
from flows.psych_flow import handle_psych
from flows.teacher_flow import handle_teacher
from flows.smalltalk_flow import handle_smalltalk
from voice_handlers import handle_voice


load_dotenv()
qa_chain = build_qa_chain()

TEACHER_TIMEOUT_SECONDS = 600
PSYCH_TIMEOUT_SECONDS = 600
BULLYING_TIMEOUT_SECONDS = 600

TEACHER_TIMEOUT_MESSAGE = (
    "Latihan kita ke-pause lumayan lama nih, ASKA pamit dulu ya. "
    "Kalau mau lanjut tinggal panggil ASKA lagi. Sampai jumpa! 😄✨"
)

PSYCH_TIMEOUT_MESSAGE = (
    "Obrolan laporan konselingnya udah sunyi lama, ASKA pamit sementara ya. "
    "Kapan pun butuh cerita lagi langsung chat ASKA. Sampai jumpa! 🤗💖"
)


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

        print(
            f"[{now_str()}] HANDLER CALLED ({source.upper()}) - FROM {username}: {normalized_input}"
        )

        storage_key = user_id if user_id is not None else f"anon:{username}"

        # Dedup frequent repeats
        recent_messages_root = context.chat_data.setdefault("recent_messages_by_user", {})
        recent_messages = recent_messages_root.setdefault(storage_key, {})
        now_ts = time.time()
        for msg_text, ts in list(recent_messages.items()):
            if (now_ts - ts) > 600:
                del recent_messages[msg_text]
        last_ts = recent_messages.get(normalized_input)
        if last_ts is not None and (now_ts - last_ts) < 60:
            print(f"[{now_str()}] DUPLICATE MESSAGE RECEIVED WITHIN 60s - SKIPPING")
            # Send a quick bubble so the user knows the message was skipped as spammy noise.
            await reply_message.reply_text(
                "Eh bestie, chat kamu kembar sama yang tadi jadi aku skip dulu biar "
                "nggak dikira spam 😅 Coba remix dikit atau tunggu bentar ya ✨"
            )
            return True
        recent_messages[normalized_input] = now_ts

        # Persist user message
        topic = source if source != "text" else None
        chat_log_id = save_chat(user_id, username, normalized_input, role="user", topic=topic)

        def mark_responded():
            if responded_store is not None and responded_key is not None:
                responded_store.add(responded_key)

        # Route to flows
        if await handle_bullying(
            update=update,
            context=context,
            reply_message=reply_message,
            raw_input=raw_input,
            normalized_input=normalized_input,
            user_id=user_id,
            username=username,
            chat_log_id=chat_log_id,
            source=source,
            storage_key=storage_key,
            now_ts=now_ts,
            timeout_seconds=BULLYING_TIMEOUT_SECONDS,
            mark_responded=mark_responded,
        ):
            return True

        if await handle_corruption(
            update=update,
            context=context,
            reply_message=reply_message,
            raw_input=raw_input,
            normalized_input=normalized_input,
            user_id=user_id,
            username=username,
            storage_key=storage_key,
            source=source,
            mark_responded=mark_responded,
        ):
            return True

        if await handle_psych(
            update=update,
            context=context,
            reply_message=reply_message,
            raw_input=raw_input,
            normalized_input=normalized_input,
            user_id=user_id,
            username=username,
            storage_key=storage_key,
            chat_log_id=chat_log_id,
            source=source,
            mark_responded=mark_responded,
            timeout_seconds=PSYCH_TIMEOUT_SECONDS,
            timeout_message=PSYCH_TIMEOUT_MESSAGE,
            now_ts=now_ts,
        ):
            return True

        if await handle_teacher(
            update=update,
            context=context,
            reply_message=reply_message,
            raw_input=raw_input,
            normalized_input=normalized_input,
            user_id=user_id,
            storage_key=storage_key,
            mark_responded=mark_responded,
            timeout_seconds=TEACHER_TIMEOUT_SECONDS,
            timeout_message=TEACHER_TIMEOUT_MESSAGE,
        ):
            return True

        if await handle_smalltalk(
            update=update,
            context=context,
            reply_message=reply_message,
            normalized_input=normalized_input,
            user_id=user_id,
            username=username,
            mark_responded=mark_responded,
        ):
            return True

        # Fallback QA
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
