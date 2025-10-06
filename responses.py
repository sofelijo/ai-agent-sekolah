import random

ASKA_NO_DATA_RESPONSE = (
    "😅 Maaf nih, *ASKA* belum nemu jawabannya di data sekolah.\n"
    "☎️ Coba hubungi langsung sekolah ya di (021) 4406363."
)

ASKA_TECHNICAL_ISSUE_RESPONSE = (
    "⚠️ Maaf, lagi ada gangguan teknis 🛠️\n"
    "🤖 Coba tanya *ASKA* nanti ya~ 🙏"
)

# ---------------------------
# THANK YOU
# ---------------------------

# Single-token (tanpa spasi) untuk pencocokan cepat
THANK_YOU_KEYWORDS = (
    "makasih", "makasi", "makasii", "makasihh", "makasihhh",
    "makaci", "makacih", "makacii", "makacihh", "maaci", "maacii"
    "terimakasih", "trimakasih", "trims", "thanks", "thankyou", 
    "thx", "tx", "tq", "tqsm", "tqvm", "ty", "tysm", "tyvm",
    "tengkyu", "mksh", "mks", "mkasih", "mksi",
)

# Multi-token / frasa umum
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

# ---------------------------
# GREETING
# ---------------------------

# Single-token greeting (tanpa spasi) + slang/typo populer
GREETING_KEYWORDS = (
    "hai", "hay",
    "halo", "hallo", "helo",
    "hello", "hey", "heyy", "heyyy",
    "hi", "hii", "hiya",
    "yo", "yow", "oy", "oi", "oii", "woy", "hoi",
    "cuy", "cui",
    "bro", "sis", "gan", "min",
    "permisi", "p",
    "assalamualaikum", "asswrwb", "asswrwb",  # variasi ditangkap normalizer jika ada
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

# Lebih banyak variasi ACK (singkat, typo, slang, dan perpanjangan huruf)
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
    "baik", "baiklah", "siiplah", "cus", "cuss", "kuy"
)

# Frasa umum yang sering dipakai buat meng-ack
ACKNOWLEDGEMENT_PHRASES = (
    "siap kak", "siap mbak", "siap mas", "siap pak", "siap bu", "siap bos", "siap bestie",
    "oke deh", "oke dah", "oke lanjut", "oke makasih", "okee makasih", "ok makasih",
    "sip lanjut", "sip makasih", "siap gas", "lanjut gan", "lanjut kak", "gaskeun bestie",
    "lets go", "let's go", "next aja", "udah paham", "udah jelas", "fix ya", "deal ya"
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


# =========================
# SELF INTRO
# =========================
SELF_INTRO_PATTERNS = (
    # inti
    "kamu siapa", "kamu itu siapa", "siapa kamu",
    "lu siapa", "loe siapa", "lo siapa", "anda siapa", "situ siapa", "ente siapa",
    "kamu sapa", "lu sapa", "lo sapa",

    # bot apa/siapa
    "ini bot apa", "bot apa ini", "bot apa sih",
    "ini bot siapa", "bot siapa ini", "bot siapa sih",
    "kamu bot apa", "kamu itu apa", "kamu apa",

    # aska apa/siapa
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

# =========================
# FAREWELL
# =========================
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
    "izin pamit", "izin keluar", "otw off", "udah dulu ya",
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

# =========================
# STATUS
# =========================
STATUS_PATTERNS = (
    # status/online
    "lagi apa", "lagi ngapain", "ngapain nih", "bot aktif", "botnya aktif",
    "bot online", "aska online", "aska aktif", "on ga", "online ga", "online gak",
    "aktif ga", "aktif gak", "masih online", "masih aktif", "down ga", "error ga",

    # kemampuan/apa yang bisa
    "bisa bantu apa", "kamu bisa apa", "bisa bantu ga", "bisa bantu gak", "bisa bantu tidak",
    "ngapain aja bisa", "bisa apa aja", "apa yang bisa", "fitur kamu apa",
    "fungsi kamu apa", "kegunaan kamu apa", "kamu bisa bantuin apa",

    # ajakan minta bantuan (sering dipakai buat status)
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



def is_acknowledgement_message(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    tokens = _tokenize(lowered)
    if len(tokens) > 5:
        return False
    if any(keyword in tokens for keyword in ACKNOWLEDGEMENT_KEYWORDS):
        return True
    return any(phrase in lowered for phrase in ACKNOWLEDGEMENT_PHRASES)


def get_acknowledgement_response() -> str:
    return random.choice(ACKNOWLEDGEMENT_RESPONSES)


def is_self_intro_message(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(phrase in lowered for phrase in SELF_INTRO_PATTERNS)


def get_self_intro_response() -> str:
    return random.choice(SELF_INTRO_RESPONSES)


def is_farewell_message(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    tokens = _tokenize(lowered)
    if any(keyword in tokens for keyword in FAREWELL_KEYWORDS):
        return True
    return any(phrase in lowered for phrase in FAREWELL_PHRASES)


def get_farewell_response() -> str:
    return random.choice(FAREWELL_RESPONSES)


def is_status_message(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(phrase in lowered for phrase in STATUS_PATTERNS)


def get_status_response() -> str:
    return random.choice(STATUS_RESPONSES)
