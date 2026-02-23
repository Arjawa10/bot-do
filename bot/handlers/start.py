"""/start and /help command handlers."""

from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from bot.middleware.auth import authorized_only

HELP_TEXT = (
    "🤖 <b>DigitalOcean Droplet Manager</b>\n\n"
    "Berikut daftar perintah yang tersedia:\n\n"
    "🔑 /setkey — Set API key DigitalOcean kamu\n"
    "🗝️ /mykey — Cek API key yang tersimpan\n"
    "🗑️ /deletekey — Hapus API key tersimpan\n\n"
    "📋 /list — Daftar semua droplet\n"
    "🔍 /info — Detail droplet tertentu\n"
    "🚀 /create — Buat droplet baru\n"
    "🗑️ /destroy — Hapus droplet\n"
    "⬆️ /upgrade — Resize (upgrade) droplet\n"
    "🟢 /poweron — Nyalakan droplet\n"
    "🔴 /poweroff — Matikan droplet\n"
    "🔄 /reboot — Reboot droplet\n"
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
