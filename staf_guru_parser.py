import csv
import requests
from io import StringIO

SHEET_URL = "https://docs.google.com/spreadsheets/d/1Mh26c54QWCdU9b_CHBbsT94PI72Ul3gsP15S2PmwEL8/export?format=csv"

def ambil_data_staf():
    try:
        response = requests.get(SHEET_URL)
        response.raise_for_status()
        content = response.content.decode("utf-8")

        reader = csv.reader(StringIO(content))
        rows = [row for row in reader if any(cell.strip() for cell in row)]

        header_index = None
        for i, row in enumerate(rows):
            if any("NAMA TANPA GELAR" in cell.upper().strip() for cell in row):
                header_index = i
                break

        if header_index is None:
            print("[ERROR] Header 'NAMA TANPA GELAR' tidak ditemukan.")
            return []

        headers = [cell.strip() for cell in rows[header_index]]
        data_rows = rows[header_index + 1:]

        cleaned_rows = []
        for r in data_rows:
            if len(r) < len(headers):
                r += [''] * (len(headers) - len(r))
            elif len(r) > len(headers):
                r = r[:len(headers)]
            # Lindungi koma agar tidak pecah saat parsing ulang
            r = [cell.replace(",", " ") for cell in r]
            cleaned_rows.append(r)

        csv_text = "\n".join([",".join(headers)] + [",".join(r) for r in cleaned_rows])
        final_reader = csv.DictReader(StringIO(csv_text))
        return list(final_reader)

    except Exception as e:
        print(f"[ERROR] Gagal ambil data staf: {e}")
        return []

def cari_info_nama(nama_dicari: str) -> str:
    data = ambil_data_staf()
    nama_dicari = nama_dicari.lower().strip()

    for baris in data:
        nama = baris.get("NAMA TANPA GELAR", "").lower().strip()
        jabatan = baris.get("JABATAN", "").strip().title()
        if nama_dicari in nama:
            return f"{baris['NAMA TANPA GELAR']} adalah {jabatan} di sekolah ini."

    return f"Maaf, saya tidak menemukan informasi tentang seseorang bernama {nama_dicari.title()}."
