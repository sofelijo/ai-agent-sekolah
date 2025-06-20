import requests

def ambil_data_pendaftar_sdn(npsn="2011225"):
    url = f"https://spmb.jakarta.go.id/seleksi/zonasi/sd/1-1{npsn}-0.json"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json().get("data", [])
    except Exception as e:
        print(f"[ERROR] Gagal ambil data dari SPMB: {e}")
        return []

def cari_urutan_nama(nama_dicari: str, npsn="2011225") -> str:
    data = ambil_data_pendaftar_sdn(npsn)
    hasil = []

    for i, siswa in enumerate(data, start=1):
        if len(siswa) > 4 and nama_dicari.lower() in siswa[4].lower():
            hasil.append((siswa[4], i))  # siswa[4] = nama lengkap

    if not hasil:
        return f"Tidak ditemukan pendaftar dengan nama '{nama_dicari}' di SDN Semper Barat 01."

    if len(hasil) == 1:
        return f"Selamat {hasil[0][0]}, kamu masuk daftar siswa sementara di SDN Semper Barat 01. Urutan: {hasil[0][1]}"

    balasan = f"Ditemukan {len(hasil)} nama '{nama_dicari}' di SDN Semper Barat 01:\n"
    for nama_lengkap, urutan in hasil:
        balasan += f"- {nama_lengkap} urutan {urutan}\n"
    return balasan.strip()
