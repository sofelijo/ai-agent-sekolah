# 🚀 Quick Start Guide - ASKA WhatsApp Bot

Panduan cepat untuk menjalankan dan test WhatsApp Bot ASKA.

---

## ⚡ Quick Test (5 Menit)

### 1. Jalankan Server

```bash
cd /Users/ainunfajar/BOT_TELE/ai-agent-sekolah/wa-aska
bash start.sh
```

**Expected output:**
```
✅ Configuration OK
🚀 Starting FastAPI server on port 8000...
INFO: Uvicorn running on http://127.0.0.1:8000
🚀 Starting ASKA WhatsApp Bot...
📱 WhatsApp Phone Number ID: 932203566642397
```

> ℹ️ Jika ada error "ModuleNotFoundError", pastikan Anda menjalankan dari folder `wa-aska/`

### 2. Test di Browser

Buka di browser: http://127.0.0.1:8000/health

**Expected response:**
```json
{
  "status": "healthy",
  "cache_size": 0,
  "debug_mode": true
}
```

### 3. Test Webhook Verification

Di terminal baru, jalankan:

```bash
cd /Users/ainunfajar/BOT_TELE/ai-agent-sekolah
source venv/bin/activate
cd wa-aska
python3 test_webhook_manual.py
```

**Expected output:**
```
✅ Health check PASSED
✅ Webhook verification PASSED
✅ Webhook message endpoint PASSED
Total: 3/3 tests passed
```

---

## 🌐 Test dengan WhatsApp (Live)

### Prerequisite

- [ ] Server lokal sudah running (step 1)
- [ ] Ngrok sudah installed (https://ngrok.com/download)
- [ ] Access token WhatsApp masih valid (cek di Meta Developer Console)

### 4. Jalankan Ngrok

Di terminal baru (jangan tutup server):

```bash
cd /Users/ainunfajar/BOT_TELE/ai-agent-sekolah/wa-aska
ngrok http 8000
```

**Copy URL HTTPS yang muncul**, contoh:
```
Forwarding  https://1234-abc-def.ngrok-free.app -> http://localhost:8000
```

### 5. Konfigurasi Webhook di Meta

1. Buka: https://developers.facebook.com/apps
2. Pilih WhatsApp app Anda
3. Sidebar kiri: **WhatsApp** → **Configuration**
4. Scroll ke **Webhook**
5. Klik **Edit**:
   - **Callback URL**: `https://1234-abc-def.ngrok-free.app/webhook`
   - **Verify token**: `aska_bot_verify_token_123`
   - Klik **Verify and Save**

**Expected**: Status "Webhook verified successfully" dengan checkmark hijau ✅

6. Subscribe to event: **messages** (centang checkbox)

### 6. Test Kirim Pesan

**Via WhatsApp:**

1. Kirim pesan dari nomor yang terdaftar sebagai Test User di Meta
2. Kirim text: **"Halo ASKA"**
3. Lihat log di terminal server, seharusnya muncul:
   ```
   INFO: Received webhook payload: {...}
   INFO: Processing 1 messages
   ```

**Via Curl (alternative):**

```bash
curl -X POST http://127.0.0.1:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "object": "whatsapp_business_account",
    "entry": [{
      "changes": [{
        "value": {
          "messages": [{
            "from": "628123456789",
            "id": "test123",
            "type": "text",
            "text": {"body": "halo"}
          }]
        }
      }]
    }]
  }'
```

Expected: `{"status":"ok"}`

---

## 📎 Test Upload PDF (Full Flow)

### 7. Test Upload & Save Command

1. **Upload PDF**:
   - Kirim file PDF ke chat WhatsApp (dari test number)
   - Bot akan simpan di cache selama 24 jam

2. **Kirim Command**:
   - Reply ke PDF dengan text: **"simpan ke drive"**
   - Atau kirim: `/save`, `/simpan`, `save to drive`

3. **Expected Response**:
   ```
   ✅ File berhasil disimpan ke Google Drive!
   
   📄 Nama: nama_file.pdf
   📁 Folder: Folder Yang Diprediksi 🟢
   💡 Alasan: [penjelasan AI]
   📝 Dianalisis dari: nama file / isi PDF
   🔗 Link: https://drive.google.com/file/d/xxx
   ```

---

## 🔍 Troubleshooting Common Issues

### ❌ Server tidak start

**Error**: `Module not found`

**Solusi**:
```bash
cd /Users/ainunfajar/BOT_TELE/ai-agent-sekolah
source venv/bin/activate
pip install -r wa-aska/requirements.txt
```

### ❌ Webhook verification failed

**Error**: "Verification failed" di Meta

**Cek**:
1. Ngrok masih running?
2. URL di Meta sama dengan ngrok URL?
3. Verify token di .env sama dengan di Meta (`aska_bot_verify_token_123`)?

**Debug**:
```bash
# Test langsung
curl -X GET "https://your-ngrok-url.ngrok-free.app/webhook?hub.mode=subscribe&hub.verify_token=aska_bot_verify_token_123&hub.challenge=test123"

# Expected: test123
```

### ❌ Pesan tidak masuk

**Error**: Kirim pesan tapi tidak ada log di server

**Cek**:
1. Nomor pengirim sudah terdaftar sebagai Test User di Meta?
2. Webhook masih subscribe ke `messages` event?
3. Ngrok URL tidak berubah? (free tier berubah setiap restart)
4. Server masih running?

**Debug di Meta**:
- WhatsApp → Configuration → Webhooks → **See Recent Deliveries**
- Cek apakah ada request masuk dan status codenya

### ❌ Access token expired

**Error**: 401 Unauthorized saat bot reply

**Solusi**:
1. Buka Meta Developer Console
2. WhatsApp → API Setup
3. Generate **temporary token** baru (valid 24 jam)
4. Atau buat **System User Token** (permanent):
   - Settings → Business Settings → System Users
   - Add New → Assign WhatsApp assets
   - Generate token
5. Update di `.env`: `WA_ASKA_ACCESS_TOKEN=new_token`
6. Restart server: `bash start.sh`

### ❌ Google Drive upload failed

**Error**: "Credentials not found"

**Solusi**:
```bash
cd /Users/ainunfajar/BOT_TELE/ai-agent-sekolah/wa-aska

# Pastikan file ada
ls -la credentials/

# Generate token ulang
python3 -c "from app.clients.gdrive_client import gdrive_client; print(gdrive_client.service)"

# Browser akan buka untuk login Google
```

### ❌ Gemini AI error

**Error**: "Rate limit exceeded"

**Cause**: Free tier limit 15 requests/menit

**Solusi**: Tunggu 1 menit, lalu coba lagi

---

## 📊 Monitoring

### Live Logs

```bash
# Lihat log server real-time
tail -f bot.log

# Lihat hanya error
grep ERROR bot.log

# Count messages processed hari ini
grep "Processing save command" bot.log | wc -l
```

### Health Check

```bash
# Check server status
curl http://127.0.0.1:8000/health | python3 -m json.tool

# Check cache size
curl http://127.0.0.1:8000/health | grep cache_size
```

### Test Endpoints

```bash
# Test root
curl http://127.0.0.1:8000/

# Test webhook verification
curl "http://127.0.0.1:8000/webhook?hub.mode=subscribe&hub.verify_token=aska_bot_verify_token_123&hub.challenge=test"
```

---

## 🎯 Checklist Testing

Gunakan checklist ini untuk memastikan semua fitur berfungsi:

- [ ] Server bisa start tanpa error (`bash start.sh`)
- [ ] Health check endpoint return status healthy
- [ ] Webhook verification bisa dipanggil (GET /webhook)
- [ ] Test script passed all tests (`python3 test_webhook_manual.py`)
- [ ] Ngrok tunnel running dan dapat public URL
- [ ] Meta webhook verification berhasil (hijau dengan checkmark)
- [ ] Kirim text ke WA muncul di log server
- [ ] Upload PDF ke WA tersimpan di cache
- [ ] Command "simpan ke drive" diproses
- [ ] Bot reply dengan link Google Drive
- [ ] File muncul di Google Drive folder yang benar
- [ ] AI prediction folder name masuk akal
- [ ] Bot handle error dengan baik (misal file corrupt)

---

## 🆘 Masih Ada Masalah?

### Debug Mode

Edit `.env`, set:
```
WA_ASKA_DEBUG=true
```

Restart server. Log akan lebih detail.

### Check Logs Detail

```bash
# Server logs
cat bot.log

# Ngrok logs
cat ngrok.log

# Meta webhook logs
# Buka: https://developers.facebook.com/apps/YOUR_APP_ID/webhooks
```

### Get Help

File yang berisi info penting:
- `DIAGNOSIS.md` - Analisis lengkap masalah
- `README.md` - Dokumentasi lengkap setup
- `.env.example` - Template konfigurasi
- `test_webhook_manual.py` - Script test

---

## ✅ Next: Production Deployment

Jika semua test passed, lihat `DIAGNOSIS.md` section "Deploy to Production" untuk:
- Setup VPS
- Nginx + SSL
- Systemd service
- Domain permanent (tidak pakai ngrok)
- Monitoring & logging

Good luck! 🚀
