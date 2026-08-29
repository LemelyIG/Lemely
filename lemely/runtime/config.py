"""Settings loader: env > .env > lemely.toml > defaults. extra='forbid' everywhere."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


def _blank_to_none(value: object) -> object:
    """Map an empty/whitespace-only string to ``None`` so it reads as *unset*.

    Found by P6.10's fresh-clone run. ``docker-compose.yml`` passes optional
    credentials through as ``${GEMINI_API_KEY:-}``, and a shell ``export VAR=``
    does the same thing: the variable is *present* and its value is the empty
    string. Pydantic then builds ``SecretStr("")``, which is not ``None`` — so
    every ``is None`` "not configured" check in the codebase silently reads as
    *configured*, with nothing behind it.

    Two live consequences, both observed on a `make up` stack with no keys
    exported: ``/api/health`` answered ``apiKeyConfigured: true`` while marking
    could not work (making ``docs/deployment.md``'s "or accept
    apiKeyConfigured:false" branch unreachable through Compose), and
    ``GoTrueClient._anon_key`` sent an empty ``apikey`` header instead of
    raising its explicit ``AuthError`` — which local Kong tolerates, so it
    works locally and fails confusingly against Supabase Cloud.

    Applied to the optional *credential* fields only. A blank value there can
    never be meaningful, whereas a blank ordinary string may be.
    """
    if isinstance(value, str) and not value.strip():
        return None
    return value


#: An optional secret where a blank env var means "not set" — see :func:`_blank_to_none`.
OptionalSecret = Annotated[SecretStr | None, BeforeValidator(_blank_to_none)]
#: The plain-text counterpart, for credential fields that are deliberately not secrets.
OptionalCredential = Annotated[str | None, BeforeValidator(_blank_to_none)]


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
    # NOTE (D2.2): this is a *budget* knob — "spend a thinking retry / a Pro call to
    # try to improve this mark before it is final". It is NOT the human-review
    # threshold, which is the separate, deliberately higher
    # ``lemely.core.schemas.REVIEW_CONFIDENCE_THRESHOLD`` (0.90) and is not
    # operator-tunable. The two were coincidentally equal (0.80) before D2.2 and
    # are now free to move independently: raising this one costs Gemini dollars,
    # raising that one costs teacher time.
    escalation_model: str | None = None
    escalation_confidence_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    # Thinking budget: map of task_tag → token budget (0 = disabled / default).
    # Mark-scheme parsing is enabled by default: the extra reasoning headroom helps
    # the model tag "any N from" pools correctly (is_optional/is_alternative), which
    # avoids spurious mark-point-sum validation failures during structured extraction.
    thinking_budget_for: dict[str, int] = Field(default_factory=lambda: {"mark_scheme": 8000})
    # Determinism substrate (M0.2 / #26): generation parameters that affect output
    # reproducibility and therefore must be part of the cache-key fingerprint (see
    # GeminiClient._cache_key / _resolved_gen_params). Global defaults below, with
    # optional per-task overrides analogous to thinking_budget_for. Unset (None)
    # means "let the API pick its own default" — the SDK accepts None for all three.
    temperature: float | None = None
    top_p: float | None = None
    seed: int | None = None
    temperature_for: dict[str, float] = Field(default_factory=dict)
    top_p_for: dict[str, float] = Field(default_factory=dict)
    seed_for: dict[str, int] = Field(default_factory=dict)
    # Pricing overrides: model_name → [input_usd_per_1k, output_usd_per_1k].
    # Built-in defaults exist for gemini-2.5-flash-lite/flash/pro; only set
    # this if you use a different model or the API pricing changes.
    pricing: dict[str, list[float]] = Field(default_factory=dict)
    max_retries: int = Field(default=3, ge=0)
    backoff_seconds: float = Field(default=2.0, gt=0)
    # Persistent, file-backed cumulative-USD hard cap (see lemely.io.cost_ledger).
    # Enforced across process restarts against the ledger, not a per-process global.
    # Default is ACTIVE at $8 — this is the intended hard ceiling for unattended runs.
    total_usd_ceiling: float | None = Field(default=8.0, ge=0)
    # Cumulative-USD thresholds that emit a BUDGET_WARNING event (ntfy) exactly once.
    usd_warning_thresholds: list[float] = Field(default_factory=lambda: [4.0, 6.0])
    # Checked against the module-level process counters in lemely.io.gemini (M0.2 /
    # #26: this ceiling was previously dead in practice because a cache hit always
    # returned before the check ran — cache_mode="bypass" is exactly what arms it).
    # Those counters accumulate for the lifetime of the process deliberately: this
    # budgets one RUN, and one run may drive many sweeps. A multi-sweep run must
    # NOT reset between sweeps — that would turn a run-level budget guard into a
    # per-sweep one and let a runaway script spend without limit. Size it instead:
    # a golden sweep is ~115k tokens, and lemely.toml sets 2,000,000 (~17 sweeps).
    # Left as None (no default ceiling) here: the operative value is set per-run in
    # lemely.toml by whoever is sizing that run.
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

    # #37 (M1.2), ruling B3 (2026-08-26): 0.99 is INHERITED, NOT MEASURED, and is
    # deliberately left untouched. The gate-9 sweep that was meant to re-derive it
    # could not: `id_positional_fallback` fired ZERO times across the 39 leaves it
    # covered, and `id_match_rate` came back 1.0 in BOTH arms. A corpus that scores
    # 1.0 either way says nothing about what genuine id agreement looks like when
    # extraction drifts, so re-deriving 0.99 from it would be PICKING a number, not
    # measuring one. Recorded as a limitation rather than dressed up as a
    # measurement. Do not cite tests/golden/results/2026-08-22-f7be062.json or
    # -79f5fa8.json as evidence the fallback never fired — they predate #37 and are
    # equally consistent with 0 fires and with all 71.
    id_match_rate_target: float = Field(default=0.99, ge=0.0, le=1.0)

    flag_precision_target: float = Field(default=0.99, ge=0.0, le=1.0)
    flag_recall_target: float = Field(default=0.85, ge=0.0, le=1.0)

    # M0.9 (#33): the review-rate two-part ratchet gate (spec §4 M0.9, §5).
    # See lemely.eval.review_gate.evaluate_review_rate_gate.
    review_rate_signal_target: float = Field(default=0.08, ge=0.0, le=1.0)
    review_rate_total_target: float = Field(default=0.10, ge=0.0, le=1.0)
    review_rate_p95_target: float = Field(default=0.15, ge=0.0, le=1.0)
    # Unarmed: a breach is recorded but does not fail the gate.
    #
    # This used to read "Armed at M1 acceptance (spec §7: M0.9 -> M1.1/#36)".
    # #36 is CLOSED, and it is "M1.1 - The confidence unit", different work
    # entirely - so that comment told every reader the arming trigger had
    # already passed and arming was simply not done. It has not passed.
    #
    # #161 has now done the distribution-aware restatement ruling C13 asked
    # for (see review_rate_last_merged below), and it did NOT unblock arming.
    # The measured blocker is not the ratchet limb at all:
    #
    #   signal 0.2903 vs target 0.08   - misses by 3.6x
    #   total  0.2903 vs target 0.10   - misses by 2.9x
    #   p95    0.8333 vs target 0.15   - misses by 5.6x
    #   ratchet ceiling min(0.10, last_merged) = 0.10, so the ratchet limb is
    #     pinned by total_target and CANNOT be moved by last_merged at all
    #     while the measured rate is above 10%.
    #
    # So all four limbs fail, and three of them fail on absolute targets that
    # last_merged does not touch. Arming needs the review rate to actually
    # COME DOWN - M1 accuracy work - not a different statistic.
    #
    # Do NOT flip this to True to "finish" the gate, and do NOT loosen
    # review_rate_signal/total/p95_target to make arming comfortable:
    # MISSION §14 names moving the target to fit the measurement as a
    # programme failure, and the ceiling only ever ratchets down.
    review_rate_ratchet_armed: bool = Field(default=False)
    # The ratchet's comparison rate. The effective ceiling is
    # min(review_rate_total_target, review_rate_last_merged), so this field can
    # only ever tighten the cap, never loosen it.
    #
    # RESTATED 2026-08-28 under ruling C13 (#161, DA33): 0.2903 -> 0.4838.
    #
    # 0.2903 was ONE DRAW - and, being truncated down from 0.29032258..., it
    # was the MINIMUM of the ten. Arming against it fails 10 of 10 unchanged
    # A/A repeats, not the 7 of 10 DA9a estimated. It was never a central
    # estimate and could not be used as one.
    #
    # 0.4838 is the 95th percentile of the beta-binomial predictive
    # distribution for a single new run's flagged-leaf count, Jeffreys prior
    # updated on the pooled 101/310 leaf-repeats of aa-floor-2026-08-23-a
    # (10 repeats x 31 distinct leaves, identical config, cache_mode=bypass).
    # Read it as: an unchanged run exceeds this rate about 5% of the time.
    # Zero of the ten observed repeats exceed it. Derivation and the checks
    # below: BUILD/accuracy-runs/ratchet-161-2026-08-28/.
    #
    # A PREDICTIVE bound, deliberately, not a confidence interval on the mean:
    # the gate judges ONE run, and a CI on the mean narrows with n until it
    # sits inside the spread unchanged code actually produces - which is the
    # DA9a single-figure trap wearing a different hat.
    #
    # Conservative, and not to be sold as tight: per-run counts are UNDER-
    # dispersed relative to binomial (observed sd 0.0415 against 0.0842),
    # because the same 31 leaves recur every repeat and most are
    # deterministic. So this bound is wider than the truth - which errs
    # toward not failing unchanged code, the safe direction for a gate.
    #
    # THIS IS NOT A LOOSENING. The effective ceiling is min(0.10, x) and was
    # 0.10 before this change and is 0.10 after it: 0.2903 and 0.4838 are both
    # above review_rate_total_target, so neither binds. What changed is what
    # the number MEANS - a property of a distribution instead of one draw -
    # and it is now honest about which statistic it is. Tests pin the
    # unchanged ceiling so this cannot be re-read as headroom.
    review_rate_last_merged: float = Field(default=0.4838, ge=0.0, le=1.0)


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
    # #110: two leaf questions in one paper sharing an id. Leaf identity is
    # (paper_id, question_id) per DA6, so duplicates COLLAPSE two questions
    # into one leaf and silently narrow every downstream denominator.
    #
    # Reported, not blocking, and deliberately so: arming routes the paper to
    # the Gemini fallback, which #166 measured failing on ~50% of the schemes
    # det cannot parse and 100% of 0606. That trades a silently-wrong paper for
    # a probably-absent one — a cost and coverage decision, not a tidy-up.
    # See lemely.io.det.reconcile.check for the measured prevalence.
    escalate_on_duplicate_leaf_ids: bool = False
    # #39 bullet 1: a leaf question whose FILTERED primary point sum exceeds its
    # tariff. The invariant is already written, and correctly, on
    # Question.validate_mark_point_sum — but it never RUNS on det output,
    # because rows.py assigns marks/answer_points after construction and
    # pydantic's revalidate_instances defaults to "never". 4 questions across
    # the 479 source schemes reach output in breach.
    #
    # Reported, not blocking, for the same reason as the duplicate-id detector
    # above: arming routes the paper to the Gemini fallback, which #166/DA35
    # measured failing on ~50% of det-failures.
    escalate_on_primary_sum_breach: bool = False


class DatabaseSettings(BaseModel):
    """Connection settings for the application Postgres (local Supabase by default).

    The default URL targets the local Supabase stack (`supabase start`), whose
    Postgres listens on ``127.0.0.1:54322`` with the well-known local dev
    credentials (``postgres:postgres``) — these are non-secret local defaults,
    not production credentials. Override in production via
    ``LEMELY_DATABASE__URL`` (a full SQLAlchemy URL) or ``lemely.toml``.
    """

    model_config = ConfigDict(extra="forbid")

    # Full SQLAlchemy URL. psycopg (v3) sync driver by default.
    url: str = "postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres"
    # Echo SQL to the logger (debugging only).
    echo: bool = False
    # QueuePool sizing.
    pool_size: int = Field(default=5, ge=1)
    max_overflow: int = Field(default=10, ge=0)
    pool_pre_ping: bool = True


class SupabaseSettings(BaseModel):
    """Supabase Auth (GoTrue) validation + admin settings.

    All defaults are the standard local-dev values printed by ``supabase status``.
    The JWT secret and service-role key are used only server-side (JWT validation
    and admin user creation); the anon key is the public client key. None of these
    are production secrets — override via ``LEMELY_SUPABASE__*`` for real deploys.
    """

    model_config = ConfigDict(extra="forbid")

    # Base URL of the local Supabase API gateway (Kong).
    url: str = "http://127.0.0.1:54321"
    # Shared HS256 secret GoTrue signs local JWTs with (well-known local default).
    jwt_secret: SecretStr = SecretStr("super-secret-jwt-token-with-at-least-32-characters-long")
    # Expected `aud` claim for user tokens.
    jwt_audience: str = "authenticated"
    # Public anon key (client-side). Populated from `supabase status` for local dev.
    anon_key: OptionalSecret = None
    # Service-role key (server-side admin: create users, etc.).
    service_role_key: OptionalSecret = None


class AuthSettings(BaseModel):
    """Auth lifecycle tuning (token lifetimes + the phone-OTP challenge store).

    Email/password identity is delegated to Supabase GoTrue; these knobs govern
    the token lifetimes the backend mints under (D1.5 — the backend is the sole
    issuer) and the in-memory parent phone-OTP challenge lifecycle, both owned by
    ``lemely.auth.service.AuthService``. Override via ``lemely.toml`` under the
    ``[auth]`` section or via ``LEMELY_AUTH__*`` env vars.
    """

    model_config = ConfigDict(extra="forbid")

    # Lifetime of a minted access token. Deliberately short: it is a bearer
    # credential with no revocation of its own, so the window in which a leaked
    # one is useful is bounded by this. The client refreshes silently, so
    # shortening it costs the user nothing — see `refresh_token_ttl_seconds`.
    access_token_ttl_seconds: int = Field(default=3600, ge=60)
    # Lifetime of a refresh token — how long a signed-in device stays signed in
    # without re-entering a credential. Long by design; the security comes from
    # the token being bound to a `devices` row, so signing that device out (or
    # evicting it past the 3-device cap) kills it immediately regardless of exp.
    refresh_token_ttl_seconds: int = Field(default=60 * 60 * 24 * 30, ge=300)
    # Time-to-live for a pending OTP challenge, in seconds.
    otp_ttl_seconds: int = Field(default=300, ge=1)
    # Maximum verify attempts before a challenge is locked out.
    otp_max_attempts: int = Field(default=5, ge=1)
    # Number of digits in a generated OTP code.
    otp_length: int = Field(default=6, ge=4, le=10)
    # Minimum seconds between successive OTP issues for the same phone. Stops an
    # attacker resetting the attempt counter by re-requesting before lockout.
    otp_min_resend_seconds: int = Field(default=30, ge=0)


class IntegritySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plagiarism_enabled: bool = True
    ai_detection_enabled: bool = False  # opt-in; Gemini call per question
    plagiarism_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    ai_detection_threshold: float = Field(default=0.80, ge=0.0, le=1.0)


class StorageSettings(BaseModel):
    """Supabase Storage settings for the student self-mark upload path (P2.5).

    Overrides via ``lemely.toml`` under the ``[storage]`` section or
    ``LEMELY_STORAGE__*`` env vars. The bucket/keys used to authenticate against
    Storage are the same ``supabase.url``/``service_role_key`` as GoTrue.
    """

    model_config = ConfigDict(extra="forbid")
    bucket: str = "uploads"
    signed_url_ttl_seconds: int = Field(default=3600, ge=1)


class PushSettings(BaseModel):
    """Web-push (VAPID) application-server credentials (P5.6 chunk B, D5.10).

    Overrides via ``lemely.toml`` under the ``[push]`` section or
    ``LEMELY_PUSH__*`` env vars.

    **All three credential fields default to ``None`` and that is a supported
    state, not a misconfiguration** (D5.9 §4): with any of them missing the
    transport reports itself unavailable and the notification inbox keeps
    working. This machine has no VAPID keys, so treating their absence as an
    error would fail every notification in exactly the environment the tests
    run in.

    ``vapid_public_key`` is deliberately a plain ``str`` and not a
    :class:`SecretStr`: it is handed to every browser that subscribes, so
    wrapping it would imply a confidentiality it does not have. The private
    key is a secret and is typed as one.
    """

    model_config = ConfigDict(extra="forbid")
    # Base64url-encoded uncompressed P-256 point (65 bytes), the value the
    # browser passes to ``pushManager.subscribe`` as ``applicationServerKey``.
    vapid_public_key: OptionalCredential = None
    # Base64url-encoded 32-byte P-256 private scalar.
    vapid_private_key: OptionalSecret = None
    # RFC 8292 ``sub`` claim: a ``mailto:`` or ``https:`` contact for whoever
    # operates this application server, so a push service can reach us.
    vapid_subject: OptionalCredential = None
    # RFC 8030 ``TTL``: how long the push service may hold an undelivered
    # message. A day matches the cadence of the notifications this build sends.
    ttl_seconds: int = Field(default=86400, ge=0)
    # Per-request timeout when talking to a push service. Kept short because
    # every push is a best-effort side effect of an already-committed action
    # (D5.9 §1) and must never make a student wait.
    timeout_seconds: float = Field(default=10.0, gt=0)


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
    storage: StorageSettings = StorageSettings()
    push: PushSettings = PushSettings()
    database: DatabaseSettings = DatabaseSettings()
    supabase: SupabaseSettings = SupabaseSettings()
    auth: AuthSettings = AuthSettings()
    # Accept the app-specific ``LEMELY_GEMINI_API_KEY`` plus the two unprefixed
    # names the google-genai SDK reads directly (``GEMINI_API_KEY`` /
    # ``GOOGLE_API_KEY``). Without these aliases only ``LEMELY_GEMINI_API_KEY``
    # populated ``settings.gemini_api_key``, so a user who exported only
    # ``GEMINI_API_KEY`` got a working CLI/Gradio but a silently-degraded web
    # portal (which gates AI features on ``settings.gemini_api_key``). One env
    # var now works everywhere. Priority follows declaration order.
    gemini_api_key: OptionalSecret = Field(
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
