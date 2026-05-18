# 🎯 INSTRUKSI SETUP WEBHOOK - Meta Developer Console

## ✅ Status Saat Ini

**Server**: ✅ Running di port 8000  
**Ngrok**: ✅ Active  
**Public URL**: ✅ `https://pseudohistoric-unkenned-pearly.ngrok-free.dev`  
**Webhook Endpoint**: ✅ Ready

---

## 📋 Langkah Setup Webhook (5 Menit)

### STEP 1: Buka Meta Developer Console

1. Buka browser dan navigasi ke: **https://developers.facebook.com/apps**
2. Login dengan akun Facebook Anda
3. Pilih **WhatsApp App** yang sudah dibuat

### STEP 2: Navigate ke Webhook Configuration

1. Di sidebar kiri, klik **WhatsApp**
2. Klik **Configuration**
3. Scroll ke section **Webhook**

### STEP 3: Edit Webhook Settings

1. Klik tombol **Edit** di section Webhook
2. Isi form dengan data berikut:

   **Callback URL**:
   ```
   https://pseudohistoric-unkenned-pearly.ngrok-free.dev/webhook
   ```
   
   **Verify Token**:
   ```
   aska_bot_verify_token_123
   ```

3. Klik **Verify and Save**

### STEP 4: Verifikasi Berhasil

**Expected Result**: 
- ✅ Status webhook berubah menjadi **hijau** (green checkmark)
- ✅ Muncul message: **"Webhook verified successfully"**
- ✅ URL tetap ada di field Callback URL

**Jika Failed**:
- Pastikan ngrok masih running (cek terminal)
- Pastikan copy URL dengan benar (HTTPS, bukan HTTP)
- Pastikan ada `/webhook` di akhir URL
- Verify token harus exact match: `aska_bot_verify_token_123`

### STEP 5: Subscribe to Messages Event

Masih di halaman yang sama:

1. Di section **Webhook fields**, cari field **messages**
2. **Centang checkbox** di sebelah **messages**
3. Pastikan ada checkmark ✅ di field messages

### STEP 6: Validasi di Meta Console

1. Scroll ke bawah ke section **Webhooks**
2. Klik **See Recent Deliveries** (atau **View Webhook Logs**)
3. Saat ini masih kosong (belum ada message)

---

## ✅ Checklist Setup

Setelah setup, pastikan:

- [ ] Webhook status: **Active/Verified** (hijau)
- [ ] Callback URL: `https://pseudohistoric-unkenned-pearly.ngrok-free.dev/webhook`
- [ ] Verify Token: `aska_bot_verify_token_123`
- [ ] Subscribed events: **messages** ✅

---

## 🧪 Testing Setelah Setup

### Test 1: Kirim Text Message

1. Dari **nomor WhatsApp yang terdaftar sebagai Test User** di Meta
2. Kirim message: **"Halo ASKA"**
3. Cek di terminal server, harus muncul log:
   ```
   INFO: Received webhook payload: {...}
   INFO: Processing 1 messages
   ```

### Test 2: Check Meta Webhook Logs

1. Kembali ke Meta Developer Console
2. WhatsApp → Configuration → Webhooks → **See Recent Deliveries**
3. Harus ada entry baru dengan:
   - Method: POST
   - Status: 200
   - Timestamp: baru saja

---

## 🔍 Troubleshooting

### ❌ "Webhook verification failed"

**Cek**:
1. Ngrok masih running? Buka: http://127.0.0.1:4040 (ngrok web interface)
2. URL benar? Copy ulang dari output ngrok
3. Token benar? Harus: `aska_bot_verify_token_123`

**Test Manual**:
```bash
curl "https://pseudohistoric-unkenned-pearly.ngrok-free.dev/webhook?hub.mode=subscribe&hub.verify_token=aska_bot_verify_token_123&hub.challenge=test123"
```
Expected output: `test123`

### ❌ "Message tidak masuk"

**Cek**:
1. Nomor pengirim sudah ditambahkan sebagai **Test User** di Meta?
   - Meta Developer → App → Roles → Test Users
2. Webhook masih subscribe ke **messages**?
3. Ngrok tidak restart? (free tier URL berubah setiap restart)

### ❌ Need to Add Test User

Jika nomor belum ditambahkan:

1. Meta Developer Console → App Settings
2. **Roles** → **Test Users** (atau **Testers**)
3. Klik **Add Test User**
4. Masukkan nomor WhatsApp (format: +628123456789)
5. Save

---

## 📞 Support

Jika ada issue:
- Cek ngrok web interface: http://127.0.0.1:4040
- Cek server logs di terminal
- Cek Meta webhook Recent Deliveries untuk error detail

---

**Next**: Setelah webhook verified, lanjut test kirim message dari WhatsApp!
