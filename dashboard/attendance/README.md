# ASKA Attendance Module

Modul attendance pada folder ini adalah paket lengkap untuk mengelola absensi kelas dan guru tanpa perlu seluruh fitur bot Telegram. Blueprint Flask (`attendance_bp`) hadir dengan UI siap pakai, import Excel, serta laporan cetak bulanan. README ini membantu sekolah yang hanya ingin menjalankan aplikasi absensi.

---

## Fitur Singkat

- **Dashboard Statistik** (`/absen`)  
  Ringkasan KPI harian, tren 7 hari, heatmap bulanan, progres tiap kelas, dan daftar submission terbaru.
- **Input Absensi Kelas** (`/absen/kelas`)  
  Guru/staff mengisi status `masuk/alpa/izin/sakit` per siswa, dengan auto-track waktu entri dan riwayat per kelas.
- **Absensi Guru & Tenaga Kependidikan** (`/absen/staff`)  
  Admin menandai kehadiran staff, lengkap dengan ringkasan status dan log siapa yang mengisi.
- **Laporan Harian & Bulanan** (`/absen/laporan-harian`, `/absen/laporan-bulanan`, `/absen/lembar-bulanan`)  
  Template HTML siap cetak (lihat `templates/attendance/report_*.html`) untuk ditempel di papan pengumuman.
- **Master Data** (`/absen/master`, `/absen/master/staff`)  
  CRUD dasar untuk siswa dan akun staff.
- **Dukungan DUK (Daftar Urut Kepangkatan)**  
  Otomatis menampilkan gelar depan/belakang kepala sekolah dan guru jika Anda menyetel `ATTENDANCE_DUK_PATH`.

---

## Struktur Folder

| File/Folder | Fungsi |
| --- | --- |
| `routes.py` | Seluruh endpoint Flask untuk dashboard, input kelas, laporan, master data. |
| `queries.py` | Akses PostgreSQL (student master, attendance_records, teacher_attendance, dsb). |
| `importer.py` | Parser Excel siswa multi-sheet (per kelas). Digunakan oleh CLI `import-attendance`. |
| `teacher_importer.py` | Parser Excel DUK untuk membuat akun staff. |
| `templates/attendance/` | Halaman HTML (stats, input kelas, laporan harian/bulanan). |
| `data_siswa/` | Contoh file Excel (`data_siswa.xlsx`, `DUK SEMBAR 01 (1).xlsx`). |
| `duk_degrees.py` | Utility membaca file DUK (CSV/Excel) untuk melengkapi gelar. |

Semua dependensi disatukan lewat `dashboard/app.py`. Bila hanya memakai absensi, Anda tetap menjalankan `dashboard.app:create_app` namun bisa menyembunyikan menu lain pada template `dashboard/templates/base.html`.

---

## Prasyarat

- Python 3.10+ dan `python3-venv`
- PostgreSQL 13+ (lokal atau managed).  
  Wajib mengisi variabel: `DB_NAME`, `DB_USER`, `DB_PASS`, `DB_HOST`, `DB_PORT`, `DB_SSLMODE` (opsional).
- Variabel Flask dasar:
  - `DASHBOARD_SECRET_KEY`
  - `DASHBOARD_SESSION_DAYS` (default 14)
  - `ATTENDANCE_DUK_PATH` (opsional, path ke file DUK `.xlsx` untuk melengkapi gelar)
- Server: Nginx + Gunicorn (opsional, untuk produksi) atau cukup `flask run` saat uji coba.

Contoh `.env` minimum:

```bash
DB_NAME=aska_attendance
DB_USER=aska_user
DB_PASS=supersecret
DB_HOST=127.0.0.1
DB_PORT=5432

DASHBOARD_SECRET_KEY=ubah-ke-random
DASHBOARD_SESSION_DAYS=14

# Otomatis baca gelar dari file DUK (opsional)
ATTENDANCE_DUK_PATH=/opt/ai-agent-sekolah/dashboard/attendance/data_siswa/DUK_SEKOLAH.xlsx
```

---

## Instalasi Cepat (Absensi Saja)

```bash
cd /opt
git clone https://github.com/sofelijo/ai-agent-sekolah.git
cd ai-agent-sekolah
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Setup DB & tabel attendance
python init_db.py
# atau minimal untuk dashboard saja:
python -m dashboard.cli init-db
```

Selanjutnya jalankan aplikasi:

```bash
export FLASK_APP=dashboard.app:create_app
flask run --host 0.0.0.0 --port 8000
# Produksi: gunicorn -w 2 -k gthread -b 127.0.0.1:8000 dashboard.app:app
```

> Modul attendance ikut blueprint `attendance_bp`, jadi login & otentikasi memakai `dashboard/auth.py`. Buat akun admin/staff via CLI sebelum akses.

---

## Deploy di VPS (Gunicorn + systemd + Nginx)

> Contoh ini memakai entry point `attendance_app.py` agar menu lain disembunyikan. Jika ingin dashboard penuh, ganti `attendance_app:app` menjadi `dashboard.app:app`.

1. **Buat service systemd**

```bash
sudo nano /etc/systemd/system/aska-attendance.service
```

Isi file:

```ini
[Unit]
Description=ASKA Attendance Dashboard
After=network.target

[Service]
WorkingDirectory=/opt/ai-agent-sekolah
EnvironmentFile=/opt/ai-agent-sekolah/.env
ExecStart=/opt/ai-agent-sekolah/venv/bin/gunicorn -w 2 -k gthread -b 127.0.0.1:8100 attendance_app:app
User=www-data
Group=www-data
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Aktifkan service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable aska-attendance.service
sudo systemctl start aska-attendance.service
sudo systemctl status aska-attendance.service
```

2. **Konfigurasi Nginx**

```bash
sudo nano /etc/nginx/sites-available/aska-attendance
```

Contoh konfigurasi:

```nginx
server {
    listen 80;
    server_name attendance.sekolah.sch.id;

    location /static/ {
        alias /opt/ai-agent-sekolah/dashboard/static/;
        access_log off;
        expires 30d;
    }

    location / {
        proxy_pass http://127.0.0.1:8100;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Aktifkan dan uji:

```bash
sudo ln -s /etc/nginx/sites-available/aska-attendance /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

3. **Pasang SSL (opsional tapi disarankan)**

```bash
sudo certbot --nginx -d attendance.sekolah.sch.id
```

4. **Monitoring**

```bash
sudo systemctl status aska-attendance.service
sudo journalctl -u aska-attendance.service -f
```

---

## Manajemen Pengguna

Buat akun admin/staff:

```bash
python -m dashboard.cli create-user admin@sekolah.sch.id "Admin Sekolah" --role admin
python -m dashboard.cli create-user guru1@sekolah.sch.id "Guru 1" --role staff
```

- **Role `staff`** → bisa mengisi menu `/absen/kelas`.
- **Role `admin`** → akses penuh (dashboard, staff attendance, master data).

---

## Import Data Siswa dari Excel

1. **Format workbook**
   - Satu sheet per kelas (mis. `1A`, `6B`). Nama sheet = nama kelas.
   - Gunakan template `data_siswa/data_siswa.xlsx` sebagai referensi.
   - Header wajib memuat kolom `NO`, `NIS`, `NISN`, `NAMA SISWA`, `JK`, `TANGGAL LAHIR`, dst (lihat tabel detail di README root).
   - Hindari cell merge / komentar. Jika ada sheet rekap, biarkan (akan dilewati).

2. **Jalankan CLI import**

```bash
source venv/bin/activate
python -m dashboard.cli import-attendance dashboard/attendance/data_siswa/data_siswa.xlsx --academic-year 2024/2025
```

- Flag `--academic-year` opsional (skrip mencoba mendeteksi teks `2024/2025`).  
- Perintah ini membuat entri kelas (`school_classes`) lalu mengisi tabel `students`.

3. **Verifikasi**
   - Buka `/absen/master` → pastikan daftar siswa & kelas sesuai.
   - Jika ingin mengulang dari nol, hapus data terkait (`DELETE FROM attendance_records; DELETE FROM students; DELETE FROM school_classes;`) lalu jalankan import lagi.

---

## Import Data Guru/Staff

1. **Siapkan file DUK** (contoh: `DUK SEMBAR 01 (1).xlsx`). Minimal kolom `STATUS PTK`, `NAMA TANPA GELAR`, `EMAIL`, `NIP`, `NRK` harus ada.
2. **Jalankan perintah**:

```bash
source venv/bin/activate
python -m dashboard.cli import-teachers dashboard/attendance/data_siswa/DUK_SEKOLAH.xlsx --password "Rahasia123"
```

- Jika `--password` tidak diisi, default `tes`.
- Skrip menggunakan email sebagai key: jika sudah ada user → update profil; jika belum → buat akun `staff`.
- Setelah selesai, minta guru mengganti password di halaman profil dashboard.

3. (Opsional) Setel `ATTENDANCE_DUK_PATH` untuk menampilkan gelar di laporan harian/bulanan secara otomatis.

---

## Menjalankan Hanya Menu Absensi

Secara default, menu attendance muncul berdampingan dengan modul dashboard lainnya. Bila ingin menampilkan hanya menu absensi:

1. Edit `dashboard/templates/base.html` dan sembunyikan link lain sehingga hanya menyisakan tab `Absensi`.
2. Gunakan role `staff` untuk guru (mereka hanya melihat halaman kelas).  
3. Entry point siap pakai `attendance_app.py` telah disediakan di root repo. Jalankan dengan `FLASK_APP=attendance_app:app flask run ...` untuk mode absensi saja (file tersebut hanya mendaftarkan blueprint `auth` dan `attendance`).

---

## Laporan yang Tersedia

| Route | Template | Keterangan |
| --- | --- | --- |
| `/absen/laporan-harian` | `templates/attendance/report_daily.html` | Rekap satu tanggal + tanda tangan kepala sekolah. |
| `/absen/laporan-bulanan` | `templates/attendance/report_monthly.html` | Grafik & tabel per kelas untuk satu bulan. |
| `/absen/lembar-bulanan` | `templates/attendance/report_class_monthly.html` | Form siap cetak per kelas/per bulan untuk diisi manual. |

Semua halaman sudah menggunakan format tanggal Indonesia (`utils.current_jakarta_time`) dan dapat langsung dicetak dari browser.

---

## Tips Operasional

- **Jam Server**: Pastikan timezone server `Asia/Jakarta` agar label hari cocok dengan filter `_format_indonesian_date`.
- **Backup Data**: `attendance_records` dan `teacher_attendance` dapat diekspor dengan `COPY` atau tool favorit Anda sebelum reset semester.
- **Pengisian Otomatis Gelar**: Jika `ATTENDANCE_DUK_PATH` di-set, modul akan membaca file DUK untuk mengisi `degree_prefix/suffix` ketika membuat laporan.
- **Keamanan**: Dashboard hanya bisa diakses user login. Pastikan HTTPS terpasang bila aplikasi dibuka dari luar jaringan sekolah.

---

Dengan panduan ini, sekolah lain dapat menyalin modul attendance saja tanpa harus mengaktifkan bot Telegram atau fitur AI lainnya. Selamat mencoba! 🎒📊
