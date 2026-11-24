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


## Mode data dummy / asli

Pengalih berada di Manajemen User → Pengaturan lanjutan, atau `/settings/data-mode`. Akses memerlukan role admin dan email dalam `DASHBOARD_DATA_MODE_ADMINS` (daftar dipisahkan koma); role dan email diperiksa ulang ke database asli setiap request. Tanpa konfigurasi, akses ditolak. Pilihan disimpan di database asli dan berlaku global untuk seluruh pengguna dashboard yang sudah login; pengunjung publik tetap memakai data asli. Login ulang diperlukan setelah perubahan role.

Mode dummy memakai salinan master siswa, kelas, buku, pembina, dan ekskul asli, sedangkan absensi serta peminjaman merupakan transaksi contoh. Pratinjau menggunakan database terpisah dan akun PostgreSQL hanya-baca. Formulir absensi kelas, staff, ekskul, dan master memakai data asli. Pada laporan tersedia tombol **Isi / ubah data asli** untuk membuka catatan yang dapat diedit. Formulir dan AJAX membawa penanda sumber; tindakan dari baris simulasi ditolak agar ID dummy tidak mengubah catatan asli. Kegagalan database dummy tidak beralih diam-diam ke data asli. Formulir dari tab dummy lama juga ditolak setelah kembali ke data asli.

Sinkronisasi master dan pembuatan ulang transaksi contoh: jalankan `venv/bin/python deploy/use_real_masters_for_demo.py --project /opt/ai-agent-sekolah` untuk melihat ringkasan, lalu tambahkan `--apply` untuk menerapkan. Database asli hanya dibaca. Skrip menyimpan backup privat sebelum mengubah database dummy secara atomik. Skrip ini hanya untuk pembuatan awal atau pemulihan dataset yang direncanakan; jangan dijalankan sebagai sinkronisasi rutin setelah outbox aktif. Daftar siswa dan kelas untuk setiap tanggal diambil dari `student_class_history` pada tahun ajaran terkait; transaksi dihentikan mulai tanggal lulus/keluar yang tercatat. Siaga memakai kelas 1–3 dan Penggalang kelas 4–6 pada tanggal kegiatan. Peminjam wajib terdaftar pada tanggal pinjam dan kembali. Tampilan historis pada mode dummy memakai kelas serta tahun ajaran saat transaksi, termasuk kelas yang kini sudah nonaktif. Skrip bootstrap/fixture lama yang mengharuskan 18 siswa tidak digunakan setelah migrasi ini.

Provisioning di VPS sebagai root: `venv/bin/python deploy/setup_dashboard_demo.py --project /opt/ai-agent-sekolah --admin-email EMAIL_ADMIN`. Skrip menyalin skema saja, mengisi data rekaan, lalu menulis `DASHBOARD_DEMO_DB_NAME`, `DASHBOARD_DEMO_DB_USER`, `DASHBOARD_DEMO_DB_PASS`, dan allowlist ke `.env`. Skrip menolak menimpa database/role yang sudah ada; opsi `--resume-empty-demo` hanya untuk melanjutkan provisioning yang gagal sebelum data terisi dan memverifikasi semua tabel masih kosong. Restart dashboard setelah konfigurasi diubah. Simpan backup `.env` secara privat.

Sinkronisasi perubahan guru memakai outbox PostgreSQL yang dibuat dalam transaksi yang sama dengan penyimpanan asli. Worker `aska-demo-sync.service` menyalin perubahan master siswa/kelas/pengguna, sejarah kelas, buku/eksemplar, ekskul/anggota/pembina, absensi kelas/staff/ekskul (termasuk foto/materi), siswa terlambat, serta poin siswa. Kata sandi asli tidak disalin. Master sensitif siswa dibatasi pada kolom operasional. Formulir asli tetap menyimpan jika worker atau database dummy tidak tersedia; antrean dicoba ulang. Worker berjalan juga saat mode asli agar salinan tetap mengikuti perubahan.

Absensi menggunakan kunci siswa–tanggal (atau guru–tanggal dan ekskul–siswa–tanggal), sehingga catatan nyata menggantikan simulasi pada kunci yang sama. Transaksi ber-ID terpisah memakai `source_record_id` unik, sehingga pengiriman ulang tidak menggandakan catatan. Peminjaman nyata menggantikan pinjaman simulasi yang bertabrakan pada eksemplar dan periode yang sama. Penghapusan asli ikut disinkronkan. Tidak ada alur menyalin dummy ke asli.

Pemasangan mode global pada database yang sudah memiliki dataset dummy: simpan backup privat kode, `.env`, dan database dummy; jalankan sebagai root `venv/bin/python deploy/setup_global_demo.py --project /opt/ai-agent-sekolah`, lalu `systemctl daemon-reload` dan `systemctl enable --now aska-demo-sync.service`. Dashboard harus dimuat ulang setelah migrasi. Pengaturan awal adalah asli; admin yang diizinkan mengaktifkan dummy melalui `/settings/data-mode`. Kredensial writer terpisah dari kredensial pembaca dashboard. Pantau jumlah antrean di halaman pengaturan serta `journalctl -u aska-demo-sync.service`; kesalahan worker hanya mencatat jenis/kode galat, tanpa isi data siswa.

Grafik tahun ajaran memakai rata-rata siswa per hari yang memiliki absensi, bukan akumulasi bulanan. Tooltip menunjukkan jumlah hari terisi; bulan tanpa catatan menjadi jeda. Total mentah tetap tersedia dalam payload `totals` dan laporan bulanan. Hari yang belum diisi tidak diartikan sebagai kehadiran nol.

Uji integrasi worker memakai dua database sementara dengan skema saja, tanpa menyalin baris production: jalankan `deploy/verify_demo_replication.py --schema-db NAMA_DATABASE_ASLI` sebagai postgres. Uji ini membersihkan database sementara setelah selesai.

Pengujian: `venv/bin/python -m unittest discover -s tests -p 'test_*.py'`.

## Laporan perundungan dari landing page

Formulir publik: `https://sdnsembar01.sch.id/lapor-bullying`. Menu **Lapor Bullying** pada halaman absensi membuka pengelolaan `/bullying-reports` untuk guru dan admin; admin juga dapat memakai menu **Laporan → Bullying**. Halaman daftar, detail, notifikasi kasus, dan penyimpanan tindak lanjut selalu memakai database asli, sehingga laporan publik tetap terlihat saat mode dummy aktif. Kasus dan kontak pelapor tidak direplikasi ke dummy. Perubahan status (termasuk massal) dicatat dalam timeline, dan form perubahan dilindungi CSRF. Tenggat dari formulir dibaca sebagai waktu WIB.

Bukti pendukung publik berupa foto/video opsional ditampilkan sebagai unduhan pada detail kasus. Endpoint unduhan memverifikasi role asli `staff`/`admin`, mengambil metadata laporan dari database asli, lalu melayani file privat dengan `Content-Disposition: attachment`, `nosniff`, dan `no-store`. Bukti disimpan di luar static; lihat `landingpage/README.md` untuk batas ukuran, direktori privat, dependency ffprobe, dan backup. Jangan menyalin folder bukti ke database atau direktori dummy/publik.

## Foto absensi ekskul periode Juli–November 2026

Folder kerja `Foto Ekskul Juli-November 2026/` dan backup `backup/foto-*/` tetap lokal dan diabaikan Git karena repo publik. Manifest tanpa gambar tersedia di `deploy/manifests/extracurricular-photos-20261124.json`. Foto Marawis (21), Pencak Silat (18), dan Tari Tradisional (3) sudah dicrop 3:4 tanpa bingkai setelah backup file asli diverifikasi.

Impor foto per folder `nama-ekskul/DD-MM-YYYY/gambar`: jalankan `venv/bin/python deploy/import_extracurricular_photos.py --photos DIREKTORI_FOTO --project /opt/ai-agent-sekolah` untuk dry-run. Untuk menerapkan, tambahkan `--apply --backup-dir DIREKTORI_BACKUP_PRIVAT_BARU --report LOKASI_LAPORAN_JSON`. Importer menolak foto yang belum 3:4, tanggal tanpa sesi, atau beberapa foto pada satu tanggal yang belum dipilih foto utamanya. Hanya baris transaksi **dummy** yang belum memiliki foto dan bukan salinan catatan asli yang diperbarui. Status kehadiran, waktu absensi, GPS, data asli, dan foto yang sudah tersedia dipertahankan. Backup tabel dibuat sebelum perubahan; pengiriman ulang bersifat idempoten. Berkas foto disimpan di `dashboard/static/uploads/ekskul/` dengan hash pada nama file.

Foto yang sudah tersedia di data asli dapat ditautkan ke sesi dummy pada tanggal dan ekskul yang sama menggunakan `deploy/reuse_original_extracurricular_photos.py --project /opt/ai-agent-sekolah --start YYYY-MM-DD --end YYYY-MM-DD`. Tambahkan `--apply --backup-dir DIREKTORI_PRIVAT_BARU --report LAPORAN_JSON` setelah meninjau dry-run. Koneksi asli hanya-baca; foto yang sudah terpasang dan catatan yang berasal dari sinkronisasi guru dipertahankan. Pramuka gabungan lama sengaja dikecualikan karena kelompok Siaga/Penggalang belum dapat dipastikan. Untuk Juli–24 November 2026, 33 foto asli ditautkan kembali selain 42 foto baru: total 75 sesi memiliki foto dan 56 sesi masih menunggu foto.
