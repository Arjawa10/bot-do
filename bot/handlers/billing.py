"""/balance and /redeem command handlers — billing management."""

from __future__ import annotations

from telegram import Update
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.middleware.auth import authorized_only
from bot.services.digitalocean import DigitalOceanClient, DigitalOceanError
from bot.storage.api_keys import get_token
from bot.utils.logger import setup_logger

logger = setup_logger("handler.billing")

# ConversationHandler state for /redeem
WAITING_FOR_PROMO = 1


def _format_balance(data: dict) -> str:
    """Format balance API response into a readable message."""
    month_to_date   = data.get("month_to_date_usage", "0.00")
    account_balance = data.get("account_balance", "0.00")
    month_to_date_balance = data.get("month_to_date_balance", "0.00")
    generated_at    = data.get("generated_at", "-")

    # Convert to float for sign comparison
    try:
        balance_float = float(account_balance)
        balance_sign  = "🟢" if balance_float >= 0 else "🔴"
    except ValueError:
        balance_float = 0
        balance_sign  = "⚪"

    return (
        f"💰 <b>Saldo Akun DigitalOcean</b>\n\n"
        f"{balance_sign} <b>Account Balance:</b> <code>${account_balance}</code>\n"
        f"📊 <b>Usage Bulan Ini:</b> <code>${month_to_date}</code>\n"
        f"📉 <b>Balance Bulan Ini:</b> <code>${month_to_date_balance}</code>\n\n"
        f"🕐 <i>Diperbarui: {generated_at[:19].replace('T', ' ')} UTC</i>"
    )


# ── /balance ──────────────────────────────────────────────────────────────────

@authorized_only
async def balance_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/balance — show current account balance."""
    user_id = update.effective_user.id  # type: ignore[union-attr]
    token = get_token(user_id)
    if not token:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "⚠️ API key DigitalOcean belum diset.\nGunakan /setkey untuk menyimpan API key kamu.",
            parse_mode="HTML",
        )
        return

    msg = await update.effective_message.reply_text(  # type: ignore[union-attr]
        "⏳ Mengambil info saldo...", parse_mode="HTML"
    )
    try:
        client = DigitalOceanClient(token)
        try:
            data = await client.get_balance()
        finally:
            await client.close()

        await msg.edit_text(_format_balance(data), parse_mode="HTML")
    except DigitalOceanError as exc:
        await msg.edit_text(exc.message, parse_mode="HTML")
    except Exception as exc:
        logger.exception("Error in /balance")
        await msg.edit_text(f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML")


# ── /redeem ───────────────────────────────────────────────────────────────────

@authorized_only
async def redeem_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """/redeem — start conversation to collect promo code."""
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "🎟️ <b>Redeem Promo Code</b>\n\n"
        "Silakan kirim kode promo/kredit DigitalOcean kamu.\n\n"
        "Ketik /cancel untuk membatalkan.",
        parse_mode="HTML",
    )
    return WAITING_FOR_PROMO


async def receive_promo(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Receive the promo code and redeem it."""
    code = (update.effective_message.text or "").strip()  # type: ignore[union-attr]
    user_id = update.effective_user.id  # type: ignore[union-attr]

    # Delete user's message for security
    try:
        await update.effective_message.delete()  # type: ignore[union-attr]
    except Exception:
        pass

    token = get_token(user_id)
    if not token:
        await update.effective_message.reply_text(  # type: ignore[union-attr]
            "⚠️ API key belum diset. Gunakan /setkey terlebih dahulu.",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    msg = await update.effective_message.reply_text(  # type: ignore[union-attr]
        f"⏳ Meredeem kode <code>{code[:4]}***</code>...", parse_mode="HTML"
    )

    try:
        client = DigitalOceanClient(token)
        try:
            data = await client.redeem_promo_code(code)
        finally:
            await client.close()

        await msg.edit_text(
            f"✅ <b>Promo code berhasil diredeem!</b>\n\n"
            f"{_format_balance(data)}",
            parse_mode="HTML",
        )
    except DigitalOceanError as exc:
        await msg.edit_text(
            f"❌ <b>Gagal meredeem kode</b>\n\n{exc.message}",
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.exception("Error in /redeem")
        await msg.edit_text(f"❌ Terjadi kesalahan: {exc}", parse_mode="HTML")

    return ConversationHandler.END


async def cancel_redeem(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """/cancel inside the redeem conversation."""
    await update.effective_message.reply_text(  # type: ignore[union-attr]
        "❎ Redeem dibatalkan.", parse_mode="HTML"
    )
    return ConversationHandler.END


# ── Registration ──────────────────────────────────────────────────────────────

def get_handlers() -> list:
    """Return handlers for registration."""
    redeem_conv = ConversationHandler(
        entry_points=[CommandHandler("redeem", redeem_start)],
        states={
            WAITING_FOR_PROMO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_promo),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_redeem)],
        name="redeem_conversation",
    )
    return [
        CommandHandler("balance", balance_command),
        redeem_conv,
    ]
