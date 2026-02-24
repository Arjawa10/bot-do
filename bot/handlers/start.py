"""/start and /help command handlers."""

from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from bot.middleware.auth import authorized_only

HELP_TEXT = (
    "🤖 <b>DigitalOcean &amp; Paperspace Manager</b>\n\n"

    "━━━ ☁️ <b>DIGITALOCEAN</b> ━━━\n\n"

    "🔑 <b>API Key</b>\n"
    "/setkey — Tambah API key DO\n"
    "/mykey — Lihat semua key tersimpan\n"
    "/usekey — Ganti key aktif\n"
    "/deletekey — Hapus key tersimpan\n\n"

    "💰 <b>Billing</b>\n"
    "/balance — Cek saldo akun DO\n"
    "/redeem — Redeem promo/kredit code\n\n"

    "🖥️ <b>Droplets</b>\n"
    "/list — Daftar semua droplet\n"
    "/info — Detail droplet\n"
    "/create — Buat droplet baru\n"
    "/destroy — Hapus droplet\n"
    "/upgrade — Resize droplet\n"
    "/poweron — Nyalakan droplet\n"
    "/poweroff — Matikan droplet\n"
    "/reboot — Reboot droplet\n\n"

    "━━━ 🟣 <b>PAPERSPACE</b> ━━━\n\n"

    "🔑 <b>API Key</b>\n"
    "/pskey — Tambah API key Paperspace\n"
    "/mypsk — Lihat semua key tersimpan\n"
    "/usepsk — Ganti key aktif\n"
    "/deletepsk — Hapus key tersimpan\n\n"

    "📂 <b>Projects</b>\n"
    "/projects — Daftar semua project\n"
    "/newproject — Buat project baru\n"
    "/delproject — Hapus project\n\n"

    "📓 <b>Notebooks</b>\n"
    "/notebooks — Daftar semua notebook\n"
    "/newnotebook — Buat notebook baru\n"
    "/stopnotebook — Hentikan notebook\n"
    "/delnotebook — Hapus notebook\n\n"

    "❓ /help — Tampilkan bantuan ini\n"
)



@authorized_only
async def start_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /start command."""
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"👋 <b>Selamat datang!</b>\n\n{HELP_TEXT}",
        parse_mode="HTML",
    )


@authorized_only
async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /help command."""
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        HELP_TEXT, parse_mode="HTML"
    )


def get_handlers() -> list[CommandHandler]:
    """Return handlers for registration."""
    return [
        CommandHandler("start", start_command),
        CommandHandler("help", help_command),
    ]
