import requests
import difflib

URL_SEKOLAH = "https://spmb.jakarta.go.id/sekolah/1-sd-zonasi.json"

def load_data_sekolah():
    try:
        r = requests.get(URL_SEKOLAH, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[ERROR] Gagal ambil daftar sekolah: {e}")
        return []

def cari_sekolah_id(nama_input: str) -> str:
    data = load_data_sekolah()
    if not data or not isinstance(nama_input, str):
        return None

    nama_input = nama_input.lower()
    for sekolah in data:
        if nama_input in sekolah["nama"].lower():
            return sekolah["sekolah_id"]

    semua_nama = [s["nama"] for s in data]
    cocok = difflib.get_close_matches(nama_input.upper(), semua_nama, n=1)
    if cocok:
        sekolah_cocok = next((s for s in data if s["nama"] == cocok[0]), None)
        if sekolah_cocok:
            return sekolah_cocok["sekolah_id"]

    return None
