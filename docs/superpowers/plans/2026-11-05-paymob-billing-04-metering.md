# Paymob billing phase 04: usage metering implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Charge every LLM-backed web action at its actual LLM cost through the phase 01 usage ledger. Each action first gets a server-computed range estimate and a payer chain check (spec §5.6). It can be blocked with a machine-readable 402.

**Architecture:** A contextvar accumulator (`lemely/io/llm/cost_meter.py`) is fed from the one place both providers price a call (`GeminiClient._record_spend`). A pure `build_payer_chain` (`lemely/core/payer_chain.py`) turns DB-loaded facts (seats, assistant row, debtors, study plans this week) into an ordered `Payer` list. `lemely/web/usage.py` has three steps. `UsageMeter.authorize` makes no writes: it estimates, builds the chain and checks the balance, and raises 402. `UsageMeter.reserve` runs in the request, so a 402 can still come back before a stream or pool job starts. `with job.run():` wraps the work in whatever thread does it, then settles on success and releases on failure. All nine audited routes are wired, and signup allowances, the usage API and three sweeper jobs are added.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (sync sessions), Postgres, pytest, structlog, `contextvars`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-11-02-paymob-billing-design.md` (revision 2). Index and shared contracts: `docs/superpowers/plans/2026-11-05-paymob-billing-00-index.md`. Names in the index are fixed.
- Signed commits only: `git commit -S -m "<msg>" -- <paths>` (stage new files with `git add <paths>` first). Scope `feat(usage):`, tests-only commits `test(usage):`.
- Before every commit: `/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files`, fix every failure, re-run until clean. The ruff hook autofixes; re-stage what it rewrote.
- Tests: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest <touched test files> -v --no-cov`. Never `make test`, never bare `pytest`.
- Repo lint tests that scan `lemely/` and must stay green (run them in the task named): `tests/architecture/` (import-linter contracts, no `print` in core), `tests/test_authz_matrix_complete.py` (every route declared, section counts checked), `tests/test_script_cost_scope.py` (AST: `script_cost_scope` encloses the paid calls in `student_correct` and `_run_grading_job`), `tests/test_events_scoping.py`, `tests/test_marking_options_wiring.py`, `tests/test_include_deleted_scope.py`, `tests/test_settings_example_drift.py`.
- Usage is integer units (`BIGINT`); USD LLM cost is `Decimal` (`NUMERIC(12, 6)`), never float, once it leaves the provider layer.
- `lemely/db/models/*` never imports `lemely.core`. `lemely.core.*` never imports `lemely.io`, `lemely.db`, `lemely.web`, `sqlalchemy` or `fastapi` (layers contract plus the new "Metering pure rules stay pure" contract).
- No placeholder code: no `TODO`, no `pass` bodies, no `test.skip`, no stub tests.
- Do not push, do not open PRs. Work only in `/home/sico/Code/Lemely/.claude/worktrees/paymob-integration`.
- Failed jobs, and inputs rejected before any model call, cost nothing (spec §2.4). Settlement or release failures after the work finished are logged (`usage_finish_failed`), never raised into the user's request.

## Consumes (phases 01 and 03, merged before this phase starts)

- `lemely/core/usage_types.py`: `GrantScope` (`ALLOWANCE`, `CREDITS`, `SEAT`, values `"allowance"`, `"credits"`, `"seat"`), `Payer(owner_user_id, scope, teacher_member_id=None, cap_units=None, cap_window_start=None, debt_exempt=False)`, `EstimatorParams(version, input_kind, base_low, base_high, per_input_low, per_input_high)`.
- `lemely/core/usage_pricing.py`: `estimate_range(params, input_count) -> tuple[int, int]`.
- `lemely/db/models/usage.py`: `GrantKind`, `UsageJobStatus`, `EstimatorInputKind`, `UsageGrant`, `UsageJob`, `UsageGrantBalance`, `UsageDebt`, `UsageRate`, `UsageEstimator` (columns per spec §4.1, §4.5; `UsageJob` has `id` PK, unique `job_id`, `created_at` from `TimestampMixin`; `UsageRate`/`UsageEstimator` unique `(version, action)`).
- `lemely/db/usage_ledger_repo.py` (verified against plan 01): `InsufficientBalance(*, available, required)` (attributes `available`, `required`), `UsageLedger(session)` with `issue_grant`, `available(payers, *, now)`, `has_debt`, `reserve(...)` (raises `ValueError` on an empty chain; stores the chain in `usage_jobs.payer_chain` JSONB), `settle(job_id, *, actual_cost_usd, now) -> UsageJob` (returns a job that is no longer open unchanged, never raises for it), `release(job_id, *, now)`, `expire_stale_jobs(*, now)`, `expire_grants(*, now)`, `reconcile_balances()` (one `(row_id, cached, actual)` per drifted value; also repairs the cache), `meter_fraction(owner_user_id, *, teacher_member_id, now)`. The ledger converts USD to units at the job's `rate_version`, applies caps per `(owner, payer.teacher_member_id)`, skips indebted payers unless `debt_exempt`, and puts debt on `payers[-1].owner_user_id`. `Payer` raises `ValueError` for `debt_exempt` on a non-SEAT payer, for a cap without `teacher_member_id`, and for `cap_window_start` without `cap_units`; every chain built here obeys all three. `UsageDebt.job_id` is nullable. Seat grants never repay the student's own debt (R13). `UsageJob.charged`/`debt_created` start at `0`.
- `lemely/db/models/billing.py` (phase 02): `CreditPack(code unique, name, units, price_minor, currency, is_active)`, CHECK `price_minor >= 0` (R11); `SubscriptionStatus.past_due` added to the existing enum in `lemely/db/models/enums.py`.
- `lemely/db/models/team.py` (phase 03): `TeacherMember(id, teacher_user_id, member_user_id, kind, scope_subjects, scope_actions, role_preset, permissions, cap_units, cap_period NOT NULL, status, leaves_at, created_at)`, `TeacherMemberKind`, `TeacherMemberStatus`, `CapPeriod`, `AssistantRole`.
- `lemely/web/deps.py` (phase 03): `ACTING_TEACHER_HEADER = "X-Lemely-Acting-Teacher"`, `TeamActor(actor_user_id, lead_teacher_user_id, member_id, auth)` where `auth` is the lead's `AuthContext` (role `teacher`) for an assistant, else the caller's own; `require_team_permission(perm, *roles)`; `get_teacher_team_store()` (tests override with `TeacherTeamStore(sm)`). Phase 03 replaces the `auth` parameter of `upload_paper`, `regrade_paper`, `quiz_preview` and `quiz_generate` with `actor: Annotated[TeamActor, Depends(_TEAM_MARK | _TEAM_REGRADE | _TEAM_QUIZ)]`.
- `lemely/core/metered_actions.py` (phase 03, R12): `MeteredAction` with the six base values, `has_subject`, `seat_eligible`, `SEAT_ACTIONS`. Task 1 only extends it.

## Contract deviations

1. **Cost hook location.** The index says to call `record_llm_cost` at "`lemely/io/llm/pricing.py` call sites". `row_cost` is called only inside `lemely/io/gemini.py`, by `price_call` and `_row_cost`, and both are called from `GeminiClient._record_spend`. That method is the single accounting path for Gemini and Claude replies (`ClaudeProvider` returns `usage_as_gemini_response`). The hook goes there, once (Task 2), because calling it in `price_call` would double-count: `_record_spend` prices every call twice (today and `PRICE_DATE_2027`).
2. **`ChainContext` carries no "cap usage".** The index lists "cap usage" as a `ChainContext` input. Caps are applied by the phase 01 ledger from `Payer.cap_units`/`cap_window_start` (spec §5.6: a cap counts settled entries plus open holds). Passing pre-computed usage into the pure chain as well would count it twice. `ChainContext` instead carries `debtors` and `study_plan_generated_this_week`, which the debt rule and the study-plan rule need.
3. **`require_usage` gains optional `target` and `team`.** The signature is `require_usage(action, *, target=None, team=None)`. `team` is the route's own `require_team_permission(...)` guard, so an assistant is billed to the lead (R4). `target` is a FastAPI dependency that returns a `UsageTarget(subject_code, input_count)` read on the server. Without it, `require_usage` could not know the subject or the input count, both of which spec §5.7 says the server must compute. Routes whose subject or inputs come from the request body or the stored record call `UsageMeter.authorize` imperatively instead (`require_usage` is a thin wrapper over it).
4. **Routes live under `/api`.** `POST /api/usage/estimate`, `GET /api/usage/meter`, `GET /api/usage/history`. Every router in `lemely/web/routers/` uses the `/api` prefix, and the authz matrix test enumerates paths with it.
5. **Marking estimates use `input_kind = "none"`, not `"pages"`.** `teacher_papers` has no page count, and `uploads.page_count` is never written. Counting pages means opening an untrusted PDF, which only the sandbox worker may do (#260, `lemely/web/upload_utils.py`). It would also need a sandbox target change and a column (phase 04 has no migration). `mark_paper` and `regrade` are seeded with a flat per-paper range, which admins tune from observed costs (spec §4.1). `usage_estimators.input_kind` is data, so a later phase that stores page counts switches the row without code changes.
6. **Catalogue defaults without a migration.** Production reference data in this repo comes from migrations (subjects come from `0024`; `lemely/db/seed.py` is dev-only), but the index gives phase 04 no migration. `ensure_usage_catalogue` inserts the version-1 `usage_rates` and `usage_estimators` rows for every `MeteredAction`, plus the two signup packs, with `ON CONFLICT DO NOTHING`. It runs lazily the first time a lookup finds no row, and also from `seed_reference_data`. Rows that admins add (higher versions) always win.
7. **Signup amounts live in `credit_packs` (confirmed by R11).** They are stored as rows with codes `signup_student` and `signup_teacher`, `is_active = false` and `price_minor = 0`. Phase 02's CHECK allows `price_minor >= 0`, and its public catalogue lists active packs only. Setting `units = 0` disables a signup grant.
8. **`MeteredAction` gains `mark_quiz` and `generate_flashcards` (R12).** Phase 03 owns the enum, `has_subject`, `seat_eligible` and `SEAT_ACTIONS`. Task 1 adds the two values, both with a subject and both seat-eligible, and adds the metering-only catalogue (`ActionSpec`, `ACTION_SPECS`, `UsageTarget`) beside them.
9. **Assistant billing (R4).** Assistant work is always charged to the lead teacher. The four teacher routes (upload, regrade, quiz preview, quiz generate) read Phase 03's `TeamActor`. `request_from_team(actor, action)` builds the request with `assistant_member_id = actor.member_id`, so the chain is the lead's allowance, then the lead's credits, within the assistant's cap. The assistant's own balance never pays for team work (tested in Tasks 6 and 10). The estimate route resolves the assistant from the `X-Lemely-Acting-Teacher` header through phase 03's `assistant_has_permission` with the permission the action's route needs (`mark_paper`→`mark`, `regrade`→`regrade`, `preview_quiz`/`generate_quiz`→`generate_quiz`). Other actions, and assistants without the permission, get the same 403 `team_permission_denied` as the routes.
10. **`platform_admin` is exempt from metering.** It has no plan and is not a customer. Exempt jobs make no ledger rows. Their cost is still logged (`usage_unmetered_cost`). `school_admin` is metered like "anyone else" (spec §2.8: school billing is out of scope).
11. **`UsageSettings.enforce` (R5).** A new settings group, `[usage]`, holds one flag, `enforce`, which defaults to `true` in `Settings`. Only `tests/conftest.py` turns it off (`LEMELY_USAGE__ENFORCE=0`), so the roughly 400 existing route tests need no ledger. Task 6 tests that default settings enforce and that the app's `get_usage_meter` built from them is enforcing.
12. **Post-settle hook registry is defined here (Task 6), not in phase 06.** `MeteredJob._finish` is the single settle point. It calls `run_post_settle_hooks(session, settled_job, payers, now)` in the settle's transaction. Phase 06 Task 7 then only registers `auto_topup_post_settle_hook` in `create_app`. The registry names and signatures are exactly the ones in plan 06 Task 7 (`PostSettleHook`, `register_post_settle_hook`, `clear_post_settle_hooks`, `run_post_settle_hooks`, `_POST_SETTLE_HOOKS`).

---

## Audit: every LLM-backed web route

Method: every router in `lemely/web/routers/` was read for dependencies on `get_gemini_client`, and for services constructed with a `GeminiClient`: `get_self_review_service`, `get_flashcard_service`, `get_quiz_marking_service`. Every `lemely/io` module that calls `generate_structured` was traced to its importers. Non-web callers (`lemely/app/cli.py`, `lemely/app/gradio_app.py`, `lemely/eval`, `lemely/accuracy`) are out of scope: they are operator tools with their own `script_cost_scope`.

| # | Route (file:line at `8d388747`+docs) | LLM work | `MeteredAction` | Subject source (server-side) | Estimate input | Runs in |
|---|---|---|---|---|---|---|
| 1 | `POST /api/student/correct` (`lemely/web/routers/student.py:954`) | scan metadata, scheme resolve, extraction, marking, adjudication, re-read | `mark_paper` | `ExamMetadata.subject_code` detected from the scan inside the job (`job.bind_subject`); `None` when detection is off or fails | none (flat) | SSE `bus_event_stream` worker thread (bare `threading.Thread`) |
| 2 | `POST /api/papers/upload` (`lemely/web/routers/teacher.py:879`) | the same pipeline, via `_run_grading_job` | `mark_paper` | not used (teacher chain has no seat) | none | `_grading_pool` thread |
| 3 | `POST /api/papers/{paper_id}/regrade` (`teacher.py:1028`) | the same pipeline | `regrade` | not used; an assistant's lead comes from `TeamActor` | none | `_grading_pool` thread |
| 4 | `POST /api/quizzes/preview` (`teacher.py:1732`) | `QuestionGenerator` via `TeacherQuizBuilder` | `preview_quiz` | not used | `count` query, clamped to 0..50 | request thread |
| 5 | `POST /api/quizzes/generate` (`teacher.py:1768`) | the same, plus bank write | `generate_quiz` | not used | `count` query, clamped | request thread |
| 6 | `POST /api/student/attempts/{attempt_id}/questions/{question_result_id}/self-review` (`student_self_review.py:294`) | `GeminiEvidenceJudge`, only for points that carry evidence | `self_review` (metered only when a point carries evidence) | `attempts.subject_code` of the caller's own attempt | `marks` = count of `question_result_points` | request thread |
| 7 | `POST /api/student/flashcards/decks/generate` (`flashcards.py:218`) | `FlashcardGenerator` | `generate_flashcards` | the deck being created (`body.subjectCode`, stored on the deck) | `questions` = `body.count` (schema bounds 1..50) | request thread |
| 8 | `POST /api/student/quizzes/{assignment_id}/submit` (`quiz.py:875`); covers placement, practice and teacher-assigned quizzes (all submit here) | `QuizMarkingService.mark_submission` (marking and integrity) | `mark_quiz` | `quizzes.subject_code` via `quiz_assignments` | `questions` = included `quiz_questions` | fire-and-forget `threading.Thread` |
| 9 | `POST /api/student/study-plan` (`study_plan.py:112`) | none today (deterministic scheduler; `StudyPlanNarrator` is CLI-only) | `study_plan` | the plan being created (`body.subjectCode`) | none; seeded estimate 0–0, so it settles 0 units | request thread |

Checked and **not** LLM-backed: `POST /api/student/uploads` (storage only), `POST /api/schemes` (deterministic parser in the sandbox), `POST /api/placement`, `POST /api/practice`, `POST /api/review/*`, `POST /api/tutor/profile/evidence`, every GET route.

Thread propagation (Task 2 adds the architecture test that keeps it true): every `pool.submit` in `lemely/io` already passes `contextvars.copy_context().run` (`answer_extraction.py:875`, `binding/chunked_read.py:292`, `binding/orchestrate.py:494-495`, `gemini.py:949`, `gemini.py:1131`). The two `pool.map` sites make no priced call: `llm/image_fit.py` does CPU-only image fitting, and `llm/claude_uploads.py` uploads to the Files API, which is not billed per token. The three web-level thread hops (SSE worker, grading pool, quiz marking thread) do not copy context, so the metered job opens its cost scope *inside* the worker (`with job.run():`), never in the request.

## File structure

| File | Status | Responsibility |
|---|---|---|
| `lemely/core/metered_actions.py` | extend (phase 03 owns it) | two new `MeteredAction` values; `ActionSpec`, `ACTION_SPECS`, `UsageTarget`, `JOB_SLACK`, `MAX_ESTIMATE_INPUTS`, `clamp_inputs` |
| `lemely/core/payer_chain.py` | create | pure chain builder and block-reason classifier (spec §5.6) |
| `lemely/io/llm/cost_meter.py` | create | `CostAccumulator`, `cost_scope`, `record_llm_cost`, `usd_decimal` |
| `lemely/io/gemini.py` | modify | one `record_llm_cost` call in `_record_spend` |
| `lemely/db/usage_catalogue_repo.py` | create | default rate, estimator and signup rows; current estimator and rate lookup; signup grant |
| `lemely/db/usage_context_repo.py` | create | DB facts for the chain, block facts, server-side targets, team lookup |
| `lemely/db/usage_views_repo.py` | create | meter view and history page queries |
| `lemely/db/seed.py` | modify | `seed_reference_data` also ensures the usage catalogue |
| `lemely/auth/mirror.py` | modify | `mark_email_verified` issues the signup grant on the first verification |
| `lemely/runtime/config.py` | modify | `UsageSettings`, `Settings.usage` |
| `lemely/web/usage.py` | create | `UsageBlocked`, handler, `UsageRequest`, `UsageGrantContext`, `MeteredJob`, `UsageMeter`, `get_usage_meter`, `require_usage`, `request_from_auth` |
| `lemely/web/schemas_usage.py` | create | DTOs for the usage routes |
| `lemely/web/routers/usage.py` | create | estimate, meter and history routes |
| `lemely/web/usage_sweeps.py` | create | `usage.expire_stale_jobs`, `usage.expire_grants`, `usage.reconcile_balances` |
| `lemely/web/app.py` | modify | include the usage router, register the 402 handler |
| `lemely/web/scheduled_notifications.py` | modify | `Sweeper` runs the usage jobs |
| `lemely/web/deps.py` | modify | `get_sweeper` turns usage jobs on |
| `lemely/web/routers/student.py`, `teacher.py`, `quiz.py`, `student_self_review.py`, `flashcards.py`, `study_plan.py` | modify | metering wired into each audited route |
| `pyproject.toml` | modify | import-linter contract for the pure metering modules |
| `tests/conftest.py` | modify | suite-wide `LEMELY_USAGE__ENFORCE=0` |
| `tests/usage_helpers.py` | create | shared seeding for the metering tests |

---

### Task 1: Extend the metered actions from the audit

**Files:**
- Modify: `lemely/core/metered_actions.py` (created by phase 03; extend only)
- Modify: `pyproject.toml` (append one import-linter contract after the "Tutoring pure rules stay pure" contract)
- Modify: `tests/test_metered_actions.py` (phase 03's file; append tests)

**Interfaces:**
- Consumes (phase 03, R12): `MeteredAction` (six base values), `MeteredAction.has_subject`, `MeteredAction.seat_eligible`, `SEAT_ACTIONS: frozenset[MeteredAction]`, plus whatever helpers phase 03 exports (`seat_scopable_actions`, `default_seat_actions`, `SEAT_ACTIONS_OFF_BY_DEFAULT`), all kept unchanged. `lemely.core.usage_types.EstimatorParams` (phase 01).
- Produces: two new members, `MeteredAction.MARK_QUIZ = "mark_quiz"` and `MeteredAction.GENERATE_FLASHCARDS = "generate_flashcards"`, both with `has_subject` and `seat_eligible` true and so in `SEAT_ACTIONS`. Also `ActionSpec(job_timeout: timedelta, default_estimator: EstimatorParams, default_units_per_usd: int)`, `ACTION_SPECS: Mapping[MeteredAction, ActionSpec]`, `UsageTarget(subject_code: str | None, input_count: int)`, `DEFAULT_UNITS_PER_USD = 1000`, `JOB_SLACK = timedelta(minutes=10)`, `MAX_ESTIMATE_INPUTS = 50` and `clamp_inputs(count: int) -> int`. Later tasks read seat eligibility only through `action in SEAT_ACTIONS` and the subject flag only through `action.has_subject`.

- [ ] **Step 1: Read phase 03's module**

Run: `sed -n '1,200p' lemely/core/metered_actions.py` and `grep -rn "metered_actions import" lemely tests`.
Note how phase 03 marks a value subject-less (for example a `_SUBJECTLESS` set) and how it marks a value not seat-eligible (for example a teacher-only set). The two new values must be in neither. Every name phase 03 exports and every importer must keep working.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_metered_actions.py`:

```python
# Billing phase 04, Task 1: the audit's extra actions and the metering catalogue.
from datetime import timedelta

from lemely.core.metered_actions import (
    ACTION_SPECS,
    DEFAULT_UNITS_PER_USD,
    JOB_SLACK,
    MAX_ESTIMATE_INPUTS,
    SEAT_ACTIONS,
    MeteredAction,
    UsageTarget,
    clamp_inputs,
)


def test_the_audited_actions_are_exactly_the_enum() -> None:
    assert {a.value for a in MeteredAction} == {
        "mark_paper",
        "regrade",
        "generate_quiz",
        "preview_quiz",
        "self_review",
        "study_plan",
        "mark_quiz",
        "generate_flashcards",
    }


def test_the_new_actions_have_a_subject_and_can_sit_in_a_seat_scope() -> None:
    for action in (MeteredAction.MARK_QUIZ, MeteredAction.GENERATE_FLASHCARDS):
        assert action.has_subject
        assert action.seat_eligible
        assert action in SEAT_ACTIONS


def test_teacher_only_actions_are_not_seat_eligible() -> None:
    teacher_only = {MeteredAction.REGRADE, MeteredAction.PREVIEW_QUIZ, MeteredAction.GENERATE_QUIZ}
    assert not (teacher_only & SEAT_ACTIONS)


def test_every_action_has_a_metering_spec() -> None:
    assert set(ACTION_SPECS) == set(MeteredAction)
    for action, spec in ACTION_SPECS.items():
        est = spec.default_estimator
        assert est.version == 1, action
        assert est.input_kind in {"pages", "marks", "questions", "none"}, action
        assert 0 <= est.base_low <= est.base_high, action
        assert 0 <= est.per_input_low <= est.per_input_high, action
        assert spec.default_units_per_usd == DEFAULT_UNITS_PER_USD, action
        assert spec.job_timeout > timedelta(0), action


def test_marking_uses_a_flat_estimate_because_page_counts_are_not_stored() -> None:
    for action in (MeteredAction.MARK_PAPER, MeteredAction.REGRADE):
        est = ACTION_SPECS[action].default_estimator
        assert est.input_kind == "none"
        assert (est.base_low, est.base_high) == (40, 120)


def test_study_plans_are_metered_at_zero_today() -> None:
    est = ACTION_SPECS[MeteredAction.STUDY_PLAN].default_estimator
    assert (est.base_low, est.base_high, est.per_input_high) == (0, 0, 0)


def test_clamp_inputs_bounds_the_hold_not_the_charge() -> None:
    assert clamp_inputs(-3) == 0
    assert clamp_inputs(7) == 7
    assert clamp_inputs(10_000) == MAX_ESTIMATE_INPUTS


def test_job_slack_and_target_shape() -> None:
    assert JOB_SLACK == timedelta(minutes=10)
    assert UsageTarget(subject_code="0580", input_count=3).input_count == 3
```

Move the two new imports to the file's import block when appending (ruff `E402`); merge with phase 03's existing `from lemely.core.metered_actions import (...)`.

- [ ] **Step 3: Run the test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_metered_actions.py -v --no-cov`
Expected: FAIL with `ImportError: cannot import name 'ACTION_SPECS'`.

- [ ] **Step 4: Extend the module**

In `lemely/core/metered_actions.py`, add two members at the end of `MeteredAction`:

```python
    MARK_QUIZ = "mark_quiz"
    GENERATE_FLASHCARDS = "generate_flashcards"
```

Phase 03's `SEAT_ACTIONS` is `{mark_paper, self_review, study_plan}`. Both new values are seat-eligible (decision: a student runs both, on a quiz or deck that carries a subject, so a seat may cover them), which makes `SEAT_ACTIONS` five values. Set `has_subject` and `seat_eligible` true for them through phase 03's own mechanism. For example, add them to its seat-eligible set, or leave them out of its subject-less and teacher-only sets, whichever form phase 03 uses. Do not drop or rename `has_subject`, `seat_eligible`, `SEAT_ACTIONS` or any phase 03 helper.

Append below phase 03's definitions:

```python
# --- Billing phase 04: how each action is metered (spec §4.1, §5.7) -----------------

from dataclasses import dataclass  # noqa: E402 - kept with the metering block
from datetime import timedelta  # noqa: E402
from types import MappingProxyType  # noqa: E402

from lemely.core.usage_types import EstimatorParams  # noqa: E402


@dataclass(frozen=True)
class ActionSpec:
    """How one action is metered. ``default_*`` seed version 1 of the admin catalogue."""

    job_timeout: timedelta
    default_estimator: EstimatorParams
    default_units_per_usd: int


@dataclass(frozen=True)
class UsageTarget:
    """What the server read off the record an action works on. Never client input."""

    subject_code: str | None
    input_count: int


#: 1 unit = USD 0.001 at the seeded rate. Admins add new rate versions (spec §4.1).
DEFAULT_UNITS_PER_USD = 1000
#: Added to an action's timeout to form ``usage_jobs.expires_at`` (spec §5.7 step 3).
JOB_SLACK = timedelta(minutes=10)
#: Upper bound on countable inputs fed to an estimate. A larger request is still charged
#: its actual cost; the bound only stops a huge ``count`` inflating the hold.
MAX_ESTIMATE_INPUTS = 50


def _estimator(
    input_kind: str, base_low: int, base_high: int, per_low: int = 0, per_high: int = 0
) -> EstimatorParams:
    return EstimatorParams(
        version=1,
        input_kind=input_kind,
        base_low=base_low,
        base_high=base_high,
        per_input_low=per_low,
        per_input_high=per_high,
    )


def _spec(minutes: int, estimator: EstimatorParams) -> ActionSpec:
    return ActionSpec(
        job_timeout=timedelta(minutes=minutes),
        default_estimator=estimator,
        default_units_per_usd=DEFAULT_UNITS_PER_USD,
    )


ACTION_SPECS = MappingProxyType(
    {
        # Flat per paper: page counts are not stored (plan deviation 5, R16). 40-120 units
        # brackets the USD 0.10/paper target at 1000 units per USD. 45 minutes covers the
        # grading pool's queue wait.
        MeteredAction.MARK_PAPER: _spec(45, _estimator("none", 40, 120)),
        MeteredAction.REGRADE: _spec(45, _estimator("none", 40, 120)),
        MeteredAction.GENERATE_QUIZ: _spec(10, _estimator("questions", 2, 4, 2, 5)),
        MeteredAction.PREVIEW_QUIZ: _spec(10, _estimator("questions", 2, 4, 2, 5)),
        MeteredAction.SELF_REVIEW: _spec(5, _estimator("marks", 1, 2, 0, 1)),
        # Deterministic today (no model call), so it settles 0 units; metered so the seat
        # rule (§2.2) and any future narrator are covered.
        MeteredAction.STUDY_PLAN: _spec(2, _estimator("none", 0, 0)),
        MeteredAction.MARK_QUIZ: _spec(15, _estimator("questions", 1, 2, 1, 3)),
        MeteredAction.GENERATE_FLASHCARDS: _spec(5, _estimator("questions", 2, 4, 1, 2)),
    }
)
"""Every action's metering spec, keyed by action (``Mapping[MeteredAction, ActionSpec]``)."""


def clamp_inputs(count: int) -> int:
    """``count`` bounded to ``0..MAX_ESTIMATE_INPUTS`` for an estimate."""
    return max(0, min(count, MAX_ESTIMATE_INPUTS))
```

Move these imports up to the module's import block instead (and drop the `noqa` comments) if phase 03's module has a normal import block; the `noqa` form is only for appending below code. Add `"ACTION_SPECS"`, `"ActionSpec"`, `"UsageTarget"`, `"DEFAULT_UNITS_PER_USD"`, `"JOB_SLACK"`, `"MAX_ESTIMATE_INPUTS"`, `"clamp_inputs"` to `__all__`.

- [ ] **Step 5: Add the purity contract**

Append to `pyproject.toml` directly after the `"Tutoring pure rules stay pure (SPEC §e.1)"` contract block:

```toml
[[tool.importlinter.contracts]]
name = "Metering pure rules stay pure (billing spec §5.6)"
type = "forbidden"
source_modules = ["lemely.core.metered_actions"]
forbidden_modules = [
  "lemely.db",
  "lemely.web",
  "lemely.io",
  "lemely.app",
  "sqlalchemy",
  "fastapi",
]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_metered_actions.py tests/test_team_permissions.py tests/architecture/ -v --no-cov`
Expected: PASS. Phase 03's existing tests in `tests/test_metered_actions.py` still pass. If one pinned the enum at exactly six values, update it to the eight above; that is the intended change.

- [ ] **Step 7: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/core/metered_actions.py pyproject.toml tests/test_metered_actions.py
git commit -S -m "feat(usage): metered actions from the LLM route audit" -- lemely/core/metered_actions.py pyproject.toml tests/test_metered_actions.py
```

---

### Task 2: Provider-agnostic LLM cost accumulator

**Files:**
- Create: `lemely/io/llm/cost_meter.py`
- Modify: `lemely/io/gemini.py`: import, and one call in `GeminiClient._record_spend` directly after `usd_rounded = round(usd, 6)`
- Test: `tests/test_cost_meter.py`, `tests/architecture/test_llm_threads_copy_context.py`

**Interfaces:**
- Consumes: `GeminiClient._record_spend` (existing; the single accounting path for Gemini and Claude replies).
- Produces: `CostAccumulator` (`add(cost_usd: Decimal) -> None`, properties `total_usd: Decimal`, `calls: int`); `cost_scope() -> ContextManager[CostAccumulator]`; `record_llm_cost(cost_usd: Decimal) -> None`; `usd_decimal(value: float) -> Decimal` (rounded up to 6 dp).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cost_meter.py
"""The per-job LLM cost accumulator (billing spec §5.7 step 4)."""

from __future__ import annotations

import contextvars
import tempfile
import threading
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from lemely.core.schemas import AIMarkResponse
from lemely.io import gemini
from lemely.io.gemini import GeminiClient, _reset_process_counters
from lemely.io.llm.cost_meter import cost_scope, record_llm_cost, usd_decimal
from tests.gemini_fakes import fake_genai_client, make_settings, mock_response
from tests.test_anthropic_adapter import _VALID_MARK, _FakeAnthropic, _message, _settings


class _Reply(BaseModel):
    value: str


def test_scope_sums_every_recorded_cost() -> None:
    with cost_scope() as acc:
        record_llm_cost(Decimal("0.010000"))
        record_llm_cost(Decimal("0.002500"))
    assert acc.total_usd == Decimal("0.012500")
    assert acc.calls == 2


def test_no_scope_records_nothing_and_does_not_raise() -> None:
    record_llm_cost(Decimal("1"))
    with cost_scope() as acc:
        pass
    assert acc.total_usd == Decimal(0)


def test_inner_scope_shadows_the_outer() -> None:
    with cost_scope() as outer:
        record_llm_cost(Decimal("0.1"))
        with cost_scope() as inner:
            record_llm_cost(Decimal("0.2"))
    assert outer.total_usd == Decimal("0.1")
    assert inner.total_usd == Decimal("0.2")


def test_copied_context_threads_feed_the_same_scope() -> None:
    with cost_scope() as acc:
        ctx = contextvars.copy_context()
        worker = threading.Thread(target=ctx.run, args=(record_llm_cost, Decimal("0.3")))
        worker.start()
        worker.join()
    assert acc.total_usd == Decimal("0.3")


def test_a_bare_thread_does_not_see_the_scope() -> None:
    with cost_scope() as acc:
        worker = threading.Thread(target=record_llm_cost, args=(Decimal("0.3"),))
        worker.start()
        worker.join()
    assert acc.total_usd == Decimal(0)


def test_negative_cost_is_refused() -> None:
    with cost_scope(), pytest.raises(ValueError, match="negative"):
        record_llm_cost(Decimal("-0.01"))


def test_usd_decimal_rounds_up_to_micro_dollars() -> None:
    assert usd_decimal(0.0002) == Decimal("0.000200")
    assert usd_decimal(0.0000001) == Decimal("0.000001")
    assert usd_decimal(0.0) == Decimal("0.000000")
    with pytest.raises(ValueError, match="not a USD cost"):
        usd_decimal(float("nan"))


def test_gemini_calls_feed_the_scope() -> None:
    _reset_process_counters()
    with patch("lemely.io.gemini._today", lambda: date(2026, 10, 19)):
        genai = fake_genai_client()
        genai.models.generate_content.side_effect = [
            mock_response('{"value": "a"}', prompt=10_000, candidates=1_000)
        ]
        client = GeminiClient(make_settings(tempfile.mkdtemp()), _genai_client=genai, ledger=None)
        with cost_scope() as acc:
            client.generate_structured(
                system_prompt="s",
                user_prompt="u",
                response_schema=_Reply,
                prompt_version="v1",
                model="gemini-3.8-flash",
                task_tag="extraction",
            )
    assert acc.calls == 1
    assert acc.total_usd == usd_decimal(gemini._process_accumulated_usd)
    assert acc.total_usd > 0


def test_claude_calls_feed_the_scope() -> None:
    _reset_process_counters()
    with patch("lemely.io.gemini._today", lambda: date(2026, 10, 19)):
        fake = _FakeAnthropic(_message(_VALID_MARK, input_tokens=1_000, output_tokens=200))
        client = GeminiClient(
            _settings(tempfile.mkdtemp()), _genai_client=object(), _anthropic_client=fake, ledger=None
        )
        with cost_scope() as acc:
            client.generate_structured(
                system_prompt="s",
                user_prompt="read",
                response_schema=AIMarkResponse,
                prompt_version="v1",
                model="claude-haiku-5-5",
                task_tag="correction",
            )
    # 1,000 in x 0.0001/1k + 200 out x 0.0005/1k (lemely/io/llm/pricing.py).
    assert acc.total_usd == Decimal("0.000200")
    assert acc.calls == 1
```

```python
# tests/architecture/test_llm_threads_copy_context.py
"""Every worker thread under lemely/io runs in a copied context (billing spec §5.7).

The usage meter's cost accumulator is a contextvar. A pool task submitted without
``contextvars.copy_context().run`` would make its model calls outside the job's scope, and
that cost would never be charged. This scans the source, so a new pool fails here first.
"""

from __future__ import annotations

import ast
from pathlib import Path

_IO = Path(__file__).resolve().parents[2] / "lemely" / "io"

#: ``pool.map`` call sites whose workers make no priced model call, with the reason.
_MAP_ALLOWED = {
    "llm/image_fit.py": "CPU-only image fitting",
    "llm/claude_uploads.py": "Files API uploads are not billed per token",
}


def _calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)]


def _is_copied_run(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "run"
        and isinstance(node.value, ast.Call)
        and getattr(node.value.func, "attr", None) == "copy_context"
    )


def test_every_pool_submit_copies_the_context() -> None:
    offenders = []
    for path in sorted(_IO.rglob("*.py")):
        for call in _calls(path):
            func = call.func
            if isinstance(func, ast.Attribute) and func.attr == "submit":
                if not call.args or not _is_copied_run(call.args[0]):
                    offenders.append(f"{path.relative_to(_IO)}:{call.lineno}")
    assert offenders == []


def test_pool_map_only_where_no_model_call_runs() -> None:
    found = set()
    for path in sorted(_IO.rglob("*.py")):
        for call in _calls(path):
            func = call.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "map"
                and getattr(func.value, "id", None) == "pool"
            ):
                found.add(path.relative_to(_IO).as_posix())
    assert found <= set(_MAP_ALLOWED), found - set(_MAP_ALLOWED)


def test_no_bare_threads_under_io() -> None:
    offenders = []
    for path in sorted(_IO.rglob("*.py")):
        for call in _calls(path):
            func = call.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name == "Thread":
                offenders.append(f"{path.relative_to(_IO)}:{call.lineno}")
    assert offenders == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_cost_meter.py tests/architecture/test_llm_threads_copy_context.py -v --no-cov`
Expected: `test_cost_meter.py` fails with `ModuleNotFoundError: No module named 'lemely.io.llm.cost_meter'`. The architecture file passes already (it pins today's state; prove it can fail by temporarily replacing `contextvars.copy_context().run, _one, index` with `_one, index` in `lemely/io/answer_extraction.py:875`, seeing `test_every_pool_submit_copies_the_context` go red, then reverting).

- [ ] **Step 3: Write the accumulator**

```python
# lemely/io/llm/cost_meter.py
"""Per-job LLM cost accumulator (billing spec §5.7 step 4).

``UsageMeter`` opens :func:`cost_scope` around a metered job. ``GeminiClient._record_spend``
(the one accounting path both providers reply through) calls :func:`record_llm_cost` with
each call's USD price. The scope is a contextvar holding a mutable, locked accumulator:
threads started under ``contextvars.copy_context().run`` share it (every pool under
``lemely/io`` does, pinned by ``tests/architecture/test_llm_threads_copy_context.py``); a
bare ``threading.Thread`` does not, which is why the web layer opens the scope inside the
worker thread, never in the request.

An inner scope shadows an outer one. Nothing here raises for a missing scope.
"""

from __future__ import annotations

import contextlib
import contextvars
import math
import threading
from decimal import ROUND_CEILING, Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

_MICRO = Decimal("0.000001")


class CostAccumulator:
    """A thread-safe running total of USD spent on model calls."""

    __slots__ = ("_calls", "_lock", "_total")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total = Decimal(0)
        self._calls = 0

    def add(self, cost_usd: Decimal) -> None:
        """Add one call's cost. Refuses a negative or non-finite amount."""
        if not cost_usd.is_finite() or cost_usd < 0:
            raise ValueError(f"LLM cost must be finite and non-negative: {cost_usd!r}")
        with self._lock:
            self._total += cost_usd
            self._calls += 1

    @property
    def total_usd(self) -> Decimal:
        with self._lock:
            return self._total

    @property
    def calls(self) -> int:
        with self._lock:
            return self._calls


_current: contextvars.ContextVar[CostAccumulator | None] = contextvars.ContextVar(
    "lemely_llm_cost", default=None
)


@contextlib.contextmanager
def cost_scope() -> Iterator[CostAccumulator]:
    """Collect every :func:`record_llm_cost` made in this context until exit."""
    accumulator = CostAccumulator()
    token = _current.set(accumulator)
    try:
        yield accumulator
    finally:
        _current.reset(token)


def record_llm_cost(cost_usd: Decimal) -> None:
    """Add ``cost_usd`` to the innermost open scope; a no-op outside any scope."""
    accumulator = _current.get()
    if accumulator is not None:
        accumulator.add(cost_usd)


def usd_decimal(value: float) -> Decimal:
    """``value`` USD as a Decimal rounded up to whole micro-dollars (``NUMERIC(12, 6)``).

    Rounded up so the total charged is never below the total spent.
    """
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"not a USD cost: {value!r}")
    return Decimal(repr(value)).quantize(_MICRO, rounding=ROUND_CEILING)
```

The test `test_negative_cost_is_refused` matches `"negative"` against the message above (`"...finite and non-negative..."`).

- [ ] **Step 4: Feed it from `_record_spend`**

In `lemely/io/gemini.py`, add to the imports beside `from lemely.io.llm.pricing import PriceRow, claude_row, row_cost`:

```python
from lemely.io.llm.cost_meter import record_llm_cost, usd_decimal
```

In `GeminiClient._record_spend`, directly after the line `usd_rounded = round(usd, 6)`, insert:

```python
        # Billing spec §5.7 step 4: the open usage job (if any) is charged this call.
        # `usd` is today's price, including an explicit cache's storage, and the
        # warn-and-fall-back price for an unpriced model, never the NaN record value.
        record_llm_cost(usd_decimal(usd))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_cost_meter.py tests/architecture/ tests/test_script_cost_scope.py -v --no-cov`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/io/llm/cost_meter.py lemely/io/gemini.py tests/test_cost_meter.py tests/architecture/test_llm_threads_copy_context.py
git commit -S -m "feat(usage): contextvar LLM cost accumulator fed by both providers" -- lemely/io/llm/cost_meter.py lemely/io/gemini.py tests/test_cost_meter.py tests/architecture/test_llm_threads_copy_context.py
```

---

### Task 3: Pure payer chain and block reasons

**Files:**
- Create: `lemely/core/payer_chain.py`
- Modify: `pyproject.toml` (add `"lemely.core.payer_chain"` to the `source_modules` of the "Metering pure rules stay pure" contract from Task 1)
- Test: `tests/test_payer_chain.py`

**Interfaces:**
- Consumes: `Payer`, `GrantScope` (phase 01); `MeteredAction`, `SEAT_ACTIONS` (phase 03, extended in Task 1).
- Produces:
  - `SeatView(member_id: UUID, teacher_user_id: UUID, scope_subjects: frozenset[str], scope_actions: frozenset[str], cap_units: int | None, cap_period: str, created_at: datetime)`
  - `AssistantView(member_id: UUID, lead_teacher_user_id: UUID, cap_units: int | None, cap_period: str)`
  - `ChainContext(actor_user_id: UUID, action: MeteredAction, subject_code: str | None, now: datetime, seats: tuple[SeatView, ...] = (), assistant: AssistantView | None = None, debtors: frozenset[UUID] = frozenset(), study_plan_generated_this_week: bool = False)`
  - `UsageBlockReason` StrEnum: `USAGE_LIMIT_REACHED="usage_limit_reached"`, `NO_ACTIVE_PLAN="no_active_plan"`, `INSUFFICIENT_CREDITS="insufficient_credits"`, `OUTSTANDING_DEBT="outstanding_debt"`, `OUT_OF_SEAT_SCOPE="out_of_seat_scope"`
  - `BlockFacts(last_resort_in_debt: bool, seat_scope_miss: bool, has_live_plan: bool, has_credit_grant: bool)`
  - `month_start(now: datetime) -> datetime`, `covering_seats(ctx) -> list[SeatView]`, `seat_scope_miss(ctx) -> bool`, `build_payer_chain(ctx) -> list[Payer]`, `job_teacher_member_id(chain: Sequence[Payer]) -> UUID | None`, `block_reason(facts: BlockFacts) -> UsageBlockReason`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_payer_chain.py
"""Spec §5.6: the payer chain, one test per table row and per rule beneath it."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from lemely.core.metered_actions import MeteredAction
from lemely.core.payer_chain import (
    AssistantView,
    BlockFacts,
    ChainContext,
    SeatView,
    UsageBlockReason,
    block_reason,
    build_payer_chain,
    covering_seats,
    job_teacher_member_id,
    month_start,
    seat_scope_miss,
)
from lemely.core.usage_types import GrantScope, Payer

NOW = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
STUDENT = uuid.UUID(int=1)
MATHS_T = uuid.UUID(int=2)
PHYS_T = uuid.UUID(int=3)
LEAD = uuid.UUID(int=4)
ASSIST = uuid.UUID(int=5)


def _seat(
    n: int,
    teacher: uuid.UUID,
    subjects: set[str],
    actions: set[MeteredAction],
    *,
    cap: int | None = 100,
    period: str = "month",
    age_days: int = 10,
) -> SeatView:
    return SeatView(
        member_id=uuid.UUID(int=100 + n),
        teacher_user_id=teacher,
        scope_subjects=frozenset(subjects),
        scope_actions=frozenset(a.value for a in actions),
        cap_units=cap,
        cap_period=period,
        created_at=NOW - timedelta(days=age_days),
    )


MATHS = _seat(1, MATHS_T, {"0580"}, {MeteredAction.MARK_PAPER, MeteredAction.STUDY_PLAN})
PHYS = _seat(2, PHYS_T, {"0625"}, {MeteredAction.MARK_PAPER})
OWN = [Payer(STUDENT, GrantScope.ALLOWANCE), Payer(STUDENT, GrantScope.CREDITS)]


def _ctx(**kw: object) -> ChainContext:
    base: dict[str, object] = {
        "actor_user_id": STUDENT,
        "action": MeteredAction.MARK_PAPER,
        "subject_code": "0580",
        "now": NOW,
    }
    base.update(kw)
    return ChainContext(**base)  # type: ignore[arg-type]


def _seat_payer(seat: SeatView) -> Payer:
    return Payer(STUDENT, GrantScope.SEAT, teacher_member_id=seat.member_id, debt_exempt=True)


def _teacher_credits(seat: SeatView) -> Payer:
    return Payer(
        seat.teacher_user_id,
        GrantScope.CREDITS,
        teacher_member_id=seat.member_id,
        cap_units=seat.cap_units,
        cap_window_start=month_start(NOW),
    )


def test_anyone_else_pays_own_allowance_then_own_credits() -> None:
    assert build_payer_chain(_ctx()) == OWN


def test_seated_in_scope_seat_then_teacher_credits_then_own() -> None:
    chain = build_payer_chain(_ctx(seats=(MATHS,)))
    assert chain == [_seat_payer(MATHS), _teacher_credits(MATHS), *OWN]


def test_a_seat_without_a_cap_never_overflows_into_teacher_credits() -> None:
    seat = _seat(3, MATHS_T, {"0580"}, {MeteredAction.MARK_PAPER}, cap=None)
    assert build_payer_chain(_ctx(seats=(seat,))) == [_seat_payer(seat), *OWN]


def test_a_total_cap_has_no_window() -> None:
    seat = _seat(4, MATHS_T, {"0580"}, {MeteredAction.MARK_PAPER}, period="total")
    chain = build_payer_chain(_ctx(seats=(seat,)))
    assert chain[1].cap_window_start is None
    assert chain[1].cap_units == 100


def test_seated_out_of_scope_action_uses_own_balance_only() -> None:
    ctx = _ctx(seats=(PHYS,), subject_code="0625", action=MeteredAction.SELF_REVIEW)
    assert build_payer_chain(ctx) == OWN
    assert seat_scope_miss(ctx) is True


def test_routing_is_per_subject() -> None:
    maths = build_payer_chain(_ctx(seats=(MATHS, PHYS), subject_code="0580"))
    physics = build_payer_chain(_ctx(seats=(MATHS, PHYS), subject_code="0625"))
    assert maths[0] == _seat_payer(MATHS)
    assert physics[0] == _seat_payer(PHYS)
    assert all(p.teacher_member_id != PHYS.member_id for p in maths)
    assert all(p.teacher_member_id != MATHS.member_id for p in physics)


def test_two_seats_on_one_subject_all_allowances_then_all_teacher_credits() -> None:
    older = _seat(5, MATHS_T, {"0580"}, {MeteredAction.MARK_PAPER}, age_days=30)
    newer = _seat(6, PHYS_T, {"0580"}, {MeteredAction.MARK_PAPER}, age_days=5)
    chain = build_payer_chain(_ctx(seats=(newer, older)))
    assert chain == [
        _seat_payer(older),
        _seat_payer(newer),
        _teacher_credits(older),
        _teacher_credits(newer),
        *OWN,
    ]
    assert covering_seats(_ctx(seats=(newer, older))) == [older, newer]


def test_a_subjectless_action_uses_no_seat() -> None:
    ctx = _ctx(seats=(MATHS,), subject_code=None)
    assert build_payer_chain(ctx) == OWN
    assert seat_scope_miss(ctx) is False


def test_teacher_only_actions_are_never_seat_paid() -> None:
    seat = _seat(7, MATHS_T, {"0580"}, {MeteredAction.REGRADE})
    assert build_payer_chain(_ctx(seats=(seat,), action=MeteredAction.REGRADE)) == OWN


def test_study_plan_first_generation_this_week_is_seat_paid() -> None:
    ctx = _ctx(seats=(MATHS,), action=MeteredAction.STUDY_PLAN)
    assert build_payer_chain(ctx)[0] == _seat_payer(MATHS)


def test_study_plan_regeneration_in_the_same_week_draws_own_balance() -> None:
    ctx = _ctx(
        seats=(MATHS,), action=MeteredAction.STUDY_PLAN, study_plan_generated_this_week=True
    )
    assert build_payer_chain(ctx) == OWN
    assert seat_scope_miss(ctx) is False


def test_study_plan_without_the_seat_action_draws_own_balance() -> None:
    ctx = _ctx(seats=(PHYS,), subject_code="0625", action=MeteredAction.STUDY_PLAN)
    assert build_payer_chain(ctx) == OWN


def test_assistant_draws_lead_allowance_then_lead_credits_within_its_cap() -> None:
    member = uuid.UUID(int=200)
    ctx = ChainContext(
        actor_user_id=ASSIST,
        action=MeteredAction.REGRADE,
        subject_code=None,
        now=NOW,
        assistant=AssistantView(member, LEAD, cap_units=500, cap_period="month"),
    )
    window = month_start(NOW)
    assert build_payer_chain(ctx) == [
        Payer(LEAD, GrantScope.ALLOWANCE, teacher_member_id=member, cap_units=500,
              cap_window_start=window),
        Payer(LEAD, GrantScope.CREDITS, teacher_member_id=member, cap_units=500,
              cap_window_start=window),
    ]
    assert job_teacher_member_id(build_payer_chain(ctx)) == member


def test_assistant_without_a_cap_is_unlimited_and_total_cap_has_no_window() -> None:
    member = uuid.UUID(int=201)
    unlimited = AssistantView(member, LEAD, cap_units=None, cap_period="month")
    total = AssistantView(member, LEAD, cap_units=50, cap_period="total")
    base = {"actor_user_id": ASSIST, "action": MeteredAction.REGRADE, "subject_code": None}
    a = build_payer_chain(ChainContext(now=NOW, assistant=unlimited, **base))  # type: ignore[arg-type]
    b = build_payer_chain(ChainContext(now=NOW, assistant=total, **base))  # type: ignore[arg-type]
    assert [p.cap_units for p in a] == [None, None]
    assert [p.cap_window_start for p in b] == [None, None]


def test_a_debtor_student_keeps_the_seat_and_stays_payer_of_last_resort() -> None:
    chain = build_payer_chain(_ctx(seats=(MATHS,), debtors=frozenset({STUDENT})))
    assert chain == [_seat_payer(MATHS), _teacher_credits(MATHS), OWN[1]]
    assert chain[-1].owner_user_id == STUDENT


def test_a_debtor_teacher_drops_out_of_the_overflow() -> None:
    chain = build_payer_chain(_ctx(seats=(MATHS,), debtors=frozenset({MATHS_T})))
    assert chain == [_seat_payer(MATHS), *OWN]


def test_a_non_seated_debtor_has_only_the_last_resort_payer() -> None:
    assert build_payer_chain(_ctx(debtors=frozenset({STUDENT}))) == [OWN[1]]


def test_job_teacher_member_id_is_the_first_seat_or_none() -> None:
    assert job_teacher_member_id(build_payer_chain(_ctx(seats=(MATHS,)))) == MATHS.member_id
    assert job_teacher_member_id(OWN) is None


def test_month_start_is_the_first_utc_instant_of_the_month() -> None:
    assert month_start(NOW) == datetime(2026, 11, 1, tzinfo=UTC)


def test_block_reason_precedence() -> None:
    def facts(**kw: bool) -> BlockFacts:
        base = {
            "last_resort_in_debt": False,
            "seat_scope_miss": False,
            "has_live_plan": False,
            "has_credit_grant": False,
        }
        base.update(kw)
        return BlockFacts(**base)

    assert block_reason(facts(last_resort_in_debt=True, seat_scope_miss=True)) is (
        UsageBlockReason.OUTSTANDING_DEBT
    )
    assert block_reason(facts(seat_scope_miss=True, has_credit_grant=True)) is (
        UsageBlockReason.OUT_OF_SEAT_SCOPE
    )
    assert block_reason(facts(has_credit_grant=True, has_live_plan=True)) is (
        UsageBlockReason.INSUFFICIENT_CREDITS
    )
    assert block_reason(facts(has_live_plan=True)) is UsageBlockReason.USAGE_LIMIT_REACHED
    assert block_reason(facts()) is UsageBlockReason.NO_ACTIVE_PLAN
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_payer_chain.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.core.payer_chain'`.

- [ ] **Step 3: Write the module**

```python
# lemely/core/payer_chain.py
"""The payer chain for one metered action (billing spec §5.6). Pure: no DB, no IO.

``lemely.db.usage_context_repo.load_chain_context`` reads the facts; this module turns
them into the ordered ``Payer`` list that ``UsageLedger.available``/``reserve``/``settle``
walk. The last payer is the payer of last resort: debt lands on its owner.

| Actor and action                          | Chain                                                   |
|-------------------------------------------|---------------------------------------------------------|
| Seated student, action in a seat's scope  | seat allowances (age order) -> those seats' teacher     |
|                                           | credits (same order, capped) -> own allowance -> own    |
|                                           | credits                                                 |
| Seated student, other action              | own allowance -> own credits                            |
| Assistant acting for a lead teacher       | lead allowance -> lead credits (capped by the row)      |
| Anyone else                               | own allowance -> own credits                            |

Debt rule: a payer whose owner has debt is dropped, except a seat payer (``debt_exempt``)
and the payer of last resort, which stays so debt still lands on the same owner. Keeping
it adds no spendable balance: every new grant repays debt first (§5.8), so a debtor's own
grants hold nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from lemely.core.metered_actions import SEAT_ACTIONS, MeteredAction
from lemely.core.usage_types import GrantScope, Payer

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence


@dataclass(frozen=True)
class SeatView:
    """One active or leaving ``student_seat`` row, as the chain needs it."""

    member_id: uuid.UUID
    teacher_user_id: uuid.UUID
    scope_subjects: frozenset[str]
    scope_actions: frozenset[str]
    cap_units: int | None
    cap_period: str
    created_at: datetime


@dataclass(frozen=True)
class AssistantView:
    """The active ``assistant`` row the actor acts under."""

    member_id: uuid.UUID
    lead_teacher_user_id: uuid.UUID
    cap_units: int | None
    cap_period: str


@dataclass(frozen=True)
class ChainContext:
    """Everything the chain depends on, read on the server for one action."""

    actor_user_id: uuid.UUID
    action: MeteredAction
    subject_code: str | None
    now: datetime
    seats: tuple[SeatView, ...] = ()
    assistant: AssistantView | None = None
    debtors: frozenset[uuid.UUID] = frozenset()
    study_plan_generated_this_week: bool = False


class UsageBlockReason(StrEnum):
    """The machine-readable ``reason`` in a 402 body."""

    USAGE_LIMIT_REACHED = "usage_limit_reached"
    NO_ACTIVE_PLAN = "no_active_plan"
    INSUFFICIENT_CREDITS = "insufficient_credits"
    OUTSTANDING_DEBT = "outstanding_debt"
    OUT_OF_SEAT_SCOPE = "out_of_seat_scope"


@dataclass(frozen=True)
class BlockFacts:
    """Why a chain could not cover an estimate. The funding owner is the lead for an
    assistant, else the actor."""

    last_resort_in_debt: bool
    seat_scope_miss: bool
    has_live_plan: bool
    has_credit_grant: bool


def month_start(now: datetime) -> datetime:
    """The first instant (UTC) of ``now``'s calendar month: a monthly cap's window."""
    moment = now.astimezone(UTC)
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _cap_window(cap_period: str, now: datetime) -> datetime | None:
    return month_start(now) if cap_period == "month" else None


def covering_seats(ctx: ChainContext) -> list[SeatView]:
    """The seats that pay for this action, oldest first (§5.6 seat selection)."""
    if ctx.subject_code is None or ctx.action not in SEAT_ACTIONS:
        return []
    if ctx.action is MeteredAction.STUDY_PLAN and ctx.study_plan_generated_this_week:
        return []
    seats = [
        seat
        for seat in ctx.seats
        if ctx.subject_code in seat.scope_subjects and ctx.action.value in seat.scope_actions
    ]
    return sorted(seats, key=lambda seat: (seat.created_at, str(seat.member_id)))


def seat_scope_miss(ctx: ChainContext) -> bool:
    """A seat covers the subject, but no seat on that subject covers the action."""
    if ctx.assistant is not None or ctx.subject_code is None:
        return False
    same_subject = [seat for seat in ctx.seats if ctx.subject_code in seat.scope_subjects]
    return bool(same_subject) and not any(
        ctx.action.value in seat.scope_actions for seat in same_subject
    )


def build_payer_chain(ctx: ChainContext) -> list[Payer]:
    """The ordered payers for ``ctx`` (module docstring table), debt rule applied."""
    if ctx.assistant is not None:
        assistant = ctx.assistant
        window = _cap_window(assistant.cap_period, ctx.now)
        chain = [
            Payer(
                owner_user_id=assistant.lead_teacher_user_id,
                scope=scope,
                teacher_member_id=assistant.member_id,
                cap_units=assistant.cap_units,
                cap_window_start=window if assistant.cap_units is not None else None,
            )
            for scope in (GrantScope.ALLOWANCE, GrantScope.CREDITS)
        ]
    else:
        seats = covering_seats(ctx)
        chain = [
            Payer(
                owner_user_id=ctx.actor_user_id,
                scope=GrantScope.SEAT,
                teacher_member_id=seat.member_id,
                debt_exempt=True,
            )
            for seat in seats
        ]
        chain += [
            Payer(
                owner_user_id=seat.teacher_user_id,
                scope=GrantScope.CREDITS,
                teacher_member_id=seat.member_id,
                cap_units=seat.cap_units,
                cap_window_start=_cap_window(seat.cap_period, ctx.now),
            )
            for seat in seats
            if seat.cap_units
        ]
        chain += [
            Payer(owner_user_id=ctx.actor_user_id, scope=GrantScope.ALLOWANCE),
            Payer(owner_user_id=ctx.actor_user_id, scope=GrantScope.CREDITS),
        ]
    last = chain[-1]
    kept = [p for p in chain[:-1] if p.debt_exempt or p.owner_user_id not in ctx.debtors]
    return [*kept, last]


def job_teacher_member_id(chain: Sequence[Payer]) -> uuid.UUID | None:
    """``usage_jobs.teacher_member_id``: the first seat or assistant row in the chain."""
    return next((p.teacher_member_id for p in chain if p.teacher_member_id is not None), None)


def block_reason(facts: BlockFacts) -> UsageBlockReason:
    """The one reason a 402 reports, most actionable first."""
    if facts.last_resort_in_debt:
        return UsageBlockReason.OUTSTANDING_DEBT
    if facts.seat_scope_miss:
        return UsageBlockReason.OUT_OF_SEAT_SCOPE
    if facts.has_credit_grant:
        return UsageBlockReason.INSUFFICIENT_CREDITS
    if facts.has_live_plan:
        return UsageBlockReason.USAGE_LIMIT_REACHED
    return UsageBlockReason.NO_ACTIVE_PLAN
```

Note the assistant-chain `cap_window_start` is `None` when `cap_units` is `None` (no cap means no window). The test `test_assistant_draws_lead_allowance_then_lead_credits_within_its_cap` expects the month window when the cap is set.

- [ ] **Step 4: Extend the purity contract**

In `pyproject.toml`, change the Task 1 contract's `source_modules` to:

```toml
source_modules = ["lemely.core.metered_actions", "lemely.core.payer_chain"]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_payer_chain.py tests/architecture/ -v --no-cov`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/core/payer_chain.py pyproject.toml tests/test_payer_chain.py
git commit -S -m "feat(usage): pure payer chain with per-subject seat routing and debt rules" -- lemely/core/payer_chain.py pyproject.toml tests/test_payer_chain.py
```

---

### Task 4: Usage catalogue defaults, lookups and signup grants

**Files:**
- Create: `lemely/db/usage_catalogue_repo.py`
- Create: `tests/usage_helpers.py`
- Modify: `lemely/db/seed.py`: `seed_reference_data` calls `ensure_usage_catalogue` in its session
- Test: `tests/test_usage_catalogue_repo.py`

**Interfaces:**
- Consumes: `UsageRate`, `UsageEstimator`, `EstimatorInputKind`, `GrantKind`, `UsageGrant` (phase 01), `UsageLedger.issue_grant` (phase 01), `CreditPack` (phase 02), `ACTION_SPECS` (Task 1).
- Produces: `SIGNUP_STUDENT_PACK = "signup_student"`, `SIGNUP_TEACHER_PACK = "signup_teacher"`, `DEFAULT_SIGNUP_UNITS: Mapping[str, int]` (`250`, `2000`), `TEACHER_SIGNUP_VALIDITY = timedelta(days=30)`, `SIGNUP_IDEMPOTENCY_KEY = "signup"`, `CATALOGUE_EFFECTIVE_FROM = datetime(2026, 1, 1, tzinfo=UTC)`, `class MeteringUnconfigured(RuntimeError)`, `ensure_usage_catalogue(session, *, now) -> int`, `current_estimator(session, action, *, now) -> EstimatorParams`, `current_rate_version(session, action, *, now) -> int`, `grant_signup_allowance(session, *, user_id, role, now) -> UsageGrant | None`. Test helpers in `tests/usage_helpers.py`: `NOW`, `seed_user`, `seed_catalogue`, `give`, `seat`, `assistant`, `seat_grant`, `jobs_for`.

- [ ] **Step 1: Write the shared test helpers**

```python
# tests/usage_helpers.py
"""Shared seeding for the metering tests (billing plan phase 04)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from lemely.core.metered_actions import MeteredAction
from lemely.db.models.enums import Role
from lemely.db.models.team import (
    AssistantRole,
    CapPeriod,
    TeacherMember,
    TeacherMemberKind,
    TeacherMemberStatus,
)
from lemely.db.models.usage import GrantKind, UsageJob
from lemely.db.models.users import User
from lemely.db.usage_catalogue_repo import ensure_usage_catalogue
from lemely.db.usage_ledger_repo import UsageLedger

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.orm import Session, sessionmaker

#: A Wednesday, so "this ISO week" and "this calendar month" are unambiguous.
NOW = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)


def seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def seed_catalogue(sm: sessionmaker[Session]) -> None:
    with sm.begin() as session:
        ensure_usage_catalogue(session, now=NOW)


def give(
    sm: sessionmaker[Session],
    owner: uuid.UUID,
    *,
    units: int,
    kind: GrantKind = GrantKind.credit_pack,
    visible: bool = True,
    teacher_member_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
) -> uuid.UUID:
    with sm.begin() as session:
        grant = UsageLedger(session).issue_grant(
            owner_user_id=owner,
            kind=kind,
            units=units,
            idempotency_key=f"test:{uuid.uuid4()}",
            expires_at=expires_at,
            visible=visible,
            effective_at=NOW - timedelta(days=1),
            teacher_member_id=teacher_member_id,
        )
        return grant.id


def seat(
    sm: sessionmaker[Session],
    *,
    teacher: uuid.UUID,
    student: uuid.UUID,
    subjects: Iterable[str],
    actions: Iterable[MeteredAction],
    cap_units: int | None = None,
    cap_period: CapPeriod = CapPeriod.month,
    status: TeacherMemberStatus = TeacherMemberStatus.active,
    created_at: datetime = NOW - timedelta(days=10),
) -> uuid.UUID:
    with sm.begin() as session:
        row = TeacherMember(
            teacher_user_id=teacher,
            member_user_id=student,
            kind=TeacherMemberKind.student_seat,
            status=status,
            scope_subjects=list(subjects),
            scope_actions=[a.value for a in actions],
            cap_units=cap_units,
            cap_period=cap_period,
            created_at=created_at,
        )
        session.add(row)
        session.flush()
        return row.id


def assistant(
    sm: sessionmaker[Session],
    *,
    teacher: uuid.UUID,
    member: uuid.UUID,
    cap_units: int | None = None,
    cap_period: CapPeriod = CapPeriod.month,
    role: AssistantRole = AssistantRole.co_teacher,
) -> uuid.UUID:
    with sm.begin() as session:
        row = TeacherMember(
            teacher_user_id=teacher,
            member_user_id=member,
            kind=TeacherMemberKind.assistant,
            status=TeacherMemberStatus.active,
            role_preset=role,
            cap_units=cap_units,
            cap_period=cap_period,
        )
        session.add(row)
        session.flush()
        return row.id


def seat_grant(
    sm: sessionmaker[Session], *, student: uuid.UUID, member_id: uuid.UUID, units: int
) -> uuid.UUID:
    return give(
        sm,
        student,
        units=units,
        kind=GrantKind.seat_allowance,
        visible=False,
        teacher_member_id=member_id,
        expires_at=datetime(2026, 12, 1, tzinfo=UTC),
    )


def jobs_for(sm: sessionmaker[Session], actor: uuid.UUID) -> list[UsageJob]:
    with sm() as session:
        return list(
            session.scalars(
                select(UsageJob)
                .where(UsageJob.actor_user_id == actor)
                .order_by(UsageJob.created_at, UsageJob.id)
            )
        )
```

The columns match plan 03's `TeacherMember` (`cap_period` is NOT NULL; `role_preset` and `permissions` are null on seats). An assistant gets the `co_teacher` preset by default, so `require_team_permission` grants it `mark`, `regrade` and `generate_quiz`.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_usage_catalogue_repo.py
"""Catalogue defaults, current-version lookups and signup grants (Task 4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from lemely.core.metered_actions import ACTION_SPECS, MeteredAction
from lemely.db.models.billing import CreditPack
from lemely.db.models.enums import Role
from lemely.db.models.usage import EstimatorInputKind, GrantKind, UsageEstimator, UsageGrant, UsageRate
from lemely.db.usage_catalogue_repo import (
    SIGNUP_STUDENT_PACK,
    SIGNUP_TEACHER_PACK,
    TEACHER_SIGNUP_VALIDITY,
    current_estimator,
    current_rate_version,
    ensure_usage_catalogue,
    grant_signup_allowance,
)
from tests.usage_helpers import NOW, seed_user

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


def test_ensure_inserts_every_default_once(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker.begin() as session:
        ensure_usage_catalogue(session, now=NOW)
    with migrated_sessionmaker.begin() as session:
        assert ensure_usage_catalogue(session, now=NOW) == 0
    with migrated_sessionmaker() as session:
        actions = {a.value for a in MeteredAction}
        assert set(session.scalars(select(UsageRate.action).where(UsageRate.version == 1))) >= actions
        assert set(session.scalars(select(UsageEstimator.action).where(UsageEstimator.version == 1))) >= actions
        packs = {p.code: p for p in session.scalars(select(CreditPack))}
        assert packs[SIGNUP_STUDENT_PACK].units == 250
        assert packs[SIGNUP_TEACHER_PACK].units == 2000
        assert packs[SIGNUP_STUDENT_PACK].is_active is False
        assert packs[SIGNUP_STUDENT_PACK].price_minor == 0


def test_lookups_seed_lazily_and_return_the_defaults(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker.begin() as session:
        params = current_estimator(session, MeteredAction.MARK_QUIZ, now=NOW)
        version = current_rate_version(session, MeteredAction.MARK_QUIZ, now=NOW)
    assert params == ACTION_SPECS[MeteredAction.MARK_QUIZ].default_estimator
    assert version == 1


def test_an_admin_version_wins_once_effective(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker.begin() as session:
        ensure_usage_catalogue(session, now=NOW)
        session.add(
            UsageEstimator(
                version=2,
                action="mark_paper",
                input_kind=EstimatorInputKind.none,
                base_low=50,
                base_high=90,
                per_input_low=0,
                per_input_high=0,
                effective_from=NOW - timedelta(hours=1),
            )
        )
        session.add(
            UsageEstimator(
                version=3,
                action="mark_paper",
                input_kind=EstimatorInputKind.none,
                base_low=1,
                base_high=2,
                per_input_low=0,
                per_input_high=0,
                effective_from=NOW + timedelta(days=1),
            )
        )
        session.add(
            UsageRate(version=2, action="mark_paper", units_per_usd=2000,
                      effective_from=NOW - timedelta(hours=1))
        )
    with migrated_sessionmaker.begin() as session:
        params = current_estimator(session, MeteredAction.MARK_PAPER, now=NOW)
        assert (params.version, params.base_low, params.base_high) == (2, 50, 90)
        assert current_rate_version(session, MeteredAction.MARK_PAPER, now=NOW) == 2


def test_student_signup_is_a_hidden_one_time_allowance(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    student = seed_user(migrated_sessionmaker, Role.student)
    with migrated_sessionmaker.begin() as session:
        first = grant_signup_allowance(session, user_id=student, role=Role.student, now=NOW)
    with migrated_sessionmaker.begin() as session:
        grant_signup_allowance(session, user_id=student, role=Role.student, now=NOW)
    assert first is not None
    with migrated_sessionmaker() as session:
        grants = list(session.scalars(select(UsageGrant).where(UsageGrant.owner_user_id == student)))
    assert len(grants) == 1
    assert grants[0].kind is GrantKind.signup
    assert grants[0].visible is False
    assert grants[0].expires_at is None
    assert grants[0].units == 250


def test_teacher_signup_is_visible_credits_for_thirty_days(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = seed_user(migrated_sessionmaker, Role.teacher)
    with migrated_sessionmaker.begin() as session:
        grant = grant_signup_allowance(session, user_id=teacher, role=Role.teacher, now=NOW)
        assert grant is not None
        assert grant.visible is True
        assert grant.units == 2000
        assert grant.expires_at == NOW + TEACHER_SIGNUP_VALIDITY


def test_other_roles_and_a_zeroed_pack_get_nothing(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    parent = seed_user(migrated_sessionmaker, Role.parent)
    student = seed_user(migrated_sessionmaker, Role.student)
    with migrated_sessionmaker.begin() as session:
        assert grant_signup_allowance(session, user_id=parent, role=Role.parent, now=NOW) is None
        ensure_usage_catalogue(session, now=NOW)
        pack = session.scalars(select(CreditPack).where(CreditPack.code == SIGNUP_STUDENT_PACK)).one()
        pack.units = 0
    with migrated_sessionmaker.begin() as session:
        assert grant_signup_allowance(session, user_id=student, role=Role.student, now=NOW) is None
    with migrated_sessionmaker() as session:
        count = session.scalar(
            select(func.count()).select_from(UsageGrant).where(UsageGrant.owner_user_id.in_([parent, student]))
        )
    assert count == 0


def test_catalogue_effective_from_predates_any_job(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker.begin() as session:
        ensure_usage_catalogue(session, now=NOW)
        earliest = session.scalar(select(func.max(UsageRate.effective_from)).where(UsageRate.version == 1))
    assert earliest is not None
    assert earliest <= datetime(2026, 1, 1, tzinfo=UTC)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_catalogue_repo.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.db.usage_catalogue_repo'`.

- [ ] **Step 4: Write the module**

```python
# lemely/db/usage_catalogue_repo.py
"""The usage catalogue's defaults and current-version lookups (billing spec §4.1, §2.1).

Rates and estimators are versioned admin data. This build seeds version 1 for every
:class:`~lemely.core.metered_actions.MeteredAction`, plus two signup packs, with
``INSERT ... ON CONFLICT DO NOTHING``. The seeding runs lazily the first time a lookup
finds no row, and from ``seed_reference_data`` (plan deviation 6). An admin's later
version wins once its ``effective_from`` has passed.

Signup amounts are ``credit_packs`` rows that are never sold (``is_active = false``,
``price_minor = 0``; plan deviation 7). ``units = 0`` turns a signup grant off.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from lemely.core.metered_actions import ACTION_SPECS, MeteredAction
from lemely.core.usage_types import EstimatorParams
from lemely.db.models.billing import CreditPack
from lemely.db.models.enums import Role
from lemely.db.models.usage import EstimatorInputKind, GrantKind, UsageEstimator, UsageRate
from lemely.db.usage_ledger_repo import UsageLedger

if TYPE_CHECKING:
    import uuid
    from collections.abc import Mapping

    from sqlalchemy.orm import Session

    from lemely.db.models.usage import UsageGrant

log = structlog.get_logger(__name__)

SIGNUP_STUDENT_PACK = "signup_student"
SIGNUP_TEACHER_PACK = "signup_teacher"
#: About two papers at the top of the seeded marking estimate (spec §2.1).
DEFAULT_SIGNUP_UNITS: Mapping[str, int] = MappingProxyType(
    {SIGNUP_STUDENT_PACK: 250, SIGNUP_TEACHER_PACK: 2000}
)
_SIGNUP_NAMES = {
    SIGNUP_STUDENT_PACK: "Student free allowance",
    SIGNUP_TEACHER_PACK: "Teacher signup credits",
}
TEACHER_SIGNUP_VALIDITY = timedelta(days=30)
#: One signup grant per account: ``usage_grants`` is unique on (owner, idempotency_key).
SIGNUP_IDEMPOTENCY_KEY = "signup"
#: Version 1 applies to every job this build can create.
CATALOGUE_EFFECTIVE_FROM = datetime(2026, 1, 1, tzinfo=UTC)


class MeteringUnconfigured(RuntimeError):
    """No rate or estimator row exists for an action, even after seeding the defaults."""


def ensure_usage_catalogue(session: Session, *, now: datetime) -> int:
    """Insert every missing version-1 default. Returns the number of rows inserted."""
    inserted = 0
    for action, spec in ACTION_SPECS.items():
        est = spec.default_estimator
        inserted += session.execute(
            pg_insert(UsageRate)
            .values(
                version=1,
                action=action.value,
                units_per_usd=spec.default_units_per_usd,
                effective_from=CATALOGUE_EFFECTIVE_FROM,
            )
            .on_conflict_do_nothing(index_elements=["version", "action"])
        ).rowcount
        inserted += session.execute(
            pg_insert(UsageEstimator)
            .values(
                version=1,
                action=action.value,
                input_kind=EstimatorInputKind(est.input_kind),
                base_low=est.base_low,
                base_high=est.base_high,
                per_input_low=est.per_input_low,
                per_input_high=est.per_input_high,
                effective_from=CATALOGUE_EFFECTIVE_FROM,
            )
            .on_conflict_do_nothing(index_elements=["version", "action"])
        ).rowcount
    for code, units in DEFAULT_SIGNUP_UNITS.items():
        inserted += session.execute(
            pg_insert(CreditPack)
            .values(
                code=code,
                name=_SIGNUP_NAMES[code],
                units=units,
                price_minor=0,
                currency="EGP",
                is_active=False,
            )
            .on_conflict_do_nothing(index_elements=["code"])
        ).rowcount
    if inserted:
        log.info("usage_catalogue_seeded", rows=inserted, at=now.isoformat())
    return inserted


def _latest_estimator(session: Session, action: MeteredAction, now: datetime) -> UsageEstimator | None:
    return session.scalars(
        select(UsageEstimator)
        .where(UsageEstimator.action == action.value, UsageEstimator.effective_from <= now)
        .order_by(UsageEstimator.version.desc())
        .limit(1)
    ).first()


def _latest_rate(session: Session, action: MeteredAction, now: datetime) -> UsageRate | None:
    return session.scalars(
        select(UsageRate)
        .where(UsageRate.action == action.value, UsageRate.effective_from <= now)
        .order_by(UsageRate.version.desc())
        .limit(1)
    ).first()


def current_estimator(session: Session, action: MeteredAction, *, now: datetime) -> EstimatorParams:
    """The newest estimator in effect at ``now``; seeds the defaults if none exists."""
    row = _latest_estimator(session, action, now)
    if row is None:
        ensure_usage_catalogue(session, now=now)
        row = _latest_estimator(session, action, now)
    if row is None:
        raise MeteringUnconfigured(f"no usage estimator for {action.value}")
    return EstimatorParams(
        version=row.version,
        input_kind=EstimatorInputKind(row.input_kind).value,
        base_low=row.base_low,
        base_high=row.base_high,
        per_input_low=row.per_input_low,
        per_input_high=row.per_input_high,
    )


def current_rate_version(session: Session, action: MeteredAction, *, now: datetime) -> int:
    """The newest rate version in effect at ``now``; seeds the defaults if none exists."""
    row = _latest_rate(session, action, now)
    if row is None:
        ensure_usage_catalogue(session, now=now)
        row = _latest_rate(session, action, now)
    if row is None:
        raise MeteringUnconfigured(f"no usage rate for {action.value}")
    return row.version


def grant_signup_allowance(
    session: Session, *, user_id: uuid.UUID, role: Role, now: datetime
) -> UsageGrant | None:
    """Issue the free start (spec §2.1): idempotent per account.

    A student gets a hidden one-time allowance with no expiry; a teacher gets visible
    credits that expire after 30 days. Other roles, or a pack set to 0 units, get none.
    """
    if role is Role.student:
        code, visible, expires_at = SIGNUP_STUDENT_PACK, False, None
    elif role is Role.teacher:
        code, visible, expires_at = SIGNUP_TEACHER_PACK, True, now + TEACHER_SIGNUP_VALIDITY
    else:
        return None
    query = select(CreditPack).where(CreditPack.code == code)
    pack = session.scalars(query).first()
    if pack is None:
        ensure_usage_catalogue(session, now=now)
        pack = session.scalars(query).first()
    if pack is None or pack.units <= 0:
        log.info("signup_grant_disabled", code=code, user_id=str(user_id))
        return None
    return UsageLedger(session).issue_grant(
        owner_user_id=user_id,
        kind=GrantKind.signup,
        units=pack.units,
        idempotency_key=SIGNUP_IDEMPOTENCY_KEY,
        expires_at=expires_at,
        visible=visible,
        effective_at=now,
    )
```

- [ ] **Step 5: Seed it in development**

In `lemely/db/seed.py`, add `from lemely.db.usage_catalogue_repo import ensure_usage_catalogue` to the imports. In `seed_reference_data`, inside the `with session_scope(settings) as session:` block and after the subject upsert loop, add:

```python
        # Billing spec §4.1: version-1 usage rates, estimators and signup packs.
        ensure_usage_catalogue(session, now=datetime.now(UTC))
```

(`datetime` and `UTC` are already imported in `seed.py`.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_catalogue_repo.py tests/test_seed.py -v --no-cov`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/db/usage_catalogue_repo.py lemely/db/seed.py tests/usage_helpers.py tests/test_usage_catalogue_repo.py
git commit -S -m "feat(usage): catalogue defaults, current-version lookups and signup grants" -- lemely/db/usage_catalogue_repo.py lemely/db/seed.py tests/usage_helpers.py tests/test_usage_catalogue_repo.py
```

---

### Task 5: Server-side chain facts and targets

**Files:**
- Create: `lemely/db/usage_context_repo.py`
- Test: `tests/test_usage_context_repo.py`

**Interfaces:**
- Consumes: `TeacherMember`, `TeacherMemberKind`, `TeacherMemberStatus` (phase 03); `UsageDebt`, `UsageGrant`, `GrantKind` (phase 01); `Subscription`, `SubscriptionStatus.past_due` (phase 02); `StudyPlan`; `Attempt`, `QuestionResult`, `QuestionResultPoint`; `Quiz`, `QuizAssignment`, `QuizQuestion`, `QuizQuestionStatus`; `SeatView`, `AssistantView`, `ChainContext`, `BlockFacts`, `seat_scope_miss` (Task 3); `MeteredAction`, `SEAT_ACTIONS`, `UsageTarget` (Task 1).
- Produces (all take a `Session` first):
  - `load_chain_context(session, *, actor_user_id: UUID, action: MeteredAction, subject_code: str | None, assistant_member_id: UUID | None, now: datetime) -> ChainContext`
  - `candidate_subjects(session, *, actor_user_id: UUID, action: MeteredAction) -> list[str | None]` (always starts with `None`)
  - `load_block_facts(session, ctx: ChainContext, chain: Sequence[Payer], *, now: datetime) -> BlockFacts`
  - `self_review_target(session, *, student_id: str, attempt_id: str, question_result_id: str) -> UsageTarget | None`
  - `quiz_assignment_target(session, *, assignment_id: str) -> UsageTarget | None`
  - `study_plan_generated_this_week(session, *, user_id: UUID, subject_code: str, now: datetime) -> bool`
  - `allowance_units(session, payer: Payer, *, now: datetime) -> int | None`
  - `has_live_plan(session, owner_user_id: UUID) -> bool`, `has_live_credit_grant(session, owner_user_id: UUID, *, now: datetime) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_usage_context_repo.py
"""DB facts behind the payer chain (Task 5). Targets for self-review and quizzes are
tested beside their routes (Tasks 12 and 13), which already seed those records."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from lemely.core.metered_actions import MeteredAction
from lemely.core.payer_chain import build_payer_chain
from lemely.core.usage_types import GrantScope, Payer
from lemely.db.models.enums import Role
from lemely.db.models.study_plan import StudyPlan
from lemely.db.models.team import TeacherMemberStatus
from lemely.db.models.usage import GrantKind, UsageDebt
from lemely.db.usage_context_repo import (
    allowance_units,
    candidate_subjects,
    has_live_credit_grant,
    load_block_facts,
    load_chain_context,
    study_plan_generated_this_week,
)
from tests.usage_helpers import NOW, assistant, give, seat, seat_grant, seed_catalogue, seed_user

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


def _debt(sm: sessionmaker[Session], owner: object, units: int) -> None:
    with sm.begin() as session:
        session.add(UsageDebt(owner_user_id=owner, job_id=None, units=units, outstanding=units))


def test_seats_load_active_and_leaving_oldest_first(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    student = seed_user(sm)
    t1, t2, t3 = (seed_user(sm, Role.teacher) for _ in range(3))
    newer = seat(sm, teacher=t1, student=student, subjects=["0580"],
                 actions=[MeteredAction.MARK_PAPER], created_at=NOW - timedelta(days=1))
    older = seat(sm, teacher=t2, student=student, subjects=["0580"],
                 actions=[MeteredAction.MARK_PAPER], status=TeacherMemberStatus.leaving,
                 created_at=NOW - timedelta(days=9))
    seat(sm, teacher=t3, student=student, subjects=["0580"],
         actions=[MeteredAction.MARK_PAPER], status=TeacherMemberStatus.removed)
    with sm() as session:
        ctx = load_chain_context(session, actor_user_id=student, action=MeteredAction.MARK_PAPER,
                                 subject_code="0580", assistant_member_id=None, now=NOW)
    assert [s.member_id for s in ctx.seats] == [older, newer]
    assert ctx.seats[0].scope_actions == frozenset({"mark_paper"})


def test_debtors_cover_the_actor_and_every_seat_teacher(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    student, teacher, stranger = seed_user(sm), seed_user(sm, Role.teacher), seed_user(sm)
    seat(sm, teacher=teacher, student=student, subjects=["0580"], actions=[MeteredAction.MARK_PAPER])
    _debt(sm, teacher, 5)
    _debt(sm, stranger, 5)
    with sm() as session:
        ctx = load_chain_context(session, actor_user_id=student, action=MeteredAction.MARK_PAPER,
                                 subject_code="0580", assistant_member_id=None, now=NOW)
    assert ctx.debtors == frozenset({teacher})


def test_assistant_row_loads_and_seats_are_ignored(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    member = assistant(sm, teacher=lead, member=helper, cap_units=300)
    with sm() as session:
        ctx = load_chain_context(session, actor_user_id=helper, action=MeteredAction.REGRADE,
                                 subject_code=None, assistant_member_id=member, now=NOW)
    assert ctx.assistant is not None
    assert (ctx.assistant.lead_teacher_user_id, ctx.assistant.cap_units) == (lead, 300)
    assert ctx.seats == ()


def test_a_foreign_assistant_member_id_is_ignored(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    lead, helper, intruder = (seed_user(sm, Role.teacher) for _ in range(3))
    member = assistant(sm, teacher=lead, member=helper)
    with sm() as session:
        ctx = load_chain_context(session, actor_user_id=intruder, action=MeteredAction.REGRADE,
                                 subject_code=None, assistant_member_id=member, now=NOW)
    assert ctx.assistant is None


def test_study_plan_week_counts_superseded_plans(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    student = seed_user(sm)
    with sm.begin() as session:
        session.add(StudyPlan(user_id=student, subject_code="0580", week_start=date(2026, 11, 2),
                              weekly_hours=4.0, available=True, generated_at=NOW,
                              superseded_at=NOW))
    with sm() as session:
        assert study_plan_generated_this_week(session, user_id=student, subject_code="0580", now=NOW)
        assert not study_plan_generated_this_week(session, user_id=student, subject_code="0625", now=NOW)
        assert not study_plan_generated_this_week(
            session, user_id=student, subject_code="0580", now=NOW + timedelta(days=7)
        )


def test_candidate_subjects_lists_seat_subjects_for_the_action(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    seat(sm, teacher=teacher, student=student, subjects=["0625", "0580"],
         actions=[MeteredAction.MARK_PAPER])
    with sm() as session:
        assert candidate_subjects(session, actor_user_id=student, action=MeteredAction.MARK_PAPER) == [
            None, "0580", "0625"
        ]
        assert candidate_subjects(session, actor_user_id=student, action=MeteredAction.MARK_QUIZ) == [None]
        assert candidate_subjects(session, actor_user_id=student, action=MeteredAction.REGRADE) == [None]


def test_block_facts_read_debt_scope_plan_and_credits(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    seat(sm, teacher=teacher, student=student, subjects=["0625"], actions=[MeteredAction.MARK_PAPER])
    give(sm, student, units=5)
    _debt(sm, student, 3)
    with sm() as session:
        ctx = load_chain_context(session, actor_user_id=student, action=MeteredAction.SELF_REVIEW,
                                 subject_code="0625", assistant_member_id=None, now=NOW)
        facts = load_block_facts(session, ctx, build_payer_chain(ctx), now=NOW)
        assert has_live_credit_grant(session, student, now=NOW)
    assert facts.last_resort_in_debt is True
    assert facts.seat_scope_miss is True
    assert facts.has_credit_grant is True
    assert facts.has_live_plan is False


def test_allowance_units_sums_live_period_and_seat_grants(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    member = seat(sm, teacher=teacher, student=student, subjects=["0580"],
                  actions=[MeteredAction.MARK_PAPER])
    give(sm, student, units=400, kind=GrantKind.period_allowance, visible=False,
         expires_at=datetime(2026, 12, 1, tzinfo=UTC))
    seat_grant(sm, student=student, member_id=member, units=150)
    with sm() as session:
        own = allowance_units(session, Payer(student, GrantScope.ALLOWANCE), now=NOW)
        seated = allowance_units(
            session, Payer(student, GrantScope.SEAT, teacher_member_id=member), now=NOW
        )
        credits = allowance_units(session, Payer(student, GrantScope.CREDITS), now=NOW)
    assert (own, seated, credits) == (400, 150, None)
```

`UsageDebt.job_id` is nullable (plan 01 deviation 9), so a debt with no job is a valid row for these facts tests.

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_context_repo.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.db.usage_context_repo'`.

- [ ] **Step 3: Write the module**

```python
# lemely/db/usage_context_repo.py
"""Server-side facts for metering (billing spec §5.6, §5.7). Read-only queries.

Everything the payer chain and the 402 reason depend on is read here, from the records an
action works on, never from client input: seats and their scope, the assistant row, which
owners have debt, whether a study plan was already generated this ISO week, and the
subject and countable inputs of a paper, quiz or question.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import exists, func, or_, select

from lemely.core.metered_actions import SEAT_ACTIONS, MeteredAction, UsageTarget
from lemely.core.payer_chain import AssistantView, BlockFacts, ChainContext, SeatView, seat_scope_miss
from lemely.core.usage_types import GrantScope
from lemely.db.models.attempts import Attempt, QuestionResult, QuestionResultPoint
from lemely.db.models.billing import Subscription
from lemely.db.models.enums import QuizQuestionStatus, SubscriptionStatus
from lemely.db.models.quizzes import Quiz, QuizAssignment, QuizQuestion
from lemely.db.models.study_plan import StudyPlan
from lemely.db.models.team import TeacherMember, TeacherMemberKind, TeacherMemberStatus
from lemely.db.models.usage import GrantKind, UsageDebt, UsageGrant

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

    from lemely.core.usage_types import Payer

_SEAT_LIVE = (TeacherMemberStatus.active, TeacherMemberStatus.leaving)
_PLAN_LIVE = (SubscriptionStatus.active, SubscriptionStatus.past_due)


def _seat_rows(session: Session, actor_user_id: uuid.UUID) -> list[TeacherMember]:
    return list(
        session.scalars(
            select(TeacherMember)
            .where(
                TeacherMember.member_user_id == actor_user_id,
                TeacherMember.kind == TeacherMemberKind.student_seat,
                TeacherMember.status.in_(_SEAT_LIVE),
            )
            .order_by(TeacherMember.created_at, TeacherMember.id)
        )
    )


def _seat_view(row: TeacherMember) -> SeatView:
    return SeatView(
        member_id=row.id,
        teacher_user_id=row.teacher_user_id,
        scope_subjects=frozenset(row.scope_subjects or ()),
        scope_actions=frozenset(row.scope_actions or ()),
        cap_units=row.cap_units,
        cap_period=row.cap_period.value if row.cap_period is not None else "month",
        created_at=row.created_at,
    )


def _assistant_view(
    session: Session, *, actor_user_id: uuid.UUID, member_id: uuid.UUID
) -> AssistantView | None:
    row = session.get(TeacherMember, member_id)
    if (
        row is None
        or row.member_user_id != actor_user_id
        or row.kind is not TeacherMemberKind.assistant
        or row.status is not TeacherMemberStatus.active
    ):
        return None
    return AssistantView(
        member_id=row.id,
        lead_teacher_user_id=row.teacher_user_id,
        cap_units=row.cap_units,
        cap_period=row.cap_period.value if row.cap_period is not None else "month",
    )


def study_plan_generated_this_week(
    session: Session, *, user_id: uuid.UUID, subject_code: str, now: datetime
) -> bool:
    """A plan (live or superseded) already exists for this ISO week (§2.2 study plans)."""
    week_start = now.date() - timedelta(days=now.weekday())
    return bool(
        session.scalar(
            select(
                exists().where(
                    StudyPlan.user_id == user_id,
                    StudyPlan.subject_code == subject_code,
                    StudyPlan.week_start == week_start,
                )
            )
        )
    )


def load_chain_context(
    session: Session,
    *,
    actor_user_id: uuid.UUID,
    action: MeteredAction,
    subject_code: str | None,
    assistant_member_id: uuid.UUID | None,
    now: datetime,
) -> ChainContext:
    """Read every fact ``build_payer_chain`` needs for one action."""
    assistant = (
        _assistant_view(session, actor_user_id=actor_user_id, member_id=assistant_member_id)
        if assistant_member_id is not None
        else None
    )
    seats = () if assistant is not None else tuple(_seat_view(r) for r in _seat_rows(session, actor_user_id))
    owners = {actor_user_id, *(s.teacher_user_id for s in seats)}
    if assistant is not None:
        owners.add(assistant.lead_teacher_user_id)
    debtors = frozenset(
        session.scalars(
            select(UsageDebt.owner_user_id)
            .where(UsageDebt.owner_user_id.in_(owners), UsageDebt.outstanding > 0)
            .distinct()
        )
    )
    generated = (
        action is MeteredAction.STUDY_PLAN
        and subject_code is not None
        and study_plan_generated_this_week(
            session, user_id=actor_user_id, subject_code=subject_code, now=now
        )
    )
    return ChainContext(
        actor_user_id=actor_user_id,
        action=action,
        subject_code=subject_code,
        now=now,
        seats=seats,
        assistant=assistant,
        debtors=debtors,
        study_plan_generated_this_week=generated,
    )


def candidate_subjects(
    session: Session, *, actor_user_id: uuid.UUID, action: MeteredAction
) -> list[str | None]:
    """Subjects a not-yet-known subject could turn out to be, for a pre-check: ``None``
    (no seat) plus every seat subject whose seat covers ``action``, sorted."""
    if action not in SEAT_ACTIONS:
        return [None]
    subjects = sorted(
        {
            subject
            for row in _seat_rows(session, actor_user_id)
            if action.value in (row.scope_actions or ())
            for subject in (row.scope_subjects or ())
        }
    )
    return [None, *subjects]


def has_live_plan(session: Session, owner_user_id: uuid.UUID) -> bool:
    return bool(
        session.scalar(
            select(
                exists().where(
                    Subscription.user_id == owner_user_id, Subscription.status.in_(_PLAN_LIVE)
                )
            )
        )
    )


def has_live_credit_grant(session: Session, owner_user_id: uuid.UUID, *, now: datetime) -> bool:
    return bool(
        session.scalar(
            select(
                exists().where(
                    UsageGrant.owner_user_id == owner_user_id,
                    UsageGrant.visible.is_(True),
                    or_(UsageGrant.expires_at.is_(None), UsageGrant.expires_at > now),
                )
            )
        )
    )


def load_block_facts(
    session: Session, ctx: ChainContext, chain: Sequence[Payer], *, now: datetime
) -> BlockFacts:
    """Why ``chain`` cannot cover an estimate, for ``block_reason``."""
    funding = ctx.assistant.lead_teacher_user_id if ctx.assistant is not None else ctx.actor_user_id
    return BlockFacts(
        last_resort_in_debt=chain[-1].owner_user_id in ctx.debtors,
        seat_scope_miss=seat_scope_miss(ctx),
        has_live_plan=has_live_plan(session, funding),
        has_credit_grant=has_live_credit_grant(session, funding, now=now),
    )


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def self_review_target(
    session: Session, *, student_id: str, attempt_id: str, question_result_id: str
) -> UsageTarget | None:
    """The caller's own question: its attempt's subject and its mark-point count."""
    sid, aid, qid = _uuid(student_id), _uuid(attempt_id), _uuid(question_result_id)
    if sid is None or aid is None or qid is None:
        return None
    subject = session.execute(
        select(Attempt.subject_code)
        .join(QuestionResult, QuestionResult.attempt_id == Attempt.id)
        .where(Attempt.id == aid, Attempt.user_id == sid, QuestionResult.id == qid)
    ).first()
    if subject is None:
        return None
    marks = session.scalar(
        select(func.count())
        .select_from(QuestionResultPoint)
        .where(QuestionResultPoint.question_result_id == qid)
    )
    return UsageTarget(subject_code=subject[0], input_count=int(marks or 0))


def quiz_assignment_target(session: Session, *, assignment_id: str) -> UsageTarget | None:
    """An assignment's quiz: its subject and its included question count."""
    aid = _uuid(assignment_id)
    if aid is None:
        return None
    quiz = session.execute(
        select(Quiz.id, Quiz.subject_code)
        .join(QuizAssignment, QuizAssignment.quiz_id == Quiz.id)
        .where(QuizAssignment.id == aid)
    ).first()
    if quiz is None:
        return None
    count = session.scalar(
        select(func.count())
        .select_from(QuizQuestion)
        .where(QuizQuestion.quiz_id == quiz.id, QuizQuestion.status == QuizQuestionStatus.included)
    )
    return UsageTarget(subject_code=quiz.subject_code, input_count=int(count or 0))


def allowance_units(session: Session, payer: Payer, *, now: datetime) -> int | None:
    """Units of the live monthly allowance a payer draws from, for "N% of your plan".

    ``None`` for a credits payer, and when no period or seat allowance is live (a
    signup-only student sees credits-style copy).
    """
    if payer.scope is GrantScope.SEAT:
        filters = (
            UsageGrant.kind == GrantKind.seat_allowance,
            UsageGrant.teacher_member_id == payer.teacher_member_id,
        )
    elif payer.scope is GrantScope.ALLOWANCE:
        filters = (UsageGrant.kind == GrantKind.period_allowance,)
    else:
        return None
    total = session.scalar(
        select(func.sum(UsageGrant.units)).where(
            UsageGrant.owner_user_id == payer.owner_user_id,
            or_(UsageGrant.expires_at.is_(None), UsageGrant.expires_at > now),
            *filters,
        )
    )
    return int(total) if total else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_context_repo.py tests/test_include_deleted_scope.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/db/usage_context_repo.py tests/test_usage_context_repo.py
git commit -S -m "feat(usage): server-side facts and targets for the payer chain" -- lemely/db/usage_context_repo.py tests/test_usage_context_repo.py
```

---

### Task 6: `UsageMeter`, `MeteredJob`, `require_usage` and the 402 contract

**Files:**
- Create: `lemely/web/usage.py`
- Modify: `lemely/runtime/config.py`: add `UsageSettings` (after `NotificationsSettings`) and `usage: UsageSettings = UsageSettings()` on `Settings` (after `tutoring:`)
- Modify: `lemely/web/app.py`: register the `UsageBlocked` handler in `create_app`
- Modify: `tests/conftest.py`: suite-wide `LEMELY_USAGE__ENFORCE=0`
- Modify: `tests/usage_helpers.py`: add `enforcing_meter`
- Test: `tests/test_web_usage_meter.py`

**Interfaces:**
- Consumes: Tasks 1–5; `UsageLedger` (`available`, `reserve`, `settle`, `release`), `InsufficientBalance` (phase 01); `estimate_range` (phase 01); `cost_scope` (Task 2); `TeamActor` (phase 03, `lemely.web.deps`).
- Produces (`lemely/web/usage.py`):
  - `USAGE_BLOCKED_MESSAGE: str`, `EXEMPT_ROLES = frozenset({Role.platform_admin})`
  - `class UsageBlocked(Exception)`: `reason: UsageBlockReason`, `estimate: tuple[int, int]`, `body() -> dict[str, object]` = `{"error": "usage_blocked", "reason": <value>, "estimate": [low, high]}`
  - `async def usage_blocked_handler(request: Request, exc: Exception) -> JSONResponse` (402)
  - `UsageRequest(actor_user_id: UUID, actor_role: Role, action: MeteredAction, subject_code: str | None = None, input_count: int = 0, assistant_member_id: UUID | None = None, subject_pending: bool = False)`
  - `UsageGrantContext(request, chain: tuple[Payer, ...], estimate: tuple[int, int], estimator_version: int, rate_version: int, teacher_member_id: UUID | None, exempt: bool = False)`, classmethod `exempt_for(request)`
  - `EstimateView(low: int, high: int, payer: str, percent_low: int | None, percent_high: int | None, blocked_reason: UsageBlockReason | None)`
  - `class MeteredJob`: attributes `job_id: UUID`, `ctx: UsageGrantContext`. Methods: `bind_subject(subject_code: str | None) -> None`, `abandon() -> None`, `release() -> None`, `run() -> ContextManager[MeteredJob]`. Classmethod `unmetered(action: MeteredAction) -> MeteredJob`
  - `class UsageMeter(sessionmaker, *, enforce: bool = True, now: Callable[[], datetime] = _utcnow)`: `now() -> datetime`, `authorize(request) -> UsageGrantContext`, `estimate(request) -> EstimateView`, `reserve(ctx) -> MeteredJob`, `job(ctx) -> ContextManager[MeteredJob]`, `resolve_target(fn: Callable[[Session], UsageTarget | None]) -> UsageTarget | None`, `read(fn: Callable[[Session], T]) -> T`
  - `get_usage_meter(settings) -> UsageMeter` (FastAPI dependency)
  - `request_from_auth(auth: AuthContext, action, *, subject_code=None, input_count=0, assistant_member_id=None, subject_pending=False) -> UsageRequest`
  - `request_from_team(actor: TeamActor, action, *, subject_code=None, input_count=0) -> UsageRequest` (R4: `assistant_member_id = actor.member_id`)
  - `require_usage(action: MeteredAction, *, target: Callable[..., UsageTarget] | None = None, team: Callable[..., TeamActor] | None = None) -> Callable[..., UsageGrantContext]`
  - Post-settle hook registry (deviation 12; names fixed by plan 06 Task 7): `PostSettleHook = Callable[[Session, UsageJob, Sequence[Payer], datetime], None]`, `_POST_SETTLE_HOOKS`, `register_post_settle_hook(hook)`, `clear_post_settle_hooks()`, `run_post_settle_hooks(session, job, payers, now)`. `MeteredJob._finish` is the only place a job settles and calls `run_post_settle_hooks` right after `UsageLedger.settle`, in the same transaction.
  - `tests/usage_helpers.enforcing_meter(sm, now=NOW) -> UsageMeter`

- [ ] **Step 1: Add the settings group and the suite switch**

In `lemely/runtime/config.py`, after the `NotificationsSettings` class, add:

```python
class UsageSettings(BaseModel):
    """Usage metering (billing spec §2.4, §5.7).

    Overrides via ``lemely.toml`` under ``[usage]`` or ``LEMELY_USAGE__*`` env vars.

    ``enforce`` is true in every deployed environment: every LLM-backed route reserves
    against the usage ledger and answers 402 when the payer chain cannot cover the top of
    the estimate. ``tests/conftest.py`` sets it false for the suite, so route tests written
    before metering need no ledger; the metering tests build an enforcing ``UsageMeter``
    themselves. Not emitted to ``lemely.toml.example``: nobody setting Lemely up turns it off.
    """

    enforce: bool = True
```

In `class Settings`, after `tutoring: TutoringSettings = TutoringSettings()`, add:

```python
    usage: UsageSettings = UsageSettings()
```

In `tests/conftest.py`, directly after the `_disable_dotenv_file` fixture, add:

```python
@pytest.fixture(scope="session", autouse=True)
def _disable_usage_enforcement() -> Iterator[None]:
    """Route tests run without the usage ledger (billing plan phase 04, deviation 11).

    Every metered route reads ``settings.usage.enforce`` through ``get_usage_meter``; with
    it off, ``UsageMeter`` returns exempt contexts and never touches the database. The
    metering tests override ``get_usage_meter`` with an enforcing meter on their own DB.
    """
    patch = pytest.MonkeyPatch()
    patch.setenv("LEMELY_USAGE__ENFORCE", "0")
    try:
        yield
    finally:
        patch.undo()
```

- [ ] **Step 2: Write the failing test**

Append to `tests/usage_helpers.py`:

```python
def enforcing_meter(sm: sessionmaker[Session], now: datetime = NOW) -> UsageMeter:
    from lemely.web.usage import UsageMeter

    return UsageMeter(sm, enforce=True, now=lambda: now)
```

and add `from lemely.web.usage import UsageMeter` under the file's `if TYPE_CHECKING:` block.

```python
# tests/test_web_usage_meter.py
"""UsageMeter: authorize, reserve, settle, release, deferred subjects, 402 (Task 6)."""

from __future__ import annotations

import contextvars
import threading
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lemely.core.metered_actions import MeteredAction
from lemely.core.payer_chain import UsageBlockReason
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind, UsageGrantBalance, UsageJobStatus
from lemely.io.llm.cost_meter import record_llm_cost
from lemely.runtime.config import Settings, UsageSettings
from lemely.web import usage
from lemely.web.deps import AuthContext, TeamActor
from lemely.web.usage import (
    MeteredJob,
    UsageBlocked,
    UsageMeter,
    UsageRequest,
    get_usage_meter,
    request_from_team,
    usage_blocked_handler,
)
from tests.usage_helpers import (
    NOW,
    assistant,
    enforcing_meter,
    give,
    jobs_for,
    seat,
    seat_grant,
    seed_catalogue,
    seed_user,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


def _req(actor: uuid.UUID, action: MeteredAction = MeteredAction.MARK_PAPER, **kw: object) -> UsageRequest:
    return UsageRequest(actor_user_id=actor, actor_role=kw.pop("role", Role.student), action=action, **kw)  # type: ignore[arg-type]


def test_enforce_is_on_by_default_and_off_under_the_suite(monkeypatch: pytest.MonkeyPatch) -> None:
    """R5: the shipped default enforces; only the suite's env var turns it off."""
    assert UsageSettings().enforce is True
    assert Settings().usage.enforce is False
    monkeypatch.delenv("LEMELY_USAGE__ENFORCE")
    default = Settings()
    assert default.usage.enforce is True
    # The app's own dependency, built from default settings, meters a student.
    assert get_usage_meter(default)._exempt(_req(uuid.uuid4())) is False


def test_an_assistant_never_spends_its_own_balance(migrated_sessionmaker: sessionmaker[Session]) -> None:
    """R4: team work is charged to the lead; the assistant's own credits are untouched."""
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    own = give(sm, helper, units=1000)
    member = assistant(sm, teacher=lead, member=helper)
    actor = TeamActor(
        actor_user_id=helper,
        lead_teacher_user_id=lead,
        member_id=member,
        auth=AuthContext(user_id=str(lead), role="teacher"),
    )
    meter = enforcing_meter(sm)
    with pytest.raises(UsageBlocked) as info:  # the lead has nothing; the helper's 1000 never counts
        meter.authorize(request_from_team(actor, MeteredAction.REGRADE))
    assert info.value.reason is UsageBlockReason.NO_ACTIVE_PLAN
    give(sm, lead, units=500)
    with meter.job(meter.authorize(request_from_team(actor, MeteredAction.REGRADE))):
        record_llm_cost(Decimal("0.050"))
    (job,) = jobs_for(sm, helper)
    assert (job.charged, job.teacher_member_id) == (50, member)
    with sm() as session:
        assert session.get(UsageGrantBalance, own).remaining == 1000


def test_post_settle_hooks_run_once_after_a_settle_never_after_a_release(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student = seed_user(sm)
    give(sm, student, units=1000)
    seen: list[tuple[int, int]] = []
    saved = list(usage._POST_SETTLE_HOOKS)
    usage.clear_post_settle_hooks()
    usage.register_post_settle_hook(lambda _s, job, payers, _now: seen.append((job.charged, len(payers))))
    try:
        meter = enforcing_meter(sm)
        with meter.job(meter.authorize(_req(student))):
            record_llm_cost(Decimal("0.020"))
        with pytest.raises(RuntimeError), meter.job(meter.authorize(_req(student))):
            raise RuntimeError("failed job")
    finally:
        usage.clear_post_settle_hooks()
        usage._POST_SETTLE_HOOKS.extend(saved)
    assert seen == [(20, 2)]


def test_blocked_without_any_balance_is_no_active_plan(migrated_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(migrated_sessionmaker)
    with pytest.raises(UsageBlocked) as info:
        enforcing_meter(migrated_sessionmaker).authorize(_req(student))
    assert info.value.body() == {"error": "usage_blocked", "reason": "no_active_plan", "estimate": [40, 120]}


def test_success_settles_the_actual_cost(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student = seed_user(sm)
    give(sm, student, units=1000)
    meter = enforcing_meter(sm)
    with meter.job(meter.authorize(_req(student))):
        record_llm_cost(Decimal("0.050"))
    (job,) = jobs_for(sm, student)
    assert job.status is UsageJobStatus.settled
    assert job.charged == 50
    assert job.action == "mark_paper"
    assert (job.estimate_low, job.estimate_high) == (40, 120)


def test_an_exception_releases_and_charges_nothing(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student = seed_user(sm)
    give(sm, student, units=1000)
    meter = enforcing_meter(sm)
    with pytest.raises(RuntimeError), meter.job(meter.authorize(_req(student))):
        record_llm_cost(Decimal("0.050"))
        raise RuntimeError("model call failed")
    (job,) = jobs_for(sm, student)
    assert job.status is UsageJobStatus.released
    assert not job.charged


def test_abandon_releases_a_normal_exit(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student = seed_user(sm)
    give(sm, student, units=1000)
    meter = enforcing_meter(sm)
    with meter.job(meter.authorize(_req(student))) as job:
        record_llm_cost(Decimal("0.050"))
        job.abandon()
    assert jobs_for(sm, student)[0].status is UsageJobStatus.released


def test_reserve_in_the_request_settle_in_a_bare_worker_thread(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """The SSE and pool shape: reserve here, run() opens the scope inside the worker."""
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student = seed_user(sm)
    give(sm, student, units=1000)
    meter = enforcing_meter(sm)
    job = meter.reserve(meter.authorize(_req(student)))
    assert jobs_for(sm, student)[0].status is UsageJobStatus.open

    def work() -> None:
        with job.run():
            record_llm_cost(Decimal("0.020"))
            nested = contextvars.copy_context()
            inner = threading.Thread(target=nested.run, args=(record_llm_cost, Decimal("0.010")))
            inner.start()
            inner.join()

    worker = threading.Thread(target=work)
    worker.start()
    worker.join()
    (row,) = jobs_for(sm, student)
    assert row.status is UsageJobStatus.settled
    assert row.charged == 30


def test_release_of_a_job_that_never_ran(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student = seed_user(sm)
    give(sm, student, units=1000)
    meter = enforcing_meter(sm)
    meter.reserve(meter.authorize(_req(student))).release()
    assert jobs_for(sm, student)[0].status is UsageJobStatus.released


def test_deferred_subject_pre_checks_seats_then_binds_the_detected_subject(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student, maths = seed_user(sm), seed_user(sm, Role.teacher)
    member = seat(sm, teacher=maths, student=student, subjects=["0580"], actions=[MeteredAction.MARK_PAPER])
    seat_grant(sm, student=student, member_id=member, units=500)
    meter = enforcing_meter(sm)
    job = meter.reserve(meter.authorize(_req(student, subject_pending=True)))
    assert jobs_for(sm, student) == []  # nothing held until the subject is known
    with job.run():
        job.bind_subject("0580")
        record_llm_cost(Decimal("0.040"))
    (row,) = jobs_for(sm, student)
    assert row.teacher_member_id == member
    assert row.charged == 40


def test_deferred_subject_that_no_payer_covers_is_blocked_inside_the_job(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student, maths = seed_user(sm), seed_user(sm, Role.teacher)
    member = seat(sm, teacher=maths, student=student, subjects=["0580"], actions=[MeteredAction.MARK_PAPER])
    seat_grant(sm, student=student, member_id=member, units=500)
    meter = enforcing_meter(sm)
    job = meter.reserve(meter.authorize(_req(student, subject_pending=True)))
    with pytest.raises(UsageBlocked) as info, job.run():
        job.bind_subject("0625")
    assert info.value.reason is UsageBlockReason.NO_ACTIVE_PLAN
    assert jobs_for(sm, student) == []


def test_a_lost_race_is_a_402_not_a_500(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student = seed_user(sm)
    give(sm, student, units=150)
    meter = enforcing_meter(sm)
    first = meter.authorize(_req(student))
    second = meter.authorize(_req(student))
    meter.reserve(first)
    with pytest.raises(UsageBlocked) as info:
        meter.reserve(second)
    assert info.value.reason is UsageBlockReason.INSUFFICIENT_CREDITS


def test_assistant_cap_limits_the_lead_teachers_balance(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    give(sm, lead, units=5000)
    member = assistant(sm, teacher=lead, member=helper, cap_units=30)
    meter = enforcing_meter(sm)
    with pytest.raises(UsageBlocked) as info:
        meter.authorize(_req(helper, MeteredAction.REGRADE, role=Role.teacher, assistant_member_id=member))
    assert info.value.reason is UsageBlockReason.INSUFFICIENT_CREDITS
    uncapped_helper = seed_user(sm, Role.teacher)
    roomy = assistant(sm, teacher=lead, member=uncapped_helper, cap_units=None)
    ctx = meter.authorize(
        _req(uncapped_helper, MeteredAction.REGRADE, role=Role.teacher, assistant_member_id=roomy)
    )
    assert [p.owner_user_id for p in ctx.chain] == [lead, lead]
    assert ctx.teacher_member_id == roomy


def test_debt_blocks_own_balance_but_a_seat_still_pays(migrated_sessionmaker: sessionmaker[Session]) -> None:
    from lemely.db.models.usage import UsageDebt

    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student, maths = seed_user(sm), seed_user(sm, Role.teacher)
    with sm.begin() as session:
        session.add(UsageDebt(owner_user_id=student, job_id=None, units=10, outstanding=10))
    meter = enforcing_meter(sm)
    with pytest.raises(UsageBlocked) as info:
        meter.authorize(_req(student, subject_code="0580"))
    assert info.value.reason is UsageBlockReason.OUTSTANDING_DEBT
    member = seat(sm, teacher=maths, student=student, subjects=["0580"], actions=[MeteredAction.MARK_PAPER])
    seat_grant(sm, student=student, member_id=member, units=500)
    assert meter.authorize(_req(student, subject_code="0580")).teacher_member_id == member


def test_platform_admins_and_a_non_enforcing_meter_are_exempt(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    admin = seed_user(sm, Role.platform_admin)
    ctx = enforcing_meter(sm).authorize(_req(admin, role=Role.platform_admin))
    assert ctx.exempt is True
    off = UsageMeter(sm, enforce=False)
    student = seed_user(sm)
    with off.job(off.authorize(_req(student))):
        record_llm_cost(Decimal("0.5"))
    assert jobs_for(sm, admin) == jobs_for(sm, student) == []


def test_unmetered_jobs_need_no_database() -> None:
    job = MeteredJob.unmetered(MeteredAction.MARK_PAPER)
    with job.run():
        record_llm_cost(Decimal("0.1"))
    job.release()


def test_the_402_body_is_the_top_level_contract() -> None:
    app = FastAPI()
    app.add_exception_handler(UsageBlocked, usage_blocked_handler)

    @app.get("/blocked")
    def _blocked() -> None:
        raise UsageBlocked(UsageBlockReason.OUT_OF_SEAT_SCOPE, (3, 5))

    resp = TestClient(app).get("/blocked")
    assert resp.status_code == 402
    assert resp.json() == {"error": "usage_blocked", "reason": "out_of_seat_scope", "estimate": [3, 5]}


def test_estimate_view_reports_the_paying_scope(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student = seed_user(sm)
    meter = enforcing_meter(sm)
    give(sm, student, units=4000, kind=GrantKind.period_allowance, visible=False,
         expires_at=NOW.replace(month=12, day=1))
    view = meter.estimate(_req(student))
    assert (view.low, view.high, view.payer) == (40, 120, "allowance")
    assert (view.percent_low, view.percent_high) == (1, 3)
    assert view.blocked_reason is None
    broke = seed_user(sm)
    blocked = meter.estimate(_req(broke))
    assert (blocked.payer, blocked.blocked_reason) == ("none", UsageBlockReason.NO_ACTIVE_PLAN)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_web_usage_meter.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.web.usage'`.

- [ ] **Step 4: Write `lemely/web/usage.py`**

```python
# lemely/web/usage.py
"""Metering for every LLM-backed web action (billing spec §2.4, §5.6, §5.7).

Every metered route takes three steps, in this order:

1. :meth:`UsageMeter.authorize`: no writes. It computes the estimate from server-side
   inputs, builds the payer chain and checks that the chain covers the top of the range.
   It raises :class:`UsageBlocked`, which ``create_app`` turns into the 402 contract.
2. :meth:`UsageMeter.reserve`: holds ``estimate_high`` across the chain and opens the
   ``usage_jobs`` row. It runs in the request, so a 402 can still come back before a
   stream or a pool job starts. A job whose subject is not known yet (a student's scan,
   read inside the job) reserves later, in :meth:`MeteredJob.bind_subject`.
3. ``with job.run():`` wraps the work, in whatever thread does it. It opens the cost
   accumulator and settles the actual cost on a normal exit. It releases on an exception
   or after :meth:`MeteredJob.abandon`. The web layer's thread hops (the SSE worker, the
   grading pool, the quiz marking thread) do not copy context, which is why the scope
   opens inside the worker.

:meth:`UsageMeter.job` is steps 2 and 3 together, for a synchronous route.
"""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, TypeVar

import structlog
from fastapi import Depends
from fastapi.responses import JSONResponse

from lemely.core.metered_actions import ACTION_SPECS, JOB_SLACK, MeteredAction, UsageTarget, clamp_inputs
from lemely.core.payer_chain import UsageBlockReason, block_reason, build_payer_chain, job_teacher_member_id
from lemely.core.usage_pricing import estimate_range
from lemely.core.usage_types import GrantScope
from lemely.db.models.enums import Role
from lemely.db.session import get_sessionmaker
from lemely.db.usage_catalogue_repo import current_estimator, current_rate_version
from lemely.db.usage_context_repo import (
    allowance_units,
    candidate_subjects,
    load_block_facts,
    load_chain_context,
)
from lemely.db.usage_ledger_repo import InsufficientBalance, UsageLedger
from lemely.io.llm.cost_meter import cost_scope
from lemely.runtime.config import Settings
from lemely.web.deps import AuthContext, get_auth_context, get_settings

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from fastapi import Request
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.core.payer_chain import ChainContext
    from lemely.core.usage_types import EstimatorParams, Payer

log = structlog.get_logger(__name__)

T = TypeVar("T")

#: The copy an SSE error frame carries when a job is blocked after it started streaming.
USAGE_BLOCKED_MESSAGE = "You don't have enough usage left for this. Check your plan or credits."
#: Roles never metered (plan deviation 10).
EXEMPT_ROLES: frozenset[Role] = frozenset({Role.platform_admin})


def _utcnow() -> datetime:
    return datetime.now(UTC)


class UsageBlocked(Exception):
    """The payer chain cannot cover the top of the estimate (HTTP 402)."""

    def __init__(self, reason: UsageBlockReason, estimate: tuple[int, int]) -> None:
        super().__init__(f"usage blocked: {reason.value}")
        self.reason = reason
        self.estimate = estimate

    def body(self) -> dict[str, object]:
        """The 402 body every client reads (index, phase 04 contract)."""
        return {
            "error": "usage_blocked",
            "reason": self.reason.value,
            "estimate": [self.estimate[0], self.estimate[1]],
        }


async def usage_blocked_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Render :class:`UsageBlocked` as the top-level 402 body (not under ``detail``)."""
    if not isinstance(exc, UsageBlocked):
        raise exc
    return JSONResponse(status_code=402, content=exc.body())


@dataclass(frozen=True)
class UsageRequest:
    """One metered action, as the server sees it. Every field is read on the server."""

    actor_user_id: uuid.UUID
    actor_role: Role
    action: MeteredAction
    subject_code: str | None = None
    input_count: int = 0
    assistant_member_id: uuid.UUID | None = None
    subject_pending: bool = False


@dataclass(frozen=True)
class UsageGrantContext:
    """What :meth:`UsageMeter.authorize` approved: the chain and the estimate."""

    request: UsageRequest
    chain: tuple[Payer, ...]
    estimate: tuple[int, int]
    estimator_version: int
    rate_version: int
    teacher_member_id: uuid.UUID | None
    exempt: bool = False

    @classmethod
    def exempt_for(cls, request: UsageRequest) -> UsageGrantContext:
        return cls(
            request=request,
            chain=(),
            estimate=(0, 0),
            estimator_version=0,
            rate_version=0,
            teacher_member_id=None,
            exempt=True,
        )


@dataclass(frozen=True)
class EstimateView:
    """``POST /api/usage/estimate``'s answer: the range and who would pay."""

    low: int
    high: int
    payer: str
    percent_low: int | None
    percent_high: int | None
    blocked_reason: UsageBlockReason | None


@dataclass(frozen=True)
class _Evaluation:
    estimator: EstimatorParams
    rate_version: int
    estimate: tuple[int, int]
    chain_ctx: ChainContext
    chain: tuple[Payer, ...]
    available: int


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


class MeteredJob:
    """One metered job: reserved in the request, run and settled wherever the work runs."""

    def __init__(self, meter: UsageMeter | None, ctx: UsageGrantContext, job_id: uuid.UUID) -> None:
        self._meter = meter
        self.ctx = ctx
        self.job_id = job_id
        self._reserved = False
        self._abandoned = False
        self._finished = False

    @classmethod
    def unmetered(cls, action: MeteredAction) -> MeteredJob:
        """A job that records nothing and needs no database (callers outside a request)."""
        request = UsageRequest(
            actor_user_id=uuid.UUID(int=0), actor_role=Role.platform_admin, action=action
        )
        return cls(None, UsageGrantContext.exempt_for(request), uuid.uuid4())

    def _live_meter(self) -> UsageMeter:
        if self._meter is None:
            raise RuntimeError("an unmetered job has no meter")
        return self._meter

    def _reserve(self) -> None:
        meter = self._live_meter()
        ctx = self.ctx
        now = meter.now()
        spec = ACTION_SPECS[ctx.request.action]
        try:
            with meter.sessionmaker.begin() as session:
                UsageLedger(session).reserve(
                    job_id=self.job_id,
                    actor_user_id=ctx.request.actor_user_id,
                    action=ctx.request.action.value,
                    payers=list(ctx.chain),
                    estimate_low=ctx.estimate[0],
                    estimate_high=ctx.estimate[1],
                    estimator_version=ctx.estimator_version,
                    rate_version=ctx.rate_version,
                    teacher_member_id=ctx.teacher_member_id,
                    expires_at=now + spec.job_timeout + JOB_SLACK,
                    now=now,
                )
        except InsufficientBalance as exc:
            # Another job took the balance between authorize and reserve.
            raise UsageBlocked(meter.reason_for(ctx.request), ctx.estimate) from exc
        self._reserved = True

    def bind_subject(self, subject_code: str | None) -> None:
        """Fix a deferred job's subject (read inside the job), re-check and reserve."""
        if self.ctx.exempt:
            return
        if not self.ctx.request.subject_pending or self._reserved:
            raise RuntimeError("bind_subject is only for a job whose subject is still pending")
        meter = self._live_meter()
        self.ctx = meter.authorize(
            replace(self.ctx.request, subject_code=subject_code, subject_pending=False)
        )
        self._reserve()

    def abandon(self) -> None:
        """Mark the work failed without raising: :meth:`run` releases instead of settling."""
        self._abandoned = True

    def release(self) -> None:
        """Release a reserved job that will never run (claim lost, submit refused)."""
        self._finish(Decimal(0), settle=False)

    @contextlib.contextmanager
    def run(self) -> Iterator[MeteredJob]:
        """Meter the enclosed work: settle on a normal exit, release on failure."""
        with cost_scope() as accumulator:
            try:
                yield self
            except BaseException:
                self._finish(accumulator.total_usd, settle=False)
                raise
            self._finish(accumulator.total_usd, settle=not self._abandoned)

    def _finish(self, cost_usd: Decimal, *, settle: bool) -> None:
        if self._finished:
            return
        self._finished = True
        if not self._reserved:
            log.info(
                "usage_unmetered_cost",
                action=self.ctx.request.action.value,
                cost_usd=str(cost_usd),
                exempt=self.ctx.exempt,
            )
            return
        meter = self._live_meter()
        now = meter.now()
        try:
            with meter.sessionmaker.begin() as session:
                ledger = UsageLedger(session)
                if settle:
                    # The single settle point (plan deviation 12). Hooks run in the settle's
                    # transaction, each in its own savepoint.
                    settled_job = ledger.settle(self.job_id, actual_cost_usd=cost_usd, now=now)
                    if settled_job.status is UsageJobStatus.settled:
                        run_post_settle_hooks(session, settled_job, list(self.ctx.chain), now)
                else:
                    ledger.release(self.job_id, now=now)
        except Exception:
            # The work has finished; metering must not turn it into a failure. The sweeper
            # expires a job left open, and the cost is in this line for the margin view.
            log.exception(
                "usage_finish_failed",
                job_id=str(self.job_id),
                settle=settle,
                cost_usd=str(cost_usd),
            )


class UsageMeter:
    """Authorize, estimate and reserve metered jobs against the usage ledger."""

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        *,
        enforce: bool = True,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.sessionmaker = sessionmaker
        self._enforce = enforce
        self._now = now

    def now(self) -> datetime:
        return self._now()

    def _exempt(self, request: UsageRequest) -> bool:
        return not self._enforce or request.actor_role in EXEMPT_ROLES

    def _evaluate(self, session: Session, request: UsageRequest, now: datetime) -> _Evaluation:
        params = current_estimator(session, request.action, now=now)
        rate_version = current_rate_version(session, request.action, now=now)
        estimate = estimate_range(params, clamp_inputs(request.input_count))
        ledger = UsageLedger(session)
        subjects = (
            candidate_subjects(session, actor_user_id=request.actor_user_id, action=request.action)
            if request.subject_pending
            else [request.subject_code]
        )
        best: _Evaluation | None = None
        for subject in subjects:
            chain_ctx = load_chain_context(
                session,
                actor_user_id=request.actor_user_id,
                action=request.action,
                subject_code=subject,
                assistant_member_id=request.assistant_member_id,
                now=now,
            )
            chain = tuple(build_payer_chain(chain_ctx))
            available = ledger.available(chain, now=now)
            if best is None or available > best.available:
                best = _Evaluation(params, rate_version, estimate, chain_ctx, chain, available)
        if best is None:
            raise RuntimeError("candidate_subjects returned no subject")
        return best

    def authorize(self, request: UsageRequest) -> UsageGrantContext:
        """Check the chain covers ``estimate_high``. Raises :class:`UsageBlocked`."""
        if self._exempt(request):
            return UsageGrantContext.exempt_for(request)
        now = self._now()
        with self.sessionmaker.begin() as session:
            ev = self._evaluate(session, request, now)
            reason = (
                None
                if ev.available >= ev.estimate[1]
                else block_reason(load_block_facts(session, ev.chain_ctx, ev.chain, now=now))
            )
        if reason is not None:
            raise UsageBlocked(reason, ev.estimate)
        return UsageGrantContext(
            request=request,
            chain=ev.chain,
            estimate=ev.estimate,
            estimator_version=ev.estimator.version,
            rate_version=ev.rate_version,
            teacher_member_id=job_teacher_member_id(ev.chain),
        )

    def reason_for(self, request: UsageRequest) -> UsageBlockReason:
        """The block reason against fresh facts (after a lost reservation race)."""
        now = self._now()
        with self.sessionmaker.begin() as session:
            ev = self._evaluate(session, request, now)
            return block_reason(load_block_facts(session, ev.chain_ctx, ev.chain, now=now))

    def estimate(self, request: UsageRequest) -> EstimateView:
        """The range, the scope that would pay first, and a block reason if any. No writes
        beyond seeding missing catalogue defaults."""
        if self._exempt(request):
            return EstimateView(0, 0, "none", None, None, None)
        now = self._now()
        with self.sessionmaker.begin() as session:
            ev = self._evaluate(session, request, now)
            ledger = UsageLedger(session)
            payer = next((p for p in ev.chain if ledger.available([p], now=now) > 0), None)
            units = (
                allowance_units(session, payer, now=now)
                if payer is not None and payer.scope is not GrantScope.CREDITS
                else None
            )
            blocked = (
                None
                if ev.available >= ev.estimate[1]
                else block_reason(load_block_facts(session, ev.chain_ctx, ev.chain, now=now))
            )
        low, high = ev.estimate
        return EstimateView(
            low=low,
            high=high,
            payer="none" if payer is None else payer.scope.value,
            percent_low=_ceil_div(100 * low, units) if units else None,
            percent_high=_ceil_div(100 * high, units) if units else None,
            blocked_reason=blocked,
        )

    def reserve(self, ctx: UsageGrantContext) -> MeteredJob:
        """Hold the estimate now (a deferred-subject job holds in ``bind_subject``)."""
        job = MeteredJob(self, ctx, uuid.uuid4())
        if not ctx.exempt and not ctx.request.subject_pending:
            job._reserve()
        return job

    @contextlib.contextmanager
    def job(self, ctx: UsageGrantContext) -> Iterator[MeteredJob]:
        """Reserve and run in one block, for a synchronous route."""
        metered = self.reserve(ctx)
        with metered.run():
            yield metered

    def resolve_target(self, fn: Callable[[Session], UsageTarget | None]) -> UsageTarget | None:
        """Read an action's server-side target. Without enforcement, reads nothing."""
        if not self._enforce:
            return UsageTarget(subject_code=None, input_count=0)
        with self.sessionmaker() as session:
            return fn(session)

    def read(self, fn: Callable[[Session], T]) -> T:
        """Run a read-only query (the meter and history views)."""
        with self.sessionmaker() as session:
            return fn(session)


def get_usage_meter(settings: Annotated[Settings, Depends(get_settings)]) -> UsageMeter:
    """The request's meter. Building it opens no connection (the engine is lazy)."""
    return UsageMeter(get_sessionmaker(settings), enforce=settings.usage.enforce)


def request_from_auth(
    auth: AuthContext,
    action: MeteredAction,
    *,
    subject_code: str | None = None,
    input_count: int = 0,
    assistant_member_id: uuid.UUID | None = None,
    subject_pending: bool = False,
) -> UsageRequest:
    """A :class:`UsageRequest` for the authenticated caller."""
    return UsageRequest(
        actor_user_id=uuid.UUID(auth.user_id),
        actor_role=Role(auth.role),
        action=action,
        subject_code=subject_code,
        input_count=input_count,
        assistant_member_id=assistant_member_id,
        subject_pending=subject_pending,
    )


def request_from_team(
    actor: TeamActor,
    action: MeteredAction,
    *,
    subject_code: str | None = None,
    input_count: int = 0,
) -> UsageRequest:
    """A :class:`UsageRequest` for a team route (R4): an assistant bills the lead.

    ``actor.member_id`` is the assistant's row, so the chain is the lead's allowance, then the
    lead's credits, within the assistant's cap; the assistant's own balance is never in it.
    ``actor.auth`` is the lead's context (role ``teacher``) for an assistant, else the
    caller's own, so ``actor_role`` is the caller's real role when acting as themselves.
    """
    return UsageRequest(
        actor_user_id=actor.actor_user_id,
        actor_role=Role(actor.auth.role),
        action=action,
        subject_code=subject_code,
        input_count=input_count,
        assistant_member_id=actor.member_id,
    )


def _no_target() -> UsageTarget:
    return UsageTarget(subject_code=None, input_count=0)


def require_usage(
    action: MeteredAction,
    *,
    target: Callable[..., UsageTarget] | None = None,
    team: Callable[..., TeamActor] | None = None,
) -> Callable[..., UsageGrantContext]:
    """A dependency that authorizes ``action`` for the caller (402 when blocked).

    ``target`` is a dependency returning the server-side :class:`UsageTarget` (subject and
    countable inputs). ``team`` is the route's own ``require_team_permission(...)`` guard
    (the same object, so FastAPI resolves it once per request): with it, an assistant's
    usage is charged to the lead teacher (R4). Declare the returned dependency *after* the
    route's role or team guard so a wrong role is still a 403 before any database read.
    """
    resolver = target or _no_target

    def _usage(
        meter: UsageMeter, resolved: UsageTarget, who: AuthContext | TeamActor
    ) -> UsageGrantContext:
        if isinstance(who, TeamActor):
            request = request_from_team(
                who, action, subject_code=resolved.subject_code, input_count=resolved.input_count
            )
        else:
            request = request_from_auth(
                who, action, subject_code=resolved.subject_code, input_count=resolved.input_count
            )
        return meter.authorize(request)

    # Built as objects, not source annotations: under `from __future__ import annotations`
    # FastAPI evaluates string annotations against module globals, where the closure's
    # `resolver` and `team` do not exist.
    keyword = inspect.Parameter.KEYWORD_ONLY
    who = (
        Annotated[TeamActor, Depends(team)]
        if team is not None
        else Annotated[AuthContext, Depends(get_auth_context)]
    )
    _usage.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        parameters=[
            inspect.Parameter("who", keyword, annotation=who),
            inspect.Parameter(
                "meter", keyword, annotation=Annotated[UsageMeter, Depends(get_usage_meter)]
            ),
            inspect.Parameter(
                "resolved", keyword, annotation=Annotated[UsageTarget, Depends(resolver)]
            ),
        ],
        return_annotation=UsageGrantContext,
    )
    return _usage
```

Add `import inspect` to the module's standard-library imports, change the deps import to `from lemely.web.deps import AuthContext, TeamActor, get_auth_context, get_settings`, and add `UsageJobStatus` to the runtime imports (`from lemely.db.models.usage import UsageJobStatus`).

Add the post-settle hook registry directly after `T = TypeVar("T")`. Its names and signatures are the ones plan 06 Task 7 tests (`tests/test_usage_post_settle_hooks.py`), so phase 06 only registers its hook:

```python
#: Called after a job settles, in the settle's transaction (Paymob billing phase 06 registers
#: the auto top-up hook in ``create_app``).
PostSettleHook = Callable[["Session", "UsageJob", Sequence["Payer"], datetime], None]
_POST_SETTLE_HOOKS: list[PostSettleHook] = []


def register_post_settle_hook(hook: PostSettleHook) -> None:
    """Add ``hook`` once. ``create_app`` registers the billing hooks at startup."""
    if hook not in _POST_SETTLE_HOOKS:
        _POST_SETTLE_HOOKS.append(hook)


def clear_post_settle_hooks() -> None:
    """Remove every hook (tests)."""
    _POST_SETTLE_HOOKS.clear()


def run_post_settle_hooks(
    session: Session, job: UsageJob, payers: Sequence[Payer], now: datetime
) -> None:
    """Run each hook in its own savepoint. A failing hook is logged and never undoes the settle."""
    for hook in tuple(_POST_SETTLE_HOOKS):
        try:
            with session.begin_nested():
                hook(session, job, payers, now)
        except Exception:
            log.warning(
                "post_settle_hook_failed",
                hook=getattr(hook, "__name__", repr(hook)),
                exc_info=True,
            )
```

`PostSettleHook` is evaluated at runtime, so `Callable` and `Sequence` must be runtime imports (`from collections.abc import Callable, Iterator, Sequence`, moved out of `TYPE_CHECKING`), and its inner names stay string forward references. Add `from lemely.db.models.usage import UsageJob` under `TYPE_CHECKING`.

- [ ] **Step 5: Register the handler**

In `lemely/web/app.py`, add `from lemely.web.usage import UsageBlocked, usage_blocked_handler` to the imports. In `create_app`, directly after the last `app.include_router(...)` line and before the `@app.exception_handler(EmptyGradeBoundaryStoreError)` block, add:

```python
    # Billing spec §5.7: a blocked metered action is a top-level 402 body, not `detail`.
    app.add_exception_handler(UsageBlocked, usage_blocked_handler)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_web_usage_meter.py tests/test_settings_example_drift.py tests/test_runtime_config.py tests/architecture/ -v --no-cov`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/web/usage.py lemely/runtime/config.py lemely/web/app.py tests/conftest.py tests/usage_helpers.py tests/test_web_usage_meter.py
git commit -S -m "feat(usage): UsageMeter, metered jobs across threads, require_usage and the 402 contract" -- lemely/web/usage.py lemely/runtime/config.py lemely/web/app.py tests/conftest.py tests/usage_helpers.py tests/test_web_usage_meter.py
```

---

### Task 7: Usage API: estimate, meter, history

**Files:**
- Create: `lemely/db/usage_views_repo.py`
- Create: `lemely/web/schemas_usage.py`
- Create: `lemely/web/routers/usage.py`
- Modify: `lemely/web/app.py`: import `usage` from `lemely.web.routers` and `app.include_router(usage.router)` after `admin_tutoring_reports.router`
- Modify: `tests/test_authz_matrix_complete.py`: three `AUTH_ANY` rows; heading `# ── AUTH_ANY (19)` becomes `# ── AUTH_ANY (22)`
- Test: `tests/test_web_usage_routes.py`

**Interfaces:**
- Consumes: `UsageMeter`, `request_from_auth`, `get_usage_meter`, `EstimateView` (Task 6); `self_review_target`, `quiz_assignment_target` (Task 5); `ACTING_TEACHER_HEADER`, `TeamPermission`, `assistant_has_permission(session, assistant_user_id, lead_teacher_user_id, perm) -> TeacherMember | None` (phase 03); `UsageLedger.meter_fraction` (phase 01); `encode_cursor`, `decode_cursor`, `CursorError` (`lemely/core/keyset.py`); `SlidingWindowLimiter` (`lemely/web/ratelimit.py`).
- Produces:
  - `lemely/db/usage_views_repo.py`: `CreditLot(remaining: int, expires_at: datetime | None)`, `SeatMeter(teacher_member_id: UUID, teacher_user_id: UUID, fraction: float | None, resets_at: datetime | None)`, `MeterView(allowance_fraction, allowance_resets_at, credits_balance: int, credit_lots: list[CreditLot], seats: list[SeatMeter], debt_units: int)`, `HistoryRow(row_id, job_id, action, status, actor_user_id, created_at, settled_at, paid_by, percent_of_plan, credits, debt_credits, estimate_percent_of_plan, estimate_credits)` (hidden-allowance display: allowance and seat portions only as a percentage of that grant, never as units), `meter_view(session, *, user_id, now) -> MeterView`, `history_page(session, *, user_id, limit, after: tuple[datetime, UUID] | None) -> list[HistoryRow]`
  - Routes: `POST /api/usage/estimate` → `EstimateDTO`; `GET /api/usage/meter` → `UsageMeterDTO`; `GET /api/usage/history?limit&cursor` → `UsageHistoryDTO`. All authenticated, any role (`AUTH_ANY`). Estimate is rate-limited to 60 per user per minute (429 with `Retry-After`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_web_usage_routes.py
"""The usage API (Task 7): estimate from server-side records, meter, history."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from lemely.core.metered_actions import MeteredAction
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind
from lemely.io.llm.cost_meter import record_llm_cost
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context
from lemely.web.usage import get_usage_meter, request_from_auth
from tests.usage_helpers import (
    NOW,
    enforcing_meter,
    give,
    seat,
    seat_grant,
    seed_catalogue,
    seed_user,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def api(migrated_sessionmaker: sessionmaker[Session]) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_usage_meter] = lambda: enforcing_meter(migrated_sessionmaker)
    seed_catalogue(migrated_sessionmaker)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(api: TestClient, user: uuid.UUID, role: Role = Role.student) -> None:
    api.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user), role=role.value
    )


def test_estimate_quotes_credits_and_the_range(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    student = seed_user(migrated_sessionmaker)
    give(migrated_sessionmaker, student, units=1000)
    _as(api, student)
    resp = api.post("/api/usage/estimate", json={"action": "generate_flashcards", "subjectCode": "0625", "count": 4})
    assert resp.status_code == 200, resp.text
    # base 2-4 + 4 cards x 1-2 = 6-12
    assert resp.json() == {
        "low": 6, "high": 12, "payer": "credits",
        "percentLow": None, "percentHigh": None, "blockedReason": None,
    }


def test_estimate_quotes_a_percentage_when_an_allowance_pays(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    student = seed_user(migrated_sessionmaker)
    give(migrated_sessionmaker, student, units=4000, kind=GrantKind.period_allowance, visible=False,
         expires_at=datetime(2026, 12, 1, tzinfo=UTC))
    _as(api, student)
    body = api.post("/api/usage/estimate", json={"action": "mark_paper"}).json()
    assert (body["payer"], body["percentLow"], body["percentHigh"]) == ("allowance", 1, 3)


def test_estimate_reports_a_block_without_raising(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    student = seed_user(migrated_sessionmaker)
    _as(api, student)
    body = api.post("/api/usage/estimate", json={"action": "mark_paper"}).json()
    assert (body["payer"], body["blockedReason"]) == ("none", "no_active_plan")


def test_an_assistants_estimate_is_quoted_against_the_lead(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """R4: the acting-teacher header quotes team work against the lead's chain."""
    from lemely.web.deps import ACTING_TEACHER_HEADER
    from tests.usage_helpers import assistant

    sm = migrated_sessionmaker
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    give(sm, helper, units=1000)
    assistant(sm, teacher=lead, member=helper)
    _as(api, helper, Role.teacher)
    headers = {ACTING_TEACHER_HEADER: str(lead)}
    body = api.post("/api/usage/estimate", json={"action": "regrade"}, headers=headers).json()
    assert (body["payer"], body["blockedReason"]) == ("none", "no_active_plan")
    own = api.post("/api/usage/estimate", json={"action": "regrade"}).json()
    assert own["payer"] == "credits"
    # Student actions carry no team permission: the header is refused, not ignored.
    study = {"action": "study_plan", "subjectCode": "0580"}
    assert api.post("/api/usage/estimate", json=study, headers=headers).status_code == 403


def test_a_viewer_assistant_cannot_estimate_for_the_lead(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """A viewer lacks `regrade`, so it gets the route's 403, not the lead's balance."""
    from lemely.db.models.team import AssistantRole
    from lemely.web.deps import ACTING_TEACHER_HEADER
    from tests.usage_helpers import assistant

    sm = migrated_sessionmaker
    lead, viewer = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    give(sm, lead, units=1000)
    assistant(sm, teacher=lead, member=viewer, role=AssistantRole.viewer)
    _as(api, viewer, Role.teacher)
    resp = api.post(
        "/api/usage/estimate", json={"action": "regrade"}, headers={ACTING_TEACHER_HEADER: str(lead)}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "team_permission_denied"


def test_estimate_requires_the_fields_its_action_reads(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    _as(api, seed_user(migrated_sessionmaker))
    assert api.post("/api/usage/estimate", json={"action": "generate_flashcards"}).status_code == 422
    assert api.post("/api/usage/estimate", json={"action": "self_review"}).status_code == 422
    unknown = {"action": "mark_quiz", "assignmentId": str(uuid.uuid4())}
    assert api.post("/api/usage/estimate", json=unknown).status_code == 404


def test_estimate_is_rate_limited(api: TestClient, migrated_sessionmaker: sessionmaker[Session]) -> None:
    _as(api, seed_user(migrated_sessionmaker))
    codes = [api.post("/api/usage/estimate", json={"action": "study_plan", "subjectCode": "0580"}).status_code
             for _ in range(61)]
    assert codes[:60] == [200] * 60
    assert codes[60] == 429


def test_meter_shows_allowance_credits_seats_and_debt(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    give(sm, student, units=300, expires_at=datetime(2027, 6, 1, tzinfo=UTC))
    give(sm, student, units=200)
    member = seat(sm, teacher=teacher, student=student, subjects=["0580"], actions=[MeteredAction.MARK_PAPER])
    seat_grant(sm, student=student, member_id=member, units=100)
    _as(api, student)
    body = api.get("/api/usage/meter").json()
    assert body["creditsBalance"] == 500
    assert [lot["remaining"] for lot in body["creditLots"]] == [300, 200]
    assert body["seats"][0]["teacherMemberId"] == str(member)
    assert body["seats"][0]["fraction"] == 0.0
    assert body["debtUnits"] == 0


def test_history_never_shows_allowance_units(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """Spec §2.1: the allowance is hidden. Allowance portions are a percentage of the plan,
    credits portions are credits, and no allowance unit count reaches the client."""
    sm = migrated_sessionmaker
    meter = enforcing_meter(sm)

    def run(user: uuid.UUID, cost: str) -> None:
        auth = AuthContext(user_id=str(user), role="student")
        with meter.job(meter.authorize(request_from_auth(auth, MeteredAction.MARK_PAPER))):
            record_llm_cost(Decimal(cost))

    planned, paying, both = seed_user(sm), seed_user(sm), seed_user(sm)
    give(sm, planned, units=4000, kind=GrantKind.period_allowance, visible=False,
         expires_at=datetime(2026, 12, 1, tzinfo=UTC))
    give(sm, paying, units=1000)
    give(sm, both, units=100, kind=GrantKind.period_allowance, visible=False,
         expires_at=datetime(2026, 12, 1, tzinfo=UTC))
    give(sm, both, units=1000)
    run(planned, "0.040")  # 40 of a 4000-unit allowance
    run(paying, "0.030")  # 30 credits
    run(both, "0.150")  # all 100 allowance units, then 50 credits

    _as(api, planned)
    raw = api.get("/api/usage/history").text
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert (row["paidBy"], row["percentOfPlan"], row["credits"]) == ("allowance", 1.0, None)
    assert (row["estimatePercentOfPlan"], row["estimateCredits"]) == ([1.0, 3.0], None)
    for key in ("charged", "estimateLow", "estimateHigh", '"units"'):
        assert key not in raw
    # An allowance-paid row carries no integer at all: no units, no allowance size.
    assert [v for v in row.values() if isinstance(v, int) and not isinstance(v, bool)] == []

    _as(api, paying)
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert (row["paidBy"], row["percentOfPlan"], row["credits"]) == ("credits", None, 30)
    assert (row["estimatePercentOfPlan"], row["estimateCredits"]) == (None, [40, 120])

    _as(api, both)
    (row,) = api.get("/api/usage/history").json()["jobs"]
    assert (row["paidBy"], row["percentOfPlan"], row["credits"]) == ("mixed", 100.0, 50)
    assert row["estimatePercentOfPlan"] == [40.0, 120.0]


def test_history_pages_newest_first_and_includes_seat_jobs_for_the_teacher(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    sm = migrated_sessionmaker
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    member = seat(sm, teacher=teacher, student=student, subjects=["0580"], actions=[MeteredAction.MARK_PAPER])
    seat_grant(sm, student=student, member_id=member, units=1000)
    meter = enforcing_meter(sm)
    auth = AuthContext(user_id=str(student), role="student")
    for cost in ("0.010", "0.020", "0.030"):
        with meter.job(meter.authorize(request_from_auth(auth, MeteredAction.MARK_PAPER, subject_code="0580"))):
            record_llm_cost(Decimal(cost))
    _as(api, student)
    first = api.get("/api/usage/history", params={"limit": 2}).json()
    assert [(j["paidBy"], j["percentOfPlan"]) for j in first["jobs"]] == [("seat", 3.0), ("seat", 2.0)]
    second = api.get("/api/usage/history", params={"limit": 2, "cursor": first["nextCursor"]}).json()
    assert [j["percentOfPlan"] for j in second["jobs"]] == [1.0]
    assert second["nextCursor"] is None
    _as(api, teacher, Role.teacher)
    seen = api.get("/api/usage/history").json()["jobs"]
    assert {j["actorUserId"] for j in seen} == {str(student)}
    assert api.get("/api/usage/history", params={"cursor": "garbage"}).status_code == 422
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_web_usage_routes.py -v --no-cov`
Expected: FAIL with 404s on `/api/usage/*` (router not mounted) or `ImportError`.

- [ ] **Step 3: Write the view queries**

```python
# lemely/db/usage_views_repo.py
"""Read models for the usage meter and usage history (billing spec §2.1, §2.4)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import func, or_, select, tuple_

from lemely.db.models.team import TeacherMember, TeacherMemberKind, TeacherMemberStatus
from lemely.db.models.usage import (
    GrantKind,
    UsageDebt,
    UsageEntry,
    UsageEntryKind,
    UsageGrant,
    UsageGrantBalance,
    UsageJob,
)
from lemely.db.usage_ledger_repo import UsageLedger

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from sqlalchemy.sql import ColumnElement


@dataclass(frozen=True)
class CreditLot:
    remaining: int
    expires_at: datetime | None


@dataclass(frozen=True)
class SeatMeter:
    teacher_member_id: uuid.UUID
    teacher_user_id: uuid.UUID
    fraction: float | None
    resets_at: datetime | None


@dataclass(frozen=True)
class MeterView:
    allowance_fraction: float | None
    allowance_resets_at: datetime | None
    credits_balance: int
    credit_lots: list[CreditLot]
    seats: list[SeatMeter]
    debt_units: int


PaidBy = Literal["allowance", "seat", "credits", "teacher_credits", "mixed", "none"]


@dataclass(frozen=True)
class HistoryRow:
    """One job, displayed without allowance unit counts (spec §2.1 hidden allowance).

    Allowance and seat portions are a percentage of the grant they drew on; credits
    portions (own or a teacher's) are credit units. ``paid_by`` is ``none`` for a job that
    charged nothing (open, released, expired, or settled at 0).
    """

    row_id: uuid.UUID
    job_id: uuid.UUID
    action: str
    status: str
    actor_user_id: uuid.UUID
    created_at: datetime
    settled_at: datetime | None
    paid_by: PaidBy
    percent_of_plan: float | None
    credits: int | None
    debt_credits: int | None
    estimate_percent_of_plan: tuple[float, float] | None
    estimate_credits: tuple[int, int] | None


def _portion(kind: GrantKind, visible: bool, owner: uuid.UUID, actor: uuid.UUID) -> str:
    """Which display bucket a grant belongs to, from the job actor's point of view."""
    if kind is GrantKind.seat_allowance:
        return "seat"
    if not visible:
        return "allowance"
    return "credits" if owner == actor else "teacher_credits"


def _percent(units: int, of: int) -> float:
    return round(100 * units / of, 1)


def _live(now: datetime) -> ColumnElement[bool]:
    return or_(UsageGrant.expires_at.is_(None), UsageGrant.expires_at > now)


def meter_view(session: Session, *, user_id: uuid.UUID, now: datetime) -> MeterView:
    """The caller's allowance meter, credit lots by expiry, seat meters and debt."""
    ledger = UsageLedger(session)
    allowance_resets_at = session.scalar(
        select(func.min(UsageGrant.expires_at)).where(
            UsageGrant.owner_user_id == user_id,
            UsageGrant.kind == GrantKind.period_allowance,
            UsageGrant.expires_at > now,
        )
    )
    spendable = UsageGrantBalance.remaining - UsageGrantBalance.held
    lots = [
        CreditLot(remaining=int(remaining), expires_at=expires_at)
        for remaining, expires_at in session.execute(
            select(spendable, UsageGrant.expires_at)
            .join(UsageGrant, UsageGrant.id == UsageGrantBalance.grant_id)
            .where(
                UsageGrant.owner_user_id == user_id,
                UsageGrant.visible.is_(True),
                _live(now),
                spendable > 0,
            )
            .order_by(UsageGrant.expires_at.asc().nulls_last(), UsageGrant.id)
        )
    ]
    seats = []
    for member in session.scalars(
        select(TeacherMember)
        .where(
            TeacherMember.member_user_id == user_id,
            TeacherMember.kind == TeacherMemberKind.student_seat,
            TeacherMember.status.in_((TeacherMemberStatus.active, TeacherMemberStatus.leaving)),
        )
        .order_by(TeacherMember.created_at, TeacherMember.id)
    ):
        resets_at = session.scalar(
            select(func.max(UsageGrant.expires_at)).where(
                UsageGrant.owner_user_id == user_id,
                UsageGrant.kind == GrantKind.seat_allowance,
                UsageGrant.teacher_member_id == member.id,
                UsageGrant.expires_at > now,
            )
        )
        seats.append(
            SeatMeter(
                teacher_member_id=member.id,
                teacher_user_id=member.teacher_user_id,
                fraction=ledger.meter_fraction(user_id, teacher_member_id=member.id, now=now),
                resets_at=resets_at,
            )
        )
    debt = session.scalar(
        select(func.coalesce(func.sum(UsageDebt.outstanding), 0)).where(
            UsageDebt.owner_user_id == user_id
        )
    )
    return MeterView(
        allowance_fraction=ledger.meter_fraction(user_id, teacher_member_id=None, now=now),
        allowance_resets_at=allowance_resets_at,
        credits_balance=sum(lot.remaining for lot in lots),
        credit_lots=lots,
        seats=seats,
        debt_units=int(debt or 0),
    )


def history_page(
    session: Session,
    *,
    user_id: uuid.UUID,
    limit: int,
    after: tuple[datetime, uuid.UUID] | None,
) -> list[HistoryRow]:
    """Jobs the caller ran, plus jobs run under their seats and assistants, newest first."""
    members = select(TeacherMember.id).where(TeacherMember.teacher_user_id == user_id)
    stmt = select(UsageJob).where(
        or_(UsageJob.actor_user_id == user_id, UsageJob.teacher_member_id.in_(members))
    )
    if after is not None:
        stmt = stmt.where(tuple_(UsageJob.created_at, UsageJob.id) < tuple_(after[0], after[1]))
    stmt = stmt.order_by(UsageJob.created_at.desc(), UsageJob.id.desc()).limit(limit)
    jobs = list(session.scalars(stmt))
    # Per-grant settle and hold amounts for these jobs, with the grant's bucket inputs.
    entries = session.execute(
        select(
            UsageEntry.job_id,
            UsageEntry.kind,
            UsageEntry.units,
            UsageEntry.event_at,
            UsageGrant.kind,
            UsageGrant.visible,
            UsageGrant.owner_user_id,
            UsageGrant.units,
        )
        .join(UsageGrant, UsageGrant.id == UsageEntry.grant_id)
        .where(
            UsageEntry.job_id.in_([job.job_id for job in jobs]),
            UsageEntry.kind.in_((UsageEntryKind.settle, UsageEntryKind.hold)),
        )
        .order_by(UsageEntry.event_at, UsageEntry.id)
    ).all()
    rows = []
    for job in jobs:
        mine = [e for e in entries if e[0] == job.job_id]
        percent = 0.0
        credits = 0
        buckets: set[str] = set()
        for _job_id, kind, units, _at, g_kind, visible, owner, g_units in mine:
            if kind is not UsageEntryKind.settle:
                continue
            bucket = _portion(g_kind, visible, owner, job.actor_user_id)
            buckets.add(bucket)
            if bucket in ("allowance", "seat"):
                percent += 100 * abs(units) / g_units
            else:
                credits += abs(units)
        paid_by: PaidBy = (
            "none" if not buckets else "mixed" if len(buckets) > 1 else buckets.pop()  # type: ignore[assignment]
        )
        # The estimate is shown in the terms of the grant that took the first hold.
        first_hold = next((e for e in mine if e[1] is UsageEntryKind.hold), None)
        estimate_percent: tuple[float, float] | None = None
        estimate_credits: tuple[int, int] | None = None
        if first_hold is not None and _portion(
            first_hold[4], first_hold[5], first_hold[6], job.actor_user_id
        ) in ("allowance", "seat"):
            estimate_percent = (
                _percent(job.estimate_low, first_hold[7]),
                _percent(job.estimate_high, first_hold[7]),
            )
        else:
            estimate_credits = (job.estimate_low, job.estimate_high)
        has_plan_part = paid_by in ("allowance", "seat", "mixed") and percent > 0
        has_credit_part = paid_by in ("credits", "teacher_credits", "mixed") and credits > 0
        rows.append(
            HistoryRow(
                row_id=job.id,
                job_id=job.job_id,
                action=job.action,
                status=job.status.value,
                actor_user_id=job.actor_user_id,
                created_at=job.created_at,
                settled_at=job.settled_at,
                paid_by=paid_by,
                percent_of_plan=round(percent, 1) if has_plan_part else None,
                credits=credits if has_credit_part else None,
                debt_credits=job.debt_created or None,
                estimate_percent_of_plan=estimate_percent,
                estimate_credits=estimate_credits,
            )
        )
    return rows
```

- [ ] **Step 4: Write the DTOs**

```python
# lemely/web/schemas_usage.py
"""DTOs for ``/api/usage/*`` (billing spec §2.1, §2.4, §5.7)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from lemely.core.metered_actions import MeteredAction
from lemely.web.schemas_auth import ApiModel


class EstimateRequestDTO(ApiModel):
    """Which action, and which record it would work on. The server reads the record."""

    action: MeteredAction
    attemptId: uuid.UUID | None = None
    questionResultId: uuid.UUID | None = None
    assignmentId: uuid.UUID | None = None
    subjectCode: str | None = Field(default=None, min_length=1, max_length=16)
    count: int | None = Field(default=None, ge=1, le=50)


class EstimateDTO(ApiModel):
    low: int
    high: int
    payer: Literal["seat", "allowance", "credits", "none"]
    percentLow: int | None
    percentHigh: int | None
    blockedReason: str | None


class CreditLotDTO(ApiModel):
    remaining: int
    expiresAt: datetime | None


class SeatMeterDTO(ApiModel):
    teacherMemberId: str
    teacherUserId: str
    fraction: float | None
    resetsAt: datetime | None


class UsageMeterDTO(ApiModel):
    allowanceFraction: float | None
    allowanceResetsAt: datetime | None
    creditsBalance: int
    creditLots: list[CreditLotDTO]
    seats: list[SeatMeterDTO]
    debtUnits: int


class UsageJobDTO(ApiModel):
    """One usage-history row. Never carries allowance unit counts (spec §2.1): plan and
    seat portions are ``percentOfPlan``; credit portions are ``credits``."""

    jobId: str
    action: str
    status: str
    paidBy: Literal["allowance", "seat", "credits", "teacher_credits", "mixed", "none"]
    percentOfPlan: float | None
    credits: int | None
    debtCredits: int | None
    estimatePercentOfPlan: list[float] | None
    estimateCredits: list[int] | None
    actorUserId: str
    createdAt: datetime
    settledAt: datetime | None


class UsageHistoryDTO(ApiModel):
    jobs: list[UsageJobDTO]
    nextCursor: str | None
```

- [ ] **Step 5: Write the router**

```python
# lemely/web/routers/usage.py
"""``/api/usage/*``: the estimate shown before an action, the meter, the history.

Every signed-in role may call these routes; each answers only about the caller. The
estimate never trusts client numbers for the record it describes: subjects and countable
inputs are read on the server, exactly as the metered route itself will read them.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from functools import lru_cache
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from lemely.core.keyset import CursorError, decode_cursor, encode_cursor
from lemely.core.metered_actions import MeteredAction
from lemely.db.models.enums import Role
from lemely.core.team_permissions import TeamPermission
from lemely.db.teacher_team_repo import assistant_has_permission
from lemely.db.usage_context_repo import quiz_assignment_target, self_review_target
from lemely.db.usage_views_repo import history_page, meter_view
from lemely.web.deps import ACTING_TEACHER_HEADER, AuthContext, get_auth_context
from lemely.web.ratelimit import SlidingWindowLimiter
from lemely.web.schemas_usage import (
    CreditLotDTO,
    EstimateDTO,
    EstimateRequestDTO,
    SeatMeterDTO,
    UsageHistoryDTO,
    UsageJobDTO,
    UsageMeterDTO,
)
from lemely.web.usage import UsageMeter, UsageRequest, get_usage_meter, request_from_auth

router = APIRouter(prefix="/api/usage")

_HISTORY_CURSOR = "usage_history"


@lru_cache(maxsize=1)
def get_usage_estimate_limiter() -> SlidingWindowLimiter:
    """60 estimates per user per minute (spec §7: estimates are rate-limited)."""
    return SlidingWindowLimiter(limit=60, window_seconds=60, clock=time.monotonic)


def _missing(field: str) -> NoReturn:
    raise HTTPException(status_code=422, detail=f"{field} is required for this action")


#: The team permission each team-billable action's route asks for (phase 03 adoption table).
_TEAM_PERMISSION: dict[MeteredAction, TeamPermission] = {
    MeteredAction.MARK_PAPER: TeamPermission.MARK,
    MeteredAction.REGRADE: TeamPermission.REGRADE,
    MeteredAction.GENERATE_QUIZ: TeamPermission.GENERATE_QUIZ,
    MeteredAction.PREVIEW_QUIZ: TeamPermission.GENERATE_QUIZ,
}


def _team_denied() -> HTTPException:
    # Same body as phase 03's `require_team_permission` refusal.
    return HTTPException(status_code=403, detail={"code": "team_permission_denied"})


def _acting_member(
    meter: UsageMeter, auth: AuthContext, action: MeteredAction, acting_teacher: str | None
) -> uuid.UUID | None:
    """The assistant row to bill under ``X-Lemely-Acting-Teacher``, or ``None`` (own chain).

    No header, or a header naming the caller: ``None``. Otherwise the caller must be a
    teacher holding the action's team permission under that lead; anything else (malformed
    id, an action with no team permission, a stranger, a viewer) is 403, as on the route.
    """
    if acting_teacher is None:
        return None
    try:
        lead_id = uuid.UUID(acting_teacher)
    except ValueError:
        raise _team_denied() from None
    actor_id = uuid.UUID(auth.user_id)
    if lead_id == actor_id:
        return None
    perm = _TEAM_PERMISSION.get(action)
    if perm is None or auth.role != Role.teacher.value:
        raise _team_denied()
    member = meter.read(
        lambda session: assistant_has_permission(session, actor_id, lead_id, perm)
    )
    if member is None:
        raise _team_denied()
    return member.id


def _estimate_request(
    meter: UsageMeter, auth: AuthContext, body: EstimateRequestDTO, acting_teacher: str | None
) -> UsageRequest:
    action = body.action
    role = Role(auth.role)
    # R4: an assistant's estimate for team work is quoted against the lead's chain, read
    # from the same header the metered route's `require_team_permission` reads, and only
    # when the assistant holds the permission that route asks for.
    member = _acting_member(meter, auth, action, acting_teacher)
    if action is MeteredAction.MARK_PAPER:
        return request_from_auth(
            auth, action, subject_pending=role is Role.student, assistant_member_id=member
        )
    if action is MeteredAction.REGRADE:
        return request_from_auth(auth, action, assistant_member_id=member)
    if action in (MeteredAction.PREVIEW_QUIZ, MeteredAction.GENERATE_QUIZ):
        if body.count is None:
            _missing("count")
        return request_from_auth(auth, action, input_count=body.count, assistant_member_id=member)
    if action is MeteredAction.SELF_REVIEW:
        if body.attemptId is None or body.questionResultId is None:
            _missing("attemptId and questionResultId")
        attempt_id, question_id = str(body.attemptId), str(body.questionResultId)
        target = meter.resolve_target(
            lambda session: self_review_target(
                session, student_id=auth.user_id, attempt_id=attempt_id, question_result_id=question_id
            )
        )
        if target is None:
            raise HTTPException(status_code=404, detail="No such question")
        return request_from_auth(
            auth, action, subject_code=target.subject_code, input_count=target.input_count
        )
    if action is MeteredAction.MARK_QUIZ:
        if body.assignmentId is None:
            _missing("assignmentId")
        assignment_id = str(body.assignmentId)
        target = meter.resolve_target(
            lambda session: quiz_assignment_target(session, assignment_id=assignment_id)
        )
        if target is None:
            raise HTTPException(status_code=404, detail="No such assignment")
        return request_from_auth(
            auth, action, subject_code=target.subject_code, input_count=target.input_count
        )
    if action is MeteredAction.GENERATE_FLASHCARDS:
        if body.subjectCode is None or body.count is None:
            _missing("subjectCode and count")
        return request_from_auth(auth, action, subject_code=body.subjectCode, input_count=body.count)
    if body.subjectCode is None:  # MeteredAction.STUDY_PLAN
        _missing("subjectCode")
    return request_from_auth(auth, action, subject_code=body.subjectCode)


@router.post("/estimate", response_model=EstimateDTO)
def estimate_usage(
    body: EstimateRequestDTO,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    meter: Annotated[UsageMeter, Depends(get_usage_meter)],
    limiter: Annotated[SlidingWindowLimiter, Depends(get_usage_estimate_limiter)],
    acting_teacher: Annotated[str | None, Header(alias=ACTING_TEACHER_HEADER)] = None,
) -> EstimateDTO:
    """The range the caller will see before an action ("3-5 credits" / "2-4% of your plan")."""
    if not limiter.allow(auth.user_id):
        raise HTTPException(
            status_code=429,
            detail="Too many estimates; try again shortly.",
            headers={"Retry-After": str(limiter.retry_after(auth.user_id))},
        )
    view = meter.estimate(_estimate_request(meter, auth, body, acting_teacher))
    return EstimateDTO(
        low=view.low,
        high=view.high,
        payer=view.payer,  # type: ignore[arg-type]
        percentLow=view.percent_low,
        percentHigh=view.percent_high,
        blockedReason=view.blocked_reason.value if view.blocked_reason is not None else None,
    )


@router.get("/meter", response_model=UsageMeterDTO)
def usage_meter(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    meter: Annotated[UsageMeter, Depends(get_usage_meter)],
) -> UsageMeterDTO:
    """The caller's allowance meter, credits with expiry breakdown, seat meters and debt."""
    user_id, now = uuid.UUID(auth.user_id), meter.now()
    view = meter.read(lambda session: meter_view(session, user_id=user_id, now=now))
    return UsageMeterDTO(
        allowanceFraction=view.allowance_fraction,
        allowanceResetsAt=view.allowance_resets_at,
        creditsBalance=view.credits_balance,
        creditLots=[CreditLotDTO(remaining=l.remaining, expiresAt=l.expires_at) for l in view.credit_lots],
        seats=[
            SeatMeterDTO(
                teacherMemberId=str(s.teacher_member_id),
                teacherUserId=str(s.teacher_user_id),
                fraction=s.fraction,
                resetsAt=s.resets_at,
            )
            for s in view.seats
        ],
        debtUnits=view.debt_units,
    )


@router.get("/history", response_model=UsageHistoryDTO)
def usage_history(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    meter: Annotated[UsageMeter, Depends(get_usage_meter)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
) -> UsageHistoryDTO:
    """Each job with its estimate range and actual charge (spec §2.4: no usage receipts)."""
    after: tuple[datetime, uuid.UUID] | None = None
    if cursor is not None:
        try:
            created_at, row_id = decode_cursor(cursor, endpoint=_HISTORY_CURSOR, types=(datetime, uuid.UUID))
        except CursorError as exc:
            raise HTTPException(status_code=422, detail="Invalid cursor") from exc
        after = (created_at, row_id)  # type: ignore[assignment]
    user_id = uuid.UUID(auth.user_id)
    rows = meter.read(lambda session: history_page(session, user_id=user_id, limit=limit + 1, after=after))
    page = rows[:limit]
    next_cursor = (
        encode_cursor(_HISTORY_CURSOR, [page[-1].created_at, page[-1].row_id])
        if len(rows) > limit
        else None
    )
    return UsageHistoryDTO(
        jobs=[
            UsageJobDTO(
                jobId=str(r.job_id),
                action=r.action,
                status=r.status,
                paidBy=r.paid_by,
                percentOfPlan=r.percent_of_plan,
                credits=r.credits,
                debtCredits=r.debt_credits,
                estimatePercentOfPlan=(
                    list(r.estimate_percent_of_plan) if r.estimate_percent_of_plan else None
                ),
                estimateCredits=list(r.estimate_credits) if r.estimate_credits else None,
                actorUserId=str(r.actor_user_id),
                createdAt=r.created_at,
                settledAt=r.settled_at,
            )
            for r in page
        ],
        nextCursor=next_cursor,
    )
```

Rename the comprehension variable `l` to `lot` if ruff flags E741.

- [ ] **Step 6: Mount the router and declare the routes**

In `lemely/web/app.py`, add `usage` to the `from lemely.web.routers import (...)` list and `app.include_router(usage.router)` after `app.include_router(admin_tutoring_reports.router)`.

In `tests/test_authz_matrix_complete.py`, change `# ── AUTH_ANY (19) ────────────────────` to `# ── AUTH_ANY (22) ────────────────────` and add under it:

```python
    # Billing phase 04: usage estimate, meter and history answer only about the caller.
    ("POST", "/api/usage/estimate"): AUTH_ANY,
    ("GET", "/api/usage/meter"): AUTH_ANY,
    ("GET", "/api/usage/history"): AUTH_ANY,
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_web_usage_routes.py tests/test_authz_matrix_complete.py -v --no-cov`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/db/usage_views_repo.py lemely/web/schemas_usage.py lemely/web/routers/usage.py lemely/web/app.py tests/test_authz_matrix_complete.py tests/test_web_usage_routes.py
git commit -S -m "feat(usage): estimate, meter and history API" -- lemely/db/usage_views_repo.py lemely/web/schemas_usage.py lemely/web/routers/usage.py lemely/web/app.py tests/test_authz_matrix_complete.py tests/test_web_usage_routes.py
```

---

### Task 8: Free allowances on the first email verification

**Files:**
- Modify: `lemely/auth/mirror.py`: `DbUserMirror.mark_email_verified` (lines 194-205)
- Test: `tests/test_usage_signup.py`

**Interfaces:**
- Consumes: `grant_signup_allowance` (Task 4); `db_settings` fixture from `tests/test_email_verified_first_timestamp.py`.
- Produces: no new names. Every verification path (`AuthService.verify_email`, `verify_email_code`, `signup(email_verified=True)` and the dev seed) goes through `mark_email_verified`. The first time it stamps `users.email_verified_at`, it issues the role's signup grant in the same transaction, inside a savepoint so a billing failure can never fail a verification.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_usage_signup.py
"""Spec §2.1 free start: the first verification issues the signup grant, once (Task 8)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from lemely.auth import mirror as mirror_module
from lemely.auth.mirror import DbUserMirror
from lemely.db.models import User
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind, UsageGrant
from tests import test_email_verified_first_timestamp as _verified

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.runtime.config import Settings

# Re-exported by attribute (see tests/test_student_self_review_web.py for why).
db_settings = _verified.db_settings

FIRST = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)


def _seed(factory: sessionmaker[Session], role: Role) -> uuid.UUID:
    uid = uuid.uuid4()
    with factory.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role))
    return uid


def _grants(factory: sessionmaker[Session], user: uuid.UUID) -> list[UsageGrant]:
    with factory() as session:
        return list(session.scalars(select(UsageGrant).where(UsageGrant.owner_user_id == user)))


def test_student_gets_one_hidden_allowance_on_first_verification(
    db_settings: tuple[Settings, sessionmaker[Session]],
) -> None:
    settings, factory = db_settings
    student = _seed(factory, Role.student)
    mirror = DbUserMirror(settings)
    mirror.mark_email_verified(student, verified_at=FIRST)
    mirror.mark_email_verified(student, verified_at=FIRST)
    (grant,) = _grants(factory, student)
    assert (grant.kind, grant.visible, grant.units, grant.expires_at) == (
        GrantKind.signup, False, 250, None
    )


def test_teacher_gets_thirty_day_visible_credits(
    db_settings: tuple[Settings, sessionmaker[Session]],
) -> None:
    settings, factory = db_settings
    teacher = _seed(factory, Role.teacher)
    DbUserMirror(settings).mark_email_verified(teacher, verified_at=FIRST)
    (grant,) = _grants(factory, teacher)
    assert grant.visible is True
    assert grant.units == 2000
    assert grant.expires_at == datetime(2026, 12, 4, 9, 0, tzinfo=UTC)


def test_parents_get_nothing_and_unknown_users_are_a_no_op(
    db_settings: tuple[Settings, sessionmaker[Session]],
) -> None:
    settings, factory = db_settings
    parent = _seed(factory, Role.parent)
    mirror = DbUserMirror(settings)
    mirror.mark_email_verified(parent, verified_at=FIRST)
    mirror.mark_email_verified(uuid.uuid4(), verified_at=FIRST)
    assert _grants(factory, parent) == []


def test_a_billing_failure_never_fails_the_verification(
    db_settings: tuple[Settings, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, factory = db_settings
    student = _seed(factory, Role.student)

    def _boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("ledger down")

    monkeypatch.setattr(mirror_module, "grant_signup_allowance", _boom)
    DbUserMirror(settings).mark_email_verified(student, verified_at=FIRST)
    with factory() as session:
        stamped = session.scalar(select(User.email_verified_at).where(User.id == student))
    assert stamped == FIRST
    assert _grants(factory, student) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_signup.py -v --no-cov`
Expected: the grant assertions fail (`ValueError: not enough values to unpack (expected 1, got 0)`). The no-op test passes. `test_a_billing_failure_never_fails_the_verification` fails with `AttributeError: ... has no attribute 'grant_signup_allowance'`.

- [ ] **Step 3: Issue the grant in the verification transaction**

In `lemely/auth/mirror.py`, add:

```python
import structlog

from lemely.db.usage_catalogue_repo import grant_signup_allowance
```

and a module logger `log = structlog.get_logger(__name__)` if the module has none. Replace `mark_email_verified` with:

```python
    def mark_email_verified(self, user_id: uuid.UUID, *, verified_at: datetime) -> None:
        """Stamp ``users.email_verified_at`` for ``user_id`` unless it is already set.

        One conditional ``UPDATE … WHERE email_verified_at IS NULL``: two
        verifications racing cannot both write, and the first instant is kept.

        Billing spec §2.1 (free start): the call that wins the stamp also issues the
        role's signup grant, in the same transaction. The grant is idempotent per
        account, and it runs in a savepoint so a ledger failure is logged and the
        verification still commits.
        """
        with session_scope(self._settings) as session:
            role = session.execute(
                update(User)
                .where(User.id == user_id, User.email_verified_at.is_(None))
                .values(email_verified_at=verified_at)
                .returning(User.role)
            ).scalar_one_or_none()
            if role is None:
                return
            try:
                with session.begin_nested():
                    grant_signup_allowance(session, user_id=user_id, role=role, now=verified_at)
            except Exception:
                log.exception("signup_grant_failed", user_id=str(user_id))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_signup.py tests/test_email_verified_first_timestamp.py tests/test_auth_service.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/auth/mirror.py tests/test_usage_signup.py
git commit -S -m "feat(usage): free signup allowances on first email verification" -- lemely/auth/mirror.py tests/test_usage_signup.py
```

---

### Task 9: Meter the student self-mark stream (`POST /api/student/correct`)

**Files:**
- Modify: `lemely/web/routers/student.py`: `student_correct` (lines 954-1272)
- Test: `tests/test_usage_student_correct.py`

**Interfaces:**
- Consumes: `UsageMeter`, `get_usage_meter`, `request_from_auth`, `UsageBlocked`, `USAGE_BLOCKED_MESSAGE` (Task 6); `MeteredAction.MARK_PAPER`.
- Produces: the route answers 402 (top-level body) before streaming when no candidate chain covers the top of the `mark_paper` estimate. Inside the worker, the job binds the subject detected from the scan. When the detected subject turns out to be blocked, the stream ends with an `error` frame carrying `code: "usage_blocked"` and `reason`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_usage_student_correct.py
"""Metering on the SSE self-mark route (Task 9): 402 before the stream, settle in the worker,
per-subject seat routing from the detected scan subject."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from lemely.core.metered_actions import MeteredAction
from lemely.db.models.enums import Role
from lemely.db.models.usage import UsageJobStatus
from lemely.io.llm.cost_meter import record_llm_cost
from lemely.runtime.events import EventType
from lemely.web.routers import student
from lemely.web.usage import get_usage_meter
from tests import test_student_correct as _student_correct
from tests.usage_helpers import enforcing_meter, give, jobs_for, seat, seat_grant, seed_catalogue, seed_user

# Fixtures re-exported by attribute (see tests/test_student_self_review_web.py for why).
client = _student_correct.client
corpus_repo = _student_correct.corpus_repo
gemini_client = _student_correct.gemini_client
pg_sessionmaker = _student_correct.pg_sessionmaker
settings = _student_correct.settings

if TYPE_CHECKING:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.upload_repo import StudentUploadRepository


@pytest.fixture
def metered(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, uuid.UUID]:
    api, student_id, _ = client
    app = cast("FastAPI", api.app)
    app.dependency_overrides[get_usage_meter] = lambda: enforcing_meter(pg_sessionmaker)
    seed_catalogue(pg_sessionmaker)

    class _Detector:
        def __init__(self, _client: object) -> None: ...

        def __call__(self, _scan_path: object) -> SimpleNamespace:
            record_llm_cost(Decimal("0.010"))
            return SimpleNamespace(subject_code="0580")

    extracted = _student_correct._extracted()

    def _extract(*_a: object, **_k: object) -> object:
        record_llm_cost(Decimal("0.040"))
        return extracted

    monkeypatch.setattr(student, "llm_key_configured", lambda *_a, **_k: True)
    monkeypatch.setattr(student, "ScanMetadataExtractor", _Detector)
    monkeypatch.setattr(student, "extract_answers", _extract)
    return api, uuid.UUID(student_id)


def _upload(api: TestClient) -> str:
    up = api.post("/api/student/uploads", files={"scan": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")})
    assert up.status_code == 200, up.text
    return up.json()["paperId"]


def test_no_balance_is_a_402_before_any_stream(
    metered: tuple[TestClient, uuid.UUID], pg_sessionmaker: sessionmaker[Session]
) -> None:
    api, student_id = metered
    resp = api.post("/api/student/correct", json={"paperId": _upload(api)})
    assert resp.status_code == 402
    assert resp.json() == {"error": "usage_blocked", "reason": "no_active_plan", "estimate": [40, 120]}
    assert jobs_for(pg_sessionmaker, student_id) == []


def test_own_credits_pay_the_actual_cost(
    metered: tuple[TestClient, uuid.UUID], pg_sessionmaker: sessionmaker[Session]
) -> None:
    api, student_id = metered
    give(pg_sessionmaker, student_id, units=1000)
    resp = api.post("/api/student/correct", json={"paperId": _upload(api)})
    assert resp.status_code == 200
    assert '"phase": "complete"' in resp.text
    (job,) = jobs_for(pg_sessionmaker, student_id)
    assert job.status is UsageJobStatus.settled
    assert job.charged == 50
    assert job.teacher_member_id is None


def test_a_maths_scan_is_paid_by_the_maths_seat(
    metered: tuple[TestClient, uuid.UUID], pg_sessionmaker: sessionmaker[Session]
) -> None:
    api, student_id = metered
    maths, physics = seed_user(pg_sessionmaker, Role.teacher), seed_user(pg_sessionmaker, Role.teacher)
    maths_seat = seat(pg_sessionmaker, teacher=maths, student=student_id, subjects=["0580"],
                      actions=[MeteredAction.MARK_PAPER])
    physics_seat = seat(pg_sessionmaker, teacher=physics, student=student_id, subjects=["0625"],
                        actions=[MeteredAction.MARK_PAPER])
    seat_grant(pg_sessionmaker, student=student_id, member_id=maths_seat, units=500)
    seat_grant(pg_sessionmaker, student=student_id, member_id=physics_seat, units=500)
    resp = api.post("/api/student/correct", json={"paperId": _upload(api)})
    assert resp.status_code == 200
    (job,) = jobs_for(pg_sessionmaker, student_id)
    assert job.teacher_member_id == maths_seat
    assert job.charged == 50


def test_a_detected_subject_nobody_pays_for_ends_the_stream_with_usage_blocked(
    metered: tuple[TestClient, uuid.UUID], pg_sessionmaker: sessionmaker[Session]
) -> None:
    api, student_id = metered
    physics = seed_user(pg_sessionmaker, Role.teacher)
    physics_seat = seat(pg_sessionmaker, teacher=physics, student=student_id, subjects=["0625"],
                        actions=[MeteredAction.MARK_PAPER])
    seat_grant(pg_sessionmaker, student=student_id, member_id=physics_seat, units=500)
    resp = api.post("/api/student/correct", json={"paperId": _upload(api)})
    assert resp.status_code == 200  # the physics seat could have paid, so the stream started
    errors = [f for f in _student_correct._frames(resp.text) if f["type"] == EventType.ERROR.value]
    assert errors
    assert errors[-1]["code"] == "usage_blocked"
    assert errors[-1]["reason"] == "no_active_plan"
    assert jobs_for(pg_sessionmaker, student_id) == []
```

Frames are `{"type": <event type>, **payload}` (`lemely/web/sse.py::_event_to_payload`), so `code` and `reason` sit at the top level.

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_student_correct.py -v --no-cov`
Expected: FAIL. The 402 test gets 200, and no `usage_jobs` rows exist.

- [ ] **Step 3: Wire the meter into the route**

In `lemely/web/routers/student.py`, add the imports:

```python
from lemely.core.metered_actions import MeteredAction
from lemely.web.usage import (
    USAGE_BLOCKED_MESSAGE,
    UsageBlocked,
    UsageMeter,
    get_usage_meter,
    request_from_auth,
)
```

Add a parameter to `student_correct` after `zones`:

```python
    meter: Annotated[UsageMeter, Depends(get_usage_meter)],
```

Directly after the 404 check (`if owned is None: raise HTTPException(...)`), add:

```python
    # Billing spec §5.7. The subject is read off the scan inside the job, so this checks
    # every chain the subject could turn out to need (own balance, or a seat covering
    # marking) and holds nothing yet; `job.bind_subject` reserves once it is known.
    job = meter.reserve(
        meter.authorize(request_from_auth(auth, MeteredAction.MARK_PAPER, subject_pending=True))
    )
```

Inside `run()`, wrap the existing `with tempfile.TemporaryDirectory() as tmp_dir:` block (and everything nested in it) in `with job.run():`. The `try:` keeps `upload_repo.set_status(owned.id, UploadStatus.processing)` first. The result:

```python
        try:
            upload_repo.set_status(owned.id, UploadStatus.processing)
            with job.run(), tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                # ... unchanged ...
```

Inside the `with script_cost_scope(...)` block, directly after the metadata-detection `if llm_key_configured(...)` block and before `mark_scheme = resolve_mark_scheme(...)`, add:

```python
                    # Spec §2.2: route to the seat covering this paper's subject.
                    job.bind_subject(metadata.subject_code if metadata is not None else None)
```

In the "no mark scheme" branch, before `return`, add `job.abandon()`:

```python
                    if mark_scheme is None:
                        bus.publish(
                            EventType.WARNING,
                            paper_id=payload.paperId,
                            message="No mark scheme available for this paper; cannot mark.",
                        )
                        upload_repo.set_status(owned.id, UploadStatus.failed)
                        job.abandon()
                        return
```

Add an `except` clause before the final `except Exception as exc:`:

```python
        except UsageBlocked as exc:
            # The detected subject's chain cannot pay (spec §5.6); nothing was held.
            bus.publish(
                EventType.ERROR,
                paper_id=payload.paperId,
                message=USAGE_BLOCKED_MESSAGE,
                code="usage_blocked",
                reason=exc.reason.value,
            )
            upload_repo.set_status(owned.id, UploadStatus.failed)
```

The `script_cost_scope` block still encloses `ScanMetadataExtractor`, `resolve_mark_scheme` and `grade_paper` exactly once each, so `tests/test_script_cost_scope.py` keeps passing.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_student_correct.py tests/test_student_correct.py tests/test_script_cost_scope.py tests/test_events_scoping.py tests/test_authz_matrix_complete.py -v --no-cov`
Expected: PASS. `tests/test_student_correct.py` runs unmetered, because the suite sets `LEMELY_USAGE__ENFORCE=0`.

- [ ] **Step 5: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/web/routers/student.py tests/test_usage_student_correct.py
git commit -S -m "feat(usage): meter the student self-mark stream with per-subject seat routing" -- lemely/web/routers/student.py tests/test_usage_student_correct.py
```

---

### Task 10: Meter teacher marking (`POST /api/papers/upload`, `POST /api/papers/{paper_id}/regrade`)

**Files:**
- Modify: `lemely/web/routers/teacher.py`: `_run_grading_job` (510-662), `_start_run_if_claimed` (665-687), `upload_paper` (879-949), `regrade_paper` (1028-1052)
- Modify: `tests/test_teacher_paper_deletion.py:819-827`: pass `job=MeteredJob.unmetered(MeteredAction.MARK_PAPER)` to the direct `_run_grading_job` call
- Test: `tests/test_usage_teacher_marking.py`

**Interfaces:**
- Consumes: `UsageMeter`, `MeteredJob`, `get_usage_meter`, `request_from_team` (Task 6); phase 03's `actor: Annotated[TeamActor, Depends(_TEAM_MARK)]` on `upload_paper` and `Depends(_TEAM_REGRADE)` on `regrade_paper`, `ACTING_TEACHER_HEADER`, `get_teacher_team_store`, `TeacherTeamStore`.
- Produces: `_run_grading_job(..., *, job: MeteredJob)` and `_start_run_if_claimed(..., *, job: MeteredJob) -> bool` (keyword-only, required). Upload is metered as `mark_paper` and regrade as `regrade`, both through `request_from_team(actor, ...)`. A teacher acting as themselves pays from their own chain. An assistant acting under `X-Lemely-Acting-Teacher` always pays from the lead's chain within its cap, and its own balance is never touched (R4). Both reserve in the request and settle on the grading pool thread. A lost claim releases the hold.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_usage_teacher_marking.py
"""Metering on console marking (Task 10): reserve in the request, settle on the pool."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from lemely.db.models.enums import Role
from lemely.db.models.usage import UsageGrantBalance, UsageJobStatus
from lemely.db.scheme_corpus_repo import SchemeCorpusRepository
from lemely.db.teacher_paper_repo import TeacherPaperRepository
from lemely.db.teacher_team_repo import TeacherTeamStore
from lemely.io.gemini import GeminiClient
from lemely.io.llm.cost_meter import record_llm_cost
from lemely.web import create_app
from lemely.web.deps import (
    ACTING_TEACHER_HEADER,
    AuthContext,
    get_auth_context,
    get_gemini_client,
    get_history_store,
    get_scheme_corpus_repo,
    get_storage_backend,
    get_teacher_paper_repo,
    get_teacher_team_store,
)
from lemely.web.routers import student as student_router
from lemely.web.routers import teacher as teacher_router
from lemely.web.services import grading as grading_service
from lemely.web.usage import get_usage_meter
from tests.storage_fakes import FakeStorageBackend
from tests.test_teacher_paper_repo import _mark_scheme, _report
from tests.usage_helpers import assistant, enforcing_meter, give, jobs_for, seed_catalogue, seed_user

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import Session, sessionmaker


class _InlinePool:
    """Runs a submitted job at once, so the settle is visible when the request returns."""

    def submit(self, fn: Callable[..., object], *args: object, **kwargs: object) -> None:
        fn(*args, **kwargs)


@pytest.fixture
def console(
    migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, TeacherPaperRepository]]:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    repo = TeacherPaperRepository(sm, stale_after=timedelta(minutes=15))
    storage = FakeStorageBackend()

    def _extract(*_a: object, **_k: object) -> list[object]:
        record_llm_cost(Decimal("0.030"))
        return []

    def _grade(*_a: object, **_k: object) -> object:
        record_llm_cost(Decimal("0.020"))
        return _report()

    monkeypatch.setattr(teacher_router, "_grading_pool", _InlinePool())
    monkeypatch.setattr(teacher_router, "_detection_available", lambda _settings: False)
    monkeypatch.setattr(student_router, "resolve_mark_scheme", lambda *_a, **_k: _mark_scheme())
    monkeypatch.setattr(grading_service, "extract_answers", _extract)
    monkeypatch.setattr(grading_service, "ensure_binding_allows_marking", lambda _x: None)
    monkeypatch.setattr(grading_service, "grade_paper", _grade)

    app = create_app()
    app.dependency_overrides[get_teacher_paper_repo] = lambda: repo
    app.dependency_overrides[get_storage_backend] = lambda: storage
    app.dependency_overrides[get_history_store] = lambda: MagicMock()
    app.dependency_overrides[get_gemini_client] = lambda: MagicMock(spec=GeminiClient)
    app.dependency_overrides[get_scheme_corpus_repo] = lambda: SchemeCorpusRepository(sm)
    app.dependency_overrides[get_usage_meter] = lambda: enforcing_meter(sm)
    app.dependency_overrides[get_teacher_team_store] = lambda: TeacherTeamStore(sm)
    yield TestClient(app), repo
    app.dependency_overrides.clear()


def _as(api: TestClient, user: uuid.UUID) -> None:
    api.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user), role="teacher"
    )


def _upload(api: TestClient, acting_for: uuid.UUID | None = None) -> object:
    headers = {ACTING_TEACHER_HEADER: str(acting_for)} if acting_for is not None else {}
    return api.post(
        "/api/papers/upload",
        files={"scan": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers=headers,
    )


def test_upload_without_balance_is_402_and_stores_nothing(
    console: tuple[TestClient, TeacherPaperRepository], migrated_sessionmaker: sessionmaker[Session]
) -> None:
    api, repo = console
    teacher = seed_user(migrated_sessionmaker, Role.teacher)
    _as(api, teacher)
    resp = _upload(api)
    assert resp.status_code == 402
    assert resp.json()["reason"] == "no_active_plan"
    assert repo.list_visible(viewer_id=teacher, viewer_role=Role.teacher) == []


def test_upload_charges_the_marking_cost(
    console: tuple[TestClient, TeacherPaperRepository], migrated_sessionmaker: sessionmaker[Session]
) -> None:
    api, _ = console
    teacher = seed_user(migrated_sessionmaker, Role.teacher)
    give(migrated_sessionmaker, teacher, units=1000)
    _as(api, teacher)
    assert _upload(api).status_code == 200
    (job,) = jobs_for(migrated_sessionmaker, teacher)
    assert (job.action, job.status, job.charged) == ("mark_paper", UsageJobStatus.settled, 50)


def test_an_assistants_upload_and_regrade_bill_the_lead_never_the_assistant(
    console: tuple[TestClient, TeacherPaperRepository], migrated_sessionmaker: sessionmaker[Session]
) -> None:
    """R4: team work under the acting-teacher header is charged to the lead teacher."""
    api, _ = console
    sm = migrated_sessionmaker
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    own = give(sm, helper, units=1000)
    member = assistant(sm, teacher=lead, member=helper)
    _as(api, helper)
    blocked = _upload(api, acting_for=lead)  # the lead has nothing; the helper's 1000 never counts
    assert blocked.status_code == 402
    assert blocked.json()["reason"] == "no_active_plan"
    give(sm, lead, units=1000)
    paper_id = _upload(api, acting_for=lead).json()["paperId"]
    regrade = api.post(
        f"/api/papers/{paper_id}/regrade", headers={ACTING_TEACHER_HEADER: str(lead)}
    )
    assert regrade.status_code == 202
    jobs = jobs_for(sm, helper)
    assert [(j.action, j.teacher_member_id, j.charged) for j in jobs] == [
        ("mark_paper", member, 50),
        ("regrade", member, 50),
    ]
    with sm() as session:
        assert session.get(UsageGrantBalance, own).remaining == 1000


def test_regrade_as_oneself_charges_ones_own_chain(
    console: tuple[TestClient, TeacherPaperRepository], migrated_sessionmaker: sessionmaker[Session]
) -> None:
    api, _ = console
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    give(sm, teacher, units=1000)
    _as(api, teacher)
    paper_id = _upload(api).json()["paperId"]
    assert api.post(f"/api/papers/{paper_id}/regrade").status_code == 202
    jobs = jobs_for(sm, teacher)
    assert [(j.action, j.teacher_member_id, j.charged) for j in jobs] == [
        ("mark_paper", None, 50),
        ("regrade", None, 50),
    ]


def test_regrade_without_balance_is_402(
    console: tuple[TestClient, TeacherPaperRepository], migrated_sessionmaker: sessionmaker[Session]
) -> None:
    api, repo = console
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    give(sm, teacher, units=120)
    _as(api, teacher)
    paper_id = _upload(api).json()["paperId"]  # spends 50 of 120; 70 < 120 is left
    resp = api.post(f"/api/papers/{paper_id}/regrade")
    assert resp.status_code == 402
    assert resp.json()["reason"] == "insufficient_credits"


def test_a_lost_claim_releases_the_hold(
    console: tuple[TestClient, TeacherPaperRepository],
    migrated_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, repo = console
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    give(sm, teacher, units=1000)
    _as(api, teacher)
    paper_id = _upload(api).json()["paperId"]
    monkeypatch.setattr(TeacherPaperRepository, "claim_run", lambda _self, _pid: False)
    assert api.post(f"/api/papers/{paper_id}/regrade").status_code == 202
    assert jobs_for(sm, teacher)[-1].status is UsageJobStatus.released


def test_a_failed_run_is_released_not_charged(
    console: tuple[TestClient, TeacherPaperRepository],
    migrated_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api, _ = console
    sm = migrated_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    give(sm, teacher, units=1000)

    def _broken(*_a: object, **_k: object) -> object:
        record_llm_cost(Decimal("0.010"))
        raise RuntimeError("model down")

    monkeypatch.setattr(grading_service, "grade_paper", _broken)
    _as(api, teacher)
    assert _upload(api).status_code == 200
    (job,) = jobs_for(sm, teacher)
    assert job.status is UsageJobStatus.released
```

Under the header, phase 03 records the paper against the lead (`uploaded_by = lead`) and hands the handler the lead's `AuthContext` as `actor.auth`, so the assistant sees and regrades the lead's paper. `usage_jobs.actor_user_id` stays the assistant (`TeamActor.actor_user_id`), with `teacher_member_id` = the assistant row.

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_teacher_marking.py -v --no-cov`
Expected: FAIL. The 402 tests get 200/202 and no `usage_jobs` rows exist.

- [ ] **Step 3: Thread a `MeteredJob` through the grading job**

In `lemely/web/routers/teacher.py`, add the imports:

```python
from lemely.core.metered_actions import MeteredAction
from lemely.web.usage import MeteredJob, UsageMeter, get_usage_meter, request_from_team
```

Change `_run_grading_job`'s signature to end with `corpus: SchemeCorpusRepository, *, job: MeteredJob,`. Add to its docstring: "``job`` was reserved by the request that claimed the run. Its cost scope opens here, on the pool thread, because a pool task does not inherit the request's context. A run that fails, finds no paper, or resolves no scheme is released, never charged (billing spec §2.4)." Restructure the body's `try:` so the work runs inside `with job.run():`:

```python
    try:
        with job.run():
            row = repo.get(paper_id)
            if row is None:
                job.abandon()
                return
            with tempfile.TemporaryDirectory() as tmp:
                # ... unchanged down to the scheme check ...
                    if scheme is None:
                        repo.fail(
                            paper_id,
                            "No mark scheme could be resolved for this paper — nothing was marked. "
                            "Attach one on upload, or add it under Mark schemes and re-run.",
                        )
                        job.abandon()
                        return
                # ... unchanged ...
            repo.finish(paper_id, report)
    except TeacherPaperDeletedError:
        # ... the existing except clauses, unchanged ...
```

An exception raised inside `with job.run():` releases the hold, then reaches the existing `except` clauses unchanged.

Change `_start_run_if_claimed`:

```python
def _start_run_if_claimed(
    paper_id: uuid.UUID,
    settings: Settings,
    repo: TeacherPaperRepository,
    storage: StorageBackend,
    history_store: HistoryStoreProtocol,
    gemini_client: GeminiClient,
    corpus: SchemeCorpusRepository,
    *,
    job: MeteredJob,
) -> bool:
    """Claim the run on the row; if this instance won, submit it to the local pool.

    ``claim_run`` is the one conditional ``UPDATE`` that replaces the old
    ``_jobs_lock``/job-registry pair (spec §4.2): exactly one caller — on this
    instance or another — ever wins the race for a given paper, so a regrade
    fired from two browser tabs, or two Cloud Run instances answering the same
    request, cannot double-mark the same scan. A lost claim releases ``job``'s
    hold: the winning request holds its own.
    """
    if not repo.claim_run(paper_id):
        job.release()
        return False
    _grading_pool.submit(
        _run_grading_job,
        paper_id,
        settings,
        repo,
        storage,
        history_store,
        gemini_client,
        corpus,
        job=job,
    )
    return True
```

- [ ] **Step 4: Reserve in `upload_paper` and `regrade_paper`**

In `upload_paper`, add the parameter `meter: Annotated[UsageMeter, Depends(get_usage_meter)],` after `corpus`. Directly after `await anyio.to_thread.run_sync(check_scan_geometry, scan_bytes, scan.content_type)`, add:

```python
    # Billing spec §5.7: validated inputs first (rejects cost nothing), then hold the
    # estimate before storing anything. Off the event loop: both calls hit Postgres.
    # R4: `actor` is phase 03's TeamActor; an assistant's upload bills the lead.
    usage = await anyio.to_thread.run_sync(
        meter.authorize, request_from_team(actor, MeteredAction.MARK_PAPER)
    )
    job = await anyio.to_thread.run_sync(meter.reserve, usage)
```

Wrap everything from `scan_key = ...` to the `_start_run_if_claimed(...)` call in a `try:` that releases the hold on failure, and pass the job:

```python
    try:
        scan_key = f"{prefix}/{_safe_upload_name(scan.filename, 'scan.pdf')}"
        # ... unchanged storage uploads and repo.create(...) ...
        _start_run_if_claimed(
            paper_id, settings, repo, storage, history_store, gemini_client, corpus, job=job
        )
    except BaseException:
        job.release()
        raise
    return UploadResponseDTO(jobId=str(paper_id), paperId=str(paper_id), detected=[])
```

In `regrade_paper`, add `meter: Annotated[UsageMeter, Depends(get_usage_meter)],` after `corpus`, and replace the body after `row = _require_paper(repo, actor.auth, paper_id)` (phase 03's line) with:

```python
    # R4 / spec §2.3: an assistant regrading for the lead draws on the lead's chain.
    job = meter.reserve(meter.authorize(request_from_team(actor, MeteredAction.REGRADE)))
    try:
        _start_run_if_claimed(
            row.id, settings, repo, storage, history_store, gemini_client, corpus, job=job
        )
    except BaseException:
        job.release()
        raise
    return {"paperId": paper_id, "status": "processing"}
```

`job.release()` is idempotent: after `_start_run_if_claimed` has released a lost claim, or after the pool job has finished, a second call is a no-op (`MeteredJob._finished`).

- [ ] **Step 5: Update the direct caller in the deletion test**

In `tests/test_teacher_paper_deletion.py`, add imports `from lemely.core.metered_actions import MeteredAction` and `from lemely.web.usage import MeteredJob`. Change the call at lines 819-827 to:

```python
        teacher_router._run_grading_job(
            pid,
            settings,
            repo,
            storage,
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            job=MeteredJob.unmetered(MeteredAction.MARK_PAPER),
        )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_teacher_marking.py tests/test_web_teacher.py tests/test_teacher_paper_deletion.py tests/test_script_cost_scope.py tests/test_marking_options_wiring.py tests/test_authz_matrix_complete.py -v --no-cov`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/web/routers/teacher.py tests/test_teacher_paper_deletion.py tests/test_usage_teacher_marking.py
git commit -S -m "feat(usage): meter console marking and regrade across the grading pool" -- lemely/web/routers/teacher.py tests/test_teacher_paper_deletion.py tests/test_usage_teacher_marking.py
```

---

### Task 11: Meter teacher quiz preview and generation

**Files:**
- Modify: `lemely/web/routers/teacher.py`: `quiz_preview` (1732-1765), `quiz_generate` (1768-1814), and two new target dependencies above them
- Test: `tests/test_usage_teacher_quiz.py`

**Interfaces:**
- Consumes: `require_usage(..., team=...)`, `UsageGrantContext`, `UsageMeter`, `get_usage_meter` (Task 6); `UsageTarget` (Task 1); phase 03's `_TEAM_QUIZ = require_team_permission(TeamPermission.GENERATE_QUIZ, *_STAFF_ROLES)` already declared on both routes as `actor`.
- Produces: `_preview_quiz_target(count: int = 4) -> UsageTarget` and `_generate_quiz_target(count: int = 5) -> UsageTarget` (module-level dependencies; the `count` query parameter becomes the estimate input). Both routes answer 402 when blocked and settle the generation cost on success. An assistant under `X-Lemely-Acting-Teacher` is charged to the lead (R4), because `require_usage` receives the route's own `_TEAM_QUIZ` guard.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_usage_teacher_quiz.py
"""Metering on quiz preview and generation (Task 11)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from lemely.core.generation import GeneratedQuiz
from lemely.db.models.enums import Role
from lemely.db.models.usage import UsageGrantBalance, UsageJobStatus
from lemely.db.teacher_team_repo import TeacherTeamStore
from lemely.io.llm.cost_meter import record_llm_cost
from lemely.web import create_app
from lemely.web.deps import (
    ACTING_TEACHER_HEADER,
    AuthContext,
    get_auth_context,
    get_class_service,
    get_gemini_client,
    get_history_store,
    get_question_bank_service,
    get_teacher_team_store,
)
from lemely.web.routers import teacher as teacher_router
from lemely.web.usage import get_usage_meter
from tests.usage_helpers import assistant, enforcing_meter, give, jobs_for, seed_catalogue, seed_user

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def api(migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    seed_catalogue(migrated_sessionmaker)

    def _build(*_a: object, **_k: object) -> tuple[GeneratedQuiz, set[str]]:
        record_llm_cost(Decimal("0.008"))
        return GeneratedQuiz(subject_code="0580", questions=[]), set()

    monkeypatch.setattr(teacher_router, "_build_quiz", _build)
    classes = MagicMock()
    classes.member_school_ids.return_value = []
    app = create_app()
    app.dependency_overrides[get_usage_meter] = lambda: enforcing_meter(migrated_sessionmaker)
    app.dependency_overrides[get_history_store] = lambda: MagicMock()
    app.dependency_overrides[get_gemini_client] = lambda: MagicMock()
    app.dependency_overrides[get_class_service] = lambda: classes
    app.dependency_overrides[get_question_bank_service] = lambda: MagicMock()
    app.dependency_overrides[get_teacher_team_store] = lambda: TeacherTeamStore(migrated_sessionmaker)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(api: TestClient, user: uuid.UUID) -> None:
    api.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user), role="teacher"
    )


@pytest.mark.parametrize(("path", "action"), [("/api/quizzes/preview", "preview_quiz"),
                                              ("/api/quizzes/generate", "generate_quiz")])
def test_blocked_without_balance(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session], path: str, action: str
) -> None:
    teacher = seed_user(migrated_sessionmaker, Role.teacher)
    _as(api, teacher)
    resp = api.post(path, params={"subject_code": "0580", "count": 3})
    assert resp.status_code == 402
    # base 2-4 + 3 questions x 2-5 = 8-19
    assert resp.json() == {"error": "usage_blocked", "reason": "no_active_plan", "estimate": [8, 19]}
    assert jobs_for(migrated_sessionmaker, teacher) == []


@pytest.mark.parametrize(("path", "action"), [("/api/quizzes/preview", "preview_quiz"),
                                              ("/api/quizzes/generate", "generate_quiz")])
def test_success_charges_the_generation(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session], path: str, action: str
) -> None:
    teacher = seed_user(migrated_sessionmaker, Role.teacher)
    give(migrated_sessionmaker, teacher, units=500)
    _as(api, teacher)
    assert api.post(path, params={"subject_code": "0580", "count": 3}).status_code == 200
    (job,) = jobs_for(migrated_sessionmaker, teacher)
    assert (job.action, job.status, job.charged) == (action, UsageJobStatus.settled, 8)


@pytest.mark.parametrize("path", ["/api/quizzes/preview", "/api/quizzes/generate"])
def test_an_assistant_is_charged_to_the_lead_never_itself(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session], path: str
) -> None:
    """R4: quiz generation under the acting-teacher header bills the lead teacher."""
    sm = migrated_sessionmaker
    lead, helper = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    own = give(sm, helper, units=500)
    member = assistant(sm, teacher=lead, member=helper)
    _as(api, helper)
    headers = {ACTING_TEACHER_HEADER: str(lead)}
    params = {"subject_code": "0580", "count": 3}
    assert api.post(path, params=params, headers=headers).status_code == 402
    give(sm, lead, units=500)
    assert api.post(path, params=params, headers=headers).status_code == 200
    (job,) = jobs_for(sm, helper)
    assert (job.teacher_member_id, job.charged) == (member, 8)
    with sm() as session:
        assert session.get(UsageGrantBalance, own).remaining == 500


def test_a_failed_generation_is_released(
    api: TestClient, migrated_sessionmaker: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    def _down(*_a: object, **_k: object) -> object:
        raise HTTPException(status_code=503, detail="Quiz generation is temporarily unavailable")

    monkeypatch.setattr(teacher_router, "_build_quiz", _down)
    teacher = seed_user(migrated_sessionmaker, Role.teacher)
    give(migrated_sessionmaker, teacher, units=500)
    _as(api, teacher)
    assert api.post("/api/quizzes/preview", params={"count": 3}).status_code == 503
    assert jobs_for(migrated_sessionmaker, teacher)[0].status is UsageJobStatus.released
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_teacher_quiz.py -v --no-cov`
Expected: FAIL (200 instead of 402; no jobs).

- [ ] **Step 3: Wire the routes**

In `lemely/web/routers/teacher.py`, extend the Task 10 import to:

```python
from lemely.core.metered_actions import MeteredAction, UsageTarget
from lemely.web.usage import (
    MeteredJob,
    UsageGrantContext,
    UsageMeter,
    get_usage_meter,
    request_from_team,
    require_usage,
)
```

Directly above `quiz_preview`, add:

```python
def _preview_quiz_target(count: int = 4) -> UsageTarget:
    """``POST /quizzes/preview``'s estimate input: the questions requested (same default)."""
    return UsageTarget(subject_code=None, input_count=count)


def _generate_quiz_target(count: int = 5) -> UsageTarget:
    """``POST /quizzes/generate``'s estimate input: the questions requested (same default)."""
    return UsageTarget(subject_code=None, input_count=count)
```

Add to `quiz_preview`'s parameters, after `bank_service`:

```python
    usage: Annotated[
        UsageGrantContext,
        Depends(
            require_usage(
                MeteredAction.PREVIEW_QUIZ, target=_preview_quiz_target, team=_TEAM_QUIZ
            )
        ),
    ],
    meter: Annotated[UsageMeter, Depends(get_usage_meter)],
```

and wrap the build:

```python
    with meter.job(usage):
        quiz, _reused = _build_quiz(
            settings,
            history_store,
            gemini_client,
            bank_service,
            caller_uuid,
            class_service.member_school_ids(caller_uuid),
            subject_code=subject_code,
            count=count,
            topics=topics,
        )
    return _quiz_to_preview(quiz)
```

Do the same in `quiz_generate` with `require_usage(MeteredAction.GENERATE_QUIZ, target=_generate_quiz_target, team=_TEAM_QUIZ)`, wrapping only the `_build_quiz(...)` call (the bank write after it is not model work):

```python
    with meter.job(usage):
        quiz, reused_prompts = _build_quiz(
            settings,
            history_store,
            gemini_client,
            bank_service,
            caller_uuid,
            class_service.member_school_ids(caller_uuid),
            subject_code=subject_code,
            count=count,
            topics=topics,
        )
```

Passing `team=_TEAM_QUIZ`, the same object as the route's `actor` dependency, makes FastAPI resolve the team guard once per request. The `usage` parameter is declared after `actor`, so a wrong role is still a 403 before any database read. `request_from_team` is imported here for Task 10's routes in the same module.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_teacher_quiz.py tests/test_web_teacher.py tests/test_authz_matrix_complete.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/web/routers/teacher.py tests/test_usage_teacher_quiz.py
git commit -S -m "feat(usage): meter teacher quiz preview and generation" -- lemely/web/routers/teacher.py tests/test_usage_teacher_quiz.py
```

---

### Task 12: Meter student self-review, flashcard generation and study plans

**Files:**
- Modify: `lemely/web/routers/student_self_review.py`: `submit_self_review` (294-318)
- Modify: `lemely/web/routers/flashcards.py`: `generate_deck` (218-243)
- Modify: `lemely/web/routers/study_plan.py`: `create_study_plan` (112-127)
- Test: `tests/test_usage_self_review.py`, `tests/test_usage_flashcards.py`, `tests/test_usage_study_plan.py`

**Interfaces:**
- Consumes: `UsageMeter`, `get_usage_meter`, `request_from_auth` (Task 6); `self_review_target` (Task 5).
- Produces: `self_review` is metered only when a submitted point carries non-blank evidence, the one case where the judge can be called. The subject comes from the caller's attempt and the input is the question's mark-point count. `generate_flashcards` is metered on the deck's subject with `count` as input. `study_plan` is metered on the plan's subject. The first plan per subject per ISO week goes to a seat that has `study_plan` in scope, and a regeneration in the same week draws on the student's own balance.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_usage_self_review.py
"""Metering on self-review (Task 12): only evidence can reach the judge, so only evidence
is metered; the subject and inputs come from the caller's own attempt."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, cast

import pytest

from lemely.db.models.usage import UsageJobStatus
from lemely.db.self_review_repo import SelfReviewService
from lemely.db.usage_context_repo import self_review_target
from lemely.io.llm.cost_meter import record_llm_cost
from lemely.web.usage import get_usage_meter
from tests import test_student_correct as _student_correct
from tests import test_student_self_review_web as _web
from tests.usage_helpers import enforcing_meter, give, jobs_for, seed_catalogue

client = _student_correct.client
corpus_repo = _student_correct.corpus_repo
gemini_client = _student_correct.gemini_client
pg_sessionmaker = _student_correct.pg_sessionmaker
settings = _student_correct.settings

if TYPE_CHECKING:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.upload_repo import StudentUploadRepository


@pytest.fixture
def wired(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, str, str, str]:
    api, student_id = _web._wire(client, pg_sessionmaker)
    cast("FastAPI", api.app).dependency_overrides[get_usage_meter] = lambda: enforcing_meter(pg_sessionmaker)
    seed_catalogue(pg_sessionmaker)
    original = SelfReviewService.submit

    def _costly(self: SelfReviewService, *args: object, **kwargs: object) -> object:
        record_llm_cost(Decimal("0.003"))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SelfReviewService, "submit", _costly)
    attempt_id, qr_id = _web._seed_attempt(pg_sessionmaker, student_id)
    return api, student_id, attempt_id, qr_id


def test_target_reads_the_attempts_subject_and_point_count(
    wired: tuple[TestClient, str, str, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    _, student_id, attempt_id, qr_id = wired
    with pg_sessionmaker() as session:
        target = self_review_target(session, student_id=student_id, attempt_id=attempt_id,
                                    question_result_id=qr_id)
        foreign = self_review_target(session, student_id=str(uuid.uuid4()), attempt_id=attempt_id,
                                     question_result_id=qr_id)
    assert target is not None
    assert target.subject_code == "0580"
    assert target.input_count == 3
    assert foreign is None


def test_evidence_without_balance_is_402(wired: tuple[TestClient, str, str, str]) -> None:
    api, _, attempt_id, qr_id = wired
    resp = api.post(_web._path(attempt_id, qr_id), json=_web._full_pass(evidence="I wrote 12 N"))
    assert resp.status_code == 402
    # base 1-2 + 3 marks x 0-1 = 1-5
    assert resp.json() == {"error": "usage_blocked", "reason": "no_active_plan", "estimate": [1, 5]}


def test_evidence_with_balance_settles(
    wired: tuple[TestClient, str, str, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    api, student_id, attempt_id, qr_id = wired
    give(pg_sessionmaker, uuid.UUID(student_id), units=100)
    resp = api.post(_web._path(attempt_id, qr_id), json=_web._full_pass(evidence="I wrote 12 N"))
    assert resp.status_code == 200, resp.text
    (job,) = jobs_for(pg_sessionmaker, uuid.UUID(student_id))
    assert (job.action, job.status, job.charged) == ("self_review", UsageJobStatus.settled, 3)


def test_no_evidence_is_never_metered(
    wired: tuple[TestClient, str, str, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    api, student_id, attempt_id, qr_id = wired
    assert api.post(_web._path(attempt_id, qr_id), json=_web._full_pass()).status_code == 200
    assert jobs_for(pg_sessionmaker, uuid.UUID(student_id)) == []


def test_someone_elses_question_is_still_a_404(wired: tuple[TestClient, str, str, str]) -> None:
    api, _, attempt_id, _ = wired
    resp = api.post(_web._path(attempt_id, str(uuid.uuid4())), json=_web._full_pass(evidence="x"))
    assert resp.status_code == 404
    assert resp.json() == {"detail": "No such question"}
```

```python
# tests/test_usage_flashcards.py
"""Metering on AI flashcard decks (Task 12)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from lemely.core.flashcards import GeneratedFlashcard
from lemely.db.flashcard_repo import FlashcardService
from lemely.db.models.usage import UsageJobStatus
from lemely.io.llm.cost_meter import record_llm_cost
from lemely.web.usage import get_usage_meter
from tests import test_web_flashcards as _flash
from tests.usage_helpers import enforcing_meter, give, jobs_for, seed_catalogue

client = _flash.client
pg_sessionmaker = _flash.pg_sessionmaker

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

_BODY = {"subjectCode": "0625", "origin": "topic", "topic": "4.3 Circuits", "count": 2}


def _wire(client: TestClient, sm: sessionmaker[Session]) -> uuid.UUID:
    seed_catalogue(sm)
    generator = _flash._mock_generator(
        [GeneratedFlashcard(front="What is current?", back="Rate of flow of charge"),
         GeneratedFlashcard(front="Unit of current?", back="Ampere")],
        topic="4.3 Circuits",
    )
    deck = generator.generate.return_value

    def _costly(*_a: object, **_k: object) -> object:
        record_llm_cost(Decimal("0.004"))
        return deck

    generator.generate.side_effect = _costly
    _flash._use_service(client, FlashcardService(sm, generator, now=lambda: _flash._FIXED_NOW))
    client.app.dependency_overrides[get_usage_meter] = lambda: enforcing_meter(sm)  # type: ignore[union-attr]
    student = _flash._seed_user(sm)
    _flash._auth_as(client, student)
    return student


def test_generation_without_balance_is_402(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    _wire(client, pg_sessionmaker)
    resp = client.post("/api/student/flashcards/decks/generate", json=_BODY)
    assert resp.status_code == 402
    # base 2-4 + 2 cards x 1-2 = 4-8
    assert resp.json()["estimate"] == [4, 8]


def test_generation_settles_the_cost(client: TestClient, pg_sessionmaker: sessionmaker[Session]) -> None:
    student = _wire(client, pg_sessionmaker)
    give(pg_sessionmaker, student, units=100)
    assert client.post("/api/student/flashcards/decks/generate", json=_BODY).status_code == 201
    (job,) = jobs_for(pg_sessionmaker, student)
    assert (job.action, job.status, job.charged) == ("generate_flashcards", UsageJobStatus.settled, 4)
```

```python
# tests/test_usage_study_plan.py
"""Spec §2.2 study plans on a seat: the seat pays the first generation per subject per ISO
week when `study_plan` is in scope; a regeneration draws own balance (Task 12)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.core.metered_actions import MeteredAction
from lemely.db.models.enums import Role
from lemely.db.models.usage import UsageJobStatus
from lemely.db.study_plan_repo import StudyPlanService
from lemely.web.usage import get_usage_meter
from tests import test_web_study_plan as _plans
from tests.usage_helpers import enforcing_meter, jobs_for, seat, seat_grant, seed_catalogue, seed_user

client = _plans.client
pg_sessionmaker = _plans.pg_sessionmaker

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker


def _wire(client: TestClient, sm: sessionmaker[Session]) -> None:
    seed_catalogue(sm)
    _plans._use_study_plan_service(client, StudyPlanService(sm, now=lambda: _plans._THIS_WEEK))
    client.app.dependency_overrides[get_usage_meter] = (  # type: ignore[union-attr]
        lambda: enforcing_meter(sm, now=_plans._THIS_WEEK)
    )


def test_first_plan_this_week_is_seat_paid_and_the_regeneration_is_not(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    sm = pg_sessionmaker
    _wire(client, sm)
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    member = seat(sm, teacher=teacher, student=student, subjects=["0625"],
                  actions=[MeteredAction.STUDY_PLAN])
    seat_grant(sm, student=student, member_id=member, units=100)
    _plans._auth_as(client, student, Role.student)
    assert client.post("/api/student/study-plan", json={"subjectCode": "0625"}).status_code == 201
    assert client.post("/api/student/study-plan", json={"subjectCode": "0625"}).status_code == 201
    first, second = jobs_for(sm, student)
    assert (first.teacher_member_id, second.teacher_member_id) == (member, None)
    assert {first.status, second.status} == {UsageJobStatus.settled}
    assert (first.charged or 0, second.charged or 0) == (0, 0)


def test_without_the_seat_action_the_student_pays(
    client: TestClient, pg_sessionmaker: sessionmaker[Session]
) -> None:
    sm = pg_sessionmaker
    _wire(client, sm)
    student, teacher = seed_user(sm), seed_user(sm, Role.teacher)
    seat(sm, teacher=teacher, student=student, subjects=["0625"], actions=[MeteredAction.MARK_PAPER])
    _plans._auth_as(client, student, Role.student)
    assert client.post("/api/student/study-plan", json={"subjectCode": "0625"}).status_code == 201
    (job,) = jobs_for(sm, student)
    assert job.teacher_member_id is None
```

Check the helper names used here against the current files before writing: `tests/test_web_flashcards.py` (`_mock_generator`, `_use_service`, `_seed_user`, `_auth_as`, `_FIXED_NOW`) and `tests/test_web_study_plan.py` (`_use_study_plan_service`, `_auth_as`, `_THIS_WEEK`). Confirm `GeneratedFlashcard`'s import path with `grep -n "class GeneratedFlashcard\b" -r lemely`. Use the names that exist.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_self_review.py tests/test_usage_flashcards.py tests/test_usage_study_plan.py -v --no-cov`
Expected: FAIL. The 402 tests get 200/201, and no jobs exist. (`test_target_reads_the_attempts_subject_and_point_count` and the 404 test pass already.)

- [ ] **Step 3: Wire self-review**

In `lemely/web/routers/student_self_review.py`, add:

```python
import contextlib

from lemely.core.metered_actions import MeteredAction
from lemely.db.usage_context_repo import self_review_target
from lemely.web.usage import UsageMeter, get_usage_meter, request_from_auth
```

(merged into the existing import block). Add a helper above `submit_self_review`:

```python
def _self_review_meter(
    meter: UsageMeter,
    auth: AuthContext,
    attempt_id: str,
    question_result_id: str,
    payload: SelfReviewSubmissionDTO,
) -> contextlib.AbstractContextManager[object]:
    """Billing spec §2.4: only a point with evidence can reach the judge (a model call),
    so only then is the pass metered; otherwise nothing is held or charged."""
    if not any((point.evidence or "").strip() for point in payload.points):
        return contextlib.nullcontext()
    target = meter.resolve_target(
        lambda session: self_review_target(
            session,
            student_id=auth.user_id,
            attempt_id=attempt_id,
            question_result_id=question_result_id,
        )
    )
    if target is None:
        raise HTTPException(status_code=404, detail="No such question")
    usage = meter.authorize(
        request_from_auth(
            auth,
            MeteredAction.SELF_REVIEW,
            subject_code=target.subject_code,
            input_count=target.input_count,
        )
    )
    return meter.job(usage)
```

Change `submit_self_review` to take `meter: Annotated[UsageMeter, Depends(get_usage_meter)],` after `service`, and its body to:

```python
    gate = _self_review_meter(meter, auth, attempt_id, question_result_id, payload)
    try:
        with gate:
            view = service.submit(
                auth.user_id,
                attempt_id,
                question_result_id,
                [
                    PointVerdict(mark_point_id=p.markPointId, earned=p.earned, evidence=p.evidence)
                    for p in payload.points
                ],
            )
    except SelfReviewError as exc:
        _raise_for(exc)
    return _revealed_dto(view)
```

- [ ] **Step 4: Wire flashcards**

In `lemely/web/routers/flashcards.py`, add:

```python
from lemely.core.metered_actions import MeteredAction
from lemely.web.usage import UsageMeter, get_usage_meter, request_from_auth
```

Add `meter: Annotated[UsageMeter, Depends(get_usage_meter)],` to `generate_deck` after `service`, and replace its body with:

```python
    # Billing spec §2.2: the deck being created carries this subject, so a seat covering
    # flashcards for it pays; `count` is schema-bounded (1..50).
    usage = meter.authorize(
        request_from_auth(
            auth,
            MeteredAction.GENERATE_FLASHCARDS,
            subject_code=body.subjectCode,
            input_count=body.count,
        )
    )
    try:
        with meter.job(usage):
            result = service.generate_deck(
                auth.user_id,
                subject_code=body.subjectCode,
                origin=_parse_origin(body.origin),
                count=body.count,
                topic=body.topic,
                title=body.title,
            )
    except FlashcardError as exc:
        _raise_for(exc)
    return _generated_to_dto(result)
```

- [ ] **Step 5: Wire study plans**

In `lemely/web/routers/study_plan.py`, add:

```python
from lemely.core.metered_actions import MeteredAction
from lemely.web.usage import UsageMeter, get_usage_meter, request_from_auth
```

Add `meter: Annotated[UsageMeter, Depends(get_usage_meter)],` to `create_study_plan` after `service`, and replace `plan = service.generate(auth.user_id, body.subjectCode)` with:

```python
    # Billing spec §2.2: the seat pays only the first plan per subject per ISO week, and
    # only when its scope includes `study_plan`; `load_chain_context` reads which.
    usage = meter.authorize(
        request_from_auth(auth, MeteredAction.STUDY_PLAN, subject_code=body.subjectCode)
    )
    with meter.job(usage):
        plan = service.generate(auth.user_id, body.subjectCode)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_self_review.py tests/test_usage_flashcards.py tests/test_usage_study_plan.py tests/test_student_self_review_web.py tests/test_web_flashcards.py tests/test_web_study_plan.py tests/test_authz_matrix_complete.py -v --no-cov`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/web/routers/student_self_review.py lemely/web/routers/flashcards.py lemely/web/routers/study_plan.py tests/test_usage_self_review.py tests/test_usage_flashcards.py tests/test_usage_study_plan.py
git commit -S -m "feat(usage): meter self-review evidence, flashcard decks and seat-paid study plans" -- lemely/web/routers/student_self_review.py lemely/web/routers/flashcards.py lemely/web/routers/study_plan.py tests/test_usage_self_review.py tests/test_usage_flashcards.py tests/test_usage_study_plan.py
```

---

### Task 13: Meter quiz marking (`POST /api/student/quizzes/{assignment_id}/submit`)

**Files:**
- Modify: `lemely/web/routers/quiz.py`: `_trigger_marking_in_background` (461-506), `submit_student_quiz` (875-913)
- Modify: `tests/test_events_scoping.py:157-185`: the double returns a result and the call passes an unmetered job
- Test: `tests/test_usage_quiz_marking.py`

**Interfaces:**
- Consumes: `UsageMeter`, `MeteredJob`, `get_usage_meter`, `request_from_auth` (Task 6); `quiz_assignment_target` (Task 5); `MarkSubmissionResult.marking_error` (existing).
- Produces: `_trigger_marking_in_background(marking_service, submission_id, job: MeteredJob) -> None`. Submitting reserves `mark_quiz` on the quiz's subject (seat-routed) before the submission is recorded. The fire-and-forget thread settles on success. It releases when marking records a `marking_error` or raises. A refused submit releases the hold.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_usage_quiz_marking.py
"""Metering on quiz marking (Task 13): placement, practice and assigned quizzes all
submit through this route; marking runs on a fire-and-forget thread."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from lemely.core.metered_actions import MeteredAction
from lemely.db.models.enums import Role
from lemely.db.models.usage import UsageJobStatus
from lemely.db.usage_context_repo import quiz_assignment_target
from lemely.io.llm.cost_meter import record_llm_cost
from lemely.web.routers import quiz as quiz_router
from lemely.web.usage import get_usage_meter
from tests import test_web_student_quiz as _quiz
from tests.usage_helpers import enforcing_meter, give, jobs_for, seat, seat_grant, seed_catalogue, seed_user

client = _quiz.client
pg_sessionmaker = _quiz.pg_sessionmaker
class_service = _quiz.class_service
bank_service = _quiz.bank_service
quiz_service = _quiz.quiz_service
taking_service = _quiz.taking_service

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.class_repo import ClassService
    from lemely.db.quiz_repo import QuizService
    from lemely.db.quiz_taking_repo import QuizTakingService


class _InlineThread:
    """Runs the marking thread's target at once, so the settle is visible on return."""

    def __init__(self, target: Callable[[], None], daemon: bool) -> None:
        self._target = target

    def start(self) -> None:
        self._target()


class _CostlyMarking:
    def __init__(self, error: str | None = None) -> None:
        self.error = error

    def mark_submission(self, submission_id: uuid.UUID) -> SimpleNamespace:
        record_llm_cost(Decimal("0.004"))
        return SimpleNamespace(submission_id=submission_id, marking_error=self.error)


@pytest.fixture
def ready(
    client: TestClient,
    pg_sessionmaker: sessionmaker[Session],
    quiz_service: QuizService,
    class_service: ClassService,
    taking_service: QuizTakingService,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, uuid.UUID, uuid.UUID, str]:
    seed_catalogue(pg_sessionmaker)
    monkeypatch.setattr(quiz_router, "threading", SimpleNamespace(Thread=_InlineThread))
    _quiz._use_taking_service(client, taking_service)
    client.app.dependency_overrides[get_usage_meter] = lambda: enforcing_meter(pg_sessionmaker)  # type: ignore[union-attr]
    teacher, class_id, assignment_id = _quiz._assigned_quiz(quiz_service, class_service, pg_sessionmaker)
    student = _quiz._enroll(pg_sessionmaker, class_id)
    _quiz._auth_as(client, student, Role.student)
    client.get(f"/api/student/quizzes/{assignment_id}")
    return client, student, teacher, assignment_id


def _use_marking(client: TestClient, marking: _CostlyMarking) -> None:
    from lemely.web.deps import get_quiz_marking_service

    client.app.dependency_overrides[get_quiz_marking_service] = lambda: marking  # type: ignore[union-attr]


def test_the_target_is_the_quizs_subject_and_question_count(
    ready: tuple[TestClient, uuid.UUID, uuid.UUID, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    _, _, _, assignment_id = ready
    with pg_sessionmaker() as session:
        target = quiz_assignment_target(session, assignment_id=assignment_id)
        assert quiz_assignment_target(session, assignment_id="not-a-uuid") is None
    assert target is not None
    assert (target.subject_code, target.input_count) == ("0625", 1)


def test_submit_without_balance_is_402_and_records_nothing(
    ready: tuple[TestClient, uuid.UUID, uuid.UUID, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    client, student, _, assignment_id = ready
    _use_marking(client, _CostlyMarking())
    resp = client.post(f"/api/student/quizzes/{assignment_id}/submit")
    assert resp.status_code == 402
    # base 1-2 + 1 question x 1-3 = 2-5
    assert resp.json() == {"error": "usage_blocked", "reason": "no_active_plan", "estimate": [2, 5]}
    assert client.get(f"/api/student/quizzes/{assignment_id}").json()["submissionStatus"] != "submitted"


def test_marking_settles_on_the_thread(
    ready: tuple[TestClient, uuid.UUID, uuid.UUID, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    client, student, _, assignment_id = ready
    give(pg_sessionmaker, student, units=100)
    _use_marking(client, _CostlyMarking())
    assert client.post(f"/api/student/quizzes/{assignment_id}/submit").status_code == 200
    (job,) = jobs_for(pg_sessionmaker, student)
    assert (job.action, job.status, job.charged) == ("mark_quiz", UsageJobStatus.settled, 4)


def test_a_marking_error_is_released(
    ready: tuple[TestClient, uuid.UUID, uuid.UUID, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    client, student, _, assignment_id = ready
    give(pg_sessionmaker, student, units=100)
    _use_marking(client, _CostlyMarking(error="model refused"))
    assert client.post(f"/api/student/quizzes/{assignment_id}/submit").status_code == 200
    assert jobs_for(pg_sessionmaker, student)[0].status is UsageJobStatus.released


def test_a_seat_covering_quiz_marking_pays(
    ready: tuple[TestClient, uuid.UUID, uuid.UUID, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    client, student, teacher, assignment_id = ready
    member = seat(pg_sessionmaker, teacher=teacher, student=student, subjects=["0625"],
                  actions=[MeteredAction.MARK_QUIZ])
    seat_grant(pg_sessionmaker, student=student, member_id=member, units=100)
    _use_marking(client, _CostlyMarking())
    assert client.post(f"/api/student/quizzes/{assignment_id}/submit").status_code == 200
    assert jobs_for(pg_sessionmaker, student)[0].teacher_member_id == member


def test_a_refused_second_submit_releases_its_hold(
    ready: tuple[TestClient, uuid.UUID, uuid.UUID, str], pg_sessionmaker: sessionmaker[Session]
) -> None:
    client, student, _, assignment_id = ready
    give(pg_sessionmaker, student, units=100)
    _use_marking(client, _CostlyMarking())
    client.post(f"/api/student/quizzes/{assignment_id}/submit")
    assert client.post(f"/api/student/quizzes/{assignment_id}/submit").status_code == 422
    assert [j.status for j in jobs_for(pg_sessionmaker, student)] == [
        UsageJobStatus.settled, UsageJobStatus.released
    ]
```

The assignment's `submissionStatus` key is the one `tests/test_web_student_quiz.py` reads off the take route. If the take route names it differently, assert on the `quiz_submissions` row instead (none exists for the assignment).

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_quiz_marking.py -v --no-cov`
Expected: FAIL. The 402 test gets 200, and no jobs exist.

- [ ] **Step 3: Meter the marking thread**

In `lemely/web/routers/quiz.py`, add:

```python
from lemely.core.metered_actions import MeteredAction, UsageTarget
from lemely.db.usage_context_repo import quiz_assignment_target
from lemely.web.usage import MeteredJob, UsageMeter, get_usage_meter, request_from_auth
```

Change `_trigger_marking_in_background` to take the job and run marking inside it:

```python
def _trigger_marking_in_background(
    marking_service: QuizMarkingService, submission_id: uuid.UUID, job: MeteredJob
) -> None:
```

Append to its docstring: "``job`` was reserved by the submit request. Its cost scope opens on this thread, which inherits no context from the request. A marking failure that ``mark_submission`` records instead of raising (``marking_error``) is released, never charged (billing spec §2.4)." Replace `run`'s body:

```python
    def run() -> None:
        # DS10: scope this thread's bus events to the submission being marked.
        # (unchanged comment block)
        token = current_run_id.set(f"quiz:{submission_id}")
        try:
            with job.run():
                outcome = marking_service.mark_submission(submission_id)
                if outcome.marking_error is not None:
                    job.abandon()
        except QuizMarkingError as exc:
            log.warning(
                "quiz_marking_trigger_rejected",
                submission_id=str(submission_id),
                error=str(exc),
            )
        except Exception:
            log.exception("quiz_marking_trigger_unexpected_error", submission_id=str(submission_id))
        finally:
            current_run_id.reset(token)
```

In `submit_student_quiz`, add `meter: Annotated[UsageMeter, Depends(get_usage_meter)],` after `xp_service`, and replace the body up to `award_xp_safely(...)` with:

```python
    # Billing spec §5.7: hold before the submission is recorded, so a blocked student
    # can still keep answering. An unknown assignment holds against no subject and is
    # refused by `submit` below, which releases the hold.
    target = meter.resolve_target(
        lambda session: quiz_assignment_target(session, assignment_id=assignment_id)
    ) or UsageTarget(subject_code=None, input_count=0)
    job = meter.reserve(
        meter.authorize(
            request_from_auth(
                auth,
                MeteredAction.MARK_QUIZ,
                subject_code=target.subject_code,
                input_count=target.input_count,
            )
        )
    )
    try:
        result = service.submit(auth.user_id, assignment_id)
    except (QuizTakingNotFoundError, QuizTakingOwnershipError, QuizTakingValidationError) as exc:
        job.release()
        _raise_for_taking(exc)
    except ValueError as exc:
        job.release()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

and change the trigger call to `_trigger_marking_in_background(marking_service, result.submission_id, job)`.

- [ ] **Step 4: Update the run-id scoping test**

In `tests/test_events_scoping.py::test_quiz_marking_thread_sets_its_run_id`, add `from types import SimpleNamespace` and the imports `from lemely.core.metered_actions import MeteredAction` and `from lemely.web.usage import MeteredJob`. Change the double and the call:

```python
    class _RecordingMarkingService:
        def mark_submission(self, sid: uuid.UUID) -> SimpleNamespace:
            seen.append(current_run_id.get())
            done.set()
            return SimpleNamespace(submission_id=sid, marking_error=None)

    _trigger_marking_in_background(
        _RecordingMarkingService(),  # type: ignore[arg-type]
        submission_id,
        MeteredJob.unmetered(MeteredAction.MARK_QUIZ),
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_quiz_marking.py tests/test_web_student_quiz.py tests/test_events_scoping.py tests/test_authz_matrix_complete.py -v --no-cov`
Expected: PASS. (`tests/test_web_student_quiz.py`'s recording double returns `None`. In its daemon thread, `outcome.marking_error` raises `AttributeError`, which is caught and logged by the thread's `except Exception`. Its assertions only check that marking was triggered, so it stays green.)

- [ ] **Step 6: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/web/routers/quiz.py tests/test_events_scoping.py tests/test_usage_quiz_marking.py
git commit -S -m "feat(usage): meter quiz marking on its background thread" -- lemely/web/routers/quiz.py tests/test_events_scoping.py tests/test_usage_quiz_marking.py
```

---

### Task 14: Sweeper jobs and the metered-route coverage guard

**Files:**
- Create: `lemely/web/usage_sweeps.py`
- Modify: `lemely/web/scheduled_notifications.py`: `Sweeper` gains `usage_metering: bool = False` and `usage_reconcile: ReconcileMemo`, and `sweep_once` appends the usage jobs
- Modify: `lemely/web/deps.py`: `get_sweeper` passes `usage_metering=settings.usage.enforce`
- Test: `tests/test_usage_sweeps.py`, `tests/test_usage_route_coverage.py`

**Interfaces:**
- Consumes: `UsageLedger.expire_stale_jobs`, `expire_grants`, `reconcile_balances` (phase 01); `run_jobs` (existing).
- Produces: `RECONCILE_HOUR_UTC = 2`, `ReconcileMemo(last_date: date | None = None)`, `usage_jobs(sessionmaker, *, now, memo) -> list[tuple[str, Callable[[], int]]]` with names `usage.expire_stale_jobs`, `usage.expire_grants` (every pass) and `usage.reconcile_balances` (once per UTC day after 02:00). Also `expire_stale_jobs(sm, *, now) -> int`, `expire_grants(sm, *, now) -> int`, `reconcile_balances(sm, *, now, memo) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_usage_sweeps.py
"""Usage sweeper jobs (Task 14): stale jobs, expired grants, nightly reconcile."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from structlog.testing import capture_logs

from lemely.core.metered_actions import MeteredAction
from lemely.db.models.usage import GrantKind, UsageGrantBalance, UsageJobStatus
from lemely.runtime.config import NotificationsSettings
from lemely.web.scheduled_notifications import Sweeper
from lemely.web.usage import request_from_auth
from lemely.web.usage_sweeps import ReconcileMemo, reconcile_balances, usage_jobs
from lemely.web.deps import AuthContext
from tests.usage_helpers import NOW, enforcing_meter, give, jobs_for, seed_catalogue, seed_user

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

AT_3AM = datetime(2026, 11, 5, 3, 0, tzinfo=UTC)


def test_job_names_and_the_nightly_gate(migrated_sessionmaker: sessionmaker[Session]) -> None:
    memo = ReconcileMemo()
    early = datetime(2026, 11, 5, 1, 0, tzinfo=UTC)
    assert [n for n, _ in usage_jobs(migrated_sessionmaker, now=early, memo=memo)] == [
        "usage.expire_stale_jobs", "usage.expire_grants",
    ]
    assert [n for n, _ in usage_jobs(migrated_sessionmaker, now=AT_3AM, memo=memo)] == [
        "usage.expire_stale_jobs", "usage.expire_grants", "usage.reconcile_balances",
    ]
    memo.last_date = AT_3AM.date()
    assert len(usage_jobs(migrated_sessionmaker, now=AT_3AM, memo=memo)) == 2


def test_stale_open_jobs_expire_and_grants_past_expiry_expire(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student = seed_user(sm)
    give(sm, student, units=500)
    give(sm, student, units=40, expires_at=NOW + timedelta(hours=1))
    meter = enforcing_meter(sm)
    auth = AuthContext(user_id=str(student), role="student")
    meter.reserve(meter.authorize(request_from_auth(auth, MeteredAction.MARK_PAPER)))
    later = NOW + timedelta(hours=2)  # mark_paper timeout 45 min + 10 min slack has passed
    results = dict((name, job()) for name, job in usage_jobs(sm, now=later, memo=ReconcileMemo()))
    assert results["usage.expire_stale_jobs"] == 1
    assert results["usage.expire_grants"] >= 1
    assert jobs_for(sm, student)[0].status is UsageJobStatus.expired


def test_reconcile_logs_drift_and_records_the_day(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student = seed_user(sm)
    grant_id = give(sm, student, units=100, kind=GrantKind.credit_pack)
    with sm.begin() as session:
        session.get(UsageGrantBalance, grant_id).remaining = 90  # cache drifts from entries
    memo = ReconcileMemo()
    with capture_logs() as logs:
        drift = reconcile_balances(sm, now=AT_3AM, memo=memo)
    assert drift == 1
    assert memo.last_date == AT_3AM.date()
    assert [e for e in logs if e["event"] == "usage_balance_drift"][0]["grant_id"] == str(grant_id)


def test_the_sweeper_runs_the_usage_jobs_only_when_metering(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    def build(metering: bool) -> Sweeper:
        return Sweeper(
            sessionmaker=migrated_sessionmaker,
            announcements=MagicMock(),
            notifications=MagicMock(),
            transport=MagicMock(),
            settings=NotificationsSettings(),
            now=lambda: AT_3AM,
            usage_metering=metering,
        )

    on, off = build(True).sweep_once(), build(False).sweep_once()
    assert {"usage.expire_stale_jobs", "usage.expire_grants", "usage.reconcile_balances"} <= set(on)
    assert not any(name.startswith("usage.") for name in off)
```

If phase 01 keys `UsageGrantBalance` by something other than `grant_id` as its primary key, load the row with `session.scalars(select(UsageGrantBalance).where(UsageGrantBalance.grant_id == grant_id)).one()`. If phase 01's `reconcile_balances` repairs the cache as well as reporting it, the assertions still hold: the job reports and logs what it found.

```python
# tests/test_usage_route_coverage.py
"""Every route that can reach a model is metered (billing plan phase 04 audit).

A new route that depends on the Gemini client or the quiz marker, and does not resolve
the usage meter, fails here. A metered route that stops resolving the meter fails here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.routing import APIRoute

from lemely.web import create_app
from lemely.web.deps import get_gemini_client, get_quiz_marking_service
from lemely.web.usage import get_usage_meter

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from fastapi.dependencies.models import Dependant

#: The audit's route list (plan "Audit" table), method and path as mounted.
METERED: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/student/correct"),
        ("POST", "/api/papers/upload"),
        ("POST", "/api/papers/{paper_id}/regrade"),
        ("POST", "/api/quizzes/preview"),
        ("POST", "/api/quizzes/generate"),
        ("POST", "/api/student/attempts/{attempt_id}/questions/{question_result_id}/self-review"),
        ("POST", "/api/student/flashcards/decks/generate"),
        ("POST", "/api/student/quizzes/{assignment_id}/submit"),
        ("POST", "/api/student/study-plan"),
    }
)
_MODEL_DEPENDENCIES: tuple[Callable[..., object], ...] = (get_gemini_client, get_quiz_marking_service)


def _walk(dependant: Dependant) -> Iterator[Dependant]:
    yield dependant
    for sub in dependant.dependencies:
        yield from _walk(sub)


def _routes() -> dict[tuple[str, str], APIRoute]:
    return {
        (method, route.path): route
        for route in create_app().routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }


def _calls(route: APIRoute) -> set[object]:
    return {d.call for d in _walk(route.dependant)}


def test_every_route_that_can_reach_a_model_is_metered() -> None:
    reaching = {key for key, route in _routes().items() if _calls(route) & set(_MODEL_DEPENDENCIES)}
    assert reaching <= METERED, reaching - METERED


def test_every_metered_route_resolves_the_meter() -> None:
    routes = _routes()
    assert METERED <= set(routes), METERED - set(routes)
    missing = {key for key in METERED if get_usage_meter not in _calls(routes[key])}
    assert missing == set()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_sweeps.py tests/test_usage_route_coverage.py -v --no-cov`
Expected: `test_usage_sweeps.py` fails with `ModuleNotFoundError: No module named 'lemely.web.usage_sweeps'`. `test_usage_route_coverage.py` passes, because Tasks 9–13 wired every route. Prove it can fail: temporarily delete the `meter` parameter from `create_study_plan`, see `test_every_metered_route_resolves_the_meter` go red, then restore it.

- [ ] **Step 3: Write the sweeper jobs**

```python
# lemely/web/usage_sweeps.py
"""Usage ledger sweeps (billing spec §5.7 step 7, §5.8, §6), run by ``Sweeper``.

* ``usage.expire_stale_jobs``: open jobs past ``expires_at`` (a crashed worker, a pool
  job that never ran) are released and marked ``expired``; no charge.
* ``usage.expire_grants``: grants past ``expires_at`` expire their unheld remainder.
* ``usage.reconcile_balances``: once per UTC day after ``RECONCILE_HOUR_UTC``, compare the
  cached balances with the entries and log every drift as an error (the alert).

All three are idempotent, so a second replica running the same pass does no harm. The
ledger takes row locks in a fixed order, and a re-run finds nothing left to do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from lemely.db.usage_ledger_repo import UsageLedger

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date, datetime

    from sqlalchemy.orm import Session, sessionmaker

log = structlog.get_logger(__name__)

RECONCILE_HOUR_UTC = 2


@dataclass(slots=True)
class ReconcileMemo:
    """The UTC date the reconcile last ran in this process."""

    last_date: date | None = None


def expire_stale_jobs(sm: sessionmaker[Session], *, now: datetime) -> int:
    with sm.begin() as session:
        return UsageLedger(session).expire_stale_jobs(now=now)


def expire_grants(sm: sessionmaker[Session], *, now: datetime) -> int:
    with sm.begin() as session:
        return UsageLedger(session).expire_grants(now=now)


def reconcile_balances(sm: sessionmaker[Session], *, now: datetime, memo: ReconcileMemo) -> int:
    """Log every cached-balance drift; returns how many grants drifted."""
    with sm.begin() as session:
        drift = UsageLedger(session).reconcile_balances()
    for grant_id, cached, actual in drift:
        log.error("usage_balance_drift", grant_id=str(grant_id), cached=cached, actual=actual)
    memo.last_date = now.date()
    return len(drift)


def usage_jobs(
    sm: sessionmaker[Session], *, now: datetime, memo: ReconcileMemo
) -> list[tuple[str, Callable[[], int]]]:
    """This pass's usage jobs, named for ``run_jobs``'s result map and the admin health view."""
    jobs: list[tuple[str, Callable[[], int]]] = [
        ("usage.expire_stale_jobs", lambda: expire_stale_jobs(sm, now=now)),
        ("usage.expire_grants", lambda: expire_grants(sm, now=now)),
    ]
    if memo.last_date != now.date() and now.hour >= RECONCILE_HOUR_UTC:
        jobs.append(
            ("usage.reconcile_balances", lambda: reconcile_balances(sm, now=now, memo=memo))
        )
    return jobs
```

- [ ] **Step 4: Run them from the sweeper**

In `lemely/web/scheduled_notifications.py`, add `from lemely.web.usage_sweeps import ReconcileMemo, usage_jobs` to the imports. Add these fields to `Sweeper` after `email_daily_cap`:

```python
    #: Billing spec §5.7: the usage ledger's sweeps run only where metering is enforced
    #: (``deps.get_sweeper``); a sweeper built for notifications alone, as most tests
    #: build one, keeps exactly the jobs it had.
    usage_metering: bool = False
    usage_reconcile: ReconcileMemo = field(default_factory=ReconcileMemo)
```

In `sweep_once`, directly before `return run_jobs(jobs)`, add:

```python
        if self.usage_metering:
            jobs.extend(usage_jobs(self.sessionmaker, now=moment, memo=self.usage_reconcile))
```

Update `sweep_once`'s docstring first line to: `"""Run announcements, streaks, study-plan reminders, purge, tutoring email and usage sweeps, once each."""`.

In `lemely/web/deps.py::get_sweeper`, add `usage_metering=settings.usage.enforce,` to the `Sweeper(...)` call.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_sweeps.py tests/test_usage_route_coverage.py tests/test_scheduled_notifications.py tests/architecture/ -v --no-cov`
Expected: PASS. (If the sweeper's own test file has a different name, find it with `grep -rln "Sweeper(" tests` and run that file.)

- [ ] **Step 6: Final phase sweep**

Run every test file this phase touched, plus the source-scanning gates:

```bash
PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest \
  tests/test_metered_actions.py tests/test_cost_meter.py tests/test_payer_chain.py \
  tests/test_usage_catalogue_repo.py tests/test_usage_context_repo.py tests/test_web_usage_meter.py \
  tests/test_web_usage_routes.py tests/test_usage_signup.py tests/test_usage_student_correct.py \
  tests/test_usage_teacher_marking.py tests/test_usage_teacher_quiz.py tests/test_usage_self_review.py \
  tests/test_usage_flashcards.py tests/test_usage_study_plan.py tests/test_usage_quiz_marking.py \
  tests/test_usage_sweeps.py tests/test_usage_route_coverage.py \
  tests/test_student_correct.py tests/test_web_teacher.py tests/test_teacher_paper_deletion.py \
  tests/test_student_self_review_web.py tests/test_web_flashcards.py tests/test_web_study_plan.py \
  tests/test_web_student_quiz.py tests/test_email_verified_first_timestamp.py tests/test_seed.py \
  tests/architecture/ tests/test_authz_matrix_complete.py tests/test_script_cost_scope.py \
  tests/test_events_scoping.py tests/test_marking_options_wiring.py tests/test_include_deleted_scope.py \
  tests/test_settings_example_drift.py -v --no-cov
```

Expected: PASS. Then run `/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files` until it is clean. Then run `graphify update .` (project rule after code changes).

- [ ] **Step 7: Commit**

```bash
git add lemely/web/usage_sweeps.py lemely/web/scheduled_notifications.py lemely/web/deps.py tests/test_usage_sweeps.py tests/test_usage_route_coverage.py graphify-out
git commit -S -m "feat(usage): usage ledger sweeps and a guard that every model route is metered" -- lemely/web/usage_sweeps.py lemely/web/scheduled_notifications.py lemely/web/deps.py tests/test_usage_sweeps.py tests/test_usage_route_coverage.py graphify-out
```

(Leave `graphify-out` out of both commands if `graphify update .` changed nothing.)

---

## Spec coverage

| Spec requirement | Task |
|---|---|
| §2.1 free start (student one-time hidden allowance, teacher 30-day credits, admin-configured) | 4, 8 |
| §2.2 per-subject seat routing, subject from the server-side record | 3, 5, 9, 12, 13 |
| §2.2 study plans seat-paid only when in scope and only for the first generation per subject per week | 3, 5, 12 |
| §2.3 / R4 assistant work always billed to the lead within the per-assistant cap; the assistant's own balance never pays | 3, 5, 6, 7, 10, 11 |
| §2.4 range estimate first; start only if the chain covers the top; charge actual cost; debt; failed jobs free; usage history | 6, 7, 9–13 |
| §3 metering hook works inside SSE generators and thread pools | 2, 6, 9, 10, 13 |
| §5.6 payer chain table, two seats ordering, subject-less, debt skip, last resort | 3 |
| §5.7 estimate endpoint without writes; reserve under the ledger's locks; settle, release, expire | 6, 7, 14 |
| §6 / §5.7 step 7 crash safety, nightly reconcile with drift alert | 14 |
| §7 estimate rate-limited; seat scope from the server, never client input | 5, 7 |
| §9 unit tests per chain row, per-subject routing, study-plan seat rule; router 402 reasons incl. `outstanding_debt` and `out_of_seat_scope` | 3, 6, 9–13 |
