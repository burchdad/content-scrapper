from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "GhostScraper"
    app_env: str = "development"
    log_level: str = "INFO"
    default_user_agent: str = "Mozilla/5.0 GhostScraper/1.0"
    request_timeout_seconds: int = 30
    max_concurrent_fetches: int = 5
    playwright_headless: bool = True
    storage_root: str = "./storage"
    enable_semantic_extraction: bool = False
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    respect_robots_txt: bool = True
    discovery_provider: str = "auto"
    discovery_timeout_seconds: int = 10
    async_queue_maxsize: int = 100

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_root)


@lru_cache
def get_settings() -> Settings:
    return Settings()
