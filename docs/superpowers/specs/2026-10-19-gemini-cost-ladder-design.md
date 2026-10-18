# LLM cost ladder: design

- Date: 2026-10-19
- Status: design approved in brainstorming, revised after web research; awaiting spec review
- Source requirements: `.omc/specs/deep-interview-gemini-cost.md` (deep interview, final ambiguity 19%)

## 1. Goal

Cut the LLM **$ per marked script on the web marking path** as far as the levers allow, while holding accuracy and latency inside the budgets in section 3.

The path is extraction, label binding (including `binding_second_read`), correction, the borderline retry and escalation. Mark-scheme parsing counts too, amortised over the scripts of its paper. Dev, sweep and live-acceptance spend, and question generation, are outside the metric.

Nothing is off-limits: models, thinking levels, prompts, the safety-net calls, and providers other than Google may all change.

Data protection for a non-Google provider is treated as already handled (decision of 2026-10-19). Anthropic offers no EU or UK data residency, and its zero-data-retention option does not cover its Batch API, so no student data goes to Anthropic's Batch API.

## 2. Evidence the design starts from

### 2.1 From the repository

- Correction makes one call per question leaf, not one per script (`lemely/io/correction_ai.py`, `task_tag="correction"`). The answer is sent as text; no page images go to correction. A first-pass confidence below `escalation_confidence_threshold` (default 0.80) triggers a borderline retry (`correction_borderline`), then an escalation (`escalation`). One leaf can cost up to three calls.
- MCQ leaves are already marked with no model call (`lemely/core/correction.py:correct_mcq_answers`).
- The correction system prompt (`marker_system_prompt`) is about 7,000–8,000 characters, roughly 1,800–2,000 tokens.
- The last cost run (`BUILD/accuracy-runs/cost-201-2026-10-01/report.json`, 12 cases, `cache_mode=bypass`) gives a mean of $0.0173 per script and a p95 of $0.0220. Correction is 83% of the spend and extraction 17%. The run predates the label binder (PR #310), so it is stale.
- `GeminiClient._record_spend` (`lemely/io/gemini.py`) counts prompt, candidate and thinking tokens but not `cached_content_token_count`.
- The pricing table already dates the end of the 3.x Flash promotion: gemini-3.8, 3.7 and 3.6-flash cost $0.75 / $3.75 per 1M tokens through 2026-12-31, then $1.50 / $7.50.

### 2.2 From web research (2026-10-19)

Prices are per 1M tokens, input / output.

| Fact | Consequence | Source |
|---|---|---|
| gemini-3.8-flash doubles to $1.50 / $7.50 (cached $0.15) on 2027-01-01 | Correction and the binder double in cost without any change; every comparison is priced at 2027 rates | ai.google.dev/gemini-api/docs/pricing |
| gemini-3.1-flash-lite: $0.25 / $1.50, cached $0.025 | Cheapest Gemini candidate for correction and extraction | same |
| Claude Haiku 5.5 (released 2026-10-07): $0.10 / $0.50 for prompts up to 100K tokens; cache read $0.01; minimum cacheable prompt 286 tokens | Cheapest strong correction candidate; needs a provider adapter | Anthropic pricing and models pages |
| Implicit caching needs a shared prefix of at least 4,096 tokens on 3.8 and 3.6-flash; hits are reported in `cached_content_token_count` | The ~2,000-token correction prompt never caches today | ai.google.dev/gemini-api/docs/generate-content/caching |
| Explicit caching (`caches.create`) works on 3.x and 2.5 models but not on Gemini 4 or later; with a 10-minute TTL it pays for itself after one reuse | A guaranteed alternative to implicit caching for a per-paper prefix | same |
| 3.8-flash defaults to `medium` thinking; `minimal` is rejected; thinking tokens bill as output | Any tag left on default thinking pays medium; the binder's first read must be checked | ai.google.dev/gemini-api/docs/generate-content/thinking |
| A Gemini 3 image costs a fixed 280 / 560 / 1,120 / 2,240 tokens at low / medium / high / ultra-high; the default is high | Image cost per page is small; greyscale or JPEG tricks save nothing | ai.google.dev/gemini-api/docs/media-resolution |
| Batch and Flex are 50% off; Flex targets 1–15 minutes and can shed load | Only mark-scheme parsing can use them | ai.google.dev/gemini-api/docs/batch-mode, /flex-inference |
| gemini-3.7-flash was deprecated on 2026-10-08 and now routes to 3.8-flash | Remove the 3.7 references | ai.google.dev/gemini-api/docs/changelog |
| Khan Academy cascade study: cascades cut cost 76% at kappa 0.802 vs 0.819; Haiku 4.5 was the best small model (kappa 0.783) with usable confidence; a Gemini Lite model's self-reported confidence was nearly useless | A cascade needs a confidence signal fitted per model, or a second trigger | arXiv 2604.19781 |
| Self-reported grading confidence is skewed: 86% of scores above 0.8 | The fixed 0.8 trigger probably rarely fires | arXiv 2603.29559 |
| Medly GCSE benchmark: small models at minimum reasoning effort match examiner–examiner agreement; Gemini 3.1 Flash-Lite competitive in science and maths | Supports cheaper correction models and lower thinking | arXiv 2606.24973 |
| Putting several items in one prompt costs up to 4 pp accuracy | Multi-leaf calls are demoted to the tail | Cheng et al. 2023 |
| 42–66% of handwritten-maths transcriptions silently correct the student's mistakes | Any extraction change must be checked for over-correction | arXiv 2604.22774 |
| LiteLLM PyPI 1.82.7 and 1.82.8 shipped a credential stealer (2026-03-24) | No routing library; write the adapter in-house | docs.litellm.ai security update, March 2026 |

## 3. Budgets and pass rule

Every lever is judged on the 12 `cost-201` cases, against the configuration it is stacked on. **All $ figures, including the baseline, are priced at the rates in force from 2027-01-01.**

| Saving from the lever | Extra mismarked question parts allowed |
|---|---|
| under 30% | no more than the A/A churn floor (one rerun of the rung-0 baseline on the same 12 cases; the same floor is reused for every later comparison) |
| 30% or more | up to `ceil(0.02 × scored parts)` extra mismarked parts; with the 31 scored parts of `cost-201`, that is 1 |

In both tiers:

- id-match must not drop;
- p95 latency per script must stay at or under 2× the original baseline;
- the structured-output validity rate must not drop;
- a run with any failed call or missing leaf fails.

Mismarks are counted per question part, not per script.

**Proof:** a lever that cannot change model output is proven by replay (response cache plus recorded inputs) with zero output diffs, and needs no live run. Every other lever gets one live screen. There is no full-corpus run. The accepted risk is that the 12 cases miss regressions on paper types they do not contain; the research agents flagged that 12 scripts cannot resolve a 2% per-part difference with confidence, and this risk was accepted.

**Frozen upstream:** when a lever touches only correction, the screen replays the baseline's extraction and binding outputs from the cache, so correction is the only thing that varies. The same holds in reverse for extraction and binding levers.

## 4. Architecture

Six units, each testable on its own.

### 4.1 Per-call cost record (rung 0)

`_record_spend` reads `cached_content_token_count` and prices cached input at the model's cached-input rate. A cached rate is added to the pricing table for each priced model. Each call emits one record: provider, task tag, model, thinking level, input / cached / output / thinking tokens, $ at 2026 rates and at 2027 rates, `latency_ms`, attempt (`first`, `borderline` or `escalation`) and question id. This changes no request, so it is proven by replay.

### 4.2 Baseline runner

The runner uses the existing `accuracy-measure` path, at `cache_mode=bypass`, on the 12 `cost-201` cases. It does one baseline run and one A/A rerun. For each configuration it reports:

- mean and p95 $ per script at 2027 rates, split by tag and by attempt;
- p95 latency per script;
- mismarked question parts;
- id-match;
- structured-output validity rate;
- escalation and borderline fire rates;
- for correction models, how well confidence separates right from wrong marks (AUROC).

Runs are stored under `BUILD/accuracy-runs/cost-ladder-<date>/`.

### 4.3 Provider adapter

A small adapter layer inside the existing client lets a task tag run on a non-Google model while keeping the client's retry, response cache, cost ledger and pricing table. The first adapter is Anthropic (Claude Haiku 5.5) through the official Python SDK. The pricing table gains a provider column. Model choice stays per task tag in settings (`correction_model` etc.), so a provider switch is a settings change. The adapter must:

- map the structured-output schema to the provider's form, and check mark bounds in code where the provider's schema cannot express min and max;
- use the provider's prompt caching for the shared prefix;
- map the thinking level to the provider's effort setting;
- report usage in the same per-call record as 4.1.

No third-party routing library is used.

### 4.4 Lever registry

Each lever is a settings flag (or a settings value) that defaults to the current behaviour. With its flag off, a lever produces byte-identical prompts and cache keys. Every flag that changes a request enters the cache-key fingerprint, so a replay can never serve an answer recorded under another configuration. Each lever's record holds: name, expected saving, proof type, measured result and verdict.

### 4.5 Gate

`judge(baseline, candidate, aa_floor) -> Verdict(passed, reason, tier, saving)` is a pure function with no I/O and no model access. It implements section 3 exactly.

### 4.6 Ladder report

There is one markdown table: one row per lever, with expected saving, measured saving at 2027 rates, per-part mismark delta, id-match, p95 latency, validity rate, proof type, verdict and reason. The report ends with the final $ per script and p95 latency against the original baseline, at both 2026 and 2027 rates, and states why the run stopped.

## 5. Flow

1. **Rung 0.** Ship the cost record (4.1). Run the baseline and the A/A rerun. Rank the levers by measured share.
2. **Phase A: ladder.** Take the top 3 levers by expected saving. Screen them one at a time. Each is screened on top of the last shipped configuration and judged against it. A passing lever ships, meaning its flag default flips. Phase A stops early if the next lever is expected to save under 5% of the current cost.
3. **Gate between phases.** If the shipped ladder has cut $ per script by **50% or more** from the rung-0 baseline, stop, and skip Phase B.
4. **Phase B: parallel tail.** Screen every remaining lever at the same time, each alone, on top of the post-ladder configuration. There is no per-lever floor; the gate decides. Combine the levers that pass, then screen the combination once. If the combination fails, drop the passing lever with the smallest saving and screen again. Repeat until the combination passes or no lever is left. Ship the combination that passes.

Replay-provable levers skip the live screen in both phases.

## 6. Levers

The order is provisional; rung 0 re-ranks by measured share. Savings are research estimates, not measurements.

### 6.1 Phase A candidates

| # | Lever | Hits | Proof | Expected saving |
|---|---|---|---|---|
| A1 | **Correction model switch.** Screen two candidates as alternatives, each on its own: gemini-3.1-flash-lite (no integration) and Claude Haiku 5.5 (through the 4.3 adapter). The better passing candidate ships. Escalation keeps a stronger model as its target. | correction | live | 55–85% of correction at 2027 rates |
| A2 | **Cascade with a fitted trigger.** First pass on the A1 model; re-mark on the strong model when one of these fires: confidence below a threshold fitted per model on the screen set, disagreement between two cheap passes, or mark-scheme points left unaddressed. Thresholds are swept offline on logged outputs. | correction | replay sweep, then one live confirm | recovers accuracy for A1; cost depends on fire rate |
| A3 | **Shared per-paper prefix.** System prompt plus the paper's whole mark scheme first, leaf-specific text last, so the prefix passes the 4,096-token implicit minimum (or uses explicit caching with a 10-minute TTL, or Anthropic caching). Every leaf of every script of the paper re-reads the prefix at about 10% of the input price. | correction | live (added context can change output) | 30–70% of correction input |

Binder thinking (B1) and the conditional second read (B2) move into Phase A if rung 0 shows the binder above any of A1–A3.

### 6.2 Phase B tail

| # | Lever | Hits | Proof | Expected saving |
|---|---|---|---|---|
| B1 | Binder thinking from the 3.8-flash default (medium) to low; output only the span-to-label map | binding | live | 30–70% of binder |
| B2 | Second read only on deterministic triggers: labels not matching the expected question set; missing, duplicated or out-of-order labels; ink with no label; extractor and binder disagree | binding | replay (trigger recall on past second-read catches must be 100%) | up to about 50% of binder |
| B3 | Exact-duplicate answer cache across students, keyed on leaf id, mark-scheme hash and normalised answer text; exact matches only | correction | replay | equals the duplicate rate on short leaves |
| B4 | Score first, short rationale; compact schema keys | correction | live | 5–25% of correction |
| B5 | Correction thinking low to minimal, on a model that supports it | correction | live | 20–60% of correction output |
| B6 | Extraction from 3.5-flash-lite to 3.1-flash-lite; checked for over-correction of student errors | extraction | live | 3–6% per script |
| B7 | Skip blank pages by template alignment and an ink-ratio check; uncertain pages still go to the model | extraction, binding | replay (zero false negatives on labelled pages) | 10–30% of the stage |
| B8 | `media_resolution` high to medium, per image | extraction, binding | live | under 10% of the stage |
| B9 | The binder labels the extractor's text spans instead of re-reading pages | binding | live | 20–50% of the combined stage |
| B10 | Mark-scheme parsing on Batch (50% off) | mark_scheme | replay or output diff | about 50% of a small amortised share |
| B11 | Several leaves per correction call | correction | live | medium; accuracy risk up to 4 pp |

### 6.3 Housekeeping (not levers)

- Remove references to gemini-3.7-flash, which now routes to 3.8-flash.
- Confirm no 3.8-flash call receives `minimal`, which the API rejects.

### 6.4 Rejected

Self-hosting (break-even around 460k scripts a month, GPUs not in a UK region, cold starts break p95); dedicated OCR services (no cheaper per page, and none does binding); Flex on the interactive path; Priority tier (1.8×); Contributor and free tiers (data used for training); LiteLLM and OpenRouter; prompt compression (breaks rubric-following); fine-tuning (needs thousands of agreed labels and ties the app to older models); already done: deterministic MCQ marking.

## 7. Error handling

- **Pricing:** a model with no row in the pricing table fails the run loudly, through the `fallback_pricing_status` path. A fallback price would understate the saving.
- **Incomplete runs:** a failed call or missing leaf in any case fails the gate, and the reason names the case.
- **Retries:** retries and escalations count in both $ and latency, so a lever that raises the retry rate pays for it.
- **Provider errors:** the adapter maps provider-specific transient errors onto the client's existing retry rule. A provider outage is not silently routed to another provider during a screen; it fails the run.
- **Spend:** a screen of about 12 × $0.03 stays well under the CLI's $8 `total_usd_ceiling`. Live runs read each provider's key through the scratch wrapper script, and no key is written to the repo.

## 8. Testing

Run only the touched test files locally; CI runs the full suite. Every check below must be shown to fail before the change it guards.

- `judge()`:
  - passes in each tier;
  - fails on extra mismarks above the floor (under 30%);
  - fails on extra mismarks above 2% of parts (30% or more);
  - fails on any id-match drop;
  - fails on any validity-rate drop;
  - fails on p95 above 2×;
  - fails on an incomplete run.
- Rung 0: a fake `usage_metadata` with cached tokens is priced at the cached rate; the 2027 price is used on and after 2027-01-01.
- Provider adapter: the schema mapping round-trips a known `AIMarkResponse`; out-of-bounds marks are rejected in code; provider usage fills the per-call record; a provider transient error is retried, a permanent one is not.
- For each lever:
  - with its flag off, prompts and the cache key are byte-identical to before;
  - with its flag on, the cache key changes.
- Cascade: each trigger re-marks on the strong model when it fires and not otherwise.
- `pre-commit run --all-files` and the repository's source-scanning lint tests pass before any commit.

## 9. Shipping a lever

Flip the flag default (or model setting) in `lemely/runtime/config.py`, the `lemely.toml.example` text and its generator `lemely/runtime/example_toml.py`, so `lemely doctor` shows the active value. A provider switch also needs the provider's API key handled as a secret in the same way as `GEMINI_API_KEY`, and documented in `docs/deployment.md`. Record the ladder row in the report.

## 10. Out of scope

- Web UI, billing tables, question generation.
- Spend in dev, sweeps or live-acceptance runs.
- A full-corpus validation run.
