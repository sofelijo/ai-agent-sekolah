import re

def parse_target_usia(user_input: str):
    """
    Ambil target usia dari input seperti:
    - "di bawah 7 tahun"
    - "dibawah 6 tahun 8 bulan"
    - "kurang dari 7 tahun 6 bulan"
    """
    pattern = re.compile(r"(di\s*bawah|dibawah|kurang\s*dari)\s*(\d+)\s*tahun(?:\s*(\d+)\s*bulan)?")
    match = pattern.search(user_input)
    if match:
        tahun = int(match.group(2))
        bulan = int(match.group(3)) if match.group(3) else 0
        return tahun, bulan
    return None

def parse_umur_to_tuple(umur_str: str):
    """
    "6 th 8 bl 30 hr" -> (6, 8)
    "7 th 3 bl" -> (7, 3)
    "9 th" -> (9, 0)
    """
    th = bl = 0
    match = re.search(r"(\d+)\s*th", umur_str)
    if match:
        th = int(match.group(1))
    match = re.search(r"(\d+)\s*bl", umur_str)
    if match:
        bl = int(match.group(1))
    return th, bl

def is_umur_kurang_dari(umur: tuple, batas: tuple):
    """
    Bandingkan dua umur (tahun, bulan)
    """
    return umur[0] < batas[0] or (umur[0] == batas[0] and umur[1] < batas[1])

# Contoh pakai
user_input = "carikan SDN dengan umur dibawah 7 tahun 3 bulan"
parsed = parse_target_usia(user_input)

if parsed:
    print("Batas pencarian:", parsed)  # (7, 3)

    # Contoh daftar umur dari JSON
    daftar = [
        ("SDN ANCOL 01", "6 th 8 bl 30 hr"),
        ("SDN XYZ", "7 th 4 bl"),
        ("SDN SEMPER BARAT 01", "7 th 2 bl")
    ]

    for nama, umur_str in daftar:
        umur = parse_umur_to_tuple(umur_str)
        if is_umur_kurang_dari(umur, parsed):
            print(f"- {nama} → {umur_str}")
