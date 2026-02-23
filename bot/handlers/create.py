"""/create command handler — create a new droplet with step-by-step flow."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.middleware.auth import authorized_only
from bot.services.digitalocean import DigitalOceanClient, DigitalOceanError
from bot.storage.api_keys import get_token
from bot.utils.formatters import format_droplet_created
from bot.utils.logger import setup_logger

logger = setup_logger("handler.create")

NAME, REGION, SIZE, IMAGE = range(4)


@authorized_only
async def create_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 0: Ask for droplet name."""
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "🚀 <b>Membuat Droplet Baru</b>\n\n"
        "📝 Masukkan nama untuk droplet baru:",
        parse_mode="HTML",
    )
    return NAME


@authorized_only
async def name_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 1: Receive name, show region choices."""
    name = update.effective_message.text.strip()  # type: ignore[union-attr]
    context.user_data["create_name"] = name  # type: ignore[index]

    msg = await update.effective_message.reply_text(  # type: ignore[union-attr]
        "⏳ Mengambil daftar region...", parse_mode="HTML"
    )

    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_token(user_id) or ""
    client = DigitalOceanClient(token)
    try:
        regions = await client.list_regions()
    except DigitalOceanError as exc:
        await msg.edit_text(exc.message, parse_mode="HTML")
        return ConversationHandler.END
    finally:
        await client.close()

    if not regions:
        await msg.edit_text("❌ Tidak ada region tersedia.", parse_mode="HTML")
        return ConversationHandler.END

    # Show 2 buttons per row
    keyboard: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for r in regions:
        btn = InlineKeyboardButton(
            f"{r['slug']} — {r['name']}",
            callback_data=f"cr_reg_{r['slug']}",
        )
        row.append(btn)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await msg.edit_text(
        f"📛 Nama: <b>{name}</b>\n\n🌍 Pilih region:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return REGION


@authorized_only
async def region_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 2: Receive region, show size choices."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    region = query.data.replace("cr_reg_", "")  # type: ignore[union-attr]
    context.user_data["create_region"] = region  # type: ignore[index]

    await query.edit_message_text(  # type: ignore[union-attr]
        "⏳ Mengambil daftar size...", parse_mode="HTML"
    )

    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_token(user_id) or ""
    client = DigitalOceanClient(token)
    try:
        sizes = await client.list_sizes()
    except DigitalOceanError as exc:
        await query.edit_message_text(exc.message, parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END
    finally:
        await client.close()

    # Filter sizes available in the chosen region and limit display
    sizes = [
        s for s in sizes if region in s.get("regions", [])
    ][:20]

    if not sizes:
        await query.edit_message_text(  # type: ignore[union-attr]
            "❌ Tidak ada size tersedia untuk region ini.", parse_mode="HTML"
        )
        return ConversationHandler.END

    keyboard = [
        [
            InlineKeyboardButton(
                f"{s['slug']} — ${s.get('price_monthly', '?')}/mo",
                callback_data=f"cr_size_{s['slug']}",
            )
        ]
        for s in sizes
    ]

    name = context.user_data.get("create_name", "?")  # type: ignore[union-attr]
    await query.edit_message_text(  # type: ignore[union-attr]
        f"📛 Nama: <b>{name}</b>\n"
        f"🌍 Region: <b>{region}</b>\n\n"
        f"💻 Pilih size:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return SIZE


@authorized_only
async def size_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 3: Receive size, show image (OS) choices."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    size = query.data.replace("cr_size_", "")  # type: ignore[union-attr]
    context.user_data["create_size"] = size  # type: ignore[index]

    await query.edit_message_text(  # type: ignore[union-attr]
        "⏳ Mengambil daftar image/OS...", parse_mode="HTML"
    )

    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_token(user_id) or ""
    client = DigitalOceanClient(token)
    try:
        images = await client.list_images("distribution")
    except DigitalOceanError as exc:
        await query.edit_message_text(exc.message, parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END
    finally:
        await client.close()

    if not images:
        await query.edit_message_text(  # type: ignore[union-attr]
            "❌ Tidak ada image tersedia.", parse_mode="HTML"
        )
        return ConversationHandler.END

    keyboard = [
        [
            InlineKeyboardButton(
                f"{img.get('distribution', '?')} {img.get('name', '?')}",
                callback_data=f"cr_img_{img['slug']}",
            )
        ]
        for img in images
        if img.get("slug")
    ][:20]

    name = context.user_data.get("create_name", "?")  # type: ignore[union-attr]
    region = context.user_data.get("create_region", "?")  # type: ignore[union-attr]
    await query.edit_message_text(  # type: ignore[union-attr]
        f"📛 Nama: <b>{name}</b>\n"
        f"🌍 Region: <b>{region}</b>\n"
        f"💻 Size: <b>{size}</b>\n\n"
        f"🖼️ Pilih image/OS:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return IMAGE


@authorized_only
async def image_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 4: Receive image, create the droplet."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    image = query.data.replace("cr_img_", "")  # type: ignore[union-attr]

    name = context.user_data.get("create_name", "droplet")  # type: ignore[union-attr]
    region = context.user_data.get("create_region", "nyc1")  # type: ignore[union-attr]
    size = context.user_data.get("create_size", "s-1vcpu-1gb")  # type: ignore[union-attr]

    await query.edit_message_text(  # type: ignore[union-attr]
        f"⏳ Membuat droplet <b>{name}</b>...\n\n"
        f"🌍 Region: {region}\n"
        f"💻 Size: {size}\n"
        f"🖼️ Image: {image}",
        parse_mode="HTML",
    )

    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_token(user_id) or ""
    client = DigitalOceanClient(token)
    try:
        droplet = await client.create_droplet(
            name=name, region=region, size=size, image=image
        )
        logger.info(
            "Created droplet name=%s id=%s region=%s size=%s image=%s",
            name,
            droplet.get("id"),
            region,
            size,
            image,
        )
        await query.edit_message_text(  # type: ignore[union-attr]
            format_droplet_created(droplet), parse_mode="HTML"
        )
    except DigitalOceanError as exc:
        await query.edit_message_text(exc.message, parse_mode="HTML")  # type: ignore[union-attr]
    except Exception as exc:
        logger.exception("Error creating droplet")
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
            entry_points=[CommandHandler("create", create_command)],
            states={
                NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, name_received)
                ],
                REGION: [
                    CallbackQueryHandler(region_selected, pattern=r"^cr_reg_.+$")
                ],
                SIZE: [
                    CallbackQueryHandler(size_selected, pattern=r"^cr_size_.+$")
                ],
                IMAGE: [
                    CallbackQueryHandler(image_selected, pattern=r"^cr_img_.+$")
                ],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    ]
