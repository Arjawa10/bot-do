"""/setkey, /mykey, /deletekey command handlers.

Conversation flow:
  /setkey  →  bot asks for token  →  user sends token  →  bot validates & saves
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.middleware.auth import authorized_only
from bot.storage.api_keys import delete_user_key, get_user_key, has_user_key, set_user_key
from bot.services.digitalocean import DigitalOceanClient, DigitalOceanError
from bot.utils.logger import setup_logger

logger = setup_logger("handler.setkey")

# ConversationHandler state
WAITING_FOR_TOKEN = 1


@authorized_only
async def setkey_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """/setkey — prompt user to send their DO API token."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    status = ""
    if has_user_key(user_id):
        status = "\n\n⚠️ Kamu sudah punya API key tersimpan. Token baru akan <b>menggantikan</b>-nya."

    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"🔑 <b>Set DigitalOcean API Key</b>{status}\n\n"
        "Silakan kirim API key DigitalOcean kamu sekarang.\n"
        "Kamu bisa mendapatkannya di: "
        "<a href='https://cloud.digitalocean.com/account/api/tokens'>cloud.digitalocean.com/account/api/tokens</a>\n\n"
        "Ketik /cancel untuk membatalkan.",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    return WAITING_FOR_TOKEN


async def receive_token(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Receive and validate the API token sent by the user."""
    token = (update.effective_message.text or "").strip()  # type: ignore[union-attr]
    user_id = update.effective_user.id  # type: ignore[union-attr]

    # Delete the user's message immediately for security
    try:
        await update.effective_message.delete()  # type: ignore[union-attr]
    except Exception:
        pass

    msg = await update.effective_message.reply_text(  # type: ignore[union-attr]
        "⏳ Memvalidasi API key ke DigitalOcean..."
    )

    # Validate token by calling the DO API
    try:
        client = DigitalOceanClient(token)
        try:
            await client.list_droplets()
        finally:
            await client.close()
    except DigitalOceanError as exc:
        await msg.edit_text(
            f"❌ <b>API key tidak valid</b>\n\n{exc.message}\n\n"
            "Kirim ulang token yang benar atau /cancel untuk membatalkan.",
            parse_mode="HTML",
        )
        return WAITING_FOR_TOKEN
    except Exception as exc:
        logger.exception("Unexpected error validating DO token")
        await msg.edit_text(
            f"❌ Terjadi kesalahan saat memvalidasi token: {exc}\n\n"
            "Coba lagi atau /cancel untuk membatalkan.",
            parse_mode="HTML",
        )
        return WAITING_FOR_TOKEN

    # Token valid — save it
    set_user_key(user_id, token)

    # Mask the token for display
    masked = token[:6] + "…" + token[-4:] if len(token) > 10 else "***"
    await msg.edit_text(
        f"✅ <b>API key berhasil disimpan!</b>\n\n"
        f"Token: <code>{masked}</code>\n\n"
        "Sekarang semua perintah bot akan menggunakan API key ini.\n"
        "Gunakan /deletekey untuk menghapusnya.",
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def cancel_setkey(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """/cancel — abort the setkey conversation."""
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "❎ Dibatalkan. API key tidak diubah.",
        parse_mode="HTML",
    )
    return ConversationHandler.END


@authorized_only
async def mykey_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/mykey — show whether the user has a saved key."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    key = get_user_key(user_id)
    if key:
        masked = key[:6] + "…" + key[-4:] if len(key) > 10 else "***"
        text = (
            f"🔑 <b>API Key Tersimpan</b>\n\n"
            f"Token: <code>{masked}</code>\n\n"
            "Gunakan /setkey untuk mengganti, atau /deletekey untuk menghapus."
        )
    else:
        text = (
            "❌ <b>Belum ada API key tersimpan</b>\n\n"
            "Gunakan /setkey untuk menyimpan API key DigitalOcean kamu."
        )
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        text, parse_mode="HTML"
    )


@authorized_only
async def deletekey_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/deletekey — remove the user's saved key."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    deleted = delete_user_key(user_id)
    if deleted:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "🗑️ API key kamu telah dihapus.\n\n"
            "Bot akan kembali menggunakan API key default dari konfigurasi server (jika ada).",
            parse_mode="HTML",
        )
    else:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "⚠️ Tidak ada API key tersimpan untuk dihapus.",
            parse_mode="HTML",
        )


def get_handlers() -> list:
    """Return handlers for registration."""
    conv = ConversationHandler(
        entry_points=[CommandHandler("setkey", setkey_start)],
        states={
            WAITING_FOR_TOKEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_token),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_setkey)],
        name="setkey_conversation",
    )
    return [
        conv,
        CommandHandler("mykey", mykey_command),
        CommandHandler("deletekey", deletekey_command),
    ]
