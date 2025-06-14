import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, ContextTypes, filters
)
from datetime import datetime, timedelta
from ai_core import build_qa_chain

# Load token dari .env
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Siapkan AI Agent khusus sekolah
qa_chain = build_qa_chain()

# Konversi nama hari ke bahasa Indonesia
indonesia_days = {
    "monday": "Senin",
    "tuesday": "Selasa",
    "wednesday": "Rabu",
    "thursday": "Kamis",
    "friday": "Jumat",
    "saturday": "Sabtu",
    "sunday": "Minggu"
}

# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.first_name or user.username or "teman"
    context.user_data["name"] = name

    await update.message.reply_text(
        f"Halo, {name}! 👋\nSaya *AI SDN Semper Barat 01*.\nTanya aja apa pun tentang sekolah ya~",
        parse_mode="Markdown"
    )

# Handle pesan biasa
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.lower()

    # Tambahkan info hari jika konteksnya "hari ini" atau "besok"
    hari_ini_en = datetime.now().strftime("%A").lower()
    hari_besok_en = (datetime.now() + timedelta(days=1)).strftime("%A").lower()
    hari_ini_id = indonesia_days.get(hari_ini_en, "hari ini")
    hari_besok_id = indonesia_days.get(hari_besok_en, "besok")

    if "besok" in user_input:
        user_input += f" (besok itu hari {hari_besok_id})"
    elif "hari ini" in user_input:
        user_input += f" (hari ini itu hari {hari_ini_id})"

    # Jalankan QA berdasarkan dokumen kecerdasan.md
    response = qa_chain.run(user_input)

    if not response:
        response = "Maaf, saya belum menemukan jawaban di data sekolah."

    await update.message.reply_text(response)

# Setup bot
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("🤖 Bot Telegram SDN Semper Barat 01 aktif...")
app.run_polling()
