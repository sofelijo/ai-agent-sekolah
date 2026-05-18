# 🚀 FINAL SETUP GUIDE - WhatsApp Bot ASKA

## ✅ Status: SEMUA KOMPONEN SIAP!

**Test Results**: ✅✅✅ All Passed (3/3)
- ✅ Public Health Check
- ✅ Webhook Verification 
- ✅ Server Status

---

## 📊 Informasi Penting

### Ngrok Public URL
```
https://pseudohistoric-unkenned-pearly.ngrok-free.dev
```

### Webhook Configuration
```
Callback URL: https://pseudohistoric-unkenned-pearly.ngrok-free.dev/webhook
Verify Token: aska_bot_verify_token_123
```

---

## 🎯 LANGKAH TERAKHIR (5 Menit)

### Setup Webhook di Meta Developer Console

1. **Buka**: https://developers.facebook.com/apps

2. **Pilih WhatsApp App** Anda

3. **Navigate**: Sidebar kiri → **WhatsApp** → **Configuration**

4. **Scroll ke Webhook**, klik **Edit**

5. **Isi form**:
   - **Callback URL**: 
     ```
     https://pseudohistoric-unkenned-pearly.ngrok-free.dev/webhook
     ```
   - **Verify token**: 
     ```
     aska_bot_verify_token_123
     ```

6. **Klik "Verify and Save"**
   - Expected: ✅ Green checkmark "Webhook verified successfully"

7. **Subscribe to events**:
   - Centang ☑️ **messages**

---

## 🧪 TEST SETELAH SETUP

### Step 1: Kirim Text Message

Dari **nomor WhatsApp yang terdaftar sebagai Test User**:

**Kirim**: `Halo ASKA`

**Monitor logs**:
```bash
cd /Users/ainunfajar/BOT_TELE/ai-agent-sekolah/wa-aska
bash wait_for_message.sh
```

**Expected log**:
```
INFO: Received webhook payload: {...}
INFO: Processing 1 messages
```

### Step 2: Upload PDF & Save

**A. Upload PDF**:
- Kirim file PDF apa saja ke chat

**Expected log**:
```
INFO: Cached document message: wamid.xxxxx
```

**B. Kirim Command**:
- Reply ke PDF dengan: `simpan ke drive`

**Expected log**:
```
INFO: Detected save command, processing in background
INFO: Processing save command: wamid.xxxxx
INFO: Successfully processed command: uploaded to [Folder]
```

**Expected WhatsApp Reply**:
```
✅ File berhasil disimpan ke Google Drive!

📄 Nama: filename.pdf
📁 Folder: [Predicted Folder] 🟢
💡 Alasan: [AI reasoning]
📝 Dianalisis dari: nama file / isi PDF
🔗 Link: https://drive.google.com/file/d/xxxxx
```

**Validation**:
- Buka Google Drive: https://drive.google.com/drive/folders/1-T2tJyG99o7-lf6mGXfLFIXfETHJV2H8
- File harus ada di folder yang diprediksi

---

## 🛠️ Helper Scripts

### Monitor Messages (Real-time)
```bash
bash wait_for_message.sh
```
Menampilkan log real-time saat message masuk

### Check Status
```bash
bash monitor.sh
```
Menampilkan status server, ngrok, dan recent logs

### Validate Setup
```bash
bash test_after_setup.sh
```
Test semua komponen (public URL, webhook, server)

---

## 🔍 Troubleshooting

### ❌ Webhook Verification Failed di Meta

**Cek**:
1. Ngrok masih running? → `bash monitor.sh`
2. URL benar? Copy ulang dari monitor
3. Token exact: `aska_bot_verify_token_123`

**Manual Test**:
```bash
curl "https://pseudohistoric-unkenned-pearly.ngrok-free.dev/webhook?hub.mode=subscribe&hub.verify_token=aska_bot_verify_token_123&hub.challenge=test"
# Expected: test
```

### ❌ Message Tidak Masuk

**Cek**:
1. Nomor sudah ditambahkan sebagai Test User di Meta?
2. Webhook masih subscribe ke `messages`?
3. Lihat Meta → Configuration → Webhooks → Recent Deliveries

### ❌ PDF Upload Gagal

**Error**: "Media expired"

**Solusi**: Upload PDF baru, kirim command dalam 2-3 menit

---

## 📚 Dokumentasi Lengkap

| File | Purpose |
|------|---------|
| `WEBHOOK_SETUP.md` | Detailed webhook setup guide |
| `QUICKSTART.md` | Quick start guide |
| `DIAGNOSIS.md` | Technical analysis |
| `README.md` | Complete documentation |

---

## ⚠️ Important Notes

### Ngrok Free Tier
> URL berubah setiap restart. Jika ngrok restart, update webhook di Meta dengan URL baru.

### Access Token
> Temporary token valid 24 jam. Untuk production, gunakan System User Token (permanent).

### Test Users Only
> Development mode: hanya Test Users di Meta yang bisa kirim pesan.

---

## 📞 What's Running

**Server**: Port 8000 ✅
```bash
# Check di browser: http://127.0.0.1:8000/health
```

**Ngrok**: Tunnel active ✅
```bash
# Web UI: http://127.0.0.1:4040
```

**Webhook**: Ready to receive ✅
```bash
# URL: https://pseudohistoric-unkenned-pearly.ngrok-free.dev/webhook
```

---

## ✅ Success Checklist

Setup selesai jika:

- [x] Server running tanpa error
- [x] Ngrok tunnel active  
- [x] Public URL accessible
- [x] Webhook endpoint verified
- [ ] **Meta webhook configured** ← YOU ARE HERE
- [ ] Test message received from WA
- [ ] PDF upload & save works
- [ ] File uploaded to Google Drive

**Current**: 4/8 automated, 4/8 requires manual testing

---

## 🚀 After Testing Success

Jika semua test passed, pertimbangkan:

1. **Monitor Usage**: Track message count, error rate
2. **Production Deployment**: VPS + domain permanent
3. **Meta Approval**: Request production access

**Good luck!** 🎉
