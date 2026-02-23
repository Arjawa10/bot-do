"""Per-user DigitalOcean API key storage — supports multiple named keys per user.

Storage schema (per user_id):
  {
    "keys":   {"Personal": "dop_v1_xxx", "Work": "dop_v1_yyy"},
    "active": "Personal"   ← name of the currently active key
  }

Backend selection (automatic):
  - DATABASE_URL set → PostgreSQL  (Heroku)
  - Otherwise        → local JSON file  (development)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from bot.utils.logger import setup_logger

logger = setup_logger("storage.api_keys")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _db_url() -> str:
    try:
        from bot.config import settings  # noqa: PLC0415
        url = settings.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url
    except Exception:
        return ""


def _use_postgres() -> bool:
    return bool(_db_url())


# ── PostgreSQL backend ────────────────────────────────────────────────────────

def _get_pg_connection():
    import psycopg2  # noqa: PLC0415
    return psycopg2.connect(_db_url())


def _pg_init() -> None:
    with _get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_api_keys (
                    user_id BIGINT PRIMARY KEY,
                    data    JSONB NOT NULL DEFAULT '{}'
                )
                """
            )
        conn.commit()


def _pg_load(user_id: int) -> dict:
    with _get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT data FROM user_api_keys WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            return row[0] if row else {}


def _pg_save(user_id: int, data: dict) -> None:
    with _get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_api_keys (user_id, data)
                VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data
                """,
                (user_id, json.dumps(data)),
            )
        conn.commit()


def _pg_delete_user(user_id: int) -> None:
    with _get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_api_keys WHERE user_id = %s", (user_id,))
        conn.commit()


# ── JSON file backend (local dev) ─────────────────────────────────────────────

_JSON_FILE = Path(__file__).parent / "user_keys.json"


def _json_load_all() -> dict:
    if not _JSON_FILE.exists():
        return {}
    try:
        return json.loads(_JSON_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load JSON storage: %s", exc)
        return {}


def _json_save_all(data: dict) -> None:
    try:
        _JSON_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to save JSON storage: %s", exc)


def _json_load(user_id: int) -> dict:
    return _json_load_all().get(str(user_id), {})


def _json_save(user_id: int, data: dict) -> None:
    all_data = _json_load_all()
    all_data[str(user_id)] = data
    _json_save_all(all_data)


def _json_delete_user(user_id: int) -> None:
    all_data = _json_load_all()
    all_data.pop(str(user_id), None)
    _json_save_all(all_data)


# ── Internal load/save dispatch ───────────────────────────────────────────────

def _load(user_id: int) -> dict:
    """Load user record: {"keys": {...}, "active": "..."}"""
    try:
        raw = _pg_load(user_id) if _use_postgres() else _json_load(user_id)
        # Ensure correct structure
        if "keys" not in raw:
            raw["keys"] = {}
        return raw
    except Exception as exc:
        logger.error("_load failed user_id=%s: %s", user_id, exc)
        return {"keys": {}}


def _save(user_id: int, data: dict) -> None:
    try:
        if _use_postgres():
            _pg_save(user_id, data)
        else:
            _json_save(user_id, data)
    except Exception as exc:
        logger.error("_save failed user_id=%s: %s", user_id, exc)
        raise


# ── Initialisation ────────────────────────────────────────────────────────────

def init_storage() -> None:
    """Call once at startup (Postgres only: ensure table exists)."""
    if _use_postgres():
        try:
            _pg_init()
            logger.info("PostgreSQL storage initialised.")
        except Exception as exc:
            logger.error("Failed to init PostgreSQL storage: %s", exc)
    else:
        logger.info("Using local JSON file storage (%s).", _JSON_FILE)


# ── Named key management ──────────────────────────────────────────────────────

def set_named_key(user_id: int, name: str, token: str) -> None:
    """Save (or overwrite) a named API key. Auto-sets as active if it's the first."""
    data = _load(user_id)
    data.setdefault("keys", {})[name] = token
    if not data.get("active"):
        data["active"] = name
    _save(user_id, data)
    logger.info("Saved key '%s' for user_id=%s", name, user_id)


def delete_named_key(user_id: int, name: str) -> bool:
    """Delete a specific named key. Returns True if deleted.
    If the deleted key was active, switch to first remaining key (or clear active).
    """
    data = _load(user_id)
    keys: dict = data.get("keys", {})
    if name not in keys:
        return False
    del keys[name]
    data["keys"] = keys
    if data.get("active") == name:
        data["active"] = next(iter(keys), None)
    _save(user_id, data)
    logger.info("Deleted key '%s' for user_id=%s", name, user_id)
    return True


def set_active_key(user_id: int, name: str) -> bool:
    """Switch the active key. Returns True if successful."""
    data = _load(user_id)
    if name not in data.get("keys", {}):
        return False
    data["active"] = name
    _save(user_id, data)
    logger.info("Switched active key to '%s' for user_id=%s", name, user_id)
    return True


def get_all_keys(user_id: int) -> dict[str, str]:
    """Return all named keys: {name: token}."""
    return _load(user_id).get("keys", {})


def get_active_name(user_id: int) -> Optional[str]:
    """Return the name of the currently active key, or None."""
    return _load(user_id).get("active")


def get_active_token(user_id: int) -> Optional[str]:
    """Return the token of the currently active key, or None."""
    data = _load(user_id)
    active = data.get("active")
    if active:
        return data.get("keys", {}).get(active)
    return None


def has_any_key(user_id: int) -> bool:
    """Return True if the user has at least one stored key."""
    return bool(_load(user_id).get("keys"))


# ── Compatibility helpers ─────────────────────────────────────────────────────
# These keep the old public API working for all existing handlers.

def set_user_key(user_id: int, token: str, name: str = "Default") -> None:
    """Legacy: save a single key under 'name' (default: 'Default')."""
    set_named_key(user_id, name, token)


def get_user_key(user_id: int) -> Optional[str]:
    """Legacy: return the active token."""
    return get_active_token(user_id)


def delete_user_key(user_id: int) -> bool:
    """Legacy: delete ALL keys for the user."""
    try:
        if _use_postgres():
            _pg_delete_user(user_id)
        else:
            _json_delete_user(user_id)
        return True
    except Exception:
        return False


def has_user_key(user_id: int) -> bool:
    """Legacy: return True if user has any key."""
    return has_any_key(user_id)


def get_token(user_id: int) -> Optional[str]:
    """Return the best available DO API token for *user_id*.
    Priority: active named key → DO_API_TOKEN env var.
    """
    tok = get_active_token(user_id)
    if tok:
        return tok
    try:
        from bot.config import settings  # noqa: PLC0415
        env = settings.DO_API_TOKEN
        return env if env else None
    except Exception:
        return None
