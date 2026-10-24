# Sub-project C: Claude Lever Screens and Default Flip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a frozen per-leaf reference for the five local real scripts, extend the cost-ladder harness with a real split and three judges, fix what the diagnosis proves broken, screen every Claude lever one at a time, and flip every task tag to Claude only when `judge_flip` passes against a Gemini rung.

**Architecture:** A pure reference module (`lemely/accuracy/reference.py`) and a thin Opus-backed builder script produce `BUILD/accuracy-runs/claude-c-reference/` (uncommitted) and its `manifest.json`. The cost ladder gains `real_split.py` (frozen scripts, production-path marking, per-leaf scoring that counts drops as 0), a `run_real` pass in `runner.py`, real fields on `RunSummary`, and two new judges in `gate.py`. The existing dev path (`run_config`) is untouched; `run_baseline` and `run_screen` take `split`, `repeats` and a judge kind. P2 diagnoses before it fixes. P3 adds four lever switches (effort `none`, cache-effort relaxation, no borderline, Sonnet adjudication) and runs the screens from the main session. P4 flips the defaults in a separate PR.

**Tech Stack:** Python 3.13, pydantic v2 settings, anthropic SDK (`>=1.15,<2`), google-genai, Pillow, pypdfium2, structlog, pytest.

**Spec:** `docs/superpowers/specs/2026-10-24-claude-screens-flip-design.md` (the "spec" below). Phases P0 to P4 map to tasks 1 to 31.

## Global Constraints

Copied verbatim from the spec:

- At most $0.10 per script, for every script in the real set, not just the mean.
- Anthropic spend is capped at $40 in total, tracked in `BUILD/accuracy-runs/cost-ladder-spend.json` ($0.6396 used at the start). C's estimate is $15 to $20.
- The default Gemini path stays byte-identical until P4: `tests/test_llm_golden.py` passes, and `tests/fixtures/llm_golden/` is never regenerated.
- Student data is never committed: reference files, extracted answers, per-leaf marks, records, events and caches. Only counts go into committed reports.
- No student data goes through the Message Batches API.
- API keys are read inside scripts from `~/.config/lemely/{anthropic,gemini}_key`, never on a command line or in an env assignment.
- Signed, path-scoped commits; pre-commit before each commit; no full test suite locally.
- Every new check has a test proven red against a failing input.

Repo and session rules (every task inherits these):

- Branch `feat/claude-screens-flip`, main tree. No worktree, no branch switch, no stash. P4 (Tasks 29 to 31) is the only exception: the main session branches `feat/claude-default-flip` off this branch's HEAD after the P0 to P3 PR is open.
- Commits: `git commit -S -m "<type>(<scope>): ..." -- <paths>`, with conventional scopes (`accuracy`, `cost_ladder`, `reference`, `anthropic`, `correction`, `binding`, `config`, `gemini`, `cli`, `test`, `docs`). Stage with `git add -- <paths>`. Never `git add -A`, `git add .` or `git add -f`.
- Pre-commit before each commit, on the task's files only (zsh: each path a separate argument): `PATH=$PWD/.venv/bin:$PATH pre-commit run --files <file1> <file2> ...`. The ruff hook autofixes: re-run until it passes with no changes, then `git diff --stat -- <files>` to confirm the tree you commit is the tree you tested.
- Tests: never the full suite locally (no `make test`, no bare `pytest`). Every pytest command has the form `.venv/bin/python -m pytest <files> -q --no-cov -o addopts=""` from the repo root. Each task runs its touched test files, plus `tests/test_llm_golden.py`, plus the source-scanning tests: `.venv/bin/python -m pytest tests/architecture tests/test_binding_expect.py tests/test_include_deleted_scope.py tests/test_marking_options_wiring.py tests/test_label_sequence_faults.py tests/test_pdf_canonical.py tests/test_marker_scored_one_formulation.py tests/test_refusal_reasons.py tests/test_scan_limits.py tests/test_label_sequence.py tests/test_web_shared_constants.py tests/test_script_cost_scope.py -q --no-cov -o addopts=""`. CI's full run is the only judge of green; say so when reporting.
- Never commit `.superpowers/`, `BUILD/accuracy-runs/claude-c-reference/`, any `cache/`, `records*.jsonl`, `escalations.jsonl`, `real_results.json`, `extracted.json`, `correction.json`, `events.jsonl`, or `outputs/`. Committed BUILD files hold counts only (`LADDER.md`, `FLIP.md`, the rung TOMLs).
- Foreign uncommitted files are in the tree: `.claude/settings.json`, `CLAUDE.md`, `BUILD/accuracy-runs/cost-ladder-2026-10-19/SPLIT.md`, `BUILD/accuracy-runs/cost-ladder-spend.json`, and untracked `BUILD/accuracy-runs/claude-e2e*` dirs. Never touch, stage or commit them. The spend ledger is written only by the runner and the reference builder through `SpendLedger`.
- Keys: live scripts read `~/.config/lemely/anthropic_key` and `~/.config/lemely/gemini_key` inside the process (`os.environ.setdefault(..., Path(...).read_text().strip())`) and never print them.
- No Message Batches API anywhere.
- Spend caps: Anthropic $40.00 and Gemini $6.00 combined across every cost-ladder run (`SpendCaps` defaults). At plan time the ledger reads anthropic $0.6396, gemini $3.0617.
- New settings read on a hot path use `is True` / `is not False` / `isinstance(..., dict)`, never truthiness (tests build settings from `MagicMock`).
- Prove every new guard red: each code task has a step that breaks the code on purpose, watches the named test fail, and reverts.
- `graphify-out/graph.json` exists: before the first code search in a task run `graphify query "<question>"`; after a code task, run `graphify update .` (do not commit `graphify-out/` changes unless the repo already tracks them; check `git status --short -- graphify-out` and leave them to the main session).
- Implementers are sonnet subagents; reviewers are opus. Implementers touch only the files their task lists. Tasks marked **MAIN SESSION** are run by the main session, never a subagent.
- Every review also runs `.venv/bin/python -m pytest tests/test_llm_golden.py -q --no-cov -o addopts=""` and checks `git diff --stat -- tests/fixtures/llm_golden` is empty.

---

## Facts this plan relies on

Checked in the code on 2026-10-24 by the planner:

- `GeminiSettings` (`lemely/runtime/config.py:143`) has `extra="forbid"`; `escalation_model` default `gemini-3.8-flash`, `escalation_confidence_threshold` 0.80, `cascade_enabled` False, `review_confidence_threshold_for` {}, `claude_effort_for` {}, `correction_citations` False, `correction_terse_rationale` False. `model_for` maps `correction_borderline` to `correction_model`. `ClaudeEffort = Literal["low","medium","high","xhigh","max"]` (`config.py:120`); the adapter's `Effort` and `EFFORTS` repeat it (`anthropic_adapter.py:136-137`), as does `lemely/io/llm/request.py:15`.
- The adapter always sends `thinking={"type": "adaptive"}` and `output_config.effort` (`anthropic_adapter.py:479-496`). There is no way to turn thinking off today.
- `AICorrector._retry_low_confidence` (`correction_ai.py:608-723`): step 1 (borderline, tag `correction_borderline`) fires when `confidence < escalation_confidence_threshold` and borderline thinking ranks above correction thinking; step 2 (tag `escalation`) fires when confidence is still below the threshold and `(escalation_model, escalation effort)` differs from the last call's `(model, effort)`. With every tag on `claude-haiku-5-5` and `correction_borderline` and `escalation` both resolving to effort `high`, step 2's tuple equals step 1's, so escalation never fires. This is the planner's reading of the 0 escalations in the four E2E runs; Task 15 confirms it with a test.
- `escalate_on_mark_mismatch` and `escalate_on_defaulted_marks` are `DetParserSettings` fields (`config.py:523,528`): they hand a mark scheme from the deterministic parser to the LLM parser. They are not leaf-marking escalation triggers.
- `verdict()` (`lemely/core/binding_gate.py:881`) returns `pass` when no `scope="paper"` check failed. A failed `scope="question"` G5 or G9 leaves the verdict `pass`.
- `_reads_share_a_claude_cache` (`lemely/io/binding/orchestrate.py:535`) requires the same claude model on both binder reads, `"images"` in `claude_cache_for` for both tags, and equal resolved effort.
- The chunked read is built only when `binding.claude_chunked_read is True` (`orchestrate.py:841`); `ChunkedLabelReader.applies` is true for a claude model whose pages are over `claude_image_token_budget` at the floor (`chunked_read.py:148`). `image_fit.fit` already steps the long edge down to the floor. `claude_row(model).tier_threshold_tokens` is 100,000 for `claude-haiku-5-5` and None for Sonnet, Opus, Fable (`lemely/io/llm/pricing.py`).
- `script_cost_scope` is opened only in `lemely/web/routers/student.py:1049` and `teacher.py:580`. `lemely/app/cli.py` `correct_paper_cmd` (line 320) and `extract_answers_cmd` (line 785) and `lemely/app/gradio_app.py:232` do not open it.
- `extract_json` / `_last_object` (`lemely/io/providers/claude_schema.py:242-283`) return None for the whole reply when any `{` or `[` never closes, even a `[` in prose after a complete object.
- `tests/test_llm_golden.py` builds settings with `tests.gemini_fakes.make_settings` (defaults) and drives `GeminiClient` directly; it does not reach `correction_ai`, `answer_extraction` or the binder. It pins records, logs, events, requests and cache keys of those direct calls.
- The cost-ladder runner (`lemely/accuracy/cost_ladder/runner.py`) is dev-only: `run_config` runs `measure_accuracy` over the 12 pinned golden cases (digest `090492b217365de4`). `RunSummary` (`gate.py:16`) has 7 fields; `Verdict` 6.
- The #59 stylus fixtures are committed at `tests/fixtures/handwritten-59/0625_{s25,w24,w25}_qp_42.pdf`; their sha256s equal `output_sha256` in `BUILD/accuracy-runs/handwritten-59/raster-manifest.json`. Schemes: `corpus/mark-schemes/0625_w24_ms_42.json` (parsed); `~/Documents/0625_s25_ms_42.pdf` (det fails, #88) and `~/Documents/0625_w25_ms_42.pdf`. The fixture README says every answer is correct (one teacher solved every question), so these scripts can only catch harsh marking.
- Other inputs: `~/Documents/P4 N24 V1_annotated (NO Corrections).pdf` (0625/41 model input), `~/testing/0625_w24_qp_41-(66..80).pdf` (corrected copy, reference builder only), `~/0625_w24_ms_41.pdf` and `corpus/mark-schemes/0625_w24_ms_41.json`, `~/testing/0625_s23_qp_22-(34..40).pdf` (MCQ model input and truth), `corpus/mark-schemes/0625_s23_ms_22.json`.
- Prior stored outputs for 0625/41: Gemini `BUILD/accuracy-runs/e2e-0625-w24-41-2026-10-19/correction.json`; Claude `BUILD/accuracy-runs/claude-e2e2-0625-w24-41-{enh1,enh2,plain1,plain2}/correction.json` and `extracted.json`.
- The prior cost ladder's dev rungs cost Gemini $0.74 to $0.95 each (`BUILD/accuracy-runs/cost-ladder-2026-10-19/baseline{,_aa}/run_cost.json`). Two fresh Gemini dev runs plus two Gemini real runs would pass the $6 Gemini cap (ledger $3.06), so the Gemini rung reuses the prior ladder's last accepted dev rung (Task 25).
- `lemely.toml.example` must equal `render_example_toml()` (`tests/test_cost_ladder_settings.py::test_example_toml_lists_new_keys`). Regenerate with `.venv/bin/python -c "from pathlib import Path; from lemely.runtime.example_toml import render_example_toml; Path('lemely.toml.example').write_text(render_example_toml(), encoding='utf-8')"`.

To confirm in the step that needs it: whether `thinking={"type": "disabled"}` is accepted together with `output_config.effort` on `claude-haiku-5-5` (Task 19, step 1, via the `claude-api` skill), and whether a binder second read with thinking disabled still reads the first read's image cache (measured by screen a1, Task 26).

## Resolved ambiguities

1. **`run_config` takes `split`.** Realised as `split` on `run_baseline` and `run_screen` plus a new `run_real` in `runner.py`; `run_config` stays the dev-only run it is, so its 60-odd tests stay unchanged.
2. **Every rung runs twice.** Real split: two live runs (`real-1`, `real-2`). Dev split: `run_baseline` already makes two (baseline and A/A); a screen with `repeats=2` runs `<label>` and `<label>-r2` on fresh copies of the frozen baseline cache. Paired dev figures are the mean of the two runs; the mismark set is the union of the two runs' sets (so both sides of a comparison count a part mismarked in either run).
3. **Manifest location.** One manifest, `BUILD/accuracy-runs/claude-c-reference/manifest.json`, one entry per frozen script with the reference, scheme, scan and source sha256s.
4. **Scheme input of a real script.** Frozen as `mark_scheme.json` in the script's reference dir (its sha256 in the manifest), so no rung re-parses a scheme.
5. **"Every real script at most $0.10".** Judged on each script's highest cost over the rung's runs, not the mean.
6. **Cost levers on the real split.** `judge_cost_lever` is the existing `judge` plus three real-split checks: abs_error may not rise by more than the real A/A floor, the mean real cost may not rise, every real script at most $0.10.
7. **`judge_accuracy_lever` review clause.** Implemented literally: "falls by at least the A/A floor" accepts an equal abs_error when the floor is 0, and only then does the 5-point review-rate clause bind (it is exempt whenever abs_error fell).
8. **Escalation triggers.** On the non-cascade path the only escalation trigger is confidence below `escalation_confidence_threshold` after the borderline retry; every escalated leaf is reported with trigger `confidence`. With `cascade_enabled` the trigger is reported as `cascade`. `escalate_on_mark_mismatch` and `escalate_on_defaulted_marks` are mark-scheme parser settings; Task 15 records that.
9. **"CLI and batch paths" for the cost scope.** The CLI `correct-paper` and `extract-answers` commands, the Gradio extraction, and the real-split runner (`mark_real_script`, Task 6). The accuracy harness is not wrapped: it is called with `MagicMock` settings in tests, which the scope's `>` comparison would break.
10. **Lever switches.** a1/a2: a new effort value `none` (thinking disabled). a3: `binding.claude_cache_ignores_effort`. c1: `gemini.correction_borderline_enabled`. c2: `gemini.adjudication_model` (None is off), `adjudication_max_leaves` (3), `adjudication_confidence_threshold` (0.80); adjudication runs inside `correct_paper` when given the scan pages.
11. **Escalation threshold fit target.** `gemini.escalation_confidence_threshold` (the cascade stays off). It also gates the borderline retry; the fit's cost model ignores that and the final rung measures the true cost.
12. **Gemini rung.** Real split: two live Gemini runs. Dev split: the stored summary of the prior ladder's last accepted rung, whose config is today's Gemini default (the Gemini cap leaves no room for two fresh dev runs).
13. **Golden pinning at P4.** `make_settings` in `tests/gemini_fakes.py` pins the pre-flip Gemini model slots, so the golden test and every fake-based test keep the Gemini path; the golden test also asserts it is on Gemini models. The fixture is not touched.

---

## File structure

| Path | Responsibility | Task |
|---|---|---|
| `lemely/accuracy/reference.py` (new) | Reference leaf files, check-first rule, review markdown, override, freeze manifest | 1 |
| `scripts/build_reference.py` (new) | CLI: prepare, mark (Opus), adopt, review-list, crop, override, freeze | 2 |
| `lemely/accuracy/cost_ladder/gate.py` | Real fields on `RunSummary`, `Verdict.notes`, `judge_cost_lever`, `judge_accuracy_lever`, `judge_flip` | 5 |
| `lemely/accuracy/cost_ladder/real_split.py` (new) | `RealScript`, manifest loader with sha check, `mark_real_script`, per-leaf scoring, pair aggregation, results I/O | 6 |
| `lemely/accuracy/cost_ladder/runner.py` | `run_real`, real fields in summaries, `split`/`repeats`/judge on `run_baseline` and `run_screen`, `run_reference_rung`, `flip_verdict` | 7 |
| `lemely/accuracy/cost_ladder/report.py` | Real and escalation columns in `LADDER.md`, `FLIP.md` | 8 |
| `scripts/cost_ladder.py` | CLI: `--config`, `--split`, `--repeats`, `--judge`, `reference-rung`, `judge-flip`, key loading | 9 |
| `lemely/accuracy/threshold_fit.py` (new) | Pure review-threshold fit (moved), recall-based pick, escalation-threshold fit | 10 |
| `scripts/fit_review_threshold.py` | CLI only; `--real` and `--escalation` modes | 10 |
| `lemely/io/answer_extraction.py`, `lemely/io/llm/claude_provider.py`, `lemely/io/scan_metadata.py` | Stage-timing log lines | 13 |
| `lemely/io/binding/orchestrate.py`, `lemely/io/binding/chunked_read.py` | Tier guard | 14 |
| `lemely/app/cli.py`, `lemely/app/gradio_app.py` | Cost scope on CLI paths | 16 |
| `lemely/io/providers/claude_schema.py` | `extract_json` prose bracket | 17 |
| `tests/test_web_teacher.py` | Flaky timing hardened | 18 |
| `lemely/runtime/config.py`, `lemely/io/llm/request.py`, `lemely/io/providers/anthropic_adapter.py`, `lemely/io/gemini.py` | Effort `none` | 19 |
| `lemely/runtime/config.py`, `lemely/io/binding/orchestrate.py` | `claude_cache_ignores_effort` | 20 |
| `lemely/runtime/config.py`, `lemely/io/correction_ai.py` | `correction_borderline_enabled` | 21 |
| `lemely/io/adjudication.py` (new), `lemely/io/correction_ai.py`, `lemely/runtime/config.py`, `lemely/io/model_table.py`, `lemely/accuracy/cost_ladder/real_split.py`, `lemely/accuracy/cost_ladder/runner.py` | Sonnet adjudication | 22 |
| `lemely/io/correction_ai.py`, `lemely/runtime/config.py` | Escalation cap (conditional) | 27 |
| `BUILD/accuracy-runs/claude-c-2026-10-24/{base,gemini}.toml`, `LADDER.md`, `FLIP.md` | Committed rung configs and count-only reports | 23 to 28 |
| `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example`, `lemely/app/cli.py`, `docs/deployment.md`, `tests/gemini_fakes.py`, `tests/test_llm_golden.py` | The flip (P4, separate PR) | 30 |

## File ownership and waves

| Task | Owns (commit with `-- <these>`) |
|---|---|
| 1 | `lemely/accuracy/reference.py`, `tests/test_reference.py` |
| 2 | `scripts/build_reference.py`, `tests/test_build_reference_cli.py` |
| 5 | `lemely/accuracy/cost_ladder/gate.py`, `tests/test_cost_ladder_judges.py` |
| 6 | `lemely/accuracy/cost_ladder/real_split.py`, `tests/test_cost_ladder_real_split.py` |
| 7 | `lemely/accuracy/cost_ladder/runner.py`, `tests/test_cost_ladder_real_runner.py` |
| 8 | `lemely/accuracy/cost_ladder/report.py`, `tests/test_cost_ladder_real_report.py` |
| 9 | `scripts/cost_ladder.py`, `tests/test_cost_ladder_cli.py` |
| 10 | `lemely/accuracy/threshold_fit.py`, `scripts/fit_review_threshold.py`, `tests/test_threshold_fit.py` |
| 13 | `lemely/io/answer_extraction.py`, `lemely/io/llm/claude_provider.py`, `lemely/io/scan_metadata.py`, `tests/test_stage_timing.py` |
| 14 | `lemely/io/binding/orchestrate.py`, `lemely/io/binding/chunked_read.py`, `lemely/io/binding/label_binder.py`, `tests/test_claude_tier_guard.py` |
| 15 | `tests/test_escalation_triggers.py` |
| 16 | `lemely/app/cli.py`, `lemely/app/gradio_app.py`, `tests/test_script_cost_scope.py` |
| 17 | `lemely/io/providers/claude_schema.py`, `tests/test_claude_schema_limits.py` |
| 18 | `tests/test_web_teacher.py` |
| 19 | `lemely/runtime/config.py`, `lemely/io/llm/request.py`, `lemely/io/providers/anthropic_adapter.py`, `lemely/io/gemini.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example`, `tests/test_claude_effort_none.py` |
| 20 | `lemely/runtime/config.py`, `lemely/io/binding/orchestrate.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example`, `tests/test_claude_cache_effort.py` |
| 21 | `lemely/runtime/config.py`, `lemely/io/correction_ai.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example`, `tests/test_borderline_switch.py` |
| 22 | `lemely/io/adjudication.py`, `lemely/io/correction_ai.py`, `lemely/runtime/config.py`, `lemely/io/model_table.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example`, `lemely/accuracy/cost_ladder/real_split.py`, `lemely/accuracy/cost_ladder/runner.py`, `tests/test_adjudication.py` |
| 27 | `lemely/io/correction_ai.py`, `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example`, `tests/test_escalation_cap.py` |
| 30 | `lemely/runtime/config.py`, `lemely/runtime/example_toml.py`, `lemely.toml.example`, `lemely/app/cli.py`, `lemely/io/model_table.py`, `docs/deployment.md`, `tests/gemini_fakes.py`, `tests/test_llm_golden.py`, `tests/test_claude_default_flip.py` |

**Waves.**

- Wave A (parallel, disjoint files): 1, 5, 15, 17, 18.
- Wave B: 2 (after 1), 6 (after 1 and 5), 13, 14, 16 (parallel with each other; 13, 14 and 16 share no file with 2 or 6). Task 10 after 6.
- Wave C: 7 (after 5 and 6), then 8 (after 7), then 9 (after 7 and 8).
- Main session, as soon as Task 2 lands: Task 3 (live reference build), then Task 4 (user review, interactive). These run while Waves B and C proceed.
- After Task 4 and Wave C: Tasks 11 and 12 (investigations, $0, parallel), Task 13's live probe (Task 13b), then the conditional fix tasks they produce.
- Config-file tasks 19, 20, 21, 22 all edit `config.py`, `example_toml.py` and `lemely.toml.example`: run them one after another (19, 20, 21, 22). They can start after Wave A; 22 needs 6 and 7 landed.
- Main session: 23 (base and Gemini rungs), 24 (cost screens), 25 (accuracy screens), 26 (stack, fit, cap decision), conditional 27 and its screen, 28 (flip judge and reports), then the P0 to P3 PR.
- P4: 29 (smoke tests), 30 (flip code), 31 (flip PR).
- A final gate sweep (Task 28, step 1) runs after the last P0 to P3 commit and again in Task 31 for P4. A later fix commit voids a sweep: rerun it.

---
## Phase P0: Reference set

### Task 1: Reference files, check-first rule and freeze manifest

**Files:**
- Create: `lemely/accuracy/reference.py`
- Test: `tests/test_reference.py` (new)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces (Tasks 2, 6, 11 rely on these exact names):
  - `REFERENCE_ROOT: Path` (repo `BUILD/accuracy-runs/claude-c-reference`), `MANIFEST_FILE = "manifest.json"`, `REFERENCE_FILE = "reference.json"`, `SCHEME_FILE = "mark_scheme.json"`, `REVIEW_FILE = "REVIEW.md"`, `FROZEN_MARKER = "FROZEN"`, `LOW_CONFIDENCE = 0.8`.
  - `Source = Literal["teacher_tick", "opus", "user_override"]`.
  - `@dataclass(frozen=True) ReferenceLeaf(question_id: str, mark: int, max_marks: int, source: Source, evidence: str, note: str = "")`.
  - `@dataclass(frozen=True) OtherMarks(name: str, marks: Mapping[str, int])`.
  - `@dataclass(frozen=True) ManifestEntry(key, scan_path, scheme_path, reference_path, reference_sha256, scheme_sha256, scan_sha256, source_sha256: Mapping[str, str])` (all paths `str`, absolute).
  - `class ReferenceStateError(RuntimeError)`.
  - `sha256_file(path: Path) -> str`, `write_reference(path, leaves) -> None`, `read_reference(path) -> dict[str, ReferenceLeaf]`, `reference_total(leaves: Mapping[str, ReferenceLeaf]) -> int`, `check_first(reference, *, others=(), confidence=None, ambiguous=(), expected_total=None) -> dict[str, list[str]]`, `render_review(key: str, reference, flagged) -> str`, `is_frozen(script_dir: Path) -> bool`, `apply_override(script_dir, question_id, mark, note) -> ReferenceLeaf`, `freeze(script_dir, *, key, scan_path, sources: Mapping[str, Path], expected_total: int | None, manifest_path: Path) -> ManifestEntry`, `read_manifest(path) -> list[ManifestEntry]`.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_reference.py`:

```python
"""Sub-project C P0: reference files, the check-first list and the freeze manifest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lemely.accuracy import reference as ref
from lemely.accuracy.reference import OtherMarks, ReferenceLeaf, ReferenceStateError


def _leaf(qid: str, mark: int, max_marks: int = 2, source: ref.Source = "opus") -> ReferenceLeaf:
    return ReferenceLeaf(question_id=qid, mark=mark, max_marks=max_marks, source=source, evidence="e")


def _script_dir(tmp_path: Path, leaves: list[ReferenceLeaf]) -> Path:
    d = tmp_path / "0625_w24_41"
    ref.write_reference(d / ref.REFERENCE_FILE, leaves)
    (d / ref.SCHEME_FILE).write_text('{"questions": []}', encoding="utf-8")
    return d


def test_mark_outside_range_is_refused() -> None:
    with pytest.raises(ValueError, match="outside 0..2"):
        _leaf("1a", 3)


def test_round_trip_and_total(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    ref.write_reference(path, [_leaf("2a", 1), _leaf("1a", 2)])
    loaded = ref.read_reference(path)
    assert list(loaded) == ["1a", "2a"]
    assert ref.reference_total(loaded) == 3


def test_duplicate_leaf_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        ref.write_reference(tmp_path / "r.json", [_leaf("1a", 1), _leaf("1a", 2)])


def test_disagreement_low_confidence_and_ambiguous_are_listed() -> None:
    reference = {q.question_id: q for q in (_leaf("1a", 2), _leaf("1b", 1), _leaf("1c", 0))}
    flagged = ref.check_first(
        reference,
        others=[OtherMarks("gemini", {"1a": 2, "1b": 0}), OtherMarks("claude", {"1a": 2})],
        confidence={"1a": 0.95, "1c": 0.6},
        ambiguous=["1a"],
    )
    assert flagged["1b"] == ["disagrees with gemini (0)"]
    assert flagged["1c"] == ["confidence 0.60 below 0.8"]
    assert flagged["1a"] == ["ambiguous tick"]


def test_agreeing_confident_leaf_is_not_listed() -> None:
    reference = {"1a": _leaf("1a", 2)}
    assert ref.check_first(reference, others=[OtherMarks("gemini", {"1a": 2})]) == {}


def test_gap_to_teacher_total_lists_the_disagreeing_leaves() -> None:
    reference = {q.question_id: q for q in (_leaf("1a", 2), _leaf("1b", 0))}
    flagged = ref.check_first(
        reference, others=[OtherMarks("opus", {"1b": 1})], expected_total=3
    )
    assert flagged["1b"][-1] == "total 2 is 1 below 3"
    assert "1a" not in flagged


def test_gap_with_no_disagreement_lists_every_leaf_that_could_hold_it() -> None:
    reference = {q.question_id: q for q in (_leaf("1a", 2), _leaf("1b", 0))}
    flagged = ref.check_first(reference, expected_total=3)
    assert list(flagged) == ["1b"]  # 1a is at full marks: it cannot hold a missing tick


def test_review_markdown_lists_reasons_and_total(tmp_path: Path) -> None:
    reference = {"1a": _leaf("1a", 2), "1b": _leaf("1b", 0)}
    text = ref.render_review("k", reference, {"1b": ["disagrees with gemini (1)"]})
    assert "| 1b | 0 / 2 | opus | disagrees with gemini (1) |" in text
    assert "Total: 2" in text


def test_override_is_stored_and_refused_after_freeze(tmp_path: Path) -> None:
    d = _script_dir(tmp_path, [_leaf("1a", 1)])
    leaf = ref.apply_override(d, "1a", 2, "teacher ticked twice")
    assert leaf.source == "user_override" and leaf.mark == 2
    assert ref.read_reference(d / ref.REFERENCE_FILE)["1a"].note == "teacher ticked twice"
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(b"%PDF-1")
    ref.freeze(d, key="k", scan_path=scan, sources={}, expected_total=None,
               manifest_path=tmp_path / ref.MANIFEST_FILE)
    with pytest.raises(ReferenceStateError, match="frozen"):
        ref.apply_override(d, "1a", 1, "no")


def test_override_of_unknown_leaf_is_refused(tmp_path: Path) -> None:
    d = _script_dir(tmp_path, [_leaf("1a", 1)])
    with pytest.raises(ReferenceStateError, match="9z"):
        ref.apply_override(d, "9z", 1, "")


def test_freeze_writes_manifest_with_digests(tmp_path: Path) -> None:
    d = _script_dir(tmp_path, [_leaf("1a", 2), _leaf("1b", 1)])
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(b"%PDF-1 scan")
    copy = tmp_path / "corrected.pdf"
    copy.write_bytes(b"%PDF-1 ticks")
    manifest = tmp_path / ref.MANIFEST_FILE
    entry = ref.freeze(d, key="0625_w24_41", scan_path=scan, sources={"corrected_copy": copy},
                       expected_total=3, manifest_path=manifest)
    assert entry.reference_sha256 == ref.sha256_file(d / ref.REFERENCE_FILE)
    assert entry.scan_sha256 == ref.sha256_file(scan)
    assert entry.source_sha256 == {"corrected_copy": ref.sha256_file(copy)}
    assert ref.is_frozen(d)
    (loaded,) = ref.read_manifest(manifest)
    assert loaded == entry


def test_freeze_refuses_a_total_that_misses_the_teacher_total(tmp_path: Path) -> None:
    d = _script_dir(tmp_path, [_leaf("1a", 2)])
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(b"x")
    with pytest.raises(ReferenceStateError, match="sums to 2, not 66"):
        ref.freeze(d, key="k", scan_path=scan, sources={}, expected_total=66,
                   manifest_path=tmp_path / ref.MANIFEST_FILE)
    assert not ref.is_frozen(d)


def test_refreeze_replaces_the_manifest_entry(tmp_path: Path) -> None:
    manifest = tmp_path / ref.MANIFEST_FILE
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(b"x")
    for key in ("a", "b"):
        d = tmp_path / key
        ref.write_reference(d / ref.REFERENCE_FILE, [_leaf("1a", 1)])
        (d / ref.SCHEME_FILE).write_text("{}", encoding="utf-8")
        ref.freeze(d, key=key, scan_path=scan, sources={}, expected_total=None, manifest_path=manifest)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert [e["key"] for e in data["scripts"]] == ["a", "b"]
```

- [ ] **Step 2: Run the tests to watch them fail.**

Run: `.venv/bin/python -m pytest tests/test_reference.py -q --no-cov -o addopts=""`
Expected: collection error, `ModuleNotFoundError: No module named 'lemely.accuracy.reference'`.

- [ ] **Step 3: Write the module.** Create `lemely/accuracy/reference.py`:

```python
"""Sub-project C reference set: per-leaf truth for the real scripts, built once and frozen.

Pure file handling: the leaf files under ``BUILD/accuracy-runs/claude-c-reference/``,
the check-first list a human reviews, overrides, and the freeze manifest the real
split checks before any spend. The model calls that fill a reference are in
``scripts/build_reference.py``. Nothing here is committed data: every file it writes
holds student marks and stays under the gitignored BUILD tree.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

REFERENCE_ROOT = (
    Path(__file__).resolve().parents[2] / "BUILD" / "accuracy-runs" / "claude-c-reference"
)
MANIFEST_FILE = "manifest.json"
REFERENCE_FILE = "reference.json"
SCHEME_FILE = "mark_scheme.json"
REVIEW_FILE = "REVIEW.md"
FROZEN_MARKER = "FROZEN"
#: A reference confidence below this puts the leaf on the check-first list (spec P0).
LOW_CONFIDENCE = 0.8

Source = Literal["teacher_tick", "opus", "user_override"]


class ReferenceStateError(RuntimeError):
    """A reference file is frozen, inconsistent, or missing what a step needs."""


@dataclass(frozen=True)
class ReferenceLeaf:
    question_id: str
    mark: int
    max_marks: int
    source: Source
    evidence: str
    note: str = ""

    def __post_init__(self) -> None:
        if not 0 <= self.mark <= self.max_marks:
            raise ValueError(
                f"{self.question_id}: mark {self.mark} outside 0..{self.max_marks}"
            )


@dataclass(frozen=True)
class OtherMarks:
    """Another source's marks for the same leaves (Opus, Gemini, Claude), by question id."""

    name: str
    marks: Mapping[str, int]


@dataclass(frozen=True)
class ManifestEntry:
    key: str
    scan_path: str
    scheme_path: str
    reference_path: str
    reference_sha256: str
    scheme_sha256: str
    scan_sha256: str
    source_sha256: Mapping[str, str]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_reference(path: Path, leaves: Iterable[ReferenceLeaf]) -> None:
    rows = sorted((asdict(leaf) for leaf in leaves), key=lambda row: row["question_id"])
    ids = [row["question_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate question_id in reference")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def read_reference(path: Path) -> dict[str, ReferenceLeaf]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    leaves = [ReferenceLeaf(**row) for row in rows]
    return {leaf.question_id: leaf for leaf in leaves}


def reference_total(leaves: Mapping[str, ReferenceLeaf]) -> int:
    return sum(leaf.mark for leaf in leaves.values())


def check_first(
    reference: Mapping[str, ReferenceLeaf],
    *,
    others: Iterable[OtherMarks] = (),
    confidence: Mapping[str, float] | None = None,
    ambiguous: Iterable[str] = (),
    expected_total: int | None = None,
) -> dict[str, list[str]]:
    """The leaves a human checks first, each with its reasons, in question-id order.

    A leaf is listed when another source's mark differs from the reference, when the
    reference's confidence is below `LOW_CONFIDENCE`, or when its tick is ambiguous.
    When the reference total misses *expected_total* (the teacher's total), the gap
    sits among the listed leaves; with none listed, among every leaf that could hold
    it (below full marks for a total that is short, above zero for one that is over).
    """
    reasons: dict[str, list[str]] = {qid: [] for qid in reference}
    sources = list(others)
    for qid, leaf in reference.items():
        seen = {o.name: o.marks[qid] for o in sources if qid in o.marks}
        differing = sorted(name for name, mark in seen.items() if mark != leaf.mark)
        if differing:
            reasons[qid].append(
                "disagrees with " + ", ".join(f"{name} ({seen[name]})" for name in differing)
            )
        if confidence is not None and qid in confidence and confidence[qid] < LOW_CONFIDENCE:
            reasons[qid].append(f"confidence {confidence[qid]:.2f} below {LOW_CONFIDENCE}")
    for qid in ambiguous:
        if qid in reasons:
            reasons[qid].append("ambiguous tick")
    if expected_total is not None:
        total = reference_total(reference)
        gap = expected_total - total
        if gap:
            suspects = [qid for qid, why in reasons.items() if why] or [
                qid
                for qid, leaf in reference.items()
                if (leaf.mark < leaf.max_marks if gap > 0 else leaf.mark > 0)
            ]
            side = "below" if gap > 0 else "above"
            for qid in suspects:
                reasons[qid].append(f"total {total} is {abs(gap)} {side} {expected_total}")
    return {qid: why for qid, why in sorted(reasons.items()) if why}


def render_review(
    key: str, reference: Mapping[str, ReferenceLeaf], flagged: Mapping[str, list[str]]
) -> str:
    """``REVIEW.md``: the check-first table, then the total. Holds marks: never committed."""
    lines = [
        f"# Reference review: {key}",
        "",
        f"Total: {reference_total(reference)} of "
        f"{sum(leaf.max_marks for leaf in reference.values())}; "
        f"{len(flagged)} of {len(reference)} leaves to check first.",
        "",
        "| leaf | mark | source | reasons |",
        "|---|---|---|---|",
    ]
    for qid, why in flagged.items():
        leaf = reference[qid]
        lines.append(
            f"| {qid} | {leaf.mark} / {leaf.max_marks} | {leaf.source} | {'; '.join(why)} |"
        )
    return "\n".join(lines) + "\n"


def is_frozen(script_dir: Path) -> bool:
    return (script_dir / FROZEN_MARKER).is_file()


def apply_override(script_dir: Path, question_id: str, mark: int, note: str) -> ReferenceLeaf:
    """Store the user's mark for one leaf as ``user_override``; refused once frozen."""
    if is_frozen(script_dir):
        raise ReferenceStateError(f"{script_dir} is frozen; an override would change it")
    path = script_dir / REFERENCE_FILE
    leaves = read_reference(path)
    if question_id not in leaves:
        raise ReferenceStateError(f"{question_id} is not a leaf of {path}")
    updated = replace(leaves[question_id], mark=mark, source="user_override", note=note)
    leaves[question_id] = updated
    write_reference(path, leaves.values())
    return updated


def read_manifest(path: Path) -> list[ManifestEntry]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [ManifestEntry(**entry) for entry in data["scripts"]]


def freeze(
    script_dir: Path,
    *,
    key: str,
    scan_path: Path,
    sources: Mapping[str, Path],
    expected_total: int | None,
    manifest_path: Path,
) -> ManifestEntry:
    """Freeze a reviewed reference: record its digests in the manifest, then mark it frozen.

    Refuses a reference whose total misses *expected_total* (the teacher's total).
    Re-freezing a key replaces its manifest entry.
    """
    reference_path = script_dir / REFERENCE_FILE
    scheme_path = script_dir / SCHEME_FILE
    for needed in (reference_path, scheme_path, scan_path):
        if not needed.is_file():
            raise ReferenceStateError(f"cannot freeze {key}: {needed} is missing")
    total = reference_total(read_reference(reference_path))
    if expected_total is not None and total != expected_total:
        raise ReferenceStateError(f"{key}: reference sums to {total}, not {expected_total}")
    entry = ManifestEntry(
        key=key,
        scan_path=str(scan_path.resolve()),
        scheme_path=str(scheme_path.resolve()),
        reference_path=str(reference_path.resolve()),
        reference_sha256=sha256_file(reference_path),
        scheme_sha256=sha256_file(scheme_path),
        scan_sha256=sha256_file(scan_path),
        source_sha256={name: sha256_file(p) for name, p in sorted(sources.items())},
    )
    entries = [e for e in read_manifest(manifest_path) if e.key != key] + [entry]
    entries.sort(key=lambda e: e.key)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"scripts": [asdict(e) for e in entries]}, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (script_dir / FROZEN_MARKER).write_text(entry.reference_sha256 + "\n", encoding="utf-8")
    return entry
```

- [ ] **Step 4: Run the tests to watch them pass.**

Run: `.venv/bin/python -m pytest tests/test_reference.py -q --no-cov -o addopts=""`
Expected: 13 passed.

- [ ] **Step 5: Prove the guards red.** In `freeze`, change `total != expected_total` to `False`; run `test_freeze_refuses_a_total_that_misses_the_teacher_total` and watch it fail (`DID NOT RAISE`). Revert. In `apply_override`, delete the `is_frozen` check; run `test_override_is_stored_and_refused_after_freeze` and watch it fail. Revert. Rerun the file: 13 passed.

- [ ] **Step 6: Gates and commit.**

```bash
.venv/bin/python -m pytest tests/test_reference.py tests/test_llm_golden.py -q --no-cov -o addopts=""
PATH=$PWD/.venv/bin:$PATH pre-commit run --files lemely/accuracy/reference.py tests/test_reference.py
git add -- lemely/accuracy/reference.py tests/test_reference.py
git commit -S -m "feat(reference): reference leaves, check-first list and freeze manifest" -- lemely/accuracy/reference.py tests/test_reference.py
```

---

### Task 2: `scripts/build_reference.py` (Opus-backed builder CLI)

**Files:**
- Create: `scripts/build_reference.py`
- Test: `tests/test_build_reference_cli.py` (new)

**Interfaces:**
- Consumes (Task 1): `REFERENCE_ROOT`, `REFERENCE_FILE`, `SCHEME_FILE`, `REVIEW_FILE`, `MANIFEST_FILE`, `ReferenceLeaf`, `OtherMarks`, `write_reference`, `read_reference`, `check_first`, `render_review`, `apply_override`, `freeze`, `is_frozen`, `ReferenceStateError`. Existing: `GeminiClient.generate_structured`, `record_calls`, `process_call_records`, `set_call_context`, `lemely.accuracy.cost_ladder.spend.{SpendLedger, SpendCaps, CapWatch, check_can_start, cost_by_provider, DEFAULT_SPEND_FILE}`, `lemely.io.rasterise.rasterise_scan_to_pages`, `lemely.io.reread.crop_and_upscale`, `lemely.io.prompts.correction_ai.render_paper_mark_scheme`, `lemely.io.det.DeterministicMarkSchemeParser`, `lemely.io.parsers.{ChainedMarkSchemeParser, GeminiMarkSchemeParser}`, `lemely.core.loose_schemas.MarkScheme`.
- Produces: the CLI used by Tasks 3 and 4:
  - `prepare KEY --scan PATH (--scheme-json PATH | --scheme-pdf PATH)`: writes `<root>/KEY/mark_scheme.json` and `inputs.json` (`{"scan": ..., "scheme_source": ...}`).
  - `mark KEY --mode {opus,teacher,mcq} [--truth PATH] [--max-usd X]`: one Opus call; writes `<root>/KEY/marks_<mode>.json` (`{"leaves": [{question_id, mark, confidence, evidence, page, ambiguous}]}`).
  - `adopt KEY --from {opus,teacher,mcq}`: builds `reference.json` from a marks file (source `opus` or `teacher_tick`; `mcq` maps to `teacher_tick`).
  - `review-list KEY [--prior NAME=correction.json ...] [--expected-total N]`: writes `REVIEW.md`.
  - `crop KEY --leaf QID --out PNG [--extracted extracted.json] [--page N]`.
  - `override KEY --leaf QID --mark N [--note TEXT]`.
  - `freeze KEY [--expected-total N] [--source NAME=PATH ...]`.
  - Global `--root PATH` (default `REFERENCE_ROOT`), `--spend-file PATH` (default `DEFAULT_SPEND_FILE`).
  - Pure helpers tested directly: `marks_from_correction(path: Path) -> dict[str, int]`, `leaves_from_marks(marks: list[dict], scheme: MarkScheme, source: Source) -> list[ReferenceLeaf]`, `scheme_leaves(scheme) -> dict[str, int]` (leaf id to max marks).

- [ ] **Step 1: Write the failing tests.** Create `tests/test_build_reference_cli.py`:

```python
"""Sub-project C P0: the reference builder CLI. Fake client only: no model call, no spend."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from lemely.accuracy import reference as ref
from lemely.core.loose_schemas import MarkScheme

_SPEC = importlib.util.spec_from_file_location(
    "build_reference", Path(__file__).resolve().parents[1] / "scripts" / "build_reference.py"
)
assert _SPEC is not None and _SPEC.loader is not None
br = importlib.util.module_from_spec(_SPEC)
sys.modules["build_reference"] = br
_SPEC.loader.exec_module(br)

_SCHEME = {
    "metadata": {"subject": "Physics", "subject_code": "0625", "paper_number": 4,
                 "paper_variant": 1, "session_month": "Oct/Nov", "session_year": 2024,
                 "paper_type": "theory_extended", "maximum_mark": 3,
                 "scheme_format": "point_based"},
    "questions": [
        {"id": "1", "marks": 3, "type": "recall", "parts": [
            {"id": "1a", "parent_id": "1", "marks": 2, "type": "calculation",
             "answer_points": [{"id": "M1", "point": "uses F = ma", "marks": 1},
                               {"id": "A1", "point": "6 N", "marks": 1}]},
            {"id": "1b", "parent_id": "1", "marks": 1, "type": "recall",
             "answer_points": [{"id": "B1", "point": "upwards", "marks": 1}]},
        ]},
    ],
}


def _scheme() -> MarkScheme:
    return MarkScheme.model_validate(_SCHEME)


def test_scheme_leaves_lists_marked_leaves() -> None:
    assert br.scheme_leaves(_scheme()) == {"1a": 2, "1b": 1}


def test_leaves_from_marks_clamps_nothing_and_refuses_unknown_leaf() -> None:
    marks = [
        {"question_id": "1a", "mark": 2, "confidence": 0.9, "evidence": "6 N", "page": 1,
         "ambiguous": False},
        {"question_id": "1b", "mark": 0, "confidence": 0.7, "evidence": "-", "page": 1,
         "ambiguous": True},
    ]
    leaves = br.leaves_from_marks(marks, _scheme(), "teacher_tick")
    assert [(l.question_id, l.mark, l.source) for l in leaves] == [
        ("1a", 2, "teacher_tick"), ("1b", 0, "teacher_tick")]
    with pytest.raises(ref.ReferenceStateError, match="9z"):
        br.leaves_from_marks([{**marks[0], "question_id": "9z"}], _scheme(), "opus")


def test_leaves_from_marks_fills_a_missing_leaf_with_zero_and_a_note() -> None:
    leaves = br.leaves_from_marks(
        [{"question_id": "1a", "mark": 1, "confidence": 0.9, "evidence": "e", "page": None,
          "ambiguous": False}], _scheme(), "opus")
    (missing,) = [l for l in leaves if l.question_id == "1b"]
    assert missing.mark == 0 and "not returned" in missing.note


def test_marks_from_correction_reads_awarded_marks(tmp_path: Path) -> None:
    path = tmp_path / "correction.json"
    path.write_text(json.dumps({"questions": [
        {"question_id": "1a", "awarded_marks": 1}, {"question_id": "1b", "awarded_marks": 0}]}))
    assert br.marks_from_correction(path) == {"1a": 1, "1b": 0}


class _FakeClient:
    def __init__(self, reply: Any) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def generate_structured(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.reply


def test_mark_writes_marks_file_and_books_spend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "ref"
    d = root / "k"
    d.mkdir(parents=True)
    (d / ref.SCHEME_FILE).write_text(json.dumps(_SCHEME), encoding="utf-8")
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(b"%PDF")
    (d / "inputs.json").write_text(json.dumps({"scan": str(scan), "scheme_source": "x"}))
    reply = br.ReferenceReply(leaves=[
        br.ReferenceLeafReply(question_id="1a", mark=2, confidence=0.9, evidence="6 N"),
        br.ReferenceLeafReply(question_id="1b", mark=1, confidence=0.95, evidence="up"),
    ])
    fake = _FakeClient(reply)
    monkeypatch.setattr(br, "_pages", lambda path: [b"png1", b"png2"])
    monkeypatch.setattr(br, "_client", lambda settings: fake)
    monkeypatch.setattr(br, "_load_keys", lambda: None)
    spend = tmp_path / "spend.json"
    spend.write_text(json.dumps({"anthropic": 1.0}))
    assert br.main(["--root", str(root), "--spend-file", str(spend), "mark", "k",
                    "--mode", "opus", "--max-usd", "2.0"]) == 0
    (call,) = fake.calls
    assert call["model"] == br.OPUS and call["task_tag"] == br.TASK_TAG
    assert call["image_parts"] == [b"png1", b"png2"]
    assert call["cache_mode"] == "read_write"
    data = json.loads((d / "marks_opus.json").read_text())
    assert [l["question_id"] for l in data["leaves"]] == ["1a", "1b"]


def test_mark_refuses_before_spend_when_the_cap_would_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "ref"
    (root / "k").mkdir(parents=True)
    (root / "k" / ref.SCHEME_FILE).write_text(json.dumps(_SCHEME), encoding="utf-8")
    (root / "k" / "inputs.json").write_text(json.dumps({"scan": str(tmp_path), "scheme_source": "x"}))
    monkeypatch.setattr(br, "_load_keys", lambda: None)

    def boom(settings: object) -> object:
        raise AssertionError("must not build a client")

    monkeypatch.setattr(br, "_client", boom)
    spend = tmp_path / "spend.json"
    spend.write_text(json.dumps({"anthropic": 39.5}))
    assert br.main(["--root", str(root), "--spend-file", str(spend), "mark", "k",
                    "--mode", "opus", "--max-usd", "1.0"]) == 2


def test_teacher_mode_needs_truth_and_sends_its_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "ref"
    d = root / "k"
    d.mkdir(parents=True)
    (d / ref.SCHEME_FILE).write_text(json.dumps(_SCHEME), encoding="utf-8")
    (d / "inputs.json").write_text(json.dumps({"scan": str(tmp_path / "scan.pdf"), "scheme_source": "x"}))
    monkeypatch.setattr(br, "_load_keys", lambda: None)
    assert br.main(["--root", str(root), "mark", "k", "--mode", "teacher"]) == 2
    truth = tmp_path / "ticks.pdf"
    truth.write_bytes(b"%PDF")
    seen: list[Path] = []
    monkeypatch.setattr(br, "_pages", lambda path: seen.append(path) or [b"t"])
    fake = _FakeClient(br.ReferenceReply(leaves=[]))
    monkeypatch.setattr(br, "_client", lambda settings: fake)
    spend = tmp_path / "spend.json"
    assert br.main(["--root", str(root), "--spend-file", str(spend), "mark", "k", "--mode",
                    "teacher", "--truth", str(truth), "--max-usd", "1"]) == 0
    assert seen == [truth]
    assert "tick" in fake.calls[0]["system_prompt"].lower()


def test_adopt_review_override_freeze_round(tmp_path: Path) -> None:
    root = tmp_path / "ref"
    d = root / "k"
    d.mkdir(parents=True)
    (d / ref.SCHEME_FILE).write_text(json.dumps(_SCHEME), encoding="utf-8")
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(b"%PDF")
    (d / "inputs.json").write_text(json.dumps({"scan": str(scan), "scheme_source": "x"}))
    (d / "marks_teacher.json").write_text(json.dumps({"leaves": [
        {"question_id": "1a", "mark": 2, "confidence": 0.9, "evidence": "tick tick", "page": 1, "ambiguous": False},
        {"question_id": "1b", "mark": 0, "confidence": 0.6, "evidence": "-", "page": 1, "ambiguous": True}]}))
    prior = tmp_path / "gemini.json"
    prior.write_text(json.dumps({"questions": [{"question_id": "1a", "awarded_marks": 1},
                                               {"question_id": "1b", "awarded_marks": 0}]}))
    assert br.main(["--root", str(root), "adopt", "k", "--from", "teacher"]) == 0
    assert br.main(["--root", str(root), "review-list", "k", "--prior", f"gemini={prior}",
                    "--expected-total", "3"]) == 0
    review = (d / ref.REVIEW_FILE).read_text()
    assert "| 1a |" in review and "| 1b |" in review
    assert br.main(["--root", str(root), "override", "k", "--leaf", "1b", "--mark", "1",
                    "--note", "tick under the line"]) == 0
    assert br.main(["--root", str(root), "freeze", "k", "--expected-total", "3"]) == 0
    (entry,) = ref.read_manifest(root / ref.MANIFEST_FILE)
    assert entry.key == "k"
    assert br.main(["--root", str(root), "override", "k", "--leaf", "1b", "--mark", "0"]) == 2
```

- [ ] **Step 2: Run the tests to watch them fail.**

Run: `.venv/bin/python -m pytest tests/test_build_reference_cli.py -q --no-cov -o addopts=""`
Expected: error at import, `FileNotFoundError` / `No such file` for `scripts/build_reference.py`.

- [ ] **Step 3: Write the script.** Create `scripts/build_reference.py`:

```python
#!/usr/bin/env python3
r"""Sub-project C P0: build, review and freeze the per-leaf reference for a real script.

Every model call goes through ``GeminiClient`` on ``claude-opus-5-5`` (synchronous
Messages API, never the batches API), inside ``record_calls``, with the combined
cost-ladder spend ledger checked before and booked after. Keys are read inside this
process from ``~/.config/lemely/{anthropic,gemini}_key`` and never printed. Every file
written holds student marks and stays under the gitignored BUILD tree.

    build_reference.py prepare KEY --scan PDF (--scheme-json JSON | --scheme-pdf PDF)
    build_reference.py mark KEY --mode {opus,teacher,mcq} [--truth PDF] --max-usd 1.5
    build_reference.py adopt KEY --from {opus,teacher,mcq}
    build_reference.py review-list KEY [--prior gemini=correction.json ...] [--expected-total N]
    build_reference.py crop KEY --leaf QID --out crop.png [--extracted extracted.json] [--page N]
    build_reference.py override KEY --leaf QID --mark N [--note TEXT]
    build_reference.py freeze KEY [--expected-total N] [--source corrected_copy=PDF ...]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from lemely.accuracy import reference as ref
from lemely.accuracy.cost_ladder.spend import (
    DEFAULT_SPEND_FILE,
    SpendCapError,
    SpendCaps,
    SpendLedger,
    check_can_start,
    cost_by_provider,
)
from lemely.core.loose_schemas import MarkScheme

if TYPE_CHECKING:
    from lemely.io.gemini import GeminiClient
    from lemely.runtime.config import Settings

OPUS = "claude-opus-5-5"
TASK_TAG = "reference"
PROMPT_VERSION = "c-reference-v1"
_KEY_FILES = (
    ("ANTHROPIC_API_KEY", "~/.config/lemely/anthropic_key"),
    ("GEMINI_API_KEY", "~/.config/lemely/gemini_key"),
)

_OPUS_SYSTEM = (
    "You are a senior Cambridge IGCSE examiner building a reference marking of one "
    "handwritten script. Mark every leaf listed against its mark scheme points only. "
    "For each leaf give the mark, your confidence from 0 to 1, the student's words or "
    "working that earn each mark quoted exactly (or '-' when nothing earns a mark), and "
    "the 1-based page the answer is on. Set ambiguous when you cannot read the answer "
    "well enough to be sure."
)
_TEACHER_SYSTEM = (
    "You are transcribing a teacher's marking of a handwritten script. The pages carry the "
    "teacher's red ticks and crosses. For each leaf listed, count the ticks the teacher "
    "gave that leaf: that count is its mark. Quote what the tick sits next to as the "
    "evidence and give the 1-based page. Do not mark the answer yourself. Set ambiguous "
    "when a tick could belong to more than one leaf, or is hard to count; confidence is "
    "how sure you are of the count."
)
_MCQ_SYSTEM = (
    "You are reading a multiple-choice script that a teacher has marked. For each leaf "
    "listed, if the teacher's tick or cross is legible, the mark is 1 for a tick and 0 for "
    "a cross. If not, read the letter the student chose, quote it as the evidence, and "
    "give the mark the key in the mark scheme gives that letter. Give the 1-based page. "
    "Set ambiguous when the chosen letter or the tick is unclear."
)
_SYSTEM_FOR = {"opus": _OPUS_SYSTEM, "teacher": _TEACHER_SYSTEM, "mcq": _MCQ_SYSTEM}


class ReferenceLeafReply(BaseModel):
    question_id: str
    mark: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str
    page: int | None = None
    ambiguous: bool = False


class ReferenceReply(BaseModel):
    leaves: list[ReferenceLeafReply]


def scheme_leaves(scheme: MarkScheme) -> dict[str, int]:
    """Leaf id to maximum marks, for every marked leaf of *scheme*."""
    return {q.id: q.marks for q in scheme.all_questions_flat() if q.marks > 0 and not q.parts}


def leaves_from_marks(
    marks: list[dict[str, Any]], scheme: MarkScheme, source: ref.Source
) -> list[ref.ReferenceLeaf]:
    """Reference leaves from a marks file; a leaf the model left out is 0 with a note."""
    maxima = scheme_leaves(scheme)
    by_id: dict[str, dict[str, Any]] = {}
    for row in marks:
        qid = str(row["question_id"])
        if qid not in maxima:
            raise ref.ReferenceStateError(f"marks name a leaf the scheme does not have: {qid}")
        by_id[qid] = row
    leaves: list[ref.ReferenceLeaf] = []
    for qid, max_marks in maxima.items():
        row = by_id.get(qid)
        if row is None:
            leaves.append(ref.ReferenceLeaf(qid, 0, max_marks, source, "-", "not returned by the model"))
            continue
        note = "ambiguous" if row.get("ambiguous") else ""
        mark = min(int(row["mark"]), max_marks)
        if mark != int(row["mark"]):
            note = (note + "; " if note else "") + f"model gave {row['mark']}, above the maximum"
        leaves.append(ref.ReferenceLeaf(qid, mark, max_marks, source, str(row["evidence"]), note))
    return leaves


def marks_from_correction(path: Path) -> dict[str, int]:
    """Awarded marks per leaf from a stored ``correction.json`` (CorrectionResult)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(q["question_id"]): int(q["awarded_marks"]) for q in data["questions"]}


def _load_keys() -> None:
    for var, key_path in _KEY_FILES:
        path = Path(key_path).expanduser()
        if path.is_file():
            os.environ.setdefault(var, path.read_text(encoding="utf-8").strip())


def _pages(path: Path) -> list[bytes]:
    from lemely.io.rasterise import rasterise_scan_to_pages

    return [page.png_bytes for page in rasterise_scan_to_pages(path)]


def _client(settings: Settings) -> GeminiClient:
    from lemely.io.gemini import GeminiClient

    # read_write on the script's own cache dir: a rerun of `mark` replays the reply ($0).
    return GeminiClient(settings, default_cache_mode="read_write")


def _settings(script_dir: Path) -> Settings:
    from lemely.runtime.config import load_settings

    s = load_settings()
    paths = s.paths.model_copy(update={"cache_dir": script_dir / "cache"})
    return s.model_copy(update={"paths": paths})


def _scheme(script_dir: Path) -> MarkScheme:
    return MarkScheme.model_validate_json((script_dir / ref.SCHEME_FILE).read_text("utf-8"))


def _inputs(script_dir: Path) -> dict[str, str]:
    path = script_dir / "inputs.json"
    if not path.is_file():
        raise ref.ReferenceStateError(f"{path} missing: run `prepare` first")
    data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _prepare(args: argparse.Namespace) -> int:
    script_dir: Path = args.root / args.key
    if ref.is_frozen(script_dir):
        raise ref.ReferenceStateError(f"{script_dir} is frozen")
    script_dir.mkdir(parents=True, exist_ok=True)
    if args.scheme_json is not None:
        scheme = MarkScheme.model_validate_json(args.scheme_json.read_text(encoding="utf-8"))
        source = str(args.scheme_json)
    else:
        from lemely.io.det import DeterministicMarkSchemeParser
        from lemely.runtime.config import load_settings

        try:
            scheme = DeterministicMarkSchemeParser(cfg=load_settings().det_parser)(args.scheme_pdf)
            source = f"det:{args.scheme_pdf}"
        except Exception as exc:  # noqa: BLE001 -- the PDF needs the LLM parser instead
            raise ref.ReferenceStateError(
                f"the deterministic parser failed on {args.scheme_pdf} ({exc}); parse it with "
                "`lemely parse-mark-schemes` and pass --scheme-json"
            ) from exc
    (script_dir / ref.SCHEME_FILE).write_text(scheme.model_dump_json(indent=1), encoding="utf-8")
    (script_dir / "inputs.json").write_text(
        json.dumps({"scan": str(args.scan.resolve()), "scheme_source": source}, indent=1) + "\n",
        encoding="utf-8",
    )
    print(f"prepared {args.key}: {len(scheme_leaves(scheme))} leaves, scheme from {source}")
    return 0


def _leaf_list(scheme: MarkScheme) -> str:
    from lemely.io.prompts.correction_ai import render_paper_mark_scheme

    leaves = ", ".join(f"{qid} (max {m})" for qid, m in scheme_leaves(scheme).items())
    return f"Leaves to mark: {leaves}\n\nMark scheme:\n{render_paper_mark_scheme(scheme)}"


def _mark(args: argparse.Namespace) -> int:
    from lemely.io.gemini import process_call_records, record_calls, set_call_context

    script_dir: Path = args.root / args.key
    if ref.is_frozen(script_dir):
        raise ref.ReferenceStateError(f"{script_dir} is frozen")
    if args.mode in ("teacher", "mcq") and args.truth is None:
        raise ref.ReferenceStateError(f"--mode {args.mode} reads the marked copy: pass --truth")
    scheme = _scheme(script_dir)
    pages_from = args.truth if args.mode in ("teacher", "mcq") else Path(_inputs(script_dir)["scan"])
    ledger = SpendLedger(args.spend_file)
    check_can_start(ledger.spent(), {"anthropic": args.max_usd}, SpendCaps())
    _load_keys()
    settings = _settings(script_dir)
    client = _client(settings)
    with record_calls():
        set_call_context(case_key=f"reference:{args.key}")
        try:
            reply = client.generate_structured(
                system_prompt=_SYSTEM_FOR[args.mode],
                user_prompt=_leaf_list(scheme),
                image_parts=_pages(pages_from),
                response_schema=ReferenceReply,
                prompt_version=PROMPT_VERSION,
                model=OPUS,
                task_tag=TASK_TAG,
                cache_mode="read_write",
                extra_cache_key=f"{args.key}:{args.mode}",
            )
        finally:
            set_call_context(case_key=None)
            spent = cost_by_provider(process_call_records())
            ledger.add(spent)
            print(f"spend this call: {spent}")
    out = script_dir / f"marks_{args.mode}.json"
    out.write_text(
        json.dumps({"leaves": [leaf.model_dump() for leaf in reply.leaves]}, indent=1) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out} ({len(reply.leaves)} leaves)")
    return 0


def _adopt(args: argparse.Namespace) -> int:
    script_dir: Path = args.root / args.key
    if ref.is_frozen(script_dir):
        raise ref.ReferenceStateError(f"{script_dir} is frozen")
    marks = json.loads((script_dir / f"marks_{args.source}.json").read_text(encoding="utf-8"))
    source: ref.Source = "opus" if args.source == "opus" else "teacher_tick"
    leaves = leaves_from_marks(marks["leaves"], _scheme(script_dir), source)
    ref.write_reference(script_dir / ref.REFERENCE_FILE, leaves)
    print(f"reference {args.key}: {sum(l.mark for l in leaves)} marks from marks_{args.source}")
    return 0


def _review_list(args: argparse.Namespace) -> int:
    script_dir: Path = args.root / args.key
    reference = ref.read_reference(script_dir / ref.REFERENCE_FILE)
    others: list[ref.OtherMarks] = []
    confidence: dict[str, float] = {}
    ambiguous: list[str] = []
    for marks_file in sorted(script_dir.glob("marks_*.json")):
        rows = json.loads(marks_file.read_text(encoding="utf-8"))["leaves"]
        name = marks_file.stem.removeprefix("marks_")
        others.append(ref.OtherMarks(name, {str(r["question_id"]): int(r["mark"]) for r in rows}))
        source_name = "opus" if name == "opus" else "teacher_tick"
        for r in rows:
            qid = str(r["question_id"])
            if qid in reference and reference[qid].source == source_name:
                confidence[qid] = float(r["confidence"])
                if r.get("ambiguous"):
                    ambiguous.append(qid)
    for pair in args.prior:
        name, _, path = pair.partition("=")
        others.append(ref.OtherMarks(name, marks_from_correction(Path(path))))
    flagged = ref.check_first(
        reference,
        others=others,
        confidence=confidence,
        ambiguous=ambiguous,
        expected_total=args.expected_total,
    )
    out = script_dir / ref.REVIEW_FILE
    out.write_text(ref.render_review(args.key, reference, flagged), encoding="utf-8")
    print(f"{len(flagged)} of {len(reference)} leaves to check first: {out}")
    return 0


def _crop(args: argparse.Namespace) -> int:
    from lemely.io.rasterise import rasterise_scan_to_pages
    from lemely.io.reread import crop_and_upscale

    script_dir: Path = args.root / args.key
    pages = rasterise_scan_to_pages(Path(_inputs(script_dir)["scan"]))
    box: list[int] | None = None
    page_index = None if args.page is None else args.page - 1
    if args.extracted is not None:
        answers = json.loads(args.extracted.read_text(encoding="utf-8"))["answers"]
        for answer in answers:
            if answer["question_id"] == args.leaf and answer.get("source_box"):
                box = answer["source_box"]["box"]
                page_index = answer["source_box"]["page"]
    if page_index is None:
        raise ref.ReferenceStateError(f"no page for {args.leaf}: pass --page or --extracted")
    page = pages[page_index]
    data = crop_and_upscale(page, box, upscale=1) if box is not None else page.png_bytes
    args.out.write_bytes(data)
    print(f"wrote {args.out} (page {page_index + 1}{', cropped' if box else ''})")
    return 0


def _override(args: argparse.Namespace) -> int:
    leaf = ref.apply_override(args.root / args.key, args.leaf, args.mark, args.note)
    print(f"{args.key} {leaf.question_id}: {leaf.mark} / {leaf.max_marks} (user_override)")
    return 0


def _freeze(args: argparse.Namespace) -> int:
    script_dir: Path = args.root / args.key
    sources = {name: Path(p) for name, _, p in (s.partition("=") for s in args.source)}
    entry = ref.freeze(
        script_dir,
        key=args.key,
        scan_path=Path(_inputs(script_dir)["scan"]),
        sources=sources,
        expected_total=args.expected_total,
        manifest_path=args.root / ref.MANIFEST_FILE,
    )
    print(f"froze {entry.key}: reference sha256 {entry.reference_sha256[:12]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--root", type=Path, default=ref.REFERENCE_ROOT)
    parser.add_argument("--spend-file", type=Path, default=DEFAULT_SPEND_FILE)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare")
    p.add_argument("key")
    p.add_argument("--scan", type=Path, required=True)
    scheme = p.add_mutually_exclusive_group(required=True)
    scheme.add_argument("--scheme-json", type=Path)
    scheme.add_argument("--scheme-pdf", type=Path)
    p.set_defaults(fn=_prepare)

    p = sub.add_parser("mark")
    p.add_argument("key")
    p.add_argument("--mode", choices=sorted(_SYSTEM_FOR), required=True)
    p.add_argument("--truth", type=Path)
    p.add_argument("--max-usd", type=float, default=1.50, help="projected Anthropic cost")
    p.set_defaults(fn=_mark)

    p = sub.add_parser("adopt")
    p.add_argument("key")
    p.add_argument("--from", dest="source", choices=sorted(_SYSTEM_FOR), required=True)
    p.set_defaults(fn=_adopt)

    p = sub.add_parser("review-list")
    p.add_argument("key")
    p.add_argument("--prior", action="append", default=[], metavar="NAME=correction.json")
    p.add_argument("--expected-total", type=int)
    p.set_defaults(fn=_review_list)

    p = sub.add_parser("crop")
    p.add_argument("key")
    p.add_argument("--leaf", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--extracted", type=Path)
    p.add_argument("--page", type=int, help="1-based page when no extracted box is given")
    p.set_defaults(fn=_crop)

    p = sub.add_parser("override")
    p.add_argument("key")
    p.add_argument("--leaf", required=True)
    p.add_argument("--mark", type=int, required=True)
    p.add_argument("--note", default="")
    p.set_defaults(fn=_override)

    p = sub.add_parser("freeze")
    p.add_argument("key")
    p.add_argument("--expected-total", type=int)
    p.add_argument("--source", action="append", default=[], metavar="NAME=PATH")
    p.set_defaults(fn=_freeze)

    args = parser.parse_args(argv)
    try:
        return int(args.fn(args))
    except (ref.ReferenceStateError, SpendCapError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

Check while writing: `crop_and_upscale` takes `upscale` as a keyword (`lemely/io/reread.py:139`); `rasterise_scan_to_pages` returns `RasterisedPage` with `png_bytes` (`lemely/io/rasterise.py:636`). If `DeterministicMarkSchemeParser`'s constructor differs from `cfg=...`, read `BUILD/accuracy-runs/claude-e2e2-0625-w24-41-enh1/driver.py`, which calls it that way.

- [ ] **Step 4: Run the tests to watch them pass.**

Run: `.venv/bin/python -m pytest tests/test_build_reference_cli.py -q --no-cov -o addopts=""`
Expected: 8 passed.

- [ ] **Step 5: Prove the spend guard red.** Delete the `check_can_start(...)` line in `_mark`; run `test_mark_refuses_before_spend_when_the_cap_would_pass` and watch it fail (`AssertionError: must not build a client`). Revert; rerun: 8 passed.

- [ ] **Step 6: Gates and commit.**

```bash
.venv/bin/python -m pytest tests/test_build_reference_cli.py tests/test_reference.py tests/test_llm_golden.py -q --no-cov -o addopts=""
PATH=$PWD/.venv/bin:$PATH pre-commit run --files scripts/build_reference.py tests/test_build_reference_cli.py
git add -- scripts/build_reference.py tests/test_build_reference_cli.py
git commit -S -m "feat(reference): Opus-backed reference builder CLI" -- scripts/build_reference.py tests/test_build_reference_cli.py
```

---

### Task 3: Build the references (MAIN SESSION, live spend)

**MAIN SESSION — live spend.** Not for a subagent. Anthropic (Opus) only; about $0.40 to $0.80 per call, 7 calls, **expected $3 to $5**. Gemini $0 unless a scheme has to be parsed by the LLM parser (step 2, at most $0.10).

**Files:** writes only under `BUILD/accuracy-runs/claude-c-reference/` (gitignored by the BUILD rules; confirm with `git check-ignore -v BUILD/accuracy-runs/claude-c-reference/x` before starting, and stop if it is not ignored). Nothing is committed.

**Stop conditions:** stop and report when any call fails twice, when the ledger's anthropic total would pass $10.00 after this task (the builder's own pre-check stops at the $40 cap; this task stops far earlier), or when a teacher-tick total misses the teacher total by more than 6 marks (a sign the transcription is off, not the marking).

- [ ] **Step 1: Prepare the five scripts.**

```bash
B=".venv/bin/python scripts/build_reference.py"
$B prepare 0625_w24_41 --scan "$HOME/Documents/P4 N24 V1_annotated (NO Corrections).pdf" --scheme-json corpus/mark-schemes/0625_w24_ms_41.json
$B prepare 0625_s23_22 --scan "$HOME/testing/0625_s23_qp_22-(34..40).pdf" --scheme-json corpus/mark-schemes/0625_s23_ms_22.json
$B prepare 0625_w24_42 --scan tests/fixtures/handwritten-59/0625_w24_qp_42.pdf --scheme-json corpus/mark-schemes/0625_w24_ms_42.json
$B prepare 0625_s25_42 --scan tests/fixtures/handwritten-59/0625_s25_qp_42.pdf --scheme-pdf "$HOME/Documents/0625_s25_ms_42.pdf"
$B prepare 0625_w25_42 --scan tests/fixtures/handwritten-59/0625_w25_qp_42.pdf --scheme-pdf "$HOME/Documents/0625_w25_ms_42.pdf"
```

Expected: one `prepared ...` line each. Compare `0625_w24_41`'s leaf count with the E2E runs (43 marked leaves, 80 marks).

- [ ] **Step 2: Schemes the deterministic parser refuses.** `0625_s25_ms_42` is a known det failure (#88). If `prepare` exits 2 for s25 or w25, parse that PDF once with the LLM parser on the default Gemini path into the reference dir, then prepare from the JSON:

```bash
.venv/bin/lemely parse-mark-schemes --help   # read the flags first; write the JSON to BUILD/accuracy-runs/claude-c-reference/_schemes/
$B prepare 0625_s25_42 --scan tests/fixtures/handwritten-59/0625_s25_qp_42.pdf --scheme-json BUILD/accuracy-runs/claude-c-reference/_schemes/0625_s25_ms_42.json
```

If the LLM parse also fails, drop that script from the real set, record why in `.superpowers/sdd/c-p0-reference.md`, and go on with four. Do not hand-write a scheme.

- [ ] **Step 3: Teacher ticks for 0625/41** (the corrected copy goes only to this builder).

```bash
$B mark 0625_w24_41 --mode teacher --truth "$HOME/testing/0625_w24_qp_41-(66..80).pdf" --max-usd 1.5
$B mark 0625_w24_41 --mode opus --max-usd 1.5
$B adopt 0625_w24_41 --from teacher
```

- [ ] **Step 4: MCQ 0625/22.**

```bash
$B mark 0625_s23_22 --mode mcq --truth "$HOME/testing/0625_s23_qp_22-(34..40).pdf" --max-usd 1.0
$B adopt 0625_s23_22 --from mcq
```

- [ ] **Step 5: Opus marks for the three #59 scripts.**

```bash
for k in 0625_w24_42 0625_s25_42 0625_w25_42; do $B mark $k --mode opus --max-usd 1.5 && $B adopt $k --from opus; done
```

- [ ] **Step 6: Check-first lists.**

```bash
G=BUILD/accuracy-runs/e2e-0625-w24-41-2026-10-19/correction.json
C=BUILD/accuracy-runs/claude-e2e2-0625-w24-41-enh2/correction.json
$B review-list 0625_w24_41 --prior gemini=$G --prior claude=$C --expected-total 66
$B review-list 0625_s23_22 --expected-total 34
for k in 0625_w24_42 0625_s25_42 0625_w25_42; do $B review-list $k; done
cat BUILD/accuracy-runs/cost-ladder-spend.json
```

Record in `.superpowers/sdd/c-p0-reference.md` (gitignored): per script the leaf count, the reference total, the number of leaves to check first, and the ledger before and after. Counts only.

---

### Task 4: User review and freeze (MAIN SESSION, interactive)

**MAIN SESSION — interactive with the user.** $0.

- [ ] **Step 1: Walk each script's `REVIEW.md` with the user.** For each listed leaf, render the crop and show it with the scheme points and the three marks:

```bash
$B crop 0625_w24_41 --leaf 7c --extracted BUILD/accuracy-runs/claude-e2e2-0625-w24-41-enh2/extracted.json --out "$SCRATCH/crop.png"   # $SCRATCH: the session scratchpad directory
```

(For the #59 scripts and 0625/22 there is no extracted.json: use `--page N` from the marks file's `page`.) Read the PNG with the Read tool so the user sees it, quote the leaf's scheme points from `mark_scheme.json` and the marks from `REVIEW.md`, and ask for a mark or "ok". On a mark, run `$B override <key> --leaf <qid> --mark <n> --note "<user's words>"`. On "ok", change nothing.

- [ ] **Step 2: Totals.** Rerun `review-list` with the same arguments. 0625/41 must total 66 and 0625/22 34 before freezing. If either does not, show the user the remaining gap leaves and repeat step 1.

- [ ] **Step 3: Freeze.**

```bash
$B freeze 0625_w24_41 --expected-total 66 --source "corrected_copy=$HOME/testing/0625_w24_qp_41-(66..80).pdf"
$B freeze 0625_s23_22 --expected-total 34 --source "marked_copy=$HOME/testing/0625_s23_qp_22-(34..40).pdf"
for k in 0625_w24_42 0625_s25_42 0625_w25_42; do $B freeze $k; done
.venv/bin/python -c "from lemely.accuracy.reference import read_manifest, REFERENCE_ROOT, MANIFEST_FILE; print([e.key for e in read_manifest(REFERENCE_ROOT / MANIFEST_FILE)])"
```

Expected: the five keys (or four, per Task 3 step 2). Append the frozen totals and digests' first 12 characters to `.superpowers/sdd/c-p0-reference.md`.

---
## Phase P1: Harness, real split and three judges

### Task 5: Real fields on `RunSummary`, `Verdict.notes`, and the new judges

**Files:**
- Modify: `lemely/accuracy/cost_ladder/gate.py` (whole file shown below)
- Test: `tests/test_cost_ladder_judges.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces (Tasks 6 to 9, 28 rely on these exact names):
  - `RunSummary` gains, all defaulted so every existing constructor call and test is unchanged: `real_scripts: tuple[str, ...] = ()`, `real_abs_error: float = 0.0`, `real_abs_error_by_run: tuple[float, ...] = ()`, `real_exact_rate: float | None = None`, `real_within1_rate: float | None = None`, `real_review_rate: float | None = None`, `real_binding_passes: float = 0.0`, `real_usd_mean: float = 0.0`, `real_usd_by_script: tuple[tuple[str, float], ...] = ()`, `real_usd_max_by_script: tuple[tuple[str, float], ...] = ()`, `real_latency_by_script: tuple[tuple[str, float], ...] = ()`, `real_escalation_rate: float | None = None`, `real_escalation_rate_max_script: float | None = None`, `real_escalation_usd_by_script: tuple[tuple[str, float], ...] = ()`, `real_escalation_triggers: tuple[tuple[str, int], ...] = ()`, `real_incomplete: tuple[str, ...] = ()`.
  - `Verdict` gains `notes: tuple[str, ...] = ()` (reported, never judged).
  - Constants `REAL_SCRIPT_CAP_USD = 0.10`, `ACCURACY_REVIEW_RISE = 0.05`, `FLIP_REVIEW_MARGIN = 0.10`.
  - `real_aa_floor(a: RunSummary, b: RunSummary) -> float` (abs difference of the two runs' `real_abs_error`).
  - `escalation_notes(c: RunSummary) -> tuple[str, ...]`.
  - `judge_cost_lever(baseline, candidate, *, aa_floor: int, real_aa_floor: float, original_latency_p95_ms: float) -> Verdict`.
  - `judge_accuracy_lever(baseline, candidate, *, aa_floor: int, real_aa_floor: float) -> Verdict`.
  - `judge_flip(gemini, candidate, *, aa_floor: int) -> Verdict`.
  - `judge_record(baseline, candidate) -> Verdict` (the fit rung: passes unless incomplete).

- [ ] **Step 1: Write the failing tests.** Create `tests/test_cost_ladder_judges.py`:

```python
"""Sub-project C P1: the accuracy and flip judges, and the real-split checks of the cost judge.

Each check is proven red on a crafted summary that fails only that check.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from lemely.accuracy.cost_ladder.gate import (
    RunSummary,
    escalation_notes,
    judge_accuracy_lever,
    judge_cost_lever,
    judge_flip,
    judge_record,
    real_aa_floor,
)

SCRIPTS = ("0625_s23_22", "0625_w24_41")


def _s(**kw: object) -> RunSummary:
    base = RunSummary(
        usd_per_script_mean=0.05,
        latency_p95_ms=1000.0,
        mismarked_parts=frozenset(),
        scored_parts=78,
        id_match_rate=1.0,
        validity_rate=1.0,
        incomplete=(),
        real_scripts=SCRIPTS,
        real_abs_error=20.0,
        real_abs_error_by_run=(20.0, 20.0),
        real_exact_rate=0.8,
        real_within1_rate=0.9,
        real_review_rate=0.30,
        real_binding_passes=2.0,
        real_usd_mean=0.05,
        real_usd_by_script=(("0625_s23_22", 0.02), ("0625_w24_41", 0.05)),
        real_usd_max_by_script=(("0625_s23_22", 0.02), ("0625_w24_41", 0.06)),
        real_escalation_rate=0.05,
        real_escalation_rate_max_script=0.07,
        real_escalation_usd_by_script=(("0625_s23_22", 0.0), ("0625_w24_41", 0.01)),
        real_escalation_triggers=(("confidence", 3),),
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def test_defaults_keep_a_dev_only_summary_unchanged() -> None:
    s = RunSummary(1.0, 1.0, frozenset(), 1, 1.0, 1.0, ())
    assert s.real_scripts == () and s.real_abs_error == 0.0 and s.real_review_rate is None


def test_real_aa_floor_is_the_abs_difference() -> None:
    assert real_aa_floor(_s(real_abs_error=20.0), _s(real_abs_error=17.5)) == 2.5


# --- judge_accuracy_lever -------------------------------------------------------------


def test_accuracy_lever_passes_when_abs_error_falls_by_the_floor() -> None:
    v = judge_accuracy_lever(_s(), _s(real_abs_error=18.0), aa_floor=0, real_aa_floor=2.0)
    assert v.passed, v.reasons


def test_accuracy_lever_fails_when_abs_error_falls_less_than_the_floor() -> None:
    v = judge_accuracy_lever(_s(), _s(real_abs_error=19.0), aa_floor=0, real_aa_floor=2.0)
    assert not v.passed
    assert v.reasons == ("real abs error fell by 1.00 marks, less than the A/A floor 2.00",)


def test_accuracy_lever_fails_on_extra_synthetic_mismarks() -> None:
    v = judge_accuracy_lever(
        _s(), _s(real_abs_error=15.0, mismarked_parts=frozenset({"c/1a", "c/2b"})),
        aa_floor=1, real_aa_floor=0.0,
    )
    assert v.reasons == ("2 newly mismarked synthetic parts exceed the A/A floor 1",)


def test_accuracy_lever_fails_when_any_script_passes_ten_cents() -> None:
    v = judge_accuracy_lever(
        _s(), _s(real_abs_error=15.0,
                 real_usd_max_by_script=(("0625_s23_22", 0.02), ("0625_w24_41", 0.1001))),
        aa_floor=0, real_aa_floor=0.0,
    )
    assert v.reasons == ("0625_w24_41 $0.1001 exceeds $0.10 per script",)


def test_review_rise_fails_only_when_abs_error_did_not_fall() -> None:
    flat = judge_accuracy_lever(_s(), _s(real_review_rate=0.36), aa_floor=0, real_aa_floor=0.0)
    assert flat.reasons == (
        "review rate rose 6.0 points (more than 5) while real abs error did not fall",
    )
    fell = judge_accuracy_lever(
        _s(), _s(real_review_rate=0.36, real_abs_error=19.0), aa_floor=0, real_aa_floor=0.0
    )
    assert fell.passed


def test_accuracy_lever_fails_on_incomplete_and_on_missing_real_split() -> None:
    v = judge_accuracy_lever(_s(), _s(real_abs_error=15.0, incomplete=("real-1:0625_w24_41 (x)",)),
                             aa_floor=0, real_aa_floor=0.0)
    assert v.reasons == ("incomplete cases: real-1:0625_w24_41 (x)",)
    v = judge_accuracy_lever(_s(), _s(real_scripts=()), aa_floor=0, real_aa_floor=0.0)
    assert "candidate has no real-split results" in v.reasons


def test_accuracy_lever_rejects_negative_floors() -> None:
    with pytest.raises(ValueError):
        judge_accuracy_lever(_s(), _s(), aa_floor=0, real_aa_floor=-1.0)


# --- judge_cost_lever -----------------------------------------------------------------


def test_cost_lever_dev_only_is_the_existing_judge() -> None:
    dev = RunSummary(1.0, 1000.0, frozenset(), 10, 1.0, 1.0, ())
    v = judge_cost_lever(dev, replace(dev, usd_per_script_mean=0.9), aa_floor=0,
                         real_aa_floor=0.0, original_latency_p95_ms=1000.0)
    assert v.passed and v.notes == ()


def test_cost_lever_real_only_skips_the_empty_dev_split() -> None:
    empty = {"usd_per_script_mean": 0.0, "scored_parts": 0}
    v = judge_cost_lever(_s(**empty), _s(**empty, real_usd_mean=0.04), aa_floor=0,
                         real_aa_floor=0.0, original_latency_p95_ms=0.0)
    assert v.passed, v.reasons


def test_cost_lever_fails_when_real_abs_error_rises_past_the_floor() -> None:
    v = judge_cost_lever(_s(), _s(real_abs_error=23.0), aa_floor=0, real_aa_floor=2.0,
                         original_latency_p95_ms=1000.0)
    assert v.reasons == ("real abs error rose by 3.00 marks, above the A/A floor 2.00",)


def test_cost_lever_fails_when_real_cost_rises() -> None:
    v = judge_cost_lever(_s(), _s(real_usd_mean=0.051), aa_floor=0, real_aa_floor=0.0,
                         original_latency_p95_ms=1000.0)
    assert v.reasons == ("real cost rose from $0.0500 to $0.0510 per script",)


def test_cost_lever_fails_when_a_script_passes_ten_cents() -> None:
    v = judge_cost_lever(_s(), _s(real_usd_max_by_script=(("0625_w24_41", 0.11),)),
                         aa_floor=0, real_aa_floor=0.0, original_latency_p95_ms=1000.0)
    assert "0625_w24_41 $0.1100 exceeds $0.10 per script" in v.reasons


def test_cost_lever_reports_real_saving_and_escalation() -> None:
    v = judge_cost_lever(_s(), _s(real_usd_mean=0.04), aa_floor=0, real_aa_floor=0.0,
                         original_latency_p95_ms=1000.0)
    assert v.passed
    assert v.notes[0] == "real saving 20.0%"
    assert "escalation rate 5.0% (max script 7.0%)" in v.notes


# --- judge_flip -----------------------------------------------------------------------


def test_flip_passes_when_no_worse_than_gemini() -> None:
    gemini = _s(real_abs_error=22.0, real_binding_passes=1.0, real_review_rate=0.21)
    v = judge_flip(gemini, _s(), aa_floor=0)
    assert v.passed, v.reasons


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        (_s(real_abs_error=22.5), "real abs error 22.50 is above Gemini's 22.00"),
        (_s(mismarked_parts=frozenset({"c/1a"})),
         "1 synthetic parts mismarked against Gemini's set exceed the A/A floor 0"),
        (_s(real_usd_max_by_script=(("0625_w24_41", 0.12),)),
         "0625_w24_41 $0.1200 exceeds $0.10 per script"),
        (_s(real_binding_passes=0.5), "binding passes 0.5 are below Gemini's 1.0"),
        (_s(real_review_rate=0.32), "review rate 32.0% is more than 10 points above Gemini's 21.0%"),
        (_s(incomplete=("real-2:0625_s23_22 (x)",)), "incomplete cases: real-2:0625_s23_22 (x)"),
        (_s(real_scripts=("0625_w24_41",)), "real scripts differ from Gemini's"),
    ],
)
def test_flip_fails_on_each_check(candidate: RunSummary, reason: str) -> None:
    gemini = _s(real_abs_error=22.0, real_binding_passes=1.0, real_review_rate=0.21)
    v = judge_flip(gemini, candidate, aa_floor=0)
    assert not v.passed
    assert reason in v.reasons


def test_flip_reports_escalation_next_to_its_checks() -> None:
    v = judge_flip(_s(real_abs_error=22.0), _s(), aa_floor=0)
    assert any(n.startswith("escalation rate") for n in v.notes)
    assert "0625_w24_41 escalation $0.0100 (20.0% of script)" in v.notes


def test_escalation_notes_empty_without_real_split() -> None:
    assert escalation_notes(RunSummary(1.0, 1.0, frozenset(), 1, 1.0, 1.0, ())) == ()


def test_record_judge_passes_unless_incomplete() -> None:
    assert judge_record(_s(), _s()).passed
    assert not judge_record(_s(), _s(incomplete=("x",))).passed
```

- [ ] **Step 2: Run the tests to watch them fail.**

Run: `.venv/bin/python -m pytest tests/test_cost_ladder_judges.py -q --no-cov -o addopts=""`
Expected: `ImportError: cannot import name 'escalation_notes'`.

- [ ] **Step 3: Write the code.** Replace `lemely/accuracy/cost_ladder/gate.py` with:

```python
"""Pure accept/reject gates for the cost ladder: cost levers, accuracy levers, the flip. No I/O."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal

BIG_TIER_SAVING = 0.30
BIG_TIER_ALLOWED_FRACTION = 0.02
BIG_TIER_TOLERANCE = 1e-9  # 1 - 0.07/0.1 is 0.29999999999999993, not 0.3
LATENCY_FACTOR = 2.0
#: Spec 2026-10-24 global constraint: every real script, not the mean.
REAL_SCRIPT_CAP_USD = 0.10
#: judge_accuracy_lever: the review rate may rise this much unless abs_error fell.
ACCURACY_REVIEW_RISE = 0.05
#: judge_flip: the candidate's review rate may be this far above Gemini's.
FLIP_REVIEW_MARGIN = 0.10
_EPS = 1e-9


@dataclass(frozen=True)
class RunSummary:
    usd_per_script_mean: float  # at 2027 rates
    latency_p95_ms: float  # per script
    mismarked_parts: frozenset[str]  # "<case_key>/<question_id>" with predicted != truth
    scored_parts: int
    id_match_rate: float
    validity_rate: float  # structured outputs parsed / attempted
    incomplete: tuple[str, ...]  # case keys with a failed call or missing leaf
    # Real split (sub-project C). Defaults: a dev-only run, as before.
    real_scripts: tuple[str, ...] = ()
    real_abs_error: float = 0.0  # mean over the runs of sum |mark - reference|
    real_abs_error_by_run: tuple[float, ...] = ()
    real_exact_rate: float | None = None
    real_within1_rate: float | None = None
    real_review_rate: float | None = None
    real_binding_passes: float = 0.0  # mean over the runs of scripts with verdict "pass"
    real_usd_mean: float = 0.0  # 2027 USD, mean over scripts and runs
    real_usd_by_script: tuple[tuple[str, float], ...] = ()  # mean over the runs
    real_usd_max_by_script: tuple[tuple[str, float], ...] = ()  # highest run: the cap check
    real_latency_by_script: tuple[tuple[str, float], ...] = ()  # wall clock ms, mean
    real_escalation_rate: float | None = None  # escalated leaves / leaves, mean
    real_escalation_rate_max_script: float | None = None
    real_escalation_usd_by_script: tuple[tuple[str, float], ...] = ()
    real_escalation_triggers: tuple[tuple[str, int], ...] = ()
    real_incomplete: tuple[str, ...] = ()


@dataclass(frozen=True)
class Verdict:
    passed: bool
    tier: Literal["small", "big"]
    saving: float  # 1 - candidate/baseline usd
    extra_mismarks: int
    allowed_extra: int
    reasons: tuple[str, ...]  # every failed check, human-readable
    notes: tuple[str, ...] = ()  # reported beside the checks, never judged


def aa_floor(a: RunSummary, b: RunSummary) -> int:
    """Churn between two runs of the same config: the symmetric difference."""
    return len(a.mismarked_parts ^ b.mismarked_parts)


def real_aa_floor(a: RunSummary, b: RunSummary) -> float:
    """Real-split noise: the abs_error difference between two identical base runs."""
    return abs(a.real_abs_error - b.real_abs_error)


def judge(
    baseline: RunSummary,
    candidate: RunSummary,
    *,
    aa_floor: int,
    original_latency_p95_ms: float,
) -> Verdict:
    ...  # unchanged: keep the existing body exactly as it is


def _saving(base_usd: float, candidate_usd: float) -> float:
    return 0.0 if base_usd == 0 else 1 - candidate_usd / base_usd


def _over_cap(candidate: RunSummary) -> list[str]:
    return [
        f"{key} ${usd:.4f} exceeds ${REAL_SCRIPT_CAP_USD:.2f} per script"
        for key, usd in candidate.real_usd_max_by_script
        if usd > REAL_SCRIPT_CAP_USD + _EPS
    ]


def _missing_real(baseline: RunSummary, candidate: RunSummary, other: str) -> list[str]:
    return [
        f"{who} has no real-split results"
        for who, summary in ((other, baseline), ("candidate", candidate))
        if not summary.real_scripts
    ]


def _pct(rate: float | None) -> str:
    return "-" if rate is None else f"{rate * 100:.1f}%"


def escalation_notes(c: RunSummary) -> tuple[str, ...]:
    """Escalation rate, dollars and triggers of a real-split run (spec "Escalation rate")."""
    if c.real_escalation_rate is None:
        return ()
    notes = [
        f"escalation rate {_pct(c.real_escalation_rate)} "
        f"(max script {_pct(c.real_escalation_rate_max_script)})"
    ]
    usd = dict(c.real_usd_by_script)
    for key, esc in c.real_escalation_usd_by_script:
        total = usd.get(key, 0.0)
        share = f"{esc / total * 100:.1f}%" if total else "-"
        notes.append(f"{key} escalation ${esc:.4f} ({share} of script)")
    if c.real_escalation_triggers:
        notes.append(
            "triggers " + ", ".join(f"{name}={n}" for name, n in c.real_escalation_triggers)
        )
    return tuple(notes)


def _incomplete(candidate: RunSummary) -> list[str]:
    return ["incomplete cases: " + ", ".join(candidate.incomplete)] if candidate.incomplete else []


def judge_cost_lever(
    baseline: RunSummary,
    candidate: RunSummary,
    *,
    aa_floor: int,
    real_aa_floor: float,
    original_latency_p95_ms: float,
) -> Verdict:
    """`judge`, plus the real split when either side has it.

    A cost lever may not raise real abs_error by more than the real A/A floor, may
    not raise the mean real cost, and must keep every real script at or below the
    cap. Dev-only summaries are judged by `judge` alone.
    """
    if baseline.real_scripts and baseline.scored_parts == 0 and candidate.scored_parts == 0:
        # A real-only rung: its dev split is empty, and `judge` would fail it on a zero cost.
        verdict = Verdict(
            passed=True, tier="small", saving=0.0, extra_mismarks=0, allowed_extra=aa_floor,
            reasons=(),
        )
    else:
        verdict = judge(
            baseline, candidate, aa_floor=aa_floor, original_latency_p95_ms=original_latency_p95_ms
        )
    if not baseline.real_scripts and not candidate.real_scripts:
        return verdict
    reasons = list(verdict.reasons) + _missing_real(baseline, candidate, "baseline")
    if baseline.real_scripts and candidate.real_scripts:
        rise = candidate.real_abs_error - baseline.real_abs_error
        if rise > real_aa_floor + _EPS:
            reasons.append(
                f"real abs error rose by {rise:.2f} marks, above the A/A floor {real_aa_floor:.2f}"
            )
        if candidate.real_usd_mean > baseline.real_usd_mean + _EPS:
            reasons.append(
                f"real cost rose from ${baseline.real_usd_mean:.4f} to "
                f"${candidate.real_usd_mean:.4f} per script"
            )
        if candidate.real_scripts != baseline.real_scripts:
            reasons.append("real scripts differ from the baseline's")
    reasons += _over_cap(candidate)
    notes = (
        f"real saving {_saving(baseline.real_usd_mean, candidate.real_usd_mean) * 100:.1f}%",
        *escalation_notes(candidate),
    )
    return replace(verdict, passed=not reasons, reasons=tuple(reasons), notes=notes)


def judge_accuracy_lever(
    baseline: RunSummary,
    candidate: RunSummary,
    *,
    aa_floor: int,
    real_aa_floor: float,
) -> Verdict:
    """A lever that adds cost or aims at accuracy (spec P1, judge 2).

    Passes when real abs_error falls by at least the real A/A floor, synthetic extra
    mismarks stay within the dev floor, every real script is at most the cap, and the
    review rate rises by no more than 5 points unless abs_error fell.
    """
    if aa_floor < 0 or real_aa_floor < 0:
        raise ValueError(f"floors must be non-negative, got {aa_floor} and {real_aa_floor}")
    reasons = _missing_real(baseline, candidate, "baseline")
    fall = baseline.real_abs_error - candidate.real_abs_error
    if not reasons and fall + _EPS < real_aa_floor:
        reasons.append(
            f"real abs error fell by {fall:.2f} marks, less than the A/A floor {real_aa_floor:.2f}"
        )
    extra = len(candidate.mismarked_parts - baseline.mismarked_parts)
    if extra > aa_floor:
        reasons.append(
            f"{extra} newly mismarked synthetic parts exceed the A/A floor {aa_floor}"
        )
    if candidate.scored_parts != baseline.scored_parts:
        reasons.append(
            f"scored parts changed from {baseline.scored_parts} to "
            f"{candidate.scored_parts} (narrowed screen)"
        )
    reasons += _over_cap(candidate)
    if baseline.real_review_rate is not None and candidate.real_review_rate is not None:
        rise = candidate.real_review_rate - baseline.real_review_rate
        if rise > ACCURACY_REVIEW_RISE + _EPS and not fall > _EPS:
            reasons.append(
                f"review rate rose {rise * 100:.1f} points (more than "
                f"{ACCURACY_REVIEW_RISE * 100:.0f}) while real abs error did not fall"
            )
    reasons += _incomplete(candidate)
    return Verdict(
        passed=not reasons,
        tier="small",
        saving=_saving(baseline.real_usd_mean, candidate.real_usd_mean),
        extra_mismarks=extra,
        allowed_extra=aa_floor,
        reasons=tuple(reasons),
        notes=escalation_notes(candidate),
    )


def judge_flip(gemini: RunSummary, candidate: RunSummary, *, aa_floor: int) -> Verdict:
    """The stacked Claude configuration against a Gemini rung (spec P1, judge 3)."""
    if aa_floor < 0:
        raise ValueError(f"aa_floor must be non-negative, got {aa_floor}")
    reasons = _missing_real(gemini, candidate, "Gemini rung")
    if not reasons:
        if candidate.real_abs_error > gemini.real_abs_error + _EPS:
            reasons.append(
                f"real abs error {candidate.real_abs_error:.2f} is above Gemini's "
                f"{gemini.real_abs_error:.2f}"
            )
        if candidate.real_scripts != gemini.real_scripts:
            reasons.append("real scripts differ from Gemini's")
        if candidate.real_binding_passes + _EPS < gemini.real_binding_passes:
            reasons.append(
                f"binding passes {candidate.real_binding_passes:.1f} are below Gemini's "
                f"{gemini.real_binding_passes:.1f}"
            )
        cand_rate = candidate.real_review_rate or 0.0
        gem_rate = gemini.real_review_rate or 0.0
        if cand_rate > gem_rate + FLIP_REVIEW_MARGIN + _EPS:
            reasons.append(
                f"review rate {_pct(cand_rate)} is more than "
                f"{FLIP_REVIEW_MARGIN * 100:.0f} points above Gemini's {_pct(gem_rate)}"
            )
    extra = len(candidate.mismarked_parts - gemini.mismarked_parts)
    if extra > aa_floor:
        reasons.append(
            f"{extra} synthetic parts mismarked against Gemini's set exceed the A/A floor "
            f"{aa_floor}"
        )
    reasons += _over_cap(candidate)
    reasons += _incomplete(candidate)
    notes = (
        f"real abs error {candidate.real_abs_error:.2f} vs Gemini {gemini.real_abs_error:.2f}",
        f"review rate {_pct(candidate.real_review_rate)} vs Gemini "
        f"{_pct(gemini.real_review_rate)}",
        f"binding passes {candidate.real_binding_passes:.1f} vs Gemini "
        f"{gemini.real_binding_passes:.1f}",
        *escalation_notes(candidate),
    )
    return Verdict(
        passed=not reasons,
        tier="small",
        saving=_saving(gemini.real_usd_mean, candidate.real_usd_mean),
        extra_mismarks=extra,
        allowed_extra=aa_floor,
        reasons=tuple(reasons),
        notes=notes,
    )


def judge_record(baseline: RunSummary, candidate: RunSummary) -> Verdict:
    """A rung recorded, not judged (the fitted thresholds): it passes unless incomplete."""
    reasons = _incomplete(candidate)
    return Verdict(
        passed=not reasons,
        tier="small",
        saving=_saving(baseline.real_usd_mean, candidate.real_usd_mean),
        extra_mismarks=len(candidate.mismarked_parts - baseline.mismarked_parts),
        allowed_extra=0,
        reasons=tuple(reasons),
        notes=("recorded, not judged", *escalation_notes(candidate)),
    )
```

The `judge` body stays byte-for-byte what it is today; the `...` above means "keep it", do not type an ellipsis. `math` stays imported for `judge`.

- [ ] **Step 4: Run the new and the existing gate tests.**

Run: `.venv/bin/python -m pytest tests/test_cost_ladder_judges.py tests/test_cost_ladder_gate.py tests/test_cost_ladder_runner.py tests/test_cost_ladder_review_rate.py -q --no-cov -o addopts=""`
Expected: all pass (the runner and report tests still construct `RunSummary` and `Verdict` positionally with 7 and 6 fields).

- [ ] **Step 5: Prove the checks red.** For each of these, break the code, run the named test, watch it fail, revert:
  - `_over_cap`: change `>` to `<`; `test_accuracy_lever_fails_when_any_script_passes_ten_cents` fails.
  - `judge_flip`: delete the binding-passes check; `test_flip_fails_on_each_check[candidate3-...]` fails.
  - `judge_accuracy_lever`: change `fall + _EPS < real_aa_floor` to `False`; `test_accuracy_lever_fails_when_abs_error_falls_less_than_the_floor` fails.
  - `judge_cost_lever`: delete the real-cost check; `test_cost_lever_fails_when_real_cost_rises` fails.
  Rerun the file: all pass.

- [ ] **Step 6: Gates and commit.**

```bash
.venv/bin/python -m pytest tests/test_cost_ladder_judges.py tests/test_cost_ladder_gate.py tests/test_llm_golden.py -q --no-cov -o addopts=""
PATH=$PWD/.venv/bin:$PATH pre-commit run --files lemely/accuracy/cost_ladder/gate.py tests/test_cost_ladder_judges.py
git add -- lemely/accuracy/cost_ladder/gate.py tests/test_cost_ladder_judges.py
git commit -S -m "feat(cost_ladder): real-split summary fields, accuracy and flip judges" -- lemely/accuracy/cost_ladder/gate.py tests/test_cost_ladder_judges.py
```

---
### Task 6: The real split: frozen scripts, production-path marking, per-leaf scoring

**Files:**
- Create: `lemely/accuracy/cost_ladder/real_split.py`
- Test: `tests/test_cost_ladder_real_split.py` (new)

**Interfaces:**
- Consumes: Task 1 (`read_manifest`, `read_reference`, `sha256_file`, `ReferenceLeaf`, `REFERENCE_ROOT`, `MANIFEST_FILE`); Task 5 (`RunSummary` real field names). Existing: `CallRecord`, `GeminiClient`, `script_cost_scope` (`lemely.io.gemini`), `ScanMetadataExtractor` (`lemely.io.scan_metadata`), `GeminiAnswerExtractor` (`lemely.io.answer_extraction`), `correct_paper` (`lemely.io.correction_ai`), `CorrectionResult` (`lemely.core.schemas`), `MarkScheme` (`lemely.core.loose_schemas`), `Settings`.
- Produces (Tasks 7, 8, 10, 11, 22 rely on these):
  - `DEFAULT_MANIFEST: Path` (= `REFERENCE_ROOT / MANIFEST_FILE`).
  - `@dataclass(frozen=True) RealScript(key, scan_path: Path, scheme_path: Path, reference_path: Path, reference_sha256, scheme_sha256, scan_sha256)`.
  - `class ReferenceDrift(RuntimeError)`.
  - `load_real_scripts(manifest_path: Path = DEFAULT_MANIFEST, *, only: Sequence[str] = ()) -> list[RealScript]` (raises `ReferenceDrift` on any missing file or sha256 mismatch, before any spend).
  - `mark_real_script(script: RealScript, client: GeminiClient, settings: Settings) -> CorrectionResult` (the production path: scan metadata, binder extraction, correction, all inside `script_cost_scope`).
  - `@dataclass(frozen=True) LeafOutcome(question_id, predicted: int, reference: int, max_marks: int, needs_review: bool, confidence: float | None, marker_source: str | None, review_reason: str | None, escalated: bool, trigger: str | None, pre_escalation_confidence: float | None)` with property `abs_error: int`.
  - `@dataclass(frozen=True) RealScriptResult(key, leaves: tuple[LeafOutcome, ...], binding_verdict: str | None, usd: float, escalation_usd: float, adjudication_usd: float, latency_ms: float, incomplete: str | None)` with properties `abs_error: int`, `escalated: int`.
  - `ESCALATION_TAG = "escalation"`, `ADJUDICATION_TAG = "adjudication"`.
  - `score_script(script, correction, records, *, latency_ms, failure, escalations, cascade_enabled) -> RealScriptResult`.
  - `real_summary_fields(runs: Sequence[Sequence[RealScriptResult]]) -> dict[str, object]` (keys are exactly the Task 5 `real_*` field names).
  - `write_real_results(path, results) -> None`, `read_real_results(path) -> list[RealScriptResult]`.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_cost_ladder_real_split.py`:

```python
"""Sub-project C P1: the real split's loader, scoring and aggregation. No model calls."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from lemely.accuracy import reference as ref
from lemely.accuracy.cost_ladder import real_split as rs
from lemely.accuracy.cost_ladder.real_split import LeafOutcome, RealScriptResult, ReferenceDrift
from lemely.core.schemas import CorrectedQuestion, CorrectionResult, ExamMetadata
from lemely.io.gemini import CallRecord


def _frozen(tmp_path: Path, key: str = "k", marks: dict[str, int] | None = None) -> rs.RealScript:
    d = tmp_path / key
    leaves = [
        ref.ReferenceLeaf(qid, m, 2, "opus", "e")
        for qid, m in (marks or {"1a": 2, "1b": 1, "1c": 0}).items()
    ]
    ref.write_reference(d / ref.REFERENCE_FILE, leaves)
    (d / ref.SCHEME_FILE).write_text("{}", encoding="utf-8")
    scan = tmp_path / f"{key}.pdf"
    scan.write_bytes(b"%PDF " + key.encode())
    ref.freeze(d, key=key, scan_path=scan, sources={}, expected_total=None,
               manifest_path=tmp_path / ref.MANIFEST_FILE)
    (script,) = rs.load_real_scripts(tmp_path / ref.MANIFEST_FILE, only=[key])
    return script


def _cq(qid: str, awarded: int, *, source: str = "ai", review: bool = False,
        conf: float = 0.9, reason: str | None = None) -> CorrectedQuestion:
    return CorrectedQuestion(
        question_id=qid, awarded_marks=awarded, maximum_marks=2, confidence="high",
        confidence_score=conf, needs_teacher_review=review, marker_source=source,
        review_reason=reason,
    )


def _result(*qs: CorrectedQuestion) -> CorrectionResult:
    meta = ExamMetadata(subject_code="0625", paper_number=4, paper_variant=1,
                        session_month="Oct/Nov", session_year=2024)
    return CorrectionResult(metadata=meta, questions=list(qs))


def _rec(tag: str, usd: float, qid: str | None = None, key: str = "k") -> CallRecord:
    return CallRecord(provider="anthropic", task_tag=tag, model="claude-haiku-5-5", thinking="low",
                      input_tokens=1, cached_tokens=0, output_tokens=1, thinking_tokens=0,
                      usd_now=usd, usd_2027=usd, latency_ms=10, attempt=None, question_id=qid,
                      case_key=key, parse_ok=True)


def test_loader_returns_frozen_scripts(tmp_path: Path) -> None:
    _frozen(tmp_path, "a")
    _frozen(tmp_path, "b")
    assert [s.key for s in rs.load_real_scripts(tmp_path / ref.MANIFEST_FILE)] == ["a", "b"]


def test_loader_refuses_a_changed_reference(tmp_path: Path) -> None:
    script = _frozen(tmp_path)
    script.reference_path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ReferenceDrift, match="reference .* sha256 differs"):
        rs.load_real_scripts(tmp_path / ref.MANIFEST_FILE)


def test_loader_refuses_a_missing_scan_and_an_empty_manifest(tmp_path: Path) -> None:
    script = _frozen(tmp_path)
    script.scan_path.unlink()
    with pytest.raises(ReferenceDrift, match="scan .* is missing"):
        rs.load_real_scripts(tmp_path / ref.MANIFEST_FILE)
    with pytest.raises(ReferenceDrift, match="lists no scripts"):
        rs.load_real_scripts(tmp_path / "none.json")


def test_loader_only_unknown_key_is_refused(tmp_path: Path) -> None:
    _frozen(tmp_path)
    with pytest.raises(ReferenceDrift, match="zz"):
        rs.load_real_scripts(tmp_path / ref.MANIFEST_FILE, only=["zz"])


def test_scoring_counts_dropped_missing_and_absent_leaves_as_zero(tmp_path: Path) -> None:
    script = _frozen(tmp_path, marks={"1a": 2, "1b": 1, "1c": 2})
    correction = _result(_cq("1a", 2), _cq("1b", 1, source="dropped", review=True))
    result = rs.score_script(script, correction, [], latency_ms=5.0, failure=None,
                             escalations=[], cascade_enabled=False)
    by = {l.question_id: l for l in result.leaves}
    assert by["1b"].predicted == 0 and by["1c"].predicted == 0
    assert by["1c"].needs_review is True  # a leaf the correction lost goes to review
    assert result.abs_error == 3 and result.incomplete is None
    assert len(result.leaves) == 3  # the denominator never shrinks


def test_failed_ai_marking_makes_the_script_incomplete(tmp_path: Path) -> None:
    script = _frozen(tmp_path)
    correction = _result(_cq("1a", 0, source="missing", review=True,
                             reason="AI marking failed: boom"), _cq("1b", 1), _cq("1c", 0))
    result = rs.score_script(script, correction, [], latency_ms=0.0, failure=None,
                             escalations=[], cascade_enabled=False)
    assert result.incomplete == "marking failed on 1a"


def test_no_correction_is_incomplete_with_the_failure(tmp_path: Path) -> None:
    script = _frozen(tmp_path)
    result = rs.score_script(script, None, [], latency_ms=0.0, failure="TimeoutError: x",
                             escalations=[], cascade_enabled=False)
    assert result.incomplete == "TimeoutError: x"
    assert [l.predicted for l in result.leaves] == [0, 0, 0]


def test_unpriced_call_makes_the_script_incomplete(tmp_path: Path) -> None:
    script = _frozen(tmp_path)
    rec = replace(_rec("correction", math.nan), model="claude-x")
    result = rs.score_script(script, _result(_cq("1a", 2), _cq("1b", 1), _cq("1c", 0)), [rec],
                             latency_ms=0.0, failure=None, escalations=[], cascade_enabled=False)
    assert result.incomplete == "unpriced model claude-x"


def test_escalation_costs_triggers_and_pre_escalation_confidence(tmp_path: Path) -> None:
    script = _frozen(tmp_path)
    records = [_rec("correction", 0.01, "1a"), _rec("escalation", 0.02, "1a"),
               _rec("adjudication", 0.005, "1b")]
    events = [
        {"question_id": "1a", "confidence": 0.7, "escalation_model": "claude-haiku-5-5 (thinking)"},
        {"question_id": "1a", "confidence": 0.75, "escalation_model": "claude-sonnet-5-5"},
    ]
    correction = _result(_cq("1a", 2, conf=0.95), _cq("1b", 1), _cq("1c", 0))
    result = rs.score_script(script, correction, records, latency_ms=0.0, failure=None,
                             escalations=events, cascade_enabled=False)
    (esc,) = [l for l in result.leaves if l.escalated]
    assert esc.question_id == "1a" and esc.trigger == "confidence"
    assert esc.pre_escalation_confidence == 0.75
    assert result.escalation_usd == pytest.approx(0.02)
    assert result.adjudication_usd == pytest.approx(0.005)
    assert result.usd == pytest.approx(0.035)
    other = [l for l in result.leaves if l.question_id == "1b"][0]
    assert other.pre_escalation_confidence == 0.9 and other.trigger is None


def _leaf(qid: str, predicted: int, reference: int, *, review: bool = False,
          escalated: bool = False) -> LeafOutcome:
    return LeafOutcome(qid, predicted, reference, 2, review, 0.9, "ai", None, escalated,
                       "confidence" if escalated else None, 0.9)


def _script(key: str, leaves: list[LeafOutcome], usd: float, *, verdict: str = "pass",
            esc_usd: float = 0.0, incomplete: str | None = None) -> RealScriptResult:
    return RealScriptResult(key, tuple(leaves), verdict, usd, esc_usd, 0.0, 1000.0, incomplete)


def test_summary_fields_average_two_runs_and_take_the_max_cost() -> None:
    run1 = [_script("a", [_leaf("1", 2, 2), _leaf("2", 0, 1, review=True)], 0.04),
            _script("b", [_leaf("1", 1, 1, escalated=True)], 0.02, verdict="hold", esc_usd=0.01)]
    run2 = [_script("a", [_leaf("1", 2, 2), _leaf("2", 1, 1)], 0.06),
            _script("b", [_leaf("1", 0, 1)], 0.02, verdict="hold", incomplete="x")]
    f = rs.real_summary_fields([run1, run2])
    assert f["real_scripts"] == ("a", "b")
    assert f["real_abs_error_by_run"] == (1.0, 1.0)
    assert f["real_abs_error"] == 1.0
    assert f["real_exact_rate"] == pytest.approx((2 / 3 + 2 / 3) / 2)
    assert f["real_review_rate"] == pytest.approx((1 / 3 + 0) / 2)
    assert f["real_binding_passes"] == 1.0
    assert dict(f["real_usd_max_by_script"]) == {"a": 0.06, "b": 0.02}  # type: ignore[arg-type]
    assert dict(f["real_usd_by_script"])["a"] == pytest.approx(0.05)  # type: ignore[arg-type]
    assert f["real_escalation_rate"] == pytest.approx((1 / 3 + 0) / 2)
    assert f["real_escalation_rate_max_script"] == 1.0
    assert f["real_escalation_triggers"] == (("confidence", 1),)
    assert f["real_incomplete"] == ("real-2:b (x)",)


def test_summary_fields_need_at_least_one_run() -> None:
    with pytest.raises(ValueError):
        rs.real_summary_fields([])


def test_results_round_trip(tmp_path: Path) -> None:
    results = [_script("a", [_leaf("1", 2, 2, escalated=True)], 0.04, esc_usd=0.01)]
    path = tmp_path / "real_results.json"
    rs.write_real_results(path, results)
    assert rs.read_real_results(path) == results
    assert json.loads(path.read_text())[0]["key"] == "a"
```

- [ ] **Step 2: Run the tests to watch them fail.**

Run: `.venv/bin/python -m pytest tests/test_cost_ladder_real_split.py -q --no-cov -o addopts=""`
Expected: `ModuleNotFoundError: No module named 'lemely.accuracy.cost_ladder.real_split'`.

- [ ] **Step 3: Write the module.** Create `lemely/accuracy/cost_ladder/real_split.py`:

```python
"""Sub-project C real split: frozen real scripts, marked on the production path, scored per leaf.

A real script is loaded only from the frozen reference manifest, and only when every
digest still matches (`load_real_scripts`), so a changed reference stops a run before
any spend. Scoring never narrows the denominator: a leaf the run dropped, lost or
failed to mark counts as mark 0 against its reference.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from lemely.accuracy.reference import (
    MANIFEST_FILE,
    REFERENCE_ROOT,
    read_manifest,
    read_reference,
    sha256_file,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from lemely.core.schemas import CorrectionResult
    from lemely.io.gemini import CallRecord, GeminiClient
    from lemely.runtime.config import Settings

DEFAULT_MANIFEST = REFERENCE_ROOT / MANIFEST_FILE
ESCALATION_TAG = "escalation"
ADJUDICATION_TAG = "adjudication"
#: The review reason ``correct_paper`` writes when the marking call itself failed.
_AI_FAILED = "AI marking failed"
#: Leaves no marker scored: their mark counts as 0, whatever was stored.
_ZERO_SOURCES = frozenset({"missing", "dropped"})
#: The borderline retry publishes GEMINI_ESCALATE with this suffix on the model name.
_BORDERLINE_SUFFIX = "(thinking)"


class ReferenceDrift(RuntimeError):
    """A frozen reference, scheme or scan changed or went missing; nothing may run."""


@dataclass(frozen=True)
class RealScript:
    key: str
    scan_path: Path
    scheme_path: Path
    reference_path: Path
    reference_sha256: str
    scheme_sha256: str
    scan_sha256: str


def load_real_scripts(
    manifest_path: Path = DEFAULT_MANIFEST, *, only: Sequence[str] = ()
) -> list[RealScript]:
    """The frozen scripts of *manifest_path* (all, or the keys in *only*), digests checked."""
    entries = read_manifest(manifest_path)
    if not entries:
        raise ReferenceDrift(f"{manifest_path} lists no scripts; freeze the reference set first")
    known = {e.key for e in entries}
    unknown = sorted(set(only) - known)
    if unknown:
        raise ReferenceDrift(f"not in {manifest_path}: {', '.join(unknown)}")
    problems: list[str] = []
    scripts: list[RealScript] = []
    for e in entries:
        if only and e.key not in only:
            continue
        for what, raw, want in (
            ("reference", e.reference_path, e.reference_sha256),
            ("scheme", e.scheme_path, e.scheme_sha256),
            ("scan", e.scan_path, e.scan_sha256),
        ):
            path = Path(raw)
            if not path.is_file():
                problems.append(f"{e.key}: {what} {path} is missing")
            elif sha256_file(path) != want:
                problems.append(f"{e.key}: {what} {path} sha256 differs from the manifest")
        scripts.append(
            RealScript(
                key=e.key,
                scan_path=Path(e.scan_path),
                scheme_path=Path(e.scheme_path),
                reference_path=Path(e.reference_path),
                reference_sha256=e.reference_sha256,
                scheme_sha256=e.scheme_sha256,
                scan_sha256=e.scan_sha256,
            )
        )
    if problems:
        raise ReferenceDrift("; ".join(problems) + ". Refusing to run.")
    return scripts


def mark_real_script(
    script: RealScript, client: GeminiClient, settings: Settings
) -> CorrectionResult:
    """Mark one real script the way production does: scan metadata, binder, correction.

    The same stages the E2E driver ran (BUILD/accuracy-runs/claude-e2e2-*/driver.py),
    on the frozen scheme, inside one `script_cost_scope`. A failure is raised to the
    caller, which records the script as incomplete.
    """
    from lemely.core.loose_schemas import MarkScheme
    from lemely.io.answer_extraction import GeminiAnswerExtractor
    from lemely.io.correction_ai import correct_paper
    from lemely.io.gemini import script_cost_scope
    from lemely.io.scan_metadata import ScanMetadataExtractor

    scheme = MarkScheme.model_validate_json(script.scheme_path.read_text(encoding="utf-8"))
    with script_cost_scope(settings, script_key=f"real:{script.key}"):
        ScanMetadataExtractor(client)(script.scan_path)
        extracted = GeminiAnswerExtractor(client)(scan_path=script.scan_path, mark_scheme=scheme)
        return correct_paper(
            mark_scheme=scheme,
            extracted_answers=extracted,
            gemini_client=client,
            options=settings.grading.marking_options(),
        )


@dataclass(frozen=True)
class LeafOutcome:
    question_id: str
    predicted: int
    reference: int
    max_marks: int
    needs_review: bool
    confidence: float | None
    marker_source: str | None
    review_reason: str | None
    escalated: bool
    trigger: str | None
    #: The confidence that decided escalation: the escalation event's for an escalated
    #: leaf, the final mark's otherwise (the threshold fit reads it).
    pre_escalation_confidence: float | None

    @property
    def abs_error(self) -> int:
        return abs(self.predicted - self.reference)


@dataclass(frozen=True)
class RealScriptResult:
    key: str
    leaves: tuple[LeafOutcome, ...]
    binding_verdict: str | None
    usd: float  # 2027 USD of every call of the script
    escalation_usd: float
    adjudication_usd: float
    latency_ms: float  # wall clock of the whole script
    incomplete: str | None  # why the script is incomplete; None when complete

    @property
    def abs_error(self) -> int:
        return sum(leaf.abs_error for leaf in self.leaves)

    @property
    def escalated(self) -> int:
        return sum(1 for leaf in self.leaves if leaf.escalated)


def _usd(records: Sequence[CallRecord], tag: str | None = None) -> float:
    return sum(
        r.usd_2027
        for r in records
        if (tag is None or r.task_tag == tag) and not math.isnan(r.usd_2027)
    )


def score_script(
    script: RealScript,
    correction: CorrectionResult | None,
    records: Sequence[CallRecord],
    *,
    latency_ms: float,
    failure: str | None,
    escalations: Sequence[Mapping[str, object]],
    cascade_enabled: bool,
) -> RealScriptResult:
    """One script's leaves against its reference; every reference leaf is scored."""
    reference = read_reference(script.reference_path)
    by_id = {q.question_id: q for q in correction.questions} if correction is not None else {}
    escalated_ids = {r.question_id for r in records if r.task_tag == ESCALATION_TAG and r.question_id}
    event_confidence: dict[str, float] = {}
    for event in escalations:
        qid, conf = event.get("question_id"), event.get("confidence")
        model = str(event.get("escalation_model", ""))
        if isinstance(qid, str) and isinstance(conf, int | float) and not model.endswith(
            _BORDERLINE_SUFFIX
        ):
            event_confidence[qid] = float(conf)
    incomplete = failure
    leaves: list[LeafOutcome] = []
    for qid in sorted(reference):
        leaf_ref = reference[qid]
        q = by_id.get(qid)
        if (
            q is not None
            and q.marker_source == "missing"
            and (q.review_reason or "").startswith(_AI_FAILED)
            and incomplete is None
        ):
            incomplete = f"marking failed on {qid}"
        predicted = 0 if q is None or q.marker_source in _ZERO_SOURCES else q.awarded_marks
        escalated = qid in escalated_ids
        final_conf = q.confidence_score if q is not None else None
        leaves.append(
            LeafOutcome(
                question_id=qid,
                predicted=predicted,
                reference=leaf_ref.mark,
                max_marks=leaf_ref.max_marks,
                needs_review=q.needs_teacher_review if q is not None else True,
                confidence=final_conf,
                marker_source=q.marker_source if q is not None else None,
                review_reason=q.review_reason if q is not None else None,
                escalated=escalated,
                trigger=("cascade" if cascade_enabled else "confidence") if escalated else None,
                pre_escalation_confidence=(
                    event_confidence.get(qid, final_conf) if escalated else final_conf
                ),
            )
        )
    if correction is None and incomplete is None:
        incomplete = "no marking"
    unpriced = [r.model for r in records if math.isnan(r.usd_2027)]
    if unpriced and incomplete is None:
        incomplete = f"unpriced model {unpriced[0]}"
    binding = correction.binding if correction is not None else None
    return RealScriptResult(
        key=script.key,
        leaves=tuple(leaves),
        binding_verdict=binding.verdict if binding is not None else None,
        usd=_usd(records),
        escalation_usd=_usd(records, ESCALATION_TAG),
        adjudication_usd=_usd(records, ADJUDICATION_TAG),
        latency_ms=latency_ms,
        incomplete=incomplete,
    )


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _rate(run: Sequence[RealScriptResult], hit: str) -> float:
    leaves = [leaf for script in run for leaf in script.leaves]
    if not leaves:
        return 0.0
    tests = {
        "exact": lambda leaf: leaf.abs_error == 0,
        "within1": lambda leaf: leaf.abs_error <= 1,
        "review": lambda leaf: leaf.needs_review,
        "escalated": lambda leaf: leaf.escalated,
    }
    return sum(1 for leaf in leaves if tests[hit](leaf)) / len(leaves)


def real_summary_fields(runs: Sequence[Sequence[RealScriptResult]]) -> dict[str, object]:
    """The `RunSummary` real fields of a rung's runs: means over the runs, max for the cap."""
    if not runs:
        raise ValueError("a rung needs at least one real run")
    keys = [script.key for script in runs[0]]
    per_key: dict[str, list[RealScriptResult]] = {k: [] for k in keys}
    for run in runs:
        for script in run:
            per_key.setdefault(script.key, []).append(script)
    by_run_abs = tuple(float(sum(s.abs_error for s in run)) for run in runs)
    script_esc_rates = [
        s.escalated / len(s.leaves) for run in runs for s in run if s.leaves
    ]
    triggers = Counter(
        leaf.trigger for run in runs for s in run for leaf in s.leaves if leaf.trigger
    )
    return {
        "real_scripts": tuple(keys),
        "real_abs_error": _mean(by_run_abs),
        "real_abs_error_by_run": by_run_abs,
        "real_exact_rate": _mean([_rate(run, "exact") for run in runs]),
        "real_within1_rate": _mean([_rate(run, "within1") for run in runs]),
        "real_review_rate": _mean([_rate(run, "review") for run in runs]),
        "real_binding_passes": _mean(
            [float(sum(1 for s in run if s.binding_verdict == "pass")) for run in runs]
        ),
        "real_usd_mean": _mean([s.usd for run in runs for s in run]),
        "real_usd_by_script": tuple((k, _mean([s.usd for s in v])) for k, v in per_key.items()),
        "real_usd_max_by_script": tuple(
            (k, max((s.usd for s in v), default=0.0)) for k, v in per_key.items()
        ),
        "real_latency_by_script": tuple(
            (k, _mean([s.latency_ms for s in v])) for k, v in per_key.items()
        ),
        "real_escalation_rate": _mean([_rate(run, "escalated") for run in runs]),
        "real_escalation_rate_max_script": max(script_esc_rates, default=0.0),
        "real_escalation_usd_by_script": tuple(
            (k, _mean([s.escalation_usd for s in v])) for k, v in per_key.items()
        ),
        "real_escalation_triggers": tuple(sorted(triggers.items())),
        "real_incomplete": tuple(
            f"real-{i}:{s.key} ({s.incomplete})"
            for i, run in enumerate(runs, start=1)
            for s in run
            if s.incomplete
        ),
    }


def write_real_results(path: Path, results: Sequence[RealScriptResult]) -> None:
    """``real_results.json``: per-leaf marks. Student data: stays under the gitignored BUILD tree."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(r) for r in results], indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_real_results(path: Path) -> list[RealScriptResult]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [
        RealScriptResult(
            **{k: v for k, v in row.items() if k != "leaves"},
            leaves=tuple(LeafOutcome(**leaf) for leaf in row["leaves"]),
        )
        for row in rows
    ]
```

Notes for the implementer: `CorrectedQuestion`'s required fields are as in the test's `_cq`; if `ExamMetadata` needs more fields, copy the values from `lemely/core/schemas.py` (search `class ExamMetadata`). `MarkingOptions` comes from `settings.grading.marking_options()` as in the E2E driver.

- [ ] **Step 4: Run the tests to watch them pass.**

Run: `.venv/bin/python -m pytest tests/test_cost_ladder_real_split.py -q --no-cov -o addopts=""`
Expected: 12 passed.

- [ ] **Step 5: Prove the guards red.** (a) In `load_real_scripts`, replace `sha256_file(path) != want` with `False`; `test_loader_refuses_a_changed_reference` fails. (b) In `score_script`, replace the `predicted = ...` line with `predicted = q.awarded_marks if q is not None else 0`; `test_scoring_counts_dropped_missing_and_absent_leaves_as_zero` fails (its dropped leaf stores 1). (c) Iterate `by_id` instead of `reference` in the leaf loop; the `len(result.leaves) == 3` assertion fails. Revert each; rerun: 12 passed.

- [ ] **Step 6: Gates and commit.**

```bash
.venv/bin/python -m pytest tests/test_cost_ladder_real_split.py tests/test_llm_golden.py -q --no-cov -o addopts=""
PATH=$PWD/.venv/bin:$PATH pre-commit run --files lemely/accuracy/cost_ladder/real_split.py tests/test_cost_ladder_real_split.py
git add -- lemely/accuracy/cost_ladder/real_split.py tests/test_cost_ladder_real_split.py
git commit -S -m "feat(cost_ladder): real split loader, production-path marking and per-leaf scoring" -- lemely/accuracy/cost_ladder/real_split.py tests/test_cost_ladder_real_split.py
```

---
### Task 7: Runner: `run_real`, split and repeats on baseline and screens, the Gemini rung, the flip verdict

**Files:**
- Modify: `lemely/accuracy/cost_ladder/runner.py`
- Test: `tests/test_cost_ladder_real_runner.py` (new)

**Interfaces:**
- Consumes: Task 5 (`RunSummary` real fields, `Verdict.notes`, `judge_cost_lever`, `judge_accuracy_lever`, `judge_flip`, `judge_record`), Task 6 (`RealScript`, `RealScriptResult`, `mark_real_script`, `score_script`, `real_summary_fields`, `write_real_results`).
- Produces (Tasks 8, 9, 22 to 28 rely on these):
  - `Split = Literal["dev", "real", "both"]`, `JudgeKind = Literal["cost", "accuracy", "record"]`, `REAL_RUN_PREFIX = "real-"`, `REPEAT_SUFFIX = "-r2"`, `FLIP_VERDICT_FILE = "flip_verdict.json"`, `EMPTY_DEV_SUMMARY: RunSummary`.
  - `run_real(label, overrides, *, run_index, out_dir, scripts, settings=None, caps=None, max_run_usd=None, spend_file=None, mark=None, on_checks_passed=None) -> tuple[RealScriptResult, ...]`; writes `<out_dir>/<label>/real-<i>/{records.jsonl,real_results.json,escalations.jsonl,run_cost.json}`.
  - `pair_summaries(a: RunSummary, b: RunSummary) -> RunSummary`, `with_real(summary, runs) -> RunSummary`.
  - `run_baseline(..., split: Split = "dev", repeats: int = 1, real_scripts: Sequence[RealScript] = ()) -> int`; `aa_floor.json` gains `"real_aa_floor"` when the real split ran.
  - `run_screen(..., split: Split = "dev", judge_kind: JudgeKind = "cost", repeats: int = 1, real_scripts: Sequence[RealScript] = ()) -> Verdict`; `verdict.json` gains `"judge"`, `"split"`, `"repeats"`, `"notes"`.
  - `run_reference_rung(label, *, out_dir, real_scripts, dev_summary_from: Path, settings=None, repeats=2, caps=None, max_run_usd=None, spend_file=None) -> RunSummary`.
  - `flip_verdict(out_dir, *, candidate: str, gemini: str) -> Verdict`; writes `<out_dir>/flip_verdict.json`.
  - `read_summary` reads the real fields (defaults for an older file); `resummarise` refuses a real-split run.
  - `models_in_play` also lists `scan_metadata`'s model and `binding.second_read_model`.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_cost_ladder_real_runner.py`:

```python
"""Sub-project C P1: the runner's real split. Fakes only: no model call, no spend."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from lemely.accuracy import reference as ref
from lemely.accuracy.cost_ladder import runner
from lemely.accuracy.cost_ladder.gate import RunSummary
from lemely.accuracy.cost_ladder.real_split import RealScript, load_real_scripts
from lemely.accuracy.cost_ladder.runner import LadderStateError, apply_overrides
from lemely.accuracy.cost_ladder.spend import SpendCapError, SpendCaps
from lemely.core.schemas import CorrectedQuestion, CorrectionResult, ExamMetadata
from lemely.io.gemini import CallRecord, UnpricedModelError
from lemely.runtime.config import Settings
from lemely.runtime.events import EventType, bus

PERFECT = {"1a": 2, "1b": 1}


@pytest.fixture(autouse=True)
def _spend_file_in_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "spend.json"
    monkeypatch.setattr(runner, "DEFAULT_SPEND_FILE", path)
    return path


def _scripts(tmp_path: Path, keys: tuple[str, ...] = ("a", "b")) -> list[RealScript]:
    root = tmp_path / "ref"
    for key in keys:
        d = root / key
        ref.write_reference(
            d / ref.REFERENCE_FILE,
            [ref.ReferenceLeaf("1a", 2, 2, "opus", "e"), ref.ReferenceLeaf("1b", 1, 1, "opus", "e")],
        )
        (d / ref.SCHEME_FILE).write_text("{}", encoding="utf-8")
        scan = root / f"{key}.pdf"
        scan.write_bytes(key.encode())
        ref.freeze(d, key=key, scan_path=scan, sources={}, expected_total=None,
                   manifest_path=root / ref.MANIFEST_FILE)
    return load_real_scripts(root / ref.MANIFEST_FILE)


def _correction(marks: dict[str, int]) -> CorrectionResult:
    meta = ExamMetadata(subject_code="0625", paper_number=4, paper_variant=1,
                        session_month="Oct/Nov", session_year=2024)
    return CorrectionResult(metadata=meta, questions=[
        CorrectedQuestion(question_id=q, awarded_marks=m, maximum_marks=2, confidence="high",
                          confidence_score=0.9, needs_teacher_review=False, marker_source="ai")
        for q, m in marks.items()])


def _rec(key: str, usd: float, *, tag: str = "correction", qid: str | None = None) -> CallRecord:
    return CallRecord(provider="anthropic", task_tag=tag, model="claude-haiku-5-5", thinking="low",
                      input_tokens=1, cached_tokens=0, output_tokens=1, thinking_tokens=0,
                      usd_now=usd, usd_2027=usd, latency_ms=5, attempt=None, question_id=qid,
                      case_key=key, parse_ok=True)


class _Harness:
    """Fake production path: bills ``usd`` per script and returns marks in call order."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, marks: list[dict[str, int]] | None = None,
                 usd: float = 0.01, raise_for: tuple[str, ...] = (), escalate: tuple[str, ...] = ()) -> None:
        self.records: list[CallRecord] = []
        self.clients: list[tuple[Settings, dict[str, Any]]] = []
        self.calls: list[str] = []
        self.marks = list(marks or [])
        self.usd, self.raise_for, self.escalate = usd, raise_for, escalate
        monkeypatch.setattr(runner, "preflight_prices", lambda settings: None)
        monkeypatch.setattr(runner, "GeminiClient", self._client)
        monkeypatch.setattr(runner, "reset_process_counters", lambda: self.records.clear())
        monkeypatch.setattr(runner, "process_call_records", lambda: list(self.records))
        monkeypatch.setattr(runner, "set_call_context", lambda *, case_key: None)
        monkeypatch.setattr(runner, "mark_real_script", self.mark)

    def _client(self, settings: Settings, **kw: Any) -> object:
        self.clients.append((settings, kw))
        return object()

    def mark(self, script: RealScript, client: object, settings: Settings) -> CorrectionResult:
        self.calls.append(script.key)
        self.records.append(_rec(script.key, self.usd))
        if script.key in self.raise_for:
            raise RuntimeError("boom")
        for qid in self.escalate:
            self.records.append(_rec(script.key, 0.02, tag="escalation", qid=qid))
            bus.publish(EventType.GEMINI_ESCALATE, question_id=qid, confidence=0.7,
                        escalation_model="claude-sonnet-5-5")
        return _correction(self.marks.pop(0) if self.marks else PERFECT)


def test_run_real_scores_writes_and_books(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    h = _Harness(monkeypatch, marks=[{"1a": 2, "1b": 0}], escalate=("1a",))
    out = tmp_path / "out"
    results = runner.run_real("base", {}, run_index=1, out_dir=out, scripts=_scripts(tmp_path),
                              settings=Settings(), max_run_usd={"anthropic": 1.0})
    assert [r.key for r in results] == ["a", "b"]
    assert [r.abs_error for r in results] == [1, 0]
    assert results[0].leaves[0].escalated and results[0].leaves[0].pre_escalation_confidence == 0.7
    run_dir = out / "base" / "real-1"
    for name in ("records.jsonl", "real_results.json", "escalations.jsonl", "run_cost.json"):
        assert (run_dir / name).is_file(), name
    spent = json.loads((tmp_path / "spend.json").read_text())
    assert spent["anthropic"] == pytest.approx(2 * (0.01 + 0.02))
    ((settings, kw),) = h.clients
    assert kw == {"default_cache_mode": "bypass"}
    assert settings.paths.cache_dir == runner.cache_dir_for(out, "base-real-1")
    assert settings.gemini.cache_forget_enabled is False


def test_run_real_failed_script_is_incomplete_and_the_rest_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _Harness(monkeypatch, raise_for=("a",))
    results = runner.run_real("base", {}, run_index=1, out_dir=tmp_path / "o",
                              scripts=_scripts(tmp_path), settings=Settings(),
                              max_run_usd={"anthropic": 1.0})
    assert results[0].incomplete == "RuntimeError: boom"
    assert results[1].incomplete is None


def test_run_real_stops_at_the_cap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    h = _Harness(monkeypatch, usd=0.01)
    results = runner.run_real("base", {}, run_index=1, out_dir=tmp_path / "o",
                              scripts=_scripts(tmp_path, ("a", "b", "c")), settings=Settings(),
                              caps=SpendCaps(anthropic_usd=0.025), max_run_usd={"anthropic": 0.02})
    assert h.calls == ["a", "b"]
    assert results[2].incomplete == "not run (spend cap)"


def test_run_real_refuses_without_a_projection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    h = _Harness(monkeypatch)
    with pytest.raises(SpendCapError, match="--max-run-usd"):
        runner.run_real("base", {}, run_index=1, out_dir=tmp_path / "o",
                        scripts=_scripts(tmp_path), settings=Settings())
    assert h.calls == [] and h.clients == []


def test_run_real_refuses_an_unpriced_model_before_any_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom(*a: object, **k: object) -> None:
        raise AssertionError("must not spend")

    monkeypatch.setattr(runner, "GeminiClient", boom)
    monkeypatch.setattr(runner, "mark_real_script", boom)
    settings = apply_overrides(Settings(), {"gemini.scan_metadata_model": "gemini-9-unknown"})
    with pytest.raises(UnpricedModelError, match="gemini-9-unknown"):
        runner.run_real("base", {}, run_index=1, out_dir=tmp_path / "o",
                        scripts=_scripts(tmp_path), settings=settings,
                        max_run_usd={"anthropic": 1.0})


def test_models_in_play_cover_the_real_path() -> None:
    s = apply_overrides(Settings(), {"gemini.scan_metadata_model": "gemini-x-meta",
                                     "binding.second_read_model": "claude-x-second"})
    names = runner.models_in_play(s)
    assert "gemini-x-meta" in names and "claude-x-second" in names


def _real_baseline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, marks: list[dict[str, int]]) -> tuple[Path, list[RealScript]]:
    _Harness(monkeypatch, marks=marks)
    scripts = _scripts(tmp_path)
    out = tmp_path / "out"
    runner.run_baseline(out_dir=out, settings=Settings(), split="real", real_scripts=scripts,
                        max_run_usd={"anthropic": 1.0})
    return out, scripts


def test_real_baseline_writes_summary_and_real_floor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out, _ = _real_baseline(monkeypatch, tmp_path,
                            [PERFECT, PERFECT, {"1a": 0, "1b": 1}, PERFECT])
    floors = json.loads((out / runner.AA_FLOOR_FILE).read_text())
    assert floors == {"aa_floor": 0, "real_aa_floor": 2.0}
    s = runner.read_summary(out / "baseline" / "summary.json")
    assert s.real_scripts == ("a", "b") and s.real_abs_error == 1.0
    assert s.scored_parts == 0


def test_screen_real_split_judges_accuracy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    low = {"1a": 1, "1b": 0}
    out, scripts = _real_baseline(monkeypatch, tmp_path, [low] * 4)
    _Harness(monkeypatch)  # the candidate marks every leaf right
    v = runner.run_screen("b1", {"gemini.correction_citations": True}, out_dir=out,
                          settings=Settings(), split="real", judge_kind="accuracy", repeats=2,
                          real_scripts=scripts)
    assert v.passed, v.reasons
    verdict = json.loads((out / "b1" / "verdict.json").read_text())
    assert verdict["judge"] == "accuracy" and verdict["repeats"] == 2 and verdict["split"] == "real"
    assert isinstance(verdict["notes"], list)
    assert json.loads((out / "ladder.json").read_text()) == ["b1"]
    summary = json.loads((out / "b1" / "summary.json").read_text())
    assert summary["overrides"] == {"gemini.correction_citations": True}
    assert summary["real_abs_error"] == 0.0
    assert (out / "b1" / "real-2" / "real_results.json").is_file()


def test_screen_real_split_refuses_without_a_real_floor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _Harness(monkeypatch)
    out = tmp_path / "out"
    runner.write_summary(runner.EMPTY_DEV_SUMMARY, out / "baseline" / "summary.json",
                         usd_per_script_mean_now=0.0)
    (out / runner.AA_FLOOR_FILE).write_text(json.dumps({"aa_floor": 0}))
    with pytest.raises(LadderStateError, match="real_aa_floor"):
        runner.run_screen("b1", {}, out_dir=out, settings=Settings(), split="real",
                          judge_kind="accuracy", real_scripts=_scripts(tmp_path))
    assert not (out / "b1").exists()


def test_reference_rung_takes_stored_dev_and_live_real(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _Harness(monkeypatch)
    out = tmp_path / "out"
    stored = tmp_path / "old" / "summary.json"
    runner.write_summary(RunSummary(0.2, 9.0, frozenset({"x/1a"}), 78, 1.0, 1.0, ()), stored,
                         usd_per_script_mean_now=0.2)
    s = runner.run_reference_rung("gemini", out_dir=out, real_scripts=_scripts(tmp_path),
                                  dev_summary_from=stored, settings=Settings(),
                                  max_run_usd={"anthropic": 1.0, "gemini": 1.0})
    assert s.mismarked_parts == frozenset({"x/1a"}) and s.real_scripts == ("a", "b")
    data = json.loads((out / "gemini" / "summary.json").read_text())
    assert data["reference_rung"] is True
    assert not (out / "ladder.json").exists()


def test_flip_verdict_writes_its_file(tmp_path: Path) -> None:
    base = RunSummary(0.05, 1.0, frozenset(), 10, 1.0, 1.0, (), real_scripts=("a",),
                      real_abs_error=3.0, real_usd_max_by_script=(("a", 0.05),),
                      real_review_rate=0.2)
    runner.write_summary(base, tmp_path / "stack" / "summary.json", usd_per_script_mean_now=0.0)
    runner.write_summary(replace(base, real_abs_error=4.0), tmp_path / "gemini" / "summary.json",
                         usd_per_script_mean_now=0.0)
    (tmp_path / runner.AA_FLOOR_FILE).write_text(json.dumps({"aa_floor": 0, "real_aa_floor": 1.0}))
    v = runner.flip_verdict(tmp_path, candidate="stack", gemini="gemini")
    assert v.passed
    data = json.loads((tmp_path / runner.FLIP_VERDICT_FILE).read_text())
    assert data["passed"] is True and data["candidate"] == "stack" and data["gemini"] == "gemini"


def test_resummarise_refuses_a_real_split_run(tmp_path: Path) -> None:
    runner.write_summary(RunSummary(0.0, 0.0, frozenset(), 0, 1.0, 1.0, (), real_scripts=("a",)),
                         tmp_path / "x" / "summary.json", usd_per_script_mean_now=0.0)
    with pytest.raises(LadderStateError, match="real split"):
        runner.resummarise("x", out_dir=tmp_path)


def test_pair_summaries_mean_and_union() -> None:
    a = RunSummary(1.0, 100.0, frozenset({"c/1"}), 10, 1.0, 1.0, ())
    b = RunSummary(3.0, 300.0, frozenset({"c/2"}), 10, 0.5, 0.9, ("c (x)",))
    p = runner.pair_summaries(a, b)
    assert p.usd_per_script_mean == 2.0 and p.latency_p95_ms == 200.0
    assert p.mismarked_parts == frozenset({"c/1", "c/2"})
    assert p.id_match_rate == 0.75 and p.validity_rate == pytest.approx(0.95)
    assert p.incomplete == ("c (x)",)
    narrowed = runner.pair_summaries(a, replace(b, scored_parts=9))
    assert "scored parts differ between the two runs (10, 9)" in narrowed.incomplete


def test_read_summary_round_trips_real_fields(tmp_path: Path) -> None:
    s = RunSummary(0.05, 1.0, frozenset(), 3, 1.0, 1.0, (), real_scripts=("a", "b"),
                   real_abs_error=2.5, real_abs_error_by_run=(2.0, 3.0), real_review_rate=0.3,
                   real_usd_by_script=(("a", 0.04),), real_escalation_triggers=(("confidence", 2),))
    path = tmp_path / "summary.json"
    runner.write_summary(s, path, usd_per_script_mean_now=0.0)
    assert runner.read_summary(path) == s
```

- [ ] **Step 2: Run the tests to watch them fail.**

Run: `.venv/bin/python -m pytest tests/test_cost_ladder_real_runner.py -q --no-cov -o addopts=""`
Expected: `AttributeError: module 'lemely.accuracy.cost_ladder.runner' has no attribute 'run_real'` (or `EMPTY_DEV_SUMMARY`) in most tests.

- [ ] **Step 3: Imports and constants.** In `lemely/accuracy/cost_ladder/runner.py`:

```python
import time
from dataclasses import asdict, dataclass, fields, replace
from typing import TYPE_CHECKING, Literal, cast

from lemely.accuracy.cost_ladder.gate import (
    RunSummary,
    Verdict,
    aa_floor,
    judge_accuracy_lever,
    judge_cost_lever,
    judge_flip,
    judge_record,
)
from lemely.accuracy.cost_ladder.real_split import (
    RealScript,
    RealScriptResult,
    mark_real_script,
    real_summary_fields,
    score_script,
    write_real_results,
)
from lemely.accuracy.cost_ladder.spend import (
    DEFAULT_SPEND_FILE,
    RUN_COST_FILE,
    CapWatch,
    SpendCapError,
    SpendCaps,
    SpendLedger,
    check_can_start,
    cost_by_provider,
    resolve_projection,
)
from lemely.runtime.errors import CostCeilingError
```

(`judge` is no longer imported by name; `run_screen` dispatches through `_judge`. Keep `from lemely.accuracy.cost_ladder.gate import judge` only if something else in the file still calls it.) Under `TYPE_CHECKING` add `from lemely.core.schemas import CorrectionResult`.

After `LADDER_FILE = "ladder.json"` add:

```python
REAL_RUN_PREFIX = "real-"
REPEAT_SUFFIX = "-r2"
FLIP_VERDICT_FILE = "flip_verdict.json"

Split = Literal["dev", "real", "both"]
JudgeKind = Literal["cost", "accuracy", "record"]

#: The dev side of a real-only rung: nothing scored, nothing spent.
EMPTY_DEV_SUMMARY = RunSummary(
    usd_per_script_mean=0.0,
    latency_p95_ms=0.0,
    mismarked_parts=frozenset(),
    scored_parts=0,
    id_match_rate=1.0,
    validity_rate=1.0,
    incomplete=(),
)
```

- [ ] **Step 4: `models_in_play`.** Add to its `names` list, after `g.model_for("escalation")`:

```python
        g.model_for("scan_metadata"),  # the real split's first stage
        settings.binding.second_read_model,  # None reads the second read on read_model
```

- [ ] **Step 5: `read_summary` with the real fields.** Replace `read_summary` with:

```python
def _pairs(raw: object) -> tuple[tuple[str, float], ...]:
    return tuple((str(k), float(v)) for k, v in raw) if isinstance(raw, list) else ()


def _opt_float(raw: object) -> float | None:
    return float(raw) if isinstance(raw, int | float) else None


def read_summary(path: Path) -> RunSummary:
    data = json.loads(path.read_text(encoding="utf-8"))
    return RunSummary(
        usd_per_script_mean=data["usd_per_script_mean"],
        latency_p95_ms=data["latency_p95_ms"],
        mismarked_parts=frozenset(data["mismarked_parts"]),
        scored_parts=data["scored_parts"],
        id_match_rate=data["id_match_rate"],
        validity_rate=data["validity_rate"],
        incomplete=tuple(data["incomplete"]),
        real_scripts=tuple(str(k) for k in data.get("real_scripts", ())),
        real_abs_error=float(data.get("real_abs_error", 0.0)),
        real_abs_error_by_run=tuple(float(x) for x in data.get("real_abs_error_by_run", ())),
        real_exact_rate=_opt_float(data.get("real_exact_rate")),
        real_within1_rate=_opt_float(data.get("real_within1_rate")),
        real_review_rate=_opt_float(data.get("real_review_rate")),
        real_binding_passes=float(data.get("real_binding_passes", 0.0)),
        real_usd_mean=float(data.get("real_usd_mean", 0.0)),
        real_usd_by_script=_pairs(data.get("real_usd_by_script")),
        real_usd_max_by_script=_pairs(data.get("real_usd_max_by_script")),
        real_latency_by_script=_pairs(data.get("real_latency_by_script")),
        real_escalation_rate=_opt_float(data.get("real_escalation_rate")),
        real_escalation_rate_max_script=_opt_float(data.get("real_escalation_rate_max_script")),
        real_escalation_usd_by_script=_pairs(data.get("real_escalation_usd_by_script")),
        real_escalation_triggers=tuple(
            (str(k), int(v)) for k, v in data.get("real_escalation_triggers", ())
        ),
        real_incomplete=tuple(str(x) for x in data.get("real_incomplete", ())),
    )
```

- [ ] **Step 6: Pairing and the real merge.** Add after `read_records`:

```python
def pair_summaries(a: RunSummary, b: RunSummary) -> RunSummary:
    """Two dev runs of one config as one: the mean of each figure, the union of mismarks."""
    incomplete = list(dict.fromkeys([*a.incomplete, *b.incomplete]))
    if a.scored_parts != b.scored_parts:
        incomplete.append(
            f"scored parts differ between the two runs ({a.scored_parts}, {b.scored_parts})"
        )
    return replace(
        a,
        usd_per_script_mean=(a.usd_per_script_mean + b.usd_per_script_mean) / 2,
        latency_p95_ms=(a.latency_p95_ms + b.latency_p95_ms) / 2,
        mismarked_parts=a.mismarked_parts | b.mismarked_parts,
        id_match_rate=(a.id_match_rate + b.id_match_rate) / 2,
        validity_rate=(a.validity_rate + b.validity_rate) / 2,
        incomplete=tuple(incomplete),
    )


def with_real(summary: RunSummary, runs: Sequence[Sequence[RealScriptResult]]) -> RunSummary:
    """*summary* with the real split's fields; real incompletes join ``incomplete``."""
    real = real_summary_fields(runs)
    real_incomplete = cast("tuple[str, ...]", real["real_incomplete"])
    merged = replace(summary, **real)  # type: ignore[arg-type]
    return replace(
        merged, incomplete=tuple(dict.fromkeys([*summary.incomplete, *real_incomplete]))
    )


def _summary_extras(path: Path) -> tuple[dict[str, object], float]:
    """The non-`RunSummary` keys of a stored summary, and its ``usd_per_script_mean_now``."""
    data: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    names = {f.name for f in fields(RunSummary)} | {"usd_per_script_mean_now"}
    now = data.get("usd_per_script_mean_now", 0.0)
    return {k: v for k, v in data.items() if k not in names}, float(cast("float", now))


def _rewrite_summary(path: Path, summary: RunSummary, *, usd_now: float | None = None) -> None:
    """Replace the `RunSummary` fields of a stored summary, keeping its other keys."""
    extra, stored_now = _summary_extras(path)
    write_summary(
        summary, path, usd_per_script_mean_now=stored_now if usd_now is None else usd_now, extra=extra
    )
```

- [ ] **Step 7: `run_real`.** Add after `run_config`:

```python
def _real_projection(
    out_dir: Path, max_run_usd: Mapping[str, float] | None
) -> dict[str, float]:
    """A real run's projected cost: the larger of *max_run_usd* and the latest real run's."""
    costs = sorted(
        out_dir.glob(f"*/{REAL_RUN_PREFIX}*/{RUN_COST_FILE}"), key=lambda p: p.stat().st_mtime
    )
    last: dict[str, float] = {}
    if costs:
        data = json.loads(costs[-1].read_text(encoding="utf-8"))
        last = {str(k): float(v) for k, v in data.items()}
    explicit = dict(max_run_usd or {})
    if not last and not explicit:
        raise SpendCapError(
            "no real run in this out-dir to project the cost from; pass "
            "--max-run-usd provider=usd for the first one"
        )
    return {
        provider: max(last.get(provider, 0.0), explicit.get(provider, 0.0))
        for provider in sorted(set(last) | set(explicit))
    }


def run_real(
    label: str,
    overrides: Mapping[str, object],
    *,
    run_index: int,
    out_dir: Path,
    scripts: Sequence[RealScript],
    settings: Settings | None = None,
    caps: SpendCaps | None = None,
    max_run_usd: Mapping[str, float] | None = None,
    spend_file: Path | None = None,
    mark: Callable[[RealScript, GeminiClient, Settings], CorrectionResult] | None = None,
    on_checks_passed: Callable[[], None] | None = None,
) -> tuple[RealScriptResult, ...]:
    """One live pass over the frozen real scripts under *overrides*; write and score it.

    Writes ``<out_dir>/<label>/real-<run_index>/`` (records, scored results, the
    escalation events, the run's cost). Every call is live: the client bypasses the
    cache, under its own cache dir. Prices and the spend caps are checked before
    anything is written (the reference digests were checked when *scripts* were
    loaded); *on_checks_passed* runs next, and only then is the client built. Each
    finished script is booked to the ledger by `_CapGuard`. A script whose marking
    raised is incomplete; scripts the cap stopped are "not run (spend cap)".
    """
    if not scripts:
        raise LadderStateError("no real scripts: build and freeze the reference set first")
    caps = caps or SpendCaps()
    run_name = f"{REAL_RUN_PREFIX}{run_index}"
    run_dir = out_dir / label / run_name
    discipline: dict[str, object] = {
        "gemini.cache_forget_enabled": False,
        "paths.cache_dir": str(cache_dir_for(out_dir, f"{label}-{run_name}")),
    }
    effective = apply_overrides(apply_overrides(settings or load_settings(), overrides), discipline)
    preflight_prices(effective)
    ledger = SpendLedger(spend_file or DEFAULT_SPEND_FILE)
    spent_before = ledger.spent()
    check_can_start(spent_before, _real_projection(out_dir, max_run_usd), caps)
    if on_checks_passed is not None:
        on_checks_passed()
    marker = mark or mark_real_script
    gemini = GeminiClient(effective, default_cache_mode="bypass")
    guard = _CapGuard(CapWatch(caps, spent_before), ledger, label=f"{label}/{run_name}")
    escalations: list[dict[str, object]] = []
    current: list[str] = []

    def on_escalate(**payload: object) -> None:
        escalations.append({"case_key": current[-1] if current else None, **payload})

    outcomes: dict[str, tuple[CorrectionResult | None, float, str | None]] = {}
    bus.subscribe(EventType.GEMINI_ESCALATE, on_escalate)
    with record_calls():
        reset_process_counters()
        try:
            for script in scripts:
                current.append(script.key)
                set_call_context(case_key=script.key)
                started = time.monotonic()
                correction: CorrectionResult | None = None
                failure: str | None = None
                try:
                    correction = marker(script, gemini, effective)
                except CostCeilingError as exc:
                    failure = f"cost ceiling: {exc}"
                except Exception as exc:  # noqa: BLE001 -- recorded as incomplete, never dropped
                    failure = f"{type(exc).__name__}: {exc}"
                outcomes[script.key] = (correction, (time.monotonic() - started) * 1000, failure)
                try:
                    guard(script.key)
                except SpendCapReached:
                    break
        finally:
            bus.unsubscribe(EventType.GEMINI_ESCALATE, on_escalate)
            set_call_context(case_key=None)
            records = process_call_records()
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / RUN_COST_FILE).write_text(
                json.dumps(cost_by_provider(records), sort_keys=True) + "\n", encoding="utf-8"
            )
            booked = set(guard.completed)
            ledger.add(cost_by_provider([r for r in records if r.case_key not in booked]))
            (run_dir / "records.jsonl").write_text(
                "".join(json.dumps(asdict(r), sort_keys=True) + "\n" for r in records),
                encoding="utf-8",
            )
            (run_dir / "escalations.jsonl").write_text(
                "".join(json.dumps(e, sort_keys=True, default=str) + "\n" for e in escalations),
                encoding="utf-8",
            )
    cascade = effective.gemini.cascade_enabled is True
    results = tuple(
        score_script(
            script,
            outcomes.get(script.key, (None, 0.0, None))[0],
            [r for r in records if r.case_key == script.key],
            latency_ms=outcomes.get(script.key, (None, 0.0, None))[1],
            failure=outcomes.get(script.key, (None, 0.0, "not run (spend cap)"))[2],
            escalations=[e for e in escalations if e.get("case_key") == script.key],
            cascade_enabled=cascade,
        )
        for script in scripts
    )
    write_real_results(run_dir / "real_results.json", results)
    return results
```

- [ ] **Step 8: Judge dispatch.** Add:

```python
def _judge(
    kind: JudgeKind,
    against: RunSummary,
    candidate: RunSummary,
    *,
    floor: int,
    real_floor: float,
    original_p95: float,
) -> Verdict:
    if kind == "cost":
        return judge_cost_lever(
            against,
            candidate,
            aa_floor=floor,
            real_aa_floor=real_floor,
            original_latency_p95_ms=original_p95,
        )
    if kind == "accuracy":
        return judge_accuracy_lever(against, candidate, aa_floor=floor, real_aa_floor=real_floor)
    return judge_record(against, candidate)
```

- [ ] **Step 9: `run_baseline` with `split` and `repeats`.** Add the parameters `split: Split = "dev"`, `repeats: int = 1`, `real_scripts: Sequence[RealScript] = ()`, and document them in the docstring ("*split* real or both adds two live real runs and ``real_aa_floor``; *repeats* 2 stores the dev baseline as the pair of the baseline and A/A runs"). Rename the current body below the `restart and aa_only` check into a nested function `dev() -> int` that does exactly what it does today and returns the floor. Then the body becomes:

```python
    if restart and aa_only:
        raise ValueError("--restart-baseline and --aa-only are mutually exclusive")
    if split != "dev" and aa_only:
        raise ValueError("--aa-only reruns the dev A/A run only; use --split dev")
    if split != "dev" and not real_scripts:
        raise LadderStateError("the real split needs the frozen reference scripts")
    base_summary = out_dir / BASELINE_LABEL / "summary.json"
    floor = 0
    if split in ("dev", "both"):
        floor = dev()
        if repeats == 2:
            aa_path = out_dir / AA_LABEL / "summary.json"
            _, aa_now = _summary_extras(aa_path)
            _, base_now = _summary_extras(base_summary)
            _rewrite_summary(
                base_summary,
                pair_summaries(read_summary(base_summary), read_summary(aa_path)),
                usd_now=(base_now + aa_now) / 2,
            )
    if split in ("real", "both"):
        if split == "real":
            if base_summary.exists() and not restart:
                raise RuntimeError(
                    f"{base_summary} exists; pass --restart-baseline to replace this baseline"
                )

            def wipe_real() -> None:
                _archive_ladder(out_dir)
                if (out_dir / BASELINE_LABEL).exists():
                    shutil.rmtree(out_dir / BASELINE_LABEL)
                (out_dir / AA_FLOOR_FILE).unlink(missing_ok=True)

            hook: Callable[[], None] | None = wipe_real if restart else None
        else:
            hook = None
        runs = []
        for index in (1, 2):
            runs.append(
                run_real(
                    BASELINE_LABEL,
                    {},
                    run_index=index,
                    out_dir=out_dir,
                    scripts=real_scripts,
                    settings=settings,
                    caps=caps,
                    max_run_usd=max_run_usd,
                    spend_file=spend_file,
                    on_checks_passed=hook if index == 1 else None,
                )
            )
        if split == "real":
            write_summary(
                with_real(EMPTY_DEV_SUMMARY, runs),
                base_summary,
                usd_per_script_mean_now=0.0,
                extra={"overrides": {}, "live_tags": [], "frozen_upstream": False, "split": "real"},
            )
        else:
            _rewrite_summary(base_summary, with_real(read_summary(base_summary), runs))
        first, second = (float(sum(s.abs_error for s in run)) for run in runs)
        floors_path = out_dir / AA_FLOOR_FILE
        floors: dict[str, object] = (
            json.loads(floors_path.read_text(encoding="utf-8"))
            if split == "both" and floors_path.is_file()
            else {"aa_floor": 0}
        )
        floors["real_aa_floor"] = abs(first - second)
        floors_path.write_text(json.dumps(floors, sort_keys=True) + "\n", encoding="utf-8")
    return floor
```

`run_real` imports nothing from `run_baseline`; the hook runs after the first real run's checks, so a refused real baseline deletes nothing.

- [ ] **Step 10: `run_screen` with `split`, `judge_kind` and `repeats`.** Add the parameters `split: Split = "dev"`, `judge_kind: JudgeKind = "cost"`, `repeats: int = 1`, `real_scripts: Sequence[RealScript] = ()`. Changes, in order:
  1. After the reserved-label checks: `if split != "dev" and not real_scripts: raise LadderStateError("the real split needs the frozen reference scripts")` and `if repeats not in (1, 2): raise ValueError(f"repeats must be 1 or 2, got {repeats}")`. Also reserve the `-r2` name: `if label.endswith(REPEAT_SUFFIX): raise ValueError(f"{label!r} ends in {REPEAT_SUFFIX!r}, which names a screen's second run")`.
  2. Replace the floor read with:

```python
    floors = json.loads(floor_path.read_text(encoding="utf-8"))
    floor = int(floors["aa_floor"])
    real_floor_raw = floors.get("real_aa_floor")
    if split != "dev" and real_floor_raw is None:
        raise LadderStateError(
            f"{floor_path} has no real_aa_floor: the baseline has no real split. "
            "Run `baseline --split both` first."
        )
    real_floor = float(real_floor_raw or 0.0)
```

  3. Read the frozen baseline records only when the dev split runs: `frozen = read_records(...) if split != "real" else []`.
  4. Replace the single `candidate = run_config(...)` call with:

```python
    summary_path = run_dir / "summary.json"
    base_cache = cache_dir_for(out_dir, BASELINE_LABEL)

    def drop_stale() -> None:
        for stale in ("verdict.json", "summary.json", "results.json"):
            (run_dir / stale).unlink(missing_ok=True)
        _drop_from_ladder(out_dir, label)

    candidate: RunSummary | None = None
    usd_now: float | None = None
    if split in ("dev", "both"):
        candidate = run_config(
            label,
            combined,
            out_dir=out_dir,
            golden_dir=golden_dir,
            cases=cases,
            settings=settings,
            caps=caps,
            max_run_usd=max_run_usd,
            cache_dir=cache,
            cache_mode="read_write",
            live_tags=tags,
            frozen_upstream=frozen,
            summary_extra={"against": against, "set": dict(sets)},
            spend_file=spend_file,
            on_checks_passed=seed,
        )
        if repeats == 2:
            second_label = f"{label}{REPEAT_SUFFIX}"
            second_cache = cache_dir_for(out_dir, second_label)

            def seed_second() -> None:
                if second_cache.exists():
                    shutil.rmtree(second_cache)
                shutil.copytree(base_cache, second_cache)

            second = run_config(
                second_label,
                combined,
                out_dir=out_dir,
                golden_dir=golden_dir,
                cases=cases,
                settings=settings,
                caps=caps,
                max_run_usd=max_run_usd,
                cache_dir=second_cache,
                cache_mode="read_write",
                live_tags=tags,
                frozen_upstream=frozen,
                summary_extra={"against": against, "set": dict(sets), "repeat_of": label},
                spend_file=spend_file,
                on_checks_passed=seed_second,
            )
            _, first_now = _summary_extras(summary_path)
            _, second_now = _summary_extras(out_dir / second_label / "summary.json")
            usd_now = (first_now + second_now) / 2
            candidate = pair_summaries(candidate, second)
    if split in ("real", "both"):
        runs = [
            run_real(
                label,
                combined,
                run_index=index,
                out_dir=out_dir,
                scripts=real_scripts,
                settings=settings,
                caps=caps,
                max_run_usd=max_run_usd,
                spend_file=spend_file,
                on_checks_passed=drop_stale if candidate is None and index == 1 else None,
            )
            for index in range(1, repeats + 1)
        ]
        candidate = with_real(candidate or EMPTY_DEV_SUMMARY, runs)
    assert candidate is not None  # split is one of the three literals
    if summary_path.is_file():
        _rewrite_summary(summary_path, candidate, usd_now=usd_now)
    else:
        write_summary(
            candidate,
            summary_path,
            usd_per_script_mean_now=0.0,
            extra={
                "overrides": combined,
                "live_tags": tags,
                "frozen_upstream": False,
                "against": against,
                "set": dict(sets),
                "split": split,
            },
        )
```

  Note the `range(...)` comprehension calls `drop_stale` only for the first real run of a real-only screen; in a "both" screen `seed` (the dev run's hook) already dropped the stale files.

  5. Replace the `verdict = judge(...)` call with:

```python
    verdict = _judge(
        judge_kind,
        read_summary(against_summary_path),
        candidate,
        floor=floor,
        real_floor=real_floor,
        original_p95=original_p95,
    )
```

  6. Add to the `verdict.json` dict: `"judge": judge_kind, "split": split, "repeats": repeats, "notes": list(verdict.notes),`.

- [ ] **Step 11: The reference rung and the flip verdict.** Add after `run_screen`:

```python
def run_reference_rung(
    label: str,
    *,
    out_dir: Path,
    real_scripts: Sequence[RealScript],
    dev_summary_from: Path,
    settings: Settings | None = None,
    repeats: int = 2,
    caps: SpendCaps | None = None,
    max_run_usd: Mapping[str, float] | None = None,
    spend_file: Path | None = None,
) -> RunSummary:
    """A comparison rung (the Gemini rung `judge_flip` reads): never a ladder row.

    The real split runs live *repeats* times under *settings*. The dev figures are
    read from *dev_summary_from*, a complete earlier run of the same configuration on
    the pinned corpus: two fresh Gemini dev runs do not fit under the Gemini cap.
    """
    if label in (BASELINE_LABEL, AA_LABEL, CACHE_SUBDIR, ARCHIVE_SUBDIR) or label in _ladder_labels(
        out_dir
    ):
        raise LadderStateError(f"{label!r} is reserved or already a ladder row")
    dev = require_complete(dev_summary_from, "dev summary of the reference rung")
    runs = [
        run_real(
            label,
            {},
            run_index=index,
            out_dir=out_dir,
            scripts=real_scripts,
            settings=settings,
            caps=caps,
            max_run_usd=max_run_usd,
            spend_file=spend_file,
        )
        for index in range(1, repeats + 1)
    ]
    summary = with_real(dev, runs)
    write_summary(
        summary,
        out_dir / label / "summary.json",
        usd_per_script_mean_now=0.0,
        extra={
            "reference_rung": True,
            "dev_from": str(dev_summary_from),
            "overrides": {},
            "live_tags": [],
        },
    )
    return summary


def flip_verdict(out_dir: Path, *, candidate: str, gemini: str) -> Verdict:
    """`judge_flip` of the *candidate* rung against the *gemini* rung; writes flip_verdict.json."""
    cand = read_summary(require_file(out_dir / candidate / "summary.json", f"rung {candidate!r}"))
    gem = read_summary(require_file(out_dir / gemini / "summary.json", f"Gemini rung {gemini!r}"))
    floors = json.loads(
        require_file(out_dir / AA_FLOOR_FILE, "A/A floor aa_floor.json").read_text(encoding="utf-8")
    )
    verdict = judge_flip(gem, cand, aa_floor=int(floors["aa_floor"]))
    (out_dir / FLIP_VERDICT_FILE).write_text(
        json.dumps(
            {
                "candidate": candidate,
                "gemini": gemini,
                "passed": verdict.passed,
                "saving": verdict.saving,
                "extra_mismarks": verdict.extra_mismarks,
                "allowed_extra": verdict.allowed_extra,
                "reasons": list(verdict.reasons),
                "notes": list(verdict.notes),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return verdict
```

- [ ] **Step 12: `resummarise` refuses a real run.** At the top of `resummarise`, after the `verdict.json` refusal, add:

```python
    stored = run_dir / "summary.json"
    if stored.is_file() and json.loads(stored.read_text(encoding="utf-8")).get("real_scripts"):
        raise LadderStateError(
            f"resummarise {label!r} is refused: it has a real split, whose per-leaf results "
            "are not rebuilt from records. Rescreen it instead."
        )
```

- [ ] **Step 13: Run the new tests and every existing runner test.**

Run: `.venv/bin/python -m pytest tests/test_cost_ladder_real_runner.py tests/test_cost_ladder_runner.py tests/test_cost_ladder_gate.py tests/test_cost_ladder_judges.py tests/test_cost_ladder_review_rate.py tests/test_cost_ladder_real_split.py -q --no-cov -o addopts=""`
Expected: all pass. If an existing runner test asserts the exact `verdict.json` keys, extend that assertion with the four new keys rather than dropping it; report the edit.

- [ ] **Step 14: Prove the guards red.**
  - In `run_real`, move `on_checks_passed()` and the client build above `check_can_start`; `test_run_real_refuses_without_a_projection` fails (`h.clients` not empty). Revert.
  - In `run_screen`, delete the `real_aa_floor` refusal; `test_screen_real_split_refuses_without_a_real_floor` fails. Revert.
  - In `run_real`, pass `failure=None` to `score_script` instead of the recorded failure; `test_run_real_failed_script_is_incomplete_and_the_rest_run` fails. Revert.
  - In `read_summary`, drop the `real_usd_by_script=` line; `test_read_summary_round_trips_real_fields` fails. Revert.
  Rerun step 13: all pass.

- [ ] **Step 15: Gates and commit.**

```bash
.venv/bin/python -m pytest tests/test_llm_golden.py -q --no-cov -o addopts=""
PATH=$PWD/.venv/bin:$PATH pre-commit run --files lemely/accuracy/cost_ladder/runner.py tests/test_cost_ladder_real_runner.py
git add -- lemely/accuracy/cost_ladder/runner.py tests/test_cost_ladder_real_runner.py
git commit -S -m "feat(cost_ladder): real-split runs, paired rungs, accuracy judging and the flip verdict" -- lemely/accuracy/cost_ladder/runner.py tests/test_cost_ladder_real_runner.py
```

---
### Task 8: Report: real and escalation columns in `LADDER.md`, and `FLIP.md`

**Files:**
- Modify: `lemely/accuracy/cost_ladder/report.py`
- Test: `tests/test_cost_ladder_real_report.py` (new)

**Interfaces:**
- Consumes: Task 5 (`RunSummary` real fields, `Verdict.notes`), Task 7 (`read_summary`, `FLIP_VERDICT_FILE`, `require_file`).
- Produces (Tasks 9, 28): `REAL_HEADER: tuple[str, ...]`; `write_ladder(rows, out, *, footer, notes=(), real=False)` (unchanged output when `real` is False); `load_rows` reads `notes`; `write_report` adds the real columns when the baseline or any row has a real split; `write_flip(out_dir: Path, *, candidate: str, gemini: str) -> Path` writes `<out_dir>/FLIP.md`.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_cost_ladder_real_report.py`:

```python
"""Sub-project C P1: real-split and escalation figures in LADDER.md and FLIP.md (counts only)."""

from __future__ import annotations

import json
from pathlib import Path

from lemely.accuracy.cost_ladder import runner
from lemely.accuracy.cost_ladder.gate import RunSummary, Verdict
from lemely.accuracy.cost_ladder.report import (
    HEADER,
    REAL_HEADER,
    LadderFooter,
    LadderRow,
    write_flip,
    write_ladder,
    write_report,
)

_FOOT = LadderFooter(0.1, 0.1, 0.05, 0.05, "done")


def _real(**kw: object) -> RunSummary:
    base = RunSummary(0.05, 1000.0, frozenset(), 78, 1.0, 1.0, (), real_scripts=("a", "b"),
                      real_abs_error=12.5, real_exact_rate=0.8, real_within1_rate=0.95,
                      real_review_rate=0.3, real_binding_passes=2.0, real_usd_mean=0.05,
                      real_usd_by_script=(("a", 0.04), ("b", 0.06)),
                      real_usd_max_by_script=(("a", 0.045), ("b", 0.07)),
                      real_escalation_rate=0.05, real_escalation_rate_max_script=0.08,
                      real_escalation_usd_by_script=(("a", 0.004), ("b", 0.006)))
    from dataclasses import replace

    return replace(base, **kw)  # type: ignore[arg-type]


def _verdict(**kw: object) -> Verdict:
    return Verdict(True, "small", 0.1, 0, 0, (), **kw)  # type: ignore[arg-type]


def test_ladder_without_real_keeps_todays_header(tmp_path: Path) -> None:
    out = tmp_path / "L.md"
    write_ladder([LadderRow("x", "1%", RunSummary(1, 1, frozenset(), 1, 1, 1, ()), _verdict(), "p")],
                 out, footer=_FOOT)
    assert "| " + " | ".join(HEADER) + " |" in out.read_text()
    assert REAL_HEADER[0] not in out.read_text()


def test_ladder_with_real_adds_the_columns(tmp_path: Path) -> None:
    out = tmp_path / "L.md"
    write_ladder([LadderRow("a1", "13%", _real(), _verdict(notes=("real saving 4.0%",)), "p")],
                 out, footer=_FOOT, real=True)
    text = out.read_text()
    assert "| " + " | ".join(HEADER + REAL_HEADER) + " |" in text
    row = [line for line in text.splitlines() if line.startswith("| a1 ")][0]
    for cell in ("12.5", "80.0%", "95.0%", "30.0%", "2.0/2", "b $0.0700", "5.0%", "10.0%",
                 "real saving 4.0%"):
        assert f"| {cell} |" in row or row.endswith(f"| {cell} |"), cell


def test_write_report_switches_real_columns_on_from_the_baseline(tmp_path: Path) -> None:
    runner.write_summary(_real(), tmp_path / "baseline" / "summary.json", usd_per_script_mean_now=0.05)
    path = write_report(tmp_path, stop_reason="none")
    assert REAL_HEADER[0] in path.read_text()


def test_flip_report_has_both_sides_and_no_leaf_marks(tmp_path: Path) -> None:
    runner.write_summary(_real(), tmp_path / "stack" / "summary.json", usd_per_script_mean_now=0.0)
    runner.write_summary(_real(real_abs_error=14.0, real_escalation_rate=None),
                         tmp_path / "gemini" / "summary.json", usd_per_script_mean_now=0.0)
    (tmp_path / runner.FLIP_VERDICT_FILE).write_text(json.dumps({
        "candidate": "stack", "gemini": "gemini", "passed": True, "reasons": [],
        "notes": ["escalation rate 5.0% (max script 8.0%)"]}))
    text = write_flip(tmp_path, candidate="stack", gemini="gemini").read_text()
    assert "| real abs error (marks) | 14.0 | 12.5 |" in text
    assert "| escalation rate | - | 5.0% |" in text
    assert "Verdict: PASS" in text
    assert "escalation rate 5.0% (max script 8.0%)" in text
    assert "| b | $0.0700 | $0.0700 | $0.0060 |" in text
```

- [ ] **Step 2: Run them to watch them fail.**

Run: `.venv/bin/python -m pytest tests/test_cost_ladder_real_report.py -q --no-cov -o addopts=""`
Expected: `ImportError: cannot import name 'REAL_HEADER'`.

- [ ] **Step 3: Write the code.** In `lemely/accuracy/cost_ladder/report.py`, import `FLIP_VERDICT_FILE` from the runner beside `read_summary`, and add after `HEADER`:

```python
#: Real-split columns, shown when the ladder has a real split (sub-project C).
REAL_HEADER = (
    "real abs err",
    "exact",
    "within 1",
    "real review",
    "binding pass",
    "max $/script",
    "esc rate",
    "esc $ share",
    "notes",
)


def _pct(rate: float | None) -> str:
    return "-" if rate is None else f"{rate * 100:.1f}%"


def _escalation_share(c: RunSummary) -> float | None:
    total = sum(usd for _, usd in c.real_usd_by_script)
    esc = sum(usd for _, usd in c.real_escalation_usd_by_script)
    return esc / total if total else None


def _worst_script(c: RunSummary) -> str:
    if not c.real_usd_max_by_script:
        return "-"
    key, usd = max(c.real_usd_max_by_script, key=lambda kv: kv[1])
    return f"{key} ${usd:.4f}"


def _real_cells(c: RunSummary, v: Verdict) -> list[str]:
    if not c.real_scripts:
        return ["-"] * (len(REAL_HEADER) - 1) + ["; ".join(v.notes) or "-"]
    return [
        f"{c.real_abs_error:.1f}",
        _pct(c.real_exact_rate),
        _pct(c.real_within1_rate),
        _pct(c.real_review_rate),
        f"{c.real_binding_passes:.1f}/{len(c.real_scripts)}",
        _worst_script(c),
        _pct(c.real_escalation_rate),
        _pct(_escalation_share(c)),
        "; ".join(v.notes) or "-",
    ]
```

Change `write_ladder`'s signature to `write_ladder(rows, out, *, footer, notes=(), real: bool = False)` and build the table with:

```python
    header = HEADER + REAL_HEADER if real else HEADER
    lines += [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    lines += [
        "| "
        + " | ".join(_cell(c) for c in _row(r) + (_real_cells(r.candidate, r.verdict) if real else []))
        + " |"
        for r in rows
    ]
```

In `load_rows`, build the `Verdict` with `notes=tuple(v.get("notes", []))`. In `write_report`, after `rows, final = load_rows(out_dir)`:

```python
    base_run = read_summary(base / "summary.json")
    real = bool(base_run.real_scripts) or any(r.candidate.real_scripts for r in rows)
    if base_run.real_scripts:
        notes.append(
            f"Baseline real split: abs error {base_run.real_abs_error:.1f} marks over "
            f"{len(base_run.real_scripts)} scripts, review {_pct(base_run.real_review_rate)}, "
            f"escalation {_pct(base_run.real_escalation_rate)}, worst script "
            f"{_worst_script(base_run)}."
        )
```

and pass `real=real` to `write_ladder`. Then add:

```python
def write_flip(out_dir: Path, *, candidate: str, gemini: str) -> Path:
    """``<out_dir>/FLIP.md``: the flip judgement, Gemini beside the candidate. Counts only."""
    cand = read_summary(require_file(out_dir / candidate / "summary.json", f"rung {candidate!r}"))
    gem = read_summary(require_file(out_dir / gemini / "summary.json", f"Gemini rung {gemini!r}"))
    verdict = json.loads(
        require_file(out_dir / FLIP_VERDICT_FILE, "flip verdict (run `judge-flip`)").read_text(
            encoding="utf-8"
        )
    )

    def usd(c: RunSummary) -> str:
        return f"${c.real_usd_mean:.4f}"

    figures = [
        ("real abs error (marks)", f"{gem.real_abs_error:.1f}", f"{cand.real_abs_error:.1f}"),
        ("exact leaves", _pct(gem.real_exact_rate), _pct(cand.real_exact_rate)),
        ("within 1 mark", _pct(gem.real_within1_rate), _pct(cand.real_within1_rate)),
        ("review rate", _pct(gem.real_review_rate), _pct(cand.real_review_rate)),
        (
            "binding passes",
            f"{gem.real_binding_passes:.1f}/{len(gem.real_scripts)}",
            f"{cand.real_binding_passes:.1f}/{len(cand.real_scripts)}",
        ),
        ("mean $ per script (2027)", usd(gem), usd(cand)),
        ("worst script", _worst_script(gem), _worst_script(cand)),
        ("escalation rate", _pct(gem.real_escalation_rate), _pct(cand.real_escalation_rate)),
        ("escalation $ share", _pct(_escalation_share(gem)), _pct(_escalation_share(cand))),
        ("synthetic mismarked parts", str(len(gem.mismarked_parts)), str(len(cand.mismarked_parts))),
    ]
    lines = [
        "# Flip judgement",
        "",
        f"Candidate `{candidate}` against the Gemini rung `{gemini}`. Real split: the frozen "
        "reference set, two live runs each; per-leaf marks stay uncommitted. Counts only.",
        "",
        "| figure | Gemini | Claude candidate |",
        "|---|---|---|",
        *(f"| {name} | {g} | {c} |" for name, g, c in figures),
        "",
        "| script | Gemini max $ | Claude max $ | Claude escalation $ |",
        "|---|---|---|---|",
    ]
    gem_max = dict(gem.real_usd_max_by_script)
    cand_esc = dict(cand.real_escalation_usd_by_script)
    for key, cand_usd in cand.real_usd_max_by_script:
        lines.append(
            f"| {key} | ${gem_max.get(key, float('nan')):.4f} | ${cand_usd:.4f} | "
            f"${cand_esc.get(key, 0.0):.4f} |"
        )
    lines += [
        "",
        f"Verdict: {'PASS' if verdict['passed'] else 'FAIL'}",
        "",
        "Reasons:",
        *(f"- {r}" for r in verdict["reasons"] or ["none"]),
        "",
        "Notes:",
        *(f"- {n}" for n in verdict.get("notes") or ["none"]),
        "",
    ]
    target = out_dir / "FLIP.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    return target
```

- [ ] **Step 4: Run the report tests, new and old.**

Run: `.venv/bin/python -m pytest tests/test_cost_ladder_real_report.py tests/test_cost_ladder_runner.py -q --no-cov -o addopts=""`
Expected: all pass (the existing ladder tests write dev-only ladders, whose header is unchanged).

- [ ] **Step 5: Prove red.** Make `write_ladder` always use `HEADER + REAL_HEADER`; `test_ladder_without_real_keeps_todays_header` fails. Revert. Swap the Gemini and candidate columns in `figures`; `test_flip_report_has_both_sides_and_no_leaf_marks` fails. Revert.

- [ ] **Step 6: Gates and commit.**

```bash
.venv/bin/python -m pytest tests/test_llm_golden.py -q --no-cov -o addopts=""
PATH=$PWD/.venv/bin:$PATH pre-commit run --files lemely/accuracy/cost_ladder/report.py tests/test_cost_ladder_real_report.py
git add -- lemely/accuracy/cost_ladder/report.py tests/test_cost_ladder_real_report.py
git commit -S -m "feat(cost_ladder): real-split and escalation columns, FLIP.md" -- lemely/accuracy/cost_ladder/report.py tests/test_cost_ladder_real_report.py
```

---

### Task 9: `scripts/cost_ladder.py` CLI for the real split

**Files:**
- Modify: `scripts/cost_ladder.py`
- Test: `tests/test_cost_ladder_cli.py` (new)

**Interfaces:**
- Consumes: Task 6 (`load_real_scripts`, `DEFAULT_MANIFEST`), Task 7 (`run_baseline`, `run_screen`, `run_reference_rung`, `flip_verdict` with their new keywords), Task 8 (`write_report`, `write_flip`).
- Produces (Tasks 13b, 23 to 28 type these commands):
  - Global flags: `--config PATH` (a lemely TOML; the settings every run uses, default: `load_settings()`), `--split {dev,real,both}` (default `dev`), `--repeats {1,2}` (default 1), `--manifest PATH` (default `DEFAULT_MANIFEST`), `--only KEY` (repeatable; restrict the real scripts).
  - `screen ... --judge {cost,accuracy,record}` (default `cost`).
  - `reference-rung --label L --dev-from PATH/summary.json`.
  - `judge-flip --candidate L --gemini G` (writes `flip_verdict.json` and `FLIP.md`).
  - Keys are loaded inside the process from `~/.config/lemely/{anthropic,gemini}_key` (`load_keys()`), before `require_gemini_key`.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_cost_ladder_cli.py`:

```python
"""Sub-project C P1: the cost-ladder CLI's real-split wiring. The runner is stubbed."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "cost_ladder_cli", Path(__file__).resolve().parents[1] / "scripts" / "cost_ladder.py"
)
assert _SPEC is not None and _SPEC.loader is not None
cli = importlib.util.module_from_spec(_SPEC)
sys.modules["cost_ladder_cli"] = cli
_SPEC.loader.exec_module(cli)


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {}
    monkeypatch.setattr(cli, "load_keys", lambda: calls.setdefault("keys", True))
    monkeypatch.setattr(cli, "require_gemini_key", lambda env: None)
    monkeypatch.setattr(cli, "load_real_scripts", lambda path, only=(): calls.setdefault(
        "scripts", (path, tuple(only))) and ["S"])
    return calls


def test_screen_passes_split_repeats_judge_and_scripts(seen: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from lemely.accuracy.cost_ladder.gate import Verdict

    def fake_screen(label: str, sets: dict[str, object], **kw: Any) -> Verdict:
        seen["screen"] = (label, sets, kw)
        return Verdict(True, "small", 0.0, 0, 0, ())

    monkeypatch.setattr(cli, "run_screen", fake_screen)
    toml = tmp_path / "base.toml"
    toml.write_text("[gemini]\ncorrection_model = \"claude-haiku-5-5\"\n")
    code = cli.main(["--out-dir", str(tmp_path), "--config", str(toml), "--split", "both",
                     "--repeats", "2", "--only", "0625_w24_41", "screen", "--label", "b1",
                     "--judge", "accuracy", "--set", "gemini.correction_citations=true"])
    assert code == 0 and seen["keys"] is True
    label, sets, kw = seen["screen"]
    assert label == "b1" and sets == {"gemini.correction_citations": True}
    assert kw["split"] == "both" and kw["repeats"] == 2 and kw["judge_kind"] == "accuracy"
    assert kw["real_scripts"] == ["S"]
    assert kw["settings"].gemini.correction_model == "claude-haiku-5-5"
    assert seen["scripts"][1] == ("0625_w24_41",)


def test_dev_split_loads_no_real_scripts(seen: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "run_baseline", lambda **kw: seen.setdefault("baseline", kw) and 0)
    assert cli.main(["--out-dir", str(tmp_path), "baseline"]) == 0
    assert "scripts" not in seen and seen["baseline"]["real_scripts"] == ()


def test_reference_rung_and_judge_flip(seen: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from lemely.accuracy.cost_ladder.gate import RunSummary, Verdict

    monkeypatch.setattr(cli, "run_reference_rung", lambda label, **kw: seen.setdefault(
        "ref", (label, kw)) and RunSummary(0, 0, frozenset(), 0, 1, 1, ()))
    monkeypatch.setattr(cli, "flip_verdict", lambda out, **kw: Verdict(False, "small", 0, 0, 0, ("x",)))
    monkeypatch.setattr(cli, "write_flip", lambda out, **kw: out / "FLIP.md")
    dev = tmp_path / "summary.json"
    assert cli.main(["--out-dir", str(tmp_path), "--split", "real", "reference-rung",
                     "--label", "gemini", "--dev-from", str(dev)]) == 0
    assert seen["ref"][0] == "gemini" and seen["ref"][1]["dev_summary_from"] == dev
    assert cli.main(["--out-dir", str(tmp_path), "judge-flip", "--candidate", "stack",
                     "--gemini", "gemini"]) == 1


def test_load_keys_reads_files_without_overwriting(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".config" / "lemely").mkdir(parents=True)
    (home / ".config" / "lemely" / "anthropic_key").write_text("ak-1\n")
    (home / ".config" / "lemely" / "gemini_key").write_text("from-file\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "kept")
    cli.load_keys()
    import os

    assert os.environ["ANTHROPIC_API_KEY"] == "ak-1"
    assert os.environ["GEMINI_API_KEY"] == "kept"
```

- [ ] **Step 2: Run them to watch them fail.**

Run: `.venv/bin/python -m pytest tests/test_cost_ladder_cli.py -q --no-cov -o addopts=""`
Expected: `AttributeError: module 'cost_ladder_cli' has no attribute 'load_keys'`.

- [ ] **Step 3: Write the code.** In `scripts/cost_ladder.py`:
  1. Update the module docstring's usage block:

```text
    cost_ladder.py [--config base.toml] [--split dev|real|both] [--repeats 1|2] baseline [--restart-baseline | --aa-only]
    cost_ladder.py ... screen --label L --lever "..." --expected-saving 40% --judge cost|accuracy|record \\
        --set gemini.correction_model=... [--against <label>] [--live-tags correction,...]
    cost_ladder.py --split real --config gemini.toml reference-rung --label gemini --dev-from OLD/summary.json
    cost_ladder.py judge-flip --candidate stack --gemini gemini
    cost_ladder.py resummarise --label L        # $0, dev runs only
    cost_ladder.py report --stop-reason "..."
```

and replace "Keys come from the environment only (a wrapper exports ...)" with "Keys are read inside this process from ~/.config/lemely/{anthropic,gemini}_key (an exported variable wins); this script never prints them."
  2. Imports: add `from lemely.accuracy.cost_ladder.real_split import DEFAULT_MANIFEST, load_real_scripts`, `from lemely.accuracy.cost_ladder.report import write_flip, write_report`, `from lemely.accuracy.cost_ladder.runner import flip_verdict, run_reference_rung` (beside the existing runner imports), `from lemely.accuracy.cost_ladder.real_split import ReferenceDrift`, `from lemely.runtime.config import Settings, load_settings`.
  3. Add helpers:

```python
_KEY_FILES = (
    ("ANTHROPIC_API_KEY", "~/.config/lemely/anthropic_key"),
    ("GEMINI_API_KEY", "~/.config/lemely/gemini_key"),
)


def load_keys() -> None:
    """Read the API keys from their files into this process; an exported value wins."""
    for var, key_path in _KEY_FILES:
        path = Path(key_path).expanduser()
        if path.is_file() and not os.environ.get(var):
            os.environ[var] = path.read_text(encoding="utf-8").strip()


def _settings(args: argparse.Namespace) -> Settings:
    return load_settings(toml_path=args.config) if args.config is not None else load_settings()


def _scripts(args: argparse.Namespace) -> list[RealScript] | tuple[()]:
    if args.split == "dev":
        return ()
    return load_real_scripts(args.manifest, only=args.only)


def _live(args: argparse.Namespace) -> None:
    load_keys()
    require_gemini_key(os.environ)
```

  (import `RealScript` from `real_split` for the annotation, under `TYPE_CHECKING`.)
  4. `_baseline`: replace `require_gemini_key(os.environ)` with `_live(args)`; pass `settings=_settings(args)`, `split=args.split`, `repeats=args.repeats`, `real_scripts=_scripts(args)`.
  5. `_screen`: same `_live(args)`; pass `settings=_settings(args)`, `split=args.split`, `repeats=args.repeats`, `judge_kind=args.judge`, `real_scripts=_scripts(args)`. After the reasons, print each note: `for note in verdict.notes: print(f"  note: {note}")`.
  6. Add commands:

```python
def _reference_rung(args: argparse.Namespace) -> int:
    _live(args)
    summary = run_reference_rung(
        args.label,
        out_dir=args.out_dir,
        real_scripts=_scripts(args) or load_real_scripts(args.manifest, only=args.only),
        dev_summary_from=args.dev_from,
        settings=_settings(args),
        repeats=2,  # the Gemini rung always runs twice (spec P4)
        caps=_caps(args),
        max_run_usd=_max_run_usd(args),
        spend_file=args.spend_file,
    )
    print(
        f"reference rung {args.label}: real abs error {summary.real_abs_error:.1f}, "
        f"mean ${summary.real_usd_mean:.4f}/script"
    )
    return 0


def _judge_flip(args: argparse.Namespace) -> int:
    verdict = flip_verdict(args.out_dir, candidate=args.candidate, gemini=args.gemini)
    target = write_flip(args.out_dir, candidate=args.candidate, gemini=args.gemini)
    print(f"{'PASS' if verdict.passed else 'FAIL'} flip {args.candidate} vs {args.gemini}: {target}")
    for reason in verdict.reasons:
        print(f"  - {reason}")
    return 0 if verdict.passed else 1
```

  7. In `main`, add the global flags after `--golden`:

```python
    parser.add_argument("--config", type=Path, default=None, help="lemely TOML every run uses")
    parser.add_argument("--split", choices=("dev", "real", "both"), default="dev")
    parser.add_argument("--repeats", type=int, choices=(1, 2), default=1)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--only", action="append", default=[], metavar="KEY")
```

  add `screen.add_argument("--judge", choices=("cost", "accuracy", "record"), default="cost")`, and the two sub-parsers:

```python
    rung = sub.add_parser("reference-rung", help="a comparison rung (the Gemini rung)")
    rung.add_argument("--label", required=True)
    rung.add_argument("--dev-from", type=Path, required=True, help="a complete dev summary.json")
    rung.set_defaults(fn=_reference_rung)
    flip = sub.add_parser("judge-flip", help="judge_flip of a rung against the Gemini rung")
    flip.add_argument("--candidate", required=True)
    flip.add_argument("--gemini", required=True)
    flip.set_defaults(fn=_judge_flip)
```

  and add `ReferenceDrift` to the caught exceptions in `main`.

- [ ] **Step 4: Run the tests.**

Run: `.venv/bin/python -m pytest tests/test_cost_ladder_cli.py tests/test_cost_ladder_runner.py -q --no-cov -o addopts=""`
Expected: all pass.

- [ ] **Step 5: Prove red.** In `load_keys`, drop `and not os.environ.get(var)`; `test_load_keys_reads_files_without_overwriting` fails on `"kept"`. Revert. In `_screen`, drop `judge_kind=args.judge`; `test_screen_passes_split_repeats_judge_and_scripts` fails. Revert.

- [ ] **Step 6: Gates and commit.**

```bash
.venv/bin/python -m pytest tests/test_llm_golden.py -q --no-cov -o addopts=""
PATH=$PWD/.venv/bin:$PATH pre-commit run --files scripts/cost_ladder.py tests/test_cost_ladder_cli.py
git add -- scripts/cost_ladder.py tests/test_cost_ladder_cli.py
git commit -S -m "feat(cost_ladder): CLI for the real split, the Gemini rung and the flip judge" -- scripts/cost_ladder.py tests/test_cost_ladder_cli.py
```

---
### Task 10: Threshold fit moves into `lemely/accuracy/`; recall-based review fit and the escalation fit

**Files:**
- Create: `lemely/accuracy/threshold_fit.py`
- Modify: `scripts/fit_review_threshold.py` (keeps its CLI and its names)
- Test: `tests/test_threshold_fit.py` (new); `tests/test_fit_review_threshold.py` must pass unchanged.

**Interfaces:**
- Consumes: Task 6 (`read_real_results`, `RealScriptResult`, `LeafOutcome`) for `parts_from_real` and `escalation_leaves`.
- Produces (Task 26 runs these):
  - Moved unchanged: `CONFIDENCE_REASON` (the regex, now public), `Part`, `ThresholdStats`, `evaluate`, `threshold_grid`, `recommend`, `leave_one_case_out`.
  - New: `RECALL_TARGET = 0.90`; `recommend_for_recall(parts, *, recall=RECALL_TARGET) -> float | None` (lowest grid threshold whose flag recall reaches *recall*); `parts_from_real(paths: Sequence[Path]) -> list[Part]` (a real rung's `real_results.json` files; `mismarked` is abs_error > 0; a leaf is refittable when `marker_source == "ai"`, its flag is not structural, and it did not escalate; `case_key` is `"<run>:<script>"`).
  - `@dataclass(frozen=True) EscalationLeaf(case_key: str, script: str, confidence: float, wrong: bool)`; `escalation_leaves(paths) -> list[EscalationLeaf]` (AI-marked leaves with a `pre_escalation_confidence`).
  - `@dataclass(frozen=True) EscalationFit(threshold: float | None, recall: float | None, escalated: int, worst_script: str | None, worst_script_usd: float | None, met_recall: bool)`.
  - `ESCALATION_USD_ESTIMATE = 0.0056` (one Sonnet escalation on a cached prefix, `claude-e2e2-.../COST.md` opportunity 3), used when a rung made no escalation call.
  - `fit_escalation_threshold(leaves, *, script_base_usd: Mapping[str, float], usd_per_escalation: float, cap_usd: float = 0.10, recall: float = RECALL_TARGET) -> EscalationFit`.
  - Script CLI: `fit_review_threshold.py RESULTS.json` (today's behaviour); `fit_review_threshold.py --real RUN_DIR [--real RUN_DIR2]` (recall-based review fit on real results); `--escalation` with `--real` adds the escalation fit.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_threshold_fit.py`:

```python
"""Sub-project C P3 lever d: the review- and escalation-threshold fits, at $0."""

from __future__ import annotations

from pathlib import Path

import pytest

from lemely.accuracy import threshold_fit as tf
from lemely.accuracy.cost_ladder.real_split import LeafOutcome, RealScriptResult, write_real_results


def _part(conf: float, mismarked: bool, *, refittable: bool = True, flag: bool = False) -> tf.Part:
    return tf.Part("c", f"q{conf}", conf, mismarked, refittable, flag)


def test_recall_pick_is_the_lowest_threshold_that_reaches_the_target() -> None:
    parts = [_part(0.70, True), _part(0.84, True), _part(0.86, False), _part(0.95, False)]
    # Both wrong leaves are flagged from 0.85 up; 0.85 is the lowest such threshold.
    assert tf.recommend_for_recall(parts, recall=0.9) == 0.85


def test_recall_pick_counts_structural_flags() -> None:
    parts = [_part(0.99, True, refittable=False, flag=True), _part(0.60, True)]
    assert tf.recommend_for_recall(parts, recall=1.0) == 0.61


def test_recall_pick_none_when_nothing_is_wrong_or_unreachable() -> None:
    assert tf.recommend_for_recall([_part(0.9, False)]) is None
    assert tf.recommend_for_recall([_part(0.995, True)], recall=1.0) is None


def _leaf(qid: str, pred: int, ref: int, conf: float, *, escalated: bool = False,
          source: str = "ai", review: bool = False, reason: str | None = None) -> LeafOutcome:
    return LeafOutcome(qid, pred, ref, 2, review, conf, source, reason, escalated,
                       "confidence" if escalated else None, conf)


def _run(tmp_path: Path, name: str, scripts: list[RealScriptResult]) -> Path:
    path = tmp_path / name / "real_results.json"
    write_real_results(path, scripts)
    return path


def test_parts_from_real_marks_wrong_leaves_and_freezes_the_rest(tmp_path: Path) -> None:
    script = RealScriptResult("a", (
        _leaf("1", 1, 2, 0.85),
        _leaf("2", 2, 2, 0.95),
        _leaf("3", 0, 1, 0.70, escalated=True),
        _leaf("4", 0, 0, 0.99, source="deterministic"),
        _leaf("5", 1, 1, 0.97, review=True, reason="uncited_mark"),
    ), "pass", 0.05, 0.01, 0.0, 1.0, None)
    parts = tf.parts_from_real([_run(tmp_path, "real-1", [script])])
    by = {p.question_id: p for p in parts}
    assert by["1"].mismarked and by["1"].refittable
    assert not by["3"].refittable and not by["4"].refittable and not by["5"].refittable
    assert by["5"].recorded_flag is True
    assert {p.case_key for p in parts} == {"real-1:a"}


def test_escalation_fit_picks_the_lowest_threshold_reaching_recall_within_the_cap() -> None:
    leaves = [tf.EscalationLeaf("r:a", "a", c, w) for c, w in
              [(0.70, True), (0.78, True), (0.82, False), (0.90, False)]]
    fit = tf.fit_escalation_threshold(leaves, script_base_usd={"a": 0.05}, usd_per_escalation=0.01)
    assert fit.threshold == 0.79 and fit.escalated == 2 and fit.met_recall
    assert fit.worst_script == "a" and fit.worst_script_usd == pytest.approx(0.07)


def test_escalation_fit_backs_off_to_the_cap() -> None:
    leaves = [tf.EscalationLeaf("r:a", "a", c, True) for c in (0.60, 0.70, 0.80)]
    fit = tf.fit_escalation_threshold(leaves, script_base_usd={"a": 0.08}, usd_per_escalation=0.01)
    # Two escalations reach $0.10; three would pass it. Recall 2/3 misses the 0.9 target.
    assert fit.escalated == 2 and not fit.met_recall
    assert fit.worst_script_usd == pytest.approx(0.10)


def test_escalation_fit_none_when_even_no_escalation_breaches_the_cap() -> None:
    leaves = [tf.EscalationLeaf("r:a", "a", 0.6, True)]
    fit = tf.fit_escalation_threshold(leaves, script_base_usd={"a": 0.11}, usd_per_escalation=0.01)
    assert fit.threshold is None


def test_escalation_leaves_skip_non_ai_leaves(tmp_path: Path) -> None:
    script = RealScriptResult("a", (_leaf("1", 1, 2, 0.75), _leaf("2", 0, 0, 0.99, source="blank")),
                              "pass", 0.05, 0.0, 0.0, 1.0, None)
    (leaf,) = tf.escalation_leaves([_run(tmp_path, "real-1", [script])])
    assert leaf.wrong and leaf.confidence == 0.75 and leaf.script == "a"
```

- [ ] **Step 2: Run them to watch them fail.**

Run: `.venv/bin/python -m pytest tests/test_threshold_fit.py -q --no-cov -o addopts=""`
Expected: `ModuleNotFoundError: No module named 'lemely.accuracy.threshold_fit'`.

- [ ] **Step 3: Create the module.** Move `_CONFIDENCE_REASON` (renamed `CONFIDENCE_REASON`), `_EPS`, `Part`, `ThresholdStats`, `_flagged`, `evaluate`, `threshold_grid`, `recommend` and `leave_one_case_out` out of `scripts/fit_review_threshold.py` into `lemely/accuracy/threshold_fit.py`, byte for byte except the rename, under this module docstring and imports:

```python
"""Pure threshold fits for sub-project C lever d: the review and escalation thresholds, at $0.

Moved from ``scripts/fit_review_threshold.py`` (whose CLI stays). The fits read stored
results only: no client, no model call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from lemely.accuracy.cost_ladder.real_split import read_real_results

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
```

Then append:

```python
RECALL_TARGET = 0.90
#: One Sonnet escalation reading the cached correction prefix (claude-e2e2 COST.md,
#: opportunity 3: $0.0015 cache read plus about 400 output tokens). Used only when a
#: rung made no escalation call to measure the cost from.
ESCALATION_USD_ESTIMATE = 0.0056


def recommend_for_recall(parts: Sequence[Part], *, recall: float = RECALL_TARGET) -> float | None:
    """The lowest grid threshold whose flag recall reaches *recall*; None if none does."""
    for t in threshold_grid():
        got = evaluate(parts, t).flag_recall
        if got is not None and got + _EPS >= recall:
            return t
    return None


def _structural(flag: bool, reason: str | None) -> bool:
    return flag and not (isinstance(reason, str) and CONFIDENCE_REASON.match(reason) is not None)


def parts_from_real(paths: Sequence[Path]) -> list[Part]:
    """Every leaf of a real rung's runs as a `Part`; mismarked means abs_error > 0."""
    parts: list[Part] = []
    for path in paths:
        run = path.parent.name
        for script in read_real_results(path):
            for leaf in script.leaves:
                refittable = (
                    leaf.marker_source == "ai"
                    and not leaf.escalated
                    and leaf.confidence is not None
                    and not _structural(leaf.needs_review, leaf.review_reason)
                )
                parts.append(
                    Part(
                        case_key=f"{run}:{script.key}",
                        question_id=leaf.question_id,
                        confidence=leaf.confidence if leaf.confidence is not None else 1.0,
                        mismarked=leaf.abs_error > 0,
                        refittable=refittable,
                        recorded_flag=leaf.needs_review,
                    )
                )
    return parts


@dataclass(frozen=True)
class EscalationLeaf:
    case_key: str  # "<run>:<script>"
    script: str
    confidence: float  # the confidence the escalation decision reads
    wrong: bool  # abs_error > 0 against the reference


@dataclass(frozen=True)
class EscalationFit:
    threshold: float | None
    recall: float | None
    escalated: int
    worst_script: str | None
    worst_script_usd: float | None
    met_recall: bool


def escalation_leaves(paths: Sequence[Path]) -> list[EscalationLeaf]:
    """AI-marked leaves with the confidence their escalation was (or would be) decided on."""
    out: list[EscalationLeaf] = []
    for path in paths:
        run = path.parent.name
        for script in read_real_results(path):
            for leaf in script.leaves:
                if leaf.marker_source == "ai" and leaf.pre_escalation_confidence is not None:
                    out.append(
                        EscalationLeaf(
                            case_key=f"{run}:{script.key}",
                            script=script.key,
                            confidence=leaf.pre_escalation_confidence,
                            wrong=leaf.abs_error > 0,
                        )
                    )
    return out


def fit_escalation_threshold(
    leaves: Sequence[EscalationLeaf],
    *,
    script_base_usd: Mapping[str, float],
    usd_per_escalation: float,
    cap_usd: float = 0.10,
    recall: float = RECALL_TARGET,
) -> EscalationFit:
    """The escalation threshold: escalate the wrong leaves, keep every script under the cap.

    For each grid threshold t, the leaves with confidence below t escalate. A run's
    script then costs its base cost (without escalation) plus its escalations at
    *usd_per_escalation*; scripts are averaged over the runs (case keys). Picks the
    lowest t whose recall of wrong leaves reaches *recall* with every script within
    *cap_usd*; when no such t exists, the highest t within the cap (``met_recall``
    False); None when even no escalation breaches the cap.
    """
    runs_per_script: dict[str, set[str]] = {}
    for leaf in leaves:
        runs_per_script.setdefault(leaf.script, set()).add(leaf.case_key)
    wrong = sum(1 for leaf in leaves if leaf.wrong)

    def cost(t: float) -> tuple[dict[str, float], int, float | None]:
        escalate = [leaf for leaf in leaves if leaf.confidence < t]
        per_script = {
            s: script_base_usd.get(s, 0.0)
            + usd_per_escalation
            * sum(1 for leaf in escalate if leaf.script == s)
            / max(len(runs_per_script.get(s, ())), 1)
            for s in set(script_base_usd) | set(runs_per_script)
        }
        hit = sum(1 for leaf in escalate if leaf.wrong)
        return per_script, len(escalate), (hit / wrong if wrong else None)

    best_within: tuple[float, dict[str, float], int, float | None] | None = None
    for t in threshold_grid():
        per_script, count, got = cost(t)
        if max(per_script.values(), default=0.0) > cap_usd + _EPS:
            continue
        best_within = (t, per_script, count, got)
        if got is not None and got + _EPS >= recall:
            worst = max(per_script, key=lambda s: per_script[s])
            return EscalationFit(t, got, count, worst, per_script[worst], True)
    if best_within is None:
        return EscalationFit(None, None, 0, None, None, False)
    t, per_script, count, got = best_within
    worst = max(per_script, key=lambda s: per_script[s])
    return EscalationFit(t, got, count, worst, per_script[worst], False)
```

Check the second test by hand before running: base $0.08 plus 2 escalations at $0.01 is $0.10 (within the cap); the threshold grid starts at 0.50, so thresholds 0.71 to 0.80 escalate two leaves (0.60, 0.70) and 0.81 and up escalate three ($0.11, over). The loop returns the highest threshold within the cap, 0.80, with recall 2/3.

- [ ] **Step 4: Slim the script.** In `scripts/fit_review_threshold.py`, delete the moved definitions and import them instead (the existing tests use `fit.evaluate`, `fit.recommend`, `fit.threshold_grid`, `fit.leave_one_case_out`, `fit.load_parts`, `fit.main`):

```python
from lemely.accuracy.threshold_fit import (
    CONFIDENCE_REASON,
    ESCALATION_USD_ESTIMATE,
    Part,
    ThresholdStats,
    escalation_leaves,
    evaluate,
    fit_escalation_threshold,
    leave_one_case_out,
    parts_from_real,
    recommend,
    recommend_for_recall,
    threshold_grid,
)

__all__ = ["Part", "ThresholdStats", "evaluate", "leave_one_case_out", "recommend", "threshold_grid"]
```

and use `CONFIDENCE_REASON` where `load_parts` used `_CONFIDENCE_REASON`. Make `results` optional (`nargs="?"`) and add the real mode:

```python
    parser.add_argument("--real", type=Path, action="append", default=[],
                        metavar="RUN_DIR", help="a real run dir (holds real_results.json)")
    parser.add_argument("--escalation", action="store_true",
                        help="with --real: also fit escalation_confidence_threshold")
    parser.add_argument("--cap-usd", type=float, default=0.10)
```

```python
    if args.real:
        paths = [d / "real_results.json" for d in args.real]
        parts = parts_from_real(paths)
        best = recommend_for_recall(parts)
        stats = evaluate(parts, best) if best is not None else None
        lines = [render(parts, target=args.target), "",
                 f"lowest threshold flagging >= 90% of leaves with abs_error > 0: "
                 f"{'none' if best is None else f'{best:.2f}'}"
                 + ("" if stats is None else f" (review rate {stats.review_rate:.3f})")]
        if args.escalation:
            records = [json.loads(line) for d in args.real
                       for line in (d / "records.jsonl").read_text(encoding="utf-8").splitlines()
                       if line.strip()]
            esc = [r["usd_2027"] for r in records if r.get("task_tag") == "escalation"]
            per_call = sum(esc) / len(esc) if esc else ESCALATION_USD_ESTIMATE
            from lemely.accuracy.cost_ladder.real_split import read_real_results

            base: dict[str, list[float]] = {}
            for p in paths:
                for s in read_real_results(p):
                    base.setdefault(s.key, []).append(s.usd - s.escalation_usd)
            fitted = fit_escalation_threshold(
                escalation_leaves(paths),
                script_base_usd={k: sum(v) / len(v) for k, v in base.items()},
                usd_per_escalation=per_call,
                cap_usd=args.cap_usd,
            )
            lines.append(
                f"escalation_confidence_threshold: "
                f"{'none' if fitted.threshold is None else f'{fitted.threshold:.2f}'} "
                f"(recall {fitted.recall}, escalated {fitted.escalated} leaves over the runs, "
                f"worst script {fitted.worst_script} ${fitted.worst_script_usd}, "
                f"per escalation ${per_call:.4f}{'' if esc else ' (estimate)'}, "
                f"{'met' if fitted.met_recall else 'MISSED'} the recall target)"
            )
        sys.stdout.write("\n".join(lines) + "\n")
        return 0
    if args.results is None:
        parser.error("give a results.json or --real RUN_DIR")
```

Update the module docstring's usage line to show both modes.

- [ ] **Step 5: Run the new and the existing fit tests.**

Run: `.venv/bin/python -m pytest tests/test_threshold_fit.py tests/test_fit_review_threshold.py -q --no-cov -o addopts=""`
Expected: all pass, `test_fit_review_threshold.py` unchanged.

- [ ] **Step 6: Prove red.** In `recommend_for_recall`, iterate `reversed(threshold_grid())`; `test_recall_pick_is_the_lowest_threshold_that_reaches_the_target` fails. Revert. In `fit_escalation_threshold`, drop the cap `continue`; `test_escalation_fit_backs_off_to_the_cap` fails. Revert.

- [ ] **Step 7: Gates and commit.**

```bash
.venv/bin/python -m pytest tests/test_llm_golden.py -q --no-cov -o addopts=""
PATH=$PWD/.venv/bin:$PATH pre-commit run --files lemely/accuracy/threshold_fit.py scripts/fit_review_threshold.py tests/test_threshold_fit.py
git add -- lemely/accuracy/threshold_fit.py scripts/fit_review_threshold.py tests/test_threshold_fit.py
git commit -S -m "refactor(accuracy): threshold fits in lemely/accuracy, recall and escalation fits" -- lemely/accuracy/threshold_fit.py scripts/fit_review_threshold.py tests/test_threshold_fit.py
```


---
## Phase P2: Diagnosis, then fixes

Rule for the whole phase (spec P2): a fix lands only with written evidence (a finding file in `.superpowers/sdd/`, gitignored) and a test proven red against the failing input. A marking-judgement cause is not fixed here: it becomes a P3 lever.

### Task 11: Diagnose the under-marking on 0625/41 ($0)

**Who:** a sonnet subagent (no spend; it reads local student data and writes only to `.superpowers/sdd/`). Needs Task 4 (frozen 0625_w24_41 reference) and Task 6 (`read_reference`).

**Files:** writes `.superpowers/sdd/c-p2-undermarking.md` and a scratch script under the session scratchpad. Commits nothing.

**Interfaces:**
- Consumes: `BUILD/accuracy-runs/claude-c-reference/0625_w24_41/reference.json` (`read_reference`), `.../mark_scheme.json`; stored outputs `BUILD/accuracy-runs/e2e-0625-w24-41-2026-10-19/{correction,extracted}.json` (Gemini) and `BUILD/accuracy-runs/claude-e2e2-0625-w24-41-{enh1,enh2,plain1,plain2}/{correction,extracted}.json` (Claude).
- Produces: the finding file, with one bucket per lost mark and a decision line per bucket (consumed by Task 11b and Task 25).

- [ ] **Step 1: Leaf table.** Write a scratch script (not in the repo) that loads the reference and each stored `correction.json` and `extracted.json`, and prints per leaf: reference mark, max, each run's awarded mark, `marker_source`, `needs_teacher_review`, `review_reason`, and the extracted answer's `binding_source` and first 80 characters of `answer` (in the finding file, quote no student text: write only whether the five runs' texts agree).
- [ ] **Step 2: Bucket every lost mark** (reference minus awarded, per run, positive only) by the first rule that holds:
  1. **binding**: the leaf is `dropped`, `blank` while the reference awards marks, `missing`, or has an unbound review reason; or its extracted text differs from the reference evidence's location (for 7c, all five runs).
  2. **transcription**: the leaf is bound and its text differs between runs or from what the reference evidence quotes, and the run that read it like the reference marks it right.
  3. **scheme parse**: the leaf's maximum or points in `mark_scheme.json` differ from the reference's `max_marks`, or a point the reference relies on is missing.
  4. **marking judgement**: bound, transcribed like the reference, scheme intact, mark still lower.
- [ ] **Step 3: Write `.superpowers/sdd/c-p2-undermarking.md`:** a table of counts (leaves and marks per bucket per run, Gemini and each Claude run), the leaves in each bucket by id (ids are not student data), and a decision per bucket: "fix in P2 (Task 11b)" for binding or transcription with a reproducible cause; "P3 lever" for marking judgement (name the leaves for screen c2 and for a prompt change); "no action" with the reason otherwise.
- [ ] **Step 4: Report** the counts to the main session. Do not commit.

### Task 11b (conditional): Fix a binding or transcription cause found in Task 11

**Run only if** Task 11's finding names a binding or transcription cause with a reproducible input. Otherwise mark this task skipped with the finding's line that says why.

**Files:** decided by the finding; most likely `lemely/io/binding/*.py` or `lemely/core/label_sequence.py`, with a test in the matching existing test file. The recorded binder streams of this very script are committed at `tests/fixtures/binding/0625_w24_41/streams` and are the preferred red input.

**Interfaces:** whatever the finding names; the fix must not change `lemely/io/gemini.py` request building (golden).

- [ ] **Step 1:** Write a test that feeds the recorded stream (or the minimal synthetic stream that reproduces the finding) and asserts the leaf the reference marks is bound and marked as the reference says (for 7c: bound, not `label_not_seen` and not blank).
- [ ] **Step 2:** Run it and watch it fail with the finding's symptom. Paste the failure into the finding file.
- [ ] **Step 3:** Make the smallest change that passes it. Do not add a lever flag: a binding fix is a correctness fix and applies to both providers.
- [ ] **Step 4:** Run the test file, `tests/test_llm_golden.py`, `tests/test_label_sequence.py`, `tests/test_label_sequence_faults.py`, `tests/test_binding_expect.py`, `tests/test_golden_binding_shapes.py`, and the source-scanning tests. All pass.
- [ ] **Step 5:** Revert the fix, watch the new test fail, restore it.
- [ ] **Step 6:** pre-commit on the touched files; `git commit -S -m "fix(binding): <the cause, in words>" -- <files>`.

### Task 12: Diagnose `pass` with G5 failed in enh1 ($0)

**Who:** a sonnet subagent. **Files:** writes `.superpowers/sdd/c-p2-g5-pass.md`; commits nothing.

**Interfaces:** reads `BUILD/accuracy-runs/claude-e2e2-0625-w24-41-enh1/{events.jsonl,correction.json}` and `lemely/core/binding_gate.py::verdict`.

- [ ] **Step 1:** From `events.jsonl`, take the `binding_gate_result` event and list each failed check's `id`, `scope` and `question_ids`. From `correction.json`, take `binding.checks` and `binding.verdict` and confirm they match.
- [ ] **Step 2:** Apply `verdict()`'s rule (pass when no `scope="paper"` check failed) to the failed checks. Expected: G5 and G9 failed with `scope="question"` only, so `pass` is the documented rule, not a leak.
- [ ] **Step 3:** For every leaf named by a failed question-scope check (enh1: 7b_i, 7b_ii, 7c), check `needs_teacher_review` and `review_reason` in `correction.json`. A failed question-scope check must send its leaves to review; if every named leaf is flagged, the verdict is correct and the finding says "documented, no fix".
- [ ] **Step 4:** Write the finding with the check table (ids, scopes, leaf ids, flagged yes/no) and the decision. If any named leaf is not flagged for review, the decision is "leak: Task 12b".

### Task 12b (conditional): Send leaves of failed question-scope checks to review

**Run only if** Task 12 found a named leaf not flagged. **Files:** `lemely/io/correction_ai.py` (the code that applies binding review reasons; locate with `graphify query "binding report question scope review reason correction"`), test in `tests/test_binding_review.py` or the existing test that covers `_sent_to_review`/`_unverified_sent_to_review`.

- [ ] **Step 1:** Write a test: a `CorrectionResult` built by `correct_paper` from an `ExtractedAnswers` whose binding report has a failed `scope="question"` G5 check naming leaf `L` must return `L` with `needs_teacher_review=True` and the check's reason in `review_reason`.
- [ ] **Step 2:** Watch it fail as the finding describes.
- [ ] **Step 3:** Fix the smallest path that drops the flag. Golden stays green.
- [ ] **Step 4 to 6:** run the test file plus golden and source-scanning tests; revert-and-fail proof; pre-commit; `git commit -S -m "fix(correction): review leaves named by a failed question-scope binding check" -- <files>`.

### Task 13: Stage timings for the extraction and scan-metadata stages

**Files:**
- Modify: `lemely/io/answer_extraction.py` (`__call__`, `_extract`), `lemely/io/llm/claude_provider.py` (`_pages`), `lemely/io/scan_metadata.py` (`__call__`, Claude branch)
- Test: `tests/test_stage_timing.py` (new)

**Interfaces:**
- Produces structlog lines (info level) the latency probe reads:
  - `extraction_rasterised`: `seconds`, `pages`.
  - `extraction_stage_timing`: `total_seconds`, `outcome` (`"ok"` or the exception class name).
  - `claude_pages_ready`: `seconds`, `pages`, `route` (`"files_api"` or `"inline"`), `tag`.
  - `scan_metadata_timing`: `rasterise_seconds`, `call_seconds`, `pages`.
- None of these is on the Gemini call path in `GeminiClient`; the golden test does not see them.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_stage_timing.py`:

```python
"""Sub-project C P2.3: the stage timings the latency diagnosis reads."""

from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from structlog.testing import capture_logs

from lemely.core.schemas import ExamMetadata
from lemely.io.llm.claude_provider import ClaudeProvider
from lemely.io.llm.image_fit import FittedImages
from lemely.io.llm.request import ImageInput, LLMRequest
from tests.gemini_fakes import make_settings


class _Stop(Exception):
    pass


def test_extraction_logs_rasterise_time_and_total_even_on_failure(tmp_path: Path) -> None:
    from lemely.io import answer_extraction as ae

    client = MagicMock()
    client._settings = make_settings(str(tmp_path))
    page = MagicMock(dpi=200.0, png_bytes=b"p")
    with (
        patch.object(ae, "build_question_manifest_hash_key", return_value="k"),
        patch.object(ae, "rasterise_scan_to_pages", return_value=[page, page]),
        patch.object(ae, "check_scan_hygiene", side_effect=_Stop),
        patch.object(ae, "marking_run_slot", contextlib.nullcontext),
        capture_logs() as logs,
        pytest.raises(_Stop),
    ):
        ae.GeminiAnswerExtractor(client)(scan_path=tmp_path / "s.pdf", mark_scheme=MagicMock())
    (raster,) = [e for e in logs if e["event"] == "extraction_rasterised"]
    assert raster["pages"] == 2 and raster["seconds"] >= 0
    (total,) = [e for e in logs if e["event"] == "extraction_stage_timing"]
    assert total["outcome"] == "_Stop" and total["total_seconds"] >= 0


def _fitted() -> FittedImages:
    return FittedImages(images=(b"i",), long_edge=1568, est_tokens=10, page_tokens=(10,),
                        base64_bytes=4, over_token_budget=False, over_byte_limit=False)


def test_claude_pages_ready_logs_route_and_seconds() -> None:
    provider = ClaudeProvider(MagicMock(), make_settings(tempfile.mkdtemp()))
    uploads = MagicMock()
    uploads.ensure.return_value = (_fitted(), ("file-1",))
    req = LLMRequest(model="claude-haiku-5-5", task_tag="extraction", system="s", prompt="p",
                     response_schema=None, images=(ImageInput(b"x"),), uploads=uploads)
    log = MagicMock()
    provider._pages(req, log)
    ((args, kwargs),) = [c for c in log.info.call_args_list if c.args[0] == "claude_pages_ready"]
    assert kwargs["route"] == "files_api" and kwargs["pages"] == 1 and kwargs["tag"] == "extraction"
    assert kwargs["seconds"] >= 0


def test_scan_metadata_logs_rasterise_and_call_time(tmp_path: Path) -> None:
    from lemely.io import scan_metadata as sm

    client = MagicMock()
    client.model_for_tag.return_value = "claude-haiku-5-5"
    meta = ExamMetadata(subject_code="0625", paper_number=4, paper_variant=1,
                        session_month="Oct/Nov", session_year=2024)
    client.generate_structured.return_value = meta
    with (
        patch.object(sm, "rasterise_scan_to_pages", return_value=[MagicMock(png_bytes=b"p")]),
        capture_logs() as logs,
    ):
        assert sm.ScanMetadataExtractor(client)(tmp_path / "s.pdf") == meta
    (line,) = [e for e in logs if e["event"] == "scan_metadata_timing"]
    assert line["pages"] == 1 and line["rasterise_seconds"] >= 0 and line["call_seconds"] >= 0
```

- [ ] **Step 2: Run them to watch them fail.**

Run: `.venv/bin/python -m pytest tests/test_stage_timing.py -q --no-cov -o addopts=""`
Expected: 3 failures (no such log lines).

- [ ] **Step 3: Write the code.**
  - `lemely/io/answer_extraction.py`: add `import time` if absent. In `__call__`:

```python
        started = time.monotonic()
        outcome = "ok"
        try:
            with marking_run_slot():
                return self._extract(scan_path, mark_scheme)
        except BaseException as exc:
            outcome = type(exc).__name__
            raise
        finally:
            structlog.get_logger().bind(component="answer_extraction").info(
                "extraction_stage_timing",
                total_seconds=round(time.monotonic() - started, 3),
                outcome=outcome,
            )
```

    and in `_extract`, around the rasterise call:

```python
        rasterise_started = time.monotonic()
        pages: list[RasterisedPage] = rasterise_scan_to_pages(scan_path)
        structlog.get_logger().bind(component="answer_extraction").info(
            "extraction_rasterised",
            seconds=round(time.monotonic() - rasterise_started, 3),
            pages=len(pages),
        )
```

    (use the module's existing logger idiom if it already binds one; check its imports first.)
  - `lemely/io/llm/claude_provider.py` `_pages`: add `import time`; time the whole method body after the `if not req.images` early return and log before each `return`:

```python
        started = time.monotonic()

        def ready(route: str) -> None:
            log.info(
                "claude_pages_ready",
                seconds=round(time.monotonic() - started, 3),
                pages=len(req.images),
                route=route,
                tag=req.task_tag,
            )
```

    call `ready("files_api")` just before `return fitted, (), file_ids` and `ready("inline")` just before `return fitted, fitted.images, ()`.
  - `lemely/io/scan_metadata.py` Claude branch:

```python
        if isinstance(model, str) and is_anthropic_model(model):
            started = time.monotonic()
            pages = rasterise_scan_to_pages(scan_path, max_pages=_METADATA_PAGES)
            rasterised = time.monotonic()
            result = self._client.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                image_parts=[page.png_bytes for page in pages],
                response_schema=ExamMetadata,
                prompt_version=VERSION,
                task_tag="scan_metadata",
                extra_cache_key=scan_path.name,
            )
            structlog.get_logger().bind(component="scan_metadata").info(
                "scan_metadata_timing",
                rasterise_seconds=round(rasterised - started, 3),
                call_seconds=round(time.monotonic() - rasterised, 3),
                pages=len(pages),
            )
            return result
```

    (add `import time` and `import structlog` if absent.)

- [ ] **Step 4: Run the tests.** `.venv/bin/python -m pytest tests/test_stage_timing.py tests/test_answer_extraction.py tests/test_scan_metadata.py tests/test_claude_uploads.py tests/test_llm_golden.py -q --no-cov -o addopts=""`. All pass.

- [ ] **Step 5: Prove red.** Remove the `finally` log in `__call__`; the first test fails. Revert. Remove `ready("files_api")`; the second fails. Revert.

- [ ] **Step 6: Commit.**

```bash
PATH=$PWD/.venv/bin:$PATH pre-commit run --files lemely/io/answer_extraction.py lemely/io/llm/claude_provider.py lemely/io/scan_metadata.py tests/test_stage_timing.py
git add -- lemely/io/answer_extraction.py lemely/io/llm/claude_provider.py lemely/io/scan_metadata.py tests/test_stage_timing.py
git commit -S -m "feat(gemini): stage timings for extraction, page preparation and scan metadata" -- lemely/io/answer_extraction.py lemely/io/llm/claude_provider.py lemely/io/scan_metadata.py tests/test_stage_timing.py
```

### Task 13b: Latency probe (MAIN SESSION, live spend)

**MAIN SESSION — live spend.** One real script, one run: **expected $0.05 Anthropic**, $0 Gemini. Needs Tasks 7, 9, 13 and a frozen 0625_w24_41.

**Stop conditions:** the run fails, or the ledger moves by more than $0.15.

- [ ] **Step 1:** Write `BUILD/accuracy-runs/claude-c-2026-10-24/base.toml` (committed later with the reports; config only):

```toml
[gemini]
model = "claude-haiku-5-5"
mark_scheme_model = "claude-haiku-5-5"
extraction_model = "claude-haiku-5-5"
correction_model = "claude-haiku-5-5"
escalation_model = "claude-sonnet-5-5"
generation_model = "claude-haiku-5-5"
scan_metadata_model = "claude-haiku-5-5"
study_plan_model = "claude-haiku-5-5"
self_review_judge_model = "claude-haiku-5-5"
correction_shared_prefix = true
claude_files_api = true
claude_image_enhance = true
claude_cache_for = { extraction = ["system", "images"], binding_second_read = ["system", "images"], correction = ["system", "prefix"], correction_borderline = ["system", "prefix"], escalation = ["system", "prefix"] }
claude_effort_for = { "correction:mcq" = "low", "correction:numeric" = "low", "correction:short" = "low", "correction:extended" = "medium" }
correction_citations = false
correction_terse_rationale = false

[binding]
read_model = "claude-haiku-5-5"
retry_model = "claude-sonnet-5-5"
claude_chunked_read = false
```

  This is the E2E config with every lever off (citations, terse, chunked) and escalation and the binder retry on Sonnet, as the spec's base requires. Paths are set by the runner.
- [ ] **Step 2:** Capture logs to a file and run one real-only baseline-shaped run in a scratch out-dir (not the ladder's):

```bash
.venv/bin/python scripts/cost_ladder.py --out-dir BUILD/accuracy-runs/claude-c-latency-probe --config BUILD/accuracy-runs/claude-c-2026-10-24/base.toml --split real --only 0625_w24_41 --max-run-usd anthropic=0.15 baseline 2>&1 | tee "$SCRATCH/latency.log"
```

  This runs the real split twice (the baseline always makes two real runs): expected $0.10, still under the stop condition's $0.15 per run. If two runs are not wanted, stop the second with Ctrl-C after `real-1/real_results.json` exists; the ledger is booked per script.
- [ ] **Step 3:** From the log, sum per stage: `scan_metadata_timing` (rasterise vs call), `extraction_rasterised`, each `claude_pages_ready` (route, seconds), call latencies from `real-1/records.jsonl`, the correction span, and `extraction_stage_timing.total_seconds`. Write `.superpowers/sdd/c-p2-latency.md`: a stage table in seconds against the E2E table in `claude-e2e2-0625-w24-41-enh1/COST.md` and Gemini's 330 s; name the stage holding the unexplained 150 s; decision: "fix in 13c" when one stage explains at least 60 s and a cheap change exists (for example: rasterising the scan twice, once for scan metadata and once for extraction; enhancing pages once per call instead of once per job; the Files API upload being serial); otherwise "no fix, recorded".

### Task 13c (conditional): Latency fix

**Run only if** Task 13b's finding names a stage and a cheap change. **Files:** the stage's module and its test file.

- [ ] **Step 1:** Write a test that counts the expensive operation (for example `rasterise_scan_to_pages` or `image_fit.fit` calls per script with a `MagicMock(wraps=...)`) and asserts the count the fix promises (for example 1 instead of 2).
- [ ] **Step 2:** Watch it fail with today's count.
- [ ] **Step 3:** Make the change (cache the rendered pages or the fit on the job's handle, never across scripts). The Gemini path must stay byte-identical: run `tests/test_llm_golden.py`.
- [ ] **Step 4 to 6:** tests, revert-and-fail proof, pre-commit, `git commit -S -m "perf(<scope>): <what is no longer repeated>" -- <files>`. Rerun Task 13b's probe ($0.05) and record the new stage table in the finding.

### Task 14: Haiku tier guard (force the chunked read on a tiered Claude model)

**Files:**
- Modify: `lemely/io/binding/chunked_read.py` (`ChunkedLabelReader.__init__` gains `tier_guard: bool = False`), `lemely/io/binding/label_binder.py` (log on a guarded read), `lemely/io/binding/orchestrate.py` (build the reader through a new `chunked_reader_for`)
- Test: `tests/test_claude_tier_guard.py` (new)

**Interfaces:**
- Produces: `chunked_reader_for(client: GeminiClient, binding: BindingSettings) -> ChunkedLabelReader | None` in `orchestrate.py` (the reader with `tier_guard=False` when `binding.claude_chunked_read is True`; with `tier_guard=True` when it is off and a binder read model is a `claude-` model whose price row has a tier; else None); `ChunkedLabelReader.tier_guard: bool`; log line `claude_tier_guard` (warning) with `pages`, `model`, `tag`.
- Behaviour: `image_fit.fit` already steps the long edge down to the floor; the guard adds the second half of spec P2.4: a read still over `claude_image_token_budget` (95,000, under the 100k tier) at the floor is read in chunks even with `claude_chunked_read` off.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_claude_tier_guard.py`:

```python
"""Sub-project C P2.4: a tiered Claude read over the budget at the floor is read in chunks."""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

from structlog.testing import capture_logs

from lemely.io.binding import chunked_read
from lemely.io.binding.chunked_read import ChunkedLabelReader
from lemely.io.binding.label_binder import LabelBinder
from lemely.io.binding.orchestrate import chunked_reader_for
from tests.gemini_fakes import make_settings

_PAGES = [MagicMock(png_bytes=b"p", index=i) for i in range(24)]


def _client() -> MagicMock:
    client = MagicMock()
    client._settings = make_settings(tempfile.mkdtemp())
    return client


def _binding(**kw: object):  # type: ignore[no-untyped-def]
    return make_settings(tempfile.mkdtemp()).binding.model_copy(update=kw)


def test_guard_builds_a_reader_for_a_tiered_claude_model_with_chunking_off() -> None:
    reader = chunked_reader_for(_client(), _binding(read_model="claude-haiku-5-5"))
    assert reader is not None and reader.tier_guard is True


def test_no_guard_for_an_untiered_claude_model_or_gemini() -> None:
    assert chunked_reader_for(_client(), _binding(read_model="claude-sonnet-5-5")) is None
    assert chunked_reader_for(_client(), _binding(read_model="gemini-3.8-flash")) is None


def test_explicit_chunking_is_not_a_guard() -> None:
    reader = chunked_reader_for(
        _client(), _binding(read_model="gemini-3.8-flash", claude_chunked_read=True)
    )
    assert reader is not None and reader.tier_guard is False


def test_guarded_24_page_read_over_the_budget_is_chunked_and_logged() -> None:
    client = _client()
    reader = ChunkedLabelReader(client, tier_guard=True)
    binder = LabelBinder(client, chunked=reader)
    sentinel = object()
    with (
        patch.object(chunked_read, "estimate_floor_tokens", return_value=120_000),
        patch.object(ChunkedLabelReader, "read", return_value=sentinel),
        capture_logs() as logs,
    ):
        got = binder.read(_PAGES, MagicMock(), uploads=MagicMock(), model="claude-haiku-5-5",
                          extra_cache_key="k")
    assert got is sentinel
    (line,) = [e for e in logs if e["event"] == "claude_tier_guard"]
    assert line["pages"] == 24 and line["model"] == "claude-haiku-5-5"
    assert line["log_level"] == "warning"


def test_guarded_read_under_the_budget_is_not_chunked() -> None:
    client = _client()
    binder = LabelBinder(client, chunked=ChunkedLabelReader(client, tier_guard=True))
    with (
        patch.object(chunked_read, "estimate_floor_tokens", return_value=50_000),
        patch.object(ChunkedLabelReader, "read") as chunked,
        patch.object(client, "generate_structured", return_value=MagicMock()),
        capture_logs() as logs,
    ):
        try:
            binder.read(_PAGES, MagicMock(), uploads=MagicMock(), model="claude-haiku-5-5",
                        extra_cache_key="k")
        except Exception:  # noqa: BLE001 -- the single-call path's parsing is not under test
            pass
    chunked.assert_not_called()
    assert "claude_tier_guard" not in [e["event"] for e in logs]
```

- [ ] **Step 2: Run them to watch them fail.**

Run: `.venv/bin/python -m pytest tests/test_claude_tier_guard.py -q --no-cov -o addopts=""`
Expected: `ImportError: cannot import name 'chunked_reader_for'`.

- [ ] **Step 3: Write the code.**
  - `chunked_read.py`: `def __init__(self, client: GeminiClient, *, tier_guard: bool = False) -> None:` and store `self.tier_guard = tier_guard` (document: "True when the reader exists only as the tier guard, with `binding.claude_chunked_read` off").
  - `label_binder.py` `LabelBinder.read`, inside `if self._chunked is not None and self._chunked.applies(pages, model):` before the `return`:

```python
            if self._chunked.tier_guard:
                structlog.get_logger().bind(component="label_binder").warning(
                    "claude_tier_guard", pages=len(pages), model=model, tag=task_tag
                )
```

    (import `structlog` if the module does not.)
  - `orchestrate.py`: add next to `_reads_share_a_claude_cache`:

```python
def chunked_reader_for(client: GeminiClient, binding: BindingSettings) -> ChunkedLabelReader | None:
    """The binder's chunked reader: on request, or as the tier guard (spec C P2.4).

    With ``claude_chunked_read`` off, a reader is still built when a binder read runs on
    a ``claude-`` model whose price has a tier (Haiku 5.5: 5x every rate past 100k
    input tokens): a script still over the image token budget at the floor is then
    read in chunks under the tier instead of being billed past it.
    """
    if binding.claude_chunked_read is True:
        return ChunkedLabelReader(client)
    models = {binding.read_model, second_read_model(binding)}
    for model in models:
        if model is not None and is_anthropic_model(model):
            row = claude_row(model)
            if row is not None and row.tier_threshold_tokens is not None:
                return ChunkedLabelReader(client, tier_guard=True)
    return None
```

    import `claude_row` from `lemely.io.llm.pricing` (and `BindingSettings` under `TYPE_CHECKING`); replace the line `chunked = ChunkedLabelReader(client) if binding.claude_chunked_read is True else None` in `run_binding` with `chunked = chunked_reader_for(client, binding)`.

- [ ] **Step 4: Run the tests.** `.venv/bin/python -m pytest tests/test_claude_tier_guard.py tests/test_chunked_read.py tests/test_llm_golden.py tests/test_golden_binding_shapes.py -q --no-cov -o addopts=""`. All pass. (Gemini read models get no reader, so the default Gemini binder path is unchanged.)

- [ ] **Step 5: Prove red.** In `chunked_reader_for`, return None after the `claude_chunked_read` branch; the first and fourth tests fail. Revert.

- [ ] **Step 6: Commit.**

```bash
PATH=$PWD/.venv/bin:$PATH pre-commit run --files lemely/io/binding/chunked_read.py lemely/io/binding/label_binder.py lemely/io/binding/orchestrate.py tests/test_claude_tier_guard.py
git add -- lemely/io/binding/chunked_read.py lemely/io/binding/label_binder.py lemely/io/binding/orchestrate.py tests/test_claude_tier_guard.py
git commit -S -m "feat(binding): tier guard reads an over-budget Haiku script in chunks" -- lemely/io/binding/chunked_read.py lemely/io/binding/label_binder.py lemely/io/binding/orchestrate.py tests/test_claude_tier_guard.py
```


### Task 15: Escalation triggers: pin today's behaviour, record the rate ($0)

**Files:**
- Test: `tests/test_escalation_triggers.py` (new; characterization tests, no production change)
- Writes: `.superpowers/sdd/c-p2-escalation.md`

**Interfaces:** reads `AICorrector._retry_low_confidence` and `_cascade` (`lemely/io/correction_ai.py:608-850`).

- [ ] **Step 1: Write the tests.** Create `tests/test_escalation_triggers.py`:

```python
"""Sub-project C P2.5: which triggers escalate with the cascade off (characterization)."""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

from lemely.core.loose_schemas import QuestionType
from lemely.core.schemas import AIMarkResponse
from lemely.io.correction_ai import AICorrector
from lemely.io.gemini import GeminiClient
from tests.gemini_fakes import fake_genai_client, make_settings
from tests.test_anthropic_adapter import _VALID_MARK

_HAIKU = "claude-haiku-5-5"
_SONNET = "claude-sonnet-5-5"


def _tags(confidences: list[float], **gemini: object) -> list[tuple[str, str | None]]:
    settings = make_settings(tempfile.mkdtemp())
    g = settings.gemini.model_copy(update={"correction_model": _HAIKU, **gemini})
    client = GeminiClient(settings.model_copy(update={"gemini": g}),
                          _genai_client=fake_genai_client(), ledger=None)
    replies = [AIMarkResponse.model_validate({**_VALID_MARK, "confidence": c}) for c in confidences]
    question = MagicMock(type=QuestionType.EXPLANATION, id="2", marks=2)
    with (
        patch("lemely.io.correction_ai.build_marker_user_prompt", return_value="u"),
        patch.object(client, "generate_structured", side_effect=replies) as call,
    ):
        AICorrector(client).mark_question(question, "answer")
    return [(c.kwargs["task_tag"], c.kwargs.get("model")) for c in call.call_args_list]


def test_all_haiku_never_escalates_after_a_borderline_retry() -> None:
    # The E2E config: escalation on Haiku, borderline and escalation both at "high".
    assert _tags([0.70, 0.70], escalation_model=_HAIKU) == [
        ("correction", None), ("correction_borderline", None)]


def test_sonnet_escalation_fires_when_still_below_the_threshold() -> None:
    assert _tags([0.70, 0.70, 0.95], escalation_model=_SONNET) == [
        ("correction", None), ("correction_borderline", None), ("escalation", _SONNET)]


def test_a_borderline_retry_that_recovers_stops_escalation() -> None:
    assert _tags([0.70, 0.85], escalation_model=_SONNET) == [
        ("correction", None), ("correction_borderline", None)]


def test_confidence_at_the_threshold_does_not_retry() -> None:
    assert _tags([0.80], escalation_model=_SONNET) == [("correction", None)]


def test_cascade_off_ignores_cascade_triggers() -> None:
    assert _tags([0.95], escalation_model=_SONNET, cascade_unaddressed_points=True,
                 cascade_two_pass_disagreement=True) == [("correction", None)]
```

- [ ] **Step 2: Run them.** `.venv/bin/python -m pytest tests/test_escalation_triggers.py -q --no-cov -o addopts=""`. Expected: 5 passed (they describe today's code). If `test_all_haiku_never_escalates_after_a_borderline_retry` fails, the planner's reading of the 0 escalations was wrong: write what the code does instead into the finding and fix the test to match it.
- [ ] **Step 3: Prove them sensitive.** Temporarily add `"escalation_confidence_threshold": 0.0` to the `update` dict in `_tags`; the three multi-call expectations fail (nothing retries). Revert.
- [ ] **Step 4: Write `.superpowers/sdd/c-p2-escalation.md`:** the trigger list with the cascade off (confidence below `escalation_confidence_threshold`, checked before the borderline retry and again after it; nothing else); that `escalate_on_mark_mismatch` and `escalate_on_defaulted_marks` are mark-scheme parser settings (`DetParserSettings`) and do not escalate leaves; why the four E2E runs made 0 escalation calls (the tuple guard); the rate the flipped config would produce on the stored E2E outputs: count per run the leaves whose `confidence_score` after the borderline retry is below 0.80 (from `correction.json` and `records_correction.jsonl`), times the Sonnet escalation cost estimate ($0.0056, `ESCALATION_USD_ESTIMATE`) and its share of $0.10. State whether it passes the 10%-of-leaves line that triggers the cap lever (spec "Escalation rate").
- [ ] **Step 5: Commit the tests.**

```bash
PATH=$PWD/.venv/bin:$PATH pre-commit run --files tests/test_escalation_triggers.py
git add -- tests/test_escalation_triggers.py
git commit -S -m "test(correction): pin which triggers escalate with the cascade off" -- tests/test_escalation_triggers.py
```

### Task 16: Cost scope on the CLI and Gradio paths

**Files:**
- Modify: `lemely/app/cli.py` (`correct_paper_cmd`, `extract_answers_cmd`), `lemely/app/gradio_app.py` (the extraction at line ~232)
- Test: `tests/test_script_cost_scope.py` (add a wiring test; it is a source-scanning test)

**Interfaces:** consumes `lemely.io.gemini.script_cost_scope(settings, *, script_key)`; produces no new names.

- [ ] **Step 1: Write the failing test.** Append to `tests/test_script_cost_scope.py`:

```python
def _function(path: str, name: str) -> ast.AST:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    (node,) = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]
    return node


def _inside_scope(node: ast.AST, call: str) -> list[bool]:
    """For every call to *call* under *node*: whether a `with script_cost_scope(...)` holds it."""
    scopes = [
        w for w in ast.walk(node)
        if isinstance(w, ast.With) and any(
            isinstance(i.context_expr, ast.Call)
            and getattr(i.context_expr.func, "id", None) == "script_cost_scope" for i in w.items)
    ]
    calls = [
        n for n in ast.walk(node)
        if isinstance(n, ast.Call)
        and (getattr(n.func, "id", None) == call or getattr(n.func, "attr", None) == call)
    ]
    return [any(s.lineno < c.lineno <= (s.end_lineno or 0) for s in scopes) for c in calls]


class CliAndBatchWiringTests(unittest.TestCase):
    def test_cli_and_gradio_paid_calls_are_inside_a_scope(self) -> None:
        cases = [
            ("lemely/app/cli.py", "correct_paper_cmd", "hybrid_correct_paper"),
            ("lemely/app/cli.py", "extract_answers_cmd", "extractor"),
            ("lemely/app/cli.py", "extract_answers_cmd", "ScanMetadataExtractor"),
        ]
        for path, fn, call in cases:
            with self.subTest(fn=fn, call=call):
                inside = _inside_scope(_function(path, fn), call)
                self.assertTrue(inside, f"{call} not found in {fn}")
                self.assertTrue(all(inside), f"{call} outside script_cost_scope in {fn}")
        tree = ast.parse(Path("lemely/app/gradio_app.py").read_text(encoding="utf-8"))
        inside = _inside_scope(tree, "extractor")
        self.assertTrue(inside and all(inside), "gradio extraction outside script_cost_scope")
```

  and add `from pathlib import Path` to its imports. Paths are repo-relative: the suite runs from the repo root, as the existing source-scanning tests assume.

- [ ] **Step 2: Watch it fail.** `.venv/bin/python -m pytest tests/test_script_cost_scope.py -q --no-cov -o addopts=""` fails on `correct_paper_cmd`.

- [ ] **Step 3: Wrap the calls.**
  - `correct_paper_cmd`: add `from lemely.io.gemini import GeminiClient, script_cost_scope`, and put the `hybrid_correct_paper(...)` call inside `with script_cost_scope(settings, script_key=f"cli:{Path(mark_scheme).stem}"):`.
  - `extract_answers_cmd`: import `script_cost_scope`, and wrap from the `if detect_metadata` block through `result = extractor(...)` in `with script_cost_scope(settings, script_key=f"cli:{Path(scan).name}"):` (indent the block; `_print_result` stays outside).
  - `gradio_app.py`: wrap `result = extractor(scan_path=Path(scan_file), mark_scheme=ms)` in `with script_cost_scope(settings, script_key=f"gradio:{Path(scan_file).name}"):` and import `script_cost_scope` beside the existing `GeminiClient` import there.
  The scope only logs; it never blocks or changes a call.

- [ ] **Step 4: Run.** `.venv/bin/python -m pytest tests/test_script_cost_scope.py tests/test_cli_doctor.py tests/test_llm_golden.py -q --no-cov -o addopts=""`, plus any `tests/test_cli*.py` that drives `correct-paper` or `extract-answers` (find them with `grep -l "correct-paper\|extract-answers" tests/test_*.py`). All pass.

- [ ] **Step 5: Prove red.** Move the `hybrid_correct_paper` call out of the `with`; the test fails. Revert.

- [ ] **Step 6: Commit.**

```bash
PATH=$PWD/.venv/bin:$PATH pre-commit run --files lemely/app/cli.py lemely/app/gradio_app.py tests/test_script_cost_scope.py
git add -- lemely/app/cli.py lemely/app/gradio_app.py tests/test_script_cost_scope.py
git commit -S -m "feat(cli): per-script cost scope on the CLI and Gradio paths" -- lemely/app/cli.py lemely/app/gradio_app.py tests/test_script_cost_scope.py
```

### Task 17: `extract_json` and an unclosed bracket in prose

**Files:**
- Modify: `lemely/io/providers/claude_schema.py` (`_last_object`)
- Test: `tests/test_claude_schema_limits.py` (append)

**Interfaces:** `extract_json(text) -> str` keeps its contract; one more input shape is answered.

- [ ] **Step 1: Write the failing tests.** Append:

```python
class ProseBracketTests(unittest.TestCase):
    def test_an_unclosed_bracket_in_prose_after_the_object_is_ignored(self) -> None:
        from lemely.io.providers.claude_schema import extract_json

        text = 'Here it is: {"a": 1} (see [note for the reasoning'
        self.assertEqual(extract_json(text), '{"a": 1}')

    def test_an_unclosed_brace_in_prose_is_ignored(self) -> None:
        from lemely.io.providers.claude_schema import extract_json

        self.assertEqual(extract_json('{"a": 1} then {x and so on'), '{"a": 1}')

    def test_a_truncated_final_object_is_still_incomplete(self) -> None:
        from lemely.io.providers.claude_schema import extract_json

        text = '{"a": 1} {"b": [1, 2'
        self.assertEqual(extract_json(text), text)
```

  (match the file's style: if it uses plain pytest functions, write them as functions.)

- [ ] **Step 2: Watch the first two fail** (`extract_json` returns the whole text).

- [ ] **Step 3: Fix `_last_object`.** Add:

```python
_JSON_VALUE_START = frozenset('{["-0123456789tfn]}')


def _opens_json(text: str, start: int) -> bool:
    """Whether the bracket at ``start`` opens JSON (not prose): what follows it, past spaces.

    ``{`` opens an object only before ``"`` or ``}``; ``[`` opens an array only before a
    JSON value or ``]``. ``[note`` and ``{x`` are prose.
    """
    rest = text[start + 1 :].lstrip()
    if not rest:
        return True  # cut off right after the bracket: a truncated reply
    if text[start] == "{":
        return rest[0] in '"}'
    return rest[0] in _JSON_VALUE_START
```

  and in `_last_object`'s `except ValueError:` branch, before computing `end`:

```python
            if not _opens_json(text, pos):
                pos += 1
                continue
```

  Update `_last_object`'s docstring: "one that never closes is a truncated reply when it opens JSON (see `_opens_json`); an unclosed bracket in prose is skipped".

- [ ] **Step 4: Run.** `.venv/bin/python -m pytest tests/test_claude_schema_limits.py tests/test_anthropic_adapter.py tests/test_llm_golden.py -q --no-cov -o addopts=""`. All pass.

- [ ] **Step 5: Prove red.** Make `_opens_json` return True always; the first two new tests fail. Revert.

- [ ] **Step 6: Commit.**

```bash
PATH=$PWD/.venv/bin:$PATH pre-commit run --files lemely/io/providers/claude_schema.py tests/test_claude_schema_limits.py
git add -- lemely/io/providers/claude_schema.py tests/test_claude_schema_limits.py
git commit -S -m "fix(anthropic): an unclosed bracket in prose no longer voids the JSON reply" -- lemely/io/providers/claude_schema.py tests/test_claude_schema_limits.py
```

### Task 18: Harden `test_a_row_queued_for_the_run_slot_is_alive_and_not_lost_while_it_waits`

**Files:** Modify `tests/test_web_teacher.py` (that test only).

**Interfaces:** none.

- [ ] **Step 1: Read the test** (`tests/test_web_teacher.py:1770`). Its margins: stale window 1.0 s, heartbeat 0.2 s, three seconds of polling with a 0.1 s sleep. On a loaded CI runner one heartbeat write can land more than 1 s after the previous one, which reads as stale.
- [ ] **Step 2: Widen the margins, keep the proof.** Change `stale_after=timedelta(seconds=1.0)` to `timedelta(seconds=2.0)`; keep `QUEUED_HEARTBEAT_SECONDS = 0.2` (a 10x margin); change the polling loop to two stale windows, `end = time.monotonic() + 4.0`, and its comment to "Two stale windows of waiting: only a heartbeat keeps it alive."
- [ ] **Step 3: Run it.** `.venv/bin/python -m pytest "tests/test_web_teacher.py::test_a_row_queued_for_the_run_slot_is_alive_and_not_lost_while_it_waits" -q --no-cov -o addopts=""`. If the Postgres fixture skips locally, say so in the report: CI is then the only place it runs.
- [ ] **Step 4: Prove red** (when it runs locally): set `run_cap.QUEUED_HEARTBEAT_SECONDS` to `60` in the test; it fails with "a queued run was reported as lost". Revert.
- [ ] **Step 5: Commit.**

```bash
PATH=$PWD/.venv/bin:$PATH pre-commit run --files tests/test_web_teacher.py
git add -- tests/test_web_teacher.py
git commit -S -m "test(web): widen the queued-heartbeat margins against CI load" -- tests/test_web_teacher.py
```

---
## Phase P3: Lever switches, then the screens

Tasks 19 to 22 each add one switch, off by default, so the Gemini path and today's Claude path are unchanged until a screen turns it on. They edit `config.py`, `example_toml.py` and `lemely.toml.example`: run them one after another.

### Task 19: Effort `none` (thinking off) for Claude calls: levers a1 and a2

**Files:**
- Modify: `lemely/runtime/config.py` (`ClaudeEffort`), `lemely/io/llm/request.py` (`Effort`), `lemely/io/providers/anthropic_adapter.py` (`EFFORTS`, `Effort`, `complete`, `complete_code_execution`), `lemely/io/gemini.py` (`_THINKING_LEVEL_ORDER` only), `lemely/runtime/example_toml.py`, `lemely.toml.example`
- Test: `tests/test_claude_effort_none.py` (new)

**Interfaces:**
- Produces: the effort value `"none"`, accepted in `gemini.claude_effort_for` for any tag or `tag:kind`. A Claude call at `none` is sent `thinking={"type": "disabled"}` and `output_config.effort = "low"` (or no effort, per step 1). `thinking_rank("none")` ranks below `"minimal"`. Lever a1 sets `claude_effort_for["binding_second_read"] = "none"`; a2 sets `claude_effort_for["extraction"] = "none"` (the binder's first read runs under `extraction`).

- [ ] **Step 1: Confirm the API shape.** Invoke the `claude-api` skill and read the extended/adaptive thinking and effort sections. Record in the task report: (a) that `thinking={"type": "disabled"}` is valid on `claude-haiku-5-5`; (b) whether `output_config.effort` may be sent with thinking disabled. If (b) is "no", drop the `output_config["effort"] = "low"` line below and change the test's expected `output_config` to have no `effort` key. Also note what the docs say about cache hits when only the thinking setting differs between two requests (screen a1 measures it).

- [ ] **Step 2: Write the failing tests.** Create `tests/test_claude_effort_none.py`:

```python
"""Sub-project C levers a1/a2: Claude effort "none" sends a request with thinking off."""

from __future__ import annotations

import tempfile
import unittest

from lemely.core.schemas import AIMarkResponse
from lemely.io.gemini import thinking_rank
from lemely.io.providers.anthropic_adapter import AnthropicAdapter, resolve_effort
from lemely.runtime.config import GeminiSettings
from tests.test_anthropic_adapter import _VALID_MARK, _FakeAnthropic, _message

_HAIKU = "claude-haiku-5-5"


class EffortNoneTests(unittest.TestCase):
    def _sent(self, thinking: str) -> dict[str, object]:
        fake = _FakeAnthropic(_message(_VALID_MARK))
        AnthropicAdapter(fake).generate(
            model=_HAIKU, system_prompt="s", user_prompt="u", response_schema=AIMarkResponse,
            thinking=thinking, cache_prefix=None,
        )
        return fake.messages.calls[0]

    def test_none_disables_thinking(self) -> None:
        call = self._sent("none")
        self.assertEqual(call["thinking"], {"type": "disabled"})
        self.assertEqual(call["output_config"]["effort"], "low")

    def test_other_efforts_stay_adaptive(self) -> None:
        call = self._sent("medium")
        self.assertEqual(call["thinking"], {"type": "adaptive"})
        self.assertEqual(call["output_config"]["effort"], "medium")

    def test_settings_accept_none_per_tag(self) -> None:
        g = GeminiSettings(claude_effort_for={"binding_second_read": "none"})
        self.assertEqual(
            resolve_effort(g.claude_effort_for, g.thinking_level_for, "binding_second_read"), "none"
        )

    def test_none_ranks_below_every_other_effort(self) -> None:
        self.assertLess(thinking_rank("none"), thinking_rank("minimal"))
        self.assertLess(thinking_rank("none"), thinking_rank("low"))

    def test_unknown_effort_is_still_refused(self) -> None:
        with self.assertRaises(ValueError):
            GeminiSettings(claude_effort_for={"extraction": "off"})  # type: ignore[dict-item]


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run them to watch them fail.** `.venv/bin/python -m pytest tests/test_claude_effort_none.py -q --no-cov -o addopts=""`. Expected: `test_settings_accept_none_per_tag` fails validation, `test_none_disables_thinking` fails (`"none"` is not an effort: `effort_for` raises `ValueError`).

- [ ] **Step 4: Write the code.**
  - `config.py`: `ClaudeEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]`, with a comment above it: `# "none" (sub-project C levers a1/a2) turns thinking off for the call.`
  - `request.py`: `Effort = Literal["none", "low", "medium", "high", "xhigh", "max"]`.
  - `anthropic_adapter.py`:

```python
EFFORTS: tuple[str, ...] = ("none", "low", "medium", "high", "xhigh", "max")
Effort = Literal["none", "low", "medium", "high", "xhigh", "max"]
#: The effort that turns thinking off (sub-project C levers a1/a2).
NO_THINKING: Effort = "none"


def _thinking_and_effort(thinking: str | None) -> tuple[dict[str, str], Effort | None]:
    """The request's ``thinking`` block and ``output_config.effort`` for *thinking*.

    "none" disables thinking and asks for the lowest effort on the visible reply;
    every other value keeps adaptive thinking at that effort.
    """
    if thinking is None:
        return {"type": "adaptive"}, None
    effort = _as_effort(thinking)
    if effort == NO_THINKING:
        return {"type": "disabled"}, "low"
    return {"type": "adaptive"}, effort
```

    In `complete`, replace `if thinking is not None: output_config["effort"] = _as_effort(thinking)` with:

```python
        thinking_block, effort = _thinking_and_effort(thinking)
        if effort is not None:
            output_config["effort"] = effort
```

    and pass `thinking=thinking_block` (typed `cast("ThinkingConfigParam", thinking_block)`, importing `ThinkingConfigParam` from `anthropic.types` under the existing `TYPE_CHECKING` import block) instead of `thinking={"type": "adaptive"}`. Make the same change in `complete_code_execution` (its `extra["output_config"]` and its `thinking=` argument).
  - `gemini.py`: `_THINKING_LEVEL_ORDER = {"none": -1, "minimal": 0, "low": 1, "medium": 2, "high": 3, "xhigh": 4, "max": 5}`. Nothing else in `gemini.py` changes. Confirm with `graphify query "_THINKING_LEVEL_ORDER"` that the map is read only by `thinking_rank` (not by any cache key or fingerprint); if anything else reads it, stop and report.
  - `example_toml.py`: change the effort comment line to `"# Claude effort (none | low | medium | high | xhigh | max) per tag or tag:kind;"` and add a line after it: `lines.append('# "none" turns thinking off for the call (levers a1/a2).')`. Regenerate `lemely.toml.example` (command in "Facts").

- [ ] **Step 5: Run.** `.venv/bin/python -m pytest tests/test_claude_effort_none.py tests/test_anthropic_adapter.py tests/test_claude_effort.py tests/test_cost_ladder_settings.py tests/test_claude_code_execution.py tests/test_llm_golden.py -q --no-cov -o addopts=""`. All pass. `test_anthropic_adapter.py::test_effort_mapping` still asserts `{"type": "adaptive"}` for the mapped levels: correct.

- [ ] **Step 6: Prove red.** Make `_thinking_and_effort` return `{"type": "adaptive"}` for `none`; `test_none_disables_thinking` fails. Revert.

- [ ] **Step 7: Commit.**

```bash
F="lemely/runtime/config.py lemely/io/llm/request.py lemely/io/providers/anthropic_adapter.py lemely/io/gemini.py lemely/runtime/example_toml.py lemely.toml.example tests/test_claude_effort_none.py"
PATH=$PWD/.venv/bin:$PATH pre-commit run --files ${=F}
git add -- ${=F}
git commit -S -m "feat(anthropic): effort none turns thinking off (levers a1/a2)" -- ${=F}
```

(`${=F}` splits the list into separate arguments in zsh; in bash write `$F`.)

### Task 20: `binding.claude_cache_ignores_effort`: lever a3

**Files:**
- Modify: `lemely/runtime/config.py` (`BindingSettings`), `lemely/io/binding/orchestrate.py` (`_reads_share_a_claude_cache`), `lemely/runtime/example_toml.py`, `lemely.toml.example`
- Test: `tests/test_claude_cache_effort.py` (new)

**Interfaces:**
- Produces: `BindingSettings.claude_cache_ignores_effort: bool = False`. True: the two binder reads are made in turn (to share the prompt cache) even when their efforts differ. A live probe showed reads at different efforts still hit the cache (spec P3 a3). Screen a3 runs after a1/a2.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_claude_cache_effort.py`:

```python
"""Sub-project C lever a3: the binder reads share the cache across efforts when asked."""

from __future__ import annotations

import tempfile

from lemely.io.binding.orchestrate import _reads_share_a_claude_cache
from lemely.runtime.config import Settings
from tests.gemini_fakes import make_settings

_HAIKU = "claude-haiku-5-5"


def _settings(*, ignore: bool, second_effort: str) -> Settings:
    s = make_settings(tempfile.mkdtemp())
    g = s.gemini.model_copy(update={
        "claude_cache_for": {"extraction": ["system", "images"],
                             "binding_second_read": ["system", "images"]},
        "claude_effort_for": {"extraction": "low", "binding_second_read": second_effort},
    })
    b = s.binding.model_copy(update={"claude_cache_ignores_effort": ignore})
    return s.model_copy(update={"gemini": g, "binding": b})


def test_different_efforts_do_not_share_by_default() -> None:
    assert _reads_share_a_claude_cache(_settings(ignore=False, second_effort="none"), _HAIKU, _HAIKU) is False


def test_the_switch_shares_across_efforts() -> None:
    assert _reads_share_a_claude_cache(_settings(ignore=True, second_effort="none"), _HAIKU, _HAIKU) is True


def test_the_switch_never_shares_across_models() -> None:
    s = _settings(ignore=True, second_effort="low")
    assert _reads_share_a_claude_cache(s, _HAIKU, "claude-sonnet-5-5") is False


def test_default_is_off() -> None:
    assert Settings().binding.claude_cache_ignores_effort is False
```

- [ ] **Step 2: Watch them fail** (`claude_cache_ignores_effort` is not a field; `model_copy` accepts it, so the second test fails on the predicate and the fourth on the attribute).

- [ ] **Step 3: Write the code.**
  - `BindingSettings`, after `claude_chunked_read`:

```python
    #: Sub-project C lever a3: make the two binder reads in turn (so the second can read
    #: the first's prompt cache) even when their efforts differ. Off: equal effort is
    #: required, as the prompt-caching docs say a changed setting invalidates the cache.
    claude_cache_ignores_effort: bool = False
```

  - `_reads_share_a_claude_cache`: replace the last two lines with

```python
    if settings.binding.claude_cache_ignores_effort is True:
        return True
    first, second = (resolve_effort(g.claude_effort_for, g.thinking_level_for, tag) for tag in tags)
    return first == second
```

    and extend its docstring: "With ``binding.claude_cache_ignores_effort`` (lever a3) the effort check is skipped."
  - `example_toml.py`, after the `claude_chunked_read` line in `[binding]`:

```python
    lines.append("# Make the two claude- binder reads in turn even when their efforts differ")
    lines.append("# (lever a3; the second read hits the first's cache only if the API allows).")
    lines.append(
        f"# claude_cache_ignores_effort = {_toml_bool(s.binding.claude_cache_ignores_effort)}"
    )
```

    then regenerate `lemely.toml.example`.

- [ ] **Step 4: Run.** `.venv/bin/python -m pytest tests/test_claude_cache_effort.py tests/test_claude_cache_plan.py tests/test_cost_ladder_settings.py tests/test_llm_golden.py -q --no-cov -o addopts=""`. All pass.
- [ ] **Step 5: Prove red.** Delete the `is True` early return; `test_the_switch_shares_across_efforts` fails. Revert.
- [ ] **Step 6: Commit.**

```bash
F="lemely/runtime/config.py lemely/io/binding/orchestrate.py lemely/runtime/example_toml.py lemely.toml.example tests/test_claude_cache_effort.py"
PATH=$PWD/.venv/bin:$PATH pre-commit run --files ${=F}
git add -- ${=F}
git commit -S -m "feat(binding): binder reads may share the Claude cache across efforts (lever a3)" -- ${=F}
```

### Task 21: `gemini.correction_borderline_enabled`: lever c1

**Files:**
- Modify: `lemely/runtime/config.py` (`GeminiSettings`), `lemely/io/correction_ai.py` (`_retry_low_confidence`), `lemely/runtime/example_toml.py`, `lemely.toml.example`
- Test: `tests/test_borderline_switch.py` (new)

**Interfaces:** `GeminiSettings.correction_borderline_enabled: bool = True`. False: step 1 (the borderline retry) never runs; step 2 (escalation) still does, and its "last call" is the first pass.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_borderline_switch.py`:

```python
"""Sub-project C lever c1: no borderline thinking retry."""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

from lemely.core.loose_schemas import QuestionType
from lemely.core.schemas import AIMarkResponse
from lemely.io.correction_ai import AICorrector
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import GeminiSettings
from tests.gemini_fakes import fake_genai_client, make_settings
from tests.test_anthropic_adapter import _VALID_MARK

_HAIKU, _SONNET = "claude-haiku-5-5", "claude-sonnet-5-5"


def _tags(confidences: list[float], **gemini: object) -> list[str]:
    settings = make_settings(tempfile.mkdtemp())
    g = settings.gemini.model_copy(update={"correction_model": _HAIKU, "escalation_model": _SONNET, **gemini})
    client = GeminiClient(settings.model_copy(update={"gemini": g}),
                          _genai_client=fake_genai_client(), ledger=None)
    replies = [AIMarkResponse.model_validate({**_VALID_MARK, "confidence": c}) for c in confidences]
    with (
        patch("lemely.io.correction_ai.build_marker_user_prompt", return_value="u"),
        patch.object(client, "generate_structured", side_effect=replies) as call,
    ):
        AICorrector(client).mark_question(MagicMock(type=QuestionType.EXPLANATION, id="2", marks=2), "a")
    return [c.kwargs["task_tag"] for c in call.call_args_list]


def test_default_keeps_the_borderline_retry() -> None:
    assert GeminiSettings().correction_borderline_enabled is True
    assert _tags([0.7, 0.9]) == ["correction", "correction_borderline"]


def test_switch_off_goes_straight_to_escalation() -> None:
    assert _tags([0.7, 0.9], correction_borderline_enabled=False) == ["correction", "escalation"]


def test_switch_off_without_low_confidence_makes_one_call() -> None:
    assert _tags([0.95], correction_borderline_enabled=False) == ["correction"]
```

- [ ] **Step 2: Watch the second fail** (borderline still runs).
- [ ] **Step 3: Write the code.**
  - `GeminiSettings`, after `correction_terse_rationale`:

```python
    # Sub-project C lever c1: False skips the borderline thinking retry; a leaf still
    # below escalation_confidence_threshold goes straight to escalation.
    correction_borderline_enabled: bool = True
```

  - `_retry_low_confidence`: `borderline_gate = g.correction_borderline_enabled is not False and thinking_rank(borderline_thinking) > thinking_rank(correction_thinking)` (`is not False`: a `MagicMock` settings object keeps today's behaviour).
  - `example_toml.py`, after the `correction_terse_rationale` lines:

```python
    lines.append("# false skips the borderline thinking retry (lever c1).")
    lines.append(
        f"# correction_borderline_enabled = {_toml_bool(s.gemini.correction_borderline_enabled)}"
    )
```

    then regenerate `lemely.toml.example`.
- [ ] **Step 4: Run.** `.venv/bin/python -m pytest tests/test_borderline_switch.py tests/test_escalation_triggers.py tests/test_claude_effort.py tests/test_cost_ladder_settings.py tests/test_llm_golden.py -q --no-cov -o addopts=""`, plus every test file that builds `MagicMock` settings and reaches `mark_question` (`grep -l "MagicMock" tests/test_*.py | xargs grep -l "mark_question\|AICorrector"`). All pass.
- [ ] **Step 5: Prove red.** Change `is not False` to `is True` and run the `MagicMock` files from step 4: any that relied on the default fails; if none fails, set the switch default to False and watch `test_default_keeps_the_borderline_retry` fail. Revert.
- [ ] **Step 6: Commit.**

```bash
F="lemely/runtime/config.py lemely/io/correction_ai.py lemely/runtime/example_toml.py lemely.toml.example tests/test_borderline_switch.py"
PATH=$PWD/.venv/bin:$PATH pre-commit run --files ${=F}
git add -- ${=F}
git commit -S -m "feat(correction): switch for the borderline retry (lever c1)" -- ${=F}
```

### Task 22: Leaf-scoped Sonnet adjudication: lever c2

**Files:**
- Create: `lemely/io/adjudication.py`
- Modify: `lemely/runtime/config.py` (`GeminiSettings`: three fields, `model_for`), `lemely/io/correction_ai.py` (`correct_paper` gains `pages`), `lemely/io/model_table.py` (`configured_models`), `lemely/accuracy/cost_ladder/real_split.py` (`mark_real_script` passes pages), `lemely/accuracy/cost_ladder/runner.py` (`models_in_play`), `lemely/runtime/example_toml.py`, `lemely.toml.example`
- Test: `tests/test_adjudication.py` (new)

**Interfaces:**
- Consumes: Task 6 (`mark_real_script`), Task 7 (`models_in_play`). Existing: `crop_and_upscale` (`lemely/io/reread.py`), `review_threshold_for` (`correction_ai.py:372`), `confidence_band_for_score` (`lemely/core/schemas.py:54`), `script_cost_scope`.
- Produces:
  - `GeminiSettings.adjudication_model: str | None = None` (None: off), `adjudication_max_leaves: int = 3` (`ge=0`), `adjudication_confidence_threshold: float = 0.80`; `model_for("adjudication")` returns `adjudication_model` (falls back to `model` like every tag; callers check `adjudication_model` first).
  - `lemely/io/adjudication.py`: `ADJUDICATION_TASK_TAG = "adjudication"`, `VERSION = "adjudication-v1"`, `class AdjudicationReply(BaseModel)` (`awarded_marks: int`, `confidence: float`, `rationale: str`), `candidates(result, *, threshold, max_leaves) -> list[str]`, `adjudicate(result, *, scheme, extracted, pages, client, review_threshold) -> CorrectionResult`.
  - `correct_paper(..., pages: Sequence[RasterisedPage] | None = None)`: with pages given and `adjudication_model` set, adjudication runs after marking, unless the binding verdict is `hold`.
  - `configured_models` lists `"adjudication"` when `adjudication_model` is set (so `lemely doctor` and the pricing check cover it).

- [ ] **Step 1: Write the failing tests.** Create `tests/test_adjudication.py`:

```python
"""Sub-project C lever c2: leaf-scoped adjudication (request shape, the cap, cost scope, off path)."""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

from lemely.core.binding import BindingCheck, BindingReport
from lemely.core.loose_schemas import MarkScheme
from lemely.core.schemas import CorrectedQuestion, CorrectionResult, ExamMetadata
from lemely.io import adjudication as adj
from lemely.io.gemini import GeminiClient, _reset_process_counters, record_calls, script_cost_scope
from lemely.io.model_table import configured_models
from tests.test_anthropic_adapter import _FakeAnthropic, _image, _message, _settings

_SONNET = "claude-sonnet-5-5"
_SCHEME = MarkScheme.model_validate({
    "metadata": {"subject": "Physics", "subject_code": "0625", "paper_number": 4,
                 "paper_variant": 1, "session_month": "Oct/Nov", "session_year": 2024,
                 "paper_type": "theory_extended", "maximum_mark": 10,
                 "scheme_format": "point_based"},
    "questions": [{"id": f"{i}a", "marks": 2, "type": "calculation", "answer_points": [
        {"id": "M1", "point": "uses F = ma", "marks": 1}, {"id": "A1", "point": "6 N", "marks": 1}]}
        for i in range(1, 6)],
})


def _cq(qid: str, conf: float, *, source: str = "ai", reason: str | None = None) -> CorrectedQuestion:
    return CorrectedQuestion(question_id=qid, awarded_marks=1, maximum_marks=2, confidence="medium",
                             confidence_score=conf, needs_teacher_review=reason is not None,
                             marker_source=source, review_reason=reason, feedback="half right",
                             student_answer="F = 6 N")


def _result(*qs: CorrectedQuestion, g9: list[str] | None = None) -> CorrectionResult:
    meta = ExamMetadata(subject_code="0625", paper_number=4, paper_variant=1,
                        session_month="Oct/Nov", session_year=2024)
    binding = None
    if g9 is not None:
        binding = BindingReport(binder="label", verdict="pass", checks=[
            BindingCheck(id="G9", passed=False, scope="question", question_ids=g9, detail="d")])
    return CorrectionResult(metadata=meta, questions=list(qs), binding=binding)


def _extracted() -> MagicMock:
    answers = [MagicMock(question_id=f"{i}a", source_box=MagicMock(page=0, box=[0, 0, 500, 500]))
               for i in range(1, 6)]
    return MagicMock(answers=answers)


def test_candidates_are_low_confidence_or_g9_most_uncertain_first_capped() -> None:
    result = _result(_cq("1a", 0.95), _cq("2a", 0.6), _cq("3a", 0.75), _cq("4a", 0.79),
                     _cq("5a", 0.5, source="deterministic"), g9=["1a"])
    assert adj.candidates(result, threshold=0.80, max_leaves=3) == ["2a", "3a", "4a"]
    assert adj.candidates(result, threshold=0.80, max_leaves=4) == ["2a", "3a", "4a", "1a"]


def _client(**gemini: object) -> tuple[GeminiClient, _FakeAnthropic]:
    settings = _settings(tempfile.mkdtemp(), adjudication_model=_SONNET, **gemini)
    replies = [_message({"awarded_marks": 2, "confidence": 0.95, "rationale": "both points"})
               for _ in range(5)]
    fake = _FakeAnthropic(*replies)
    client = GeminiClient(settings, _genai_client=object(), _anthropic_client=fake, ledger=None)
    return client, fake


def test_adjudication_request_shape_and_new_mark() -> None:
    client, fake = _client()
    result = _result(_cq("1a", 0.6, reason="confidence 0.60 below review threshold 0.90"),
                     _cq("2a", 0.95))
    with patch.object(adj, "crop_and_upscale", return_value=_image(40, 40)):
        out = adj.adjudicate(result, scheme=_SCHEME, extracted=_extracted(), pages=[MagicMock()],
                             client=client, review_threshold=0.90)
    (call,) = fake.messages.calls
    assert call["model"] == _SONNET
    text = str(call["messages"])
    assert "uses F = ma" in text and "1 of 2" in text and "half right" in text
    q1 = out.questions[0]
    assert q1.awarded_marks == 2 and q1.confidence_score == 0.95
    assert q1.needs_teacher_review is False and q1.review_reason is None
    assert out.awarded_marks == 3  # totals recomputed


def test_cap_of_three_leaves_per_script() -> None:
    client, fake = _client()
    result = _result(*(_cq(f"{i}a", 0.5) for i in range(1, 6)))
    with patch.object(adj, "crop_and_upscale", return_value=_image(40, 40)):
        adj.adjudicate(result, scheme=_SCHEME, extracted=_extracted(), pages=[MagicMock()],
                       client=client, review_threshold=0.90)
    assert len(fake.messages.calls) == 3


def test_adjudication_cost_lands_in_the_script_scope() -> None:
    client, _ = _client()
    _reset_process_counters()
    with (
        record_calls(),
        script_cost_scope(client._settings, script_key="k") as costs,
        patch.object(adj, "crop_and_upscale", return_value=_image(40, 40)),
    ):
        adj.adjudicate(_result(_cq("1a", 0.5)), scheme=_SCHEME, extracted=_extracted(),
                       pages=[MagicMock()], client=client, review_threshold=0.90)
    assert costs.get("adjudication", 0.0) > 0


def test_off_by_default_and_on_gemini_settings() -> None:
    client = MagicMock()
    client._settings = _settings(tempfile.mkdtemp())
    out = adj.adjudicate(_result(_cq("1a", 0.5)), scheme=_SCHEME, extracted=_extracted(),
                         pages=[MagicMock()], client=client, review_threshold=0.90)
    client.generate_structured.assert_not_called()
    assert out.questions[0].awarded_marks == 1
    assert "adjudication" not in configured_models(client._settings)


def test_a_leaf_without_a_crop_is_skipped() -> None:
    client, fake = _client()
    extracted = MagicMock(answers=[MagicMock(question_id="1a", source_box=None)])
    adj.adjudicate(_result(_cq("1a", 0.5)), scheme=_SCHEME, extracted=extracted,
                   pages=[MagicMock()], client=client, review_threshold=0.90)
    assert fake.messages.calls == []


def test_structural_review_reasons_survive() -> None:
    client, _ = _client()
    reason = "binding unverified | confidence 0.50 below review threshold 0.90"
    with patch.object(adj, "crop_and_upscale", return_value=_image(40, 40)):
        out = adj.adjudicate(_result(_cq("1a", 0.5, reason=reason)), scheme=_SCHEME,
                             extracted=_extracted(), pages=[MagicMock()], client=client,
                             review_threshold=0.90)
    assert out.questions[0].needs_teacher_review is True
    assert out.questions[0].review_reason == "binding unverified"


def test_model_table_lists_adjudication_when_set() -> None:
    client, _ = _client()
    assert configured_models(client._settings)["adjudication"] == _SONNET
```

`_settings(tmp, **gemini_updates)` from `tests/test_anthropic_adapter.py` sets an Anthropic key and copies the gemini updates; `_image(w, h)` returns real PNG bytes.

- [ ] **Step 2: Watch them fail.** `.venv/bin/python -m pytest tests/test_adjudication.py -q --no-cov -o addopts=""`: `ModuleNotFoundError: lemely.io.adjudication` (and `adjudication_model` unknown).

- [ ] **Step 3: Settings.** In `GeminiSettings`, after `correction_borderline_enabled`:

```python
    # Sub-project C lever c2: after a script is marked, this model re-marks at most
    # adjudication_max_leaves AI-marked leaves (confidence below
    # adjudication_confidence_threshold, or named by a failed G9 check), each from its
    # own page crops, its scheme points and the first mark. None: off. Needs the scan
    # pages (correct_paper's ``pages``).
    adjudication_model: str | None = None
    adjudication_max_leaves: int = Field(default=3, ge=0)
    adjudication_confidence_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
```

  and add `"adjudication": self.adjudication_model,` to `model_for`'s mapping. In `example_toml.py`, after the `correction_borderline_enabled` lines:

```python
    lines.append("# Lever c2: a stronger model re-marks the least certain leaves of a script")
    lines.append('# from their page crops, e.g. "claude-sonnet-5-5". Unset: off.')
    lines.append('# adjudication_model = "claude-sonnet-5-5"')
    lines.append(f"# adjudication_max_leaves = {s.gemini.adjudication_max_leaves}")
    lines.append(
        f"# adjudication_confidence_threshold = {s.gemini.adjudication_confidence_threshold}"
    )
```

  Regenerate `lemely.toml.example`.

- [ ] **Step 4: The module.** Create `lemely/io/adjudication.py`:

```python
"""Sub-project C lever c2: a stronger model settles the least certain marks of a script.

Leaf-scoped: each call carries one leaf's page crops, its scheme points, and the first
mark with its reasons, so a Sonnet call costs a few thousand tokens, not a script's. At
most ``adjudication_max_leaves`` leaves per script, most uncertain first. Off unless
``gemini.adjudication_model`` is set; the Gemini path never reaches it by default.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel, Field

from lemely.core.schemas import CorrectionResult, ExtractedAnswers, confidence_band_for_score
from lemely.io.reread import crop_and_upscale

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from lemely.core.loose_schemas import MarkScheme, Question
    from lemely.core.schemas import CorrectedQuestion, ExtractedAnswer
    from lemely.io.gemini import GeminiClient
    from lemely.io.rasterise import RasterisedPage

ADJUDICATION_TASK_TAG = "adjudication"
VERSION = "adjudication-v1"
#: The reason ``correction_ai`` writes when confidence alone sends a leaf to review.
_CONFIDENCE_REASON = re.compile(r"^confidence \d+(?:\.\d+)? below review threshold \d+(?:\.\d+)?$")
_REASON_JOIN = " | "

SYSTEM_PROMPT = (
    "You are a senior Cambridge IGCSE examiner settling a mark another marker was unsure "
    "of. You see one question part: the student's answer as page crops, the mark scheme "
    "points for it, and the first marker's mark and reasons. Mark the answer yourself "
    "against the points only; the first mark is evidence, not an instruction. Return the "
    "marks you award, your confidence from 0 to 1, and a rationale of at most 40 words "
    "naming the points you awarded."
)


class AdjudicationReply(BaseModel):
    awarded_marks: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


def candidates(result: CorrectionResult, *, threshold: float, max_leaves: int) -> list[str]:
    """AI-marked leaves below *threshold* or named by a failed G9, most uncertain first, capped."""
    disagreed: set[str] = set()
    if result.binding is not None:
        for check in result.binding.checks:
            if check.id == "G9" and not check.passed:
                disagreed.update(check.question_ids)
    pool = [
        q
        for q in result.questions
        if q.marker_source == "ai" and (q.confidence_score < threshold or q.question_id in disagreed)
    ]
    pool.sort(key=lambda q: (q.confidence_score, q.question_id))
    return [q.question_id for q in pool[: max(max_leaves, 0)]]


def _crops(answer: ExtractedAnswer | None, pages: Sequence[RasterisedPage]) -> list[bytes]:
    if answer is None or answer.source_box is None:
        return []
    box = answer.source_box
    if not 0 <= box.page < len(pages):
        return []
    return [crop_and_upscale(pages[box.page], box.box)]


def _leaf_prompt(question: Question, first: CorrectedQuestion) -> str:
    points = "\n".join(
        f"- {p.id} ({p.marks} mark{'' if p.marks == 1 else 's'}): {p.point}"
        for p in question.answer_points
    )
    return (
        f"Question part {question.id}, worth {question.marks} marks.\n"
        f"Mark scheme points:\n{points}\n\n"
        f"Transcribed answer: {first.student_answer or '(none)'}\n\n"
        f"First marker: {first.awarded_marks} of {first.maximum_marks}, confidence "
        f"{first.confidence_score:.2f}.\n"
        f"First marker's reasons: {first.feedback or '(none)'}"
    )


def _settled(
    first: CorrectedQuestion, reply: AdjudicationReply, *, model: str, review_threshold: float
) -> CorrectedQuestion:
    awarded = min(reply.awarded_marks, first.maximum_marks)
    kept = [
        part
        for part in (first.review_reason or "").split(_REASON_JOIN)
        if part and not _CONFIDENCE_REASON.match(part)
    ]
    if reply.confidence < review_threshold:
        kept.append(
            f"confidence {reply.confidence:.2f} below review threshold {review_threshold:.2f}"
        )
    return first.model_copy(
        update={
            "awarded_marks": awarded,
            "confidence_score": reply.confidence,
            "confidence": confidence_band_for_score(reply.confidence),
            "needs_teacher_review": bool(kept),
            "review_reason": _REASON_JOIN.join(kept) or None,
            "feedback": f"{reply.rationale} (adjudicated by {model}; first mark "
            f"{first.awarded_marks})",
        }
    )


def adjudicate(
    result: CorrectionResult,
    *,
    scheme: MarkScheme,
    extracted: ExtractedAnswers | Mapping[str, str],
    pages: Sequence[RasterisedPage],
    client: GeminiClient,
    review_threshold: float,
) -> CorrectionResult:
    """*result* with up to ``adjudication_max_leaves`` leaves re-marked by the adjudication model.

    A leaf with no page crop (no source box) is skipped and logged. Totals are recomputed.
    """
    g = client._settings.gemini
    model = g.adjudication_model
    if not isinstance(model, str) or not model:
        return result
    ids = candidates(
        result,
        threshold=float(g.adjudication_confidence_threshold),
        max_leaves=int(g.adjudication_max_leaves),
    )
    if not ids:
        return result
    log = structlog.get_logger().bind(component="adjudication")
    by_question = {q.id: q for q in scheme.all_questions_flat()}
    answers = (
        {a.question_id: a for a in extracted.answers}
        if isinstance(extracted, ExtractedAnswers) or hasattr(extracted, "answers")
        else {}
    )
    settled: dict[str, CorrectedQuestion] = {}
    for qid in ids:
        first = next(q for q in result.questions if q.question_id == qid)
        question = by_question.get(qid)
        crops = _crops(answers.get(qid), pages)
        if question is None or not crops:
            log.info("adjudication_skipped", question_id=qid, reason="no crop or no scheme leaf")
            continue
        reply = client.generate_structured(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=_leaf_prompt(question, first),
            image_parts=crops,
            response_schema=AdjudicationReply,
            prompt_version=VERSION,
            model=model,
            task_tag=ADJUDICATION_TASK_TAG,
            question_id=qid,
            extra_cache_key=f"q={qid}:adjudicated",
        )
        settled[qid] = _settled(first, reply, model=model, review_threshold=review_threshold)
        log.info(
            "adjudication",
            question_id=qid,
            first=first.awarded_marks,
            settled=settled[qid].awarded_marks,
            model=model,
        )
    if not settled:
        return result
    return CorrectionResult(
        metadata=result.metadata,
        questions=[settled.get(q.question_id, q) for q in result.questions],
        binding=result.binding,
    )
```

  (`hasattr(extracted, "answers")` lets the tests pass a stand-in; a plain mapping of answers has no boxes and adjudicates nothing.)

- [ ] **Step 5: Wire it.**
  - `correction_ai.correct_paper`: add the keyword `pages: Sequence[RasterisedPage] | None = None` (import `RasterisedPage` under `TYPE_CHECKING`), document it ("the scan's pages; with ``gemini.adjudication_model`` set, the least certain leaves are adjudicated from their crops (lever c2)"), and before `_forget_reads_of_a_held_paper(...)`:

```python
    if pages is not None and gemini_client is not None:
        g = gemini_client._settings.gemini
        held = result.binding is not None and result.binding.verdict == "hold"
        if isinstance(g.adjudication_model, str) and not held:
            from lemely.io.adjudication import adjudicate

            result = adjudicate(
                result,
                scheme=scheme,
                extracted=extracted_answers,
                pages=pages,
                client=gemini_client,
                review_threshold=review_threshold_for(g, g.adjudication_model),
            )
```

    (the local import avoids a cycle: `adjudication` does not import `correction_ai`, but keep the import local so `correction_ai`'s import graph is unchanged when the lever is off.)
  - `model_table.configured_models`: after the cascade lines, `if isinstance(g.adjudication_model, str) and g.adjudication_model: models["adjudication"] = g.adjudication_model`.
  - `runner.models_in_play`: add `g.adjudication_model,` to the list.
  - `real_split.mark_real_script`: before `correct_paper`, `pages = rasterise_scan_to_pages(script.scan_path) if isinstance(settings.gemini.adjudication_model, str) else None` (import `rasterise_scan_to_pages` from `lemely.io.rasterise` inside the function) and pass `pages=pages`.
  - Add to `tests/test_cost_ladder_real_split.py`:

```python
def test_mark_real_script_passes_pages_only_with_adjudication(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from lemely.io import answer_extraction, correction_ai, rasterise, scan_metadata
    from lemely.runtime.config import Settings
    from lemely.accuracy.cost_ladder.runner import apply_overrides

    script = _frozen(tmp_path)
    script.scheme_path.write_text(_SCHEME_JSON, encoding="utf-8")
    seen: list[object] = []
    monkeypatch.setattr(scan_metadata, "ScanMetadataExtractor", lambda client: (lambda path: None))
    monkeypatch.setattr(answer_extraction, "GeminiAnswerExtractor",
                        lambda client: (lambda scan_path, mark_scheme: "EXTRACTED"))
    monkeypatch.setattr(rasterise, "rasterise_scan_to_pages", lambda path: ["PAGE"])
    monkeypatch.setattr(correction_ai, "correct_paper", lambda **kw: seen.append(kw["pages"]) or "R")
    rs.mark_real_script(script, object(), Settings())  # type: ignore[arg-type]
    on = apply_overrides(Settings(), {"gemini.adjudication_model": "claude-sonnet-5-5"})
    rs.mark_real_script(script, object(), on)  # type: ignore[arg-type]
    assert seen == [None, ["PAGE"]]
```

    with `_SCHEME_JSON` a module constant holding a valid scheme (reuse the JSON of `_SCHEME` from `tests/test_build_reference_cli.py`, written out with `json.dumps`). Note the `_frozen` reference's scheme file is replaced after freezing: this test calls `mark_real_script` directly and never reloads the manifest, so the digest is not checked.
  - Add `real_split.py` and its test file to this task's commit.

- [ ] **Step 6: Run.** `.venv/bin/python -m pytest tests/test_adjudication.py tests/test_cost_ladder_real_split.py tests/test_cost_ladder_real_runner.py tests/test_model_table.py tests/test_cli_doctor.py tests/test_cost_ladder_settings.py tests/test_marking_options_wiring.py tests/test_llm_golden.py -q --no-cov -o addopts=""`, plus the source-scanning tests. All pass.

- [ ] **Step 7: Prove red.** (a) `candidates`: drop the `[: max(max_leaves, 0)]` slice; `test_cap_of_three_leaves_per_script` fails. (b) `_settled`: keep the old confidence reason; `test_adjudication_request_shape_and_new_mark` fails on `review_reason`. (c) `correct_paper`: call `adjudicate` even when `pages` is None: no test fails yet, so add `test_correct_paper_without_pages_never_adjudicates` to `tests/test_adjudication.py`: patch `lemely.io.adjudication.adjudicate` with a `MagicMock`, run `correct_paper` on a one-leaf MCQ scheme (no AI client needed, `mcq_only=True`), assert the mock was not called; watch it fail with the broken code; revert.

- [ ] **Step 8: Commit.**

```bash
F="lemely/io/adjudication.py lemely/runtime/config.py lemely/io/correction_ai.py lemely/io/model_table.py lemely/accuracy/cost_ladder/real_split.py lemely/accuracy/cost_ladder/runner.py lemely/runtime/example_toml.py lemely.toml.example tests/test_adjudication.py tests/test_cost_ladder_real_split.py"
PATH=$PWD/.venv/bin:$PATH pre-commit run --files ${=F}
git add -- ${=F}
git commit -S -m "feat(correction): leaf-scoped Sonnet adjudication (lever c2)" -- ${=F}
```

---

### Task 23: Base and Gemini rungs (MAIN SESSION, live spend)

**MAIN SESSION — live spend.** Needs Tasks 4, 7, 9, 13b's `base.toml`, 19 to 22 landed (so the base runs the code the screens will run), and the P2 fixes that landed.

**Expected spend:** base, dev split twice (all tags on Haiku, escalation on Sonnet): $0.40 to $1.00 Anthropic; real split twice over five scripts: about $0.50. Gemini rung, real split twice: about $1.60 Gemini (5 scripts at about $0.16). **Total about $1.5 Anthropic, $1.6 Gemini.**

**Stop conditions:** the baseline summary has any incomplete case (stop; diagnose with the run's `records.jsonl` and `real_results.json`); the Gemini ledger would pass $5.50; the anthropic ledger passes $12 at any point in this phase.

- [ ] **Step 1: Out-dir and configs.**

```bash
OUT=BUILD/accuracy-runs/claude-c-2026-10-24
mkdir -p $OUT
printf '# Gemini rung: today'"'"'s defaults (no overrides).\n' > $OUT/gemini.toml
cat BUILD/accuracy-runs/cost-ladder-spend.json
```

  (`base.toml` was written in Task 13b.) Check that both TOMLs load: `.venv/bin/python -c "from lemely.runtime.config import load_settings as l; print(l(toml_path='$OUT/base.toml').gemini.escalation_model, l(toml_path='$OUT/gemini.toml').gemini.correction_model)"` prints `claude-sonnet-5-5 gemini-3.1-flash-lite`.
- [ ] **Step 2: Base, both splits, twice.**

```bash
.venv/bin/python scripts/cost_ladder.py --out-dir $OUT --config $OUT/base.toml --split both --repeats 2 --max-run-usd anthropic=1.20 --max-run-usd gemini=0.10 baseline
```

  Record `aa_floor.json` (dev floor and real floor), and from `baseline/summary.json`: real abs error, review rate, escalation rate (max script), worst script cost.
- [ ] **Step 3: Find the Gemini dev summary to reuse.** The prior ladder's last accepted rung:

```bash
.venv/bin/python - <<'EOF'
import json, pathlib
d = pathlib.Path("BUILD/accuracy-runs/cost-ladder-2026-10-19")
rows = json.loads((d / "ladder.json").read_text())
passed = [r for r in rows if json.loads((d / r / "verdict.json").read_text())["passed"]]
print(passed[-1] if passed else "baseline")
EOF
```

  Confirm its `summary.json` overrides match today's Gemini defaults (`correction_model = gemini-3.1-flash-lite`, second read `low`, the binder caps) by reading `lemely/runtime/config.py`'s comments that cite those verdicts. If they do not match, stop and ask the user whether to spend about $1.80 Gemini on two fresh dev runs instead.
- [ ] **Step 4: Gemini rung.**

```bash
.venv/bin/python scripts/cost_ladder.py --out-dir $OUT --config $OUT/gemini.toml --split real reference-rung --label gemini --dev-from BUILD/accuracy-runs/cost-ladder-2026-10-19/<label>/summary.json --max-run-usd gemini=1.00 --max-run-usd anthropic=0.05
```

- [ ] **Step 5: Record** in `.superpowers/sdd/c-p3-screens.md`: ledger before and after; base and Gemini figures (counts); the escalation rate at base (Sonnet prices) against the 10% line.

### Task 24: Cost screens a1, a2, b2, c1, then a3 (MAIN SESSION, live spend)

**MAIN SESSION — live spend.** Each screen: dev twice (live tags only) plus real twice. **Expected about $0.60 to $0.90 Anthropic per screen; about $4 for the five.** Stop when the anthropic ledger passes $20 (re-plan before going on), or when a screen ends incomplete twice.

The base effort map, restated in every `claude_effort_for` override (a `--set` replaces the whole map):
`{"correction:mcq":"low","correction:numeric":"low","correction:short":"low","correction:extended":"medium"}`.

Common flags: `C="--out-dir $OUT --config $OUT/base.toml --split both --repeats 2"`; the live tags always include the defaults: `L=correction,correction_borderline,escalation,correction_prefix_cache`.

- [ ] **a1 (second binder read at effort none):**

```bash
.venv/bin/python scripts/cost_ladder.py ${=C} screen --label a1 --lever "second binder read effort none" --expected-saving "13%" --judge cost --live-tags $L,binding_second_read --set 'gemini.claude_effort_for={"correction:mcq":"low","correction:numeric":"low","correction:short":"low","correction:extended":"medium","binding_second_read":"none"}'
```

- [ ] **a2 (first binder read at effort none):** same with `--label a2 --lever "first binder read effort none" --expected-saving "6%" --live-tags $L,extraction,binding_second_read` and `"extraction":"none"` in the map (the second read is live too: it reads the first read's output).
- [ ] **b2 (terse rationale):** `--label b2 --lever "terse rationale" --expected-saving "5%" --live-tags $L --set gemini.correction_terse_rationale=true`.
- [ ] **c1 (no borderline):** `--label c1 --lever "no borderline calls" --expected-saving "7%" --live-tags $L --set gemini.correction_borderline_enabled=false`.
- [ ] **a3 (cache across efforts), after a1/a2:** only if a1 or a2 passed. Stack on the passing one (say a1): `--label a3 --against a1 --lever "binder reads share the cache across efforts" --expected-saving "8%" --live-tags $L,extraction,binding_second_read --set binding.claude_cache_ignores_effort=true`. If both failed, skip a3 and record why.
- [ ] **After each screen:** a refusal with `UpstreamNotFrozen` names the tags to add to `--live-tags`; rescreen with them (the refused run's spend is booked; it is not a verdict). Record each verdict, its reasons and notes (saving, escalation) in `.superpowers/sdd/c-p3-screens.md`. For a1, also record the second read's `cached_tokens` in `a1/real-1/records.jsonl` (task tag `binding_second_read`): zero means disabling thinking broke the image cache (see Task 19 step 1).

### Task 25: Accuracy screens b1, b3, c2 (MAIN SESSION, live spend)

**MAIN SESSION — live spend.** **Expected about $0.70 each for b1 and b3; c2 about $1.00 (Sonnet, at most 3 leaves per script).** Same stop conditions as Task 24.

- [ ] **b1 (citations, `uncited_mark` to review):** `${=C} screen --label b1 --lever "correction citations" --expected-saving "-5%" --judge accuracy --live-tags $L --set gemini.correction_citations=true`.
- [ ] **b3 (chunked read forced on):** `--label b3 --lever "chunked binder read" --judge accuracy --live-tags $L,extraction,binding_second_read,binding_overview --set binding.claude_chunked_read=true`. With no script over the budget at the floor, the chunked reader does not apply and the screen measures noise: say so in the record if `binding_overview` never appears in the records.
- [ ] **c2 (Sonnet adjudication):** `--label c2 --lever "leaf-scoped Sonnet adjudication" --judge accuracy --live-tags $L,adjudication --set gemini.adjudication_model=claude-sonnet-5-5`.
- [ ] **Marking-judgement levers from Task 11:** if Task 11 named a prompt change, it needs code first: write it as a new task in this plan's style (a switch, off by default, with a test), land it, then screen it here with `--judge accuracy`. Do not edit prompts during a screen.
- [ ] **Record** each verdict in `.superpowers/sdd/c-p3-screens.md`.

### Task 26: Stack the winners, fit lever d, decide the cap (MAIN SESSION)

**MAIN SESSION.** Stacking rungs are live (about $0.80 each); the fit is $0.

- [ ] **Step 1: Stack.** Order: cost winners (in the order they were screened), then accuracy winners. Each step is a screen `--against` the previous accepted rung, with the next winner's `--set` and live tags, judged by the winner's own kind; name them `s1`, `s2`, .... A step that fails is dropped from the stack (record why) and the next winner stacks on the last accepted rung. With no winner at all, the stack is the base.
- [ ] **Step 2: Fit lever d ($0).** On the last accepted stacking rung `S`:

```bash
.venv/bin/python scripts/fit_review_threshold.py --real $OUT/S/real-1 --real $OUT/S/real-2 --escalation
```

  Record the lowest review threshold flagging at least 90% of leaves with abs_error > 0, and the fitted `escalation_confidence_threshold` with its recall, worst script and per-escalation cost.
- [ ] **Step 3: The fit rung.**

```bash
.venv/bin/python scripts/cost_ladder.py ${=C} screen --label fit --against S --judge record --lever "fitted review and escalation thresholds" --live-tags $L --set 'gemini.review_confidence_threshold_for={"claude-haiku-5-5": R}' --set gemini.escalation_confidence_threshold=E
```

  with R and E from step 2 (omit E if the fit returned none).
- [ ] **Step 4: Cap decision.** Read `fit/summary.json`: if `real_escalation_rate_max_script` is above 0.10 on any script, Task 27 runs and its lever is screened (`--label cap --against fit --judge cost --live-tags $L --set gemini.escalation_cap_per_script=N`, N = the largest count that keeps each script's escalated share at or under 10% of its leaves). Otherwise record "cap not needed" with the figure and skip Task 27.
- [ ] **Step 5: Report.** `.venv/bin/python scripts/cost_ladder.py --out-dir $OUT report --stop-reason "<why the ladder stopped>"` writes `$OUT/LADDER.md`.

### Task 27 (conditional): Per-script escalation cap, most uncertain first

**Run only if** Task 26 step 4 found a script above 10% escalated leaves.

**Files:**
- Modify: `lemely/runtime/config.py` (`GeminiSettings.escalation_cap_per_script: int | None = None`, `ge=0`), `lemely/io/correction_ai.py` (`AICorrector` defers escalation when capped; `correct_paper` escalates the most uncertain deferred leaves after the marking loop), `lemely/runtime/example_toml.py`, `lemely.toml.example`
- Test: `tests/test_escalation_cap.py` (new)

**Interfaces:** `escalation_cap_per_script` None: today's inline escalation. An int N: during the loop, step 2 is deferred (the leaf keeps its post-borderline mark); after the loop, the N deferred leaves with the lowest confidence are escalated and rebuilt; the rest keep their mark. Sibling `prior_results` passed to later leaves during the loop are the pre-escalation marks (documented limitation).

- [ ] **Step 1: Read the marking loop first** (`correct_paper`, the block from `ai.mark_question(` to `corrected_by_id[q.id] = cq`, about `correction_ai.py:3200-3290`) and list the arguments `_build_ai_corrected` and the citations check take there: `q`, `student_answer`, `mark`, `student_working`, `extraction_confidence`, `equivalence_gate`, `review_threshold`.
- [ ] **Step 2: Write the failing tests.** Create `tests/test_escalation_cap.py`:

```python
"""Sub-project C escalation cap: at most N escalations per script, most uncertain first."""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

from lemely.core.loose_schemas import QuestionType
from lemely.core.schemas import AIMarkResponse
from lemely.io.correction_ai import AICorrector
from lemely.io.gemini import GeminiClient
from tests.gemini_fakes import fake_genai_client, make_settings
from tests.test_anthropic_adapter import _VALID_MARK

_HAIKU, _SONNET = "claude-haiku-5-5", "claude-sonnet-5-5"


def _corrector(cap: int | None) -> tuple[AICorrector, GeminiClient]:
    s = make_settings(tempfile.mkdtemp())
    g = s.gemini.model_copy(update={"correction_model": _HAIKU, "escalation_model": _SONNET,
                                    "correction_borderline_enabled": False,
                                    "escalation_cap_per_script": cap})
    client = GeminiClient(s.model_copy(update={"gemini": g}), _genai_client=fake_genai_client(), ledger=None)
    return AICorrector(client), client


def _reply(conf: float) -> AIMarkResponse:
    return AIMarkResponse.model_validate({**_VALID_MARK, "confidence": conf})


def test_capped_corrector_defers_instead_of_escalating() -> None:
    ai, client = _corrector(1)
    with (
        patch("lemely.io.correction_ai.build_marker_user_prompt", return_value="u"),
        patch.object(client, "generate_structured", side_effect=[_reply(0.6), _reply(0.7)]) as call,
    ):
        for qid in ("1", "2"):
            ai.mark_question(MagicMock(type=QuestionType.EXPLANATION, id=qid, marks=2), "a")
    assert [c.kwargs["task_tag"] for c in call.call_args_list] == ["correction", "correction"]
    assert sorted(ai.deferred) == ["1", "2"]


def test_escalate_deferred_takes_the_most_uncertain_first() -> None:
    ai, client = _corrector(1)
    with (
        patch("lemely.io.correction_ai.build_marker_user_prompt", return_value="u"),
        patch.object(client, "generate_structured",
                     side_effect=[_reply(0.7), _reply(0.6), _reply(0.95)]) as call,
    ):
        for qid in ("1", "2"):
            ai.mark_question(MagicMock(type=QuestionType.EXPLANATION, id=qid, marks=2), "a")
        escalated = ai.escalate_deferred()
    assert list(escalated) == ["2"]
    assert call.call_args_list[-1].kwargs["task_tag"] == "escalation"
    assert call.call_args_list[-1].kwargs["question_id"] == "2"


def test_no_cap_escalates_inline_as_today() -> None:
    ai, client = _corrector(None)
    with (
        patch("lemely.io.correction_ai.build_marker_user_prompt", return_value="u"),
        patch.object(client, "generate_structured", side_effect=[_reply(0.6), _reply(0.95)]) as call,
    ):
        ai.mark_question(MagicMock(type=QuestionType.EXPLANATION, id="1", marks=2), "a")
    assert [c.kwargs["task_tag"] for c in call.call_args_list] == ["correction", "escalation"]
    assert ai.deferred == {}
```

  and one `correct_paper`-level test: a two-leaf scheme (the `_SCHEME` shape of `tests/test_adjudication.py`, two leaves), `ExtractedAnswers`-like answers as a plain `{"1a": "x", "2a": "y"}` mapping, cap 1, replies `[0.7, 0.6, 0.95]`: the returned result has leaf `2a` at the escalation reply's marks and `1a` at its first-pass marks, and exactly one call with `task_tag="escalation"`.
- [ ] **Step 3: Watch them fail.**
- [ ] **Step 4: Write the code.**
  - Setting, after `escalation_confidence_threshold`:

```python
    # Sub-project C: at most this many escalation calls per script, most uncertain
    # leaves first (decided after every leaf is marked). None: escalate inline, as before.
    escalation_cap_per_script: int | None = Field(default=None, ge=0)
```

  - `AICorrector.__init__`: `self.deferred: dict[str, tuple[Question, str, str, _PrefixKwargs, float]] = {}`.
  - In `_retry_low_confidence`, replace the step-2 block's body (from `bus.publish(` to `return result, escalation_model`) with a branch:

```python
            cap = g.escalation_cap_per_script
            if isinstance(cap, int) and not isinstance(cap, bool):
                self.deferred[question.id] = (
                    question, system_prompt, user_prompt, prefix_kwargs, result.confidence
                )
                return result, last_call[0]
            return (
                self._escalate(question, system_prompt, user_prompt, prefix_kwargs, result.confidence),
                escalation_model,
            )
```

    and move the existing publish-and-call code into:

```python
    def _escalate(
        self,
        question: Question,
        system_prompt: str,
        user_prompt: str,
        prefix_kwargs: _PrefixKwargs,
        confidence: float,
    ) -> AIMarkResponse:
        """Step 2: the escalation call (today's prompt, cache key and tag)."""
        g = self._client._settings.gemini
        escalation_model = cast("str", g.escalation_model)
        bus.publish(
            EventType.GEMINI_ESCALATE,
            question_id=question.id,
            confidence=confidence,
            escalation_model=escalation_model,
        )
        return self._client.generate_structured(
            system_prompt=system_prompt,
            user_prompt=(
                user_prompt + "\n\nNOTE: A previous marking attempt returned low confidence. "
                "Please re-evaluate carefully before responding."
            ),
            response_schema=self._mark_schema(),
            prompt_version=VERSION,
            extra_cache_key=f"q={question.id}:escalated",
            task_tag="escalation",
            model=escalation_model,
            attempt="escalation",
            question_id=question.id,
            **prefix_kwargs,
        )

    def escalate_deferred(self) -> dict[str, AIMarkResponse]:
        """Escalate the most uncertain deferred leaves, up to the cap; their new responses."""
        cap = self._client._settings.gemini.escalation_cap_per_script
        if not isinstance(cap, int) or isinstance(cap, bool):
            return {}
        order = sorted(self.deferred, key=lambda qid: (self.deferred[qid][4], qid))[:cap]
        out: dict[str, AIMarkResponse] = {}
        for qid in order:
            question, system_prompt, user_prompt, prefix_kwargs, confidence = self.deferred[qid]
            out[qid] = self._escalate(question, system_prompt, user_prompt, prefix_kwargs, confidence)
        return out
```

    The event's `confidence` stays what it is today (the inline path passes `result.confidence`, the deferred path the stored one): the real-split runner reads it (Task 6). `mark_question` sets `self.last_mark_model` from the returned model as today; a deferred leaf returns the correction model.
  - `correct_paper`: in the loop, after `cq = _build_ai_corrected(...)` and the citations check, store the build arguments for a deferred leaf: `if q.id in ai.deferred: pending[q.id] = (q, student_answer or "", student_working, extraction_confidence)` (declare `pending: dict[...] = {}` before the loop). After the loop and before `_attach_extraction_context`:

```python
    for qid, mark in ai.escalate_deferred().items():
        q, answer, working, extraction_confidence = pending[qid]
        threshold = review_threshold_for(gemini_client._settings.gemini, gemini_client._settings.gemini.escalation_model)
        cq = _build_ai_corrected(q, answer, mark, working, extraction_confidence,
                                 equivalence_gate=equivalence_gate, review_threshold=threshold)
        if ai.citations_on() and uncited(q, mark):
            cq = flag_uncited(cq)
        corrected = [cq if c.question_id == qid else c for c in corrected]
        corrected_by_id[qid] = cq
```

    (guard the block with `if gemini_client is not None and ai is not None` as the variables require; check the names `ai` and `corrected` in the loop you read in step 1.)
  - `example_toml.py`: `lines.append("# At most this many escalations per script, most uncertain first (unset: no cap).")` and `lines.append("# escalation_cap_per_script = 2")`; regenerate `lemely.toml.example`.
- [ ] **Step 5: Run** the new file, `tests/test_escalation_triggers.py`, `tests/test_borderline_switch.py`, `tests/test_claude_effort.py`, every `MagicMock`-settings file that reaches `mark_question`, golden and source-scanning tests. All pass.
- [ ] **Step 6: Prove red.** Sort `escalate_deferred` by descending confidence; the most-uncertain test fails. Revert.
- [ ] **Step 7: Commit** with `git commit -S -m "feat(correction): per-script escalation cap, most uncertain first" -- <files>`. Then the main session screens it (Task 26 step 4) and reruns the report.

### Task 28: Flip judgement, reports, gate sweep, the P0 to P3 PR (MAIN SESSION)

**MAIN SESSION.** $0.

- [ ] **Step 1: Gate sweep** (derived from `.github/workflows/ci.yml`), after the last P0 to P3 commit:

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy lemely && .venv/bin/pyright lemely && .venv/bin/lint-imports
.venv/bin/python scripts/check_review_rate_gate.py
PATH=$PWD/.venv/bin:$PATH pre-commit run --files $(git diff --name-only origin/develop...HEAD)
.venv/bin/python -m pytest tests/test_llm_golden.py <every test file this branch added or touched> <the source-scanning tests> -q --no-cov -o addopts=""
git diff --stat origin/develop...HEAD -- tests/fixtures/llm_golden
```

  Expected: every command passes; the last prints nothing. The full suite runs in CI only. (`ruff check .` and `ruff format --check .` read the foreign uncommitted files too; a failure in one of them is not this branch's: confirm with `git stash`-free inspection, `git diff --name-only`, and report it rather than fixing it.)
- [ ] **Step 2: Flip judgement.** Let `F` be the final accepted rung (`fit`, or `cap` if Task 27 ran and passed):

```bash
.venv/bin/python scripts/cost_ladder.py --out-dir $OUT judge-flip --candidate F --gemini gemini
```

  This writes `$OUT/flip_verdict.json` and `$OUT/FLIP.md`.
- [ ] **Step 3: Check the reports hold counts only.** `LADDER.md` and `FLIP.md` must name no student text and no per-leaf marks (leaf ids are allowed in reasons only when they come from a check). Read both.
- [ ] **Step 4: Commit the reports and configs.**

```bash
git add -- $OUT/LADDER.md $OUT/FLIP.md $OUT/base.toml $OUT/gemini.toml
git commit -S -m "docs(accuracy): sub-project C ladder and flip judgement (counts only)" -- $OUT/LADDER.md $OUT/FLIP.md $OUT/base.toml $OUT/gemini.toml
```

- [ ] **Step 5: The PR.** Ask the user before pushing (project rule: no push unless asked). On a yes: push `feat/claude-screens-flip` and open a PR to `develop` with the ladder table, the flip verdict, the spend (ledger before and after), and "CI's full run is the only judge of green".
- [ ] **Step 6: Decide P4.** If `judge_flip` failed, P4 does not run: report the failed checks and stop. If it passed, go on to Task 29.

---
## Phase P4: The flip (a separate PR)

Runs only if Task 28's `judge_flip` passed. The main session creates the branch: `git switch -c feat/claude-default-flip` from `feat/claude-screens-flip`'s HEAD after the P0 to P3 PR is open (this is the one branch switch in the plan; check `git status --short` first and stop if anything of this plan's is uncommitted). The flip PR targets `develop` after the P0 to P3 PR merges, so it can be reverted alone.

### Task 29: Smoke tests for the unscreened tags (MAIN SESSION, live spend)

**MAIN SESSION — live spend.** One live call each on `claude-haiku-5-5` for `generation`, `question_validity`, `study_plan` and `self_review_judge`. **Expected under $0.05 Anthropic.** Stop on a second failure of the same tag.

- [ ] **Step 1: Find each tag's production entry point** with `graphify query "<tag> generate_structured entry point"`: `lemely/io/question_generation.py:97` (`generation`), `lemely/io/question_gates.py:277` (`question_validity`), `lemely/io/study_plan_ai.py:45` (`study_plan`), and the self-review evidence judge (`graphify query "self_review_judge model_for"`). Read each entry function's signature.
- [ ] **Step 2: Write a scratch driver** (session scratchpad, not the repo) that reads the keys from `~/.config/lemely/*_key` into the process, builds settings with every one of those tags' model slots (and `gemini.model`, which `question_validity`, `study_plan` and `self_review_judge` fall back to) set to `claude-haiku-5-5`, opens `record_calls()`, checks the ledger with `check_can_start(ledger.spent(), {"anthropic": 0.10}, SpendCaps())`, calls each entry once on a synthetic input (no student data: a made-up question topic, a made-up study history), and books `cost_by_provider(process_call_records())` to `BUILD/accuracy-runs/cost-ladder-spend.json` in a `finally`.
- [ ] **Step 3: Pass rule per tag:** the call returns an object that validates against its schema, its `CallRecord` has a finite `usd_2027`, and the output is not empty (non-empty list or text field). Record pass/fail per tag in `.superpowers/sdd/c-p4-smoke.md`. A tag that fails stays on Gemini in Task 30 and the PR names it.

### Task 30: Flip the defaults

**Files:**
- Modify: `lemely/runtime/config.py` (defaults), `lemely/runtime/example_toml.py`, `lemely.toml.example`, `lemely/app/cli.py` (doctor key checks), `docs/deployment.md`, `tests/gemini_fakes.py` (`make_settings` pins the pre-flip Gemini settings), `tests/test_llm_golden.py` (an assertion only), `tests/test_cost_ladder_settings.py` (the default it asserts)
- Conditional: `lemely/web/services/grading.py` (pages for adjudication, only if c2 is in the final rung)
- Test: `tests/test_claude_default_flip.py` (new), `tests/test_cli_doctor.py` (two cases)

**Interfaces:**
- Consumes: the final rung's effective configuration: `$OUT/base.toml` plus the `overrides` recorded in `$OUT/F/summary.json` (Task 28's `F`), and Task 29's smoke results.
- Produces: new defaults. `claude-haiku-5-5` for `mark_scheme_model`, `extraction_model`, `correction_model` (so borderline), `scan_metadata_model`, `generation_model`, `binding.read_model` (and the second read, `second_read_model = None` reads on it); `claude-sonnet-5-5` for `escalation_model`, `binding.retry_model`, and `adjudication_model` if c2 is in `F`; `gemini.model` (the fallback of `study_plan`, `self_review_judge`, `question_validity`) `claude-haiku-5-5` if those tags passed Task 29; the base config's `correction_shared_prefix`, `claude_cache_for`, `claude_effort_for`; every accepted lever's value; the fitted `review_confidence_threshold_for` and `escalation_confidence_threshold`.

- [ ] **Step 1: Write the target table.** From `$OUT/base.toml` and `$OUT/F/summary.json`'s `overrides`, list every setting whose default changes, old value and new value, in `.superpowers/sdd/c-p4-flip.md`. This list drives steps 2 and 3; nothing else changes.
- [ ] **Step 2: Pin the Gemini path in the fakes first** (test-only). In `tests/gemini_fakes.py`:

```python
#: Sub-project C P4: the pre-flip default of every setting the flip changed. The
#: fake-based tests, tests/test_llm_golden.py among them, pin the Gemini path with it.
PRE_FLIP_DEFAULTS: dict[str, object] = {
    "gemini.model": "gemini-2.5-flash",
    "gemini.mark_scheme_model": "gemini-2.5-flash",
    "gemini.extraction_model": "gemini-3.5-flash-lite",
    "gemini.correction_model": "gemini-3.1-flash-lite",
    "gemini.generation_model": "gemini-3.5-flash-lite",
    "gemini.scan_metadata_model": "gemini-3.5-flash-lite",
    "gemini.escalation_model": "gemini-3.8-flash",
    "gemini.correction_shared_prefix": False,
    "gemini.claude_cache_for": {},
    "gemini.claude_effort_for": {},
    "gemini.review_confidence_threshold_for": {},
    "gemini.escalation_confidence_threshold": 0.80,
    "binding.read_model": "gemini-3.8-flash",
    "binding.retry_model": "gemini-3.8-flash",
    # plus one entry for every other row of the step-1 table, at its old value
}


def _pinned(settings: Settings, values: Mapping[str, object]) -> Settings:
    for dotted, value in values.items():
        section_name, _, field = dotted.partition(".")
        section = getattr(settings, section_name)
        settings = settings.model_copy(
            update={section_name: type(section).model_validate({**section.model_dump(), field: value})}
        )
    return settings
```

  and in `make_settings`, return `_pinned(s.model_copy(update={"paths": ...}), PRE_FLIP_DEFAULTS)`. Add every step-1 row to `PRE_FLIP_DEFAULTS` (the comment line above is an instruction to you, not code to keep: replace it with the rows). In `tests/test_llm_golden.py::_run_in`, after `settings = make_settings(str(tmp))`, add:

```python
    # Sub-project C P4: the golden pins the Gemini path, whatever the defaults are.
    assert settings.gemini.model_for("correction").startswith("gemini-"), settings.gemini.model
```

  Run `.venv/bin/python -m pytest tests/test_llm_golden.py -q --no-cov -o addopts=""` before changing any default: it passes (the pins equal today's defaults).
- [ ] **Step 3: Write the failing flip test.** Create `tests/test_claude_default_flip.py`:

```python
"""Sub-project C P4: every screened tag defaults to Claude; every default model is priced."""

from __future__ import annotations

from lemely.accuracy.cost_ladder import runner
from lemely.runtime.config import Settings

_HAIKU, _SONNET = "claude-haiku-5-5", "claude-sonnet-5-5"


def test_screened_tags_default_to_haiku() -> None:
    g = Settings().gemini
    for tag in ("mark_scheme", "extraction", "correction", "correction_borderline",
                "scan_metadata", "generation"):
        assert g.model_for(tag) == _HAIKU, tag


def test_escalation_and_binder_retry_default_to_sonnet() -> None:
    s = Settings()
    assert s.gemini.model_for("escalation") == _SONNET
    assert s.binding.read_model == _HAIKU and s.binding.retry_model == _SONNET
    assert s.binding.second_read_model in (None, _HAIKU)


def test_every_default_model_is_priced() -> None:
    runner.preflight_prices(Settings())
```

  Add one assertion per accepted lever and fitted threshold from the step-1 table (for example `assert Settings().gemini.correction_terse_rationale is True` if b2 was accepted; `assert Settings().gemini.review_confidence_threshold_for == {_HAIKU: R}`), and per smoke-tested tag its decided model. Run it: it fails on the first assertion.
- [ ] **Step 4: Change the defaults** in `config.py` to the step-1 table, and rewrite the comments that describe the old choice (for example the `correction_model` comment that says Claude is "development-only, via config") to cite `BUILD/accuracy-runs/claude-c-2026-10-24/FLIP.md`. Update `example_toml.py` where it prints a literal model name rather than the default; regenerate `lemely.toml.example`. Update `tests/test_cost_ladder_settings.py::test_defaults_reproduce_current_behaviour` to the new `correction_model` and to any other default it asserts that the flip changed.
- [ ] **Step 5: Doctor key rules.** In `lemely/app/cli.py` `doctor_cmd`: compute `configured_models` before the Gemini key check, then:

```python
    gemini_tags = [t for t, m in configured_models.items() if m.startswith("gemini-")]
    has_key = bool((settings.gemini_api_key is not None) or os.environ.get("GEMINI_API_KEY"))
    record(
        "gemini_api_key",
        has_key or not gemini_tags,
        detail=(
            ""
            if has_key or not gemini_tags
            else "no GEMINI_API_KEY set but task tag(s) "
            + ", ".join(f"{t}={configured_models[t]}" for t in gemini_tags)
            + " use a gemini- model"
        ),
    )
```

  The Anthropic check (`anthropic_key_missing_tags`) already requires the key only for `claude-` tags. Read the network check near `cli.py:727` ("no API key configured; set GEMINI_API_KEY ..."): make it accept either provider's key for the provider in use, keeping its message for the Gemini case. Add two cases to `tests/test_cli_doctor.py` in its existing style: all-Claude settings and no Gemini key pass `gemini_api_key`; one `gemini-` tag and no Gemini key fail it.
- [ ] **Step 6 (only if c2 is in `F`): adjudication in production.** In `lemely/web/services/grading.py::grade_paper`, rasterise the scan once (`rasterise_scan_to_pages`) when `settings.gemini.adjudication_model` is a string and pass `pages=` to `correct_paper`. Add a test in the grading test file that a configured adjudication model makes `correct_paper` receive pages, and that it does not when unset. Note the extra rasterise time in the PR.
- [ ] **Step 7: Docs.** `docs/deployment.md`: in the `ANTHROPIC_API_KEY` row, "Required: every task tag defaults to a `claude-` model since sub-project C (FLIP.md)"; in the `GEMINI_API_KEY` row, "Required only when a task tag resolves to a `gemini-` model"; keep and restate the zero-data-retention note: Files API storage and code execution are not ZDR-eligible, so the key must belong to a dedicated workspace. Name any tag left on Gemini by Task 29.
- [ ] **Step 8: Tests that assumed Gemini defaults.** Find them: `grep -lE "gemini-(2\.5|3\.[0-9])" tests/test_*.py | xargs grep -lE "Settings\(\)|load_settings\(" `. For each failing one (run them), either pin Gemini explicitly (`_pinned(..., PRE_FLIP_DEFAULTS)`) when it tests Gemini behaviour, or update the expected default when it tests the default. List every edit in the PR body. CI's full run is the judge.
- [ ] **Step 9: Run.** `tests/test_claude_default_flip.py tests/test_llm_golden.py tests/test_cli_doctor.py tests/test_cost_ladder_settings.py tests/test_cost_ladder_runner.py tests/test_model_table.py` plus every file step 8 touched, plus the source-scanning tests. All pass, and `git diff --stat -- tests/fixtures/llm_golden` is empty.
- [ ] **Step 10: Prove red.** Revert one default (for example `correction_model`); `test_screened_tags_default_to_haiku` fails. Restore. Remove the pin of `gemini.correction_model` from `PRE_FLIP_DEFAULTS`; `tests/test_llm_golden.py` fails on the new assertion. Restore.
- [ ] **Step 11: Commit** (path-scoped, every file of this task): `git commit -S -m "feat(config): every screened task tag defaults to Claude (sub-project C flip)" -- <files>`.

### Task 31: The flip PR (MAIN SESSION)

- [ ] **Step 1:** Rerun Task 28 step 1's gate sweep on `feat/claude-default-flip` (diff against `feat/claude-screens-flip`, or `develop` once the first PR merged).
- [ ] **Step 2:** Ask the user before pushing. On a yes: push and open the PR to `develop`, separate from the P0 to P3 PR. Body: the `FLIP.md` table, the step-1 default table, the smoke results (tags left on Gemini, by name), the tests edited in Task 30 step 8, and the revert instruction ("revert this PR alone to go back to Gemini; sub-project D removes Gemini later").

---

## Spec coverage

| Spec item | Task |
|---|---|
| P0 reference set: builder, resumable, Opus through `GeminiClient`, `reference.json` fields, `REVIEW.md`, check-first rules, in-session review, freeze, manifest sha256s | 1, 2, 3, 4 |
| P0 corrected copy never given to a model under test | 3 step 3 (`--truth` only in the builder), 6 (`RealScript` carries the scan only) |
| P1 `RealScript`, manifest loading, `split` | 6, 7 |
| P1 scoring: abs_error, exact, within 1, review rate, binding verdict, dollars, latency; drops count 0 | 6 |
| P1 `RunSummary` fields with defaults | 5, 7 |
| P1 every rung twice; real A/A floor | 7 (`repeats`, `real_aa_floor`) |
| P1 `judge`, `judge_accuracy_lever`, `judge_flip`, every failed reason | 5 |
| P1 refuse on reference drift, corpus drift, unpriced model; incomplete script fails the rung | 6 (`ReferenceDrift`), existing `assert_corpus_digest`, 7 (`preflight_prices` in `run_real`), 5 (`incomplete`) |
| P1 threshold fit moved, recall 90% rule, no API calls | 10 |
| P2.1 under-marking | 11, 11b |
| P2.2 pass with G5 failed | 12, 12b |
| P2.3 latency | 13, 13b, 13c |
| P2.4 tier guard, synthetic 24-page estimate | 14 |
| P2.5 escalation triggers and rate | 15, 6 (reporting) |
| P2.6 minors: cost scope, `extract_json`, flaky test | 16, 17, 18 |
| P3 base config, levers a1 to d, adjudication tag, stacking order | 19 to 22, 23 to 26 |
| Escalation rate: reporting fields, Sonnet pricing in screens, threshold fit, cap lever, flip-bar reporting | 6 + 5 (fields, notes), 13b `base.toml` (Sonnet), 10 + 26 (fit), 26 + 27 (cap), 5 + 8 (`judge_flip` notes, `FLIP.md`) |
| P4 defaults, smoke tests, example TOML, doctor, deployment docs, golden pinning, separate PR | 29, 30, 31 |
| Error handling: `_CapGuard` and ledger on every live run, failed call makes the script incomplete | 2 (ledger), 7 (`run_real`) |
| Deliverables: `LADDER.md`, `FLIP.md` counts only | 8, 26, 28 |
