"""Deteksi laporan konseling psikologis / curhat dan respons pendamping Gen-Z."""

from __future__ import annotations

import random
import re
from typing import Optional, Sequence


SEVERITY_GENERAL = "general"
SEVERITY_ELEVATED = "elevated"
SEVERITY_CRITICAL = "critical"

_TRIGGER_KEYWORDS: tuple[str, ...] = (
    "laporan konseling",
    "mau konseling",
    "butuh konseling",
    "layanan konseling",
    "konseling",
    "curhat",
    "laporan curhat",
    "mau curhat",
    "butuh curhat",
    "layanan curhat",
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
    # --- Penambahan Gaya Gen Z ---
    "mental health",
    "gak baik-baik aja",
    "spill the tea",
    "butuh temen",
    "pengen ngobrol",
    "capek",
    "sumpek",
    "butek",
    "ngerasa aneh",
    "ada yang mau aku ceritain",
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
    # --- Penambahan Gaya Gen Z ---
    "insecure",
    "insecure parah",
    "down parah",
    "ancur banget",
    "gaada harapan",
    "putus asa",
    "ngerasa gagal",
    "kena mental",
    "benci diri sendiri",
    "hampa",
    "pengen nyerah",
    "jadi beban",
    "gaada gunanya",
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
     # --- Penambahan Gaya Gen Z & Variasi ---
    "gamau hidup lagi",
    "gak mau hidup lagi",
    "ga mau hidup lagi",
    "lebih baik mati",
    "mending mati",
    "pengen hilang",
    "pengen udahan aja",
    "silet", # Sering digunakan sebagai kata benda untuk self-harm
    "cutter", "cuter",
    "sayat tangan",
    "sayat nadi",
    "loncat dari", # Frasa pemicu untuk loncat dari ketinggian
    "terjun dari",
    "tabrakin diri",
    "sh", # Singkatan umum untuk self-harm
)

_STOP_KEYWORDS: tuple[str, ...] = (
    "stop laporan konseling",
    "stop curhat",
    "udah cukup",
    "sampai sini",
    "makasih ya",
    "cukup curhat",
    "selesai curhat",
    "cukup curhatnya",
    "selesai curhatnya",
    # --- Penambahan Gaya Gen Z ---
    "udahan",
    "udah dulu ya",
    "ntar lagi",
    "nanti lagi deh",
    "segitu dulu",
    "thanks ya",
    "oke makasih",
    "selesai",
    "stop",
)

_CONFIRM_YES: tuple[str, ...] = (
    "iya", "ya", "yaa", "yaaa",
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
     # --- Penambahan Gaya Gen Z ---
    "kuy",
    "lanjutin",
    "bener",
    "hooh",
    "heeh",
    "sip",
    "siap",
    "betul",
    "yup",
)

_CONFIRM_NO: tuple[str, ...] = (
    "enggak",
    "gak",
    "tidak",
    "ga usah",
    "nggak jadi",
    "nanti aja",
    "udah kok",
    # --- Penambahan Gaya Gen Z ---
    "skip dulu",
    "skip",
    "gak dulu",
    "ga dulu",
    "ngga",
    "ga",
    "nope", "no"
    "jangan dulu",
    "lain kali aja",
    "kayaknya engga deh",
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
    "Makasih udah percaya buat spill ke ASKA. Kamu keren banget udah berani speak up! 💖✨",
    "Pelan-pelan aja ceritanya, kamu gak sendirian. ASKA bakal di sini nemenin kamu, for real! 🤗",
    "Apapun yang kamu rasain itu valid, bestie. Tarik napas dulu... kita hadapi bareng-bareng, ya! 😌",
    "Sending virtual hug! 🤗 Makasih udah mau terbuka, you're so strong! 💪",
)

_CLOSING_MESSAGES: tuple[str, ...] = (
    "Kalau butuh ngobrol lagi, tinggal panggil ASKA kapan aja. Jangan lupa ajak ngobrol guru BK atau orang dewasa yang kamu percaya ya 💪",
    "Terima kasih sudah cerita. Tetap jaga dirimu dan kalau makin berat, langsung hubungi guru BK atau orang rumah ya 🙏",
    "ASKA bangga sama kamu yang mau cerita. Sering-sering ngobrol sama guru BK/teman terpercaya biar kamu lebih ringan 🤍",
    "Inget ya, kamu gak sendirian. Kalo butuh temen ngobrol lagi, ASKA always here for you! Jangan ragu juga buat reach out ke guru BK atau orang yang kamu percaya, oke? Stay strong! 💪",
    "Thanks for sharing! Jaga diri baik-baik ya. Kalau bebannya makin berat, please langsung ngobrol sama guru BK atau keluargamu 🙏",
    "ASKA bangga banget sama kamu yang udah mau cerita. Sering-sering ngobrol sama support system kamu ya biar hati lebih plong! 🤍",
    "See you when I see you! Jangan lupa buat self-care ya, kamu pantes buat bahagia. ✨",
)

_CRITICAL_RESPONSES: tuple[str, ...] = (
    "Ini serius banget ya. Tolong segera hubungi guru BK, wali kelas, atau orang dewasa yang lagi ada di dekatmu sekarang juga 🙏",
    "ASKA bener-bener khawatir. Coba langsung cari bantuan ke guru BK atau orang dewasa yang kamu percaya, atau telepon 119 buat layanan darurat ya 🚨",
    "Kamu berharga banget. Tolong jangan sendirian, segera kontak guru BK, orang tua, atau layanan darurat di 119 supaya kamu dapet bantuan cepat ⚠️",
    "Bestie, ini serius banget. ASKA khawatir. Please, jangan sendirian ya. Langsung cari guru BK, wali kelas, atau orang dewasa terdekat SEKARANG. Atau call 119 ya, please 🙏🚨",
    "Hey, kamu berharga banget. Tolong jangan pendem ini sendirian. Segera kontak guru BK, orang tua, atau layanan darurat di 119 biar kamu dapet bantuan secepatnya, okay? ⚠️",
    "ASKA mohon banget, please cari bantuan sekarang juga. Ngobrol sama guru BK atau orang dewasa yang ada di deketmu. Your life matters! 💖",
)

_SUPPORT_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "lonely",
        (
            "kesepian", "sendiri", "ga ada teman", "gak punya temen", "merasa sendiri",
            "ditinggalin", "ngerasa ditinggalin", "ga punya circle",
        ),
        (
            "Ngerasa sepi itu emang ga enak banget 😔. Tapi inget, kamu ga sendirian kok. Coba deh reach out ke temen deket atau guru BK. ASKA juga di sini nemenin kamu! 🤝",
            "Feeling lonely sucks. Coba deh join ekskul atau komunitas yang kamu suka, siapa tau nemu temen baru! ASKA is rooting for you! 👭",
        ),
    ),
    (
        "family",
        (
            "keluarga", "orang tua", "ortu", "ayah", "ibu", "papa", "mama", "rumah",
            "berantem sama ortu", "broken home", "suasana rumah",
        ),
        (
            "Duh, masalah keluarga emang complicated 💔. Coba omongin pelan-pelan sama orang dewasa di rumah yang kamu percaya, atau curhat ke guru BK bisa ngebantu banget loh.",
            "Kalau suasana di rumah lagi panas, coba cari waktu buat nenangin diri dulu. Kamu berhak buat didengerin dan ngerasa aman. ❤️",
        ),
    ),
    (
        "school_pressure",
        (
            "nilai", "ujian", "ulangan", "pr", "tugas", "ranking", "rapor", "sekolah",
            "pelajaran susah", "remedial", "tugas numpuk", "dimarahin guru",
        ),
        (
            "Pressure sekolah emang suka bikin puyeng 🤯. It's okay to not be okay. Coba deh kerjain tugasnya dikit-dikit, jangan lupa istirahat juga. Semangat! 🔥",
            "Belajar itu maraton, bukan sprint. Coba bikin jadwal yang chill & jangan ragu minta bantuan guru atau temen yang jago. You can do this! 📚",
        ),
    ),
    (
        "relationship",
        (
            "teman", "bestie", "sahabat", "dibenci", "dimusuhi", "cekcok", "berantem",
            "toxic", "circle", "dighosting", "musuhan", "pacar", "mantan", "gebetan",
        ),
        (
            "Friendship drama tuh emang nguras energi banget 😮‍💨. Coba ambil jarak dulu bentar. Kalo udah adem, baru deh diobrolin baik-baik. Kamu pantes dapet circle yang positif! ✨",
            "Kalau ada temen yang bikin kamu ngerasa down, it's okay to set boundaries. Prioritasin mental health kamu, ya! 💬",
        ),
    ),
    (
        "self_worth",
        (
            "gak berharga", "gak berguna", "insecure", "benci diri", "jelek", "bodoh",
            "gagal", "ga berguna", "aku beban", "nyusahin", "minder",
        ),
        (
            "Hey, you are enough and you matter! 💖 Coba deh list 3 hal kecil yang kamu suka dari diri kamu. Kalo lagi down, ngobrol sama orang yang bisa naikin mood kamu ya!",
            "Rasa insecure itu wajar, tapi jangan biarin dia ngontrol kamu. Fokus ke progress, bukan kesempurnaan. Kamu itu a masterpiece and a work in progress at the same time! 🌟",
        ),
    ),
    (
        "stress",
        (
            "stress", "stres", "overthinking", "burnout", "capek banget", "pusing banget",
            "cemas parah", "panik", "anxious", "khawatir",
        ),
        (
            "Stres & overthinking emang nyebelin banget 😫. Coba deh lakuin hal yang kamu suka buat ngalihin pikiran sejenak. Nulis jurnal juga bisa bantu ngeluarin unek-unek, lho! 📝",
            "Kalau lagi penat, coba deh tarik napas dalem-dalem. It's okay to take a break. Habis itu, coba cerita ke guru BK atau ortu biar bebannya kebagi, ya! 😌",
        ),
    ),
)

_DEFAULT_SUPPORT_RESPONSES: tuple[str, ...] = (
    "Thank you udah spill cerita. Ingat, kamu boleh banget minta bantuan guru BK atau orang dewasa yang kamu percaya supaya makin lega 🤍",
    "Kamu kuat banget bisa cerita. Jangan lupa rawat diri sendiri, istirahat cukup, dan tetap terhubung dengan orang-orang yang sayang sama kamu 🌷",
    "ASKA ada di pihak kamu. Langkah kecil untuk cerita ini udah keren banget. Lanjutkan cari dukungan offline juga ya 🙌",
    "Makasih udah mau terbuka, you're so strong! 💪 Inget, ngobrol sama guru BK atau orang yang kamu percaya bisa bikin lega lho. Take care, ya! 🤍",
    "Kamu hebat banget udah bisa lewatin ini semua. Jangan lupa self-care, istirahat yang cukup, dan kelilingi dirimu sama orang-orang yang positif! 🌷",
    "ASKA ada di pihak kamu, 100%! Cerita ini langkah awal yang keren. Jangan berhenti di sini ya, terus cari support system di dunia nyata juga! 🙌",
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
        "ASKA here! Siap jadi kuping buat semua cerita kamu. Mau spill the tea sekarang? Bilang 'kuy' atau 'skip dulu' aja 😉"
    )
    if severity == SEVERITY_CRITICAL:
        base = (
             # Prompt yang lebih serius dan mendesak untuk situasi kritis
            "Hey, ASKA ngerasa ini penting banget. Please, jangan dipendem sendiri. Kamu mau cerita lebih dalem sekarang? Aku di sini buat kamu. 🙏"
        )
    elif severity == SEVERITY_ELEVATED:
        base = (
             "Kayaknya lagi berat banget ya? 🥺 ASKA siap dengerin kok, no judgement. Mau cerita sekarang?"
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
        return "Kamu mau cerita apa pun, tulis aja di sini ya, ASKA dengerin kok. 😊"
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
            f"{support_text} Please, jangan ditunda, segera cari guru BK atau orang dewasa yang bisa nemenin kamu sekarang juga ya 🙏"
        )
    elif severity == SEVERITY_ELEVATED:
        support_text = (
            f"{support_text} Kalau rasanya makin berat, please jangan hadapi sendirian. Reach out ke guru BK atau keluarga-mu ya! 💛"
        )

    if stage == "support":
        support_text = (
            f"{support_text} Btw, siapa sih orang yang paling kamu percaya buat jadi support system-mu?"
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
