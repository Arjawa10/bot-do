"""Authorization middleware – restricts bot access to allowed user IDs."""

from __future__ import annotations

import functools
from typing import Any, Callable, Coroutine

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import settings
from bot.utils.logger import setup_logger

logger = setup_logger("auth")


def authorized_only(
    func: Callable[..., Coroutine[Any, Any, Any]],
) -> Callable[..., Coroutine[Any, Any, Any]]:
    """Decorator that checks if the user is in the allowed list."""

    @functools.wraps(func)
    async def wrapper(
        update: Update, context: ContextTypes.DEFAULT_TYPE, *args: Any, **kwargs: Any
    ) -> Any:
        user = update.effective_user
        user_id = user.id if user else None

        if user_id not in settings.ALLOWED_USER_IDS:
            logger.warning(
                "Unauthorized access attempt by user_id=%s username=%s",
                user_id,
                user.username if user else "N/A",
            )
            if update.effective_message:
                await update.effective_message.reply_text("⛔ Akses ditolak.")
            elif update.callback_query:
                await update.callback_query.answer("⛔ Akses ditolak.", show_alert=True)
            return None

        logger.info(
            "Authorized user_id=%s username=%s calling %s",
            user_id,
            user.username if user else "N/A",
            func.__name__,
        )
        return await func(update, context, *args, **kwargs)

    return wrapper
