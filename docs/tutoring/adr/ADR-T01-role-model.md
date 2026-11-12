# ADR-T01: A tutor is a profile on a `teacher` account, not a new role

**Status:** Accepted (decisions locked by the user, 2026-10-25, `BUILD/tutoring/decision-log.md` rows 1a, 1b)
**Date:** 2026-10-25 (rev 2: citations corrected; suspension and close effects added)
**Deciders:** Product owner (user); architect

## Context

Lemely has exactly one platform role per account: `users.role` is a single
`Role` enum column (`lemely/db/models/users.py:36`, `lemely/db/models/enums.py:22`)
with five values (`student`, `parent`, `teacher`, `school_admin`,
`platform_admin`, MISSION §3). Every route names its roles through
`require_role(...)` (`lemely/web/deps.py:941`), and
`tests/test_authz_matrix_complete.py` freezes the guard of every route.

The marketplace needs people who tutor privately. Some of them already teach
at a school on Lemely; some only tutor. MISSION §1 says "a teacher can be
independent, belong to a school, or both", and `SchoolClass.school_id` is
already nullable for independent teachers (D3.1).

Forces:
- One account per person: a school teacher who also tutors must not need a
  second login.
- The class roster (`_visible_students`, `lemely/web/routers/teacher.py:1890`)
  and private tutoring must stay separate gates (see ADR-T03).
- Touching every `require_role` call, or adding a sixth enum value, is a large,
  cross-cutting change with a large authz-matrix diff.

## Decision

A tutor is a row in a new table `tutor_profiles`, 1:1 with a `users` row whose
role is `teacher` (`UNIQUE (user_id)`; the role check is enforced in the
service at profile creation, not by a DB trigger). No new `Role` value.

- Tutor-side routes live under `/api/tutor/*`, are guarded by
  `require_role(Role.teacher)`, and then require the caller to own a
  `tutor_profiles` row (resolved from `auth.user_id`, never from a path id).
  A teacher without a profile gets 404 on every `/api/tutor/*` route except
  `POST /api/tutor/profile`.
- Teacher self-service sign-up (issue #10) already creates a school-less
  teacher. A "pure tutor" is that account plus a tutor profile; no new sign-up
  route.
- Co-teaching (row 1b) is peer-only: a second teacher has their own profile,
  own bookings, own grants. There is no delegation table and no third adult
  who can read a student's data through someone else's grant.
- `school_admin` and `platform_admin` cannot hold a tutor profile.

## Options Considered

### Option A: New `tutor` role
| Dimension | Assessment |
|-----------|------------|
| Complexity | High: enum migration, every `require_role` reviewed, role switcher (C-12) needed for teacher-tutors |
| Cost | Large authz-matrix diff; a second account for anyone who both teaches and tutors |
| Scalability | Fine |
| Team familiarity | Medium |

**Pros:** guard alone says "tutor"; no object-level "has profile" check.
**Cons:** one role per account forces two accounts for a school teacher who tutors; duplicates identity, devices, notifications.

### Option B: Capability flag on `users` (`is_tutor boolean`)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low |
| Cost | Low |
| Scalability | Poor: every tutor attribute then needs its own column on `users` or a profile table anyway |
| Team familiarity | High |

**Pros:** trivial migration.
**Cons:** the profile, listing state, ratings and zone still need a table; the flag duplicates "profile row exists".

### Option C: `tutor_profiles` row on a teacher account (chosen)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low-medium: one table, one object-level check |
| Cost | Additive migration only |
| Scalability | Good: tutor attributes have a home |
| Team familiarity | High (same shape as `student_profiles`) |

**Pros:** one account; no enum change; tutor state lives with the tutor.
**Cons:** the authz matrix guard says `TEACHER`; the "is a tutor" half is an object-level rule the matrix cannot see and needs its own tests.

## Trade-off Analysis

Option C trades a coarser route guard for no change to the role model. The
gap is closed by one rule applied in one place (`TutorProfileRepository.for_user`
returns the caller's profile or raises a 404), and by DB-backed tests that a
teacher without a profile is refused on every tutor route. Option A would
have bought a sharper guard at the price of two accounts per teacher-tutor,
which contradicts MISSION §1's "independent, school, or both".

## Consequences

- Easier: one login; additive migration; existing teacher routes untouched.
- Harder: the authz matrix proves the role half only. The "owns a profile"
  half needs object-level tests (SPEC §c.3).
- A teacher who has classes and a tutor profile holds two independent gates
  (roster; grant). They never union in code (ADR-T03), but the same person can
  hold both; ADR-T03 and SPEC §c.4 cover how tutoring safeguards reach the
  tutor's school-less classes.
- **Suspending or closing a tutor profile does not disable the account**
  (THREAT-MODEL CB-8). No account-level switch exists: `users.is_active` is
  never read, and the role comes from the JWT (`get_auth_context`,
  `lemely/web/deps.py:884-938`). A suspension or close therefore revokes the
  tutor's grants, cancels future sessions and removes their tutoring students
  from the tutor's school-less classes in one transaction (SPEC §a.3); the
  teacher account itself keeps working for school classes. An account-level
  disable is out of scope.
- Tutor profiles are never deleted: `tutor_profiles.user_id` is
  `ON DELETE RESTRICT` and offboarding uses the `closed` listing state
  (`POST /api/admin/tutors/{tutor_id}/close`), so the safeguarding record
  survives (SPEC §a, SC-21).
- Revisit if a tutoring centre needs staff tutors under one organisation:
  that would be a delegation model and a new ADR.

## Action Items
1. [ ] Migration `0045_tutor_profiles` (SPEC §f).
2. [ ] `TutorProfileRepository.for_user(user_id)` as the single resolver for all `/api/tutor/*` handlers.
3. [ ] Object-level tests: teacher without profile → 404 on each tutor route; `school_admin`/`platform_admin` refused by guard (403).
