"""Deteksi laporan bullying dan respons pendamping."""

from __future__ import annotations

import re
from typing import Iterable, Optional

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
)

_EXCLUSION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bapa itu (bully|bullying|perundungan)\b"),
    re.compile(r"\bcontoh (bully|bullying|perundungan)\b"),
    re.compile(r"\bcara (mencegah|menghindari) (bully|bullying|perundungan)\b"),
)

_REPORT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:aku|saya|gue|gw|gua|teman(?:ku)?|temen(?:ku)?|adik(?:ku)?|kakak(?:ku)?|keponakan|adik|teman|temen)\s+"
        r"(?:lagi\s+|sedang\s+)?di[a-z]*?(bul|bully|buly|buli|tindas|keroyok|ancam|sakiti|peleceh|cabuli|pukul|tampar|tendang)\b"
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


def get_bullying_ack_response(category: str = CATEGORY_GENERAL) -> str:
    """Respons default ketika user mengirim laporan bullying."""
    base = (
        "Terima kasih sudah cerita ke ASKA. Laporan kamu sudah ASKA teruskan ke tim sekolah. "
        "Kalau situasinya gawat atau butuh bantuan cepat, segera hubungi guru atau orang dewasa yang kamu percaya, ya."
    )

    if category == CATEGORY_SEXUAL:
        return (
            "ASKA dengerin kamu. Laporan pelecehan seksual ini langsung ASKA tandai sebagai prioritas tinggi. "
            "Jangan ragu untuk cari bantuan dari guru BK atau orang dewasa terpercaya di sekitarmu sekarang juga. "
            "Kalau kamu merasa tidak aman, tetap bareng teman atau orang dewasa yang bisa melindungi kamu."
        )
    if category == CATEGORY_PHYSICAL:
        return (
            "Kamu nggak sendirian. Laporan kekerasan fisik ini sudah ASKA teruskan supaya cepat ditindaklanjuti. "
            "Kalau situasinya makin bahaya, segera cari tempat aman dan hubungi guru atau satpam sekolah, ya."
        )
    return base


__all__ = [
    "detect_bullying_category",
    "get_bullying_ack_response",
    "CATEGORY_GENERAL",
    "CATEGORY_SEXUAL",
    "CATEGORY_PHYSICAL",
]
