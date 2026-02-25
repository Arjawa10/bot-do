"""
AMD GPU DigitalOcean Availability Checker — Telegram Bot
Entry point: python main.py
"""

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import TELEGRAM_BOT_TOKEN, CHECK_INTERVAL
from browser_handler import BrowserHandler

# ── Conversation states ──────────────────────────────────────────────
WAITING_EMAIL, WAITING_PASSWORD, WAITING_OTP = range(3)

# ── Shared browser handler instance ──────────────────────────────────
browser_handler = BrowserHandler()

# ── Monitoring state ─────────────────────────────────────────────────
last_check_result: dict | None = None
is_monitoring: bool = False


# =====================================================================
#  /start
# =====================================================================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *AMD GPU DigitalOcean Checker Bot*\n\n"
        "Perintah:\n"
        "/login — Mulai proses login ke DigitalOcean\n"
        "/stop\\_monitor — Hentikan monitoring GPU\n"
        "/status — Cek status monitoring saat ini\n"
        "/check\\_now — Lakukan pengecekan GPU sekarang (manual)"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# =====================================================================
#  /login conversation
# =====================================================================
async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📧 Silakan kirimkan *email* DigitalOcean kamu:", parse_mode="Markdown")
    return WAITING_EMAIL


async def receive_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["email"] = update.message.text.strip()
    await update.message.reply_text("🔑 Sekarang kirimkan *password* kamu:", parse_mode="Markdown")
    return WAITING_PASSWORD


async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = context.user_data.get("email", "")
    password = update.message.text.strip()

    await update.message.reply_text("⏳ Membuka browser dan melakukan login...")

    # Start browser & login
    browser_result = await browser_handler.start_browser()
    if "Failed" in browser_result:
        await update.message.reply_text(
            f"❌ Gagal membuka browser.\n`{browser_result}`",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    result = await browser_handler.login(email, password)

    if result == "OTP_REQUIRED":
        await update.message.reply_text(
            "🔐 DigitalOcean meminta kode *OTP*.\n"
            "Silakan kirimkan kode OTP kamu:",
            parse_mode="Markdown",
        )
        return WAITING_OTP

    elif result == "LOGIN_SUCCESS":
        await update.message.reply_text("✅ Login berhasil! Monitoring GPU dimulai...")
        await _start_monitoring(update, context)
        return ConversationHandler.END

    else:
        await update.message.reply_text(f"❌ Login gagal.\n`{result}`", parse_mode="Markdown")
        await browser_handler.close_browser()
        return ConversationHandler.END


async def receive_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    otp_code = update.message.text.strip()
    await update.message.reply_text("⏳ Mengirim kode OTP...")

    result = await browser_handler.submit_otp(otp_code)

    if result == "LOGIN_SUCCESS":
        await update.message.reply_text("✅ Login berhasil! Monitoring GPU dimulai...")
        await _start_monitoring(update, context)
        return ConversationHandler.END
    else:
        await update.message.reply_text(f"❌ Verifikasi OTP gagal.\n`{result}`", parse_mode="Markdown")
        await browser_handler.close_browser()
        return ConversationHandler.END


async def cancel_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Proses login dibatalkan.")
    await browser_handler.close_browser()
    return ConversationHandler.END


# =====================================================================
#  Monitoring helpers
# =====================================================================
async def _start_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Register a repeating job that checks GPU availability."""
    global is_monitoring
    chat_id = update.effective_chat.id

    # Remove existing jobs for this chat (avoid duplicates)
    current_jobs = context.job_queue.get_jobs_by_name(f"gpu_monitor_{chat_id}")
    for job in current_jobs:
        job.schedule_removal()

    context.job_queue.run_repeating(
        monitor_gpu_job,
        interval=CHECK_INTERVAL,
        first=5,  # first check after 5 seconds
        chat_id=chat_id,
        name=f"gpu_monitor_{chat_id}",
    )
    is_monitoring = True
    print(f"[MONITOR] Monitoring started for chat {chat_id} (interval={CHECK_INTERVAL}s)")


async def monitor_gpu_job(context: ContextTypes.DEFAULT_TYPE):
    """Background job — called by JobQueue every CHECK_INTERVAL seconds."""
    global last_check_result, is_monitoring

    try:
        result = await browser_handler.check_gpu_availability()
        last_check_result = result

        if result["available"]:
            # Notify user GPU is available
            message = (
                f"✅ *[GPU TERSEDIA!]*\n"
                f"🕐 {result['timestamp']}\n"
                f"🔗 {result['current_url']}\n"
                f"📝 {result['message']}\n\n"
                f"🚀 *Membuat GPU Droplet otomatis...*"
            )
            await context.bot.send_message(
                chat_id=context.job.chat_id,
                text=message,
                parse_mode="Markdown",
            )

            # Auto-create GPU Droplet
            create_result = await browser_handler.create_gpu_droplet()
            print(f"[CREATE] Result: {create_result}")

            if create_result.get("success"):
                create_msg = (
                    f"🎉 *GPU DROPLET BERHASIL DIBUAT!*\n\n"
                    f"📦 Plan: MI300X (1 GPU)\n"
                    f"🖼️ Image: PyTorch\n"
                    f"🔑 SSH Key: All keys selected\n"
                    f"🕐 {create_result['timestamp']}\n"
                    f"🔗 {create_result.get('url', 'N/A')}\n\n"
                    f"✅ Droplet sedang diproses. Cek dashboard untuk status."
                )
                # Stop monitoring since droplet is created
                is_monitoring = False
                for job in context.job_queue.get_jobs_by_name(f"gpu_monitor_{context.job.chat_id}"):
                    job.schedule_removal()
                print("[MONITOR] Monitoring stopped — droplet created.")
            else:
                create_msg = (
                    f"⚠️ *GAGAL MEMBUAT DROPLET*\n\n"
                    f"📝 {create_result['message']}\n"
                    f"🕐 {create_result['timestamp']}\n\n"
                    f"⏳ Akan coba lagi pada pengecekan berikutnya..."
                )

            await context.bot.send_message(
                chat_id=context.job.chat_id,
                text=create_msg,
                parse_mode="Markdown",
            )

        else:
            message = (
                f"❌ *[GPU TIDAK TERSEDIA]*\n"
                f"🕐 {result['timestamp']}\n"
                f"📝 {result['message']}\n"
                f"⏳ Pengecekan berikutnya dalam {CHECK_INTERVAL // 60} menit..."
            )

            # Console log
            print(f"[LOG] {result['timestamp']} | Available: {result['available']} | {result['message']}")

            # Send to Telegram
            await context.bot.send_message(
                chat_id=context.job.chat_id,
                text=message,
                parse_mode="Markdown",
            )

    except Exception as e:
        error_msg = f"⚠️ Error saat monitoring GPU:\n`{e}`"
        print(f"[MONITOR ERROR] {e}")
        is_monitoring = False
        try:
            await context.bot.send_message(
                chat_id=context.job.chat_id,
                text=error_msg,
                parse_mode="Markdown",
            )
        except Exception:
            pass


# =====================================================================
#  /stop_monitor
# =====================================================================
async def stop_monitor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_monitoring
    chat_id = update.effective_chat.id

    current_jobs = context.job_queue.get_jobs_by_name(f"gpu_monitor_{chat_id}")
    if not current_jobs:
        await update.message.reply_text("ℹ️ Tidak ada monitoring yang sedang berjalan.")
        return

    for job in current_jobs:
        job.schedule_removal()

    await browser_handler.close_browser()
    is_monitoring = False

    await update.message.reply_text("🛑 Monitoring GPU dihentikan dan browser ditutup.")
    print(f"[MONITOR] Monitoring stopped for chat {chat_id}")


# =====================================================================
#  /status
# =====================================================================
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_monitoring:
        status_text = "🟢 *Monitoring aktif*"
    else:
        status_text = "🔴 *Monitoring tidak aktif*"

    if last_check_result:
        status_text += (
            f"\n\n📊 *Pengecekan terakhir:*\n"
            f"🕐 {last_check_result['timestamp']}\n"
            f"{'✅ Tersedia' if last_check_result['available'] else '❌ Tidak tersedia'}\n"
            f"📝 {last_check_result['message']}"
        )
    else:
        status_text += "\n\nBelum ada pengecekan yang dilakukan."

    await update.message.reply_text(status_text, parse_mode="Markdown")


# =====================================================================
#  /check_now
# =====================================================================
async def check_now_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global last_check_result

    if not is_monitoring:
        await update.message.reply_text("⚠️ Belum login / monitoring belum dimulai. Gunakan /login terlebih dahulu.")
        return

    await update.message.reply_text("⏳ Melakukan pengecekan GPU sekarang...")

    result = await browser_handler.check_gpu_availability()
    last_check_result = result

    if result["available"]:
        message = (
            f"✅ *[GPU TERSEDIA!]*\n"
            f"🕐 {result['timestamp']}\n"
            f"🔗 {result['current_url']}\n"
            f"📝 {result['message']}\n\n"
            f"🚨 AMD GPU DigitalOcean TERSEDIA! Segera buka dan buat droplet!"
        )
    else:
        message = (
            f"❌ *[GPU TIDAK TERSEDIA]*\n"
            f"🕐 {result['timestamp']}\n"
            f"📝 {result['message']}"
        )

    print(f"[LOG] {result['timestamp']} | Available: {result['available']} | {result['message']}")
    await update.message.reply_text(message, parse_mode="Markdown")


# =====================================================================
#  Main
# =====================================================================
def main():
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN belum diset! Buat file .env dan isi token bot Telegram.")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Conversation handler untuk login flow
    login_conv = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            WAITING_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_email)],
            WAITING_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password)],
            WAITING_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_otp)],
        },
        fallbacks=[CommandHandler("cancel", cancel_login)],
    )

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(login_conv)
    app.add_handler(CommandHandler("stop_monitor", stop_monitor_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("check_now", check_now_cmd))

    print("🤖 Bot is running... Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
