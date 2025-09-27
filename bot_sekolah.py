import os
import re
import time
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, ContextTypes, filters
)
from ai_core import build_qa_chain
from datetime import datetime

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

         # Tambahan alias agar pertanyaan tetap dikenali
        "anbk untuk sd kapan": "jadwal anbk sd",
        "kapan anbk sd": "jadwal anbk sd",
        "anbk sd kapan": "jadwal anbk sd",
        "jadwal anbk": "jadwal anbk sd"
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text

def strip_markdown(text):
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)  # bold **text**
    text = re.sub(r"#+\s*", "", text)             # remove ###
    return text

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
        user_input = update.message.text
        if not isinstance(user_input, str):
            user_input = str(user_input)

        user_input = normalize_input(user_input)

        # log input user dengan waktu
        print(f"[{now_str()}] FROM {update.effective_user.username or update.effective_user.first_name}: {user_input}")

        # mulai hitung durasi
        start_time = time.perf_counter()

        result = qa_chain.invoke(user_input)
        response = result["result"] if isinstance(result, dict) and "result" in result else str(result)

        if not response.strip():
            response = (
                "😅 Maaf nih, *ASKA* belum nemu jawabannya di data sekolah. "
                "Coba hubungi langsung sekolah ya di ☎️ (021) 4406363."
            )

        response = strip_markdown(response)
        await update.message.reply_text(response)

        # selesai hitung durasi
        end_time = time.perf_counter()
        duration_ms = (end_time - start_time) * 1000  # konversi ke ms

        # log jawaban bot dengan waktu + durasi
        print(f"[{now_str()}] ASKA : {response} ⏱️ {duration_ms:.2f} ms")

    except Exception as e:
        print(f"[{now_str()}] [ERROR] {e}")
        await update.message.reply_text(
            "⚠️ Maaf, lagi ada gangguan teknis. Coba tanya *ASKA* nanti ya~ 🙏",
            parse_mode="Markdown"
        )

# ───── JALANKAN BOT ─────
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("🤖 ASKA AKTIF...")
app.run_polling()
