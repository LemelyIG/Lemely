# Claude provider: parity and Claude-native levers (design)

Date: 2026-10-19
Branch: `feat/cost-ladder`
Status: approved in brainstorming, awaiting spec review

## Context and goal

Lemely plans to move every LLM task off Gemini and onto Claude, and then remove Gemini. That move has four sub-projects, each with its own spec:

| | Sub-project | This spec |
|---|---|---|
| A | Parity: every task tag can run on a `claude-` model | yes |
| B | Claude-native levers: cache breakpoints, citations, effort per tag | yes |
| C | Migration screens: choose model and effort per tag, flip defaults | no (next) |
| D | Gemini removal: drop `google-genai`, rename `GeminiClient` to `LLMClient` | no |

Nothing here runs in production yet. Claude stays a development provider until C flips the defaults.

**Headline target.** At most **$0.10 per marked paper**, end to end, with mark-scheme parsing amortised over the paper's scripts. It is measured on the real script `0625_w24_41` with the E2E driver. The Gemini figure for the same script is $0.158 (run at `01f371c3`). A rough Haiku 5.5 estimate is $0.03–0.05; that is arithmetic, not a measurement.

**Standing rule.** All LLM and marking work looks for cost and accuracy opportunities (section 8).

## Starting point

- `lemely/io/gemini.py` (`GeminiClient`, about 2,400 lines) owns the response cache, retry, cost ceiling, cost ledger and `CallRecord`. It dispatches `claude-` models to `lemely/io/providers/anthropic_adapter.py`.
- Commits `188542b1` and `4e065532` added page images for Claude and `BindingSettings.second_read_model`. Their review returned **Needs fixes**:
  - **Critical.** Real scans render at 2430×3439 RGB. The 19-page script is 79.6 MB base64 after downscaling, against the 30 MB request limit, so every real script is refused. The synthetic test images were tiny and hid this.
  - **Important.** The Claude path has a fixed 16,000-token output cap. It ignores `max_output_tokens_for` and is unmeasured for a 19-page binder read.
  - **Minor.**
    - The cache key has no image-preprocessing version.
    - `resized.save(...)` sits outside the `try` in `_fit`.
    - The `lemely.toml.example` `second_read` comment is stale.
- These are fixed in T2 below, not separately.
- Still Gemini-only:
  - `file_paths` (PDFs): `parsers.py:26` for the mark-scheme fallback, `scan_metadata.py:44`.
  - `generate_with_code_execution`: `question_gates.py:355`.
- Missing prices: Sonnet, Opus and Fable rows; cache-write rates; Haiku's above-100k tier.

## Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Spec scope | A + B together |
| Architecture | Provider interface: `LLMRequest` plus a `Provider` protocol; the client keeps the shared machinery |
| PDFs | Per caller: typed PDFs (mark schemes) as native `document` blocks, scans rasterised to images |
| Code execution | Claude's server tool, not a Google Cloud or local sandbox (cheaper at our volume, and no sandbox for us to secure) |
| Haiku 100k tier | Preflight, then downscale best-effort. If the floor is reached, send anyway, price the higher tier and warn. The extra cost is accepted only where no other reduction exists. |
| B levers | Cache breakpoints, citations, effort per tag. The 1h cache TTL was dropped. |
| Opportunities in scope | Blank-leaf skip, effort by leaf kind, greyscale everywhere, terse rationale |
| Data rule (standing) | Student data goes only through the synchronous Messages API, never the Batch API |

## 1. Architecture

New package `lemely/io/llm/`:

- `request.py`: `LLMRequest`, a frozen dataclass holding:
  - `model`, `task_tag`, `system`, `prompt`, `response_schema`;
  - `images: tuple[ImageInput, ...]` and `documents: tuple[DocumentInput, ...]`;
  - `tool: CodeExecution | None`, `cache_plan: CachePlan`, `effort`;
  - `fingerprint()`, the single source for the provider part of the cache key.
- `provider.py`: the `Provider` protocol:
  - `complete(req) -> ProviderReply`, where `ProviderReply` is the text plus `Usage`;
  - `count_tokens(req) -> int | None`.
- `gemini_provider.py`: today's Gemini call code, moved unchanged. It keeps the Files API uploads, `media_resolution` and Gemini code execution.
- `claude_provider.py`: today's `anthropic_adapter.py`, extended with documents, the code-execution tool, cache breakpoints and citations.
- `image_fit.py`: the pure image-fit policy (section 2).
- `pricing.py`: the price table with tiered rows (section 3).

`GeminiClient` keeps the response cache, retry, cost ceiling, ledger and `CallRecord`.
- **Per call:** it builds an `LLMRequest`, picks the provider by model prefix and calls `complete`.
- **Callers:** its public method signatures do not change, so the ~20 callers stay as they are, except the three in section 3.
- **Rename:** the change to `LLMClient` belongs to D.

**Invariant.** With today's configured Gemini models, the following stay byte-identical before and after this work:
- cache keys;
- logged events;
- `CallRecord` fields that exist today;
- outputs.

T0 pins this with a golden test before the refactor begins.

## 2. Image fit and budgets

`image_fit.fit(images, *, byte_limit, token_budget, floor_px) -> FittedImages`:

1. **Greyscale.** Convert to greyscale PNG. The exception: a page where a colour detector finds meaningful colour ink keeps its colour.
2. **Estimate.** Tokens per page are estimated as `w*h/750`.
3. **Step down.** While the request is over `token_budget` or `byte_limit`, step the long edge down: 2576, 2200, 2000, 1800, 1568.
   - `token_budget` defaults to 95,000: the 100k tier line, less headroom for the prompt.
   - `byte_limit` is 30,000,000 base64 bytes.
4. **Floor.** `floor_px` defaults to 1568 (about 135 DPI on A4) and is configurable. It marks the point below which handwriting is treated as unreadable.
5. **Still over the token budget at the floor.** Send at the floor, price at the higher tier and log `claude_over_tier` (pages, estimated tokens, tag).
6. **Still over the byte limit at the floor.** This is the only refusal: a `ProviderError` that names the page count and the byte total.

Further rules:

- **Order.** Images keep page order.
- **Cache-key version.** The fit result is deterministic in the input bytes and the policy constants. The anthropic fingerprint segment gains `img_fit=v1`, so a policy change invalidates replies cached under the old policy.
- **Encoding errors.** Raise `ProviderError` with the page number (encode inside the `try`).
- **Preflight.** When the estimate is within 10% of the budget, the free `count_tokens` endpoint confirms it. The count is logged, never part of the cache key.
- **Output cap.** The Claude path honours `max_output_tokens_for[tag]` when set, and otherwise uses the adapter default. The cap goes into the fingerprint, as `max_tokens` already does.
- **Cost guard.** Each script's ledger total is compared with `paper_cost_target_usd` (default 0.10). Going over logs `script_over_cost_target` with the split by tag. It never blocks marking.

## 3. Parity: PDFs, code execution, pricing

### PDFs

`DocumentInput(data: bytes, media_type="application/pdf", cache: bool, citations: bool)`.

- **Claude.** One base64 `document` block, placed before the images and the text, with `cache_control` when `cache` is set. The 32 MB request limit is checked before sending. The page limit is confirmed against the official docs in T4 and enforced with a `ProviderError`.
- **Gemini.** `GeminiProvider` maps `documents` back onto today's `file_paths` upload, so the Gemini behaviour is unchanged.
- **Callers.**
  - `parsers.py` (mark scheme, typed PDF): sends a `document`.
  - `scan_metadata.py` (scan): rasterises with the existing `rasterise_pdf_to_pages` and sends images through `image_fit`.
  - `file_paths` stays accepted for Gemini. On Claude, only the callers converted here are supported. Any other `file_paths` use raises, naming the caller.

### Code execution

- **Request.** `LLMRequest.tool = CodeExecution()` maps to `code_execution_20260521` on Claude. The version string is confirmed against the docs in T5.
- **Reply.** The reply text is the final text block of the response, matching today's Gemini contract. `question_gates._run_code_execution` is unchanged: `None` still means "could not verify".
- **Cost.** Container seconds are read from the response and priced at $0.05 per hour. The free monthly allowance is ignored so the ledger reads high rather than low.
- **Data rule.** The tool is allowed only on non-student task tags (`question_validity`, `generation`). Any other tag raises. Code execution is not covered by zero data retention.

### Pricing (`pricing.py`)

- **Fields.** `PriceRow` gains:
  - `cache_write_5m` and `cache_write_1h`;
  - `tier_threshold_tokens` and a `tier2` row.
- **Rows.** Haiku 5.5, Sonnet 5.5, Opus 5.5 and Fable 5.1. Each row records its source URL and the date it was read. T3 re-reads every rate from the official pricing page; the brainstorming research numbers are not trusted on their own. For reference, the research reported:

  | Model | Input | Output | Write 5m | Write 1h | Hit |
  |---|---|---|---|---|---|
  | Haiku 5.5 ≤100k | 0.10 | 0.50 | 0.125 | 0.20 | 0.01 |
  | Haiku 5.5 >100k | 0.50 | 2.50 | 0.625 | 1.00 | 0.05 |
  | Sonnet 5.5 | 2 | 10 | 2.50 | 4 | 0.10 |
  | Opus 5.5 | 4 | 20 | 5 | 8 | 0.20 |
  | Fable 5.1 | 10 | 50 | 12.50 | 20 | 0.25 |

  ($ per million tokens.)
- **Usage fields.** `Usage` and `CallRecord` gain `cache_write_5m_tokens` and `cache_write_1h_tokens` (from `usage.cache_creation`), and `container_seconds`. The new fields default to 0, so existing records keep their meaning.
- **Tier selection.** The tier is chosen per request on total input: uncached plus cache write plus cache read.
- **`inference_geo`.** Stays unset, so the 1.1× multiplier never applies. A test asserts it is unset.
- **Unknown model.** A `claude-` model with no row raises `UnpricedModelError`, as today.
- **Doctor and model table.** For each tag, list the provider, model, effort and price row, and flag any tag with no row.

## 4. Claude-native levers (B)

All are off by default. Each is a config flag that sub-project C screens.

### B1. Cache breakpoints

`CachePlan(breakpoints, ttl="5m")`, set per tag through `claude_cache_for[tag]`.

- **Block order:** system prompt, then documents, then images, then per-call text. At most 4 breakpoints.
- **Small blocks.** A block under the model's 512-token minimum gets no breakpoint.
- **Binder.** A breakpoint after the images lets the second read hit the cache on every page.
- **Correction.** The existing `SharedPrefix` (lever A3) already places breakpoints on the instructions and the mark scheme. The flag turns it on for Claude.
- **Risk to verify in T6.** A cache hit needs an identical prefix. If changing effort between the two binder reads invalidates the cached message blocks, either both reads use the same effort, or the miss is accepted and reported. T6 checks the docs and a live pair of calls.

### B2. Citations

Flag: `correction_citations`.

- **Request.** The mark scheme goes in as a text `document` with `citations.enabled`. Every awarded mark carries its cited mark-scheme passage.
- **Check.** A deterministic check confirms each cited span exists in the mark scheme. A mark with no citation, or an invalid one, sets `review_reason="uncited_mark"`. This feeds the later review-signal work.
- **Risk to verify in T8.** Citations may not combine with structured outputs. If they don't, the fallback is an `evidence_quote` field in the schema, checked by the same substring check, with no API dependency.

### B3. Effort per tag and per leaf kind

`claude_effort_for: dict[str, Effort]`, keyed by tag or by `tag:kind`.

- **Lookup order:** the `tag:kind` key, then the tag key, then today's `effort_for(thinking_level_for[tag])`.
- **Kinds:** `mcq`, `numeric`, `short`, `extended`, taken from the leaf's mark-scheme answer type.
- **Values:** `low`, `medium`, `high`, `xhigh`, `max`.
- **Cache key.** Effort is already in it.

## 5. Opportunities in scope

1. **Blank-leaf skip.**
   - Flag: `correction_skip_blank`.
   - When a leaf's extracted answer is empty after the binding gate, it gets 0 marks, `marker_source="blank_skip"` and no model call.
   - T9 first confirms that no such path exists today. If one does, this item becomes a no-op.
2. **Effort by leaf kind.** Built as part of B3.
3. **Greyscale everywhere.** `image_fit` greyscale applies to every Claude image request (section 2, step 1), not only when fitting under a limit.
4. **Terse rationale.**
   - Flag: `correction_terse_rationale`.
   - A correction schema variant caps rationale length, saving output tokens.
   - Intended to pair with B2, so the evidence lives in the citations. It is screened in C, together with B2 and on its own.

Candidates recorded for C, not built here:
- one correction call per question rather than per leaf;
- Sonnet 5.5 adjudication only on leaves where the binder's two reads disagree;
- `uncited_mark` as the escalation trigger.

## 6. Errors

- `ProviderError` is permanent. `ProviderTransientError` is retried by the client's existing policy.
- **Image refusals** come only from the byte limit at the floor, and name the page count and the byte total.
- **Output cap.** Hitting the cap gets one fresh retry, as today, then fails.
- **Unpriced models** fail closed.
- **Code execution** on a student-data tag raises before sending.

## 7. Testing

- **T0.** A golden test pins Gemini cache keys, events and `CallRecord`s for representative calls of each tag.
- **Fake-SDK unit tests** for every feature, with no network.
- **Realistic image fixture.** 19 pages at 2430×3439, noisy RGB. It must fit under the byte limit and the token budget at or above the floor.
- **`inference_geo`.** A test asserts it is unset.
- **Live E2E (T9).**
  - The real script `0625_w24_41` runs with every task tag on `claude-haiku-5-5` and every lever on, from the pinned worktree, inside the existing $40 Anthropic cap.
  - It reports:
    - $ per paper against the $0.10 target, split by tag;
    - the binding verdict, and marks per leaf against the `01f371c3` Gemini run;
    - `claude_over_tier` and `script_over_cost_target` events.
  - Student-answer outputs stay uncommitted.
- **CI gate sweep** goes last, after the final commit.

## 8. Task order

| # | Task |
|---|---|
| T0 | Golden pin of Gemini behaviour |
| T1 | Provider refactor (`LLMRequest`, `Provider`, both providers); no behaviour change |
| T2 | `image_fit`, which fixes the review findings on `188542b1`/`4e065532` (critical byte limit, output cap, version token, encode in `try`, stale TOML comment) |
| T3 | Pricing: tiered rows, cache writes, container time, doctor |
| T4 | PDFs: document blocks, the `parsers.py` and `scan_metadata.py` callers |
| T5 | Code execution on Claude |
| T6 | B1 cache breakpoints |
| T7 | B3 effort per tag and per kind |
| T8 | B2 citations, then terse rationale |
| T9 | Blank-leaf skip |
| T10 | Live E2E on the real script; report against $0.10 |

Each task gets its own spec and quality review. T1 also gets a check that the T0 golden test still passes unchanged.

## Out of scope

- Default flips and per-tag screens (C).
- Removing Gemini and renaming the client (D).
- The Batch API (data rule).
- The 1h cache TTL (dropped in brainstorming).
- Production deployment of Claude and its secrets.
