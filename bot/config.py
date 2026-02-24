from __future__ import annotations

import json
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    TG_BOT_TOKEN: str
    DO_API_TOKEN: str = ""  # optional — user can set per-user DO key via /setkey
    PS_API_TOKEN: str = ""  # optional — user can set per-user Paperspace key via /pskey
    ALLOWED_USER_IDS: list[int] = []
    DATABASE_URL: str = ""  # set automatically by Heroku Postgres add-on

    @field_validator("ALLOWED_USER_IDS", mode="before")
    @classmethod
    def parse_allowed_user_ids(cls, v: Any) -> list[int]:
        """Accept any of these formats from env vars:
        - Already a list: [123, 456]          (local .env)
        - JSON string:    "[123, 456]"        (local .env)
        - Single int:     610029060           (Heroku config:set without brackets)
        - Single string:  "610029060"         (Heroku config:set without brackets)
        - Comma-sep str:  "123,456"           (alternative)
        """
        if isinstance(v, list):
            return [int(i) for i in v]
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            v = v.strip()
            # Try JSON array first: "[123, 456]"
            if v.startswith("["):
                try:
                    parsed = json.loads(v)
                    return [int(i) for i in parsed]
                except (json.JSONDecodeError, ValueError):
                    pass
            # Comma-separated: "123,456" or single "123"
            return [int(i.strip()) for i in v.split(",") if i.strip()]
        return []

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()  # type: ignore[call-arg]
