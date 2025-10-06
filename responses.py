import random

ASKA_NO_DATA_RESPONSE = (
    "😅 Maaf nih, *ASKA* belum nemu jawabannya di data sekolah.\n"
    "☎️ Coba hubungi langsung sekolah ya di (021) 4406363."
)

ASKA_TECHNICAL_ISSUE_RESPONSE = (
    "⚠️ Maaf, lagi ada gangguan teknis 🛠️\n"
    "🤖 Coba tanya *ASKA* nanti ya~ 🙏"
)

THANK_YOU_KEYWORDS = (
    "makasih",
    "makasi",
    "makaci",
    "makacii",
    "terima kasih",
    "trimakasih",
    "trims",
    "thanks",
    "thank you",
    "tengkyu",
    "mksh",
)

THANK_YOU_RESPONSES = [
    "Sama-sama bestie! *ASKA* selalu standby buat kamu 😎✨",
    "Yeay~ seneng bisa bantu 😁 Kalau butuh apa-apa tinggal panggil *ASKA* ya! 🤖💬",
    "UwU makasiii, kamu juga keren banget! ✨🔥",
    "No problem! Semoga harimu makin sat set bersama *ASKA* 🚀💥",
    "Love you 3000! Kalau mau curhat info sekolah lagi, *ASKA* siap! 💖📚",
    
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

GREETING_KEYWORDS = (
    "hai",
    "halo",
    "helo",
    "hello",
    "hey",
    "heyy",
    "hi",
    "hii",
    "hiya",
    "yo",
    "bro",
)

GREETING_PHRASES = (
    "selamat pagi",
    "selamat siang",
    "selamat sore",
    "selamat malam",
    "good morning",
    "good afternoon",
    "good evening",
    "assalamualaikum",
    "pagi",
    "malam",
    "sore",
    
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


def _tokenize(text: str):
    return {
        token.strip("!?.:,;()").lower()
        for token in text.split()
        if token.strip("!?.:,;()")
    }


def is_thank_you_message(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(keyword in lowered for keyword in THANK_YOU_KEYWORDS)


def get_thank_you_response() -> str:
    return random.choice(THANK_YOU_RESPONSES)


def is_greeting_message(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    tokens = _tokenize(lowered)
    if any(keyword in tokens for keyword in GREETING_KEYWORDS):
        return True
    return any(phrase in lowered for phrase in GREETING_PHRASES)


def get_greeting_response() -> str:
    return random.choice(GREETING_RESPONSES)
