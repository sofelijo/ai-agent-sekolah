# responses/acknowledgement.py
import random

from ._shared import tokenize

ACKNOWLEDGEMENT_KEYWORDS = (
    "ok", "oke", "okey", "okeh", "okee", "okii", "okdeh", "okedeh", "okelah", "oklah",
    "k", "kk",
    "sip", "siip", "siipp", "sippp",
    "siap", "siapp", "siappp",
    "mantap", "mantapp", "mantab", "mantul", "mantull", "mantulll",
    "noted",
    "beres", "done", "fix",
    "gas", "gass", "gaskan", "gasken", "gaskeun",
    "next", "lanjut", "lanjutt", "lanjutkan",
    "letsgo", "letsgow", "letgo", "letsgol",
    "baik", "baiklah", "siiplah", "cus", "cuss", "kuy",
)

ACKNOWLEDGEMENT_PHRASES = (
    "siap kak", "siap mbak", "siap mas", "siap pak", "siap bu", "siap bos", "siap bestie",
    "oke deh", "oke dah", "oke lanjut", "oke makasih", "okee makasih", "ok makasih",
    "sip lanjut", "sip makasih", "siap gas", "lanjut gan", "lanjut kak", "gaskeun bestie",
    "lets go", "let's go", "next aja", "udah paham", "udah jelas", "fix ya", "deal ya",
)

# 15 balasan pendek, gen-Z, dan ramah dipakai di banyak konteks
ACKNOWLEDGEMENT_RESPONSES = [
    "Siap! *ASKA* standby, tinggal ping kalau lanjut 😉🤖",
    "Oke noted. Kalau mau next step, spill aja ya ✍️✨",
    "Sip mantul! *ASKA* siap bantu round berikutnya 🚀📚",
    "Gaskeun~ butuh link/aturan? bilang aja 🔗✅",
    "Done diterima. Semoga urusannya sat set 🎯⚡",
    "Baik, dicatat. Mau rekap ringkas? tinggal bilang 🗒️✨",
    "Mantap! *ASKA* ready kapan pun kamu butuh 🤝🤖",
    "Cus lanjut! Kirim kata kunci atau topiknya 📩🔍",
    "Noted bestie. Kita jaga tetap no drama 😌🛡️",
    "Okeee~ *ASKA* nunggu komando berikutnya 📲🧭",
    "Siap captain! Arahkan tujuan, *ASKA* yang navigasi 🧭🚀",
    "Sip, kalau ada yang kurang jelas tinggal tanya ulang 🧩💬",
    "Fix ya. Next kalau perlu bukti resmi, aku cariin 🔎📘",
    "Deal! *ASKA* tetap on buat follow-up kapan saja ⏱️🤖",
    "Maknyus! Lanjut kerja santuy, info serahin ke *ASKA* 😌📊",
]


def is_acknowledgement_message(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    tokens = tokenize(lowered)
    if len(tokens) > 5:
        return False
    if any(keyword in tokens for keyword in ACKNOWLEDGEMENT_KEYWORDS):
        return True
    return any(phrase in lowered for phrase in ACKNOWLEDGEMENT_PHRASES)


def get_acknowledgement_response() -> str:
    return random.choice(ACKNOWLEDGEMENT_RESPONSES)
