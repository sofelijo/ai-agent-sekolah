"""Deteksi laporan bullying dan respons pendamping."""

from __future__ import annotations

import os
import random
import re
from typing import Iterable, Optional

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - import guard saat OpenAI SDK tak tersedia
    OpenAI = None  # type: ignore[misc,assignment]

_BULLYING_KEYWORDS: tuple[str, ...] = (
    "bully",
    "bullying",
    "dibully",
    "dibuli",
    "membully",
    "membuli",
    "perundungan",
    "perundung",
    "intimidasi",
    "ditindas",
    "penindasan",
    "pemalakan",
    "memalak",
    "diancam",
    "ancaman",
    "dikeroyok",
    "kekerasan",
    "disakiti",
      ### PENAMBAHAN GEN Z ###
    "dijahatin",
    "dijahilin",
    "diganggu",
    "diejek",
    "dikatain",
    "dijauhin",
    "dimusuhin",
    "dipalak",
    "diperas",
    "disindir",
    "body shaming",
)

_REPORT_SIGNALS: tuple[str, ...] = (
    "tolong",
    "minta tolong",
    "bantu",
    "minta bantuan",
    "lapor",
    "melapor",
    "laporan",
    "laporin",
    "report",
    "lapor dong",
    ### PENAMBAHAN GEN Z ###
    "help",
    "plis",
    "please",
    "gimana cara lapor",
    "mau ngadu",
    "mau laporin",
)

_PRONOUN_HINTS: tuple[str, ...] = (
    "aku",
    "saya",
    "gue",
    "gw",
    "gua",
    "kami",
    "kita",
    "teman",
    "temen",
    "adik",
    "kakak",
    "adikku",
    "temanku",
    "temenku",
      ### PENAMBAHAN GEN Z ###
    "doi",
    "dia",
    "bestie",
    "sahabat",
)

_SEXUAL_KEYWORDS: tuple[str, ...] = (
    "pelecehan",
    "seksual",
    "seks",
    "cabul",
    "dicabuli",
    "cabuli",
    "melecehkan",
    "dilecehkan",
    "diraba",
    "meraba",
    "dirangkul paksa",
    "disentuh",
    "dipegang",
    "aurat",
    "meremas",
    "mesum",
    ### PENAMBAHAN GEN Z ###
    "catcalling",
    "dicatcall",
    "dilecehin",
    "digodain",
    "dikirim foto aneh",
    "pap aneh", "dimintain pap",
    "grooming",
    "digrepe",
    "dipeluk",
)

_PHYSICAL_KEYWORDS: tuple[str, ...] = (
    "dipukul",
    "memukul",
    "pemukulan",
    "ditendang",
    "menendang",
    "ditampar",
    "menampar",
    "dikeroyok",
    "dijambak",
    "dianiaya",
    "penganiayaan",
    "didorong",
    "dicekik",
    "ditusuk",
    "disiksa",
    "kekerasan fisik",
    ### PENAMBAHAN GEN Z ###
    "digebukin",
    "dihajar",
    "ditonjok",
    "dijegal",
    "disundut",
    "dilempar",
    "dibunuh",
)

_EXCLUSION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bapa itu (bully|bullying|perundungan)\b"),
    re.compile(r"\bcontoh (bully|bullying|perundungan)\b"),
    re.compile(r"\bcara (mencegah|menghindari) (bully|bullying|perundungan)\b"),
)

_REPORT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:aku|saya|gue|gw|gua|teman(?:ku)?|temen(?:ku)?|adik(?:ku)?|kakak(?:ku)?|keponakan|adik|teman|temen)\s+"
        r"(?:lagi\s+|sedang\s+)?di[\s-]*[a-z]*?(bul|bully|buly|buli|tindas|keroyok|ancam|sakiti|peleceh|cabuli|pukul|tampar|tendang)\b"
    ),
    re.compile(r"\bkorban\s+(?:bully|bullying|perundungan|intimidasi|penindasan|pelecehan)\b"),
    re.compile(r"\bada\s+(?:kejadian\s+)?(?:bully|bullying|perundungan|intimidasi|pemalakan|pelecehan|pemukulan)\b"),
    re.compile(r"\blagi\s*(?:dibully|dibuli|diintimidasi)\b"),
)

_SEXUAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bpelecehan\s+seksual\b"),
    re.compile(r"\bdi(?:lecehkan|cabuli|pegang|raba)\b"),
    re.compile(r"\bdiganggu\s+secara\s+seksual\b"),
)

_PHYSICAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:di|ke)\s*pukul\b"),
    re.compile(r"\bdi(tendang|tampar|siksa|keroyok|aniaya)\b"),
    re.compile(r"\b(dianiaya|penganiayaan)\b"),
)

CATEGORY_GENERAL = "general"
CATEGORY_SEXUAL = "sexual"
CATEGORY_PHYSICAL = "physical"

_CATEGORY_LABELS: dict[str, str] = {
    CATEGORY_GENERAL: "perundungan (verbal atau sosial)",
    CATEGORY_SEXUAL: "pelecehan atau kekerasan bernuansa seksual",
    CATEGORY_PHYSICAL: "kekerasan fisik",
}

_CATEGORY_SAFETY_HINTS: dict[str, str] = {
    CATEGORY_GENERAL: (
        "ingatkan untuk cari dukungan dari guru BK, wali kelas, atau orang dewasa tepercaya tanpa memaksa mereka bercerita ulang"
    ),
    CATEGORY_SEXUAL: (
        "tegaskan bahwa korban tidak bersalah, anjurkan segera cari bantuan orang dewasa tepercaya dan tetap bersama orang yang aman"
    ),
    CATEGORY_PHYSICAL: (
        "ingatkan prioritas keselamatan fisik, sarankan menjauh dari pelaku dan menghubungi guru, satpam, atau orang dewasa tepercaya"
    ),
}

_CONVERSATION_STAGES: tuple[str, ...] = ("feelings", "context", "support")

_STAGE_OBJECTIVES: dict[str, str] = {
    "feelings": "validasi perasaan mereka dan apresiasi keberanian buat speak up.",
    "context": "gali kronologi/pemicunya secara lembut tanpa menginterogasi supaya kamu paham situasinya.",
    "support": "arahkan ke langkah aman: cari guru BK/orang dewasa tepercaya, lindungi diri, dokumentasi bukti bila aman.",
}

_STAGE_PROMPTS: dict[str, tuple[str, ...]] = {
    "feelings": (
        "Yang penting sekarang gimana kamu ngerasainnya, boleh spill ke aku ya 💬",
        "Aku mau pastiin kamu didengerin. Kamu lagi ngerasa apa banget detik ini?",
        "Ceritain dulu perasaan kamu ya—takut, kesel, sedih—semua valid kok 💛",
    ),
    "context": (
        "Kalau kamu ready, boleh share apa yang kejadian? Biar aku bisa bantu lebih tepat 🙏",
        "Yang bikin kamu ngerasa gini apa aja sih? Spill pelan-pelan ya, aku dengerin kok 🤗",
        "Kalo kamu nyaman, ceritain detailnya biar kita bisa cari langkah aman bareng-bareng 📌",
    ),
    "support": (
        "Sekarang yuk pikirin langkah aman. Siapa orang dewasa yang paling bisa diandalkan buat bantu kamu?",
        "Menurut kamu, apa yang paling urgent buat bikin kamu ngerasa lebih aman sekarang? 💡",
        "Aku ada di sini, tapi kamu juga butuh backup. Guru BK, wali kelas, atau orang rumah yang kamu percaya siapa?",
    ),
}

_LLM_MODEL = os.getenv("ASKA_BULLYING_MODEL") or os.getenv("ASKA_QA_MODEL") or "llama-3.1-8b-instant"
_LLM_TEMPERATURE = float(os.getenv("ASKA_BULLYING_TEMPERATURE", "0.4"))
_LLM_MAX_OUTPUT_TOKENS = int(os.getenv("ASKA_BULLYING_MAX_TOKENS", "280"))
_llm_client: Optional[OpenAI] = None
_llm_client_failed = False
_LLM_API_BASE = (
    os.getenv("ASKA_BULLYING_API_BASE")
    or os.getenv("ASKA_OPENAI_API_BASE")
    or os.getenv("OPENAI_API_BASE")
    or os.getenv("ASKA_GROQ_API_BASE")
    or "https://api.groq.com/openai/v1"
)

_STOP_KEYWORDS: tuple[str, ...] = (
    "udah","dah",
    "udah kok",
    "udah ya",
    "udahan",
    "cukup",
    "cukup ya",
    "segitu aja",
    "itu aja",
    "selesai",
    "selesai ya",
    "stop",
    "makasih ask",
    "makasih aska",
    "makasi ask",
    "makasih kak",
    "thx aska",
    "thanks ask",
)

_OPENING_MESSAGES: dict[str, tuple[str, ...]] = {
    CATEGORY_GENERAL: (
        "Bestie, makasih udah berani spill ke ASKA 💛 Ceritain aja pelan-pelan, aku dengerin tanpa nge-judge. "
        "Kalau nanti udah selesai, tinggal bilang 'udah ya' biar aku bantu wrap up.",
        "Heyy! Kamu keren banget mau speak up. Spill semuanya sepuasnya ya, aku standby nemenin ✨ "
        "Kalau udah kelar, infoin aja biar kita tutup bareng.",
    ),
    CATEGORY_PHYSICAL: (
        "Ya ampun, aku ikut ngerasain deg-degannya 😣 Ceritain detailnya pelan-pelan aja, aku jagain space ini buat kamu. "
        "Kalau udah selesai, tinggal bilang 'udah ya'.",
        "Makasih udah share, aku dengerin full. Langsung spill aja apa yang kejadian biar aku bisa bantu maksimal 💪 "
        "Nanti kalau udah selesai, kasih kode ya.",
    ),
    CATEGORY_SEXUAL: (
        "Aku dengerin kamu seutuhnya, dan kamu gak sendirian 🤍 Spill aja semua yang bikin kamu gak nyaman. "
        "Kalau udah cukup ceritanya, tinggal bilang 'udah ya' biar aku bantu next step aman.",
        "Pelan-pelan aja ya, aku ada di sini buat kamu. Ceritain apa yang terjadi semampunya. "
        "Kalau kamu merasa udah cukup, tinggal bilang aja biar aku wrap up dengan aman 🫶",
    ),
}

_FOLLOWUP_FALLBACKS: dict[str, tuple[str, ...]] = {
    CATEGORY_GENERAL: (
        "Aku nangkep vibes kamu soal '{snippet}'. Ambil napas dulu, terus spill lagi kalau siap ya ☕️💛",
        "Noted banget, bestie. Rasanya pasti berat pas bilang '{snippet}'. Aku tetep di sini nemenin kamu 🤗✨",
        "Aku dengerin semua curhatmu barusan. Kalau ada detail lain, lanjut aja ya—aku stay dengerin ❤️‍🩹",
    ),
    CATEGORY_PHYSICAL: (
        "Deg-degan banget dengernya pas kamu ceritain '{snippet}'. Aku jaga space ini buat kamu, lanjut kalau siap ya 🛡️💛",
        "Aku nangkep kamu lagi cerita soal kejadian kasar itu. Pelan-pelan aja, aku siap dengerin lanjutan ceritanya 🤝",
        "Thanks udah share detailnya. Kalau masih ada yang bikin kamu takut, spill lagi aja ya—aku di sini buat kamu 💪😢",
    ),
    CATEGORY_SEXUAL: (
        "Aku serius dengerin kamu waktu bilang '{snippet}'. Kamu aman buat spill lanjutan kapan pun siap ya 🤍🫶",
        "Aku kerasa beratnya cerita kamu barusan. Tarik napas dulu, terus kalau masih kuat, kamu bisa lanjut pelan-pelan 💗",
        "Makasih udah terbuka sejauh ini. Kalau masih ada yang ngeganjel, lanjut aja ya—aku siap nenangin kamu 💞",
    ),
}

_TIMEOUT_MESSAGE = (
    "Karena kamu belum balas lagi lebih dari 10 menit, aku tutup dulu sesi curhat bullying-nya ya. "
    "Kalau mau lanjut atau ada update baru, tinggal chat aku lagi kapan pun. Aku selalu standby buat kamu 🤍"
)


def _get_llm_client() -> Optional[OpenAI]:
    """Cache dan kembalikan klien OpenAI jika tersedia."""
    global _llm_client, _llm_client_failed
    if _llm_client_failed:
        return None
    if OpenAI is None:
        return None
    if _llm_client is None:
        api_key = (
            os.getenv("ASKA_BULLYING_API_KEY")
            or os.getenv("GROQ_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )
        if not api_key:
            print("[BULLYING] GROQ_API_KEY atau OPENAI_API_KEY belum di-set; respons bullying dimatikan.")
            _llm_client_failed = True
            return None
        try:
            _llm_client = OpenAI(api_key=api_key, base_url=_LLM_API_BASE)
        except Exception as exc:  # pragma: no cover - kegagalan inisialisasi SDK
            print(f"[BULLYING] Gagal inisialisasi klien Groq/OpenAI-compatible: {exc}")
            _llm_client_failed = True
            return None
    return _llm_client


def _sanitize_report_text(text: Optional[str]) -> str:
    if not text:
        return "pengguna belum memberikan detail tambahan."
    cleaned = re.sub(r"\s+", " ", text.strip())
    if not cleaned:
        return "pengguna belum memberikan detail tambahan."
    if len(cleaned) > 600:
        cleaned = cleaned[:600].rstrip()
        if not cleaned.endswith("…"):
            cleaned += "…"
    return cleaned


def _generate_bullying_response_via_llm(category: str, report_text: Optional[str]) -> Optional[str]:
    client = _get_llm_client()
    if client is None:
        return None

    category_label = _CATEGORY_LABELS.get(category, _CATEGORY_LABELS[CATEGORY_GENERAL])
    safety_hint = _CATEGORY_SAFETY_HINTS.get(category, _CATEGORY_SAFETY_HINTS[CATEGORY_GENERAL])
    report_excerpt = _sanitize_report_text(report_text)

    system_message = (
        "Kamu adalah ASKA, teman digital yang suportif untuk siswa sekolah dasar. "
        "Jawablah dengan Bahasa Indonesia santun nan hangat, terasa seperti kakak yang peduli. "
        "Validasi perasaan, hargai keberanian, dan arahkan langkah aman tanpa menginterogasi. "
        "Jangan sebut kamu memantau, mencatat laporan, atau meneruskan ke pihak lain."
    )
    user_message = (
        f"Ada siswa yang bercerita soal {category_label}. "
        f"Detail dari pengguna: {report_excerpt}\n\n"
        "Buat satu jawaban maksimal empat kalimat (tanpa bullet). "
        "Fokus: 1) apresiasi keberanian memberi tahu, 2) validasi rasa takut/sedih mereka, "
        "3) ingatkan langkah aman: {safety_hint}, 4) tawarkan untuk tetap ada bila mereka mau cerita lagi. "
        "Bahasa harus ringan, empatik, dan pakai slang Gen Z Indonesia sewajarnya (contoh: bestie, spill, vibes). "
        "Hindari pertanyaan lanjutan, hindari kata 'laporan', 'monitor', 'pantau', atau 'catat'. "
        "Gunakan 2-3 emoji hangat yang relevan."
    ).format(safety_hint=safety_hint)

    try:
        response = client.chat.completions.create(
            model=_LLM_MODEL,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            temperature=_LLM_TEMPERATURE,
            max_tokens=_LLM_MAX_OUTPUT_TOKENS,
        )
    except Exception as exc:  # pragma: no cover - kesalahan pemanggilan API
        print(f"[BULLYING] Gagal memanggil OpenAI chat: {exc}")
        return None

    choice = response.choices[0] if response.choices else None
    message = getattr(choice, "message", None)
    content = getattr(message, "content", None) if message else None
    if not content:
        return None

    cleaned = content.strip()
    if not cleaned:
        return None
    return cleaned


def _summarize_snippet(text: Optional[str], *, limit: int = 80) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", text.strip())
    if len(cleaned) <= limit:
        return cleaned
    snippet = cleaned[: limit - 1].rstrip()
    return f"{snippet}…"


def _generate_bullying_live_response_via_llm(
    category: str,
    *,
    aggregated_text: str,
    latest_message: str,
) -> Optional[str]:
    client = _get_llm_client()
    if client is None:
        return None

    category_label = _CATEGORY_LABELS.get(category, _CATEGORY_LABELS[CATEGORY_GENERAL])
    report_excerpt = _sanitize_report_text(aggregated_text)
    latest_excerpt = _sanitize_report_text(latest_message)

    system_message = (
        "Kamu adalah ASKA, sahabat digital yang empatik buat siswa sekolah dasar. "
        "Jawab dengan Bahasa Indonesia bernuansa Gen Z (slang sopan) dan hangat. "
        "Tunjukkan kamu memahami isi curhat terbaru, berikan validasi perasaan, "
        "dan ajak mereka tetap cari dukungan aman tanpa menginterogasi. "
        "Jangan sebut tentang memantau, mencatat, atau meneruskan laporan."
    )
    user_message = (
        f"Ini sesi curhat bullying tentang {category_label}.\n"
        f"Ringkasan obrolan sejauh ini: {report_excerpt}\n"
        f"Pesan terbaru siswa: {latest_excerpt}\n\n"
        "Buat satu tanggapan singkat maksimal tiga kalimat (tanpa bullet). "
        "Harus terasa natural, sokong perasaan mereka, sebut langkah aman bila relevan, "
        "dan ajak mereka lanjut cerita kalau mau. "
        "Gunakan 1-3 emoji hangat, hindari pertanyaan lanjutan ataupun frasa monitoring/administratif."
    )

    try:
        response = client.chat.completions.create(
            model=_LLM_MODEL,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            temperature=_LLM_TEMPERATURE,
            max_tokens=min(_LLM_MAX_OUTPUT_TOKENS, 220),
        )
    except Exception as exc:  # pragma: no cover - pemanggilan API gagal
        print(f"[BULLYING] Gagal memanggil OpenAI chat (live follow-up): {exc}")
        return None

    choice = response.choices[0] if response.choices else None
    message = getattr(choice, "message", None)
    content = getattr(message, "content", None) if message else None
    if not content:
        return None
    cleaned = content.strip()
    return cleaned or None


def _generate_bullying_conversation_via_llm(
    *,
    category: str,
    aggregated_text: Optional[str],
    latest_message: Optional[str],
    stage: Optional[str],
    next_stage: Optional[str],
    severity: str,
    message_index: int,
) -> Optional[str]:
    client = _get_llm_client()
    if client is None:
        return None

    category_label = _CATEGORY_LABELS.get(category, _CATEGORY_LABELS[CATEGORY_GENERAL])
    conversation_excerpt = _sanitize_report_text(aggregated_text)
    latest_excerpt = _sanitize_report_text(latest_message)

    stage_objective = _STAGE_OBJECTIVES.get(
        stage or "",
        "tetap jadi pendengar suportif, validasi emosi mereka, dan bantu mikirin langkah aman tanpa menginterogasi.",
    )
    next_stage_objective = (
        _STAGE_OBJECTIVES.get(next_stage or "", "")
        if next_stage
        else ""
    )

    if severity == "critical":
        severity_hint = (
            "Situasi KRITIS. Tekankan mereka harus segera hubungi guru BK, wali kelas, orang tua, "
            "atau layanan darurat 119 dan jangan hadapi pelaku sendirian."
        )
    elif severity == "high":
        severity_hint = (
            "Situasi FISIK/serius. Sarankan segera cari tempat aman, jauhi pelaku, dan minta bantuan guru BK "
            "atau orang dewasa tepercaya."
        )
    else:
        severity_hint = (
            "Tetap ingatkan untuk cerita ke guru BK atau orang dewasa yang dipercaya biar kasusnya ditangani."
        )

    if next_stage_objective:
        transition_hint = (
            f"Ajak perlahan menuju tahap {next_stage} (fokus: {next_stage_objective}) setelah merespon curhatnya."
        )
    else:
        transition_hint = (
            "Fokus di tahap sekarang dan ajak mereka lanjut cerita atau pikirkan langkah aman berikutnya."
        )

    system_message = (
        "Kamu ASKA, sahabat digital gen Z yang empatik buat siswa sekolah dasar. "
        "Gunakan Bahasa Indonesia santai ala bestie (tetap sopan), maksimal empat kalimat, sisipkan 1-3 emoji relevan. "
        "Validasi emosi mereka, sebut dukungan nyata (guru BK/orang dewasa tepercaya), dan jangan sebut memantau/catat laporan."
    )
    user_message = (
        f"Kategori kasus: {category_label}\n"
        f"Ringkasan obrolan sejauh ini: {conversation_excerpt}\n"
        f"Pesan terbaru siswa: {latest_excerpt}\n"
        f"Stage saat ini: {stage or 'feelings'} (tujuan: {stage_objective})\n"
        f"Nomor bubble: {message_index}\n"
        f"Instruksi tambahan: {transition_hint}\n"
        f"Severity: {severity}. {severity_hint}\n\n"
        "Buat jawaban hangat maksimal empat kalimat tanpa bullet. "
        "Panggil mereka dengan 'kamu', tunjukkan kamu paham isi curhatnya, "
        "dan tutup dengan ajakan lembut lanjut cerita atau ambil langkah aman."
    )

    try:
        response = client.chat.completions.create(
            model=_LLM_MODEL,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            temperature=_LLM_TEMPERATURE,
            max_tokens=min(_LLM_MAX_OUTPUT_TOKENS, 340),
        )
    except Exception as exc:  # pragma: no cover - kesalahan pemanggilan API
        print(f"[BULLYING] Gagal memanggil OpenAI chat (conversation): {exc}")
        return None

    choice = response.choices[0] if response.choices else None
    message = getattr(choice, "message", None)
    content = getattr(message, "content", None) if message else None
    if not content:
        return None
    cleaned = content.strip()
    return cleaned or None


def _pick_prompt(category: str, options_map: dict[str, tuple[str, ...]]) -> str:
    bucket = options_map.get(category) or options_map.get(CATEGORY_GENERAL) or ()
    if not bucket:
        return ""
    return random.choice(bucket)


def get_bullying_opening_prompt(category: str, stage: Optional[str] = None) -> str:
    """Pesan pembuka ketika user pertama kali curhat bullying."""
    opening = _pick_prompt(category, _OPENING_MESSAGES)
    stage_prompt = get_bullying_stage_prompt(stage)
    if stage_prompt:
        return f"{opening}\n\n{stage_prompt}"
    return opening


def get_bullying_stage_prompt(stage: Optional[str]) -> str:
    stage_key = stage if stage in _STAGE_PROMPTS else "feelings"
    prompts = _STAGE_PROMPTS.get(stage_key)
    if not prompts:
        return "Ceritain aja ya, aku dengerin kok. 😊"
    return random.choice(prompts)


def bullying_next_stage(current_stage: Optional[str]) -> Optional[str]:
    if current_stage is None:
        return _CONVERSATION_STAGES[0]
    try:
        idx = _CONVERSATION_STAGES.index(current_stage)
    except ValueError:
        return None
    if idx + 1 < len(_CONVERSATION_STAGES):
        return _CONVERSATION_STAGES[idx + 1]
    return None


def bullying_stage_exists(stage: Optional[str]) -> bool:
    return stage in _CONVERSATION_STAGES


def get_bullying_followup_response(
    category: str,
    *,
    latest_message: str,
    aggregated_text: str,
    message_index: int,
    stage: Optional[str],
    next_stage: Optional[str],
    severity: str,
) -> str:
    """Bangun respons selama sesi curhat berlangsung, prioritas pakai LLM."""
    live_response = _generate_bullying_conversation_via_llm(
        category=category,
        aggregated_text=aggregated_text,
        latest_message=latest_message,
        stage=stage,
        next_stage=next_stage,
        severity=severity,
        message_index=message_index,
    )
    if live_response:
        return live_response

    bucket = _FOLLOWUP_FALLBACKS.get(category) or _FOLLOWUP_FALLBACKS.get(CATEGORY_GENERAL, ())
    if not bucket:
        bucket = (
            "Aku denger kok ceritamu. Pelan-pelan aja lanjutinnya, aku di sini nemenin 💛",
        )
    index = (max(message_index, 1) - 1) % len(bucket)
    template = bucket[index]
    snippet = _summarize_snippet(latest_message) or "cerita kamu barusan"
    try:
        base = template.format(snippet=snippet)
    except Exception:
        base = template

    stage_prompt = get_bullying_stage_prompt(stage)
    response = f"{stage_prompt}\n\n{base}" if stage_prompt else base

    if severity == "critical":
        response = (
            f"{response}\n\nPlease banget, segera kontak guru BK/wali kelas atau orang dewasa tepercaya. "
            "Kalau situasinya bahaya, minta pendampingan atau hubungi layanan darurat ya 🙏🚨"
        )
    elif severity == "high":
        response = (
            f"{response}\n\nUtamain keselamatan kamu. Kalau pelaku masih ngeganggu, segera jauhi dan panggil guru atau satpam sekolah ya 🛡️"
        )
    else:
        response = (
            f"{response}\n\nJangan lupa kabarin guru BK atau orang dewasa yang kamu percaya biar mereka bisa bantu proses lanjut 💛"
        )

    return response


def get_bullying_conversation_reply(
    *,
    category: str,
    aggregated_text: Optional[str],
    latest_message: Optional[str],
    stage: Optional[str],
    next_stage: Optional[str],
    severity: str,
    message_index: int,
) -> Optional[str]:
    return _generate_bullying_conversation_via_llm(
        category=category,
        aggregated_text=aggregated_text,
        latest_message=latest_message,
        stage=stage,
        next_stage=next_stage,
        severity=severity,
        message_index=message_index,
    )


def get_bullying_timeout_message() -> str:
    """Pesan penutup ketika sesi berakhir karena timeout."""
    return _TIMEOUT_MESSAGE


def is_bullying_stop_request(message: str) -> bool:
    """Deteksi apakah user menandai curhat sudah selesai."""
    if not message:
        return False
    lowered = _normalize(message)
    return any(keyword in lowered for keyword in _STOP_KEYWORDS)


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _contains_any(text: str, candidates: Iterable[str]) -> bool:
    return any(candidate in text for candidate in candidates)


def detect_bullying_category(message: str) -> Optional[str]:
    """Return the bullying category if the message is a report."""
    if not message:
        return None

    normalized = _normalize(message)

    for pattern in _EXCLUSION_PATTERNS:
        if pattern.search(normalized):
            return None

    sexual_hit = _contains_any(normalized, _SEXUAL_KEYWORDS) or any(
        pattern.search(normalized) for pattern in _SEXUAL_PATTERNS
    )
    physical_hit = _contains_any(normalized, _PHYSICAL_KEYWORDS) or any(
        pattern.search(normalized) for pattern in _PHYSICAL_PATTERNS
    )
    has_core_keyword = _contains_any(normalized, _BULLYING_KEYWORDS) or sexual_hit or physical_hit
    has_signal = _contains_any(normalized, _REPORT_SIGNALS) or any(
        pattern.search(normalized) for pattern in _REPORT_PATTERNS
    )
    pronoun_present = _contains_any(normalized, _PRONOUN_HINTS)
    location_hint = any(hint in normalized for hint in ("kelas", "sekolah", "teman", "kawan"))
    has_context = has_signal or (pronoun_present and (location_hint or sexual_hit or physical_hit))

    if not has_core_keyword or not has_context:
        return None

    if sexual_hit:
        return CATEGORY_SEXUAL

    if physical_hit:
        return CATEGORY_PHYSICAL

    return CATEGORY_GENERAL


def get_bullying_ack_response(
    category: str = CATEGORY_GENERAL,
    *,
    report_text: Optional[str] = None,
) -> str:
    """Bangun respons empatik untuk laporan bullying, memanfaatkan LLM jika tersedia."""
    ai_response = _generate_bullying_response_via_llm(category, report_text)
    if ai_response:
        return ai_response

    base = (
        "Thank you banget udah spill ke ASKA, bestie 💛 Aku ikut ngerasain beratnya dan bakal stay nemenin kamu. "
        "Please reach out ke guru BK, wali kelas, atau orang dewasa tepercaya biar kamu gak ngadepin ini sendirian. "
        "Kalau situasinya makin bikin anxious, langsung minta bantuan mereka ya. Aku standby kapan pun kamu butuh. 🤗"
    )

    if category == CATEGORY_SEXUAL:
        return (
            "Makasih udah percaya cerita hal sepenting ini, kamu super brave 🫶 Apa pun yang terjadi, ini sama sekali bukan salah kamu. "
            "Please segera cari guru BK, wali kelas, atau orang dewasa tepercaya dan usahain tetep bareng orang yang bikin kamu feel safe. "
            "Kalau mau lanjut spill atau butuh ditemenin, tinggal panggil ASKA lagi ya. 🤍"
        )
    if category == CATEGORY_PHYSICAL:
        return (
            "Ikut ngilu dengernya, kamu kuat banget bisa cerita 😢 Keselamatan kamu nomor satu. "
            "Kalau situasinya belum aman, segera menjauh dari pelaku dan temui guru, satpam, atau orang dewasa yang kamu percaya biar mereka bisa backup kamu. "
            "Aku tetep ada di sini kapan pun kamu mau cerita lagi. 💪"
        )
    return base


__all__ = [
    "detect_bullying_category",
    "get_bullying_ack_response",
    "get_bullying_opening_prompt",
    "get_bullying_followup_response",
    "get_bullying_stage_prompt",
    "get_bullying_conversation_reply",
    "bullying_next_stage",
    "bullying_stage_exists",
    "get_bullying_timeout_message",
    "is_bullying_stop_request",
    "CATEGORY_GENERAL",
    "CATEGORY_SEXUAL",
    "CATEGORY_PHYSICAL",
    "_EXCLUSION_PATTERNS",
]
