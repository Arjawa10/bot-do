from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    TG_BOT_TOKEN: str
    DO_API_TOKEN: str = ""  # optional — user can set per-user key via /setkey
    ALLOWED_USER_IDS: list[int] = []
    DATABASE_URL: str = ""  # set automatically by Heroku Postgres add-on

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()  # type: ignore[call-arg]
