import os
import re
import difflib
import requests
import string
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, ContextTypes, filters
)
from datetime import datetime, timedelta
from ai_core import build_qa_chain
from data_loader import load_statistik_sd_zonasi, load_statistik_smp_prestasi
from pendaftar_spmb import cari_urutan_nama
from staf_guru_parser import cari_info_nama
from telegram.error import NetworkError
import httpx  # <── untuk identifikasi error httpx jika perlu retry
import asyncio

# Fungsi hapus markdown seperti **tebal** atau ### heading

def strip_markdown(text):
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)  # Ubah **bold** jadi plain
    text = re.sub(r"#+\s*", "", text)             # Hapus ### heading
    return text

# ───── UTIL PARSING ─────

def parse_target_usia(user_input: str):
    pattern = re.compile(r"(di\s*bawah|dibawah|kurang\s*dari)\s*(\d+)\s*tahun(?:\s*(\d+)\s*bulan)?")
    match = pattern.search(user_input)
    if match:
        tahun = int(match.group(2))
        bulan = int(match.group(3)) if match.group(3) else 0
        return tahun, bulan
    return None

def parse_umur_to_tuple(umur_str: str):
    th = bl = 0
    if not umur_str:
        return (0, 0)
    match = re.search(r"(\d+)\s*th", umur_str)
    if match:
        th = int(match.group(1))
    match = re.search(r"(\d+)\s*bl", umur_str)
    if match:
        bl = int(match.group(1))
    return th, bl

def is_umur_kurang_dari(umur: tuple, batas: tuple):
    return umur[0] < batas[0] or (umur[0] == batas[0] and umur[1] < batas[1])

def cari_statistik_sekolah(nama_input, statistik_data: list):
    nama_input = str(nama_input).lower()
    for sekolah in statistik_data:
        nama_sekolah = str(sekolah.get("nama_sekolah", "")).lower()
        if nama_input in nama_sekolah:
            return sekolah
    semua_nama = [str(s.get("nama_sekolah", "")) for s in statistik_data]
    terbaik = difflib.get_close_matches(nama_input.upper(), semua_nama, n=1)
    if terbaik:
        return next((s for s in statistik_data if str(s.get("nama_sekolah", "")) == terbaik[0]), None)
    return None


def normalize_input(text):
    text = str(text).lower()  # ⬅️ ini yang penting!
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


# ───── SETUP AWAL ─────

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_TESTING")
qa_chain = build_qa_chain()

indonesia_days = {
    "monday": "Senin",
    "tuesday": "Selasa",
    "wednesday": "Rabu",
    "thursday": "Kamis",
    "friday": "Jumat",
    "saturday": "Sabtu",
    "sunday": "Minggu"
}

# ───── HANDLER /START ─────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.first_name or user.username or "teman"
    response = (
        f"Halo, {name}! 👋\nSaya *BOT TESTING SDN Semper Barat 01*.\n"
        f"Tanya aja apa pun tentang sekolah ya~"
    )
    await update.message.reply_text(response, parse_mode="Markdown")
    print(f"[FROM] {user.username or user.first_name} : /start")
    print(f"[BOT RESPONSE] {response}")

# ───── HANDLER PESAN UTAMA ─────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        raw_input = update.message.text
        user_input = str(raw_input).strip().lower()  # Pastikan string
        user_input = normalize_input(user_input)

        print(f"[FROM] {user.username or user.first_name} : {user_input}")

        if not user_input or len(user_input) < 2:
            await update.message.reply_text("Tolong ketikkan pertanyaan dengan lebih lengkap ya.")
            return

        if user_input in ["halo", "hai", "hi", "pagi", "siang", "malam"]:
            response = "Halo juga! 👋 Ada yang bisa saya bantu tentang sekolah?"
            await update.message.reply_text(response)
            print(f"[BOT RESPONSE] {response}")
            return

        # Deteksi urutan pendaftar
        if any(kata in user_input for kata in ["urutan", "masuk", "terdaftar", "daftar", "spmb"]) and not any(k in user_input for k in ["umur", "usia"]):
            kata_kunci = {"urutan", "berapa", "masuk", "terdaftar", "daftar", "spmb", "apakah", "sudah", "masih", "yang"}
            kandidat_nama = []
            for k in user_input.split():
                bersih = k.strip(string.punctuation)
                if bersih.lower() not in kata_kunci:
                    kandidat_nama.append(bersih)

            if kandidat_nama:
                nama_dicari = " ".join(kandidat_nama)
                response = cari_urutan_nama(nama_dicari)
                await update.message.reply_text(response)
                print(f"[BOT RESPONSE] {response}")
                return

        # Info hari otomatis
        hari_ini_en = datetime.now().strftime("%A").lower()
        hari_besok_en = (datetime.now() + timedelta(days=1)).strftime("%A").lower()
        hari_ini_id = indonesia_days.get(hari_ini_en, "hari ini")
        hari_besok_id = indonesia_days.get(hari_besok_en, "besok")

        if "besok" in user_input:
            user_input += f" (besok itu hari {hari_besok_id})"
        elif "hari ini" in user_input:
            user_input += f" (hari ini itu hari {hari_ini_id})"

        # Deteksi batas usia spesifik
        target = parse_target_usia(user_input)
        if target:
            statistik_data = load_statistik_sd_zonasi()
            hasil = []
            for sekolah in statistik_data:
                umur = parse_umur_to_tuple(sekolah["umur_terendah"])
                if is_umur_kurang_dari(umur, target):
                    hasil.append((sekolah["nama_sekolah"], sekolah["umur_terendah"]))
            if hasil:
                response = f"📋 Sekolah dengan umur di bawah {target[0]} th {target[1]} bl:\n"
                for nama, umur in hasil[:5]:
                    response += f"- {nama} → {umur}\n"
            else:
                response = "Tidak ditemukan sekolah dengan umur di bawah batas tersebut."

        # Statistik SD
        elif any(kata in user_input for kata in ["umur", "usia", "terendah", "tertinggi", "kuota", "pendaftar"]):
            statistik_data = load_statistik_sd_zonasi()
            nama_sekolah = ""
            if "sdn" in user_input:
                idx = user_input.find("sdn")
                nama_sekolah = user_input[idx:].strip("?.,! ").upper()
            if not isinstance(nama_sekolah, str) or not nama_sekolah:
                nama_sekolah = "SDN SEMPER BARAT 01"
            sekolah = cari_statistik_sekolah(nama_sekolah, statistik_data)
            if sekolah:
                response = (
                    f"📊 Statistik untuk {sekolah['nama_sekolah']}:\n"
                    f"- Umur Terendah: {sekolah['umur_terendah']}\n"
                    f"- Umur Tertinggi: {sekolah['umur_tertinggi']}\n"
                    f"- Umur Rata-rata: {sekolah['umur_rerata']}"
                )
            else:
                response = "Maaf, data statistik sekolah tersebut belum tersedia."

        # Statistik SMP
        elif any(kata in user_input for kata in ["nilai", "rerata"]) and "smp" in user_input:
            statistik_data = load_statistik_smp_prestasi()
            idx = user_input.find("smp")
            nama_sekolah = user_input[idx:].strip("?.,! ").upper()
            sekolah = cari_statistik_sekolah(nama_sekolah, statistik_data)
            if sekolah:
                response = (
                    f"📊 Statistik SMP untuk {sekolah['nama_sekolah']}:\n"
                    f"- Nilai Terendah: {sekolah['nilai_terendah']}\n"
                    f"- Nilai Tertinggi: {sekolah['nilai_tertinggi']}\n"
                    f"- Nilai Rata-rata: {sekolah['nilai_rerata']}"
                )
            else:
                response = "Maaf, data statistik sekolah tersebut belum tersedia."

        # Fallback ke QA
        else:
            result = qa_chain.invoke(str(user_input))
            response = result["result"] if isinstance(result, dict) and "result" in result else str(result)
            response = strip_markdown(response)  # <── ini baris tambahannya

            if not response.strip():
                response = "Maaf, saya belum menemukan jawaban di data sekolah."

        await update.message.reply_text(response)
        print(f"[BOT RESPONSE] {response}")

    except Exception as e:
        print(f"[ERROR] {e}")
        await update.message.reply_text("Maaf, terjadi kesalahan teknis. Silakan coba lagi nanti.")

# ───── JALANKAN BOT ─────

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("🤖 BOT TESTING Telegram SDN Semper Barat 01 aktif...")

try:
    app.run_polling()
except NetworkError as e:
    print(f"❌ NetworkError: {e}")
except httpx.ReadError as e:
    print(f"❌ HTTPX ReadError: {e}")
except Exception as e:
    print(f"🔥 Unhandled Error: {e}")
