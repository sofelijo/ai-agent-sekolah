import requests
import json

# Ambil data dari API SPMB (digunakan untuk fitur umum)
def load_statistik_sd_zonasi():
    url_data = "https://spmb.jakarta.go.id/statistik/1-sd-zonasi.json"
    url_meta = "https://spmb.jakarta.go.id/sekolah/1-sd-zonasi.json"

    try:
        data_res = requests.get(url_data)
        data_res.raise_for_status()
        json_data = data_res.json()

        meta_res = requests.get(url_meta)
        meta_res.raise_for_status()
        meta_data = meta_res.json()

        # Buat mapping nama sekolah ke kota dari metadata
        nama_to_kota = {}
        for entry in meta_data:
            nama = entry.get("nama")
            kota = entry.get("kota")
            if isinstance(nama, str) and isinstance(kota, str):
                nama_to_kota[nama.strip().lower()] = kota.strip()

        sekolah_data = []
        for entry in json_data["data"].values():
            rekap = entry.get("rekap", [])
            if not rekap or not isinstance(rekap[0], list) or len(rekap[0]) < 3:
                continue

            nama_sekolah = entry.get("sekolah")
            nama_sekolah_clean = nama_sekolah.strip() if isinstance(nama_sekolah, str) else ""
            kota = nama_to_kota.get(nama_sekolah_clean.lower(), "")
            print(f"[DEBUG] Kota untuk {nama_sekolah_clean}: {kota}")

            sekolah_data.append({
                "nama_sekolah": nama_sekolah_clean,
                "umur_terendah": rekap[0][0],
                "umur_tertinggi": rekap[0][1],
                "umur_rerata": rekap[0][2],
                "kota": kota
            })

        return sekolah_data
    except Exception as e:
        print(f"[ERROR] Gagal memuat data SD dari API: {e}")
        return []

def load_statistik_smp_prestasi():
    url = "https://spmb.jakarta.go.id/statistik/1-smp-prestasi.json"
    try:
        response = requests.get(url)
        response.raise_for_status()
        json_data = response.json()

        sekolah_data = []
        for entry in json_data["data"].values():
            rekap = entry.get("rekap", [])
            if not rekap or not isinstance(rekap[0], list) or len(rekap[0]) < 3:
                continue

            nama_sekolah = entry.get("sekolah")
            nama_sekolah_clean = nama_sekolah.strip() if isinstance(nama_sekolah, str) else ""

            sekolah_data.append({
                "nama_sekolah": nama_sekolah_clean,
                "nilai_terendah": rekap[0][0],
                "nilai_tertinggi": rekap[0][1],
                "nilai_rerata": rekap[0][2],
                "kota": entry.get("kota", "")
            })

        return sekolah_data
    except Exception as e:
        print(f"[ERROR] Gagal memuat data SMP: {e}")
        return []
