# responses/greeting.py
import random

from ._shared import tokenize

GREETING_KEYWORDS = (
    "hai", "hay",
    "halo", "hallo", "helo",
    "hello", "hey", "heyy", "heyyy",
    "hi", "hii", "hiya",
    "yo", "yow", "oy", "oi", "oii", "woy", "hoi",
    "cuy", "cui",
    "bro", "sis", "gan", "min",
    "permisi", "p",
    "assalamualaikum", "asswrwb", "asswrwb",
    "morning", "afternoon", "evening",
)

GREETING_PHRASES = (
    "selamat pagi", "selamat siang", "selamat sore", "selamat malam",
    "good morning", "good afternoon", "good evening",
    "assalamualaikum", "assalamualaikum wr wb", "assalamu alaikum",
    "permisi kak", "permisi min", "permisi bang",
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

TIME_GREETING_PATTERNS = {
    "pagi": ("selamat pagi", "good morning", "met pagi"),
    "siang": ("selamat siang", "good afternoon", "met siang"),
    "sore": ("selamat sore", "met sore"),
    "malam": ("selamat malam", "good evening", "good night", "met malam"),
}

TIME_GREETING_KEYWORDS = {
    "pagi": {"pagi", "pagii", "pagiii", "pg", "morning", "gm", "gmorn", "goodmorning", "subuh"},
    "siang": {"siang", "siangg", "sianggg", "afternoon", "noon", "midday"},
    "sore": {"sore", "soree", "sorean", "evening", "petang"},
    "malam": {"malam", "malemm", "malammm", "mlm", "night", "evening", "gn", "goodnight", "nite", "midnight", "larut"},
}

# Respons sapaan bergaya Gen-Z + tetap sopan, 10 per waktu
TIME_GREETING_RESPONSES = {
    "pagi": [
        "Selamat pagi! *ASKA* doain harimu sesegar kopi pertama ☀️☕",
        "Morning squad! *ASKA* siap bikin pagi kamu makin produktif ☀️🚀",
        "Hai pagi! Yuk mulai hari dengan info valid dari *ASKA* 🌅🧠",
        "Pagi, bestie! Biar makin on-track, tanya *ASKA* aja dulu 🌞📋",
        "Rise and shine! *ASKA* ready bantu urusan sekolah kamu 🌤️📚",
        "Pagi ceria! Cek jadwal, seragam, atau tugas bareng *ASKA* ☀️🗓️",
        "Selamat pagi! Semoga nilai dan mood kamu sama-sama naik 📈😊",
        "Good morning! Butuh pengumuman terbaru? *ASKA* siap spill 🗞️🤖",
        "Pagi-pagi udah rajin? Mantap! *ASKA* temenin kamu cari info 💪🔎",
        "Halo pagi! Gaskeun aktivitas dengan data akurat dari *ASKA* ⚡️✅",
    ],
    "siang": [
        "Selamat siang! Jangan lupa makan siang dulu, *ASKA* jagain infonya 🍽️🤖",
        "Siang bestie! *ASKA* standby kalau butuh update sekolah 🌤️📚",
        "Halo siang! Mau lanjut urusan sekolah? Spill ke *ASKA* aja ☀️💬",
        "Siang-siang gini enaknya ngerapiin agenda. *ASKA* bantuin ya 🗂️🕑",
        "Good afternoon! Cek pengumuman atau jadwal bareng *ASKA* 🗓️📰",
        "Siang produktif! *ASKA* siap jawab yang bikin kamu bingung 💡🙌",
        "Selamat siang! Minum air dulu, lanjut tanya *ASKA* biar fokus 💧🧠",
        "Hi siang! Lagi di sekolah? *ASKA* bisa cek info cepat untukmu 🏫⚡️",
        "Siang cerah, info juga harus terang. Tanya *ASKA* ya 🌞🔍",
        "Siang! Mau kirim surat/izin/agenda? *ASKA* kasih panduan singkat ✉️📌",
    ],
    "sore": [
        "Selamat sore! Saatnya wrap-up bareng *ASKA*, biar soremu tetap sat set 🌇📋",
        "Sore vibes! *ASKA* siap bantu beresin agenda hari ini 🌆🤖",
        "Hai sore! Kalau perlu rekap info sekolah, *ASKA* siap bantu 🌄📝",
        "Sore-sore waktunya cek tugas besok. *ASKA* temenin ya 🌤️✅",
        "Good evening! Siap review jadwal & seragam buat besok? *ASKA* bantu 🧭👕",
        "Sore chill, info tetap clear. Tanyain ke *ASKA* aja ✨🔎",
        "Selamat sore! Ada kegiatan ekskul? *ASKA* bisa cekin detailnya 🏀🎶",
        "Halo sore! Biar pulang tenang, pastiin infonya valid via *ASKA* 🏠✅",
        "Sore mantap! Perlu ringkas pengumuman hari ini? *ASKA* ringkasin 🗞️✂️",
        "Waktunya wind down. *ASKA* bantu planning to-do besok 🗒️🕟",
    ],
    "malam": [
        "Selamat malam! Santai dulu, urusan info sekolah biar *ASKA* yang handle 🌙😴",
        "Malam bestie! Yuk tutup hari dengan data akurat bareng *ASKA* 🌌📊",
        "Halo malam! Kalau masih ada PR info sekolah, tinggal tanya *ASKA* 🌛💬",
        "Good evening! Siapkan seragam & jadwal, *ASKA* siap bantu cek 🧺🗓️",
        "Malam produktif? Boleh juga. *ASKA* siap bantu cari referensi 📚✨",
        "Selamat malam! Minum hangat, lalu curhat ke *ASKA* soal jadwal besok 🍵🕘",
        "Malam-malam kepo pengumuman? *ASKA* bisa spill yang terbaru 🌙🗞️",
        "Time to recharge. Sebelum tidur, cek checklist bareng *ASKA* 🔋📝",
        "Malam hening, info tetap jernih. Tanyain *ASKA* kalau bingung 🌃🔍",
        "Good night! Semoga mimpinya indah, besok kita gas lagi bareng *ASKA* 🌠🚀",
    ],
}


def _detect_time_greeting(text: str) -> str | None:
    if not text:
        return None
    lowered = text.lower()
    for period, phrases in TIME_GREETING_PATTERNS.items():
        if any(phrase in lowered for phrase in phrases):
            return period
    tokens = tokenize(lowered)
    for period, keywords in TIME_GREETING_KEYWORDS.items():
        if tokens & keywords:
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


def is_greeting_message(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    tokens = tokenize(lowered)
    if any(keyword in tokens for keyword in GREETING_KEYWORDS):
        return True
    return any(phrase in lowered for phrase in GREETING_PHRASES)


def get_greeting_response() -> str:
    return random.choice(GREETING_RESPONSES)
