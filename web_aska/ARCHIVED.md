# Status layanan Web ASKA lama

Mulai 7 Oktober 2026, aplikasi Web ASKA pada `aska.sdnsembar01.sch.id`
dinonaktifkan untuk mengurangi penggunaan RAM server.

Kode, template, aset, dan riwayat aplikasi lama tetap disimpan utuh dalam
direktori `web_aska/` dan riwayat Git. Nginx menampilkan halaman statis ringan
dari `web_aska/static/aska-moved/index.html` yang mengarahkan pengguna ke:

`http://aska.sudindikju2.com/`

Konfigurasi Nginx untuk mode nonaktif disimpan di
`deploy/nginx/aska-webapp-disabled.conf`.
