# ADR-T03: Tutoring is a platform-wide marketplace; the grant is its only door to student data

**Status:** Accepted (follows from locked rows 1a, 2+3a, 5a, 10, 14)
**Date:** 2026-10-25 (rev 2 after `THREAT-MODEL.md` XT-1..XT-6)
**Deciders:** Product owner (user); architect

## Context

Lemely's existing tenancy is the class roster, not the school:
`SchoolClass.school_id` is nullable (D3.1), and a teacher reaches a student
only through `_visible_students` (`lemely/web/routers/teacher.py:1890`), the
union of rosters the caller may see. Any teacher can create a class with no
school (`POST /api/classes`, `lemely/web/routers/classes.py:592`), and a bare
`classes.join_code` enrols any student who enters it, without limit
(`InviteService.redeem`, `lemely/db/invite_repo.py:680-759`;
`ClassService.join_by_code`, `lemely/db/class_repo.py:456`). Direct enrolment
by a teacher needs a school seat (`enroll_by_seat`, `classes.py:683`), so a
school-less roster grows only by the student entering a code. `school_admin` scope is a school's
classes. `platform_admin` deliberately sees no classes (D1.6/D1.10: no
super-role bypass). Parents reach children through `ParentChildLink`.

MISSION §1 also names "tutoring centres" as buyers of seats. Those are
organisations and fit the existing `School` tenant. The marketplace in this
feature is individual tutors offering themselves to any student.

The design must stay multi-tenant-safe for all five roles and board-agnostic
(CAIE now, Edexcel and Oxford AQA later).

## Decision

1. **The marketplace has no tenant.** `tutor_profiles` has no `school_id`.
   Listings are platform-wide, gated only by `platform_admin` approval
   (row 5a). A tutoring centre remains a `School`; v1 does not link
   marketplace tutors to schools.
2. **Three disjoint gates to a student's analytics, never unioned:**
   | Gate | Who | Mechanism |
   |---|---|---|
   | Roster | teacher, school_admin | `_visible_students` (unchanged) |
   | Parent link | parent | `ParentChildLink` (unchanged) |
   | **Grant** | teacher holding a tutor profile | `tutor_data_grants` + `grant_status()` (new) |

   A tutor route never consults the roster; a teacher route never consults
   grants. A teacher with both a class and a tutor profile sees a class
   student through `/api/teacher/*` only, and a granted student through
   `/api/tutor/*` only.
   **The same person can still hold both gates (THREAT-MODEL XT-1).** "Never
   unioned" holds in code, but a tutor who meets a student through the
   marketplace can ask them to join a school-less class by code and then read
   the same T-05 data through the roster, with no grant, no audit row and no
   parent notice, and that access survived a block or a suspension in rev 1.
   Row 14 closes this without changing any permission (SPEC §c.4):
   - a block deletes the student's enrolments in every school-less class owned
     by the tutor's user; a suspension or a close deletes, from that tutor's
     school-less classes, the enrolments of every student who has a booking or
     a grant with them. School classes are never touched (a school's roster is
     the school's decision);
   - a student can leave a school-less class (`DELETE /api/student/classes/{class_id}`);
   - when a student joins a school-less class whose teacher holds a tutor
     profile, the student's linked parents are told;
   - the student's "Tutors & your data" screen lists every class teacher who
     can see their progress, and the revoke sheet says when the tutor also
     teaches one of the student's classes (computed for the student only).
   This is the one place tutoring code writes to class enrolments, and only
   by deleting a student's own enrolment in a school-less class.
3. **`school_admin` sees nothing of tutoring**, including tutoring by
   teachers of their own school. Tutoring is a private arrangement between a
   tutor and a student. Checked (XT-6): school-console grading never writes
   into a student's history (`grade_paper(..., student_id=None,
   history_store=None)`, `lemely/web/routers/teacher.py:614-625`), so school
   assessments do not reach a tutor through a grant.
4. **`platform_admin` moderates but never reads student analytics.** Admin
   routes return profiles, evidence, reviews, reports and (only through a
   report) notes. There is no admin path into `StudentDetailDTO`. Every admin
   view of a reported thread and every evidence download is recorded in
   `tutoring_admin_access` (SC-23).
5. **Board-agnostic by data, not code.** Subjects are FKs to `subjects.code`.
   Areas are codes from a versioned reference file with a `country_code`.
   The outcome grade ladder is passed into the core function per subject
   (ADR-T04). The tutor's zone is a column (`Africa/Cairo` default).

## Options Considered

### Option A: Each tutor is a `School` tenant with a hidden class
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low code, high conceptual cost |
| Cost | Reuses rosters and `_visible_students` |
| Scalability | Poor: every school-scoped view (seats, K-01..K-04, announcements) must learn to hide fake schools |
| Team familiarity | High |

**Pros:** no new gate.
**Cons:** conflates consent with enrolment; a roster entry cannot express "revoked", "audited", or "student-issued"; school dashboards would count tutoring students; `platform_admin` exclusions become special cases.

### Option B: Tutors belong to a school, marketplace per school
**Pros:** school_admin oversight.
**Cons:** contradicts row 1a (school-less pure tutors) and row 5a (platform-wide public directory).

### Option C: Tenant-free marketplace, grant as a sibling gate (chosen)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium: one new gate with its own tests |
| Cost | Additive tables |
| Scalability | Good: listing and access are independent of schools |
| Team familiarity | High (mirrors `_visible_students` shape) |

## Trade-off Analysis

Option C adds a second authorization path to student data, which is the risk
this ADR exists to contain. Containment is structural: the tutor gate lives in
one repository method (`TutorGrantRepository.require_valid_grant`), its SQL
predicate is pinned to the pure `grant_status()` by a parity test, and a
cross-gate test proves no union in either direction. Option A would have
avoided the second path by abusing rosters, and every school-scoped screen
would then carry a hidden exception.

## Consequences

- Easier: listing, booking and access do not depend on schools or seats.
- Harder: two separate tests per cross-gate rule; a tutor cannot reuse class
  analytics screens (T-04) because there is no class. Safeguarding actions
  (block, suspension, close) reach into school-less class enrolments, so
  `class_repo.py` gains two small methods and the class-join routes gain a
  parent notice (no permission change).
- Residual: a student can re-join a tutor's school-less class after a block,
  because row 14 adds no refusal to the join routes; their linked parents are
  told when it happens.
- Subscription/seat gating does not apply to tutoring in v1 (no prices, no
  payments, row 11). Decided at SPEC rev 3 (former O-15, SPEC §i.1): no
  tutoring route checks a subscription or an activation, for tutors, students
  or parents.
- Revisit if a tutoring centre wants its staff listed as one organisation.

## Action Items
1. [ ] `TutorGrantRepository.require_valid_grant(tutor_profile_id, student_id, now)` as the only tutor gate.
2. [ ] Cross-gate tests: class teacher without grant → `/api/tutor/students/{id}` 404; tutor with grant but no roster → `/api/teacher/students/{id}` 403 (existing behaviour, re-asserted).
3. [ ] Admin routes return no `StudentDetailDTO` field; asserted by a schema test over `schemas_tutoring_admin.py`.
4. [ ] Side-door tests (`tests/test_class_side_door.py`, SPEC §c.4): block/suspension/close remove only school-less enrolments; leave route; join notice.
