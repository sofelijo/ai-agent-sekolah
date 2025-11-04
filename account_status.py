"""Shared helpers untuk status akun pengguna ASKA."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal, Optional

AccountStatus = Literal["active", "suspended", "under_review"]
Channel = Literal["web", "telegram", "generic"]

ACCOUNT_STATUS_ACTIVE: AccountStatus = "active"
ACCOUNT_STATUS_SUSPENDED: AccountStatus = "suspended"
ACCOUNT_STATUS_UNDER_REVIEW: AccountStatus = "under_review"

ACCOUNT_STATUS_CHOICES: tuple[AccountStatus, ...] = (
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_STATUS_SUSPENDED,
    ACCOUNT_STATUS_UNDER_REVIEW,
)

ACCOUNT_STATUS_LABELS: Dict[AccountStatus, str] = {
    ACCOUNT_STATUS_ACTIVE: "Aktif",
    ACCOUNT_STATUS_SUSPENDED: "Suspended",
    ACCOUNT_STATUS_UNDER_REVIEW: "Ditinjau",
}

ACCOUNT_STATUS_BADGES: Dict[AccountStatus, str] = {
    ACCOUNT_STATUS_ACTIVE: "success",
    ACCOUNT_STATUS_SUSPENDED: "danger",
    ACCOUNT_STATUS_UNDER_REVIEW: "warning",
}

BLOCKING_STATUSES: set[AccountStatus] = {
    ACCOUNT_STATUS_SUSPENDED,
    ACCOUNT_STATUS_UNDER_REVIEW,
}

_STATUS_RESPONSES: Dict[AccountStatus, Dict[str, str]] = {
    ACCOUNT_STATUS_SUSPENDED: {
        "title": "Akun kamu lagi di-suspend",
        "web": (
            "Akun web ASKA kamu sementara dibekukan oleh sekolah. "
            "Hubungi pihak sekolah kalau mau aktif lagi ya."
        ),
        "telegram": (
            "Akun Telegram kamu lagi di-suspend 😔\n"
            "Silakan hubungi pihak sekolah kalau ingin pulihin akses."
        ),
        "generic": "Akun kamu lagi tidak aktif. Hubungi sekolah untuk info lanjut.",
    },
    ACCOUNT_STATUS_UNDER_REVIEW: {
        "title": "Akun sedang ditinjau",
        "web": (
            "Tim sekolah lagi ngecek aktivitas akun kamu. "
            "Sementara ini chat baru nggak bisa dulu ya."
        ),
        "telegram": (
            "Akun kamu lagi dalam proses review sama sekolah. "
            "Tunggu kabar berikutnya atau hubungi sekolah kalau mendesak."
        ),
        "generic": "Akun kamu lagi ditinjau. Silakan cek ke sekolah untuk info detailnya.",
    },
}


@dataclass
class StatusNotice:
    status: AccountStatus
    title: str
    message: str
    reason: Optional[str] = None


def build_status_notice(
    status: Optional[str],
    *,
    reason: Optional[str] = None,
    channel: Channel = "generic",
) -> Optional[StatusNotice]:
    """
    Bentuk pesan status siap kirim.
    Mengembalikan None kalau status tidak butuh notifikasi khusus.
    """
    if not status or status not in ACCOUNT_STATUS_CHOICES:
        return None
    meta = _STATUS_RESPONSES.get(status)
    if not meta:
        return None
    channel_key = channel if channel in {"web", "telegram"} else "generic"
    body = meta.get(channel_key) or meta.get("generic")
    if not body:
        body = ACCOUNT_STATUS_LABELS.get(status, "Status akun tidak aktif.")
    if reason:
        trimmed = reason.strip()
        if trimmed:
            body = f"{body}\n\nCatatan sekolah: {trimmed}"
    return StatusNotice(
        status=status,
        title=meta.get("title") or ACCOUNT_STATUS_LABELS.get(status, "Status akun"),
        message=body.strip(),
        reason=reason,
    )


__all__ = [
    "AccountStatus",
    "Channel",
    "ACCOUNT_STATUS_CHOICES",
    "ACCOUNT_STATUS_LABELS",
    "ACCOUNT_STATUS_BADGES",
    "ACCOUNT_STATUS_ACTIVE",
    "ACCOUNT_STATUS_SUSPENDED",
    "ACCOUNT_STATUS_UNDER_REVIEW",
    "BLOCKING_STATUSES",
    "StatusNotice",
    "build_status_notice",
]
