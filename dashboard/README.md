# ASKA Stakeholder Dashboard

Dashboard web modern untuk menampilkan performa bot ASKA, memberikan wawasan bagi stakeholder tanpa perlu akses langsung ke PostgreSQL.

## Fitur Utama

- Login dengan session berbasis cookie dan role (`admin`, `editor`, `viewer`).
- Kartu KPI: total pesan, pengguna unik, aktivitas 7 hari terakhir, pengguna aktif hari ini.
- Grafik tren 14 hari (Chart.js) berikut ringkasan waktu respon rata-rata dan P90.
- Feed pertanyaan terbaru dan daftar top user aktif.
- Tabel chat dengan filter tanggal, role, user ID, pencarian teks, serta ekspor CSV.
- Timeline percakapan per user untuk inspeksi percakapan lengkap.
- Halaman manajemen user dashboard khusus admin.

## Prasyarat

- Python 3.10+ dengan paket: `flask`, `psycopg2-binary`, `python-dotenv`.
- Tabel `chat_logs` yang sudah digunakan oleh bot utama.
- File `.env` yang memuat kredensial PostgreSQL berikut:
  - `DB_NAME`
  - `DB_USER`
  - `DB_PASS`
  - `DB_HOST`
  - `DB_PORT`
  - (opsional) `DB_SSLMODE`

Tambahkan juga variabel khusus dashboard:

```
DASHBOARD_SECRET_KEY=isi-dengan-string-acak-panjang
DASHBOARD_SESSION_DAYS=14
DASHBOARD_DB_MAX_CONN=8
```

## Instalasi Dependensi

```
pip install flask psycopg2-binary python-dotenv
```

## Inisialisasi Skema Dashboard

Jalankan perintah berikut untuk membuat tabel `dashboard_users` bila belum ada:

```
python -m dashboard.cli init-db
```

Jika ingin mengeksekusi secara manual, SQL yang digunakan:

```sql
CREATE TABLE IF NOT EXISTS dashboard_users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ
);
```

## Menjalankan Aplikasi

Gunakan salah satu cara berikut:

```
export FLASK_APP=dashboard.app:create_app  # PowerShell: $env:FLASK_APP = 'dashboard.app:create_app'
flask run --host 0.0.0.0 --port 5001
```

atau langsung:

```
python -m dashboard.app
```

Dashboard dapat diakses pada `http://localhost:5001`.

## CLI Manajemen

- Membuat user pertama:

  ```
  python -m dashboard.cli create-user admin@example.com "Nama Admin"
  ```

  Jika argumen `--password` tidak diberikan, sistem akan meminta input aman.

- Inisialisasi ulang skema (aman dijalankan ulang):

  ```
  python -m dashboard.cli init-db
  ```

## Struktur Folder

- `dashboard/app.py` : entry point WSGI.
- `dashboard/__init__.py` : factory Flask.
- `dashboard/auth.py` : blueprint autentikasi dan otorisasi.
- `dashboard/routes.py` : endpoint utama dan API.
- `dashboard/queries.py` : query agregasi dan retrieval data.
- `dashboard/db_access.py` : koneksi pooling PostgreSQL.
- `dashboard/schema.py` : helper pembuatan tabel dashboard.
- `dashboard/static/` : aset CSS/JS.
- `dashboard/templates/` : tampilan Jinja2.
- `dashboard/cli.py` : utilitas command-line.

## Catatan Produksi

- Ganti `SECRET_KEY` dengan string acak minimal 32 karakter.
- Nonaktifkan mode debug saat deploy (`FLASK_ENV=production`).
- Jalankan di belakang reverse proxy (Nginx/Caddy) dan aktifkan HTTPS.
- Pertimbangkan sistem autentikasi tunggal (SSO) dengan menyesuaikan `auth.py` bila dibutuhkan.
- Jadwalkan backup berkala untuk tabel `dashboard_users` dan `chat_logs`.

## Troubleshooting

- **Tidak bisa login:** pastikan password diset dengan CLI, bukan disimpan plaintext. Cek log untuk error koneksi DB.
- **Grafik kosong:** cek bahwa `chat_logs` memiliki data dalam rentang 14 hari terakhir.
- **Ekspor CSV gagal:** periksa izin koneksi ke database dan pastikan filter tidak menghasilkan dataset sangat besar.

Selamat menggunakan ASKA Stakeholder Dashboard!
