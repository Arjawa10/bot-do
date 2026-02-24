"""/pskey, /mypsk, /usepsk, /deletepsk — Paperspace API key management.

Flow /pskey:
  1. /pskey             → bot asks: "Apa nama untuk key ini?"
  2. user sends name    → bot asks: "Sekarang kirim API key Paperspace-nya"
  3. user sends token   → validate → save as named key
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
from bot.storage.api_keys import (
    ps_delete_named_key,
    ps_get_active_name,
    ps_get_all_keys,
    ps_has_any_key,
    ps_set_active_key,
    ps_set_named_key,
)
from bot.utils.logger import setup_logger

logger = setup_logger("handler.ps_setkey")

# ConversationHandler states
PS_WAITING_FOR_NAME, PS_WAITING_FOR_TOKEN = range(2)


# ── /pskey ────────────────────────────────────────────────────────────────────

@authorized_only
async def pskey_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """/pskey — step 1: ask for a key name."""
    keys = ps_get_all_keys(update.effective_user.id)  # type: ignore[union-attr]
    hint = ""
    if keys:
        existing = ", ".join(f"<code>{k}</code>" for k in keys)
        hint = f"\n\n🗂️ Key tersimpan saat ini: {existing}"

    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"🔑 <b>Tambah API Key Paperspace</b>{hint}\n\n"
        "📝 <b>Langkah 1/2:</b> Masukkan <b>nama</b> untuk API key ini.\n"
        "Contoh: <code>Personal</code>, <code>Work</code>, <code>MyTeam</code>\n\n"
        "Ketik /cancel untuk membatalkan.",
        parse_mode="HTML",
    )
    return PS_WAITING_FOR_NAME


async def ps_receive_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 2: receive key name, ask for the token."""
    name = (update.effective_message.text or "").strip()  # type: ignore[union-attr]
    if not name or len(name) > 50:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "⚠️ Nama tidak valid. Gunakan nama singkat (maks 50 karakter).",
            parse_mode="HTML",
        )
        return PS_WAITING_FOR_NAME

    context.user_data["pskey_name"] = name  # type: ignore[index]

    user_id = update.effective_user.id  # type: ignore[union-attr]
    existing_keys = ps_get_all_keys(user_id)
    overwrite_note = ""
    if name in existing_keys:
        overwrite_note = f"\n\n⚠️ Key dengan nama <code>{name}</code> sudah ada dan akan <b>diganti</b>."

    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"✅ Nama: <b>{name}</b>{overwrite_note}\n\n"
        "🔐 <b>Langkah 2/2:</b> Sekarang kirim <b>API key</b> Paperspace kamu.\n"
        "Dapatkan di: <a href='https://console.paperspace.com/settings/api'>"
        "console.paperspace.com/settings/api</a>\n\n"
        "Ketik /cancel untuk membatalkan.",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    return PS_WAITING_FOR_TOKEN


async def ps_receive_token(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 3: receive token, validate, and save."""
    token = (update.effective_message.text or "").strip()  # type: ignore[union-attr]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    name: str = context.user_data.get("pskey_name", "Default")  # type: ignore[union-attr]

    # Delete the user's message for security
    try:
        await update.effective_message.delete()  # type: ignore[union-attr]
    except Exception:
        pass

    msg = await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"⏳ Memvalidasi API key Paperspace <b>{name}</b>...", parse_mode="HTML"
    )

    # Validate token
    try:
        client = PaperspaceClient(token)
        try:
            await client.validate_token()
        finally:
            await client.close()
    except PaperspaceError as exc:
        await msg.edit_text(
            f"❌ <b>API key tidak valid</b>\n\n{exc.message}\n\n"
            "Kirim ulang token yang benar atau /cancel untuk membatalkan.",
            parse_mode="HTML",
        )
        return PS_WAITING_FOR_TOKEN
    except Exception as exc:
        logger.exception("Unexpected error validating Paperspace token")
        await msg.edit_text(
            f"❌ Kesalahan validasi: {exc}\n\nCoba lagi atau /cancel.",
            parse_mode="HTML",
        )
        return PS_WAITING_FOR_TOKEN

    # Save named key
    ps_set_named_key(user_id, name, token)
    masked = token[:6] + "…" + token[-4:] if len(token) > 10 else "***"

    # Check if now active
    active = ps_get_active_name(user_id)
    active_note = (
        f"\n✅ Key <b>{name}</b> sekarang menjadi key aktif."
        if active == name
        else f"\n📌 Key aktif saat ini: <b>{active}</b>\nGunakan /usepsk untuk mengganti."
    )

    await msg.edit_text(
        f"✅ <b>API key Paperspace berhasil disimpan!</b>\n\n"
        f"🏷️ Nama: <b>{name}</b>\n"
        f"🔑 Token: <code>{masked}</code>"
        f"{active_note}\n\n"
        "Gunakan /mypsk untuk melihat semua key.",
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def ps_cancel_setkey(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "❎ Dibatalkan.", parse_mode="HTML"
    )
    return ConversationHandler.END


# ── /mypsk ────────────────────────────────────────────────────────────────────

@authorized_only
async def mypsk_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/mypsk — show all stored Paperspace keys."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    keys = ps_get_all_keys(user_id)
    active = ps_get_active_name(user_id)

    if not keys:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "❌ <b>Belum ada API key Paperspace tersimpan.</b>\n\nGunakan /pskey untuk menambahkan.",
            parse_mode="HTML",
        )
        return

    lines = []
    keyboard: list[list[InlineKeyboardButton]] = []
    for name, token in keys.items():
        masked = token[:6] + "…" + token[-4:] if len(token) > 10 else "***"
        active_mark = " ✅" if name == active else ""
        lines.append(f"• <b>{name}</b>{active_mark} — <code>{masked}</code>")
        row = []
        if name != active:
            row.append(InlineKeyboardButton(f"✅ Aktifkan {name}", callback_data=f"usepsk_{name}"))
        row.append(InlineKeyboardButton(f"🗑️ Hapus {name}", callback_data=f"delpsk_{name}"))
        keyboard.append(row)

    text = (
        "🗝️ <b>Paperspace API Keys Tersimpan</b>\n\n"
        + "\n".join(lines)
        + f"\n\n📌 <b>Key aktif:</b> {active}\n\n"
        "Gunakan /pskey untuk menambah key baru."
    )
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
    )


# ── /usepsk callback ──────────────────────────────────────────────────────────

@authorized_only
async def usepsk_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Inline button: switch active Paperspace key."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    name = query.data.replace("usepsk_", "", 1)  # type: ignore[union-attr]

    if ps_set_active_key(user_id, name):
        await query.edit_message_text(  # type: ignore[union-attr]
            f"✅ Paperspace key aktif diganti ke <b>{name}</b>.\n\nGunakan /mypsk untuk melihat semua key.",
            parse_mode="HTML",
        )
    else:
        await query.edit_message_text(  # type: ignore[union-attr]
            f"❌ Key <code>{name}</code> tidak ditemukan.", parse_mode="HTML"
        )


# ── /deletepsk callback ───────────────────────────────────────────────────────

@authorized_only
async def delpsk_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Inline button: delete a named Paperspace key."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    name = query.data.replace("delpsk_", "", 1)  # type: ignore[union-attr]

    deleted = ps_delete_named_key(user_id, name)
    if deleted:
        remaining = ps_get_all_keys(user_id)
        active = ps_get_active_name(user_id)
        info = (
            f"📌 Key aktif sekarang: <b>{active}</b>"
            if remaining
            else "Tidak ada key tersisa. Gunakan /pskey untuk menambah baru."
        )
        await query.edit_message_text(  # type: ignore[union-attr]
            f"🗑️ Key <b>{name}</b> berhasil dihapus.\n\n{info}",
            parse_mode="HTML",
        )
    else:
        await query.edit_message_text(  # type: ignore[union-attr]
            f"⚠️ Key <code>{name}</code> tidak ditemukan.", parse_mode="HTML"
        )


# ── /usepsk command ───────────────────────────────────────────────────────────

@authorized_only
async def usepsk_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/usepsk — show inline keyboard to switch active Paperspace key."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    keys = ps_get_all_keys(user_id)
    active = ps_get_active_name(user_id)

    if not keys:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "❌ Belum ada API key Paperspace. Gunakan /pskey.", parse_mode="HTML"
        )
        return

    keyboard = [
        [InlineKeyboardButton(
            f"{'✅ ' if name == active else ''}{name}",
            callback_data=f"usepsk_{name}",
        )]
        for name in keys
    ]
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"📌 <b>Paperspace key aktif:</b> {active}\n\nPilih key yang ingin diaktifkan:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── /deletepsk command ────────────────────────────────────────────────────────

@authorized_only
async def deletepsk_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/deletepsk — show inline keyboard to delete a Paperspace key."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    keys = ps_get_all_keys(user_id)

    if not keys:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "⚠️ Tidak ada API key Paperspace tersimpan.", parse_mode="HTML"
        )
        return

    keyboard = [
        [InlineKeyboardButton(f"🗑️ {name}", callback_data=f"delpsk_{name}")]
        for name in keys
    ]
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "🗑️ <b>Hapus Paperspace API Key</b>\n\nPilih key yang ingin dihapus:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Registration ──────────────────────────────────────────────────────────────

def get_handlers() -> list:
    conv = ConversationHandler(
        entry_points=[CommandHandler("pskey", pskey_start)],
        states={
            PS_WAITING_FOR_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ps_receive_name),
            ],
            PS_WAITING_FOR_TOKEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ps_receive_token),
            ],
        },
        fallbacks=[CommandHandler("cancel", ps_cancel_setkey)],
        name="pskey_conversation",
    )
    return [
        conv,
        CommandHandler("mypsk", mypsk_command),
        CommandHandler("deletepsk", deletepsk_command),
        CommandHandler("usepsk", usepsk_command),
        CallbackQueryHandler(usepsk_callback, pattern=r"^usepsk_.+$"),
        CallbackQueryHandler(delpsk_callback, pattern=r"^delpsk_.+$"),
    ]
