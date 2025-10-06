# input_normalizer.py

def normalize_input(text: str) -> str:
    text = text.lower().strip()

    # ANBK variations
    if "anbk" in text and "sd" in text and "kapan" in text:
        return "jadwal anbk sd"
    
    if "anbk sd" in text and "jadwal" not in text:
        return "jadwal anbk sd"

    # PPDB
    if "ppdb" in text and "syarat" in text:
        return "syarat ppdb"
    
    # Jadwal pelajaran
    if "jadwal" in text and "kelas" in text:
        return "jadwal pelajaran kelas"

    # Default return
    return text
