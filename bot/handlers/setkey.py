"""/setkey, /mykey, /deletekey, /usekey command handlers.

Flow /setkey:
  1. /setkey             → bot asks: "Apa nama untuk key ini?"
  2. user sends name     → bot asks: "Sekarang kirim API key-nya"
  3. user sends token    → validate → save as named key
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
from bot.storage.api_keys import (
    delete_named_key,
    get_active_name,
    get_all_keys,
    has_any_key,
    set_active_key,
    set_named_key,
)
from bot.utils.logger import setup_logger

logger = setup_logger("handler.setkey")

# ConversationHandler states
WAITING_FOR_NAME, WAITING_FOR_TOKEN = range(2)


# ── /setkey ───────────────────────────────────────────────────────────────────

@authorized_only
async def setkey_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """/setkey — step 1: ask for a key name."""
    keys = get_all_keys(update.effective_user.id)  # type: ignore[union-attr]
    hint = ""
    if keys:
        existing = ", ".join(f"<code>{k}</code>" for k in keys)
        hint = f"\n\n🗂️ Key tersimpan saat ini: {existing}"

    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"🔑 <b>Tambah API Key DigitalOcean</b>{hint}\n\n"
        "📝 <b>Langkah 1/2:</b> Masukkan <b>nama</b> untuk API key ini.\n"
        "Contoh: <code>Personal</code>, <code>Work</code>, <code>Project X</code>\n\n"
        "Ketik /cancel untuk membatalkan.",
        parse_mode="HTML",
    )
    return WAITING_FOR_NAME


async def receive_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 2: receive key name, ask for the token."""
    name = (update.effective_message.text or "").strip()  # type: ignore[union-attr]
    if not name or len(name) > 50:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "⚠️ Nama tidak valid. Gunakan nama singkat (maks 50 karakter).",
            parse_mode="HTML",
        )
        return WAITING_FOR_NAME

    context.user_data["setkey_name"] = name  # type: ignore[index]

    user_id = update.effective_user.id  # type: ignore[union-attr]
    existing_keys = get_all_keys(user_id)
    overwrite_note = ""
    if name in existing_keys:
        overwrite_note = f"\n\n⚠️ Key dengan nama <code>{name}</code> sudah ada dan akan <b>diganti</b>."

    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"✅ Nama: <b>{name}</b>{overwrite_note}\n\n"
        "🔐 <b>Langkah 2/2:</b> Sekarang kirim <b>API key</b> DigitalOcean kamu.\n"
        "Dapatkan di: <a href='https://cloud.digitalocean.com/account/api/tokens'>"
        "cloud.digitalocean.com/account/api/tokens</a>\n\n"
        "Ketik /cancel untuk membatalkan.",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    return WAITING_FOR_TOKEN


async def receive_token(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Step 3: receive token, validate, and save."""
    token = (update.effective_message.text or "").strip()  # type: ignore[union-attr]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    name: str = context.user_data.get("setkey_name", "Default")  # type: ignore[union-attr]

    # Delete the user's message for security
    try:
        await update.effective_message.delete()  # type: ignore[union-attr]
    except Exception:
        pass

    msg = await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"⏳ Memvalidasi API key <b>{name}</b>...", parse_mode="HTML"
    )

    # Validate token
    try:
        client = DigitalOceanClient(token)
        try:
            await client.list_droplets()
        finally:
            await client.close()
    except DigitalOceanError as exc:
        await msg.edit_text(
            f"❌ <b>API key tidak valid</b>\n\n{exc.message}\n\n"
            "Kirim ulang token yang benar atau /cancel untuk membatalkan.",
            parse_mode="HTML",
        )
        return WAITING_FOR_TOKEN
    except Exception as exc:
        logger.exception("Unexpected error validating DO token")
        await msg.edit_text(
            f"❌ Kesalahan validasi: {exc}\n\nCoba lagi atau /cancel.",
            parse_mode="HTML",
        )
        return WAITING_FOR_TOKEN

    # Save named key
    set_named_key(user_id, name, token)
    masked = token[:6] + "…" + token[-4:] if len(token) > 10 else "***"

    # Check if this is now the active key
    active = get_active_name(user_id)
    active_note = (
        f"\n✅ Key <b>{name}</b> sekarang menjadi key aktif."
        if active == name
        else f"\n📌 Key aktif saat ini: <b>{active}</b>\nGunakan /usekey untuk mengganti."
    )

    await msg.edit_text(
        f"✅ <b>API key berhasil disimpan!</b>\n\n"
        f"🏷️ Nama: <b>{name}</b>\n"
        f"🔑 Token: <code>{masked}</code>"
        f"{active_note}\n\n"
        "Gunakan /mykey untuk melihat semua key.",
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def cancel_setkey(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "❎ Dibatalkan.", parse_mode="HTML"
    )
    return ConversationHandler.END


# ── /mykey ────────────────────────────────────────────────────────────────────

@authorized_only
async def mykey_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/mykey — show all stored keys with inline buttons to switch or delete."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    keys = get_all_keys(user_id)
    active = get_active_name(user_id)

    if not keys:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "❌ <b>Belum ada API key tersimpan.</b>\n\nGunakan /setkey untuk menambahkan.",
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
            row.append(InlineKeyboardButton(f"✅ Aktifkan {name}", callback_data=f"usekey_{name}"))
        row.append(InlineKeyboardButton(f"🗑️ Hapus {name}", callback_data=f"delkey_{name}"))
        keyboard.append(row)

    text = (
        "🗝️ <b>API Keys Tersimpan</b>\n\n"
        + "\n".join(lines)
        + f"\n\n📌 <b>Key aktif:</b> {active}\n\n"
        "Gunakan /setkey untuk menambah key baru."
    )
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
    )


@authorized_only
async def usekey_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Inline button: switch active key."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    name = query.data.replace("usekey_", "", 1)  # type: ignore[union-attr]

    if set_active_key(user_id, name):
        await query.edit_message_text(  # type: ignore[union-attr]
            f"✅ Key aktif diganti ke <b>{name}</b>.\n\nGunakan /mykey untuk melihat semua key.",
            parse_mode="HTML",
        )
    else:
        await query.edit_message_text(  # type: ignore[union-attr]
            f"❌ Key <code>{name}</code> tidak ditemukan.", parse_mode="HTML"
        )


@authorized_only
async def delkey_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Inline button: delete a named key."""
    query = update.callback_query
    await query.answer()  # type: ignore[union-attr]
    user_id = update.effective_user.id  # type: ignore[union-attr]
    name = query.data.replace("delkey_", "", 1)  # type: ignore[union-attr]

    deleted = delete_named_key(user_id, name)
    if deleted:
        remaining = get_all_keys(user_id)
        active = get_active_name(user_id)
        if remaining:
            info = f"📌 Key aktif sekarang: <b>{active}</b>"
        else:
            info = "Tidak ada key tersisa. Gunakan /setkey untuk menambah baru."
        await query.edit_message_text(  # type: ignore[union-attr]
            f"🗑️ Key <b>{name}</b> berhasil dihapus.\n\n{info}",
            parse_mode="HTML",
        )
    else:
        await query.edit_message_text(  # type: ignore[union-attr]
            f"⚠️ Key <code>{name}</code> tidak ditemukan.", parse_mode="HTML"
        )


# ── /usekey ───────────────────────────────────────────────────────────────────

@authorized_only
async def usekey_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/usekey — show inline keyboard to switch active key."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    keys = get_all_keys(user_id)
    active = get_active_name(user_id)

    if not keys:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "❌ Belum ada API key. Gunakan /setkey.", parse_mode="HTML"
        )
        return

    keyboard = [
        [InlineKeyboardButton(
            f"{'✅ ' if name == active else ''}{name}",
            callback_data=f"usekey_{name}",
        )]
        for name in keys
    ]
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"📌 <b>Key aktif:</b> {active}\n\nPilih key yang ingin diaktifkan:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── /deletekey ────────────────────────────────────────────────────────────────

@authorized_only
async def deletekey_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/deletekey — show inline keyboard to delete a key."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    keys = get_all_keys(user_id)

    if not keys:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "⚠️ Tidak ada API key tersimpan.", parse_mode="HTML"
        )
        return

    keyboard = [
        [InlineKeyboardButton(f"🗑️ {name}", callback_data=f"delkey_{name}")]
        for name in keys
    ]
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "🗑️ <b>Hapus API Key</b>\n\nPilih key yang ingin dihapus:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Registration ──────────────────────────────────────────────────────────────

def get_handlers() -> list:
    conv = ConversationHandler(
        entry_points=[CommandHandler("setkey", setkey_start)],
        states={
            WAITING_FOR_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name),
            ],
            WAITING_FOR_TOKEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_token),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_setkey)],
        name="setkey_conversation",
    )
    return [
        conv,
        CommandHandler("mykey", mykey_command),
        CommandHandler("deletekey", deletekey_command),
        CommandHandler("usekey", usekey_command),
        CallbackQueryHandler(usekey_callback, pattern=r"^usekey_.+$"),
        CallbackQueryHandler(delkey_callback, pattern=r"^delkey_.+$"),
    ]
