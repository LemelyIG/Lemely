"""Settings loader: env > .env > lemely.toml > defaults. extra='forbid' everywhere."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


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
    # Per-task model overrides — each falls back to `model` when unset.
    mark_scheme_model: str | None = None
    extraction_model: str | None = None
    correction_model: str | None = None
    generation_model: str | None = None
    study_plan_model: str | None = None
    integrity_model: str | None = None
    scan_metadata_model: str | None = None
    # Escalation: re-mark with a stronger model when marker confidence is low.
    escalation_model: str | None = None
    escalation_confidence_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    # Thinking budget: map of task_tag → token budget (0 = disabled / default).
    # Mark-scheme parsing is enabled by default: the extra reasoning headroom helps
    # the model tag "any N from" pools correctly (is_optional/is_alternative), which
    # avoids spurious mark-point-sum validation failures during structured extraction.
    thinking_budget_for: dict[str, int] = Field(default_factory=lambda: {"mark_scheme": 8000})
    # Pricing overrides: model_name → [input_usd_per_1k, output_usd_per_1k].
    # Built-in defaults exist for gemini-2.5-flash-lite/flash/pro; only set
    # this if you use a different model or the API pricing changes.
    pricing: dict[str, list[float]] = Field(default_factory=dict)
    max_retries: int = Field(default=3, ge=0)
    backoff_seconds: float = Field(default=2.0, gt=0)
    monthly_usd_ceiling: float | None = None
    per_run_token_ceiling: int | None = None

    def model_for(self, task_tag: str) -> str:
        """Resolve the Gemini model name for a task, falling back to the global default."""
        mapping: dict[str, str | None] = {
            "mark_scheme": self.mark_scheme_model,
            "extraction": self.extraction_model,
            "correction": self.correction_model,
            "generation": self.generation_model,
            "study_plan": self.study_plan_model,
            "integrity": self.integrity_model,
            "scan_metadata": self.scan_metadata_model,
        }
        return mapping.get(task_tag) or self.model


class AccuracyEvalSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mark_accuracy_target: float = Field(default=0.95, ge=0.0, le=1.0)
    id_match_rate_target: float = Field(default=0.99, ge=0.0, le=1.0)
    flag_precision_target: float = Field(default=0.99, ge=0.0, le=1.0)
    flag_recall_target: float = Field(default=0.85, ge=0.0, le=1.0)


class DetParserSettings(BaseModel):
    """Tuning knobs for ``DeterministicMarkSchemeParser``.

    All values have sensible defaults; override via ``lemely.toml`` under the
    ``[det_parser]`` section or via ``LEMELY_DET_PARSER__*`` env vars.
    """

    model_config = ConfigDict(extra="forbid")

    # Maximum mark value considered valid for a single mark-point cell.
    # Prevents false-positive column detection on year numbers (e.g. "2019").
    max_mark_per_point: int = Field(default=40, ge=1)

    # PDF page range (0-indexed, exclusive end) to search for GMP text.
    gmp_pages_start: int = Field(default=1, ge=0)
    gmp_pages_end: int = Field(default=4, ge=1)

    # Header keywords used to filter out per-page table-header rows.
    # Extend this set (via TOML list-append) to suppress any additional
    # column-header words specific to your papers.
    header_keywords: frozenset[str] = frozenset(
        {"question", "answer", "marks", "guidance", "notes", "input", "output"}
    )

    # Words on a cover-page line that indicate it is NOT the subject name.
    skip_line_tokens: frozenset[str] = frozenset(
        {"cambridge", "igcse", "mark scheme", "©", "maximum", "published", "confidential"}
    )

    # Reconciliation: compare leaf-mark total to metadata.maximum_mark.
    # When True and the discrepancy exceeds the tolerance, raise ParseError
    # (→ ChainedMarkSchemeParser hands the paper to Gemini).
    escalate_on_mark_mismatch: bool = True
    mark_reconcile_tolerance: int = Field(default=0, ge=0)

    # When True, raise ParseError if any leaf question still has marks
    # derived from the default (mark-cell not parseable → assumed 1).
    escalate_on_defaulted_marks: bool = True


class IntegritySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plagiarism_enabled: bool = True
    ai_detection_enabled: bool = False  # opt-in; Gemini call per question
    plagiarism_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    ai_detection_threshold: float = Field(default=0.80, ge=0.0, le=1.0)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LEMELY_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="forbid",
        # gemini_api_key uses a validation_alias (see below). Without this,
        # model_validate(model_dump()) round-trips (used by test fixtures and
        # any code that reconstructs Settings from a dump) would reject the
        # field-name key as an extra input. Allow both field name and aliases.
        populate_by_name=True,
    )
    gradio: GradioSettings = GradioSettings()
    paths: PathsSettings = PathsSettings()
    logging: LoggingSettings = LoggingSettings()
    gemini: GeminiSettings = GeminiSettings()
    accuracy_eval: AccuracyEvalSettings = AccuracyEvalSettings()
    det_parser: DetParserSettings = DetParserSettings()
    integrity: IntegritySettings = IntegritySettings()
    # Accept the app-specific ``LEMELY_GEMINI_API_KEY`` plus the two unprefixed
    # names the google-genai SDK reads directly (``GEMINI_API_KEY`` /
    # ``GOOGLE_API_KEY``). Without these aliases only ``LEMELY_GEMINI_API_KEY``
    # populated ``settings.gemini_api_key``, so a user who exported only
    # ``GEMINI_API_KEY`` got a working CLI/Gradio but a silently-degraded web
    # portal (which gates AI features on ``settings.gemini_api_key``). One env
    # var now works everywhere. Priority follows declaration order.
    gemini_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("LEMELY_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"),
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Precedence: env > .env > init (which we use for TOML) > file-secrets > defaults
        return (
            env_settings,  # highest: LEMELY_* env vars
            dotenv_settings,  # .env file
            init_settings,  # TOML payload from load_settings(**toml_data)
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


def load_settings(*, toml_path: Path | None = None, cwd: Path | None = None) -> Settings:
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
