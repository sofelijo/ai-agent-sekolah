"""Advice helpers for encouraging respectful language in school contexts."""

import random
import re
import unicodedata

# All entries are lowercase; detection runs on lowercased text.
INAPPROPRIATE_KEYWORDS = {
    # Indonesian slang and insults
    "anjing", "anjir", "anjay", "anjrit", "anjrr", "anj",
    "bangsat", "brengsek", "bajingan", "keparat", "laknat",
    "goblok", "tolol", "bodoh", "bego", "dungu", "idiot",
    "kampret", "tai", "taik", "babi", "asu",
    "bacot", "bacott",
    "kontol", "k0nt0l", "memek", "m3m3k", "titit", "peler", "pler",
    "ngewe", "ewe", "entot", "ngentot", "entod",
    "coly", "coli", "colmek",
    "perek", "lonte", "pelacur",
    "jancuk", "jancok", "cuk", "cukimay",
    "bangke", "bangkai",
    "pantek", "matamu",
    # English profanity
    "fuck", "fck", "fak", "wtf", "stfu",
    "shit", "bullshit", "bs",
    "bitch", "btch", "slut",
    "asshole", "ass", "dick", "d1ck", "pussy",
    "jerk",
}

INAPPROPRIATE_PHRASES = (
    "dasar bodoh",
    "dasar tolol",
    "dasar goblok",
    "mulut kotor",
    "kata-kata kotor",
    "bahasa kasar",
    "otak udang",
    "otak kosong",
    "muka badak",
    "kurang ajar",
    "nggak sopan",
    "mulutmu harimau mu",
    "jaga mulut",
    "sampah masyarakat",
    "tidak berguna",
    "malu-maluin",
    "tidak sopan banget",
    "buruk budi",
    "mata mu",
)

ADVICE_RESPONSES = (
    "ASKA paham kamu lagi panas, tapi kita jaga kelas biar vibes tetap adem. Tarik napas bentar, pilih kata sopan ya 🌬️🙏.",
    "Kalau emosi meledak, ASKA saranin pause dulu terus spill versi yang lebih santun biar pesannya tetep ngena 🤝✨.",
    "ASKA timnya anak sekolah kece—kata kasar bikin ambience rusak. Yuk ubah jadi kritik yang rapi dan hormat 🧠💬.",
    "Tiap chat ke ASKA jadi jejak digital, bestie. Make sure yang kebaca itu sikap good vibes, bukan toxic rant 📲🌟.",
    "Marah boleh, ngelempar kata pedes jangan. ASKA bantu kamu rephrase kalau perlu, tinggal bilang aja 🙋‍♀️🛠️.",
    "Inget pesan guru: mulutmu harimaumu. ASKA jagain kamu biar tetep elegan dengan bahasa positif 🐯😎.",
    "Kalau lawan debat bikin kesel, ASKA rekomend fokus ke fakta dan solusi. Itu baru anak sekolah visioner 🎯📚.",
    "ASKA sayang sama vibes kelas. Ganti kata kasar pakai kalimat supportif biar temenmu nggak kena mental 💗🛡️.",
    "Butuh ngeluarin uneg-uneg? Ketik dulu di draft, baca ulang, baru kirim ke ASKA dengan tone yang respect 🙌📝.",
    "Kita gas produktif bareng ASKA. Bahasa santun = otak jernih = masalah kelar tanpa drama 🧋✅.",
)

_LEET = str.maketrans({
    "0": "o", "1": "i", "!": "i", "|": "i",
    "3": "e", "4": "a", "5": "s", "$": "s",
    "7": "t", "@": "a",
})


def _strip_accents(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def _normalize_text(text: str) -> str:
    lowered = text.lower()
    lowered = _strip_accents(lowered)
    lowered = lowered.translate(_LEET)
    lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    lowered = re.sub(r"(.)\1{2,}", r"\1\1", lowered)
    return lowered


def _spaced_regex_from_word(word: str) -> re.Pattern:
    mapping = {
        "a": "[a4@]",
        "e": "[e3]",
        "i": "[i1!|]",
        "o": "[o0]",
        "s": "[s5$]",
        "t": "[t7]",
    }
    parts = [mapping.get(char, re.escape(char)) for char in word]
    pattern = r"".join(f"{segment}[\\W_]*" for segment in parts)
    return re.compile(pattern, flags=re.IGNORECASE)


INAPPROPRIATE_REGEXES = tuple(_spaced_regex_from_word(keyword) for keyword in INAPPROPRIATE_KEYWORDS)


def contains_inappropriate(text: str) -> bool:
    raw = text or ""
    normalized = _normalize_text(raw)
    raw_lower = raw.lower()

    for phrase in INAPPROPRIATE_PHRASES:
        if phrase in raw_lower or phrase in normalized:
            return True

    tokens = set(normalized.split())
    if tokens & INAPPROPRIATE_KEYWORDS:
        return True

    for regex in INAPPROPRIATE_REGEXES:
        if regex.search(raw):
            return True

    return False


def contains_inappropriate_language(text: str) -> bool:
    """Backward-compatible alias used by handlers."""
    return contains_inappropriate(text)


def get_advice_response() -> str:
    return random.choice(ADVICE_RESPONSES)

