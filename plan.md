# 🤖 Bot Telegram — AMD GPU DigitalOcean Availability Checker (Playwright + Python)

## 📌 Deskripsi Proyek
Buat sebuah aplikasi Python yang berfungsi sebagai bot Telegram untuk mengecek ketersediaan AMD GPU di DigitalOcean (amd.digitalocean.com). Sistem menggunakan Playwright untuk otomasi browser dan python-telegram-bot untuk komunikasi dengan user via Telegram.

---

## 🗂️ Struktur File yang Harus Dibuat

```
gpu_checker_bot/
├── main.py               # Entry point, menjalankan bot Telegram
├── browser_handler.py    # Semua logika Playwright (login, OTP, cek GPU)
├── config.py             # Konfigurasi (token bot, interval, dsb)
├── requirements.txt      # Semua dependency Python
└── .env.example          # Contoh file environment variable
```

---

## 📦 Dependencies (requirements.txt)

```
python-telegram-bot==20.7
playwright==1.41.0
python-dotenv==1.0.0
asyncio
```

---

## ⚙️ Konfigurasi (config.py)

Buat file `config.py` yang memuat:
- `TELEGRAM_BOT_TOKEN` — diambil dari environment variable `.env`
- `CHECK_INTERVAL` — interval pengecekan dalam detik, default: `300` (5 menit)
- `GPU_PAGE_URL` — `https://amd.digitalocean.com/gpus`
- `LOGIN_URL` — `https://amd.digitalocean.com/login`
- `OUT_OF_STOCK_TEXT` — `"We're out of GPU's right now."`

---

## 🌐 Logika Browser (browser_handler.py)

Buat class `BrowserHandler` dengan Playwright (async) yang memiliki method berikut:

### 1. `async start_browser()`
- Launch browser Chromium dengan `headless=False` (agar terlihat prosesnya)
- Simpan instance `browser` dan `page` sebagai attribute class
- Kembalikan pesan sukses

### 2. `async login(email: str, password: str) -> str`
- Buka URL `https://amd.digitalocean.com/login`
- Tunggu field email muncul, isi dengan parameter `email`
- Isi field password dengan parameter `password`
- Klik button login / submit
- Tunggu response: apakah muncul halaman OTP atau langsung berhasil login
- Jika muncul field OTP → kembalikan string `"OTP_REQUIRED"`
- Jika langsung berhasil → kembalikan string `"LOGIN_SUCCESS"`
- Jika gagal → kembalikan string `"LOGIN_FAILED: <pesan error>"`

### 3. `async submit_otp(otp_code: str) -> str`
- Isi field OTP di halaman yang sudah terbuka dengan `otp_code`
- Klik button submit OTP
- Tunggu navigasi berhasil
- Jika berhasil login → kembalikan `"LOGIN_SUCCESS"`
- Jika gagal → kembalikan `"OTP_FAILED: <pesan error>"`

### 4. `async check_gpu_availability() -> dict`
- Navigasi ke `https://amd.digitalocean.com/gpus` di tab yang **sama** (jangan buka tab baru)
- Tunggu halaman selesai load
- Cari dan klik button dengan teks **"Create a GPU Droplet"**
- Tunggu halaman baru/konten setelah klik button tersebut selesai load
- Cek apakah terdapat elemen yang mengandung teks `"We're out of GPU's right now."`
- Kembalikan dictionary:
  ```python
  {
      "available": True/False,        # True jika GPU tersedia, False jika tidak
      "message": "...",               # Pesan status
      "timestamp": "DD-MM-YYYY HH:MM:SS",  # Waktu pengecekan (WIB/lokal)
      "current_url": "..."            # URL saat pengecekan
  }
  ```

### 5. `async close_browser()`
- Tutup browser dan bersihkan semua resource

---

## 🤖 Bot Telegram (main.py)

Gunakan `python-telegram-bot` versi 20+ dengan `ApplicationBuilder` dan async handler.

### State Management (ConversationHandler)
Gunakan `ConversationHandler` dengan state berikut:
```
WAITING_EMAIL → WAITING_PASSWORD → WAITING_OTP → MONITORING
```

### Command & Handler yang Harus Ada:

#### `/start`
Kirim pesan sambutan dan instruksi penggunaan bot:
```
🤖 AMD GPU DigitalOcean Checker Bot

Perintah:
/login — Mulai proses login ke DigitalOcean
/stop_monitor — Hentikan monitoring GPU
/status — Cek status monitoring saat ini
/check_now — Lakukan pengecekan GPU sekarang (manual)
```

#### `/login` (memulai ConversationHandler)
1. Minta user untuk mengirimkan **email** DigitalOcean
2. Setelah email diterima, minta **password**
3. Jalankan `browser_handler.login(email, password)`
4. Jika return `"OTP_REQUIRED"` → minta user kirim kode OTP
5. Jika return `"LOGIN_SUCCESS"` → langsung mulai monitoring
6. Jika return `"LOGIN_FAILED"` → kirim pesan error, akhiri conversation

#### Handler OTP
1. Terima kode OTP dari user
2. Jalankan `browser_handler.submit_otp(otp_code)`
3. Jika `"LOGIN_SUCCESS"` → kirim konfirmasi dan **mulai monitoring otomatis**
4. Jika `"OTP_FAILED"` → kirim pesan error

#### Monitoring Loop (Background Job)
Gunakan `context.job_queue` dari `python-telegram-bot` untuk membuat **repeating job** dengan interval **300 detik (5 menit)**:

```python
async def monitor_gpu_job(context: ContextTypes.DEFAULT_TYPE):
    result = await browser_handler.check_gpu_availability()
    
    if result["available"]:
        message = (
            f"✅ [GPU TERSEDIA!]\n"
            f"🕐 {result['timestamp']}\n"
            f"🔗 {result['current_url']}\n"
            f"📝 {result['message']}\n\n"
            f"🚨 AMD GPU DigitalOcean TERSEDIA! Segera buka dan buat droplet!"
        )
    else:
        message = (
            f"❌ [GPU TIDAK TERSEDIA]\n"
            f"🕐 {result['timestamp']}\n"
            f"📝 {result['message']}\n"
            f"⏳ Pengecekan berikutnya dalam 5 menit..."
        )
    
    # Print ke console sebagai log
    print(f"[LOG] {result['timestamp']} | Available: {result['available']} | {result['message']}")
    
    # Kirim ke Telegram
    await context.bot.send_message(chat_id=context.job.chat_id, text=message)
```

#### `/stop_monitor`
- Hentikan semua job monitoring yang berjalan
- Tutup browser
- Kirim konfirmasi ke user

#### `/status`
Kirim status saat ini:
- Apakah monitoring sedang berjalan
- Waktu pengecekan terakhir
- Hasil pengecekan terakhir

#### `/check_now`
- Langsung jalankan `check_gpu_availability()` satu kali tanpa menunggu interval
- Kirim hasilnya ke Telegram

---

## 🔐 File .env.example

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
```

---

## 🚨 Error Handling & Ketentuan Penting

1. **Semua fungsi Playwright harus dibungkus try-except** — jika terjadi error, kirim pesan error ke Telegram dan print ke console
2. **Jika browser crash/timeout** — bot harus mengirim notifikasi ke user dan menghentikan monitoring dengan bersih
3. **Jangan simpan email/password di file apapun** — hanya simpan di memory (variable) selama session berlangsung
4. **Gunakan `WebDriverWait` equivalent di Playwright** yaitu `page.wait_for_selector()` dan `page.wait_for_load_state("networkidle")` untuk memastikan halaman benar-benar loaded sebelum melakukan aksi
5. **Selector untuk DigitalOcean** — gunakan kombinasi:
   - `page.get_by_text("We're out of GPU's right now.")` untuk mengecek ketersediaan GPU
   - `page.get_by_role("button", name="Create a GPU Droplet")` untuk tombol
   - Untuk field login gunakan `page.get_by_label("Email")` dan `page.get_by_label("Password")`
6. **Pastikan `job_queue` aktif** — saat membuat `ApplicationBuilder`, tambahkan `.job_queue(True)` agar fitur job scheduling aktif

---

## 📋 Alur Lengkap Sistem (Flow)

```
User kirim /login
    → Bot minta email
    → User kirim email
    → Bot minta password
    → User kirim password
    → [Playwright] Buka browser → Buka amd.digitalocean.com/login
    → [Playwright] Isi email & password → Submit
    → Jika muncul OTP:
        → Bot minta OTP ke user
        → User kirim OTP
        → [Playwright] Submit OTP
    → Login berhasil
    → Bot kirim "✅ Login berhasil! Monitoring dimulai..."
    → [Job Queue] Setiap 5 menit:
        → [Playwright] Buka https://amd.digitalocean.com/gpus
        → [Playwright] Klik "Create a GPU Droplet"
        → [Playwright] Cek teks "We're out of GPU's right now."
        → Print log ke console
        → Kirim hasil ke Telegram
```

---

## ✅ Checklist Output yang Diharapkan

- [ ] `requirements.txt` berisi semua dependency yang diperlukan
- [ ] `config.py` memuat semua konstanta konfigurasi
- [ ] `browser_handler.py` berisi class `BrowserHandler` dengan semua 5 method
- [ ] `main.py` berisi bot Telegram lengkap dengan semua command handler
- [ ] ConversationHandler berjalan dengan benar untuk alur login → OTP → monitoring
- [ ] Job queue berjalan setiap 5 menit dan mengirim log ke Telegram
- [ ] Error handling ada di setiap fungsi kritis
- [ ] Console print log setiap kali pengecekan dilakukan
- [ ] `.env.example` tersedia sebagai template konfigurasi