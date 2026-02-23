from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    TG_BOT_TOKEN: str
    DO_API_TOKEN: str
    ALLOWED_USER_IDS: list[int] = []

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()  # type: ignore[call-arg]
