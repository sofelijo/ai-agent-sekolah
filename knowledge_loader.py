from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
KECERDASAN_DIR = BASE_DIR / "kecerdasan"
GENERAL_FILE = KECERDASAN_DIR / "umum.md"
SPECIFIC_FILE = KECERDASAN_DIR / "profil_sekolah.md"
OUTPUT_FILE = BASE_DIR / "kecerdasan.md"
PLACEHOLDER = "<!-- {{ASKA_PROFIL_DAN_JADWAL}} -->"


def _read(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Tidak menemukan berkas: {path}")
    return path.read_text(encoding="utf-8")


def load_kecerdasan(*, ensure_output_file: bool = True) -> str:
    """
    Gabungkan potongan pengetahuan menjadi satu string markdown.

    Saat ensure_output_file=True, hasil gabungan juga ditulis ulang ke kecerdasan.md
    sehingga komponen yang masih membaca berkas lama tetap bekerja.
    """

    general_text = _read(GENERAL_FILE)
    specific_text = _read(SPECIFIC_FILE).strip()

    insertion = f"{specific_text}\n\n" if specific_text else ""
    if PLACEHOLDER in general_text:
        combined = general_text.replace(PLACEHOLDER, insertion)
    else:
        combined = f"{general_text.rstrip()}\n\n{specific_text}\n"

    combined = combined.strip() + "\n"
    if ensure_output_file:
        OUTPUT_FILE.write_text(combined, encoding="utf-8")
    return combined


def build_kecerdasan_file() -> Path:
    """Utility agar mudah dipanggil via CLI/script."""
    load_kecerdasan(ensure_output_file=True)
    return OUTPUT_FILE


if __name__ == "__main__":
    path = build_kecerdasan_file()
    rel = path.relative_to(BASE_DIR)
    print(f"Sukses menyusun {rel}")
