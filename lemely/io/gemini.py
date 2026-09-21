"""Shared Gemini AI client: retry, persistent cache, cost guard, structured logging."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, TypeVar, cast

import structlog
from pydantic import BaseModel
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from lemely.io.cost_ledger import CostLedger
from lemely.runtime.config import Settings
from lemely.runtime.errors import CostCeilingError, ExternalServiceError, ParseError
from lemely.runtime.events import EventType, bus

_T = TypeVar("_T", bound=BaseModel)

# Output-token cap sent on every call. A module constant rather than a literal
# because it feeds the cache-key fingerprint (spec 3.3): changing it changes what
# the model may return, so it must invalidate cached replies.
_MAX_OUTPUT_TOKENS: int = 65536

# I1: the SDK's `types.PartMediaResolutionLevel` enum members are named
# "MEDIA_RESOLUTION_MEDIUM" etc., not the short "medium"/"high" the plan
# (and every caller of `generate_structured`/`_call_once`) writes — passing
# the short form straight through hits `CaseInSensitiveEnum._missing_`'s
# fallback (it only tries `.upper()`/`.lower()` against the *member name*,
# so "MEDIUM" still doesn't match "MEDIA_RESOLUTION_MEDIUM"), which emits a
# UserWarning and silently sends the literal string "medium" as the level
# instead of a real enum value. Mapped here once so every call site can keep
# using the short, prompt-and-plan-matching form.
_MEDIA_RESOLUTION_LEVELS: dict[str, str] = {
    "low": "MEDIA_RESOLUTION_LOW",
    "medium": "MEDIA_RESOLUTION_MEDIUM",
    "high": "MEDIA_RESOLUTION_HIGH",
    "ultra_high": "MEDIA_RESOLUTION_ULTRA_HIGH",
}

# Built-in pricing table: model-name substring → (input_usd_per_1k, output_usd_per_1k).
# GA rates (M0.2 / #26) — the table previously carried the preview price sheet
# (flash: $0.150/$0.600 per 1M) while the configured model is GA gemini-2.5-flash
# ($0.30/$2.50 per 1M), which understated real spend against total_usd_ceiling by
# 2-4x. Matched by substring so "gemini-2.5-flash-preview-05-20" still maps to the
# flash row (a *model name* can legitimately say "preview" without the pricing
# tier being the old preview tier).
#
# F1 (Gemini 3.x migration, 2026-09-17): 3.x rows added below at the current
# promotional GA rate (re-verified against live docs 17 Sep). Corrected on
# review (2026-09-17): 3.8/3.7/3.6-flash bill $0.75/$3.75 per 1M through
# 2026-12-31 ONLY, then $1.50/$7.50 from 2027-01-01. `total_usd_ceiling`
# (enforced against a ledger computed from this table, see `_call_once`)
# would otherwise be enforced against a stale rate once it doubles — the
# $14 ceiling would then trip at roughly $28 of real spend.
#
# US-026: date-gated below. `gemini-3.8-flash`/`-3.7-flash`/`-3.6-flash` are
# NOT static keys in `_DEFAULT_PRICING` — `_resolve_pricing` merges a
# date-selected rate for them into a COPY of this table before running its one
# length-descending substring match, so a future maintainer adding a correctly
# priced `gemini-3.8-flash-<suffix>` row still wins on key length exactly as
# the existing sort intends (a promo model is never allowed a second, earlier
# matching path that could shadow it). `FLASH_3X_PROMO_END_DATE` is the single
# constant both that merge and `promo_pricing_status` (surfaced by `lemely
# doctor`) read, so a future price change is one edit. `_resolve_pricing`'s
# `today` clock defaults to the module-level `_today`, resolved by name at
# call time so `unittest.mock.patch("lemely.io.gemini._today", ...)` reaches
# it (as well as the explicit `today=` override tests use to pin either side
# of the boundary).
FLASH_3X_PROMO_END_DATE: date = date(2026, 12, 31)

_FLASH_3X_PROMO_MODELS: tuple[str, ...] = (
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
)
_FLASH_3X_PROMO_RATE: tuple[float, float] = (0.000750, 0.003750)
_FLASH_3X_POST_PROMO_RATE: tuple[float, float] = (0.001500, 0.007500)

# US-034: `gemini-3.5-flash` had no row here, so the length-descending
# substring match below fell through to the unrecognised-model fallback
# (`gemini-2.5-flash`'s rate) for it — the PRD's headline evidence for this
# story cited a model, `gemini-3.9-pro`, that does not exist on Google's
# published price list and must not be repeated as a real measurement; the
# one genuinely missing row was `gemini-3.5-flash`. No currently configured
# model resolved through the fallback (see `fallback_pricing_status` below),
# so this is a pre-emptive fix, not a correction of an active overrun.
# Source: https://ai.google.dev/gemini-api/docs/pricing, retrieved
# 2026-09-21: $1.50 / $9.00 per 1M tokens. That page was also checked for a
# 2027-01-01 scheduled increase on `gemini-3.5-flash` (the mechanism
# `gemini-3.8/3.7/3.6-flash` use, see `FLASH_3X_PROMO_END_DATE` below) —
# unlike those three, the page states no scheduled change for
# `gemini-3.5-flash`, so this is a plain static row rather than a
# date-gated one. Note `gemini-2.5-pro` below is priced <=200k context per
# the same page; if the real rate differs above that context window, this
# table does not yet account for it (out of scope for US-034).
_DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash-lite": (0.000100, 0.000400),
    "gemini-2.5-flash": (0.000300, 0.002500),
    "gemini-2.5-pro": (0.001250, 0.010000),
    "gemini-3.5-flash-lite": (0.000300, 0.002500),
    "gemini-3.5-flash": (0.001500, 0.009000),
}


def _today() -> date:
    """The module clock.

    A plain function, looked up by name (never captured as a bound default)
    at every call site that needs "now" — `unittest.mock.patch
    ("lemely.io.gemini._today", ...)` therefore reaches every caller,
    `_resolve_pricing` included.
    """
    return datetime.now(UTC).date()


def promo_pricing_status(settings: Settings, today: date | None = None) -> tuple[bool, str]:
    """Advisory status for `lemely doctor`.

    Warns once the 3.8/3.7/3.6-flash promotional window
    (`FLASH_3X_PROMO_END_DATE`) is within 30 days of lapsing to the real,
    doubled rate — or has already lapsed — so a developer notices before the
    $14 ceiling silently starts guarding a stale price. Returns (ok, detail);
    never fatal (see `advisory_checks` in `lemely.app.cli.doctor_cmd`).

    A `settings.gemini.pricing` override pinned on any of the promo models
    bypasses the date gate entirely (`_resolve_pricing` checks overrides
    first) — that is pre-existing, intentional override-wins behaviour, not
    something this function changes. But it means "rates now bill at the
    post-promo rate" would be a FALSE claim once the window lapses, so that
    case is reported on its own rather than folded into the date check below.
    """
    overridden = sorted(m for m in _FLASH_3X_PROMO_MODELS if m in settings.gemini.pricing)
    if overridden:
        return (
            False,
            "lemely.toml pins a fixed price for "
            + ", ".join(overridden)
            + " under [gemini.pricing]; that configured price is used regardless of "
            f"FLASH_3X_PROMO_END_DATE ({FLASH_3X_PROMO_END_DATE}) — verify it still "
            "matches the real billed rate, promotional or not.",
        )
    resolved_today = today if today is not None else _today()
    days_left = (FLASH_3X_PROMO_END_DATE - resolved_today).days
    if days_left < 0:
        return (
            False,
            f"3.8/3.7/3.6-flash promotional pricing expired {-days_left} day(s) ago "
            f"(on {FLASH_3X_PROMO_END_DATE}); rates now bill at the post-promo rate.",
        )
    if days_left <= 30:
        return (
            False,
            f"3.8/3.7/3.6-flash promotional pricing expires in {days_left} day(s) "
            f"(on {FLASH_3X_PROMO_END_DATE}); verify the post-promo rate is still "
            "correct before it takes effect.",
        )
    return (True, f"promotional pricing valid through {FLASH_3X_PROMO_END_DATE}")


_GEMINI_UNSUPPORTED_KEYS = {
    "additionalProperties",
    "additional_properties",
    "$defs",
    "title",
    "default",
}

# F1: 3.x models reject the JSON-Schema `pattern` keyword outright (brief
# #15/B7; live docs re-verified 17 Sep 2026). Stripped only for 3.x models —
# 2.5 still accepts it — as defence-in-depth alongside moving the one
# remaining `pattern`-bearing field (`subject_code`) to a Pydantic validator
# (lemely.core.schemas / loose_schemas / question_papers).
_GEMINI_3X_UNSUPPORTED_KEYS = {"pattern"}

# Model-line detector (F1 approach (b)): matches "gemini-3.5-flash-lite",
# "gemini-3.6-flash", "gemini-3.8-flash", etc. Anything not matching this is
# treated as a 2.x-and-earlier model and keeps the temperature/top_p/seed/
# thinking_budget substrate.
_GEMINI_3X_RE = re.compile(r"^gemini-3\.\d")

# F1 approach (b) note ‡: `thinking_level="minimal"` is only honoured on
# 3.6-flash and 3.5-flash-lite (B7); every other 3.x model falls back to
# "low" if configured with "minimal".
_MINIMAL_THINKING_MODELS_RE = re.compile(r"^gemini-3\.(5-flash-lite|6-flash)\b")

# Ordered weakest → strongest, mirrors google.genai.types.ThinkingLevel.
_THINKING_LEVEL_ORDER = {"minimal": 0, "low": 1, "medium": 2, "high": 3}


def thinking_rank(value: int | str) -> int:
    """Order a resolved thinking value so two can be compared across API lines.

    See :meth:`GeminiClient.resolved_thinking`, which produces the values this
    ranks. A 2.5 model's ``thinking_budget`` is already ordinal (a bigger int means
    more thinking), so it ranks as itself. A 3.x model's ``thinking_level`` is
    a name, so it ranks via ``_THINKING_LEVEL_ORDER``. Public (not
    underscore-prefixed) because callers outside this module — the
    ``AICorrector`` escalation gates in ``correction_ai.py`` — need it to
    decide "would this call actually think harder than the last one" without
    re-deriving the ordering themselves (F1 review MUST-FIX 2).
    """
    if isinstance(value, str):
        return _THINKING_LEVEL_ORDER.get(value, 0)
    return value


def _is_3x(model: str) -> bool:
    """True for a Gemini 3.x model line (``gemini-3.5-flash-lite``, ``gemini-3.8-flash``, ...).

    3.x removes temperature/top_p/top_k/candidate_count, replaces
    ``thinking_budget`` with ``thinking_level``, and rejects the JSON-Schema
    ``pattern`` keyword (brief #15/B7; live docs re-verified 2026-09-17).
    """
    return bool(_GEMINI_3X_RE.match(model))


def _resolve_thinking_level(model: str, requested: str) -> str:
    """Apply the "minimal" fallback rule (F1 approach (b) note ‡)."""
    if requested == "minimal" and not _MINIMAL_THINKING_MODELS_RE.match(model):
        return "low"
    return requested


_process_input_tokens: int = 0
_process_output_tokens: int = 0
_process_accumulated_usd: float = 0.0
_process_cost_by_task: dict[str, float] = {}


def _reset_process_counters() -> None:
    global \
        _process_input_tokens, \
        _process_output_tokens, \
        _process_accumulated_usd, \
        _process_cost_by_task
    _process_input_tokens = 0
    _process_output_tokens = 0
    _process_accumulated_usd = 0.0
    _process_cost_by_task = {}


def reset_process_counters() -> None:
    """Reset the process-wide token/USD counters that back ``per_run_token_ceiling``.

    M0.2 / #26: until ``cache_mode="bypass"`` existed, a cache hit always
    returned before the check ran, so this ceiling was effectively dead. Bypassed
    calls reach the API every time, which is what arms it.

    The counters accumulate for the lifetime of the process **on purpose**: the
    ceiling is per *run*, and a run is allowed to drive many sweeps. Sizing it
    is therefore a budget decision, not a code one — ``lemely.toml`` sets the
    operative value (2,000,000, against ~115k tokens per golden sweep, so ~17
    sweeps fit). A multi-sweep run must NOT reset between its sweeps: that would
    convert a run-level budget guard into a per-sweep one and let a runaway
    script spend without limit.

    Call this only when a long-lived process genuinely begins a second,
    independent run. Previously exposed only as the private
    ``_reset_process_counters`` test helper.
    """
    _reset_process_counters()


def process_token_totals() -> tuple[int, int]:
    """Read-only accessor for tests / doctor: (input_tokens, output_tokens)."""
    return _process_input_tokens, _process_output_tokens


def process_token_totals_by_task() -> dict[str, float]:
    """Return accumulated USD cost broken down by task_tag."""
    return dict(_process_cost_by_task)


def _resolve_pricing(
    model: str, settings: Settings, *, today: Callable[[], date] | None = None
) -> tuple[float, float]:
    """Return (input_usd_per_1k, output_usd_per_1k) for the given model.

    Checks user-configured overrides first. Then resolves the 3.8/3.7/
    3.6-flash promotional rate (US-026 — see `FLASH_3X_PROMO_END_DATE`) for
    "today" and merges it into a COPY of `_DEFAULT_PRICING` under those three
    exact keys, so the length-descending substring match below is the ONLY
    matching mechanism in this function — a promo model can never shadow, or
    be shadowed by, another row via a second matching path. Falls back to
    Flash rates with a warning if the model is unrecognised.

    ``today`` is injectable so tests can pin both sides of the promo
    boundary without depending on the real calendar; when omitted it is
    resolved from the module clock `_today` BY NAME at call time (not bound
    as a default), so `mock.patch("lemely.io.gemini._today", ...)` reaches
    this function too.
    """
    user = settings.gemini.pricing
    if model in user:
        p = user[model]
        return (float(p[0]), float(p[1]))
    pricing_table = _dated_pricing_table((today or _today)())
    # Substring match against built-in table (longest key wins to avoid flash matching flash-lite).
    for key in sorted(pricing_table, key=len, reverse=True):
        if key in model:
            return pricing_table[key]
    structlog.get_logger().warning("gemini_unknown_model_pricing", model=model)
    return _DEFAULT_PRICING["gemini-2.5-flash"]


def _dated_pricing_table(today: date) -> dict[str, tuple[float, float]]:
    """`_DEFAULT_PRICING` with the promo/post-promo rate merged in.

    Merged in for `_FLASH_3X_PROMO_MODELS` as of `today` (US-026). Shared by
    `_resolve_pricing` and `fallback_pricing_status` so the two can never
    disagree about which models have a real row versus fall through to the
    unrecognised-model fallback.
    """
    promo_rate = (
        _FLASH_3X_PROMO_RATE if today <= FLASH_3X_PROMO_END_DATE else _FLASH_3X_POST_PROMO_RATE
    )
    return {**_DEFAULT_PRICING, **dict.fromkeys(_FLASH_3X_PROMO_MODELS, promo_rate)}


def fallback_pricing_status(
    settings: Settings,
    configured_models: dict[str, str],
    *,
    today: Callable[[], date] | None = None,
) -> tuple[bool, str]:
    """Advisory status for `lemely doctor` (US-034).

    Names any task tag whose configured model would resolve, via
    `_resolve_pricing`, through the unrecognised-model fallback (silently
    billed at the `gemini-2.5-flash` rate) rather than a user override, an
    exact row, or a promo-dated row. Silent fallback is what let a stale or
    unpriced model understate the `total_usd_ceiling` ledger unnoticed — this
    makes that visible instead.

    `configured_models` maps task tag -> resolved model name, exactly as
    `lemely doctor`'s `gemini_model_table` check already builds it via
    `settings.gemini.model_for(tag)` for each task tag; this function has no
    opinion of its own about which task tags exist.

    Currently a no-op guard: none of the three models this repo ships
    configured today (`gemini-3.8-flash`, `gemini-3.5-flash-lite`,
    `gemini-2.5-flash`) resolves through the fallback. It starts earning the
    moment someone configures a model this table does not recognise —
    exactly the scenario that made a wrong ledger possible in the first
    place. Advisory, never fatal (see `advisory_checks` in
    `lemely.app.cli.doctor_cmd`).
    """
    user_pricing = settings.gemini.pricing
    pricing_table = _dated_pricing_table((today or _today)())
    hits = sorted(
        f"{tag}={model}"
        for tag, model in configured_models.items()
        if model not in user_pricing and not any(key in model for key in pricing_table)
    )
    if hits:
        return (
            False,
            "these configured models resolve via the unrecognised-model pricing "
            "fallback (silently billed at the gemini-2.5-flash rate rather than "
            "their real rate): " + ", ".join(hits),
        )
    return (True, "all configured models resolve to an exact, overridden, or promo-dated row")


def _resolve_refs(
    schema: Any,
    defs: dict[str, Any],
    _resolving: frozenset[str] = frozenset(),
    *,
    drop_keys: frozenset[str] = frozenset(),
) -> Any:
    if isinstance(schema, dict):
        if "$ref" in schema:
            name = schema["$ref"].split("/")[-1]
            if name in _resolving:
                # Circular reference — Gemini can't handle recursive schemas;
                # emit a generic object to break the cycle.
                return {"type": "object"}
            return _resolve_refs(defs[name], defs, _resolving | {name}, drop_keys=drop_keys)
        return {
            k: _resolve_refs(v, defs, _resolving, drop_keys=drop_keys)
            for k, v in schema.items()
            if k not in _GEMINI_UNSUPPORTED_KEYS and k not in drop_keys
        }
    if isinstance(schema, list):
        return [_resolve_refs(i, defs, _resolving, drop_keys=drop_keys) for i in schema]
    return schema


def _strip_schema(schema: Any, *, is_3x: bool = False) -> Any:
    """Resolve ``$ref``s and drop keys Gemini's structured-output rejects.

    ``is_3x`` additionally drops ``pattern`` (F1): 3.x models reject the
    JSON-Schema ``pattern`` keyword outright, unlike 2.5.
    """
    defs = schema.get("$defs", {}) if isinstance(schema, dict) else {}
    drop_keys = _GEMINI_3X_UNSUPPORTED_KEYS if is_3x else frozenset()
    return _resolve_refs(schema, defs, drop_keys=frozenset(drop_keys))


class _TransientError(Exception):
    """Wraps transient Gemini SDK errors so tenacity can detect them."""


class _DefaultLedger:
    """Sentinel: build the file ledger under ``paths.output_dir`` (CLI, Gradio, eval)."""


#: Default for :paramref:`GeminiClient.ledger` — build the persistent file
#: ledger at ``settings.paths.output_dir / "gemini_spend.json"``, exactly as
#: today (CLI, Gradio, eval and scripts are untouched by DS3). Pass an
#: explicit ``ledger=None`` to run with no ceiling check, no ledger file and
#: no budget events (the web process; spec DS3).
DEFAULT_LEDGER = _DefaultLedger()


class GeminiClient:
    def __init__(
        self,
        settings: Settings,
        *,
        _genai_client: Any = None,
        default_cache_mode: Literal["read_write", "bypass", "refresh"] = "read_write",
        ledger: CostLedger | _DefaultLedger | None = DEFAULT_LEDGER,
    ) -> None:
        self._settings = settings
        self._raw_client: Any = _genai_client
        self._ledger: CostLedger | None = (
            CostLedger(settings.paths.output_dir / "gemini_spend.json")
            if isinstance(ledger, _DefaultLedger)
            else ledger
        )
        #: Single source of truth for this client's cache behaviour when a
        #: call site does not pass an explicit ``cache_mode`` (spec §3.3):
        #: ``_build_run_manifest`` reads this attribute rather than assuming
        #: the ``"read_write"`` literal (#73).
        self.default_cache_mode = default_cache_mode

    @property
    def _client(self) -> Any:
        if self._raw_client is None:
            from google import genai

            api_key = (
                self._settings.gemini_api_key.get_secret_value()
                if self._settings.gemini_api_key
                else None
            )
            self._raw_client = genai.Client(api_key=api_key)
        return self._raw_client

    def start_new_run(self) -> None:
        """Reset the token/USD counters at the start of a new logical RUN.

        A *run*, not a sweep. ``per_run_token_ceiling`` budgets one whole run —
        every sweep it drives — and that is the point of it: it is the guard
        that stops a runaway multi-sweep script from spending the §10 budget.
        Resetting between sweeps would mean a script doing 100 sweeps never
        trips a ceiling sized for one, which is not a fix but the removal of
        the guard. See :func:`reset_process_counters`.

        A multi-sweep run must therefore NOT call this between its sweeps. It
        exists for a long-lived process that genuinely starts a second,
        independent run — and for tests.
        """
        reset_process_counters()

    def _resolved_gen_params(self, task_tag: str | None, model: str) -> dict[str, Any]:
        """Resolve the generation parameters that affect output determinism.

        Single source of truth for both the actual API call config
        (:meth:`_call_once`) and the cache-key fingerprint (:meth:`_cache_key`) —
        keeping them in sync is what makes the fingerprint meaningful.

        F1: the two API lines are disjoint knobs. A 3.x ``model`` resolves
        ``thinking_level`` (from ``thinking_level_for``, "low" if the task tag
        has no entry, "minimal" demoted to "low" off the two models that
        support it) and leaves temperature/top_p/seed/thinking_budget at their
        inert defaults — 3.x removes those parameters outright, so reading
        ``temperature_for`` here would make a config knob that has no effect
        on the actual call still perturb the cache key. A 2.5-and-earlier
        ``model`` keeps the original temperature/top_p/seed/thinking_budget
        substrate and never reads ``thinking_level_for``.
        """
        g = self._settings.gemini
        key = task_tag or ""
        if _is_3x(model):
            requested_level = g.thinking_level_for.get(key, "low")
            return {
                "thinking_budget": None,
                "temperature": None,
                "top_p": None,
                "seed": None,
                "thinking_level": _resolve_thinking_level(model, requested_level),
            }
        return {
            "thinking_budget": g.thinking_budget_for.get(key, 0),
            "temperature": g.temperature_for.get(key, g.temperature),
            "top_p": g.top_p_for.get(key, g.top_p),
            "seed": g.seed_for.get(key, g.seed),
            "thinking_level": None,
        }

    def resolved_thinking(self, task_tag: str, model: str) -> int | str:
        """The ONE thinking knob that actually affects ``model``'s output for ``task_tag``.

        F1 review MUST-FIX 2 (2026-09-17): this is the single source of truth
        for "how hard is this call thinking", used both to build the actual
        API request (:meth:`_call_once`, via :meth:`_resolved_gen_params`) and
        by callers outside this class — ``AICorrector.mark_question``'s
        Step-1/Step-2 escalation gates — that need to compare "would this call
        actually differ from the previous one" without re-deriving the
        defaults themselves. Before this existed, ``correction_ai.py`` had its
        own copy of this resolution with its own (different) defaults for a
        missing ``thinking_level_for`` tag, which silently disagreed with the
        actual resolved value here: a partial TOML override
        (``thinking_level_for = {"correction": "low"}``, which REPLACES the
        default dict rather than merging into it) demonstrated the drift by
        making a Step-1 retry run at a different level than the gate that
        decided to fire it believed it would.

        Returns the resolved ``thinking_level`` (a string, already demoted by
        the "minimal" fallback rule) on a 3.x model, or the resolved
        ``thinking_budget`` (an int) on a 2.5-and-earlier model — exactly the
        two disjoint substrates :meth:`_resolved_gen_params` already computes.
        """
        params = self._resolved_gen_params(task_tag, model)
        if _is_3x(model):
            return cast(str, params["thinking_level"])
        return cast(int, params["thinking_budget"])

    def _params_fingerprint(
        self,
        model: str,
        task_tag: str | None,
        response_schema: type[BaseModel] | None = None,
        *,
        media_resolution: str | None = None,
    ) -> str:
        """Hash every input that can change the model's output.

        Includes the response schema and ``max_output_tokens`` per spec §3.3.
        The schema matters for correctness, not just completeness: the cache key
        is ``model:prompt_hash:files_hash:params_fingerprint`` and ``prompt_hash``
        covers only the system/user prompts, so without the schema here two calls
        with identical prompts but different response schemas collide and the
        second silently receives the first one's differently-shaped reply.

        F1: also folds in the API line (``2x``/``3x``) and ``thinking_level``.
        Because ``_resolved_gen_params`` zeroes out the knobs each line does not
        use, a temperature/top_p/seed change is inert (and therefore leaves this
        fingerprint unchanged) on a 3.x model, and a ``thinking_level_for``
        change is inert on a 2.5 model — exactly the two directions F1's
        acceptance test (4) checks.

        I1: ``media_resolution`` folds in too. It is a per-call knob (the
        image-part resolution passed to :meth:`generate_structured`, not a
        ``settings.gemini`` field), so it is not covered by
        ``_resolved_gen_params`` — it must still change this fingerprint, or
        a per-page-image extraction call (``media_resolution="medium"``)
        would collide in the on-disk cache with a pre-I1 call that set no
        media resolution at all, silently serving a stale cached reply.
        """
        params = self._resolved_gen_params(task_tag, model)
        schema_hash = ""
        if response_schema is not None:
            schema_json = json.dumps(response_schema.model_json_schema(), sort_keys=True)
            schema_hash = hashlib.sha256(schema_json.encode()).hexdigest()[:12]
        api_line = "3x" if _is_3x(model) else "2x"
        raw = (
            f"{model}|{api_line}|{params['temperature']}|{params['top_p']}"
            f"|{params['seed']}|{params['thinking_budget']}|{params['thinking_level']}"
            f"|{_MAX_OUTPUT_TOKENS}|{schema_hash}|{media_resolution or 'none'}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def check_reachable(self) -> None:
        """Verify the Gemini API is reachable with the configured credentials.

        Performs a lightweight ``models.list()`` request (no content generation,
        so no token/USD cost) and forces it to execute. Used by ``lemely doctor``
        to report real reachability rather than a stub.

        Raises:
            ExternalServiceError: no key is configured, the key is rejected, or
                the API/network is unreachable.
        """
        if self._settings.gemini_api_key is None:
            raise ExternalServiceError("No Gemini API key configured; cannot reach the API.")
        try:
            # models.list() returns a lazy pager; consume one item to force the
            # HTTP round-trip that actually validates auth + connectivity.
            next(iter(self._client.models.list()), None)
        except Exception as exc:
            raise ExternalServiceError(f"Gemini API not reachable: {exc}") from exc

    def _cache_key(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        prompt_version: str,
        file_paths: list[Path] | None,
        extra_key: str,
        params_fingerprint: str,
        image_parts: list[bytes] | None = None,
    ) -> str:
        prompt_hash = hashlib.sha256(
            (system_prompt + user_prompt + prompt_version + extra_key).encode()
        ).hexdigest()[:12]
        # I1: image_parts (in-memory rasterised page PNGs) take precedence
        # over file_paths for hashing — the two are mutually exclusive at the
        # call site, and hashing the actual bytes sent (rather than reading
        # back off disk, which image_parts has no path for) is what keeps
        # `files_hash` meaning "the files_hash of what was actually sent".
        if image_parts:
            h = hashlib.sha256()
            for data in image_parts:
                # Length-prefixed so [b"ab"] and [b"a", b"b"] cannot hash
                # identically (I1 review nit: unreachable with real
                # self-delimiting PNGs today, but a one-line guard against a
                # future non-PNG image_parts caller costs nothing here).
                h.update(len(data).to_bytes(8, "big"))
                h.update(data)
            files_hash = h.hexdigest()[:12]
        elif file_paths:
            h = hashlib.sha256()
            for fp in sorted(file_paths):
                h.update(fp.read_bytes())
            files_hash = h.hexdigest()[:12]
        else:
            files_hash = "none"
        # M0.2 / #26: params_fingerprint (temperature/top_p/seed/thinking_budget)
        # folded in so two calls with identical generation params hit the cache
        # and two with differing params (a real A/B) do not silently collide.
        combined = f"{model}:{prompt_hash}:{files_hash}:{params_fingerprint}"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def _cache_path(self, key: str) -> Path:
        d = self._settings.paths.cache_dir / "gemini"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{key}.json"

    def _check_cost_ceiling(self) -> None:
        g = self._settings.gemini
        if g.per_run_token_ceiling is not None:
            total = _process_input_tokens + _process_output_tokens
            if total >= g.per_run_token_ceiling:
                # CostCeilingError (not plain ExternalServiceError): a budget
                # stop is a signal for the whole run, not a per-call failure
                # a caller may legitimately absorb (I1 review round 2,
                # MUST-FIX 1).
                raise CostCeilingError(
                    f"Token ceiling ({g.per_run_token_ceiling}) exceeded; accumulated {total}."
                )
        if g.total_usd_ceiling is not None and self._ledger is not None:
            ledger_total = self._ledger.total()
            if ledger_total >= g.total_usd_ceiling:
                raise CostCeilingError(
                    f"USD ceiling (${g.total_usd_ceiling:.4f}) exceeded; persistent "
                    f"cumulative spend is ${ledger_total:.4f} (across all runs)."
                )

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        file_paths: list[Path] | None = None,
        image_parts: list[bytes] | None = None,
        media_resolution: str | None = None,
        response_schema: type[_T],
        prompt_version: str,
        model: str | None = None,
        extra_cache_key: str = "",
        task_tag: str | None = None,
        cache_mode: Literal["read_write", "bypass", "refresh"] | None = None,
    ) -> _T:
        """I1: send per-page images instead of uploading a whole file.

        ``image_parts`` is in-memory PNG bytes, one per rasterised page, sent
        as individual ``types.Part`` objects instead of uploading ``file_paths``
        through the Files API — this is what lets each part carry its own
        ``media_resolution`` (Gemini's bounding-box output is documented for
        image inputs, not PDF inputs). Mutually exclusive with ``file_paths``;
        when both are given, ``image_parts`` wins (see :meth:`_call_once`).
        ``media_resolution`` (e.g. ``"medium"``/``"high"``) is applied to every
        part in ``image_parts`` and is folded into the cache-key fingerprint
        (:meth:`_params_fingerprint`) so it never collides with a call that set
        no media resolution.
        """
        if cache_mode is None:
            cache_mode = self.default_cache_mode
        if cache_mode not in ("read_write", "bypass", "refresh"):
            raise ValueError(
                f"cache_mode must be one of 'read_write', 'bypass', 'refresh'; got {cache_mode!r}"
            )
        g = self._settings.gemini
        if model is not None:
            active_model = model
        elif task_tag is not None:
            active_model = g.model_for(task_tag)
        else:
            active_model = g.model

        log = structlog.get_logger().bind(
            component="gemini_client",
            model=active_model,
            task=task_tag or "untagged",
        )

        params_fingerprint = self._params_fingerprint(
            active_model, task_tag, response_schema, media_resolution=media_resolution
        )
        cache_key = self._cache_key(
            active_model,
            system_prompt,
            user_prompt,
            prompt_version,
            file_paths,
            extra_cache_key,
            params_fingerprint,
            image_parts=image_parts,
        )
        cache_path = self._cache_path(cache_key)

        # cache_mode="read_write" (default): read-then-write, current behaviour.
        # cache_mode="bypass": skip the read (always call the API); does NOT
        #   write either, so a bypassed call — used for A/B churn measurement —
        #   is fully side-effect-free with respect to the shared cache.
        # cache_mode="refresh": skip the read (always call the API) and DOES
        #   write, overwriting any existing entry — used to force-regenerate a
        #   specific known-stale response so later read_write calls see it.
        if cache_mode == "read_write" and cache_path.exists():
            log.info("gemini_cache_hit", cache_key=cache_key)
            bus.publish(
                EventType.GEMINI_CACHE_HIT,
                task=task_tag or "untagged",
                model=active_model,
                cache_key=cache_key,
            )
            return response_schema.model_validate_json(cache_path.read_text(encoding="utf-8"))

        self._check_cost_ceiling()

        bus.publish(
            EventType.GEMINI_CALL_START,
            task=task_tag or "untagged",
            model=active_model,
        )
        t0 = time.monotonic()
        raw_text = self._call_with_retry(
            active_model,
            system_prompt,
            user_prompt,
            file_paths,
            response_schema,
            log,
            task_tag,
            image_parts=image_parts,
            media_resolution=media_resolution,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        log.debug("gemini_latency_ms", latency_ms=latency_ms)

        try:
            result: _T = response_schema.model_validate_json(raw_text)
        except Exception as exc:
            log.debug(
                "gemini_validation_failure",
                schema=response_schema.__name__,
                validation_error=str(exc)[:500],
                raw_response=raw_text[:2000] + ("…" if len(raw_text) > 2000 else ""),
            )
            corrected = (
                user_prompt + f"\n\nYour previous response failed validation for "
                f"{response_schema.__name__} with the following error:\n{exc}\n\n"
                "Fix only the fields mentioned in the error above and return valid JSON "
                "matching the schema exactly. Do not change any other fields."
            )
            raw_text = self._call_with_retry(
                active_model,
                system_prompt,
                corrected,
                file_paths,
                response_schema,
                log,
                task_tag,
                image_parts=image_parts,
                media_resolution=media_resolution,
            )
            try:
                result = response_schema.model_validate_json(raw_text)
            except Exception as exc:
                log.debug(
                    "gemini_validation_failure_retry",
                    schema=response_schema.__name__,
                    validation_error=str(exc)[:500],
                    raw_response=raw_text[:2000] + ("…" if len(raw_text) > 2000 else ""),
                )
                raise ParseError(
                    f"Gemini response did not validate against {response_schema.__name__} "
                    "even after schema-correction retry."
                ) from exc

        if cache_mode in ("read_write", "refresh"):
            cache_path.write_text(raw_text, encoding="utf-8")
        return result

    def _call_with_retry(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        file_paths: list[Path] | None,
        response_schema: type[_T],
        log: Any,
        task_tag: str | None = None,
        *,
        image_parts: list[bytes] | None = None,
        media_resolution: str | None = None,
    ) -> str:
        def _before_sleep(state: RetryCallState) -> None:
            exc = state.outcome.exception() if state.outcome else None
            err = str(exc) if exc else ""
            log.warning(
                "gemini_retry",
                attempt=state.attempt_number,
                error=err,
            )
            bus.publish(
                EventType.GEMINI_RETRY,
                task=task_tag or "untagged",
                model=model,
                attempt=state.attempt_number,
                error=err[:80],
            )

        g = self._settings.gemini
        try:
            for attempt in Retrying(
                stop=stop_after_attempt(g.max_retries + 1),
                wait=wait_exponential(multiplier=g.backoff_seconds, min=1, max=60),
                retry=retry_if_exception_type(_TransientError),
                before_sleep=_before_sleep,
                reraise=True,
            ):
                with attempt:
                    return self._call_once(
                        model,
                        system_prompt,
                        user_prompt,
                        file_paths,
                        response_schema,
                        log,
                        task_tag,
                        image_parts=image_parts,
                        media_resolution=media_resolution,
                    )
        except _TransientError as exc:
            # Retries exhausted on a transient (503/rate-limit) failure. Surface the
            # public ExternalServiceError so callers never see the private signal type.
            raise ExternalServiceError(str(exc)) from exc
        raise ParseError("Unreachable")  # pragma: no cover  # pragma: no cover

    def _call_once(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        file_paths: list[Path] | None,
        response_schema: type[_T],
        log: Any,
        task_tag: str | None = None,
        *,
        image_parts: list[bytes] | None = None,
        media_resolution: str | None = None,
    ) -> str:
        from google.genai import types

        # I1: image_parts (in-memory rasterised page PNGs) are sent as inline
        # `Part`s so each one can carry its own `media_resolution` — the
        # Files API upload path below has no such per-part knob. Mutually
        # exclusive with file_paths; image_parts wins when both are given
        # (generate_structured never passes both today).
        resolved_media_resolution = (
            _MEDIA_RESOLUTION_LEVELS.get(media_resolution, media_resolution)
            if media_resolution is not None
            else None
        )
        file_parts: list[Any] = []
        if image_parts:
            for data in image_parts:
                file_parts.append(
                    types.Part.from_bytes(
                        data=data,
                        mime_type="image/png",
                        media_resolution=resolved_media_resolution,
                    )
                )
        elif file_paths:
            for fp in file_paths:
                file_parts.append(self._client.files.upload(file=fp))

        is_3x = _is_3x(model)
        gen_params = self._resolved_gen_params(task_tag, model)
        stripped_schema = _strip_schema(response_schema.model_json_schema(), is_3x=is_3x)
        log.debug(
            "gemini_schema_sent",
            schema=response_schema.__name__,
            top_level_properties=list((stripped_schema.get("properties") or {}).keys()),
        )
        t0 = time.monotonic()

        # F1: 2.5 and 3.x are disjoint API lines. 3.x removes
        # temperature/top_p/top_k/candidate_count outright (passing them is
        # rejected, not merely ignored) and replaces the numeric
        # thinking_budget with a named thinking_level; it also takes the
        # structured-output schema via response_json_schema rather than
        # response_schema (google-genai 2.10.0, types.py:6029 —
        # GenerateContentConfig.response_json_schema, "alternative to
        # response_schema that accepts JSON Schema"; both fields exist on the
        # same config class in this SDK version, so 2.5 is untouched by
        # keeping response_schema).
        config_kwargs: dict[str, Any] = {
            "max_output_tokens": _MAX_OUTPUT_TOKENS,
            "response_mime_type": "application/json",
            "system_instruction": system_prompt,
        }
        if is_3x:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=gen_params["thinking_level"]
            )
            config_kwargs["response_json_schema"] = stripped_schema
        else:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_budget=gen_params["thinking_budget"]
            )
            config_kwargs["response_schema"] = stripped_schema
            config_kwargs["temperature"] = gen_params["temperature"]
            config_kwargs["top_p"] = gen_params["top_p"]
            config_kwargs["seed"] = gen_params["seed"]

        try:
            response = self._client.models.generate_content(
                model=model,
                config=types.GenerateContentConfig(**config_kwargs),
                contents=[user_prompt, *file_parts],
            )
        except Exception as exc:
            msg = str(exc).lower()
            if any(
                t in msg for t in ("500", "503", "rate limit", "resource exhausted", "connection")
            ):
                raise _TransientError(str(exc)) from exc
            raise ExternalServiceError(str(exc)) from exc

        latency_ms = int((time.monotonic() - t0) * 1000)

        global \
            _process_input_tokens, \
            _process_output_tokens, \
            _process_accumulated_usd, \
            _process_cost_by_task
        in_tok = int(getattr(response.usage_metadata, "prompt_token_count", 0) or 0)
        candidates_tok = int(getattr(response.usage_metadata, "candidates_token_count", 0) or 0)
        # M0.2 / #26: thoughts_token_count was previously never counted, silently
        # understating both the ledgered output-token count and its USD cost for
        # any call made with a non-zero thinking budget (e.g. mark_scheme's 8000).
        thoughts_tok = int(getattr(response.usage_metadata, "thoughts_token_count", 0) or 0)
        out_tok = candidates_tok + thoughts_tok
        _process_input_tokens += in_tok
        _process_output_tokens += out_tok

        in_price, out_price = _resolve_pricing(model, self._settings)
        usd = in_tok / 1000 * in_price + out_tok / 1000 * out_price
        usd_rounded = round(usd, 6)
        _process_accumulated_usd += usd
        if task_tag:
            _process_cost_by_task[task_tag] = _process_cost_by_task.get(task_tag, 0.0) + usd

        # Persist cumulative spend to the cross-run ledger; this is the source of
        # truth for the hard USD ceiling. Emit budget events for the UI/ntfy.
        # DS3: a ledgerless client (the web process) skips all of this — no
        # ledger file, no budget events. Spend is still observable via the
        # unconditional `gemini_call` log line below.
        g = self._settings.gemini
        if self._ledger is not None:
            new_total, crossed = self._ledger.add(usd, thresholds=g.usd_warning_thresholds)
            for threshold in crossed:
                bus.publish(
                    EventType.BUDGET_WARNING,
                    threshold=threshold,
                    total_usd=round(new_total, 6),
                    ceiling=g.total_usd_ceiling,
                )
            if g.total_usd_ceiling is not None and new_total >= g.total_usd_ceiling:
                bus.publish(
                    EventType.BUDGET_EXCEEDED,
                    total_usd=round(new_total, 6),
                    ceiling=g.total_usd_ceiling,
                )

        log.info(
            "gemini_call",
            input_tokens=in_tok,
            output_tokens=out_tok,
            # Broken out separately from output_tokens (which now includes them)
            # so a thinking-budget change is visible in the logs rather than
            # showing up as unexplained output-token drift.
            thoughts_tokens=thoughts_tok,
            usd_cost=usd_rounded,
            cache_hit=False,
            # M0.4 reads this off the log to record which generation parameters
            # a sweep actually ran under, without re-deriving them from config
            # that may have changed since.
            params_fingerprint=self._params_fingerprint(
                model, task_tag, response_schema, media_resolution=media_resolution
            ),
        )
        bus.publish(
            EventType.GEMINI_CALL_END,
            task=task_tag or "untagged",
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            usd_cost=usd_rounded,
            latency_ms=latency_ms,
        )

        raw = response.text or ""
        finish = str(response.candidates[0].finish_reason if response.candidates else "")
        if finish == "MAX_TOKENS":
            raise _TransientError(f"Gemini hit max_output_tokens ({model})")
        return raw
