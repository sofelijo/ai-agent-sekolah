# bot_sekolah.py
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from telegram import Update
from telegram.ext import ContextTypes

from ai_core import build_qa_chain
from db import save_chat, get_chat_history
from utils import (
    normalize_input,
    strip_markdown,
    now_str,
    format_history_for_chain,
    coerce_to_text,
    IMG_MD,
)
from responses import (
    ASKA_NO_DATA_RESPONSE,
    ASKA_TECHNICAL_ISSUE_RESPONSE,
    get_greeting_response,
    get_thank_you_response,
    is_greeting_message,
    is_thank_you_message,
)

import os
import time
import asyncio
from dotenv import load_dotenv
from thinking_messages import get_random_thinking_message

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
qa_chain = build_qa_chain()


async def send_typing_once(bot, chat_id, delay: float = 0.5):
    await bot.send_chat_action(chat_id=chat_id, action="typing")
    if delay:
        await asyncio.sleep(delay)


async def keep_typing_indicator(bot, chat_id, interval: float = 2.0):
    while True:
        try:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
            await asyncio.sleep(interval)
        except Exception:
            break


async def send_thinking_bubble(update: Update):
    message_text = get_random_thinking_message()
    message = await update.message.reply_text(message_text)
    print(f"[{now_str()}] {message_text}")
    return message


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_typing_once(context.bot, update.effective_chat.id)

    user = update.effective_user
    name = user.first_name or user.username or "bestie"
    response = (
        f"Yoo, {name}! 🫶\n"
        f"Aku *ASKA*, bestie AI kamu 🤖✨\n"
        f"Mau tanya apa aja soal sekolah? Gaskeun~ 🚀"
    )
    await update.message.reply_text(response, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_input = update.message.text or ""
        user_input = normalize_input(user_input)
        user_id = update.effective_user.id
        username = (
            update.effective_user.username or update.effective_user.first_name or "anon"
        )
        print(f"[{now_str()}] HANDLER CALLED - FROM {username}: {user_input}")

        if hasattr(context, "processed_messages"):
            if user_input in context.processed_messages:
                print(f"[{now_str()}] DUPLICATE MESSAGE DETECTED - SKIPPING")
                return
        else:
            context.processed_messages = set()

        context.processed_messages.add(user_input)
        print(f"[{now_str()}] SAVING USER MESSAGE")
        save_chat(user_id, username, user_input, role="user")

        if is_greeting_message(user_input):
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            response = get_greeting_response()
            await update.message.reply_text(response, parse_mode="Markdown")
            save_chat(user_id, "ASKA", response, role="aska")
            return

        if is_thank_you_message(user_input):
            await send_typing_once(context.bot, update.effective_chat.id, delay=0.2)
            response = get_thank_you_response()
            await update.message.reply_text(response, parse_mode="Markdown")
            save_chat(user_id, "ASKA", response, role="aska")
            return

        await send_typing_once(context.bot, update.effective_chat.id, delay=0)
        print(f"[{now_str()}] ASKA sedang mengetik...")

        history_from_db = get_chat_history(user_id, limit=5)
        chat_history = format_history_for_chain(history_from_db)

        start_time = time.perf_counter()

        typing_task = asyncio.create_task(
            keep_typing_indicator(context.bot, update.effective_chat.id)
        )

        try:
            thinking_message = await send_thinking_bubble(update)
            await asyncio.sleep(1.0)
            result = qa_chain.invoke({"input": user_input, "chat_history": chat_history})
        finally:
            typing_task.cancel()

        print(f"[{now_str()}] \U0001F4DA ASKA AMBIL {len(result['context'])} KONTEN:")
        for i, doc in enumerate(result["context"], 1):
            print(f"  {i}. {doc.page_content[:200]}...")

        response = coerce_to_text(result)

        if not response.strip():
            response = ASKA_NO_DATA_RESPONSE

        try:
            await thinking_message.delete()
            print(f"[{now_str()}] Thinking bubble deleted")
        except Exception as e:
            print(f"[{now_str()}] Failed to delete thinking bubble: {e}")

        match = IMG_MD.search(response)
        if match:
            img_url = match.group(1)
            caption = IMG_MD.sub("", response).strip()[:1024]
            caption = strip_markdown(caption)
            await update.message.reply_photo(photo=img_url, caption=caption)
        else:
            response = strip_markdown(response)
            await update.message.reply_text(response)

        duration_ms = (time.perf_counter() - start_time) * 1000
        print(f"[{now_str()}] ASKA : {response} ⏱️ {duration_ms:.2f} ms")
        save_chat(user_id, "ASKA", response, role="aska", response_time_ms=int(duration_ms))

    except Exception as e:
        print(f"[{now_str()}] [ERROR] {e}")

        try:
            if "thinking_message" in locals():
                await thinking_message.delete()
        except Exception:
            pass

        await update.message.reply_text(
            ASKA_TECHNICAL_ISSUE_RESPONSE,
            parse_mode="Markdown",
        )


app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("ASKA AKTIF...")
app.run_polling()
