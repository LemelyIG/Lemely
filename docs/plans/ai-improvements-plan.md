# Lemely AI Improvements Plan

Status: `approved` 2026-09-17 — execution not started. Amended after approval with the user's answers to
OQ1 (ceiling $14), OQ7 (both mark-scheme PDFs supplied), OQ6 (marginal + OR-gate, auto-upgrade at n₁ ≥ 100)
and D5 (approved) — see §7.
Produced by /ralplan consensus planning, 2026-09-16/17, against `develop` @ `5564fd14`.
Consensus: Architect (opus) ×2, Critic (opus) ×4 — Critic verdict **APPROVE** at iteration 4 (§7).
Execution: ralph + ultrawork, opus orchestrator, subagents routed sonnet/opus/fable by complexity (§8).
Sources: "Lemely AI Research Brief" (artifact 4826bdfe, 15 Sep 2026, B8 code-grounded 16 Sep), 8 digest/pointer
agents, 6 web re-verification agents (17 Sep), 8 interview rounds (decisions D1–D22, Appendix C).

Identifier legend: **Dn** = interview decision (Appendix C). **SDn** = verified defect in
`docs/ACCURACY-STRATEGIES.md` §2 (SD1–SD21). **Tn.m** = strategy item in the same doc §3. **D2.x / DAn / Cn /
#n** = BUILD/DECISIONS.md phase ids, decision records, rulings, GitHub issues. **[brief key n]** = brief
appendix citation. **Mn** = milestone in §3.

## 1. Summary

Lemely's marking error budget sits in vision, its review gate is a flat 0.90 self-report threshold with 14.29%
flag recall, and the accuracy programme that built the measurement instrument retired without a single human
label. This cycle: (M0) move to Gemini 3.x behind config and re-baseline once; (M1) switch extraction to
per-page images with bounding boxes and a second-read agreement seam, add a transcription error metric, fix
MCQ confidence leakage, flip mark-scheme parsing to Gemini-primary with deterministic verification; (M2) label
~300 real leaves, replace the threshold with a learned calibrator + Mondrian conformal gate at α = 0.10, add
a hidden random-audit stream served only through a server-side CLI export run by the `platform_admin` seat
(D5's "ops role" satisfied without a new role or a web tenancy bypass — approved by the user 2026-09-17), and an
offline drift canary; (M3) one batched marker
change — per-point verdicts with quoted spans, ecf by substitution, SymPy A-mark equivalence — then rubric
rewrites from the measured confusion matrix; (M4) remove the AI-text flag; (M5) gate generated questions with
local SymPy + sandbox fallback + validity check. Cost ceiling is $14 (ledger reset; raised from $7 by the
user on 2026-09-17), which funds every sweep in §3 including the I9 rubric rewrite, with ≈ $5 contingency.

### RALPLAN-DR summary

**Principles**
1. Measure before claiming: every accuracy item ships with a harness metric on the frozen split, paired
   McNemar vs. the M0 baseline, honest denominators (programme §14 anti-goals bind).
2. Determinism where the mark scheme allows it: SymPy, Python-summed verdicts, deterministic sampling.
3. Confidence is learned from labels, never read from the model; agreement and structure are features.
4. Human review is the compliance story (Ofqual 14 Jan 2026 principles, Cambridge digital-mocks precedent):
   the gate guarantees a miss rate, the review rate is reported.
5. One baseline line: migrate first, compare nothing across the 2.5→3.x boundary.

**Decision drivers** (top 3)
1. Zero labels exist; the user labels ~300 leaves personally; real student scripts arrive in ~4 weeks (D2, D3).
2. $14 dev spend ceiling (D4, raised 2026-09-17) vs. 3.8-flash marking at ≈$1.25 per 300-leaf sweep.
3. Gemini 3.x removes temperature/top_p/logprobs and changes thinking/schema keywords (B7, re-verified 17 Sep).

**Viable options considered at plan level**
- **Option A (chosen): migration-first, label-parallel, calibrator-gated.** Pros: single baseline; label-
  independent code lands while labelling runs; conformal gate has a guarantee. Cons: A/A floor and golden cache
  reset once; calibrator quality bounded by ~300 labels (minority class n≈45–60).
- **Option B: label-first on 2.5, migrate last.** Pros: keeps `temperature`/`seed` determinism during labelling.
  Cons: two baselines; every marker/vision result must be re-measured after migration; user rejected (D15).
- **Option C: threshold-retune only, no calibrator.** Pros: near-zero effort. Cons: class-imbalance failure
  documented (marginal thresholding collapses minority coverage); no FNR guarantee; rejected.

## 2. Items

Effort: S (<1 day) M (1–3 days) L (1–2 weeks) XL (>2 weeks). Gemini cost = dev-cycle estimate at chosen
models (3.5-flash-lite $0.30/$2.50, 3.8-flash $0.75/$3.75, 2.5-flash $0.30/$2.50 per 1M in/out); prod delta
per 16-page theory paper. All file/function pointers verified against `5564fd14` (Appendix A).

### 2.1 Fixes

#### F1 — Gemini 3.x migration behind config, one re-baseline, cost guardrails
- **Problem**: baseline is `gemini-2.5-flash` (`config.py:94`); `_params_fingerprint` folds temperature/top_p/
  seed/thinking_budget into `_cache_key` (`gemini.py:231-253`, `:275`); `_strip_schema` passes `pattern`
  (`gemini.py:122-145`) on `subject_code` (`loose_schemas.py:501`); `thinking_budget` int via
  `types.ThinkingConfig` (`gemini.py:529`); pricing table 2.5-only (`gemini.py:40-44`); 3.x removes
  temperature/top_p/top_k/candidate_count, uses `thinking_level`, `response_format`, rejects `pattern`
  (brief #15/B7; live docs re-verified 17 Sep). Source: roadmap #15, #9 (cache half), D14, D15, D4.
- **Approach**: (a) `GeminiSettings`: defaults `correction_model="gemini-3.8-flash"`,
  `escalation_model="gemini-3.8-flash"`, `extraction_model`/`generation_model`/`scan_metadata_model`=
  `"gemini-3.5-flash-lite"`, `mark_scheme_model="gemini-2.5-flash"` (`integrity_model` removed by F4); add
  `thinking_level_for: dict[str,str]` with defaults `{"correction": "low", "correction_borderline": "high",
  "escalation": "high", "extraction": "minimal"‡, "generation": "low"}`; keep `thinking_budget_for` for 2.5
  tags; `total_usd_ceiling=14.0`, ledger reset documented as a human step. **Escalation must stay reachable**:
  `AICorrector.mark_question` (`correction_ai.py:104-126`) only escalates when
  `escalation_model != model_for("correction")` (`:106`) and only retries with thinking when
  `thinking_budget_for["correction_borderline"] > 0` (`:84-85`) — both inert under same-model defaults. Four
  edits (Architect iteration 2): (1) `config.py:153-164` `model_for` gains keys `correction_borderline` →
  `correction_model` and `escalation` → `escalation_model` (today the borderline retry falls through to the
  global `model`, i.e. 2.5-flash, `gemini.py:342-347`); (2) `gemini.py:215-229` and `:527-536` gain a 3.x
  branch building `ThinkingConfig(thinking_level=...)` instead of `thinking_budget`; (3) `correction_ai.py:84-85`
  gate becomes "borderline level ranks above the correction level" on the ordered scale
  minimal<low<medium<high (2.5 keeps the `> 0` budget gate); (4) `correction_ai.py:104-108` guard compares the
  `(model, thinking)` tuple and the Step-2 call at `:124` is tagged `task_tag="escalation"` so
  `thinking_level_for["escalation"]="high"` is actually read. (b) `gemini.py`:
  model-line detector (`_is_3x(model)`); `_resolved_gen_params` omits temperature/top_p/seed on 3.x and
  emits `thinking_level`; `_params_fingerprint` (`gemini.py:231-253`, already folds temperature/top_p/seed/
  thinking_budget/max_output_tokens **and `schema_hash`**) adds `api_line` + `thinking_level` +
  `media_resolution`; `_strip_schema` drops `pattern` for 3.x and app-side validation of `subject_code`
  (`^\d{4}$`) moves to a Pydantic validator; structured-output call uses the SDK's 3.x field name
  ([uncertain]: `response_json_schema` vs `response_format` in google-genai ≥2.1 — confirm at implementation).
  (c) pricing rows for 3.x models incl. promo→2027 note. (d) Re-measure A/A churn floor on the dev split with
  `--cache-mode bypass`, 5 repeats (`lemely/eval` already publishes it). ‡ `minimal` only on
  3.6-flash/3.5-flash-lite (B7) — fall back to "low".
- **Rejected**: stay on 2.5 (D14); Vertex for logprobs (logprobs absent on 3.x, auth model change);
  Interactions API now (implicit-cache-only, no benefit); 3.8-flash for extraction (2.5× cost, vision gain
  unmeasured — becomes an I3 variant instead).
- **Touches**: `lemely/runtime/config.py` (`GeminiSettings`, `model_for`, `thinking_budget_for`),
  `lemely/io/gemini.py` (`_resolved_gen_params`, `_params_fingerprint`, `_cache_key`, `_strip_schema`,
  `_call_once`, `_DEFAULT_PRICING`), `lemely/core/loose_schemas.py:501` + `schemas.py:51,230`,
  `lemely/core/question_papers.py:107`, `tests/test_gemini*.py`, `tests/test_config*.py`,
  `lemely.toml.example`.
- **Impact** High (unblocks everything) · **Effort** M · **Gemini cost** ≈ $0.6 (A/A floor 5×31 leaves) ·
  prod delta ≈ +$0.08/paper (marking on 3.8-flash).
- **Dependencies**: none. Blocks all measurement items.
- **Acceptance**: (1) `model_for()` resolves every tag to the defaults above with `lemely doctor` printing the
  table. (2) A recorded 3.x request contains no `temperature`/`top_p`/`seed`/`candidate_count` and contains
  `thinking_level`; a 2.5 request still carries `thinking_budget` (unit test with request capture).
  (3) No schema sent to a 3.x model contains `pattern`; `MarkSchemeMetadata(subject_code="12a")` still
  raises. (4) On a 3.x model, changing `temperature_for["correction"]` leaves `_cache_key` unchanged while
  changing `thinking_level_for["correction"]` changes it; on 2.5 the reverse holds (test). (4b) With F1
  defaults, a borderline mark (confidence < 0.80 after the first call) on a recorded fixture triggers the
  thinking retry on `correction_model` with `thinking_level=high` and then the Step-2 call tagged
  `escalation` (request recorder shows three calls: low / high / high-escalation, all on 3.8-flash; none on
  the global 2.5 model).
  (5) Golden corpus re-run once on 3.x; `BUILD/review-rate-baseline.json` + A/A floor republished
  with n and run id; no metric compared to pre-migration numbers anywhere in docs (grep gate in a NEW test
  `tests/test_docs_consistency.py` — no such file exists today). (6) Ledger reads $0 at start, ceiling 14.0
  enforced (existing
  `ExternalServiceError` path test).
- **Fixture test**: `tests/golden/0625_s20_qp_31_theory_correct` marks end-to-end on 3.x with cache bypass;
  `mark_accuracy` and `id_match_rate` recorded as the new baseline.
- **Skills**: `engineering-advanced-skills:migration-architect`, `caching-strategies`,
  `superpowers:test-driven-development`, `accuracy-measure` (A/A floor), `superpowers:verification-before-completion`.

#### F3 — (removed) MCQ confidence leakage and abstention
- **Withdrawn by the Critic pass, verified against source 2026-09-17**: #36 (commit `5cc58cb8`) already
  applies caps as the last step and removed the single-letter bonus (`answer_extraction.py:95-134`),
  `_build_mcq_corrected` propagates `extraction_confidence` (`correction_ai.py:190-200`), a missing key
  returns `0.0/LOW/needs_teacher_review=True` (`correction_ai.py:137-159`), and `_build_calibration` includes
  MCQ (`harness.py:567-580`). SD13/SD14/SD15/SD19 are closed. Residual: MCQ rows and the deterministic
  `CorrectedQuestion.review_reason` strings ("missing answer", "invalid MCQ answer") become features in I4;
  no code item. Roadmap #4's OMR half stays rejected (D18).

#### F4 — Remove the AI-generated-answer detector; JCQ/Ofqual-aligned review copy
- **Problem**: `AIContentDetector` (`integrity.py:23-60`) is a zero-shot prompt (`prompts/integrity.py:7-16`)
  with no FPR; every published detector needs 100–300 words, L2 writers hit ~61% FPR, JCQ says detectors
  cannot be sole evidence (B5 [integrity 1,5,6,11]); already `ai_detection_enabled=False` (`config.py:458`).
  Source: roadmap #8 (first half), #17, D9.
- **Approach**: delete detector, prompt, `IntegritySettings.ai_detection_enabled`/threshold, `integrity_model`
  tag, web reason filter option; **one review-queue migration for the whole cycle**: remove
  `ai_detection_flag` (existing rows → `manual` + audit-log entry), add `random_audit` (N2), and add the
  column `review_queue.is_audit BOOLEAN NOT NULL DEFAULT false` on `ReviewQueueItem`
  (`lemely/db/models/ops.py:26-59`, consumed by N2) in the same revision so parallel streams never collide
  on an Alembic head; rename plagiarism UI label
  to "matches mark-scheme wording"; add review-UI copy: flags are advisory, Lemely marks in parallel with the
  teacher, never sole marker (Ofqual 14 Jan 2026 principles; Ofqual 16 Jul 2026 approach; Cambridge
  digital-mocks human verification).
- **Rejected**: keep opt-in with warning (carries a signal with no evidence base); script-level anomaly
  variant (no evidence, deferred); Binoculars/SynthID (token floors, no API); three separate enum migrations.
- **Touches**: `lemely/io/integrity.py`, `lemely/io/prompts/integrity.py`, `lemely/runtime/config.py:456-460`,
  `lemely/db/models/enums.py:175-181`, `lemely/db/models/ops.py:26-59` (`is_audit`), one new migration under
  `lemely/db/migrations/versions/`, `web/src/portals/teacher/screens/ReviewItem.tsx` (+ queue filter),
  `tests/test_integrity.py:239-255`, `tests/test_config_new_tasks.py`, `DELIVERY.md`/docs.
- **Impact** Medium (liability) · **Effort** S · **Cost** $0 · prod delta −(one call/question when it was on).
- **Dependencies**: none (parallel stream C). **Lands before N2** (it consumes the enum member and column).
- **Acceptance**: (1) `grep -r ai_detection lemely web/src` returns nothing except the migration. (2a) Schema
  round-trip: upgrade then downgrade on an empty DB leaves the schema identical (enum members and column
  restored). (2b) One-way data assertion: on a DB seeded with an `ai_detection_flag` row, upgrade rewrites
  it to `manual` and writes one audit-log entry; downgrade does NOT restore `ai_detection_flag` on that row
  (documented lossy step). (2c) After upgrade `random_audit` exists and `is_audit` defaults to false on all
  existing rows. (3) `tests/test_integrity.py` retains
  plagiarism tests; `test_disable_plagiarism` (`tests/test_config_new_tasks.py:66`) still passes.
  (4) Review UI shows the advisory copy (vitest snapshot). (5) `lemely doctor` warns if `lemely.toml` still
  sets the removed keys.
- **Skills**: `database-design-patterns`, `impeccable` (copy in review UI), `vitest-testing-patterns`,
  `technical-writer`.

### 2.2 Improvements

#### I1 — Per-page image extraction with bounding boxes and crop-and-re-read
- **Problem**: extraction uploads the whole PDF in one call (`answer_extraction.py:148`, `gemini.py:497-538`),
  no rasterisation/DPI/`media_resolution`; `source_region` is prose (`schemas.py:208`, prompt example
  `prompts/answer_extraction.py:34`); crop-and-re-read has nothing to crop (B8 #3). Bounding boxes are
  documented for image inputs only (`ai.google.dev/gemini-api/docs/image-understanding`, 2026-09-02); medium
  = 560 tokens/page is Google's PDF recommendation, high = 1120 (re-verified). Source: roadmap #3, D16.
- **Approach**: rasterise with pypdfium2 (already a dependency; `scripts/rasterise_handwritten_fixtures.py`
  pattern) at 200 DPI → PNG pages; ONE extraction call carrying all page images (keeps cross-page question
  context) with per-part `media_resolution: medium`; schema adds `source_box: {page:int, box:[ymin,xmin,ymax,xmax]}`
  (0–1000) beside the retained prose `source_region`; re-read step: for answers with low agreement (I3) or
  confidence < τ, crop `source_box` + 8% padding from the page PNG, upscale ×2, resend at `high` with a
  single-answer prompt; result stored as `answer_reread` + `reread_agreement`. Cache: `files_hash` over page
  PNG bytes; `extra_cache_key` for re-reads. Scan hygiene gate (T2.6): page count vs QP, blank/blur
  (Laplacian variance, DPI-relative threshold) → `scan_quality` warning surfaced, never silent.
  **Deviation (I1 review round 4, SHOULD-FIX H):** shipped as a flat (not DPI-relative) threshold
  on ink-masked variance — `(dpi/96)**2` scaling was derived for whole-page variance and scales in
  the wrong direction for the masked metric over most of the measured range (masked variance
  *decreases* as DPI increases from 96 to ~400, reversing above that). Measured FP=0/16, FN=0/16 at
  every DPI from 96–600 on `handwritten-59` with a single flat threshold, so the flat design is
  kept; see `lemely/io/scan_hygiene.py` module docstring for the numbers.
- **Rejected**: one call per page (brief's unsourced "degrades past ~3 pages"; loses numbering context,
  multiplies output tokens); whole-PDF + bbox (undocumented for PDF); 300 DPI (tertiary source; 200 DPI
  keeps images under the 2,240-token ultra tier); PyMuPDF rasteriser (AGPL; pypdfium2 already present).
- **Touches**: `lemely/io/answer_extraction.py::GeminiAnswerExtractor.__call__` (+ new `lemely/io/rasterise.py`,
  `lemely/io/reread.py`), `lemely/io/prompts/answer_extraction.py` (VERSION bump), `lemely/core/schemas.py`
  (`ExtractedAnswer`), `lemely/io/gemini.py::_call_once` (image parts + `media_resolution`),
  `lemely/accuracy/synth.py` (fixtures already rasterised at 150 DPI — keep), `tests/test_answer_extraction.py`.
- **Impact** High · **Effort** L · **Cost** ≈ $0.3 (Phase-A gold set on flash-lite: 54 handwritten-59 pages +
  the 4 solved scripts, ≈ 200 answers, ~600 tokens/page) · prod delta ≈ +$0.01/paper (16 × 560 in-tokens at
  $0.30/M) + re-reads.
- **Dependencies**: F1 (code); N1 Phase A pass-1 transcripts for the box hit-rate criterion (2) below.
  Feeds I2 (transcripts), I3 (second read), I4 (features).
- **Acceptance — label-free (M1 gate)**: (1) On `tests/fixtures/handwritten-59/0625_w24_qp_42.pdf` (16 pages,
  0 text chars) every extracted answer carries a `source_box` whose page index exists and whose box area > 0.
  (3) Scan-hygiene gate flags a deliberately blurred fixture page (Gaussian blur σ=3) and passes the clean
  one. (4) `id_match_rate` on the golden corpus non-inferior to the M0 baseline: lower bound of the 95% CI on
  the paired difference (discordant pairs, n reported) ≥ −2 pp. (5) Request recorder shows
  `media_resolution` set per part.
- **Acceptance — label-dependent (M2 gate)**: (2) Box hit-rate on handwritten-59 = share of boxes whose crop
  contains the gold-transcribed answer (I2). ≥ 90%: pass. 70–90%: pass with the number disclosed in the
  report, re-read stays agreement-triggered (I3), and the box is not used as an I4 feature. < 70%:
  per-page re-read becomes the default path and `source_box` is demoted to advisory.
  (6) One-time A/B on a 3-page subset of handwritten-59: single multi-image call vs one call per page — box
  agreement with the gold transcription reported for both; the single-call default is kept only if
  non-inferior at the same −2 pp margin (cost ≤ $0.1, inside the I1 budget). (7) Re-read triggers on ≥ 1
  low-agreement case and the re-read agreement is logged.
- **Fixture test**: golden `0625_s20_qp_31_theory_*` (synthetic handwriting) + handwritten-59 all three papers.
- **Skills**: `computer-vision-pipeline` (hygiene gate), `engineering-skills:senior-computer-vision`,
  `superpowers:test-driven-development`, `accuracy-issue-execute`, `caching-strategies`.

#### I2 — Gold transcription set and transcription error metric
- **Problem**: `AccuracyMetrics` has no transcription metric (`harness.py:274-279`); `GoldenAnswer.student_answer`
  is never diffed against `ExtractedAnswer.answer` (`harness.py:341-367`); no CER primitive anywhere; the 2×2
  ablation (`ablation_2x2`) never ran with a real oracle arm. Source: roadmap #1, D2, D3.
- **Approach**: labels pass 1 (`lemely/labelling/records.py` `transcription.jsonl`) becomes the gold
  transcript; harness computes per-answer CER (jiwer 4.0, Apache-2) after normalisation (whitespace, unicode
  NFKC, `×`/`x`, superscript unfold) and `expression_exact` (SymPy-normalised equality where parseable, I8
  module); new `AccuracyMetrics.transcription_cer`, `.transcription_exact_rate`, per question type and per
  page-position; 2×2 ablation run with oracle transcription arm; frozen split membership extended to the new
  real papers via the existing split mechanism + test-touch ledger (H4/H9 human steps).
- **Rejected**: Mathpix as pseudo-gold ($, not gold, no CAIE layout); synthetic TTF as gold (structurally
  easier: printed ids, no drift — strategy §1a).
- **Touches**: `lemely/accuracy/harness.py` (`AccuracyMetrics`, `_compute_metrics`, `_metrics_from_eval_records`),
  `lemely/eval/analyses.py` (`cer()`, `ablation_2x2` wiring), `lemely/labelling/paths.py:58`,
  `lemely/labelling/records.py`, `pyproject.toml` (+jiwer, +sympy), `tests/test_accuracy_harness.py`,
  `tests/eval/test_analyses.py`.
- **Impact** High · **Effort** M · **Cost** $0 (uses I1 runs) · prod delta 0.
- **Dependencies**: N1 pass-1 labels (first 54 pages); I1 for the extraction arm; I8 for expression equality.
- **Acceptance**: (1) `cer(ref="3.0 × 10^8", hyp="3.0 x 108")` = 0.125 (normalisation maps `x`→`×` and
  collapses spaces; one deletion of `^` over 8 reference characters); table-driven unit tests for the
  normalisation rules. (2a) Phase A (teacher-solved, no student errors): harness report shows
  `transcription_cer` with n per question type; the 2×2 is reported with its population named and b, c may
  be 0. (2b) Phase B (real scripts): 2×2 has b, c, n_pairs > 0 (the retired programme's unmet box) — this is
  the **M3** gate (Phase B labels land during M2; the oracle+mark arm runs in the M3 sweep). (3) Extraction
  share of error reported as a lower bound with Wilson interval, Phase A and Phase B never pooled.
- **Fixture test**: handwritten-59 (teacher-solved) labelled first; synthetic golden gives CER ≈ 0 sanity check.
- **Skills**: `accuracy-label-batch`, `accuracy-measure`, `engineering-skills:senior-data-scientist`,
  `superpowers:test-driven-development`.

#### I3 — Second-read agreement seam (variant chosen by measurement)
- **Problem**: single extraction pass; confidence = self-report + heuristics (`_calibrate_confidence`);
  self-reported confidence AUROC ≈ chance under degradation (B2 [ocr 9]); cross-model agreement beats
  same-model self-consistency (Consensus Entropy v4, May 2026); large k adds nothing on strong Gemini
  (arXiv 2604.26954); logprobs unavailable on 3.x. Source: roadmap #2, D17.
- **Approach**: `SecondReader` protocol in `lemely/io/second_read.py`; agreement = 1 − normalised
  Levenshtein (rapidfuzz) per answer after the I2 normaliser → `ExtractedAnswer.extraction_agreement`;
  two implementations behind `GeminiSettings.second_reader`: `cross_model` (primary 3.5-flash-lite, second
  3.8-flash, same prompt) and `structural` (same model, document-guided vs field-guided prompt, T1.9,
  `extra_cache_key`); `none` default until measured. Selection rule: AUROC of agreement for predicting
  CER > 0.1 on the **Phase A transcription set only** (handwritten-59 + solved scripts, target = transcription
  error); adopt the variant with higher AUROC if ≥ 0.70, else keep `none`. The calibrator (I4) is fit on
  **Phase B mark labels** (target = wrong mark), so variant selection never touches the calibration rows;
  I4 additionally reports 5-fold CV. Re-read (I1) fires on agreement < 0.8.
- **Rejected**: k=5 sampling with entropy (no temperature on 3.x; no gain evidence); logprobs; Mathpix
  second opinion (cost, deferred).
- **Touches**: new `lemely/io/second_read.py`, `lemely/io/answer_extraction.py`, `lemely/runtime/config.py`,
  `lemely/core/schemas.py`, `lemely/io/prompts/answer_extraction.py` (field-guided variant), `tests/`.
- **Impact** High (if AUROC clears) · **Effort** M · **Cost** ≈ $0.5 (both variants over the Phase-A gold
  set, ≈ 200 answers / 54+ pages, once; ≈ $0.25 if only the first variant runs) · prod delta ≈ +$0.01
  (structural) or +$0.05 (cross-model) per paper.
- **Dependencies**: I1, I2. Feeds I4.
- **Acceptance**: (1) Both variants produce `extraction_agreement ∈ [0,1]` on all gold answers. (2) AUROC per
  variant published in the harness report with n. (3) Config default remains `none` unless the selection rule
  passes, recorded in `BUILD/DECISIONS.md`. (4) Cache test: second read never returns the primary's cached
  reply (SD21 — `extra_cache_key` differs).
- **Skills**: `engineering-skills:senior-ml-engineer`, `accuracy-measure`, `superpowers:test-driven-development`.

#### I4 — Learned calibrator + Mondrian conformal review gate (α = 0.10) + risk-coverage reporting
- **Problem**: `REVIEW_CONFIDENCE_THRESHOLD = 0.90` (`schemas.py:47`, consumed at `correction_ai.py:14,211,504`,
  `attempt_repo.py:60,313`, `teacher.py:61,175`, `teacher_paper_repo.py:58,149`, **`quiz_marking_repo.py:9`**
  (second marking flow), **`core/at_risk.py:50`**, mirrored `web/src/lib/markingConfidence.ts:35` with parity
  guard `tests/test_web_shared_constants.py`); `risk_coverage()` exists (`eval/analyses.py:780`) but harness
  imports only `exclusion_funnel` (`harness.py:19`); flag recall 14.29% (n=71); marginal thresholding fails
  under class imbalance ([calib 11]); EMNLP 2025 precedent for conformal review routing in scoring
  (arXiv 2509.15926). Source: roadmap #7, D6.
- **Approach**: `lemely/core/review_policy.py`: features per question = model confidence, calibrated heuristic
  confidence, `extraction_agreement` (I3), `reread_agreement`, coherence-gate result (#40), verdict coverage
  (I6: points awarded without span), `_verify_calculated_answers` outcome, equivalence result (I8), question
  type, marks available, #answer points, answer length, escalation delta (primary vs escalated mark, present
  only when the 0.80 path fired — reachable after F1's guard fix), scan quality, deterministic structural
  reason (`CorrectedQuestion.review_reason` non-empty: missing/invalid MCQ answer, unmatched id), MCQ rows
  included (already in calibration since #36). Calibrator: L2-logistic
  regression on labels (P(mark wrong)); conformal: crepes 0.9.1 `WrapClassifier`/`ConformalClassifier` with
  `class_cond=True` over classes {wrong, right}; α = 0.10 on the FNR (share of wrong marks not flagged);
  output `needs_review` + `review_score`. **Frozen-surface rule**: the policy is fit on the M3 validation
  sweep (after I6/I7/I8 land), so every feature comes from the final marker surface; the artifact records
  prompt `VERSION`, model ids, feature schema and split hash and refuses to load on mismatch (falls back to
  threshold + warning), so any later prompt/model change forces a refit on that change's own validation sweep
  (no extra spend). **Minority-class floor rule (OQ6 answered 2026-09-17)**: if the labelled set has < 50
  wrong marks, ship marginal conformal with the floor disclosed AND keep the 0.90 threshold as an OR-gate
  (union), so the flag set is a superset of today's and recall cannot regress. The marginal guarantee is
  reported as pooled, never as class-conditional, and the report states n₁ with the Beta SD
  √(α(1−α)/(n₁+2)) of the realised FNR. **Automatic upgrade**: the policy artifact carries `n1` and
  `mode ∈ {marginal_or_gate, mondrian}`; once cumulative wrong-mark labels (N1 + N2 audit imports) reach
  **n₁ ≥ 100**, the next refit switches to class-conditional Mondrian and drops the OR-gate, published as a
  new artifact version with the review-rate delta. No re-design, no extra sweep — the refit rides the next
  validation run. Cold start: no artifact → 0.90 threshold (unchanged behaviour).
  Artifact `BUILD/review-policy/<run>.json`. One policy for both marking flows (`attempt_repo` papers and
  `quiz_marking_repo` quizzes) and for `core/at_risk.py`. Harness: wire `risk_coverage()`, AURC, per-trigger
  breakdown, MCQ included; publish review rate as an output; ratchet stays observational. Web mirror:
  `markingConfidence.ts` reads the server-provided `needs_review` instead of recomputing from 0.9 (constant
  kept for display only; parity test updated to assert the API contract instead).
- **Rejected**: threshold retune (no guarantee); Mondrian by question type (n per class < 50 at 300 labels —
  arXiv 2607.27143 §6.3) → conditioning on {wrong,right} only, question type as a feature; k-sample entropy
  gate (VUB paper: no stable threshold); logprob features (unavailable); fitting before the marker batch
  (features would move under the guarantee).
- **Touches**: new `lemely/core/review_policy.py`, `lemely/io/correction_ai.py` (gate call sites),
  `lemely/db/attempt_repo.py`, `lemely/db/teacher_paper_repo.py`, `lemely/db/quiz_marking_repo.py:9`,
  `lemely/core/at_risk.py:50`, `lemely/web/routers/teacher.py`, `lemely/accuracy/harness.py`,
  `lemely/eval/analyses.py` (AURC), `web/src/lib/markingConfidence.ts`, `tests/test_web_shared_constants.py`,
  `pyproject.toml` (+crepes, +scikit-learn), `tests/`.
- **Impact** High · **Effort** L · **Cost** $0 beyond sweeps already budgeted (fit uses eval records) ·
  prod delta 0.
- **Dependencies**: N1 Phase B (≥150 labels for first fit, 300 for release), I3, I6/I7/I8 landed (frozen
  surface); policy must tolerate missing features.
- **Acceptance**: (1) With no artifact, behaviour is byte-identical to today (golden queue diff empty).
  (2) On the frozen dev split with a fitted policy: empirical FNR ≤ 0.10 + 2B/(n+1) slack reported; review rate
  reported with Wilson interval; AURC reported; 5-fold CV NLL/Brier reported. (3) Flag recall on the labelled
  set reported with Wilson interval at the published review rate — new-line baseline, **no comparison to any
  pre-migration figure** (P5). (4) Unit tests: policy with missing features degrades to available ones;
  artifact metadata mismatch → fallback + warning. (5) Web: `needs_review` from API, no client recompute
  (vitest); `test_web_shared_constants.py` asserts the API contract. (6) Quiz marking and at-risk use the same
  policy object (test). (7) Artifact records `n1` and `mode`; a fitted policy with n₁ < 50 loads in
  `marginal_or_gate` mode and its flag set on the dev split is a strict superset of the 0.90-threshold flag
  set (test); a synthetic calibration set with n₁ ≥ 100 fits in `mondrian` mode with no OR-gate (test).
- **Fixture test**: synthetic golden + handwritten-59 rows form the calibration set for CI smoke (n small,
  guarantee not claimed there).
- **Skills**: `engineering-skills:senior-ml-engineer`, `engineering-skills:senior-data-scientist`,
  `engineering-advanced-skills:slo-architect`, `accuracy-measure`, `accuracy-review`,
  `engineering-advanced-skills:feature-flags-architect` (artifact-gated rollout).

#### I5 — Offline drift canary (seeded known-mark items, no production injection)
- **Problem**: no continuous check that prompt/model changes keep accuracy; AQA seeds live marking with
  known-mark items (B4 [calib 16]); user wants offline only (D8). Source: roadmap #13 (seed half).
- **Approach**: `lemely canary compare <baseline-run> <candidate-run>` compares two existing run manifests /
  eval-record sets (`mark_accuracy`, `transcription_cer`, review rate) with McNemar + Wilson, writes
  `BUILD/canary/<date>.json`, exits non-zero on drift beyond tolerance (default: McNemar p<0.05 worse, or CER
  +0.03); `lemely canary run` executes the dev split with `--cache-mode bypass` first, then compares. Every
  funded validation sweep (M0 baseline, M3 batch) doubles as a canary run — no separate spend this cycle.
  Trigger: manual + on prompt `VERSION` change (CI job with manual approval), NOT nightly.
- **Rejected**: production seeding (D8); nightly schedule (budget); a standalone funded canary run.
- **Touches**: new `lemely/app/cli.py` `canary` group (or `scripts/canary.py`), `.github/workflows/*` (manual
  dispatch), `lemely/eval/` (reuse), `BUILD/canary/`.
- **Impact** Medium · **Effort** S · **Cost** $0 this cycle (reuses funded sweeps) · prod 0.
- **Dependencies**: N1, F1; M0 and M3 sweep records.
- **Acceptance**: (1) `canary compare` of the M0 baseline against itself reports "no drift" (offline, $0).
  (2) `canary compare` M0 vs M3 produces the drift report used as the M3 gate. (3) A fixture pair with an
  injected 5-row regression makes it exit non-zero with the failing metric named (offline).
- **Skills**: `github-actions-pipeline-builder`, `engineering-advanced-skills:observability-designer`, `accuracy-measure`.

#### I6 — Per-point verdicts with quoted spans, marks summed in Python (batched with I7, I8)
- **Problem**: `AIMarkResponse` = awarded_marks/confidence/matched_point_ids/feedback (`schemas.py:222-226`);
  chain-of-thought instruction not captured (`prompts/correction_ai.py:60-62`); a mark with no evidence cannot
  be flagged; human markers verify method, LLMs match rubric text (B1 [marking 2,3,14,15]). Source: roadmap
  #11, D11, D19.
- **Approach**: `AIMarkResponse` v2: `point_verdicts: list[PointVerdict{point_id, verdict: awarded|withheld|
  unverifiable, evidence_span: str, evidence_box: optional, note}]`, `feedback`, `confidence`; `awarded_marks`
  computed in `correction_ai.py` from verdicts (cap at `q.marks`); prompt ordering evidence → verdict → total
  (T2.8), `thinking_level` low; coherence gate (#40, `_check_coherence` `correction_ai.py:384`) extended:
  awarded ⇒ non-empty
  span that fuzzy-matches the transcription (rapidfuzz partial ratio ≥ 0.8) else `no_span` review trigger
  (queued under `low_confidence` with the structural reason string; no new enum member); M-point awarded
  requires span inside `working_out` when present (working-vs-answer, D11); feedback note
  auto-added when a correct answer has no method span. One prompt `VERSION` bump shared with I7/I8 (D19).
  **Mandatory attribution aids**: harness reports point-level F1 split by point type (M/A/B) and the signed
  over/under-award split; `equivalence_gate` and `ecf_substitution` are config flags from day one so an
  ablation costs one sweep, not a rebuild. Note `schema_hash` in `_params_fingerprint` means the schema change
  alone invalidates the marking cache — expected, once.
- **Rejected**: keep holistic mark + ask for rationale (rationalisation bias); separate VERSION bumps (user
  chose batched, D19); RefGrader rubric expansion per question (cost per question, deferred to I9 evidence).
- **Touches**: `lemely/core/schemas.py` (`AIMarkResponse`, `PointVerdict`), `lemely/io/correction_ai.py`
  (`mark_question` call sites `:74,92,115`, `_check_coherence` `:384`, review reasons `:475`),
  `lemely/io/prompts/correction_ai.py` (VERSION 5→6), `lemely/accuracy/harness.py` (point-level F1, signed
  bias), `lemely/accuracy/metamorphic.py`, `web/src/portals/teacher/screens/ReviewItem.tsx` (render verdicts +
  spans), `tests/test_correction_ai.py::CoherenceGateTests`.
- **Impact** High · **Effort** L · **Cost** ≈ $1.25 (one full labelled sweep after the batch) · prod delta ≈
  +$0.02/paper (longer outputs).
- **Dependencies**: F1, I10 (schemes carry types/points), I8 (equivalence for A points). Measurement needs N1.
- **Acceptance**: (1) Schema round-trip: sum(awarded verdicts' point marks) == `awarded_marks` on every golden
  row (metamorphic test: shuffling point order leaves marks unchanged). (2) On the synthetic golden partial
  fixtures (`*_theory_partial`) every awarded point has a span found in the fixture's answer text. (3) Point-
  level F1 (by M/A/B) and signed over/under-award reported on the labelled set; `mark_accuracy` non-inferior
  to the M0 baseline at a pre-specified −2 pp margin (lower bound of the 95% CI on the paired difference over
  discordant pairs, n reported) — improvement reported, not gated. (4) Review UI renders spans (vitest).
- **Fixture test**: `0580_s23_qp_22_theory_partial`, `0606_s23_qp_12_theory_partial`, handwritten-59 papers.
- **Skills**: `engineering-skills:senior-prompt-engineer`, `prompt-engineer`, `superpowers:test-driven-development`,
  `accuracy-issue-execute`, `accuracy-review`, `impeccable` (verdict rendering).

#### I7 — Error-carried-forward by substitution, try-without-replacement first
- **Problem**: ecf/ft is prose-only in the system prompt; `required_with` (`loose_schemas.py:231-235`)
  populated by the parsing prompt but never read in marking (only `accuracy/metamorphic.py:228-234`); prior
  results pass mark counts not values (SD9); scoping to immediate parent drops 34% of chains (SD8); Numbas
  "try without replacements first" matches CAIE ft semantics (B1 [marking 33,34]). Source: roadmap #6, D19.
- **Approach**: build the dependency chain per question from `required_with` + parent ids scoped to the
  top-level question; pass `PRIOR VALUES` = the student's extracted numeric/expression answers for each
  prerequisite part (from I1 transcription + I8 parse), not marks; marking runs once without substitution;
  if below max on a part whose scheme carries `ecf`/`ft`/`dep`, re-mark that part with the substituted prior
  value; `ecf_applied: bool` recorded on the verdict; harness reports ecf activation count (fixes SD8/SD9).
  Honest limit:
  schemes carry no machine-readable formula, so recomputation is by the model with the substituted value plus
  the I8 numeric check — not full Numbas recompute.
- **Rejected**: full deterministic recompute (needs per-part formulas the schemes lack); pass marks only
  (status quo, SD9).
- **Touches**: `lemely/io/correction_ai.py` (`correct_paper` sibling-prior block ~`:612-660`),
  `lemely/io/prompts/correction_ai.py` (ECF section), `lemely/core/loose_schemas.py` (chain helper),
  `lemely/core/schemas.py` (`PointVerdict.ecf_applied`), `tests/golden/` nested multi-part fixture (#32
  exists), `tests/test_correction_ai.py`.
- **Impact** Medium-High · **Effort** M · **Cost** in I6's sweep · prod delta ≈ +1 call per ecf re-mark.
- **Dependencies**: I6 (verdict schema), I8; nested fixture with `parent_id` (present since #32).
- **Acceptance**: (1) On the nested multi-part golden fixture, an injected wrong part-(a) value with correct
  method in (b) yields full marks in (b) with `ecf_applied=True`; correct (a) never triggers substitution.
  (2) Chain builder returns the `(a)(i)→(b)` transition for `0625_s20_ms_31` (SD8 case). (3) ecf activation
  count > 0 on the labelled set and reported.
- **Skills**: `engineering-skills:senior-prompt-engineer`, `superpowers:test-driven-development`, `accuracy-issue-execute`.

#### I8 — SymPy equivalence module: A-mark gate and shared solver
- **Problem**: `_verify_calculated_answers` (`correction_ai.py:304-360`) is a regex literal-presence backstop;
  no `sympy` anywhere; notation mismatches and near-misses are adjudicated by the LLM alone (B8 #5).
  Source: roadmap #5, D12 (shared with N3), D19.
- **Approach**: `lemely/core/equivalence.py`: `parse_expr_safe(text) -> sympy.Expr|None` (plain + light LaTeX
  via SymPy's Lark backend to avoid the antlr4 runtime pin), unit stripping table, sig-fig/dp tolerance from
  scheme; `equivalent(a, b) -> Verdict{equal|not_equal|unparseable, method: simplify|numeric}` with
  `simplify(a-b)==0` then random numeric substitution (5 points) fallback; used by (i) I6 A-point verdicts:
  awarded but `not_equal` → withhold + review trigger `equivalence_conflict`; withheld but `equal` → review
  trigger (no silent auto-award), (ii) I2 `expression_exact`, (iii) N3 solver, (iv) `_verify_calculated_answers`
  retained as fallback when unparseable.
- **Rejected**: Gemini code_execution as primary (non-deterministic, network, cache complexity); auto-award on
  equivalence (accuracy-first but unlabelled — becomes review candidate until labels show FPR).
- **Touches**: new `lemely/core/equivalence.py`, `lemely/io/correction_ai.py:278-360`, `pyproject.toml` (+sympy
  1.14), `tests/test_equivalence.py` (table-driven: 40 CAIE-style pairs incl. `1/2 mv^2` vs `0.5mv²`,
  `3.0×10^8` vs `300000000`, `g/cm3` vs `g cm^-3`).
- **Impact** High · **Effort** M · **Cost** $0 · prod delta 0 (local).
- **Dependencies**: none (pure Python). Blocks I6/I7/N3/I2-exact.
- **Acceptance**: (1) 40-pair table passes with ≥ 38 correct and zero false `equal`. (2) Parse of every
  `calculated_answer.value` in the Gemini-parsed golden schemes succeeds for ≥ 90% (reported). (3) Timeout:
  any `simplify` > 2 s falls to numeric within 0.5 s (test with a pathological expression).
- **Skills**: `engineering-skills:tech-stack-evaluator` (Lark vs antlr), `dependency-management`,
  `superpowers:test-driven-development`.

#### I9 — Rubric wording rewrite from the measured confusion matrix
- **Problem**: prompt is hand-authored, `VERSION="5"`; error-targeted rubric wording reached human-level
  agreement in physics and beat few-shot (B1 [marking 3,4]); nothing in repo derives wording from
  disagreements. Source: roadmap #10.
- **Approach**: after the I6 sweep on labels, harness emits a per-question-type confusion matrix (predicted
  vs true points) and the top-20 disagreement rows with spans; prompt edits target the conflated boundaries
  (M-vs-A, list-rule, unit-rule) as static rules in `MARKER_SYSTEM_PROMPT`; one VERSION bump (5→6→7), one
  sweep, paired McNemar; keep or revert. No automated prompt optimisation (DSPy/GEPA) this cycle.
- **Rejected**: fine-tuning (ASAG2024 underperformance, corpus too small); DSPy/GEPA (budget, overfit risk on
  a ~300-item set with a frozen test split).
- **Touches**: `lemely/accuracy/harness.py` (confusion report), `lemely/io/prompts/correction_ai.py`,
  `lemely/core/review_policy.py` (refit), `BUILD/review-policy/`, `BUILD/DECISIONS.md`.
- **Impact** Medium · **Effort** S–M · **Cost** ≈ $1.25 (one sweep) — **funded at the $14 ceiling (OQ1
  answered 2026-09-17); runs in M4** · prod delta 0.
- **Dependencies**: I6 sweep, N1. Its validation sweep also refits I4 (frozen-surface rule).
- **Acceptance**: (1) Confusion matrix artifact with n per cell (this part is funded — it reads the M3 sweep
  records). (2) Post-rewrite sweep shows `mark_accuracy` non-inferior at the −2 pp margin (95% CI lower
  bound on the paired difference) and the targeted cells'
  off-diagonal count reduced — reported. (3) Test-split touched at most once (ledger). (4) I4 policy refit on
  the same sweep and artifact metadata updated.
- **Skills**: `engineering-skills:senior-prompt-engineer`, `accuracy-measure`, `accuracy-review`.

#### I10 — Mark-scheme parsing: Gemini-primary, deterministic parser demoted to verifier, fidelity gates
- **Problem**: chain is det-first, Gemini on `ParseError` (`parsers.py::ChainedMarkSchemeParser`); det yields
  all-`RECALL`, zero `calculated_answer` (SD5, SD10, SD11); Gemini fallback fails 12/24 (50%) by size, Pydantic
  validation (#166, DA35), output checked by nothing (SD6); 40 failing 0625 are `mark_total_mismatch`
  (`BUILD/DECISIONS.md:198`). Source: roadmap #14 (reframed), D20.
- **Approach**: (a) order flip: Gemini (`mark_scheme` tag, gemini-2.5-flash, temperature 0.0, thinking_budget
  8000 kept; try 4096 only if budget allows) parses every scheme; (b) #166 fix: parse per question block
  (split by the det row/question detector where available, else by page) into `MarkSchemeQuestion` and
  assemble, so oversized schemes stop failing validation; log the Pydantic error class; (c) fidelity gates on
  every Gemini parse: leaf sum == `maximum_mark`, `sum(answer_points) == q.marks` per question, operator-
  newline detector (SD3), phantom-point detector (marks cell empty → `marks_defaulted`, #38), and where det
  parses the same PDF, totals cross-check (det as verifier, `ParseWarning` on mismatch → escalate); (d) QP
  tariff join (T2.9) when the question paper is in the corpus (`det/question_papers.py:69` `_MARKS_RE`,
  `:352-357` already extract `[n]` tariffs); (e) no new det features; bold/underline detection deferred.
  **Scope and ordering**: code lands in M1; Gemini re-parses are run only for schemes the labelled papers
  reference, output to `corpus/mark-schemes/<id>.json` (existing location, 289 det-parsed JSONs today,
  `corpus/manifest.json` `gemini_used: false`; the directory is git-tracked in the public repo — precedent
  set by ask B8 for the 289 existing JSONs, so parsed schemes may be committed but never scripts). Phase A =
  5 schemes: `0625_w24_ms_42` and `0625_m21_ms_62` (det JSONs exist in `corpus/`; re-parsed via Gemini for
  parser parity), `0625_s19_ms_43` (PDF in `Sources/Physics/MarkingSchemes/`, no corpus JSON — the SD1
  phantom-point case), and `0625_s25_ms_42` + `0625_w25_ms_42`, supplied by the user on 2026-09-17 at
  `/home/sico/Documents/` (OQ7 closed; verified 19 and 20 pages, IGCSE Physics 0625/42, "Maximum Mark: 80",
  text-bearing) — the first M1 step copies both into `Sources/Physics/MarkingSchemes/` (gitignored
  `.gitignore:51`), which makes all three handwritten-59 P42 papers markable. Phase B adds ~8. Spent as papers are labelled and always **before** the M0 labelled baseline sweep, so
  the baseline and the M3 sweep see the same parser. The 40-failing-0625 re-parse (~$9.6) is a separately
  funded item. Denominators reported separately: det-verifiable schemes (det also parses) vs det-unverifiable
  (internal-sum gates only). **Contingency if chunked parsing does not clear #166**: spend cap $3.5 on this
  item; a scheme that fails twice is excluded and its paper is not labelled (label only papers whose schemes
  parse), so the budget, not the parser, bounds the labelled set; golden schemes already have Gemini JSON.
- **Rejected**: delete det (loses the only exact-checksum verifier, SD6); keep chain (user decision); Docling/
  Marker/MinerU (drop typography semantics); PyMuPDF texttrace bold (AGPL already present but the measured
  failures are not font-weight); 3.x for parsing (schema `pattern` + thinking tuned on 2.5; user chose 2.5).
- **Touches**: `lemely/io/parsers.py` (`ChainedMarkSchemeParser`, `GeminiMarkSchemeParser`),
  `lemely/io/prompts/mark_scheme_parsing.py` (chunked variant), `lemely/io/det/reconcile.py::check` (verifier
  API), `lemely/io/det/question_papers.py:263-275`, `lemely/core/loose_schemas.py` (`MarkScheme` assembly),
  `lemely/io/mark_schemes.py::process_mark_scheme_batch`, `tests/test_parsers*.py`, `tests/test_parsers_det.py`.
- **Impact** High (marker sees one rich schema) · **Effort** L · **Cost** ≈ $1.20 Phase A (5 schemes) +
  ≈ $2 Phase B (~8 schemes) — full 40-scheme re-parse (~$9.6) is out of budget · prod delta: parsing cost
  moves to Gemini for all schemes (~$0.24/scheme, one-off, cached).
- **Dependencies**: F1 (config split keeps this tag on 2.5). Precedes I6 baseline measurement.
- **Acceptance**: (1) The 12 schemes that failed in DA35's sweep (list in `BUILD/DECISIONS.md` DA35) parse
  under chunked mode with fidelity gates passing or raising named warnings — count reported. (2) For every
  scheme det also parses, totals match or a `ParseWarning` is raised; `0625_s19_ms_43` phantom-point case
  (82 vs 80) is caught. (3) `0625_s20_ms_31` operator-newline count drops from 21 to 0 in the Gemini parse
  (SD3 detector). (4) Golden `MarkScheme` JSONs regenerated once; diff reviewed and committed with the run id.
- **Skills**: `engineering-skills:senior-prompt-engineer`, `superpowers:systematic-debugging` (#166),
  `accuracy-gate-triage`, `superpowers:test-driven-development`.

### 2.3 New features

#### N1 — Labelling campaign (human, ~300 leaves, two-pass, blind) with self-agreement sample
- **Problem**: `eval/labels/` holds `.gitkeep`; labeller built (`lemely/labelling/server.py`, `records.py`,
  `rulings.py`, hash-chained) and never used; 300 leaves ≈ 7–8 papers gives ±4.2pp Wilson and McNemar power
  for +3pp at n=219 (strategy §5). Source: roadmap #1/#7 prerequisite, D2, D3.
- **Approach**: Phase A (now): pass 1 transcription on all 54 handwritten-59 pages (3 × 0625 P42, teacher-
  solved; transcription needs no scheme) + `Sources/Physics/Solved/` (4 scripts); pass 2 per-point marks only
  where a scheme exists — now all three P42 papers: `0625_w24_ms_42` (det JSON in `corpus/mark-schemes/`)
  plus `0625_s25_ms_42` and `0625_w25_ms_42`, whose PDFs the user supplied on 2026-09-17 at
  `/home/sico/Documents/` (OQ7 closed; parsed by I10 Phase A); solved scripts m20_12,
  s20_31, m21_62 (JSON present) and s19_43 (PDF only, I10 parses it) — so Phase A marking set = 3 P42 papers
  + 4 solved scripts. `Sources/` is gitignored (`.gitignore:51`), so the
  solved-script half runs locally, not in CI.
  Blind: labeller never sees pipeline output (existing structural rule). Phase B (~week 4): real student
  scripts (consent recorded per H-ruling pattern), **never committed** — repo is PUBLIC — stored under
  `tests/fixtures/real-papers/` (gitignored) with labels under `eval/labels/` (gitignored); stratified across
  MCQ/calculation/explanation/diagram and across 0625/0580/0606, target 300 leaves total. Self-agreement:
  relabel a pre-committed 10% sample after ≥ 7 days (H7 fallback for a single labeller; report κ). Split:
  extend frozen split (H4) and record test-touch (H9). Code support: labeller CLI ergonomics only (S).
- **Rejected**: contractor (user chose self); ~100 leaves (no conformal floor); pseudo-labels from Gemini
  (circular).
- **Touches**: `eval/labels/**`, `lemely/labelling/*` (small CLI fixes), `BUILD/DECISIONS.md` rulings,
  `tests/golden/split*.json`.
- **Impact** Critical path · **Effort** XL (human time ≈ 20–30 h) · **Cost** $0 · prod 0.
- **Dependencies**: none to start; Phase B on script arrival.
- **Acceptance**: (1) ≥ 300 labelled leaves across both passes, hash chain verifies (`lemely/labelling/verify.py`).
  (2) Stratification table published (type × syllabus × parse path). (3) Self-agreement κ on the 10% sample
  reported. (4) Split membership frozen with ledger entry.
- **Skills**: `accuracy-label-batch`, `accuracy-scribe` (rulings), `checklist-discipline`.

#### N2 — Hidden random-audit stream (CLI-only)
- **Problem**: every queue row arrives because something flagged it (`review_repo.py:287-297`, `ReviewReason`
  4 members); recall becomes unmeasurable once flagging changes which items get labelled; T1.10 unshipped
  (`docs/ACCURACY-STRATEGIES.md:178`); Cambridge routes a random sample to humans regardless of confidence
  (B4 [calib 14]); user wants it hidden from teachers under an ops role (D5, D7). `Role` enum already has
  student/parent/teacher/**school_admin/platform_admin** (`enums.py`); authz is `require_role(*allowed)`
  (`lemely/web/deps.py:872-896`); `_STAFF_ROLES = (teacher, school_admin, platform_admin)`
  (`web/routers/teacher.py:195`). Source: roadmap #13, D5, D7.
- **Approach**: **no new role, no web queue change for admins.** Tenancy is deliberate: `list_queue` scopes
  through `_visible_class_map` (`review_repo.py:638-660`), the service docstring (`:260-268`) states there
  is no super-role bypass and `platform_admin` sees no classes; the console excludes it too (`:363-371`).
  The audit stream therefore lives **outside the web queue**: sampling in `correct_paper` (deterministic
  hash(attempt_id, question_id, salt) < `audit_sample_rate`, default 0.05, over questions NOT otherwise
  flagged) sets a carrier field `CorrectedQuestion.audit_sampled: bool` (`schemas.py:117-133`, beside
  `plagiarism_flagged`); a **fourth** `ReviewQueueItem(` branch is added beside the three existing ones in
  `AttemptRepository.persist_correction` (`attempt_repo.py:315,323,331`) and a fourth yield in
  `_review_items_for` (`teacher_paper_repo.py:123-166`), writing `ReviewReason.random_audit` +
  `is_audit=True` (both from F4's migration); the exclusion `is_audit = false` is added to the two
  `list_queue` select statements (attempt half ~`review_repo.py:340-355`, console half `:372-380`) and to
  `_find_any_item` (`:686-710`) so no web path can read or open an audit row; a repository method
  `list_audit_items()` with no class scoping is exposed ONLY to the CLI (`lemely audit export` → labeller
  pass-2 format under `outputs/audit/` — `outputs/` is gitignored at `.gitignore:52`; **never** under
  `BUILD/audit/`, which is git-tracked in a PUBLIC repo (`LemelyIG/Lemely`); `lemely audit import` → human
  mark, recall estimate with Wilson interval, I4 refit input), run server-side by the user (the
  `platform_admin` seat; the CLI, not a role check, is the boundary). No web route for admins this cycle.
  Teacher-facing marks unaffected (audit never blocks release). Built in M2; live sampling switched on in M4.
- **Rejected**: teacher-visible audit (D7); paper-level sampling (clumpy); a sixth `ops` role (inverts the
  existing lattice); a `platform_admin` web bypass of class scoping (reverses the documented tenancy
  decision at `review_repo.py:260-268`); admin web UI now (scope).
- **Touches**: `lemely/core/schemas.py:117-133` (`CorrectedQuestion.audit_sampled`), `lemely/io/correction_ai.py`
  (`correct_paper`), `lemely/db/attempt_repo.py:315-331` (fourth branch), `lemely/db/teacher_paper_repo.py:123-166`
  (fourth yield), `lemely/db/review_repo.py` (`list_queue` selects ~`:340-355` and `:372-380`,
  `_find_any_item` `:686-710`; new `list_audit_items`), `lemely/runtime/config.py` (`audit_sample_rate`,
  `audit_salt`), `lemely/app/cli.py` (`audit` group), `tests/test_review_repo.py:281-336`,
  `tests/test_attempt_repo*.py`, `tests/test_teacher_paper_repo*.py`. (Column and enum member come from F4.)
- **Impact** High (only trigger that catches confidently-wrong) · **Effort** M · **Cost** $0 · prod delta 0
  (no extra calls; human time ≈ 5% of eligible questions).
- **Dependencies**: F4 (migration). Feeds I4 retraining.
- **Acceptance**: (1) Over 1,000 seeded questions of which 800 are eligible (not otherwise flagged), with
  `audit_sample_rate=0.05` the sampled count lies within the Wilson 95% interval around 40 and is identical
  across two runs (determinism); no flagged question is ever sampled. (2) `list_queue` (both halves), the
  console listing and `_find_any_item` never return `is_audit` rows for teacher or school_admin callers;
  platform_admin web behaviour stays at zero rows (regression assertion, unchanged); `list_audit_items()`
  returns them and no module under `lemely/web/` imports it (import-graph test). (3) Export/import
  round-trip on a fixture attempt updates the recall estimate artifact `outputs/audit/recall-<date>.json`;
  a test asserts `git check-ignore outputs/audit/x.jsonl` succeeds and that the export command refuses any
  destination that is not gitignored. (4) Audit rows never change `needs_review` shown to students/teachers
  (`persist_correction` test: `needs_teacher_review` unchanged when `audit_sampled=True`).
- **Skills**: `database-design-patterns`, `security-review` (CLI bypass path), `superpowers:test-driven-development`,
  `accuracy-issue-execute`.

#### N3 — Generated-question gates: local SymPy solve-and-filter, sandbox fallback, validity check
- **Problem**: `QuestionGenerator.generate` returns Gemini output verbatim (`question_generation.py:29-57`);
  `TeacherQuizBuilder` tops up shortfall the same way (`teacher_quiz.py:14-69`); unverified AI items: 6%
  factual error, 14% wrong difficulty, 38% clear discrimination bar (B6 [gen 6]); MathQ-Verify +25 F1
  ([gen 1]); Gemini code_execution has SymPy, no surcharge, 30 s ([gemini 17]). Source: roadmap #12, D12.
- **Approach**: `lemely/io/question_gates.py`: (1) validity pass — one structured call (3.5-flash-lite)
  returning {well_posed, missing_data, contradictory, single_answer}; (2) for CALCULATION/EQUATION/numeric
  RECALL items: local I8 solve — model must emit `solution_expr` and `answer`; `equivalent(solve(...), answer)`
  where solvable, else (3) `generate_with_code_execution` in `gemini.py` (tool `code_execution`, cache key
  includes tool flag; parse `code_execution_result`) and require sandbox answer ≡ stated answer; (4) reject →
  regenerate up to 3 with the failure reason in the prompt; (5) tag `verified_by ∈ {sympy, sandbox,
  validity_only}` and `rejection_reason` on `GeneratedQuestion`; `TeacherQuizBuilder` shortfall routed through
  the same gate; rejection stats logged per subject. Difficulty stays `declared_by_generator` (out of scope);
  distractors from examiner reports deferred (reports not in checkout).
- **Rejected**: sandbox-only (non-deterministic, no offline tests); trust-and-tag (status quo — unverified AI
  items measured at 6% factual error, 14% wrong difficulty, 38% clearing discrimination, [gen 6]); MCQ
  distractor mining (examiner reports not in checkout).
- **Touches**: new `lemely/io/question_gates.py`, `lemely/io/question_generation.py`, `lemely/io/teacher_quiz.py`,
  `lemely/io/gemini.py` (code-execution call + cache), `lemely/core/generation.py` (`GeneratedQuestion` fields),
  `lemely/db/question_bank_repo.py:741` (persist tags), `lemely/io/prompts/question_generation.py`,
  `tests/test_question_generation.py` (extend `TestGenerateQuizCLI` — it covers `generate-quiz`; add
  `teacher-quiz` coverage).
- **Impact** High (integrity of bank) · **Effort** L · **Cost** ≈ $0.3 (20 generated items × validity +
  sandbox on flash-lite) · prod delta ≈ +1–2 calls per generated item.
- **Dependencies**: F1, I8. Independent of labels (parallel stream D).
- **Acceptance**: (1) A seeded ill-posed item (missing quantity) is rejected by the validity pass (recorded
  fixture response). (2) A numeric item whose stated answer is wrong by 10% is rejected by SymPy; with a
  non-parseable expression the sandbox path runs and its result is compared. (3) `teacher-quiz` CLI shortfall
  items all carry `verified_by`. (4) Rejection rate per subject reported after generating 20 items each for
  0580/0606/0625 (≤ $0.3).
- **Skills**: `ai-engineer`, `engineering-skills:senior-prompt-engineer`, `superpowers:test-driven-development`,
  `error-handling-patterns` (retry/regenerate), `dependency-management`.

## 3. Milestones (dependency order; ∥ = parallel streams)

| M | contents | streams | gate to next |
|---|---|---|---|
| **M0 Baseline line** | F1 | — | 3.x defaults live; escalation reachable (F1 4b); A/A floor + golden baseline republished in `BUILD/accuracy-runs/<run>/` (existing dir, new run) and `BUILD/review-rate-baseline.json` (existing); ledger ≈ $0.6 |
| **M1 Vision + parser + hygiene** | F4 (migration first) ∥ I8 ∥ I1 ∥ I10 (code + Phase-A schemes) ∥ N1-Phase-A (human, starts day 0) | A: I1; B: I8; C: F4; E: I10 | I1 label-free criteria (1,3,4,5); I10 Phase-A schemes regenerated → `corpus/mark-schemes/<id>.json` (existing dir) + `BUILD/accuracy-runs/<run>/parse-report.json` (NEW file) with gate results; F4 merged; Phase-A transcripts in `eval/labels/<paper>/transcription.jsonl` (NEW, gitignored) |
| **M2 Measurement** | I2 ∥ I3 ∥ N2 (built, sampling off) ∥ N3 (code) ∥ I6/I7 code behind flags; N1-Phase-B (scripts ~wk 4) → I10 Phase-B schemes → **M0 labelled baseline sweep** ($1.25) | A: I2+I3; C: N2; D: N3; F: I6/I7 code | CER published (Phase A, I2 2a); I1 box hit-rate three-band rule (I1 2): ≥ 90% pass, 70–90% pass-with-disclosure, < 70% per-page default recorded; I1 A/B reported (I1 6); I3 variant decided on Phase A; ≥150 Phase-B labels; baseline sweep recorded as `BUILD/accuracy-runs/<run-id>/` (existing dir, new run: RunManifest + eval records) and its summary in `BUILD/review-rate-baseline.json` (existing) |
| **M3 Marker batch** | I6+I7+I8 enabled (one VERSION bump) → validation sweep ($1.25) → I5 `canary compare` M0 vs M3 → I4 first fit on this sweep | A: I6/I7; B: I4 | `mark_accuracy` non-inferior to M0 at −2 pp (I6 3); 2×2 b,c>0 (I2 2b); policy artifact v1 `BUILD/review-policy/<run>.json` (NEW dir); FNR ≤ 0.10 on dev; canary report `BUILD/canary/<date>.json` (NEW dir) |
| **M4 Calibrated release** | I4 final fit at 300 labels; N2 live sampling on; I9 (funded at the $14 ceiling; its sweep refits I4) | — | recall + review rate + AURC published in `BUILD/ACCURACY-REPORT.md` (existing, new section) with the run id; `BUILD/review-policy/<run>.json` metadata matches prompt VERSION + model ids and records `n1` + `mode` (`marginal_or_gate` below n₁ = 50, `mondrian` at n₁ ≥ 100) |

Parallel-safe pairs: {I8, I1, I10, F4} share no files except `schemas.py` (coordinate `ExtractedAnswer`/
`AIMarkResponse` edits: I1 first, I6 later). All `ReviewReason` changes live in F4's single migration —
F4 → N2. {I4, I6} share `correction_ai.py` gate sites — I6 first. I10 Phase-B re-parses precede the
labelled baseline sweep so baseline and M3 use the same parser.

Budget schedule ($14 ceiling, raised 2026-09-17): F1 A/A $0.60 → I1 gold passes + single-vs-per-page A/B
$0.30 → I10 Phase A $1.20 (5 schemes) → I3 variants $0.50 → I10 Phase B $2.00 → M0 labelled baseline sweep
$1.25 → I6/I7 sweep $1.25 → N3 $0.30 → I9 rubric-rewrite sweep $1.25 = **$8.65, $5.35 contingency**. Two
conditional lines now fit inside that contingency and each still stops for a go-ahead: the I6/I7/I8
mechanism-attribution ablation ($1.25, run only if the batch regresses or attribution is wanted) and the
OQ5 `thinking_budget` 4096 parsing test ($1.00) → **$10.90 worst case, $3.10 contingency**. Out of budget
regardless: the 40-scheme 0625 re-parse (≈ $9.6) and any corpus-wide re-parse (≈ $270). Trims are levers,
not plan: I3 second variant only if the first misses AUROC 0.70 (−$0.25); N3 trial capped at 10
items/subject (−$0.15); drop the I1 A/B (−$0.10); limit I10 Phase-B re-parses to the schemes of the first
150 labelled leaves (−$1.00). I5 reuses funded sweeps ($0). The Phase-A transcription set is 54
handwritten-59 pages + 4 solved scripts (≈ 200 answers); the Phase-A marking set is 3 P42 papers + 4 solved
scripts; the labelled sweeps are 300 leaves.

## 4. Risks and open questions

| risk | mitigation |
|---|---|
| $14 ceiling (raised 2026-09-17): schedule $8.65, worst case $10.90 with both conditional lines; one failed sweep ($1.25) is absorbed, several are not | Spend guard per §8: each Gemini step reads the ledger before and after and stops at its budget line. Levers in order: I3 second variant only on an AUROC miss (−$0.25), N3 capped at 10 items/subject (−$0.15), drop the I1 A/B (−$0.10), limit I10 Phase-B re-parses to the schemes of the first 150 labelled leaves (−$1.00); exploratory sweeps on 3.5-flash-lite for correction (≈ 40% cheaper); golden cache makes unchanged re-runs free |
| Minority class (wrong marks) at 300 labels ≈ 45–60 → Mondrian per-class floor (n₁ ≥ 50) borderline; at n₁ = 45 the realised FNR has SD ≈ 0.044, so a 0.10 promise can land near 0.19 | OQ6 answered: below 50 ship marginal conformal + 0.90 OR-gate (flag set ⊇ today's, recall cannot regress), disclose n₁ and the Beta SD, never call it class-conditional; auto-upgrade to Mondrian at n₁ ≥ 100 on the next refit. Condition on {wrong,right} only; report the 2B/(n+1) slack. Audit-stream yield ≈ 0.05 × V × p_wrong (V = monthly confident questions, unknown) — the upgrade is not scheduled against it; label real scripts first |
| Teacher-solved handwritten-59 has no student errors → CER measurable, marking error distribution not | Phase B real scripts; report both populations separately; never pool |
| Migration removes `temperature`/`seed`; A/A floor may widen → smaller effects undetectable | Publish floor with n; power calc per §5; batch changes (user already batching marker) |
| Batched VERSION bump (I6+I7+I8) makes mechanism attribution impossible | Signed over/under-award split + point-level F1 by point type (M/A/B) in the harness; if the batch regresses, ablate by feature flags (`equivalence_gate`, `ecf_substitution`) in a second sweep — $1.25, inside the $14 ceiling, run on regression or on request |
| Gemini-primary parsing at ~$0.24/success + 50% failure until #166 fixed; full 1,130-scheme re-parse ≈ $270 | Scope to gold-set schemes; chunked parsing first; det verifier catches sum errors; corpus-wide re-parse is a separate funded item |
| `response_format` vs SDK field naming; `seed` on 3.x; Files-API URIs in implicit cache — all [uncertain] | Verify against google-genai SDK at F1 start; implicit caching irrelevant (local cache) |
| bbox on multi-image calls for handwriting undocumented accuracy | I1 acceptance measures box hit-rate on handwritten-59 before I3 relies on it; fall back to page-level re-read if < 70% |
| CLI audit export bypasses class scoping by design and emits student work; the repo is PUBLIC and `BUILD/audit/` is git-tracked | No web route or router import of `list_audit_items` (import-graph test); CLI runs server-side only; exports land under `outputs/audit/` (gitignored `.gitignore:52`) and the command refuses non-ignored destinations (N2 acceptance 3); `security-review` pass on the CLI path |
| Real student scripts (N1 Phase B) in a PUBLIC repo | Never committed: scripts under `tests/fixtures/real-papers/` (gitignored `.gitignore:95`) or `outputs/`, labels under `eval/labels/` (gitignored); CI fixtures stay the committed teacher-solved set; any published excerpt needs a C7-style ruling first |
| Labelling is one person, ~20–30 h; schedule slip stalls M3/M4 | Everything in M1 and N3 is label-independent; I6/I7/I4 code lands behind flags before labels |
| Escalation path is dead under same-model defaults (`correction_ai.py:106` guard, `:84-85` borderline budget) | F1 changes the guard to a (model, thinking) tuple and sets `correction_borderline`; acceptance 4b proves it fires; escalation rate reported |
| Feature-selection leakage: I3 variant chosen on the same rows I4 calibrates on | I3 selects on Phase-A transcription labels; I4 fits on Phase-B mark labels; 5-fold CV reported |
| Calibrator guarantee invalidated by any later prompt/model change (e.g. I9) | Artifact metadata (VERSION, models, split hash) enforced at load; refit on the change's own validation sweep |
| Strategy §6: marker tuned on Gemini-parsed schemes only | I10 makes Gemini the primary for all, removing the split distribution |

Open questions (do not block M0–M1): (1) **ANSWERED 2026-09-17 — ceiling raised to $14**
(`total_usd_ceiling=14.0`); the schedule is $8.65 with $5.35 contingency and I9 is funded. (2) consent +
commit authorisation for real student scripts (C7-style ruling needed before Phase B lands in `tests/`).
(3) I3 variant cutoff AUROC 0.70 — adjust after seeing the curve? (4) Should equivalence
`equal`-but-withheld auto-award once FPR is measured (< 2%)? (5) Whether `thinking_budget` 4096 for parsing
keeps DA35 success rate (test costs ≈ $1, now inside budget). (6) **ANSWERED 2026-09-17 — marginal
conformal + 0.90 OR-gate below n₁ = 50**, floor and Beta SD disclosed, with an automatic refit to
class-conditional Mondrian once n₁ ≥ 100 (labels + audit imports); the calibrator is not held back. (7) **ANSWERED 2026-09-17 — both PDFs supplied** at
`/home/sico/Documents/0625_s25_ms_42.pdf` and `/home/sico/Documents/0625_w25_ms_42.pdf` (verified 19 and 20
pages, IGCSE Physics 0625/42, Maximum Mark 80); the first M1 step copies them into
`Sources/Physics/MarkingSchemes/` and corrects the stale line at `handwritten-59/README.md:57-65`; Phase A
marking = all 3 P42 papers + 4 solved scripts.

## 5. Traceability (brief roadmap → plan)

| # | brief row | plan | note |
|---|---|---|---|
| 1 | Gold transcription set + CER | I2, N1 | as brief; jiwer; 2×2 finally run |
| 2 | Two-pass agreement confidence | I3 (+I4) | seam + measurement; cross-model variant added per Consensus Entropy |
| 3 | 300 DPI, per-page, media_resolution, crop-re-read | I1 | 200 DPI, single multi-image call, medium/high; bbox field added first |
| 4 | OpenCV OMR for MCQ | — (F3 withdrawn) | **rejected**: users circle on QP (D18); confidence leakage already fixed by #36; MCQ rows feed I4 |
| 5 | SymPy A-mark gate | I8 (+I6) | new module; conflicts route to review, no auto-award yet |
| 6 | Numbas-style ecf/ft | I7 | substitution of values, try-without-replacement; not full recompute (schemes lack formulas) |
| 7 | Calibrator + Mondrian conformal, AURC | I4 | α=0.10 FNR; crepes; {wrong,right} classes |
| 8 | Remove AI flag; cohort similarity; inconsistency | F4; I6 (inconsistency as verdict gate) | cohort similarity **deferred** (D10) |
| 9 | Cache reorder + Batch API | F1 (cache key) | reorder is a no-op (local cache); Batch **deferred** (D21) |
| 10 | Rubric rewrite vs confusion matrix | I9 | funded sweep at the $14 ceiling; runs in M4 |
| 11 | Per-step verdicts + spans | I6 | batched with 5/6 (D19) |
| 12 | Solve-and-filter + validity | N3 | local SymPy primary, sandbox fallback |
| 13 | Random audit + seeded items | N2, I5 | audit hidden/ops-only; seeding offline only |
| 14 | Cluster failing schemes, texttrace bold, pdfplumber sweep | I10 | reframed: Gemini-primary + det verifier + fidelity gates; bold/underline **deferred** (failures are sum mismatches) |
| 15 | Gemini 3.x migration plan | F1 | executed, not planned; mark_scheme stays 2.5 |
| 16 | Two-stage flashcards, tags, PlanGlow loop | — | **deferred** (D13) |
| 17 | Ofqual positioning | F4 copy | folded into review-UI copy + docs |
| — | NOT-REC list (fine-tune, detectors, Docling, DKT, logprobs, advisory prompt) | — | all **rejected**, consistent |

## 6. ADR

- **Decision**: Option A — migrate to Gemini 3.x first (3.8-flash marking, 3.5-flash-lite vision/generation,
  2.5-flash parsing), then run one baseline line; build label-independent pipeline changes (per-page vision,
  second-read seam, SymPy, verdict schema, Gemini-primary parsing, AI-flag removal, generation gates) while
  the user labels ~300 leaves; replace the 0.90 threshold with a learned calibrator + Mondrian conformal gate
  at α=0.10 and a hidden random audit served only via CLI export to the `platform_admin` seat (D5's "ops
  role" satisfied without a sixth role and without a web tenancy bypass).
- **Drivers**: zero labels and a single labeller; $14 ceiling; 3.x API removals; Ofqual/Cambridge human-review
  framing.
- **Alternatives considered**: label-first on 2.5 (two baselines); threshold retune (no guarantee); OMR
  (wrong input modality); delete det (loses verifier); Batch/Interactions API (no benefit now); fine-tuning,
  detectors, Docling, DKT, logprobs (evidence against).
- **Why chosen**: single comparable baseline; guarantee-bearing gate; maximum label-independent progress;
  every item measurable on the existing instrument.
- **Consequences**: golden cache invalidated once; A/A floor re-measured; prod marking cost ≈ +$0.08/paper;
  I5 canary reuses funded sweeps; mechanism attribution within the marker batch is recovered only by the
  optional ablation sweep.
- **Follow-ups**: cohort similarity, Batch opt-in marking, flashcards/study-plan BKT, examiner-report
  distractors, bold/underline parsing, OMR, the 40-scheme 0625 re-parse — next cycle.

## 8. Execution protocol (user directive at approval, 2026-09-17)

**Mode**: `ralph` + `ultrawork` (`/oh-my-claudecode:ralph` with parallel ultrawork agents), plan path
`docs/plans/ai-improvements-plan.md` as the task source. **Main session = orchestrator on opus**: decides,
sequences milestones, dispatches, reads verifier evidence; never implements directly. Subagents routed by
task complexity:

| tier | use for | items / passes |
|---|---|---|
| **fable** | judgement-heavy, cross-cutting, or guarantee-bearing design where a wrong call invalidates a milestone | I4 policy + conformal design and the fit/report; I10 #166 root-cause + chunked-parse design; F1 migration design review (cache key, thinking, schema); adversarial review of any accuracy claim before it enters `BUILD/` |
| **opus** | architecture, prompt/schema engineering, review, critique | I6 verdict schema + prompt (VERSION bump), I7 ecf chain, I9 rubric rewrite; `accuracy-reviewer` pass on every PR touching `lemely/io/correction_ai.py`, `lemely/eval`, `lemely/accuracy`, gates or a measurement; Architect/Critic re-checks between milestones |
| **sonnet** | implementation with tests, mechanical refactors, harness plumbing, CLI, migrations, web copy | F1 code, F4, I1, I2, I3, I5, I8, N2, N3, all test suites, `lemely doctor` output, docs updates |
| **haiku** | lookups, scribe work, formatting, run-log transcription | `accuracy-scribe` entries in `BUILD/DECISIONS.md` / `JOURNAL.md`, pricing table rows, changelog lines, fixture inventories |

**Per-item loop** (ralph): implement (sonnet/opus per table) → tests green on touched files only (memory:
no full local suite; CI runs it) → `pre-commit run --all-files` → reviewer pass (opus `accuracy-reviewer`
for accuracy items, `reviewer` otherwise; fable for the four fable-tier items) → verifier evidence
(`superpowers:verification-before-completion`) → signed conventional commit (`git commit -S`, scopes as in
CLAUDE.md, no push) → next item. Milestone gates in §3 are checked by the orchestrator against the named
artifacts before the next milestone starts.

**Spend guard**: every Gemini-spending step (F1 A/A, I1 passes, I3 variants, I10 parses, the two labelled
sweeps, N3 trial) is a separate ralph task with its budget line from §3; the orchestrator reads the ledger
before and after; a step that would exceed its line stops and asks.

**Human-only steps** (ralph pauses, never simulates): N1 labelling passes, real-script arrival (D3),
C7-style ruling if
any excerpt is ever published, frozen-split extension (H4/H9).

**Not done by execution**: anything in §5 marked deferred/rejected; pushing; merging to `develop`.

## 7. Changelog (Architect/Critic consensus)

Post-approval amendments (user answers, 2026-09-17) — applied:
- OQ1 answered: ceiling $7 → **$14** (`total_usd_ceiling=14.0`). I9 is funded and moves into M4; the
  schedule becomes $8.65 with $5.35 contingency; the I6/I7/I8 ablation ($1.25) and the OQ5 parsing test
  ($1.00) fit inside it (worst case $10.90); trims demoted from plan to levers. §1, §2 (F1, I9), §3, §4,
  §5 row 10, §6, §8 and Appendix A/C updated.
- OQ7 answered: `0625_s25_ms_42.pdf` and `0625_w25_ms_42.pdf` supplied at `/home/sico/Documents/` (verified
  19 and 20 pages, IGCSE Physics 0625/42, Maximum Mark 80). I10 Phase A = **5 schemes ($1.20)**; N1 Phase A
  marking = **3 P42 papers + 4 solved scripts**; first M1 step copies both PDFs into
  `Sources/Physics/MarkingSchemes/` and fixes the stale `handwritten-59/README.md:57-65` line.
- OQ6 answered: ship **marginal conformal + 0.90 OR-gate** when n₁ < 50, with n₁ and the realised-FNR Beta
  SD disclosed and the guarantee labelled pooled (never class-conditional); the artifact records `n1` and
  `mode`, and the next refit at **n₁ ≥ 100** upgrades to Mondrian and drops the OR-gate. Rejected: holding
  the calibrator in shadow until the audit stream fills (timeline depends on unknown production volume);
  extra targeted labelling with weighted conformal (costs labelling hours, adds shift machinery); loosening
  α to 0.20 (weaker promise than the user's D6 choice). I4 approach/acceptance, §4 risk row and §3 M4 gate
  updated.
- D5 approved: `platform_admin` seat + server-side CLI export, no sixth role, no web tenancy bypass (N2
  unchanged).

Architect pass (opus, 2026-09-17) — applied:
- MUST: F1 escalation made reachable (guard on (model, thinking) tuple; `correction_borderline` level);
  I4 "escalation delta" feature now conditional; F1 acceptance (4) replaced (was vacuous: `model` is already
  in the key) + new 4b.
- MUST: `Role` fact corrected (five members incl. school_admin/platform_admin; `require_role` at
  `deps.py:872-896`); N2 uses `platform_admin`, no sixth role; Appendix A corrected.
- MUST: I4 acceptance no longer compares to the pre-migration 14.29% (P5); new-line baseline only.
- SHOULD: I3 variant selection on Phase-A transcription labels, I4 fit on Phase-B mark labels (no leakage);
  5-fold CV; `quiz_marking_repo.py:9`, `core/at_risk.py:50`, `tests/test_web_shared_constants.py` added to I4.
- SHOULD: one `ReviewReason` migration (F4) → N2 (F3 later withdrawn); I10 re-parses tied to labelled
  papers and run before the labelled baseline sweep; det-verifiable vs det-unverifiable denominators.
- Also: I1 acceptance split into label-free (M1) and label-dependent (M2) with a single-call vs per-page
  A/B; I2 2×2 requirement moved to Phase B; I5 canary reuses funded sweeps; I6 attribution aids mandatory
  (M/A/B point F1, flags); I4 frozen-surface + artifact-metadata rule + minority-floor default; I9 explicitly
  unfunded; budget schedule recomputed ($7.7 at $7 → trims listed); risks/open questions updated.
- Architect's steelman (freeze surface before calibrator) adopted via the frozen-surface rule: I4 fits on the
  M3 sweep, after the marker batch, not before.

Critic pass (opus, 2026-09-17) — applied:
- BLOCKER: F3 withdrawn — all four defects already fixed by #36 (`5cc58cb8`), verified at
  `answer_extraction.py:95-134`, `correction_ai.py:137-200`, `harness.py:567-580`; residual folded into I4
  features; F4 migration no longer adds `missing_key`.
- BLOCKER: identifier namespace legend added (Dn interview decisions vs SDn strategy defects); all strategy
  defect references renamed SDn.
- MAJOR: platform_admin wording propagated to §1 and §6 with a D5 sign-off note; non-inferiority margin
  (−2 pp, CI lower bound on paired difference) replaces "not worse (McNemar)" in I1, I6, I9 and the M3 gate;
  I1 criterion 6 moved to the label-dependent block; 2×2 gate placed in M3 only; 70–90% box hit-rate band
  defined; ceiling risk now names a pre-committed cut list ($6.20 path); audit-yield claim replaced by the
  formula and marked not relied on.
- MINOR: coherence gate pointer `:384`; `tests/test_docs_consistency.py` marked NEW; I1 cost uses 54 pages
  + solved scripts (~200 answers, defines the Phase-A gold set); 12 golden fixture dirs; I7 Touches +
  `schemas.py`; I9 Touches + `review_policy.py`; N3 "trust-and-tag" rejection grounded in [gen 6]; I2
  criterion (1) states the expected CER (0.125); I10 gains a #166 contingency and $3.5 cap.

Architect pass, iteration 2 (opus, 2026-09-17) — applied:
- Escalation: four named edits (`model_for` keys `correction_borderline`/`escalation`; 3.x `ThinkingConfig`
  branch at `gemini.py:215-229`,`:527-536`; ordered-level gate at `correction_ai.py:84-85`; tuple guard +
  `task_tag="escalation"` at `:104-108`,`:124`); acceptance 4b restated (three calls, none on the global
  2.5 model).
- N2 re-designed for tenancy: no web bypass for `platform_admin` (`review_repo.py:260-268`, `:638-660`,
  `:363-371` preserved); audit rows carried by `CorrectedQuestion.audit_sampled` → `review_queue.is_audit`
  (`models/ops.py:26-59`) written at `attempt_repo.py:315-331` / `teacher_paper_repo.py:123-162`; served
  only via CLI `list_audit_items()`; Touches/acceptance updated; §1/§6 wording aligned.
- M2 gate aligned with I1's 70–90% band; changelog no longer routes through withdrawn F3.
- Steelman confirmed: no cheaper ordering under D14/D15/D19 (I6 schema enters the cache fingerprint; two
  sweeps irreducible).

Critic pass, iteration 2 (opus, 2026-09-17) — ITERATE, applied:
- F4 now carries `review_queue.is_audit` (approach, touches, acceptance 2c); acceptance 2 split into schema
  round-trip (2a) and one-way data assertion (2b).
- N2 exclusion retargeted to the two `list_queue` selects (~`:340-355`, `:372-380`) and `_find_any_item`
  (`:686-710`); fourth insert branch/yield rather than edits to the existing three; heading "CLI-only";
  acceptance (1) states the eligible population (800 of 1,000); platform_admin clause kept as a regression
  assertion; risk row rewritten for the CLI bypass; §1 notes built-in-M2 / live-in-M4.
- M2 gate restated as the three-band rule; M1/M2/M4 gates now name artifacts
  (`Sources/Physics/MarkingSchemes/<id>.json`, `BUILD/accuracy-runs/<run>/parse-report.json`,
  `eval/labels/<paper>/transcription.jsonl`, `BUILD/accuracy-runs/<run-id>/`, `BUILD/review-rate-baseline.json`,
  `BUILD/ACCURACY-REPORT.md`, `BUILD/review-policy/<run>.json`, `BUILD/canary/<date>.json`).
- Appendix C D5 annotated with the planning amendment.

Critic pass, iteration 3 (opus, 2026-09-17; Critic-only — Architect iteration-2 items were fully applied and
code-verified by the Critic) — ITERATE, applied:
- Public-repo safety: audit exports → `outputs/audit/` (gitignored), export command refuses non-ignored
  destinations (N2 acceptance 3); Phase-B student scripts never committed (N1, new risk row); `BUILD/audit/`
  is tracked — never used.
- Phase A restated from `handwritten-59/README.md:57-65`: transcription on all 54 pages; marking on ≤ 2 P42
  papers + 4 solved scripts; I10 Phase A = 4 schemes ($1.00); open question 7 (missing scheme PDFs).
- Parsed-scheme path corrected to `corpus/mark-schemes/<id>.json`; §3 artifacts marked NEW vs existing.
- Budget recomputed: $7.20 → $6.80 after trims ($0.20 contingency) → $5.70 on the cut list.
- Appendix A extended with repo visibility, gitignore lines, corpus facts.

Critic pass, iteration 4 (opus, 2026-09-17) — **APPROVE**; five minors applied: README staleness on the
s25 PDF flagged; I10 Phase A = 3 schemes ($0.72) and Phase-A marking = 1 P42 paper + 4 solved scripts;
m21_62 has a det JSON (only s19_43 lacks one); `Sources/` gitignored (`:51`) noted; `eval/labels/` line
(`:151`) added; budget $6.92 → $6.52 after trims → $5.42 on the cut list; `corpus/mark-schemes/` tracked-in-
public-repo precedent (ask B8) recorded in I10.

---

## Appendix A — verified repo baseline (do not re-derive)

- Accuracy programme (#23) retired 2026-08-29 (ruling C26). Instrument landed on develop: `lemely/eval`
  (EvalRecord, RunManifest, ablation_2x2, mcnemar, wilson, risk_coverage, exclusion_funnel, review_rate),
  determinism substrate + `--cache-mode bypass`, A/A churn floor, frozen split + test-touch ledger,
  review-rate ratchet CI gate (unarmed), coherence gate (#40, `correction_ai.py:387`), positional fallback
  deleted → UNMATCHED (#37), defaulted-mark provenance (#38, `det/rows.py:264`), GMP injection (#41),
  two-pass blind labeller (`lemely/labelling/`).
- Never done: zero of ~300 human labels (`eval/labels/.gitkeep` only); 2×2 attribution; review rate 29.03%
  dev-split (`BUILD/review-rate-baseline.json`, n=31) / 32.58% vs 10% budget; flag_recall 14.29% (n=71);
  Gemini mark-scheme fallback fails ~50% (#166); pre-2017 parsing strategy.
- Corpus: 1,130 schemes (2010–2025), det parses 393 (34.8%). 0625: 32/72 (`BUILD/DECISIONS.md:198`).
- Real handwriting: `tests/fixtures/handwritten-59/` (3 teacher-solved 0625 P42 papers, 54 pages, 0 text
  chars, NOT student attempts) + `Sources/Physics/Solved/` (4 solved scripts). Synthetic golden: `tests/golden/`
  12 fixture dirs, 71 rows, 31 leaves, 150 DPI. Examiner reports NOT in checkout.
- Spend: $6.37 of `total_usd_ceiling` 8.0 (ledger to be reset to 0, ceiling 14.0 — D4, raised 2026-09-17). Pricing table keyed to
  2.5 family (`gemini.py:40-44`).
- Gemini client: `genai.Client(api_key=...)` only; model `gemini-2.5-flash` (`config.py:94`); per-task model
  overrides + `escalation_model`/`escalation_confidence_threshold=0.80` (`config.py:96-112`);
  `thinking_budget_for` {"mark_scheme": 8000} (`:117`); `temperature_for`/`top_p_for`/`seed_for` (`:123-128`);
  `_params_fingerprint` (`gemini.py:231-253`) → `_cache_key` (`:275`); `_MAX_OUTPUT_TOKENS=65536`;
  `_strip_schema` passes `pattern` (`:122-145`).
- Confidence: `_calibrate_confidence` (`answer_extraction.py:83-136`); `REVIEW_CONFIDENCE_THRESHOLD=0.90`
  (`schemas.py:47`, mirrored `web/src/lib/markingConfidence.ts:35`).
- Marker: `AIMarkResponse` 4 fields (`schemas.py:222-226`); `_verify_calculated_answers` regex backstop
  (`correction_ai.py:304-360`); `_build_mcq_corrected` (`:131-189`); prompt `VERSION="5"`; ecf/ft prose-only;
  `required_with` never read in marking (only `accuracy/metamorphic.py:228-234`).
- Review: `ReviewService.list_queue` (`review_repo.py:287`) no sampling; `ReviewReason` 4 members
  (`enums.py:175-181`); `Role` = student/parent/teacher/school_admin/platform_admin (`enums.py:21+`);
  authz `require_role(*allowed)` (`lemely/web/deps.py:872-896`); `_STAFF_ROLES` (`web/routers/teacher.py:195`).
  Escalation: `AICorrector.mark_question` (`correction_ai.py:104-126`), guard `:106`, borderline budget `:84-85`.
  Other 0.90 consumers: `quiz_marking_repo.py:9`, `core/at_risk.py:50`, parity test
  `tests/test_web_shared_constants.py`. Coherence gate `_check_coherence` at `correction_ai.py:384`.
- Integrity: `ai_detection_enabled=False` (`config.py:458`); `PlagiarismChecker.check` vs mark-scheme answer
  (`plagiarism.py:31`). `test_disable_plagiarism` EXISTS (`tests/test_config_new_tasks.py:66`) — brief B8 wrong.
- Generation: `QuestionGenerator.generate` verbatim; `TeacherQuizBuilder` (`teacher_quiz.py:14`);
  `TestGenerateQuizCLI` covers `generate-quiz` not `teacher-quiz`; SM-2 live; no FSRS/DKT.
- Parsing: `lemely/io/det/` pdfplumber; no bold/underline; failures = mark_total_mismatch (SD1–SD7);
  `ChainedMarkSchemeParser` det-first (`parsers.py`).
- Already fixed by #36 (`5cc58cb8`), NOT re-planned: caps-last calibration, no MCQ bonus, extraction
  confidence propagated into MCQ marks, missing key → LOW/review, MCQ in calibration (SD13/14/15/19).
- Deps already present: PyMuPDF (AGPL), pdfplumber, pypdfium2, Pillow, numpy. Not present: sympy, crepes,
  jiwer, rapidfuzz, scikit-learn.
- Repo `LemelyIG/Lemely` is **PUBLIC** (`gh repo view`). Gitignored: `Sources/` (`.gitignore:51` — solved
  scripts are local-only, not in CI), `outputs/` (`:52`), `tests/fixtures/real-papers/` (`:95`),
  `/eval/labels/` (`:151`, `.gitkeep` unignored `:154`). `BUILD/audit/` and `corpus/mark-schemes/` are
  git-tracked.
- Parsed schemes: `corpus/mark-schemes/` 289 JSON (det only, `corpus/manifest.json` `gemini_used: false`,
  generated from `/home/sico/PaperScraper/papers` which is absent from disk) incl. `0625_w24_ms_42.json`
  and `0625_m21_ms_62.json`; no `0625_s25_ms_42.json`. `Sources/Physics/MarkingSchemes/`: PDFs m20_12,
  m21_62, s19_43, s20_31 + JSON m20_12, s20_31. `0625_s25_ms_42.pdf` and `0625_w25_ms_42.pdf` were supplied
  by the user on 2026-09-17 at `/home/sico/Documents/` (19 and 20 pages, Maximum Mark 80) and are copied into
  `Sources/Physics/MarkingSchemes/` at M1 start; `handwritten-59/README.md:57-65` still needs its stale s25
  line corrected.
- Brief numbers: 32/72 and 14.29% real; "58:1" is [calib 11]'s benchmark; 40-MCQ anecdote real
  (`docs/ACCURACY-STRATEGIES.md:56`).
- `docs/ACCURACY-STRATEGIES.md` T-items converging with this plan: T1.7, T1.9, T1.10, T2.1, T2.3, T2.5, T2.6,
  T2.8, T2.9, T2.10, Tier-3 conformal.

## Appendix B — web re-verification (2026-09-17)

Gemini API (official pages): UNCHANGED vs brief — 3.8-flash latest at $0.75/$3.75 promo to 31 Dec 2026 (then
$1.50/$7.50); 3.5-flash $1.50/$9.00; 3.5-flash-lite $0.30/$2.50; 3.1-flash-lite $0.25/$1.50 (retires 7 May
2027); 2.5-flash $0.30/$2.50; 2.5-flash-lite $0.10/$0.40; temperature/top_p/top_k/candidate_count removed on
3.x; `thinking_level` (minimal only 3.6-flash/3.5-flash-lite); structured output `response_format`, `pattern`
unsupported, `enum` ok; media_resolution low/medium/high/ultra_high = 280/560/1120/2240 tokens (PDF max 1120),
medium recommended for PDFs; implicit cache 90% off, floors 4,096 (3.x)/2,048 (2.5); Batch 50% off, 24 h,
2 GB/file; code_execution no surcharge, 30 s, SymPy present; safety default Off; Files API 2 GB/file, 48 h.
[uncertain]: `seed` on 3.x; Files-API URIs in implicit cache; cache TTL; SDK field name for 3.x schema.
Logprobs: absent on 3.x (forum 176557) and Interactions API.
Tooling: crepes 0.9.1 (BSD-3, `class_cond=True` Mondrian); MAPIE 1.5.0 no Mondrian; py-fsrs = FSRS-6; PyMuPDF
1.28.2 AGPL `get_texttrace()` exists; pdfplumber 0.11.10; OMRChecker v1.1.0 (2023, MIT); Mathpix $0.002/image;
SymPy 1.14 (`parse_latex` antlr4==4.11 or Lark); jiwer 4.0.0; rapidfuzz 3.14.6.
Regulatory: Ofqual principles 14 Jan 2026 unchanged; NEW Ofqual "approach to regulating AI in the
qualifications sector" 16 Jul 2026; NEW Cambridge International AI-assisted marking for July-2026 digital
mocks (200k+ marks, human verification); JCQ Rev 2 (30 Apr 2025); DfE 12 Aug 2025; SynthID text API preview
only, no public verification.
Vision: bbox 0–1000 `[ymin,xmin,ymax,xmax]` documented for images (2026-09-02), not PDF; Consensus Entropy
v4 (May 2026): cross-model > same-model; "PDF capped at 1120" inverted (medium=560); "degrades past 3 pages"
unsourced; 0625 P2 = separate soft-pencil sheet (specimen 595784); 0580 P1/P2 no MCQ; no CAIE OMR project.
Calibration: arXiv 2609.10996 tested Gemini 2.5 Pro (pre-2025 bucket) and 3.1 Pro (post); brief misattributes
arXiv 2603.13083 (VUB HITL handwritten maths; consistency gating failed); arXiv 2412.06910 confirmed; SURE
(MDPI MAKE 2026-03-16, doi 10.3390/make8030074); arXiv 2604.26954 Gemini 3.1 Pro j=1→7 no gain; arXiv
2605.09702 budget is binary-only; Mondrian n₁<50 caveat (arXiv 2607.27143 §6.3); arXiv 2509.15926 (EMNLP 2025
conformal essay routing); ETS e-rater ≈ 2% escalation; AQA FOI Aug 2025 no AI marking [uncertain].
Competitors not in brief: GradeOrbit, MarkIt (98.6% within ±1 mark, £5.99/30 papers), TeachEdge.ai,
ReMarkAble AI, MarkMe, exam-mate AI Exam Marker (CAIE brand), Top Marks AI (r=0.91 Edexcel IGCSE English),
Save My Exams Smart Mark [uncertain scope]; AQA QA pilot (80% match); Google Document AI $1.50/1k + Math OCR
$6/1k; Textract $0.0015/page.

## Appendix C — interview decisions (8 rounds, 2026-09-17)

| # | decision |
|---|---|
| D1 | Priority: marking accuracy on real handwriting first |
| D2 | User labels ~300 leaves personally (two-pass) |
| D3 | Real student scripts within ~4 weeks; teacher-solved + synthetic until then |
| D4 | Accuracy first, cost secondary — dev ceiling **$14 total, ledger reset to 0** (raised from $7 on 2026-09-17) |
| D5 | Reviewer = uploading teacher; ops/admin seat (user) for hidden audit stream — **amended in planning**: satisfied by the existing `platform_admin` seat running a server-side CLI, no new role (N2); **approved by the user 2026-09-17** |
| D6 | Gate optimises FNR: α = 0.10; review rate reported, no cap; ratchet observational |
| D7 | Random audit: unconditional, hidden from teachers, ops-only |
| D8 | Seeded drift check: offline canary only |
| D9 | AI-generated-answer flag removed entirely + JCQ-aligned note |
| D10 | Cohort similarity: wanted, **deferred** |
| D11 | Working-vs-answer inconsistency: M-mark verdict gate + advisory note |
| D12 | Solver: local SymPy primary, code_execution fallback; validity check; all types, all subjects |
| D13 | Flashcards two-stage + study-plan BKT/critique: **deferred** |
| D14 | 3.8-flash correction/escalation; 3.5-flash-lite extraction/generation/scan_metadata; mark_scheme on 2.5-flash (tuning per plan) |
| D15 | Migrate first; all measurement on the new line |
| D16 | Per-page images (pypdfium2) at medium; high on re-read; bbox `source_box` |
| D17 | Second-read seam; variant chosen after gold-set AUROC |
| D18 | No OMR; MCQ on VLM; fix confidence leakage; MCQ in calibration |
| D19 | #5/#6/#11 as one batched VERSION bump (user override of strategy §4) |
| D20 | Parser: Gemini primary, det verifier; #166 + fidelity gates mandatory; no new det features |
| D21 | Batch API: deferred entirely |
| D22 | Horizon: open-ended, dependency-ordered |
