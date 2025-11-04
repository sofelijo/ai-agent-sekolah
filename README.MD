# 🤖 ASKA — Agent AI Sekolah Kita (Telegram Bot)

**ASKA** adalah asisten AI berbasis Telegram untuk SDN Semper Barat 01 yang mampu menjawab pertanyaan seputar sekolah berdasarkan file `.md`. Dibangun dengan Groq Llama 3.1 (OpenAI-compatible), LangChain, dan FAISS. Bot ini aktif 24 jam di server VPS dengan auto-restart.

---

## 📦 Fitur Utama

- Menjawab pertanyaan dari file `kecerdasan.md`
- Menggunakan gaya bahasa Gen-Z yang santai 😎
- Bisa jalan di lokal atau server (VPS)
- Bot Telegram aktif 24 jam via `systemd`
- Web Dashboard untuk administrasi
- Web App untuk antarmuka chat
- Integrasi opsional dengan Twitter/X untuk balas mention otomatis
- Auto-post tweet terjadwal (opsional), bisa pakai RAG untuk nyusun info sekolah

---

## 🧑‍💻 Langkah Instalasi Otomatis (1x Klik Copy untuk Semua Perintah)

```bash
# 1. Update dan install dependensi utama
apt update && apt upgrade -y
apt install git python3-pip python3-venv nginx certbot python3-certbot-nginx -y

# 2. Clone repository
git clone https://github.com/sofelijo/ai-agent-sekolah.git
cd ai-agent-sekolah

# 3. Buat virtual environment dan aktifkan
python3 -m venv venv
source venv/bin/activate

# 4. Install requirements
pip install --upgrade pip
pip install -r requirements.txt

# 5. Buat file .env dan isi kredensial produksi
cat > .env <<'EOF'
TELEGRAM_BOT_TOKEN=ISI_TOKEN_DARI_BOTFATHER
GROQ_API_KEY=ISI_API_KEY_GROQ
# Opsional (aktifkan endpoint OpenAI-compatible bila butuh)
OPENAI_API_KEY=ISI_API_KEY_OPENAI
ASKA_EMBEDDING_API_KEY=ISI_API_KEY_OPENAI
ASKA_STT_API_KEY=ISI_API_KEY_OPENAI
# Embedding default GRATIS (HuggingFace)
ASKA_EMBEDDING_MODEL_LOCAL=sentence-transformers/all-MiniLM-L6-v2

# Koneksi PostgreSQL (bot + dashboard)
DB_NAME=nama_database
DB_USER=nama_user
DB_PASS=password
DB_HOST=127.0.0.1
DB_PORT=5432
# Opsional kalau provider butuh TLS: DB_SSLMODE=require

# Cache vectorstore (opsional)
ASKA_VECTORSTORE_PATH=.aska_vectorstore
ASKA_VECTORSTORE_INDEX=kecerdasan

# Integrasi Twitter/X (opsional)
TWITTER_BEARER_TOKEN=ISI_DARI_PORTAL_DEVELOPER_X
TWITTER_API_KEY=ISI_DARI_PORTAL_DEVELOPER_X
TWITTER_API_SECRET=ISI_DARI_PORTAL_DEVELOPER_X
TWITTER_ACCESS_TOKEN=ISI_DARI_PORTAL_DEVELOPER_X
TWITTER_ACCESS_SECRET=ISI_DARI_PORTAL_DEVELOPER_X
TWITTER_POLL_INTERVAL=90
TWITTER_AUTOPOST_ENABLED=false
TWITTER_AUTOPOST_INTERVAL=3600
TWITTER_AUTOPOST_MESSAGES_PATH=twitter_posts.txt
TWITTER_AUTOPOST_RECENT_LIMIT=8
TWITTER_SPAM_KEYWORDS=promo,follback,followback

# Konfigurasi dashboard Flask
DASHBOARD_SECRET_KEY=ganti-dengan-string-acak-minimal-32-karakter
DASHBOARD_SESSION_DAYS=14
DASHBOARD_DB_MAX_CONN=8
EOF

> Catatan: mulai sekarang embedding default-nya memakai model lokal HuggingFace (`sentence-transformers/all-MiniLM-L6-v2`) sehingga tidak menguras kuota OpenAI. Isi `ASKA_EMBEDDING_API_KEY` hanya jika ingin tetap memakai layanan berbayar OpenAI-compatible. Setelah pull terbaru, jalankan `pip install -r requirements.txt` untuk meng-install dependensi tambahan (`langchain-huggingface`, `sentence-transformers`, dan pin `numpy<2` agar kompatibel dengan PyTorch). Embedding apa pun yang sudah sukses dibuat otomatis dicache ke folder `.aska_vectorstore`, sehingga token OpenAI tidak akan terkuras lagi setiap kali service restart. Jika ingin mengatur ulang potongan dokumen, gunakan variabel `ASKA_CHUNK_SIZE` dan `ASKA_CHUNK_OVERLAP` atau hapus folder cache tersebut.

# 6. Inisialisasi Database
# Skrip ini akan membuat semua tabel dan skema yang dibutuhkan oleh bot dan dashboard.
# Pastikan koneksi database di .env sudah benar sebelum menjalankan ini.
python3 init_db.py

# 7. Buat Akun Admin Dashboard (Opsional)
# Ganti email dan nama dengan yang Anda inginkan.
python3 -m dashboard.cli create-user admin@example.com "Nama Admin"

# 8. Jalankan bot pertama kali (tes manual)
python3 bot_sekolah.py
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
sudo nano /etc/systemd/system/ai-bots.service
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
sudo systemctl daemon-reload
sudo systemctl enable ai-bots.service
sudo systemctl start ai-bots.service
sudo systemctl status ai-bots.service
```

---

## 🚀 Deploy Aplikasi Web (Dashboard & Web Chat)

Berikut adalah cara mendeploy kedua aplikasi web (Dashboard Admin dan Web Chat Aska) agar berjalan 24/7 di server VPS Anda.

### 1. Deploy Dashboard Admin (`https://admin.sdnsembar01.sch.id`)

```bash
# Buat service systemd untuk Gunicorn Dashboard
sudo nano /etc/systemd/system/aska-dashboard.service
```

Isi file `aska-dashboard.service`:

```ini
[Unit]
Description=ASKA Dashboard (Gunicorn)
After=network.target

[Service]
WorkingDirectory=/root/ai-agent-sekolah
EnvironmentFile=/root/ai-agent-sekolah/.env
ExecStart=/root/ai-agent-sekolah/venv/bin/gunicorn -w 2 -k gthread -b 127.0.0.1:8000 dashboard.app:app
Restart=always
User=www-data
Group=www-data

[Install]
WantedBy=multi-user.target
```

Aktifkan service dashboard:

```bash
sudo systemctl daemon-reload
sudo systemctl enable aska-dashboard.service
sudo systemctl start aska-dashboard.service
```

Konfigurasi Nginx untuk `admin.sdnsembar01.sch.id`:

```bash
sudo nano /etc/nginx/sites-available/aska-dashboard
```

Isi file:

```nginx
server {
    listen 80;
    server_name admin.sdnsembar01.sch.id;

    location /static/ {
        alias /root/ai-agent-sekolah/dashboard/static/;
        access_log off;
        expires 30d;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Aktifkan site dan amankan dengan SSL:

```bash
sudo ln -s /etc/nginx/sites-available/aska-dashboard /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d admin.sdnsembar01.sch.id
```

### 2. Deploy Web Chat Aska (`https://aska.sdnsembar01.sch.id`)

```bash
# Buat service systemd untuk Gunicorn Web Chat
sudo nano /etc/systemd/system/aska-webapp.service
```

Isi file `aska-webapp.service`:

```ini
[Unit]
Description=ASKA Web App (Gunicorn)
After=network.target

[Service]
WorkingDirectory=/root/ai-agent-sekolah
EnvironmentFile=/root/ai-agent-sekolah/.env
ExecStart=/root/ai-agent-sekolah/venv/bin/gunicorn -w 2 -k gthread -b 127.0.0.1:5001 web_aska.app:app
Restart=always
User=www-data
Group=www-data

[Install]
WantedBy=multi-user.target
```

Aktifkan service web app:

```bash
sudo systemctl daemon-reload
sudo systemctl enable aska-webapp.service
sudo systemctl start aska-webapp.service
```

Konfigurasi Nginx untuk `aska.sdnsembar01.sch.id`:

```bash
sudo nano /etc/nginx/sites-available/aska-webapp
```

Isi file:

```nginx
server {
    listen 80;
    server_name aska.sdnsembar01.sch.id;

    location / {
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Aktifkan site dan amankan dengan SSL:

```bash
sudo ln -s /etc/nginx/sites-available/aska-webapp /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d aska.sdnsembar01.sch.id
```

---

## 🧠 Cara Kerja ASKA

ASKA menggunakan:
- LangChain RetrievalQA
- Groq `llama-3.1-8b-instant` (OpenAI-compatible)
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

## 🗄️ Struktur Database

Proyek ini menggunakan **PostgreSQL** sebagai database. Inisialisasi skema dapat dilakukan dengan menjalankan `python3 init_db.py`. Skrip ini akan membuat tabel-tabel berikut:

- **`chat_logs`**: Menyimpan riwayat semua percakapan antara pengguna dan bot.
- **`bullying_reports`**: Mencatat laporan kasus perundungan yang masuk melalui bot.
- **`psych_reports`**: Mencatat permintaan atau laporan terkait kesehatan psikologis.
- **`corruption_reports`**: Mencatat laporan terkait potensi korupsi.
- **`twitter_worker_logs`**: Menyimpan log aktivitas dari worker Twitter (balasan mention, auto-post).
- **`dashboard_users`**: Menyimpan data pengguna yang dapat mengakses aplikasi web dashboard (login, role, dll).
- **`bullying_report_events`**: Log jejak audit untuk setiap perubahan pada laporan perundungan.
- **`notifications`**: Tabel untuk sistem notifikasi di dashboard.
- **`web_users`**: Menyimpan data pengguna yang berinteraksi melalui antarmuka web chat.

---

## 🛠 Update Proyek (jika ada perubahan)

```bash
cd /root/ai-agent-sekolah
git pull origin main
source venv/bin/activate
pip install -r requirements.txt

# Restart semua service
sudo systemctl restart ai-bots.service
sudo systemctl restart aska-dashboard.service
sudo systemctl restart aska-webapp.service
```

---

## 🐦 Integrasi Twitter/X (Opsional)

ASKA bisa ikut menyapa warga sekolah di Twitter/X dengan membalas mention secara otomatis.

1. Pastikan variabel `TWITTER_*` di `.env` sudah terisi dari [portal developer X](https://developer.x.com/).
2. Aktifkan virtualenv dan jalankan `python twitter_bot.py` untuk memulai worker penjawab mention.
3. Secara default bot akan mengecek mention baru setiap 90 detik. Atur dengan `TWITTER_POLL_INTERVAL`.
4. ID mention terakhir disimpan di `twitter_state.json` (bisa diubah lewat `TWITTER_STATE_PATH`).
5. Untuk auto-post, isi file `twitter_posts.txt` (satu tweet per baris, bisa pakai `#` untuk komentar), set `TWITTER_AUTOPOST_ENABLED=true`, dan sesuaikan interval lewat `TWITTER_AUTOPOST_INTERVAL` (detik).
6. Mau auto-post berbasis pengetahuan sekolah? Awali baris dengan `RAG:` (mis. `RAG: Ringkas info penting minggu ini`), ASKA otomatis menarik jawaban dari `kecerdasan.md`.
7. Gunakan placeholder seperti `{{DATE}}`, `{{TIME}}`, `{{DAY}}`, `{{DATETIME}}`, `{{STAMP}}`, atau `{{UNIQUE}}` supaya tweet selalu beda di setiap putaran (cache duplikat dikontrol `TWITTER_AUTOPOST_RECENT_LIMIT`).
8. Setelah mengubah daftar pesan auto-post, restart worker agar daftar terbaru dimuat ulang.
9. Untuk memblokir mention spam tertentu, isi `TWITTER_SPAM_KEYWORDS` dengan daftar kata kunci (dipisah koma). ASKA juga memiliki filter bawaan untuk permintaan follow/promo.

> **Catatan:** Worker Twitter berjalan terpisah dari bot Telegram. Jalankan di screen/tmux atau buat service systemd baru kalau ingin 24/7.

### ⚙️ Deploy Worker Twitter/X di Server Ubuntu (Systemd)

Gunakan tutorial ini ketika worker Twitter sudah diuji jalan secara manual.

```bash
# 1. Pastikan dependensi terpasang dan virtualenv aktif
cd /root/ai-agent-sekolah
source venv/bin/activate
pip install -r requirements.txt

# 2. Cek kredensial Twitter di .env (gunakan nilai produksi)
nano .env  # periksa TWITTER_BEARER_TOKEN, TWITTER_API_KEY, dll.

# 3. Uji coba worker secara manual (Ctrl+C untuk berhenti)
python twitter_bot.py
```

Setelah worker terbukti jalan, buat service systemd khusus supaya worker ikut hidup otomatis saat server reboot.

```bash
# 4. Buat unit service systemd
sudo nano /etc/systemd/system/aska-twitter.service
```

Isi file `aska-twitter.service`:

```ini
[Unit]
Description=ASKA Twitter Worker
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/ai-agent-sekolah
EnvironmentFile=/root/ai-agent-sekolah/.env
ExecStart=/root/ai-agent-sekolah/venv/bin/python twitter_bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
User=www-data
Group=www-data

[Install]
WantedBy=multi-user.target
```

Kemudian aktifkan service:

```bash
# 5. Reload systemd dan jalankan worker
sudo systemctl daemon-reload
sudo systemctl enable aska-twitter.service
sudo systemctl start aska-twitter.service

# 6. Pantau status dan log cepat
sudo systemctl status aska-twitter.service
sudo journalctl -u aska-twitter.service -f
```

Tips produksi:

- Simpan file state di lokasi yang persisten (`TWITTER_STATE_PATH=/root/ai-agent-sekolah/twitter_state.json`).
- Gunakan interval yang masuk akal (`TWITTER_POLL_INTERVAL`, `TWITTER_AUTOPOST_INTERVAL`) agar tidak melewati rate limit.
- Atur kata kunci spam (`TWITTER_SPAM_KEYWORDS`) dan panjang maksimal (`TWITTER_MAX_TWEET_LEN`) sesuai strategi konten.
- Pastikan direktori `twitter_posts.txt` dapat dibaca oleh user service (`www-data` atau user lain yang dipilih).

---

## 📈 Cek Status & Log

```bash
# Cek status bot
sudo systemctl status ai-bots.service
# Cek status dashboard
sudo systemctl status aska-dashboard.service
# Cek status web app
sudo systemctl status aska-webapp.service

# Lihat log realtime bot
sudo journalctl -u ai-bots.service -f
```

---

## 🧪 Troubleshooting

| Masalah                         | Solusi                                        |
|-------------------------------|-----------------------------------------------|
| Tidak bisa `venv`             | Jalankan `apt install python3-venv -y`        |
| Gagal install `faiss`         | Jalankan `pip install faiss-cpu`              |
| Bot tidak merespons           | Cek `.env` dan jalankan `journalctl -u ai-bots.service -f` |
| OpenAI key error              | Pastikan variabel `OPENAI_API_KEY` benar      |
| Web tidak bisa diakses        | Cek status Nginx (`sudo systemctl status nginx`) dan log errornya |

---

## 🙋 Tentang

- Proyek Latsar CPNS 2025
- Oleh: **MH. Ainun Fajar**
- Sekolah: SDN Semper Barat 01
- GitHub: [@sofelijo](https://github.com/sofelijo)
