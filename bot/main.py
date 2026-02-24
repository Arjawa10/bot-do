"""Entry point — build and run the Telegram bot."""

from __future__ import annotations

import logging

from telegram import BotCommand, Update
from telegram.ext import Application, ContextTypes

from bot.config import settings
from bot.handlers import (
    start,
    list as list_handler,
    info,
    power,
    create,
    destroy,
    upgrade,
    setkey,
    billing,
    ps_setkey,
    ps_projects,
    ps_notebooks,
)
from bot.storage.api_keys import init_storage
from bot.utils.logger import setup_logger

logger = setup_logger("main")

# Commands shown in Telegram's "/" menu autocomplete
BOT_COMMANDS = [
    # ── DigitalOcean — API Keys ────────────────────────────────────────────
    BotCommand("setkey",         "DO: Tambah API key DigitalOcean"),
    BotCommand("mykey",          "DO: Lihat semua API key tersimpan"),
    BotCommand("usekey",         "DO: Ganti API key aktif"),
    BotCommand("deletekey",      "DO: Hapus API key tersimpan"),
    # ── DigitalOcean — Billing ────────────────────────────────────────────
    BotCommand("balance",        "DO: Cek saldo akun DigitalOcean"),
    BotCommand("redeem",         "DO: Redeem promo/kredit code"),
    # ── DigitalOcean — Droplets ───────────────────────────────────────────
    BotCommand("list",           "DO: Daftar semua droplet"),
    BotCommand("info",           "DO: Detail droplet tertentu"),
    BotCommand("create",         "DO: Buat droplet baru"),
    BotCommand("destroy",        "DO: Hapus droplet"),
    BotCommand("upgrade",        "DO: Resize (upgrade) droplet"),
    BotCommand("poweron",        "DO: Nyalakan droplet"),
    BotCommand("poweroff",       "DO: Matikan droplet"),
    BotCommand("reboot",         "DO: Reboot droplet"),
    # ── Paperspace — API Keys ─────────────────────────────────────────────
    BotCommand("pskey",          "PS: Tambah API key Paperspace"),
    BotCommand("mypsk",          "PS: Lihat semua Paperspace key"),
    BotCommand("usepsk",         "PS: Ganti Paperspace key aktif"),
    BotCommand("deletepsk",      "PS: Hapus Paperspace key"),
    # ── Paperspace — Projects ─────────────────────────────────────────────
    BotCommand("projects",       "PS: Daftar semua project"),
    BotCommand("newproject",     "PS: Buat project baru"),
    BotCommand("delproject",     "PS: Hapus project"),
    # ── Paperspace — Notebooks ────────────────────────────────────────────
    BotCommand("notebooks",      "PS: Daftar semua notebook"),
    BotCommand("newnotebook",    "PS: Buat notebook baru"),
    BotCommand("stopnotebook",   "PS: Hentikan notebook"),
    BotCommand("delnotebook",    "PS: Hapus notebook"),
    # ── General ───────────────────────────────────────────────────────────
    BotCommand("help",           "Tampilkan bantuan"),
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
    for module in (
        # DigitalOcean
        start, list_handler, info, power, create, destroy, upgrade, setkey, billing,
        # Paperspace
        ps_setkey, ps_projects, ps_notebooks,
    ):
        for handler in module.get_handlers():
            app.add_handler(handler)

    # Global error handler
    app.add_error_handler(error_handler)

    logger.info("Bot started. Allowed users: %s", settings.ALLOWED_USER_IDS)
    init_storage()
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
