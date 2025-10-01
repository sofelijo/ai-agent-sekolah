# bot_sekolah.py
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from telegram import Update
from telegram.constants import ParseMode
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

import os
import time
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
qa_chain = build_qa_chain()


# ───── HANDLER ─────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.first_name or user.username or "bestie"
    response = (
        f"Yoo, {name}! ✨👋\n"
        f"Aku *ASKA*, bestie AI kamu 🤖💡\n"
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
        print(f"[{now_str()}] FROM {username}: {user_input}")
        save_chat(user_id, username, user_input, role="user")

        history_from_db = get_chat_history(user_id, limit=5)
        chat_history = format_history_for_chain(history_from_db)

        start_time = time.perf_counter()
        result = qa_chain.invoke({"input": user_input, "chat_history": chat_history})

        print(f"[{now_str()}] \U0001F4DA ASKA AMBIL {len(result['context'])} KONTEN:")
        for i, doc in enumerate(result["context"], 1):
            print(f"  {i}. {doc.page_content[:200]}...")

        response = coerce_to_text(result)

        if not response.strip():
            response = (
                "\U0001F605 Maaf nih, *ASKA* belum nemu jawabannya di data sekolah. "
                "Coba hubungi langsung sekolah ya di \u260e\ufe0f (021) 4406363."
            )

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
        await update.message.reply_text(
            "\u26a0\ufe0f Maaf, lagi ada gangguan teknis. Coba tanya *ASKA* nanti ya~ \ud83d\ude4f",
            parse_mode="Markdown",
        )


# ───── JALANKAN BOT ─────
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("\U0001F916 ASKA AKTIF...")
app.run_polling()
