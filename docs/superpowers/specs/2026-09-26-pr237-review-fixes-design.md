# Fixing the ten PR #237 review findings

Date: 2026-09-26. Status: design approved in conversation; awaiting spec review.

Branch `feat/ai-improvements`, base `b32860f3`. Every file:line anchor below is at that SHA.

## Problem

`/code-review high` on PR #237 posted ten findings. Each was verified at `b32860f3`, either by a reproduction or by reading the code. The ideation record, with the probes, is `review-fixes-ideation.md` in the job scratch directory.

| # | Finding | Where | Effect |
|---|---|---|---|
| 1 | The verdict path adds up alternative and optional-pool points and only caps at `question.marks` | `correction_ai.py:819-862` | Over-award with no review flag. Reproduced: 2/2 where the marker itself claimed 1 |
| 2 | Scans are rasterised at 200 DPI with no page or pixel limit | `rasterise.py:64` | One upload can exhaust the 1 GiB worker |
| 3 | `second_reader.read()` has no error handling | `answer_extraction.py:938-949` | A failure in the optional second read throws away the paid primary extraction |
| 4 | The dropped-answer check runs before answers are consulted | `correction_ai.py:1883-1936` | A malformed duplicate entry wins over a valid answer for the same id |
| 5 | The generation gate compares stated answers exactly | `question_gates.py:207, :243` | 3 s.f. and unit-bearing answers are rejected; valid questions are dropped |
| 6 | Removed F4 keys are filtered from env and TOML, but not from `.env` | `config.py:1083` | A stale `.env` line crashes `load_settings`, so `lemely doctor` and the web app fail to start |
| 7 | Code-execution calls skip the thresholds, `BUDGET_EXCEEDED` and per-task totals | `gemini.py:1229` | Budget warnings are never published; `question_validity` spend is missing from the totals |
| 8 | `CostCeilingError` is caught as an `ExternalServiceError` in the sandbox step | `question_gates.py:162` | A ceiling breach turns into "sandbox produced no usable result" |
| 9 | Crop-and-re-read makes up to 15 paid high-resolution calls per paper, and nothing reads the result | `answer_extraction.py:995-1022` | Spend and latency with no effect |
| 10 | The Step-2 escalation guard compares against the original call, not the Step-1 retry | `correction_ai.py:188-249` | With the defaults, the same model is billed twice at the same thinking level |

Two facts found during ideation shape the design:

- **Written answers are not reviewed on extraction confidence.** Only the MCQ builder reads extraction confidence (`correction_ai.py:356`). Written answers are flagged on the marker's own confidence (`:1172`). So the re-read is the only signal that a written answer was misread.
- **Extraction sends every page inline, in one request.** At 200 DPI the committed fixture's PNG pages measure 0.59–1.98 MB. The 16-page fixture is about 22 MB, which is already over Google's documented 20 MB inline limit. A 40-page paper would be 55–80 MB.

## Decisions

The user made these calls during brainstorming:

| Topic | Decision |
|---|---|
| #1 | Cap each scheme group at its maximum. **No** review flag when a cap applies. |
| #2 | Hybrid: pages within a band above the target are downscaled; pages beyond it are rejected. |
| #5 | Stated answers match at **3 significant figures**, through a gate-local helper. No prompt change. |
| #6 | Filter removed keys out of the dotenv source; `doctor` reports them. |
| #7 | One shared, locked `_record_spend` for both Gemini call paths. |
| #9 | A disagreeing re-read sends the question to teacher review. The cap becomes a setting, default **15**. A new marking option, `reread_substitution` (default off), marks the re-read text instead. |
| Re-read latency | Bounded concurrency with a wall-clock budget, fully wired and on by default. |
| Inline size | Whole-paper page images go through the **Gemini Files API**. Pages stay PNG. |
| #3, #4, #8, #10 | As recommended in the ideation record. |

## Design

### 1. Group-capped verdict totals (#1)

`_group_points` moves from `lemely/db/question_points.py:146-239` to a new module, `lemely/core/point_groups.py`, as the public `group_points`. The code is unchanged. `question_points.py` imports it back under its old name, so `derive_point_rows` and its tests do not change.

`_awarded_from_verdicts` returns `_VerdictTotals(capped, additive, matched_point_ids)`:

- Independent points add their tariff.
- Each scheme group adds `min(group cap, sum of awarded tariffs in the group)`.
- The total is capped at `question.marks`.

Groups come from scheme order, so the result does not depend on the order of the verdicts. I6's metamorphic property still holds.

Capping without a flag needs two more changes. The probe showed that without them the capped total trips the coherence check ("implies between 2 and 2").

- `_check_coherence` mode 2 becomes group-aware **on the verdict path only**, through a new `groups=` keyword. For each matched group the minimum contribution is the smaller of the group cap and the largest member tariff, and the maximum is `min(cap, sum of member tariffs)`. The legacy call (`:1160`) passes no groups and keeps today's global rule.
- The coverage check (`:967`) compares against `additive`, not `capped`. A marker that awarded both alternatives and claimed 2 is then not reported as "answer_points may not fully describe its marking scheme".

### 2. A surviving answer beats a dropped duplicate (#4)

`dropped_ids = _dropped_question_ids(extracted_answers) - answers.keys()`, where both sides are normalised ids. The docstring of `ExtractedAnswers.dropped_question_ids` is updated to say this.

### 3. Step-2 compares against the call that actually ran (#10)

`correct_paper` records `last_call = (model, thinking)` for each call it makes. Step 2 runs only if `(escalation_model, escalation_thinking) != last_call`. The existing test `test_borderline_mark_produces_three_calls_all_on_3x_correction_model` asserts the bug. It is rewritten so Step 2 runs only when escalation thinks harder than Step 1.

### 4. The re-read becomes a review signal, with optional substitution (#9)

**Review reason.** In `lemely/io/reread.py`, `REREAD_REVIEW_AGREEMENT_THRESHOLD = 0.8` is the plan's 0.8 applied to the difflib agreement measure. It carries the same caveat as `second_read.py:77-84`.

`_flatten_answers` returns a `_FlatAnswer` NamedTuple that also carries `answer_reread` and `reread_agreement`. A re-read disagrees when `reread_agreement` is not `None` and is below the threshold, EXCEPT on an MCQ leaf where the re-read normalises (fix round 2: strip surrounding punctuation/brackets, upper-case) to the SAME letter as the first read -- "A." or "(A)" against "A" is agreement, whatever the raw difflib score says. The flag and reason are added at one place: the post-loop assembly in `correct_paper`, where the question list is finished. They apply to rows whose `marker_source` is `ai` or `deterministic`. Any existing reason is kept and joined with `" | "`. Dropped, blank and missing rows are not touched.

Fix round 1 briefly extended the flag to a `blank` row (first read empty) whose re-read found non-blank text, on the theory that the re-read saw something extraction missed. Fix round 2 reverted this: a reviewer reproduced first read `""` / re-read `"a"` flagging the row, which makes `low_confidence_review_needed` (`review_queue_rules.py`) return True, which makes `is_marking_low_confidence` True, and `self_review.decide_point` then GRANTS any challenged point on that row with no evidence. The re-read text comes from the MODEL, not the student -- it is Gemini's own second look at the crop, never anything the student entered -- so the risk is not a student writing a fake re-read: it is that ANY non-blank re-read on a genuinely blank first read, including one the model simply hallucinated over blank pixels, would grant self-mark authority on a question the student left blank, with nothing a human could point to as evidence. Known gap, deliberately left open: the proper fix belongs in the self-review authority gate itself (what counts as evidence for a GRANT), not in correction, which has no way to tell a genuine recovered answer from a hallucinated one -- so a blank row stays exactly as `_build_blank_corrected` left it, same as before this story.

The reason quotes both readings, each cut to 60 characters. It has three shapes:

- Substitution off: `extraction re-read disagreed with the first read (agreement 0.42 < 0.80); marked the first read 'x', the re-read gave 'y'`
- Substitution on and applied: `...; marked the re-read 'y', the first read was 'x'`
- Substitution on, but the re-read is empty: `...; the re-read returned nothing usable, marked the first read 'x'`

**`reread_substitution`.** This is a third field on both halves of the Plan 3 pair: `MarkingOptions.reread_substitution` and `GradingSettings.reread_substitution`, both `bool = False`. So every marking path carries it, and the Plan 3 AST guard covers it with no change. The option works on its own; it does not depend on `equivalence_gate`, so there is no "inert" warning case. The startup `marking_flags` line gains the field.

When the option is on, the re-read disagrees and the re-read text is not blank, the leaf is marked on `answer_reread`. This happens before dispatch, so it applies to the deterministic MCQ path and the AI path alike; a misread letter is the typical case. `student_working` is unchanged. `CorrectedQuestion.student_answer` already stores the text that was marked, so the stored record stays truthful. **The review flag still fires when substitution is on.** Substitution must never hide a disagreement from the teacher.

The teacher sees both readings with no schema change: `studentAnswer` holds the marked text, `review_reason` quotes the other reading, and the crop shows the pixels. Structured `firstRead`/`reread` fields on the review wire are a later UI story.

The option is set per environment like the other two flags:

- `LEMELY_GRADING__REREAD_SUBSTITUTION`, with a `deploy.yml` line reading `vars.GRADING_REREAD_SUBSTITUTION`, default `'false'`;
- a new row in `docs/ci-cd.md`;
- a commented `[grading]` entry in `lemely.toml.example`, framed like `equivalence_gate`: it changes how papers are marked, so leave it off.

The harness appends `|reread_substitution=True` to `params_fingerprint` **only when the option is on**, so the pin `af7fa9cd0e2a` does not move.

**Settings.** New `GeminiSettings` fields:

| Field | Default | Bounds | Meaning |
|---|---|---|---|
| `max_rereads_per_paper` | 15 | `ge=0` | Per-paper cap; 0 disables the stage |
| `reread_concurrency` | 4 | 1–16 | Worker threads for the re-read stage |
| `reread_budget_seconds` | 45.0 | `> 0` | Wall-clock limit for the whole re-read stage |
| `upload_concurrency` | 4 | 1–16 | Parallel Files API uploads (section 7) |

`GeminiAnswerExtractor` keeps its `max_rereads_per_paper: int | None = None` keyword. When the keyword is `None`, the extractor takes the value from its client's settings; it reads concurrency and budget from the same place. The three construction sites do not change.

### 5. Concurrent re-reads under a wall-clock budget

**Why it matters.** The student grading run executes inside the request as an SSE stream (`student.py`, `StreamingResponse(bus_event_stream(...))`). Cloud Run's `--timeout=300` therefore bounds the whole run: extraction, second read, re-reads, every marking call and persistence. The teacher run is a daemon thread started after a 202 (`teacher.py:426`). Sequential re-reads at 3–6 s each would cost 45–90 s of that window.

**Numbers.**

- **Concurrency 4.** The workers are I/O-bound, so four threads cost nothing on one vCPU. 15 re-reads finish in about 4 rounds, roughly 12–24 s. That is far below Gemini's paid-tier request limits. Above about 8 threads there is no latency gain, and 429s become more likely; those are already retried as transient.
- **Budget 45 s.** This caps the stage at 15% of the 300 s window, even in the worst retry case of 3 attempts plus 6 s of backoff.

**Mechanics.** `GeminiAnswerExtractor._run_rereads` replaces the sequential loop. It uses a `ThreadPoolExecutor(max_workers=min(concurrency, n))`.

- Each worker checks the deadline and a stop `Event` **before** issuing its call. No re-read starts after the budget runs out or after a ceiling breach. Calls already in flight finish; an HTTPS call cannot be aborted, and the retry policy bounds it.
- Each worker runs under `contextvars.copy_context().run`, so bus events from a worker carry the run id.
- A `CostCeilingError` in any worker sets the stop event. The pool drains, then the error is re-raised out of `__call__`.
- Any other `LemelyError` publishes `REREAD_FAILED`, as today.
- Results are reassembled in the extractor's answer order, whatever order they complete in.
- An answer that was not re-read keeps its first read, with `answer_reread` and `reread_agreement` set to `None`.

**Telemetry.**

- A new `EventType.REREAD_BUDGET_EXHAUSTED` event carries `budget_seconds`, `started` and `skipped`.
- A new field, `ExtractedAnswers.reread_skipped_by_budget`, records the skipped count.
- `reread_attempts` now counts re-reads **started**, and its docstring says so.

**Thread safety.** `GeminiClient` mutates only the process spend counters and the cost ledger per call. Both move under a module-level `_SPEND_LOCK` (section 9). Cache writes go to per-key files with distinct question ids, so they do not collide.

### 6. Scan geometry limits (#2, hybrid)

A new pure module, `lemely/io/scan_limits.py`, holds the constants:

| Constant | Value | Why |
|---|---|---|
| `MAX_SCAN_PAGES` | 40 | The committed question paper has 16 pages; answer booklets with continuation sheets reach the low 30s. |
| `MAX_PAGE_PX` | 16 Mpx | The target after downscaling. A4 at 400 DPI is 15.5 Mpx, the top of normal document scanners. The corpus at 200 DPI is 3.87 Mpx. |
| `MAX_DECODE_PX` | 40 Mpx | The reject boundary. This is the crop route's existing `_MAX_DECODE_PX` (`review.py:340`), moved here so the app has one "too big to open" number. It is 2.5 times the target, which is the downscale band. |
| `EXTRACTION_DPI` | 200.0 | Moved from `rasterise.py`, which re-exports it. |

Pixels are counted at 200 DPI for a PDF page, and at native size for an image.

- **Up to the target:** used as is.
- **Between the target and the reject boundary:** downscaled to fit.
  - A PDF page is rendered at `floor(200 * sqrt(MAX_PAGE_PX / px))` DPI, the crop route's formula.
  - A JPEG (which includes MPO) uses `draft` at native scale.
  - Other image formats decode, then `reduce(k)` by the smallest integer that fits. That is at most a 120 MB transient, once.
- **Beyond the boundary, or more than 40 pages:** `ScanTooLargeError`, a `LemelyError` whose message says which limit was exceeded. PIL's `DecompressionBombError` maps to the same error.

**Whole-scan pixel budget (final review I1, user decision: hybrid, 160 Mpx).** The per-page rule alone does not bound a scan: 40 pages at the 16 Mpx cap is 640 Mpx, and a 1.13 MB PDF of 40 such pages sharing one JPEG rendered to ~1.5 GB of pages held at once, past the 1 GiB worker. So after the per-page rule, `plan_pdf_pages` sums the planned pixels over every page. Up to `MAX_SCAN_TOTAL_PX = 160_000_000` nothing changes (an honest 40-page A4 scan at 200 DPI is 155 Mpx). Over it, every page's DPI is multiplied by one factor `s = sqrt(160 Mpx / sum)` and floored, and that DPI reaches `RasterisedPage.dpi`. If any page would drop below `MIN_EXTRACTION_DPI = 100`, the scan is refused with `ScanTooLargeError`: a 422 at upload, the same error at extraction. An image upload is one page capped at 16 Mpx, so the budget never binds there.

`rasterise.py` plans every page before rendering any, so the page cap applies first. `RasterisedPage` gains a `dpi` field. The existing fixtures fall below the target, so their bytes do not change.

**Where the 422 happens.** Both grading flows run outside a plain request/response, so an error at extraction time becomes a failed status, not an HTTP code. The clear error therefore happens at **upload**:

- `upload_utils.check_scan_geometry(data)` raises a 422 with the limit message. It runs right after `check_upload_cap` at `teacher.py:762` and `student.py:679`.
- `check_upload_cap` still returns 413 for oversize bytes.
- The check reads page sizes and image headers only; it renders nothing.
- Extraction repeats the same check as a second line of defence.
- `review.py` imports `MAX_DECODE_PX` from the new module, and its behaviour is identical.

### 7. Whole-paper pages go through the Files API

Pages stay lossless PNG, and only the transport changes. Every whole-paper image call uses the Files API, with no size threshold. A size threshold would mean a second transport path and a point where a paper's behaviour suddenly changes, and both paths would need tests. The upload round costs about 3–6 s for 40 pages; that is small next to a 10–30 s extraction call. Re-read crops stay inline: each is a single PNG of about 50–300 KB.

**What exists today.** The pre-I1 upload is one line, `files.upload(file=fp)` at `gemini.py:1050`. It sits inside `_call_once`, so every retry re-uploaded the file. Nothing in the codebase deletes uploaded files or waits for them to become `ACTIVE`. That `file_paths` branch, used by the mark-scheme parsers, is left as it is. In google-genai 2.10.0, `Part.from_uri` accepts `media_resolution`, so the extraction and second-read resolutions carry over unchanged. The comment at `:1027-1030` saying otherwise is corrected.

**Client (`gemini.py`).** A new `ImageUploads` object, created by `GeminiClient.image_uploads(images)`:

- `ensure()` uploads every image once, with up to `upload_concurrency` in parallel. It keeps page order and is thread-safe and idempotent. Each upload uses `io.BytesIO` with `mime_type="image/png"`.
- Each upload runs under the same tenacity policy as a generate call. To share it, the transient classification at `:1097-1103` is extracted into `_is_transient(exc)` and the `retry(...)` configuration into `_retry_policy()`. When retries are exhausted, the upload raises `ExternalServiceError`.
- A file that is not `ACTIVE` is polled with `files.get` every 0.5 s for up to 30 s, then raises `ExternalServiceError`. Images are expected to come back `ACTIVE` at once; the poll is a guard.
- `delete()` removes every uploaded file, in parallel, on a best-effort basis. A failed delete logs `gemini_file_delete_failed` and never fails the paper. The 48 h server-side expiry is the backstop.
- `__exit__` calls `delete()` on both the success and the failure path.

`generate_structured` gains an `image_uploads=` argument:

- The cache key is still computed from the `image_parts` **bytes**. A cache hit returns before anything is uploaded, so a warm harness sweep uploads nothing.
- On a miss it runs `_check_cost_ceiling()` first, then `ensure()`, both **outside** `_call_with_retry`, so a retried generate call never re-uploads.
- `_call_once` builds `Part.from_uri` parts in page order and never builds `inline_data`.
- Passing `image_uploads` without `image_parts` is a `ValueError`.

Uploads return no `usage_metadata` and are not billed as tokens, so `_record_spend` is not called for them. Nothing is counted twice.

**Extractor (`answer_extraction.py`, `second_read.py`).** `__call__` wraps everything from the primary call to its return in `with client.image_uploads(page_bytes) as uploads:`. `SecondReader.read` and both of its implementations gain `image_uploads=`, which they pass straight through. As a result:

- the second read reuses the same URIs, so each page is uploaded once per paper;
- leaving the block deletes the files after a success, a `CostCeilingError`, any other exception, and a re-read stage that ran out of budget.

**Privacy.** Before this PR the whole PDF went through the Files API and was never deleted, so this adds no new data flow. It shortens retention from 48 h to the length of the run.

**Caches and the pin.** The cache key is still `model:prompt_hash:files_hash(page bytes):params_fingerprint`, so existing cache entries stay valid, and URIs never enter the key. `_params_fingerprint` and the run-manifest fingerprint gain nothing, so `af7fa9cd0e2a` does not move.

### 8. The second read cannot lose the primary extraction (#3)

`second_reader.read` is wrapped in the same pattern the re-read block already uses:

- `CostCeilingError` is re-raised first.
- Any other `LemelyError` publishes a new `EventType.SECOND_READ_FAILED` and sets `second_read_texts = None`.
- Extraction continues with the primary answers, and `extraction_agreement` stays `None`.

### 9. Spend accounting (#7, #8)

**#7.** `GeminiClient._record_spend` is the body of `gemini.py:1106-1176`, moved into one helper that both `_call_with_retry` and `_call_code_execution_once` call.

- The read-modify-write section, meaning the four process counters and `CostLedger.add`, runs under `_SPEND_LOCK`.
- The log line, the `BUDGET_*` publishes and `GEMINI_CALL_END` run after the lock is released, so the bus is not serialised.
- `_reset_process_counters` and the reads in `_check_cost_ceiling` take the same lock.
- The structured-call log line keeps exactly the fields it has today, including `params_fingerprint`.
- The code-execution call adds `tool="code_execution"`, and receives the `params_fingerprint` that `generate_with_code_execution` already computes.

**#8.** In the sandbox step in `question_gates.py`, `except CostCeilingError: raise` comes before the `(ParseError, ExternalServiceError)` handler. The comment is the one from `mark_schemes.py:96-106`.

### 10. The generation gate compares at 3 s.f. (#5)

In `question_gates.py`:

- `GATE_SIG_FIGS = 3`. This is the IGCSE/A-level convention, and a generation-gate policy, not a marking tolerance.
- `_compare_stated(exact, stated)`, used at both compare sites (`:207` and `:243`).

When the exact side parses to a constant with no free symbols, `_compare_stated`:

- evaluates it numerically with `sympy.N`, because a constant symbolic difference otherwise gets no tolerance window;
- strips one trailing unit from the stated answer.

It then calls `equivalent(..., sig_figs=GATE_SIG_FIGS)`. An unparseable exact side takes today's path with the tolerance added. `equivalence.py` is not changed.

Measured on the probe:

- **Accepted:** `22/7`/`3.14`, `9.81*2`/`19.6`, `100/3`/`33.3`, `sqrt(2)`/`1.41`, `2*pi`/`6.28` and `0.5*3*4**2`/`24 J`.
- **Still rejected:** `27.5` vs `25`.

### 11. Removed keys in `.env` (#6)

- **Filtered source.** `_RemovedKeysDotEnvSource`, a subclass of `DotEnvSettingsSource`, filters removed keys out of `_load_env_vars()` (keys are lower-cased; verified on pydantic-settings 2.14.2). `settings_customise_sources` returns it in place of the default dotenv source.
- **Doctor report.** `find_removed_config_keys` also reads `dotenv_values(Path.cwd() / ".env")`: the process working directory, which is where pydantic resolves `env_file=".env"`. So `lemely doctor` reports a stale `.env` key as a warning, without failing.
- **Comment.** The "both supply paths" comment now says three.

## Testing

Each fix starts with a failing test that reproduces the finding, is shown red, and then goes green. The plan names every test. The key ones:

- **#1:** the either/or case from the review (`p1`, `p1a` alternative, `p2`; `p1` and `p1a` awarded) gives 1/1 with no flag. Also: an any-N pool capped at `select_count`, order independence, and a claim above the additive sum still tripping coverage.
- **#2:** a page within the band renders at a lower DPI; a 14400 pt page is rejected; 41 pages are rejected before any render; images are reduced or rejected; the committed fixture is unchanged. Both upload routes return 422 on oversized geometry.
- **#3:** a failed second read keeps the primary answers and publishes `SECOND_READ_FAILED`; a ceiling breach still propagates.
- **#4:** a surviving answer for a dropped id is marked, not short-circuited.
- **#5:** the six rounded or unit-bearing pairs verify at `sympy` with no code-execution call; the existing 10%-wrong rejection stays green.
- **#6:** a removed key in `.env` no longer crashes `load_settings`; `find_removed_config_keys` and `doctor` report it.
- **#7:** a code-execution call publishes a crossed `BUDGET_WARNING` and `BUDGET_EXCEEDED` and is attributed to its task tag.
  - **Lock:** a deterministic test asserts `_SPEND_LOCK` is held around `CostLedger.add`, and a soak test gets exact totals under 8 concurrent callers.
- **#8:** a ceiling breach in the sandbox call propagates.
- **#9 review reason:** each of the three reason shapes; `None` or high agreement leaves the flag alone; an existing reason is kept.
- **#9 substitution:** marks the re-read text, still flags, skips an empty re-read, and requires disagreement.
  - **Flag plumbing:** projection, `marking_flags`, the deps wiring, and the fingerprint moving only when on.
- **#10:** Step 2 is skipped when it would repeat Step 1, and runs when escalation thinks harder.
- **Concurrency:** re-reads overlap up to the configured concurrency, proved with a `Barrier`; no re-read starts after the budget; a ceiling in one worker stops the rest and propagates; result order is kept; worker events carry the run id.
- **Files API:**
  - **Transport and reuse:** URI parts only, no inline data; the second read reuses the uploads; cache-hit calls upload nothing.
  - **Retries and cache key:** a retried generate call does not re-upload; the cache key is identical to the inline-bytes key.
  - **Lifecycle:** files are deleted on success, on failure and on a ceiling breach; a failed delete only warns.
  - **Uploads:** they overlap up to `upload_concurrency`; the ceiling is checked before any upload.
  - **Worst case:** a 40-page paper of incompressible 2 MB pages builds no inline payload at all.

Threaded tests prove overlap with a `Barrier`, not sleeps, and use side-effect functions keyed on the prompt, never ordered lists. Fixtures are generated in the test; no student scans are committed, because the repo is public.

The pin guard is `tests/test_accuracy_harness.py`: `af7fa9cd0e2a` at `:1586`, and `test_flag_off_fingerprint_is_unchanged` at `:1631`. It runs in the task that adds the harness segment and again in the final gate sweep.

## Risks

- **#1 changes verdict-path marks.** An over-awarded alternative now drops. `PointVerdictGoldenFixtureTests` may need a golden updated; the commit body gives the reason. The verdict path is behind `equivalence_gate`, which is off in production.
- **#9 raises the review rate on written answers.** The CI review-rate gate reads the committed `BUILD/review-rate-baseline.json`, so CI does not move. A re-measured baseline would. The commit body says so.
- **Concurrency adds threads to the request path.** The spend lock, context propagation and ceiling cancellation are the guards, and each has a test.
- **The Files API adds a network round and a new failure point before extraction.** A failed upload fails the extraction the same way a failed extraction call does today. Deletes are best-effort, with the 48 h expiry as the backstop.
- **The Files API has project storage quotas.** Deleting after each run keeps usage near zero.
- **The review-reason text is user-visible to teachers.** It quotes student text. That text is already shown on the same screen.

## Out of scope

- Structured `firstRead`/`reread` fields on the teacher review wire (a later UI story).
- The legacy-path `_check_coherence` mode 2 stays global.
- The constant-symbolic-difference limitation in `equivalence.py` on the marking path.
- `_call_code_execution_once` sends no temperature, seed or thinking settings.
- There is no latency budget for the primary extraction call or the second read. The student run is still bounded only by Cloud Run's 300 s.
- Moving the mark-scheme parsers' `file_paths` upload onto `ImageUploads`.
- A size-threshold hybrid of inline and Files API transport.
