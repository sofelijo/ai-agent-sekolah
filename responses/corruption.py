"""Deteksi laporan korupsi dan respons pendamping."""

from __future__ import annotations
import os
import uuid
import random
from typing import Iterable, Optional

# Impor fungsi untuk menyimpan laporan korupsi dari modul database
from db import record_corruption_report

# Kata kunci untuk mendeteksi niat laporan korupsi
_CORRUPTION_KEYWORDS: tuple[str, ...] = (
    "korupsi", "korup", "suap", "menyuap", "disuap", "pungli", 
    "pungutan liar", "gratifikasi", "tilep", "mark up", "markup", 
    "dana", "anggaran", "diselewengkan", "penyelewengan",
)

# Sinyal bahwa pengguna ingin membuat laporan
_REPORT_SIGNALS: tuple[str, ...] = (
    "lapor", "melaporkan", "laporan", "ngadu", "mengadu", "laporkan", "report",
)

# Pola yang perlu dihindari agar tidak salah terpicu
_EXCLUSION_PATTERNS: tuple[str, ...] = (
    "apa itu korupsi", "definisi korupsi", "contoh korupsi", "cara mencegah korupsi",
)
# Keywords to cancel the reporting flow
_CANCEL_KEYWORDS: tuple[str, ...] = ("batal", "cancel", "batalkan", "stop")

_STATUS_BASE_URL = os.getenv("ASKA_PUBLIC_BASE_URL", "https://aska.sdnsembar01.sch.id").rstrip("/")

# Kata kunci untuk intent "cara/tutor lapor korupsi"
_HOWTO_KEYWORDS: tuple[str, ...] = (
    "cara", "gimana", "bagaimana", "tutorial", "tutor", "gmn", "gimana sih",
)


def _normalize(text: str) -> str:
    """Membersihkan dan menormalkan teks input."""
    return " ".join(text.lower().split())


def _contains_any(text: str, candidates: Iterable[str]) -> bool:
    """Memeriksa apakah teks mengandung salah satu dari kandidat kata."""
    return any(candidate in text for candidate in candidates)


def _build_status_link(ticket_id: str) -> str:
    """Bangun URL pengecekan status yang bisa langsung dipakai user."""
    if not ticket_id:
        return "/cek-laporan"

    if _STATUS_BASE_URL:
        return f"{_STATUS_BASE_URL}/cek-laporan/{ticket_id}"

    return f"/cek-laporan/{ticket_id}"


def is_corruption_report_intent(message: str) -> bool:
    """
    Mendeteksi apakah pesan dari pengguna adalah niat untuk melaporkan korupsi.
    """
    if not message:
        return False

    normalized = _normalize(message)

    if _contains_any(normalized, _EXCLUSION_PATTERNS):
        return False

    has_keyword = _contains_any(normalized, _CORRUPTION_KEYWORDS)
    has_signal = _contains_any(normalized, _REPORT_SIGNALS)

    return has_keyword and has_signal


def is_corruption_howto_request(message: str) -> bool:
    """Deteksi pertanyaan cara/tutor melapor korupsi agar tidak langsung memulai flow laporan.

    Contoh yang harus terpicu:
    - "gimana cara lapor korupsi ke ASKA?"
    - "tutorial lapor pungli sekolah jakarta utara"
    - "bagaimana melaporkan korupsi lewat aska"
    """
    if not message:
        return False

    normalized = _normalize(message)
    if _contains_any(normalized, _EXCLUSION_PATTERNS):
        return False

    has_corruption = _contains_any(normalized, _CORRUPTION_KEYWORDS)
    asking_howto = _contains_any(normalized, _HOWTO_KEYWORDS) or (
        "cara lapor" in normalized or "cara melapor" in normalized or "tutorial lapor" in normalized
    )
    # Hindari bentrok: kalau user jelas2 minta mulai/report, jangan tangkap sebagai how-to.
    wants_to_start = _contains_any(normalized, _REPORT_SIGNALS)

    return has_corruption and asking_howto and not wants_to_start


def get_corruption_howto_response() -> str:
    """Berikan panduan singkat step-by-step untuk melapor via ASKA (fokus Jakarta Utara)."""
    status_home = _build_status_link("")
    return (
        "Mau lapor korupsi via ASKA? Siap! Ini step cepatnya buat wilayah pendidikan Jakarta Utara 🚀\n\n"
        "1) Ketik: 'lapor korupsi' atau 'mulai laporan korupsi' biar ASKA buka alur khusus.\n"
        "2) Jawab pertanyaan inti dari ASKA: siapa yang terlibat, lokasi, waktu, dan kronologi lengkapnya.\n"
        "3) Cek ringkasan yang ASKA kasih. Kalau udah pas, balas 'benar'. Kalau mau ubah, ketik 'edit'.\n"
        "4) Setelah tersimpan, kamu dapat tiket + link buat pantau progres tanpa login.\n\n"
        f"Pantau status di sini: {status_home}\n"
        "- Masukkan nomor tiket kalau sudah punya, atau klik link yang ASKA kasih setelah laporan tersimpan.\n\n"
        "Tips biar makin efektif: sebut jabatan/unit (kalau ada), lokasi spesifik (ruang/bagian), dan waktu setepat mungkin. Hindari sebar data pribadi yang nggak perlu. ASKA jaga privasimu. 🔐\n\n"
        "Kalau udah siap, langsung ketik: 'lapor korupsi' ya. ASKA standby! 💙"
    )


def mentions_corruption_only(message: str) -> bool:
    """Deteksi jika user menyebut isu korupsi tapi belum jelas ingin melapor atau hanya tanya cara.

    Dipakai untuk menampilkan saran/CTA ringan agar user tahu bisa melapor via ASKA.
    """
    if not message:
        return False
    normalized = _normalize(message)
    if _contains_any(normalized, _EXCLUSION_PATTERNS):
        return False
    has_corruption = _contains_any(normalized, _CORRUPTION_KEYWORDS)
    wants_to_start = _contains_any(normalized, _REPORT_SIGNALS)
    asking_howto = is_corruption_howto_request(normalized)
    return has_corruption and not wants_to_start and not asking_howto


class CorruptionResponse:
    """
    Mengelola alur percakapan untuk laporan korupsi dengan validasi, 
    konfirmasi, edit, dan pembatalan.
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.state = "idle"
        self.report_data = {}
        self.questions = [
            ("involved", [
                "OMG, gila sih ini korupsi 🤢, red flag parah! 🚩 ASKA bantu usut tuntas, spill dong siapa aja yang terlibat di kasus ini? 🕵️‍♀️\n\n👤 Pelaku:",
                "Oke, kita mulai investigasinya! 🕵️‍♂️ Korupsi itu big no no! ❌ Siapa aja nih oknum-oknum yang main kotor di kasus ini? Sebutin semua ke ASKA ya!\n\n👤 Pelaku:",
            ]),
            ("location", [
                "Oke, noted. Biar makin jelas jejaknya, spill TKP-nya di mana ke ASKA? Gak ada tempat aman buat koruptor! 🗺️📍\n\n📍 Lokasi:",
                "Sip, nama-namanya udah ASKA kunci. Sekarang, kejadiannya di mana nih? Biar kita bisa cek CCTV dan bukti lain. 📹\n\n📍 Lokasi:",
            ]),
            ("time", [
                "Sip, ASKA catet. Kapan nih kejadiannya? Detail waktu penting bgt buat ngelacak bukti, biar ga ada yg bisa ngeles! ⏰🗓️\n\n⏰ Waktu:",
                "Oke, lokasi udah. Sekarang, kapan waktunya? Pagi, siang, malem? Tanggal berapa? Kasih tau ASKA biar alibinya gampang dipatahin! 🧐\n\n⏰ Waktu:",
            ]),
            ("chronology", [
                "Makasih banyak udah berani speak up ke ASKA! 🙏 Kamu keren bgt! Sekarang, coba ceritain semua kronologinya dari A-Z, jangan ada yg ke-skip ya. The tea is hot! ☕️ Spill semuanya biar kita bisa bongkar tuntas kasus ini! 🔥\n\n📝 Kronologi:",
                "Kamu pahlawan! 🦸‍♀️ Makasih udah lapor ke ASKA. Sekarang, tolong ceritain alur ceritanya dari awal sampe akhir. Jangan ragu, ceritain aja semuanya. ASKA dengerin! 🎧\n\n📝 Kronologi:",
            ]),
        ]
        self.current_question_index = 0
        self.is_editing = False

    def start_report(self) -> str:
        """Memulai alur laporan dan menanyakan pertanyaan pertama."""
        self.state = "reporting"
        self.is_editing = False
        self.current_question_index = 0
        self.report_data = {}
        question_variations = self.questions[self.current_question_index][1]
        return random.choice(question_variations)

    def _generate_confirmation_message(self) -> str:
        """Menghasilkan pesan ringkasan laporan untuk konfirmasi."""
        involved = self.report_data.get('involved', 'N/A')
        location = self.report_data.get('location', 'N/A')
        time = self.report_data.get('time', 'N/A')
        chronology = self.report_data.get('chronology', 'N/A')

        return (
            "Oke, sebelum ASKA simpan, cek dulu ya laporannya udah bener atau belum:\n\n"
            f"🕵️  Siapa yang terlibat:\n{involved}\n\n"
            f"📍  Lokasi kejadian:\n{location}\n\n"
            f"⏰  Waktu kejadian:\n{time}\n\n"
            f"📝  Kronologi:\n{chronology}\n\n"
            "---\n"
            "Gimana, datanya udah bener?\n"
            "Ketik 'benar' untuk simpan, 'edit' untuk ubah, atau 'batal' untuk cancel."
        )

    def handle_response(self, message: str) -> Optional[str]:
        """Menangani respons pengguna berdasarkan state saat ini."""
        normalized_message = _normalize(message)

        # Allow cancellation from any state
        if normalized_message in _CANCEL_KEYWORDS:
            self.state = "idle"
            self.report_data = {}
            return "Oke, laporan dibatalkan. Gak apa-apa kok, semua info yang tadi kamu kasih udah ASKA hapus demi privasimu. Kalau kamu berubah pikiran atau butuh bantuan lagi, jangan ragu panggil ASKA ya. Semangat terus! 💪"

        if self.state == "confirming":
            if normalized_message == "benar":
                return self.finalize_report()
            elif normalized_message == "edit":
                self.state = "editing_selection"
                return "Bagian mana yang mau diubah? (1. Terlibat, 2. Lokasi, 3. Waktu, 4. Kronologi)"
            else:
                return "Maaf, ASKA gak ngerti. Ketik 'benar' atau 'edit' ya. Untuk membatalkan, ketik 'batal'."

        elif self.state == "editing_selection":
            try:
                # Coba konversi ke angka (misal, "1" -> 0)
                selection_idx = int(normalized_message) - 1
                if 0 <= selection_idx < len(self.questions):
                    self.current_question_index = selection_idx
                else:
                    raise ValueError
            except (ValueError, IndexError):
                # Jika bukan angka, coba cari berdasarkan nama kunci
                key_map = {q[0]: i for i, q in enumerate(self.questions)}
                if normalized_message in key_map:
                    self.current_question_index = key_map[normalized_message]
                else:
                    return "Pilihannya gak valid. Coba lagi, ketik angka atau namanya (misal: 'waktu')."
            
            self.state = "reporting"
            self.is_editing = True
            question_variations = self.questions[self.current_question_index][1]
            return f"Oke, kita ubah bagian '{self.questions[self.current_question_index][0]}'.\n{random.choice(question_variations)}"

        elif self.state == "reporting":
            question_key = self.questions[self.current_question_index][0]
            self.report_data[question_key] = message

            if self.is_editing:
                self.state = "confirming"
                self.is_editing = False
                return self._generate_confirmation_message()

            self.current_question_index += 1
            if self.current_question_index < len(self.questions):
                next_question_variations = self.questions[self.current_question_index][1]
                return random.choice(next_question_variations)
            else:
                self.state = "confirming"
                return self._generate_confirmation_message()
        
        return None

    def finalize_report(self) -> str:
        """Menyimpan laporan ke database dan memberikan pesan konfirmasi."""
        self.state = "idle"
        ticket_id = str(uuid.uuid4()).split('-')[0].upper()
        self.report_data["ticket_id"] = ticket_id
        self.report_data["user_id"] = self.user_id
        self.report_data["status"] = "open"
        status_link = _build_status_link(ticket_id)
        
        try:
            record_corruption_report(self.report_data)
            return (
                "Keren banget! Laporanmu udah ASKA terima dan langsung kita lock biar aman. Makasih udah berani speak up, kamu real hero anti-korupsi! 🦸‍♀️🔥\n\n"
                f"🎟️ **Nomor tiketmu:** {ticket_id}\n"
                f"🔗 **Link instan cek status:** {status_link}\n\n"
                "Klik linknya kapan pun kamu mau buat liat progres terbaru tanpa perlu login. Simpen juga nomor tiketnya kalau mau input manual. "
                "No worries, semua data yang kamu spill dijaga rapat sama ASKA—privasi tetap nomor satu! 🤫🔐\n\n"
                "Kalau butuh update tambahan atau mau lapor lagi, tinggal panggil ASKA ya. Stay safe dan makasih udah bantu jaga lingkungan sekolah! 💙"
            )
        except Exception as e:
            print(f"Error saving corruption report: {e}")
            return (
                "Yah, sorry banget, ada sedikit gangguan teknis di sistem ASKA nih. 😭 "
                "Tapi jangan panik! Laporanmu penting banget dan nggak akan hilang gitu aja. Coba deh kirim ulang laporannya beberapa saat lagi. "
                "Kalau masih error, please laporin error ini ke admin ya. Semangat! Jangan kasih kendor! 💪"
            )

__all__ = ["is_corruption_report_intent", "CorruptionResponse"]
