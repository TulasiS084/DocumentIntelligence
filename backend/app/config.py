"""Application settings loaded from the environment."""

from __future__ import annotations

import tempfile
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration with safe production defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    clone_timeout_seconds: int = Field(default=60, ge=1)
    max_clone_size_bytes: int = Field(default=300 * 1024 * 1024, ge=1)
    max_files_analyzed: int = Field(default=2000, ge=1)
    max_file_size_bytes: int = Field(default=1024 * 1024, ge=1)
    temp_dir: str = Field(default_factory=tempfile.gettempdir)
    database_url: str = Field(default="sqlite:///./repo_analyzer.db")
    allowed_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173"
    )
    log_level: str = Field(default="INFO")

    @property
    def cors_origins(self) -> list[str]:
        """Parse comma-separated CORS origins into a list."""
        return [part.strip() for part in self.allowed_origins.split(",") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
