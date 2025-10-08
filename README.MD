# 🤖 ASKA — Agent AI Sekolah Kita (Telegram Bot)

**ASKA** adalah asisten AI berbasis Telegram untuk SDN Semper Barat 01 yang mampu menjawab pertanyaan seputar sekolah berdasarkan file `.md`. Dibangun dengan OpenAI GPT-4o, LangChain, dan FAISS. Bot ini aktif 24 jam di server VPS dengan auto-restart.

---

## 📦 Fitur Utama

- Menjawab pertanyaan dari file `kecerdasan.md`
- Menggunakan gaya bahasa Gen-Z yang santai 😎
- Bisa jalan di lokal atau server (VPS)
- Bot Telegram aktif 24 jam via `systemd`
- Web Dashboard untuk administrasi
- Web App untuk antarmuka chat

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
OPENAI_API_KEY=ISI_API_KEY_OPENAI

# Koneksi PostgreSQL (bot + dashboard)
DB_NAME=nama_database
DB_USER=nama_user
DB_PASS=password
DB_HOST=127.0.0.1
DB_PORT=5432
# Opsional kalau provider butuh TLS: DB_SSLMODE=require

# Konfigurasi dashboard Flask
DASHBOARD_SECRET_KEY=ganti-dengan-string-acak-minimal-32-karakter
DASHBOARD_SESSION_DAYS=14
DASHBOARD_DB_MAX_CONN=8
EOF

# Jalankan sekali untuk inisialisasi tabel pengguna dashboard
python -m dashboard.cli init-db

# Buat akun admin pertama dashboard
python -m dashboard.cli create-user admin@example.com "Nama Admin"

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
ExecStart=/root/ai-agent-sekolah/venv/bin/gunicorn -w 2 -k gthread -b 127.0.0.1:5001 app:app
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

# Restart semua service
sudo systemctl restart ai-bots.service
sudo systemctl restart aska-dashboard.service
sudo systemctl restart aska-webapp.service
```

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