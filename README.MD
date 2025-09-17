# 🤖 ASKA - AI Agent Sekolah Kita

Selamat datang di repositori **ASKA (Agent AI Sekolah Kita)**, sebuah proyek asisten AI cerdas yang dirancang khusus untuk lingkungan SDN Semper Barat 01. ASKA diciptakan untuk menjadi teman belajar yang interaktif, informatif, dan aman bagi siswa, guru, dan orang tua.

## ✨ Tentang Proyek

ASKA adalah chatbot AI yang memiliki kepribadian ramah dan suportif, layaknya seorang teman. Tujuannya adalah untuk menjawab pertanyaan seputar informasi sekolah, membantu siswa dengan materi pelajaran SD, dan memberikan dukungan moral dengan cara yang positif. Proyek ini menggabungkan backend untuk bot Telegram dan antarmuka web untuk interaksi.

## 🌟 Fitur Utama

- **Asisten Informasi Sekolah:** Menjawab pertanyaan umum mengenai jadwal, guru, dan kegiatan sekolah berdasarkan basis pengetahuan (knowledge base).
- **Teman Belajar Interaktif:** Menyajikan materi pelajaran SD kelas 4-6 dengan gaya bahasa yang seru dan mudah dipahami.
- **Persona Gen Z & Ceria:** Dirancang dengan kepribadian "Yapping" yang antusias dan menggunakan bahasa gaul yang relevan untuk membangun kedekatan dengan siswa.
- **Dukungan Emosional:** Memberikan respons empatik dan kutipan motivasi dari guru saat pengguna merasa sedih atau mengeluh.
- **Aman untuk Anak-Anak:** Memiliki filter untuk menolak menjawab pertanyaan yang tidak pantas dan memberikan nasihat edukatif.
- **Integrasi Telegram:** Dapat diakses dengan mudah melalui aplikasi Telegram, memungkinkan interaksi kapan saja.

## 🛠️ Teknologi yang Digunakan

- **Backend:** Python
- **Telegram Bot Framework:** `python-telegram-bot`
- **AI & Machine Learning:** LangChain, Google Gemini (atau model LLM lainnya)
- **Frontend/Web Interface:** (Berdasarkan struktur folder) Kemungkinan menggunakan JavaScript/TypeScript.

## 🚀 Cara Memulai

Berikut adalah langkah-langkah untuk menjalankan proyek ini di lingkungan lokal Anda.

### Prasyarat

- Python 3.8+
- Git
- Akun Bot Telegram (dapatkan Token API dari [BotFather](https://core.telegram.org/bots#botfather))
- API Key dari platform AI yang Anda gunakan (misalnya, Google AI Studio)

### Instalasi

1.  **Clone repositori ini:**
    ```bash
    git clone [https://github.com/sofelijo/ai-agent-sekolah.git](https://github.com/sofelijo/ai-agent-sekolah.git)
    cd ai-agent-sekolah
    ```

2.  **Buat dan aktifkan virtual environment:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # Untuk Windows gunakan: venv\Scripts\activate
    ```

3.  **Install semua dependensi Python:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Konfigurasi Environment Variables:**
    - Buat file bernama `.env` di direktori utama proyek.
    - Isi file tersebut dengan token dan kunci API yang Anda miliki. Contoh:
        ```env
        TELEGRAM_BOT_TOKEN="MASUKKAN_TOKEN_TELEGRAM_ANDA_DI_SINI"
        GEMINI_API_KEY="MASUKKAN_API_KEY_ANDA_DI_SINI"
        ```

### Menjalankan Bot

Setelah semua konfigurasi selesai, jalankan skrip utama bot:

```bash
python bot_sekolah.py