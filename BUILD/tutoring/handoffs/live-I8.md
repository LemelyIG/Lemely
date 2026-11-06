# Live run I8 (T32): the five E2E journeys, the seed contract, the existing journeys and the smoke table

Final run, tree `af46e47e` (clean). Lock owner T32 (held for the lead; not released by T32). Earlier run on `a468709f`
(46 passed, 17 failed: defects D1, D2, D3) is superseded by this one.

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

Playwright totals: **62 passed, 1 failed** (63 tests). The one failure is `student-journey.spec.ts` (D3, pre-existing).

| Spec | Result |
|---|---|
| `tutoring-discover` (E2E 1), `tutoring-onboard` (E2E 2), `tutoring-revoke` (E2E 3), `tutoring-parent` (E2E 4), `tutoring-double-booking` (E2E 5) | pass |
| `seed-contract`, `parent-journey`, `teacher-journey`, `staff-inbox`, `rbac`, `tutoring-smoke` (every row) | pass |
| `student-journey` | fails only on D3 |

## History of the defects
- D1 (product, tutor with no class redirected to first-class): fixed by the lead at `12553735`.
- D2 (not a product defect): SPEC §b.4 tells existing linked parents when another parent is added. `parent-journey` (a) redeemed
  `declining`'s code, which notified the seeded parent and filled the inbox `staff-inbox` asserts empty. Fixed in the seed:
  `students.inviteOnly` (own `parentInviteCode`, no linked parent); `parent-journey` (a) now redeems it. Mutation proof: with (a)
  pointed back at `declining`, `staff-inbox` "parent inbox renders for a parent" fails on "When your child may need support".
- D3 (pre-existing on the develop merge-base `e80cb9fc`, not ours): `student-journey` expects "0625 mastery: 88%", the screen says
  "Physics mastery: 88%". Left failing.
