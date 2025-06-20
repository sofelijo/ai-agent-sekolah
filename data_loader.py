import requests

def load_statistik_sd_zonasi():
    url = "https://spmb.jakarta.go.id/statistik/1-sd-zonasi.json"
    try:
        response = requests.get(url)
        response.raise_for_status()
        json_data = response.json()

        sekolah_data = []
        for entry in json_data["data"].values():
            rekap = entry.get("rekap", [])
            if not rekap or not isinstance(rekap[0], list) or len(rekap[0]) < 3:
                continue

            sekolah_data.append({
                "nama_sekolah": entry["sekolah"],
                "umur_terendah": rekap[0][0],
                "umur_tertinggi": rekap[0][1],
                "umur_rerata": rekap[0][2],
            })

        return sekolah_data
    except Exception as e:
        print(f"[ERROR] Gagal memuat data SD: {e}")
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

            sekolah_data.append({
                "nama_sekolah": entry["sekolah"],
                "nilai_terendah": rekap[0][0],
                "nilai_tertinggi": rekap[0][1],
                "nilai_rerata": rekap[0][2],
            })

        return sekolah_data
    except Exception as e:
        print(f"[ERROR] Gagal memuat data SMP: {e}")
        return []
