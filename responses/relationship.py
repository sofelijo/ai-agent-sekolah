"""Responses for romance-related questions with teacher-style guidance."""

import random
from typing import Iterable

from ._shared import tokenize

# Core words that directly refer to romance or a partner.
CORE_RELATIONSHIP_KEYWORDS = {
    "jodoh",
    "pacar",
    "pasangan",
    "nikah",
    "menikah",
    "pernikahan",
    "tunangan",
    "lamaran",
    "doi",
    "gebetan",
    "pdkt",
    "bucin",
    "crush",
    "romansa",
    "asmara",
}

# Phrases that typically indicate soulmate or dating topics.
RELATIONSHIP_PHRASES = (
    "cari jodoh",
    "nyari jodoh",
    "kapan nikah",
    "kapan aku nikah",
    "kapan aku kawin",
    "gimana dapet pacar",
    "minta pacar",
    "pengen pacar",
    "pengen nikah",
    "butuh pacar",
    "butuh pasangan",
    "cara pdkt",
    "cara dapetin doi",
    "cara dapetin pacar",
    "cara dapat pacar",
    "tips pdkt",
    "tips asmara",
    "soal jodoh",
    "siapa jodohku",
    "sapa jodohku",
    "siapa pacarku",
    "sapa pacarku",
    "siapa pasanganku",
    "sapa pasanganku",
)

# Words that on their own are generic but signal romance when paired with question cues.
SECONDARY_KEYWORDS = {
    "cinta",
    "sayang",
    "dihianati",
    "selingkuh",
    "putus",
    "balikan",
    "gebet",
}

QUESTION_CUES = {
    "gimana",
    "bagaimana",
    "boleh",
    "harus",
    "apa",
    "kenapa",
    "kapan",
    "ngapain",
    "cara",
    "tips",
    "minta",
    "tolong",
    "siapa",
    "sapa",
}

RELATIONSHIP_ADVICE_RESPONSES = (
    "Bestie, ASKA ngerti kamu penasaran soal jodoh ✨ tapi mode wali kelas bilang fokus dulu benahin nilai dan attitude biar pondasi kuat 📚.",
    "Lagi galau gebetan? ASKA saranin bikin laporan konseling ke guru BK atau ngobrol sama ortu, habis itu back to to-do sekolah biar hati dan otak tetap balance 💬📝.",
    "ASKA percaya jodoh datang pas kamu siap tanggung jawab; sementara upgrade skill lewat belajar, ekskul, sama karakter kece 💪🎓.",
    "Daripada overthinking pasangan, ASKA ajak kamu salurin energi ke lomba, organisasi, atau project kreatif buat masa depan cerah 🚀🏆.",
    "Guru-guru dan ASKA sepakat batas pertemanan harus dijaga; hormati diri sendiri dan temen supaya vibes kelas tetap sehat 🙌❤️.",
    "Kalau temen sibuk pacaran, chill aja-ASKA dukung kamu fokus ngejar mimpi dulu, biarin prestasi yang bikin kamu auto dilirik nanti ✨😉.",
    "Pas patah hati, ASKA siap ngingetin: tulis jurnal, gerak badan, terus bangkit lagi kayak siswa champion yang tahan banting 🏃‍♀️📔.",
    "ASKA define relationship goals pelajar sebagai akrab sama buku, guru, dan habit produktif biar masa depan makin stabil 📖✅.",
    "Ingat kata ASKA, masa sekolah cuma sekali; kumpulin pengalaman positif, temen suportif, dan nilai mantap-jodoh bakal nyusul 🕒💫.",
    "Kalau masih bingung, DM guru BK atau panggil ASKA lagi; kita siap jadi support system biar kamu tetap on track 👩‍🏫🤝.",
)

def _contains_any(haystack: Iterable[str], needles: Iterable[str]) -> bool:
    """Return True when any item from needles appears in haystack."""
    return any(item in haystack for item in needles)


def is_relationship_question(text: str) -> bool:
    """Detect whether the user is asking about romance or soulmate topics."""
    if not text:
        return False

    lowered = text.lower()
    tokens = tokenize(lowered)

    if tokens & CORE_RELATIONSHIP_KEYWORDS:
        return True

    if any(keyword in token for token in tokens for keyword in CORE_RELATIONSHIP_KEYWORDS):
        return True

    if any(phrase in lowered for phrase in RELATIONSHIP_PHRASES):
        return True

    has_secondary = bool(tokens & SECONDARY_KEYWORDS)
    has_question_cue = _contains_any(tokens, QUESTION_CUES) or "?" in lowered

    return has_secondary and has_question_cue


def get_relationship_advice_response() -> str:
    """Return a random teacher-style advice response for romance questions."""
    return random.choice(RELATIONSHIP_ADVICE_RESPONSES)


