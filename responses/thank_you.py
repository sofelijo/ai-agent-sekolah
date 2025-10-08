# responses/thank_you.py
import random

THANK_YOU_KEYWORDS = (
    "makasih", "makasi", "makasii", "makasihh", "makasihhh",
    "makaci", "makacih", "makacii", "makacihh", "maaci", "maacii",
    "terimakasih", "trimakasih", "trims", "thanks", "thankyou",
    "thx", "tx", "tq", "tqsm", "tqvm", "ty", "tysm", "tyvm",
    "tengkyu", "mksh", "mks", "mkasih", "mksi",
)

THANK_YOU_PHRASES = (
    "terima kasih", "terima kasih banyak", "makasih ya", "makasih banyak",
    "thanks ya", "thank you so much", "makasih banget", "makasih min",
    "makasih kak", "makasih gan", "makasih bro", "makasih sis",
    "makasih bos", "makasih bang", "makasih mbak", "makasih mas",
)


THANK_YOU_RESPONSES = [
    "Sama-sama bestie! *ASKA* selalu standby buat kamu 😎✨",
    "Yeay~ seneng bisa bantu 😁 Kalau butuh apa-apa tinggal panggil *ASKA* ya! 🤖💬",
    "UwU makasiii, kamu juga keren banget! ✨🔥",
    "No problem! Semoga harimu makin sat set bersama *ASKA* 🚀💥",
    "Love you 3000! Kalau mau buat laporan konseling info sekolah lagi, *ASKA* siap! 💖📚",
    "Sama-samaa! Kalau mentok lagi, tinggal tag *ASKA* ya 🔁🤖",
    "Anytime, bestie! *ASKA* standby 24/7 ⏰💪",
    "You’re welcomeee~ semoga urusannya makin ngebut bareng *ASKA* 🏎️💨",
    "Sip dah! Ada *ASKA*, gak perlu overthinking 😌🧩",
    "No worries! *ASKA* happy to help—gas terus produktifnya 💼⚡",
    "Mantul! Kapan pun butuh, panggil *ASKA* aja 🔔✨",
    "Santuy, gampang itu mah—*ASKA* on the way kalau dipanggil 📲😉",
    "Makasi balik! Kamu the real MVP, *ASKA* backup-anmu 🛡️🌟",
    "Seneng bisa bantu! Next time yang lebih ribet juga hayuk 💡🚀",
    "Stay winning! Update-info sekolah serahin ke *ASKA* aja 🏆🏫",
]


def is_thank_you_message(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if any(keyword in lowered for keyword in THANK_YOU_KEYWORDS):
        return True
    return any(phrase in lowered for phrase in THANK_YOU_PHRASES)


def get_thank_you_response() -> str:
    return random.choice(THANK_YOU_RESPONSES)
