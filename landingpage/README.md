# Landing page sekolah

Aplikasi `landingpage.app:app` dilayani oleh `aska-landingpage.service` pada
port lokal 5003 dan diproksikan lewat domain sekolah.

- `/cek-siswa`: formulir NISN dan status/riwayat kelas siswa.
- `/kelulusan`: formulir NISN, hasil kelulusan, serta tautan lihat/unduh SKL.
- `/cek-kelulusan` dan `/lp/kelulusan`: alias menuju `/kelulusan`.

Kelulusan memakai data aktif `landingpage_graduations` untuk
`LANDINGPAGE_SITE_KEY` (default `default`). Dokumen dibaca dari metadata
`document.relative_path` di bawah `landingpage/static/landingpage/uploads/graduations/`.
Halaman ini tidak memanggil chat atau API ASKA dan tidak mengubah data kelulusan.

`LANDINGPAGE_SECRET_KEY` atau `DASHBOARD_SECRET_KEY` diperlukan untuk sesi
akses surat. Setelah NISN ditemukan, akses surat berlaku 15 menit melalui
cookie HTTPS `landingpage_session`; unduh/preview mengecek ulang status aktif,
tanggal pengumuman, dan lokasi file. Formulir serta dokumen memakai `no-store`.
Waktu countdown lama tetap 2 Juni 2026 pukul 10.00 WIB; tanggal pengumuman
per siswa juga dihormati.

URL kelulusan pada domain ASKA lama dialihkan oleh
`deploy/nginx/aska-webapp-disabled.conf`. API/chat ASKA lama tetap nonaktif.

Pengujian: `venv/bin/python -m unittest discover -s tests -p test_landing_graduation.py`.

## Pelaporan perundungan publik

`/lapor-bullying` tersedia tanpa login, dengan tautan dari beranda. Pelapor dapat mengosongkan nama dan kontak. Formulir menerima jenis, lokasi, kronologi, tanggal, pihak terlibat, serta penanda butuh perhatian segera. Tidak ada daftar siswa pada halaman publik. Bukti foto/video bersifat opsional. Konfirmasi hanya menampilkan kode acak milik sesi pengirim; isi laporan dan catatan guru tidak dibuka kepada publik.

Penyimpanan memakai database **asli**, termasuk saat mode dummy global aktif. Laporan masuk ke `bullying_reports` dan kejadian awal ke `bullying_report_events` dalam satu transaksi. Guru (role `staff`) dan admin menindaklanjuti di dashboard `/bullying-reports`, dengan status, catatan, penanggung jawab, tenggat WIB, dan riwayat perubahan. Role diperiksa ulang ke database asli. Role lain tidak dapat membaca kasus. Data laporan publik tidak disalin ke database dummy.

Formulir memiliki CSRF, batas panjang, validasi tanggal, honeypot, token pengiriman untuk mencegah duplikasi, serta batas per alamat jaringan (5 kiriman/10 menit, 20/hari). Identitas jaringan disimpan sebagai HMAC, bukan alamat IP mentah. Saat di belakang satu nginx tepercaya dan gunicorn hanya mendengarkan localhost, set `LANDINGPAGE_TRUST_PROXY=1`; ini mempercayai satu hop `X-Forwarded-For` / `X-Forwarded-Proto`. Jangan aktifkan jika aplikasi langsung terbuka ke internet. Pasang indeks dari `deploy/setup_public_bullying.sql` pada database asli. Akses detail dan perubahan dashboard memakai CSRF terpisah, dan laporan selalu dibaca dari asli.

Uji: `python -m unittest tests.test_public_bullying tests.test_bullying_access`. Uji storage PostgreSQL juga mencakup retry idempoten, pembatasan kiriman, audit, pembaruan massal, dan rollback di database sementara tanpa menyalin baris production.


Bukti pendukung: maksimal 3 berkas, masing-masing 20 MB, total 40 MB. Foto JPG/PNG/WebP diperiksa dengan Pillow (maksimal 20 megapiksel, tanpa animasi); video MP4/MOV/WebM diperiksa menggunakan `ffprobe` (wajib memiliki stream video, durasi maksimal 180 detik). MIME kiriman browser tidak dipercaya. Berkas asli dipertahankan, dicatat SHA-256-nya, disimpan dengan nama acak dan izin 0600 di `instance/private/bullying/` (opsional `BULLYING_EVIDENCE_DIR`). Folder ini harus dapat ditulis pengguna service dan **tidak boleh** dipasang sebagai static/alias nginx. Backup database beserta folder bukti ini secara privat.

Unduhan hanya melalui `/bullying-reports/<id>/evidence/<file_id>` pada domain admin, dengan pemeriksaan role guru/admin ke database asli untuk setiap request. Unduhan bersifat attachment dan no-store; bukan URL publik. Kiriman ulang tidak menambah berkas, dan berkas dibersihkan jika validasi atau transaksi database gagal. Saat formulir gagal, pengguna perlu memilih ulang berkas. Di production dibutuhkan paket sistem `ffmpeg` (penyedia ffprobe); nginx `location = /lapor-bullying` memakai `client_max_body_size 41m`, selaras dengan batas request aplikasi.
