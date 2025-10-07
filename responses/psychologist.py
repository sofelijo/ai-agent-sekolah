"""Deteksi curhat psikologis dan respons pendamping Gen-Z."""

from __future__ import annotations

import random
import re
from typing import Optional, Sequence


SEVERITY_GENERAL = "general"
SEVERITY_ELEVATED = "elevated"
SEVERITY_CRITICAL = "critical"

_TRIGGER_KEYWORDS: tuple[str, ...] = (
    "curhat",
    "mau cerita",
    "pengen cerita",
    "butuh teman cerita",
    "lagi sedih",
    "lagi down",
    "lagi galau",
    "stress",
    "stres",
    "cemas",
    "anxiety",
    "sendiri",
    "kesepian",
    "nangis",
    "mental",
)

_ELEVATED_KEYWORDS: tuple[str, ...] = (
    "depresi",
    "depression",
    "burn out",
    "burnout",
    "overthinking",
    "trauma",
    "takut banget",
    "gak berharga",
    "tidak berharga",
    "gak kuat",
    "nggak kuat",
    "capek hidup",
    "cape hidup",
    "cape banget",
    "pusing banget",
)

_CRITICAL_KEYWORDS: tuple[str, ...] = (
    "bunuh diri",
    "mau mati",
    "pengen mati",
    "ingin mati",
    "akhiri hidup",
    "melukai diri",
    "self harm",
    "self-harm",
    "menyakiti diri",
    "potong tangan",
    "minum obat banyak",
    "gantung diri",
)

_STOP_KEYWORDS: tuple[str, ...] = (
    "stop curhat",
    "udah cukup",
    "sampai sini",
    "makasih ya",
    "cukup curhat",
    "selesai curhat",
)

_CONFIRM_YES: tuple[str, ...] = (
    "iya",
    "iya mau",
    "iya dong",
    "lanjut",
    "boleh",
    "yuk",
    "gas",
    "gaskeun",
    "yes",
    "ok",
    "oke",
    "yoi",
)

_CONFIRM_NO: tuple[str, ...] = (
    "enggak",
    "gak",
    "tidak",
    "ga usah",
    "nggak jadi",
    "nanti aja",
    "udah kok",
)

_STAGES: tuple[str, ...] = ("feelings", "context", "support")

_STAGE_PROMPTS: dict[str, tuple[str, ...]] = {
    "feelings": (
        "Cerita dong, sekarang kamu lagi ngerasain apa? Aku siap dengerin 💬",
        "Kamu boleh banget ngejelasin perasaanmu sekarang. Lagi campur aduk atau gimana nih?",
        "Mulai dari perasaanmu dulu ya. Lagi sedih, takut, atau capek? Spill aja di sini.",
    ),
    "context": (
        "Kalau kamu nyaman, ceritain apa yang bikin kamu ngerasa kayak gitu ya.",
        "Pemicunya apa nih? Aku pengen ngerti biar bisa nemenin kamu lebih pas.",
        "Ada kejadian tertentu yang bikin kamu down? Ceritain versi kamu aja.",
    ),
    "support": (
        "Menurut kamu, bantuan atau dukungan seperti apa yang lagi kamu butuhin sekarang?",
        "Ada orang yang kamu percaya buat diajak ngobrol langsung? Guru BK atau orang rumah mungkin?",
        "Kira-kira apa yang bisa bikin kamu ngerasa sedikit lebih baik saat ini?",
    ),
}

_GEN_Z_VALIDATIONS: tuple[str, ...] = (
    "Makasih udah percaya curhat ke ASKA, kamu keren banget berani cerita 💖",
    "Pelan-pelan aja ya, kamu nggak sendirian. ASKA di sini buat nemenin 🤗",
    "Apa pun yang kamu rasain valid kok. Tarik napas dulu, kita bahas bareng ya 😌",
)

_CLOSING_MESSAGES: tuple[str, ...] = (
    "Kalau butuh ngobrol lagi, tinggal panggil ASKA kapan aja. Jangan lupa ajak ngobrol guru BK atau orang dewasa yang kamu percaya ya 💪",
    "Terima kasih sudah cerita. Tetap jaga dirimu dan kalau makin berat, langsung hubungi guru BK atau orang rumah ya 🙏",
    "ASKA bangga sama kamu yang mau cerita. Sering-sering ngobrol sama guru BK/teman terpercaya biar kamu lebih ringan 🤍",
)

_CRITICAL_RESPONSES: tuple[str, ...] = (
    "Ini serius banget ya. Tolong segera hubungi guru BK, wali kelas, atau orang dewasa yang lagi ada di dekatmu sekarang juga 🙏",
    "ASKA bener-bener khawatir. Coba langsung cari bantuan ke guru BK atau orang dewasa yang kamu percaya, atau telepon 119 buat layanan darurat ya 🚨",
    "Kamu berharga banget. Tolong jangan sendirian, segera kontak guru BK, orang tua, atau layanan darurat di 119 supaya kamu dapet bantuan cepat ⚠️",
)

_SUPPORT_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "lonely",
        (
            "kesepian",
            "sendiri",
            "ga ada teman",
            "gak ada teman",
            "nggak ada teman",
            "merasa sendiri",
            "tidak ada teman",
        ),
        (
            "Rasa sepi itu berat, tapi kamu nggak sendirian. Coba ajak ngobrol guru BK atau teman yang kamu percaya ya 🤝",
            "Kalau merasa sendiri, kamu boleh cari kegiatan bareng temen atau cerita ke keluarga. ASKA juga siap nemenin kapan pun 👭",
        ),
    ),
    (
        "family",
        (
            "keluarga",
            "orang tua",
            "ayah",
            "ibu",
            "papa",
            "mama",
            "ortu",
            "rumah",
        ),
        (
            "Masalah keluarga memang bikin hati campur aduk. Kamu bisa coba bicara pelan-pelan sama orang dewasa yang kamu percaya di rumah atau guru BK 🏠",
            "Kalau lagi berat di rumah, ambil waktu buat nenangin diri dulu, lalu cerita ke orang dewasa yang paling kamu nyaman. Kamu berhak didengar ❤️",
        ),
    ),
    (
        "school_pressure",
        (
            "nilai",
            "ujian",
            "ulangan",
            "pekerjaan rumah",
            "pr",
            "tugas",
            "ranking",
            "rapor",
        ),
        (
            "Belajar boleh capek, tapi kamu nggak harus sempurna. Atur jadwal kecil-kecil dan jangan sungkan minta bantuan guru atau teman 💪",
            "Coba pecah tugas jadi langkah kecil dan kasih waktu istirahat ke diri sendiri. Kalau butuh, curhat ke guru BK atau teman belajar bareng 📚",
        ),
    ),
    (
        "relationship",
        (
            "teman",
            "bestie",
            "sahabat",
            "dibenci",
            "dimusuhi",
            "cekcok",
            "berantem",
            "toxic",
        ),
        (
            "Drama pertemanan bisa bikin capek. Ambil jeda dulu, lalu ngobrol baik-baik atau ajak guru BK jadi penengah kalau perlu 🤝",
            "Kalau ada temen yang bikin kamu down, kamu boleh fokus ke lingkungan yang suportif dan cerita ke guru atau keluarga supaya dapat sudut pandang baru 💬",
        ),
    ),
    (
        "self_worth",
        (
            "gak berharga",
            "tidak berharga",
            "tidak berguna",
            "gak berguna",
            "ga berguna",
            "low self esteem",
            "benci diri",
        ),
        (
            "Kamu itu berarti dan berharga. Coba ingat hal-hal kecil yang pernah bikin kamu bangga, dan cerita ke orang yang bisa menguatkan kamu 💖",
            "Rasa minder wajar kok. Fokus ke hal baik yang kamu punya dan jangan ragu minta support guru BK atau orang terdekat yang positif 🌟",
        ),
    ),
    (
        "stress",
        (
            "stress",
            "stres",
            "overthinking",
            "burnout",
            "capek banget",
            "lelah banget",
            "pusing banget",
        ),
        (
            "Kalau lagi penat banget, tarik napas dalam-dalam dan kasih jeda buat diri sendiri. Setelah itu cerita ke orang dewasa yang bisa bantu, ya 😌",
            "Overthinking tuh melelahkan. Kamu bisa coba tulis yang kamu rasain, lalu diskusikan ke guru BK atau orang tua supaya lebih ringan 📝",
        ),
    ),
)

_DEFAULT_SUPPORT_RESPONSES: tuple[str, ...] = (
    "Thank you udah spill cerita. Ingat, kamu boleh banget minta bantuan guru BK atau orang dewasa yang kamu percaya supaya makin lega 🤍",
    "Kamu kuat banget bisa cerita. Jangan lupa rawat diri sendiri, istirahat cukup, dan tetap terhubung dengan orang-orang yang sayang sama kamu 🌷",
    "ASKA ada di pihak kamu. Langkah kecil untuk cerita ini udah keren banget. Lanjutkan cari dukungan offline juga ya 🙌",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _contains_any(text: str, keywords: Sequence[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def detect_psych_intent(message: str) -> Optional[str]:
    if not message:
        return None
    lowered = _normalize(message)
    if _contains_any(lowered, _CRITICAL_KEYWORDS):
        return SEVERITY_CRITICAL
    if _contains_any(lowered, _ELEVATED_KEYWORDS):
        return SEVERITY_ELEVATED
    if _contains_any(lowered, _TRIGGER_KEYWORDS):
        return SEVERITY_GENERAL
    return None


def classify_message_severity(message: str, default: str = SEVERITY_GENERAL) -> str:
    lowered = _normalize(message)
    if _contains_any(lowered, _CRITICAL_KEYWORDS):
        return SEVERITY_CRITICAL
    if _contains_any(lowered, _ELEVATED_KEYWORDS):
        return SEVERITY_ELEVATED
    return default


def get_confirmation_prompt(severity: str = SEVERITY_GENERAL) -> str:
    base = (
        "ASKA siap dengerin cerita kamu. Beneran mau curhat sekarang? Tinggal bilang iya atau enggak aja."
    )
    if severity == SEVERITY_CRITICAL:
        base = (
            "Aku merasa ini penting banget buat dibahas. ASKA siap dengerin full. "
            "Kamu mau cerita lebih lanjut sekarang?"
        )
    elif severity == SEVERITY_ELEVATED:
        base = (
            "Kayaknya kamu lagi berat banget ya. ASKA siap nemenin. "
            "Mau lanjut curhat sekarang?"
        )
    return f"{base} 😊"


def is_positive_confirmation(message: str) -> bool:
    lowered = _normalize(message)
    return lowered in _CONFIRM_YES or lowered.startswith(("iya", "ya", "boleh", "lanjut"))


def is_negative_confirmation(message: str) -> bool:
    lowered = _normalize(message)
    return lowered in _CONFIRM_NO or lowered.startswith(("enggak", "gak", "ga", "nggak", "tidak"))


def is_stop_request(message: str) -> bool:
    lowered = _normalize(message)
    return _contains_any(lowered, _STOP_KEYWORDS)


def pick_validation_message() -> str:
    return random.choice(_GEN_Z_VALIDATIONS)


def pick_stage_prompt(stage: str) -> str:
    prompts = _STAGE_PROMPTS.get(stage)
    if not prompts:
        return "Kamu mau cerita apa pun, tulis aja di sini ya."
    return random.choice(prompts)


def pick_closing_message() -> str:
    return random.choice(_CLOSING_MESSAGES)


def pick_critical_message() -> str:
    return random.choice(_CRITICAL_RESPONSES)


def generate_support_message(
    message: str,
    stage: Optional[str] = None,
    severity: str = SEVERITY_GENERAL,
) -> str:
    lowered = _normalize(message)
    best_rule: Optional[tuple[str, tuple[str, ...], tuple[str, ...]]] = None
    for rule in _SUPPORT_RULES:
        _, keywords, _ = rule
        if _contains_any(lowered, keywords):
            best_rule = rule
            break

    if best_rule:
        responses = best_rule[2]
        support_text = random.choice(responses)
    else:
        support_text = random.choice(_DEFAULT_SUPPORT_RESPONSES)

    if severity == SEVERITY_CRITICAL:
        support_text = (
            f"{support_text} Jangan tunggu lama, segera cari guru BK atau orang dewasa yang bisa nemenin kamu sekarang juga ya 🙏"
        )
    elif severity == SEVERITY_ELEVATED:
        support_text = (
            f"{support_text} Kalau makin berat, jangan ragu minta pendampingan langsung ke guru BK atau keluarga ya 💛"
        )

    if stage == "support":
        support_text = (
            f"{support_text} Kamu juga boleh sebut siapa yang paling kamu percaya buat jadi support system."
        )

    return support_text


def summarize_for_dashboard(message: str, max_chars: int = 200) -> str:
    clean = re.sub(r"\s+", " ", message or "").strip()
    if len(clean) <= max_chars:
        return clean
    snippet = clean[: max_chars - 3].rstrip()
    return f"{snippet}..."


def next_stage(current_stage: Optional[str]) -> Optional[str]:
    if current_stage is None:
        return _STAGES[0]
    try:
        idx = _STAGES.index(current_stage)
    except ValueError:
        return None
    if idx + 1 < len(_STAGES):
        return _STAGES[idx + 1]
    return None


def stage_exists(stage: Optional[str]) -> bool:
    return stage in _STAGES


__all__ = [
    "SEVERITY_GENERAL",
    "SEVERITY_ELEVATED",
    "SEVERITY_CRITICAL",
    "detect_psych_intent",
    "classify_message_severity",
    "get_confirmation_prompt",
    "is_positive_confirmation",
    "is_negative_confirmation",
    "is_stop_request",
    "pick_validation_message",
    "pick_stage_prompt",
    "pick_closing_message",
    "pick_critical_message",
    "generate_support_message",
    "summarize_for_dashboard",
    "next_stage",
    "stage_exists",
]
