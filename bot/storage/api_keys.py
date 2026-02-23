"""Per-user DigitalOcean API key storage.

Backend selection (automatic):
  - If DATABASE_URL is set (Heroku Postgres) → PostgreSQL
  - Otherwise → local JSON file (development / non-Heroku)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from bot.utils.logger import setup_logger

logger = setup_logger("storage.api_keys")

# ── Helpers ──────────────────────────────────────────────────────────────────


def _db_url() -> str:
    """Return DATABASE_URL from config (empty string if not set)."""
    try:
        from bot.config import settings  # noqa: PLC0415
        url = settings.DATABASE_URL
        # Heroku gives postgres:// but psycopg2 needs postgresql://
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url
    except Exception:
        return ""


def _use_postgres() -> bool:
    return bool(_db_url())


# ── PostgreSQL backend ────────────────────────────────────────────────────────


def _get_pg_connection():
    """Open a psycopg2 connection."""
    import psycopg2  # noqa: PLC0415
    return psycopg2.connect(_db_url())


def _pg_init() -> None:
    """Create the table if it doesn't exist."""
    with _get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_api_keys (
                    user_id BIGINT PRIMARY KEY,
                    token   TEXT NOT NULL
                )
                """
            )
        conn.commit()


def _pg_set(user_id: int, token: str) -> None:
    with _get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_api_keys (user_id, token)
                VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET token = EXCLUDED.token
                """,
                (user_id, token),
            )
        conn.commit()


def _pg_get(user_id: int) -> Optional[str]:
    with _get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT token FROM user_api_keys WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            return row[0] if row else None


def _pg_delete(user_id: int) -> bool:
    with _get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_api_keys WHERE user_id = %s RETURNING user_id",
                (user_id,),
            )
            deleted = cur.fetchone() is not None
        conn.commit()
        return deleted


def _pg_has(user_id: int) -> bool:
    return _pg_get(user_id) is not None


# ── JSON file backend (local dev) ─────────────────────────────────────────────

_JSON_FILE = Path(__file__).parent / "user_keys.json"


def _json_load() -> dict[str, str]:
    if not _JSON_FILE.exists():
        return {}
    try:
        return json.loads(_JSON_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load api_keys JSON: %s", exc)
        return {}


def _json_save(data: dict[str, str]) -> None:
    try:
        _JSON_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to save api_keys JSON: %s", exc)


def _json_set(user_id: int, token: str) -> None:
    data = _json_load()
    data[str(user_id)] = token
    _json_save(data)


def _json_get(user_id: int) -> Optional[str]:
    return _json_load().get(str(user_id))


def _json_delete(user_id: int) -> bool:
    data = _json_load()
    if str(user_id) in data:
        del data[str(user_id)]
        _json_save(data)
        return True
    return False


def _json_has(user_id: int) -> bool:
    return str(user_id) in _json_load()


# ── Initialisation ────────────────────────────────────────────────────────────

def init_storage() -> None:
    """Call once at startup to ensure the DB table exists (Postgres only)."""
    if _use_postgres():
        try:
            _pg_init()
            logger.info("PostgreSQL storage initialised.")
        except Exception as exc:
            logger.error("Failed to initialise PostgreSQL storage: %s", exc)
    else:
        logger.info("Using local JSON file storage (%s).", _JSON_FILE)


# ── Public API ────────────────────────────────────────────────────────────────


def set_user_key(user_id: int, token: str) -> None:
    """Save or update the DO API key for the given user."""
    try:
        if _use_postgres():
            _pg_set(user_id, token)
        else:
            _json_set(user_id, token)
        logger.info("Saved DO API key for user_id=%s", user_id)
    except Exception as exc:
        logger.error("set_user_key failed for user_id=%s: %s", user_id, exc)
        raise


def get_user_key(user_id: int) -> Optional[str]:
    """Return the stored DO API key for *user_id*, or None if not set."""
    try:
        if _use_postgres():
            return _pg_get(user_id)
        return _json_get(user_id)
    except Exception as exc:
        logger.error("get_user_key failed for user_id=%s: %s", user_id, exc)
        return None


def delete_user_key(user_id: int) -> bool:
    """Remove the stored key. Returns True if a key was deleted."""
    try:
        if _use_postgres():
            deleted = _pg_delete(user_id)
        else:
            deleted = _json_delete(user_id)
        if deleted:
            logger.info("Deleted DO API key for user_id=%s", user_id)
        return deleted
    except Exception as exc:
        logger.error("delete_user_key failed for user_id=%s: %s", user_id, exc)
        return False


def has_user_key(user_id: int) -> bool:
    """Return True if the user has a stored API key."""
    try:
        if _use_postgres():
            return _pg_has(user_id)
        return _json_has(user_id)
    except Exception as exc:
        logger.error("has_user_key failed for user_id=%s: %s", user_id, exc)
        return False


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

    try:
        from bot.config import settings  # noqa: PLC0415
        env_token = settings.DO_API_TOKEN
        return env_token if env_token else None
    except Exception:
        return None
