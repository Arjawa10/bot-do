"""/list command handler — list all droplets."""

from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from bot.middleware.auth import authorized_only
from bot.services.digitalocean import DigitalOceanClient, DigitalOceanError
from bot.config import settings
from bot.utils.formatters import format_droplet_list
from bot.utils.logger import setup_logger

logger = setup_logger("handler.list")


@authorized_only
async def list_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /list command."""
    msg = await update.effective_message.reply_text(  # type: ignore[union-attr]
        "⏳ Mengambil daftar droplet...", parse_mode="HTML"
    )
    try:
        client = DigitalOceanClient(settings.DO_API_TOKEN)
        try:
            droplets = await client.list_droplets()
        finally:
            await client.close()

        text = format_droplet_list(droplets)
        await msg.edit_text(text, parse_mode="HTML")
    except DigitalOceanError as exc:
        await msg.edit_text(exc.message, parse_mode="HTML")
    except Exception as exc:
        logger.exception("Error in /list")
        await msg.edit_text(f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML")


def get_handlers() -> list[CommandHandler]:
    return [CommandHandler("list", list_command)]
