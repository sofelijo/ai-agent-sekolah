from db import save_chat, get_chat_history
import os
import re
import time
from dotenv import load_dotenv

from telegram import Update
from telegram.constants import ParseMode  # <-- TAMBAHAN UNTUK FORMAT TEKS
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from ai_core import build_qa_chain
from datetime import datetime
from langchain_core.messages import HumanMessage, AIMessage  # <-- IMPORT BARU

# ───── SETUP ─────
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
qa_chain = build_qa_chain()


# ───── HELPER ─────
def normalize_input(text):
    if not isinstance(text, str):
        text = str(text)
    text = text.lower()
    # ... (fungsi ini tidak perlu diubah, biarkan seperti aslinya)
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
        "anbk untuk sd kapan": "anbk untuk sd jadwalnya kapan",
        "kapan anbk sd": "jadwal anbk sd",
        "anbk sd kapan": "jadwal anbk sd",
        "jadwal anbk": "jadwal anbk sd",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def strip_markdown(text):
    if not isinstance(text, str):
        text = str(text or "")
    try:
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"#+\s*", "", text)
        return text
    except Exception:
        return str(text)


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ✨ FUNGSI INI DIPERBARUI ✨
def format_history_for_chain(history):
    """Mengubah format history dari DB menjadi list of Message objects."""
    messages = []
    for role, text in history:
        if role == "user":
            messages.append(HumanMessage(content=text))
        else:  # aska
            messages.append(AIMessage(content=text))
    return messages


def coerce_to_text(result_obj):
    """Fungsi ini sudah bagus, tidak perlu diubah. Ia akan mengambil nilai dari kunci 'answer'."""
    if result_obj is None:
        return ""
    if isinstance(result_obj, str):
        return result_obj
    if hasattr(result_obj, "content"):
        if isinstance(result_obj.content, str):
            return result_obj.content
    if isinstance(result_obj, dict):
        for key in ("answer", "output_text", "result", "text"):
            if key in result_obj and isinstance(result_obj[key], str):
                return result_obj[key]
    return str(result_obj)


# ⬇️ Tambahan untuk mendeteksi gambar dari markdown ![](url)
IMG_MD = re.compile(r'!\[[^\]]*\]\((https?://[^\s)]+)\)')


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

        # ✨ CARA MENGAMBIL & FORMAT HISTORY DIPERBARUI ✨
        history_from_db = get_chat_history(
            user_id, limit=5
        )  # Ambil lebih banyak history
        chat_history = format_history_for_chain(history_from_db)

        start_time = time.perf_counter()

        # ✨ CARA MEMANGGIL CHAIN DIPERBARUI ✨
        result = qa_chain.invoke({"input": user_input, "chat_history": chat_history})

        # Log dokumen yang digunakan sebagai context
        print(f"[{now_str()}] 📚 ASKA AMBIL {len(result['context'])} KONTEN:")
        for i, doc in enumerate(result["context"], 1):
            print(f"  {i}. {doc.page_content[:200]}...")

        # Fungsi coerce_to_text akan otomatis mengambil dari result['answer']
        response = coerce_to_text(result)

        # ❗Fallback jika response kosong
        if not response.strip():
            response = (
                "😅 Maaf nih, *ASKA* belum nemu jawabannya di data sekolah. "
                "Coba hubungi langsung sekolah ya di ☎️ (021) 4406363."
            )

        # ⬇️ CEK APAKAH JAWABAN MENGANDUNG MARKDOWN GAMBAR
        match = IMG_MD.search(response)
        if match:
            # Ambil URL dan caption-nya
            img_url = match.group(1)
            caption = IMG_MD.sub("", response).strip()[:1024]  # hapus markdown
            caption = strip_markdown(caption)  # bersihin karakter spesial
            await update.message.reply_photo(photo=img_url, caption=caption)
        else:
            # Tanpa gambar, kirim teks seperti biasa
            response = strip_markdown(response)
            await update.message.reply_text(response)

        duration_ms = (time.perf_counter() - start_time) * 1000
        print(f"[{now_str()}] ASKA : {response} ⏱️ {duration_ms:.2f} ms")
        save_chat(user_id, "ASKA", response, role="aska", response_time_ms=int(duration_ms))


    except Exception as e:
        print(f"[{now_str()}] [ERROR] {e}")
        await update.message.reply_text(
            "⚠️ Maaf, lagi ada gangguan teknis. Coba tanya *ASKA* nanti ya~ 🙏",
            parse_mode="Markdown",
        )


# ───── JALANKAN BOT ─────
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("🤖 ASKA AKTIF...")
app.run_polling()
