import os
import re
import string
import difflib
import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, ContextTypes, filters
)
from data_loader import load_statistik_sd_zonasi, load_statistik_smp_prestasi
from pendaftar_spmb import cari_urutan_nama, get_sekolah_id_from_nama

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_DATA")

# ───── UTIL ─────

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

def umur_ke_hari(umur_str):
    match = re.findall(r"(\d+)", umur_str)
    if not match:
        return 9999
    th = int(match[0])
    bl = int(match[1]) if len(match) > 1 else 0
    hr = int(match[2]) if len(match) > 2 else 0
    return th * 365 + bl * 30 + hr

def is_umur_kurang_dari(umur: tuple, batas: tuple):
    return umur[0] < batas[0] or (umur[0] == batas[0] and umur[1] < batas[1])

def cari_statistik_sekolah(nama_input: str, statistik_data: list):
    if not isinstance(nama_input, str):
        return None
    nama_input = nama_input.lower()
    for sekolah in statistik_data:
        if nama_input in sekolah["nama_sekolah"].lower():
            return sekolah
    semua_nama = [s["nama_sekolah"] for s in statistik_data]
    terbaik = difflib.get_close_matches(nama_input.upper(), semua_nama, n=1)
    if terbaik:
        return next((s for s in statistik_data if s["nama_sekolah"] == terbaik[0]), None)
    return None

def parse_target_usia(user_input: str):
    pattern = re.compile(r"(di\s*bawah|dibawah|kurang\s*dari)\s*(\d+)\s*tahun(?:\s*(\d+)\s*bulan)?")
    match = pattern.search(user_input)
    if match:
        tahun = int(match.group(2))
        bulan = int(match.group(3)) if match.group(3) else 0
        return tahun, bulan
    return None

# ───── HANDLER ─────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = ("Halo! Ini *BOT DATA* untuk bantu cek:\n"
           "- Umur termuda pendaftar SD\n"
           "- Nilai tertinggi SMP jalur prestasi\n"
           "- Urutan siswa dari SPMB\n\n"
           "Contoh:\n"
           "• umur termuda di SDN Ancol 01\n"
           "• nilai SMP 81\n"
           "• reza urutan berapa\n"
           "(default sekolah: SDN Semper Barat 01 jika tidak disebutkan)")
    await update.message.reply_text(msg, parse_mode="Markdown")

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.lower()
    print(f"[FROM] {update.effective_user.username or update.effective_user.first_name} : {user_input}")

    try:
        kota_mapping = {
            "jakut": "kota jakarta utara",
            "jaksel": "kota jakarta selatan",
            "jakbar": "kota jakarta barat",
            "jakpus": "kota jakarta pusat",
            "jaktim": "kota jakarta timur",
            "jakarta utara": "kota jakarta utara",
            "jakarta selatan": "kota jakarta selatan",
            "jakarta barat": "kota jakarta barat",
            "jakarta pusat": "kota jakarta pusat",
            "jakarta timur": "kota jakarta timur",
        }

        if ("paling rendah" in user_input or "yang terendah" in user_input or "sd mana" in user_input) and "jak" in user_input:
            statistik_data = load_statistik_sd_zonasi()
            target_kota = None

            for kunci, val in kota_mapping.items():
                if kunci in user_input:
                    target_kota = val
                    break

            if not target_kota:
                response = "Sebutkan nama kota yang ingin dicek, contoh: *jakut*, *jaksel*, atau *jakarta utara*."
            else:
                print(f"[DEBUG] Kota yang dicari: {target_kota}")
                filtered = [
                    s for s in statistik_data
                    if s.get("kota", "").strip().lower() == target_kota.strip().lower()
                ]
                sorted_data = sorted(filtered, key=lambda x: umur_ke_hari(x["umur_terendah"]))[:5]

                if sorted_data:
                    response = f"📋 SD dengan umur termuda di {target_kota.title()}:\n"
                    for s in sorted_data:
                        response += f"- {s['nama_sekolah']} → {s['umur_terendah']}\n"
                else:
                    response = f"Tidak ditemukan data untuk SD di {target_kota.title()}."

        elif any(k in user_input for k in ["urutan", "ranking"]):
            kata_kunci = {"urutan", "berapa", "ranking", "masuk", "daftar", "yang", "di"}
            tokens = [k.strip(string.punctuation) for k in user_input.lower().split()]
            nama_tokens = []
            sekolah_tokens = []

            if "di" in tokens:
                idx_di = tokens.index("di")
                nama_tokens = [t for t in tokens[:idx_di] if t not in kata_kunci]
                sekolah_tokens = tokens[idx_di + 1:]
            else:
                nama_tokens = [t for t in tokens if t not in kata_kunci]

            nama_dicari = " ".join(nama_tokens).strip()
            nama_sekolah_input = " ".join(sekolah_tokens).strip().upper() if sekolah_tokens else "SDN SEMPER BARAT 01"

            sekolah_id, nama_sekolah = get_sekolah_id_from_nama(nama_sekolah_input)
            if not sekolah_id:
                response = "Maaf, belum bisa mengenali sekolah tujuan dari input kamu."
            else:
                response = cari_urutan_nama(nama_dicari, sekolah_id, nama_sekolah)

        elif "umur" in user_input or "usia" in user_input:
            statistik_data = load_statistik_sd_zonasi()
            batas = parse_target_usia(user_input)
            if batas:
                hasil = []
                for sekolah in statistik_data:
                    umur = parse_umur_to_tuple(sekolah["umur_terendah"])
                    if is_umur_kurang_dari(umur, batas):
                        hasil.append((sekolah["nama_sekolah"], sekolah["umur_terendah"]))
                if hasil:
                    response = f"📋 SD dengan umur di bawah {batas[0]} th {batas[1]} bl:\n"
                    for nama, umur in hasil[:5]:
                        response += f"- {nama} → {umur}\n"
                else:
                    response = "Tidak ditemukan SD dengan umur di bawah batas tersebut."
            else:
                nama_sekolah = "SDN SEMPER BARAT 01"
                if "sdn" in user_input:
                    idx = user_input.find("sdn")
                    nama_sekolah = user_input[idx:].strip()
                sekolah = cari_statistik_sekolah(nama_sekolah, statistik_data)
                if sekolah:
                    response = (
                        f"📊 Umur Pendaftar {sekolah['nama_sekolah']}:\n"
                        f"- Termuda: {sekolah['umur_terendah']}\n"
                        f"- Tertua: {sekolah['umur_tertinggi']}\n"
                        f"- Rata-rata: {sekolah['umur_rerata']}")
                else:
                    response = "Data SD tidak ditemukan."

        elif "nilai" in user_input and "smp" in user_input:
            statistik_data = load_statistik_smp_prestasi()
            nama_sekolah = "SMP NEGERI"
            if "smp" in user_input:
                idx = user_input.find("smp")
                nama_sekolah = user_input[idx:].strip()
            sekolah = cari_statistik_sekolah(nama_sekolah, statistik_data)
            if sekolah:
                response = (
                    f"📊 Nilai SMP {sekolah['nama_sekolah']}:\n"
                    f"- Tertinggi: {sekolah['nilai_tertinggi']}\n"
                    f"- Terendah: {sekolah['nilai_terendah']}\n"
                    f"- Rata-rata: {sekolah['nilai_rerata']}")
            else:
                tertinggi = sorted(statistik_data, key=lambda x: float(x['nilai_tertinggi']), reverse=True)
                response = "📊 SMP dengan nilai tertinggi:\n"
                for s in tertinggi[:5]:
                    response += f"- {s['nama_sekolah']} → {s['nilai_tertinggi']}\n"

        else:
            response = "Pertanyaan tidak terdeteksi. Gunakan kata kunci: umur, nilai, urutan."

        await update.message.reply_text(response)
        print(f"[BOT RESPONSE] {response}")

    except Exception as e:
        print(f"[ERROR] {e}")
        await update.message.reply_text("Terjadi error teknis. Silakan coba lagi.")

# ───── MAIN ─────

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("🤖 BOT DATA AKTIF...")
app.run_polling()
