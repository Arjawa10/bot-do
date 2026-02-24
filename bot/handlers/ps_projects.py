"""/projects, /newproject, /delproject — Paperspace project management."""

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

logger = setup_logger("handler.ps_projects")

# Conversation state
PS_PRJ_WAITING_NAME = 0

_NO_KEY_MSG = (
    "⚠️ API key Paperspace belum diset.\n"
    "Gunakan /pskey untuk menyimpan API key Paperspace kamu."
)


def _fmt_project(p: dict) -> str:
    pid = p.get("id", "-")
    name = p.get("name", "Unnamed")
    nb_count = p.get("notebookCount", p.get("deploymentCount", "?"))
    return f"• <b>{name}</b> — <code>{pid}</code>"


# ── /projects ─────────────────────────────────────────────────────────────────

@authorized_only
async def projects_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/projects — list all Paperspace projects."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_ps_token(user_id)
    if not token:
        await update.effective_message.reply_text(_NO_KEY_MSG, parse_mode="HTML")  # type: ignore[union-attr]
        return

    msg = await update.effective_message.reply_text(  # type: ignore[union-attr]
        "⏳ Mengambil daftar project Paperspace...", parse_mode="HTML"
    )
    try:
        client = PaperspaceClient(token)
        try:
            projects = await client.list_projects()
        finally:
            await client.close()

        if not projects:
            await msg.edit_text(
                "📂 Tidak ada project Paperspace.\n\nGunakan /newproject untuk membuat project baru.",
                parse_mode="HTML",
            )
            return

        lines = [_fmt_project(p) for p in projects]
        text = (
            f"📂 <b>Paperspace Projects</b> ({len(projects)} project)\n\n"
            + "\n".join(lines)
            + "\n\n<i>Gunakan /newproject untuk membuat project baru.</i>"
        )
        await msg.edit_text(text, parse_mode="HTML")
    except PaperspaceError as exc:
        await msg.edit_text(exc.message, parse_mode="HTML")
    except Exception as exc:
        logger.exception("Error in /projects")
        await msg.edit_text(f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML")


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
            f"📂 Nama: <b>{name}</b>\n"
            f"🆔 ID: <code>{pid}</code>\n\n"
            "Gunakan /projects untuk melihat semua project.",
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
) -> None:
    """/delproject — show inline keyboard to pick a project to delete."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_ps_token(user_id)
    if not token:
        await update.effective_message.reply_text(_NO_KEY_MSG, parse_mode="HTML")  # type: ignore[union-attr]
        return

    msg = await update.effective_message.reply_text(  # type: ignore[union-attr]
        "⏳ Mengambil daftar project...", parse_mode="HTML"
    )
    try:
        client = PaperspaceClient(token)
        try:
            projects = await client.list_projects()
        finally:
            await client.close()

        if not projects:
            await msg.edit_text(
                "📂 Tidak ada project yang bisa dihapus.", parse_mode="HTML"
            )
            return

        keyboard = [
            [InlineKeyboardButton(
                f"🗑️ {p.get('name', p.get('id', '?'))}",
                callback_data=f"delprj_{p.get('id')}",
            )]
            for p in projects
        ]
        await msg.edit_text(
            "🗑️ <b>Hapus Project Paperspace</b>\n\n"
            "⚠️ <b>Perhatian:</b> menghapus project bisa menghapus semua resource di dalamnya.\n\n"
            "Pilih project yang ingin dihapus:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except PaperspaceError as exc:
        await msg.edit_text(exc.message, parse_mode="HTML")
    except Exception as exc:
        logger.exception("Error in /delproject")
        await msg.edit_text(f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML")


@authorized_only
async def delproject_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Inline button: confirm and delete a project."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    project_id = query.data.replace("delprj_", "", 1)  # type: ignore[union-attr]

    token = get_ps_token(user_id)
    if not token:
        await query.edit_message_text(_NO_KEY_MSG, parse_mode="HTML")  # type: ignore[union-attr]
        return

    await query.edit_message_text(  # type: ignore[union-attr]
        f"⏳ Menghapus project <code>{project_id}</code>...", parse_mode="HTML"
    )
    try:
        client = PaperspaceClient(token)
        try:
            await client.delete_project(project_id)
        finally:
            await client.close()

        await query.edit_message_text(  # type: ignore[union-attr]
            f"🗑️ Project <code>{project_id}</code> berhasil dihapus.\n\n"
            "Gunakan /projects untuk melihat sisa project.",
            parse_mode="HTML",
        )
    except PaperspaceError as exc:
        await query.edit_message_text(  # type: ignore[union-attr]
            f"❌ <b>Gagal menghapus project</b>\n\n{exc.message}", parse_mode="HTML"
        )
    except Exception as exc:
        logger.exception("Error in delproject callback")
        await query.edit_message_text(  # type: ignore[union-attr]
            f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML"
        )


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
    return [
        CommandHandler("projects", projects_command),
        newproject_conv,
        CommandHandler("delproject", delproject_command),
        CallbackQueryHandler(delproject_callback, pattern=r"^delprj_.+$"),
    ]
