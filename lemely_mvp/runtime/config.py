"""Settings loader: env > .env > lemely.toml > defaults. extra='forbid' everywhere."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GradioSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str = "127.0.0.1"
    port: int = Field(default=7860, ge=1, le=65535)
    max_file_size_mb: int = Field(default=25, ge=1)


class PathsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources_dir: Path = Path("Sources")
    output_dir: Path = Path("outputs")
    cache_dir: Path = Path(".lemely-cache")


class LoggingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    format: Literal["auto", "json", "console"] = "auto"


class GeminiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = "gemini-2.5-flash"
    max_retries: int = Field(default=3, ge=0)
    backoff_seconds: float = Field(default=2.0, gt=0)
    monthly_usd_ceiling: float | None = None
    per_run_token_ceiling: int | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LEMELY_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="forbid",
    )
    gradio: GradioSettings = GradioSettings()
    paths: PathsSettings = PathsSettings()
    logging: LoggingSettings = LoggingSettings()
    gemini: GeminiSettings = GeminiSettings()
    gemini_api_key: SecretStr | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        # Precedence: env > .env > init (which we use for TOML) > file-secrets > defaults
        return (
            env_settings,        # highest: LEMELY_* env vars
            dotenv_settings,     # .env file
            init_settings,       # TOML payload from load_settings(**toml_data)
            file_secret_settings,
        )


def _discover_toml(cwd: Path) -> Path | None:
    cwd_toml = cwd / "lemely.toml"
    if cwd_toml.is_file():
        return cwd_toml
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    home_toml = Path(xdg) / "lemely" / "lemely.toml"
    if home_toml.is_file():
        return home_toml
    return None


def load_settings(
    *, toml_path: Path | None = None, cwd: Path | None = None
) -> Settings:
    """Load Settings with precedence: env > .env > TOML > defaults.

    Args:
        toml_path: explicit TOML path (from --config). If None, discover.
        cwd: working directory for TOML discovery (defaults to Path.cwd()).
    """
    cwd = cwd or Path.cwd()
    toml = toml_path if toml_path is not None else _discover_toml(cwd)
    if toml is None:
        return Settings()
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore[no-redef]
    with toml.open("rb") as fh:
        toml_data = tomllib.load(fh)
    return Settings(**toml_data)
