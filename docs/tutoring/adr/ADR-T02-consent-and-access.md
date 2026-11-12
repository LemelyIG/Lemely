# ADR-T02: Student-issued data grants, an audit log the student can read, and the safeguarding posture

**Status:** Accepted (decisions locked by the user, 2026-10-25; rows 2+3a, 3b, 4, 4b, 10, 14, 15, 16 of `BUILD/tutoring/decision-log.md`). Several choices were made **against the architect's recommendation** and are recorded below as accepted risks.
**Date:** 2026-10-25 (rev 2 after `THREAT-MODEL.md` and `ADVERSARIAL-SPEC.md`)
**Deciders:** Product owner (user); architect

## Context

A tutor needs to see how a student is doing. Today only three parties see a
student's grades: the student, linked parents, and teachers whose class roster
holds the student (MISSION §3; UI spec §1.4 principle 3; `_visible_students`,
`lemely/web/routers/teacher.py:1890`). A tutor is none of these. Many students
are minors. Parents are read-only everywhere (UI spec §1.4 principle 5), and
`ParentChildLink` is child-issued (D-2026-09-08): **the child chooses who their
linked parents are and can remove a link at any time**
(`DELETE /api/student/parent-links/{parent_id}`, `lemely/web/routers/student.py:1375-1389`).

**Timers.** Rev 1 said "there is no scheduler". That was wrong: an in-process
sweeper runs every 60 s by default (`lemely/web/scheduled_notifications.py`,
started in `lemely/web/app.py:63-90`, `NotificationsSettings.sweeper_enabled = True`).
This ADR still evaluates every time-bound rule (grant validity, request expiry,
note windows) when it is read; the sweeper is used only to deliver queued
email (SPEC §b.4).

## Decision

### Grants
- A **grant** is a row in `tutor_data_grants (student_id, tutor_profile_id)`.
  **The student alone creates it, minors included** (row 2+3a), with a
  verified email. Parents cannot create, approve or revoke it (row 4).
- **Scope: all subjects, until revoked** (row 3b). `scope` has the single value
  `all_subjects_derived`; `expires_at` exists and is NULL in v1.
- **Derived analytics only, minimised.** The tutor sees the T-05 DTO
  (`StudentDetailDTO`) through a tutor projection (SPEC §e.2): timestamps
  truncated to the date, question ids removed, no acknowledgements. No scans,
  crops, answers, transcriptions, question routes or integrity signals. The
  student's explainer names everything that is shared, including target grades
  and at-risk warnings.
- **Validity is computed at read time** by `lemely.core.tutor_grants.grant_status`:
  valid iff not revoked, not expired, no active block between the two users,
  and the tutor's `listing_state` is `listed` or `pending_review` (paused is
  fine). A suspension or a close **revokes** every live grant in the same
  transaction (`revoke_reason = 'tutor_suspended'` / `'tutor_closed'`), and a
  reinstatement restores nothing; the student must grant again.
- **The gate is keyed on the caller's own profile** (`for_user(auth.user_id)`),
  never on another profile id. A tutor whose grant ended gets one generic code,
  `access_ended`; the reason (revoked, blocked, suspended) is shown only to the
  student.
- **Audit:** every tutor read of granted data writes one `tutor_access_audit`
  row in the validity-check transaction, before data loads; if the insert
  fails, the request fails. The student reads the full log (S11); **linked
  parents read the same grants and log, read-only** (PA6, PA7, P-08; row 16 i).
  Ids are random UUIDs and never exposed.

### Safeguarding posture
- **Parents are notified, never asked** (row 4), of each grant and each booking
  event (inbox and email), and of each **tutor-authored** note (inbox only, no
  text, at most once per booking per day). They read every booking, its notes
  thread, and the child's grants and access log. They cannot revoke.
- **The parent link is now watched** (row 14). Removing a link tells the
  removed parent once (inbox and email, fixed text, no reason); adding a link
  tells every parent already linked; every link and unlink is recorded in
  `parent_link_events`; a child can have at most 4 linked parents. After an
  unlink, that parent is told nothing more.
- **The class roster is not a second door** (row 14; ADR-T03). A block, a
  suspension and a close remove the student from the tutor's school-less
  classes; a student can leave a school-less class; linked parents are told
  when a student joins a school-less class run by someone who tutors; the
  student sees which class teachers can see their progress.
- **First-booking safety notice** (row 16 ii). A student must acknowledge a
  fixed notice (keep contact on Lemely, meet in public, tell an adult, report,
  block, Egypt's 16000 child helpline) before their first booking request and
  before their first note. The acknowledgement is stored server-side and
  enforced by the server, so it is shown once per student.
- **Booking-scoped notes thread** (row 4b): free text between the student and
  the tutor, readable by linked parents, reportable by anyone who can read it,
  immutable. Free text and meeting links are checked for contact details
  (phone numbers including Arabic-Indic digits, emails, links, handles; meeting
  links only from Google Meet, Zoom, Microsoft Teams, Whereby). Threads close 7
  days after the session, and sessions can be booked at most 28 days ahead.
  A `safety_concern` report from a party freezes the thread until an admin
  resolves it; safety reports go first in the admin queue and notify every
  platform admin. Platform admins read notes **only** through a report, and
  every such read is logged (`tutoring_admin_access`).
- **Parent books for the child** (row 10). Bookings store the subject
  (`student_id`) and the actor (`requested_by_user_id`, `requested_by_party`).
  The link is locked and re-checked inside every parent action. A parent
  cannot write a first note (it would be stored as the child's words).
- **Verified email** is required to book, grant, review, submit a tutor
  profile and read full tutor profiles; reporting and blocking stay open to
  everyone, because they are safety paths.

### Notifications and email
D5.9 §1 is binding: inbox rows and push are written **after** the change
commits, through `notify_safely`, and never fail the action. Email rows are
written to `email_outbox` **inside** the change's transaction, so a rolled-back
change sends nothing and a committed one is never silently dropped. The
existing sweeper sends each queued row once (no retry, row 12), only to
verified addresses, with a daily cap below the provider quota. Notification
text is fixed copy with names only; email never carries note text, links,
places or addresses. Push is payload-less (D5.10).

## Options Considered

### Who consents
| Option | Assessment |
|--------|------------|
| A. Parent approves for under-18s, self for 18+ (**recommended**) | Guardian in the loop; needs a date of birth Lemely does not hold |
| B. Student AND parent always | Strongest; blocks students without a linked parent |
| C. **Student alone, minors included (chosen by user)** | Simplest; no guardian gate |

### Scope and duration
| Option | Assessment |
|--------|------------|
| A. Per subject, 90 days (**recommended**) | Least exposure |
| B. Tied to booking lifetime | Hard to define for ongoing tutoring |
| C. **All subjects until revoked (chosen by user)** | Simplest; indefinite exposure |

### Messaging
| Option | Assessment |
|--------|------------|
| A. No messaging in v1 (**recommended**) | No adult-minor free-text surface |
| B. **Booking-scoped notes, parents can read, report + admin moderation (chosen by user)** | Useful logistics channel; reactive moderation plus contact-detail checks |

### Notification atomicity (architect's choice, rev 2)
| Option | Assessment |
|--------|------------|
| A. Inbox rows inside the change transaction via a new savepoint method (THREAT-MODEL SC-5) | Atomic; contradicts D5.9 §1 and adds a second `NotificationService.create` call site |
| B. **Outbox in transaction, inbox after commit via `notify_safely` (chosen)** | Honours D5.9; email durable; inbox loss only on a crash between commit and notify, and the parent's screens (P-05, P-08) hold the facts anyway |

### Access mechanism (architect's choice)
| Option | Assessment |
|--------|------------|
| A. Hidden per-tutor class with granted students enrolled | Conflates consent with rosters; rejected (ADR-T03) |
| B. **Grant table + sibling gate + audit (chosen)** | Explicit consent object; separate gate; audit natural |

## Trade-off Analysis

The user chose simplicity and reach over guardian control on three axes (who
consents, how long, messaging). Together they are the weakest point of the
design: a minor can, alone, give an adult indefinite access to all their
grades, book an in-person session, and exchange free text, while their parent
can only watch. Rows 14 and 16 make the watching harder to switch off and
easier to do; they do not give the parent a veto.

## Accepted risks and the compensating controls in force

| # | Accepted risk (user decision, argued against) | Compensating controls that ARE built |
|---|---|---|
| R1 | A minor consents alone to an adult reading their data (row 2+3a) | Listed (admin-approved) tutor; verified email; every linked parent notified of every grant and able to see the grants and every tutor read (P-08); the student sees every read; one-tap revoke, effective on the next read; a block revokes in the same transaction; a suspension or close revokes and reinstatement restores nothing. **Limit:** a student can remove a parent link first; that parent is told once, at the unlink, and nothing after (row 14) |
| R2 | Indefinite, all-subject exposure (row 3b) | Derived, minimised analytics only; audit log visible to the student and parents; `scope`/`expires_at` make a narrower model additive later |
| R3 | Guardian cannot stop a grant or an in-person booking (row 4) | Parents notified of grants, of every booking event and of tutor notes; parents read bookings, threads, grants and the access log; parents can report; the exact place is hidden until accept; the first-booking safety notice. **Limit:** the child chooses who the parents are (up to 4, each new one announced to the others) |
| R4 | Free text between an adult and a minor, moderated only on report (row 4b) | Booking-scoped threads that close 7 days after the session; 28-day booking horizon; contact-detail checks; parents can read and are told when the tutor writes; immutable notes; report, freeze, hide, cancel, suspend; blocks; admin reads logged. **Limit:** a determined adult can spell a number out in words |
| R5 | Parent write actions (row 10) | New routes only; existing parent routes keep their guards; the link is locked and re-checked on every action; a parent may cancel or complete only bookings they requested; no parent notes |

**Optional safeguards not adopted** (THREAT-MODEL §6 [U]; listed in SPEC §i.1): an
in-person request needing a linked parent with a verified email; a system
report when a grant or in-person booking follows an unlink within 14 days; a
logged admin read of every thread of a reported tutor.

**Principle conflicts to record.** UI spec §1.4 principle 3 ("Nobody else,
ever") and principle 5 ("Parents observe; they don't drive") are amended in
effect by rows 3b and 10. The UI spec text is updated in the Phase 4 docs
when the feature ships. MISSION §3 lists "their teachers"; a tutor holding a
valid grant is read here as one of the student's teachers by the student's own
choice. The user confirmed both readings on 2026-10-25 (decision-log row 19,
former SPEC O-11), so this ADR is not blocked.

## Consequences

- Easier: one consent object, one validity function, one audit table; revoke
  is one UPDATE.
- Harder: the tutor gate is a second authorization path to student data and
  must never union with the roster gate (ADR-T03). Every tutor read pays one
  INSERT. Two existing parent-link routes and two class-join routes gain side
  effects (SPEC §c.4), with no permission change.
- The audit table and `parent_link_events` grow without bound (no retention
  job in v1; a retention period is to be set in `docs/deployment.md`).
- Revisit when a date of birth exists: the recommended guardian gate becomes
  buildable.

## Action Items
1. [ ] Migrations `0046` (outbox, link events), `0047` (preferences incl. the safety-notice timestamp), `0049` (grants, audit) (SPEC §f).
2. [ ] `lemely/core/tutor_grants.py` and its SQL mirror with a parity test.
3. [ ] `lemely/web/student_detail_view.py` with the tutor projection and the route-level test (SPEC §e.2).
4. [ ] Fail-closed audit test: audit INSERT raises → 500, no body.
5. [ ] Row 14 changes to existing routes with their tests (SPEC §c.4).
6. [ ] P-08 and C-24 (row 16).
