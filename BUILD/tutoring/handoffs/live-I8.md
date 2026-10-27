# Live run I8 (T32): the five E2E journeys, the seed contract, the existing journeys and the smoke table

Tree at the run: `a468709f` (clean). Lock owner T32 (held by the lead; not released by T32).

```
===== live run summary =====
kind: e2e
mode: dedicated
database: lemely_tutoring_e2e
worktree: /home/sico/Code/Lemely/.claude/worktrees/tutoring-marketplace
lock owner: T32
run: e2e/tutoring-discover.spec.ts e2e/tutoring-onboard.spec.ts e2e/tutoring-revoke.spec.ts e2e/tutoring-parent.spec.ts e2e/tutoring-double-booking.spec.ts e2e/seed-contract.spec.ts e2e/student-journey.spec.ts e2e/teacher-journey.spec.ts e2e/parent-journey.spec.ts e2e/staff-inbox.spec.ts e2e/rbac.spec.ts e2e/tutoring-smoke.spec.ts
alembic_version before: 0043_merge_heads
alembic_version after: 0043_merge_heads
alembic_version verify: ok
result: FAIL (exit 1)
============================
```

Playwright totals for that run: **46 passed, 17 failed** (63 tests).

## Result by spec

| Spec | Result | Note |
|---|---|---|
| `tutoring-discover.spec.ts` (E2E 1) | 1 of 3 pass | student part passes; the tutor's accept and the later read fail on defect D1 |
| `tutoring-onboard.spec.ts` (E2E 2) | 0 of 7 pass | the first step is the tutor's own profile screen: D1 |
| `tutoring-revoke.spec.ts` (E2E 3) | fail | the tutor's first step: D1 |
| `tutoring-parent.spec.ts` (E2E 4) | 2 of 3 pass | parent booking, the child's S-36 and S-37 pass; "the booking shows for the tutor": D1 |
| `tutoring-double-booking.spec.ts` (E2E 5) | pass | exactly one of two requests holds the slot, by screen and by API |
| `seed-contract.spec.ts` | 6 of 6 pass | |
| `tutoring-smoke.spec.ts` | 4 rows fail, the rest pass | the four failing rows are the tutor account on T-15, T-19, T-18, T-20: D1 |
| `parent-journey`, `teacher-journey`, `rbac` | pass | |
| `student-journey` | fail | pre-existing, see D3 |
| `staff-inbox` | 1 fail ("parent inbox renders for a parent") | tutoring regression, see D2; passes alone (5 of 5) |

## Defects

- **D1 (BLOCKED-DEFECT, product).** A tutor is a teacher with no class. `TeacherLayout` sends every teacher with
  zero classes to `/teacher/first-class` (`teacherFirstClassRedirect`, `web/src/portals/teacher/index.tsx`), including
  on every `/teacher/tutoring/*` route, so a tutor cannot reach T-15..T-21. Evidence: `tutoring-smoke` rows for the tutor
  account read h1 "Create your first class" at `/teacher/tutoring`, `/students`, `/sessions/:id`, `/students/:id`.
  With that one guard bypassed in a scratch export (never committed), E2E 1 to 5 and all smoke rows pass.
- **D2 (regression, tutoring change vs an existing spec).** `staff-inbox.spec.ts` "parent inbox renders for a parent"
  asserts the inbox empty-state copy. After `parent-journey.spec.ts` (a) links a second parent to the child, the seeded
  parent's inbox holds "A parent was added" (`lemely/web/tutoring_notify.py`, `parent_link_notices`), so the copy is gone.
  On the merge-base with develop (`e80cb9fc`) the same three specs pass (8 of 8 for parent-journey and staff-inbox).
- **D3 (pre-existing, not tutoring).** `student-journey.spec.ts` expects the progressbar name "0625 mastery: 88%"; the
  Overview names it "Physics mastery: 88%" (`row.name`). Fails identically on `e80cb9fc` (the merge-base with develop).
- Observation: T-19 `/teacher/tutoring/students` for a teacher with classes and no tutor profile shows the C-11 error
  "You don't have a tutor profile yet." rather than an empty or onboarding state.
