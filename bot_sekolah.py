import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, ContextTypes, filters
)
from ai_core import build_qa_chain
import re

# ───── SETUP ─────
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
qa_chain = build_qa_chain()

# ───── HELPER ─────
def normalize_input(text):
    if not isinstance(text, str):
        text = str(text)
    text = text.lower()
    replacements = {
        "umur pendaftar": "umur",
        "usia pendaftar": "umur",
        "usia siswa": "umur",
        "umur siswa": "umur",
        "pendaftar termuda": "umur terendah",
        "pendaftar tertua": "umur tertinggi",
        "usia paling muda": "umur terendah",
        "usia paling tua": "umur tertinggi",
        "ranking": "urutan",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text

# Optional: hapus markdown dari hasil
def strip_markdown(text):
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)  # bold **text**
    text = re.sub(r"#+\s*", "", text)               # remove ###
    return text

# ───── HANDLER ─────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.first_name or user.username or "teman"
    response = (
        f"Halo, {name}! 👋\nSaya *BOT SEKOLAH*.\nTanya aja apa pun tentang sekolah ya~"
    )
    await update.message.reply_text(response, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_input = update.message.text
        if not isinstance(user_input, str):
            user_input = str(user_input)

        user_input = normalize_input(user_input)
        print(f"[FROM] {update.effective_user.username or update.effective_user.first_name} : {user_input}")

        result = qa_chain.invoke(user_input)
        response = result["result"] if isinstance(result, dict) and "result" in result else str(result)

        if not response.strip():
            response = "Maaf, saya belum menemukan jawaban di data sekolah."

        response = strip_markdown(response)
        await update.message.reply_text(response)
        print(f"[BOT RESPONSE] {response}")

    except Exception as e:
        print(f"[ERROR] {e}")
        await update.message.reply_text("Maaf, terjadi kesalahan teknis. Silakan coba lagi nanti.")

# ───── JALANKAN BOT ─────
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("🤖 BOT SEKOLAH AKTIF...")
app.run_polling()
