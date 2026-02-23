# 🤖 DigitalOcean Telegram Bot

Telegram Bot untuk mengelola **DigitalOcean Droplets** melalui DigitalOcean API v2.

## ✨ Fitur

| Perintah | Deskripsi |
|---|---|
| `/start` | Pesan selamat datang |
| `/help` | Daftar semua perintah |
| `/list` | Daftar semua droplet |
| `/info` | Detail lengkap droplet |
| `/create` | Buat droplet baru (step-by-step) |
| `/destroy` | Hapus droplet (dengan konfirmasi) |
| `/upgrade` | Resize/upgrade droplet |
| `/poweron` | Nyalakan droplet |
| `/poweroff` | Matikan droplet |
| `/reboot` | Reboot droplet |

## 📋 Prerequisites

- **Python 3.12+**
- **Telegram Bot Token** — dapatkan dari [@BotFather](https://t.me/BotFather)
- **DigitalOcean API Token** — buat di [DO Control Panel](https://cloud.digitalocean.com/account/api/tokens)
- **Telegram User ID** — dapatkan dari [@userinfobot](https://t.me/userinfobot)

## 🚀 Setup & Menjalankan

### Menggunakan Docker (Rekomendasi)

1. Clone repository:
   ```bash
   git clone <repo-url>
   cd do-telegram-bot
   ```

2. Buat file `.env` dari template:
   ```bash
   cp .env.example .env
   ```

3. Edit `.env` dan isi dengan token Anda:
   ```env
   TG_BOT_TOKEN=your_telegram_bot_token_here
   DO_API_TOKEN=your_digitalocean_api_token_here
   ALLOWED_USER_IDS=[123456789,987654321]
   ```

4. Build dan jalankan:
   ```bash
   docker-compose up -d --build
   ```

5. Lihat log:
   ```bash
   docker-compose logs -f
   ```

### Menjalankan Lokal

1. Buat virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   # atau
   venv\Scripts\activate     # Windows
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Buat file `.env` (lihat langkah di atas)

4. Jalankan bot:
   ```bash
   python -m bot.main
   ```

## 📖 Contoh Penggunaan

### Membuat Droplet Baru
1. Kirim `/create`
2. Masukkan nama droplet (misal: `web-server-01`)
3. Pilih region dari tombol yang muncul
4. Pilih size/plan dari tombol yang muncul
5. Pilih OS/image dari tombol yang muncul
6. Tunggu hingga droplet dibuat ✅

### Upgrade Droplet
1. Kirim `/upgrade`
2. Pilih droplet yang ingin di-upgrade
3. Pilih size baru yang lebih besar
4. Konfirmasi — bot akan otomatis: power off → resize → power on
5. Pantau progress melalui update pesan real-time

## 🔒 Security Notes

- **ALLOWED_USER_IDS** — Hanya user dengan ID yang terdaftar yang bisa menggunakan bot. Jangan biarkan kosong di production.
- **API Token** — Jangan pernah commit file `.env` ke repository. File ini sudah ada di `.gitignore`.
- **DigitalOcean Token** — Gunakan token dengan scope minimum yang diperlukan (read + write).
- **Destroy Confirmation** — Penghapusan droplet selalu memerlukan konfirmasi eksplisit.

## 🛠️ Tech Stack

- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) v21 (fully async)
- [httpx](https://www.python-httpx.org/) v0.27 (async HTTP client)
- [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) v2 (config management)
- Docker + Docker Compose

## 📁 Struktur Proyek

```
do-telegram-bot/
├── bot/
│   ├── main.py               # Entry point
│   ├── config.py              # Configuration (pydantic-settings)
│   ├── handlers/              # Command handlers
│   │   ├── start.py           # /start, /help
│   │   ├── create.py          # /create (ConversationHandler)
│   │   ├── destroy.py         # /destroy (ConversationHandler)
│   │   ├── upgrade.py         # /upgrade (ConversationHandler)
│   │   ├── list.py            # /list
│   │   ├── info.py            # /info
│   │   └── power.py           # /poweron, /poweroff, /reboot
│   ├── services/
│   │   └── digitalocean.py    # DigitalOcean API client (httpx async)
│   ├── middleware/
│   │   └── auth.py            # Authorization decorator
│   └── utils/
│       ├── logger.py          # Logging config
│       └── formatters.py      # Message formatting
├── .env.example
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
