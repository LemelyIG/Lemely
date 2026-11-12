# Marking Flags Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every `correct_paper` caller reads `equivalence_gate` and `ecf_substitution` from settings through one `MarkingOptions` object, each process logs its marking mode at startup, harness fingerprints tell flag-on runs apart, and CD sets the flags per environment.

**Architecture:** A frozen `MarkingOptions` dataclass lives in `lemely/runtime/config.py` beside `GradingSettings`, which builds it. `correct_paper` and `grade_paper` take `options: MarkingOptions` instead of two bools. All six callers pass `settings.grading.marking_options()`. A pure function decides the startup log line's level. The harness folds each flag into `params_fingerprint` only when it is on.

**Tech Stack:** Python 3.12+, pydantic-settings, structlog, pytest, FastAPI lifespan, GitHub Actions (`google-github-actions/deploy-cloudrun@v3`).

**Spec:** `docs/superpowers/specs/2026-09-26-marking-flags-wiring-design.md`

## Global Constraints

- Defaults stay `False` for both flags. With nothing configured, every marking path behaves exactly as today.
- `lemely.runtime` must not import `lemely.core`, `lemely.io` or `lemely.app` (import-linter). `MarkingOptions` lives in `lemely/runtime/config.py`.
- One API: `correct_paper` and `grade_paper` take `options: MarkingOptions = MarkingOptions()`. The `equivalence_gate`/`ecf_substitution` bool keyword arguments are removed from those two functions. Functions below `correct_paper` keep their bool parameters.
- A harness run with both flags off must produce the same `params_fingerprint` as before this change.
- `ecf_substitution` on with `equivalence_gate` off logs a warning and keeps running. It never refuses to start.
- **Shared-venv hazard:** `.venv` is shared by every worktree, and its editable install points at another worktree. Prefix every Python command with `PYTHONPATH=/home/sico/Code/Lemely/.claude/worktrees/feat-ai-improvements PATH="$PWD/.venv/bin:$PATH"`. If the sandbox refuses the inline prefix, use a wrapper script and confirm it imports this worktree's `lemely`. Commands below are written without the prefix for readability; add it every time.
- Never run the full test suite locally; CI does. Run only the named test files, with `--no-cov`. Report counts from the `N passed` line.
- Before each commit: `pre-commit run --files <changed files>` (with the prefix), then `ruff check` and `ruff format --check` on the same files. Pyright's package-wide error count (164 locally) is environmental; only new errors in changed lines matter.
- Signed commits with conventional messages: `git commit -S -- <paths>`. Never `-a`, `add -A` or `add .`. New files need `git add -- <path>` first. Do not push.
- Do not run prettier; this repo does not use it.

---

### Task 1: `MarkingOptions`, the settings projection, and the flag-state rule

**Files:**
- Modify: `lemely/runtime/config.py` (add `MarkingOptions`, `GradingSettings.marking_options`, `marking_options_from`, `marking_flags_event`, `log_marking_flags`)
- Test: `tests/test_config_new_tasks.py`

**Interfaces:**
- Produces:
  - `MarkingOptions(equivalence_gate: bool = False, ecf_substitution: bool = False)`, a frozen dataclass.
  - `GradingSettings.marking_options(self) -> MarkingOptions`
  - `marking_options_from(settings: object) -> MarkingOptions`. Reads `settings.grading` when it is a `GradingSettings`; otherwise returns `MarkingOptions()`. For callers whose `settings` is untyped or may be `None` (the harness).
  - `marking_flags_event(options: MarkingOptions) -> tuple[Literal["info", "warning"], dict[str, object]]`
  - `log_marking_flags(options: MarkingOptions) -> None`. Emits event `"marking_flags"` on `structlog.get_logger("lemely.marking")` at the level `marking_flags_event` returns.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config_new_tasks.py`:

```python
class TestMarkingOptions:
    """Spec 2026-09-26: one object carries both marking flags to every caller."""

    def test_defaults_are_off(self) -> None:
        from lemely.runtime.config import MarkingOptions

        assert MarkingOptions() == MarkingOptions(equivalence_gate=False, ecf_substitution=False)

    def test_is_frozen(self) -> None:
        import dataclasses

        import pytest

        from lemely.runtime.config import MarkingOptions

        with pytest.raises(dataclasses.FrozenInstanceError):
            MarkingOptions().equivalence_gate = True  # type: ignore[misc]

    def test_grading_settings_projects_both_flags(self) -> None:
        from lemely.runtime.config import GradingSettings, MarkingOptions

        s = GradingSettings(equivalence_gate=True, ecf_substitution=True)
        assert s.marking_options() == MarkingOptions(equivalence_gate=True, ecf_substitution=True)

    def test_projection_reads_env_vars(self, monkeypatch) -> None:
        from lemely.runtime.config import MarkingOptions, Settings

        monkeypatch.setenv("LEMELY_GRADING__EQUIVALENCE_GATE", "true")
        monkeypatch.setenv("LEMELY_GRADING__ECF_SUBSTITUTION", "true")
        settings = Settings()
        assert settings.grading.marking_options() == MarkingOptions(
            equivalence_gate=True, ecf_substitution=True
        )

    def test_from_untyped_settings(self) -> None:
        from types import SimpleNamespace

        from lemely.runtime.config import GradingSettings, MarkingOptions, marking_options_from

        assert marking_options_from(None) == MarkingOptions()
        assert marking_options_from(SimpleNamespace()) == MarkingOptions()
        on = SimpleNamespace(grading=GradingSettings(equivalence_gate=True))
        assert marking_options_from(on) == MarkingOptions(equivalence_gate=True)


class TestMarkingFlagsEvent:
    """The startup line's level rule, tested without logging."""

    def test_consistent_flags_log_at_info(self) -> None:
        from lemely.runtime.config import MarkingOptions, marking_flags_event

        for opts in (
            MarkingOptions(),
            MarkingOptions(equivalence_gate=True),
            MarkingOptions(equivalence_gate=True, ecf_substitution=True),
        ):
            level, fields = marking_flags_event(opts)
            assert level == "info"
            assert fields == {
                "equivalence_gate": opts.equivalence_gate,
                "ecf_substitution": opts.ecf_substitution,
            }

    def test_ecf_without_gate_warns_that_ecf_is_inert(self) -> None:
        from lemely.runtime.config import MarkingOptions, marking_flags_event

        level, fields = marking_flags_event(MarkingOptions(ecf_substitution=True))
        assert level == "warning"
        assert fields["equivalence_gate"] is False
        assert fields["ecf_substitution"] is True
        assert fields["ecf_inert"] is True
        assert fields["reason"] == (
            "ecf_substitution has no effect unless equivalence_gate is also on"
        )
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `pytest tests/test_config_new_tasks.py -k "MarkingOptions or MarkingFlagsEvent" --no-cov -v`
Expected: FAIL with `ImportError: cannot import name 'MarkingOptions'`.

- [ ] **Step 3: Implement**

In `lemely/runtime/config.py`, add near the other imports (keep the file's existing import style and ordering):

```python
from dataclasses import dataclass
from typing import Literal

import structlog
```

Immediately above `class GradingSettings`, add:

```python
@dataclass(frozen=True)
class MarkingOptions:
    """The marking flags every ``correct_paper`` caller forwards together.

    Built by :meth:`GradingSettings.marking_options`. Both flags travel in
    one object so a caller cannot pass one and forget the other: three of
    six callers once passed ``equivalence_gate`` and none passed
    ``ecf_substitution``. Defaults are off, which marks exactly as a
    caller that sets nothing.
    """

    equivalence_gate: bool = False
    ecf_substitution: bool = False
```

Add this method inside `GradingSettings`, after the `ecf_substitution` field:

```python
    def marking_options(self) -> MarkingOptions:
        """Return the marking flags as the object ``correct_paper`` takes."""
        return MarkingOptions(
            equivalence_gate=self.equivalence_gate,
            ecf_substitution=self.ecf_substitution,
        )
```

After the `GradingSettings` class, add:

```python
_ECF_INERT_REASON = "ecf_substitution has no effect unless equivalence_gate is also on"


def marking_options_from(settings: object) -> MarkingOptions:
    """Read marking flags off an untyped or absent settings object.

    For callers such as the accuracy harness, whose ``settings`` is typed
    ``object`` and is ``None`` in unit tests. Anything without a real
    ``GradingSettings`` at ``.grading`` yields the defaults.
    """
    grading = getattr(settings, "grading", None)
    if isinstance(grading, GradingSettings):
        return grading.marking_options()
    return MarkingOptions()


def marking_flags_event(
    options: MarkingOptions,
) -> tuple[Literal["info", "warning"], dict[str, object]]:
    """Decide the level and fields of the startup ``marking_flags`` line.

    ``ecf_substitution`` on with ``equivalence_gate`` off is a legal but
    inert configuration: ECF is applied only on the verdicts path, which
    the gate controls. It logs at warning level so the mismatch is visible
    in Cloud Run logs; the process keeps running.
    """
    fields: dict[str, object] = {
        "equivalence_gate": options.equivalence_gate,
        "ecf_substitution": options.ecf_substitution,
    }
    if options.ecf_substitution and not options.equivalence_gate:
        fields["ecf_inert"] = True
        fields["reason"] = _ECF_INERT_REASON
        return "warning", fields
    return "info", fields


def log_marking_flags(options: MarkingOptions) -> None:
    """Emit one ``marking_flags`` line recording the process's marking mode."""
    level, fields = marking_flags_event(options)
    log = structlog.get_logger("lemely.marking")
    getattr(log, level)("marking_flags", **fields)
```

If `structlog`, `dataclass` or `Literal` are already imported in `config.py`, do not import them twice.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `pytest tests/test_config_new_tasks.py --no-cov`
Expected: all pass, including the pre-existing `TestEcfSubstitutionSettings`.

- [ ] **Step 5: Check layering**

Run: `lint-imports`
Expected: all contracts kept. `config.py` imports only `structlog`, the standard library and pydantic, never `lemely.core`, `lemely.io` or `lemely.app`.

- [ ] **Step 6: Commit**

```bash
git commit -S -m "feat(config): add MarkingOptions, the one object the marking flags travel in" -- lemely/runtime/config.py tests/test_config_new_tasks.py
```

---

### Task 2: `correct_paper` and `grade_paper` take `MarkingOptions`; CLI, student upload and teacher grading pass it

**Files:**
- Modify: `lemely/io/correction_ai.py` (`correct_paper` signature, docstring, start of body)
- Modify: `lemely/web/services/grading.py` (`grade_paper` signature, docstring, `correct_paper` call)
- Modify: `lemely/app/cli.py` (the `hybrid_correct_paper(...)` call in `correct_paper_cmd`, about line 354)
- Modify: `lemely/web/routers/student.py` (the `grade_paper(...)` call, about line 1059)
- Modify: `lemely/web/routers/teacher.py` (the `grade_paper(...)` call, about line 489)
- Test: `tests/test_web_teacher.py`, `tests/test_cli_json_contract.py`, `tests/test_student_correct.py`

**Interfaces:**
- Consumes: `MarkingOptions`, `GradingSettings.marking_options()`, `log_marking_flags` (Task 1).
- Produces:
  - `correct_paper(mark_scheme, extracted_answers, *, gemini_client=None, mcq_only=False, options: MarkingOptions = MarkingOptions()) -> CorrectionResult`
  - `grade_paper(mark_scheme, extracted_answers, *, gemini_client=None, mcq_only=False, student_id=None, history_store=None, boundary_store=None, integrity_settings=None, options: MarkingOptions = MarkingOptions()) -> AccuracyReport`

- [ ] **Step 1: Rewrite the two existing `grade_paper` forwarding tests to the new API**

In `tests/test_web_teacher.py`, replace `test_grade_paper_forwards_equivalence_gate_when_enabled` and `test_grade_paper_defaults_equivalence_gate_off` (added by `08df9302`, around line 654) with:

```python
def test_grade_paper_forwards_marking_options(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both flags must reach ``correct_paper``, not merely exist in settings.

    A test of the default alone cannot detect an unreachable flag; US-005b's
    original criteria passed while nothing could turn the gate on.
    """
    from lemely.runtime.config import MarkingOptions
    from lemely.web.services import grading as grading_service

    seen: dict[str, object] = {}

    def _spy(**kwargs: object) -> None:
        seen.update(kwargs)
        raise _StopForTest

    monkeypatch.setattr(grading_service, "correct_paper", _spy)
    opts = MarkingOptions(equivalence_gate=True, ecf_substitution=True)
    with pytest.raises(_StopForTest):
        grading_service.grade_paper(_scheme(), {}, options=opts)
    assert seen["options"] == opts


def test_grade_paper_defaults_marking_options_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from lemely.runtime.config import MarkingOptions
    from lemely.web.services import grading as grading_service

    seen: dict[str, object] = {}

    def _spy(**kwargs: object) -> None:
        seen.update(kwargs)
        raise _StopForTest

    monkeypatch.setattr(grading_service, "correct_paper", _spy)
    with pytest.raises(_StopForTest):
        grading_service.grade_paper(_scheme(), {})
    assert seen["options"] == MarkingOptions()
```

- [ ] **Step 2: Add a test that the teacher grading job passes settings' options**

First find the existing test that drives the teacher grading job through `grade_paper`:

Run: `grep -n "grade_paper" tests/test_web_teacher.py`

Pick the test that monkeypatches `lemely.web.routers.teacher.grade_paper` (or the module attribute the router calls) and runs the job to completion. Copy its arrangement into a new test named `test_grading_job_passes_marking_options_from_settings`, with two changes:
1. Before the job runs, set the flags: `monkeypatch.setenv("LEMELY_GRADING__EQUIVALENCE_GATE", "true")`, `monkeypatch.setenv("LEMELY_GRADING__ECF_SUBSTITUTION", "true")`, then call `deps.reset_singletons()` from `lemely.web import deps` so `get_settings()` re-reads the env. Call it again in a `finally` (or use the file's settings-reset fixture if it has one).
2. The fake `grade_paper` records its `options` keyword. Assert `recorded["options"] == MarkingOptions(equivalence_gate=True, ecf_substitution=True)`.

If no existing test drives the job with a patched `grade_paper`, write the test by calling the job function directly with the arguments its router call site builds. Say which in your report.

Do the same in `tests/test_student_correct.py`, which tests the student upload flow, as `test_upload_flow_passes_marking_options_from_settings`.

- [ ] **Step 3: Add a CLI forwarding test**

Append to `tests/test_cli_json_contract.py`, inside the existing test class that defines `test_correct_paper_json_validates_accuracy_report` (it has `self.runner` and `_real_ms_text()`):

```python
    def test_correct_paper_passes_marking_options_from_settings(self) -> None:
        import os
        from unittest import mock

        from lemely.io import correction_ai
        from lemely.runtime.config import MarkingOptions

        seen: dict[str, object] = {}

        class _Stop(Exception):
            pass

        def _spy(**kwargs: object) -> None:
            seen.update(kwargs)
            raise _Stop

        with TemporaryDirectory() as tmp:
            ms = Path(tmp) / "ms.json"
            ms.write_text(_real_ms_text(), "utf-8")
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "LEMELY_GRADING__EQUIVALENCE_GATE": "true",
                        "LEMELY_GRADING__ECF_SUBSTITUTION": "true",
                    },
                ),
                mock.patch.object(correction_ai, "correct_paper", _spy),
            ):
                self.runner.invoke(
                    cli, ["correct-paper", "--mark-scheme", str(ms), "--answers", "1 A"]
                )
        self.assertEqual(
            seen.get("options"), MarkingOptions(equivalence_gate=True, ecf_substitution=True)
        )
```

This works because `correct_paper_cmd` imports `correct_paper` from `lemely.io.correction_ai` inside the function, so patching the module attribute takes effect.

- [ ] **Step 4: Run the new and rewritten tests and confirm they fail**

Run: `pytest tests/test_web_teacher.py tests/test_cli_json_contract.py tests/test_student_correct.py -k "marking_options" --no-cov -v`
Expected: FAIL. `grade_paper` raises `TypeError: grade_paper() got an unexpected keyword argument 'options'`; the CLI and route tests fail because `options` was never passed.

- [ ] **Step 5: Change `correct_paper`**

In `lemely/io/correction_ai.py`, change the signature (about line 1851) from:

```python
    mcq_only: bool = False,
    equivalence_gate: bool = False,
    ecf_substitution: bool = False,
) -> CorrectionResult:
```

to:

```python
    mcq_only: bool = False,
    options: MarkingOptions = MarkingOptions(),
) -> CorrectionResult:
```

Import `MarkingOptions` from `lemely.runtime.config` with the file's other `lemely.runtime` imports.

Replace the `equivalence_gate:` and `ecf_substitution:` entries in the docstring's `Args` with:

```
        options: the marking flags, built by
            ``GradingSettings.marking_options()``. ``options.equivalence_gate``
            (US-005b) selects the verdicts marking path with the SymPy award
            gate. ``options.ecf_substitution`` (I7, US-013) applies
            error-carried-forward by substitution and has no effect unless
            ``equivalence_gate`` is also on: see
            :func:`_maybe_apply_ecf_substitution` for the gate/chain rules and
            the measured activation ceiling (0 on the committed corpus by
            construction). Defaults to both off.
```

As the first lines of the body, before `scheme = _load_mark_scheme(mark_scheme)`, add:

```python
    equivalence_gate = options.equivalence_gate
    ecf_substitution = options.ecf_substitution
```

The body's existing uses of `equivalence_gate` and `ecf_substitution` (about lines 2039, 2076, 2086, 2087) then need no change.

- [ ] **Step 6: Change `grade_paper`**

In `lemely/web/services/grading.py`, replace the parameter `equivalence_gate: bool = False,` with `options: MarkingOptions = MarkingOptions(),`. Replace its docstring entry with:

```
        options: The marking flags, forwarded to `correct_paper`. Defaults to
            both off, so behaviour is unchanged unless a caller opts in.
            Callers pass `settings.grading.marking_options()`.
```

In the `correct_paper(...)` call, replace `equivalence_gate=equivalence_gate,` with `options=options,`. Import `MarkingOptions` from `lemely.runtime.config`.

- [ ] **Step 7: Change the three callers**

`lemely/app/cli.py`, in `correct_paper_cmd`. Replace:

```python
        equivalence_gate=settings.grading.equivalence_gate,
    )
```

with:

```python
        options=marking_options,
    )
```

and, directly after `settings = _get_settings(ctx)`, add:

```python
    marking_options = settings.grading.marking_options()
    log_marking_flags(marking_options)
```

Import `log_marking_flags` from `lemely.runtime.config` inside the function, next to the other in-function imports.

`lemely/web/routers/student.py` and `lemely/web/routers/teacher.py`. In each `grade_paper(...)` call, replace `equivalence_gate=settings.grading.equivalence_gate,` with `options=settings.grading.marking_options(),`.

- [ ] **Step 8: Check nothing else passes the old keyword arguments**

Run: `grep -rn "equivalence_gate=\|ecf_substitution=" lemely tests scripts`
Expected: only uses of the internal helpers (`_build_ai_corrected`, `_maybe_apply_ecf_substitution`, `mark_question`, `build_marker_user_prompt`), `GradingSettings(...)`/`MarkingOptions(...)` constructors, and the two lines inside `correct_paper`'s own body. No call to `correct_paper` or `grade_paper` may pass either keyword. Fix any that do.

- [ ] **Step 9: Run the covering tests and confirm they pass**

Run: `pytest tests/test_web_teacher.py tests/test_cli_json_contract.py tests/test_student_correct.py tests/test_correction_ai.py tests/test_question_points.py tests/test_config_new_tasks.py --no-cov`
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git commit -S -m "feat(correction): take MarkingOptions in correct_paper and grade_paper, and pass it from the CLI and both web grading flows" -- lemely/io/correction_ai.py lemely/web/services/grading.py lemely/app/cli.py lemely/web/routers/student.py lemely/web/routers/teacher.py tests/test_web_teacher.py tests/test_cli_json_contract.py tests/test_student_correct.py
```

---

### Task 3: Quiz marking passes the configured options

**Files:**
- Modify: `lemely/db/quiz_marking_repo.py` (`QuizMarkingService.__init__` and the `correct_paper(...)` call, about line 263)
- Modify: `lemely/web/deps.py` (`get_quiz_marking_service`, about line 552)
- Test: `tests/test_quiz_marking_repo.py`

**Interfaces:**
- Consumes: `MarkingOptions`, `GradingSettings.marking_options()` (Task 1); `correct_paper(..., options=...)` (Task 2).
- Produces: `QuizMarkingService.__init__(..., *, integrity_settings=None, marking_options: MarkingOptions | None = None, now=_utcnow)`

- [ ] **Step 1: Write the failing test**

Read the test at `tests/test_quiz_marking_repo.py:572`. It builds a `QuizMarkingService` over a throwaway database and marks a submission. Add a new test, `test_marking_passes_configured_marking_options`, reusing that arrangement exactly, with these changes:

1. Construct the service with `marking_options=MarkingOptions(equivalence_gate=True, ecf_substitution=True)`.
2. Before calling `mark_submission`, patch the module attribute the service calls:

```python
    from lemely.db import quiz_marking_repo
    from lemely.runtime.config import MarkingOptions

    seen: dict[str, object] = {}

    class _Stop(Exception):
        pass

    def _spy(**kwargs: object) -> None:
        seen.update(kwargs)
        raise _Stop

    monkeypatch.setattr(quiz_marking_repo, "correct_paper", _spy)
```

3. Call `mark_submission` inside `contextlib.suppress(Exception)`: the service may catch `_Stop` and record a failure, and either outcome is fine here.
4. Assert: `assert seen["options"] == MarkingOptions(equivalence_gate=True, ecf_substitution=True)`.

Add a second test, `test_marking_defaults_marking_options_off`, identical except that the service is built without `marking_options`, and assert `seen["options"] == MarkingOptions()`.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `pytest tests/test_quiz_marking_repo.py -k "marking_options" --no-cov -v`
Expected: FAIL with `TypeError: ... unexpected keyword argument 'marking_options'`.

- [ ] **Step 3: Implement**

In `QuizMarkingService.__init__`, add the parameter after `integrity_settings`:

```python
        marking_options: MarkingOptions | None = None,
```

Add to its docstring: "``marking_options`` defaults to both flags off when omitted." In the body, add:

```python
        self._marking_options = marking_options or MarkingOptions()
```

In the `correct_paper(...)` call (about line 263), add `options=self._marking_options,`. Import `MarkingOptions` beside the existing `from lemely.runtime.config import IntegritySettings`.

In `lemely/web/deps.py`, `get_quiz_marking_service`, change the return to:

```python
    settings = get_settings()
    return QuizMarkingService(
        get_sessionmaker(settings),
        get_attempt_repo(),
        get_gemini_client(),
        marking_options=settings.grading.marking_options(),
    )
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `pytest tests/test_quiz_marking_repo.py tests/test_placement_repo.py --no-cov`
Expected: all pass. `tests/test_placement_repo.py:614` also builds a `QuizMarkingService`, and the new parameter has a default, so it must still pass.

- [ ] **Step 5: Commit**

```bash
git commit -S -m "feat(quiz): mark quizzes with the configured marking options, as papers are" -- lemely/db/quiz_marking_repo.py lemely/web/deps.py tests/test_quiz_marking_repo.py
```

Out of scope; note it in your report, do not fix it: `get_quiz_marking_service` also never passes `integrity_settings`, so quiz marking uses the default `IntegritySettings` rather than the configured ones.

---

### Task 4: The accuracy harness and Gradio pass the options; the fingerprint tells flag-on runs apart

**Files:**
- Modify: `lemely/accuracy/harness.py` (`measure_accuracy`, its `correct_paper(...)` call about line 1209, `_build_run_manifest` about line 866)
- Modify: `lemely/app/gradio_app.py` (the `hybrid_correct_paper(...)` call, about line 273)
- Test: `tests/test_accuracy_harness.py`

**Interfaces:**
- Consumes: `MarkingOptions`, `marking_options_from`, `log_marking_flags` (Task 1); `correct_paper(..., options=...)` (Task 2).
- Produces: no new public names. `params_fingerprint` gains `|equivalence_gate=True` and/or `|ecf_substitution=True` only when a flag is on.

- [ ] **Step 1: Write the failing fingerprint tests**

In `tests/test_accuracy_harness.py`, inside `class RunManifestTests` (about line 1303, which defines `_case` and `_settings_with_models`), add:

```python
    def _manifest(self, settings: object) -> object:
        from lemely.accuracy.harness import _build_run_manifest

        return _build_run_manifest(
            "run",
            [self._case()],
            settings,
            {"extraction": "v1", "correction": "v1", "mark_scheme": "v1"},
        )

    def test_flag_off_fingerprint_is_unchanged(self) -> None:
        """Settings with both flags off hash exactly as before this change.

        Before the change the harness never read ``settings.grading``, so a
        stand-in without it reproduces the old computation. Adding a
        flags-off ``grading`` must not move the hash, or every existing
        baseline becomes incomparable.
        """
        from lemely.runtime.config import GradingSettings

        without = self._settings_with_models()
        with_off = self._settings_with_models()
        with_off.grading = GradingSettings()
        self.assertEqual(
            self._manifest(without).params_fingerprint,
            self._manifest(with_off).params_fingerprint,
        )

    def test_each_flag_moves_the_fingerprint(self) -> None:
        from lemely.runtime.config import GradingSettings

        prints = set()
        for grading in (
            GradingSettings(),
            GradingSettings(equivalence_gate=True),
            GradingSettings(ecf_substitution=True),
            GradingSettings(equivalence_gate=True, ecf_substitution=True),
        ):
            settings = self._settings_with_models()
            settings.grading = grading
            prints.add(self._manifest(settings).params_fingerprint)
        self.assertEqual(len(prints), 4, "each flag combination must hash differently")
```

If `_settings_with_models()` returns an object that rejects attribute assignment, build the settings instead as `SimpleNamespace(**vars(stand_in), grading=...)`, and say so in your report.

- [ ] **Step 2: Write the failing `measure_accuracy` forwarding test**

In the same file, find an existing test that calls `measure_accuracy` with a stubbed or recorded `correct_paper` (run `grep -n "measure_accuracy(" tests/test_accuracy_harness.py`). Copy its arrangement into `test_measure_accuracy_passes_marking_options_from_settings`, with two changes:
1. Patch `lemely.accuracy.harness.correct_paper` with a spy that records `kwargs["options"]` and then returns what the original stub returned (or raises a local `_Stop`, caught with `contextlib.suppress`).
2. Pass settings whose `grading` is `GradingSettings(equivalence_gate=True, ecf_substitution=True)`.

Assert the recorded options equal `MarkingOptions(equivalence_gate=True, ecf_substitution=True)`.

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `pytest tests/test_accuracy_harness.py -k "fingerprint or marking_options" --no-cov -v`
Expected: `test_flag_off_fingerprint_is_unchanged` PASSES (nothing reads `grading` yet). `test_each_flag_moves_the_fingerprint` FAILS (one distinct value, not four). The forwarding test FAILS (no `options` passed).

The first test passing before the change is expected: it pins behaviour that must not change. Record that in your report rather than forcing it red.

- [ ] **Step 4: Implement the fingerprint segments**

In `_build_run_manifest`, inside the `if gemini is not None:` branch, directly before `if arm is not None:`, add:

```python
        # Spec 2026-09-26: the marking flags decide which calls a run issues
        # (the verdicts path, ECF re-marks), so two sweeps differing only in
        # them must not share a fingerprint. Each segment is appended only
        # when its flag is ON, so a flags-off run hashes exactly as it did
        # before the flags were read here and every existing baseline stays
        # comparable.
        marking = marking_options_from(settings)
        if marking.equivalence_gate:
            fingerprint_raw += "|equivalence_gate=True"
        if marking.ecf_substitution:
            fingerprint_raw += "|ecf_substitution=True"
```

Import `marking_options_from` and `log_marking_flags` from `lemely.runtime.config`, with the file's existing `lemely.runtime` imports.

- [ ] **Step 5: Implement `measure_accuracy` forwarding and the start log**

At the start of `measure_accuracy`'s body (after the docstring, before any case is processed), add:

```python
    marking_options = marking_options_from(settings)
    log_marking_flags(marking_options)
```

In the `correct_paper(...)` call (about line 1209), add `options=marking_options,`.

- [ ] **Step 6: Gradio**

In `lemely/app/gradio_app.py`, in the `hybrid_correct_paper(...)` call (about line 273), add `options=settings.grading.marking_options(),`. `settings` is already in scope there; it is used on the line above to build `GeminiClient(settings)`.

- [ ] **Step 7: Run the tests and confirm they pass**

Run: `pytest tests/test_accuracy_harness.py --no-cov`
Expected: all pass, including the pre-existing fingerprint tests (`test_params_fingerprint_distinguishes_different_models` and the thinking-level test).

- [ ] **Step 8: Commit**

```bash
git commit -S -m "feat(harness): pass marking options to correct_paper and fold enabled flags into params_fingerprint" -- lemely/accuracy/harness.py lemely/app/gradio_app.py tests/test_accuracy_harness.py
```

---

### Task 5: Web startup log, a guard against unwired callers, and stale comments

**Files:**
- Modify: `lemely/web/app.py` (`_lifespan`)
- Modify: `lemely/runtime/config.py` (the `equivalence_gate` and `ecf_substitution` comments)
- Test: `tests/test_web_app.py`, `tests/test_marking_options_wiring.py` (create)

**Interfaces:**
- Consumes: `log_marking_flags`, `MarkingOptions` (Task 1); every caller wired in Tasks 2-4.

- [ ] **Step 1: Write the failing startup-log test**

In `tests/test_web_app.py`, after `test_the_sweeper_is_started_on_startup_and_stopped_on_shutdown`, add:

```python
@pytest.mark.usefixtures("_fresh_settings")
def test_startup_logs_the_marking_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every revision records which marking mode it runs, in its own logs."""
    from structlog.testing import capture_logs

    monkeypatch.setenv("LEMELY_NOTIFICATIONS__SWEEPER_ENABLED", "0")
    monkeypatch.setenv("LEMELY_GRADING__ECF_SUBSTITUTION", "true")

    with capture_logs() as logs, TestClient(create_app()) as client:
        assert client.get("/api/health").status_code == 200

    flags = [e for e in logs if e["event"] == "marking_flags"]
    assert len(flags) == 1
    assert flags[0]["log_level"] == "warning"
    assert flags[0]["equivalence_gate"] is False
    assert flags[0]["ecf_substitution"] is True
    assert flags[0]["ecf_inert"] is True
```

- [ ] **Step 2: Write the failing wiring guard**

Create `tests/test_marking_options_wiring.py`:

```python
"""Every call to correct_paper or grade_paper in lemely/ passes options=.

Three of six callers once passed equivalence_gate and none passed
ecf_substitution, and no test noticed, because each caller's own tests
only covered the default. This is a structural check: it covers callers,
such as the Gradio app, that no behavioural test drives. A new call site
that omits options= fails here instead of silently marking with the
defaults.
"""

from __future__ import annotations

import ast
from pathlib import Path

_TARGETS = {"correct_paper", "hybrid_correct_paper", "grade_paper"}
_PACKAGE = Path(__file__).resolve().parent.parent / "lemely"


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def test_every_marking_call_passes_options() -> None:
    missing: list[str] = []
    for path in sorted(_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _called_name(node) not in _TARGETS:
                continue
            if not any(kw.arg == "options" for kw in node.keywords):
                rel = path.relative_to(_PACKAGE.parent)
                missing.append(f"{rel}:{node.lineno} {_called_name(node)}(...)")
    assert not missing, "marking call sites without options=:\n" + "\n".join(missing)


def test_the_guard_sees_all_six_callers() -> None:
    """The guard is not vacuous: it finds the six known call sites."""
    found = 0
    for path in _PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _called_name(node) in _TARGETS
        )
    assert found >= 6
```

- [ ] **Step 3: Run the tests**

Run: `pytest tests/test_web_app.py -k marking_flags tests/test_marking_options_wiring.py --no-cov -v`
Expected: `test_startup_logs_the_marking_flags` FAILS (no `marking_flags` event). Both guard tests PASS, because Tasks 2-4 wired every caller.

The wiring guard cannot go red naturally at this point. Prove it discriminates: temporarily delete `options=settings.grading.marking_options(),` from `lemely/app/gradio_app.py`, run the guard and record that `test_every_marking_call_passes_options` fails and names `lemely/app/gradio_app.py`. Then restore the line and confirm `git diff lemely/app/gradio_app.py` is empty.

- [ ] **Step 4: Implement the startup log**

In `lemely/web/app.py` `_lifespan`, directly after `settings = get_settings()`, add:

```python
    log_marking_flags(settings.grading.marking_options())
```

Import `log_marking_flags` from `lemely.runtime.config`. It logs through structlog, not through the module's stdlib `log`; the structlog bridge still routes it to the same output.

- [ ] **Step 5: Correct the stale comments in `config.py`**

In `lemely/runtime/config.py`:

1. In the `equivalence_gate` comment, replace the sentence that starts "`08df9302` closed US-040: this field is now read off a loaded config at all three existing `correct_paper` entry points" and ends "so these two adjacent flags do not behave alike." with:

```
    # Every `correct_paper` caller now reads this field through
    # `GradingSettings.marking_options()` (spec 2026-09-26): the CLI, both
    # web grading flows, quiz marking, the accuracy harness and the Gradio
    # app. `tests/test_marking_options_wiring.py` fails if a call site omits
    # `options=`. Setting `equivalence_gate = true` changes how every one of
    # them marks non-MCQ answers. In the deployed service it is set by
    # `LEMELY_GRADING__EQUIVALENCE_GATE`; see `docs/ci-cd.md`.
```

2. In the `ecf_substitution` comment, delete the final paragraph that starts "Whole-branch review Minor C" and ends "see US-040." Replace it with:

```
    #
    # Read by every `correct_paper` caller through `marking_options()`, the
    # same as `equivalence_gate`. Setting it without `equivalence_gate` is
    # legal but inert, and each process logs a `marking_flags` warning at
    # startup when that is the case. In the deployed service it is set by
    # `LEMELY_GRADING__ECF_SUBSTITUTION`.
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `pytest tests/test_web_app.py tests/test_marking_options_wiring.py tests/test_config_new_tasks.py --no-cov`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add -- tests/test_marking_options_wiring.py
git commit -S -m "feat(web): log the marking flags at startup, and guard every marking call site" -- lemely/web/app.py lemely/runtime/config.py tests/test_web_app.py tests/test_marking_options_wiring.py
```

---

### Task 6: CD sets the flags per environment, and `docs/ci-cd.md` explains deployed configuration

**Files:**
- Modify: `.github/workflows/deploy.yml` (the Cloud Run `env_vars` block, about lines 327-344)
- Modify: `docs/ci-cd.md` (new section after "### 4. GitHub — environments, secrets, variables")

**Interfaces:**
- Consumes: the setting names `grading.equivalence_gate` and `grading.ecf_substitution`, and the `marking_flags` startup line (Task 5).

- [ ] **Step 1: Add the two variables to the deploy**

In `.github/workflows/deploy.yml`, in the `env_vars: |-` block, directly after the line `LEMELY_LOGGING__FORMAT=json`, add:

```
            LEMELY_GRADING__EQUIVALENCE_GATE=${{ vars.GRADING_EQUIVALENCE_GATE || 'false' }}
            LEMELY_GRADING__ECF_SUBSTITUTION=${{ vars.GRADING_ECF_SUBSTITUTION || 'false' }}
```

Match the block's existing indentation exactly.

- [ ] **Step 2: Validate the workflow file**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/deploy.yml'))" && echo ok`
Expected: `ok`.

If `actionlint` is installed, also run `actionlint .github/workflows/deploy.yml`. Otherwise say it was not run.

- [ ] **Step 3: Add the documentation section**

In `docs/ci-cd.md`, insert this section immediately before `## Credentials checklist`:

```markdown
## Configuring the deployed service

The API reads its settings in this order: environment variables, then
`.env`, then `lemely.toml`, then built-in defaults
(`lemely/runtime/config.py`). The Docker image ships no `lemely.toml` and no
`.env`, so on Cloud Run a setting is either an environment variable or its
default.

**Naming.** Any setting maps to an environment variable: prefix `LEMELY_`,
section and key joined by `__`, in capitals. `[grading] equivalence_gate`
becomes `LEMELY_GRADING__EQUIVALENCE_GATE`; `[storage] bucket` becomes
`LEMELY_STORAGE__BUCKET`.

**Where the value comes from.** `deploy.yml` sets the service's environment
in the Cloud Run step's `env_vars` block. Each line takes its value from
GitHub:

- `${{ vars.NAME }}` for anything that is not a secret, such as feature
  flags, bucket names and URLs.
- `${{ secrets.NAME }}` for credentials.

Both are defined per environment under **Settings → Environments →
`staging` / `production`**. The deploy job runs inside the environment it
targets, so the same line picks up staging's value on a staging deploy and
production's value on a production deploy.

**Adding a new setting takes two steps.** Setting a GitHub variable alone
does nothing:

1. Add a line to `env_vars` in `deploy.yml`, with a default:
   `LEMELY_SECTION__KEY=${{ vars.SECTION_KEY || 'default' }}`.
2. Set `SECTION_KEY` in each environment where it should differ from the
   default, then redeploy that environment.

### The marking flags

Two settings change how answers are marked:

| Setting | GitHub variable | Default | Effect |
|---|---|---|---|
| `LEMELY_GRADING__EQUIVALENCE_GATE` | `GRADING_EQUIVALENCE_GATE` | `false` | Marks non-MCQ answers on the verdicts path with the SymPy award gate. |
| `LEMELY_GRADING__ECF_SUBSTITUTION` | `GRADING_ECF_SUBSTITUTION` | `false` | Applies error-carried-forward by substitution. Has no effect unless `GRADING_EQUIVALENCE_GATE` is also `true`. |

Both apply to every marking path: paper uploads, the teacher grading job,
quiz marking and the CLI. Turning one on changes marks for real students, so
measure it first with an accuracy sweep. The harness reads the same
settings, and a flag-on sweep gets a different `params_fingerprint` from a
flag-off one, so the two can be compared.

To try a flag on staging only:

1. **Settings → Environments → `staging` → Environment variables → Add**:
   `GRADING_EQUIVALENCE_GATE` = `true`.
2. Re-run the deploy workflow for staging (`workflow_dispatch` with
   `environment: staging`, or push to the staging branch).
3. Confirm the new revision's mode in Cloud Run logs. Every revision logs one
   `marking_flags` line at startup with both values. If ECF is on without the
   gate, that line is a warning with `ecf_inert=true`.

Production is unaffected until its own `production` environment variable is
set and production is redeployed.
```

- [ ] **Step 4: Check the documented names against the code**

Run: `grep -n "GRADING_EQUIVALENCE_GATE\|GRADING_ECF_SUBSTITUTION" .github/workflows/deploy.yml docs/ci-cd.md`
Expected: each variable name appears in both files, spelled identically.

Also read the paragraph about the deploy trigger. Check `deploy.yml`'s `on:` block and `resolve-env` job, and correct step 2's "push to the staging branch" if staging deploys are triggered some other way. The `resolve-env` job treats `refs/heads/main` as production and everything else as staging; describe exactly what `on:` allows.

- [ ] **Step 5: Commit**

```bash
git commit -S -m "ci(deploy): set the marking flags per environment, and document how deployed config works" -- .github/workflows/deploy.yml docs/ci-cd.md
```

- [ ] **Step 6: Manual check after the next staging deploy (not part of this task's commit)**

After the branch reaches staging, open the Cloud Run logs for the new revision and confirm one `marking_flags` line with `equivalence_gate=false` and `ecf_substitution=false`. Record the result in the ledger.

---

## Controller notes, not implementer tasks

- After Task 6, update the PR #237 description. Replace the section "Two flags ship OFF, and one of them is not merely off" with one saying both flags are now wired through every marking path, default off, and set per environment through `GRADING_EQUIVALENCE_GATE`/`GRADING_ECF_SUBSTITUTION`, pointing at `docs/ci-cd.md`.
- Whole-branch review at the end, per subagent-driven-development.
