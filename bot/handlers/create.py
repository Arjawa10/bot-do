"""/create command handler — create a new droplet with step-by-step flow.

Flow:
  1. /create         → ask droplet name
  2. name received   → ask region
  3. region selected → show size CATEGORIES found in region
  4. category picked → show sizes in that category
  5. size selected   → ask image/OS
  6. image selected  → create droplet

IMPORTANT: The DO API does **not** expose account-level size restrictions.
For example, an account with only AMD access will still see Intel sizes
listed as 'available'. The only way to truly know is to attempt creation.
If creation fails, we show a clear "size not available for your account" hint.
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
NAME, REGION, CATEGORY, SIZE, IMAGE = range(5)

_MAX_IMAGES = 20

# ── Size categories ───────────────────────────────────────────────────────────
# Order in _CATEGORIES matters — it is the display order.
_CATEGORIES = [
    ("gpu-",  "🎮 GPU Droplet"),
    ("s-",    "🟢 Basic (Shared CPU)"),
    ("c2-",   "⚡ CPU-Optimized 2x"),
    ("c-",    "⚡ CPU-Optimized"),
    ("g-",    "🔵 General Purpose"),
    ("gd-",   "🔵 General Purpose Dedicated"),
    ("m3-",   "🟣 Memory-Optimized 3x"),
    ("m-",    "🟣 Memory-Optimized"),
    ("so1_5-","🟠 Storage-Optimized 1.5x"),
    ("so-",   "🟠 Storage-Optimized"),
]

# Fallback
_DEFAULT_CAT_LABEL = "💻 Other"


def _categorize_slug(slug: str) -> tuple[str, str]:
    """Return (prefix, label) for a size slug."""
    s = slug.lower()
    for prefix, label in _CATEGORIES:
        if s.startswith(prefix):
            # Detect AMD variant
            if "-amd" in s and not prefix.startswith("gpu"):
                label = f"{label} AMD"
            return prefix, label
    return "other", _DEFAULT_CAT_LABEL


def _size_label(s: dict) -> str:
    slug   = s.get("slug", "?")
    vcpus  = s.get("vcpus", "?")
    mem_gb = round(s.get("memory", 0) / 1024, 1)
    price  = s.get("price_monthly", "?")
    disk   = s.get("disk", "?")
    if slug.startswith("gpu-"):
        return f"{slug} | {vcpus}vCPU {mem_gb}GB | ${price}/mo"
    return f"{slug} | {vcpus}vCPU {mem_gb}GB {disk}GB | ${price}/mo"


def _get_available_sizes(all_sizes: list[dict], region_slug: str, region_sizes: list[str]) -> list[dict]:
    """Return sizes available in the region, sorted by price."""
    region_set = set(region_sizes)
    result = [s for s in all_sizes if s.get("slug") in region_set and s.get("available", False)]
    if not result:
        result = [s for s in all_sizes if region_slug in s.get("regions", []) and s.get("available", False)]
    result.sort(key=lambda s: float(s.get("price_monthly", 0)))
    return result


def _build_categories(sizes: list[dict]) -> dict[str, list[dict]]:
    """Group sizes by category. Returns {cat_key: [sizes]}."""
    cats: dict[str, list[dict]] = {}
    for s in sizes:
        slug = s.get("slug", "")
        prefix, _label = _categorize_slug(slug)
        # Use prefix as key but also detect AMD/non-AMD separately
        cat_key = prefix
        if "-amd" in slug.lower() and not prefix.startswith("gpu"):
            cat_key = f"{prefix}amd"
        cats.setdefault(cat_key, []).append(s)
    return cats


def _cat_display_name(cat_key: str, sizes: list[dict]) -> str:
    """Return display name for a category key."""
    if sizes:
        _, label = _categorize_slug(sizes[0].get("slug", ""))
        return f"{label} ({len(sizes)})"
    return cat_key


# ── Step 0: /create ───────────────────────────────────────────────────────────

@authorized_only
async def create_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "🚀 <b>Buat Droplet Baru</b>\n\n"
        "📝 <b>Langkah 1/5:</b> Masukkan nama untuk droplet:\n\n"
        "Ketik /cancel untuk membatalkan.",
        parse_mode="HTML",
    )
    return NAME


# ── Step 1: Receive name, show regions ───────────────────────────────────────

async def name_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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

    context.user_data["create_regions_meta"] = {r["slug"]: r for r in regions}  # type: ignore[index]

    keyboard: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for r in regions:
        row.append(InlineKeyboardButton(f"{r['slug']} — {r['name']}", callback_data=f"cr_reg_{r['slug']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await msg.edit_text(
        f"📛 Nama: <b>{name}</b>\n\n🌍 <b>Langkah 2/5:</b> Pilih region:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return REGION


# ── Step 2: Region selected → show size CATEGORIES ──────────────────────────

@authorized_only
async def region_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    region = query.data.replace("cr_reg_", "")  # type: ignore[union-attr]
    context.user_data["create_region"] = region  # type: ignore[index]

    await query.edit_message_text("⏳ Mengambil daftar size...", parse_mode="HTML")  # type: ignore[union-attr]

    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_token(user_id) or ""
    client = DigitalOceanClient(token)
    try:
        all_sizes = await client.list_sizes()
    except DigitalOceanError as exc:
        await query.edit_message_text(exc.message, parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END
    finally:
        await client.close()

    regions_meta = context.user_data.get("create_regions_meta", {})  # type: ignore[union-attr]
    region_obj = regions_meta.get(region, {})
    region_sizes = region_obj.get("sizes", [])

    sizes = _get_available_sizes(all_sizes, region, region_sizes)

    if not sizes:
        await query.edit_message_text(f"❌ Tidak ada size tersedia di region <b>{region}</b>.", parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END

    # Group by category
    cats = _build_categories(sizes)
    context.user_data["create_sizes_by_cat"] = cats  # type: ignore[index]

    # Build category buttons
    keyboard = []
    for cat_key in cats:
        cat_sizes = cats[cat_key]
        display = _cat_display_name(cat_key, cat_sizes)
        keyboard.append([InlineKeyboardButton(display, callback_data=f"cr_cat_{cat_key}")])

    name = context.user_data.get("create_name", "?")  # type: ignore[union-attr]
    await query.edit_message_text(  # type: ignore[union-attr]
        f"📛 Nama: <b>{name}</b>\n"
        f"🌍 Region: <b>{region}</b>\n\n"
        f"📦 <b>Langkah 3/5:</b> Pilih kategori size:\n\n"
        f"<i>⚠️ Catatan: DO API tidak membedakan size per akun.\n"
        f"Jika size tertentu terkunci, akan muncul error saat create.</i>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return CATEGORY


# ── Step 3: Category picked → show sizes in that category ────────────────────

@authorized_only
async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    cat_key = query.data.replace("cr_cat_", "")  # type: ignore[union-attr]
    cats = context.user_data.get("create_sizes_by_cat", {})  # type: ignore[union-attr]
    sizes = cats.get(cat_key, [])

    if not sizes:
        await query.edit_message_text("❌ Tidak ada size dalam kategori ini.", parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(_size_label(s), callback_data=f"cr_size_{s['slug']}")]
        for s in sizes[:30]
    ]
    # Add back button
    keyboard.append([InlineKeyboardButton("⬅️ Kembali ke kategori", callback_data="cr_cat_back")])

    name = context.user_data.get("create_name", "?")  # type: ignore[union-attr]
    region = context.user_data.get("create_region", "?")  # type: ignore[union-attr]
    cat_label = _cat_display_name(cat_key, sizes)

    await query.edit_message_text(  # type: ignore[union-attr]
        f"📛 Nama: <b>{name}</b>\n"
        f"🌍 Region: <b>{region}</b>\n"
        f"📦 Kategori: <b>{cat_label}</b>\n\n"
        f"💻 <b>Langkah 4/5:</b> Pilih size:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return SIZE


@authorized_only
async def category_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Back button: return to category selection."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    cats = context.user_data.get("create_sizes_by_cat", {})  # type: ignore[union-attr]
    keyboard = []
    for cat_key in cats:
        cat_sizes = cats[cat_key]
        display = _cat_display_name(cat_key, cat_sizes)
        keyboard.append([InlineKeyboardButton(display, callback_data=f"cr_cat_{cat_key}")])

    name = context.user_data.get("create_name", "?")  # type: ignore[union-attr]
    region = context.user_data.get("create_region", "?")  # type: ignore[union-attr]

    await query.edit_message_text(  # type: ignore[union-attr]
        f"📛 Nama: <b>{name}</b>\n"
        f"🌍 Region: <b>{region}</b>\n\n"
        f"📦 <b>Langkah 3/5:</b> Pilih kategori size:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return CATEGORY


# ── Step 4: Size selected, show images ───────────────────────────────────────

@authorized_only
async def size_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    size = query.data.replace("cr_size_", "")  # type: ignore[union-attr]
    context.user_data["create_size"] = size  # type: ignore[index]

    await query.edit_message_text("⏳ Mengambil daftar image/OS...", parse_mode="HTML")  # type: ignore[union-attr]

    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_token(user_id) or ""
    client = DigitalOceanClient(token)
    try:
        images = await client.list_images("distribution")
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

    name = context.user_data.get("create_name", "?")  # type: ignore[union-attr]
    region = context.user_data.get("create_region", "?")  # type: ignore[union-attr]
    await query.edit_message_text(  # type: ignore[union-attr]
        f"📛 Nama: <b>{name}</b>\n"
        f"🌍 Region: <b>{region}</b>\n"
        f"💻 Size: <b>{size}</b>\n\n"
        f"🖼️ <b>Langkah 5/5:</b> Pilih image/OS:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return IMAGE


# ── Step 5: Image selected → create ──────────────────────────────────────────

@authorized_only
async def image_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    image  = query.data.replace("cr_img_", "")  # type: ignore[union-attr]
    name   = context.user_data.get("create_name", "droplet")      # type: ignore[union-attr]
    region = context.user_data.get("create_region", "nyc1")       # type: ignore[union-attr]
    size   = context.user_data.get("create_size", "s-1vcpu-1gb")  # type: ignore[union-attr]

    await query.edit_message_text(  # type: ignore[union-attr]
        f"⏳ Membuat droplet <b>{name}</b>...\n\n"
        f"🌍 Region: {region} | 💻 Size: {size} | 🖼️ Image: {image}",
        parse_mode="HTML",
    )

    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_token(user_id) or ""
    client = DigitalOceanClient(token)
    try:
        droplet = await client.create_droplet(name=name, region=region, size=size, image=image)
        logger.info("Created droplet name=%s id=%s", name, droplet.get("id"))
        await query.edit_message_text(format_droplet_created(droplet), parse_mode="HTML")  # type: ignore[union-attr]
    except DigitalOceanError as exc:
        await query.edit_message_text(  # type: ignore[union-attr]
            f"❌ <b>Gagal membuat droplet</b>\n\n"
            f"{exc.message}\n\n"
            f"💡 <i>Kemungkinan size <code>{size}</code> tidak tersedia untuk akun kamu.\n"
            f"Coba gunakan size dari kategori yang berbeda (misal: Basic AMD).\n"
            f"Gunakan /create untuk mencoba lagi.</i>",
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
                CATEGORY: [
                    CallbackQueryHandler(category_selected, pattern=r"^cr_cat_(?!back).+$"),
                ],
                SIZE: [
                    CallbackQueryHandler(size_selected, pattern=r"^cr_size_.+$"),
                    CallbackQueryHandler(category_back, pattern=r"^cr_cat_back$"),
                ],
                IMAGE: [
                    CallbackQueryHandler(image_selected, pattern=r"^cr_img_.+$")
                ],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            per_message=False,
        )
    ]
