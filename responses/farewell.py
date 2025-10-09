# responses/farewell.py
import random

from ._shared import tokenize

FAREWELL_KEYWORDS = (
    "bye", "byee", "byeee", "goodbye", "gbye",
    "dadah", "dadaa", "dadaah", "daa", "daaah",
    "pamit", "cabut", "cabs",
    "ciao", "ciauu", "ciaw",
    "permisi", "leave", "left",
    "gtg", "g2g", "brb", "out",
    "off", "logoff", "logout",
)

FAREWELL_PHRASES = (
    "bye bye", "see you", "see u", "see ya",
    "sampai jumpa", "sampai ketemu", "udah ya", "cukup ya",
    "aku pamit", "aku cabut", "aku off dulu",
    "izin pamit", "izin keluar", "otw off", "udah dulu ya", "dah dulu ya",
)

FAREWELL_RESPONSES = [
    "Makasih udah ngobrol, sampai jumpa lagi! ✨👋",
    "Oke, *ASKA* pamit dulu. Butuh lagi tinggal chat ya~ 🤖💬",
    "See ya! Semoga harimu lancar dan sat set. 🚀🌈",
    "Sip, ketemu lagi di pertanyaan berikutnya ya. 😉📚",
    "Bye bestie! *ASKA* off dulu—ping aja kalau perlu. 💤🔔",
    "Mantap, sesi selesai. Sampai ketemu di chat berikutnya! ✅💬",
    "Dadah~ semoga semua urusannya smooth. 🌊✨",
    "Cuss lanjut aktivitasmu, *ASKA* standby kapan pun. 🕒🤖",
    "Take care! *ASKA* cabut dulu ya. 🙌🛡️",
    "Thank you & see you, pejuang data sekolah! 🏫🔥",
    "Udahan dulu ya—kalau bingung lagi, panggil *ASKA*. 🧩📲",
    "Misi selesai. Sampai jumpa, keep shining! ✨🏆",
    "OTW off, next time kita gas lagi bareng *ASKA*. ⚡🚀",
    "Cukup segini dulu—tetap semangat dan produktif! 💪📈",
    "See you next chat! *ASKA* suka data akurat, kamu juga ya 😉📊",
]


def is_farewell_message(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    tokens = tokenize(lowered)
    if any(keyword in tokens for keyword in FAREWELL_KEYWORDS):
        return True
    return any(phrase in lowered for phrase in FAREWELL_PHRASES)


def get_farewell_response() -> str:
    return random.choice(FAREWELL_RESPONSES)
