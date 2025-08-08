import requests
import json
import os

# Cache sekolah agar tidak selalu fetch
SEKOLAH_JSON_URL = "https://spmb.jakarta.go.id/sekolah/1-sd-zonasi.json"
cached_sekolah_list = []

def load_sekolah_list():
    global cached_sekolah_list
    if not cached_sekolah_list:
        try:
            response = requests.get(SEKOLAH_JSON_URL, timeout=10)
            response.raise_for_status()
            cached_sekolah_list = response.json()
        except Exception as e:
            print(f"[ERROR] Gagal ambil daftar sekolah: {e}")
            cached_sekolah_list = []
    return cached_sekolah_list

def get_sekolah_id_from_nama(nama: str) -> str:
    semua_sekolah = load_sekolah_list()
    nama = nama.lower()
    for s in semua_sekolah:
        if nama in s["nama"].lower():
            return s["sekolah_id"], s["nama"]
    return None, None

def ambil_data_pendaftar_sdn(sekolah_id="12011225"):
    url = f"https://spmb.jakarta.go.id/seleksi/zonasi/sd/1-{sekolah_id}-0.json"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json().get("data", [])
    except Exception as e:
        print(f"[ERROR] Gagal ambil data dari SPMB: {e}")
        return []

def cari_urutan_nama(nama_dicari: str, sekolah_id="12011225", nama_sekolah="SDN Semper Barat 01") -> str:
    data = ambil_data_pendaftar_sdn(sekolah_id)
    hasil = []

    print(f"[DEBUG] Total pendaftar: {len(data)}")

    for i, siswa in enumerate(data, start=1):
        nama_lengkap = ""
        for kolom in siswa:
            if isinstance(kolom, str) and nama_dicari.lower() in kolom.lower():
                nama_lengkap = kolom
                break

        if nama_lengkap:
            hasil.append((nama_lengkap, i))
            print(f"[MATCH] {nama_lengkap} pada urutan {i}")

    if not hasil:
        return f"Tidak ditemukan pendaftar dengan nama '{nama_dicari}' di {nama_sekolah}."

    if len(hasil) == 1:
        return f"Selamat {hasil[0][0]}, kamu masuk daftar siswa sementara di {nama_sekolah}. Urutan: {hasil[0][1]}"

    balasan = f"Ditemukan {len(hasil)} nama '{nama_dicari}' di {nama_sekolah}:\n"
    for nama_lengkap, urutan in hasil:
        balasan += f"- {nama_lengkap} urutan {urutan}\n"
    return balasan.strip()
