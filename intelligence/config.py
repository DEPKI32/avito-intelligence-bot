from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_ignore_empty=True, extra="ignore"
    )

    telegram_bot_token: str = ""
    telegram_allowed_user_ids: str = ""
    database_url: str = "sqlite:///data/intelligence.sqlite3"
    check_interval_seconds: int = Field(default=900, ge=300, le=86400)
    request_delay_seconds: int = Field(default=30, ge=10, le=300)
    scan_page_limit: int = Field(default=30, ge=1, le=30)
    watch_pages: int = Field(default=1, ge=1, le=5)
    timezone: str = "Europe/Moscow"
    log_level: str = "INFO"
    ai_enabled: bool = False
    ai_provider: str = "openai-compatible"
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""
    ai_max_images: int = Field(default=2, ge=0, le=5)
    ai_daily_request_limit: int = Field(default=50, ge=0, le=10000)
    quiet_hours_start: int | None = Field(default=None, ge=0, le=23)
    quiet_hours_end: int | None = Field(default=None, ge=0, le=23)

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @property
    def allowed_ids(self) -> set[int]:
        return {
            int(x.strip())
            for x in self.telegram_allowed_user_ids.split(",")
            if x.strip()
        }

    def validate_runtime(self) -> None:
        if not self.telegram_bot_token:
            raise ValueError("Укажите TELEGRAM_BOT_TOKEN в .env")
        if not self.allowed_ids:
            raise ValueError("Укажите TELEGRAM_ALLOWED_USER_IDS в .env")
        if self.ai_enabled and not (
            self.ai_api_key and self.ai_base_url and self.ai_model
        ):
            raise ValueError("Для AI нужны AI_API_KEY, AI_BASE_URL и AI_MODEL")
        if self.database_url.startswith("sqlite:///"):
            Path(self.database_url.removeprefix("sqlite:///")).parent.mkdir(
                parents=True, exist_ok=True
            )
