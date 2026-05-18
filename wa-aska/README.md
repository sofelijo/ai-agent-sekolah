# ASKA WhatsApp Bot

Bot otomasi AI untuk menyimpan file PDF dari grup WhatsApp ke Google Drive dengan **prediksi folder otomatis menggunakan Gemini AI**.

## 🌟 Fitur

- **Integrasi WhatsApp Cloud API** (Meta Official)
- **Google Drive API** untuk upload file
- **AI Folder Prediction** menggunakan Gemini 1.5 Flash (gratis):
  - Level 1: Analisis nama file
  - Level 2: Membaca isi PDF jika nama file generic
  - Support PDF text-based dan scanned (image analysis)
- **Message Cache** dengan TTL 24 jam
- **Background Processing** untuk response cepat

---

## 📋 Tutorial Setup Lengkap

### STEP 1: Install Dependencies

Karena venv sudah ada di root folder, jalankan dari root:

```bash
# Dari root folder (ai-agent-sekolah)
source venv/bin/activate

# Install dependencies wa-aska
pip install -r wa-aska/requirements.txt
```

### STEP 2: Buat File .env

```bash
cd wa-aska
cp .env.example .env
```

### STEP 3: Dapatkan Gemini API Key (GRATIS)

1. Buka https://aistudio.google.com/
2. Login dengan Google Account
3. Klik **"Get API Key"** → **"Create API Key"**
4. Copy API Key
5. Paste ke `.env`:
   ```
   GEMINI_API_KEY=your_gemini_api_key_here
   ```

### STEP 4: Setup WhatsApp Cloud API

1. Buka https://developers.facebook.com/
2. Buat App baru → Pilih **"Business"**
3. Tambahkan produk **"WhatsApp"**
4. Di WhatsApp → API Setup:
   - Copy **Phone Number ID**
   - Copy **Access Token** (temporary, valid 24 jam)
5. Paste ke `.env`:
   ```
   WHATSAPP_ACCESS_TOKEN=your_access_token
   WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
   WHATSAPP_VERIFY_TOKEN=aska_verify_token_123  # Buat sendiri
   ```

### STEP 5: Setup Google Drive API

#### 5a. Buat Project di Google Cloud

1. Buka https://console.cloud.google.com/
2. Buat project baru atau pilih existing
3. Di menu, pilih **"APIs & Services"** → **"Enable APIs"**
4. Cari dan enable **"Google Drive API"**

#### 5b. Buat OAuth Credentials

1. Di **"APIs & Services"** → **"Credentials"**
2. Klik **"+ Create Credentials"** → **"OAuth client ID"**
3. Jika diminta, configure **OAuth consent screen** dulu:
   - User Type: External
   - App name: ASKA Bot
   - Email: isi email anda
   - Scopes: skip (lanjut)
   - Test users: tambahkan email anda
4. Kembali ke Credentials, buat **OAuth client ID**:
   - Application type: **Desktop app**
   - Name: ASKA Bot
5. Download file JSON
6. Rename menjadi `credentials.json`
7. Pindahkan ke `wa-aska/credentials/credentials.json`

#### 5c. Dapatkan Folder ID

1. Buka Google Drive
2. Buat atau pilih folder untuk menyimpan file
3. Buka folder tersebut
4. Copy ID dari URL: `https://drive.google.com/drive/folders/FOLDER_ID_DISINI`
5. Paste ke `.env`:
   ```
   GDRIVE_DEFAULT_FOLDER_ID=your_folder_id
   ```

#### 5d. Generate Token

```bash
# Dari folder wa-aska
cd /Users/ainunfajar/BOT_TELE/ai-agent-sekolah
source venv/bin/activate
cd wa-aska

python3 -c "from app.clients.gdrive_client import gdrive_client; print(gdrive_client.service)"
```

Browser akan terbuka untuk login Google. Setelah login, token akan disimpan otomatis.

### STEP 6: Jalankan Server

```bash
# Dari folder wa-aska
cd /Users/ainunfajar/BOT_TELE/ai-agent-sekolah
source venv/bin/activate
cd wa-aska

uvicorn app.main:app --reload --port 8000
```

### STEP 7: Setup Webhook (untuk Production)

1. Install ngrok: https://ngrok.com/download
2. Jalankan:
   ```bash
   ngrok http 8000
   ```
3. Copy URL https (misal: `https://abc123.ngrok.io`)
4. Di Meta Developer Console:
   - WhatsApp → Configuration → Webhook
   - Callback URL: `https://abc123.ngrok.io/webhook`
   - Verify Token: sama dengan di `.env`
   - Subscribe to: `messages`

---

## 📖 Cara Penggunaan

1. Tambahkan bot ke grup WhatsApp
2. User mengirim file PDF ke grup
3. User lain reply ke PDF tersebut dengan:
   - `simpan ke drive`
   - `save to drive`
   - `/save`
   - `/simpan`
4. Bot akan:
   - Download PDF dari WhatsApp
   - Analisis dengan AI untuk prediksi folder
   - Upload ke Google Drive
   - Kirim konfirmasi dengan link

### Contoh Konfirmasi

```
✅ File berhasil disimpan ke Google Drive!

📄 Nama: Invoice_PT_ABC_2024.pdf
📁 Folder: Keuangan/Invoice 🟢
💡 Alasan: Nama file mengandung "Invoice" yang cocok dengan folder Keuangan
📝 Dianalisis dari nama file
🔗 Link: https://drive.google.com/file/d/xxx
```

---

## 🏗️ Struktur Proyek

```
wa-aska/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI entry point
│   ├── config.py            # Environment configuration
│   ├── webhook.py           # Webhook handlers
│   ├── clients/
│   │   ├── whatsapp_client.py   # WhatsApp API client
│   │   ├── gdrive_client.py     # Google Drive client
│   │   └── gemini_client.py     # Gemini AI client
│   ├── services/
│   │   ├── message_cache.py     # Message caching
│   │   ├── message_parser.py    # Webhook parsing
│   │   ├── pdf_extractor.py     # PDF content extraction
│   │   ├── ai_folder_predictor.py  # AI prediction
│   │   └── file_handler.py      # Main orchestration
│   └── models/
│       └── schemas.py           # Pydantic models
├── credentials/             # Google OAuth (gitignored)
├── tests/
├── .env.example
├── .gitignore
└── requirements.txt
```

---

## ⚠️ Limitasi

### WhatsApp Cloud API
- **24-hour Window**: Bot hanya bisa reply dalam 24 jam
- **Media Expiry**: URL media bisa expired, download harus cepat
- **No Message Fetch**: Tidak bisa ambil pesan by ID → perlu cache

### Gemini Free Tier
- **15 RPM** (requests per minute)
- **1,500 requests/day**
- Sudah cukup untuk use case normal

---

## 🔧 Troubleshooting

### Error: "Credentials file not found"
- Pastikan `credentials.json` ada di `wa-aska/credentials/`

### Error: "Token refresh failed"
- Hapus `wa-aska/credentials/token.json` dan generate ulang

### Error: "Rate limit exceeded"
- Tunggu beberapa menit, Gemini free tier punya limit 15 request/menit

### Error: "Media expired"
- File sudah tidak bisa didownload, minta user upload ulang

---

## 📝 License

MIT License
