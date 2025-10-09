# ASKA Stakeholder Dashboard

Dashboard Flask untuk memantau performa bot ASKA tanpa akses langsung ke database. Aplikasi menampilkan KPI, grafik aktivitas, daftar percakapan, serta manajemen pengguna dashboard.

## Fitur Utama

- Login berbasis session dengan role (`admin`, `editor`, `viewer`).
- Kartu KPI: total pesan, pengguna unik, volume 7 hari terakhir, pengguna aktif hari ini.
- Grafik tren 14 hari (Chart.js) termasuk rata-rata dan p90 waktu respon.
- Feed pertanyaan terbaru, top user aktif, dan timeline percakapan per user.
- Tabel chat dengan filter tanggal, role, user ID, pencarian teks, serta ekspor CSV.
- Halaman manajemen user dashboard khusus admin.

## Konfigurasi `.env`

Dashboard memakai kredensial database yang sama dengan bot. Tambahkan variabel berikut di file `.env` pada root proyek:

```bash
TELEGRAM_BOT_TOKEN=...            # digunakan oleh bot
OPENAI_API_KEY=...

DB_NAME=...
DB_USER=...
DB_PASS=...
DB_HOST=...
DB_PORT=5432
# Opsional: DB_SSLMODE=require

DASHBOARD_SECRET_KEY=ganti-dengan-string-acak
DASHBOARD_SESSION_DAYS=14
DASHBOARD_DB_MAX_CONN=8
```

## Instalasi & Setup

```bash
cd /opt/ai-agent-sekolah            # sesuaikan dengan lokasi Anda
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Inisialisasi tabel dashboard_users (sekali saja)
python -m dashboard.cli init-db

# Buat akun admin pertama
python -m dashboard.cli create-user admin@example.com "Nama Admin"
```

## Menjalankan Secara Lokal

```
export FLASK_APP=dashboard.app:create_app  # PowerShell: $env:FLASK_APP = 'dashboard.app:create_app'
flask run --host 0.0.0.0 --port 5001
```

Atau jalankan langsung:

```
python -m dashboard.app
```

## Menjalankan di VPS (Gunicorn + systemd)

Mode default memakai Nginx sebagai reverse proxy supaya lebih mudah pasang HTTPS dan memberi lapisan keamanan tambahan. Kalau mau langsung expose port Gunicorn, lihat opsi di bagian Alternatif tanpa Nginx.

Buat service `aska-dashboard.service`:

```
nano /etc/systemd/system/aska-dashboard.service
```

Isi file:

```
[Unit]
Description=ASKA Dashboard (Gunicorn)
After=network.target

[Service]
WorkingDirectory=/opt/ai-agent-sekolah
EnvironmentFile=/opt/ai-agent-sekolah/.env
ExecStart=/opt/ai-agent-sekolah/venv/bin/gunicorn -w 2 -k gthread -b 127.0.0.1:8001 dashboard.app:app
Restart=always
User=www-data
Group=www-data

[Install]
WantedBy=multi-user.target
```

Aktifkan service:

```
systemctl daemon-reload
systemctl enable aska-dashboard.service
systemctl start aska-dashboard.service
systemctl status aska-dashboard.service
```

Log dapat dipantau dengan `journalctl -u aska-dashboard.service -f`.

## Reverse Proxy & HTTPS

Contoh konfigurasi Nginx untuk subdomain `dashboard.domainmu.com`:

```
nano /etc/nginx/sites-available/aska-dashboard
```

```
server {
    listen 80;
    server_name dashboard.domainmu.com;

    location /static/ {
        alias /opt/ai-agent-sekolah/dashboard/static/;
        access_log off;
        expires 30d;
    }

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Aktifkan site dan reload Nginx:

```
ln -s /etc/nginx/sites-available/aska-dashboard /etc/nginx/sites-enabled/aska-dashboard
nginx -t
systemctl reload nginx
```

Tambahkan HTTPS dengan Certbot (opsional):

```
apt install certbot python3-certbot-nginx -y
certbot --nginx -d dashboard.domainmu.com
```

### Alternatif tanpa Nginx

Jika ingin langsung membuka dashboard lewat IP VPS tanpa reverse proxy:

- Ubah perintah Gunicorn menjadi `-b 0.0.0.0:5001` atau port lain yang dibuka.
- Izinkan port tersebut di firewall, mis. `ufw allow 5001/tcp`.
- Akses via `http://IP-VPS:5001`.

Mode ini tidak memberikan HTTPS otomatis maupun proteksi header tambahan, jadi pastikan kredensial kuat dan pertimbangkan kembali memasang proxy saat butuh TLS.

## CLI Manajemen

- `python -m dashboard.cli init-db` � membuat tabel dashboard.
- `python -m dashboard.cli create-user email@example.com "Nama"` � membuat user baru. Gunakan opsi `--role` (`admin`, `editor`, `viewer`) dan `--password` bila ingin langsung mengisi password di CLI.

## Struktur Folder

- `dashboard/app.py` : entry point WSGI.
- `dashboard/__init__.py` : factory Flask.
- `dashboard/auth.py` : blueprint autentikasi & otorisasi.
- `dashboard/routes.py` : endpoint utama & API.
- `dashboard/queries.py` : query agregasi data bot.
- `dashboard/db_access.py` : koneksi pooling PostgreSQL.
- `dashboard/schema.py` : helper pembuatan tabel dashboard.
- `dashboard/static/` : aset CSS/JS.
- `dashboard/templates/` : tampilan Jinja2.
- `dashboard/cli.py` : utilitas command-line.

## Troubleshooting

- **Tidak bisa login** � pastikan user dibuat via CLI dan password benar, cek log `journalctl` untuk error DB.
- **Grafik kosong** � data `chat_logs` mungkin belum ada dalam 14 hari terakhir.
- **Ekspor CSV gagal** � periksa koneksi database dan pastikan filter tidak menghasilkan dataset terlalu besar.
- **Service gagal start** � cek path `WorkingDirectory` dan hak akses user `www-data` (atau ganti ke user lain sesuai setup Anda).

Selamat menggunakan ASKA Stakeholder Dashboard!
