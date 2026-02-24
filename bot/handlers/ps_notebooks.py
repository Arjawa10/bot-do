"""/psmachines, /newmachine, /startmachine, /stopmachine, /restartmachine, /delmachine
Paperspace Machine management (Notebooks deprecated as of July 2024).
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
from bot.services.paperspace import PaperspaceClient, PaperspaceError
from bot.storage.api_keys import get_ps_token
from bot.utils.logger import setup_logger

logger = setup_logger("handler.ps_machines")

# Conversation states for /newmachine
(
    PS_MC_WAITING_NAME,
    PS_MC_WAITING_TYPE,
    PS_MC_WAITING_TEMPLATE,
    PS_MC_WAITING_REGION,
    PS_MC_WAITING_DISK,
) = range(5)

_NO_KEY_MSG = (
    "⚠️ API key Paperspace belum diset.\n"
    "Gunakan /pskey untuk menyimpan API key Paperspace kamu."
)

# Common machine types
_MACHINE_TYPES = [
    ("C5",       "🖥️  C5    — CPU, 8 vCPU 30 GB RAM"),
    ("P4000",    "⚡ P4000 — Quadro P4000 8 vCPU"),
    ("P5000",    "🔥 P5000 — Quadro P5000 8 vCPU"),
    ("RTX4000",  "💎 RTX4000 — 8 vCPU 30 GB RAM"),
    ("A4000",    "⚙️  A4000 — NVIDIA A4000"),
    ("A5000",    "⚙️  A5000 — NVIDIA A5000"),
    ("A6000",    "⚙️  A6000 — NVIDIA A6000 48 GB"),
    ("A100-80G", "🚀 A100  — 80 GB HBM2e"),
]

# Common regions
_REGIONS = [
    ("ny2", "🇺🇸 New York 2"),
    ("ca1", "🇺🇸 California 1"),
    ("tx1", "🇺🇸 Texas 1"),
    ("eu1", "🇳🇱 Europe 1"),
]

# Common templates  (name only — user can type custom template ID)
_COMMON_TEMPLATES = [
    ("tlvh5xr", "Ubuntu 20.04"),
    ("t0nspur5", "Ubuntu 22.04"),
]

# Machine state emoji map
_STATE_EMOJI = {
    "running":      "🟢",
    "off":          "🔴",
    "stopped":      "🔴",
    "starting":     "🟡",
    "stopping":     "🟠",
    "restarting":   "🟠",
    "provisioning": "🔵",
    "serviceready": "🟢",
}


def _fmt_machine(m: dict) -> str:
    mid   = m.get("id", "-")
    name  = m.get("name", "Unnamed")
    state = (m.get("state") or m.get("status") or "unknown").lower()
    mtype = m.get("machineType", "-")
    region = m.get("region", "-")
    emoji = _STATE_EMOJI.get(state, "⚪")
    return (
        f"• {emoji} <b>{name}</b>\n"
        f"  🆔 <code>{mid}</code>  |  🖥️ {mtype}  |  🌐 {region}  |  {state}"
    )


# ── /psmachines ────────────────────────────────────────────────────────────────

@authorized_only
async def psmachines_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/psmachines — list all Paperspace machines."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_ps_token(user_id)
    if not token:
        await update.effective_message.reply_text(_NO_KEY_MSG, parse_mode="HTML")  # type: ignore[union-attr]
        return

    msg = await update.effective_message.reply_text(  # type: ignore[union-attr]
        "⏳ Mengambil daftar machine...", parse_mode="HTML"
    )
    try:
        client = PaperspaceClient(token)
        try:
            machines = await client.list_machines()
        finally:
            await client.close()

        if not machines:
            await msg.edit_text(
                "🖥️ Tidak ada Paperspace Machine.\n\n"
                "Gunakan /newmachine untuk membuat machine baru.",
                parse_mode="HTML",
            )
            return

        lines = [_fmt_machine(m) for m in machines]
        text = (
            f"🖥️ <b>Paperspace Machines</b> ({len(machines)} machine)\n\n"
            + "\n\n".join(lines)
        )
        if len(text) > 4000:
            text = text[:3990] + "\n…"
        await msg.edit_text(text, parse_mode="HTML")
    except PaperspaceError as exc:
        await msg.edit_text(exc.message, parse_mode="HTML")
    except Exception as exc:
        logger.exception("Error in /psmachines")
        await msg.edit_text(f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML")


# ── /newmachine (conversation) ─────────────────────────────────────────────────

@authorized_only
async def newmachine_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """/newmachine — step 1: ask for machine name."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_ps_token(user_id)
    if not token:
        await update.effective_message.reply_text(_NO_KEY_MSG, parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END

    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "🖥️ <b>Buat Machine Baru</b>\n\n"
        "<b>Langkah 1/4:</b> Masukkan <b>nama</b> untuk machine ini.\n"
        "Contoh: <code>gpu-dev</code>, <code>training-box</code>\n\n"
        "Ketik /cancel untuk membatalkan.",
        parse_mode="HTML",
    )
    return PS_MC_WAITING_NAME


async def newmachine_receive_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    name = (update.effective_message.text or "").strip()  # type: ignore[union-attr]
    if not name or len(name) > 100:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "⚠️ Nama tidak valid (maks 100 karakter). Coba lagi:",
            parse_mode="HTML",
        )
        return PS_MC_WAITING_NAME

    context.user_data["mc_name"] = name  # type: ignore[index]

    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"mctype_{slug}")]
        for slug, label in _MACHINE_TYPES
    ]
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"✅ Nama: <b>{name}</b>\n\n"
        "<b>Langkah 2/4:</b> Pilih tipe machine:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return PS_MC_WAITING_TYPE


async def newmachine_receive_type(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]
    machine_type = query.data.replace("mctype_", "", 1)  # type: ignore[union-attr]
    context.user_data["mc_type"] = machine_type  # type: ignore[index]

    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"mctpl_{tid}")]
        for tid, label in _COMMON_TEMPLATES
    ] + [
        [InlineKeyboardButton("✏️ Masukkan template ID manual", callback_data="mctpl_manual")]
    ]
    await query.edit_message_text(  # type: ignore[union-attr]
        f"✅ Machine type: <b>{machine_type}</b>\n\n"
        "<b>Langkah 3/4:</b> Pilih OS template:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return PS_MC_WAITING_TEMPLATE


async def newmachine_receive_template(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]
    value = query.data.replace("mctpl_", "", 1)  # type: ignore[union-attr]

    if value == "manual":
        await query.edit_message_text(  # type: ignore[union-attr]
            "✏️ Masukkan <b>template ID</b> secara manual:\n"
            "(Contoh: <code>tlvh5xr</code>)\n\n"
            "Ketik /cancel untuk membatalkan.",
            parse_mode="HTML",
        )
        context.user_data["mc_template_mode"] = "manual"  # type: ignore[index]
        return PS_MC_WAITING_TEMPLATE

    context.user_data["mc_template"] = value  # type: ignore[index]

    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"mcreg_{slug}")]
        for slug, label in _REGIONS
    ]
    await query.edit_message_text(  # type: ignore[union-attr]
        f"✅ Template: <b>{value}</b>\n\n"
        "<b>Langkah 4/4:</b> Pilih region:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return PS_MC_WAITING_REGION


async def newmachine_receive_template_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle manual template ID input."""
    tpl = (update.effective_message.text or "").strip()  # type: ignore[union-attr]
    if not tpl:
        await update.effective_message.reply_text("⚠️ Template ID tidak boleh kosong. Coba lagi:")  # type: ignore[union-attr]
        return PS_MC_WAITING_TEMPLATE

    context.user_data["mc_template"] = tpl  # type: ignore[index]

    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"mcreg_{slug}")]
        for slug, label in _REGIONS
    ]
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"✅ Template: <b>{tpl}</b>\n\n"
        "<b>Langkah 4/4:</b> Pilih region:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return PS_MC_WAITING_REGION


async def newmachine_receive_region(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]
    region = query.data.replace("mcreg_", "", 1)  # type: ignore[union-attr]
    context.user_data["mc_region"] = region  # type: ignore[index]

    name     = context.user_data.get("mc_name", "")  # type: ignore[union-attr]
    mc_type  = context.user_data.get("mc_type", "")  # type: ignore[union-attr]
    template = context.user_data.get("mc_template", "")  # type: ignore[union-attr]

    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_ps_token(user_id)
    if not token:
        await query.edit_message_text(_NO_KEY_MSG, parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END

    await query.edit_message_text(  # type: ignore[union-attr]
        f"⏳ Membuat machine <b>{name}</b> ({mc_type}, {region})...",
        parse_mode="HTML",
    )
    try:
        client = PaperspaceClient(token)
        try:
            machine = await client.create_machine(
                name=name,
                machine_type=mc_type,
                template_id=template,
                region=region,
            )
        finally:
            await client.close()

        mid   = machine.get("id", "-")
        state = machine.get("state", machine.get("status", "provisioning"))
        await query.edit_message_text(  # type: ignore[union-attr]
            f"✅ <b>Machine berhasil dibuat!</b>\n\n"
            f"🖥️ Nama   : <b>{name}</b>\n"
            f"🆔 ID     : <code>{mid}</code>\n"
            f"⚙️ Type   : <b>{mc_type}</b>\n"
            f"🌐 Region : <b>{region}</b>\n"
            f"📊 Status : <b>{state}</b>\n\n"
            "Gunakan /psmachines untuk melihat semua machine.",
            parse_mode="HTML",
        )
    except PaperspaceError as exc:
        await query.edit_message_text(  # type: ignore[union-attr]
            f"❌ <b>Gagal membuat machine</b>\n\n{exc.message}", parse_mode="HTML"
        )
    except Exception as exc:
        logger.exception("Error in /newmachine")
        await query.edit_message_text(  # type: ignore[union-attr]
            f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML"
        )
    return ConversationHandler.END


async def newmachine_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.effective_message.reply_text("❎ Dibatalkan.", parse_mode="HTML")  # type: ignore[union-attr]
    return ConversationHandler.END


# ── Action commands: start / stop / restart / delete ─────────────────────────

def _build_machine_keyboard(machines: list[dict], action: str) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(
            m.get("name", m.get("id", "?")),
            callback_data=f"{action}mc_{m.get('id')}",
        )]
        for m in machines
    ]
    return InlineKeyboardMarkup(keyboard)


async def _machine_list_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    filter_state: str | None,
    action_prefix: str,
    title: str,
    empty_msg: str,
) -> None:
    """Shared helper: fetch machines, optionally filter by state, show keyboard."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_ps_token(user_id)
    if not token:
        await update.effective_message.reply_text(_NO_KEY_MSG, parse_mode="HTML")  # type: ignore[union-attr]
        return

    msg = await update.effective_message.reply_text(  # type: ignore[union-attr]
        "⏳ Mengambil daftar machine...", parse_mode="HTML"
    )
    try:
        client = PaperspaceClient(token)
        try:
            machines = await client.list_machines()
        finally:
            await client.close()

        if filter_state:
            machines = [
                m for m in machines
                if (m.get("state") or m.get("status") or "").lower() in filter_state
            ]

        if not machines:
            await msg.edit_text(empty_msg, parse_mode="HTML")
            return

        await msg.edit_text(
            title,
            parse_mode="HTML",
            reply_markup=_build_machine_keyboard(machines, action_prefix),
        )
    except PaperspaceError as exc:
        await msg.edit_text(exc.message, parse_mode="HTML")
    except Exception as exc:
        logger.exception("Error fetching machines for %s", action_prefix)
        await msg.edit_text(f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML")


async def _machine_action_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    prefix: str,
    action_fn: str,
    success_msg: str,
    doing_msg: str,
) -> None:
    """Generic callback for machine action buttons."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    machine_id = query.data.replace(f"{prefix}mc_", "", 1)  # type: ignore[union-attr]

    token = get_ps_token(user_id)
    if not token:
        await query.edit_message_text(_NO_KEY_MSG, parse_mode="HTML")  # type: ignore[union-attr]
        return

    await query.edit_message_text(  # type: ignore[union-attr]
        doing_msg.format(mid=machine_id), parse_mode="HTML"
    )
    try:
        client = PaperspaceClient(token)
        try:
            fn = getattr(client, action_fn)
            await fn(machine_id)
        finally:
            await client.close()
        await query.edit_message_text(  # type: ignore[union-attr]
            success_msg.format(mid=machine_id), parse_mode="HTML"
        )
    except PaperspaceError as exc:
        await query.edit_message_text(  # type: ignore[union-attr]
            f"❌ <b>Gagal</b>\n\n{exc.message}", parse_mode="HTML"
        )
    except Exception as exc:
        logger.exception("Error in machine callback %s", prefix)
        await query.edit_message_text(  # type: ignore[union-attr]
            f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML"
        )


# /startmachine
@authorized_only
async def startmachine_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _machine_list_action(
        update, context,
        filter_state="off|stopped",
        action_prefix="start",
        title="▶️ <b>Start Machine</b>\n\nPilih machine yang ingin dinyalakan:",
        empty_msg="✅ Tidak ada machine yang sedang mati.",
    )


@authorized_only
async def startmachine_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _machine_action_callback(
        update, context,
        prefix="start",
        action_fn="start_machine",
        doing_msg="⏳ Menyalakan machine <code>{mid}</code>...",
        success_msg="▶️ Machine <code>{mid}</code> berhasil dinyalakan.\n\nGunakan /psmachines untuk melihat status.",
    )


# /stopmachine
@authorized_only
async def stopmachine_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _machine_list_action(
        update, context,
        filter_state="running|serviceready|starting",
        action_prefix="stop",
        title="⏹️ <b>Stop Machine</b>\n\nPilih machine yang ingin dihentikan:",
        empty_msg="✅ Tidak ada machine yang sedang berjalan.",
    )


@authorized_only
async def stopmachine_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _machine_action_callback(
        update, context,
        prefix="stop",
        action_fn="stop_machine",
        doing_msg="⏳ Menghentikan machine <code>{mid}</code>...",
        success_msg="⏹️ Machine <code>{mid}</code> berhasil dihentikan.\n\nGunakan /psmachines untuk melihat status.",
    )


# /restartmachine
@authorized_only
async def restartmachine_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _machine_list_action(
        update, context,
        filter_state=None,
        action_prefix="restart",
        title="🔄 <b>Restart Machine</b>\n\nPilih machine yang ingin di-restart:",
        empty_msg="🖥️ Tidak ada machine.",
    )


@authorized_only
async def restartmachine_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _machine_action_callback(
        update, context,
        prefix="restart",
        action_fn="restart_machine",
        doing_msg="⏳ Me-restart machine <code>{mid}</code>...",
        success_msg="🔄 Machine <code>{mid}</code> berhasil di-restart.\n\nGunakan /psmachines untuk melihat status.",
    )


# /delmachine
@authorized_only
async def delmachine_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _machine_list_action(
        update, context,
        filter_state=None,
        action_prefix="del",
        title="🗑️ <b>Hapus Machine Paperspace</b>\n\nPilih machine yang ingin dihapus:",
        empty_msg="🖥️ Tidak ada machine yang bisa dihapus.",
    )


@authorized_only
async def delmachine_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _machine_action_callback(
        update, context,
        prefix="del",
        action_fn="delete_machine",
        doing_msg="⏳ Menghapus machine <code>{mid}</code>...",
        success_msg="🗑️ Machine <code>{mid}</code> berhasil dihapus.\n\nGunakan /psmachines untuk melihat sisa machine.",
    )


# ── Registration ──────────────────────────────────────────────────────────────

def get_handlers() -> list:
    newmachine_conv = ConversationHandler(
        entry_points=[CommandHandler("newmachine", newmachine_start)],
        states={
            PS_MC_WAITING_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, newmachine_receive_name),
            ],
            PS_MC_WAITING_TYPE: [
                CallbackQueryHandler(newmachine_receive_type, pattern=r"^mctype_.+$"),
            ],
            PS_MC_WAITING_TEMPLATE: [
                CallbackQueryHandler(newmachine_receive_template, pattern=r"^mctpl_.+$"),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    newmachine_receive_template_text,
                ),
            ],
            PS_MC_WAITING_REGION: [
                CallbackQueryHandler(newmachine_receive_region, pattern=r"^mcreg_.+$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", newmachine_cancel)],
        name="newmachine_conversation",
    )
    return [
        CommandHandler("psmachines",      psmachines_command),
        newmachine_conv,
        CommandHandler("startmachine",    startmachine_command),
        CommandHandler("stopmachine",     stopmachine_command),
        CommandHandler("restartmachine",  restartmachine_command),
        CommandHandler("delmachine",      delmachine_command),
        CallbackQueryHandler(startmachine_callback,   pattern=r"^startmc_.+$"),
        CallbackQueryHandler(stopmachine_callback,    pattern=r"^stopmc_.+$"),
        CallbackQueryHandler(restartmachine_callback, pattern=r"^restartmc_.+$"),
        CallbackQueryHandler(delmachine_callback,     pattern=r"^delmc_.+$"),
    ]
