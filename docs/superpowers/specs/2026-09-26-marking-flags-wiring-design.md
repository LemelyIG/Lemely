# Wiring the marking flags through every marking path, and into CD

Date: 2026-09-26. Status: design approved.

## Problem

Two settings in `GradingSettings` (`lemely/runtime/config.py`) change how non-MCQ answers are marked:

- `equivalence_gate` (US-005b): the verdicts marking path with the SymPy award gate.
- `ecf_substitution` (I7, US-013): error-carried-forward by substitution. It has no effect unless `equivalence_gate` is also on, because `_maybe_apply_ecf_substitution` checks the gate explicitly.

`correct_paper` (`lemely/io/correction_ai.py`) accepts both. Its six callers do not all pass them:

| Caller | `equivalence_gate` | `ecf_substitution` |
|---|---|---|
| `lemely/app/cli.py` (`correct_paper_cmd`) | passed | not passed |
| `lemely/web/routers/student.py` (paper upload, via `grade_paper`) | passed | not passed |
| `lemely/web/routers/teacher.py` (grading job, via `grade_paper`) | passed | not passed |
| `lemely/db/quiz_marking_repo.py` (`QuizMarkingService`, live quiz marking) | not passed | not passed |
| `lemely/accuracy/harness.py` (`measure_accuracy`) | not passed | not passed |
| `lemely/app/gradio_app.py` | not passed | not passed |

Consequences today:

- Setting `ecf_substitution` anywhere has no effect on any run.
- Setting `equivalence_gate` changes paper grading, but not quiz marking. The same student can then be marked under two different rules on the same day.
- The accuracy harness cannot measure either flag. Neither flag should be turned on in production without that evidence.
- The deployed service has no way to set either flag. The image ships no `lemely.toml`, and `deploy.yml` sets no `LEMELY_GRADING__*` variable.

## Goals

1. Every `correct_paper` caller reads both flags from settings.
2. A caller cannot forget one flag, because the flags travel together.
3. Every process records which marking mode it runs.
4. Harness sweeps with different flags never share a `params_fingerprint`, and flag-off sweeps keep today's fingerprint.
5. Staging and production can set the flags independently, without a code change.

Non-goals:

- Turning either flag on anywhere. Defaults stay `False`.
- Changing what either flag does once it reaches `correct_paper`.
- Widening the ECF gate. Its activation ceiling on the committed corpus is 0 by construction (see the `ecf_substitution` comment in `config.py`). That is an input-data limit, not something this work addresses.

## Design

### 1. `MarkingOptions`

A frozen dataclass in `lemely/runtime/config.py`, next to `GradingSettings`:

```python
@dataclass(frozen=True)
class MarkingOptions:
    equivalence_gate: bool = False
    ecf_substitution: bool = False
```

`GradingSettings.marking_options() -> MarkingOptions` builds it. This method is the single place where settings become marking behaviour.

It lives in `lemely.runtime` because of the import-linter contracts: `lemely.runtime` must not import `lemely.core`, `lemely.io` or `lemely.app`. All three may import `lemely.runtime`.

`correct_paper` replaces its two bool keyword arguments with `options: MarkingOptions = MarkingOptions()`. `grade_paper` (`lemely/web/services/grading.py`) does the same and forwards it. Functions below `correct_paper` keep their bool parameters; `correct_paper` unpacks the object once.

There is one API, not two. The four test files that pass the bools today (`test_web_teacher.py`, `test_config_new_tasks.py`, `test_correction_ai.py`, `test_question_points.py`) move to `options=MarkingOptions(...)`.

### 2. The six callers

Each passes `settings.grading.marking_options()`:

- **CLI, student upload, teacher grading.** Swap the existing `equivalence_gate=...` argument for `options=...`.
- **Quiz marking.** `QuizMarkingService.__init__` gains `marking_options: MarkingOptions | None = None`, following its existing `integrity_settings` parameter. `web/deps.py` passes `settings.grading.marking_options()` where it builds the service. `None` means `MarkingOptions()`.
- **Harness.** `measure_accuracy` already receives `settings`. It reads `settings.grading.marking_options()` when settings are present, and `MarkingOptions()` when they are `None` (the test path).
- **Gradio.** It already has `settings` in scope; pass it.

### 3. Recording the flag state

Each process logs one line when it starts:

```
marking_flags equivalence_gate=<bool> ecf_substitution=<bool>
```

- Web: in `_lifespan` (`lemely/web/app.py`), after logging is configured.
- CLI: at the start of `correct_paper_cmd`.
- Harness: at the start of `measure_accuracy`.

When `ecf_substitution` is on and `equivalence_gate` is off, the same event logs at warning level with an extra field: `ecf_inert=True, reason="ecf_substitution has no effect unless equivalence_gate is also on"`. The process keeps running; this was chosen over refusing to start.

A pure function, `marking_flags_event(options) -> tuple[level, fields]`, decides the level and fields. The three log sites call it, so the rule lives in one place and is unit-tested without logging.

### 4. Harness fingerprint

In the manifest builder (`harness.py`, around `fingerprint_raw`), append a segment only when a flag is on:

```python
if options.equivalence_gate:
    fingerprint_raw += "|equivalence_gate=True"
if options.ecf_substitution:
    fingerprint_raw += "|ecf_substitution=True"
```

A run with both flags off hashes exactly as it does today, so existing baselines stay comparable. Any flag-on run gets a different fingerprint. This follows the rule the surrounding comments already state: two sweeps that issue different calls must not share a fingerprint.

The segments go before the `arm` suffix, and both apply in the same code path as the other settings-derived segments.

### 5. CD

In `deploy.yml`'s Cloud Run `env_vars` block:

```
LEMELY_GRADING__EQUIVALENCE_GATE=${{ vars.GRADING_EQUIVALENCE_GATE || 'false' }}
LEMELY_GRADING__ECF_SUBSTITUTION=${{ vars.GRADING_ECF_SUBSTITUTION || 'false' }}
```

The deploy job runs inside the `staging` or `production` GitHub environment, so `vars.*` resolves per environment. An unset variable deploys `false`.

`docs/ci-cd.md` gets a section, "Configuring the deployed service", covering:

- Any setting maps to `LEMELY_<SECTION>__<KEY>`: prefix `LEMELY_`, nested delimiter `__`.
- Precedence is env > `.env` > `lemely.toml` > defaults. The image ships no `lemely.toml`, so on Cloud Run only environment variables and defaults apply.
- Non-secret values go in environment **variables** (`vars.*`); credentials go in environment **secrets** (`secrets.*`). Both are set per environment under Settings > Environments.
- To turn a marking flag on for staging only: set `GRADING_EQUIVALENCE_GATE=true` in the `staging` environment's variables, then redeploy staging. Production is unchanged until its own variable is set.
- A new setting reaches Cloud Run only once a line for it is added to `env_vars`. Setting a GitHub variable alone does nothing.
- The startup `marking_flags` log line is how to confirm what a revision is running.

### 6. Stale text to remove

These describe the unwired state and become false:

- `config.py`, the `ecf_substitution` comment's "Whole-branch review Minor C" paragraph ("currently has NO effect on a live `correct_paper` run").
- The `equivalence_gate` comment's "all three existing `correct_paper` entry points".
- `correct_paper` and `grade_paper` docstrings describing the bool arguments.
- The PR #237 description section "Two flags ship OFF, and one of them is not merely off".

## Testing

- **Callers.** One test per caller proving the options from settings reach `correct_paper`. Model them on 08df9302's teacher-job test: patch `correct_paper`, set the flags, assert the received `options`. That covers CLI, student upload, teacher grading, quiz marking, harness and Gradio. Each must fail against today's code.
- **`GradingSettings.marking_options()`.** Maps both fields, including from `LEMELY_GRADING__*` environment variables.
- **`marking_flags_event`.** Info level when consistent. Warning with `ecf_inert` when ECF is on and the gate is off.
- **Fingerprint.** Pin today's flag-off value so it cannot drift. Assert that each flag alone, and both together, produce three distinct values that differ from the off value.
- **Startup log.** One web lifespan test using `capture_logs`. The global structlog reset in `tests/conftest.py` makes that reliable in the full suite.

`deploy.yml` and `docs/ci-cd.md` changes have no automated test. The plan should include a manual check: after the next staging deploy, confirm the `marking_flags` line appears in Cloud Run logs with both values `False`.

## Risks

- **Quiz marking changes behaviour when the gate is flipped.** That is the point, but it means flipping the gate now affects quizzes too. The `docs/ci-cd.md` section says so.
- **Signature change.** Any caller outside `lemely/` and `tests/` that passes `equivalence_gate=` to `correct_paper` breaks. A repository-wide search should find none; the plan includes it.
