"""Application settings loaded from backend/.env using absolute pathing."""

from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    """Runtime configuration with safe production defaults."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
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

    # ── Step 3 RAG & LLM configuration ──────────────────────────────────
    llm_provider: Literal["gemini", "groq", "ollama"] = Field(default="gemini")
    gemini_api_key: Optional[SecretStr] = Field(default=None)
    groq_api_key: Optional[SecretStr] = Field(default=None)
    ollama_base_url: str = Field(default="http://localhost:11434")

    gemini_model: str = Field(default="gemini-2.5-flash")
    groq_model: str = Field(default="llama-3.3-70b-versatile")
    ollama_model: str = Field(default="llama3.2")

    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5")
    chroma_path: str = Field(default="./chroma_data")

    max_summary_calls: int = Field(default=60, ge=1)
    llm_timeout_seconds: int = Field(default=30, ge=1)
    llm_max_retries: int = Field(default=3, ge=0)

    retrieval_top_k_each: int = Field(default=20, ge=1)
    retrieval_top_k_final: int = Field(default=6, ge=1)
    rrf_k: int = Field(default=60, ge=1)

    min_confidence: float = Field(default=0.3, ge=0.0, le=1.0)

    def model_post_init(self, __context: Any) -> None:
        """Resolve relative database and chroma paths against the backend folder."""
        # 1. Resolve relative SQLite URL against BACKEND_DIR
        if self.database_url.startswith("sqlite:///./"):
            rel_file = self.database_url.removeprefix("sqlite:///./")
            abs_path = (BACKEND_DIR / rel_file).resolve().as_posix()
            self.database_url = f"sqlite:///{abs_path}"
        elif self.database_url.startswith("sqlite:///") and not self.database_url.startswith("sqlite:////"):
            candidate = self.database_url.removeprefix("sqlite:///")
            p = Path(candidate)
            if not p.is_absolute():
                abs_path = (BACKEND_DIR / candidate).resolve().as_posix()
                self.database_url = f"sqlite:///{abs_path}"

        # 2. Resolve relative chroma_path against BACKEND_DIR
        cp = Path(self.chroma_path)
        if not cp.is_absolute():
            self.chroma_path = str((BACKEND_DIR / cp).resolve())

    @property
    def cors_origins(self) -> list[str]:
        """Parse comma-separated CORS origins into a list."""
        return [part.strip() for part in self.allowed_origins.split(",") if part.strip()]

    @property
    def is_gemini_key_configured(self) -> bool:
        """Check whether GEMINI_API_KEY is non-empty without exposing it."""
        if not self.gemini_api_key:
            return False
        return bool(self.gemini_api_key.get_secret_value().strip())

    @property
    def is_groq_key_configured(self) -> bool:
        """Check whether GROQ_API_KEY is non-empty without exposing it."""
        if not self.groq_api_key:
            return False
        return bool(self.groq_api_key.get_secret_value().strip())


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
