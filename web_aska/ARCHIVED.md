# Status layanan Web ASKA lama

Mulai 7 Oktober 2026, aplikasi Web ASKA pada `aska.sdnsembar01.sch.id`
dinonaktifkan untuk mengurangi penggunaan RAM server.

Kode, template, aset, dan riwayat aplikasi lama tetap disimpan utuh dalam
direktori `web_aska/` dan riwayat Git. Nginx menampilkan halaman statis ringan
dari `web_aska/static/aska-moved/index.html` yang mengarahkan pengguna ke:

`http://aska.sudindikju2.com/`

Konfigurasi Nginx untuk mode nonaktif disimpan di
`deploy/nginx/aska-webapp-disabled.conf`.

Layanan cek kelulusan kini berjalan mandiri di
`https://sdnsembar01.sch.id/kelulusan` melalui aplikasi `landingpage/`, dengan
alur formulir NISN, hasil kelulusan, serta unduh/lihat SKL. URL lama
`/kelulusan`, `/cek-kelulusan`, dan `/lp/kelulusan` pada domain ASKA diarahkan
ke halaman sekolah tersebut. Aplikasi chat ASKA lama tetap nonaktif.
