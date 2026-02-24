"""/projects, /newproject, /delproject — Paperspace project management.

NOTE: GET /v1/projects returns 500 Internal Server Error on Paperspace's side
(confirmed via direct API testing — this is a known server-side bug).
      - /projects will show a notice about this limitation
      - /newproject (POST /projects) works fine
      - /delproject accepts a project ID manually
"""

from __future__ import annotations

from telegram import Update
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

logger = setup_logger("handler.ps_projects")

# Conversation states
PS_PRJ_WAITING_NAME   = 0
PS_DEL_WAITING_ID     = 1

_NO_KEY_MSG = (
    "⚠️ API key Paperspace belum diset.\n"
    "Gunakan /pskey untuk menyimpan API key Paperspace kamu."
)

_PROJECTS_API_BUG = (
    "⚠️ <b>Fitur ini terbatas</b>\n\n"
    "Endpoint <code>GET /projects</code> dari Paperspace API saat ini mengembalikan "
    "<b>500 Internal Server Error</b> secara konsisten — ini adalah bug di sisi server Paperspace, "
    "bukan di bot ini.\n\n"
    "<b>Yang masih bisa dilakukan:</b>\n"
    "• /newproject — Buat project baru ✅\n"
    "• /delproject — Hapus project dengan ID tertentu ✅\n\n"
    "<i>ID project bisa dicatat saat membuat project baru via /newproject.</i>"
)


# ── /projects ─────────────────────────────────────────────────────────────────

@authorized_only
async def projects_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/projects — inform about the Paperspace API bug for project listing."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_ps_token(user_id)
    if not token:
        await update.effective_message.reply_text(_NO_KEY_MSG, parse_mode="HTML")  # type: ignore[union-attr]
        return

    await update.effective_message.reply_text(_PROJECTS_API_BUG, parse_mode="HTML")  # type: ignore[union-attr]


# ── /newproject ───────────────────────────────────────────────────────────────

@authorized_only
async def newproject_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """/newproject — step 1: ask for project name."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    if not get_ps_token(user_id):
        await update.effective_message.reply_text(_NO_KEY_MSG, parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END

    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "📂 <b>Buat Project Paperspace Baru</b>\n\n"
        "Masukkan <b>nama project</b> yang ingin dibuat.\n\n"
        "Ketik /cancel untuk membatalkan.",
        parse_mode="HTML",
    )
    return PS_PRJ_WAITING_NAME


async def newproject_receive_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 2: receive project name, create the project."""
    name = (update.effective_message.text or "").strip()  # type: ignore[union-attr]
    if not name or len(name) > 100:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "⚠️ Nama tidak valid. Gunakan nama yang lebih singkat (maks 100 karakter).",
            parse_mode="HTML",
        )
        return PS_PRJ_WAITING_NAME

    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_ps_token(user_id)
    if not token:
        await update.effective_message.reply_text(_NO_KEY_MSG, parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END

    msg = await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"⏳ Membuat project <b>{name}</b>...", parse_mode="HTML"
    )
    try:
        client = PaperspaceClient(token)
        try:
            project = await client.create_project(name)
        finally:
            await client.close()

        pid = project.get("id", "-")
        await msg.edit_text(
            f"✅ <b>Project berhasil dibuat!</b>\n\n"
            f"📂 Nama : <b>{name}</b>\n"
            f"🆔 ID   : <code>{pid}</code>\n\n"
            "💡 <b>Simpan ID ini</b> — diperlukan jika ingin menghapus project nanti "
            "karena Paperspace API tidak mendukung listing project saat ini.",
            parse_mode="HTML",
        )
    except PaperspaceError as exc:
        await msg.edit_text(
            f"❌ <b>Gagal membuat project</b>\n\n{exc.message}", parse_mode="HTML"
        )
    except Exception as exc:
        logger.exception("Error in /newproject")
        await msg.edit_text(f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML")

    return ConversationHandler.END


async def newproject_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.effective_message.reply_text("❎ Dibatalkan.", parse_mode="HTML")  # type: ignore[union-attr]
    return ConversationHandler.END


# ── /delproject ───────────────────────────────────────────────────────────────

@authorized_only
async def delproject_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """/delproject — ask for project ID to delete (list not available due to API bug)."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    if not get_ps_token(user_id):
        await update.effective_message.reply_text(_NO_KEY_MSG, parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END

    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "🗑️ <b>Hapus Project Paperspace</b>\n\n"
        "⚠️ Karena Paperspace API tidak mendukung listing project saat ini, "
        "masukkan <b>Project ID</b> secara manual.\n\n"
        "Project ID didapat saat membuat project via /newproject.\n"
        "Contoh: <code>pfr3vb3sjene3</code>\n\n"
        "Ketik /cancel untuk membatalkan.",
        parse_mode="HTML",
    )
    return PS_DEL_WAITING_ID


async def delproject_receive_id(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Receive project ID and delete it."""
    project_id = (update.effective_message.text or "").strip()  # type: ignore[union-attr]
    if not project_id:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "⚠️ ID tidak boleh kosong. Masukkan Project ID:", parse_mode="HTML"
        )
        return PS_DEL_WAITING_ID

    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_ps_token(user_id)
    if not token:
        await update.effective_message.reply_text(_NO_KEY_MSG, parse_mode="HTML")  # type: ignore[union-attr]
        return ConversationHandler.END

    msg = await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"⏳ Menghapus project <code>{project_id}</code>...", parse_mode="HTML"
    )
    try:
        client = PaperspaceClient(token)
        try:
            await client.delete_project(project_id)
        finally:
            await client.close()

        await msg.edit_text(
            f"🗑️ Project <code>{project_id}</code> berhasil dihapus.",
            parse_mode="HTML",
        )
    except PaperspaceError as exc:
        await msg.edit_text(
            f"❌ <b>Gagal menghapus project</b>\n\n{exc.message}", parse_mode="HTML"
        )
    except Exception as exc:
        logger.exception("Error in /delproject")
        await msg.edit_text(f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML")

    return ConversationHandler.END


async def delproject_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.effective_message.reply_text("❎ Dibatalkan.", parse_mode="HTML")  # type: ignore[union-attr]
    return ConversationHandler.END


# ── Registration ──────────────────────────────────────────────────────────────

def get_handlers() -> list:
    newproject_conv = ConversationHandler(
        entry_points=[CommandHandler("newproject", newproject_start)],
        states={
            PS_PRJ_WAITING_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, newproject_receive_name),
            ],
        },
        fallbacks=[CommandHandler("cancel", newproject_cancel)],
        name="newproject_conversation",
    )
    delproject_conv = ConversationHandler(
        entry_points=[CommandHandler("delproject", delproject_command)],
        states={
            PS_DEL_WAITING_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, delproject_receive_id),
            ],
        },
        fallbacks=[CommandHandler("cancel", delproject_cancel)],
        name="delproject_conversation",
    )
    return [
        CommandHandler("projects", projects_command),
        newproject_conv,
        delproject_conv,
    ]
