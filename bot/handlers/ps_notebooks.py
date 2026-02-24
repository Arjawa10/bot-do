"""/notebooks, /newnotebook, /stopnotebook, /delnotebook — Paperspace notebook management."""

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

logger = setup_logger("handler.ps_notebooks")

# Conversation states for /newnotebook
(
    PS_NB_WAITING_PROJECT,
    PS_NB_WAITING_MACHINE,
    PS_NB_WAITING_NAME,
) = range(3)

_NO_KEY_MSG = (
    "⚠️ API key Paperspace belum diset.\n"
    "Gunakan /pskey untuk menyimpan API key Paperspace kamu."
)

# Common Paperspace machine types for notebook (GPU + CPU)
_MACHINE_TYPES = [
    ("C5", "🖥️ C5 — 8 vCPU, 30 GB RAM"),
    ("P4000", "⚡ P4000 — Quadro P4000 GPU, 8 vCPU"),
    ("P5000", "🔥 P5000 — Quadro P5000 GPU, 8 vCPU"),
    ("P6000", "🚀 P6000 — Quadro P6000 GPU, 8 vCPU"),
    ("RTX4000", "💎 RTX4000 — 8 vCPU, 30 GB RAM"),
    ("A4000", "⚙️ A4000 — NVIDIA A4000"),
    ("A5000", "⚙️ A5000 — NVIDIA A5000"),
    ("A6000", "⚙️ A6000 — NVIDIA A6000 48 GB"),
]


def _fmt_notebook(nb: dict) -> str:
    nid = nb.get("id", "-")
    name = nb.get("name", "Unnamed")
    state = nb.get("state", nb.get("status", "unknown"))
    machine = nb.get("machineType", nb.get("machine", {}).get("machineType", "-"))
    state_emoji = {
        "Running": "🟢",
        "Stopped": "🔴",
        "Pending": "🟡",
        "Stopping": "🟠",
    }.get(state, "⚪")
    return f"• {state_emoji} <b>{name}</b>\n  🆔 <code>{nid}</code>  |  🖥️ {machine}  |  {state}"


# ── /notebooks ────────────────────────────────────────────────────────────────

@authorized_only
async def notebooks_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/notebooks — list all Paperspace notebooks."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_ps_token(user_id)
    if not token:
        await update.effective_message.reply_text(_NO_KEY_MSG, parse_mode="HTML")  # type: ignore[union-attr]
        return

    msg = await update.effective_message.reply_text(  # type: ignore[union-attr]
        "⏳ Mengambil daftar notebook...", parse_mode="HTML"
    )
    try:
        client = PaperspaceClient(token)
        try:
            notebooks = await client.list_notebooks()
        finally:
            await client.close()

        if not notebooks:
            await msg.edit_text(
                "📓 Tidak ada notebook Paperspace.\n\n"
                "Gunakan /newnotebook untuk membuat notebook baru.",
                parse_mode="HTML",
            )
            return

        lines = [_fmt_notebook(nb) for nb in notebooks]
        text = (
            f"📓 <b>Paperspace Notebooks</b> ({len(notebooks)} notebook)\n\n"
            + "\n\n".join(lines)
        )
        # Telegram message limit safety
        if len(text) > 4000:
            text = text[:3990] + "\n…"
        await msg.edit_text(text, parse_mode="HTML")
    except PaperspaceError as exc:
        await msg.edit_text(exc.message, parse_mode="HTML")
    except Exception as exc:
        logger.exception("Error in /notebooks")
        await msg.edit_text(f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML")


# ── /newnotebook ──────────────────────────────────────────────────────────────

@authorized_only
async def newnotebook_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """/newnotebook — step 1: ask for project ID."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_ps_token(user_id)
    if not token:
        await update.effective_message.reply_text(_NO_KEY_MSG, parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END

    # Fetch projects and show as inline keyboard
    msg = await update.effective_message.reply_text(  # type: ignore[union-attr]
        "⏳ Mengambil daftar project...", parse_mode="HTML"
    )
    try:
        client = PaperspaceClient(token)
        try:
            projects = await client.list_projects()
        finally:
            await client.close()
    except PaperspaceError as exc:
        await msg.edit_text(exc.message, parse_mode="HTML")
        return ConversationHandler.END
    except Exception as exc:
        await msg.edit_text(f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML")
        return ConversationHandler.END

    if not projects:
        await msg.edit_text(
            "❌ Kamu belum memiliki project Paperspace.\n\n"
            "Buat project dulu dengan /newproject.",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(
            p.get("name", p.get("id", "?")),
            callback_data=f"nbnewprj_{p.get('id')}",
        )]
        for p in projects
    ]
    await msg.edit_text(
        "📓 <b>Buat Notebook Baru</b>\n\n"
        "<b>Langkah 1/3:</b> Pilih project untuk notebook ini:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return PS_NB_WAITING_PROJECT


async def newnotebook_receive_project(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 2 via callback: project selected — ask machine type."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]
    project_id = query.data.replace("nbnewprj_", "", 1)  # type: ignore[union-attr]
    context.user_data["nb_project_id"] = project_id  # type: ignore[index]

    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"nbmachine_{slug}")]
        for slug, label in _MACHINE_TYPES
    ]
    await query.edit_message_text(  # type: ignore[union-attr]
        f"✅ Project dipilih: <code>{project_id}</code>\n\n"
        "<b>Langkah 2/3:</b> Pilih tipe mesin (machine type):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return PS_NB_WAITING_MACHINE


async def newnotebook_receive_machine(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 3 via callback: machine type selected — ask notebook name."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]
    machine_type = query.data.replace("nbmachine_", "", 1)  # type: ignore[union-attr]
    context.user_data["nb_machine_type"] = machine_type  # type: ignore[index]

    await query.edit_message_text(  # type: ignore[union-attr]
        f"✅ Machine type: <b>{machine_type}</b>\n\n"
        "<b>Langkah 3/3:</b> Masukkan <b>nama notebook</b>:\n\n"
        "Ketik /cancel untuk membatalkan.",
        parse_mode="HTML",
    )
    return PS_NB_WAITING_NAME


async def newnotebook_receive_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Final step via text: create the notebook."""
    name = (update.effective_message.text or "").strip()  # type: ignore[union-attr]
    if not name or len(name) > 100:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "⚠️ Nama tidak valid. Gunakan nama singkat (maks 100 karakter).",
            parse_mode="HTML",
        )
        return PS_NB_WAITING_NAME

    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_ps_token(user_id)
    if not token:
        await update.effective_message.reply_text(_NO_KEY_MSG, parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END

    project_id: str = context.user_data.get("nb_project_id", "")  # type: ignore[union-attr]
    machine_type: str = context.user_data.get("nb_machine_type", "")  # type: ignore[union-attr]

    msg = await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"⏳ Membuat notebook <b>{name}</b> ({machine_type})...", parse_mode="HTML"
    )
    try:
        client = PaperspaceClient(token)
        try:
            notebook = await client.create_notebook(project_id, machine_type, name)
        finally:
            await client.close()

        nid = notebook.get("id", "-")
        state = notebook.get("state", notebook.get("status", "Pending"))
        await msg.edit_text(
            f"✅ <b>Notebook berhasil dibuat!</b>\n\n"
            f"📓 Nama: <b>{name}</b>\n"
            f"🆔 ID: <code>{nid}</code>\n"
            f"🖥️ Machine: <b>{machine_type}</b>\n"
            f"📊 Status: <b>{state}</b>\n\n"
            "Gunakan /notebooks untuk melihat semua notebook.",
            parse_mode="HTML",
        )
    except PaperspaceError as exc:
        await msg.edit_text(
            f"❌ <b>Gagal membuat notebook</b>\n\n{exc.message}", parse_mode="HTML"
        )
    except Exception as exc:
        logger.exception("Error in /newnotebook")
        await msg.edit_text(f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML")

    return ConversationHandler.END


async def newnotebook_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.effective_message.reply_text("❎ Dibatalkan.", parse_mode="HTML")  # type: ignore[union-attr]
    return ConversationHandler.END


# ── /stopnotebook ─────────────────────────────────────────────────────────────

@authorized_only
async def stopnotebook_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/stopnotebook — show inline keyboard to stop a running notebook."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_ps_token(user_id)
    if not token:
        await update.effective_message.reply_text(_NO_KEY_MSG, parse_mode="HTML")  # type: ignore[union-attr]
        return

    msg = await update.effective_message.reply_text(  # type: ignore[union-attr]
        "⏳ Mengambil daftar notebook...", parse_mode="HTML"
    )
    try:
        client = PaperspaceClient(token)
        try:
            notebooks = await client.list_notebooks()
        finally:
            await client.close()

        running = [
            nb for nb in notebooks
            if nb.get("state", nb.get("status", "")).lower() in ("running", "pending")
        ]
        if not running:
            await msg.edit_text(
                "✅ Tidak ada notebook yang sedang berjalan.", parse_mode="HTML"
            )
            return

        keyboard = [
            [InlineKeyboardButton(
                f"⏹️ {nb.get('name', nb.get('id', '?'))}",
                callback_data=f"stopnb_{nb.get('id')}",
            )]
            for nb in running
        ]
        await msg.edit_text(
            "⏹️ <b>Stop Notebook</b>\n\nPilih notebook yang ingin dihentikan:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except PaperspaceError as exc:
        await msg.edit_text(exc.message, parse_mode="HTML")
    except Exception as exc:
        logger.exception("Error in /stopnotebook")
        await msg.edit_text(f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML")


@authorized_only
async def stopnotebook_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Inline button: stop a notebook."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    notebook_id = query.data.replace("stopnb_", "", 1)  # type: ignore[union-attr]

    token = get_ps_token(user_id)
    if not token:
        await query.edit_message_text(_NO_KEY_MSG, parse_mode="HTML")  # type: ignore[union-attr]
        return

    await query.edit_message_text(  # type: ignore[union-attr]
        f"⏳ Menghentikan notebook <code>{notebook_id}</code>...", parse_mode="HTML"
    )
    try:
        client = PaperspaceClient(token)
        try:
            await client.stop_notebook(notebook_id)
        finally:
            await client.close()

        await query.edit_message_text(  # type: ignore[union-attr]
            f"⏹️ Notebook <code>{notebook_id}</code> berhasil dihentikan.\n\n"
            "Gunakan /notebooks untuk melihat status terbaru.",
            parse_mode="HTML",
        )
    except PaperspaceError as exc:
        await query.edit_message_text(  # type: ignore[union-attr]
            f"❌ <b>Gagal menghentikan notebook</b>\n\n{exc.message}", parse_mode="HTML"
        )
    except Exception as exc:
        logger.exception("Error in stopnotebook callback")
        await query.edit_message_text(  # type: ignore[union-attr]
            f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML"
        )


# ── /delnotebook ──────────────────────────────────────────────────────────────

@authorized_only
async def delnotebook_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/delnotebook — show inline keyboard to delete a notebook."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_ps_token(user_id)
    if not token:
        await update.effective_message.reply_text(_NO_KEY_MSG, parse_mode="HTML")  # type: ignore[union-attr]
        return

    msg = await update.effective_message.reply_text(  # type: ignore[union-attr]
        "⏳ Mengambil daftar notebook...", parse_mode="HTML"
    )
    try:
        client = PaperspaceClient(token)
        try:
            notebooks = await client.list_notebooks()
        finally:
            await client.close()

        if not notebooks:
            await msg.edit_text(
                "📓 Tidak ada notebook yang bisa dihapus.", parse_mode="HTML"
            )
            return

        keyboard = [
            [InlineKeyboardButton(
                f"🗑️ {nb.get('name', nb.get('id', '?'))}",
                callback_data=f"delnb_{nb.get('id')}",
            )]
            for nb in notebooks
        ]
        await msg.edit_text(
            "🗑️ <b>Hapus Notebook Paperspace</b>\n\nPilih notebook yang ingin dihapus:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except PaperspaceError as exc:
        await msg.edit_text(exc.message, parse_mode="HTML")
    except Exception as exc:
        logger.exception("Error in /delnotebook")
        await msg.edit_text(f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML")


@authorized_only
async def delnotebook_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Inline button: delete a notebook."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    notebook_id = query.data.replace("delnb_", "", 1)  # type: ignore[union-attr]

    token = get_ps_token(user_id)
    if not token:
        await query.edit_message_text(_NO_KEY_MSG, parse_mode="HTML")  # type: ignore[union-attr]
        return

    await query.edit_message_text(  # type: ignore[union-attr]
        f"⏳ Menghapus notebook <code>{notebook_id}</code>...", parse_mode="HTML"
    )
    try:
        client = PaperspaceClient(token)
        try:
            await client.delete_notebook(notebook_id)
        finally:
            await client.close()

        await query.edit_message_text(  # type: ignore[union-attr]
            f"🗑️ Notebook <code>{notebook_id}</code> berhasil dihapus.\n\n"
            "Gunakan /notebooks untuk melihat sisa notebook.",
            parse_mode="HTML",
        )
    except PaperspaceError as exc:
        await query.edit_message_text(  # type: ignore[union-attr]
            f"❌ <b>Gagal menghapus notebook</b>\n\n{exc.message}", parse_mode="HTML"
        )
    except Exception as exc:
        logger.exception("Error in delnotebook callback")
        await query.edit_message_text(  # type: ignore[union-attr]
            f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML"
        )


# ── Registration ──────────────────────────────────────────────────────────────

def get_handlers() -> list:
    newnotebook_conv = ConversationHandler(
        entry_points=[CommandHandler("newnotebook", newnotebook_start)],
        states={
            PS_NB_WAITING_PROJECT: [
                CallbackQueryHandler(newnotebook_receive_project, pattern=r"^nbnewprj_.+$"),
            ],
            PS_NB_WAITING_MACHINE: [
                CallbackQueryHandler(newnotebook_receive_machine, pattern=r"^nbmachine_.+$"),
            ],
            PS_NB_WAITING_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, newnotebook_receive_name),
            ],
        },
        fallbacks=[CommandHandler("cancel", newnotebook_cancel)],
        name="newnotebook_conversation",
    )
    return [
        CommandHandler("notebooks", notebooks_command),
        newnotebook_conv,
        CommandHandler("stopnotebook", stopnotebook_command),
        CommandHandler("delnotebook", delnotebook_command),
        CallbackQueryHandler(stopnotebook_callback, pattern=r"^stopnb_.+$"),
        CallbackQueryHandler(delnotebook_callback, pattern=r"^delnb_.+$"),
    ]
