# 🤖 ASKA — Agent AI Sekolah Kita (Telegram Bot)

**ASKA** adalah asisten AI berbasis Telegram untuk SDN Semper Barat 01 yang mampu menjawab pertanyaan seputar sekolah berdasarkan file `.md`. Dibangun dengan OpenAI GPT-4o, LangChain, dan FAISS. Bot ini aktif 24 jam di server VPS dengan auto-restart.

---

## 📦 Fitur Utama

- Menjawab pertanyaan dari file `kecerdasan.md`
- Menggunakan gaya bahasa Gen-Z yang santai 😎
- Bisa jalan di lokal atau server (VPS)
- Bot Telegram aktif 24 jam via `systemd`

---

## 🧑‍💻 Langkah Instalasi Otomatis (1x Klik Copy untuk Semua Perintah)

```bash
# 1. Update dan install dependensi utama
apt update && apt upgrade -y
apt install git python3-pip python3-venv -y

# 2. Clone repository
git clone https://github.com/sofelijo/ai-agent-sekolah.git
cd ai-agent-sekolah

# 3. Buat virtual environment dan aktifkan
python3 -m venv venv
source venv/bin/activate

# 4. Install requirements
pip install --upgrade pip
pip install -r requirements.txt

# 5. Buat file .env dan isi token Telegram & API OpenAI
cat > .env <<EOF
TOKEN=ISI_TOKEN_DARI_BOTFATHER
OPENAI_API_KEY=ISI_API_KEY_OPENAI
EOF

# 6. Jalankan bot pertama kali (tes manual)
python bot_sekolah.py
```

---

## 🤖 Buat Bot Telegram (1x via BotFather)

1. Buka Telegram, cari `@BotFather`
2. Kirim `/newbot`
3. Masukkan nama bot: `ASKA Sekolah`
4. Masukkan username: `aska_sekolah_bot`
5. Simpan token yang diberikan (untuk `.env`)

---

## 🔁 Jalankan Bot Otomatis 24/7 di VPS

```bash
# 1. Buat service systemd
nano /etc/systemd/system/ai-bots.service
```

Isi file:

```ini
[Unit]
Description=AI Agent Sekolah Bots
After=network.target

[Service]
WorkingDirectory=/root/ai-agent-sekolah
ExecStart=/root/ai-agent-sekolah/venv/bin/python bot_sekolah.py
Restart=always
RestartSec=5
EnvironmentFile=/root/ai-agent-sekolah/.env

[Install]
WantedBy=multi-user.target
```

Aktifkan service:

```bash
# Reload systemd dan aktifkan bot
systemctl daemon-reload
systemctl enable ai-bots.service
systemctl start ai-bots.service
systemctl status ai-bots.service
```

---

## 🧠 Cara Kerja ASKA

ASKA menggunakan:
- LangChain RetrievalQA
- GPT-4o (model mini)
- Dokumen `.md` dari `kecerdasan.md`
- Prompt bergaya Gen-Z dengan emoji

Contoh prompt sistem (dalam kode):

```python
prompt = ChatPromptTemplate.from_messages([
    ("system", "Aku ASKA 🤖✨, Agent AI Sekolah Kita. Jawab pertanyaan dengan gaya Gen-Z yang santai, pakai emoji, dan sebutkan namamu. Gunakan info berikut:\n\n{context}"),
    ("human", "{question}")
])
```

---

## 🛠 Update Proyek (jika ada perubahan)

```bash
cd /root/ai-agent-sekolah
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
systemctl restart ai-bots.service
```

---

## 📈 Cek Status & Log

```bash
# Cek status bot
systemctl status ai-bots.service

# Lihat log realtime
journalctl -u ai-bots.service -f
```

---

## 🧪 Troubleshooting

| Masalah                         | Solusi                                        |
|-------------------------------|-----------------------------------------------|
| Tidak bisa `venv`             | Jalankan `apt install python3-venv -y`        |
| Gagal install `faiss`         | Jalankan `pip install faiss-cpu`              |
| Bot tidak merespons           | Cek `.env` dan jalankan `journalctl -u ai-bots.service -f` |
| OpenAI key error              | Pastikan variabel `OPENAI_API_KEY` benar      |

---

## 🙋 Tentang

- Proyek Latsar CPNS 2025
- Oleh: **MH. Ainun Fajar**
- Sekolah: SDN Semper Barat 01
- GitHub: [@sofelijo](https://github.com/sofelijo)