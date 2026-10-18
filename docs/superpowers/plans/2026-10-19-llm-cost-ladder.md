# LLM Cost Ladder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the LLM $ per marked script on the web marking path, lever by lever, with every lever judged by one pure gate on the 12-case `cost-201` screen set.

**Architecture:** Rung 0 makes cost measurable: a per-call cost record with cached tokens and 2027 prices, a pure `judge()` gate, lever settings that default to today's behaviour, a cache mode per task tag so upstream stages can be frozen, and a runner that writes the ladder report. A live baseline then re-ranks the levers. Phase A builds and screens three correction levers in sequence: a model switch (gemini-3.1-flash-lite or Claude Haiku 5.5 through a new provider adapter), a cascade with fitted triggers, and a shared prefix per paper. Phase B gets its own plan, written only if Phase A cuts less than 50%.

**Tech Stack:** Python 3, pydantic settings, google-genai (`>=2.1,<3`), anthropic (new), structlog, pytest, click.

**Spec:** `docs/superpowers/specs/2026-10-19-gemini-cost-ladder-design.md` (the "design" below).

## Global Constraints

- Metric: $ per marked script on the web marking path, **priced at the rates in force from 2027-01-01**.
- Pass rule, judged against the configuration the lever stacks on:
  - saving under 30%: extra mismarked scored parts ≤ the A/A churn floor;
  - saving of 30% or more: extra mismarked scored parts ≤ `max(aa_floor, ceil(0.02 × scored parts))`; the 2% term is 1 on `cost-201`'s 31 scored parts;
  - both tiers: id-match must not drop, the structured-output validity rate must not drop, p95 latency per script ≤ 2× the rung-0 baseline, and any failed call or missing leaf fails the run.
- A/A floor: one rerun of the rung-0 baseline, reused for every later comparison.
- Spend caps across all cost-ladder runs combined, in billed dollars: **Gemini $3.00, Anthropic $40.00** (user decision 2026-10-19). Enforced by the runner (Task 5) before and during every run; overshoot is at most one case's cost.
- Screen set: `tests/golden`, dev split, the 12 cases of `BUILD/accuracy-runs/cost-201-2026-10-01` (corpus digest `76989782d6fda9fc`). No full-corpus run.
- Phase A stops when the next lever is expected to save under 5% of the current cost. Phase B is skipped if Phase A cuts 50% or more from the rung-0 baseline.
- Every new behaviour sits behind a setting whose default reproduces today's prompts and cache keys byte for byte.
- No third-party routing library (no LiteLLM, no OpenRouter).
- No student data through Anthropic's Batch API.
- Implementers are sonnet agents. Each task lists the files it owns. An implementer touches only those files and commits with `git commit -S -- <owned paths>`.
- Run only the touched test files locally (`pytest tests/<file> -v`), never the full suite. Run `pre-commit run --all-files`, plus the repo's source-scanning lint tests, before every commit.
- Conventional, signed commits (`git commit -S`). **No commit or push happens unless the user has asked for execution with commits.**
- Live runs read keys through the scratch wrapper script that reads `~/.config/lemely/gemini_key` (and an Anthropic key file for Task 9). No key ever enters the repo or a command line.

---

## File ownership map

| Task | Owns |
|---|---|
| 1 Cost record | `lemely/io/gemini.py` (pricing + `_record_spend` region), `tests/test_gemini_cost_record.py` (new) |
| 2 Gate | `lemely/accuracy/cost_ladder/__init__.py`, `lemely/accuracy/cost_ladder/gate.py`, `tests/test_cost_ladder_gate.py` (all new) |
| 3 Lever settings | `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example`, `tests/test_cost_ladder_settings.py` (new) |
| 4 Cache mode per tag | `lemely/io/gemini.py` (cache-mode resolution only), `tests/test_gemini_cache_mode_for.py` (new) |
| 5 Runner + report | `lemely/accuracy/cost_ladder/runner.py`, `lemely/accuracy/cost_ladder/report.py`, `scripts/cost_ladder.py`, `tests/test_cost_ladder_runner.py` (all new) |
| 6 Rung-0 live baseline | `BUILD/accuracy-runs/cost-ladder-<date>/` |
| 7 Re-rank checkpoint | this plan file (amendment only) |
| 8 Anthropic adapter | `lemely/io/providers/__init__.py`, `lemely/io/providers/anthropic_adapter.py` (new), `lemely/io/gemini.py` (dispatch only), `pyproject.toml`, `docs/deployment.md`, `tests/test_anthropic_adapter.py` (new) |
| 9 A1 screen | `BUILD/accuracy-runs/cost-ladder-<date>/a1-*` |
| 10 Cascade | `lemely/io/correction_ai.py`, `tests/test_correction_cascade.py` (new), `scripts/cascade_sweep.py` (new) |
| 11 A2 sweep + screen | `BUILD/accuracy-runs/cost-ladder-<date>/a2-*` |
| 12 Shared prefix | `lemely/io/prompts/correction_ai.py`, `lemely/io/correction_ai.py` (call site only), `tests/test_correction_shared_prefix.py` (new) |
| 13 A3 screen + final report | `BUILD/accuracy-runs/cost-ladder-<date>/a3-*`, `BUILD/accuracy-runs/cost-ladder-<date>/LADDER.md` |

**Waves.** Wave 1 runs Tasks 1, 2 and 3 in parallel. Wave 2 runs 4 and 5 in parallel; Task 4 waits for Task 1 because both edit `gemini.py`. Then Task 6, then Task 7. Wave 4 runs Tasks 8 and 10 in parallel. Then Task 9, then 11. Task 12 starts after Task 10 (both edit `correction_ai.py`). Then Task 13.

**Shipping a lever** means flipping its default in `config.py`, `example_toml.py` and `lemely.toml.example`. Each shipping change is a separate one-commit task, run by the orchestrator after a PASS verdict. The owner of `config.py` at that moment is the shipping step alone.

---

### Task 1: Per-call cost record (rung 0)

**Files:**
- Modify: `lemely/io/gemini.py`: the pricing constants (`FLASH_3X_PROMO_END_DATE`, `_FLASH_3X_*`, `_DEFAULT_PRICING`), `_resolve_pricing`, `_dated_pricing_table`, `GeminiClient._record_spend`, the process counters (`_reset_process_counters`)
- Test: `tests/test_gemini_cost_record.py` (new; reuse fakes from `tests/gemini_fakes.py`)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `PriceRow = NamedTuple("PriceRow", [("input", float), ("cached_input", float), ("output", float)])`, in USD per 1k tokens, matching the existing per-1k convention.
  - `price_row(model: str, settings: Settings, *, on: date) -> PriceRow`, using the same longest-substring match as `_resolve_pricing`. An unknown model raises `UnpricedModelError(model)`; it never silently falls back. `_resolve_pricing` keeps its existing signature and return value, so its other callers are untouched.
  - `price_call(model: str, settings: Settings, *, input_tokens: int, cached_tokens: int, output_tokens: int, on: date) -> float`. Uncached input is `input_tokens - cached_tokens` at the input rate, cached input is at the cached rate, and output includes thinking tokens.
  - `CallRecord` (a frozen dataclass): `provider: str, task_tag: str | None, model: str, thinking: str | int | None, input_tokens: int, cached_tokens: int, output_tokens: int, thinking_tokens: int, usd_now: float, usd_2027: float, latency_ms: int, attempt: Literal["first", "borderline", "escalation"] | None, question_id: str | None, case_key: str | None, parse_ok: bool`. `parse_ok` is False when the response failed structured-output validation (the record is still appended before the error propagates).
  - `process_call_records() -> list[CallRecord]` (a copy) and `set_call_context(*, case_key: str | None) -> None`. The harness sets the current case. `_reset_process_counters` clears the records.
  - `PRICE_DATE_2027 = date(2027, 1, 1)`.
- Pricing rows to hold, from the design §2.2 and the official pricing page, per 1M tokens (store per 1k):
  - gemini-3.8-flash / 3.6-flash: cached input $0.075, or $0.15 from 2027-01-01.
  - gemini-3.5-flash-lite: cached input $0.03.
  - **gemini-3.1-flash-lite (new row):** $0.25 input, $0.025 cached, $1.50 output.
  - gemini-2.5-flash: cached input $0.03.
  - Claude Haiku 5.5 (new row, provider `anthropic`): $0.10 input, $0.01 cache read, $0.50 output. Use the exact model id from Anthropic's models page, which the implementer confirms through the `claude-api` skill. Anthropic's cache-write premium is out of scope for this row; Task 8 records cache writes as uncached input, so cost is conservatively overstated.
  - Housekeeping: drop `gemini-3.7-flash` from `_FLASH_3X_PROMO_MODELS` and `_DEFAULT_PRICING` (deprecated 2026-10-08, now routed to 3.8-flash). Remove any test that pins a 3.7 price.
- Behaviour: `_record_spend` reads `usage_metadata.cached_content_token_count` (default 0) and passes it to `price_call` twice, once for today and once for `on=PRICE_DATE_2027`. It appends a `CallRecord`, and it keeps today's ledger and log fields unchanged except for a new `cached_tokens` field. The existing ledger amount (`usd`) becomes `usd_now`, which now discounts cached tokens; this is intended.
- The `attempt` and `question_id` fields are filled from two new optional keyword arguments to `generate_structured`: `attempt=` and `question_id=`. Their defaults are `None`. They are **not** part of the cache key.

- [ ] **Step 1: Write the failing tests** in `tests/test_gemini_cost_record.py`:
  - `test_cached_tokens_priced_at_cached_rate`: a fake response with prompt 10,000, cached 8,000 and candidates 1,000 on gemini-3.8-flash at 2026-10-19 gives `usd_now == (2000*0.00075 + 8000*0.000075 + 1000*0.00375)/1000`.
  - `test_2027_price_used_on_and_after_boundary`: `price_call(..., on=date(2026,12,31))` uses the promo rate, and `on=date(2027,1,1)` the doubled rate, for input, cached and output.
  - `test_thinking_tokens_billed_as_output`.
  - `test_unknown_model_raises_unpriced`: `price_row("gemini-9-ultra", ...)` raises `UnpricedModelError`.
  - `test_3_1_flash_lite_row_exists`.
  - `test_call_record_appended_with_attempt_and_question`: `generate_structured(..., attempt="borderline", question_id="3b")` appends one record carrying both.
  - `test_attempt_and_question_id_not_in_cache_key`: the same call with different `attempt` values yields the same cache key.
  - `test_reset_clears_call_records`.
  - `test_case_key_from_context`.
  - `test_parse_failure_recorded_with_parse_ok_false`.
- [ ] **Step 2: Run the tests to see them fail.** Run `pytest tests/test_gemini_cost_record.py -v`. Expected: FAIL (ImportError on `price_call`, `CallRecord`).
- [ ] **Step 3: Implement** the interfaces above in `lemely/io/gemini.py`, then update the 3.7 references.
- [ ] **Step 4: Run the tests to see them pass.** Run `pytest tests/test_gemini_cost_record.py tests/test_gemini_client.py tests/test_cost_ledger.py -v`. Expected: all PASS. Any existing test broken by the 3.7 removal or the cached-token discount gets updated in the same commit, and the commit message explains why.
- [ ] **Step 5: Prove the guard goes red.** Temporarily price cached tokens at the full rate in `price_call`, confirm that `test_cached_tokens_priced_at_cached_rate` fails, then revert.
- [ ] **Step 6: Commit** (only when commits are authorised): `git commit -S -m "feat(gemini): per-call cost record with cached tokens and 2027 pricing" -- lemely/io/gemini.py tests/test_gemini_cost_record.py <updated tests>`

### Task 2: The gate, `judge()`

**Files:**
- Create: `lemely/accuracy/cost_ladder/__init__.py` (empty), `lemely/accuracy/cost_ladder/gate.py`
- Test: `tests/test_cost_ladder_gate.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class RunSummary:
      usd_per_script_mean: float      # at 2027 rates
      latency_p95_ms: float           # per script
      mismarked_parts: frozenset[str] # "<case_key>/<question_id>" of scored parts with predicted != truth
      scored_parts: int
      id_match_rate: float
      validity_rate: float            # structured outputs parsed / attempted
      incomplete: tuple[str, ...]     # case keys with a failed call or missing leaf

  @dataclass(frozen=True)
  class Verdict:
      passed: bool
      tier: Literal["small", "big"]
      saving: float                   # 1 - candidate/baseline usd
      extra_mismarks: int
      allowed_extra: int
      reasons: tuple[str, ...]        # every failed check, human-readable

  def judge(baseline: RunSummary, candidate: RunSummary, *, aa_floor: int,
            original_latency_p95_ms: float) -> Verdict
  def aa_floor(a: RunSummary, b: RunSummary) -> int  # len(a.mismarked_parts ^ b.mismarked_parts)
  ```
- Rules:
  - `extra_mismarks = len(candidate.mismarked_parts - baseline.mismarked_parts)`. Newly wrong parts count; parts the candidate fixes do not offset them.
  - The tier is `big` when `saving >= 0.30`.
  - `allowed_extra = aa_floor` in the small tier, or `max(aa_floor, math.ceil(0.02 * candidate.scored_parts))` in the big tier.
  - The run fails on any of: `extra_mismarks > allowed_extra`; `candidate.id_match_rate < baseline.id_match_rate`; `candidate.validity_rate < baseline.validity_rate`; `candidate.latency_p95_ms > 2 * original_latency_p95_ms`; a non-empty `candidate.incomplete`; or `candidate.scored_parts != baseline.scored_parts`, because a changed denominator is a narrowed screen.
  - The module does no I/O and has no imports from `lemely.io`.

- [ ] **Step 1: Write the failing tests**, one per rule:
  - `test_small_tier_passes_within_floor`
  - `test_small_tier_fails_above_floor`
  - `test_big_tier_allows_ceil_two_percent` (31 parts, 1 extra, passes)
  - `test_big_tier_fails_two_extra_on_31_parts`
  - `test_fixed_parts_do_not_offset_new_mismarks`
  - `test_id_match_drop_fails`
  - `test_validity_drop_fails`
  - `test_latency_over_double_original_fails` (stacked on a faster config, it is still judged against the original)
  - `test_incomplete_run_fails_with_case_named`
  - `test_scored_parts_change_fails`
  - `test_aa_floor_is_symmetric_difference`
  - `test_all_reasons_reported`: two failures give two reasons.
- [ ] **Step 2: Run** `pytest tests/test_cost_ladder_gate.py -v`. Expected: FAIL (ModuleNotFoundError).
- [ ] **Step 3: Implement** `gate.py`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Prove the guard goes red.** Change `>` to `>=` in the mismark check, confirm that `test_small_tier_passes_within_floor` fails, then revert.
- [ ] **Step 6: Commit:** `feat(accuracy): cost-ladder gate judge()`, scoped to the owned paths.

### Task 3: Lever settings (defaults reproduce today)

**Files:**
- Modify: `lemely/runtime/config.py` (`GeminiSettings`), `lemely/runtime/example_toml.py`, `lemely.toml.example`
- Test: `tests/test_cost_ladder_settings.py`

**Interfaces:**
- Produces new `GeminiSettings` fields, with defaults equal to current behaviour:
  - `cache_mode_for: dict[str, Literal["read_write", "bypass", "refresh"]] = {}`, used by Task 4.
  - `cascade_enabled: bool = False`
  - `cascade_strong_model: str | None = None` (None means use `escalation_model`)
  - `cascade_threshold_for: dict[str, float] = {}`: model name to fitted confidence threshold. A model missing from the dict uses `escalation_confidence_threshold`.
  - `cascade_two_pass_disagreement: bool = False`
  - `cascade_unaddressed_points: bool = False`
  - `correction_shared_prefix: bool = False`
  - `correction_prefix_cache: Literal["implicit", "explicit"] = "implicit"`
  - `anthropic_api_key: SecretStr | None = None`, read from the env var `ANTHROPIC_API_KEY` in the same way as `gemini_api_key`.
  - `correction_model` keeps its default of `"gemini-3.8-flash"`; it already accepts any string.
- `example_toml.py` emits each new key commented out with its default and a one-line comment. `lemely.toml.example` is regenerated to match, and the existing test comparing the two must stay green.

- [ ] **Step 1: Write the failing tests:**
  - `test_defaults_reproduce_current_behaviour`: every new field equals its documented default.
  - `test_example_toml_lists_new_keys`
  - `test_anthropic_key_from_env_is_secret`: the value is redacted in `repr`.
  - `test_cache_mode_for_rejects_unknown_mode`
- [ ] **Step 2: Run** `pytest tests/test_cost_ladder_settings.py tests/test_runtime_config.py tests/test_config_new_tasks.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the fields and regenerate `lemely.toml.example`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit:** `feat(config): cost-ladder lever settings, defaults off`.

### Task 4: Cache mode per task tag (frozen upstream)

**Files:**
- Modify: `lemely/io/gemini.py`, only where a call's effective cache mode is chosen (the place that reads `self.default_cache_mode` when the caller passes no `cache_mode`)
- Test: `tests/test_gemini_cache_mode_for.py`

**Interfaces:**
- Consumes: `GeminiSettings.cache_mode_for` (Task 3).
- Behaviour: effective mode = the call site's explicit `cache_mode`, else `settings.gemini.cache_mode_for[task_tag]`, else `self.default_cache_mode`. A screen of a correction lever then runs with the client default `read_write` and `cache_mode_for = {"correction": "bypass", "correction_borderline": "bypass", "escalation": "bypass"}`. Extraction and binding replay from the baseline's cache, and correction is paid live.
- `RunManifest.cache_mode` keeps recording the client default. The runner (Task 5) records `cache_mode_for` separately.

- [ ] **Step 1: Write the failing tests:**
  - `test_tag_override_bypasses_only_that_tag`: with a fake client and a warm cache for tags `extraction` and `correction`, and `cache_mode_for={"correction": "bypass"}`, extraction is served from cache and correction calls the model.
  - `test_explicit_call_site_mode_wins`
  - `test_empty_map_is_todays_behaviour`
- [ ] **Step 2: Run** `pytest tests/test_gemini_cache_mode_for.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_gemini_cache_mode_for.py tests/test_gemini_client.py tests/test_gemini_cost_record.py -v`. Expected: PASS.
- [ ] **Step 5: Commit:** `feat(gemini): per-task-tag cache mode for frozen-upstream screens`.

### Task 5: Ladder runner and report

**Files:**
- Create: `lemely/accuracy/cost_ladder/runner.py`, `lemely/accuracy/cost_ladder/report.py`, `scripts/cost_ladder.py`
- Test: `tests/test_cost_ladder_runner.py`

**Interfaces:**
- Consumes: `measure_accuracy(cases, gemini_client, settings, *, run_id, split, arm, cost_probe)` (`lemely/accuracy/harness.py`), `AccuracyResult.question_results` / `.metrics` / `.funnel`, `process_call_records()` and `set_call_context()` (Task 1), `RunSummary`, `judge` and `aa_floor` (Task 2), and settings (Tasks 3 and 4).
- Produces:
  - `summarise(result: AccuracyResult, records: list[CallRecord]) -> RunSummary`:
    - mismarked parts are `{case/qid for scored question results with predicted_marks != truth_marks}`;
    - `usd_per_script_mean` is the mean over cases of the summed `usd_2027`;
    - `latency_p95_ms` is the nearest-rank p95 over cases of the summed `latency_ms`;
    - `validity_rate` is the share of records with `parse_ok`;
    - `incomplete` lists cases with a funnel shortfall or a failed call.
  - `run_config(label: str, overrides: dict, *, out_dir: Path) -> RunSummary` applies the setting overrides, runs the 12 cases, and writes `<out_dir>/<label>/summary.json`, `records.jsonl` and `results.json`.
  - `write_ladder(rows: list[LadderRow], out: Path)`. Its table columns: lever, expected saving, measured saving (2027), extra mismarks / allowed, id-match, p95 latency, validity, proof, verdict, reasons. The footer gives final against baseline at both 2026 and 2027 rates, and the stop reason.
  - `scripts/cost_ladder.py` provides three subcommands:
    - `baseline` runs the baseline and the A/A rerun and prints the floor;
    - `screen --label L --set key=value ...` runs one configuration and judges it against a given `--against` summary;
    - `report` writes `LADDER.md`.
  - The case set is pinned by `--golden tests/golden --split dev`. The run asserts corpus digest `76989782d6fda9fc` and aborts on mismatch.
  - The script refuses to run without the wrapper-provided key env, and never echoes it.

- [ ] **Step 1: Write the failing tests** (fake harness result and fake records, with no model calls):
  - `test_summarise_counts_only_scored_mismarks`
  - `test_summarise_uses_2027_usd`
  - `test_latency_p95_nearest_rank`
  - `test_incomplete_case_listed`
  - `test_corpus_digest_mismatch_aborts`
  - `test_ladder_table_has_reasons_and_stop_line`
- [ ] **Step 2: Run** `pytest tests/test_cost_ladder_runner.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_cost_ladder_runner.py tests/test_cost_ladder_gate.py -v`. Expected: PASS.
- [ ] **Step 5: Commit:** `feat(accuracy): cost-ladder runner and report`.

### Task 6: Rung-0 live baseline (accuracy-measurer agent; spends money)

**Files:** `BUILD/accuracy-runs/cost-ladder-<date>/baseline/`, `.../baseline-aa/`, `.../SPLIT.md`

- [ ] **Step 1:** Run `python scripts/cost_ladder.py baseline --golden tests/golden --split dev --out BUILD/accuracy-runs/cost-ladder-<date>` through the key wrapper, with the client default `bypass`. Expected spend: under $1.
- [ ] **Step 2:** Write `SPLIT.md`:
  - $ per script at 2027 rates, split by tag × attempt × token kind (input, cached, output, thinking);
  - the escalation and borderline fire rates;
  - the cache-hit share;
  - the binder's thinking level as actually sent (expected `medium` for `binding_read`);
  - confirmation that no gemini-3.8-flash record carries thinking `minimal`, which the API rejects (design §6.3);
  - the A/A floor.
- [ ] **Step 3:** Run the `accuracy-reviewer` agent over `SPLIT.md` against `records.jsonl`. The numbers must be recomputable from the records.

### Task 7: Re-rank checkpoint (orchestrator, no code)

- [ ] **Step 1:** Compute the expected saving of A1, A2, A3, B1 and B2 from `SPLIT.md`.
- [ ] **Step 2:** If B1 or B2 beats any of A1–A3, amend this plan. Swap that lever into Phase A with its own build and screen tasks, written to the standard of Tasks 10–13. Then stop and get the user's approval before continuing.
- [ ] **Step 3:** If correction is no longer the largest share, stop and report to the user. Phase A as written assumes it is.

### Task 8: Anthropic provider adapter

**Files:**
- Create: `lemely/io/providers/__init__.py`, `lemely/io/providers/anthropic_adapter.py`
- Modify: `lemely/io/gemini.py` (in `generate_structured`, dispatch to the adapter when the resolved model starts with `claude-`; cache lookup and store, ceiling check, retry and `_record_spend` stay in `GeminiClient`), `pyproject.toml` (add `anthropic` with a version floor at the current release, confirmed via the `claude-api` skill), `docs/deployment.md` (document the `ANTHROPIC_API_KEY` secret)
- Test: `tests/test_anthropic_adapter.py`

**Interfaces:**
- Consumes: `GeminiSettings.anthropic_api_key` (Task 3), `price_call` and `CallRecord` (Task 1), and the `thinking_level_for` levels.
- Produces:
  - `class AnthropicAdapter: def generate(self, *, model: str, system_prompt: str, user_prompt: str, response_schema: type[BaseModel], thinking: str | None, cache_prefix: str | None) -> tuple[BaseModel, Usage]`
  - `Usage(input_tokens, cached_tokens, output_tokens, thinking_tokens)`
- Behaviour:
  - Use the official SDK's structured output with a JSON schema built from `response_schema`. Validate the result with pydantic, and enforce mark bounds in code: `0 <= awarded_marks <= max` comes from the question, because the provider schema cannot express min and max.
  - Mark the system prompt (and `cache_prefix` when given) with prompt caching.
  - Map thinking levels to Anthropic effort: minimal and low map to `low`, medium to `medium`, high to `high`.
  - Map 429, 529 and 5xx onto the client's `_TransientError`, so the existing retry policy applies. Other 4xx errors are not retried.
  - Images are not supported. A call with `image_parts` and a `claude-` model raises `ValueError`, because Phase A uses Anthropic for correction only.
  - The implementer loads the `claude-api` skill before writing SDK calls, and confirms the Haiku 5.5 model id, the structured-output parameter names and the effort parameter.
  - The cache key gains a provider component only for `claude-` models, so every Gemini key stays byte-identical.

- [ ] **Step 1: Write the failing tests** (fake SDK client):
  - `test_schema_roundtrip_ai_mark_response`
  - `test_out_of_bounds_marks_rejected`
  - `test_usage_fills_call_record_with_provider_anthropic`
  - `test_transient_error_retried_permanent_not`
  - `test_effort_mapping`
  - `test_images_rejected`
  - `test_gemini_cache_keys_unchanged`: a fixed Gemini call's key equals the value captured before this task.
  - `test_dispatch_by_model_prefix`
- [ ] **Step 2: Run** `pytest tests/test_anthropic_adapter.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_anthropic_adapter.py tests/test_gemini_client.py tests/test_gemini_cost_record.py tests/test_gemini_cache_mode_for.py -v`. Expected: PASS.
- [ ] **Step 5: Commit:** `feat(io): Anthropic provider adapter behind model-prefix dispatch`.

### Task 9: A1 screen, correction model switch (accuracy-measurer; spends money)

- [ ] **Step 1:** Screen `a1-flash-lite`: `--set gemini.correction_model=gemini-3.1-flash-lite`, with `cache_mode_for` bypassing the three correction tags, against the baseline. Keep escalation on `gemini-3.8-flash`.
- [ ] **Step 2:** Screen `a1-haiku`: `--set gemini.correction_model=<haiku-5.5-id>` with the same settings. This needs Task 8.
- [ ] **Step 3:** For each screen, record the verdict, the per-model confidence AUROC (right vs wrong marks) and the escalation fire rate.
- [ ] **Step 4:** If both pass, ship the one with the lower 2027 $ per script. If one passes, ship it. If neither passes, A1 fails; record that and continue to Task 10 with the model unchanged. Shipping is a one-commit change of the `correction_model` default, with `pre-commit` run first.
- [ ] **Step 5:** Run the `accuracy-reviewer` agent on the verdicts.

### Task 10: Cascade with fitted triggers (A2 build)

**Files:**
- Modify: `lemely/io/correction_ai.py` (the `correct` method's step-1 and step-2 blocks)
- Create: `scripts/cascade_sweep.py`, `tests/test_correction_cascade.py`

**Interfaces:**
- Consumes: the cascade settings from Task 3, the `attempt=` and `question_id=` keywords from Task 1, and `process_call_records()`.
- Behaviour, when `cascade_enabled`:
  1. The first pass runs on `correction_model`.
  2. It re-marks on `cascade_strong_model or escalation_model` (`attempt="escalation"`) when any enabled trigger fires:
     - confidence below `cascade_threshold_for.get(correction_model, escalation_confidence_threshold)`;
     - with `cascade_two_pass_disagreement`, a second cheap pass (`attempt="borderline"`, same model, `extra_cache_key` suffix `:pass2`) awards different marks;
     - with `cascade_unaddressed_points`, the response's `point_verdicts` leaves any mark-scheme point unaddressed. When that field is empty, this trigger is inert.
  3. The borderline thinking retry is skipped while the cascade is on.

  When `cascade_enabled` is False, behaviour and cache keys are unchanged.
- `scripts/cascade_sweep.py`: given a screen directory with logged first-pass outputs and the baseline's strong-model outputs, it sweeps thresholds from 0.50 to 0.99 in 0.01 steps, combined with each trigger combination. For each it simulates the marks and the cost from the records, with no API calls, and prints the cheapest combination that would pass `judge()`.

- [ ] **Step 1: Write the failing tests:**
  - `test_cascade_off_is_byte_identical` (prompts and cache keys)
  - `test_low_confidence_escalates_to_strong`
  - `test_high_confidence_does_not_escalate`
  - `test_disagreement_trigger_fires_on_mark_mismatch`
  - `test_unaddressed_point_trigger`
  - `test_unaddressed_trigger_inert_without_point_verdicts`
  - `test_borderline_retry_skipped_under_cascade`
  - `test_fitted_threshold_per_model`
  - `test_sweep_picks_cheapest_passing` (synthetic records)
- [ ] **Step 2: Run** `pytest tests/test_correction_cascade.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_correction_cascade.py tests/test_correction_ai.py tests/test_correction.py -v`. Expected: PASS.
- [ ] **Step 5: Commit:** `feat(correction): cascade with fitted triggers behind cascade_enabled`.

### Task 11: A2 sweep and confirm screen (accuracy-measurer; spends money)

- [ ] **Step 1:** Run one logging screen, `a2-log`, stacked on the post-A1 configuration. Settings: `cascade_enabled=true`; `correction_model` = the cheap model; `cascade_threshold_for={<cheap model>: 1.0}` so every leaf gets a real strong re-mark; `cascade_two_pass_disagreement=true` and `cascade_unaddressed_points=true` so pass 2 is logged. Export `LEMELY_CASCADE_LEAF_LOG=<out>/a2-log/cascade_leaves.jsonl` and delete that file before any rerun. This screen's own verdict is not a shipping decision; it only feeds the sweep.
- [ ] **Step 2:** Run `scripts/cascade_sweep.py --loo` and pick the cheapest combination that passes `judge()` on the full run and on every 11-case subset.
- [ ] **Step 3:** Run one live confirm screen with the chosen settings against the post-A1 configuration.
- [ ] **Step 4:** Ship on PASS (a one-commit defaults flip). Record the verdict either way.

### Task 12: Shared prefix per paper (A3 build)

**Files:**
- Modify: `lemely/io/prompts/correction_ai.py`, and the call site in `lemely/io/correction_ai.py` where the system prompt is built
- Test: `tests/test_correction_shared_prefix.py`

**Interfaces:**
- Produces: `build_shared_prefix(mark_scheme: MarkScheme, *, reader_describes_drawings: bool) -> str`. It returns the system prompt followed by the paper's full mark scheme, rendered deterministically: questions in source order, stable formatting, and no timestamps or ids that vary between scripts.
- Behaviour, when `correction_shared_prefix`:
  - the system prompt sent is `build_shared_prefix(...)`, identical for every leaf of every script of the paper;
  - the user prompt keeps only the leaf-specific part;
  - with `correction_prefix_cache="explicit"` on a Gemini 3.x model, the client creates a `cached_content` per (paper, prompt version, model) with a 10-minute TTL and reuses it;
  - with a `claude-` model, the prefix goes through the adapter's `cache_prefix`.

  When the flag is off, prompts are unchanged.

- [ ] **Step 1: Write the failing tests:**
  - `test_flag_off_prompts_unchanged`
  - `test_prefix_identical_across_leaves_and_scripts`
  - `test_prefix_at_least_4096_tokens_on_cost201_papers` (count with the repo's existing token-estimate helper, or `len(text)//4` as a floor, and report each paper's size)
  - `test_leaf_text_only_in_user_prompt`
  - `test_explicit_cache_created_once_per_paper` (fake client)
- [ ] **Step 2: Run** `pytest tests/test_correction_shared_prefix.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_correction_shared_prefix.py tests/test_correction_ai.py tests/test_correction_cascade.py -v`. Expected: PASS.
- [ ] **Step 5: Commit:** `feat(correction): shared per-paper prompt prefix for caching`.

### Task 13: A3 screen, Phase A close and the final report

- [ ] **Step 1:** Screen `a3-implicit` (`correction_shared_prefix=true`) against the post-A2 configuration. Confirm `cached_tokens > 0` on correction records; if not, record why, for example a prefix under 4,096 tokens. Then screen `a3-explicit` only if the implicit screen showed no cache hits.
- [ ] **Step 2:** Ship on PASS.
- [ ] **Step 3:** Apply the gate between phases. If $ per script at 2027 rates is cut by 50% or more from the rung-0 baseline, record "Phase B skipped". Otherwise record "Phase B required", and the orchestrator writes `docs/superpowers/plans/<date>-llm-cost-ladder-phase-b.md` for levers B1–B11 in the design §6.2, after the user approves.
- [ ] **Step 4:** Run `python scripts/cost_ladder.py report` to write `LADDER.md`.
- [ ] **Step 5:** Run the `accuracy-reviewer` and `verifier` agents over `LADDER.md` and the shipped diffs. Every verdict must be recomputable from the stored summaries.
