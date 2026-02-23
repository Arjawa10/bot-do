"""/create command handler — create a new droplet with step-by-step flow.

Flow:
  1. /create         → ask droplet name
  2. name received   → ask region (from API — all available)
  3. region selected → fetch sizes available IN that region, show grouped by category
  4. size selected   → ask image/OS
  5. image selected  → create droplet

NOTE: CPU/GPU distinction is done by labeling each size by its category.
The DO API does not expose account-level restrictions (e.g. AMD-only access),
so we show everything the region reports as available. If a size is locked for
your account, DO will return an error at creation time.
"""

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

# ── States ────────────────────────────────────────────────────────────────────
NAME, REGION, SIZE, IMAGE = range(4)

_MAX_SIZES  = 30
_MAX_IMAGES = 20


# ── Size categorization ───────────────────────────────────────────────────────

def _size_category(slug: str) -> str:
    """Return an emoji + label for a size slug."""
    s = slug.lower()
    if s.startswith("gpu-"):
        return "🎮 GPU"
    if s.startswith("gd-"):
        return "🔵 General Purpose Dedicated"
    if s.startswith("g-"):
        is_amd = s.endswith("-amd") or "-amd-" in s
        return "🔵 General Purpose AMD" if is_amd else "🔵 General Purpose"
    if s.startswith("c2-"):
        return "⚡ CPU-Opt 2x"
    if s.startswith("c-"):
        return "⚡ CPU-Optimized"
    if s.startswith("m3-"):
        return "🟣 Memory-Opt 3x"
    if s.startswith("m-"):
        return "🟣 Memory-Optimized"
    if s.startswith("so1_"):
        return "🟠 Storage-Opt 1.5x"
    if s.startswith("so-"):
        return "🟠 Storage-Optimized"
    if s.startswith("s-"):
        is_amd = s.endswith("-amd") or "-amd-" in s
        return "🟢 Basic AMD" if is_amd else "🟢 Basic"
    return "💻 Other"


def _size_label(s: dict) -> str:
    slug   = s.get("slug", "?")
    vcpus  = s.get("vcpus", "?")
    mem_gb = round(s.get("memory", 0) / 1024, 1)
    price  = s.get("price_monthly", "?")
    disk   = s.get("disk", "?")
    cat    = _size_category(slug)
    if slug.startswith("gpu-"):
        return f"{cat} | {slug} | {vcpus}vCPU {mem_gb}GB | ${price}/mo"
    return f"{cat} | {vcpus}vCPU {mem_gb}GB {disk}GB disk | ${price}/mo"


def _get_available_sizes(
    all_sizes: list[dict],
    region_slug: str,
    region_sizes: list[str],       # slugs the region says are available
) -> list[dict]:
    """
    Return sizes that are:
    1. In the region's own 'sizes' list  (primary source of truth)
    2. Have available=True in the global sizes response
    Sorted by category then price.
    """
    region_set = set(region_sizes)
    result = [
        s for s in all_sizes
        if s.get("slug") in region_set and s.get("available", False)
    ]
    # Secondary fallback: use size.regions if region.sizes is empty
    if not result:
        result = [
            s for s in all_sizes
            if region_slug in s.get("regions", []) and s.get("available", False)
        ]
    result.sort(key=lambda s: (
        0 if s.get("slug", "").startswith("gpu-") else 1,  # GPU first
        float(s.get("price_monthly", 0)),
    ))
    return result[:_MAX_SIZES]


# ── Step 0: /create ───────────────────────────────────────────────────────────

@authorized_only
async def create_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "🚀 <b>Buat Droplet Baru</b>\n\n"
        "📝 <b>Langkah 1/4:</b> Masukkan nama untuk droplet:\n\n"
        "Ketik /cancel untuk membatalkan.",
        parse_mode="HTML",
    )
    return NAME


# ── Step 1: Receive name, show regions ───────────────────────────────────────

async def name_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    name = (update.effective_message.text or "").strip()  # type: ignore[union-attr]
    if not name:
        await update.effective_message.reply_text("⚠️ Nama tidak boleh kosong. Coba lagi:")  # type: ignore[union-attr]
        return NAME

    context.user_data["create_name"] = name  # type: ignore[index]

    msg = await update.effective_message.reply_text("⏳ Mengambil daftar region...", parse_mode="HTML")  # type: ignore[union-attr]

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

    # Store region metadata for later (to get region.sizes list)
    context.user_data["create_regions_meta"] = {r["slug"]: r for r in regions}  # type: ignore[index]

    keyboard: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for r in regions:
        row.append(InlineKeyboardButton(
            f"{r['slug']} — {r['name']}",
            callback_data=f"cr_reg_{r['slug']}",
        ))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await msg.edit_text(
        f"📛 Nama: <b>{name}</b>\n\n"
        "🌍 <b>Langkah 2/4:</b> Pilih region:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return REGION


# ── Step 2: Region selected, show ALL available sizes ────────────────────────

@authorized_only
async def region_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    region = query.data.replace("cr_reg_", "")  # type: ignore[union-attr]
    context.user_data["create_region"] = region  # type: ignore[index]

    await query.edit_message_text("⏳ Mengambil daftar size...", parse_mode="HTML")  # type: ignore[union-attr]

    user_id = update.effective_user.id  # type: ignore[union-attr]
    token   = get_token(user_id) or ""
    client  = DigitalOceanClient(token)
    try:
        all_sizes = await client.list_sizes()
    except DigitalOceanError as exc:
        await query.edit_message_text(exc.message, parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END
    finally:
        await client.close()

    # Get region.sizes (the slugs this region says are available)
    regions_meta: dict = context.user_data.get("create_regions_meta", {})  # type: ignore[union-attr]
    region_obj   = regions_meta.get(region, {})
    region_sizes = region_obj.get("sizes", [])

    sizes = _get_available_sizes(all_sizes, region, region_sizes)

    if not sizes:
        await query.edit_message_text(  # type: ignore[union-attr]
            f"❌ Tidak ada size tersedia di region <b>{region}</b>.",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(_size_label(s), callback_data=f"cr_size_{s['slug']}")]
        for s in sizes
    ]

    name = context.user_data.get("create_name", "?")  # type: ignore[union-attr]
    await query.edit_message_text(  # type: ignore[union-attr]
        f"📛 Nama: <b>{name}</b>\n"
        f"🌍 Region: <b>{region}</b>\n\n"
        f"💻 <b>Langkah 3/4:</b> Pilih size ({len(sizes)} tersedia):\n"
        f"<i>Kategori: 🟢 Basic · ⚡ CPU-Opt · 🔵 Gen Purpose · 🟣 Mem-Opt · 🎮 GPU</i>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return SIZE


# ── Step 3: Size selected, show images ───────────────────────────────────────

@authorized_only
async def size_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    size = query.data.replace("cr_size_", "")  # type: ignore[union-attr]
    context.user_data["create_size"] = size  # type: ignore[index]

    await query.edit_message_text("⏳ Mengambil daftar image/OS...", parse_mode="HTML")  # type: ignore[union-attr]

    user_id = update.effective_user.id  # type: ignore[union-attr]
    token   = get_token(user_id) or ""
    client  = DigitalOceanClient(token)
    try:
        images = await client.list_images("distribution")
        # For GPU sizes, also include application images (CUDA, ML frameworks etc.)
        if size.startswith("gpu-"):
            try:
                app_images = await client.list_images("application")
                images = images + app_images
            except Exception:
                pass
    except DigitalOceanError as exc:
        await query.edit_message_text(exc.message, parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END
    finally:
        await client.close()

    images = [img for img in images if img.get("slug")][:_MAX_IMAGES]

    if not images:
        await query.edit_message_text("❌ Tidak ada image tersedia.", parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(
            f"{img.get('distribution', '?')} {img.get('name', '?')}",
            callback_data=f"cr_img_{img['slug']}",
        )]
        for img in images
    ]

    name   = context.user_data.get("create_name", "?")  # type: ignore[union-attr]
    region = context.user_data.get("create_region", "?")  # type: ignore[union-attr]
    await query.edit_message_text(  # type: ignore[union-attr]
        f"📛 Nama: <b>{name}</b>\n"
        f"🌍 Region: <b>{region}</b>\n"
        f"💻 Size: <b>{size}</b>\n\n"
        f"🖼️ <b>Langkah 4/4:</b> Pilih image/OS:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return IMAGE


# ── Step 4: Image selected → create ──────────────────────────────────────────

@authorized_only
async def image_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query  = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    image  = query.data.replace("cr_img_", "")  # type: ignore[union-attr]
    name   = context.user_data.get("create_name", "droplet")    # type: ignore[union-attr]
    region = context.user_data.get("create_region", "nyc1")     # type: ignore[union-attr]
    size   = context.user_data.get("create_size", "s-1vcpu-1gb")  # type: ignore[union-attr]

    await query.edit_message_text(  # type: ignore[union-attr]
        f"⏳ Membuat droplet <b>{name}</b>...\n\n"
        f"🌍 Region: {region} | 💻 Size: {size}\n"
        f"🖼️ Image: {image}",
        parse_mode="HTML",
    )

    user_id = update.effective_user.id  # type: ignore[union-attr]
    token   = get_token(user_id) or ""
    client  = DigitalOceanClient(token)
    try:
        droplet = await client.create_droplet(name=name, region=region, size=size, image=image)
        logger.info("Created droplet name=%s id=%s region=%s size=%s", name, droplet.get("id"), region, size)
        await query.edit_message_text(format_droplet_created(droplet), parse_mode="HTML")  # type: ignore[union-attr]
    except DigitalOceanError as exc:
        await query.edit_message_text(  # type: ignore[union-attr]
            f"{exc.message}\n\n"
            "💡 <i>Jika ukuran ini terkunci untuk akun kamu, pilih size lain dan coba lagi.</i>",
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.exception("Error creating droplet")
        await query.edit_message_text(f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML")  # type: ignore[union-attr]
    finally:
        await client.close()

    return ConversationHandler.END


# ── Cancel ────────────────────────────────────────────────────────────────────

@authorized_only
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text("❌ Dibatalkan.", parse_mode="HTML")  # type: ignore[union-attr]
    return ConversationHandler.END


# ── Registration ──────────────────────────────────────────────────────────────

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
