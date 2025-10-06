# responses/self_intro.py
import random

SELF_INTRO_PATTERNS = (
    "kamu siapa", "kamu itu siapa", "siapa kamu",
    "lu siapa", "loe siapa", "lo siapa", "anda siapa", "situ siapa", "ente siapa",
    "kamu sapa", "lu sapa", "lo sapa",
    "ini bot apa", "bot apa ini", "bot apa sih",
    "ini bot siapa", "bot siapa ini", "bot siapa sih",
    "kamu bot apa", "kamu itu apa", "kamu apa",
    "aska siapa", "siapa aska", "aska itu siapa", "aska itu siapa sih",
    "aska itu apa", "apa itu aska", "aska itu apa sih",
    "aska chatbot", "aska ngapain", "aska bisa apa", "aska gunanya apa", "aska buat apa",
    "kenalin aska", "perkenalkan aska", "kenalan sama aska",
)

SELF_INTRO_RESPONSES = [
    "Aku *ASKA*—chatbot sekolah. Tugasnya bantu cari info akademik, jadwal, dan layanan. 🤖📚",
    "Ini bot apa? *ASKA* nih—bot info sekolah yang narik jawaban dari database resmi. 🔎🗂️",
    "ASKA itu apa? Asisten digital sekolah buat urusan PPDB, KJP, pengumuman, dan prosedur. 🎓📢",
    "Siapa *ASKA*? AI sekolah yang standby 24/7 bantu kamu biar urusan cepet sat set. ⏱️⚡",
    "Kamu siapa? Aku *ASKA*, co-pilot urusan sekolah—tinggal tanya, aku jelasin. 🛫🧭",
    "ASKA bisa apa? Cek jadwal, baca kebijakan, jelasin alur layanan step by step. 🧩✅",
    "*ASKA* di sini—bot sekolah yang bikin info cepet, jelas, anti ribet. 🚀✨",
    "Halo! *ASKA* chatbot sekolah: tanya data guru, kalender, atau formulir—gaskeun. 🗓️📝",
    "Ini bot apa? *ASKA*—temen ngobrol soal info sekolah biar kamu nggak overthinking. 😌💬",
    "Singkatnya: *ASKA* = bot info sekolah yang responsif & transparan. Sat set no drama. 🛡️⚙️",
    "Siapa *ASKA*? Kurator info sekolah—data valid dulu, opini belakangan. 📊🔒",
    "ASKA itu apa? Portal chat sekali ketik buat jadwal, syarat, biaya, dan link resmi. 🔗📘",
    "Kamu siapa? Aku *ASKA*, AI sekolah yang bantu ortu, siswa, dan guru biar tetap update. 👪🧠",
    "ASKA bisa apa? Cari pengumuman, jadwal ujian, dan panduan administrasi harian. 📢🖇️",
    "*ASKA* on duty—chatbot sekolah buat jawab FAQ & kebutuhan info harian. Tembak aja. 🎯💬",
]


def is_self_intro_message(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(phrase in lowered for phrase in SELF_INTRO_PATTERNS)


def get_self_intro_response() -> str:
    return random.choice(SELF_INTRO_RESPONSES)
