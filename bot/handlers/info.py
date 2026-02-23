"""/info command handler — show detailed droplet information."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
)

from bot.middleware.auth import authorized_only
from bot.services.digitalocean import DigitalOceanClient, DigitalOceanError
from bot.storage.api_keys import get_token
from bot.utils.formatters import format_droplet_detail, format_droplet_short
from bot.utils.logger import setup_logger

logger = setup_logger("handler.info")

SELECT_DROPLET = 0


@authorized_only
async def info_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle /info — show droplet list for selection."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_token(user_id)
    if not token:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "⚠️ API key DigitalOcean belum diset.\nGunakan /setkey untuk menyimpan API key kamu.",
            parse_mode="HTML",
        )
        return ConversationHandler.END
    client = DigitalOceanClient(token)
    try:
        droplets = await client.list_droplets()
    except DigitalOceanError as exc:
        await update.effective_message.reply_text(exc.message, parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END
    finally:
        await client.close()

    if not droplets:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "📭 Tidak ada droplet aktif.", parse_mode="HTML"
        )
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(format_droplet_short(d), callback_data=f"info_{d['id']}")]
        for d in droplets
    ]
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "🔍 <b>Pilih droplet untuk melihat detail:</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return SELECT_DROPLET


@authorized_only
async def droplet_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle droplet selection callback."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    droplet_id = int(query.data.replace("info_", ""))  # type: ignore[union-attr]

    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_token(user_id)
    if not token:
        await query.edit_message_text("⚠️ API key belum diset. Gunakan /setkey.", parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END
    client = DigitalOceanClient(token)
    try:
        droplet = await client.get_droplet(droplet_id)
    except DigitalOceanError as exc:
        await query.edit_message_text(exc.message, parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END
    finally:
        await client.close()

    await query.edit_message_text(  # type: ignore[union-attr]
        format_droplet_detail(droplet), parse_mode="HTML"
    )
    return ConversationHandler.END


@authorized_only
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "❌ Dibatalkan.", parse_mode="HTML"
    )
    return ConversationHandler.END


def get_handlers() -> list[ConversationHandler]:
    return [
        ConversationHandler(
            entry_points=[CommandHandler("info", info_command)],
            states={
                SELECT_DROPLET: [
                    CallbackQueryHandler(droplet_selected, pattern=r"^info_\d+$")
                ],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    ]
