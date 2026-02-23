"""/poweron, /poweroff, /reboot command handlers."""

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
from bot.config import settings
from bot.utils.formatters import format_droplet_short
from bot.utils.logger import setup_logger

logger = setup_logger("handler.power")

SELECT_DROPLET, CONFIRM = range(2)

_ACTION_META = {
    "power_on": {"emoji": "🟢", "label": "Power On", "verb": "menyalakan"},
    "power_off": {"emoji": "🔴", "label": "Power Off", "verb": "mematikan"},
    "reboot": {"emoji": "🔄", "label": "Reboot", "verb": "merestart"},
}


async def _start_power(
    update: Update, context: ContextTypes.DEFAULT_TYPE, action_type: str
) -> int:
    """Common entry point for all power commands."""
    context.user_data["power_action"] = action_type  # type: ignore[index]

    client = DigitalOceanClient(settings.DO_API_TOKEN)
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

    meta = _ACTION_META[action_type]
    keyboard = [
        [
            InlineKeyboardButton(
                format_droplet_short(d),
                callback_data=f"pwr_sel_{d['id']}",
            )
        ]
        for d in droplets
    ]
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"{meta['emoji']} <b>Pilih droplet untuk {meta['label']}:</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return SELECT_DROPLET


@authorized_only
async def poweron_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _start_power(update, context, "power_on")


@authorized_only
async def poweroff_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _start_power(update, context, "power_off")


@authorized_only
async def reboot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _start_power(update, context, "reboot")


@authorized_only
async def droplet_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle droplet selection — ask confirmation."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    droplet_id = int(query.data.replace("pwr_sel_", ""))  # type: ignore[union-attr]
    context.user_data["power_droplet_id"] = droplet_id  # type: ignore[index]

    action_type = context.user_data.get("power_action", "reboot")  # type: ignore[union-attr]
    meta = _ACTION_META[action_type]

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Ya, Lanjutkan", callback_data="pwr_confirm_yes"
                ),
                InlineKeyboardButton("❌ Batal", callback_data="pwr_confirm_no"),
            ]
        ]
    )
    await query.edit_message_text(  # type: ignore[union-attr]
        f"⚠️ Yakin ingin <b>{meta['verb']}</b> droplet ID <code>{droplet_id}</code>?",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    return CONFIRM


@authorized_only
async def confirm_action(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle confirmation callback."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    if query.data == "pwr_confirm_no":  # type: ignore[union-attr]
        await query.edit_message_text("❌ Dibatalkan.", parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END

    droplet_id = context.user_data.get("power_droplet_id")  # type: ignore[union-attr]
    action_type = context.user_data.get("power_action", "reboot")  # type: ignore[union-attr]
    meta = _ACTION_META[action_type]

    await query.edit_message_text(  # type: ignore[union-attr]
        f"⏳ Menjalankan {meta['label']}...", parse_mode="HTML"
    )

    client = DigitalOceanClient(settings.DO_API_TOKEN)
    try:
        action_map = {
            "power_on": client.power_on_droplet,
            "power_off": client.power_off_droplet,
            "reboot": client.reboot_droplet,
        }
        action = await action_map[action_type](droplet_id)
        logger.info(
            "Power action %s on droplet %s — action_id=%s",
            action_type,
            droplet_id,
            action.get("id"),
        )
        await query.edit_message_text(  # type: ignore[union-attr]
            f"✅ <b>{meta['label']}</b> berhasil dikirim ke droplet "
            f"<code>{droplet_id}</code>.\n\n"
            f"Action ID: <code>{action.get('id')}</code>\n"
            f"Status: {action.get('status', '?')}",
            parse_mode="HTML",
        )
    except DigitalOceanError as exc:
        await query.edit_message_text(exc.message, parse_mode="HTML")  # type: ignore[union-attr]
    except Exception as exc:
        logger.exception("Error in power action")
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
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("poweron", poweron_command),
            CommandHandler("poweroff", poweroff_command),
            CommandHandler("reboot", reboot_command),
        ],
        states={
            SELECT_DROPLET: [
                CallbackQueryHandler(droplet_selected, pattern=r"^pwr_sel_\d+$")
            ],
            CONFIRM: [
                CallbackQueryHandler(confirm_action, pattern=r"^pwr_confirm_(yes|no)$")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    return [conv]
