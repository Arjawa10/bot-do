"""/destroy command handler — delete a droplet with confirmation."""

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
from bot.utils.formatters import format_droplet_short
from bot.utils.logger import setup_logger

logger = setup_logger("handler.destroy")

SELECT_DROPLET, CONFIRM = range(2)


@authorized_only
async def destroy_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 1: Show list of droplets to destroy."""
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
        [
            InlineKeyboardButton(
                format_droplet_short(d),
                callback_data=f"dest_sel_{d['id']}",
            )
        ]
        for d in droplets
    ]
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "🗑️ <b>Hapus Droplet</b>\n\nPilih droplet yang ingin dihapus:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return SELECT_DROPLET


@authorized_only
async def droplet_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 2: Confirm deletion."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    droplet_id = int(query.data.replace("dest_sel_", ""))  # type: ignore[union-attr]
    context.user_data["destroy_droplet_id"] = droplet_id  # type: ignore[index]

    # Fetch name for display
    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_token(user_id) or ""
    client = DigitalOceanClient(token)
    try:
        droplet = await client.get_droplet(droplet_id)
        name = droplet.get("name", str(droplet_id))
    except DigitalOceanError:
        name = str(droplet_id)
    finally:
        await client.close()

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Ya, Hapus", callback_data="dest_confirm_yes"
                ),
                InlineKeyboardButton("❌ Batal", callback_data="dest_confirm_no"),
            ]
        ]
    )
    await query.edit_message_text(  # type: ignore[union-attr]
        f"⚠️ <b>PERINGATAN</b>\n\n"
        f"Anda akan menghapus droplet:\n"
        f"📛 <b>{name}</b> (ID: <code>{droplet_id}</code>)\n\n"
        f"⚡ Tindakan ini <b>TIDAK DAPAT</b> dibatalkan!\n\n"
        f"Yakin ingin melanjutkan?",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    return CONFIRM


@authorized_only
async def confirm_destroy(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 3: Execute or cancel deletion."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    if query.data == "dest_confirm_no":  # type: ignore[union-attr]
        await query.edit_message_text("❌ Penghapusan dibatalkan.", parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END

    droplet_id = context.user_data.get("destroy_droplet_id")  # type: ignore[union-attr]

    await query.edit_message_text(  # type: ignore[union-attr]
        f"⏳ Menghapus droplet <code>{droplet_id}</code>...", parse_mode="HTML"
    )

    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_token(user_id) or ""
    client = DigitalOceanClient(token)
    try:
        await client.destroy_droplet(droplet_id)
        logger.info("Destroyed droplet id=%s", droplet_id)
        await query.edit_message_text(  # type: ignore[union-attr]
            f"✅ Droplet <code>{droplet_id}</code> berhasil dihapus!",
            parse_mode="HTML",
        )
    except DigitalOceanError as exc:
        await query.edit_message_text(exc.message, parse_mode="HTML")  # type: ignore[union-attr]
    except Exception as exc:
        logger.exception("Error destroying droplet")
        await query.edit_message_text(  # type: ignore[union-attr]
            f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML"
        )
    finally:
        await client.close()

    return ConversationHandler.END


@authorized_only
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text("❌ Dibatalkan.", parse_mode="HTML")  # type: ignore[union-attr]
    return ConversationHandler.END


def get_handlers() -> list[ConversationHandler]:
    return [
        ConversationHandler(
            entry_points=[CommandHandler("destroy", destroy_command)],
            states={
                SELECT_DROPLET: [
                    CallbackQueryHandler(
                        droplet_selected, pattern=r"^dest_sel_\d+$"
                    )
                ],
                CONFIRM: [
                    CallbackQueryHandler(
                        confirm_destroy, pattern=r"^dest_confirm_(yes|no)$"
                    )
                ],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            per_message=False,
        )
    ]
