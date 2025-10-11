import random

AFFIRMATION_MESSAGES = [
    "Tentu, {user_name}. Ingatlah bahwa setiap tantangan adalah kesempatan untuk bertumbuh. Anda lebih kuat dan lebih mampu dari yang Anda sadari.",
    "Pikiran yang hebat! {user_name}, setiap langkah yang Anda ambil, sekecil apapun, adalah sebuah kemajuan. Teruslah bergerak maju dengan semangat belajar.",
    "Benar sekali, {user_name}. Percayalah pada proses. Sama seperti belajar hal baru, konsistensi dan kesabaran akan membawa Anda pada hasil yang luar biasa.",
    "Tentu saja, {user_name}. Wajar jika terkadang merasa ragu. Namun, keraguan itu adalah tanda bahwa Anda peduli. Gunakan itu sebagai bahan bakar untuk belajar lebih giat.",
    "Anda sudah berada di jalur yang benar, {user_name}. Fokus pada kemajuan, bukan kesempurnaan. Setiap kesalahan adalah pelajaran berharga.",
    "Pasti bisa, {user_name}! Potensi dalam diri Anda tidak terbatas. Terus asah kemampuan Anda dan jangan takut untuk mencoba hal-hal baru.",
    "Saya setuju, {user_name}. Pola pikir positif adalah kunci. Anggap setiap hari sebagai lembaran baru untuk diisi dengan pengetahuan dan pengalaman positif.",
    "Ingatlah ini, {user_name}: Anda memiliki semua yang diperlukan untuk berhasil. Teruslah percaya pada diri sendiri dan kemampuan Anda untuk belajar dan beradaptasi."
]

def get_affirmation_response(user_name: str = "Anda") -> str:
    """
    Memilih respon afirmasi acak dan memformatnya dengan nama pengguna.
    Fungsi ini selalu mengembalikan pesan yang positif dan memberi semangat dengan gaya edukatif.

    Args:
        user_name: Nama pengguna untuk personalisasi pesan. Defaultnya adalah "Anda".

    Returns:
        String afirmasi positif yang sudah diformat.
    """
    message = random.choice(AFFIRMATION_MESSAGES)
    return message.format(user_name=user_name)

# Contoh penggunaan
if __name__ == '__main__':
    print("Contoh respon untuk pertanyaan negatif ('Apakah saya cukup baik?'):")
    print(get_affirmation_response("Siswa"))
    
    print("\nContoh respon untuk pertanyaan positif ('Saya pasti bisa!'):")
    print(get_affirmation_response("Pelajar"))
