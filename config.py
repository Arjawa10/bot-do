import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Interval pengecekan GPU (dalam detik) — default 5 menit
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))

# URL DigitalOcean AMD GPU
GPU_PAGE_URL = "https://amd.digitalocean.com/gpus"
LOGIN_URL = "https://amd.digitalocean.com/login"

# Teks indikator GPU habis
OUT_OF_STOCK_TEXT = "We're out of GPU's right now."
