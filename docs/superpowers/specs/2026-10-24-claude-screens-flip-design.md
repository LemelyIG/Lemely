# Sub-project C: Claude lever screens and the default flip

Status: approved design, 2026-10-24. Follows sub-projects A and B (PR #323, merged as `e80cb9fc`). Sub-project D (Gemini removal) comes after this.

## Goal

Every task tag defaults to Claude. The flip ships only once a measured gate shows the Claude configuration is no worse than Gemini on real handwriting and on the synthetic ladder, and is at most $0.10 per script. Before the flip, the Claude-native and B levers are screened one at a time, and only the winners go into the flipped configuration.

## Starting point (evidence)

- One real script, 0625/41 w24 (19 pages, 43 marked leaves, 80 marks):
  - Claude Haiku 5.5 after the binding fixes: $0.0445 per script (enhanced mean), 60/80 in both enhanced runs, binding `pass`.
  - Gemini: $0.158, 58/80, `hold`.
  - Reports: `BUILD/accuracy-runs/claude-e2e2-0625-w24-41-enh1/COST.md`, `BUILD/accuracy-runs/e2e-0625-w24-41-2026-10-19/COST.md`.
- **The teacher's mark for that script is 66/80.** The corrected copy (`~/testing/0625_w24_qp_41-(66..80).pdf`, identical to `~/Downloads/P4 N24 V1.pdf`) shows a tick per answer. Both models under-mark, Claude by 6 and Gemini by 8. This is the largest accuracy gap known, and it is larger than any cost lever.
- Review queue: Claude flags 13 to 19 of 43 leaves, Gemini 9. Of Claude's flags, 8 to 12 come from confidence below 0.90 alone.
- Second-read thinking is bimodal: about 12.5k thinking tokens in 2 of 4 runs and none in the other 2. That costs up to $0.0064 and 60 s.
- The cost ladder (`BUILD/accuracy-runs/cost-ladder-2026-10-19/LADDER.md`) already accepted Haiku for correction on the 12 synthetic dev cases (0 extra mismarks).

## Decisions (by the user)

- End state: a full flip, gated. Levers are screened first, and the winners ship in the flip. Gemini stays available through config until D.
- Ground truth: a reference made by Opus 5.5 and reviewed by the user. For 0625/41 the reference is the teacher's ticks.
- Real set: the local scripts only (listed in P0); no script over 22 pages exists, so the tier guard is unit-tested.
- Flip bar: "not worse than Gemini" (defined in P1).
- Levers: all four groups (binder thinking, the built B levers, borderline and adjudication, the review threshold).
- Approach: extend the cost-ladder harness with a real split rather than ad-hoc drivers.

## Global constraints

- At most $0.10 per script, for every script in the real set, not just the mean.
- Anthropic spend is capped at $40 in total, tracked in `BUILD/accuracy-runs/cost-ladder-spend.json` ($0.6396 used at the start). C's estimate is $15 to $20.
- The default Gemini path stays byte-identical until P4: `tests/test_llm_golden.py` passes, and `tests/fixtures/llm_golden/` is never regenerated.
- Student data is never committed: reference files, extracted answers, per-leaf marks, records, events and caches. Only counts go into committed reports.
- No student data goes through the Message Batches API.
- API keys are read inside scripts from `~/.config/lemely/{anthropic,gemini}_key`, never on a command line or in an env assignment.
- Signed, path-scoped commits; pre-commit before each commit; no full test suite locally.
- Every new check has a test proven red against a failing input.

## Phases

### P0. Reference set

| Script | Model input | Truth source |
|---|---|---|
| 0625/41 w24 | `~/Documents/P4 N24 V1_annotated (NO Corrections).pdf` | Teacher ticks, transcribed by Opus from the corrected copy. The user confirms each leaf. Leaf marks must sum to 66. |
| 0625/22 s23 (MCQ) | `~/testing/0625_s23_qp_22-(34..40).pdf` | Ticks if legible; otherwise the MCQ key applied to the letters the user confirms. Must sum to 34. Marking is deterministic, so this script tests extraction only. |
| 0625 s25/w24/w25 paper 42 (#59 stylus fixtures) | the rasterised copies listed in `BUILD/accuracy-runs/handwritten-59/raster-manifest.json` | Opus marks each leaf against the scheme with quoted evidence. The user reviews the flagged leaves. |

The corrected copy of 0625/41 is never given to a model under test. Only the reference builder reads it.

Tool: `scripts/build_reference.py`.

- It is resumable and caches per script.
- Opus calls go through `GeminiClient`, so the ledger, records and spend cap apply.
- Output goes to `BUILD/accuracy-runs/claude-c-reference/<script>/` (uncommitted):
  - `reference.json`, one entry per leaf: `question_id`, `mark`, `max_marks`, `source` (`teacher_tick` | `opus` | `user_override`), `evidence`, `note`;
  - `REVIEW.md`, which lists the leaves to check first.
- A leaf goes on the check-first list when any of these holds:
  - Opus, the latest Gemini mark and the latest Claude mark disagree;
  - Opus confidence is below 0.8;
  - the leaf takes part in a gap to the teacher total;
  - the tick is ambiguous.
- Review happens in the session. For each flagged leaf the main session shows the page crop (rendered locally), the scheme point and the three marks. The user replies with a mark or "ok", and an override is stored as `user_override`.
- After review a script is frozen. `manifest.json` in the same directory records each reference's sha256 and the source sha256s.

### P1. Harness: real split and three judges

The code lives in `lemely/accuracy/cost_ladder/`.

**Real split**
- A new case type, `RealScript`: scan path, scheme path, reference path and reference sha256. It is loaded from `BUILD/accuracy-runs/claude-c-reference/manifest.json`.
- `run_config` takes `split="dev" | "real" | "both"`. Real cases run the production `correct_paper` path (scan metadata, binder reads, correction), the same path the E2E driver used.
- Scoring per leaf, against the reference:
  - `abs_error` = the sum of |mark − reference|;
  - the exact rate and the within-1 rate;
  - the review rate (`needs_teacher_review` leaves ÷ leaves);
  - the binding verdict per script;
  - dollars per script;
  - latency.
- A missing, dropped or unbound leaf counts as mark 0. A drop can never shrink the denominator.
- `RunSummary` gains these fields, with defaults that keep dev-only runs and the existing tests unchanged.
- **Noise:** every rung runs twice, and its figures are the mean of the two runs. The real-split A/A floor is the `abs_error` difference between two identical base runs.

**Judges** (pure functions in `gate.py`, each returning a `Verdict` with every failed reason):

1. `judge` (existing) for cost-cutting levers.
2. `judge_accuracy_lever` for levers that add cost or aim at accuracy. It passes when all of these hold:
   - real-split `abs_error` falls by at least the A/A floor;
   - synthetic extra mismarks stay within the floor;
   - every real script is at most $0.10;
   - the review rate rises by no more than 5 percentage points, unless `abs_error` falls.
3. `judge_flip` for the candidate against a Gemini rung. It passes when all of these hold:
   - real-split `abs_error` ≤ Gemini's;
   - synthetic extra mismarks against Gemini stay within the floor;
   - every real script is at most $0.10;
   - binding passes ≥ Gemini's binding passes;
   - the review rate ≤ Gemini's + 10 percentage points.

The runner refuses to start when any of these holds:
- a reference sha256 differs from the manifest;
- the corpus digest has drifted;
- a model in play is unpriced.

An incomplete script fails the rung.

**Threshold fit:** the pure parts of `scripts/fit_review_threshold.py` (`evaluate`, `threshold_grid`) move into `lemely/accuracy/` and the script keeps its CLI. The fit picks the lowest threshold that still flags at least 90% of the leaves with `abs_error > 0` against the reference. It makes no API calls.

### P2. Fixes before the screens

These are diagnosis first. A fix lands only with evidence and a red test.

1. **Under-marking on 0625/41.** With the reference in hand, compare the stored E2E outputs leaf by leaf ($0) and bucket each lost mark:
   - binding (wrong or missing leaf; 7c's 3 marks are unmarked in every run);
   - transcription;
   - marking judgement;
   - scheme parse.

   Binding and transcription causes are fixed here. A marking-judgement cause becomes a P3 lever instead (a prompt change, or adjudication).
2. **`pass` with G5 failed (enh1).** Trace `verdict()` on the stored gate result. If the rate rule explains it, document it. If it is a leak, fix it.
3. **Latency regression.** 371 to 442 s against 330 s for Gemini, with more than 150 s of preparation that the logs don't account for. Add stage timings, find the cause, and fix it if cheap. Target: at most Gemini's time.
4. **Haiku >100k tier guard.** When an image request on a tiered Claude model estimates more than 100k input tokens:
   - step the image size down;
   - if it still does not fit, force the chunked read;
   - log `claude_tier_guard`.

   Unit-tested with a synthetic 24-page estimate.
5. **Escalation rate.** Haiku made 0 `escalation` calls in all four E2E runs, even though 3 to 4 leaves per run were below `escalation_confidence_threshold` (0.80) and Claude confidences sit at 0.80 to 0.85, just above it. Confirm which triggers can escalate when `cascade_enabled = false`:
   - the confidence threshold;
   - `escalate_on_mark_mismatch`;
   - `escalate_on_defaulted_marks`;
   - and the others.

   Record the rate the flipped config would produce. Moving escalation to Sonnet costs 20x Haiku per call. A small downward shift in Claude's confidences could therefore turn many leaves into Sonnet calls. See "Escalation rate" below.
6. **Minors:**
   - the per-script cost scope also covers the CLI and batch paths (today only the web routes warn);
   - `extract_json` and a bracket in prose that never closes;
   - harden the timing of `tests/test_web_teacher.py::test_a_row_queued_for_the_run_slot_is_alive_and_not_lost_while_it_waits`.

### P3. Screens

Base: Claude Haiku 5.5 on every tag, the current E2E settings, with every lever off. Each lever is screened alone, twice, on both splits.

| Id | Lever | Judge |
|---|---|---|
| a1 | Second binder read at effort `none` | cost |
| a2 | First binder read at effort `none` | cost |
| a3 | Relax the effort-equality condition in `_reads_share_a_claude_cache`. A live probe showed reads at different efforts still hit the prompt cache. | cost, run after a1/a2 |
| b1 | `correction_citations` with `uncited_mark` as a review trigger | accuracy |
| b2 | `correction_terse_rationale` | cost |
| b3 | `binding.claude_chunked_read` forced on | accuracy |
| c1 | No borderline calls | cost |
| c2 | Leaf-scoped Sonnet adjudication | accuracy |
| d | Review threshold, fitted last on the stacked config | fit, no judge |

Adjudication (c2):
- It is a new task tag, `adjudication`, on `claude-sonnet-5-5`.
- Its prompt holds one leaf: that leaf's page crops, its scheme points, and Haiku's mark and rationale.
- It runs on leaves with confidence below 0.80, or with a disagreement between the binder reads.
- It is capped at 3 leaves per script.
- The Gemini path is untouched.

Stacking order: cost winners, then accuracy winners, then the threshold fit on the stacked configuration.

### Escalation rate

Escalation moves from Haiku (as in the E2E runs) to `claude-sonnet-5-5` at the flip. Sonnet's input, cache-write and output rates are 20x Haiku's. The escalation rate is a cost driver, so it is tracked throughout:

- **Reporting.** Every rung reports:
  - the escalation rate (escalated leaves ÷ leaves, per script and mean);
  - escalation dollars per script and their share of the script cost;
  - which trigger fired for each escalated leaf.

  These figures go into `LADDER.md` and `FLIP.md`.
- **Pricing in the screens.** From the screens onward, the base and every rung run escalation on `claude-sonnet-5-5`, the model it will use after the flip. Escalation cost is therefore measured, not estimated.
- **Fit.** When lever d fits the review threshold, it also fits `escalation_confidence_threshold` (or `cascade_threshold_for`) for Haiku. The fit is done on the stacked configuration's confidences, against the reference, with no API calls. It picks the threshold that escalates the leaves with `abs_error > 0` while keeping every script at or below $0.10 at Sonnet prices.
- **Cap.** If the stacked configuration escalates more than 10% of leaves on any script, add a per-script escalation cap (most-uncertain leaves first) as an extra cost lever. It is screened with `judge` before the flip.
- **Flip bar.** `judge_flip` reports escalation rate and escalation dollars next to its checks. Every real script must stay at or below $0.10 with escalation included.

### P4. Flip

It goes in only if `judge_flip` passes for the stacked configuration against a Gemini rung (two runs each).

New defaults in `lemely/runtime/config.py`:
- `claude-haiku-5-5` for mark scheme, extraction, correction (and borderline, if kept), scan metadata, generation, and the binder `read_model` and `second_read_model`;
- `claude-sonnet-5-5` for escalation, the binder `retry_model` and adjudication;
- plus the winning levers and the fitted threshold.

Tags that are not screened (generation, study_plan, self_review_judge) flip only after a smoke test: one live call each, where the output parses against its schema, is priced, and is not empty. A tag that fails stays on Gemini, and the PR names it.

Also updated:
- `lemely.toml.example` and `example_toml.py`;
- `lemely doctor`: `ANTHROPIC_API_KEY` is required when any tag resolves to a `claude-` model, and `GEMINI_API_KEY` only when one resolves to `gemini-`;
- `docs/deployment.md`: the ZDR note for code execution and the Files API.

Golden test: it must keep pinning the Gemini path. If it reads the default settings, P4 first makes it pass explicit Gemini settings (a test-only change; the fixture is unchanged).

The flip is its own PR, separate from P0 to P3, so it can be reverted cleanly.

## Error handling

- Every live run goes through `_CapGuard` and the spend ledger.
- Upload failures fall back to inline images (existing behaviour).
- A failed call makes its script incomplete, and the rung fails. Nothing is dropped silently.
- A reference changed after freeze, a corpus drift or an unpriced model stops the run before any spend.

## Testing

- Unit tests:
  - the real-split loader, with the sha256 check proven red;
  - scoring that counts drops as 0;
  - each of the three judges, each proven red on a crafted failing summary;
  - the threshold fit;
  - the tier guard;
  - the adjudication tag (request shape, the 3-leaf cap, cost scope, Gemini path untouched);
  - the P2 fixes.
- Locally, run only the touched test files, plus `tests/test_llm_golden.py` and the source-scanning tests. CI runs the full suite.

## Deliverables

- Committed:
  - code and tests;
  - this spec and the plan;
  - `BUILD/accuracy-runs/claude-c-<date>/LADDER.md` and `FLIP.md`, holding counts only.
- Uncommitted: `BUILD/accuracy-runs/claude-c-reference/`, plus per-leaf outputs, records and caches.

## Out of scope

- Removing Gemini code, which is sub-project D.
- UI changes.
- Scripts over 22 pages live (none exist locally).
- Other subjects.
