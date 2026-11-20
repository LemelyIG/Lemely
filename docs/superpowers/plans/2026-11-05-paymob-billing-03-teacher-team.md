# Paymob billing 03 — teacher team Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a teacher lease student seats through the existing class join flow, set each seat's scope and cap, and attach assistants whose role-based permissions let them act on the lead teacher's resources. Billing and seat management stay with the lead teacher.

**Architecture:** One new table, `teacher_members`, holds both seats (`kind=student_seat`) and assistants (`kind=assistant`). `TeacherTeamService` works inside a caller's SQLAlchemy `Session`, so the class join can claim a seat in the same transaction as the enrolment. A seat is refused when active plus leaving seats would exceed `included_seats + extra_seats`, checked under a row lock on the teacher's live subscription. `require_team_permission(perm)` is a FastAPI dependency. It resolves the acting teacher from an optional `X-Lemely-Acting-Teacher` header and returns a `TeamActor` whose `auth` is scoped to the lead teacher. Existing teacher endpoints adopt it with a two-line change per handler. The new `/api/teacher/team` router is lead-teacher only.

**Tech Stack:** FastAPI, SQLAlchemy 2.x (`Mapped`), Alembic, Postgres 16 (enums, `ARRAY`, `JSONB`, `SELECT … FOR UPDATE`), pydantic v2, pytest against throwaway Postgres databases.

**Spec:** `docs/superpowers/specs/2026-11-02-paymob-billing-design.md` §2.2, §2.3, §3 (Teacher team, Team permissions rows), §4.4, §5.6, §5.9, §7, §9.
**Index and shared contracts:** `docs/superpowers/plans/2026-11-05-paymob-billing-00-index.md` §Phase 03.

## Contract deviations

These differ from the index's Phase 03 contract. Each is the closest correct version.

1. **`lemely/core/metered_actions.py` is created here, not in Phase 04.** Phase 03 has to validate `scope_actions` against `MeteredAction` before Phase 04 exists. This phase creates the module with the six base values (`mark_paper`, `regrade`, `generate_quiz`, `preview_quiz`, `self_review`, `study_plan`). Per index R12, each value has a `has_subject` and a `seat_eligible` property (seat-eligible: `mark_paper`, `self_review`, `study_plan`), and the module exports `SEAT_ACTIONS`, which scope validation uses. Phase 04 replaces the body: it adds `mark_quiz` and `generate_flashcards` and moves the flags into `ACTION_SPECS`. Phase 03 code imports only `MeteredAction` and `SEAT_ACTIONS`, which Phase 04 keeps. The default seat scope (`default_seat_actions()`, `SEAT_ACTIONS_OFF_BY_DEFAULT`) lives in `teacher_team_repo`, so it picks up Phase 04's new seat actions with no change here.
2. **`lemely/core/team_permissions.py` declares its own `AssistantRole` StrEnum.** It mirrors `lemely.db.models.team.AssistantRole`. `lemely/db/models/*` must not import `lemely.core`, and `lemely/core` is pure (no `lemely.db` import anywhere in it today). `PRESET_PERMISSIONS` is keyed by the core enum. `effective_permissions(role, overrides)` accepts the model enum, the core enum or a plain string, because both enums are `StrEnum`. A test pins the two enums member-for-member, as `study_plan.py` does.
3. **`TeamActor` has a fourth field, `auth: AuthContext`.** For the lead teacher it is the caller's own `AuthContext`. For an assistant it is `AuthContext(user_id=<lead id>, role="teacher")`. With it, an adopted handler keeps its body unchanged after one added line, `auth = actor.auth`. **`require_team_permission(perm, *roles)` also accepts optional roles.** The default is `(Role.teacher,)`. Each adopted route passes the roles it already allows, so `tests/test_authz_matrix_complete.py`'s wired-guard check reads the same role set as before.
4. **`TeacherTeamService.__init__(self, session: Session)`.** The index gives no constructor. A session-bound service is the only way to claim a seat inside the class join transaction, and it matches `UsageLedger(session)`. A new `TeacherTeamStore(sessionmaker)` opens one transaction per unit of work for routers and the team guard (`with store.transaction() as team:`).
   - **Added public methods:** `seats_used`, `owned_member`, `list_seats`, `list_assistants`, `update_assistant`, `remove_assistant`, `memberships_for_assistant` and `display_names`.
   - **Added helper:** a module-level `month_end(now)`.
   - **Exceptions:** `NoFreeSeat` subclasses a new `TeamError(Exception)`, so it is still an `Exception`.
5. **`invites` also gains `assistant_role` (nullable `assistantrole`) and `ck_invites_assistant_shape`.** `create_assistant_invite(..., role=...)` needs somewhere to store the role the invite grants until redemption. The check is `(role::text = 'assistant') = (team_teacher_id IS NOT NULL) AND (role::text = 'assistant') = (assistant_role IS NOT NULL)`: an assistant invite has both columns, and no other invite has either. It compares `role::text` because a value added by `ALTER TYPE … ADD VALUE` cannot be used as an enum literal in the same transaction.
6. **Invite code generation moves to `lemely/db/invite_codes.py`.** `class_repo` will import `teacher_team_repo`, and `invite_repo` imports `class_repo`. If `teacher_team_repo` imported `invite_repo` there would be an import cycle. `invite_repo` now imports from the new module, and its codes and behaviour are unchanged.

## Decisions (spec readings the reviewer should check)

- **Seat claim scope.** Only joins of a **school-less** class (`classes.school_id IS NULL`) by a user whose role is `student` claim a seat. Spec §2.8 keeps school billing out of scope, and school classes enrol through school seats. A teacher redeeming a class code never takes a seat.
- **Enforcement switch (index R5).**
  - `TeamSettings.enforce_teacher_seats` defaults to **true** (`Settings.team`, env `LEMELY_TEAM__ENFORCE_TEACHER_SEATS`). It is not emitted to `lemely.toml.example`, like Phase 04's `usage.enforce`.
  - Only the test suite turns it off: a session-wide autouse fixture in `tests/conftest.py` sets `LEMELY_TEAM__ENFORCE_TEACHER_SEATS=0`. The 33 existing test files that join classes use teachers with no plan, and keep passing.
  - `ClassService(sessionmaker, *, enforce_teacher_seats: bool | None = None)`. `None` reads `Settings().team.enforce_teacher_seats`, so the more than 100 direct `ClassService(sm)` constructions in tests follow the suite switch, and any other caller gets the enforcing default. `get_class_service` passes `get_settings().team.enforce_teacher_seats` explicitly, so `lemely.toml` overrides apply.
  - When enforced, `NoFreeSeat` refuses the join (409 `no_free_seat`) and rolls back the enrolment. When not enforced, a free seat is still claimed; otherwise the student is enrolled without a seat.
  - Tests prove that settings built with no override, and the app's `get_class_service` built from them, enforce.
- **Rejoin while `leaving`.** The seat stays `leaving` (the teacher's removal stands) and the class subject is added to its scope. A rejoin after `removed` reactivates the row with fresh default scope, subject to the seat count.
- **Removing an assistant is immediate** (`status=removed`). The month-end rule (§2.2) is about seat allowances, which assistants do not have.
- **The marker preset is `{mark, regrade, view_results}`.** "Mark and regrade only" (§2.3) is read as the write actions. A marker must still read the paper and review item it marks, and the console's read routes are gated by `view_results`. Viewer is `{view_results, view_usage}`. Co-teacher is all seven permissions.
- **Who an action is recorded against.** An assistant's actions through adopted routes are recorded against the lead teacher's id (`actor.auth.user_id`), for example `acknowledged_by` and `uploaded_by`. `TeamActor.actor_user_id` and `member_id` keep the real actor for Phase 04 metering.
- **Assistant invite redemption** happens only at `POST /api/teacher/team/assistants/redeem`.
  - The generic `POST /api/invites/{code}/redeem` refuses an assistant invite with its existing fixed 403.
  - `GET /api/invites/{code}` previews an assistant invite (role `assistant`, the lead teacher's name).
- **Invite redemption rate limit.** `POST /api/teacher/team/assistants/redeem` allows 10 attempts per user per 10 minutes, as spec §7 requires. Live unredeemed assistant invites are capped at 20 per teacher.

## Global Constraints

- Signed commits only, with a path list: `git add <new files>` then `git commit -S -m "<msg>" -- <paths>`. Scope `feat(team):` (`test(team):` for test-only commits).
- Before each commit, run `/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files`. If it rewrites files, re-add them and run it again until it passes with no changes.
- Every pytest command carries `--no-cov` (index R2: the repo's `--cov-fail-under=70` fails any subset run).
- Run Python as `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/<tool>` from `/home/sico/Code/Lemely/.claude/worktrees/paymob-integration`.
- Never run the full suite. Run only the test files a task names. When a task adds a module under `lemely/`, also run `tests/architecture/`.
- Do not push and do not open PRs.
- UUID PKs `server_default=sa.text("gen_random_uuid()")`, Postgres enums, `TimestampMixin`. Usage units are `BIGINT`.
- `lemely/db/models/*` never imports `lemely.core`. `lemely/core/*` never imports `lemely.db`, `lemely.web` or `sqlalchemy`.
- Billing, plan changes, seat purchases, seat scope, caps and assistants are never team permissions. Their routes act only on the caller's own team.
- No `TODO`, no `pass` bodies, no skipped or stub tests.
- After the last task, run `graphify update .` (AST only).

## Prerequisites (consumed from earlier phases)

Phase 01 (`0052_usage_ledger`) and Phase 02 (`0053_billing_payments`) must be merged into the branch. This plan uses these names. Task 2 Step 1 and Task 3 Step 1 check them:

| Name | From | Used for |
|---|---|---|
| `lemely.db.models.usage.UsageGrant.teacher_member_id` (plain nullable UUID column) | Phase 01 | FK to `teacher_members` added here |
| `PlanAudience` (`lemely/db/models/billing.py`, members `student`, `teacher`), `PlanTier.audience`, `PlanTier.included_seats` | Phase 02 (checked against its plan) | seat capacity |
| `Subscription.extra_seats`, `Subscription.payer_user_id` | Phase 02 | seat capacity, test seeding |
| `SubscriptionStatus.past_due` | Phase 02 | a `past_due` plan still holds seats (grace, §5.2) |
| Alembic revision id `0053_billing_payments` | Phase 02 | `down_revision` of 0054 |

If Phase 02 named any of these differently, use its name everywhere this plan uses the name above. Record the substitution in the task's commit message body.

## File structure

| File | Status | Responsibility |
|---|---|---|
| `lemely/core/metered_actions.py` | Create | `MeteredAction` base values with `has_subject` and `seat_eligible`; `SEAT_ACTIONS` (R12) |
| `lemely/core/team_permissions.py` | Create | `AssistantRole` (core mirror), `TeamPermission`, presets, override validation, effective permissions |
| `lemely/db/models/team.py` | Create | `TeacherMemberKind`, `TeacherMemberStatus`, `AssistantRole`, `CapPeriod`, `TeacherMember` |
| `lemely/db/models/enums.py` | Modify | `InviteRole.assistant` |
| `lemely/db/models/invites.py` | Modify | `team_teacher_id`, `assistant_role`, widened `ck_invites_target`, `ck_invites_assistant_shape` |
| `lemely/db/models/usage.py` | Modify | FK `usage_grants.teacher_member_id → teacher_members.id` |
| `lemely/db/models/__init__.py` | Modify | register `team`, re-export `TeacherMember` |
| `lemely/db/migrations/versions/0054_teacher_team.py` | Create | schema for all of the above |
| `lemely/db/invite_codes.py` | Create | shared invite code generator |
| `lemely/db/invite_repo.py` | Modify | use `invite_codes`; refuse assistant invites in `redeem`; preview names the lead teacher |
| `lemely/db/teacher_team_repo.py` | Create | `TeacherTeamService`, `TeacherTeamStore`, team exceptions, `month_end` |
| `lemely/db/class_repo.py` | Modify | seat claim inside `join_by_code_with_notice`; `enforce_teacher_seats` |
| `lemely/runtime/config.py` | Modify | `TeamSettings(enforce_teacher_seats=True)` as `Settings.team` (R5) |
| `tests/conftest.py` | Modify | suite-wide `LEMELY_TEAM__ENFORCE_TEACHER_SEATS=0` (R5) |
| `lemely/web/team_http.py` | Create | `no_free_seat_error()`, `team_error_to_http()` |
| `lemely/web/deps.py` | Modify | `TeamActor`, `require_team_permission`, `get_teacher_team_store`, `get_assistant_redeem_limiter`, enforced `get_class_service` |
| `lemely/web/schemas_team.py` | Create | team router DTOs |
| `lemely/web/routers/teacher_team.py` | Create | `/api/teacher/team/*` |
| `lemely/web/app.py` | Modify | include `teacher_team.router` |
| `pyproject.toml` | Modify | `TC001–TC003` per-file-ignores for `routers/teacher_team.py` and `schemas_team.py`, as for every runtime-annotated router/schema module |
| `lemely/web/schemas_invites.py` | Modify | `InvitePreviewDTO.role` accepts `"assistant"` |
| `lemely/web/routers/invites.py`, `lemely/web/routers/student.py` | Modify | map `NoFreeSeat` to 409 |
| `lemely/web/routers/classes.py`, `announcements.py`, `teacher.py`, `quiz.py`, `review.py` | Modify | adopt `require_team_permission` |
| `tests/team_db.py` | Create | shared DB helpers for the team tests |
| `tests/test_metered_actions.py`, `tests/test_team_permissions.py`, `tests/test_team_schema.py`, `tests/test_migration_teacher_team.py`, `tests/test_teacher_team_seats.py`, `tests/test_teacher_team_assistants.py`, `tests/test_team_seat_claim_join.py`, `tests/test_team_permission_dep.py`, `tests/test_web_teacher_team.py`, `tests/test_team_permission_adoption.py`, `tests/test_web_team_adoption.py` | Create | tests |
| `tests/test_authz_matrix_complete.py` | Modify | register the 13 team routes |
| `tests/test_web_app.py` | Modify | `grading_queue` direct call takes a `TeamActor` |

## Endpoint → permission map (audit result)

Every route below currently answers to the role guard shown. After adoption it answers to the **same** role guard plus the team permission. Callers with no `X-Lemely-Acting-Teacher` header see no change.

| Route | Handler (file) | Roles passed | Permission |
|---|---|---|---|
| `POST /api/papers/upload` | `upload_paper` (teacher.py) | STAFF | `mark` |
| `GET /api/papers` | `list_papers` (teacher.py) | STAFF | `view_results` |
| `POST /api/papers/{paper_id}/regrade` | `regrade_paper` (teacher.py) | STAFF | `regrade` |
| `GET /api/papers/deleted` | `list_deleted_papers` (teacher.py) | STAFF | `view_results` |
| `DELETE /api/papers/{paper_id}` | `delete_paper` (teacher.py) | STAFF | `manage_classes` |
| `POST /api/papers/{paper_id}/restore` | `restore_paper` (teacher.py) | STAFF | `manage_classes` |
| `GET /api/papers/{paper_id}` | `get_paper` (teacher.py) | STAFF | `view_results` |
| `GET /api/papers/{paper_id}/preview` | `get_paper_preview` (teacher.py) | STAFF | `view_results` |
| `GET /api/grading/queue` | `grading_queue` (teacher.py) | STAFF | `view_results` |
| `GET /api/quizzes/pools` | `quiz_pools` (teacher.py) | STAFF | `generate_quiz` |
| `POST /api/quizzes/preview` | `quiz_preview` (teacher.py) | STAFF | `generate_quiz` |
| `POST /api/quizzes/generate` | `quiz_generate` (teacher.py) | STAFF | `generate_quiz` |
| `GET /api/teacher/overview` | `teacher_overview` (teacher.py) | STAFF | `view_results` |
| `GET /api/teacher/students/{student_id}` | `teacher_student_detail` (teacher.py) | STAFF | `view_results` |
| `GET /api/teacher/at-risk` | `teacher_at_risk_list` (teacher.py) | STAFF | `view_results` |
| `POST /api/teacher/at-risk/{student_id}/acknowledge` | `acknowledge_at_risk_flag` (teacher.py) | STAFF | `manage_students` |
| `DELETE /api/teacher/at-risk/{student_id}/acknowledge/{reason}` | `unacknowledge_at_risk_flag` (teacher.py) | STAFF | `manage_students` |
| `GET /api/teacher/classes` | `list_classes` (classes.py) | STAFF | `view_results` |
| `GET /api/classes/{class_id}` | `get_class` (classes.py) | STAFF | `view_results` |
| `GET /api/classes/{class_id}/analytics` | `class_analytics` (classes.py) | STAFF | `view_results` |
| `POST /api/classes` | `create_class` (classes.py) | teacher | `manage_classes` |
| `PATCH /api/classes/{class_id}` | `update_class` (classes.py) | teacher | `manage_classes` |
| `DELETE /api/classes/{class_id}` | `delete_class` (classes.py) | teacher | `manage_classes` |
| `GET /api/classes/{class_id}/roster` | `get_roster` (classes.py) | STAFF | `view_results` |
| `POST /api/classes/{class_id}/enroll` | `enroll_student` (classes.py) | STAFF | `manage_students` |
| `DELETE /api/classes/{class_id}/students/{student_id}` | `remove_student` (classes.py) | STAFF | `manage_students` |
| `GET /api/classes/{class_id}/papers` | `list_class_papers` (classes.py) | teacher, school_admin | `view_results` |
| `POST /api/classes/{class_id}/papers/{attempt_id}/unshare` | `unshare_paper` (classes.py) | teacher, school_admin | `manage_classes` |
| `DELETE /api/classes/{class_id}/papers/{attempt_id}/unshare` | `reshare_paper` (classes.py) | teacher, school_admin | `manage_classes` |
| `POST /api/school/classes/{class_id}/invite-code` | `mint_class_invite_code` (classes.py) | teacher, school_admin | `manage_students` |
| `POST /api/teacher/quizzes` | `create_quiz` (quiz.py) | STAFF | `generate_quiz` |
| `GET /api/teacher/quizzes` | `list_quizzes` (quiz.py) | STAFF | `view_results` |
| `GET /api/teacher/quizzes/pool-count` | `quiz_pool_count` (quiz.py) | STAFF | `view_results` |
| `GET /api/teacher/quizzes/{quiz_id}` | `get_quiz` (quiz.py) | STAFF | `view_results` |
| `PATCH /api/teacher/quizzes/{quiz_id}` | `patch_quiz_draft` (quiz.py) | STAFF | `generate_quiz` |
| `POST /api/teacher/quizzes/{quiz_id}/status` | `set_quiz_status` (quiz.py) | STAFF | `generate_quiz` |
| `POST /api/teacher/quizzes/{quiz_id}/questions/generate` | `generate_quiz_questions` (quiz.py) | STAFF | `generate_quiz` |
| `DELETE /api/teacher/quizzes/{quiz_id}/questions/{question_ref}` | `remove_quiz_question` (quiz.py) | STAFF | `generate_quiz` |
| `POST /api/teacher/quizzes/{quiz_id}/assignments` | `create_quiz_assignment` (quiz.py) | STAFF | `generate_quiz` |
| `GET /api/teacher/quizzes/{quiz_id}/assignments` | `list_quiz_assignments` (quiz.py) | STAFF | `view_results` |
| `DELETE /api/teacher/quizzes/{quiz_id}/assignments/{assignment_id}` | `delete_quiz_assignment` (quiz.py) | STAFF | `generate_quiz` |
| `GET /api/teacher/quizzes/{quiz_id}/assignments/{assignment_id}/results` | `quiz_assignment_results` (quiz.py) | STAFF | `view_results` |
| `GET /api/teacher/review` | `list_review_queue` (review.py) | STAFF | `view_results` |
| `GET /api/teacher/review/{item_id}` | `get_review_item` (review.py) | STAFF | `view_results` |
| `GET /api/teacher/review/{item_id}/crop` | `get_review_item_crop` (review.py) | STAFF | `view_results` |
| `POST /api/teacher/review/bulk-approve` | `bulk_approve_review_items` (review.py) | STAFF | `mark` |
| `POST /api/teacher/review/{item_id}/resolve` | `resolve_review_item` (review.py) | STAFF | `mark` |
| `POST /api/teacher/review/{item_id}/dismiss` | `dismiss_review_item` (review.py) | STAFF | `mark` |
| `GET /api/teacher/announcements` | `list_announcements` (announcements.py) | teacher, school_admin | `view_results` |
| `POST /api/teacher/announcements` | `create_announcement` (announcements.py) | teacher, school_admin | `manage_classes` |
| `DELETE /api/teacher/announcements/{announcement_id}` | `delete_announcement` (announcements.py) | teacher, school_admin | `manage_classes` |

STAFF = `(Role.teacher, Role.school_admin, Role.platform_admin)`, which is the files' existing `_STAFF_ROLES`. For `announcements.py`, `_STAFF_ROLES` is `(Role.teacher, Role.school_admin)`.

**Not adopted, on purpose:**

- `GET /api/schemes`, `POST /api/schemes` and `GET /api/quizzes/topics` take no caller identity. They read or write the shared scheme corpus and topic list, so nothing is lead-scoped.
- Every `/api/tutor/*` and `/api/tutoring/*` route is the tutoring marketplace (sub-project B), which belongs to the account holder.
- `/api/teacher/team/*` and every billing route are lead-only by rule.
- `view_usage` gates no existing route. Phase 04's usage meter adopts it.

---

### Task 1: Pure core — metered actions and team permissions

**Files:**
- Create: `lemely/core/metered_actions.py`
- Create: `lemely/core/team_permissions.py`
- Test: `tests/test_metered_actions.py`, `tests/test_team_permissions.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `MeteredAction(StrEnum)` with `.has_subject -> bool` and `.seat_eligible -> bool`
  - `SEAT_ACTIONS: frozenset[MeteredAction]`, the actions a seat's `scope_actions` may name (index R12)
  - `AssistantRole(StrEnum)` (core mirror: `CO_TEACHER`, `MARKER`, `VIEWER`)
  - `TeamPermission(StrEnum)`
  - `PRESET_PERMISSIONS: Mapping[AssistantRole, frozenset[TeamPermission]]`
  - `UnknownPermissionError(ValueError)`
  - `validate_overrides(overrides: Mapping[str, object]) -> dict[str, bool]`
  - `effective_permissions(role: AssistantRole | str, overrides: Mapping[str, bool]) -> frozenset[TeamPermission]`

- [ ] **Step 1: Write the failing tests**

`tests/test_metered_actions.py`:

```python
"""MeteredAction base values and the seat-eligible set (index R12, spec §2.2, §5.6)."""

from __future__ import annotations

from lemely.core.metered_actions import SEAT_ACTIONS, MeteredAction

BASE_VALUES = {
    "mark_paper",
    "regrade",
    "generate_quiz",
    "preview_quiz",
    "self_review",
    "study_plan",
}


def test_the_six_base_values_exist() -> None:
    assert BASE_VALUES <= {action.value for action in MeteredAction}


def test_every_base_action_has_a_subject() -> None:
    for value in BASE_VALUES:
        assert MeteredAction(value).has_subject is True


def test_only_student_actions_are_seat_eligible() -> None:
    assert {a for a in MeteredAction if a.seat_eligible} == {
        MeteredAction.MARK_PAPER,
        MeteredAction.SELF_REVIEW,
        MeteredAction.STUDY_PLAN,
    }


def test_seat_actions_is_the_seat_eligible_set() -> None:
    assert frozenset(a for a in MeteredAction if a.seat_eligible) == SEAT_ACTIONS
    assert MeteredAction.STUDY_PLAN in SEAT_ACTIONS
    assert MeteredAction.REGRADE not in SEAT_ACTIONS
```

`tests/test_team_permissions.py`:

```python
"""Assistant role presets and per-permission toggles (spec §2.3, §7)."""

from __future__ import annotations

import pytest

from lemely.core.team_permissions import (
    PRESET_PERMISSIONS,
    AssistantRole,
    TeamPermission,
    UnknownPermissionError,
    effective_permissions,
    validate_overrides,
)


def test_permission_values_match_the_index_contract() -> None:
    assert {p.value for p in TeamPermission} == {
        "mark",
        "regrade",
        "generate_quiz",
        "manage_classes",
        "view_results",
        "manage_students",
        "view_usage",
    }


def test_billing_and_seats_are_never_permissions() -> None:
    for permission in TeamPermission:
        for forbidden in ("billing", "seat", "plan", "assistant", "cap"):
            assert forbidden not in permission.value


def test_co_teacher_has_everything() -> None:
    assert PRESET_PERMISSIONS[AssistantRole.CO_TEACHER] == frozenset(TeamPermission)


def test_marker_marks_regrades_and_reads() -> None:
    assert PRESET_PERMISSIONS[AssistantRole.MARKER] == frozenset(
        {TeamPermission.MARK, TeamPermission.REGRADE, TeamPermission.VIEW_RESULTS}
    )


def test_viewer_is_read_only() -> None:
    assert PRESET_PERMISSIONS[AssistantRole.VIEWER] == frozenset(
        {TeamPermission.VIEW_RESULTS, TeamPermission.VIEW_USAGE}
    )


def test_every_role_has_a_preset() -> None:
    assert set(PRESET_PERMISSIONS) == set(AssistantRole)


def test_override_grants_a_permission() -> None:
    granted = effective_permissions(AssistantRole.VIEWER, {"manage_classes": True})
    assert TeamPermission.MANAGE_CLASSES in granted
    assert TeamPermission.VIEW_RESULTS in granted


def test_override_revokes_a_permission() -> None:
    granted = effective_permissions(AssistantRole.CO_TEACHER, {"mark": False})
    assert TeamPermission.MARK not in granted
    assert TeamPermission.REGRADE in granted


def test_role_may_be_a_plain_string() -> None:
    assert effective_permissions("marker", {}) == PRESET_PERMISSIONS[AssistantRole.MARKER]


@pytest.mark.parametrize("key", ["billing", "manage_seats", "manage_assistants", "plan"])
def test_unknown_override_keys_are_refused(key: str) -> None:
    with pytest.raises(UnknownPermissionError):
        validate_overrides({key: True})
    with pytest.raises(UnknownPermissionError):
        effective_permissions(AssistantRole.CO_TEACHER, {key: True})


def test_non_boolean_override_is_refused() -> None:
    with pytest.raises(UnknownPermissionError):
        validate_overrides({"mark": "yes"})


def test_validate_overrides_returns_a_sorted_clean_copy() -> None:
    assert validate_overrides({"regrade": False, "mark": True}) == {"mark": True, "regrade": False}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_metered_actions.py tests/test_team_permissions.py -v`
Expected: collection errors with `ModuleNotFoundError: No module named 'lemely.core.metered_actions'` and `... 'lemely.core.team_permissions'`.

- [ ] **Step 3: Write `lemely/core/metered_actions.py`**

```python
"""The metered LLM-backed actions (spec §2.4, §5.6; index §Phase 04 and R12).

Phase 03 creates this module with the six base actions so seat scopes
(``teacher_members.scope_actions``) can be validated against :data:`SEAT_ACTIONS`.
Phase 04 replaces the body: it adds ``mark_quiz`` and ``generate_flashcards``, moves
both flags into its ``ACTION_SPECS`` table, and keeps ``MeteredAction`` and
``SEAT_ACTIONS``. Pure: no DB, no IO.

``has_subject``: the action works on a record that carries a subject (a paper, a quiz,
a plan), so per-subject seat routing can apply. ``seat_eligible``: a student runs the
action, so a teacher may put it in a seat's scope. Teacher-side actions (regrade, quiz
generation and preview) are never seat-paid.
"""

from __future__ import annotations

from enum import StrEnum


class MeteredAction(StrEnum):
    MARK_PAPER = "mark_paper"
    REGRADE = "regrade"
    GENERATE_QUIZ = "generate_quiz"
    PREVIEW_QUIZ = "preview_quiz"
    SELF_REVIEW = "self_review"
    STUDY_PLAN = "study_plan"

    @property
    def has_subject(self) -> bool:
        """Return whether the action's record carries a subject."""
        return self.value not in _SUBJECTLESS

    @property
    def seat_eligible(self) -> bool:
        """Return whether a teacher may put the action in a seat's scope."""
        return self.value in _SEAT_ELIGIBLE


_SUBJECTLESS: frozenset[str] = frozenset()
"""Values of actions with no subject. Empty: every base action has one."""

_SEAT_ELIGIBLE: frozenset[str] = frozenset({"mark_paper", "self_review", "study_plan"})
"""Values of the actions a student runs (the ones a seat may pay for)."""

SEAT_ACTIONS: frozenset[MeteredAction] = frozenset(
    action for action in MeteredAction if action.seat_eligible
)
"""The actions a teacher may put in a seat's ``scope_actions`` (index R12)."""


__all__ = ["SEAT_ACTIONS", "MeteredAction"]
```

- [ ] **Step 4: Write `lemely/core/team_permissions.py`**

```python
"""Assistant roles and team permissions (spec §2.3, §7). Pure: no DB, no IO.

An assistant acts on the lead teacher's resources only when the effective permission
set of their ``teacher_members`` row grants the permission a route asks for
(``lemely.web.deps.require_team_permission``). The set is the role preset with the
row's per-permission toggles applied on top.

Billing, plan changes, seats, caps and assistants are never permissions. No value of
:class:`TeamPermission` names them, so no toggle can grant them. Those routes stay
behind ``require_role(Role.teacher)`` and act only on the caller's own team.

:class:`AssistantRole` mirrors ``lemely.db.models.team.AssistantRole`` member for
member. ``lemely.db.models`` never imports ``lemely.core``, and this module stays
pure, so the enum is declared twice; ``tests/test_team_schema.py`` pins that the two
agree. Both are ``StrEnum``, so either converts to the other by value.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


class AssistantRole(StrEnum):
    CO_TEACHER = "co_teacher"
    MARKER = "marker"
    VIEWER = "viewer"


class TeamPermission(StrEnum):
    MARK = "mark"
    REGRADE = "regrade"
    GENERATE_QUIZ = "generate_quiz"
    MANAGE_CLASSES = "manage_classes"
    VIEW_RESULTS = "view_results"
    MANAGE_STUDENTS = "manage_students"
    VIEW_USAGE = "view_usage"


PRESET_PERMISSIONS: Mapping[AssistantRole, frozenset[TeamPermission]] = MappingProxyType(
    {
        AssistantRole.CO_TEACHER: frozenset(TeamPermission),
        AssistantRole.MARKER: frozenset(
            {TeamPermission.MARK, TeamPermission.REGRADE, TeamPermission.VIEW_RESULTS}
        ),
        AssistantRole.VIEWER: frozenset(
            {TeamPermission.VIEW_RESULTS, TeamPermission.VIEW_USAGE}
        ),
    }
)
"""Spec §2.3. A marker also reads (``view_results``) so it can see what it marks."""

_PERMISSION_VALUES: frozenset[str] = frozenset(p.value for p in TeamPermission)


class UnknownPermissionError(ValueError):
    """An override names something that is not a :class:`TeamPermission`, or is not a bool."""


def validate_overrides(overrides: Mapping[str, object]) -> dict[str, bool]:
    """Return a sorted, checked copy of ``overrides``.

    Raises:
        UnknownPermissionError: A key is not a :class:`TeamPermission` value, or a
            value is not a bool.
    """
    clean: dict[str, bool] = {}
    for key, value in overrides.items():
        if key not in _PERMISSION_VALUES:
            raise UnknownPermissionError(f"Unknown team permission: {key!r}")
        if not isinstance(value, bool):
            raise UnknownPermissionError(f"Team permission {key!r} must be true or false")
        clean[key] = value
    return dict(sorted(clean.items()))


def effective_permissions(
    role: AssistantRole | str, overrides: Mapping[str, bool]
) -> frozenset[TeamPermission]:
    """Return the role preset with ``overrides`` applied (``True`` grants, ``False`` revokes).

    Raises:
        ValueError: ``role`` is not an assistant role.
        UnknownPermissionError: See :func:`validate_overrides`.
    """
    granted = set(PRESET_PERMISSIONS[AssistantRole(role)])
    for key, allowed in validate_overrides(overrides).items():
        permission = TeamPermission(key)
        if allowed:
            granted.add(permission)
        else:
            granted.discard(permission)
    return frozenset(granted)


__all__ = [
    "PRESET_PERMISSIONS",
    "AssistantRole",
    "TeamPermission",
    "UnknownPermissionError",
    "effective_permissions",
    "validate_overrides",
]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_metered_actions.py tests/test_team_permissions.py tests/architecture/ -v`
Expected: all PASS (architecture tests prove `lemely.core` stays pure under the import-linter contracts).

- [ ] **Step 6: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/core/metered_actions.py lemely/core/team_permissions.py tests/test_metered_actions.py tests/test_team_permissions.py
git commit -S -m "feat(team): metered action names and assistant team permissions" -- lemely/core/metered_actions.py lemely/core/team_permissions.py tests/test_metered_actions.py tests/test_team_permissions.py
```

---

### Task 2: Schema — `teacher_members`, invite extension, usage FK, migration 0054

**Files:**
- Create: `lemely/db/models/team.py`
- Modify: `lemely/db/models/enums.py` (`InviteRole`)
- Modify: `lemely/db/models/invites.py`
- Modify: `lemely/db/models/usage.py` (`UsageGrant.teacher_member_id`)
- Modify: `lemely/db/models/__init__.py`
- Create: `lemely/db/migrations/versions/0054_teacher_team.py`
- Create: `tests/team_db.py`
- Test: `tests/test_team_schema.py`, `tests/test_migration_teacher_team.py`

**Interfaces:**
- Consumes: `lemely.core.team_permissions.AssistantRole` (only in the mirror test), and Phase 01 `UsageGrant`.
- Produces (`lemely/db/models/team.py`):
  - `TeacherMemberKind` (`student_seat`, `assistant`)
  - `TeacherMemberStatus` (`active`, `leaving`, `removed`)
  - `AssistantRole` (`co_teacher`, `marker`, `viewer`)
  - `CapPeriod` (`month`, `total`), all `enum.StrEnum`
  - `TeacherMember` columns:
    - `id`, `teacher_user_id`, `member_user_id`, `kind`
    - `scope_subjects: list[str] | None`, `scope_actions: list[str] | None`
    - `role_preset: AssistantRole | None`, `permissions: dict[str, bool] | None`
    - `cap_units: int | None`, `cap_period: CapPeriod`
    - `status: TeacherMemberStatus`, `leaves_at: datetime | None`, `created_at`, `updated_at`
- Produces (`Invite`): `team_teacher_id: uuid.UUID | None`, `assistant_role: AssistantRole | None`.
- Produces: `InviteRole.assistant`.
- Produces (`tests/team_db.py`):
  - `team_database()`, `emptied_after(factory)`, `NOW`
  - `add_user(factory, role=Role.student, *, display_name=None) -> UUID`
  - `add_subject(factory, code, name="Mathematics") -> str`
  - `add_class(factory, *, teacher_id, subject_code=None, school_id=None) -> tuple[UUID, str]` (class id, join code)
  - `enrol(factory, class_id, student_id) -> None`
  - `add_teacher_plan(factory, teacher_id, *, included_seats, extra_seats=0, status=SubscriptionStatus.active, audience="teacher") -> UUID`
  - `add_seat(factory, *, teacher_id, student_id, subjects=(), actions=("mark_paper",), status=TeacherMemberStatus.active, leaves_at=None, cap_units=None) -> UUID`
  - `add_assistant(factory, *, teacher_id, assistant_id, role=AssistantRole.co_teacher, permissions=None, status=TeacherMemberStatus.active) -> UUID`

- [ ] **Step 1: Confirm the consumed Phase 01/02 names**

Run:
```bash
grep -n "teacher_member_id" lemely/db/models/usage.py
grep -n "audience\|included_seats" lemely/db/models/billing.py
grep -n "extra_seats\|payer_user_id" lemely/db/models/billing.py
grep -n "past_due" lemely/db/models/enums.py
grep -n "^revision" lemely/db/migrations/versions/0053_*.py
```
Expected:
- `UsageGrant` has a `teacher_member_id` mapped column.
- `PlanTier` has `audience` and `included_seats`.
- `Subscription` has `extra_seats` and `payer_user_id`.
- `SubscriptionStatus` has `past_due`.
- The revision is `revision: str = "0053_billing_payments"`.

If a name differs, use Phase 02's name in this task and Task 3 (see Prerequisites).

- [ ] **Step 2: Write the DB helper `tests/team_db.py`**

```python
"""Database helpers shared by the teacher-team test modules (Phase 03).

Not a test module (no ``test_`` prefix). Each test module defines its own fixtures
from these helpers, as ``tests/tutoring_db.py`` explains: a fixture imported by name
would be redefined by the parameter that uses it.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models import (
    ClassEnrollment,
    PlanTier,
    SchoolClass,
    Subject,
    Subscription,
    User,
    import_all_models,
)
from lemely.db.models.billing import PlanAudience
from lemely.db.models.enums import PlanInterval, Role, SubscriptionStatus
from lemely.db.models.team import (
    AssistantRole,
    CapPeriod,
    TeacherMember,
    TeacherMemberKind,
    TeacherMemberStatus,
)
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

import_all_models()

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


@contextmanager
def team_database() -> Iterator[sessionmaker[Session]]:
    """A fresh ``create_all`` database for one test module."""
    base = make_url(DatabaseSettings().url)
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect():
            pass
    except OperationalError:
        admin.dispose()
        pytest.skip("local Postgres not reachable")
    name = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(base.set(database=name))
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def emptied_after(factory: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    """Yield ``factory``, then empty every table reachable from users, subjects and plans."""
    yield factory
    with factory.begin() as session:
        session.execute(sa.text("TRUNCATE users, subjects, plan_tiers CASCADE"))


def add_user(
    factory: sessionmaker[Session],
    role: Role = Role.student,
    *,
    display_name: str | None = None,
) -> uuid.UUID:
    uid = uuid.uuid4()
    with factory.begin() as session:
        session.add(
            User(id=uid, email=f"{uid}@example.com", role=role, display_name=display_name)
        )
    return uid


def add_subject(factory: sessionmaker[Session], code: str, name: str = "Mathematics") -> str:
    with factory.begin() as session:
        session.add(Subject(code=code, name=name))
    return code


def add_class(
    factory: sessionmaker[Session],
    *,
    teacher_id: uuid.UUID,
    subject_code: str | None = None,
    school_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, str]:
    class_id = uuid.uuid4()
    join_code = f"J{uuid.uuid4().hex[:6].upper()}"
    with factory.begin() as session:
        session.add(
            SchoolClass(
                id=class_id,
                teacher_id=teacher_id,
                school_id=school_id,
                name="Team Test Class",
                subject_code=subject_code,
                join_code=join_code,
            )
        )
    return class_id, join_code


def enrol(factory: sessionmaker[Session], class_id: uuid.UUID, student_id: uuid.UUID) -> None:
    with factory.begin() as session:
        session.add(ClassEnrollment(class_id=class_id, student_id=student_id))


def add_teacher_plan(
    factory: sessionmaker[Session],
    teacher_id: uuid.UUID,
    *,
    included_seats: int,
    extra_seats: int = 0,
    status: SubscriptionStatus = SubscriptionStatus.active,
    audience: PlanAudience = PlanAudience.teacher,
) -> uuid.UUID:
    """Seed a plan tier and a subscription for ``teacher_id``; return the subscription id.

    Column names are Phase 02's (``audience``, ``allowance_units``, ``included_seats``,
    ``seat_allowance_units``, ``extra_seat_price_minor``, ``is_active``,
    ``payer_user_id``, ``extra_seats``). If Phase 02 added another NOT NULL column
    without a server default, set it here.
    """
    tier_id, sub_id = uuid.uuid4(), uuid.uuid4()
    with factory.begin() as session:
        session.add(
            PlanTier(
                id=tier_id,
                code=f"teacher_{tier_id.hex[:8]}",
                name="Teacher",
                price_minor=0,
                interval=PlanInterval.monthly,
                audience=audience,
                allowance_units=1000,
                included_seats=included_seats,
                seat_allowance_units=100,
                extra_seat_price_minor=0,
                is_active=True,
            )
        )
        session.flush()
        session.add(
            Subscription(
                id=sub_id,
                user_id=teacher_id,
                payer_user_id=teacher_id,
                plan_tier_id=tier_id,
                status=status,
                extra_seats=extra_seats,
            )
        )
    return sub_id


def add_seat(
    factory: sessionmaker[Session],
    *,
    teacher_id: uuid.UUID,
    student_id: uuid.UUID,
    subjects: Sequence[str] = (),
    actions: Sequence[str] = ("mark_paper",),
    status: TeacherMemberStatus = TeacherMemberStatus.active,
    leaves_at: datetime | None = None,
    cap_units: int | None = None,
) -> uuid.UUID:
    member_id = uuid.uuid4()
    with factory.begin() as session:
        session.add(
            TeacherMember(
                id=member_id,
                teacher_user_id=teacher_id,
                member_user_id=student_id,
                kind=TeacherMemberKind.student_seat,
                scope_subjects=list(subjects),
                scope_actions=list(actions),
                cap_units=cap_units,
                cap_period=CapPeriod.month,
                status=status,
                leaves_at=leaves_at,
            )
        )
    return member_id


def add_assistant(
    factory: sessionmaker[Session],
    *,
    teacher_id: uuid.UUID,
    assistant_id: uuid.UUID,
    role: AssistantRole = AssistantRole.co_teacher,
    permissions: Mapping[str, bool] | None = None,
    status: TeacherMemberStatus = TeacherMemberStatus.active,
) -> uuid.UUID:
    member_id = uuid.uuid4()
    with factory.begin() as session:
        session.add(
            TeacherMember(
                id=member_id,
                teacher_user_id=teacher_id,
                member_user_id=assistant_id,
                kind=TeacherMemberKind.assistant,
                role_preset=role,
                permissions=dict(permissions or {}),
                cap_period=CapPeriod.month,
                status=status,
            )
        )
    return member_id
```

- [ ] **Step 3: Write the failing schema tests `tests/test_team_schema.py`**

```python
"""teacher_members constraints and the invites extension, on a create_all database (§4.4)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import IntegrityError

from lemely.core.team_permissions import AssistantRole as CoreAssistantRole
from lemely.db.base import Base
from lemely.db.models import Invite
from lemely.db.models.enums import InviteRole, Role
from lemely.db.models.team import (
    AssistantRole,
    CapPeriod,
    TeacherMember,
    TeacherMemberKind,
    TeacherMemberStatus,
)
from tests.team_db import NOW, add_assistant, add_seat, add_user, emptied_after, team_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def team_db() -> Iterator[sessionmaker[Session]]:
    with team_database() as factory:
        yield factory


@pytest.fixture
def sm(team_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(team_db)


def _insert(sm: sessionmaker[Session], row: object) -> None:
    with sm.begin() as session:
        session.add(row)


def test_core_and_model_assistant_roles_agree() -> None:
    assert {m.value for m in AssistantRole} == {m.value for m in CoreAssistantRole}


def test_invite_role_has_assistant() -> None:
    assert InviteRole("assistant") is InviteRole.assistant


def test_usage_grant_teacher_member_fk_targets_teacher_members() -> None:
    column = Base.metadata.tables["usage_grants"].c.teacher_member_id
    assert {fk.target_fullname for fk in column.foreign_keys} == {"teacher_members.id"}


def test_a_valid_seat_and_assistant_insert(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    student = add_user(sm, Role.student)
    helper = add_user(sm, Role.teacher)
    add_seat(sm, teacher_id=teacher, student_id=student, subjects=["0580"])
    add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    with sm() as session:
        assert session.query(TeacherMember).count() == 2


def test_seat_without_scope_is_refused(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    row = TeacherMember(
        teacher_user_id=teacher,
        member_user_id=student,
        kind=TeacherMemberKind.student_seat,
        cap_period=CapPeriod.month,
    )
    with pytest.raises(IntegrityError, match="ck_teacher_members_seat_fields"):
        _insert(sm, row)


def test_assistant_with_scope_is_refused(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    row = TeacherMember(
        teacher_user_id=teacher,
        member_user_id=helper,
        kind=TeacherMemberKind.assistant,
        role_preset=AssistantRole.viewer,
        permissions={},
        scope_subjects=["0580"],
        cap_period=CapPeriod.month,
    )
    with pytest.raises(IntegrityError, match="ck_teacher_members_assistant_fields"):
        _insert(sm, row)


def test_assistant_without_role_is_refused(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    row = TeacherMember(
        teacher_user_id=teacher,
        member_user_id=helper,
        kind=TeacherMemberKind.assistant,
        permissions={},
        cap_period=CapPeriod.month,
    )
    with pytest.raises(IntegrityError, match="ck_teacher_members_assistant_fields"):
        _insert(sm, row)


def test_self_membership_is_refused(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    with pytest.raises(IntegrityError, match="ck_teacher_members_not_self"):
        add_assistant(sm, teacher_id=teacher, assistant_id=teacher)


def test_one_row_per_teacher_and_member(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_seat(sm, teacher_id=teacher, student_id=student)
    with pytest.raises(IntegrityError, match="uq_teacher_members_teacher_member"):
        add_seat(sm, teacher_id=teacher, student_id=student)


def test_leaving_needs_a_date_and_active_has_none(sm: sessionmaker[Session]) -> None:
    teacher, s1, s2 = add_user(sm, Role.teacher), add_user(sm), add_user(sm)
    with pytest.raises(IntegrityError, match="ck_teacher_members_leaving_has_date"):
        add_seat(sm, teacher_id=teacher, student_id=s1, status=TeacherMemberStatus.leaving)
    with pytest.raises(IntegrityError, match="ck_teacher_members_active_has_no_date"):
        add_seat(sm, teacher_id=teacher, student_id=s2, leaves_at=NOW)


def test_negative_cap_is_refused(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    with pytest.raises(IntegrityError, match="ck_teacher_members_cap_nonnegative"):
        add_seat(sm, teacher_id=teacher, student_id=student, cap_units=-1)


def test_assistant_invite_targets_only_a_team(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    _insert(
        sm,
        Invite(
            code=f"A{uuid.uuid4().hex[:9].upper()}",
            role=InviteRole.assistant,
            created_by=teacher,
            team_teacher_id=teacher,
            assistant_role=AssistantRole.marker,
            expires_at=NOW,
        ),
    )


def test_assistant_invite_without_team_is_refused(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    row = Invite(
        code=f"A{uuid.uuid4().hex[:9].upper()}",
        role=InviteRole.assistant,
        created_by=teacher,
        child_id=teacher,
        assistant_role=AssistantRole.marker,
    )
    with pytest.raises(IntegrityError, match="ck_invites_assistant_shape"):
        _insert(sm, row)


def test_non_assistant_invite_with_team_is_refused(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    row = Invite(
        code=f"S{uuid.uuid4().hex[:9].upper()}",
        role=InviteRole.student,
        created_by=teacher,
        team_teacher_id=teacher,
    )
    with pytest.raises(IntegrityError, match="ck_invites_assistant_shape"):
        _insert(sm, row)
```

- [ ] **Step 4: Run the schema tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_team_schema.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'lemely.db.models.team'`.

- [ ] **Step 5: Write `lemely/db/models/team.py`**

```python
"""ORM model for a teacher's team: leased student seats and assistants (spec §4.4).

One row per person attached to a teacher, unique on ``(teacher_user_id,
member_user_id)``. ``kind`` decides which columns mean anything, and two CHECK
constraints make that a database fact:

* ``student_seat``: ``scope_subjects`` (``subjects.code`` values) and
  ``scope_actions`` (``MeteredAction`` values) are set; ``role_preset`` and
  ``permissions`` are null.
* ``assistant``: ``role_preset`` and ``permissions`` (JSONB toggles over the preset)
  are set; both scope columns are null.

``cap_units`` caps the teacher's credits a seat may overflow into (null means no
overflow), or the teacher's balance an assistant may draw (null means no limit), per
``cap_period``. A removed seat keeps its row. ``status`` moves ``active`` → ``leaving``
(``leaves_at`` = end of the month removal was requested) → ``removed``, so a rejoin
reuses the row and the seat count (active plus leaving seats ≤ the plan's seats) is a
plain COUNT under the subscription row lock (``lemely/db/teacher_team_repo.py``).

The four enums mirror nothing in ``lemely.core`` except :class:`AssistantRole`, which
``lemely.core.team_permissions.AssistantRole`` mirrors; ``tests/test_team_schema.py``
pins the pair. ``lemely.db.models`` never imports ``lemely.core``.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import TimestampMixin


class TeacherMemberKind(enum.StrEnum):
    student_seat = "student_seat"
    assistant = "assistant"


class TeacherMemberStatus(enum.StrEnum):
    active = "active"
    leaving = "leaving"
    removed = "removed"


class AssistantRole(enum.StrEnum):
    co_teacher = "co_teacher"
    marker = "marker"
    viewer = "viewer"


class CapPeriod(enum.StrEnum):
    month = "month"
    total = "total"


class TeacherMember(TimestampMixin, Base):
    __tablename__ = "teacher_members"
    __table_args__ = (
        sa.UniqueConstraint(
            "teacher_user_id", "member_user_id", name="uq_teacher_members_teacher_member"
        ),
        sa.CheckConstraint("teacher_user_id <> member_user_id", name="not_self"),
        sa.CheckConstraint(
            "kind <> 'student_seat' OR (scope_subjects IS NOT NULL AND scope_actions IS NOT NULL"
            " AND role_preset IS NULL AND permissions IS NULL)",
            name="seat_fields",
        ),
        sa.CheckConstraint(
            "kind <> 'assistant' OR (role_preset IS NOT NULL AND permissions IS NOT NULL"
            " AND scope_subjects IS NULL AND scope_actions IS NULL)",
            name="assistant_fields",
        ),
        sa.CheckConstraint("cap_units IS NULL OR cap_units >= 0", name="cap_nonnegative"),
        sa.CheckConstraint(
            "status <> 'leaving' OR leaves_at IS NOT NULL", name="leaving_has_date"
        ),
        sa.CheckConstraint("status <> 'active' OR leaves_at IS NULL", name="active_has_no_date"),
        sa.Index("ix_teacher_members_member_user_id", "member_user_id"),
        sa.Index("ix_teacher_members_teacher_kind_status", "teacher_user_id", "kind", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    teacher_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    member_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[TeacherMemberKind] = mapped_column(
        sa.Enum(TeacherMemberKind, name="teachermemberkind"), nullable=False
    )
    scope_subjects: Mapped[list[str] | None] = mapped_column(ARRAY(sa.String), nullable=True)
    scope_actions: Mapped[list[str] | None] = mapped_column(ARRAY(sa.String), nullable=True)
    role_preset: Mapped[AssistantRole | None] = mapped_column(
        sa.Enum(AssistantRole, name="assistantrole"), nullable=True
    )
    permissions: Mapped[dict[str, bool] | None] = mapped_column(JSONB, nullable=True)
    cap_units: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    cap_period: Mapped[CapPeriod] = mapped_column(
        sa.Enum(CapPeriod, name="capperiod"),
        nullable=False,
        server_default=sa.text("'month'::capperiod"),
    )
    status: Mapped[TeacherMemberStatus] = mapped_column(
        sa.Enum(TeacherMemberStatus, name="teachermemberstatus"),
        nullable=False,
        server_default=sa.text("'active'::teachermemberstatus"),
    )
    leaves_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


__all__ = ["AssistantRole", "CapPeriod", "TeacherMember", "TeacherMemberKind", "TeacherMemberStatus"]
```

- [ ] **Step 6: Extend `InviteRole` in `lemely/db/models/enums.py`**

Replace the member list of `class InviteRole(enum.StrEnum)` (currently `student`, `teacher`, `parent`) with the block below. Add the paragraph to the end of its docstring:

```python
    student = "student"
    teacher = "teacher"
    parent = "parent"
    assistant = "assistant"
```

Docstring paragraph to append:

```text
    ``assistant`` (paymob billing Phase 03, spec §4.4) is a teacher's single-use,
    expiring invite for another teacher account to become their assistant. Its target
    is ``invites.team_teacher_id``; it is redeemed only through
    ``POST /api/teacher/team/assistants/redeem``.
```

- [ ] **Step 7: Extend `lemely/db/models/invites.py`**

Add the import below the existing `from lemely.db.models.enums import InviteRole, TimestampMixin`:

```python
from lemely.db.models.team import AssistantRole
```

Replace the `ck_invites_target` `CheckConstraint` in `__table_args__` with these two constraints and one index. Keep the other entries:

```python
        sa.CheckConstraint(
            "school_id IS NOT NULL OR class_id IS NOT NULL OR child_id IS NOT NULL"
            " OR team_teacher_id IS NOT NULL",
            name="ck_invites_target",
        ),
        sa.CheckConstraint(
            "(role::text = 'assistant') = (team_teacher_id IS NOT NULL)"
            " AND (role::text = 'assistant') = (assistant_role IS NOT NULL)",
            name="assistant_shape",
        ),
        sa.Index("ix_invites_team_teacher_id", "team_teacher_id"),
```

Add these two columns after `seat_id`:

```python
    team_teacher_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    """The lead teacher an ``assistant`` invite attaches its redeemer to (spec §4.4)."""
    assistant_role: Mapped[AssistantRole | None] = mapped_column(
        sa.Enum(AssistantRole, name="assistantrole"),
        nullable=True,
    )
    """The role preset an ``assistant`` invite grants; set exactly when ``team_teacher_id`` is."""
```

Append this sentence to the class docstring's first paragraph: "A fourth target, ``team_teacher_id``, carries a teacher's assistant invite (paymob billing Phase 03); ``ck_invites_assistant_shape`` ties it to ``role = 'assistant'``."

- [ ] **Step 8: Add the FK on `UsageGrant.teacher_member_id` in `lemely/db/models/usage.py`**

Replace the existing `teacher_member_id` mapped column on `UsageGrant` (a plain nullable UUID since Phase 01) with:

```python
    teacher_member_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("teacher_members.id"),
        nullable=True,
    )
    """The seat a ``seat_allowance`` grant belongs to (FK added by 0054_teacher_team)."""
```

No `ondelete`: `teacher_members` rows are never deleted (status `removed` instead), and a seat grant must never lose its seat link. Losing it would turn it into a plain allowance.

- [ ] **Step 9: Register the module in `lemely/db/models/__init__.py`**

- Add `team,` to the `from lemely.db.models import (...)` tuple inside `import_all_models()`, in alphabetical position (after `teacher_papers`, before `thresholds`).
- Add `from lemely.db.models.team import TeacherMember` to the re-export block.
- Add `"TeacherMember",` to `__all__` in alphabetical position.

- [ ] **Step 10: Run the schema tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_team_schema.py -v`
Expected: all PASS.

- [ ] **Step 11: Write the failing migration test `tests/test_migration_teacher_team.py`**

```python
"""Migration 0054_teacher_team: teacher_members, assistant invites, usage_grants FK (§4.4)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from lemely.db.base import Base
from lemely.db.models import import_all_models
from tests.test_migration_tutoring_enums import (
    current_revision,
    object_names,
    public_tables,
    upgrade_head,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0054_teacher_team"
DOWN_REVISION = "0053_billing_payments"
TABLE = "teacher_members"
INVITE_OBJECTS = {
    "ck_invites_target",
    "ck_invites_assistant_shape",
    "fk_invites_team_teacher_id_users",
    "ix_invites_team_teacher_id",
}
GRANT_FK = "fk_usage_grants_teacher_member_id_teacher_members"


def _orm_names() -> set[str]:
    table = Base.metadata.tables[TABLE]
    names = {str(constraint.name) for constraint in table.constraints}
    return names | {str(index.name) for index in table.indexes}


def _enum_values(session: Session, name: str) -> set[str]:
    rows = session.execute(
        sa.text(
            "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
            "WHERE t.typname = :name"
        ),
        {"name": name},
    ).scalars()
    return set(rows)


def test_orm_declares_the_named_objects() -> None:
    assert _orm_names() == {
        "pk_teacher_members",
        "fk_teacher_members_teacher_user_id_users",
        "fk_teacher_members_member_user_id_users",
        "uq_teacher_members_teacher_member",
        "ck_teacher_members_not_self",
        "ck_teacher_members_seat_fields",
        "ck_teacher_members_assistant_fields",
        "ck_teacher_members_cap_nonnegative",
        "ck_teacher_members_leaving_has_date",
        "ck_teacher_members_active_has_no_date",
        "ix_teacher_members_member_user_id",
        "ix_teacher_members_teacher_kind_status",
    }


def test_revision_is_in_the_history_after_0053() -> None:
    """In the history and chained from 0053; never asserted to be head (index R10)."""
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    assert REVISION in {rev.revision for rev in script_dir.walk_revisions()}
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32


def test_objects_present_by_name(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        assert object_names(session, [TABLE]) == _orm_names()
        assert INVITE_OBJECTS <= object_names(session, ["invites"])
        assert GRANT_FK in object_names(session, ["usage_grants"])
        assert "assistant" in _enum_values(session, "inviterole")
        assert _enum_values(session, "assistantrole") == {"co_teacher", "marker", "viewer"}


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    teacher, helper, child = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with sm.begin() as session:
        for uid, role in ((teacher, "teacher"), (helper, "teacher"), (child, "student")):
            session.execute(
                sa.text("INSERT INTO users (id, email, role) VALUES (:u, :e, :r)"),
                {"u": uid, "e": f"{uid}@example.com", "r": role},
            )
        session.execute(
            sa.text(
                "INSERT INTO teacher_members (teacher_user_id, member_user_id, kind, "
                "role_preset, permissions) VALUES (:t, :h, 'assistant', 'marker', '{}')"
            ),
            {"t": teacher, "h": helper},
        )
        session.execute(
            sa.text(
                "INSERT INTO invites (code, role, created_by, team_teacher_id, assistant_role, "
                "expires_at) VALUES ('ASSIST0001', 'assistant', :t, :t, 'viewer', now())"
            ),
            {"t": teacher},
        )
        session.execute(
            sa.text(
                "INSERT INTO invites (code, role, created_by, child_id) "
                "VALUES ('PARENT0001', 'parent', :c, :c)"
            ),
            {"c": child},
        )

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        assert TABLE not in public_tables(session)
        codes = set(session.execute(sa.text("SELECT code FROM invites")).scalars())
        assert codes == {"PARENT0001"}  # assistant invites cannot satisfy the old target check
        assert not (INVITE_OBJECTS - {"ck_invites_target"}) & object_names(session, ["invites"])
        assert GRANT_FK not in object_names(session, ["usage_grants"])

    upgrade_head()

    with sm() as session:
        assert object_names(session, [TABLE]) == _orm_names()
        assert INVITE_OBJECTS <= object_names(session, ["invites"])
        assert GRANT_FK in object_names(session, ["usage_grants"])
```

- [ ] **Step 12: Run the migration test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_migration_teacher_team.py -v`
Expected:
- `test_orm_declares_the_named_objects` PASSES.
- `test_revision_is_in_the_history_after_0053` FAILS (`0054_teacher_team` not in the history).
- The two DB tests FAIL (`teacher_members` missing, or skip if local Postgres is down; it must be up for this task).

- [ ] **Step 13: Write `lemely/db/migrations/versions/0054_teacher_team.py`**

```python
"""teacher team: teacher_members, assistant invites, usage_grants seat FK

Revision ID: 0054_teacher_team
Revises: 0053_billing_payments
Create Date: 2026-11-05 00:00:00.000000

Paymob billing Phase 03 (spec §4.4).

* ``teacher_members``: one row per seat or assistant attached to a teacher, with
  four new enums (``teachermemberkind``, ``teachermemberstatus``, ``assistantrole``,
  ``capperiod``) and CHECKs that tie the columns to ``kind`` and ``status``.
* ``invites``: ``inviterole`` gains ``assistant``; new ``team_teacher_id`` (FK users,
  CASCADE) and ``assistant_role`` columns; ``ck_invites_target`` is widened to accept
  ``team_teacher_id``; ``ck_invites_assistant_shape`` ties both columns to
  ``role = 'assistant'`` (an assistant invite has both, no other invite has either).
  It compares ``role::text`` because the enum value added in this transaction cannot
  be used as an enum literal before commit.
* ``usage_grants.teacher_member_id`` gets its FK to ``teacher_members``.

``downgrade`` deletes assistant invites first (they would violate the narrower
target check), then reverses everything else. The ``inviterole`` value stays, as in
0034 and 0019: Postgres cannot drop an enum value.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0054_teacher_team"
down_revision: str | Sequence[str] | None = "0053_billing_payments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUMS = (
    ("teachermemberkind", ("student_seat", "assistant")),
    ("teachermemberstatus", ("active", "leaving", "removed")),
    ("assistantrole", ("co_teacher", "marker", "viewer")),
    ("capperiod", ("month", "total")),
)


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE inviterole ADD VALUE IF NOT EXISTS 'assistant'")
    bind = op.get_bind()
    for name, values in _ENUMS:
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    op.create_table(
        "teacher_members",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("teacher_user_id", sa.UUID(), nullable=False),
        sa.Column("member_user_id", sa.UUID(), nullable=False),
        sa.Column("kind", _enum("teachermemberkind"), nullable=False),
        sa.Column("scope_subjects", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("scope_actions", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("role_preset", _enum("assistantrole"), nullable=True),
        sa.Column("permissions", postgresql.JSONB(), nullable=True),
        sa.Column("cap_units", sa.BigInteger(), nullable=True),
        sa.Column(
            "cap_period",
            _enum("capperiod"),
            server_default=sa.text("'month'::capperiod"),
            nullable=False,
        ),
        sa.Column(
            "status",
            _enum("teachermemberstatus"),
            server_default=sa.text("'active'::teachermemberstatus"),
            nullable=False,
        ),
        sa.Column("leaves_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["teacher_user_id"],
            ["users.id"],
            name=op.f("fk_teacher_members_teacher_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["member_user_id"],
            ["users.id"],
            name=op.f("fk_teacher_members_member_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teacher_members")),
        sa.UniqueConstraint(
            "teacher_user_id", "member_user_id", name="uq_teacher_members_teacher_member"
        ),
        sa.CheckConstraint(
            "teacher_user_id <> member_user_id", name=op.f("ck_teacher_members_not_self")
        ),
        sa.CheckConstraint(
            "kind <> 'student_seat' OR (scope_subjects IS NOT NULL AND scope_actions IS NOT NULL"
            " AND role_preset IS NULL AND permissions IS NULL)",
            name=op.f("ck_teacher_members_seat_fields"),
        ),
        sa.CheckConstraint(
            "kind <> 'assistant' OR (role_preset IS NOT NULL AND permissions IS NOT NULL"
            " AND scope_subjects IS NULL AND scope_actions IS NULL)",
            name=op.f("ck_teacher_members_assistant_fields"),
        ),
        sa.CheckConstraint(
            "cap_units IS NULL OR cap_units >= 0", name=op.f("ck_teacher_members_cap_nonnegative")
        ),
        sa.CheckConstraint(
            "status <> 'leaving' OR leaves_at IS NOT NULL",
            name=op.f("ck_teacher_members_leaving_has_date"),
        ),
        sa.CheckConstraint(
            "status <> 'active' OR leaves_at IS NULL",
            name=op.f("ck_teacher_members_active_has_no_date"),
        ),
    )
    op.create_index("ix_teacher_members_member_user_id", "teacher_members", ["member_user_id"])
    op.create_index(
        "ix_teacher_members_teacher_kind_status",
        "teacher_members",
        ["teacher_user_id", "kind", "status"],
    )

    op.add_column(
        "invites",
        sa.Column(
            "team_teacher_id",
            sa.UUID(),
            sa.ForeignKey(
                "users.id", name=op.f("fk_invites_team_teacher_id_users"), ondelete="CASCADE"
            ),
            nullable=True,
        ),
    )
    op.add_column("invites", sa.Column("assistant_role", _enum("assistantrole"), nullable=True))
    op.create_index("ix_invites_team_teacher_id", "invites", ["team_teacher_id"])
    op.drop_constraint(op.f("ck_invites_target"), "invites", type_="check")
    op.create_check_constraint(
        op.f("ck_invites_target"),
        "invites",
        "school_id IS NOT NULL OR class_id IS NOT NULL OR child_id IS NOT NULL"
        " OR team_teacher_id IS NOT NULL",
    )
    op.create_check_constraint(
        op.f("ck_invites_assistant_shape"),
        "invites",
        "(role::text = 'assistant') = (team_teacher_id IS NOT NULL)"
        " AND (role::text = 'assistant') = (assistant_role IS NOT NULL)",
    )

    op.create_foreign_key(
        op.f("fk_usage_grants_teacher_member_id_teacher_members"),
        "usage_grants",
        "teacher_members",
        ["teacher_member_id"],
        ["id"],
    )


def downgrade() -> None:
    """Downgrade schema. The ``inviterole`` value ``assistant`` stays (see docstring)."""
    op.drop_constraint(
        op.f("fk_usage_grants_teacher_member_id_teacher_members"),
        "usage_grants",
        type_="foreignkey",
    )
    op.execute("DELETE FROM invites WHERE team_teacher_id IS NOT NULL")
    op.drop_constraint(op.f("ck_invites_assistant_shape"), "invites", type_="check")
    op.drop_constraint(op.f("ck_invites_target"), "invites", type_="check")
    op.create_check_constraint(
        op.f("ck_invites_target"),
        "invites",
        "school_id IS NOT NULL OR class_id IS NOT NULL OR child_id IS NOT NULL",
    )
    op.drop_index("ix_invites_team_teacher_id", table_name="invites")
    op.drop_column("invites", "assistant_role")
    op.drop_column("invites", "team_teacher_id")
    op.drop_table("teacher_members")
    bind = op.get_bind()
    for name, _values in reversed(_ENUMS):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
```

- [ ] **Step 14: Run the migration and schema tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_migration_teacher_team.py tests/test_team_schema.py tests/test_invite_repo.py tests/test_web_invites.py -v`
Expected: all PASS. The two invite suites prove the widened check left existing invites working.

No test asserts that any revision is head (index R10: Phase 01 replaced the old "0051 is head" checks), so adding 0054 breaks no earlier migration test.

- [ ] **Step 15: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/db/models/team.py lemely/db/migrations/versions/0054_teacher_team.py tests/team_db.py tests/test_team_schema.py tests/test_migration_teacher_team.py
git commit -S -m "feat(team): teacher_members table, assistant invites and seat grant FK (0054)" -- lemely/db/models/team.py lemely/db/models/enums.py lemely/db/models/invites.py lemely/db/models/usage.py lemely/db/models/__init__.py lemely/db/migrations/versions/0054_teacher_team.py tests/team_db.py tests/test_team_schema.py tests/test_migration_teacher_team.py
```

---

### Task 3: `TeacherTeamService` — seats (capacity, claim, scope, cap, removal, release)

**Files:**
- Create: `lemely/db/teacher_team_repo.py`
- Test: `tests/test_teacher_team_seats.py`

**Interfaces:**
- Consumes:
  - Task 1: `MeteredAction`, `SEAT_ACTIONS`
  - Task 2: `TeacherMember` and its enums; the `tests/team_db.py` helpers
  - Phase 02: `PlanTier.audience`, `PlanTier.included_seats`, `Subscription.extra_seats`, `SubscriptionStatus.past_due`
- Produces (`lemely/db/teacher_team_repo.py`):
  - Exceptions, all subclasses of `TeamError(Exception)`:
    - `NoFreeSeat`
    - `TeamMemberNotFound`
    - `TeamStateError`
    - `InvalidScope`
    - `InvalidCap`
    - `InvalidPermissions`
    - `AssistantInviteNotFound`
    - `AssistantInviteRedeemed`
    - `AssistantInviteLimitError`

    The last four are used in Task 4.
  - `month_end(now: datetime) -> datetime`: the first instant of the next UTC month.
  - Constants: `LIVE_PLAN_STATUSES`, `TEACHER_AUDIENCE = PlanAudience.teacher`, `SEAT_ACTIONS_OFF_BY_DEFAULT = frozenset({MeteredAction.STUDY_PLAN})`.
  - `default_seat_actions() -> list[str]`: sorted values of `SEAT_ACTIONS - SEAT_ACTIONS_OFF_BY_DEFAULT` (a new seat's `scope_actions`).
  - `class TeacherTeamService`, constructed as `TeacherTeamService(session: Session)`:
    - `seat_capacity(teacher_user_id: UUID) -> int`
    - `seats_used(teacher_user_id: UUID) -> int`
    - `claim_seat_for_class_join(*, student_user_id: UUID, class_id: UUID, now: datetime) -> TeacherMember` (raises `NoFreeSeat`)
    - `seats_for_student(student_user_id: UUID) -> list[TeacherMember]`
    - `list_seats(teacher_user_id: UUID) -> list[TeacherMember]`
    - `owned_member(teacher_user_id: UUID, member_id: UUID, *, kind: TeacherMemberKind | None) -> TeacherMember`
    - `set_scope(member_id: UUID, *, subjects: list[str], actions: list[str]) -> None`
    - `set_cap(member_id: UUID, *, cap_units: int | None, cap_period: CapPeriod) -> None`
    - `request_removal(member_id: UUID, *, now: datetime) -> None`
    - `release_due(*, now: datetime) -> int`
    - `display_names(user_ids: Sequence[UUID]) -> dict[UUID, str | None]`
  - `class TeacherTeamStore(sessionmaker)` with a `transaction()` context manager that yields a `TeacherTeamService`.

- [ ] **Step 1: Write the failing tests `tests/test_teacher_team_seats.py`**

```python
"""TeacherTeamService seats: capacity, claim, scope, cap, removal, release (§2.2, §4.4, §5.9)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, TypeVar

import pytest

from lemely.db.models.billing import PlanAudience
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.team import CapPeriod, TeacherMemberKind, TeacherMemberStatus
from lemely.db.teacher_team_repo import (
    InvalidCap,
    InvalidScope,
    NoFreeSeat,
    TeacherTeamService,
    TeamMemberNotFound,
    TeamStateError,
    default_seat_actions,
    month_end,
)
from tests._concurrency import _Paused, _wait_until_a_backend_waits_on_a_lock
from tests.team_db import (
    NOW,
    add_assistant,
    add_class,
    add_seat,
    add_subject,
    add_teacher_plan,
    add_user,
    emptied_after,
    enrol,
    team_database,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import Session, sessionmaker

T = TypeVar("T")


@pytest.fixture(scope="module")
def team_db() -> Iterator[sessionmaker[Session]]:
    with team_database() as factory:
        yield factory


@pytest.fixture
def sm(team_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(team_db)


def run(sm: sessionmaker[Session], fn: Callable[[TeacherTeamService], T]) -> T:
    with sm.begin() as session:
        return fn(TeacherTeamService(session))


def join(sm: sessionmaker[Session], class_id: uuid.UUID, student: uuid.UUID) -> uuid.UUID:
    """Enrol, then claim, as the class join flow does; return the seat id."""
    enrol(sm, class_id, student)
    return run(
        sm,
        lambda team: team.claim_seat_for_class_join(
            student_user_id=student, class_id=class_id, now=NOW
        ).id,
    )


# ── capacity ────────────────────────────────────────────────────────────────


def test_capacity_is_zero_without_a_live_plan(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    assert run(sm, lambda team: team.seat_capacity(teacher)) == 0


def test_capacity_is_included_plus_extra(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    add_teacher_plan(sm, teacher, included_seats=2, extra_seats=3)
    assert run(sm, lambda team: team.seat_capacity(teacher)) == 5


def test_past_due_plan_keeps_its_seats(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    add_teacher_plan(sm, teacher, included_seats=2, status=SubscriptionStatus.past_due)
    assert run(sm, lambda team: team.seat_capacity(teacher)) == 2


def test_expired_plan_has_no_seats(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    add_teacher_plan(sm, teacher, included_seats=2, status=SubscriptionStatus.expired)
    assert run(sm, lambda team: team.seat_capacity(teacher)) == 0


def test_a_student_audience_plan_gives_no_seats(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    add_teacher_plan(sm, teacher, included_seats=2, audience=PlanAudience.student)
    assert run(sm, lambda team: team.seat_capacity(teacher)) == 0


# ── claim ───────────────────────────────────────────────────────────────────


def test_claim_creates_a_seat_with_default_scope(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    join(sm, class_id, student)
    [seat] = run(sm, lambda team: team.seats_for_student(student))
    assert seat.kind is TeacherMemberKind.student_seat
    assert seat.teacher_user_id == teacher
    assert seat.scope_subjects == ["0580"]
    assert seat.scope_actions == default_seat_actions()
    assert "study_plan" not in seat.scope_actions
    assert seat.cap_units is None
    assert seat.cap_period is CapPeriod.month
    assert seat.status is TeacherMemberStatus.active


def test_a_second_class_of_the_same_teacher_uses_the_same_seat(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    maths, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    physics, _ = add_class(sm, teacher_id=teacher, subject_code="0625")
    first = join(sm, maths, student)
    second = join(sm, physics, student)
    assert first == second
    [seat] = run(sm, lambda team: team.seats_for_student(student))
    assert seat.scope_subjects == ["0580", "0625"]
    assert run(sm, lambda team: team.seats_used(teacher)) == 1


def test_a_class_without_subject_adds_no_subject(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    plain, _ = add_class(sm, teacher_id=teacher)
    join(sm, plain, student)
    [seat] = run(sm, lambda team: team.seats_for_student(student))
    assert seat.scope_subjects == []


def test_no_free_seat_when_full(sm: sessionmaker[Session]) -> None:
    teacher, s1, s2 = add_user(sm, Role.teacher), add_user(sm), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    join(sm, class_id, s1)
    with pytest.raises(NoFreeSeat):
        join(sm, class_id, s2)
    assert run(sm, lambda team: team.seats_for_student(s2)) == []


def test_no_plan_means_no_seat(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    with pytest.raises(NoFreeSeat):
        join(sm, class_id, student)


def test_leaving_seats_still_count(sm: sessionmaker[Session]) -> None:
    teacher, s1, s2 = add_user(sm, Role.teacher), add_user(sm), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    add_seat(
        sm,
        teacher_id=teacher,
        student_id=s1,
        status=TeacherMemberStatus.leaving,
        leaves_at=month_end(NOW),
    )
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    with pytest.raises(NoFreeSeat):
        join(sm, class_id, s2)


def test_rejoin_while_leaving_stays_leaving_and_adds_the_subject(
    sm: sessionmaker[Session],
) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    add_seat(
        sm,
        teacher_id=teacher,
        student_id=student,
        subjects=["0580"],
        status=TeacherMemberStatus.leaving,
        leaves_at=month_end(NOW),
    )
    physics, _ = add_class(sm, teacher_id=teacher, subject_code="0625")
    join(sm, physics, student)
    [seat] = run(sm, lambda team: team.seats_for_student(student))
    assert seat.status is TeacherMemberStatus.leaving
    assert seat.scope_subjects == ["0580", "0625"]


def test_rejoin_after_removal_reactivates_with_fresh_scope(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    old = add_seat(
        sm,
        teacher_id=teacher,
        student_id=student,
        subjects=["9709"],
        actions=["study_plan"],
        status=TeacherMemberStatus.removed,
        leaves_at=month_end(NOW),
        cap_units=50,
    )
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    assert join(sm, class_id, student) == old
    [seat] = run(sm, lambda team: team.seats_for_student(student))
    assert seat.status is TeacherMemberStatus.active
    assert seat.leaves_at is None
    assert seat.scope_subjects == ["0580"]
    assert seat.scope_actions == default_seat_actions()
    assert seat.cap_units is None


def test_rejoin_after_removal_needs_a_free_seat(sm: sessionmaker[Session]) -> None:
    teacher, s1, s2 = add_user(sm, Role.teacher), add_user(sm), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    add_seat(sm, teacher_id=teacher, student_id=s1)
    add_seat(
        sm,
        teacher_id=teacher,
        student_id=s2,
        status=TeacherMemberStatus.removed,
        leaves_at=month_end(NOW),
    )
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    with pytest.raises(NoFreeSeat):
        join(sm, class_id, s2)


def test_an_existing_seat_survives_a_lapsed_plan(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_seat(sm, teacher_id=teacher, student_id=student, subjects=["0580"])
    physics, _ = add_class(sm, teacher_id=teacher, subject_code="0625")
    join(sm, physics, student)
    [seat] = run(sm, lambda team: team.seats_for_student(student))
    assert seat.scope_subjects == ["0580", "0625"]


def test_an_assistant_row_cannot_become_a_seat(sm: sessionmaker[Session]) -> None:
    teacher, other = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    add_assistant(sm, teacher_id=teacher, assistant_id=other)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    with pytest.raises(TeamStateError):
        join(sm, class_id, other)


def test_concurrent_claims_cannot_exceed_capacity(sm: sessionmaker[Session]) -> None:
    teacher, s1, s2 = add_user(sm, Role.teacher), add_user(sm), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    class_id, _ = add_class(sm, teacher_id=teacher, subject_code="0580")
    enrol(sm, class_id, s1)
    enrol(sm, class_id, s2)

    def second_claim() -> object:
        with sm.begin() as session:
            return TeacherTeamService(session).claim_seat_for_class_join(
                student_user_id=s2, class_id=class_id, now=NOW
            )

    first = sm()
    first.begin()
    try:
        TeacherTeamService(first).claim_seat_for_class_join(
            student_user_id=s1, class_id=class_id, now=NOW
        )
        worker = _Paused(second_claim)
        _wait_until_a_backend_waits_on_a_lock(sm)
        first.commit()
    finally:
        first.close()
    worker.join()
    assert isinstance(worker.error, NoFreeSeat)
    assert run(sm, lambda team: team.seats_used(teacher)) == 1


# ── listing ─────────────────────────────────────────────────────────────────


def test_seats_for_student_are_oldest_first_and_exclude_removed(
    sm: sessionmaker[Session],
) -> None:
    t1, t2, t3, student = (
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm),
    )
    first = add_seat(sm, teacher_id=t1, student_id=student)
    second = add_seat(
        sm,
        teacher_id=t2,
        student_id=student,
        status=TeacherMemberStatus.leaving,
        leaves_at=month_end(NOW),
    )
    add_seat(
        sm,
        teacher_id=t3,
        student_id=student,
        status=TeacherMemberStatus.removed,
        leaves_at=month_end(NOW),
    )
    seats = run(sm, lambda team: [m.id for m in team.seats_for_student(student)])
    assert seats == [first, second]


def test_list_seats_is_the_teachers_own_held_seats(sm: sessionmaker[Session]) -> None:
    teacher, other, s1, s2 = (
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm),
        add_user(sm),
    )
    mine = add_seat(sm, teacher_id=teacher, student_id=s1)
    add_seat(sm, teacher_id=other, student_id=s2)
    assert run(sm, lambda team: [m.id for m in team.list_seats(teacher)]) == [mine]


def test_owned_member_is_not_found_for_another_teacher(sm: sessionmaker[Session]) -> None:
    teacher, other, student = add_user(sm, Role.teacher), add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    with pytest.raises(TeamMemberNotFound):
        run(sm, lambda team: team.owned_member(other, seat, kind=None))
    with pytest.raises(TeamMemberNotFound):
        run(sm, lambda team: team.owned_member(teacher, seat, kind=TeacherMemberKind.assistant))
    assert run(sm, lambda team: team.owned_member(teacher, seat, kind=None).id) == seat


# ── scope and cap ───────────────────────────────────────────────────────────


def test_set_scope_dedupes_sorts_and_accepts_study_plan(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_subject(sm, "0580")
    add_subject(sm, "0625", "Physics")
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    run(
        sm,
        lambda team: team.set_scope(
            seat,
            subjects=["0625", "0580", "0625"],
            actions=["study_plan", "mark_paper", "study_plan"],
        ),
    )
    [row] = run(sm, lambda team: team.seats_for_student(student))
    assert row.scope_subjects == ["0580", "0625"]
    assert row.scope_actions == ["mark_paper", "study_plan"]


def test_set_scope_refuses_unknown_actions_and_subjects(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_subject(sm, "0580")
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    with pytest.raises(InvalidScope):
        run(sm, lambda team: team.set_scope(seat, subjects=["0580"], actions=["buy_seats"]))
    with pytest.raises(InvalidScope):  # a teacher-side action is never seat-paid (R12)
        run(sm, lambda team: team.set_scope(seat, subjects=["0580"], actions=["regrade"]))
    with pytest.raises(InvalidScope):
        run(sm, lambda team: team.set_scope(seat, subjects=["9999"], actions=["mark_paper"]))


def test_set_scope_refuses_assistants_and_removed_seats(sm: sessionmaker[Session]) -> None:
    teacher, helper, student = add_user(sm, Role.teacher), add_user(sm, Role.teacher), add_user(sm)
    assistant = add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    removed = add_seat(
        sm,
        teacher_id=teacher,
        student_id=student,
        status=TeacherMemberStatus.removed,
        leaves_at=month_end(NOW),
    )
    for member in (assistant, removed):
        with pytest.raises(TeamStateError):
            run(sm, lambda team, m=member: team.set_scope(m, subjects=[], actions=[]))


def test_set_cap(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    run(sm, lambda team: team.set_cap(seat, cap_units=300, cap_period=CapPeriod.total))
    [row] = run(sm, lambda team: team.seats_for_student(student))
    assert (row.cap_units, row.cap_period) == (300, CapPeriod.total)
    run(sm, lambda team: team.set_cap(seat, cap_units=None, cap_period=CapPeriod.month))
    [row] = run(sm, lambda team: team.seats_for_student(student))
    assert row.cap_units is None
    with pytest.raises(InvalidCap):
        run(sm, lambda team: team.set_cap(seat, cap_units=-5, cap_period=CapPeriod.month))


def test_unknown_member_is_not_found(sm: sessionmaker[Session]) -> None:
    unknown = uuid.uuid4()
    with pytest.raises(TeamMemberNotFound):
        run(sm, lambda team: team.set_cap(unknown, cap_units=1, cap_period=CapPeriod.month))


# ── removal and release ─────────────────────────────────────────────────────


def test_month_end_is_the_first_instant_of_next_month() -> None:
    assert month_end(datetime(2026, 11, 14, 12, tzinfo=UTC)) == datetime(2026, 12, 1, tzinfo=UTC)
    assert month_end(datetime(2026, 12, 31, 23, 59, tzinfo=UTC)) == datetime(
        2027, 1, 1, tzinfo=UTC
    )


def test_request_removal_sets_leaving_until_month_end(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    run(sm, lambda team: team.request_removal(seat, now=NOW))
    run(sm, lambda team: team.request_removal(seat, now=NOW + timedelta(days=30)))
    [row] = run(sm, lambda team: team.seats_for_student(student))
    assert row.status is TeacherMemberStatus.leaving
    assert row.leaves_at == datetime(2026, 12, 1, tzinfo=UTC)  # the second call changed nothing


def test_request_removal_refuses_assistants(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    assistant = add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    with pytest.raises(TeamStateError):
        run(sm, lambda team: team.request_removal(assistant, now=NOW))


def test_release_due_frees_only_due_seats(sm: sessionmaker[Session]) -> None:
    teacher, s1, s2, s3 = add_user(sm, Role.teacher), add_user(sm), add_user(sm), add_user(sm)
    due = add_seat(
        sm,
        teacher_id=teacher,
        student_id=s1,
        status=TeacherMemberStatus.leaving,
        leaves_at=NOW - timedelta(seconds=1),
    )
    add_seat(
        sm,
        teacher_id=teacher,
        student_id=s2,
        status=TeacherMemberStatus.leaving,
        leaves_at=NOW + timedelta(days=1),
    )
    add_seat(sm, teacher_id=teacher, student_id=s3)
    assert run(sm, lambda team: team.release_due(now=NOW)) == 1
    assert run(sm, lambda team: team.release_due(now=NOW)) == 0
    assert run(sm, lambda team: team.seats_used(teacher)) == 2
    with pytest.raises(TeamMemberNotFound):
        run(sm, lambda team: team.owned_member(teacher, due, kind=None))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_teacher_team_seats.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'lemely.db.teacher_team_repo'`.

- [ ] **Step 3: Write `lemely/db/teacher_team_repo.py`**

```python
"""Teacher team service: leased student seats and assistants (spec §2.2, §2.3, §4.4, §5.9).

:class:`TeacherTeamService` works inside a ``Session`` its caller owns, so the class
join (``ClassService.join_by_code_with_notice``) claims a seat in the same
transaction as the enrolment: a refused seat rolls the enrolment back.
:class:`TeacherTeamStore` opens one transaction per unit of work for routers and the
team-permission guard.

**Seat count.** Active plus leaving ``student_seat`` rows must stay at or below
``included_seats + extra_seats`` of the teacher's live subscription (status
``active`` or ``past_due``; ``past_due`` is the grace period, §5.2). The count is
taken under ``SELECT … FOR UPDATE`` on that subscription row, so two concurrent joins
serialise and the second sees the first's seat. A teacher with no live plan has zero
seats.

**Lock order.** The subscription row first, then ``teacher_members`` rows. Every path
that creates or reactivates a seat takes them in that order.

**Ownership.** Methods that take a ``member_id`` do not know the caller. Routers call
:meth:`TeacherTeamService.owned_member` first, which answers an id the caller does not
own exactly like an unknown id.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from sqlalchemy import func, select, update

from lemely.core.metered_actions import SEAT_ACTIONS, MeteredAction
from lemely.db.models import ClassEnrollment, PlanTier, SchoolClass, Subject, Subscription, User
from lemely.db.models.billing import PlanAudience
from lemely.db.models.enums import SubscriptionStatus
from lemely.db.models.team import (
    CapPeriod,
    TeacherMember,
    TeacherMemberKind,
    TeacherMemberStatus,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator, Sequence

    from sqlalchemy.orm import Session, sessionmaker

LIVE_PLAN_STATUSES: Final = (SubscriptionStatus.active, SubscriptionStatus.past_due)
"""Subscription states whose seats count (``past_due`` is the 3-day grace, spec §5.2)."""

TEACHER_AUDIENCE: Final = PlanAudience.teacher
"""``plan_tiers.audience`` of a teacher tier (Phase 02)."""

_HELD: Final = (TeacherMemberStatus.active, TeacherMemberStatus.leaving)

SEAT_ACTIONS_OFF_BY_DEFAULT: Final = frozenset({MeteredAction.STUDY_PLAN})
"""Seat actions a teacher turns on per seat (spec §2.2: study plans are off by default)."""


def default_seat_actions() -> list[str]:
    """Return a new seat's ``scope_actions``: every seat action except the opt-in ones."""
    return sorted(action.value for action in SEAT_ACTIONS - SEAT_ACTIONS_OFF_BY_DEFAULT)


class TeamError(Exception):
    """Base class for teacher-team failures."""


class NoFreeSeat(TeamError):
    """The teacher has no free seat for a new student (→ 409 ``no_free_seat``)."""


class TeamMemberNotFound(TeamError):
    """No such member, or not the caller's, or the wrong kind, or removed (→ 404)."""


class TeamStateError(TeamError):
    """The member exists but cannot take this change in its current state (→ 409)."""


class InvalidScope(TeamError):
    """A scope names an unknown subject or an action a seat cannot cover (→ 422)."""


class InvalidCap(TeamError):
    """A cap is negative (→ 422)."""


class InvalidPermissions(TeamError):
    """Permission toggles name something that is not a team permission (→ 422)."""


class AssistantInviteNotFound(TeamError):
    """No live assistant invite has this code (→ 404)."""


class AssistantInviteRedeemed(TeamError):
    """The assistant invite was redeemed by someone else (→ 409)."""


class AssistantInviteLimitError(TeamError):
    """The teacher already holds the most live assistant invites allowed (→ 409)."""


def month_end(now: datetime) -> datetime:
    """Return the first instant of the UTC month after ``now`` (a seat's ``leaves_at``)."""
    current = now.astimezone(UTC)
    if current.month == 12:
        return datetime(current.year + 1, 1, 1, tzinfo=UTC)
    return datetime(current.year, current.month + 1, 1, tzinfo=UTC)


class TeacherTeamService:
    """Seats and assistants of teachers, inside one caller-owned transaction."""

    def __init__(self, session: Session) -> None:
        """Bind the service to ``session``; the caller owns its transaction."""
        self._session = session

    # -- Seats: capacity -----------------------------------------------------

    def seat_capacity(self, teacher_user_id: uuid.UUID) -> int:
        """Return ``included_seats + extra_seats`` of the live teacher plan, or 0."""
        return self._capacity(teacher_user_id, lock=False)

    def seats_used(self, teacher_user_id: uuid.UUID) -> int:
        """Return the teacher's active plus leaving seats."""
        stmt = (
            select(func.count())
            .select_from(TeacherMember)
            .where(
                TeacherMember.teacher_user_id == teacher_user_id,
                TeacherMember.kind == TeacherMemberKind.student_seat,
                TeacherMember.status.in_(_HELD),
            )
        )
        return int(self._session.scalar(stmt) or 0)

    # -- Seats: claim ----------------------------------------------------------

    def claim_seat_for_class_join(
        self, *, student_user_id: uuid.UUID, class_id: uuid.UUID, now: datetime
    ) -> TeacherMember:
        """Take (or extend) the student's seat with the class's teacher (spec §4.4).

        Call after the enrolment row is written, in the same transaction. The first
        join with a teacher creates the seat with default scope: the subjects of the
        teacher's school-less classes the student is in, and every seat action except
        ``study_plan`` (:func:`default_seat_actions`). A later join adds the class
        subject to the seat. A
        ``leaving`` seat stays ``leaving``; a ``removed`` seat is reactivated with
        fresh defaults if a seat is free. ``now`` is the claim instant, passed on to
        Phase 05's seat-allowance-on-claim hook.

        Raises:
            NoFreeSeat: A new or reactivated seat would exceed the plan's seats.
            TeamStateError: The class does not exist, or the pair is an assistant.
        """
        del now  # the claim itself is instant-independent; Phase 05 adds the allowance
        cls = self._session.get(SchoolClass, class_id)
        if cls is None:
            raise TeamStateError(f"Unknown class: {class_id}")
        teacher_id = cls.teacher_id
        capacity = self._capacity(teacher_id, lock=True)
        existing = self._member_row(teacher_id, student_user_id, lock=True)
        if existing is not None and existing.kind is not TeacherMemberKind.student_seat:
            raise TeamStateError("This account is already this teacher's assistant")
        if existing is not None and existing.status is not TeacherMemberStatus.removed:
            subject = cls.subject_code
            current = list(existing.scope_subjects or [])
            if subject is not None and subject not in current:
                existing.scope_subjects = sorted([*current, subject])
                self._session.flush()
            return existing
        if self.seats_used(teacher_id) >= capacity:
            raise NoFreeSeat(f"Teacher {teacher_id} has no free seat")
        subjects = self._joined_subjects(student_user_id, teacher_id, also=cls.subject_code)
        if existing is None:
            member = TeacherMember(
                teacher_user_id=teacher_id,
                member_user_id=student_user_id,
                kind=TeacherMemberKind.student_seat,
                scope_subjects=subjects,
                scope_actions=default_seat_actions(),
                cap_units=None,
                cap_period=CapPeriod.month,
                status=TeacherMemberStatus.active,
            )
            self._session.add(member)
        else:
            member = existing
            member.status = TeacherMemberStatus.active
            member.leaves_at = None
            member.scope_subjects = subjects
            member.scope_actions = default_seat_actions()
            member.cap_units = None
            member.cap_period = CapPeriod.month
        self._session.flush()
        return member

    # -- Seats: reads -------------------------------------------------------------

    def seats_for_student(self, student_user_id: uuid.UUID) -> list[TeacherMember]:
        """Return the student's active and leaving seats, oldest first (spec §5.6)."""
        stmt = (
            select(TeacherMember)
            .where(
                TeacherMember.member_user_id == student_user_id,
                TeacherMember.kind == TeacherMemberKind.student_seat,
                TeacherMember.status.in_(_HELD),
            )
            .order_by(TeacherMember.created_at, TeacherMember.id)
        )
        return list(self._session.scalars(stmt))

    def list_seats(self, teacher_user_id: uuid.UUID) -> list[TeacherMember]:
        """Return the teacher's active and leaving seats, oldest first."""
        stmt = (
            select(TeacherMember)
            .where(
                TeacherMember.teacher_user_id == teacher_user_id,
                TeacherMember.kind == TeacherMemberKind.student_seat,
                TeacherMember.status.in_(_HELD),
            )
            .order_by(TeacherMember.created_at, TeacherMember.id)
        )
        return list(self._session.scalars(stmt))

    def owned_member(
        self,
        teacher_user_id: uuid.UUID,
        member_id: uuid.UUID,
        *,
        kind: TeacherMemberKind | None,
    ) -> TeacherMember:
        """Return the teacher's own non-removed member ``member_id`` (of ``kind`` if given).

        Raises:
            TeamMemberNotFound: Unknown, another teacher's, the wrong kind, or removed;
                one answer for all four, so an id leaks nothing.
        """
        stmt = select(TeacherMember).where(
            TeacherMember.id == member_id,
            TeacherMember.teacher_user_id == teacher_user_id,
            TeacherMember.status != TeacherMemberStatus.removed,
        )
        if kind is not None:
            stmt = stmt.where(TeacherMember.kind == kind)
        member = self._session.scalars(stmt).first()
        if member is None:
            raise TeamMemberNotFound(f"Unknown team member: {member_id}")
        return member

    def display_names(self, user_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str | None]:
        """Return ``users.display_name`` for each id (never the email)."""
        if not user_ids:
            return {}
        rows = self._session.execute(
            select(User.id, User.display_name).where(User.id.in_(list(user_ids)))
        )
        return {user_id: name for user_id, name in rows}

    # -- Seats: scope, cap, removal --------------------------------------------------

    def set_scope(self, member_id: uuid.UUID, *, subjects: list[str], actions: list[str]) -> None:
        """Replace a seat's subjects and actions (spec §2.2).

        Raises:
            TeamMemberNotFound: No such member.
            TeamStateError: The member is an assistant or removed.
            InvalidScope: An action is not in ``SEAT_ACTIONS`` (index R12), or a subject
                is not a ``subjects.code``.
        """
        member = self._locked_member(member_id)
        if (
            member.kind is not TeacherMemberKind.student_seat
            or member.status is TeacherMemberStatus.removed
        ):
            raise TeamStateError("Only a held seat has a scope")
        scopable = {action.value for action in SEAT_ACTIONS}
        unknown_actions = sorted(set(actions) - scopable)
        if unknown_actions:
            raise InvalidScope(f"Actions a seat cannot cover: {unknown_actions}")
        wanted = sorted(set(subjects))
        known = set(self._session.scalars(select(Subject.code).where(Subject.code.in_(wanted))))
        unknown_subjects = [code for code in wanted if code not in known]
        if unknown_subjects:
            raise InvalidScope(f"Unknown subjects: {unknown_subjects}")
        member.scope_subjects = wanted
        member.scope_actions = sorted(set(actions))
        self._session.flush()

    def set_cap(
        self, member_id: uuid.UUID, *, cap_units: int | None, cap_period: CapPeriod
    ) -> None:
        """Set a seat's overflow cap or an assistant's spend cap (``None`` = see model doc).

        Raises:
            TeamMemberNotFound: No such member.
            TeamStateError: The member is removed.
            InvalidCap: ``cap_units`` is negative.
        """
        member = self._locked_member(member_id)
        if member.status is TeacherMemberStatus.removed:
            raise TeamStateError("A removed member has no cap")
        if cap_units is not None and cap_units < 0:
            raise InvalidCap("A cap cannot be negative")
        member.cap_units = cap_units
        member.cap_period = CapPeriod(cap_period)
        self._session.flush()

    def request_removal(self, member_id: uuid.UUID, *, now: datetime) -> None:
        """Mark a seat ``leaving`` until the end of the current month (spec §5.9).

        Idempotent: a seat already leaving keeps its original ``leaves_at``.

        Raises:
            TeamMemberNotFound: No such member.
            TeamStateError: The member is an assistant or already removed.
        """
        member = self._locked_member(member_id)
        if (
            member.kind is not TeacherMemberKind.student_seat
            or member.status is TeacherMemberStatus.removed
        ):
            raise TeamStateError("Only a held seat can be removed this way")
        if member.status is TeacherMemberStatus.leaving:
            return
        member.status = TeacherMemberStatus.leaving
        member.leaves_at = month_end(now)
        self._session.flush()

    def release_due(self, *, now: datetime) -> int:
        """Set every leaving seat whose ``leaves_at`` has passed to ``removed``; the count.

        Run by the ``seats.release_due`` sweeper job (registered in Phase 05). The
        current seat grant runs to its own expiry (spec §5.9).
        """
        released = self._session.scalars(
            update(TeacherMember)
            .where(
                TeacherMember.kind == TeacherMemberKind.student_seat,
                TeacherMember.status == TeacherMemberStatus.leaving,
                TeacherMember.leaves_at <= now,
            )
            .values(status=TeacherMemberStatus.removed)
            .returning(TeacherMember.id)
            .execution_options(synchronize_session=False)
        ).all()
        return len(released)

    # -- Internals ------------------------------------------------------------------

    def _capacity(self, teacher_user_id: uuid.UUID, *, lock: bool) -> int:
        stmt = (
            select(Subscription.extra_seats, PlanTier.included_seats)
            .join(PlanTier, Subscription.plan_tier_id == PlanTier.id)
            .where(
                Subscription.user_id == teacher_user_id,
                Subscription.status.in_(LIVE_PLAN_STATUSES),
                PlanTier.audience == TEACHER_AUDIENCE,
            )
            .order_by(Subscription.created_at, Subscription.id)
            .limit(1)
        )
        if lock:
            stmt = stmt.with_for_update(of=Subscription)
        row = self._session.execute(stmt).first()
        if row is None:
            return 0
        extra, included = row
        return int(included or 0) + int(extra or 0)

    def _member_row(
        self, teacher_user_id: uuid.UUID, member_user_id: uuid.UUID, *, lock: bool
    ) -> TeacherMember | None:
        stmt = select(TeacherMember).where(
            TeacherMember.teacher_user_id == teacher_user_id,
            TeacherMember.member_user_id == member_user_id,
        )
        if lock:
            stmt = stmt.with_for_update()
        return self._session.scalars(stmt).first()

    def _locked_member(self, member_id: uuid.UUID) -> TeacherMember:
        member = self._session.get(TeacherMember, member_id, with_for_update=True)
        if member is None:
            raise TeamMemberNotFound(f"Unknown team member: {member_id}")
        return member

    def _joined_subjects(
        self, student_user_id: uuid.UUID, teacher_user_id: uuid.UUID, *, also: str | None
    ) -> list[str]:
        stmt = (
            select(SchoolClass.subject_code)
            .join(ClassEnrollment, ClassEnrollment.class_id == SchoolClass.id)
            .where(
                ClassEnrollment.student_id == student_user_id,
                SchoolClass.teacher_id == teacher_user_id,
                SchoolClass.school_id.is_(None),
                SchoolClass.subject_code.is_not(None),
            )
            .distinct()
        )
        subjects = {code for code in self._session.scalars(stmt) if code is not None}
        if also is not None:
            subjects.add(also)
        return sorted(subjects)


class TeacherTeamStore:
    """Opens one transaction per unit of team work (routers and the team guard)."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Wire the store to a session factory."""
        self._sessionmaker = sessionmaker

    @contextmanager
    def transaction(self) -> Iterator[TeacherTeamService]:
        """Yield a service bound to a new transaction; commit on exit, roll back on error."""
        with self._sessionmaker() as session, session.begin():
            yield TeacherTeamService(session)


__all__ = [
    "LIVE_PLAN_STATUSES",
    "SEAT_ACTIONS_OFF_BY_DEFAULT",
    "TEACHER_AUDIENCE",
    "AssistantInviteLimitError",
    "AssistantInviteNotFound",
    "AssistantInviteRedeemed",
    "InvalidCap",
    "InvalidPermissions",
    "InvalidScope",
    "NoFreeSeat",
    "TeacherTeamService",
    "TeacherTeamStore",
    "TeamError",
    "TeamMemberNotFound",
    "TeamStateError",
    "default_seat_actions",
    "month_end",
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_teacher_team_seats.py tests/architecture/ -v`
Expected: all PASS. If Postgres is unreachable the DB tests skip. Postgres must be up for this task, so start it and rerun if you see skips.

- [ ] **Step 5: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/db/teacher_team_repo.py tests/test_teacher_team_seats.py
git commit -S -m "feat(team): seat capacity, claim, scope, caps and month-end release" -- lemely/db/teacher_team_repo.py tests/test_teacher_team_seats.py
```

---

### Task 4: `TeacherTeamService` — assistants, assistant invites, invite preview/redeem

**Files:**
- Create: `lemely/db/invite_codes.py`
- Modify: `lemely/db/invite_repo.py`
- Modify: `lemely/db/teacher_team_repo.py`
- Modify: `lemely/web/schemas_invites.py` (`InvitePreviewDTO.role`)
- Test: `tests/test_teacher_team_assistants.py`

**Interfaces:**
- Consumes:
  - Task 1: `validate_overrides`, `UnknownPermissionError`
  - Task 2: `Invite.team_teacher_id`, `Invite.assistant_role`, `InviteRole.assistant`
  - Task 3: `TeacherTeamService` internals (`_member_row`, `_locked_member`), the team exceptions
- Produces (`lemely/db/invite_codes.py`): `generate_invite_code() -> str`, `INVITE_CODE_ALPHABET`, `INVITE_CODE_LENGTH`.
- Produces (`lemely/db/teacher_team_repo.py`):
  - Constant: `MAX_LIVE_ASSISTANT_INVITES = 20`
  - `create_assistant_invite(teacher_user_id: UUID, *, role: AssistantRole, expires_at: datetime) -> Invite`
  - `redeem_assistant_invite(*, code: str, user_id: UUID, now: datetime) -> TeacherMember`
  - `list_assistant_invites(teacher_user_id: UUID, *, now: datetime) -> list[Invite]` (unredeemed, unexpired, oldest first)
  - `revoke_assistant_invite(teacher_user_id: UUID, invite_id: UUID) -> None` (deletes the teacher's own unredeemed invite; anything else raises `AssistantInviteNotFound`) (index R3)
  - `assistant_membership(assistant_user_id: UUID, teacher_user_id: UUID) -> TeacherMember | None` (active assistant rows only)
  - `memberships_for_assistant(assistant_user_id: UUID) -> list[TeacherMember]`
  - `list_assistants(teacher_user_id: UUID) -> list[TeacherMember]`
  - `update_assistant(member_id: UUID, *, role: AssistantRole | None, permissions: Mapping[str, object] | None) -> TeacherMember`
  - `remove_assistant(member_id: UUID) -> None`
- Produces (`InviteService`):
  - `redeem` raises `InviteRoleMismatchError` for an assistant invite.
  - `preview` of an assistant invite returns `role=InviteRole.assistant` and `teacher_name` set to the lead teacher.

- [ ] **Step 1: Write the failing tests `tests/test_teacher_team_assistants.py`**

```python
"""Assistants: invites, redemption, roles, toggles, removal (spec §2.3, §4.4, §7)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, TypeVar

import pytest
from sqlalchemy import select

from lemely.db.class_repo import ClassService
from lemely.db.invite_codes import INVITE_CODE_ALPHABET, INVITE_CODE_LENGTH, generate_invite_code
from lemely.db.invite_repo import InviteRoleMismatchError, InviteService
from lemely.db.models import Invite
from lemely.db.models.enums import InviteRole, Role
from lemely.db.models.team import (
    AssistantRole,
    CapPeriod,
    TeacherMemberKind,
    TeacherMemberStatus,
)
from lemely.db.parent_repo import ParentLinkService
from lemely.db.teacher_team_repo import (
    MAX_LIVE_ASSISTANT_INVITES,
    AssistantInviteLimitError,
    AssistantInviteNotFound,
    AssistantInviteRedeemed,
    InvalidPermissions,
    TeacherTeamService,
    TeamMemberNotFound,
    TeamStateError,
)
from tests.team_db import (
    NOW,
    add_assistant,
    add_seat,
    add_user,
    emptied_after,
    team_database,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import Session, sessionmaker

T = TypeVar("T")


@pytest.fixture(scope="module")
def team_db() -> Iterator[sessionmaker[Session]]:
    with team_database() as factory:
        yield factory


@pytest.fixture
def sm(team_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(team_db)


def run(sm: sessionmaker[Session], fn: Callable[[TeacherTeamService], T]) -> T:
    with sm.begin() as session:
        return fn(TeacherTeamService(session))


FAR = NOW + timedelta(days=3650)
"""Expiry for invites a test redeems or previews: InviteService.preview reads the real
clock, so a near expiry would make these tests fail once the calendar passes it."""


def mint(sm: sessionmaker[Session], teacher: uuid.UUID, role: AssistantRole) -> str:
    return run(
        sm,
        lambda team: team.create_assistant_invite(teacher, role=role, expires_at=FAR).code,
    )


def redeem(sm: sessionmaker[Session], code: str, user: uuid.UUID) -> uuid.UUID:
    return run(sm, lambda team: team.redeem_assistant_invite(code=code, user_id=user, now=NOW).id)


def test_generated_codes_use_the_invite_alphabet() -> None:
    code = generate_invite_code()
    assert len(code) == INVITE_CODE_LENGTH
    assert set(code) <= set(INVITE_CODE_ALPHABET)


def test_create_assistant_invite_is_single_use_and_expiring(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    code = mint(sm, teacher, AssistantRole.marker)
    with sm() as session:
        invite = session.scalars(select(Invite).where(Invite.code == code)).one()
    assert invite.role is InviteRole.assistant
    assert invite.team_teacher_id == teacher
    assert invite.created_by == teacher
    assert invite.assistant_role is AssistantRole.marker
    assert invite.reusable is False
    assert invite.expires_at == FAR


def test_live_assistant_invites_are_capped(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    for _ in range(MAX_LIVE_ASSISTANT_INVITES):
        mint(sm, teacher, AssistantRole.viewer)
    with pytest.raises(AssistantInviteLimitError):
        mint(sm, teacher, AssistantRole.viewer)


def test_redeem_creates_an_active_assistant(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    member_id = redeem(sm, mint(sm, teacher, AssistantRole.marker), helper)
    member = run(sm, lambda team: team.assistant_membership(helper, teacher))
    assert member is not None
    assert member.id == member_id
    assert member.kind is TeacherMemberKind.assistant
    assert member.role_preset is AssistantRole.marker
    assert member.permissions == {}
    assert member.cap_units is None
    assert member.cap_period is CapPeriod.month


def test_redeem_is_idempotent_for_the_same_user(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    code = mint(sm, teacher, AssistantRole.viewer)
    assert redeem(sm, code, helper) == redeem(sm, code, helper)


def test_redeem_by_a_second_user_is_refused(sm: sessionmaker[Session]) -> None:
    teacher, h1, h2 = add_user(sm, Role.teacher), add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    code = mint(sm, teacher, AssistantRole.viewer)
    redeem(sm, code, h1)
    with pytest.raises(AssistantInviteRedeemed):
        redeem(sm, code, h2)


def test_expired_or_unknown_or_foreign_codes_are_not_found(sm: sessionmaker[Session]) -> None:
    teacher, helper, child = (
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm, Role.student),
    )
    expired = run(
        sm,
        lambda team: team.create_assistant_invite(
            teacher, role=AssistantRole.viewer, expires_at=NOW - timedelta(seconds=1)
        ).code,
    )
    parent_code = InviteService(sm, ClassService(sm), ParentLinkService(sm)).mint_parent_invite(
        child, reusable=False
    ).code
    for code in (expired, "NOSUCHCODE", parent_code):
        with pytest.raises(AssistantInviteNotFound):
            redeem(sm, code, helper)


def test_list_and_revoke_assistant_invites(sm: sessionmaker[Session]) -> None:
    teacher, other, helper = (
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
    )
    live = mint(sm, teacher, AssistantRole.viewer)
    redeem(sm, mint(sm, teacher, AssistantRole.viewer), helper)
    run(
        sm,
        lambda team: team.create_assistant_invite(
            teacher, role=AssistantRole.viewer, expires_at=NOW - timedelta(seconds=1)
        ),
    )
    invites = run(sm, lambda team: team.list_assistant_invites(teacher, now=NOW))
    assert [i.code for i in invites] == [live]  # redeemed and expired ones are not listed
    invite_id = invites[0].id
    with pytest.raises(AssistantInviteNotFound):
        run(sm, lambda team: team.revoke_assistant_invite(other, invite_id))
    run(sm, lambda team: team.revoke_assistant_invite(teacher, invite_id))
    assert run(sm, lambda team: team.list_assistant_invites(teacher, now=NOW)) == []
    with pytest.raises(AssistantInviteNotFound):
        redeem(sm, live, helper)


def test_a_redeemed_invite_cannot_be_revoked(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    code = mint(sm, teacher, AssistantRole.viewer)
    redeem(sm, code, helper)
    with sm() as session:
        invite_id = session.scalars(select(Invite.id).where(Invite.code == code)).one()
    with pytest.raises(AssistantInviteNotFound):
        run(sm, lambda team: team.revoke_assistant_invite(teacher, invite_id))


def test_a_teacher_cannot_assist_themselves(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    with pytest.raises(TeamStateError):
        redeem(sm, mint(sm, teacher, AssistantRole.viewer), teacher)


def test_a_seat_holder_cannot_become_the_same_teachers_assistant(
    sm: sessionmaker[Session],
) -> None:
    teacher, other = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_seat(sm, teacher_id=teacher, student_id=other)
    with pytest.raises(TeamStateError):
        redeem(sm, mint(sm, teacher, AssistantRole.viewer), other)


def test_redeem_after_removal_reactivates_with_the_new_role(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    old = add_assistant(
        sm,
        teacher_id=teacher,
        assistant_id=helper,
        role=AssistantRole.co_teacher,
        permissions={"mark": False},
        status=TeacherMemberStatus.removed,
    )
    assert redeem(sm, mint(sm, teacher, AssistantRole.viewer), helper) == old
    member = run(sm, lambda team: team.assistant_membership(helper, teacher))
    assert member is not None
    assert member.role_preset is AssistantRole.viewer
    assert member.permissions == {}


def test_membership_reads_only_active_assistants(sm: sessionmaker[Session]) -> None:
    t1, t2, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    first = add_assistant(sm, teacher_id=t1, assistant_id=helper)
    add_assistant(sm, teacher_id=t2, assistant_id=helper, status=TeacherMemberStatus.removed)
    assert run(sm, lambda team: team.assistant_membership(helper, t2)) is None
    assert run(sm, lambda team: [m.id for m in team.memberships_for_assistant(helper)]) == [first]
    assert run(sm, lambda team: [m.id for m in team.list_assistants(t1)]) == [first]
    assert run(sm, lambda team: team.list_assistants(t2)) == []


def test_update_assistant_role_and_toggles(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    member = add_assistant(sm, teacher_id=teacher, assistant_id=helper, role=AssistantRole.viewer)
    run(
        sm,
        lambda team: team.update_assistant(
            member, role=AssistantRole.marker, permissions={"view_usage": True}
        ),
    )
    row = run(sm, lambda team: team.assistant_membership(helper, teacher))
    assert row is not None
    assert row.role_preset is AssistantRole.marker
    assert row.permissions == {"view_usage": True}
    run(sm, lambda team: team.update_assistant(member, role=None, permissions=None))
    row = run(sm, lambda team: team.assistant_membership(helper, teacher))
    assert row is not None
    assert row.role_preset is AssistantRole.marker  # None leaves each field unchanged


def test_update_assistant_refuses_unknown_toggles(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    member = add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    with pytest.raises(InvalidPermissions):
        run(sm, lambda team: team.update_assistant(member, role=None, permissions={"billing": True}))


def test_update_and_remove_refuse_seats(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    with pytest.raises(TeamStateError):
        run(sm, lambda team: team.update_assistant(seat, role=AssistantRole.viewer, permissions=None))
    with pytest.raises(TeamStateError):
        run(sm, lambda team: team.remove_assistant(seat))


def test_remove_assistant_is_immediate(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    member = add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    run(sm, lambda team: team.remove_assistant(member))
    assert run(sm, lambda team: team.assistant_membership(helper, teacher)) is None
    with pytest.raises(TeamMemberNotFound):
        run(sm, lambda team: team.owned_member(teacher, member, kind=TeacherMemberKind.assistant))


# ── InviteService: preview and generic redeem ────────────────────────────────


def test_generic_preview_names_the_lead_teacher(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher, display_name="Ms Hoda")
    code = mint(sm, teacher, AssistantRole.marker)
    preview = InviteService(sm, ClassService(sm), ParentLinkService(sm)).preview(code)
    assert preview.role is InviteRole.assistant
    assert preview.teacher_name == "Ms Hoda"
    assert preview.class_name is None
    assert preview.school_name is None
    assert preview.child_name is None


def test_generic_redeem_refuses_an_assistant_invite(sm: sessionmaker[Session]) -> None:
    teacher, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    code = mint(sm, teacher, AssistantRole.marker)
    service = InviteService(sm, ClassService(sm), ParentLinkService(sm))
    with pytest.raises(InviteRoleMismatchError):
        service.redeem(helper, code, caller_role=Role.teacher)
    with sm() as session:
        invite = session.scalars(select(Invite).where(Invite.code == code)).one()
    assert invite.redeemed_by is None
    assert run(sm, lambda team: team.assistant_membership(helper, teacher)) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_teacher_team_assistants.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'lemely.db.invite_codes'`.

- [ ] **Step 3: Create `lemely/db/invite_codes.py`**

```python
"""Invite code generation shared by every invite minter (D7.3; paymob billing Phase 03).

Moved out of ``lemely/db/invite_repo.py`` so ``lemely/db/teacher_team_repo.py`` can
mint assistant invites without importing ``invite_repo`` (which imports
``class_repo``, which imports ``teacher_team_repo``). Codes are unchanged.

The alphabet excludes visually ambiguous characters (0/O, 1/I/L), mirroring
``class_repo._JOIN_CODE_ALPHABET``: a holder must be able to transcribe a code read
off a screen. The length differs from a class join code's so the two families look
different.
"""

from __future__ import annotations

import secrets
from typing import Final

INVITE_CODE_ALPHABET: Final = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
INVITE_CODE_LENGTH: Final = 10


def generate_invite_code() -> str:
    """Return a random invite code from the non-ambiguous alphabet."""
    return "".join(secrets.choice(INVITE_CODE_ALPHABET) for _ in range(INVITE_CODE_LENGTH))


__all__ = ["INVITE_CODE_ALPHABET", "INVITE_CODE_LENGTH", "generate_invite_code"]
```

- [ ] **Step 4: Point `lemely/db/invite_repo.py` at it, and handle assistant invites**

1. Delete the module-level `_INVITE_CODE_ALPHABET = …` and `_INVITE_CODE_LENGTH = …` lines and the comment block above them. Keep `_INVITE_CODE_MAX_ATTEMPTS = 8`. Also delete the `def _generate_invite_code() -> str:` function at the bottom of the module.
2. Delete `import secrets` (its only use was `_generate_invite_code`). Add this import with the other `lemely.db` imports:

```python
from lemely.db.invite_codes import generate_invite_code
```

3. In `_insert_invite`, replace `code=_generate_invite_code(),` with `code=generate_invite_code(),`.
4. In `redeem`, inside `if invite is not None:`, insert this branch **before** `if invite.role is InviteRole.parent:`:

```python
                if invite.role is InviteRole.assistant:
                    # An assistant invite attaches a teacher account to a team; it is
                    # redeemed only by POST /api/teacher/team/assistants/redeem, which
                    # checks the caller is a teacher (paymob billing Phase 03).
                    raise InviteRoleMismatchError(
                        f"Invite {code!r} is an assistant invite; redeem it from the team page"
                    )
```

5. In `_preview_for_invite`, insert before the `return InvitePreview(`:

```python
        if invite.team_teacher_id is not None:
            teacher_name = self._teacher_name(session, invite.team_teacher_id)
```

6. In the `redeem` docstring's `Raises:` entry for `InviteRoleMismatchError`, append: "or ``code`` is an assistant invite (redeemed only through the team route)".

- [ ] **Step 5: Let the public preview carry the new role in `lemely/web/schemas_invites.py`**

In `InvitePreviewDTO`, replace `role: Literal["student", "teacher", "parent"]` with:

```python
    role: Literal["student", "teacher", "parent", "assistant"]
```

Append to its docstring: "An ``assistant`` preview names only the lead teacher (paymob billing Phase 03)."

- [ ] **Step 6: Add the assistant methods to `lemely/db/teacher_team_repo.py`**

Imports. Merge them into the existing import lines:

```python
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from lemely.core.metered_actions import SEAT_ACTIONS, MeteredAction
from lemely.core.team_permissions import UnknownPermissionError, validate_overrides
from lemely.db.invite_codes import generate_invite_code
from lemely.db.models import (
    ClassEnrollment,
    Invite,
    PlanTier,
    SchoolClass,
    Subject,
    Subscription,
    User,
)
from lemely.db.models.enums import InviteRole, SubscriptionStatus
from lemely.db.models.team import (
    AssistantRole,
    CapPeriod,
    TeacherMember,
    TeacherMemberKind,
    TeacherMemberStatus,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator, Mapping, Sequence

    from sqlalchemy.orm import Session, sessionmaker
```

Module constants, below `_HELD`:

```python
MAX_LIVE_ASSISTANT_INVITES: Final = 20
"""Cap on a teacher's live (unexpired, unredeemed) assistant invites, as for parent links."""

_INVITE_CODE_ATTEMPTS: Final = 8
```

This section goes inside `TeacherTeamService`, between `release_due` and `# -- Internals`:

```python
    # -- Assistants ------------------------------------------------------------------

    def create_assistant_invite(
        self, teacher_user_id: uuid.UUID, *, role: AssistantRole, expires_at: datetime
    ) -> Invite:
        """Mint a single-use, expiring assistant invite for the teacher's team (spec §4.4).

        Serialised per teacher by a lock on the teacher's ``users`` row, so the live-invite
        cap holds under concurrent mints.

        Raises:
            AssistantInviteLimitError: The teacher holds the most live invites allowed.
            TeamError: No unique code after several attempts (astronomically unlikely).
        """
        self._session.execute(
            select(User.id).where(User.id == teacher_user_id).with_for_update()
        )
        live = self._session.scalar(
            select(func.count())
            .select_from(Invite)
            .where(
                Invite.team_teacher_id == teacher_user_id,
                Invite.redeemed_by.is_(None),
                Invite.expires_at > func.now(),
            )
        )
        if int(live or 0) >= MAX_LIVE_ASSISTANT_INVITES:
            raise AssistantInviteLimitError(
                f"A teacher may hold at most {MAX_LIVE_ASSISTANT_INVITES} live assistant invites"
            )
        for _ in range(_INVITE_CODE_ATTEMPTS):
            invite = Invite(
                code=generate_invite_code(),
                role=InviteRole.assistant,
                created_by=teacher_user_id,
                team_teacher_id=teacher_user_id,
                assistant_role=AssistantRole(role),
                expires_at=expires_at,
                reusable=False,
            )
            try:
                with self._session.begin_nested():
                    self._session.add(invite)
                    self._session.flush()
            except IntegrityError:
                continue
            return invite
        raise TeamError("Could not generate a unique invite code; please retry")

    def redeem_assistant_invite(
        self, *, code: str, user_id: uuid.UUID, now: datetime
    ) -> TeacherMember:
        """Attach ``user_id`` to the invite's teacher as an assistant (spec §2.3).

        Idempotent for the same user: an active assistant keeps its row, role and
        toggles. A removed assistant is reactivated with the invite's role and no
        toggles. The caller must be a teacher account; the router checks the role.

        Raises:
            AssistantInviteNotFound: No unexpired assistant invite has ``code``.
            AssistantInviteRedeemed: Another user already redeemed it.
            TeamStateError: The redeemer is the teacher, or holds a seat with them.
        """
        invite = self._session.scalars(
            select(Invite).where(Invite.code == code).with_for_update()
        ).first()
        if (
            invite is None
            or invite.role is not InviteRole.assistant
            or invite.team_teacher_id is None
            or invite.assistant_role is None
            or (invite.expires_at is not None and invite.expires_at <= now)
        ):
            raise AssistantInviteNotFound("Unknown assistant invite")
        if invite.redeemed_by is not None and invite.redeemed_by != user_id:
            raise AssistantInviteRedeemed("This assistant invite has already been used")
        teacher_id = invite.team_teacher_id
        if teacher_id == user_id:
            raise TeamStateError("A teacher cannot be their own assistant")
        member = self._member_row(teacher_id, user_id, lock=True)
        if member is not None and member.kind is not TeacherMemberKind.assistant:
            raise TeamStateError("This account already holds a seat with this teacher")
        if member is None:
            member = TeacherMember(
                teacher_user_id=teacher_id,
                member_user_id=user_id,
                kind=TeacherMemberKind.assistant,
                role_preset=invite.assistant_role,
                permissions={},
                cap_units=None,
                cap_period=CapPeriod.month,
                status=TeacherMemberStatus.active,
            )
            self._session.add(member)
        elif member.status is TeacherMemberStatus.removed:
            member.status = TeacherMemberStatus.active
            member.leaves_at = None
            member.role_preset = invite.assistant_role
            member.permissions = {}
            member.cap_units = None
            member.cap_period = CapPeriod.month
        if invite.redeemed_by is None:
            invite.redeemed_by = user_id
            invite.redeemed_at = now
        self._session.flush()
        return member

    def list_assistant_invites(
        self, teacher_user_id: uuid.UUID, *, now: datetime
    ) -> list[Invite]:
        """Return the teacher's unredeemed, unexpired assistant invites, oldest first."""
        stmt = (
            select(Invite)
            .where(
                Invite.team_teacher_id == teacher_user_id,
                Invite.redeemed_by.is_(None),
                Invite.expires_at > now,
            )
            .order_by(Invite.created_at, Invite.id)
        )
        return list(self._session.scalars(stmt))

    def revoke_assistant_invite(self, teacher_user_id: uuid.UUID, invite_id: uuid.UUID) -> None:
        """Delete the teacher's own unredeemed assistant invite (index R3).

        Raises:
            AssistantInviteNotFound: Unknown, another teacher's, or already redeemed;
                one answer for all three.
        """
        invite = self._session.scalars(
            select(Invite)
            .where(
                Invite.id == invite_id,
                Invite.team_teacher_id == teacher_user_id,
                Invite.redeemed_by.is_(None),
            )
            .with_for_update()
        ).first()
        if invite is None:
            raise AssistantInviteNotFound(f"Unknown assistant invite: {invite_id}")
        self._session.delete(invite)
        self._session.flush()

    def assistant_membership(
        self, assistant_user_id: uuid.UUID, teacher_user_id: uuid.UUID
    ) -> TeacherMember | None:
        """Return the active assistant row linking the two accounts, or ``None``."""
        stmt = select(TeacherMember).where(
            TeacherMember.teacher_user_id == teacher_user_id,
            TeacherMember.member_user_id == assistant_user_id,
            TeacherMember.kind == TeacherMemberKind.assistant,
            TeacherMember.status == TeacherMemberStatus.active,
        )
        return self._session.scalars(stmt).first()

    def memberships_for_assistant(self, assistant_user_id: uuid.UUID) -> list[TeacherMember]:
        """Return every team the account actively assists, oldest first."""
        stmt = (
            select(TeacherMember)
            .where(
                TeacherMember.member_user_id == assistant_user_id,
                TeacherMember.kind == TeacherMemberKind.assistant,
                TeacherMember.status == TeacherMemberStatus.active,
            )
            .order_by(TeacherMember.created_at, TeacherMember.id)
        )
        return list(self._session.scalars(stmt))

    def list_assistants(self, teacher_user_id: uuid.UUID) -> list[TeacherMember]:
        """Return the teacher's active assistants, oldest first."""
        stmt = (
            select(TeacherMember)
            .where(
                TeacherMember.teacher_user_id == teacher_user_id,
                TeacherMember.kind == TeacherMemberKind.assistant,
                TeacherMember.status == TeacherMemberStatus.active,
            )
            .order_by(TeacherMember.created_at, TeacherMember.id)
        )
        return list(self._session.scalars(stmt))

    def update_assistant(
        self,
        member_id: uuid.UUID,
        *,
        role: AssistantRole | None,
        permissions: Mapping[str, object] | None,
    ) -> TeacherMember:
        """Change an assistant's role preset and/or toggles; ``None`` leaves a field as is.

        Raises:
            TeamMemberNotFound: No such member.
            TeamStateError: The member is a seat or removed.
            InvalidPermissions: A toggle is not a team permission or not a bool.
        """
        member = self._locked_member(member_id)
        if (
            member.kind is not TeacherMemberKind.assistant
            or member.status is TeacherMemberStatus.removed
        ):
            raise TeamStateError("Only an active assistant has a role")
        if permissions is not None:
            try:
                member.permissions = validate_overrides(permissions)
            except UnknownPermissionError as exc:
                raise InvalidPermissions(str(exc)) from exc
        if role is not None:
            member.role_preset = AssistantRole(role)
        self._session.flush()
        return member

    def remove_assistant(self, member_id: uuid.UUID) -> None:
        """Remove an assistant at once (no month-end period; assistants have no allowance).

        Raises:
            TeamMemberNotFound: No such member.
            TeamStateError: The member is a seat or already removed.
        """
        member = self._locked_member(member_id)
        if (
            member.kind is not TeacherMemberKind.assistant
            or member.status is TeacherMemberStatus.removed
        ):
            raise TeamStateError("Only an active assistant can be removed this way")
        member.status = TeacherMemberStatus.removed
        member.leaves_at = None
        self._session.flush()
```

Add `"MAX_LIVE_ASSISTANT_INVITES",` to `__all__`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_teacher_team_assistants.py tests/test_teacher_team_seats.py tests/test_invite_repo.py tests/test_web_invites.py tests/architecture/ -v`
Expected: all PASS. The invite suites prove that moving code generation changed nothing.

- [ ] **Step 8: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/db/invite_codes.py tests/test_teacher_team_assistants.py
git commit -S -m "feat(team): assistant invites, redemption, roles and removal" -- lemely/db/invite_codes.py lemely/db/invite_repo.py lemely/db/teacher_team_repo.py lemely/web/schemas_invites.py tests/test_teacher_team_assistants.py
```

---

### Task 5: Seat claim on class join, with the 409 refusal

**Files:**
- Modify: `lemely/db/class_repo.py` (`ClassService.__init__`, `join_by_code_with_notice`, new `_claim_teacher_seat`)
- Create: `lemely/web/team_http.py`
- Modify: `lemely/runtime/config.py` (`TeamSettings`, `Settings.team`)
- Modify: `tests/conftest.py` (suite switch)
- Modify: `lemely/web/deps.py` (`get_class_service`)
- Modify: `lemely/web/routers/student.py` (`student_join_class`)
- Modify: `lemely/web/routers/invites.py` (`redeem_invite`)
- Test: `tests/test_team_seat_claim_join.py`

**Interfaces:**
- Consumes (Task 3):
  - `TeacherTeamService.claim_seat_for_class_join`, `seats_for_student`
  - Exceptions: `NoFreeSeat`, `TeamMemberNotFound`, `TeamStateError`, `InvalidScope`, `InvalidCap`, `InvalidPermissions`, `AssistantInviteNotFound`, `AssistantInviteRedeemed`, `AssistantInviteLimitError`, `TeamError`
- Produces:
  - `TeamSettings(enforce_teacher_seats: bool = True)`, exposed as `Settings.team`
  - `ClassService(sessionmaker, *, enforce_teacher_seats: bool | None = None)` (`None` reads `Settings().team.enforce_teacher_seats`)
  - `join_by_code_with_notice` raises `NoFreeSeat` when enforced and no seat is free. The enrolment is rolled back.
  - `lemely.web.team_http`:
    - `NO_FREE_SEAT_MESSAGE`
    - `no_free_seat_error() -> HTTPException` (409, `{"code": "no_free_seat", "message": NO_FREE_SEAT_MESSAGE}`)
    - `team_error_to_http(exc: TeamError) -> HTTPException`

- [ ] **Step 1: Write the failing tests `tests/test_team_seat_claim_join.py`**

```python
"""Joining a teacher's class claims or extends a seat; no free seat refuses the join (§4.4)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from lemely.db.class_repo import ClassService
from lemely.db.invite_repo import InviteService
from lemely.db.models import ClassEnrollment, Invite, School
from lemely.db.models.enums import InviteRole, Role
from lemely.db.parent_repo import ParentLinkService
from lemely.db.teacher_team_repo import NoFreeSeat, TeacherTeamService
from lemely.runtime.config import Settings, TeamSettings
from lemely.web import deps
from lemely.web.app import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_class_service, get_invite_service
from lemely.web.team_http import NO_FREE_SEAT_MESSAGE
from tests.team_db import (
    add_class,
    add_teacher_plan,
    add_user,
    emptied_after,
    team_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI
    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def team_db() -> Iterator[sessionmaker[Session]]:
    with team_database() as factory:
        yield factory


@pytest.fixture
def sm(team_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(team_db)


def _enrolled(sm: sessionmaker[Session], class_id: uuid.UUID, student: uuid.UUID) -> bool:
    with sm() as session:
        count = session.scalar(
            select(func.count())
            .select_from(ClassEnrollment)
            .where(ClassEnrollment.class_id == class_id, ClassEnrollment.student_id == student)
        )
    return bool(count)


def _seats(sm: sessionmaker[Session], student: uuid.UUID) -> list[uuid.UUID]:
    with sm() as session:
        return [m.teacher_user_id for m in TeacherTeamService(session).seats_for_student(student)]


# ── ClassService ──────────────────────────────────────────────────────────────


def test_enforced_join_claims_a_seat(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    class_id, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    ClassService(sm, enforce_teacher_seats=True).join_by_code_with_notice(student, code)
    assert _enrolled(sm, class_id, student)
    assert _seats(sm, student) == [teacher]


def test_enforced_join_without_a_free_seat_is_refused_and_rolled_back(
    sm: sessionmaker[Session],
) -> None:
    teacher, s1, s2 = add_user(sm, Role.teacher), add_user(sm), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    class_id, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    service = ClassService(sm, enforce_teacher_seats=True)
    service.join_by_code_with_notice(s1, code)
    with pytest.raises(NoFreeSeat):
        service.join_by_code_with_notice(s2, code)
    assert not _enrolled(sm, class_id, s2)
    assert _seats(sm, s2) == []


def test_enforced_join_of_a_teacher_without_a_plan_is_refused(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    class_id, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    with pytest.raises(NoFreeSeat):
        ClassService(sm, enforce_teacher_seats=True).join_by_code_with_notice(student, code)
    assert not _enrolled(sm, class_id, student)


def test_soft_join_without_a_free_seat_enrols_without_a_seat(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    class_id, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    ClassService(sm, enforce_teacher_seats=False).join_by_code_with_notice(student, code)
    assert _enrolled(sm, class_id, student)
    assert _seats(sm, student) == []


def test_soft_join_with_a_free_seat_still_claims_it(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    _, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    ClassService(sm, enforce_teacher_seats=False).join_by_code_with_notice(student, code)
    assert _seats(sm, student) == [teacher]


def test_rejoining_the_same_class_keeps_one_seat(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    _, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    service = ClassService(sm, enforce_teacher_seats=True)
    service.join_by_code_with_notice(student, code)
    service.join_by_code_with_notice(student, code)
    assert _seats(sm, student) == [teacher]


def test_a_school_class_takes_no_seat(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    school_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(School(id=school_id, name="Seat-free School", seat_quota=10))
    class_id, code = add_class(sm, teacher_id=teacher, subject_code="0580", school_id=school_id)
    ClassService(sm, enforce_teacher_seats=True).join_by_code_with_notice(student, code)
    assert _enrolled(sm, class_id, student)
    assert _seats(sm, student) == []


def test_a_teacher_joining_takes_no_seat(sm: sessionmaker[Session]) -> None:
    teacher, other_teacher = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    class_id, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    ClassService(sm, enforce_teacher_seats=True).join_by_code_with_notice(other_teacher, code)
    assert _enrolled(sm, class_id, other_teacher)
    assert _seats(sm, other_teacher) == []


def test_seats_are_enforced_by_default_and_off_under_the_suite() -> None:
    assert TeamSettings().enforce_teacher_seats is True
    assert Settings().team.enforce_teacher_seats is False  # tests/conftest.py's switch


def test_the_app_built_from_default_settings_enforces_seats(
    sm: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LEMELY_TEAM__ENFORCE_TEACHER_SEATS", raising=False)
    deps.reset_singletons()
    try:
        assert deps.get_settings().team.enforce_teacher_seats is True
        assert deps.get_class_service()._enforce_teacher_seats is True
        assert ClassService(sm)._enforce_teacher_seats is True
    finally:
        deps.reset_singletons()


def test_the_suite_switch_reaches_direct_constructions(sm: sessionmaker[Session]) -> None:
    assert ClassService(sm)._enforce_teacher_seats is False


# ── HTTP: both join entry points answer 409 no_free_seat ─────────────────────


def _client(sm: sessionmaker[Session], student: uuid.UUID) -> TestClient:
    app: FastAPI = create_app()
    classes = ClassService(sm, enforce_teacher_seats=True)
    app.dependency_overrides[get_class_service] = lambda: classes
    app.dependency_overrides[get_invite_service] = lambda: InviteService(
        sm, classes, ParentLinkService(sm)
    )
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(student), role=Role.student.value
    )
    return TestClient(app)


def _full_class(sm: sessionmaker[Session]) -> tuple[uuid.UUID, uuid.UUID, str]:
    teacher, holder = add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, teacher, included_seats=1)
    class_id, code = add_class(sm, teacher_id=teacher, subject_code="0580")
    ClassService(sm, enforce_teacher_seats=True).join_by_code_with_notice(holder, code)
    return teacher, class_id, code


def test_student_join_route_answers_409_no_free_seat(sm: sessionmaker[Session]) -> None:
    _, class_id, code = _full_class(sm)
    student = add_user(sm)
    resp = _client(sm, student).post("/api/student/classes/join", json={"joinCode": code})
    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": "no_free_seat", "message": NO_FREE_SEAT_MESSAGE}
    assert not _enrolled(sm, class_id, student)


def test_invite_redeem_of_a_bare_join_code_answers_409(sm: sessionmaker[Session]) -> None:
    _, class_id, code = _full_class(sm)
    student = add_user(sm)
    resp = _client(sm, student).post(f"/api/invites/{code}/redeem")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "no_free_seat"
    assert not _enrolled(sm, class_id, student)


def test_class_invite_redeem_answers_409_and_stays_unredeemed(sm: sessionmaker[Session]) -> None:
    teacher, class_id, _ = _full_class(sm)
    invite_code = f"C{uuid.uuid4().hex[:9].upper()}"
    with sm.begin() as session:
        session.add(
            Invite(code=invite_code, role=InviteRole.student, created_by=teacher, class_id=class_id)
        )
    student = add_user(sm)
    resp = _client(sm, student).post(f"/api/invites/{invite_code}/redeem")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "no_free_seat"
    with sm() as session:
        invite = session.scalars(select(Invite).where(Invite.code == invite_code)).one()
    assert invite.redeemed_by is None
    assert not _enrolled(sm, class_id, student)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_team_seat_claim_join.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'lemely.web.team_http'`.

- [ ] **Step 3: Create `lemely/web/team_http.py`**

```python
"""HTTP mapping for teacher-team errors (paymob billing Phase 03).

Bodies use the ``{"code", "message"}`` shape (``lemely.web.tutoring_http``). The
message is fixed copy, never ``str(exc)``, so no member id or teacher id is echoed.
"""

from __future__ import annotations

from typing import Final

from fastapi import HTTPException

from lemely.db.teacher_team_repo import (
    AssistantInviteLimitError,
    AssistantInviteNotFound,
    AssistantInviteRedeemed,
    InvalidCap,
    InvalidPermissions,
    InvalidScope,
    NoFreeSeat,
    TeamError,
    TeamMemberNotFound,
)

NO_FREE_SEAT_MESSAGE: Final = (
    "This teacher has no free student seats. Ask your teacher to add more seats, then try again."
)


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def no_free_seat_error() -> HTTPException:
    """Return the 409 a class join gets when the teacher has no free seat (spec §4.4)."""
    return _error(409, "no_free_seat", NO_FREE_SEAT_MESSAGE)


def team_error_to_http(exc: TeamError) -> HTTPException:
    """Map a :class:`TeamError` onto its HTTP status and fixed body."""
    if isinstance(exc, NoFreeSeat):
        return no_free_seat_error()
    if isinstance(exc, (TeamMemberNotFound, AssistantInviteNotFound)):
        return _error(404, "not_found", "Not found.")
    if isinstance(exc, InvalidScope):
        return _error(422, "invalid_scope", "Use known subjects and seat actions only.")
    if isinstance(exc, InvalidCap):
        return _error(422, "invalid_cap", "A cap must be zero or more.")
    if isinstance(exc, InvalidPermissions):
        return _error(422, "invalid_permissions", "Use known team permissions only.")
    if isinstance(exc, AssistantInviteRedeemed):
        return _error(409, "invite_already_redeemed", "This invite has already been used.")
    if isinstance(exc, AssistantInviteLimitError):
        return _error(409, "invite_limit", "You have too many open assistant invites.")
    return _error(409, "conflict", "That change is not possible right now.")


__all__ = ["NO_FREE_SEAT_MESSAGE", "no_free_seat_error", "team_error_to_http"]
```

- [ ] **Step 4: Hook the claim into `lemely/db/class_repo.py`**

Imports. Add to the existing imports:

```python
from datetime import UTC, datetime

from lemely.db.teacher_team_repo import NoFreeSeat, TeacherTeamService
from lemely.runtime.config import Settings
```

`lemely.db` may import `lemely.runtime` (only `lemely.runtime` is forbidden from importing the domain layers).

Replace `ClassService.__init__` with:

```python
    def __init__(
        self, sessionmaker: sessionmaker[Session], *, enforce_teacher_seats: bool | None = None
    ) -> None:
        """Wire the service to a session factory.

        Builds its own :class:`~lemely.db.parent_repo.ParentLinkService` on the
        same factory: the class-join notice reads a student's linked parents
        through that service (the single ``parent_child_links`` query), inside
        the enrolment's transaction.

        ``enforce_teacher_seats`` (paymob billing Phase 03, spec §4.4; index R5): when
        true, a student's join of a school-less class that finds no free teacher seat is
        refused with :class:`~lemely.db.teacher_team_repo.NoFreeSeat` and the enrolment
        rolls back. When false, the seat is still claimed if one is free, and otherwise
        the student is enrolled without one. ``None`` (the default) reads
        ``Settings().team.enforce_teacher_seats``, which is true unless
        ``LEMELY_TEAM__ENFORCE_TEACHER_SEATS`` turns it off (only ``tests/conftest.py``
        does). ``lemely.web.deps.get_class_service`` passes the loaded setting.
        """
        self._sessionmaker = sessionmaker
        self._parent_links = ParentLinkService(sessionmaker)
        if enforce_teacher_seats is None:
            enforce_teacher_seats = Settings().team.enforce_teacher_seats
        self._enforce_teacher_seats = enforce_teacher_seats
```

In `join_by_code_with_notice`, insert this between the `enrollment_id = …` statement and `tutor_join = None`:

```python
            if cls.school_id is None:
                self._claim_teacher_seat(session, cls, student_uuid)
```

In its docstring's `Raises:` add:

```text
            NoFreeSeat: ``enforce_teacher_seats`` is on, the class has no school, the
                caller is a student, and the teacher has no free seat. Nothing is
                written: the enrolment and any outbox rows roll back.
```

Add this method in the `# -- Internals` section, after `_queue_tutor_class_join`:

```python
    def _claim_teacher_seat(
        self, session: Session, cls: SchoolClass, student_uuid: uuid.UUID
    ) -> None:
        """Claim or extend the joining student's seat with the class teacher (spec §4.4).

        Only a ``student`` account takes a seat: a teacher redeeming a class code
        does not. Runs in a savepoint, so when not enforced a refused claim leaves the
        enrolment in place.
        """
        student = session.get(User, student_uuid)
        if student is None or student.role is not Role.student:
            return
        try:
            with session.begin_nested():
                TeacherTeamService(session).claim_seat_for_class_join(
                    student_user_id=student_uuid, class_id=cls.id, now=datetime.now(UTC)
                )
        except NoFreeSeat:
            if self._enforce_teacher_seats:
                raise
```

- [ ] **Step 5: Add the setting, the suite switch and the production wiring**

`lemely/runtime/config.py`, after `TutoringSettings`:

```python
class TeamSettings(BaseModel):
    """Teacher seats and assistants (paymob billing spec §2.2, §4.4).

    Overrides via ``lemely.toml`` under ``[team]`` or ``LEMELY_TEAM__*`` env vars.

    ``enforce_teacher_seats`` is true in every deployed environment: a student's join
    of a school-less class whose teacher has no free seat is refused (409
    ``no_free_seat``). ``tests/conftest.py`` sets it false for the suite, so class-join
    tests written before seats need no plan; the seat tests enforce explicitly. Not
    emitted to ``lemely.toml.example``: nobody setting Lemely up turns it off.
    """

    model_config = ConfigDict(extra="forbid")
    enforce_teacher_seats: bool = True
```

In `class Settings`, after `tutoring: TutoringSettings = TutoringSettings()` (and after Phase 04's `usage` line if present):

```python
    team: TeamSettings = TeamSettings()
```

`tests/conftest.py`, directly after the `_disable_dotenv_file` fixture (next to Phase 04's `_disable_usage_enforcement` if present):

```python
@pytest.fixture(scope="session", autouse=True)
def _disable_teacher_seat_enforcement() -> Iterator[None]:
    """Class joins in the suite need no teacher plan (paymob billing Phase 03, index R5).

    ``ClassService`` reads ``settings.team.enforce_teacher_seats``; with it off, a join
    with no free seat enrols without one. The seat tests build an enforcing
    ``ClassService(sm, enforce_teacher_seats=True)`` themselves.
    """
    patch = pytest.MonkeyPatch()
    patch.setenv("LEMELY_TEAM__ENFORCE_TEACHER_SEATS", "0")
    try:
        yield
    finally:
        patch.undo()
```

`lemely/web/deps.py`: replace the body of `get_class_service` and append to its docstring:

```python
    settings = get_settings()
    return ClassService(
        get_sessionmaker(settings),
        enforce_teacher_seats=settings.team.enforce_teacher_seats,
    )
```

Docstring sentence: "Teacher seats are enforced unless ``settings.team.enforce_teacher_seats`` is off (paymob billing Phase 03): a student's join of a school-less class with no free seat is a 409 ``no_free_seat``."

- [ ] **Step 6: Map `NoFreeSeat` in both join routes**

`lemely/web/routers/student.py`: add the imports and a new `except` clause in `student_join_class`, between `except JoinCodeError` and `except ValueError`.

```python
from lemely.db.teacher_team_repo import NoFreeSeat
from lemely.web.team_http import no_free_seat_error
```

```python
    except NoFreeSeat as exc:
        raise no_free_seat_error() from exc
```

Append to the route's docstring: "A teacher with no free seat refuses the join with a 409 ``no_free_seat`` (paymob billing Phase 03); nothing is enrolled."

`lemely/web/routers/invites.py`: add the same two imports and this clause in `redeem_invite`, after `except InviteNotFoundError`:

```python
    except NoFreeSeat as exc:
        raise no_free_seat_error() from exc
```

Append to the route's docstring: "**409 ``no_free_seat``** (paymob billing Phase 03): a class code whose teacher has no free seat; the invite stays unredeemed."

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_team_seat_claim_join.py tests/test_class_repo.py tests/test_invite_repo.py tests/test_web_invites.py tests/test_class_side_door.py tests/test_web_student.py -v`
Expected: all PASS. The existing suites still pass: under `tests/conftest.py`'s switch, `ClassService(sm)` does not enforce, and their teachers have no plan. Add `tests/test_settings_example_drift.py` to the command; it must still pass, because `[team]` is not emitted to the example file.

- [ ] **Step 8: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/web/team_http.py tests/test_team_seat_claim_join.py
git commit -S -m "feat(team): claim a teacher seat on class join; refuse with no_free_seat" -- lemely/db/class_repo.py lemely/runtime/config.py tests/conftest.py lemely/web/team_http.py lemely/web/deps.py lemely/web/routers/student.py lemely/web/routers/invites.py tests/test_team_seat_claim_join.py
```

---

### Task 6: `require_team_permission` and `TeamActor`

**Files:**
- Modify: `lemely/db/teacher_team_repo.py` (the permission check)
- Modify: `lemely/web/deps.py`
- Test: `tests/test_team_permission_dep.py`

**Interfaces:**
- Consumes:
  - Task 1: `TeamPermission`, `effective_permissions`
  - Task 3: `TeacherTeamStore`
  - Task 4: `TeacherTeamService.assistant_membership`
- Produces (`lemely/db/teacher_team_repo.py`). This is the one place the "may this assistant do `perm` for that lead" rule lives. `require_team_permission` uses it, and so does Phase 04's estimate route, so a viewer cannot get estimates against the lead's balance:
  - `TeacherTeamService.assistant_has_permission(assistant_user_id: UUID, lead_teacher_user_id: UUID, perm: TeamPermission) -> TeacherMember | None`
  - module function `assistant_has_permission(session: Session, assistant_user_id: UUID, lead_teacher_user_id: UUID, perm: TeamPermission) -> TeacherMember | None`, the same check for callers holding a `Session`
  - Both return the active assistant row when its effective permissions include `perm`, otherwise `None`. That covers no row, a removed row, a missing permission, and the lead themselves.
- Produces (`lemely/web/deps.py`):
  - `ACTING_TEACHER_HEADER: Final = "X-Lemely-Acting-Teacher"`
  - `TeamActor(actor_user_id: UUID, lead_teacher_user_id: UUID, member_id: UUID | None, auth: AuthContext)`, a frozen dataclass
  - `get_teacher_team_store() -> TeacherTeamStore`, a cached singleton that tests override
  - `get_assistant_redeem_limiter() -> SlidingWindowLimiter`: 10 attempts per user per 600 s, cached. Used in Task 7.
  - `require_team_permission(perm: TeamPermission, *roles: Role) -> Callable[..., TeamActor]`:
    - The inner dependency is named `_team_guard` and holds `perm` in its closure.
    - It depends on `require_role(*(roles or (Role.teacher,)))`.
    - On refusal it raises 403 `{"code": "team_permission_denied", "message": …}`.

- [ ] **Step 1: Write the failing tests `tests/test_team_permission_dep.py`**

```python
"""require_team_permission: who may act for which teacher, with what (spec §2.3, §7)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from lemely.core.team_permissions import TeamPermission
from lemely.db.models.enums import Role
from lemely.db.models.team import AssistantRole, TeacherMemberStatus
from lemely.db.teacher_team_repo import (
    TeacherTeamService,
    TeacherTeamStore,
    assistant_has_permission,
)
from lemely.web.deps import (
    ACTING_TEACHER_HEADER,
    AuthContext,
    TeamActor,
    get_auth_context,
    get_teacher_team_store,
    require_team_permission,
)
from tests.team_db import add_assistant, add_user, emptied_after, team_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

_VIEW = require_team_permission(TeamPermission.VIEW_RESULTS)
_MANAGE = require_team_permission(TeamPermission.MANAGE_CLASSES)
_STAFF_VIEW = require_team_permission(
    TeamPermission.VIEW_RESULTS, Role.teacher, Role.school_admin, Role.platform_admin
)


def _body(actor: TeamActor) -> dict[str, str | None]:
    return {
        "actor": str(actor.actor_user_id),
        "lead": str(actor.lead_teacher_user_id),
        "member": str(actor.member_id) if actor.member_id is not None else None,
        "authUser": actor.auth.user_id,
        "authRole": actor.auth.role,
    }


probe = FastAPI()


@probe.get("/view")
def view(actor: Annotated[TeamActor, Depends(_VIEW)]) -> dict[str, str | None]:
    return _body(actor)


@probe.get("/manage")
def manage(actor: Annotated[TeamActor, Depends(_MANAGE)]) -> dict[str, str | None]:
    return _body(actor)


@probe.get("/staff")
def staff(actor: Annotated[TeamActor, Depends(_STAFF_VIEW)]) -> dict[str, str | None]:
    return _body(actor)


@pytest.fixture(scope="module")
def team_db() -> Iterator[sessionmaker[Session]]:
    with team_database() as factory:
        yield factory


@pytest.fixture
def sm(team_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(team_db)


def _call(
    sm: sessionmaker[Session],
    path: str,
    *,
    caller: uuid.UUID,
    role: Role = Role.teacher,
    acting_for: str | None = None,
) -> tuple[int, dict[str, object]]:
    probe.dependency_overrides[get_teacher_team_store] = lambda: TeacherTeamStore(sm)
    probe.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(caller), role=role.value
    )
    headers = {ACTING_TEACHER_HEADER: acting_for} if acting_for is not None else {}
    try:
        resp = TestClient(probe).get(path, headers=headers)
    finally:
        probe.dependency_overrides.clear()
    return resp.status_code, resp.json()


def test_lead_without_header_acts_as_self(sm: sessionmaker[Session]) -> None:
    lead = add_user(sm, Role.teacher)
    status, body = _call(sm, "/manage", caller=lead)
    assert status == 200
    assert body == {
        "actor": str(lead),
        "lead": str(lead),
        "member": None,
        "authUser": str(lead),
        "authRole": "teacher",
    }


def test_header_naming_self_acts_as_self(sm: sessionmaker[Session]) -> None:
    lead = add_user(sm, Role.teacher)
    status, body = _call(sm, "/manage", caller=lead, acting_for=str(lead))
    assert status == 200
    assert body["member"] is None


def test_assistant_with_the_permission_acts_as_the_lead(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    member = add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.viewer)
    status, body = _call(sm, "/view", caller=helper, acting_for=str(lead))
    assert status == 200
    assert body == {
        "actor": str(helper),
        "lead": str(lead),
        "member": str(member),
        "authUser": str(lead),
        "authRole": "teacher",
    }


def test_assistant_without_the_permission_is_403(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.marker)
    status, body = _call(sm, "/manage", caller=helper, acting_for=str(lead))
    assert status == 403
    assert body["detail"]["code"] == "team_permission_denied"


def test_a_toggle_grants_beyond_the_preset(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_assistant(
        sm,
        teacher_id=lead,
        assistant_id=helper,
        role=AssistantRole.viewer,
        permissions={"manage_classes": True},
    )
    assert _call(sm, "/manage", caller=helper, acting_for=str(lead))[0] == 200


def test_a_toggle_revokes_from_the_preset(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_assistant(
        sm,
        teacher_id=lead,
        assistant_id=helper,
        role=AssistantRole.co_teacher,
        permissions={"manage_classes": False},
    )
    assert _call(sm, "/manage", caller=helper, acting_for=str(lead))[0] == 403


def test_a_removed_assistant_is_403(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_assistant(
        sm, teacher_id=lead, assistant_id=helper, status=TeacherMemberStatus.removed
    )
    assert _call(sm, "/view", caller=helper, acting_for=str(lead))[0] == 403


def test_a_stranger_teacher_is_403(sm: sessionmaker[Session]) -> None:
    lead, stranger = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    assert _call(sm, "/view", caller=stranger, acting_for=str(lead))[0] == 403


def test_assisting_one_teacher_gives_nothing_for_another(sm: sessionmaker[Session]) -> None:
    lead, other_lead, helper = (
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
    )
    add_assistant(sm, teacher_id=lead, assistant_id=helper)
    assert _call(sm, "/view", caller=helper, acting_for=str(other_lead))[0] == 403


def test_a_malformed_header_is_403(sm: sessionmaker[Session]) -> None:
    helper = add_user(sm, Role.teacher)
    assert _call(sm, "/view", caller=helper, acting_for="not-a-uuid")[0] == 403


def test_a_school_admin_may_not_act_for_a_teacher(sm: sessionmaker[Session]) -> None:
    lead, admin = add_user(sm, Role.teacher), add_user(sm, Role.school_admin)
    status, _ = _call(sm, "/staff", caller=admin, role=Role.school_admin, acting_for=str(lead))
    assert status == 403


def test_a_school_admin_without_header_keeps_their_own_role(sm: sessionmaker[Session]) -> None:
    admin = add_user(sm, Role.school_admin)
    status, body = _call(sm, "/staff", caller=admin, role=Role.school_admin)
    assert status == 200
    assert body["authRole"] == "school_admin"
    assert body["authUser"] == str(admin)


def test_the_role_guard_still_runs_first(sm: sessionmaker[Session]) -> None:
    student = add_user(sm, Role.student)
    assert _call(sm, "/view", caller=student, role=Role.student)[0] == 403


def test_assistant_has_permission_is_the_shared_rule(sm: sessionmaker[Session]) -> None:
    lead, viewer, marker, gone = (
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
    )
    viewer_row = add_assistant(sm, teacher_id=lead, assistant_id=viewer, role=AssistantRole.viewer)
    add_assistant(
        sm,
        teacher_id=lead,
        assistant_id=marker,
        role=AssistantRole.marker,
        permissions={"mark": False},
    )
    add_assistant(sm, teacher_id=lead, assistant_id=gone, status=TeacherMemberStatus.removed)
    with sm() as session:
        member = assistant_has_permission(session, viewer, lead, TeamPermission.VIEW_RESULTS)
        assert member is not None
        assert member.id == viewer_row
        # A viewer cannot mark: Phase 04's estimate route refuses on this.
        assert assistant_has_permission(session, viewer, lead, TeamPermission.MARK) is None
        assert assistant_has_permission(session, marker, lead, TeamPermission.MARK) is None
        assert assistant_has_permission(session, marker, lead, TeamPermission.REGRADE) is not None
        assert assistant_has_permission(session, gone, lead, TeamPermission.VIEW_RESULTS) is None
        assert assistant_has_permission(session, lead, lead, TeamPermission.VIEW_RESULTS) is None
        assert TeacherTeamService(session).assistant_has_permission(
            viewer, lead, TeamPermission.VIEW_USAGE
        ) is not None


def test_the_guard_carries_its_permission_and_role_guard() -> None:
    cells = dict(zip(_MANAGE.__code__.co_freevars, _MANAGE.__closure__ or (), strict=True))
    assert _MANAGE.__name__ == "_team_guard"
    assert cells["perm"].cell_contents is TeamPermission.MANAGE_CLASSES
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_team_permission_dep.py -v`
Expected: collection error `ImportError: cannot import name 'assistant_has_permission' from 'lemely.db.teacher_team_repo'` (or the same for `ACTING_TEACHER_HEADER` from `lemely.web.deps`).

- [ ] **Step 3: Implement in `lemely/web/deps.py`**

Imports. Merge into the existing import lines:

```python
from typing import TYPE_CHECKING, Annotated, Final

from fastapi import Depends, Header, HTTPException, status

from lemely.core.team_permissions import TeamPermission
from lemely.db.teacher_team_repo import TeacherTeamStore
```

`TeamPermission` appears only in the `require_team_permission` signature, which FastAPI never resolves. If ruff's `TC001` flags it, move it under `if TYPE_CHECKING:` in `deps.py`; nothing reads it at runtime.

First, in `lemely/db/teacher_team_repo.py`, add `TeamPermission` and `effective_permissions` to the `lemely.core.team_permissions` import. Then add this method to `TeacherTeamService`, right after `assistant_membership`:

```python
    def assistant_has_permission(
        self,
        assistant_user_id: uuid.UUID,
        lead_teacher_user_id: uuid.UUID,
        perm: TeamPermission,
    ) -> TeacherMember | None:
        """Return the active assistant row if it grants ``perm`` for that lead, else ``None``.

        The single rule behind ``require_team_permission`` and Phase 04's estimate route:
        the row's role preset with its toggles applied (spec §2.3) must include ``perm``.
        No row, a removed row, a missing permission, and the lead themselves are all
        ``None``.
        """
        if assistant_user_id == lead_teacher_user_id:
            return None
        member = self.assistant_membership(assistant_user_id, lead_teacher_user_id)
        if member is None or member.role_preset is None:
            return None
        granted = effective_permissions(member.role_preset, member.permissions or {})
        return member if perm in granted else None
```

And this module-level function, after the `TeacherTeamService` class:

```python
def assistant_has_permission(
    session: Session,
    assistant_user_id: uuid.UUID,
    lead_teacher_user_id: uuid.UUID,
    perm: TeamPermission,
) -> TeacherMember | None:
    """:meth:`TeacherTeamService.assistant_has_permission` for a caller holding a session."""
    return TeacherTeamService(session).assistant_has_permission(
        assistant_user_id, lead_teacher_user_id, perm
    )
```

Add `"assistant_has_permission",` to `__all__`.

Then, in `lemely/web/deps.py`, add next to the other cached providers, below `get_class_service`:

```python
@lru_cache(maxsize=1)
def get_teacher_team_store() -> TeacherTeamStore:
    """Return the process-wide :class:`TeacherTeamStore` (paymob billing Phase 03).

    One transaction per unit of team work, for the team router and the team guard.
    Tests override this dependency with a store built on a throwaway database.
    """
    return TeacherTeamStore(get_sessionmaker(get_settings()))


# Spec §7: invite redemption is rate-limited. 10 tries per user per 10 minutes is
# far above a real assistant typing one code, and far below guessing a 10-character
# code from a 32-letter alphabet.
_ASSISTANT_REDEEM_LIMIT = 10
_ASSISTANT_REDEEM_WINDOW_SECONDS = 600.0


@lru_cache(maxsize=1)
def get_assistant_redeem_limiter() -> SlidingWindowLimiter:
    """Return the per-user limiter on ``POST /api/teacher/team/assistants/redeem``."""
    return SlidingWindowLimiter(
        limit=_ASSISTANT_REDEEM_LIMIT,
        window_seconds=_ASSISTANT_REDEEM_WINDOW_SECONDS,
        clock=time.monotonic,
    )
```

Add after `require_verified_email`:

```python
ACTING_TEACHER_HEADER: Final = "X-Lemely-Acting-Teacher"
"""Request header naming the lead teacher an assistant acts for (paymob billing Phase 03)."""


@dataclass(frozen=True, slots=True)
class TeamActor:
    """Who is acting, and for which teacher (spec §2.3).

    ``actor_user_id`` is the caller. ``lead_teacher_user_id`` is the teacher whose
    resources the request touches: the caller themselves, or the lead teacher an
    active assistant acts for. ``member_id`` is that assistant's ``teacher_members``
    row (``None`` when acting as oneself); Phase 04 meters assistant usage by it.

    ``auth`` is what the handler passes to its services. For the caller acting as
    themselves it is their own :class:`AuthContext`. For an assistant it is an
    ``AuthContext`` for the lead teacher with role ``teacher``, so every existing
    ownership check (``classes.teacher_id == caller``, paper visibility, quiz
    ownership) applies unchanged to the lead teacher's resources.
    """

    actor_user_id: uuid.UUID
    lead_teacher_user_id: uuid.UUID
    member_id: uuid.UUID | None
    auth: AuthContext


def _team_permission_denied() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "team_permission_denied",
            "message": "You do not have permission to do this for that teacher.",
        },
    )


def require_team_permission(perm: TeamPermission, *roles: Role) -> Callable[..., TeamActor]:
    """Build a dependency resolving the acting teacher for a route an assistant may use.

    ``roles`` are the platform roles the route already allows (default: teacher). They
    are enforced first by :func:`require_role`, unchanged. Then:

    * no ``X-Lemely-Acting-Teacher`` header, or a header naming the caller: the caller
      acts as themselves;
    * a header naming another account: the caller must be a ``teacher`` with an
      active assistant row under that teacher whose effective permissions
      (:func:`~lemely.db.teacher_team_repo.assistant_has_permission`) include ``perm``.
      Anything else (malformed id, stranger, removed assistant, missing permission,
      non-teacher caller) is the same 403 ``team_permission_denied``.

    Billing, plan, seat, cap and assistant routes never use this dependency (spec
    §2.3, §7): they act only on the caller's own team.

    The inner function is named ``_team_guard``, not ``_guard``, so
    ``tests/test_authz_matrix_complete.py`` reads the wrapped :func:`require_role`
    closure for the role set, and ``tests/test_team_permission_adoption.py`` reads
    ``perm`` from this one.
    """
    role_guard = require_role(*(roles or (Role.teacher,)))

    def _team_guard(
        auth: Annotated[AuthContext, Depends(role_guard)],
        store: Annotated[TeacherTeamStore, Depends(get_teacher_team_store)],
        acting_teacher: Annotated[str | None, Header(alias=ACTING_TEACHER_HEADER)] = None,
    ) -> TeamActor:
        actor_id = uuid.UUID(auth.user_id)
        if acting_teacher is None:
            return TeamActor(
                actor_user_id=actor_id, lead_teacher_user_id=actor_id, member_id=None, auth=auth
            )
        try:
            lead_id = uuid.UUID(acting_teacher)
        except ValueError:
            raise _team_permission_denied() from None
        if lead_id == actor_id:
            return TeamActor(
                actor_user_id=actor_id, lead_teacher_user_id=actor_id, member_id=None, auth=auth
            )
        if auth.role != Role.teacher.value:
            raise _team_permission_denied()
        with store.transaction() as team:
            member = team.assistant_has_permission(actor_id, lead_id, perm)
            member_id = member.id if member is not None else None
        if member_id is None:
            raise _team_permission_denied()
        return TeamActor(
            actor_user_id=actor_id,
            lead_teacher_user_id=lead_id,
            member_id=member_id,
            auth=AuthContext(user_id=str(lead_id), role=Role.teacher.value),
        )

    return _team_guard
```

In `reset_singletons()`, add (after `get_invite_service.cache_clear()`):

```python
    # Paymob billing Phase 03: the teacher-team store and the assistant-redeem limiter.
    get_teacher_team_store.cache_clear()
    get_assistant_redeem_limiter.cache_clear()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_team_permission_dep.py tests/test_authz_matrix_complete.py tests/architecture/ -v`
Expected: all PASS. The authz matrix is unchanged because no route uses the guard yet.

- [ ] **Step 5: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add tests/test_team_permission_dep.py
git commit -S -m "feat(team): require_team_permission resolves the acting teacher" -- lemely/db/teacher_team_repo.py lemely/web/deps.py tests/test_team_permission_dep.py
```

---

### Task 7: Team router `/api/teacher/team` (lead-teacher only) and authz registration

**Files:**
- Modify: `lemely/db/teacher_team_repo.py` (usage reads: `month_start`, `cap_used`, `seat_meter_fraction`)
- Modify: `tests/team_db.py` (ledger seeding helpers)
- Create: `lemely/web/schemas_team.py`
- Create: `lemely/web/routers/teacher_team.py`
- Modify: `lemely/web/app.py`
- Modify: `tests/test_authz_matrix_complete.py`
- Test: `tests/test_teacher_team_usage.py`, `tests/test_web_teacher_team.py`

**Interfaces:**
- Consumes:
  - Tasks 3–4: every `TeacherTeamService` method
  - Task 5: `team_error_to_http`
  - Task 6: `get_teacher_team_store`, `get_assistant_redeem_limiter`
  - Task 1: `effective_permissions`
  - Phase 01: `UsageLedger.meter_fraction`, `UsageLedger.issue_grant` (tests), `HELD_KINDS`, `UsageEntry`, `UsageGrant`, `UsageGrantBalance`, `GrantKind`, `UsageEntryKind`
- Produces (`TeacherTeamService`):
  - `cap_used(member: TeacherMember, *, now: datetime) -> int`
  - `seat_meter_fraction(member: TeacherMember, *, now: datetime) -> float | None`
  - module `month_start(now) -> datetime`
- Produces the 13 routes below. All are `require_role(Role.teacher)` and act on `auth.user_id`'s own team. None reads `X-Lemely-Acting-Teacher`.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/teacher/team/seats` | — | `SeatListDTO` |
| GET | `/api/teacher/team/capacity` | — | `SeatCapacityDTO` |
| PUT | `/api/teacher/team/seats/{member_id}/scope` | `SetSeatScopeRequestDTO` | `SeatDTO` |
| DELETE | `/api/teacher/team/seats/{member_id}` | — | `SeatDTO` (status `leaving`) |
| PUT | `/api/teacher/team/members/{member_id}/cap` | `SetCapRequestDTO` | `SeatDTO` or `AssistantDTO` (the updated member; `kind` tells them apart) |
| GET | `/api/teacher/team/assistants` | — | `AssistantListDTO` |
| POST | `/api/teacher/team/assistants/invites` | `CreateAssistantInviteRequestDTO` | 201 `AssistantInviteDTO` |
| GET | `/api/teacher/team/invites` | — | `AssistantInviteListDTO` (live, unredeemed) |
| DELETE | `/api/teacher/team/invites/{invite_id}` | — | 204 (index R3: revoke an unredeemed assistant invite) |
| POST | `/api/teacher/team/assistants/redeem` | `RedeemAssistantInviteRequestDTO` | `MembershipDTO` |
| PATCH | `/api/teacher/team/assistants/{member_id}` | `UpdateAssistantRequestDTO` | `AssistantDTO` |
| DELETE | `/api/teacher/team/assistants/{member_id}` | — | 204 |
| GET | `/api/teacher/team/memberships` | — | `MembershipListDTO` |

- [ ] **Step 0a: Add ledger seeding helpers to `tests/team_db.py`**

Append to the imports of `tests/team_db.py`:

```python
from lemely.db.models.usage import GrantKind, UsageEntry, UsageEntryKind, UsageGrantBalance
from lemely.db.usage_ledger_repo import UsageLedger
```

Append these helpers:

```python
def add_grant(
    factory: sessionmaker[Session],
    *,
    owner_id: uuid.UUID,
    kind: GrantKind,
    units: int,
    at: datetime,
    teacher_member_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Issue a grant through Phase 01's ledger, usable from ``at - 60 days`` for a year."""
    with factory.begin() as session:
        grant = UsageLedger(session).issue_grant(
            owner_user_id=owner_id,
            kind=kind,
            units=units,
            idempotency_key=f"test:{uuid.uuid4()}",
            expires_at=at + timedelta(days=365),
            visible=kind in (GrantKind.credit_pack, GrantKind.auto_topup),
            effective_at=at - timedelta(days=60),
            teacher_member_id=teacher_member_id,
        )
        return grant.id


def add_entry(
    factory: sessionmaker[Session],
    *,
    grant_id: uuid.UUID,
    member_id: uuid.UUID | None,
    kind: UsageEntryKind,
    units: int,
    at: datetime,
) -> None:
    """Append one ledger line directly (settle lines are negative, hold lines positive)."""
    with factory.begin() as session:
        session.add(
            UsageEntry(
                grant_id=grant_id,
                teacher_member_id=member_id,
                kind=kind,
                units=units,
                event_at=at,
                idempotency_key=f"test:{uuid.uuid4()}",
            )
        )


def set_remaining(factory: sessionmaker[Session], grant_id: uuid.UUID, remaining: int) -> None:
    """Set a grant's cached balance (what ``UsageLedger.meter_fraction`` reads)."""
    with factory.begin() as session:
        session.execute(
            sa.update(UsageGrantBalance)
            .where(UsageGrantBalance.grant_id == grant_id)
            .values(remaining=remaining)
        )
```

Also change `from datetime import UTC, datetime` at the top of `tests/team_db.py` to `from datetime import UTC, datetime, timedelta`.

- [ ] **Step 0b: Write the failing usage-read tests `tests/test_teacher_team_usage.py`**

```python
"""Per-member usage for the team screens: cap use and seat meter (spec §2.2, §2.3, §5.6)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from lemely.db.models.enums import Role
from lemely.db.models.team import CapPeriod
from lemely.db.models.usage import GrantKind, UsageEntryKind
from lemely.db.teacher_team_repo import TeacherTeamService, month_start
from tests.team_db import (
    NOW,
    add_assistant,
    add_entry,
    add_grant,
    add_seat,
    add_user,
    emptied_after,
    set_remaining,
    team_database,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def team_db() -> Iterator[sessionmaker[Session]]:
    with team_database() as factory:
        yield factory


@pytest.fixture
def sm(team_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(team_db)


def _cap_used(sm: sessionmaker[Session], teacher: uuid.UUID, member_id: uuid.UUID) -> int:
    with sm() as session:
        team = TeacherTeamService(session)
        return team.cap_used(team.owned_member(teacher, member_id, kind=None), now=NOW)


def _meter(sm: sessionmaker[Session], teacher: uuid.UUID, member_id: uuid.UUID) -> float | None:
    with sm() as session:
        team = TeacherTeamService(session)
        return team.seat_meter_fraction(team.owned_member(teacher, member_id, kind=None), now=NOW)


def test_month_start_is_the_first_instant_of_the_month() -> None:
    assert month_start(NOW) == NOW.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def test_seat_cap_use_counts_teacher_draws_in_the_window_plus_open_holds(
    sm: sessionmaker[Session],
) -> None:
    teacher, student, other_student = add_user(sm, Role.teacher), add_user(sm), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    other_seat = add_seat(sm, teacher_id=teacher, student_id=other_student)
    credits = add_grant(sm, owner_id=teacher, kind=GrantKind.credit_pack, units=1000, at=NOW)
    allowance = add_grant(
        sm,
        owner_id=student,
        kind=GrantKind.seat_allowance,
        units=100,
        at=NOW,
        teacher_member_id=seat,
    )
    for kind, units, at, grant, member in (
        (UsageEntryKind.settle, -40, NOW, credits, seat),  # this month: counts
        (UsageEntryKind.settle, -25, NOW - timedelta(days=30), credits, seat),  # last month
        (UsageEntryKind.hold, 10, NOW, credits, seat),  # held then released: nets to 0
        (UsageEntryKind.release, -10, NOW, credits, seat),
        (UsageEntryKind.hold, 7, NOW, credits, seat),  # still open: counts
        (UsageEntryKind.settle, -100, NOW, credits, other_seat),  # another seat
        (UsageEntryKind.settle, -50, NOW, allowance, seat),  # the student's own grant
    ):
        add_entry(sm, grant_id=grant, member_id=member, kind=kind, units=units, at=at)
    assert _cap_used(sm, teacher, seat) == 47
    with sm.begin() as session:
        TeacherTeamService(session).set_cap(seat, cap_units=500, cap_period=CapPeriod.total)
    assert _cap_used(sm, teacher, seat) == 72  # "total" has no window


def test_assistant_cap_use_counts_draws_on_the_leads_balance(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    member = add_assistant(sm, teacher_id=lead, assistant_id=helper)
    credits = add_grant(sm, owner_id=lead, kind=GrantKind.credit_pack, units=1000, at=NOW)
    add_entry(
        sm, grant_id=credits, member_id=member, kind=UsageEntryKind.settle, units=-30, at=NOW
    )
    assert _cap_used(sm, lead, member) == 30


def test_no_usage_is_zero(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    assert _cap_used(sm, teacher, seat) == 0


def test_seat_meter_reads_the_seat_allowance(sm: sessionmaker[Session]) -> None:
    teacher, student, helper = add_user(sm, Role.teacher), add_user(sm), add_user(sm, Role.teacher)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    assistant = add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    assert _meter(sm, teacher, seat) is None  # no grant yet
    allowance = add_grant(
        sm,
        owner_id=student,
        kind=GrantKind.seat_allowance,
        units=100,
        at=NOW,
        teacher_member_id=seat,
    )
    set_remaining(sm, allowance, 70)
    assert _meter(sm, teacher, seat) == pytest.approx(0.3)
    assert _meter(sm, teacher, assistant) is None  # assistants have no allowance
```

- [ ] **Step 0c: Run the usage-read tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_teacher_team_usage.py -v`
Expected: collection error `ImportError: cannot import name 'month_start' from 'lemely.db.teacher_team_repo'`.

- [ ] **Step 0d: Add the usage reads to `lemely/db/teacher_team_repo.py`**

Add these imports (merge with the existing ones):

```python
from lemely.db.models.usage import UsageEntry, UsageEntryKind, UsageGrant
from lemely.db.usage_ledger_repo import HELD_KINDS, UsageLedger
```

Add next to `month_end`:

```python
def month_start(now: datetime) -> datetime:
    """Return the first instant of ``now``'s UTC month (a ``month`` cap's window start)."""
    current = now.astimezone(UTC)
    return datetime(current.year, current.month, 1, tzinfo=UTC)
```

Add this section inside `TeacherTeamService`, before `# -- Internals`:

```python
    # -- Usage reads (team screens) ------------------------------------------------------

    def cap_used(self, member: TeacherMember, *, now: datetime) -> int:
        """Units the member drew from the teacher's grants in its cap window, plus open holds.

        The same sum as Phase 01's ``UsageLedger._cap_used`` for the payer the chain
        builds from this row (owner = the teacher, ``teacher_member_id`` = this row,
        window = this UTC month for ``month``, none for ``total``): settled draws in the
        window, negated, plus the hold and release lines still netting to an open hold.
        A seat's own ``seat_allowance`` grants are owned by the student, so they never
        count against the cap.
        """
        base = (
            select(func.coalesce(func.sum(UsageEntry.units), 0))
            .join(UsageGrant, UsageGrant.id == UsageEntry.grant_id)
            .where(
                UsageGrant.owner_user_id == member.teacher_user_id,
                UsageEntry.teacher_member_id == member.id,
            )
        )
        settled = base.where(UsageEntry.kind == UsageEntryKind.settle)
        if member.cap_period is CapPeriod.month:
            settled = settled.where(UsageEntry.event_at >= month_start(now))
        held = base.where(UsageEntry.kind.in_(HELD_KINDS))
        return -int(self._session.scalar(settled) or 0) + int(self._session.scalar(held) or 0)

    def seat_meter_fraction(self, member: TeacherMember, *, now: datetime) -> float | None:
        """Share of the seat's current allowance used (``UsageLedger.meter_fraction``).

        ``None`` for an assistant, and for a seat with no current ``seat_allowance`` grant.
        """
        if member.kind is not TeacherMemberKind.student_seat:
            return None
        return UsageLedger(self._session).meter_fraction(
            member.member_user_id, teacher_member_id=member.id, now=now
        )
```

Add `"month_start",` to `__all__`.

- [ ] **Step 0e: Run the usage-read tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_teacher_team_usage.py tests/test_teacher_team_seats.py -v`
Expected: all PASS.

- [ ] **Step 1: Write the failing tests `tests/test_web_teacher_team.py`**

```python
"""HTTP tests for /api/teacher/team: lead-only management, IDOR, rate limit (§2.2, §2.3, §7)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from datetime import UTC, datetime

from lemely.db.models import Invite
from lemely.db.models.enums import Role
from lemely.db.models.team import AssistantRole, TeacherMemberStatus
from lemely.db.models.usage import GrantKind, UsageEntryKind
from lemely.db.teacher_team_repo import TeacherTeamService, TeacherTeamStore
from lemely.web.app import create_app
from lemely.web.deps import (
    ACTING_TEACHER_HEADER,
    AuthContext,
    get_assistant_redeem_limiter,
    get_auth_context,
    get_teacher_team_store,
)
from lemely.web.ratelimit import SlidingWindowLimiter
from tests.team_db import (
    add_assistant,
    add_entry,
    add_grant,
    add_seat,
    add_subject,
    add_teacher_plan,
    add_user,
    emptied_after,
    set_remaining,
    team_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

BASE = "/api/teacher/team"
# The router reads the real clock (month window, grant validity), so seed usage at it.
NOW_REAL = datetime.now(UTC)


@pytest.fixture(scope="module")
def team_db() -> Iterator[sessionmaker[Session]]:
    with team_database() as factory:
        yield factory


@pytest.fixture
def sm(team_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(team_db)


def client(
    sm: sessionmaker[Session],
    user: uuid.UUID,
    role: Role = Role.teacher,
    *,
    limiter: SlidingWindowLimiter | None = None,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_teacher_team_store] = lambda: TeacherTeamStore(sm)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(user), role=role.value
    )
    fresh = limiter or SlidingWindowLimiter(limit=1000, window_seconds=60.0, clock=lambda: 0.0)
    app.dependency_overrides[get_assistant_redeem_limiter] = lambda: fresh
    return TestClient(app)


# ── seats ─────────────────────────────────────────────────────────────────────


def test_list_seats_and_capacity(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    student = add_user(sm, display_name="Omar")
    add_teacher_plan(sm, teacher, included_seats=2, extra_seats=1)
    seat = add_seat(sm, teacher_id=teacher, student_id=student, subjects=["0580"])
    credits = add_grant(sm, owner_id=teacher, kind=GrantKind.credit_pack, units=1000, at=NOW_REAL)
    add_entry(
        sm, grant_id=credits, member_id=seat, kind=UsageEntryKind.settle, units=-40, at=NOW_REAL
    )
    allowance = add_grant(
        sm,
        owner_id=student,
        kind=GrantKind.seat_allowance,
        units=100,
        at=NOW_REAL,
        teacher_member_id=seat,
    )
    set_remaining(sm, allowance, 75)
    c = client(sm, teacher)
    seats = c.get(f"{BASE}/seats").json()["seats"]
    assert [(s["memberId"], s["studentName"], s["scopeSubjects"]) for s in seats] == [
        (str(seat), "Omar", ["0580"])
    ]
    assert seats[0]["kind"] == "student_seat"
    assert seats[0]["capUsedUnits"] == 40
    assert seats[0]["meterFraction"] == pytest.approx(0.25)
    assert seats[0]["joinedAt"] is not None
    assert "email" not in seats[0]
    assert c.get(f"{BASE}/capacity").json() == {"capacity": 3, "used": 1, "free": 2}


def test_set_scope_including_study_plan(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    add_subject(sm, "0580")
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    resp = client(sm, teacher).put(
        f"{BASE}/seats/{seat}/scope",
        json={"subjects": ["0580"], "actions": ["mark_paper", "study_plan"]},
    )
    assert resp.status_code == 200
    assert resp.json()["scopeActions"] == ["mark_paper", "study_plan"]


def test_set_scope_with_an_unknown_action_is_422(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    resp = client(sm, teacher).put(
        f"{BASE}/seats/{seat}/scope", json={"subjects": [], "actions": ["buy_seats"]}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "invalid_scope"


def test_remove_seat_sets_leaving(sm: sessionmaker[Session]) -> None:
    teacher, student = add_user(sm, Role.teacher), add_user(sm)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    resp = client(sm, teacher).delete(f"{BASE}/seats/{seat}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "leaving"
    assert resp.json()["leavesAt"] is not None


def test_set_cap_on_a_seat_and_an_assistant(sm: sessionmaker[Session]) -> None:
    teacher, student, helper = add_user(sm, Role.teacher), add_user(sm), add_user(sm, Role.teacher)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    assistant = add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    c = client(sm, teacher)
    for member, kind in ((seat, "student_seat"), (assistant, "assistant")):
        resp = c.put(f"{BASE}/members/{member}/cap", json={"capUnits": 250, "capPeriod": "total"})
        assert resp.status_code == 200
        body = resp.json()
        assert (body["kind"], body["memberId"]) == (kind, str(member))
        assert (body["capUnits"], body["capPeriod"], body["capUsedUnits"]) == (250, "total", 0)
    assert c.put(f"{BASE}/members/{seat}/cap", json={"capUnits": -1}).status_code == 422


# ── IDOR: another teacher's members are invisible ────────────────────────────


def test_another_teachers_members_are_404(sm: sessionmaker[Session]) -> None:
    owner, intruder = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    student, helper = add_user(sm), add_user(sm, Role.teacher)
    add_subject(sm, "0580")
    seat = add_seat(sm, teacher_id=owner, student_id=student)
    assistant = add_assistant(sm, teacher_id=owner, assistant_id=helper)
    c = client(sm, intruder)
    scope = {"subjects": ["0580"], "actions": ["mark_paper"]}
    assert c.put(f"{BASE}/seats/{seat}/scope", json=scope).status_code == 404
    assert c.delete(f"{BASE}/seats/{seat}").status_code == 404
    assert c.put(f"{BASE}/members/{seat}/cap", json={"capUnits": 1}).status_code == 404
    assert c.patch(f"{BASE}/assistants/{assistant}", json={"role": "viewer"}).status_code == 404
    assert c.delete(f"{BASE}/assistants/{assistant}").status_code == 404
    assert c.get(f"{BASE}/seats").json() == {"seats": []}
    assert c.get(f"{BASE}/assistants").json() == {"assistants": []}
    with sm() as session:
        member = TeacherTeamService(session).assistant_membership(helper, owner)
        assert member is not None
        assert member.role_preset is AssistantRole.co_teacher


def test_a_malformed_member_id_is_404(sm: sessionmaker[Session]) -> None:
    teacher = add_user(sm, Role.teacher)
    assert client(sm, teacher).delete(f"{BASE}/seats/not-a-uuid").status_code == 404


def test_seat_routes_do_not_accept_assistant_ids_and_vice_versa(sm: sessionmaker[Session]) -> None:
    teacher, student, helper = add_user(sm, Role.teacher), add_user(sm), add_user(sm, Role.teacher)
    seat = add_seat(sm, teacher_id=teacher, student_id=student)
    assistant = add_assistant(sm, teacher_id=teacher, assistant_id=helper)
    c = client(sm, teacher)
    assert c.delete(f"{BASE}/seats/{assistant}").status_code == 404
    assert c.delete(f"{BASE}/assistants/{seat}").status_code == 404


# ── assistants never reach seat or assistant management of their lead ────────


def test_an_assistant_cannot_manage_the_leads_team_even_with_the_header(
    sm: sessionmaker[Session],
) -> None:
    lead, helper, student = add_user(sm, Role.teacher), add_user(sm, Role.teacher), add_user(sm)
    add_teacher_plan(sm, lead, included_seats=3)
    seat = add_seat(sm, teacher_id=lead, student_id=student)
    add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.co_teacher)
    c = client(sm, helper)
    as_lead = {ACTING_TEACHER_HEADER: str(lead)}
    assert c.delete(f"{BASE}/seats/{seat}", headers=as_lead).status_code == 404
    assert c.get(f"{BASE}/seats", headers=as_lead).json() == {"seats": []}
    assert c.get(f"{BASE}/capacity", headers=as_lead).json()["capacity"] == 0
    invite = c.post(f"{BASE}/assistants/invites", json={"role": "co_teacher"}, headers=as_lead)
    assert invite.status_code == 201
    with sm() as session:
        # The invite is for the assistant's own team, never the lead's.
        assert set(session.scalars(select(Invite.team_teacher_id))) == {helper}
        seats = TeacherTeamService(session).list_seats(lead)
        assert [(s.id, s.status) for s in seats] == [(seat, TeacherMemberStatus.active)]


# ── invites and redemption ────────────────────────────────────────────────────


def test_invite_then_redeem_then_membership(sm: sessionmaker[Session]) -> None:
    lead = add_user(sm, Role.teacher, display_name="Ms Hoda")
    helper = add_user(sm, Role.teacher)
    invite = client(sm, lead).post(
        f"{BASE}/assistants/invites", json={"role": "marker", "expiresInDays": 3}
    )
    assert invite.status_code == 201
    code = invite.json()["code"]
    assert invite.json()["role"] == "marker"
    redeemed = client(sm, helper).post(f"{BASE}/assistants/redeem", json={"code": code})
    assert redeemed.status_code == 200
    assert redeemed.json()["teacherId"] == str(lead)
    assert redeemed.json()["teacherName"] == "Ms Hoda"
    assert redeemed.json()["effectivePermissions"] == ["mark", "regrade", "view_results"]
    memberships = client(sm, helper).get(f"{BASE}/memberships").json()["memberships"]
    assert [m["teacherId"] for m in memberships] == [str(lead)]
    assistants = client(sm, lead).get(f"{BASE}/assistants").json()["assistants"]
    assert [a["assistantId"] for a in assistants] == [str(helper)]


def test_list_and_revoke_invites(sm: sessionmaker[Session]) -> None:
    lead, intruder, helper = (
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
        add_user(sm, Role.teacher),
    )
    c = client(sm, lead)
    created = c.post(f"{BASE}/assistants/invites", json={"role": "viewer"}).json()
    listed = c.get(f"{BASE}/invites").json()["invites"]
    assert [(i["inviteId"], i["code"]) for i in listed] == [(created["inviteId"], created["code"])]
    invite_id = created["inviteId"]
    # IDOR: another teacher cannot see or revoke it.
    assert client(sm, intruder).get(f"{BASE}/invites").json() == {"invites": []}
    assert client(sm, intruder).delete(f"{BASE}/invites/{invite_id}").status_code == 404
    assert c.delete(f"{BASE}/invites/{invite_id}").status_code == 204
    assert c.get(f"{BASE}/invites").json() == {"invites": []}
    redeemed = client(sm, helper).post(
        f"{BASE}/assistants/redeem", json={"code": created["code"]}
    )
    assert redeemed.status_code == 404  # a revoked code is gone


def test_a_redeemed_or_malformed_invite_cannot_be_revoked(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    c = client(sm, lead)
    created = c.post(f"{BASE}/assistants/invites", json={"role": "viewer"}).json()
    client(sm, helper).post(f"{BASE}/assistants/redeem", json={"code": created["code"]})
    assert c.delete(f"{BASE}/invites/{created['inviteId']}").status_code == 404
    assert c.delete(f"{BASE}/invites/not-a-uuid").status_code == 404


def test_an_assistant_cannot_revoke_the_leads_invites(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.co_teacher)
    created = client(sm, lead).post(f"{BASE}/assistants/invites", json={"role": "viewer"}).json()
    resp = client(sm, helper).delete(
        f"{BASE}/invites/{created['inviteId']}", headers={ACTING_TEACHER_HEADER: str(lead)}
    )
    assert resp.status_code == 404
    assert len(client(sm, lead).get(f"{BASE}/invites").json()["invites"]) == 1


def test_redeem_requires_a_teacher_account(sm: sessionmaker[Session]) -> None:
    lead, student = add_user(sm, Role.teacher), add_user(sm)
    code = client(sm, lead).post(f"{BASE}/assistants/invites", json={"role": "viewer"}).json()[
        "code"
    ]
    resp = client(sm, student, Role.student).post(
        f"{BASE}/assistants/redeem", json={"code": code}
    )
    assert resp.status_code == 403


def test_redeem_of_an_unknown_or_used_code(sm: sessionmaker[Session]) -> None:
    lead, h1, h2 = add_user(sm, Role.teacher), add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    code = client(sm, lead).post(f"{BASE}/assistants/invites", json={"role": "viewer"}).json()[
        "code"
    ]
    assert client(sm, h1).post(f"{BASE}/assistants/redeem", json={"code": code}).status_code == 200
    used = client(sm, h2).post(f"{BASE}/assistants/redeem", json={"code": code})
    assert used.status_code == 409
    assert used.json()["detail"]["code"] == "invite_already_redeemed"
    unknown = client(sm, h2).post(f"{BASE}/assistants/redeem", json={"code": "NOSUCHCODE"})
    assert unknown.status_code == 404


def test_redeem_is_rate_limited(sm: sessionmaker[Session]) -> None:
    helper = add_user(sm, Role.teacher)
    limiter = SlidingWindowLimiter(limit=2, window_seconds=600.0, clock=lambda: 0.0)
    c = client(sm, helper, limiter=limiter)
    statuses = [
        c.post(f"{BASE}/assistants/redeem", json={"code": "NOSUCHCODE"}).status_code
        for _ in range(3)
    ]
    assert statuses == [404, 404, 429]


def test_update_assistant_role_and_toggles(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    member = add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.viewer)
    c = client(sm, lead)
    resp = c.patch(
        f"{BASE}/assistants/{member}",
        json={"role": "marker", "permissions": {"view_usage": True}},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "marker"
    assert resp.json()["permissions"] == {"view_usage": True}
    assert resp.json()["effectivePermissions"] == ["mark", "regrade", "view_results", "view_usage"]
    bad = c.patch(f"{BASE}/assistants/{member}", json={"permissions": {"billing": True}})
    assert bad.status_code == 422


def test_assistant_rows_carry_cap_use_and_no_email(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher, display_name="Sara")
    member = add_assistant(sm, teacher_id=lead, assistant_id=helper)
    credits = add_grant(sm, owner_id=lead, kind=GrantKind.credit_pack, units=1000, at=NOW_REAL)
    add_entry(
        sm, grant_id=credits, member_id=member, kind=UsageEntryKind.settle, units=-30, at=NOW_REAL
    )
    [row] = client(sm, lead).get(f"{BASE}/assistants").json()["assistants"]
    assert (row["kind"], row["assistantName"], row["capUsedUnits"]) == ("assistant", "Sara", 30)
    assert "email" not in row


def test_remove_assistant(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    member = add_assistant(sm, teacher_id=lead, assistant_id=helper)
    c = client(sm, lead)
    assert c.delete(f"{BASE}/assistants/{member}").status_code == 204
    assert c.get(f"{BASE}/assistants").json() == {"assistants": []}
    with sm() as session:
        assert TeacherTeamService(session).assistant_membership(helper, lead) is None


def test_removed_assistant_has_no_membership(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=lead, assistant_id=helper, status=TeacherMemberStatus.removed)
    assert client(sm, helper).get(f"{BASE}/memberships").json() == {"memberships": []}


@pytest.mark.parametrize("role", [Role.student, Role.parent, Role.school_admin, Role.platform_admin])
def test_only_teachers_reach_the_team_router(sm: sessionmaker[Session], role: Role) -> None:
    user = add_user(sm, role)
    assert client(sm, user, role).get(f"{BASE}/seats").status_code == 403
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_web_teacher_team.py -v`
Expected: every test FAILS with 404 responses (routes not mounted). For example `assert 404 == 200`, or `KeyError: 'seats'`.

- [ ] **Step 3: Write `lemely/web/schemas_team.py`**

```python
"""Wire DTOs for /api/teacher/team (paymob billing Phase 03, spec §2.2, §2.3).

Field names are camelCase on the wire, like every other ``schemas_*`` module. Names
shown to a teacher are ``users.display_name`` with a neutral fallback, never an email.
``kind`` lets a client tell a seat from an assistant where one route returns either
(``PUT /members/{id}/cap``).
"""

# Pydantic construction needs these type imports at runtime (see the per-file-ignore
# in pyproject.toml).
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AssistantRoleLiteral = Literal["co_teacher", "marker", "viewer"]
CapPeriodLiteral = Literal["month", "total"]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SeatDTO(ApiModel):
    kind: Literal["student_seat"]
    memberId: str
    studentId: str
    studentName: str
    status: Literal["active", "leaving"]
    leavesAt: datetime | None
    scopeSubjects: list[str]
    scopeActions: list[str]
    capUnits: int | None
    capPeriod: CapPeriodLiteral
    capUsedUnits: int
    """Units this seat drew from the teacher's credits in the current cap window (this
    month for ``month``, ever for ``total``), plus open holds (Phase 01 cap accounting)."""
    meterFraction: float | None
    """Share of this month's seat allowance used, 0..1; ``None`` before the first grant."""
    joinedAt: datetime


class SeatListDTO(ApiModel):
    seats: list[SeatDTO]


class SeatCapacityDTO(ApiModel):
    capacity: int
    used: int
    free: int


class SetSeatScopeRequestDTO(ApiModel):
    subjects: list[str] = Field(max_length=50)
    actions: list[str] = Field(max_length=20)


class SetCapRequestDTO(ApiModel):
    capUnits: int | None = None
    capPeriod: CapPeriodLiteral = "month"


class AssistantDTO(ApiModel):
    kind: Literal["assistant"]
    memberId: str
    assistantId: str
    assistantName: str
    role: AssistantRoleLiteral
    permissions: dict[str, bool]
    effectivePermissions: list[str]
    capUnits: int | None
    capPeriod: CapPeriodLiteral
    capUsedUnits: int
    """Units this assistant drew from the lead's balance in the current cap window, plus
    open holds (Phase 01 cap accounting)."""


class AssistantListDTO(ApiModel):
    assistants: list[AssistantDTO]


class CreateAssistantInviteRequestDTO(ApiModel):
    role: AssistantRoleLiteral
    expiresInDays: int = Field(default=7, ge=1, le=30)


class AssistantInviteDTO(ApiModel):
    inviteId: str
    code: str
    role: AssistantRoleLiteral
    expiresAt: datetime
    createdAt: datetime


class AssistantInviteListDTO(ApiModel):
    invites: list[AssistantInviteDTO]


class RedeemAssistantInviteRequestDTO(ApiModel):
    code: str = Field(min_length=1, max_length=32)


class UpdateAssistantRequestDTO(ApiModel):
    role: AssistantRoleLiteral | None = None
    permissions: dict[str, bool] | None = Field(default=None, max_length=20)


class MembershipDTO(ApiModel):
    memberId: str
    teacherId: str
    teacherName: str
    role: AssistantRoleLiteral
    effectivePermissions: list[str]


class MembershipListDTO(ApiModel):
    memberships: list[MembershipDTO]
```

Add the two new modules to `[tool.ruff.lint.per-file-ignores]` in `pyproject.toml`, next to the `invites` entries, as every router and schema module whose annotations FastAPI/pydantic resolve at runtime is:

```toml
"lemely/web/routers/teacher_team.py" = ["TC001", "TC002", "TC003"]
"lemely/web/schemas_team.py" = ["TC001", "TC002", "TC003"]
```

- [ ] **Step 4: Write `lemely/web/routers/teacher_team.py`**

```python
"""Teacher team routes: seats, scope, caps and assistants (spec §2.2, §2.3, §4.4, §7).

Every route is lead-teacher only. It acts on the caller's own team, keyed by
``auth.user_id``, and none reads ``X-Lemely-Acting-Teacher``. So an assistant can
never manage another teacher's seats, caps, invites or assistants: with or without the
header, an assistant reaches only their own team. Ids from the path are re-checked
against the caller (``owned_member``, ``revoke_assistant_invite``). An id the caller
does not own, an id of the wrong kind, a removed member and a malformed id all get the
same 404.

Names shown are ``users.display_name`` only, never an email (names-only privacy).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from lemely.core.team_permissions import effective_permissions
from lemely.db.models.enums import Role
from lemely.db.models.team import AssistantRole, CapPeriod, TeacherMemberKind
from lemely.db.teacher_team_repo import (
    AssistantInviteNotFound,
    TeacherTeamService,
    TeacherTeamStore,
    TeamError,
    TeamMemberNotFound,
)
from lemely.web.deps import (
    AuthContext,
    get_assistant_redeem_limiter,
    get_teacher_team_store,
    require_role,
)
from lemely.web.ratelimit import SlidingWindowLimiter
from lemely.web.schemas_team import (
    AssistantDTO,
    AssistantInviteDTO,
    AssistantInviteListDTO,
    AssistantListDTO,
    CreateAssistantInviteRequestDTO,
    MembershipDTO,
    MembershipListDTO,
    RedeemAssistantInviteRequestDTO,
    SeatCapacityDTO,
    SeatDTO,
    SeatListDTO,
    SetCapRequestDTO,
    SetSeatScopeRequestDTO,
    UpdateAssistantRequestDTO,
)
from lemely.web.team_http import team_error_to_http

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lemely.db.models import Invite
    from lemely.db.models.team import TeacherMember

router = APIRouter(prefix="/api/teacher/team")

LeadTeacher = Annotated[AuthContext, Depends(require_role(Role.teacher))]
Store = Annotated[TeacherTeamStore, Depends(get_teacher_team_store)]


def _member_uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise team_error_to_http(TeamMemberNotFound(raw)) from None


def _invite_uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise team_error_to_http(AssistantInviteNotFound(raw)) from None


def _sorted_permissions(member: TeacherMember) -> list[str]:
    if member.role_preset is None:
        return []
    granted = effective_permissions(member.role_preset, member.permissions or {})
    return sorted(permission.value for permission in granted)


def _seat_dtos(
    team: TeacherTeamService, seats: Sequence[TeacherMember], *, now: datetime
) -> list[SeatDTO]:
    names = team.display_names([s.member_user_id for s in seats])
    return [
        SeatDTO(
            kind="student_seat",
            memberId=str(seat.id),
            studentId=str(seat.member_user_id),
            studentName=names.get(seat.member_user_id) or "Student",
            status="leaving" if seat.status.value == "leaving" else "active",
            leavesAt=seat.leaves_at,
            scopeSubjects=list(seat.scope_subjects or []),
            scopeActions=list(seat.scope_actions or []),
            capUnits=seat.cap_units,
            capPeriod=seat.cap_period.value,
            capUsedUnits=team.cap_used(seat, now=now),
            meterFraction=team.seat_meter_fraction(seat, now=now),
            joinedAt=seat.created_at,
        )
        for seat in seats
    ]


def _assistant_dtos(
    team: TeacherTeamService, members: Sequence[TeacherMember], *, now: datetime
) -> list[AssistantDTO]:
    names = team.display_names([m.member_user_id for m in members])
    return [
        AssistantDTO(
            kind="assistant",
            memberId=str(member.id),
            assistantId=str(member.member_user_id),
            assistantName=names.get(member.member_user_id) or "Assistant",
            role=member.role_preset.value if member.role_preset is not None else "viewer",
            permissions=dict(member.permissions or {}),
            effectivePermissions=_sorted_permissions(member),
            capUnits=member.cap_units,
            capPeriod=member.cap_period.value,
            capUsedUnits=team.cap_used(member, now=now),
        )
        for member in members
    ]


def _membership_dto(team: TeacherTeamService, member: TeacherMember) -> MembershipDTO:
    names = team.display_names([member.teacher_user_id])
    return MembershipDTO(
        memberId=str(member.id),
        teacherId=str(member.teacher_user_id),
        teacherName=names.get(member.teacher_user_id) or "Teacher",
        role=member.role_preset.value if member.role_preset is not None else "viewer",
        effectivePermissions=_sorted_permissions(member),
    )


def _invite_dto(invite: Invite) -> AssistantInviteDTO:
    role = invite.assistant_role.value if invite.assistant_role is not None else "viewer"
    expires_at = invite.expires_at if invite.expires_at is not None else invite.created_at
    return AssistantInviteDTO(
        inviteId=str(invite.id),
        code=invite.code,
        role=role,
        expiresAt=expires_at,
        createdAt=invite.created_at,
    )


# ── seats ─────────────────────────────────────────────────────────────────────


@router.get("/seats", response_model=SeatListDTO)
def list_seats(auth: LeadTeacher, store: Store) -> SeatListDTO:
    """The caller's active and leaving seats, oldest first, with per-seat usage."""
    now = datetime.now(UTC)
    with store.transaction() as team:
        seats = team.list_seats(uuid.UUID(auth.user_id))
        return SeatListDTO(seats=_seat_dtos(team, seats, now=now))


@router.get("/capacity", response_model=SeatCapacityDTO)
def seat_capacity(auth: LeadTeacher, store: Store) -> SeatCapacityDTO:
    """Seats in the caller's live plan, seats held, and seats free."""
    teacher_id = uuid.UUID(auth.user_id)
    with store.transaction() as team:
        capacity = team.seat_capacity(teacher_id)
        used = team.seats_used(teacher_id)
    return SeatCapacityDTO(capacity=capacity, used=used, free=max(capacity - used, 0))


@router.put("/seats/{member_id}/scope", response_model=SeatDTO)
def set_seat_scope(
    member_id: str, body: SetSeatScopeRequestDTO, auth: LeadTeacher, store: Store
) -> SeatDTO:
    """Replace a seat's subjects and actions (``study_plan`` is opt-in, spec §2.2)."""
    member_uuid = _member_uuid(member_id)
    now = datetime.now(UTC)
    try:
        with store.transaction() as team:
            member = team.owned_member(
                uuid.UUID(auth.user_id), member_uuid, kind=TeacherMemberKind.student_seat
            )
            team.set_scope(member.id, subjects=body.subjects, actions=body.actions)
            return _seat_dtos(team, [member], now=now)[0]
    except TeamError as exc:
        raise team_error_to_http(exc) from exc


@router.delete("/seats/{member_id}", response_model=SeatDTO)
def remove_seat(member_id: str, auth: LeadTeacher, store: Store) -> SeatDTO:
    """Free a seat at the end of the current month (spec §2.2, §5.9)."""
    member_uuid = _member_uuid(member_id)
    now = datetime.now(UTC)
    try:
        with store.transaction() as team:
            member = team.owned_member(
                uuid.UUID(auth.user_id), member_uuid, kind=TeacherMemberKind.student_seat
            )
            team.request_removal(member.id, now=now)
            return _seat_dtos(team, [member], now=now)[0]
    except TeamError as exc:
        raise team_error_to_http(exc) from exc


@router.put("/members/{member_id}/cap", response_model=SeatDTO | AssistantDTO)
def set_member_cap(
    member_id: str, body: SetCapRequestDTO, auth: LeadTeacher, store: Store
) -> SeatDTO | AssistantDTO:
    """Set a seat's overflow cap or an assistant's spend cap; return the updated member.

    The body is a :class:`SeatDTO` for a seat and an :class:`AssistantDTO` for an
    assistant; ``kind`` tells them apart.
    """
    member_uuid = _member_uuid(member_id)
    now = datetime.now(UTC)
    try:
        with store.transaction() as team:
            member = team.owned_member(uuid.UUID(auth.user_id), member_uuid, kind=None)
            team.set_cap(member.id, cap_units=body.capUnits, cap_period=CapPeriod(body.capPeriod))
            if member.kind is TeacherMemberKind.student_seat:
                return _seat_dtos(team, [member], now=now)[0]
            return _assistant_dtos(team, [member], now=now)[0]
    except TeamError as exc:
        raise team_error_to_http(exc) from exc


# ── assistants and invites ────────────────────────────────────────────────────


@router.get("/assistants", response_model=AssistantListDTO)
def list_assistants(auth: LeadTeacher, store: Store) -> AssistantListDTO:
    """The caller's active assistants, oldest first, with per-assistant usage."""
    now = datetime.now(UTC)
    with store.transaction() as team:
        members = team.list_assistants(uuid.UUID(auth.user_id))
        return AssistantListDTO(assistants=_assistant_dtos(team, members, now=now))


@router.post("/assistants/invites", response_model=AssistantInviteDTO, status_code=201)
def create_assistant_invite(
    body: CreateAssistantInviteRequestDTO, auth: LeadTeacher, store: Store
) -> AssistantInviteDTO:
    """Mint a single-use assistant invite for the caller's team (spec §2.3, §4.4)."""
    expires_at = datetime.now(UTC) + timedelta(days=body.expiresInDays)
    try:
        with store.transaction() as team:
            invite = team.create_assistant_invite(
                uuid.UUID(auth.user_id), role=AssistantRole(body.role), expires_at=expires_at
            )
            return _invite_dto(invite)
    except TeamError as exc:
        raise team_error_to_http(exc) from exc


@router.get("/invites", response_model=AssistantInviteListDTO)
def list_assistant_invites(auth: LeadTeacher, store: Store) -> AssistantInviteListDTO:
    """The caller's live (unredeemed, unexpired) assistant invites, oldest first."""
    with store.transaction() as team:
        invites = team.list_assistant_invites(uuid.UUID(auth.user_id), now=datetime.now(UTC))
        return AssistantInviteListDTO(invites=[_invite_dto(i) for i in invites])


@router.delete("/invites/{invite_id}", status_code=204)
def revoke_assistant_invite(invite_id: str, auth: LeadTeacher, store: Store) -> Response:
    """Revoke one of the caller's unredeemed assistant invites (index R3).

    Another teacher's invite, a redeemed one, an unknown id and a malformed id all get
    the same 404.
    """
    invite_uuid = _invite_uuid(invite_id)
    try:
        with store.transaction() as team:
            team.revoke_assistant_invite(uuid.UUID(auth.user_id), invite_uuid)
    except TeamError as exc:
        raise team_error_to_http(exc) from exc
    return Response(status_code=204)


@router.post("/assistants/redeem", response_model=MembershipDTO)
def redeem_assistant_invite(
    body: RedeemAssistantInviteRequestDTO,
    auth: LeadTeacher,
    store: Store,
    limiter: Annotated[SlidingWindowLimiter, Depends(get_assistant_redeem_limiter)],
) -> MembershipDTO:
    """Join a teacher's team as an assistant with one's own teacher account (spec §2.3).

    Rate-limited per caller (spec §7): the 11th attempt in 10 minutes is a 429.
    """
    if not limiter.allow(auth.user_id):
        raise HTTPException(
            status_code=429,
            detail={"code": "rate_limited", "message": "Too many attempts. Try again later."},
            headers={"Retry-After": str(limiter.retry_after(auth.user_id))},
        )
    try:
        with store.transaction() as team:
            member = team.redeem_assistant_invite(
                code=body.code, user_id=uuid.UUID(auth.user_id), now=datetime.now(UTC)
            )
            return _membership_dto(team, member)
    except TeamError as exc:
        raise team_error_to_http(exc) from exc


@router.patch("/assistants/{member_id}", response_model=AssistantDTO)
def update_assistant(
    member_id: str, body: UpdateAssistantRequestDTO, auth: LeadTeacher, store: Store
) -> AssistantDTO:
    """Change an assistant's role preset and/or per-permission toggles."""
    member_uuid = _member_uuid(member_id)
    now = datetime.now(UTC)
    try:
        with store.transaction() as team:
            member = team.owned_member(
                uuid.UUID(auth.user_id), member_uuid, kind=TeacherMemberKind.assistant
            )
            updated = team.update_assistant(
                member.id,
                role=AssistantRole(body.role) if body.role is not None else None,
                permissions=body.permissions,
            )
            return _assistant_dtos(team, [updated], now=now)[0]
    except TeamError as exc:
        raise team_error_to_http(exc) from exc


@router.delete("/assistants/{member_id}", status_code=204)
def remove_assistant(member_id: str, auth: LeadTeacher, store: Store) -> Response:
    """Remove an assistant from the caller's team at once."""
    member_uuid = _member_uuid(member_id)
    try:
        with store.transaction() as team:
            member = team.owned_member(
                uuid.UUID(auth.user_id), member_uuid, kind=TeacherMemberKind.assistant
            )
            team.remove_assistant(member.id)
    except TeamError as exc:
        raise team_error_to_http(exc) from exc
    return Response(status_code=204)


@router.get("/memberships", response_model=MembershipListDTO)
def list_memberships(auth: LeadTeacher, store: Store) -> MembershipListDTO:
    """The teams the caller assists, with their effective permissions (for the UI's switcher)."""
    with store.transaction() as team:
        members = team.memberships_for_assistant(uuid.UUID(auth.user_id))
        return MembershipListDTO(memberships=[_membership_dto(team, m) for m in members])


__all__ = ["router"]
```

`SeatDTO.status` admits only `active`/`leaving`. Seat DTOs are only ever built for held seats: `owned_member` excludes removed rows, and `request_removal` leaves the row `leaving`.

- [ ] **Step 5: Mount the router in `lemely/web/app.py`**

Add `teacher_team,` to the `from lemely.web.routers import (...)` list (alphabetical). Add this line after `app.include_router(invites.router)`:

```python
    app.include_router(teacher_team.router)
```

- [ ] **Step 6: Register the routes in `tests/test_authz_matrix_complete.py`**

Insert after `("PATCH", "/api/classes/{class_id}"): TEACHER,`:

```python
    # Paymob billing Phase 03 (spec §2.2, §2.3, §7): the teacher-team router. Lead
    # teacher only, acting on the caller's own team; an assistant never reaches
    # another teacher's seats, caps or assistants through it (row-level proof:
    # tests/test_web_teacher_team.py). Redeeming an assistant invite needs a
    # teacher account, hence TEACHER on that route too.
    ("GET", "/api/teacher/team/seats"): TEACHER,
    ("GET", "/api/teacher/team/capacity"): TEACHER,
    ("PUT", "/api/teacher/team/seats/{member_id}/scope"): TEACHER,
    ("DELETE", "/api/teacher/team/seats/{member_id}"): TEACHER,
    ("PUT", "/api/teacher/team/members/{member_id}/cap"): TEACHER,
    ("GET", "/api/teacher/team/assistants"): TEACHER,
    ("POST", "/api/teacher/team/assistants/invites"): TEACHER,
    ("GET", "/api/teacher/team/invites"): TEACHER,
    ("DELETE", "/api/teacher/team/invites/{invite_id}"): TEACHER,
    ("POST", "/api/teacher/team/assistants/redeem"): TEACHER,
    ("PATCH", "/api/teacher/team/assistants/{member_id}"): TEACHER,
    ("DELETE", "/api/teacher/team/assistants/{member_id}"): TEACHER,
    ("GET", "/api/teacher/team/memberships"): TEACHER,
```

Raise the number in the `# ── TEACHER (N) ──` heading by 13 (from 24 to 37 if Phases 01–02 added no teacher route; otherwise add 13 to whatever it reads).

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_teacher_team_usage.py tests/test_web_teacher_team.py tests/test_authz_matrix_complete.py tests/test_authz_matrix.py tests/architecture/ -v`
Expected: all PASS. In the authz matrix, `test_every_route_is_declared`, `test_declared_guard_matches_the_wired_guard`, the 401/403 sweeps and `test_the_section_counts_in_this_file_match_what_it_registers` all pass.

- [ ] **Step 8: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add lemely/web/schemas_team.py lemely/web/routers/teacher_team.py tests/test_teacher_team_usage.py tests/test_web_teacher_team.py
git commit -S -m "feat(team): lead-teacher team router for seats, caps, invites and assistants" -- lemely/db/teacher_team_repo.py tests/team_db.py lemely/web/schemas_team.py lemely/web/routers/teacher_team.py lemely/web/app.py pyproject.toml tests/test_authz_matrix_complete.py tests/test_teacher_team_usage.py tests/test_web_teacher_team.py
```

---

### Task 8: Adopt team permissions in `classes.py` and `announcements.py`

**Files:**
- Modify: `lemely/web/routers/classes.py` (13 handlers)
- Modify: `lemely/web/routers/announcements.py` (3 handlers)
- Create: `tests/test_team_permission_adoption.py`
- Create: `tests/test_web_team_adoption.py`

**Interfaces:**
- Consumes (Task 6): `require_team_permission`, `TeamActor`.
- Produces: the 16 routes below accept an assistant acting for the lead through `X-Lemely-Acting-Teacher`, under the permission shown. Callers without the header behave exactly as before.

**The edit applied to every handler in this task (and Task 9).** Replace the handler's `auth` parameter line (whatever its current `Depends(...)`) with an `actor` parameter using the module constant from the table. Then make the handler body's first statement, right after the docstring, `auth = actor.auth`. Change nothing else in the body. Example, `get_roster` in `classes.py`:

Before:
```python
def get_roster(
    class_id: str,
    auth: Annotated[AuthContext, Depends(require_role(*_STAFF_ROLES))],
    service: Annotated[ClassService, Depends(get_class_service)],
) -> RosterDTO:
    """…existing docstring…"""
    try:
```

After:
```python
def get_roster(
    class_id: str,
    actor: Annotated[TeamActor, Depends(_TEAM_VIEW)],
    service: Annotated[ClassService, Depends(get_class_service)],
) -> RosterDTO:
    """…existing docstring…"""
    auth = actor.auth
    try:
```

- [ ] **Step 1: Write the failing registry test `tests/test_team_permission_adoption.py`**

```python
"""Which existing routes an assistant may use, and under which permission (spec §2.3, §3).

The registry below is the reviewed endpoint → permission map from the Phase 03 plan.
``test_adopted_routes_are_exactly_the_registry`` reads the permission actually wired
into each route (the ``perm`` cell of ``require_team_permission``'s ``_team_guard``)
and requires the two to be equal. A route that gains or loses the guard, or changes
its permission, fails here and must be changed twice, deliberately.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.core.team_permissions import TeamPermission
from lemely.web import create_app
from tests.test_authz_matrix_complete import _flatten, _walk

if TYPE_CHECKING:
    from fastapi.routing import APIRoute

VIEW = TeamPermission.VIEW_RESULTS
MARK = TeamPermission.MARK
REGRADE = TeamPermission.REGRADE
QUIZ = TeamPermission.GENERATE_QUIZ
CLASSES = TeamPermission.MANAGE_CLASSES
STUDENTS = TeamPermission.MANAGE_STUDENTS

ADOPTED: dict[tuple[str, str], TeamPermission] = {
    # classes.py
    ("GET", "/api/teacher/classes"): VIEW,
    ("GET", "/api/classes/{class_id}"): VIEW,
    ("GET", "/api/classes/{class_id}/analytics"): VIEW,
    ("POST", "/api/classes"): CLASSES,
    ("PATCH", "/api/classes/{class_id}"): CLASSES,
    ("DELETE", "/api/classes/{class_id}"): CLASSES,
    ("GET", "/api/classes/{class_id}/roster"): VIEW,
    ("POST", "/api/classes/{class_id}/enroll"): STUDENTS,
    ("DELETE", "/api/classes/{class_id}/students/{student_id}"): STUDENTS,
    ("GET", "/api/classes/{class_id}/papers"): VIEW,
    ("POST", "/api/classes/{class_id}/papers/{attempt_id}/unshare"): CLASSES,
    ("DELETE", "/api/classes/{class_id}/papers/{attempt_id}/unshare"): CLASSES,
    ("POST", "/api/school/classes/{class_id}/invite-code"): STUDENTS,
    # announcements.py
    ("GET", "/api/teacher/announcements"): VIEW,
    ("POST", "/api/teacher/announcements"): CLASSES,
    ("DELETE", "/api/teacher/announcements/{announcement_id}"): CLASSES,
}

LEAD_ONLY_PREFIXES = (
    "/api/teacher/team",
    "/api/tutor/",
    "/api/tutoring/",
    "/api/billing",
    "/billing",
    "/api/admin",
    "/webhooks",
)
"""Surfaces that must never take the team guard (spec §2.3, §7; tutoring is sub-project B)."""


def _team_permission(route: APIRoute) -> TeamPermission | None:
    found: TeamPermission | None = None
    for dependant in _walk(route.dependant):
        call = dependant.call
        if call is None or getattr(call, "__name__", "") != "_team_guard":
            continue
        cells = dict(zip(call.__code__.co_freevars, call.__closure__ or (), strict=True))
        permission = cells["perm"].cell_contents
        assert found in (None, permission), f"{route.path} carries two team permissions"
        found = permission
    return found


def _wired() -> dict[tuple[str, str], TeamPermission | None]:
    wired: dict[tuple[str, str], TeamPermission | None] = {}
    for route in _flatten(create_app()):
        permission = _team_permission(route)
        for method in sorted(route.methods or ()):
            wired[(method, route.path)] = permission
    return wired


def test_registry_names_only_real_routes() -> None:
    assert set(ADOPTED) <= set(_wired())


def test_adopted_routes_are_exactly_the_registry() -> None:
    adopted = {key: perm for key, perm in _wired().items() if perm is not None}
    assert adopted == ADOPTED


def test_lead_only_surfaces_never_take_the_team_guard() -> None:
    for (method, path), permission in _wired().items():
        if path.startswith(LEAD_ONLY_PREFIXES):
            assert permission is None, (method, path)
```

- [ ] **Step 2: Write the failing behaviour test `tests/test_web_team_adoption.py`**

```python
"""Assistants acting on the lead teacher's classes through adopted routes (spec §2.3, §7)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from lemely.db.class_repo import ClassService
from lemely.db.invite_repo import InviteService
from lemely.db.models import ClassEnrollment, Invite, SchoolClass
from lemely.db.models.enums import Role
from lemely.db.models.team import AssistantRole
from lemely.db.parent_repo import ParentLinkService
from lemely.db.teacher_team_repo import TeacherTeamStore
from lemely.web.app import create_app
from lemely.web.deps import (
    ACTING_TEACHER_HEADER,
    AuthContext,
    get_auth_context,
    get_class_service,
    get_invite_service,
    get_teacher_team_store,
)
from tests.team_db import (
    add_assistant,
    add_class,
    add_user,
    emptied_after,
    enrol,
    team_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI
    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def team_db() -> Iterator[sessionmaker[Session]]:
    with team_database() as factory:
        yield factory


@pytest.fixture
def sm(team_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(team_db)


def build_app(sm: sessionmaker[Session], user: uuid.UUID) -> FastAPI:
    app = create_app()
    classes = ClassService(sm)
    app.dependency_overrides[get_class_service] = lambda: classes
    app.dependency_overrides[get_invite_service] = lambda: InviteService(
        sm, classes, ParentLinkService(sm)
    )
    app.dependency_overrides[get_teacher_team_store] = lambda: TeacherTeamStore(sm)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(user), role=Role.teacher.value
    )
    return app


def as_user(sm: sessionmaker[Session], user: uuid.UUID) -> TestClient:
    return TestClient(build_app(sm, user))


def _class_exists(sm: sessionmaker[Session], class_id: uuid.UUID) -> bool:
    with sm() as session:
        return session.get(SchoolClass, class_id) is not None


def _enrolled(sm: sessionmaker[Session], class_id: uuid.UUID, student: uuid.UUID) -> bool:
    with sm() as session:
        count = session.scalar(
            select(func.count())
            .select_from(ClassEnrollment)
            .where(ClassEnrollment.class_id == class_id, ClassEnrollment.student_id == student)
        )
    return bool(count)


def _team(sm: sessionmaker[Session], role: AssistantRole) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A lead with one class (one student enrolled) and an assistant of ``role``."""
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    class_id, _ = add_class(sm, teacher_id=lead, subject_code="0580")
    enrol(sm, class_id, add_user(sm))
    add_assistant(sm, teacher_id=lead, assistant_id=helper, role=role)
    return lead, helper, class_id


def test_the_lead_without_header_is_unchanged(sm: sessionmaker[Session]) -> None:
    lead, _, class_id = _team(sm, AssistantRole.viewer)
    resp = as_user(sm, lead).get(f"/api/classes/{class_id}/roster")
    assert resp.status_code == 200
    assert len(resp.json()["students"]) == 1


def test_a_viewer_reads_the_leads_roster(sm: sessionmaker[Session]) -> None:
    lead, helper, class_id = _team(sm, AssistantRole.viewer)
    resp = as_user(sm, helper).get(
        f"/api/classes/{class_id}/roster", headers={ACTING_TEACHER_HEADER: str(lead)}
    )
    assert resp.status_code == 200
    assert len(resp.json()["students"]) == 1


def test_a_viewer_cannot_delete_the_leads_class(sm: sessionmaker[Session]) -> None:
    lead, helper, class_id = _team(sm, AssistantRole.viewer)
    resp = as_user(sm, helper).delete(
        f"/api/classes/{class_id}", headers={ACTING_TEACHER_HEADER: str(lead)}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "team_permission_denied"
    assert _class_exists(sm, class_id)


def test_a_co_teacher_deletes_the_leads_class(sm: sessionmaker[Session]) -> None:
    lead, helper, class_id = _team(sm, AssistantRole.co_teacher)
    resp = as_user(sm, helper).delete(
        f"/api/classes/{class_id}", headers={ACTING_TEACHER_HEADER: str(lead)}
    )
    assert resp.status_code == 204
    assert not _class_exists(sm, class_id)


def test_a_marker_cannot_remove_students(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    class_id, _ = add_class(sm, teacher_id=lead)
    student = add_user(sm)
    enrol(sm, class_id, student)
    add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.marker)
    resp = as_user(sm, helper).delete(
        f"/api/classes/{class_id}/students/{student}", headers={ACTING_TEACHER_HEADER: str(lead)}
    )
    assert resp.status_code == 403
    assert _enrolled(sm, class_id, student)


def test_a_co_teacher_mints_a_class_invite_as_the_lead(sm: sessionmaker[Session]) -> None:
    lead, helper, class_id = _team(sm, AssistantRole.co_teacher)
    resp = as_user(sm, helper).post(
        f"/api/school/classes/{class_id}/invite-code", headers={ACTING_TEACHER_HEADER: str(lead)}
    )
    assert resp.status_code == 200
    with sm() as session:
        invite = session.scalars(select(Invite).where(Invite.code == resp.json()["code"])).one()
    assert invite.created_by == lead


def test_a_stranger_with_the_header_is_403(sm: sessionmaker[Session]) -> None:
    lead, _, class_id = _team(sm, AssistantRole.co_teacher)
    stranger = add_user(sm, Role.teacher)
    resp = as_user(sm, stranger).get(
        f"/api/classes/{class_id}/roster", headers={ACTING_TEACHER_HEADER: str(lead)}
    )
    assert resp.status_code == 403


def test_an_assistant_without_header_cannot_touch_the_leads_class(
    sm: sessionmaker[Session],
) -> None:
    _, helper, class_id = _team(sm, AssistantRole.co_teacher)
    assert as_user(sm, helper).get(f"/api/classes/{class_id}/roster").status_code == 403


def test_the_header_reaches_only_the_leads_own_classes(sm: sessionmaker[Session]) -> None:
    lead, helper, _ = _team(sm, AssistantRole.co_teacher)
    other_teacher = add_user(sm, Role.teacher)
    other_class, _ = add_class(sm, teacher_id=other_teacher)
    resp = as_user(sm, helper).delete(
        f"/api/classes/{other_class}", headers={ACTING_TEACHER_HEADER: str(lead)}
    )
    assert resp.status_code == 403
    assert _class_exists(sm, other_class)
```

- [ ] **Step 3: Run both tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_team_permission_adoption.py tests/test_web_team_adoption.py -v`
Expected:
- `test_adopted_routes_are_exactly_the_registry` FAILS (left side `{}`).
- `test_registry_names_only_real_routes` and `test_lead_only_surfaces_never_take_the_team_guard` PASS.
- The assistant-with-header tests FAIL with 403 (the header is ignored, so the assistant acts as themselves and does not own the class). The no-header tests PASS.

- [ ] **Step 4: Adopt in `lemely/web/routers/classes.py`**

Imports. Add `from lemely.core.team_permissions import TeamPermission`, and add `TeamActor` and `require_team_permission` to the existing `from lemely.web.deps import (...)` list.

Add the constants directly below `router = APIRouter(prefix="/api", dependencies=[...])`:

```python
# Paymob billing Phase 03 (spec §2.3): routes an assistant may use for their lead
# teacher. Each passes the roles the route already allowed, so the wired role guard
# (tests/test_authz_matrix_complete.py) is unchanged.
_TEAM_VIEW = require_team_permission(TeamPermission.VIEW_RESULTS, *_STAFF_ROLES)
_TEAM_MANAGE_STUDENTS = require_team_permission(TeamPermission.MANAGE_STUDENTS, *_STAFF_ROLES)
_TEAM_MANAGE_CLASSES = require_team_permission(TeamPermission.MANAGE_CLASSES, Role.teacher)
_TEAM_VIEW_CLASS_PAPERS = require_team_permission(
    TeamPermission.VIEW_RESULTS, Role.teacher, Role.school_admin
)
_TEAM_SHARE_PAPERS = require_team_permission(
    TeamPermission.MANAGE_CLASSES, Role.teacher, Role.school_admin
)
_TEAM_MINT_INVITE = require_team_permission(
    TeamPermission.MANAGE_STUDENTS, Role.teacher, Role.school_admin
)
```

Apply the edit to each handler:

| Handler | Constant |
|---|---|
| `list_classes` | `_TEAM_VIEW` |
| `get_class` | `_TEAM_VIEW` |
| `class_analytics` | `_TEAM_VIEW` |
| `create_class` | `_TEAM_MANAGE_CLASSES` |
| `update_class` | `_TEAM_MANAGE_CLASSES` |
| `delete_class` | `_TEAM_MANAGE_CLASSES` |
| `get_roster` | `_TEAM_VIEW` |
| `enroll_student` | `_TEAM_MANAGE_STUDENTS` |
| `remove_student` | `_TEAM_MANAGE_STUDENTS` |
| `list_class_papers` | `_TEAM_VIEW_CLASS_PAPERS` |
| `unshare_paper` | `_TEAM_SHARE_PAPERS` |
| `reshare_paper` | `_TEAM_SHARE_PAPERS` |
| `mint_class_invite_code` | `_TEAM_MINT_INVITE` |

- [ ] **Step 5: Adopt in `lemely/web/routers/announcements.py`**

Same imports. Add below `router = APIRouter(...)` (this file's `_STAFF_ROLES` is `(Role.teacher, Role.school_admin)`):

```python
# Paymob billing Phase 03 (spec §2.3): an assistant may use these for their lead teacher.
_TEAM_VIEW = require_team_permission(TeamPermission.VIEW_RESULTS, *_STAFF_ROLES)
_TEAM_MANAGE_CLASSES = require_team_permission(TeamPermission.MANAGE_CLASSES, *_STAFF_ROLES)
```

| Handler | Constant |
|---|---|
| `list_announcements` | `_TEAM_VIEW` |
| `create_announcement` | `_TEAM_MANAGE_CLASSES` |
| `delete_announcement` | `_TEAM_MANAGE_CLASSES` |

If ruff then reports `AuthContext` (or any other import) unused in either file, delete that import.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_team_permission_adoption.py tests/test_web_team_adoption.py tests/test_authz_matrix_complete.py tests/test_web_classes.py tests/test_web_invites.py tests/test_class_unshare.py -v`
Expected: all PASS. The authz matrix's wired-guard check still reads the same role sets. The existing class suites pass because a caller without the header gets their own `auth` back.

If `tests/test_web_announcements*.py` exists, add it to the command (`ls tests | grep announcement`).

- [ ] **Step 7: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git add tests/test_team_permission_adoption.py tests/test_web_team_adoption.py
git commit -S -m "feat(team): assistants act on the lead's classes and announcements" -- lemely/web/routers/classes.py lemely/web/routers/announcements.py tests/test_team_permission_adoption.py tests/test_web_team_adoption.py
```

---

### Task 9: Adopt team permissions in `teacher.py`, `quiz.py` and `review.py`

**Files:**
- Modify: `lemely/web/routers/teacher.py` (17 handlers)
- Modify: `lemely/web/routers/quiz.py` (12 handlers)
- Modify: `lemely/web/routers/review.py` (6 handlers)
- Modify: `tests/test_team_permission_adoption.py` (registry)
- Modify: `tests/test_web_team_adoption.py` (behaviour)
- Modify: `tests/test_web_app.py` (`grading_queue` direct call)

**Interfaces:**
- Consumes (Task 6): `require_team_permission`, `TeamActor`.
- Consumes (Task 8): the registry and the `build_app`/`as_user` helpers.
- Produces: the 35 routes below accept an assistant acting for the lead.

- [ ] **Step 1: Extend the registry in `tests/test_team_permission_adoption.py`**

Add these entries to `ADOPTED`, after the announcements block:

```python
    # teacher.py
    ("POST", "/api/papers/upload"): MARK,
    ("GET", "/api/papers"): VIEW,
    ("POST", "/api/papers/{paper_id}/regrade"): REGRADE,
    ("GET", "/api/papers/deleted"): VIEW,
    ("DELETE", "/api/papers/{paper_id}"): CLASSES,
    ("POST", "/api/papers/{paper_id}/restore"): CLASSES,
    ("GET", "/api/papers/{paper_id}"): VIEW,
    ("GET", "/api/papers/{paper_id}/preview"): VIEW,
    ("GET", "/api/grading/queue"): VIEW,
    ("GET", "/api/quizzes/pools"): QUIZ,
    ("POST", "/api/quizzes/preview"): QUIZ,
    ("POST", "/api/quizzes/generate"): QUIZ,
    ("GET", "/api/teacher/overview"): VIEW,
    ("GET", "/api/teacher/students/{student_id}"): VIEW,
    ("GET", "/api/teacher/at-risk"): VIEW,
    ("POST", "/api/teacher/at-risk/{student_id}/acknowledge"): STUDENTS,
    ("DELETE", "/api/teacher/at-risk/{student_id}/acknowledge/{reason}"): STUDENTS,
    # quiz.py
    ("POST", "/api/teacher/quizzes"): QUIZ,
    ("GET", "/api/teacher/quizzes"): VIEW,
    ("GET", "/api/teacher/quizzes/pool-count"): VIEW,
    ("GET", "/api/teacher/quizzes/{quiz_id}"): VIEW,
    ("PATCH", "/api/teacher/quizzes/{quiz_id}"): QUIZ,
    ("POST", "/api/teacher/quizzes/{quiz_id}/status"): QUIZ,
    ("POST", "/api/teacher/quizzes/{quiz_id}/questions/generate"): QUIZ,
    ("DELETE", "/api/teacher/quizzes/{quiz_id}/questions/{question_ref}"): QUIZ,
    ("POST", "/api/teacher/quizzes/{quiz_id}/assignments"): QUIZ,
    ("GET", "/api/teacher/quizzes/{quiz_id}/assignments"): VIEW,
    ("DELETE", "/api/teacher/quizzes/{quiz_id}/assignments/{assignment_id}"): QUIZ,
    ("GET", "/api/teacher/quizzes/{quiz_id}/assignments/{assignment_id}/results"): VIEW,
    # review.py
    ("GET", "/api/teacher/review"): VIEW,
    ("GET", "/api/teacher/review/{item_id}"): VIEW,
    ("GET", "/api/teacher/review/{item_id}/crop"): VIEW,
    ("POST", "/api/teacher/review/bulk-approve"): MARK,
    ("POST", "/api/teacher/review/{item_id}/resolve"): MARK,
    ("POST", "/api/teacher/review/{item_id}/dismiss"): MARK,
```

Add a test that pins the three deliberately unadopted, caller-agnostic routes:

```python
def test_caller_agnostic_routes_stay_unadopted() -> None:
    wired = _wired()
    for key in (("GET", "/api/schemes"), ("POST", "/api/schemes"), ("GET", "/api/quizzes/topics")):
        assert wired[key] is None, key
```

- [ ] **Step 2: Add the behaviour tests to `tests/test_web_team_adoption.py`**

Append these imports to the module's import block (merge with the existing ones):

```python
from datetime import timedelta

from lemely.db.question_bank_repo import QuestionBankService
from lemely.db.quiz_repo import QuizService
from lemely.db.teacher_paper_repo import TeacherPaperRepository
from lemely.web.deps import get_quiz_service, get_teacher_paper_repo
from tests.team_db import add_subject
```

Append these tests:

```python
def _quiz_and_paper_app(sm: sessionmaker[Session], user: uuid.UUID) -> TestClient:
    app = build_app(sm, user)
    classes = ClassService(sm)
    app.dependency_overrides[get_quiz_service] = lambda: QuizService(
        sm, classes, QuestionBankService(sm)
    )
    app.dependency_overrides[get_teacher_paper_repo] = lambda: TeacherPaperRepository(
        sm, stale_after=timedelta(minutes=10)
    )
    return TestClient(app)


def test_a_viewer_lists_the_leads_quizzes(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_subject(sm, "0580")
    add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.viewer)
    QuizService(sm, ClassService(sm), QuestionBankService(sm)).create_quiz(lead, "0580", "Lead quiz")
    resp = _quiz_and_paper_app(sm, helper).get(
        "/api/teacher/quizzes", headers={ACTING_TEACHER_HEADER: str(lead)}
    )
    assert resp.status_code == 200
    assert [q["title"] for q in resp.json()["quizzes"]] == ["Lead quiz"]


def test_a_marker_cannot_create_quizzes_but_a_co_teacher_creates_them_as_the_lead(
    sm: sessionmaker[Session],
) -> None:
    lead, marker, co = add_user(sm, Role.teacher), add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_subject(sm, "0580")
    add_assistant(sm, teacher_id=lead, assistant_id=marker, role=AssistantRole.marker)
    add_assistant(sm, teacher_id=lead, assistant_id=co, role=AssistantRole.co_teacher)
    body = {"subjectCode": "0580", "title": "Made by an assistant"}
    as_lead = {ACTING_TEACHER_HEADER: str(lead)}
    denied = _quiz_and_paper_app(sm, marker).post("/api/teacher/quizzes", json=body, headers=as_lead)
    assert denied.status_code == 403
    created = _quiz_and_paper_app(sm, co).post("/api/teacher/quizzes", json=body, headers=as_lead)
    assert created.status_code == 201
    listed = _quiz_and_paper_app(sm, lead).get("/api/teacher/quizzes").json()["quizzes"]
    assert [q["title"] for q in listed] == ["Made by an assistant"]


def test_a_viewer_sees_the_leads_papers_but_cannot_regrade(sm: sessionmaker[Session]) -> None:
    lead, helper = add_user(sm, Role.teacher), add_user(sm, Role.teacher)
    add_assistant(sm, teacher_id=lead, assistant_id=helper, role=AssistantRole.viewer)
    paper_id = TeacherPaperRepository(sm, stale_after=timedelta(minutes=10)).create(
        paper_id=uuid.uuid4(),
        uploaded_by=lead,
        storage_path="papers/lead/scan.pdf",
        scheme_storage_path=None,
        original_filename="scan.pdf",
        content_type="application/pdf",
        byte_size=10,
    )
    client = _quiz_and_paper_app(sm, helper)
    as_lead = {ACTING_TEACHER_HEADER: str(lead)}
    listed = client.get("/api/papers", headers=as_lead)
    assert listed.status_code == 200
    assert [p["id"] for p in listed.json()["papers"]] == [str(paper_id)]
    assert client.get("/api/papers").json()["papers"] == []  # as themselves: nothing
    regrade = client.post(f"/api/papers/{paper_id}/regrade", headers=as_lead)
    assert regrade.status_code == 403
    assert regrade.json()["detail"]["code"] == "team_permission_denied"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_team_permission_adoption.py tests/test_web_team_adoption.py -v`
Expected:
- `test_adopted_routes_are_exactly_the_registry` FAILS: the 35 new registry entries are missing from the wired side.
- `test_a_viewer_lists_the_leads_quizzes` FAILS (empty list).
- The co-teacher create FAILS (the quiz is owned by the assistant, so the lead's list is empty).
- The papers test FAILS (empty list).
- The marker 403 and regrade 403 assertions may already pass or fail. Either is fine before adoption.

- [ ] **Step 4: Adopt in `lemely/web/routers/teacher.py`**

Imports. Add `from lemely.core.team_permissions import TeamPermission`; add `TeamActor` and `require_team_permission` to the `from lemely.web.deps import (...)` list.

Add these directly below `_STAFF_ROLES = (Role.teacher, Role.school_admin, Role.platform_admin)`:

```python
# Paymob billing Phase 03 (spec §2.3): routes an assistant may use for their lead
# teacher. All pass the router's STAFF triple, so the wired role guard is unchanged.
_TEAM_VIEW = require_team_permission(TeamPermission.VIEW_RESULTS, *_STAFF_ROLES)
_TEAM_MARK = require_team_permission(TeamPermission.MARK, *_STAFF_ROLES)
_TEAM_REGRADE = require_team_permission(TeamPermission.REGRADE, *_STAFF_ROLES)
_TEAM_QUIZ = require_team_permission(TeamPermission.GENERATE_QUIZ, *_STAFF_ROLES)
_TEAM_MANAGE_CLASSES = require_team_permission(TeamPermission.MANAGE_CLASSES, *_STAFF_ROLES)
_TEAM_MANAGE_STUDENTS = require_team_permission(TeamPermission.MANAGE_STUDENTS, *_STAFF_ROLES)
```

Apply the Task 8 edit. For the handlers whose `auth` currently uses `Depends(get_auth_context)` (the router-level guard is STAFF), the replacement is the same `actor: Annotated[TeamActor, Depends(<constant>)],` line.

| Handler | Constant |
|---|---|
| `upload_paper` (async) | `_TEAM_MARK` |
| `list_papers` | `_TEAM_VIEW` |
| `regrade_paper` | `_TEAM_REGRADE` |
| `list_deleted_papers` | `_TEAM_VIEW` |
| `delete_paper` | `_TEAM_MANAGE_CLASSES` |
| `restore_paper` | `_TEAM_MANAGE_CLASSES` |
| `get_paper` | `_TEAM_VIEW` |
| `get_paper_preview` | `_TEAM_VIEW` |
| `grading_queue` | `_TEAM_VIEW` |
| `quiz_pools` | `_TEAM_QUIZ` |
| `quiz_preview` | `_TEAM_QUIZ` |
| `quiz_generate` | `_TEAM_QUIZ` |
| `teacher_overview` | `_TEAM_VIEW` |
| `teacher_student_detail` | `_TEAM_VIEW` |
| `teacher_at_risk_list` | `_TEAM_VIEW` |
| `acknowledge_at_risk_flag` | `_TEAM_MANAGE_STUDENTS` |
| `unacknowledge_at_risk_flag` | `_TEAM_MANAGE_STUDENTS` |

Leave `list_schemes`, `upload_scheme` and `quiz_topics` untouched. They take no caller identity.

- [ ] **Step 5: Adopt in `lemely/web/routers/quiz.py`**

Same imports. Add below the `router = APIRouter(prefix="/api/teacher/quizzes", ...)` definition:

```python
# Paymob billing Phase 03 (spec §2.3): an assistant may use these for their lead teacher.
_TEAM_VIEW = require_team_permission(TeamPermission.VIEW_RESULTS, *_STAFF_ROLES)
_TEAM_QUIZ = require_team_permission(TeamPermission.GENERATE_QUIZ, *_STAFF_ROLES)
```

| Handler | Constant |
|---|---|
| `create_quiz` | `_TEAM_QUIZ` |
| `list_quizzes` | `_TEAM_VIEW` |
| `quiz_pool_count` | `_TEAM_VIEW` |
| `get_quiz` | `_TEAM_VIEW` |
| `patch_quiz_draft` | `_TEAM_QUIZ` |
| `set_quiz_status` | `_TEAM_QUIZ` |
| `generate_quiz_questions` | `_TEAM_QUIZ` |
| `remove_quiz_question` | `_TEAM_QUIZ` |
| `create_quiz_assignment` | `_TEAM_QUIZ` |
| `list_quiz_assignments` | `_TEAM_VIEW` |
| `delete_quiz_assignment` | `_TEAM_QUIZ` |
| `quiz_assignment_results` | `_TEAM_VIEW` |

Do not touch `student_router` handlers.

- [ ] **Step 6: Adopt in `lemely/web/routers/review.py`**

Same imports. Add below `router = APIRouter(...)`:

```python
# Paymob billing Phase 03 (spec §2.3): an assistant may use these for their lead teacher.
_TEAM_VIEW = require_team_permission(TeamPermission.VIEW_RESULTS, *_STAFF_ROLES)
_TEAM_MARK = require_team_permission(TeamPermission.MARK, *_STAFF_ROLES)
```

| Handler | Constant |
|---|---|
| `list_review_queue` | `_TEAM_VIEW` |
| `get_review_item` | `_TEAM_VIEW` |
| `get_review_item_crop` | `_TEAM_VIEW` |
| `bulk_approve_review_items` | `_TEAM_MARK` |
| `resolve_review_item` | `_TEAM_MARK` |
| `dismiss_review_item` | `_TEAM_MARK` |

`review.py` is not in the `TC001–TC003` per-file-ignores. `TeamActor` is imported together with `require_team_permission`, which is used at runtime by the module constants, so ruff keeps the import at runtime. Do not move it under `TYPE_CHECKING`: FastAPI resolves the annotation at runtime. Delete any import ruff reports unused (`AuthContext`, `get_auth_context`).

- [ ] **Step 7: Fix the direct handler call in `tests/test_web_app.py`**

Confirm the known caller and look for any other direct calls:

```bash
grep -rn "from lemely.web.routers.\(teacher\|quiz\|review\|classes\|announcements\) import" tests
```

Expected: the only adopted handler imported directly is `grading_queue` (`tests/test_web_app.py`, around line 529). The other hits import private helpers (`_average_for`, `_at_risk`, …), which this plan does not change. If a newer test imports another adopted handler, give it a `TeamActor` the same way.

In that test, change the import `from lemely.web.deps import AuthContext` to `from lemely.web.deps import AuthContext, TeamActor`. Replace the two lines around `grading_queue(auth, _FakeRepo())` with:

```python
    auth = AuthContext(user_id=str(uuid.uuid4()), role=Role.teacher.value)
    me = uuid.UUID(auth.user_id)
    actor = TeamActor(actor_user_id=me, lead_teacher_user_id=me, member_id=None, auth=auth)

    dto = grading_queue(actor, _FakeRepo())  # type: ignore[arg-type]
```

- [ ] **Step 8: Run the tests to verify they pass**

Run:
```bash
PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_team_permission_adoption.py tests/test_web_team_adoption.py tests/test_authz_matrix_complete.py tests/test_authz_matrix.py tests/test_web_app.py tests/test_web_teacher.py tests/test_web_review.py tests/test_web_quiz_origin_filtering.py tests/test_web_teacher_overview_fields.py -v
```
Then list the quiz router suites and run them too:
```bash
ls tests | grep -E "^test_web_quiz"
```
Expected: all PASS. Callers without the header get their own `auth` back, so every existing teacher-portal test is unchanged.

- [ ] **Step 9: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(team): assistants mark, regrade, build quizzes and review for the lead" -- lemely/web/routers/teacher.py lemely/web/routers/quiz.py lemely/web/routers/review.py tests/test_team_permission_adoption.py tests/test_web_team_adoption.py tests/test_web_app.py
```

---

### Task 10: Phase gate

**Files:** none created. This task proves the final tree.

**Interfaces:**
- Consumes: everything above.
- Produces: evidence that the phase is green on the final tree. This includes the knowledge graph refreshed per the project `CLAUDE.md`.

- [ ] **Step 1: Run every test file this phase touched, plus the source-scanning suites**

```bash
PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov \
  tests/test_metered_actions.py tests/test_team_permissions.py tests/test_team_schema.py \
  tests/test_migration_teacher_team.py tests/test_teacher_team_seats.py \
  tests/test_teacher_team_assistants.py tests/test_teacher_team_usage.py \
  tests/test_team_seat_claim_join.py \
  tests/test_team_permission_dep.py tests/test_web_teacher_team.py \
  tests/test_team_permission_adoption.py tests/test_web_team_adoption.py \
  tests/test_authz_matrix_complete.py tests/test_authz_matrix.py tests/test_web_app.py \
  tests/test_invite_repo.py tests/test_web_invites.py tests/test_class_repo.py \
  tests/test_web_classes.py tests/test_web_student.py tests/test_settings_example_drift.py \
  tests/architecture/ -v
```

Expected: all PASS, with no skips in the DB-backed team files. Postgres must be up. A skip here is not a pass.

- [ ] **Step 2: Prove the guards go red when broken (one mutation each, then revert)**

1. In `lemely/web/routers/classes.py`, change `_TEAM_MANAGE_CLASSES`'s permission to `TeamPermission.VIEW_RESULTS`. Run `pytest --no-cov tests/test_team_permission_adoption.py tests/test_web_team_adoption.py`. Expected: `test_adopted_routes_are_exactly_the_registry` and `test_a_viewer_cannot_delete_the_leads_class` FAIL. Revert with `git checkout -- lemely/web/routers/classes.py`.
2. In `lemely/db/teacher_team_repo.py`, delete `lock=True` from the `_capacity(teacher_id, lock=True)` call in `claim_seat_for_class_join`. Run `pytest --no-cov tests/test_teacher_team_seats.py::test_concurrent_claims_cannot_exceed_capacity`. Expected: FAIL (the second claim never queues, and `_wait_until_a_backend_waits_on_a_lock` fails). Revert with `git checkout -- lemely/db/teacher_team_repo.py`.
3. In `lemely/db/teacher_team_repo.py`, delete the line `TeacherMember.teacher_user_id == teacher_user_id,` from `owned_member`. Run `pytest --no-cov tests/test_web_teacher_team.py::test_another_teachers_members_are_404 tests/test_teacher_team_seats.py::test_owned_member_is_not_found_for_another_teacher`. Expected: both FAIL. Revert with `git checkout -- lemely/db/teacher_team_repo.py`.

Confirm `git status --short` shows a clean tree after the three reverts.

- [ ] **Step 3: Pre-commit on the final tree**

Run: `/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files`
Expected: every hook `Passed`. If a hook rewrites a file, commit that rewrite with `git commit -S -m "style(team): pre-commit fixes" -- <files>` and rerun until it passes with no changes.

- [ ] **Step 4: Refresh the knowledge graph**

Run: `graphify update .`
Expected: completes without error. If `graphify-out/` changed and is tracked, commit it: `git add graphify-out && git commit -S -m "chore(graph): refresh after teacher team" -- graphify-out`.

- [ ] **Step 5: Report handoff notes to the controller (no commit)**

Include these points in the final report:
- Phase 04 builds the seat chain from `TeacherTeamService.seats_for_student`, uses `TeamActor.member_id` and `assistant_membership` for assistant chains, and extends `MeteredAction` and `_SUBJECTLESS` in `lemely/core/metered_actions.py`.
- Phase 05 registers the sweeper job `seats.release_due` → `TeacherTeamService(session).release_due(now=now)`. It also calls `grant_seat_allowance_on_claim` right after `claim_seat_for_class_join` in `ClassService._claim_teacher_seat`; the claim's `now` argument exists for that.
- The downgrade check uses `seats_used`.
