"""Application configuration.

All environment-specific values live here. Nothing else in the application
reads ``os.environ`` directly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, populated from environment variables or ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -----------------------------------------------------
    app_name: str = "CodeOops API"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    environment: str = Field(default="development")
    debug: bool = Field(default=True)

    # --- HTTP ------------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8000

    # Comma-separated in the environment, list in code. NoDecode: pydantic-settings
    # otherwise tries to JSON-decode a list-typed env var itself before any
    # field_validator runs, and raises on a plain "a,b,c" string instead of
    # ever reaching _split_csv below — only surfaces once this is actually
    # set via a real env var rather than left on its Python default.
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:4200"]
    )

    # --- Repository policy ----------------------------------------------
    # Only these Git hosts may be submitted. GitHub only for this phase.
    allowed_repository_hosts: Annotated[list[str], NoDecode] = Field(
        default=["github.com"]
    )
    default_branch_fallback: str = "main"

    # --- Documentation provider -----------------------------------------
    # Set to "codewiki" to wire the real adapter. Unset (the default) means
    # no provider is connected, and the application must not pretend
    # otherwise. See app/providers/documentation_provider.py.
    documentation_provider: str | None = Field(default=None)

    # --- CodeWiki ----------------------------------------------------------
    # Base URL of a running CodeWiki web app instance, e.g. http://localhost:8000.
    codewiki_base_url: str | None = Field(default=None)
    # Host directory CodeWiki mounts at /app/output — the shared volume its
    # docs_path values are read relative to. Required for a real integration.
    codewiki_output_root: str | None = Field(default=None)
    # Where CodeOops copies verified CodeWiki bytes on job completion, keyed
    # by CodeOops's own job id (not CodeWiki's, which is per-repository only).
    artifact_root: str = Field(default="./var/artifacts")
    codewiki_timeout_seconds: float = Field(default=7200.0)
    codewiki_poll_interval_seconds: float = Field(default=5.0)

    # --- ZIP upload ingestion ---------------------------------------------
    # Untrusted-input limits enforced before/while extracting an uploaded
    # archive. Extracted repositories are written under codewiki_output_root
    # (required for uploads — CodeWiki must be able to see them on its own
    # shared volume), never anywhere else.
    # 2GB compressed ceiling per product requirement; extracted ceiling is
    # set well above that (repos routinely decompress to several times their
    # zip size) rather than at a tight 1:1 ratio.
    upload_max_archive_bytes: int = Field(default=2 * 1024 * 1024 * 1024)
    upload_max_extracted_bytes: int = Field(default=8 * 1024 * 1024 * 1024)
    upload_max_file_count: int = Field(default=200_000)

    @field_validator("allowed_origins", "allowed_repository_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Allow ``A,B,C`` in the environment for list-valued settings."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
