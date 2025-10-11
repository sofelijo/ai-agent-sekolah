# responses/greeting.py
from __future__ import annotations

import random
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from ._shared import tokenize


# ─────────────────────────────────────────────────────────
# 0) Penanda pertanyaan dasar (untuk mencegah false positive greeting)
QUESTION_TOKENS = {
    "apa", "gimana", "bagaimana", "kenapa", "mengapa",
    "siapa", "kapan", "dimana", "di", "mana", "berapa", "kah"
}


# ─────────────────────────────────────────────────────────
# 1) Kata/frasa sapaan umum (tanpa kata waktu agar tidak bentrok)
GREETING_KEYWORDS = (
    "hai", "hay",
    "halo", "hallo", "helo",
    "hello", "hey", "heyy", "heyyy",
    "hi", "hii", "hiya",
    "yo", "yow", "oy", "oi", "oii", "woy", "hoi",
    "cuy", "cui",
    "bro", "sis", "gan", "min",
    "permisi", "p",
    "assalamualaikum", "asswrwb",
    # Catatan: sengaja TIDAK menyertakan "morning/afternoon/evening"
    # maupun "pagi/siang/sore/malam" di sini; itu diproses di TIME_*
)
GREETING_KEYWORDS_SET = set(GREETING_KEYWORDS)

GREETING_PHRASES = (
    "selamat pagi", "selamat siang", "selamat sore", "selamat malam",
    "good morning", "good afternoon", "good evening",
    "assalamualaikum", "assalamualaikum wr wb", "assalamu alaikum",
    "permisi kak", "permisi min", "permisi bang",
    "ass wr wb", "ass.wr.wb"
)

GREETING_RESPONSES = [
    "Haii! *ASKA* hadir, siap bantu kamu hari ini ✨👋",
    "Hello bestie! Ada yang bisa *ASKA* bantu? 😁🚀",
    "Yo yo! *ASKA* udah online, spill aja pertanyaannya 😉💬",
    "Hai sunshine! Semoga harimu vibes positif—ASKA standby ya ☀️🤖",
    "Halo! Jangan sungkan, langsung aja tanya soal sekolah 🔍📚",
    "Wassup! *ASKA* on duty—tanya aja biar cepet kelar 💼⚡",
    "Hola! *ASKA* nongol nih, kabarin aja kebutuhanmu 😉📲",
    "Pagi/siang/sore! *ASKA* ready mode ON—spill masalahnya ✍️🤖",
    "Yo, squad! Info sekolah? *ASKA* bantuin dari A sampai Z 🔤🧩",
    "Hey there! *ASKA* hadir dengan good vibes, gaskeun pertanyaannya 🌈✨",
    "Hai tim sukses! *ASKA* siap jadi co-pilotmu hari ini 🛫🧭",
    "Halloo! Mau data, jadwal, atau aturan? *ASKA* siap nyariin 🔎🗂️",
    "Good day! *ASKA* online—kamu santai aja, biar *ASKA* yang mikir 😌🧠",
    "Cek cek! *ASKA* connected—ketik aja, langsung kita urai bareng 🔗💬",
    "Welcome back! *ASKA* kangen nih, siap bantu lagi 💖🤖",
]


# ─────────────────────────────────────────────────────────
# 2) Sapaan berbasis waktu (dibersihkan agar konsisten)
TIME_GREETING_PATTERNS = {
    "pagi": ("selamat pagi", "good morning", "met pagi"),
    "siang": ("selamat siang", "good afternoon", "met siang"),
    "sore": ("selamat sore", "met sore"),
    # Konsisten: "good evening" → malam
    "malam": ("selamat malam", "good evening", "good night", "met malam"),
}

TIME_GREETING_KEYWORDS = {
    "pagi": {"pagi", "pagii", "pagiii", "pg", "morning", "gm", "gmorn", "goodmorning", "subuh"},
    "siang": {"siang", "siangg", "sianggg", "afternoon", "noon", "midday"},
    "sore": {"sore", "soree", "sorean", "petang"},
    "malam": {"malam", "malemm", "malammm", "mlm", "night", "evening", "gn", "goodnight", "nite", "midnight", "larut"},
}

# Respons sapaan bergaya Gen-Z + sopan (≤10/slot waktu)
TIME_GREETING_RESPONSES = {
    "pagi": [
        "Selamat pagi! ☀️ *ASKA* doain harimu sesegar kopi pertama ☕",
        "Morning squad! ☀️ *ASKA* siap bikin pagi kamu makin produktif 🚀",
        "Hai pagi! Yuk mulai hari dengan info valid dari *ASKA* 🌅🧠",
        "Pagi, bestie! Biar makin on-track, tanya *ASKA* dulu 🌞📋",
        "Rise and shine! *ASKA* ready bantu urusan sekolah kamu 🌤️📚",
        "Pagi ceria! Cek jadwal/seragam/tugas bareng *ASKA* 🗓️✅",
        "Semoga nilai & mood kamu sama-sama naik hari ini 📈😊",
        "Good morning! Butuh pengumuman terbaru? *ASKA* siap spill 🗞️🤖",
        "Pagi-pagi udah rajin? Mantap! *ASKA* temenin cari info 💪🔎",
        "Gaskeun aktivitas dengan data akurat dari *ASKA* ⚡️✅",
    ],
    "siang": [
        "Selamat siang! Jangan lupa makan dulu, *ASKA* jagain infonya 🍽️🤖",
        "Siang bestie! *ASKA* standby kalau butuh update sekolah 🌤️📚",
        "Halo siang! Mau lanjut urusan sekolah? Spill ke *ASKA* ☀️💬",
        "Siang gini enaknya ngerapiin agenda. *ASKA* bantuin ya 🗂️🕑",
        "Good afternoon! Cek pengumuman atau jadwal bareng *ASKA* 🗓️📰",
        "Siang produktif! *ASKA* siap jawab yang bikin bingung 💡🙌",
        "Minum air dulu, lanjut tanya *ASKA* biar fokus 💧🧠",
        "Lagi di sekolah? *ASKA* bisa cek info cepat untukmu 🏫⚡️",
        "Siang cerah, info juga harus terang. Tanya *ASKA* ya 🌞🔍",
        "Mau kirim izin/agenda? *ASKA* kasih panduan singkat ✉️📌",
    ],
    "sore": [
        "Selamat sore! Saatnya wrap-up bareng *ASKA* 🌇📋",
        "Sore vibes! *ASKA* siap bantu beresin agenda hari ini 🌆🤖",
        "Hai sore! Butuh rekap info sekolah? *ASKA* bantu 🌄📝",
        "Sore-sore waktunya cek tugas besok. *ASKA* temenin 🌤️✅",
        "Sore chill, info tetap clear. Tanyain ke *ASKA* aja ✨🔎",
        "Ada ekskul? *ASKA* bisa cekin detailnya 🏀🎶",
        "Biar pulang tenang, pastiin infonya valid via *ASKA* 🏠✅",
        "Perlu ringkas pengumuman hari ini? *ASKA* ringkasin 🗞️✂️",
        "Waktunya wind down. *ASKA* bantu planning to-do besok 🗒️🕟",
        "Sebelum magrib, cek checklist bareng *ASKA* 🌇📝",
    ],
    "malam": [
        "Selamat malam! 🌙 Urusan info sekolah biar *ASKA* yang handle 😴",
        "Malam bestie! Yuk tutup hari dengan data akurat *ASKA* 🌌📊",
        "Halo malam! Kalau masih ada PR info sekolah, tanya *ASKA* 🌛💬",
        "Good evening! Siapkan seragam & jadwal, *ASKA* bantu cek 🧺🗓️",
        "Malam produktif? Boleh. *ASKA* siap cari referensi 📚✨",
        "Minum hangat, lalu cek checklist besok bareng *ASKA* 🍵🕘",
        "Malam-malam kepo pengumuman? *ASKA* bisa spill terbaru 🌙🗞️",
        "Time to recharge. Sebelum tidur, cek to-do bareng *ASKA* 🔋📝",
        "Malam hening, info tetap jernih. Tanyain *ASKA* 🌃🔍",
        "Good night! Semoga mimpi indah, besok kita gas lagi 🌠🚀",
    ],
}


# ─────────────────────────────────────────────────────────
# 3) Util: infer periode waktu dari jam lokal Asia/Jakarta
def _infer_period_from_clock(now: datetime | None = None) -> str:
    """
    pagi: 04:00–10:59
    siang: 11:00–14:59
    sore: 15:00–18:29
    malam: 18:30–03:59
    """
    if now is None:
        try:
            now = datetime.now(ZoneInfo("Asia/Jakarta"))
        except Exception:
            now = datetime.now()
    h, m = now.hour, now.minute
    total = h * 60 + m
    if 4 * 60 <= total <= 10 * 60 + 59:
        return "pagi"
    if 11 * 60 <= total <= 14 * 60 + 59:
        return "siang"
    if 15 * 60 <= total <= 18 * 60 + 29:
        return "sore"
    return "malam"


# ─────────────────────────────────────────────────────────
# 4) Deteksi sapaan waktu dari teks (dipersempit agar tidak false positive)
def _detect_time_greeting(text: str) -> str | None:
    if not text:
        return None

    lowered = text.lower()
    tokens = tokenize(lowered)

    # Jika ada indikasi pertanyaan, jangan anggap salam waktu
    if "?" in lowered or (tokens & QUESTION_TOKENS):
        return None

    # Cek frasa salam eksplisit (selamat pagi, good evening, dst.)
    for period, phrases in TIME_GREETING_PATTERNS.items():
        if any(phrase in lowered for phrase in phrases):
            return period

    # Untuk kata kunci waktu (pagi/siang/sore/malam/morning/...), anggap salam
    # hanya bila:
    #   - kata waktu berada di awal kalimat, dan
    #   - panjang kalimat pendek (≤ 3 kata)
    # Ini mencegah "pagi ini ada rapat..." dianggap sebagai salam.
    words = re.findall(r"\w+", lowered)
    for period, keywords in TIME_GREETING_KEYWORDS.items():
        if words and words[0] in keywords and len(words) <= 3:
            return period

    return None


def get_time_based_greeting_response(text: str) -> str | None:
    period = _detect_time_greeting(text)
    if not period:
        return None
    options = TIME_GREETING_RESPONSES.get(period)
    if not options:
        return None
    return random.choice(options)


def get_contextual_greeting_response(text: str | None = None, now: datetime | None = None) -> str:
    """
    Gunakan ini kalau ingin sapaan terasa kontekstual:
    - Jika teks berisi salam waktu → pakai respons waktu.
    - Jika tidak → fallback ke waktu jam lokal Asia/Jakarta.
    """
    if text:
        resp = get_time_based_greeting_response(text)
        if resp:
            return resp
    period = _infer_period_from_clock(now)
    options = TIME_GREETING_RESPONSES.get(period)
    if options:
        return random.choice(options)
    return random.choice(GREETING_RESPONSES)


# ─────────────────────────────────────────────────────────
# 5) Deteksi apakah sebuah pesan adalah "pure greeting"
def is_greeting_message(text: str) -> bool:
    """
    Mengembalikan True hanya jika pesan adalah sapaan "murni".
    Aturan utama:
      - Jika ada penanda pertanyaan (token tanya atau '?') → BUKAN greeting.
      - 'p' dihitung greeting hanya bila pesan sangat pendek.
      - Kata/Frasa salam umum diizinkan bila panjang kalimat pendek (≤3 kata).
      - Salam waktu diizinkan bila ada frasa eksplisit atau kata waktu
        berada di awal kalimat dan kalimatnya pendek (≤3 kata).
    """
    if not text:
        return False

    lowered = text.lower().strip()
    tokens = tokenize(lowered)

    # Kalau ada indikasi bertanya → bukan greeting
    if "?" in lowered or (tokens & QUESTION_TOKENS):
        return False

    # Perlakukan 'p' / 'permisi' sebagai greeting bila pesan memang pendek/salam
    if lowered in {"p", "permisi", "permisi min", "permisi kak"} or tokens == {"p"}:
        return True

    # Frasa sapaan eksplisit
    if any(phrase in lowered for phrase in GREETING_PHRASES):
        # Batasi supaya tidak menelan kalimat panjang non-salam
        words = re.findall(r"\w+", lowered)
        return len(words) <= 6  # frasa salam + 1–2 kata tambahan (mis. "selamat pagi min")

    # Kata salam umum (tanpa waktu) → hanya kalau pesan pendek
    if GREETING_KEYWORDS_SET & tokens:
        words = re.findall(r"\w+", lowered)
        return len(words) <= 3

    # Salam waktu yang dipersempit
    return _detect_time_greeting(lowered) is not None


# ─────────────────────────────────────────────────────────
# 6) Ambil respons sapaan generik (kompatibilitas lama)
def get_greeting_response() -> str:
    return random.choice(GREETING_RESPONSES)
