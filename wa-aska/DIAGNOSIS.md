# Diagnosis WhatsApp Bot ASKA

**Tanggal**: 29 Desember 2025  
**Status**: ⚠️ Belum bisa test chat dari WhatsApp

---

## 📊 Hasil Analisis

### ✅ Yang Sudah OK

1. **Struktur Project** - Lengkap dan terorganisir dengan baik
2. **Konfigurasi Environment** - Sudah ada di `.env` root folder:
   ```
   WA_ASKA_ACCESS_TOKEN=EAARxlZCzigB4BQ... (valid)
   WA_ASKA_PHONE_NUMBER_ID=932203566642397
   WA_ASKA_VERIFY_TOKEN=aska_bot_verify_token_123
   WA_ASKA_GDRIVE_FOLDER_ID=1-T2tJyG99o7... (valid)
   WA_ASKA_GEMINI_API_KEY=AIzaSyD1QV_pL2... (valid)
   ```

3. **Google Drive Credentials** - Sudah ada:
   - `credentials/credentials.json` ✅
   - `credentials/token.json` ✅

4. **Dependencies** - Terinstall di venv root

### ❌ Masalah yang Ditemukan

#### 1. **Server Tidak Berjalan**
- Bot log menunjukkan error: `nohup: uvicorn: No such file or directory`
- Server pernah dijalankan tapi tidak bisa start karena module error
- Port 8000 tidak ada proses yang running

#### 2. **File .env.example Tidak Ada**
- README.md menyebut `cp .env.example .env` di step 2
- Tapi file `.env.example` tidak ditemukan di folder `wa-aska/`
- Ini bisa membingungkan untuk setup di server baru

#### 3. **Webhook Belum Dikonfigurasi**
- `ngrok.log` kosong → ngrok belum pernah dijalankan
- Meta Developer Console webhook belum di-setup
- Tanpa webhook, WA tidak bisa mengirim pesan ke bot

#### 4. **Token WhatsApp Mungkin Expired**
- Access token di `.env` adalah temporary token (valid 24 jam)
- Belum ada konfigurasi untuk permanent token
- Perlu regenerate atau gunakan System User Token (permanent)

---

## 🔍 Alur Kerja WhatsApp Bot (Yang Seharusnya)

```
┌─────────────────────────────────────────────────────────────┐
│                     WhatsApp User                           │
│                                                              │
│  1. User mengirim PDF ke grup                               │
│  2. User/lain reply: "simpan ke drive"                      │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              WhatsApp Cloud API (Meta)                       │
│                                                              │
│  - Menerima pesan dari user                                 │
│  - Kirim webhook POST ke server kita                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼ (melalui Internet)
┌─────────────────────────────────────────────────────────────┐
│                    Ngrok Tunnel                              │
│                                                              │
│  https://abc123.ngrok.io --> localhost:8000                 │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              FastAPI Server (uvicorn)                        │
│              Running on port 8000                            │
│                                                              │
│  POST /webhook                                               │
│  ├─ Extract message dari payload                            │
│  ├─ Cek apakah ada command "simpan"                         │
│  ├─ Jika ada PDF di cache → process                         │
│  └─ Background task:                                         │
│      ├─ Download PDF dari WA                                │
│      ├─ Extract text/analyze dengan Gemini AI               │
│      ├─ Upload ke Google Drive                              │
│      └─ Kirim reply ke user dengan link                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Solusi Step-by-Step

### STEP 1: Buat File .env.example

Buat template untuk referensi:

```bash
cd /Users/ainunfajar/BOT_TELE/ai-agent-sekolah/wa-aska
cat > .env.example << 'EOF'
# WhatsApp Cloud API Configuration
WA_ASKA_ACCESS_TOKEN=your_whatsapp_access_token_here
WA_ASKA_PHONE_NUMBER_ID=your_phone_number_id_here
WA_ASKA_VERIFY_TOKEN=aska_bot_verify_token_123

# Google Drive Configuration
WA_ASKA_GDRIVE_FOLDER_ID=your_google_drive_folder_id_here

# Gemini AI Configuration
WA_ASKA_GEMINI_API_KEY=your_gemini_api_key_here

# Server Configuration (Optional)
WA_ASKA_DEBUG=true
WA_ASKA_PORT=8000
WA_ASKA_HOST=0.0.0.0
EOF
```

### STEP 2: Jalankan Server

```bash
# Terminal 1: Jalankan FastAPI Server
cd /Users/ainunfajar/BOT_TELE/ai-agent-sekolah
source venv/bin/activate
cd wa-aska
uvicorn app.main:app --reload --port 8000
```

Server harus menampilkan:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
🚀 Starting ASKA WhatsApp Bot...
📱 WhatsApp Phone Number ID: 932203566642397
```

### STEP 3: Test Server Lokal

Buka terminal baru dan jalankan test script:

```bash
# Terminal 2: Test webhook
cd /Users/ainunfajar/BOT_TELE/ai-agent-sekolah
source venv/bin/activate
cd wa-aska
python3 test_webhook_manual.py
```

Expected output:
```
=== Testing Health Check ===
Status Code: 200
✅ Health check PASSED

=== Testing Webhook Verification ===
Status Code: 200
✅ Webhook verification PASSED

Total: 3/3 tests passed
```

### STEP 4: Setup Ngrok (untuk Koneksi dengan WhatsApp)

```bash
# Terminal 3: Jalankan ngrok
ngrok http 8000
```

Copy URL HTTPS yang muncul (contoh: `https://abc123.ngrok-free.app`)

### STEP 5: Konfigurasi Webhook di Meta Developer

1. Buka: https://developers.facebook.com/
2. Pilih App WhatsApp Anda
3. WhatsApp → Configuration → Webhook
4. Edit webhook:
   - **Callback URL**: `https://abc123.ngrok-free.app/webhook`
   - **Verify Token**: `aska_bot_verify_token_123` (sama dengan di .env)
   - Klik **Verify and Save**
5. Subscribe to **messages** event

### STEP 6: Generate Permanent Access Token

Access token temporary hanya valid 24 jam. Untuk production, gunakan System User Token:

1. Di Meta Developer Console → Settings → Business Settings
2. System Users → Add New System User
3. Assign WhatsApp assets
4. Generate token dengan permission: `whatsapp_business_messaging`
5. Copy permanent token
6. Update di `.env`: `WA_ASKA_ACCESS_TOKEN=permanent_token_here`

### STEP 7: Test dari WhatsApp Real

1. Kirim pesan test dari nomor yang terdaftar di Meta (test number)
2. Kirim text: "Halo ASKA"
3. Cek log di terminal FastAPI, seharusnya muncul:
   ```
   INFO: Received webhook payload: {...}
   INFO: Processing 1 messages
   ```

4. Upload PDF dan reply dengan: "simpan ke drive"
5. Bot akan:
   - Download PDF
   - Analyze dengan Gemini AI
   - Upload ke Google Drive
   - Reply dengan link

---

## 🧪 Testing Checklist

- [ ] Server bisa start tanpa error
- [ ] Health check endpoint (`/health`) response 200
- [ ] Webhook verification endpoint response challenge string
- [ ] Ngrok tunnel aktif dan public URL tersedia
- [ ] Meta webhook verification berhasil (hijau)
- [ ] Test message dari WA masuk ke log server
- [ ] Bot bisa reply ke test message
- [ ] Upload PDF dan command "simpan" berfungsi
- [ ] File terupload ke Google Drive
- [ ] Bot reply dengan link Google Drive

---

## 🚨 Troubleshooting

### Error: "ModuleNotFoundError: No module named 'app'"

**Solusi**: Jalankan dengan uvicorn dari folder `wa-aska/`:
```bash
cd wa-aska
uvicorn app.main:app --reload --port 8000
```

Jangan jalankan langsung `python app/main.py` karena path module akan salah.

### Error: "Access token expired"

**Solusi**: Generate permanent token dari System User (lihat STEP 6)

### Error: "Media URL expired"

WhatsApp media URL hanya valid beberapa menit. Bot harus download segera.
File sudah handle ini di `file_handler.py` dengan background task.

### Webhook tidak menerima pesan

**Checklist**:
1. Ngrok masih running? URL tidak berubah?
2. Webhook di Meta masih subscribe ke `messages`?
3. Nomor pengirim adalah test user di Meta?
4. Server FastAPI masih running?

### Error: "No messages in cache"

User harus kirim PDF dulu, BARU orang lain reply "simpan ke drive".
Bot cache PDF selama 24 jam. Jika lebih dari 24 jam, upload ulang PDF.

---

## 📝 Catatan Penting

1. **Callback URL Ngrok**: URL ngrok berubah setiap restart gratis. Untuk production gunakan ngrok paid atau deploy ke VPS dengan domain tetap.

2. **Test Phone Numbers**: Di mode development, hanya nomor yang didaftarkan di Meta bisa kirim pesan. Untuk production, app harus di-approve oleh Meta.

3. **Rate Limits**:
   - WhatsApp: 1000 messages/day (free tier)
   - Gemini AI: 15 requests/minute, 1500/day (free tier)

4. **Security**: Token di `.env` jangan di-commit ke git (sudah ada di `.gitignore`)

---

## ✅ Next Steps

Setelah semua test passed:

1. **Deploy to Production**:
   - Setup server VPS (seperti Rumahweb)
   - Install nginx + SSL
   - Setup systemd service untuk auto-restart
   - Gunakan domain tetap (bukan ngrok)

2. **Monitoring**:
   - Setup logging ke file dengan rotation
   - Add Sentry/error tracking
   - Monitor disk space untuk uploaded files

3. **Features Enhancement**:
   - Support image upload (selain PDF)
   - Support multiple file formats
   - Custom folder mapping per user/grup
   - Notification ke admin jika ada error

---

## 🆘 Butuh Bantuan?

Jika masih ada masalah, cek:
1. Log server FastAPI untuk error detail
2. Log ngrok untuk koneksi issue
3. Meta Developer Console → Webhooks → Recent Deliveries (untuk debug payload)
