"""/upgrade command handler — resize a droplet with progress updates."""

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

logger = setup_logger("handler.upgrade")

SELECT_DROPLET, SELECT_SIZE, CONFIRM = range(3)


@authorized_only
async def upgrade_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 1: Show droplets to upgrade."""
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

    keyboard = [
        [
            InlineKeyboardButton(
                format_droplet_short(d),
                callback_data=f"upg_sel_{d['id']}",
            )
        ]
        for d in droplets
    ]
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "⬆️ <b>Upgrade (Resize) Droplet</b>\n\nPilih droplet yang ingin di-upgrade:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return SELECT_DROPLET


@authorized_only
async def droplet_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 2: Show available sizes larger than current."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    droplet_id = int(query.data.replace("upg_sel_", ""))  # type: ignore[union-attr]
    context.user_data["upgrade_droplet_id"] = droplet_id  # type: ignore[index]

    await query.edit_message_text("⏳ Mengambil info droplet dan size...", parse_mode="HTML")  # type: ignore[union-attr]

    client = DigitalOceanClient(settings.DO_API_TOKEN)
    try:
        droplet = await client.get_droplet(droplet_id)
        all_sizes = await client.list_sizes()
    except DigitalOceanError as exc:
        await query.edit_message_text(exc.message, parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END
    finally:
        await client.close()

    current_size = droplet.get("size", {})
    current_slug = droplet.get("size_slug", current_size.get("slug", "?"))
    current_disk = current_size.get("disk", 0)
    current_memory = current_size.get("memory", 0)
    current_vcpus = current_size.get("vcpus", 0)
    droplet_region = droplet.get("region", {}).get("slug", "")

    context.user_data["upgrade_droplet_name"] = droplet.get("name", str(droplet_id))  # type: ignore[index]
    context.user_data["upgrade_current_size"] = current_slug  # type: ignore[index]

    # Filter for bigger sizes in the same region
    bigger = [
        s
        for s in all_sizes
        if (
            s.get("disk", 0) >= current_disk
            and s.get("memory", 0) > current_memory
            and droplet_region in s.get("regions", [])
            and s.get("slug") != current_slug
        )
    ][:15]

    if not bigger:
        await query.edit_message_text(  # type: ignore[union-attr]
            "❌ Tidak ada size yang lebih besar tersedia untuk droplet ini.",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    keyboard = [
        [
            InlineKeyboardButton(
                f"{s['slug']} ({s.get('vcpus', '?')} vCPU / "
                f"{s.get('memory', 0) // 1024} GB) — "
                f"${s.get('price_monthly', '?')}/mo",
                callback_data=f"upg_size_{s['slug']}",
            )
        ]
        for s in bigger
    ]

    mem_gb = f"{current_memory // 1024}" if current_memory >= 1024 else str(current_memory)
    await query.edit_message_text(  # type: ignore[union-attr]
        f"📊 <b>Size saat ini:</b> {current_slug} "
        f"({current_vcpus} vCPU / {mem_gb} GB RAM)\n\n"
        f"⬆️ Pilih size baru:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return SELECT_SIZE


@authorized_only
async def size_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 3: Confirm upgrade with warning."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    new_size = query.data.replace("upg_size_", "")  # type: ignore[union-attr]
    context.user_data["upgrade_new_size"] = new_size  # type: ignore[index]

    droplet_name = context.user_data.get("upgrade_droplet_name", "?")  # type: ignore[union-attr]
    current_size = context.user_data.get("upgrade_current_size", "?")  # type: ignore[union-attr]

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Ya, Upgrade", callback_data="upg_confirm_yes"
                ),
                InlineKeyboardButton("❌ Batal", callback_data="upg_confirm_no"),
            ]
        ]
    )
    await query.edit_message_text(  # type: ignore[union-attr]
        f"⚠️ <b>Konfirmasi Upgrade</b>\n\n"
        f"📛 Droplet: <b>{droplet_name}</b>\n"
        f"📊 Size lama: <b>{current_size}</b>\n"
        f"📊 Size baru: <b>{new_size}</b>\n\n"
        f"⚡ <b>PERINGATAN:</b> Droplet akan <b>dimatikan sementara</b> "
        f"selama proses resize.\n\n"
        f"Lanjutkan?",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    return CONFIRM


@authorized_only
async def confirm_upgrade(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 4: Execute the full resize workflow with progress updates."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    if query.data == "upg_confirm_no":  # type: ignore[union-attr]
        await query.edit_message_text("❌ Upgrade dibatalkan.", parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END

    droplet_id = context.user_data.get("upgrade_droplet_id")  # type: ignore[union-attr]
    new_size = context.user_data.get("upgrade_new_size")  # type: ignore[union-attr]
    droplet_name = context.user_data.get("upgrade_droplet_name", "?")  # type: ignore[union-attr]

    async def update_progress(text: str) -> None:
        try:
            await query.edit_message_text(text, parse_mode="HTML")  # type: ignore[union-attr]
        except Exception:
            pass  # Ignore edit errors (e.g. message not modified)

    client = DigitalOceanClient(settings.DO_API_TOKEN)
    try:
        # Step 1: Power off
        await update_progress(
            f"🔄 <b>Upgrade {droplet_name}</b>\n\n"
            f"[1/5] 🔴 Mematikan droplet..."
        )
        action = await client.power_off_droplet(droplet_id)
        action_id = action.get("id")
        logger.info("Power off droplet %s — action %s", droplet_id, action_id)

        # Step 2: Poll power off
        await update_progress(
            f"🔄 <b>Upgrade {droplet_name}</b>\n\n"
            f"[2/5] ⏳ Menunggu droplet mati..."
        )
        await client.poll_action(action_id)

        # Step 3: Resize
        await update_progress(
            f"🔄 <b>Upgrade {droplet_name}</b>\n\n"
            f"[3/5] ⬆️ Melakukan resize ke <b>{new_size}</b>..."
        )
        action = await client.resize_droplet(droplet_id, new_size, disk=True)
        action_id = action.get("id")
        logger.info("Resize droplet %s to %s — action %s", droplet_id, new_size, action_id)

        # Step 4: Poll resize
        await update_progress(
            f"🔄 <b>Upgrade {droplet_name}</b>\n\n"
            f"[4/5] ⏳ Menunggu resize selesai..."
        )
        await client.poll_action(action_id)

        # Step 5: Power on
        await update_progress(
            f"🔄 <b>Upgrade {droplet_name}</b>\n\n"
            f"[5/5] 🟢 Menyalakan droplet..."
        )
        action = await client.power_on_droplet(droplet_id)
        logger.info("Power on droplet %s — action %s", droplet_id, action.get("id"))

        # Done
        await update_progress(
            f"✅ <b>Upgrade Berhasil!</b>\n\n"
            f"📛 Droplet: <b>{droplet_name}</b>\n"
            f"🆔 ID: <code>{droplet_id}</code>\n"
            f"📊 Size baru: <b>{new_size}</b>\n\n"
            f"Droplet sedang dinyalakan. Gunakan /info untuk cek status."
        )
    except DigitalOceanError as exc:
        await update_progress(
            f"❌ <b>Upgrade Gagal</b>\n\n"
            f"Droplet: {droplet_name}\n"
            f"Error: {exc.message}"
        )
    except Exception as exc:
        logger.exception("Error in upgrade flow")
        await update_progress(f"❌ Terjadi kesalahan: {exc}")
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
            entry_points=[CommandHandler("upgrade", upgrade_command)],
            states={
                SELECT_DROPLET: [
                    CallbackQueryHandler(
                        droplet_selected, pattern=r"^upg_sel_\d+$"
                    )
                ],
                SELECT_SIZE: [
                    CallbackQueryHandler(
                        size_selected, pattern=r"^upg_size_.+$"
                    )
                ],
                CONFIRM: [
                    CallbackQueryHandler(
                        confirm_upgrade, pattern=r"^upg_confirm_(yes|no)$"
                    )
                ],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    ]
