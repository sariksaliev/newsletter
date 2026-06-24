from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./data/outreach.db"
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    anthropic_api_key: str = ""
    dialog_model: str = "claude-sonnet-4-20250514"
    openai_api_key: str = ""
    sales_telegram_bot_token: str = ""
    sales_telegram_chat_id: str = ""
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    secret_key: str = "dev-secret"

    warmup_days: int = 3
    warmup_channels_per_day: int = 5
    warmup_messages_per_day: int = 6
    warmup_reactions_per_day: int = 5
    warmup_browse_messages: int = 15

    outreach_daily_limit_per_account: int = 4
    outreach_min_delay_sec: int = 45
    outreach_max_delay_sec: int = 180
    delivery_target_pct: int = 85

    max_accounts_per_proxy: int = 3
    max_profile_edits_per_hour: int = 5
    profile_edit_jitter_min_sec: int = 900
    profile_edit_jitter_max_sec: int = 7200

    @property
    def data_dir(self) -> Path:
        return Path("data")

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def avatars_dir(self) -> Path:
        return self.data_dir / "avatars"


@lru_cache
def get_settings() -> Settings:
    return Settings()
