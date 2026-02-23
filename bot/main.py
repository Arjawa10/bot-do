"""Entry point — build and run the Telegram bot."""

from __future__ import annotations

import logging

from telegram import BotCommand, Update
from telegram.ext import Application, ContextTypes

from bot.config import settings
from bot.handlers import start, list as list_handler, info, power, create, destroy, upgrade, setkey
from bot.storage.api_keys import init_storage
from bot.utils.logger import setup_logger

logger = setup_logger("main")

# Commands shown in Telegram's "/" menu autocomplete
BOT_COMMANDS = [
    BotCommand("setkey",    "Set API key DigitalOcean kamu"),
    BotCommand("mykey",     "Cek API key yang tersimpan"),
    BotCommand("deletekey", "Hapus API key tersimpan"),
    BotCommand("list",      "Daftar semua droplet"),
    BotCommand("info",      "Detail droplet tertentu"),
    BotCommand("create",    "Buat droplet baru"),
    BotCommand("destroy",   "Hapus droplet"),
    BotCommand("upgrade",   "Resize (upgrade) droplet"),
    BotCommand("poweron",   "Nyalakan droplet"),
    BotCommand("poweroff",  "Matikan droplet"),
    BotCommand("reboot",    "Reboot droplet"),
    BotCommand("help",      "Tampilkan bantuan"),
]


async def post_init(application: Application) -> None:
    """Called after the Application has been initialized — register commands."""
    await application.bot.set_my_commands(BOT_COMMANDS)
    logger.info("Bot commands registered with Telegram (%d commands).", len(BOT_COMMANDS))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler — logs exceptions and notifies the user."""
    logger.error("Exception while handling an update:", exc_info=context.error)

    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ Terjadi kesalahan internal. Silakan coba lagi.",
                parse_mode="HTML",
            )
        except Exception:
            pass


def main() -> None:
    """Build the bot application and start polling."""
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    app = (
        Application.builder()
        .token(settings.TG_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Register handlers — order matters for ConversationHandlers
    for module in (start, list_handler, info, power, create, destroy, upgrade, setkey):
        for handler in module.get_handlers():
            app.add_handler(handler)

    # Global error handler
    app.add_error_handler(error_handler)

    logger.info("Bot started. Allowed users: %s", settings.ALLOWED_USER_IDS)
    init_storage()
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
