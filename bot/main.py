"""Entry point — build and run the Telegram bot."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, ContextTypes

from bot.config import settings
from bot.handlers import start, list as list_handler, info, power, create, destroy, upgrade, setkey
from bot.storage.api_keys import init_storage
from bot.utils.logger import setup_logger

logger = setup_logger("main")


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

    app = Application.builder().token(settings.TG_BOT_TOKEN).build()

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
