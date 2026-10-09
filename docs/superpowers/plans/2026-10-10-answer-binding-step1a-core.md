# Answer Binding Step 1A (Core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** No paper whose answers are bound to the wrong questions is marked and published; the binding comes from evidence the code verifies, never from an id the model supplies.

**Architecture:** The extraction model stops returning question ids. It returns two streams: the question labels it can see on each page (printed or handwritten) and the answers, each with a page and box. Code aligns the label stream with the mark scheme's known label sequence and attaches each answer to the label above it. A pure gate then checks the result before marking and once more after marking; a failed gate triggers one retry on a stronger model, and a second failure stops the paper.

**Tech Stack:** Python 3.13, pydantic v2, google-genai through `lemely.io.gemini.GeminiClient`, SymPy through `lemely.core.equivalence`, pytest, click CLI.

Spec: `docs/superpowers/specs/2026-10-09-answer-binding-design.md`. Line numbers refer to `develop` at 885724d0.

## Scope

Step 1 of the spec holds two subsystems. This plan is **1A**, the binding core. **1B**, the product hold flow (`UploadStatus.held`, `ReviewReason.binding_unverified`, the result API's `state`, the student, teacher and admin screens), gets its own plan.

Until 1B lands, a paper the gate holds takes the existing failure path: nothing is persisted, the upload becomes `failed`, and the student sees a message that says why. That is fail-closed, and it is temporary.

Not in this plan: the question-paper corpus, `PaperLayout`, `PageMap`, `PositionBinder`, and checks G3 and G4.

## Global Constraints

- The reader never sees expected answers. Prompts may carry a leaf's label, marks, expected shape and stem; never a mark-scheme point.
- No code path may assign a question id by position in a list. An answer with no aligned label is `unbound`.
- `ExtractedAnswer.confidence` keeps its meaning (legibility). Binding has its own fields.
- `lemely/core` must not import `lemely/io` (import-linter contract). Gate, parser and types live in `lemely/core`.
- Every prompt change bumps that prompt module's `VERSION`, which invalidates the cache.
- Never commit the student's scan. Fixtures hold extracted text only, with no absolute paths.
- Tests run per file: `pytest tests/<file>.py -q`. Never `make test` or bare `pytest` locally; CI runs the full suite.
- Imports resolve through a shared venv whose editable path may name another worktree. Run every script and CLI as `PYTHONPATH=$(pwd) python -m …`, and print `lemely.__file__` once per live run.
- Commits are signed (`git commit -S`), use conventional messages with scopes, and name their paths (`git commit -S -m … -- <paths>`). Run `pre-commit run --all-files` first.
- Model routing: implementation and tests by `sonnet`; prompt and wire-schema text by `opus`; live measurement by `accuracy-measurer`; review of every diff by `accuracy-reviewer`.

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `lemely/core/binding.py` | new | Types: `BindingSource`, `BindingStatus`, `BindingCheck`, `BindingVerdict`, `BindingReport`, `LabelMarker`, `ReadAnswer` |
| `lemely/core/label_sequence.py` | new | Expected label sequence from a mark scheme; parsing of quoted labels; alignment of a seen stream with the expected sequence |
| `lemely/core/binding_expect.py` | new | Expected shape and expected numeric values of a leaf; shape of an answer text |
| `lemely/core/binding_gate.py` | new | Checks G1, G2, G5, G6, G7, G8, G9 and the verdict |
| `lemely/core/schemas.py` | modify | Binding fields on `ExtractedAnswer`, `ExtractedAnswers`, `AIMarkResponse`, `CorrectedQuestion`, `CorrectionResult` |
| `lemely/io/prompts/label_binding.py` | new | System and user prompt for the two-stream read; `VERSION` |
| `lemely/io/binding/__init__.py`, `lemely/io/binding/label_binder.py` | new | The model call, per-element salvage, and `bind_by_markers` |
| `lemely/io/answer_extraction.py` | modify | Orchestration: binder, pre-marking gate, one retry, report |
| `lemely/io/prompts/correction_ai.py`, `lemely/io/correction_ai.py` | modify | `addresses_question` in the marker's reply; post-marking gate |
| `lemely/runtime/config.py` | modify | `[binding]` settings |
| `lemely/runtime/events.py` | modify | `EventType.BINDING_GATE_RESULT` |
| `lemely/web/routers/student.py`, `lemely/db/teacher_paper_repo.py` callers | modify | Fail-closed handling of a held paper |
| `lemely/accuracy/metamorphic.py` | modify | Misbinding transforms |
| `lemely/app/cli.py` | modify | `audit-bindings` command |
| `tests/fixtures/binding/0625_w24_41/` | new | Recorded extraction outputs and the reference binding |

---

### Task 1: Recorded fixtures

**Files:**
- Create: `tests/fixtures/binding/0625_w24_41/{full_shift_lite,full_shift_38_a,full_shift_38_b,full_shift_38_c,chaotic,partial_a,partial_b,aligned}.json`, `tests/fixtures/binding/0625_w24_41/README.md`
- Test: `tests/test_binding_fixtures.py`

**Interfaces:**
- Consumes: `.omc/research/p4n24-shift/runs/{d72_1,m38_1,m38_2,m38_3,d72_2,d72_4,d72_5}.json` and `.omc/research/p4n24-shift/aligned_ref.json` (in that order, matching the file names above).
- Produces: `tests/fixtures/binding/0625_w24_41/<name>.json`, each a valid `ExtractedAnswers` document. Later tasks load them with `ExtractedAnswers.model_validate_json`.

- [ ] **Step 1: Write the failing test.** `test_fixture_set_is_complete`: all eight files exist and validate as `ExtractedAnswers`. `test_fixtures_carry_no_local_paths`: no file contains `/home/` or `/tmp/`; `source_scan` equals `"0625_w24_41_student_scan.pdf"`. `test_aligned_fixture_matches_the_scan`: `aligned.json` binds `1a_i` to an answer containing both `43` and `63`, `1a_ii` to `20`, `9c_iv` to `4.5`, and has no entry for `7c` (the student left it blank).
- [ ] **Step 2: Run it.** `pytest tests/test_binding_fixtures.py -q`. Expected: fails, files missing.
- [ ] **Step 3: Copy and sanitise.** Copy each source file to its fixture name, replacing `source_scan` with `"0625_w24_41_student_scan.pdf"`. Change nothing else. Write the README: which run produced each file (model, render dpi, date 2026-10-09), that `aligned.json` came from checkout 1bee5a4d, and that the scan itself is deliberately absent.
- [ ] **Step 4: Run it.** Expected: 3 passed.
- [ ] **Step 5: Commit.** `test(binding): recorded extraction outputs for 0625/41 O/N 24`.

---

### Task 2: Go/no-go measurement of the two-stream read

This task writes no product code. It decides whether Tasks 6 and 7 are worth building.

**Files:**
- Create (ignored, not committed): `.omc/research/p4n24-shift/two_stream.py`

**Interfaces:**
- Consumes: the scan at `.omc/research/p4n24-shift/student.pdf`; `corpus/mark-schemes/0625_w24_ms_41.json`; the harness pattern in `.omc/research/p4n24-shift/exp.py` (cache bypass, separate ledger, `--dpi 72`).
- Produces: a table reported to the orchestrator: per run, the share of manifest leaves whose label was found in order, and the share of answers attached to the right leaf (judged against `tests/fixtures/binding/0625_w24_41/aligned.json`).

- [ ] **Step 1: Draft the prompt (opus).** One call over all page images. The reply has two lists. `markers`: every question label visible on a page, printed or handwritten, in reading order, each `{page, box, text, kind}` with `text` copied exactly as seen (`1`, `(a)`, `(i)`, `(ii)`, `Q3 b`). `answers`: every block of student writing, each `{page, box, answer, working_out, confidence}`. The prompt forbids question ids in the reply and states that numbered lines inside one part (`1. …`, `2. …`) are not question labels.
- [ ] **Step 2: Run five times on `gemini-3.5-flash-lite` and five on `gemini-3.8-flash`** (accuracy-measurer), cache bypassed, two processes at most at once.
- [ ] **Step 3: Score.** Build the expected label sequence by hand for this paper (`1`, `(a)`, `(i)`, `(ii)`, `(b)`, `(c)`, `(i)`, `(ii)`, `2`, …). Align each run's marker texts to it with `difflib.SequenceMatcher`. Attach each answer to the nearest marker above it on its page, or to the last marker of the previous page.
- [ ] **Step 4: Decide.** Go: on at least one model, at least 4 of 5 runs find 95% of leaf labels in order and attach every answer in `aligned.json` to its leaf. No-go: report the numbers and stop; the orchestrator returns to the owner with the option of building spec steps 2 and 3 first.

No commit.

---

### Task 3: Binding types and schema fields

**Files:**
- Create: `lemely/core/binding.py`
- Modify: `lemely/core/schemas.py` (`ExtractedAnswer` near its `extraction_agreement` field; `ExtractedAnswers:591`; `AIMarkResponse:708`; `CorrectedQuestion:305`; `CorrectionResult:469`)
- Test: `tests/test_binding_types.py`

**Interfaces:**
- Produces, in `lemely/core/binding.py` (all `StrictModel` or `Literal`):
  - `BindingSource = Literal["position", "label"]`
  - `BindingStatus = Literal["verified", "unverified", "unbound"]`
  - `BindingVerdict = Literal["pass", "retry", "hold"]`
  - `CheckId = Literal["G1", "G2", "G5", "G6", "G7", "G8", "G9"]`
  - `BindingCheck(id: CheckId, passed: bool, scope: Literal["paper", "question"], question_ids: list[str] = [], detail: str)`
  - `BindingReport(binder: BindingSource, checks: list[BindingCheck], verdict: BindingVerdict, retried: bool = False, model: str | None = None)`
  - `LabelMarker(page: int, top: int, text: str, kind: Literal["printed", "handwritten"])`
  - `ReadAnswer(page: int, box: list[int], answer: str, working_out: str | None, confidence: float)`
- Produces, in `lemely/core/schemas.py`:
  - `ExtractedAnswer.binding_source: BindingSource | None = None`, `.binding_status: BindingStatus | None = None`, `.label_seen: str | None = None`
  - `ExtractedAnswers.binding: BindingReport | None = None`, `.unbound_answers: list[ReadAnswer] = []`
  - `AIMarkResponse.addresses_question: Literal["yes", "no", "unclear"] = "unclear"`
  - `CorrectedQuestion.addresses_question: Literal["yes", "no", "unclear"] | None = None`
  - `CorrectionResult.binding: BindingReport | None = None`

- [ ] **Step 1: Write the failing tests.** `test_new_fields_default_to_none_so_stored_documents_still_load` (every fixture from Task 1 validates unchanged); `test_binding_report_round_trips_through_json`; `test_check_id_rejects_unknown_ids`; `test_addresses_question_defaults_to_unclear_on_a_reply_without_it`.
- [ ] **Step 2: Run.** `pytest tests/test_binding_types.py -q`. Expected: import error.
- [ ] **Step 3: Implement** the types and fields exactly as listed. Docstrings on the three `ExtractedAnswer` fields say what each means and that `confidence` is unrelated.
- [ ] **Step 4: Run** `pytest tests/test_binding_types.py tests/test_binding_fixtures.py tests/test_answer_extraction.py -q`. Expected: all pass. `tests/test_answer_extraction.py` pins the wire schema sent to the model; it must be unchanged, because `_RawExtractedAnswer` is a separate class.
- [ ] **Step 5: Commit.** `feat(core): binding types and binding fields on extraction and correction records`.

---

### Task 4: Expected label sequence, label parsing, alignment

**Files:**
- Create: `lemely/core/label_sequence.py`
- Test: `tests/test_label_sequence.py`

**Interfaces:**
- Consumes: `lemely.core.loose_schemas.MarkScheme.all_questions_flat()`; `LabelMarker`.
- Produces:
  - `LabelStep(level: Literal["number", "letter", "roman"], token: str)`
  - `expected_steps(mark_scheme: MarkScheme) -> list[tuple[LabelStep, str | None]]`: the label steps a reader meets walking the paper, each paired with the leaf id it completes or `None` for a container. For `1a_i, 1a_ii, 1b` it yields `number 1`, `letter a`, `roman i -> 1a_i`, `roman ii -> 1a_ii`, `letter b -> 1b`.
  - `parse_marker(text: str) -> list[LabelStep]`: `"(a)"` gives one step; `"Q3 b ii"` gives three; `"1."` and `"2"` give a number step; text that is not a label gives `[]`. Roman numerals are tried before single letters, so `"(i)"`, `"(v)"` and `"(x)"` are romans.
  - `AlignedLeaf(question_id: str, page: int, top: int, label_seen: str)`
  - `align(markers: list[LabelMarker], mark_scheme: MarkScheme) -> tuple[list[AlignedLeaf], list[str], list[LabelMarker]]`: aligned leaves in reading order, ids of leaves with no aligned label, and markers that matched nothing.

Behaviour of `align`:
- Markers are ordered by `(page, top)`. Their steps are matched to `expected_steps` as a longest common subsequence, so an extra or missing marker costs only its own leaf.
- A number step that the expected sequence does not have at that point, sitting under an aligned leaf with no children, is a numbered answer line. It is dropped from the stream, never matched forward. This is the Q1(a)(i) case.
- An ambiguous letter that is also a roman (`i`, `v`, `x`, `c`, `d`, `l`, `m`) is resolved by which reading keeps the alignment longer.
- A leaf is aligned only when its whole path is: `(ii)` aligns to `1a_ii` only if a `1` and an `(a)` aligned before it.

- [ ] **Step 1: Write the failing tests.** `test_expected_steps_for_the_0625_w24_41_scheme` (first eight steps as above; 43 leaf-completing steps in total); `test_parse_marker_table` (at least: `(a)`, `(ii)`, `Q3 b ii`, `3(b)(ii)`, `1.`, `ii)`, `iv`, `Fig. 1.2` gives `[]`, `[2]` gives `[]`); `test_roman_is_tried_before_letter`; `test_align_clean_stream_binds_every_leaf`; `test_numbered_lines_inside_a_leaf_do_not_consume_the_next_leaf` (stream `1,(a),(i),1.,2.,(ii),(b)` aligns `1a_i`, `1a_ii`, `1b`); `test_a_missing_marker_costs_only_its_leaf`; `test_an_invented_marker_is_returned_as_unmatched`; `test_leaf_needs_its_whole_path`; `test_question_number_printed_on_an_earlier_page_carries_down`.
- [ ] **Step 2: Run.** `pytest tests/test_label_sequence.py -q`. Expected: import error.
- [ ] **Step 3: Implement.** Pure functions, no I/O. Match the comment density of `lemely/core/text_agreement.py`.
- [ ] **Step 4: Run.** Expected: all pass.
- [ ] **Step 5: Commit.** `feat(core): expected label sequence and alignment of seen question labels`.

---

### Task 5: Expected shape and expected values

**Files:**
- Create: `lemely/core/binding_expect.py`
- Test: `tests/test_binding_expect.py`

**Interfaces:**
- Consumes: `lemely.core.loose_schemas.Question` (`answer_points[*].point`, `.math_mark_type`, `.calculated_answer`, `.tolerance`); `lemely.core.equivalence.equivalent(a, b, *, tolerance=…) -> Verdict` and `VerdictKind`.
- Produces:
  - `Shape = Literal["number", "text", "drawing", "unknown"]`
  - `expected_shape(question: Question) -> Shape`
  - `expected_numeric_values(question: Question) -> list[str]`: the final-answer values of the leaf, units stripped; `[]` when the leaf has none.
  - `answer_shape(answer: str) -> Shape`
  - `matches_expected(answer: str, question: Question) -> bool`: true when `answer` holds a value `equivalent` to one of `expected_numeric_values(question)`.

Behaviour:
- Final-answer points are those with `math_mark_type` `A` or `B` whose text starts with a number, after `OR` alternatives are split. Method points (`C`, `M`) are ignored: `k = F / x OR 5.6 / 20` is not an expected value. `calculated_answer` is used when set.
- `43 cm AND 63 cm` yields `["43", "63"]`. `1.8 × 105 kg m / s` yields `["1.8e5"]`: a mantissa followed by `× 10` and a run of digits is standard form with a lost superscript. `3.2(0) m / s2` yields `["3.2"]`.
- A match counts only as `VerdictKind.EQUAL_PROVEN` or, for plain decimals, equality within 2% relative tolerance.
- `expected_shape` is `drawing` when the leaf has `drawing_criteria` or `plot_requirements`, `number` when `expected_numeric_values` is non-empty, `text` when every point is prose, else `unknown`.
- `answer_shape`: `number` when the text is a value with an optional unit and at most three other words; `drawing` when it begins with `[` or names a drawing (`diagram`, `drawn`, `field lines`); else `text`.

- [ ] **Step 1: Write the failing tests.** `test_expected_values_table_for_0625_w24_41` (`1a_i` gives `43, 63`; `1a_ii` gives `20`; `1b` gives `0.28`; `1c_i` gives `4.9`; `1c_ii` gives `3.2`; `2a_i` gives `1.8e5`; `2a_iii` gives `420`; `3b_ii` gives `2.2e7`; `2a_ii` gives `[]`); `test_method_points_are_not_expected_values`; `test_matches_expected_accepts_rounding` (`"180,000kg m/s"` matches `2a_i`; `"422.5 m"` does not match `2a_iii`'s `420` at 2% and is reported as no match); `test_answer_shape_table`; `test_expected_shape_table`.
- [ ] **Step 2: Run.** `pytest tests/test_binding_expect.py -q`. Expected: import error.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: all pass.
- [ ] **Step 5: Commit.** `feat(core): expected shape and expected values of a mark scheme leaf`.

---

### Task 6: Gate checks and verdict

**Files:**
- Create: `lemely/core/binding_gate.py`
- Test: `tests/test_binding_gate.py`

**Interfaces:**
- Consumes: `BindingCheck`, `BindingReport`, `BindingVerdict` (Task 3); `expected_shape`, `answer_shape`, `matches_expected` (Task 5); `ExtractedAnswers`, `CorrectionResult`, `MarkScheme`.
- Produces:
  - `GateThresholds(shape_mismatch_rate: float = 0.25, shift_min_matches: int = 3, off_topic_count: int = 4, off_topic_run: int = 3, second_read_disagreement_rate: float = 0.10)`, a frozen dataclass. Task 9 replaces these defaults with measured values.
  - `check_unknown_ids(extracted, mark_scheme) -> BindingCheck` (G1)
  - `check_duplicate_ids(extracted) -> BindingCheck` (G2)
  - `check_label_coverage(extracted, mark_scheme, unaligned_ids: list[str], unmatched_markers: int) -> BindingCheck` (G5)
  - `check_shape(extracted, mark_scheme, thresholds) -> BindingCheck` (G6)
  - `check_shift(extracted, mark_scheme, thresholds) -> list[BindingCheck]` (G7; one paper-scope check, plus one question-scope check when single leaves are affected)
  - `check_off_topic(correction: CorrectionResult, thresholds) -> BindingCheck` (G8)
  - `check_second_read(first: ExtractedAnswers, second: ExtractedAnswers, thresholds) -> BindingCheck` (G9)
  - `verdict(checks: list[BindingCheck], *, retried: bool) -> BindingVerdict`

Behaviour:
- G1 fails at paper scope when any answer id is absent from the leaf ids.
- G2 fails at paper scope when an id occurs twice.
- G5 fails at question scope for leaves in `unaligned_ids` that have a non-blank answer nearby; it fails at paper scope when more than 10% of leaves are unaligned or any marker matched nothing.
- G6 counts leaves whose `answer_shape` contradicts `expected_shape` (`unknown` never contradicts) and fails at paper scope when the rate over shaped leaves exceeds `shape_mismatch_rate`.
- G7 works over leaves in manifest order. For each answered leaf it records whether the answer `matches_expected` its own leaf, the previous leaf, or the next leaf. A leaf "points away" when it matches a neighbour and not itself. The check fails at paper scope when at least `shift_min_matches` leaves point the same way and outnumber the leaves matching themselves within the span they cover. Leaves that point away without reaching that count fail at question scope, listing their ids.
- G8 fails at paper scope when `addresses_question == "no"` on at least `off_topic_count` questions or on `off_topic_run` consecutive leaves; below that it fails at question scope for those leaves.
- G9 pairs answers of the two reads by id and compares text with `lemely.core.text_agreement.text_agreement`. An id disagrees when agreement is below 0.8 while the second read's text agrees at 0.8 or more with the first read's text for a different id. It fails at paper scope above `second_read_disagreement_rate`, else at question scope for the disagreeing ids.
- `verdict`: `pass` when no paper-scope check failed; otherwise `retry` when `retried` is false and `hold` when it is true. Question-scope failures never change the verdict.

- [ ] **Step 1: Write the failing tests.** Fixture-driven first:
  - `test_g7_fires_at_paper_scope_on_every_full_shift` (the four `full_shift_*` fixtures)
  - `test_g7_flags_the_shifted_leaves_of_a_partial_shift` (`partial_a`, `partial_b`: question scope, ids include `1b`, `1c_i`, `1c_ii`)
  - `test_g1_fires_on_invented_ids` (`chaotic`, `partial_b`)
  - `test_g2_fires_on_duplicate_ids` (`chaotic`, `partial_a`)
  - `test_every_misbound_fixture_fails_at_least_one_check`
  - `test_aligned_fixture_passes_g1_g2_g6_g7`
  
  Then unit tests on small hand-built inputs: `test_g6_ignores_unknown_shapes`; `test_g7_needs_more_shifted_than_self_matching_leaves`; `test_g7_is_silent_when_a_student_is_simply_wrong`; `test_g8_counts_a_run_of_three`; `test_g9_detects_text_agreeing_under_a_different_id`; `test_verdict_pass_retry_hold`; `test_question_scope_failures_do_not_hold_the_paper`.
- [ ] **Step 2: Run.** `pytest tests/test_binding_gate.py -q`. Expected: import error.
- [ ] **Step 3: Implement.** Pure functions. Each `BindingCheck.detail` names the evidence in one sentence, for example `"7 answers equal the previous question's expected value: 1b, 1c_i, 1c_ii, 2a_ii, …"`.
- [ ] **Step 4: Run.** Expected: all pass. If a fixture test fails because the check's rule is too strict or too loose, change the rule and its docstring, not the fixture.
- [ ] **Step 5: Commit.** `feat(core): binding gate checks G1, G2, G5-G9 and verdict`.

---

### Task 7: Label binder

Blocked on a "go" from Task 2.

**Files:**
- Create: `lemely/io/prompts/label_binding.py`, `lemely/io/binding/__init__.py`, `lemely/io/binding/label_binder.py`
- Modify: `lemely/io/prompts/__init__.py` (export, following the existing entries)
- Test: `tests/test_label_binder.py`

**Interfaces:**
- Consumes: `GeminiClient.generate_structured(system_prompt=…, user_prompt=…, image_parts=…, image_uploads=…, media_resolution=…, response_schema=…, prompt_version=…, extra_cache_key=…, task_tag=…)` as called at `lemely/io/answer_extraction.py:988`; `RasterisedPage`; `align` (Task 4); `LabelMarker`, `ReadAnswer` (Task 3); `_coerce_page`, `_coerce_box`, `_coerce_answer_text`, `_coerce_confidence` from `lemely/io/answer_extraction.py`.
- Produces:
  - `lemely.io.prompts.label_binding.VERSION = "1"`, `LABEL_BINDING_SYSTEM_PROMPT`, `build_label_binding_user_prompt(mark_scheme: MarkScheme, *, page_count: int) -> str`
  - `TwoStreamRead(markers: list[LabelMarker], answers: list[ReadAnswer], drops: dict[str, int])`
  - `LabelBinder(client: GeminiClient)` with `read(pages: list[RasterisedPage], mark_scheme: MarkScheme, *, uploads, model: str | None = None, media_resolution: str = "high", extra_cache_key: str) -> TwoStreamRead`
  - `bind_by_markers(read: TwoStreamRead, mark_scheme: MarkScheme) -> BoundRead`
  - `BoundRead(answers: list[ExtractedAnswer], unbound: list[ReadAnswer], unaligned_ids: list[str], unmatched_markers: int)`

Behaviour:
- The prompt is the one measured in Task 2, moved into the module unchanged. The user prompt lists, per leaf, the printed label (`1(a)(i)`), marks and expected shape, and tells the model this list is for orientation only and that no id may appear in the reply. No mark-scheme point text appears in it.
- The wire schema is declared the way `_RawExtractedAnswer` does it: lenient `Any` fields for parsing, a strict typed schema sent to the model, one malformed element dropped and counted in `drops` without losing the rest.
- `bind_by_markers` calls `align`, then attaches each `ReadAnswer` to the aligned leaf with the greatest `(page, top)` not below the answer's own `(page, box top)`. Several answers attached to one leaf are joined in reading order: answers with `"; "`, workings with a newline; the box becomes their union on the first answer's page; confidence is the minimum.
- Every bound answer gets `binding_source="label"`, `binding_status="verified"`, and `label_seen` set to the quoted path (`"1 (a) (i)"`). An answer above the first aligned leaf, or attached to an unaligned stretch, goes to `unbound`.
- `task_tag="extraction"` so the existing model and thinking settings apply; `model` overrides it for the retry.

- [ ] **Step 1: Write the failing tests**, with a fake client in the style of `tests/test_answer_extraction.py`: `test_two_lines_under_one_label_become_one_answer` (markers `1,(a),(i),(ii)`; answers `43cm`, `63cm` under `(i)`, `20cm` under `(ii)`; result `1a_i == "43cm; 63cm"`, `1a_ii == "20cm"`); `test_answer_on_the_next_page_attaches_to_the_last_label_of_the_previous_page`; `test_answer_before_any_label_is_unbound`; `test_blank_leaf_gets_no_answer_and_shifts_nothing`; `test_a_malformed_marker_is_dropped_and_counted`; `test_the_reply_schema_has_no_question_id_property`; `test_user_prompt_contains_no_mark_scheme_point_text` (asserts none of the scheme's `answer_points[*].point` strings occur in the prompt for `corpus/mark-schemes/0625_w24_ms_41.json`); `test_bound_answers_carry_label_source_and_label_seen`.
- [ ] **Step 2: Run.** `pytest tests/test_label_binder.py -q`. Expected: import error.
- [ ] **Step 3: Implement** (prompt and schema text by opus, the rest by sonnet).
- [ ] **Step 4: Run** `pytest tests/test_label_binder.py tests/test_label_sequence.py -q`. Expected: all pass.
- [ ] **Step 5: Commit.** `feat(io): label binder that reads labels and answers as two streams and binds in code`.

---

### Task 8: Marker reports whether an answer addresses its question

**Files:**
- Modify: `lemely/io/prompts/correction_ai.py` (`VERSION = "5"` at line 7; `MARKER_SYSTEM_PROMPT` at line 9), `lemely/io/correction_ai.py` (`_build_ai_corrected:1370`, the verdict-path builder it dispatches to, `correct_paper:2255`)
- Test: `tests/test_correction_ai.py` (add), `tests/test_correction_off_topic.py` (new)

**Interfaces:**
- Consumes: `AIMarkResponse.addresses_question`, `CorrectedQuestion.addresses_question`, `CorrectionResult.binding` (Task 3); `check_off_topic`, `verdict`, `GateThresholds` (Task 6); `ExtractedAnswers.binding`.
- Produces:
  - `lemely.io.prompts.correction_ai.VERSION = "6"`
  - `correct_paper(...)` returns a `CorrectionResult` whose `binding` is the extraction's report with the G8 check appended and the verdict recomputed. When `extracted_answers` is a plain mapping, or carries no report, `binding` holds G8 alone with `binder="label"` and `retried=True`, so a paper-scope G8 failure yields `hold`.

Behaviour:
- The system prompt gains one paragraph: set `addresses_question` to `no` when the response is clearly an answer to a different question (a definition where a calculation is asked, a value with the wrong quantity or unit, an explanation of another topic); `yes` when it attempts this question, right or wrong; `unclear` when blank or too short to tell. It states that this does not change the mark.
- Both builders copy the field to `CorrectedQuestion`. MCQ, blank, dropped and missing paths leave it `None`.
- A question-scope G8 failure sets `needs_teacher_review=True` on those questions and appends `"binding unverified: answer appears to address a different question"` to `review_reason`. `awarded_marks` is unchanged.

- [ ] **Step 1: Write the failing tests.** `test_marker_prompt_version_is_6`; `test_ai_corrected_carries_addresses_question`; `test_mcq_and_blank_paths_leave_addresses_question_none`; `test_run_of_off_topic_answers_sets_paper_verdict_hold`; `test_single_off_topic_answer_sends_only_that_question_to_review`; `test_marks_are_not_changed_by_addresses_question`; `test_plain_mapping_answers_still_get_a_g8_only_report`.
- [ ] **Step 2: Run.** `pytest tests/test_correction_off_topic.py -q`. Expected: fails.
- [ ] **Step 3: Implement** (prompt paragraph by opus).
- [ ] **Step 4: Run** `pytest tests/test_correction_off_topic.py tests/test_correction_ai.py -q`. Expected: all pass. Tests in `tests/test_correction_ai.py` that pin the prompt version or the reply schema are updated in the same commit, each with the reason in its diff.
- [ ] **Step 5: Commit.** `feat(correction_ai): marker reports whether an answer addresses its question (G8)`.

---

### Task 9: Misbinding transforms and threshold sweep

**Files:**
- Modify: `lemely/accuracy/metamorphic.py`
- Create: `tests/test_binding_gate_sweep.py`, `scripts/sweep_binding_gate.py`
- Modify: `lemely/core/binding_gate.py` (defaults of `GateThresholds` only)

**Interfaces:**
- Consumes: `load_golden_cases(_GOLDEN_DIR)` exactly as `tests/test_golden_corpus.py` imports and calls it (each case directory under `tests/golden/` holds `answers.json` and `mark_scheme.json`); the checks from Task 6.
- Produces, in `lemely/accuracy/metamorphic.py`:
  - `shift_answers(answers: Mapping[str, str], order: list[str], *, start: int, by: int) -> dict[str, str]`
  - `split_answer(answers: Mapping[str, str], order: list[str], *, at: int) -> dict[str, str]` (the answer at `at` is cut in two and everything after moves one leaf later; the last answer falls off)
  - `drop_answer(answers: Mapping[str, str], order: list[str], *, at: int) -> dict[str, str]` (everything after `at` moves one leaf earlier)
  - `scripts/sweep_binding_gate.py`: prints, per threshold setting, detection rate over transformed sets affecting three or more questions and false-fire rate over untransformed sets.

- [ ] **Step 1: Write the failing tests.** `test_shift_split_drop_move_the_expected_answers` (table on a six-leaf example); `test_gate_detects_at_least_99_percent_of_misbindings_affecting_three_or_more_questions`; `test_gate_holds_at_most_2_percent_of_aligned_papers`. The two rate tests use every golden case whose name ends in `_correct` or `_partial` and whose scheme has at least one non-MCQ leaf, three seeded start positions per transform, `random.Random(20261009)`, and the pre-marking checks G1, G2, G6, G7 only. MCQ leaves are excluded from G7: with four options, a letter matches a neighbour's key by chance one time in four.
- [ ] **Step 2: Run.** `pytest tests/test_binding_gate_sweep.py -q`. Expected: transforms missing.
- [ ] **Step 3: Implement the transforms; run the sweep script; set `GateThresholds` defaults** to the setting that meets both targets with the widest margin. Record the sweep table in the commit body.
- [ ] **Step 4: Run** `pytest tests/test_binding_gate_sweep.py tests/test_binding_gate.py tests/test_metamorphic.py -q`. Expected: all pass. If no setting meets both targets, stop and report the table: papers with fewer than three numeric leaves may need G8 or G9 to reach the target, and that is a finding for the owner, not something to tune away.
- [ ] **Step 5: Commit.** `test(accuracy): misbinding transforms and measured binding gate thresholds`.

---

### Task 10: Orchestration in the extractor

**Files:**
- Modify: `lemely/runtime/config.py` (new `BindingSettings`, attached to `Settings` as `binding`), `lemely/runtime/events.py`, `lemely/io/answer_extraction.py` (`_extract:942`), `lemely.toml.example`
- Test: `tests/test_extraction_binding.py`

**Interfaces:**
- Consumes: `LabelBinder`, `bind_by_markers` (Task 7); all pre-marking checks and `verdict` (Task 6); `BindingReport`.
- Produces:
  - `BindingSettings(binder: Literal["label", "legacy"] = "label", gate: Literal["enforce", "observe", "off"] = "enforce", retry_model: str = "gemini-3.8-flash", retry_thinking_level: ThinkingLevel = "medium", second_read: bool = True)`
  - `EventType.BINDING_GATE_RESULT = "binding_gate_result"`, published with `binder`, `verdict`, `retried`, `failed_checks` (list of ids), `unbound`.
  - `GeminiAnswerExtractor.__call__` returns `ExtractedAnswers` with `binding` set whenever `gate != "off"`.

Behaviour:
- `binder="label"`: read with `LabelBinder` on the extraction model, bind, run G1, G2, G5, G6, G7. With `second_read` on, read again on `retry_model` and run G9; the second read doubles as the retry candidate.
- Verdict `pass`: return the first read's answers. Verdict `retry`: evaluate the second read with the same checks and `retried=True`; return it when it passes, else return the first read with verdict `hold`.
- `binder="legacy"`: the current single call is unchanged; the gate runs G1, G2, G6, G7 on its output, and a paper-scope failure triggers one retry on `retry_model` through the same legacy call.
- `gate="observe"`: checks run and the event is published, but the verdict written to the report is always `pass`. `gate="off"`: no checks, `binding=None`.
- Question-scope failures set `binding_status="unverified"` on those answers.
- Calibration, crop re-reads, the progress events and `normalize_extracted_answers` stay as they are and run after binding. `CostCeilingError` propagates from either read exactly as it does from the re-read stage today.

- [ ] **Step 1: Write the failing tests** with fake clients: `test_clean_read_passes_and_carries_a_report`; `test_shifted_first_read_and_clean_second_read_returns_the_second`; `test_two_bad_reads_return_verdict_hold`; `test_observe_mode_never_holds_but_publishes_the_event`; `test_gate_off_leaves_binding_none`; `test_legacy_binder_output_is_gated` (feed `full_shift_lite.json` as the legacy reply; verdict is `retry`, then `hold`); `test_question_scope_failure_marks_answers_unverified`; `test_cost_ceiling_in_second_read_propagates`; `test_binding_gate_result_event_fields`.
- [ ] **Step 2: Run.** `pytest tests/test_extraction_binding.py -q`. Expected: fails.
- [ ] **Step 3: Implement.** Keep `_extract` readable: move the new flow into a helper in `lemely/io/binding/orchestrate.py` (`run_binding(client, pages, mark_scheme, uploads, settings) -> tuple[list[ExtractedAnswer], BindingReport, list[ReadAnswer]]`) and call it from `_extract`.
- [ ] **Step 4: Run** `pytest tests/test_extraction_binding.py tests/test_answer_extraction.py tests/test_second_read.py tests/test_reread.py -q`. Expected: all pass. Existing extraction tests that assume one model call set `binder="legacy"`, `gate="off"` in their settings fixture; none is deleted.
- [ ] **Step 5: Commit.** `feat(extraction): bind by labels, gate before marking, retry once on a stronger model`.

---

### Task 11: Fail-closed handling of a held paper

**Files:**
- Modify: `lemely/web/services/grading.py` (`grade_paper:56`), `lemely/web/routers/student.py` (the marking job, lines 1060-1240: `extract_answers` at 1067, `grade_paper` at 1068, the failure branches at 1231-1240), `lemely/web/routers/teacher.py` (the console marking job, lines 595-634: `extract_answers` at 604, `grade_paper` at 613, `repo.fail(paper_id, …)` at 634; and `regrade_paper` at 1006)
- Test: `tests/test_web_student.py` (add), `tests/test_grading_binding.py` (new)

**Interfaces:**
- Consumes: `CorrectionResult.binding.verdict` (Task 8).
- Produces: `lemely.web.services.grading.BindingHeldError(LemelyError)` with `reasons: list[str]`, raised by `grade_paper` when the verdict is `hold`, before any history record is written.

Behaviour:
- Student job: the existing `except Exception` branch already publishes an `ERROR` frame and sets `UploadStatus.failed`. `BindingHeldError` gets its own branch above it with the message `"We could not match some answers to their questions, so this paper has not been marked. Please check every page is included and in order, then upload it again."` No attempt is persisted, no XP is awarded, no `grade_ready` notification is sent.
- Teacher console job and `regrade_paper`: `repo.fail(paper_id, <the same sentence>)`, in a `BindingHeldError` branch above the generic one, so the console does not prefix it with `Grading failed:`.
- A structured log line `binding_held` carries the upload id and the failed check ids, so held papers can be counted before 1B adds a queue.

- [ ] **Step 1: Write the failing tests.** `test_grade_paper_raises_binding_held_on_hold_verdict`; `test_grade_paper_records_no_history_when_held`; `test_student_upload_held_sets_failed_and_sends_the_binding_message`; `test_held_paper_awards_no_xp_and_sends_no_grade_ready`; `test_teacher_console_held_paper_is_failed_with_the_binding_message`.
- [ ] **Step 2: Run** `pytest tests/test_grading_binding.py -q`. Expected: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_grading_binding.py tests/test_web_student.py -q`. Expected: all pass.
- [ ] **Step 5: Commit.** `feat(web): a paper held by the binding gate fails closed and is never published`.

---

### Task 12: Audit command for stored attempts

**Files:**
- Modify: `lemely/app/cli.py`
- Create: `lemely/db/binding_audit.py`
- Test: `tests/test_binding_audit.py`

**Interfaces:**
- Consumes: `QuestionResult.question_id`, `.student_answer`, `.attempt_id` (`lemely/db/models/attempts.py`); `SchemeCorpusRepository.find_for(metadata: ExamMetadata) -> MarkScheme | None` (`lemely/db/scheme_corpus_repo.py:215`); `check_shape`, `check_shift` (Task 6).
- Produces:
  - `audit_attempt(question_results: Sequence[QuestionResult], mark_scheme: MarkScheme) -> list[BindingCheck]`
  - CLI `lemely audit-bindings [--since YYYY-MM-DD] [--limit N]`: one line per suspect attempt (`attempt id, user id, paper, failed checks, detail`), then a count. With `--json`, a list of objects. Read-only.

Stored rows are already keyed by manifest id, so G1 and G2 cannot fire on them; the audit runs G6 and G7.

- [ ] **Step 1: Write the failing tests.** `test_audit_flags_a_shifted_attempt` (rows built from `full_shift_lite.json`); `test_audit_passes_an_aligned_attempt` (rows from `aligned.json`); `test_audit_skips_attempts_whose_scheme_cannot_be_resolved_and_counts_them`; `test_audit_command_is_read_only` (no row is modified; assert on a session spy).
- [ ] **Step 2: Run** `pytest tests/test_binding_audit.py -q`. Expected: fails.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest tests/test_binding_audit.py tests/test_cli.py -q`. Expected: all pass.
- [ ] **Step 5: Commit.** `feat(cli): audit-bindings lists stored attempts that look misbound`.

---

### Task 13: Live acceptance on the paper that failed

No product code. Run by `accuracy-measurer`.

- [ ] **Step 1:** Ten fresh end-to-end runs (extract, then `correct_paper`) on `.omc/research/p4n24-shift/student.pdf` with defaults from this branch, cache bypassed, `PYTHONPATH=$(pwd)`, one run at a time. Print `lemely.__file__` at the start of each.
- [ ] **Step 2:** Per run record: verdict, failed checks, whether a retry ran, binding accuracy against `tests/fixtures/binding/0625_w24_41/aligned.json`, total mark when published, wall-clock time, cost from the run's ledger.
- [ ] **Step 3:** Acceptance, from the spec: no published run contains a misbound answer; every published total is within 5 marks of 66. Also report the hold rate; more than 2 held runs in 10 is a finding to bring to the owner before 1B, not a failure of this plan.
- [ ] **Step 4:** Report the table to the orchestrator. If production-size uploads stall, as they did on 2026-10-09, say so and report which render size was used.

---

### Task 14: Gate sweep

Last, on the final tree. A later fix commit voids it.

- [ ] `ruff check .`
- [ ] `ruff format --check .` (check mode, so an autofix cannot hide a failure)
- [ ] `mypy lemely`
- [ ] `pyright lemely`. If it reports unresolved imports of modules that exist in this tree, the shared venv's editable path is stale: prove the tree with a temporary config that copies `[tool.pyright]` and adds `extraPaths` for this worktree, and report both results.
- [ ] `lint-imports`
- [ ] `python scripts/check_review_rate_gate.py`
- [ ] `pytest` on every test file this plan created or modified, in one invocation.
- [ ] Search the diff for `TODO`, `FIXME`, `skip(`, `xfail`, `.only`. Any hit is resolved or reported.
- [ ] `accuracy-reviewer` reviews the combined diff at the branch's head SHA; `verifier` confirms each task's tests exist and fail when the behaviour they guard is removed.

---

## Order and parallelism

- Task 1 first. Task 2 next; it gates Task 7.
- Tasks 3, then 4 and 5 in parallel (disjoint files), then 6.
- Tasks 7 and 8 in parallel after 6 (disjoint files: `lemely/io/binding/*` and `lemely/io/prompts/label_binding.py` for 7; `lemely/io/correction_ai.py` and `lemely/io/prompts/correction_ai.py` for 8).
- Task 9 after 6. Task 10 after 7 and 9. Task 11 after 8 and 10. Task 12 after 6, in parallel with 10.
- Tasks 13 and 14 last, in that order.

## Spec coverage

| Spec item | Task |
|---|---|
| Model never has the final say on an id | 4, 7, 10 |
| Reader never sees expected answers | 7 (test) |
| Binding source, evidence and status on each answer | 3, 7, 10 |
| G1, G2, G5 | 6 |
| G6, G7 | 5, 6 |
| G8 | 8 |
| G9 | 6, 10 |
| Retry once on stronger settings, then hold | 10, 11 |
| Thresholds from a synthetic sweep, 99% and 2% targets | 9 |
| `BINDING_GATE_RESULT` event | 10 |
| Failing-case fixtures | 1, 6 |
| Audit of existing results | 12 |
| Live acceptance | 13 |
| `held` status, review reason, result `state`, screens | plan 1B |
| `binding_accuracy` harness metric | later plan, with the question-paper corpus; Task 13 measures it by hand |
| G3, G4, layout, page map, position binder | spec steps 2 and 3 |
