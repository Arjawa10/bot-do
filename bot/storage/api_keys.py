"""Per-user DigitalOcean API key storage (persisted to JSON file)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from bot.utils.logger import setup_logger

logger = setup_logger("storage.api_keys")

# Storage file path — next to this module, in bot/storage/
_STORAGE_FILE = Path(__file__).parent / "user_keys.json"


def _load() -> dict[str, str]:
    """Load the key store from disk. Returns empty dict if file missing."""
    if not _STORAGE_FILE.exists():
        return {}
    try:
        return json.loads(_STORAGE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load api_keys storage: %s", exc)
        return {}


def _save(data: dict[str, str]) -> None:
    """Persist the key store to disk."""
    try:
        _STORAGE_FILE.write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        logger.error("Failed to save api_keys storage: %s", exc)


def set_user_key(user_id: int, token: str) -> None:
    """Save or update the DO API key for the given user."""
    data = _load()
    data[str(user_id)] = token
    _save(data)
    logger.info("Saved DO API key for user_id=%s", user_id)


def get_user_key(user_id: int) -> Optional[str]:
    """Return the stored DO API key for *user_id*, or None if not set."""
    return _load().get(str(user_id))


def delete_user_key(user_id: int) -> bool:
    """Remove the stored key. Returns True if a key was deleted."""
    data = _load()
    if str(user_id) in data:
        del data[str(user_id)]
        _save(data)
        logger.info("Deleted DO API key for user_id=%s", user_id)
        return True
    return False


def has_user_key(user_id: int) -> bool:
    """Return True if the user has a stored API key."""
    return str(user_id) in _load()


def get_token(user_id: int) -> Optional[str]:
    """Return the best available DO API token for *user_id*.

    Priority:
      1. User-specific key stored via /setkey
      2. DO_API_TOKEN from environment / .env (may be empty string)
    Returns None if neither source has a valid token.
    """
    user_key = get_user_key(user_id)
    if user_key:
        return user_key

    # Lazy import to avoid circular deps
    try:
        from bot.config import settings  # noqa: PLC0415
        env_token = settings.DO_API_TOKEN
        return env_token if env_token else None
    except Exception:
        return None
