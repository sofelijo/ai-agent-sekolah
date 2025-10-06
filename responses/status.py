# responses/status.py
import random

STATUS_PATTERNS = (
    "lagi apa", "lagi ngapain", "ngapain nih", "bot aktif", "botnya aktif",
    "bot online", "aska online", "aska aktif", "on ga", "online ga", "online gak",
    "aktif ga", "aktif gak", "masih online", "masih aktif", "down ga", "error ga",
    "bisa bantu apa", "kamu bisa apa", "bisa bantu ga", "bisa bantu gak", "bisa bantu tidak",
    "ngapain aja bisa", "bisa apa aja", "apa yang bisa", "fitur kamu apa",
    "fungsi kamu apa", "kegunaan kamu apa", "kamu bisa bantuin apa",
    "bantu dong", "bantuin dong", "bisa bantuin", "bisa tolong ga", "bisa tolong gak",
)

STATUS_RESPONSES = [
    "*ASKA* lagi online dan siap bantu — dari jadwal sampai prosedur layanan. 🚀📚",
    "Standby 24/7, bestie. Tulis pertanyaanmu, *ASKA* siap sat-set nyariin. ⏱️🤖",
    "*ASKA* on duty. Butuh data akademik/administrasi? Spill aja, kita urai step by step. 🧩✨",
    "Server aman, vibes stabil. *ASKA* ready cek pengumuman, jadwal, dan aturan. ✅🔎",
    "Mode turbo ON. *ASKA* bantu urusan sekolah biar nggak drama. ⚡🎓",
    "Online, respons cepet. Mau formulir, syarat, atau alur? *ASKA* bantuin. 📝🧭",
    "*ASKA* aktif nonstop—dari PPDB sampai KJP, tinggal tanya. 🏁💬",
    "Everything good! *ASKA* udah warming up, drop pertanyaanmu ya. 🔥🙌",
    "Siap tempur knowledge base. *ASKA* cari jawaban cepat dan akurat. 🗂️🔍",
    "Radar nyala. *ASKA* monitor info penting buat kamu. 📡📢",
    "OTW bantu! Perlu panduan? *ASKA* kasih langkah-langkahnya. 🪜🤝",
    "Command center ON. *ASKA* siap support TU, guru, dan ortu. 🖥️🏫",
    "Sinyal full bar. *ASKA* standby tanpa ribet—gaskeun! 📶⚙️",
    "Online mode santuy—tetep serius kalau soal data. *ASKA* jaga akurasi. 😌📊",
    "Always here for you. *ASKA* jadi co-pilot urusan sekolahmu hari ini. 🛫🧠",
]


def is_status_message(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(phrase in lowered for phrase in STATUS_PATTERNS)


def get_status_response() -> str:
    return random.choice(STATUS_RESPONSES)
