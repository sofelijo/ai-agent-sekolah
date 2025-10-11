"""Deteksi laporan korupsi dan respons pendamping."""

from __future__ import annotations
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


def _normalize(text: str) -> str:
    """Membersihkan dan menormalkan teks input."""
    return " ".join(text.lower().split())


def _contains_any(text: str, candidates: Iterable[str]) -> bool:
    """Memeriksa apakah teks mengandung salah satu dari kandidat kata."""
    return any(candidate in text for candidate in candidates)


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
                "OMG, gila sih ini korupsi 🤢, red flag parah! 🚩 ASKA bantu usut tuntas, spill dong siapa aja yang terlibat di kasus ini? 🕵️‍♀️",
                "Oke, kita mulai investigasinya! 🕵️‍♂️ Korupsi itu big no no! ❌ Siapa aja nih oknum-oknum yang main kotor di kasus ini? Sebutin semua ke ASKA ya!",
            ]),
            ("location", [
                "Oke, noted. Biar makin jelas jejaknya, spill TKP-nya di mana ke ASKA? Gak ada tempat aman buat koruptor! 🗺️📍",
                "Sip, nama-namanya udah ASKA kunci. Sekarang, kejadiannya di mana nih? Biar kita bisa cek CCTV dan bukti lain. 📹",
            ]),
            ("time", [
                "Sip, ASKA catet. Kapan nih kejadiannya? Detail waktu penting bgt buat ngelacak bukti, biar ga ada yg bisa ngeles! ⏰🗓️",
                "Oke, lokasi udah. Sekarang, kapan waktunya? Pagi, siang, malem? Tanggal berapa? Kasih tau ASKA biar alibinya gampang dipatahin! 🧐",
            ]),
            ("chronology", [
                "Makasih banyak udah berani speak up ke ASKA! 🙏 Kamu keren bgt! Sekarang, coba ceritain semua kronologinya dari A-Z, jangan ada yg ke-skip ya. The tea is hot! ☕️ Spill semuanya biar kita bisa bongkar tuntas kasus ini! 🔥",
                "Kamu pahlawan! 🦸‍♀️ Makasih udah lapor ke ASKA. Sekarang, tolong ceritain alur ceritanya dari awal sampe akhir. Jangan ragu, ceritain aja semuanya. ASKA dengerin! 🎧",
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

        if self.state == "confirming":
            if normalized_message == "benar":
                return self.finalize_report()
            elif normalized_message == "edit":
                self.state = "editing_selection"
                return "Bagian mana yang mau diubah? (1. Terlibat, 2. Lokasi, 3. Waktu, 4. Kronologi)"
            elif normalized_message == "batal":
                self.state = "idle"
                self.report_data = {}
                return "Oke, laporan dibatalkan. Gak apa-apa kok, semua info yang tadi kamu kasih udah ASKA hapus demi privasimu. Kalau kamu berubah pikiran atau butuh bantuan lagi, jangan ragu panggil ASKA ya. Semangat terus! 💪"
            else:
                return "Maaf, ASKA gak ngerti. Ketik 'benar', 'edit', atau 'batal' ya."

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
        
        try:
            record_corruption_report(self.report_data)
            return (
                f"Keren banget! Laporanmu udah ASKA terima dan amankan! Makasih banyak ya udah jadi pahlawan anti-korupsi! 🦸‍♀️🔥\n\n"
                f"Ini nomor tiket laporanmu: {ticket_id}. Simpen baik-baik ya, jangan sampe ilang!\n\n"
                f"Kamu bisa pake nomor ini buat nanyain progres kasusnya ke ASKA nanti. Tenang aja, semua datamu 100% aman dan rahasia sama ASKA. Privasimu nomor satu! 🤫🔐"
            )
        except Exception as e:
            print(f"Error saving corruption report: {e}")
            return (
                "Yah, sorry banget, ada sedikit gangguan teknis di sistem ASKA nih. 😭 "
                "Tapi jangan panik! Laporanmu penting banget dan nggak akan hilang gitu aja. Coba deh kirim ulang laporannya beberapa saat lagi. "
                "Kalau masih error, please laporin error ini ke admin ya. Semangat! Jangan kasih kendor! 💪"
            )

__all__ = ["is_corruption_report_intent", "CorruptionResponse"]
