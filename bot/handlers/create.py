"""/create command handler — create CPU or GPU droplet with step-by-step flow.

Flow:
  1. /create         → ask droplet name
  2. name received   → ask CPU or GPU
  3. type selected   → ask region
  4. region selected → fetch & filter sizes (available + matching type, in region)
  5. size selected   → ask image/OS
  6. image selected  → confirm + create
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
NAME, TYPE, REGION, SIZE, IMAGE = range(5)

# GPU size slug prefixes — DO GPU droplets use ONLY the 'gpu-' prefix.
# NOTE: 'gd-' = General Purpose Dedicated **CPU** (not GPU)
_GPU_PREFIXES = ("gpu-",)

# CPU size family labels (for display)
_CPU_FAMILY: dict[str, str] = {
    "s-":   "Basic",
    "c-":   "CPU-Optimized",
    "c2-":  "CPU-Opt 2x",
    "g-":   "General Purpose",
    "gd-":  "General Purpose Dedicated",
    "m-":   "Memory-Optimized",
    "m3-":  "Memory-Opt 3x",
    "so-":  "Storage-Optimized",
    "so1_": "Storage-Opt 1.5x",
}

# Max sizes/images to show in one keyboard (Telegram limit ≈ 100 buttons)
_MAX_SIZES  = 25
_MAX_IMAGES = 20


def _is_gpu_size(slug: str) -> bool:
    """Return True only for genuine GPU droplet sizes (slug starts with 'gpu-')."""
    return slug.startswith("gpu-")


def _cpu_family_label(slug: str) -> str:
    """Return a human-readable family tag for CPU sizes."""
    # AMD variants end with '-amd'
    is_amd = slug.endswith("-amd") or "-amd-" in slug
    for prefix, label in _CPU_FAMILY.items():
        if slug.startswith(prefix):
            suffix = " AMD" if is_amd else " Intel"
            return f"{label}{suffix}"
    return "CPU"


def _filter_sizes(
    sizes: list[dict],
    region: str,
    want_gpu: bool,
) -> list[dict]:
    """Return sizes that are:
    - available=True at the API level
    - available in the selected region
    - match the requested type (CPU vs GPU)
    Sorted by monthly price.
    """
    result = []
    for s in sizes:
        if not s.get("available", False):
            continue
        if region not in s.get("regions", []):
            continue
        slug = s.get("slug", "")
        if want_gpu != _is_gpu_size(slug):
            continue
        result.append(s)
    result.sort(key=lambda s: float(s.get("price_monthly", 0)))
    return result[:_MAX_SIZES]


def _size_label(s: dict) -> str:
    slug      = s.get("slug", "?")
    vcpus     = s.get("vcpus", "?")
    mem_gb    = round(s.get("memory", 0) / 1024, 1)
    price     = s.get("price_monthly", "?")
    disk      = s.get("disk", "?")
    if _is_gpu_size(slug):
        # GPU sizes: slug encodes GPU specs, no need for vCPU/RAM breakdown
        return f"{slug} • {vcpus}vCPU {mem_gb}GB RAM • ${price}/mo"
    family = _cpu_family_label(slug)
    return f"{slug} • {family} • {vcpus}vCPU {mem_gb}GB RAM {disk}GB • ${price}/mo"


# ── Step 0: /create ───────────────────────────────────────────────────────────

@authorized_only
async def create_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 0: Ask for droplet name."""
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "🚀 <b>Buat Droplet Baru</b>\n\n"
        "📝 <b>Langkah 1/5:</b> Masukkan nama untuk droplet:\n\n"
        "Ketik /cancel untuk membatalkan.",
        parse_mode="HTML",
    )
    return NAME


# ── Step 1: Receive name, ask CPU/GPU ─────────────────────────────────────────

async def name_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 1: Save name, ask type (CPU or GPU)."""
    name = (update.effective_message.text or "").strip()  # type: ignore[union-attr]
    if not name:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "⚠️ Nama tidak boleh kosong. Coba lagi:"
        )
        return NAME

    context.user_data["create_name"] = name  # type: ignore[index]

    keyboard = [
        [
            InlineKeyboardButton("💻 CPU Droplet", callback_data="cr_type_cpu"),
            InlineKeyboardButton("🎮 GPU Droplet", callback_data="cr_type_gpu"),
        ]
    ]
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"📛 Nama: <b>{name}</b>\n\n"
        "🖥️ <b>Langkah 2/5:</b> Pilih tipe droplet:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return TYPE


# ── Step 2: Receive type, ask region ─────────────────────────────────────────

@authorized_only
async def type_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 2: Save type, fetch and show available regions."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    want_gpu = query.data == "cr_type_gpu"  # type: ignore[union-attr]
    context.user_data["create_gpu"] = want_gpu  # type: ignore[index]

    type_label = "🎮 GPU" if want_gpu else "💻 CPU"
    await query.edit_message_text(  # type: ignore[union-attr]
        "⏳ Mengambil daftar region...", parse_mode="HTML"
    )

    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_token(user_id) or ""
    client = DigitalOceanClient(token)
    try:
        regions = await client.list_regions()
        all_sizes = await client.list_sizes()
    except DigitalOceanError as exc:
        await query.edit_message_text(exc.message, parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END
    finally:
        await client.close()

    # Only show regions that have at least one matching available size
    size_slugs_by_type = {
        s["slug"]
        for s in all_sizes
        if s.get("available") and (_is_gpu_size(s["slug"]) == want_gpu)
    }

    viable_regions = [
        r for r in regions
        if any(slug in size_slugs_by_type for slug in r.get("sizes", []))
    ]

    if not viable_regions:
        await query.edit_message_text(  # type: ignore[union-attr]
            f"❌ Tidak ada region dengan {type_label} droplet yang tersedia untuk akun ini.",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    # 2 buttons per row
    keyboard: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for r in viable_regions:
        row.append(InlineKeyboardButton(
            f"{r['slug']} — {r['name']}",
            callback_data=f"cr_reg_{r['slug']}",
        ))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    name = context.user_data.get("create_name", "?")  # type: ignore[union-attr]
    await query.edit_message_text(  # type: ignore[union-attr]
        f"📛 Nama: <b>{name}</b>\n"
        f"🖥️ Tipe: <b>{type_label}</b>\n\n"
        f"🌍 <b>Langkah 3/5:</b> Pilih region:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return REGION


# ── Step 3: Region selected, show sizes ──────────────────────────────────────

@authorized_only
async def region_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 3: Save region, fetch and show available sizes for the chosen type."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    region = query.data.replace("cr_reg_", "")  # type: ignore[union-attr]
    context.user_data["create_region"] = region  # type: ignore[index]
    want_gpu: bool = context.user_data.get("create_gpu", False)  # type: ignore[union-attr]
    type_label = "🎮 GPU" if want_gpu else "💻 CPU"

    await query.edit_message_text(  # type: ignore[union-attr]
        "⏳ Mengambil daftar size...", parse_mode="HTML"
    )

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

    sizes = _filter_sizes(all_sizes, region, want_gpu)

    if not sizes:
        await query.edit_message_text(  # type: ignore[union-attr]
            f"❌ Tidak ada {type_label} size yang tersedia di region <b>{region}</b>.\n\n"
            "Coba pilih region lain dengan /create.",
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
        f"🖥️ Tipe: <b>{type_label}</b>\n"
        f"🌍 Region: <b>{region}</b>\n\n"
        f"💻 <b>Langkah 4/5:</b> Pilih size ({len(sizes)} tersedia):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return SIZE


# ── Step 4: Size selected, show images ───────────────────────────────────────

@authorized_only
async def size_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 4: Save size, fetch and show OS images."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    size = query.data.replace("cr_size_", "")  # type: ignore[union-attr]
    context.user_data["create_size"] = size  # type: ignore[index]
    want_gpu: bool = context.user_data.get("create_gpu", False)  # type: ignore[union-attr]

    await query.edit_message_text(  # type: ignore[union-attr]
        "⏳ Mengambil daftar image/OS...", parse_mode="HTML"
    )

    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_token(user_id) or ""
    client = DigitalOceanClient(token)
    try:
        # GPU droplets often need custom images; fetch both distribution + application
        images = await client.list_images("distribution")
        if want_gpu:
            # Also include application images for GPU (CUDA etc.)
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
        await query.edit_message_text(  # type: ignore[union-attr]
            "❌ Tidak ada image tersedia.", parse_mode="HTML"
        )
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
    type_label = "🎮 GPU" if want_gpu else "💻 CPU"
    await query.edit_message_text(  # type: ignore[union-attr]
        f"📛 Nama: <b>{name}</b>\n"
        f"🖥️ Tipe: <b>{type_label}</b>\n"
        f"🌍 Region: <b>{region}</b>\n"
        f"💻 Size: <b>{size}</b>\n\n"
        f"🖼️ <b>Langkah 5/5:</b> Pilih image/OS:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return IMAGE


# ── Step 5: Image selected → create ──────────────────────────────────────────

@authorized_only
async def image_selected(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 5: Receive image, create the droplet."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]

    image  = query.data.replace("cr_img_", "")  # type: ignore[union-attr]
    name   = context.user_data.get("create_name", "droplet")  # type: ignore[union-attr]
    region = context.user_data.get("create_region", "nyc1")    # type: ignore[union-attr]
    size   = context.user_data.get("create_size", "s-1vcpu-1gb")  # type: ignore[union-attr]
    want_gpu: bool = context.user_data.get("create_gpu", False)  # type: ignore[union-attr]
    type_label = "🎮 GPU" if want_gpu else "💻 CPU"

    await query.edit_message_text(  # type: ignore[union-attr]
        f"⏳ Membuat droplet <b>{name}</b>...\n\n"
        f"🖥️ Tipe: {type_label}\n"
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
            name, droplet.get("id"), region, size, image,
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
                TYPE: [
                    CallbackQueryHandler(type_selected, pattern=r"^cr_type_(cpu|gpu)$")
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
