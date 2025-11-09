# 🤖 ASKA — Agent AI Sekolah Kita

ASKA adalah _stack_ AI untuk sekolah dasar hingga menengah yang siap digandakan. Satu repositori ini berisi:

- Bot Telegram yang mengenali konteks sekolah, menerima teks, foto, serta suara.
- Mesin RAG (Retrieval Augmented Generation) berbasis LangChain + Groq Llama 3.1 (bisa diganti OpenAI atau embedding lokal gratis).
- Dashboard Flask untuk monitoring percakapan, data kedisiplinan, dan notifikasi laporan sensitif.
- Web chat dengan login Google (belajar.id / Gmail) plus kuota percakapan.
- Workflow pelaporan bullying, psikolog, dan dugaan korupsi yang langsung masuk PostgreSQL.
- Worker opsional untuk Twitter/X (balas mention dan auto-post berbasis RAG).

Repo ini diproduksi di SDN Semper Barat 01, namun seluruh konfigurasi dipisah ke `.env` dan file markdown sehingga sekolah lain dapat mengkloning dengan cepat.

---

## 🔍 Kenapa Cocok untuk Sekolah Lain?

- **Modular** — tiga kanal (Telegram, Web, Twitter) berbagi _logic_ yang sama di `ai_core.py` + `flows/`.
- **Pengetahuan mudah diganti** — cukup edit `kecerdasan/profil_sekolah.md` & `kecerdasan/umum.md`, lalu jalankan `python knowledge_loader.py`.
- **Data internal aman** — semua laporan masuk PostgreSQL dan bisa dimonitor via dashboard.
- **Ops-friendly** — tersedia skrip `init_db.py`, CLI dashboard (`dashboard/cli.py`), serta contoh unit `systemd` dan Nginx.
- **Gratis bila perlu** — dukung embedding lokal HuggingFace dan STT/LLM OpenAI-compatible.

---

## 🧱 Arsitektur Singkat

```
Telegram / Web / Twitter
        │
        ▼
   handlers.py / web_aska.handlers
        │
        ▼
   LangChain RAG (ai_core.py)
        │           ▲
        │           │
        ▼           │
  PostgreSQL  ◄─────┘  (chat_logs, laporan, quota, dashboard)
        │
        ▼
Dashboard Flask + layanan Attendance
```

Direktori penting:

- `bot_sekolah.py` – entri bot Telegram.
- `web_aska/` – web chat (Flask + Google OAuth); ganti tampilan di `templates/`.
- `dashboard/` – dashboard admin, attendance tracker, CLI utility.
- `flows/` – percakapan khusus (bullying, psikologi, guru, korupsi, small talk).
- `responses/` – template jawaban dan detektor niat.
- `knowledge_loader.py` + `kecerdasan/` – sumber pengetahuan sekolah.
- `twitter_bot.py` – worker balas mention & auto-post.
- `db.py` & `init_db.py` – koneksi dan bootstrap PostgreSQL.

> Folder `backup/` tidak dipakai di produksi; abaikan saat melakukan penyesuaian.

---

## ✅ Prasyarat

**Server & Tooling**

- Ubuntu 22.04 LTS atau setara.
- Python 3.10+, `python3-venv`, `pip`, `git`.
- PostgreSQL 13+ (boleh layanan _managed_ seperti Supabase/Railway).
- Nginx + Certbot bila ingin HTTPS.

**Akun & Token**

- Token Bot Telegram dari `@BotFather`.
- Groq API key **atau** OpenAI API key (untuk LLM + embedding).
- (Opsional) OpenAI/HuggingFace key untuk embedding/STT lokal.
- Google OAuth client (untuk login web, bisa satu project per sekolah).
- (Opsional) Twitter/X developer keys.

---

## ⚡️ Langkah Instalasi Cepat (Ubuntu)

```bash
# 0. Sistem dasar
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3-venv python3-pip nginx certbot python3-certbot-nginx postgresql

# 1. Clone repo
cd /opt
sudo git clone https://github.com/sofelijo/ai-agent-sekolah.git
sudo chown -R $USER:$USER ai-agent-sekolah
cd ai-agent-sekolah

# 2. Virtualenv
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. Salin konfigurasi
cp .env .env.local.example  # opsional backup
nano .env                   # isi sesuai sekolah Anda

# 4. Susun ulang pengetahuan & cache vektor
python knowledge_loader.py

# 5. Inisialisasi semua tabel
python init_db.py

# 6. Buat akun admin dashboard
python -m dashboard.cli create-user admin@sekolah.sch.id "Admin Sekolah"

# 7. Uji komponen
python bot_sekolah.py          # hentikan dengan Ctrl+C setelah tes
python -m dashboard.app &
python -m web_aska.app &
```

---

## 🔐 Konfigurasi `.env`

Contoh templat (hapus bagian yang tidak dipakai):

```bash
###############################################################################
# Identitas dasar
###############################################################################
ASKA_SCHOOL_NAME="SDN Contoh 01"
ASKA_TIMEZONE=Asia/Jakarta

###############################################################################
# LLM & RAG
###############################################################################
GROQ_API_KEY=sk-...
OPENAI_API_KEY=                      # isi bila pakai OpenAI langsung
ASKA_QA_MODEL=llama-3.1-8b-instant   # bisa ganti gpt-4o, dsb.
ASKA_QA_TEMPERATURE=0
ASKA_QA_MAX_TOKENS=350

# Embedding
ASKA_EMBEDDING_BACKEND=auto          # auto | openai | local
ASKA_EMBEDDING_API_KEY=              # pakai OPENAI_API_KEY jika kosong
ASKA_EMBEDDING_MODEL=text-embedding-3-large
ASKA_EMBEDDING_MODEL_LOCAL=sentence-transformers/all-MiniLM-L6-v2
ASKA_EMBEDDING_DEVICE=cpu
ASKA_CHUNK_SIZE=500
ASKA_CHUNK_OVERLAP=50
ASKA_VECTORSTORE_PATH=.aska_vectorstore
ASKA_VECTORSTORE_INDEX=kecerdasan

# Speech-to-text (Telegram voice note)
ASKA_STT_API_KEY=
ASKA_STT_API_BASE=https://api.openai.com/v1
OPENAI_STT_MODEL=gpt-4o-mini-transcribe

###############################################################################
# Database (dipakai bot, dashboard, web, twitter worker)
###############################################################################
DB_NAME=aska_db
DB_USER=aska_user
DB_PASS=super-secret
DB_HOST=127.0.0.1
DB_PORT=5432
DB_SSLMODE=                       # isi require bila perlu

###############################################################################
# Kanal Telegram
###############################################################################
TELEGRAM_BOT_TOKEN=123456:ABC

###############################################################################
# Dashboard Flask
###############################################################################
DASHBOARD_SECRET_KEY=ubah-ke-random-32-karakter
DASHBOARD_SESSION_DAYS=14
DASHBOARD_DB_MAX_CONN=8

###############################################################################
# Web Chat (OAuth Google)
###############################################################################
APP_SECRET_KEY=ubah-lagi-untuk-web
GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=yyy
WEB_QUOTA_LIMIT=3
WEB_QUOTA_RESET_HOURS=24

###############################################################################
# Twitter / X (opsional)
###############################################################################
TWITTER_BEARER_TOKEN=
TWITTER_API_KEY=
TWITTER_API_SECRET=
TWITTER_ACCESS_TOKEN=
TWITTER_ACCESS_SECRET=
TWITTER_POLL_INTERVAL=90
TWITTER_STATE_PATH=twitter_state.json
TWITTER_AUTOPOST_ENABLED=false
TWITTER_AUTOPOST_INTERVAL=3600
TWITTER_AUTOPOST_MESSAGES_PATH=twitter_posts.txt
TWITTER_AUTOPOST_RECENT_LIMIT=8
TWITTER_SPAM_KEYWORDS=promo,follback
```

> Saran: gunakan `cp .env .env.production` lalu simpan versi berbeda untuk staging.

---

## 📚 Menyiapkan Pengetahuan Sekolah

1. Isi `kecerdasan/profil_sekolah.md` dengan data unik sekolah (profil, guru piket, jadwal kegiatan).
2. Lengkapi `kecerdasan/umum.md` untuk panduan generik (layanan, kebijakan nasional, FAQ).
3. Sisipkan `<!-- {{ASKA_PROFIL_DAN_JADWAL}} -->` di `umum.md` bila ingin menempel profil secara otomatis.
4. Jalankan `python knowledge_loader.py` agar `kecerdasan.md` diperbarui dan tersimpan di cache FAISS.
5. Jika ingin mereset vektor, hapus folder `.aska_vectorstore/` kemudian jalankan ulang bot.

---

## 🗄️ Inisialisasi Database & Data Referensi

- Jalankan `python init_db.py` setiap kali mengubah struktur atau saat setup baru. Skrip ini memanggil `db.py` dan `dashboard/schema.py` untuk menyiapkan:
  - `chat_logs`, `web_users`, `telegram_users`, `corruption_reports`, `bullying_reports`, `psych_reports`, `twitter_worker_logs`.
  - Tabel dashboard (`dashboard_users`, `bullying_report_events`, `notifications`) serta kolom pendukung attendance.
- Buat akun dashboard dengan CLI:

```bash
python -m dashboard.cli create-user admin@contoh.sch.id "Admin Contoh" --role admin
python -m dashboard.cli list-users
```

### 📥 Tutorial Import Data Siswa (Excel)

1. **Siapkan workbook per kelas**  
   - Gunakan template `dashboard/attendance/data_siswa/data_siswa.xlsx` atau ekspor Dapodik per kelas.  
   - Tiap sheet = 1 kelas, nama sheet menjadi nama kelas (mis. `1A`, `6B`).  
   - Header wajib berada pada baris setelah kolom judul dan minimal memiliki kolom berikut (urut sesuai template):

     | Kolom | Keterangan |
     | --- | --- |
     | `NO` | Nomor urut siswa di kelas |
     | `KELAS` | Label kelas (boleh kosong karena diambil dari nama sheet) |
     | `NIS` | Nomor induk sekolah |
     | `NISN` | Nomor induk nasional |
     | `NAMA SISWA` | Nama lengkap tanpa gelar (WAJIB) |
     | `JK` | Jenis kelamin |
     | `TEMPAT LAHIR` | Opsional |
     | `TANGGAL LAHIR` | Format `YYYY-MM-DD` atau `DD/MM/YYYY` |
     | `AGAMA` | Opsional |
     | `ALAMAT`, `RT`, `RW`, `KELURAHAN`, `KECAMATAN` | Opsional |
     | `NAMA AYAH`, `NAMA IBU` | Opsional |
     | `NIK`, `NO KK` | Opsional |

   - Hapus baris gabungan, gambar, atau catatan lain di dalam sheet kelas. Jika workbook memiliki sheet `Rekap` atau `Siswa`, biarkan—skrip akan melewatinya.

2. **Letakkan file di repo (opsional tapi memudahkan)**  
   Simpan pada `dashboard/attendance/data_siswa/namafile.xlsx` agar historinya terdokumentasi.

3. **Jalankan import melalui CLI**  
   Aktifkan virtualenv lalu jalankan:

   ```bash
   source venv/bin/activate
   python -m dashboard.cli import-attendance dashboard/attendance/data_siswa/data_siswa.xlsx --academic-year 2024/2025
   ```

   - `--academic-year` boleh diabaikan jika file sudah mengandung teks `2024/2025` (skrip otomatis mendeteksi).
   - Perintah akan membuat entri kelas di tabel `school_classes` dan memasukkan siswa ke `students`.

4. **Verifikasi**  
   - Buka Dashboard → Attendance → Master Data untuk memastikan kelas/siswa muncul.  
   - Jika perlu ulang, hapus data via dashboard atau `DELETE FROM students WHERE academic_year = ...` sebelum re-import.

### 👩‍🏫 Tutorial Import Data Guru & Staff

1. **Gunakan file DUK / rekap guru** seperti `DUK SEMBAR 01 (1).xlsx`. Pastikan kolom `STATUS PTK`, `NAMA TANPA GELAR`, `EMAIL`, `NIP`, `NRK` berada dalam urutan default Dapodik (skrip membaca otomatis).  
2. **Jalankan perintah berikut**:

   ```bash
   source venv/bin/activate
   python -m dashboard.cli import-teachers dashboard/attendance/data_siswa/DUK_SEKOLAH.xlsx --password "Rahasia123"
   ```

   - Jika `--password` tidak diisi, semua staff akan memiliki password awal `tes`.  
   - Skrip memanfaatkan `email` sebagai kunci unik: jika sudah ada akan di-_update_, jika belum akan dibuat user role `staff`.

3. **Beritahu guru** tentang kredensial login dashboard dan minta mereka mengubah password setelah masuk.

> Tips kerapihan: sebelum impor, buka file di Excel/LibreOffice, gunakan fitur **Remove Duplicates** pada kolom `NISN` dan `Email`, serta pastikan tanggal lahir dalam format tanggal standar agar parser tidak gagal.

---

## ▶️ Menjalankan Komponen

### 1. Telegram Bot

```bash
source venv/bin/activate
python bot_sekolah.py
```

### 2. Dashboard Admin

```bash
export FLASK_APP=dashboard.app:create_app
flask run --host 0.0.0.0 --port 8000
# produksi: gunicorn -w 2 -k gthread -b 127.0.0.1:8000 dashboard.app:app
```

### 3. Web Chat (Flask + Google OAuth)

```bash
export FLASK_APP=web_aska.app:app
flask run --host 0.0.0.0 --port 5001
# produksi: gunicorn -w 2 -k gthread -b 127.0.0.1:5001 web_aska.app:app
```

### Opsional: Dashboard Absensi Saja

```bash
export FLASK_APP=attendance_app:app
flask run --host 0.0.0.0 --port 8000
```

Entry point `attendance_app.py` hanya mendaftarkan blueprint autentikasi dan modul absensi, sehingga menu KPI lain tersembunyi. Abaikan langkah ini bila ingin menjalankan dashboard lengkap.

### 4. Twitter Worker (opsional)

```bash
python twitter_bot.py
```

### 5. Regenerasi Knowledge & Cache

```bash
python knowledge_loader.py
rm -rf .aska_vectorstore && python bot_sekolah.py   # paksa rebuild
```

---

## 🛡️ Contoh Unit `systemd`

Sesuaikan jalur `WorkingDirectory` dengan lokasi repo Anda (mis. `/opt/aska`).

### `ai-bot.service`

```ini
[Unit]
Description=ASKA Telegram Bot
After=network.target

[Service]
WorkingDirectory=/opt/ai-agent-sekolah
EnvironmentFile=/opt/ai-agent-sekolah/.env
ExecStart=/opt/ai-agent-sekolah/venv/bin/python bot_sekolah.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### `aska-dashboard.service`

```ini
[Unit]
Description=ASKA Dashboard
After=network.target

[Service]
WorkingDirectory=/opt/ai-agent-sekolah
EnvironmentFile=/opt/ai-agent-sekolah/.env
ExecStart=/opt/ai-agent-sekolah/venv/bin/gunicorn -w 2 -k gthread -b 127.0.0.1:8000 dashboard.app:app
User=www-data
Group=www-data
Restart=always

[Install]
WantedBy=multi-user.target
```

### `aska-webapp.service`

```ini
[Unit]
Description=ASKA Web Chat
After=network.target

[Service]
WorkingDirectory=/opt/ai-agent-sekolah
EnvironmentFile=/opt/ai-agent-sekolah/.env
ExecStart=/opt/ai-agent-sekolah/venv/bin/gunicorn -w 2 -k gthread -b 127.0.0.1:5001 web_aska.app:app
User=www-data
Group=www-data
Restart=always

[Install]
WantedBy=multi-user.target
```

### `aska-twitter.service` (opsional) sudah dicontohkan pada bagian Twitter.

---

## 🌐 Contoh Nginx

```nginx
server {
    listen 80;
    server_name dashboard.sekolah.sch.id;

    location /static/ {
        alias /opt/ai-agent-sekolah/dashboard/static/;
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

Ulangi pola yang sama untuk web chat (port 5001). Jangan lupa TLS:

```bash
sudo certbot --nginx -d dashboard.sekolah.sch.id -d aska.sekolah.sch.id
```

---

## 🏫 Checklist Migrasi ke Sekolah Baru

1. **Branding & Copy**
   - Ubah nama sekolah di `.env`, `web_aska/templates/*.html`, dan `dashboard/templates/*.html`.
   - Sesuaikan emoji/gaya bahasa di `responses/`.
2. **Pengetahuan**
   - Tulis data unik sekolah di `kecerdasan/profil_sekolah.md`.
   - Isi kalender kegiatan dan SOP di `kecerdasan/umum.md`.
   - Jalankan `python knowledge_loader.py`.
3. **Data Siswa & Guru**
   - Perbarui Excel di `dashboard/attendance/data_siswa/`.
   - Gunakan halaman Attendance Admin atau skrip importer untuk memuat data.
4. **Integrasi Google**
   - Buat OAuth client baru, isi `GOOGLE_CLIENT_ID/SECRET`, dan perbarui domain yang diizinkan.
5. **Kebijakan Akses**
   - Atur kuota web di `.env` (`DEFAULT_LIMITED_QUOTA`, dsb).
   - Gunakan `account_status.py` untuk memblokir atau memberi prioritas user tertentu.
6. **Keamanan & Privasi**
   - Ganti semua `SECRET_KEY`, `APP_SECRET_KEY`, password DB, serta buat user PostgreSQL unik.
   - Pastikan hanya admin sekolah yang punya akses dashboard (`dashboard_users`).
7. **Opsional: Twitter & Voice**
   - Isi kredensial `TWITTER_*` bila ingin kampanye publik.
   - Aktifkan `ASKA_STT_API_KEY` untuk fitur voice note.

---

## 📊 Monitoring & Pemeliharaan

```bash
sudo systemctl status ai-bot.service
sudo systemctl status aska-dashboard.service
sudo systemctl status aska-webapp.service
sudo journalctl -u ai-bot.service -f   # lihat log real-time
```

Update kode secara berkala:

```bash
cd /opt/ai-agent-sekolah
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart ai-bot.service aska-dashboard.service aska-webapp.service
```

---

## 🧪 Troubleshooting Cepat

| Gejala | Langkah cek cepat |
| --- | --- |
| Tidak bisa membuat `venv` | `sudo apt install python3-venv -y` |
| Bot diam | Pastikan `.env` benar, cek `journalctl -u ai-bot.service -f` |
| Error `faiss` | `pip install faiss-cpu` (atau pasang dari conda pada CPU lawas) |
| Google login gagal | Pastikan domain di konsol Google sudah memasukkan URL callback `/authorize` |
| Dashboard blank | Periksa koneksi DB (`psql`), jalankan ulang `python init_db.py` |
| Embedding lokal error | Install `pip install langchain-huggingface sentence-transformers torch>=1.11` |

---

## 🙋‍♂️ Kontributor

- MH. Ainun Fajar — Latsar CPNS 2025, SDN Semper Barat 01.
- GitHub: [@sofelijo](https://github.com/sofelijo)

Silakan buka _issue_ atau _pull request_ bila ada saran perbaikan. Semoga membantu sekolah Anda membangun layanan AI dengan cepat! 🙌
