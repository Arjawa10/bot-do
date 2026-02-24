"""Per-user API key storage — supports DigitalOcean AND Paperspace keys.

Storage schema (per user_id):
  {
    "do": {
      "keys":   {"Personal": "dop_v1_xxx", "Work": "dop_v1_yyy"},
      "active": "Personal"
    },
    "ps": {
      "keys":   {"MyTeam": "ps_abc123"},
      "active": "MyTeam"
    }
  }

Backward-compatibility: older records without the "do"/"ps" wrapper are
transparently migrated on first read.

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
    """Create or migrate the user_api_keys table.

    Old schema: (user_id BIGINT PK, token TEXT)
    Mid schema: (user_id BIGINT PK, data JSONB)  — single DO key namespace
    New schema: same JSONB column, but data contains {"do": {...}, "ps": {...}}

    Migration happens transparently in _load().
    """
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

            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'user_api_keys'
                  AND column_name = 'token'
                """
            )
            old_schema = cur.fetchone() is not None

            if old_schema:
                logger.info("Old schema detected — migrating 'token' column to JSONB 'data'.")

                cur.execute(
                    """
                    ALTER TABLE user_api_keys
                    ADD COLUMN IF NOT EXISTS data JSONB NOT NULL DEFAULT '{}'
                    """
                )

                cur.execute("SELECT user_id, token FROM user_api_keys WHERE token IS NOT NULL")
                rows = cur.fetchall()
                for uid, token in rows:
                    migrated = json.dumps({
                        "do": {
                            "keys":   {"Default": token},
                            "active": "Default",
                        },
                        "ps": {},
                    })
                    cur.execute(
                        "UPDATE user_api_keys SET data = %s WHERE user_id = %s",
                        (migrated, uid),
                    )
                logger.info("Migrated %d rows to new schema.", len(rows))

                cur.execute("ALTER TABLE user_api_keys DROP COLUMN IF EXISTS token")
                logger.info("Dropped old 'token' column.")

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

def _raw_load(user_id: int) -> dict:
    """Load the raw top-level user record from storage."""
    try:
        return _pg_load(user_id) if _use_postgres() else _json_load(user_id)
    except Exception as exc:
        logger.error("_raw_load failed user_id=%s: %s", user_id, exc)
        return {}


def _migrate_if_needed(raw: dict) -> dict:
    """Migrate older storage formats to the new dual-namespace format.

    Old format (mid schema): {"keys": {...}, "active": "..."}
    New format: {"do": {"keys": {...}, "active": "..."}, "ps": {}}
    """
    if "do" not in raw and "ps" not in raw:
        if "keys" in raw or "active" in raw:
            logger.info("Migrating mid-schema DO keys to new dual-namespace format.")
            return {
                "do": {
                    "keys":   raw.get("keys", {}),
                    "active": raw.get("active"),
                },
                "ps": {},
            }
        return {"do": {}, "ps": {}}
    return raw


def _load(user_id: int) -> dict:
    """Load & migrate user record, returning {"do": {...}, "ps": {...}}."""
    raw = _raw_load(user_id)
    data = _migrate_if_needed(raw)
    data.setdefault("do", {}).setdefault("keys", {})
    data.setdefault("ps", {}).setdefault("keys", {})
    return data


def _save(user_id: int, data: dict) -> None:
    try:
        if _use_postgres():
            _pg_save(user_id, data)
        else:
            _json_save(user_id, data)
    except Exception as exc:
        logger.error("_save failed user_id=%s: %s", user_id, exc)
        raise


# ── Namespace helpers ─────────────────────────────────────────────────────────

def _ns_get_all_keys(user_id: int, ns: str) -> dict[str, str]:
    return _load(user_id).get(ns, {}).get("keys", {})


def _ns_get_active_name(user_id: int, ns: str) -> Optional[str]:
    return _load(user_id).get(ns, {}).get("active")


def _ns_get_active_token(user_id: int, ns: str) -> Optional[str]:
    data = _load(user_id)
    ns_data = data.get(ns, {})
    active = ns_data.get("active")
    if active:
        return ns_data.get("keys", {}).get(active)
    return None


def _ns_set_named_key(user_id: int, ns: str, name: str, token: str) -> None:
    data = _load(user_id)
    ns_data = data.setdefault(ns, {"keys": {}})
    ns_data.setdefault("keys", {})[name] = token
    if not ns_data.get("active"):
        ns_data["active"] = name
    _save(user_id, data)
    logger.info("Saved %s key '%s' for user_id=%s", ns, name, user_id)


def _ns_delete_named_key(user_id: int, ns: str, name: str) -> bool:
    data = _load(user_id)
    ns_data = data.get(ns, {})
    keys: dict = ns_data.get("keys", {})
    if name not in keys:
        return False
    del keys[name]
    ns_data["keys"] = keys
    if ns_data.get("active") == name:
        ns_data["active"] = next(iter(keys), None)
    _save(user_id, data)
    logger.info("Deleted %s key '%s' for user_id=%s", ns, name, user_id)
    return True


def _ns_set_active_key(user_id: int, ns: str, name: str) -> bool:
    data = _load(user_id)
    ns_data = data.get(ns, {})
    if name not in ns_data.get("keys", {}):
        return False
    ns_data["active"] = name
    _save(user_id, data)
    logger.info("Switched %s active key to '%s' for user_id=%s", ns, name, user_id)
    return True


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


# ── DigitalOcean — Named key management ───────────────────────────────────────

def set_named_key(user_id: int, name: str, token: str) -> None:
    """Save (or overwrite) a named DO API key. Auto-sets as active if first."""
    _ns_set_named_key(user_id, "do", name, token)


def delete_named_key(user_id: int, name: str) -> bool:
    """Delete a specific named DO key. Returns True if deleted."""
    return _ns_delete_named_key(user_id, "do", name)


def set_active_key(user_id: int, name: str) -> bool:
    """Switch the active DO key. Returns True if successful."""
    return _ns_set_active_key(user_id, "do", name)


def get_all_keys(user_id: int) -> dict[str, str]:
    """Return all named DO keys: {name: token}."""
    return _ns_get_all_keys(user_id, "do")


def get_active_name(user_id: int) -> Optional[str]:
    """Return the name of the currently active DO key, or None."""
    return _ns_get_active_name(user_id, "do")


def get_active_token(user_id: int) -> Optional[str]:
    """Return the token of the currently active DO key, or None."""
    return _ns_get_active_token(user_id, "do")


def has_any_key(user_id: int) -> bool:
    """Return True if the user has at least one stored DO key."""
    return bool(get_all_keys(user_id))


# ── Paperspace — Named key management ────────────────────────────────────────

def ps_set_named_key(user_id: int, name: str, token: str) -> None:
    """Save (or overwrite) a named Paperspace API key."""
    _ns_set_named_key(user_id, "ps", name, token)


def ps_delete_named_key(user_id: int, name: str) -> bool:
    """Delete a specific named Paperspace key. Returns True if deleted."""
    return _ns_delete_named_key(user_id, "ps", name)


def ps_set_active_key(user_id: int, name: str) -> bool:
    """Switch the active Paperspace key. Returns True if successful."""
    return _ns_set_active_key(user_id, "ps", name)


def ps_get_all_keys(user_id: int) -> dict[str, str]:
    """Return all named Paperspace keys: {name: token}."""
    return _ns_get_all_keys(user_id, "ps")


def ps_get_active_name(user_id: int) -> Optional[str]:
    """Return the name of the currently active Paperspace key, or None."""
    return _ns_get_active_name(user_id, "ps")


def ps_get_active_token(user_id: int) -> Optional[str]:
    """Return the token of the currently active Paperspace key, or None."""
    return _ns_get_active_token(user_id, "ps")


def ps_has_any_key(user_id: int) -> bool:
    """Return True if the user has at least one stored Paperspace key."""
    return bool(ps_get_all_keys(user_id))


# ── Compatibility helpers ─────────────────────────────────────────────────────

def set_user_key(user_id: int, token: str, name: str = "Default") -> None:
    """Legacy: save a single DO key under 'name' (default: 'Default')."""
    set_named_key(user_id, name, token)


def get_user_key(user_id: int) -> Optional[str]:
    """Legacy: return the active DO token."""
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
    """Legacy: return True if user has any DO key."""
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


def get_ps_token(user_id: int) -> Optional[str]:
    """Return the best available Paperspace API token for *user_id*.
    Priority: active named key → PS_API_TOKEN env var.
    """
    tok = ps_get_active_token(user_id)
    if tok:
        return tok
    try:
        from bot.config import settings  # noqa: PLC0415
        env = settings.PS_API_TOKEN
        return env if env else None
    except Exception:
        return None
