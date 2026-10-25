# Tutoring marketplace — threat model (T-THREAT)

**Status:** Review input for SPEC sign-off · **Date:** 2026-10-25 · **Branch:** `feat/tutoring-marketplace`
**Reviewed:** `docs/tutoring/SPEC.md`, `docs/tutoring/adr/ADR-T01..T04`, `BUILD/tutoring/{decision-log,recon,design-summary}.md`.
**Method:** STRIDE per data-flow element, scored by severity × likelihood × blast radius. Code claims were checked with tokensave (index served from `develop`; the worktree is `develop` @ `314ef8ec`, so the cited files match) and direct reads. The marking pipeline was not read.
**Rules followed:** locked decisions are not re-argued. Each threat models a consequence of a locked row, then asks for the cheapest spec change that is compatible with it. A change that would alter a locked display or consent rule is tagged **[U]** (needs the user). Everything else is tagged **[A]** (compatible with the locked rows).

---

## 0. Verdict

**Risk level: HIGH.** The SPEC is careful about object-level authorization (O1–O17 are mostly right). The weak points are elsewhere:

1. **The safeguarding controls depend on "linked parents", and the child controls that link.** A student can silently delete a parent link and can choose who the "parent" is. Every compensating control in ADR-T02 R1–R4 is only as strong as that link.
2. **A second door to the same data sits outside the grant.** Any teacher, including a suspended or blocked tutor, can get a student to join a school-less class with a join code. That gives the full T-05 analytics with no audit, no parent notice and no way for the student to leave, and it survives a block or a suspension.
3. **Free-text fields and meeting links can carry contact details**, so a tutor can move a minor off the platform to a place with no oversight. Several of these fields are never moderated, even reactively.

The outcome figures add a fourth HIGH risk. The tutor knows who is in the cohort, holds grants for some of them and decides when bookings are marked completed. That lets them work out the grades of students who never shared their data.

**Must-fix SPEC changes before implementation: 27** (§5). 26 are compatible with the locked rows. One (SC-14) needs a user decision because it adds suppression rules to row 8's display rule.

---

## 1. Facts found in code that change the picture

| # | Fact | Evidence | Consequence |
|---|---|---|---|
| F1 | A student can hard-delete a parent link at any time. The parent is not told and no history is kept | `DELETE /api/student/parent-links/{parent_id}`, `lemely/web/routers/student.py:1377-1389`; `ParentLinkService.unlink`, `lemely/db/parent_repo.py:210-224` | "Linked parents are notified" (ADR-T02 R1/R3/R4) can be switched off by the child before granting or booking |
| F2 | Parent links come from child-issued invites. One reusable code never expires. Anyone holding it with a parent-role account (free, email unverified) becomes a parent. The cap counts only *unredeemed* single-use invites | `InviteService.mint_parent_invite`, `lemely/db/invite_repo.py:356-415`; `redeem`, `:680-759` | The child picks who the "parent" is, and there is no limit on how many parents redeem |
| F3 | Any teacher can create a class with no school. A bare `classes.join_code` can be used without limit. Joining enrols the student, and the roster then gates T-05. No student-side "leave class" route was found. Roster reads are not audited | `create_class`, `lemely/web/routers/classes.py:592-613`; `redeem` docstring `invite_repo.py:680-759`; `_visible_students`, `lemely/web/routers/teacher.py:1891-1912`; `teacher_student_detail`, `:2380` | A roster entry is a way into the same data that skips every grant control |
| F4 | No account-level disable exists: `users.is_active` is never read or written. The role comes from the JWT (`app_metadata.role`, 1 h TTL). A device session can be revoked | `lemely/db/models/users.py:42-64` docstring; `get_auth_context`, `lemely/web/deps.py:884-938`; `access_token_ttl_seconds`, `lemely/runtime/config.py:649` | "Suspend tutor" only touches the profile. The teacher account keeps working, including classes (F3) |
| F5 | `NotificationService.create` opens **its own** session and transaction | `lemely/db/notification_repo.py:292-376` | The SPEC §b.4 claim that inbox rows are "written in the same transaction as the state change" is false with the existing service |
| F6 | The email provider is the mock whenever `[email] api_key` is missing, and nothing says so. The real provider is Resend's JSON API. Links are joined to `app_base_url`. Templates are fixed and HTML-escaped | `_build_email_provider`, `lemely/web/deps.py:305-321`; `lemely/auth/email.py:147-198, 289-305, 330-371` | A production deploy without the secret delivers no parent emails |
| F7 | Email verification gates exactly one route, `POST /api/student/correct` | `lemely/db/models/users.py:43-58` | Student, parent and teacher accounts cost nothing and are unverified, so sock puppets are free |
| F8 | `StudentDetailDTO` carries `recordedAt` per attempt, `lastActiveAt`, `paperId` and `questionIds` | `lemely/web/schemas_analytics.py:132-193` | The tutor sees the minor's exact activity times. `paperId` is **not** an IDOR key: teacher paper routes allow only the uploader's own papers (`teacher_paper_visible`, `lemely/db/teacher_paper_repo.py:179-202`). Checked |
| F9 | In production the SPA is served by Workers Static Assets, and the worker runs only for `/api/*`. In nginx, `location /` uses `try_files … /index.html`, which redirects internally to `location = /index.html`, a block with its own `add_header` set | `web/wrangler.jsonc` (`run_worker_first: ["/api/*"]`); `web/worker/index.ts:1-6`; `web/nginx.conf:90-132` | The SPEC's O-8 plan ("nginx location block; web/worker") would not send `X-Robots-Tag` on `/tutors*` |
| F10 | Signed URLs default to a 3600 s TTL. `create_signed_url` has no content-disposition option | `lemely/runtime/config.py:1039`; `lemely/io/storage.py:57` | Evidence-file links stay valid for an hour as bearer URLs and open inline |
| F11 | The cooldown store lives in process memory, per worker | `lemely/auth/cooldown.py:17-27` | Confirms O-9. A COUNT over a domain table is still a valid DB-backed quota |
| F12 | The worker proxies `/api/*` with plain `fetch()` and no cache options | `web/worker/index.ts` | `Cache-Control: public, max-age=60` gives no edge load shielding unless a Cloudflare cache rule is added (verify). Each public request reaches Cloud Run and Postgres |
| F13 | The react-query cache persists to IndexedDB by allowlist, and `["notifications"]` is on the allowlist | `web/src/lib/offline/persistAllowlist.ts:20-28` | Notification titles and bodies stay on the device. The service worker never caches `/api` (`web/src/sw.ts:126-133`). Checked |

Dependency and secret checks: `npm audit --omit=dev` reports 2 high (`react-router` GHSA-qwww-vcr4-c8h2, RSC-mode CSRF). The app uses SPA mode, so this probably does not apply, but upgrade anyway. `pip-audit` is not installed, so the Python audit was not run. The design adds no Python packages, only the `btree_gist` extension. The secret scan of `docs/tutoring` and `BUILD/tutoring` found nothing.

---

## 2. Scope, assets, actors, trust boundaries

**Assets (most sensitive first):** a minor's physical safety (meeting place and time, contact routes); notes between an adult and a minor; a minor's derived grades and activity; grades of cohort members who did not consent; parent contact addresses; tutor evidence documents (names, possibly ID numbers); tutor identity on the open web; review integrity; booking integrity.

**Adversaries:** (A1) a predatory adult who passes admin approval as a tutor. (A2) a dishonest tutor (inflates ratings, suppresses reviews, retaliates, is curious about grades). (A3) a rival tutor (calendar griefing, review bombing). (A4) a fake "parent", meaning a friend or groomer the child linked. (A5) a scraper or anonymous web user. (A6) a curious logged-in student or parent. (A7) a careless platform admin, as an insider risk.

**Trust boundaries and data flows (DFD elements):**

```
 Web (anon) ──TB1──► /api/public/tutors*  ─────────────► tutor_profiles (PUBLIC cols)
 Student ─────TB2──► /api/student/*, /api/tutors*, POST /api/bookings ─► bookings, notes, grants, audit, prefs
 Parent ──────TB2──► /api/parent/children/{id}/*  (ParentChildLink gate, child-controlled: F1/F2)
 Tutor(teacher)TB2─► /api/tutor/*  (profile gate) ──grant gate──► history_store (T-05 DTO)
        └──────────► /api/teacher/*, /api/classes (roster gate, F3) ─────► history_store (T-05 DTO)   ◄─ side door
 Admin ───────TB3──► /api/admin/tutor*, reports (A10 = only path to notes)
 Backend ─────TB4──► email_outbox ─► Resend (or mock, F6);  inbox ─► push (off-platform payload)
 Backend ─────TB5──► GCS private bucket (evidence; signed URLs)
```

STRIDE was applied to each element: external entities (S, R), processes (S, T, R, I, D, E), stores (T, R, I, D), flows (T, I, D). The findings below are grouped by the nine areas in the brief. IDs use prefixes (`ID-`, `CB-`, `XT-`, `RF-`, `PP-`, `CS-`, `OS-`, `EM-`, `BK-`) so they do not collide with the SPEC's `O1–O17` and `O-1–O-19`.

---

## 3. Threats

Format: **Attack** · **Preconditions** · **Impact** · **Existing defence** · **GAP** · **Fix** (→ spec change in §5).

### 3.1 IDOR on student data

**ID-1 · Another tutor's grant authorises the read (T20).**
Attack: tutor B calls `GET /api/tutor/students/{id}` for a student who granted tutor A. B knows the id from a booking with that student. Impact: full T-05 data. Defence: O2 `require_valid_grant(tutor_profile_id, student_id, now)`. GAP: no test pins the lookup to the *caller's* profile. A query such as "has any live grant for this student" is the classic mistake, and the 403-with-reason path makes it worse (B would get `grant_revoked` for A's grant). Fix: the repository signature takes only the profile from `for_user(auth.user_id)`, and a negative test proves it → SC-27.

**ID-2 · Reviews are de-anonymised through `BookingDTO.review`.**
Attack: the tutor opens T9/T10. `BookingDTO` is shared across viewers and embeds `review: BookingReviewRefDTO` (reviewId, stars, textState). Preconditions: none. Impact: every "A student, month" review is tied to a named minor. The tutor may still have an open notes channel (7-day grace), a live grant to the minor's grades, and the minor's off-platform contact. Defence: `ReviewDTO` drops names. GAP: the booking DTO undoes it, and the `tutor_review` "new review" notification may carry a booking id. Fix: serialise `review` for the student viewer only; no booking or student reference in review notifications; show the review date as a quarter; publish a review only once that booking's notes window has closed → SC-12.

**ID-3 · Confused report targets.**
Attack: `POST /api/tutoring/reports` with `targetType=booking_note` and the `targetId` of a note in someone else's booking. Impact: the note body is copied into `target_snapshot`, and an admin is made to read the whole thread through A10. Defence: O12 says the target must be visible. GAP: the visibility check must start from the target's own parent rows (note → booking → participants; reply → review → listed tutor), never from ids the client supplies. Fix → SC-27.

**ID-4 · Evidence objects.**
Attack: `DELETE /api/tutor/profile/evidence/{evidence_id}` with another tutor's id. Separately, a signed URL leaks through history, a screenshot or a share. Defence: O1 resolves the profile; O17 limits signed URLs to admins. GAP: T7 needs `WHERE tutor_profile_id = :caller`. The signed URL TTL is 3600 s and the file opens inline (F10). Fix → SC-22, SC-27.

**ID-5 · Audit-log identifiers.** `AccessLogEntryDTO.entryId` is a global `bigint` identity, so it reveals platform-wide tutor-read volume. Low. Fix: return an opaque id, or none, since the cursor already exists (recommended, §6).

**ID-6 · Cursor tampering.** The cursor is client-controlled base64 JSON. If a scope value ever goes into it, or a value is interpolated into SQL, the scope widens or injection follows. Fix: the cursor holds sort-key values only, decoded with types (UUID, Decimal, ISO instant) and bound as parameters → SC-27.

**ID-7 · The outcomes preview after suspension.** T8 returns `OutcomesDTO` "in any listing state", so a suspended or rejected tutor can keep polling figures about former students (feeds OS-3). Fix → SC-4.

**ID-8 · Existence oracle on parent routes.** PA1/SP6 answer 403 or 404 depending on whether the child exists. Accepted precedent (`teacher.py:2406-2414` documents the same trade; UUIDs make enumeration impractical). No change.

**ID-9 · Analytics beyond need (F8).** Exact attempt timestamps and `lastActiveAt` show the minor's routine (for example, submissions at 01:40). `questionIds` are useless to a tutor, who has no question routes. Fix: a tutor projection that truncates times to the Cairo date and drops `questionIds`; the parity test compares after projection → SC-20.

### 3.2 Consent bypass

**CB-1 · The child switches off parent oversight (F1).**
Attack: a groomer tells the minor "remove your parent link first", then gets a grant, an in-person booking and notes. Impact: R1, R3 and R4 all fall away; the parent gets nothing. Defence: none. GAP: total. Fix: unlinking notifies the unlinked parent (inbox + email, fixed text). Link and unlink go to an append-only `parent_link_events` table → SC-1. [U, recommended]: a grant or in-person booking within 14 days of a parent unlink raises a system item in the admin report queue (§6).

**CB-2 · The child picks the "parent" (F2).**
Attack: the minor links a friend, or the tutor's second account, as "parent". Impact: oversight notices go to a non-guardian. A groomer posing as parent gets the exact in-person place and time of **every** session with any tutor (O16), every notes thread, the right to book for the child, and the existing parent analytics. Defence: none. GAP: no cap on redeemed links, and nobody is told about a new one. Fix: a new link notifies every parent already linked; redeemed links capped at 4 per child → SC-1.

**CB-3 · Revocation and client caches.** T20 checks validity and writes the audit row in one transaction, then loads history afterwards. A revoke that commits in that gap lets one read finish. That is acceptable under "effective on next read". The service worker never caches `/api`, and react-query persistence is allowlist-only (F13). GAP: no `Cache-Control: private, no-store` on granted-data and notes responses, and no test that tutoring keys stay off the persist allowlist. Fix → SC-26.

**CB-4 · The grant stays valid after the tutor is delisted.** `grant_status` checks only `suspended` (SPEC §e.1). A tutor whose re-review was **rejected** keeps reading indefinitely, and cannot be found through directory-based reporting either. Fix: valid only while `listing_state ∈ {listed, pending_review}` (paused is fine) → SC-3.

**CB-5 · Reinstatement brings grants back.** Suspension only makes grants invalid at read time, so A3 "reinstate" silently restores access to every minor's data with no new consent. Fix: suspension sets `revoked_at` with a new `grantrevokereason` value `tutor_suspended` in the same transaction. Reinstatement restores nothing. Students are told → SC-3.

**CB-6 · TOCTOU between block or suspension and booking writes.** Booking creation checks "no block, listed" and then inserts. A concurrent block or suspension cancels only the rows its snapshot can see, so a booking that commits in the gap survives as active. T11 accept has no block or suspension guard (SPEC §a.3), so the suspended or blocked tutor accepts it and gets a channel. Fix: lock protocol plus re-checks inside the transaction → SC-4. (Grants are safe here because `grant_status` re-checks the block at read time.)

**CB-7 · A suspended tutor keeps writing.** O9 checks the block but not suspension, and completed bookings stay postable for 7 days. Decline and cancel reasons, replies and no-show marks also stay open. Fix: every tutor **write** route refuses a suspended profile (409 `tutor_suspended`) → SC-4.

**CB-8 · No account kill switch (F4).** Suspension leaves the teacher account fully usable, which is what makes XT-1 work. Fix: the safeguarding suspension also severs school-less class enrolments (SC-2). Session eviction stays optional.

**CB-9 · Consent coaching.** A tutor asks the minor in notes to "share your progress". The minor alone consents (locked row 2+3a). Controls: the confirm sheet, parent notice (only as strong as CB-1/2), the audit log. Recommended (§6, [A]): a grant needs at least one *accepted* booking with that tutor. That narrows who can receive grants without changing who consents.

**CB-10 · What "Stop sharing" actually stops.** Revoking does not remove the student from outcome counting, and does not affect a tutor who also teaches the student's class. S-37 says "They lose access the next time they open your page", which is false for that person. Fix: the copy and an S-37 list of class-roster adults → SC-2.

**CB-11 · Deletion wipes the evidence.** There is no account-deletion path today (no `delete(User)` found). But the FKs cascade `users`/`tutor_profiles` → `tutor_bookings` → `tutor_booking_notes`, so a future deletion path, or admin SQL, erases every note with minors unless a report snapshot exists. Fix: RESTRICT on the safeguarding tables, plus a tutor profile soft-close → SC-21.

### 3.3 Cross-tenant reads

**XT-1 · The roster side door (F3, F4).**
Attack: a tutor (or any teacher who met the minor through the marketplace) creates a school-less class and asks the minor to join with its code. Preconditions: contact with the minor, which the notes thread and sessions provide. Impact: `GET /api/teacher/students/{id}` returns the same T-05 DTO, with no `tutor_access_audit` row, no parent notice, no S-37 entry and no student-side way out. It survives a block (block only touches grants and bookings) and a suspension (profile only). ADR-T03's "never unioned" holds in code, but the person is the same. Defence: none. Fix [A], touching classes but no locked row: the block transaction removes the student from every school-less class owned by the blocked teacher; the safeguarding suspension does the same for students who ever booked or granted that tutor; a student can leave a school-less class; linked parents are told when a student joins a school-less class whose owner holds a tutor profile; S-37 lists "teachers who can see your progress through a class" → SC-2.

**XT-2 · Dual-gate confusion.** A school teacher who is also the student's tutor still sees them through the roster after the grant is revoked (correct by ADR-T03, but unexpected for the student). Fix: S-37 shows the case (computed on the student side only, never shown to the tutor) → SC-2.

**XT-3 · Class data used for tutoring sales.** A school teacher uses roster at-risk flags to approach their own students for paid lessons. In Egypt, school teachers giving private lessons is restricted. Nothing leaks technically; it is a policy risk. Recommended (§6): a conflict-of-interest declaration at tutor approval, with school memberships shown to the admin on X-05.

**XT-4 · Tutoring data reaching school views.** None found. `school_admin` has no tutoring route; teacher routes never read grants; `AttemptDTO.paperId` cannot open scripts through teacher routes (F8). Keep the cross-gate tests (O14) and the admin schema test (O15).

**XT-5 · `platform_admin` reads of minors' notes are not recorded** (SPEC O-17). Fix: an admin access log for A10 thread views and A2 evidence opens → SC-23.

**XT-6 · Not verified.** Whether school-console grading writes into the student's `history_store`. If it does, school assessments flow to private tutors through the grant. Check before wave 4.

### 3.4 Review fraud

**RF-1 · Sock-puppet students (F7).** The tutor creates N free student accounts, accepts their requests, marks them completed at `starts_at` and leaves 5★. Stars count from insert with no moderation. Ten 5★ puppets lift the Bayesian score from 4.0 to about 4.67 (prior 4.0, weight 5). Fix: verified email to book and to review; tutor completion only after `ends_at` → SC-15, SC-17. Recommended (§6): hold stars from accounts under 14 days old.

**RF-2 · One account writes many reviews.** "One review per completed booking" (locked) means one loyal or puppet student with 20 sessions writes 20 reviews. Fix [A]: aggregates count each student's latest stars once; the card says "n students" → SC-16. Row 7 is unchanged.

**RF-3 · The tutor suppresses reviews.** Only the tutor marks `completed`. Marking a dissatisfied student `no_show`, or never marking an outcome, blocks the review for good. Fix: if no outcome is marked 48 h after `ends_at`, the student (or the requesting parent) may mark it completed; a `disputed_outcome` report reason → SC-17.

**RF-4 · Cherry-picked outcomes.** The same lever keeps low-graded students out of the outcome cohort, and the tutor can see granted grades when deciding. Fix: a tutor-marked `no_show` does not remove a student from the cohort → SC-17.

**RF-5 · Review bombing by rivals.** Mostly prevented, because the target tutor controls completion. Residual: rival puppets book real sessions. Report and admin removal exist. Low.

**RF-6 · Retaliation for a review.** Replies are moderated before publication (good). Retaliation happens outside the reply instead: the tutor identifies the reviewer (ID-2), then uses notes, the grant or off-platform contact. Fix → SC-12.

**RF-7 · Getting round moderation by editing.** An edit sends the text back to `pending` (good). Replies cannot be edited (no route). A rejected reply blocks any further reply because of the unique key, which is a usability issue, not a security one. Low.

### 3.5 PII on the public profile

**PP-1 · `noindex` is not enforced as specified (F9).** On Workers, `/tutors*` never reaches the worker. In nginx, headers set on a `location /tutors` block are lost on the internal redirect to `= /index.html`. Impact: tutor cards become indexable once linked. Fix: a `_headers` rule for `/tutors` and `/tutors/*` (if the SPA fallback does not apply `_headers`, add `/tutors*` to `run_worker_first` and set the header in the worker); in nginx, a `map $request_uri $robots_tag` with `add_header X-Robots-Tag $robots_tag always;` inside `location = /index.html`; never `Disallow: /tutors` in `robots.txt` (crawlers would then never see the header); a staging smoke test with `curl -sI`; `<meta name="robots">` on the client as defence in depth → SC-18.

**PP-2 · "Logged-in only" is not a privacy boundary (F7).** Bio, availability, review text and outcome figures are one free, unverified account away, so scrapers can harvest outcome figures over time (feeds OS-3). Fix: verified email for SP2–SP5 → SC-15.

**PP-3 · Contact details in free-text profile fields.** `headline`, `bio` and `qualification_note` are moderated. **`other_mode_note` is not on the moderated list (SPEC §a.3)**, so a listed tutor can add a phone number or WhatsApp with no re-review. Fix → SC-7.

**PP-4 · Re-identifying a tutor.** First name, initial, city, subjects and headline can identify a school teacher, with professional harm for some teachers in Egypt. Defence: minimal card, `noindex`. Residual accepted. Recommended: T-14 copy says so, and the areas file uses governorate level outside large cities.

**PP-5 · Block API identifiers.** B2 takes `userId` (`users.id`), but student DTOs carry only `tutorId` (the profile id). Implementers will be tempted to add `users.id` to `TutorCardDTO`, which is PUBLIC. `BlockDTO.displayName` could also leak a tutor's full account name. Fix: B2 takes `tutorId` from students and `studentId` from tutors; tutors' public name only; a schema test that no student, parent or public DTO carries a tutor's `users.id` → SC-19.

**PP-6 · Timing and shape side channels on P2/SP2.** One predicate query; 404 for unknown, unlisted, paused and suspended alike. Low. A test asserts identical bodies (§7).

**PP-7 · No rate limit, and caching that does nothing (F11, F12).** O-9's mitigation is ineffective as deployed. Fix: a Cloudflare WAF rate-limit rule on `/api/public/tutors*` (edge-level, which fits §0's "no process state"), or a `caches.default` read-through in the worker for public GETs only → SC-26.

**PP-8 · Evidence files.** The bucket is private and the column holds a path (good). GAPs: 1 h inline signed URLs (F10); the type is trusted from the declared `content_type`; EXIF data; objects orphaned when a row is cascade-deleted. Fix → SC-22.

### 3.6 Child-safety abuse paths

**CS-1 · Oversight depends on the parent link.** See CB-1 and CB-2. Top risk.

**CS-2 · Parents are not told about notes.** §b.4 notifies only the other participant, so a parent must think to go and look. Fix: linked parents get an inbox notice for tutor-authored notes (no text, one per booking per Cairo day). The tutor's composer always says "This student's parents can read these notes." Never add anything that tells a tutor whether a student *has* a linked parent: that would mark unsupervised children → SC-9.

**CS-3 · Contact exfiltration.** Channels: notes (2000 chars), `firstNote`, `decline_reason`, `cancel_reason`, `location_detail`, booking and profile `other_mode_note`, and `meeting_link` (any `https://` URL, so `wa.me/…`, `instagram.com/…`, `t.me/…` all pass). Moving a minor to WhatsApp removes every control. Benign tutors in Egypt share WhatsApp routinely, so likelihood is high. Fix [A, input validation, nothing stored or read by a person]: a pure `core.contact_patterns` check rejects Egyptian mobiles (`01[0125]` plus 8 digits, `+20`/`0020`, Arabic-Indic digits `٠-٩`, separators), emails, URLs and social handles in tutor-written and student-written free text, returning 422 `contact_details_not_allowed`; a host allowlist for `meeting_link`; notes rendered as plain text, never auto-linked → SC-7. Disclose it in DELIVERY §5.7.

**CS-4 · Channel lifetime.** SP6 `startsAt` has no maximum (SP5 `from` only has a lower bound), so a request six months ahead keeps a "booking-scoped" thread open for months. The states in which `can_post_note` allows posting are not written down. Fix: `MAX_BOOKING_HORIZON = 28 days`, plus a state table → SC-8.

**CS-5 · In-person booking of a minor with no linked parent.** Every parent-based control is void, and Lemely holds no date of birth, so every student must be treated as a possible minor. [U] options for the user: an in-person request needs at least one linked parent with a verified email; or adopt O-2 (the first-booking safety notice) at least for in-person mode (§6).

**CS-6 · Reports have no immediate effect.** The queue is FIFO (`ix_tutoring_reports_queue`), so a safety report waits behind spam. Admins are not notified. **A paused or re-review tutor cannot be reported** (O12 says "listed profile"), so pausing dodges profile reports. Fix: safety reports first in the queue; an admin inbox notice; any booking participant can report the tutor profile in any state; a `safety_concern` report from a booking party freezes posting on that booking until resolved; the report sheet names Egypt's child helpline (16000) → SC-10.

**CS-7 · A block announces itself.** T20 returns 403 `blocked`, and the cancel reason literal is "Blocked", so a possibly abusive adult learns that the child blocked them. Fix: generic tutor-facing codes (`access_ended`, "Cancelled"); notes stay readable and reportable after a block → SC-11. A block must also sever roster access (SC-2). Parents cannot block (O-18, a consequence of locked row 4).

**CS-8 · Gaps in admin investigation.** An admin sees only the reported thread, so a pattern across one tutor's other minors stays invisible, and admin reads are not recorded. Fix: an admin access log → SC-23. [U] recommended: a logged, time-boxed "safeguarding investigation" read of every thread of a reported tutor (§6).

**CS-9 · Notification text escapes.** If `booking_note` notifications carry note text, hiding a note does not retract it; push sends it off the platform; and `["notifications"]` persists in IndexedDB (F13). Fix: fixed title and body, ids only in the payload → SC-9.

**CS-10 · Fake tutors.** "Documents seen" is the only gate, and teacher signup is unverified. Fix: tutor submission (T4) needs a verified email → SC-15. DELIVERY §5.7 already says there is no background check.

### 3.7 Outcome-stat re-identification

**OS-1 · What k counts is unclear.** ADR-T04 says "contributing students", while the DTO has both `nGraded` and `nWithoutGrade`. If k counts the cohort, 4 puppets with no papers plus 1 real student discloses one grade. Fix: k counts `nGraded` (distribution) and `nPaired` (change); `nWithoutGrade` is null whenever its figure is insufficient → SC-13.

**OS-2 · Subtracting grades the tutor already knows.** The tutor knows every cohort member, having taught them, and holds exact grades through grants from some of them. Distribution minus known grades gives the grades of members who **never** granted. With k = 5 and four granting members, the fifth grade is exact. Homogeneity (SPEC O-3) is a special case. Fix [U, adds suppression to row 8]: a figure is insufficient unless the number of members who never granted this tutor is 0 or at least k, and also whenever the largest bucket holds at least n−1 → SC-14.

**OS-3 · Differencing over time.** Figures are computed on every request. The tutor (T8) and any free account (SP4) can poll. The "during" grade moves as members upload papers inside `[S, E+60d]`, and the tutor decides *when* a member joins by marking completed with no deadline. Before-and-after views reveal one student's bucket and direction. Fix [A]: a member counts only once their window has closed (no completed session with this tutor in this subject for `DURING_GRACE` days), which fixes their grades; the published set is the first ⌊n_closed / k⌋·k closed members by close time, so figures change in steps of k students. All computed at read time, no scheduler → SC-13.

**OS-4 · Opting out discloses.** Removing a member "on the next read" shows which bucket lost one, so the privacy action itself discloses the grade. Fix [A]: a 90-day hold. The figure shows the insufficient state for 90 days after any member's opt-out (`student_tutoring_preferences.updated_at`) and is then recomputed → SC-13.

**OS-5 · Padding the cohort with sybils.** Puppets with known grades pad the cohort. Grading needs a verified email (F7) and Gemini spend, so the cost is non-zero. Fix: a member counts only with a verified email and an account at least 30 days old at their first session → SC-13. Residual risk is documented.

**OS-6 · Before-grade leak.** The change figure reveals each paired member's pre-tutoring grade relative to later. Covered by OS-2 and OS-3.

**OS-7 · Default-on counting of minors.** Locked row 8, so it stays a residual risk. The S-37 revoke copy must say that revoking does not stop counting (SC-2, from CB-10).

### 3.8 Email path

**EM-1 · The mock runs in production without anyone knowing (F6).** If mock "deliveries" are marked `sent`, parent email notices look delivered when nothing left the building. Fix: the mock marks `skipped` (reason `mock_provider`), never `sent`; it logs only the outbox id and template; `lemely doctor` and startup warn when tutoring runs without an `[email] api_key` → SC-6.

**EM-2 · Inbox writes are not atomic (F5).** A grant commits, the parent notification fails, and the parent is never told. Or the notification is written and the transition rolls back, giving a false notice. Parent notification is the main compensating control in ADR-T02. Fix: `NotificationService.create_in_session(session, …)` (savepoint, same preference gate), used by every tutoring fan-out; correct the §b.4 claim → SC-5.

**EM-3 · Header, content and link injection.** Resend's JSON API and `html.escape` make header injection unlikely (`email.py:147-198, 330-371`). But tutor-controlled `public_first_name` in a body or subject can carry phishing text ("Sara visit lemely-help.com"), CR/LF or bidi controls, and plain-text parts get auto-linked by mail clients. Fix: a character allowlist for the name (Unicode letters including Arabic, space, hyphen, apostrophe; no digits, `.`, `/`, `@`, controls or bidi U+202A–202E / U+2066–2069); a schema per template for `context`; links built only as `urljoin(app_base_url, fixed route + uuid)` → SC-25.

**EM-4 · Address-based abuse.** A parent account can carry any unverified address (F7). A student links an attacker-made "parent" whose address belongs to a victim, then loops request→cancel. Each new booking id is a new dedupe key, so the victim is spammed and the sender domain's reputation suffers. Fix: tutoring email goes only to recipients with `email_verified_at`, otherwise `skipped`; a DB-backed quota per requester (COUNT over `ix_tutor_bookings_requested_by` in the last 24 h) → SC-15.

**EM-5 · Address enumeration and PII in errors.** No route returns an email except A2 `accountEmail` (admin only). `ExternalServiceError` messages include the recipient (`email.py:359-369`), and those would land in `email_outbox.last_error`. Fix: strip the address from `last_error` → SC-25.

**EM-6 · Phone-only parents.** Placeholder addresses are skipped (O-19), and the SMS provider is hard-wired to the mock (`deps.py:296`), so phone-only parents get in-app notices only. Document it. Low.

### 3.9 Booking integrity

**BK-1 · Double booking.** Prevented by the two exclusion constraints, which were verified live (SPEC §a.4). Residual: calendar griefing. A `requested` booking holds the slot with no auto-expiry, and puppets (1 per student per tutor) can hold a rival's whole calendar. Fix: the horizon cap (SC-8) and verified email to request (SC-15).

**BK-2 · Locked out by the pending limit.** If `MAX_PENDING_PER_STUDENT` counts stored `requested` rows, requests that have expired in effect only get persisted as expired on a later write to *the same tutor*. After 5 ignored requests to 5 tutors the student can never book again. "Row-locked count" is also not defined. Fix: count `state='requested' AND starts_at > now()` under `SELECT … FROM users WHERE id=:student FOR UPDATE` (precedent: `mint_parent_invite`) → SC-24.

**BK-3 · TOCTOU around unlink, block and suspension.** See CB-6. The parent's link must be read `FOR SHARE` inside the insert transaction → SC-4.

**BK-4 · Accept guards are incomplete.** T11 checks only time and link or location. It must also refuse a suspended or rejected tutor, a blocked pair, and a subject who is no longer a student → SC-4.

**BK-5 · Actor versus subject in `firstNote`.** `author_party` allows only `student`/`tutor`, so a parent's `firstNote` either fails or gets stored **as the child's words**, a misattribution in a safeguarding record. Fix: reject `firstNote` on parent-requested bookings (422) → SC-24.

**BK-6 · Parent authority after unlink.** O7 and O8 re-check on every call (good). Notification fan-out reads the current links at event time (good).

**BK-7 · Time zones, DST and clocks.** Rules are wall clock plus zone, and instants are UTC (correct, O-5). Residuals: Egypt has changed DST rules at a few days' notice before; a client-sent instant in the ambiguous hour; clock skew between Cloud Run instances at the 24 h cutoff. Recommended (§6): accept only instants produced by `bookable_slots`; compare times with DB `now()` inside the compare-and-set; keep `tzdata` current.

**BK-8 · Instant completion.** `accepted → completed` is allowed at `starts_at`, which makes puppet reviews fast. Fix: completion needs `now >= ends_at` → SC-17.

**BK-9 · Blocking to dodge the cancel window.** A block overrides the 24 h window, on either side. It is a safety tool, so accept it and log it. Low.

---

## 4. Ranked risk register

Severity: impact if exploited. Likelihood: how plausible exploitation is, given who uses Lemely (mostly minors in Egypt) and how much effort it takes. Ranked by severity × likelihood × blast radius.

| Rank | ID(s) | Threat | STRIDE | Severity | Likelihood | Fix |
|---|---|---|---|---|---|---|
| 1 | CB-1, CB-2, CS-1 | The child can delete or choose the parent link, so every "parent notified" control fails | S, R, E | High | High | SC-1 |
| 2 | XT-1, CB-8 | Roster side door: any teacher gets full analytics through a class join code, unaudited, unrevocable, surviving block and suspension | E, I, R | High | Medium | SC-2 |
| 3 | CS-3, CS-4, PP-3 | Contact exfiltration through unmoderated free text and meeting links; booking threads with no time limit | I, E | High | High | SC-7, SC-8 |
| 4 | OS-2, OS-3, OS-4 | Outcome figures as a grade oracle for students who never consented (subtracting granted grades, differencing, opt-out disclosure) | I | High | Medium | SC-13, SC-14 [U] |
| 5 | ID-2, RF-6 | Reviewer de-anonymised through `BookingDTO.review`, leading to retaliation against a minor | I | Medium-High | High | SC-12 |
| 6 | EM-2, EM-1 | Parent notices lost (non-atomic inbox; mock provider in production) | R, D | High | Medium | SC-5, SC-6 |
| 7 | CB-4, CB-5, CB-7, ID-7 | A suspended or rejected tutor keeps grants and channels; reinstatement restores grants | E | High | Low-Medium | SC-3, SC-4 |
| 8 | CS-2, CS-9 | Parents not told about notes; note text in inbox, push and IndexedDB | I, R | Medium | High | SC-9 |
| 9 | CS-6, CS-7 | Report queue gaps (FIFO, unreportable paused profile, no freeze); block reveals itself | D, I | Medium | Medium | SC-10, SC-11 |
| 10 | CB-6, BK-3, BK-4 | TOCTOU: a booking survives a block or suspension; a blocked or suspended tutor can accept | T, E | Medium-High | Low | SC-4 |
| 11 | RF-1, RF-2, RF-3, RF-4, BK-8 | Sock-puppet ratings; one account many reviews; review suppression and cohort cherry-picking via no-show | T, R | Medium | High | SC-15, SC-16, SC-17 |
| 12 | PP-1 | `noindex` not delivered on `/tutors*` as specified | I | Medium | High | SC-18 |
| 13 | ID-9 | Exact activity timestamps of a minor shown to a tutor | I | Medium | High | SC-20 |
| 14 | XT-2, CB-10 | The student misunderstands what revoking stops | R, I | Medium | Medium | SC-2 |
| 15 | EM-4, EM-3 | Email spam to third parties; phishing text in tutor names | S, T | Medium | Low-Medium | SC-15, SC-25 |
| 16 | CB-11 | Cascade deletes erase safeguarding evidence (latent: no deletion path yet) | R | Medium | Low | SC-21 |
| 17 | PP-5 | Tutor `users.id` and full name leak through the block API | I | Medium | Medium | SC-19 |
| 18 | PP-8, ID-4 | Evidence: 1 h inline signed URLs, trusted declared type, EXIF data | I | Medium | Low | SC-22 |
| 19 | XT-5, CS-8 | Admin reads of minors' notes not recorded; no cross-thread investigation | R | Medium | Low | SC-23 |
| 20 | ID-1, ID-3, ID-6 | Object-level checks without a test that can go red (other tutor's grant, report target, cursor) | E, I | High if wrong | Low | SC-27 |
| 21 | PP-7 | Public directory: no rate limit, and caching gives no load shielding | D | Low-Medium | Medium | SC-26 |
| 22 | BK-2 | Pending limit locks a student out for good | D | Low-Medium | Medium | SC-24 |
| 23 | BK-5 | A parent's `firstNote` stored as the child's words | R | Low-Medium | Medium | SC-24 |
| 24 | CB-3 | Granted data in HTTP caches after revoke (no `no-store`) | I | Low | Low | SC-26 |
| 25 | PP-4, XT-3, BK-7, BK-9, EM-6, ID-5 | Residual and low items | — | Low | — | §6 |

---

## 5. SPEC changes required before implementation (must-fix)

Each item names the threats it closes and where in the SPEC it goes. [A] = compatible with the locked rows. [U] = needs the user.

**SC-1 [A] Parent-link integrity** (CB-1, CB-2, CS-1). New dependency section in §b.4 and a migration in wave 1. (a) `DELETE /api/student/parent-links/{id}` notifies the unlinked parent (inbox `parent_link`, email `parent_unlinked`, fixed copy, no reason). (b) Redeeming a parent invite notifies every parent already linked. (c) An append-only `parent_link_events(child_id, parent_id, event, at)` table. (d) Redeemed links capped at 4 per child (409 `parent_limit`). The tutoring §b.4 fan-out keeps reading current links.

**SC-2 [A] Close the roster side door** (XT-1, XT-2, CB-8, CB-10, OS-7). §a.2 `tutoring_blocks` effects, §a.3 suspension, new routes. (a) The block transaction deletes the blocked student's enrolments in every school-less class (`school_id IS NULL`) owned by the blocked teacher. (b) Suspension deletes, from that teacher's school-less classes, the enrolments of every student who ever booked or granted the tutor. (c) New `DELETE /api/student/classes/{class_id}` (STUDENT; school-less classes only; 404 otherwise). (d) When a student joins a school-less class whose owner holds a tutor profile, linked parents get a `tutor_access`-style notice. (e) S-37 gains a section "Teachers who can see your progress through a class", with Leave for school-less classes. The revoke confirm sheet says: "This tutor also teaches your class {name}, so they still see your class progress there" (only when true; computed on the student side) and "Your grades are still counted in their results unless you turn that off below."

**SC-3 [A] Grant validity and suspension** (CB-4, CB-5). §a.1 adds `grantrevokereason` value `tutor_suspended`. §e.1 `GrantFacts` gains `tutor_listing_state`; valid only when `listing_state ∈ {listed, pending_review}` (paused allowed), and `grant_status` returns `tutor_unavailable` otherwise. §a.3 suspension sets `revoked_at = now(), revoke_reason = 'tutor_suspended'` on every live grant in the same transaction and notifies each student; `reinstated` restores nothing. The SQL predicate parity test covers the new column.

**SC-4 [A] Lock protocol and action guards** (CB-6, CB-7, BK-3, BK-4, ID-7). New §a.4b. Booking create, accept, complete, no-show and note post run `SELECT … FROM tutor_profiles WHERE id=:t FOR SHARE`, re-check block, suspension and listing in the same transaction, and include those conditions in the compare-and-set `WHERE`. Block and suspension take `FOR UPDATE` on the tutor row plus `pg_advisory_xact_lock(hashtextextended(student_id::text || tutor_profile_id::text, 0))` before sweeping. A parent booking reads its `ParentChildLink` `FOR SHARE` inside the insert transaction. Every tutor **write** route (T3–T7, T11–T15, T17, T18, B2) returns 409 `tutor_suspended` for a suspended profile. T8 omits `OutcomesDTO` unless the profile is listed or pending_review.

**SC-5 [A] Atomic inbox fan-out** (EM-2). §b.4: add `NotificationService.create_in_session(session, user_id, type, title, *, body, payload, dedupe_key)`, which uses a savepoint and the same preference gate and returns push eligibility to send after commit. All tutoring fan-out uses it. Replace the sentence "already gates by preference and dedupes … in the same transaction" with the accurate description.

**SC-6 [A] An honest mock** (EM-1). §b.4: `MockTransactionalEmailProvider` marks rows `skipped` with `last_error='mock_provider'` and logs only the outbox id and template. `lemely doctor` and app startup log a WARNING when tutoring routes are mounted and `[email] api_key` is unset. Platform-admin X-05 shows "Email delivery: mock".

**SC-7 [A] Contact-detail validation** (CS-3, PP-3). New pure `lemely/core/contact_patterns.py` (`find_contact_details(text) -> list[Match]`), applied to `tutor_booking_notes.body`, `firstNote`, `decline_reason`, `cancel_reason`, `location_detail`, booking `other_mode_note`, profile `headline`/`bio`/`qualification_note`/`other_mode_note`, and replies. Matches give 422 `{"code":"contact_details_not_allowed"}` with copy telling the user to keep contact on Lemely. `meeting_link`: parsed with `urllib.parse`; `https` only, no userinfo, default port, host equal to or a subdomain of an allowlist (`meet.google.com`, `zoom.us`, `teams.microsoft.com`, `teams.live.com`, `whereby.com`); otherwise 422 `meeting_link_not_allowed`. Add `other_mode_note` to the moderated-field list in §a.3. C-21 renders note text as plain text, never auto-linked. DELIVERY §5.7 discloses the validation.

**SC-8 [A] Channel lifetime** (CS-4, BK-1). §e.1: `MAX_BOOKING_HORIZON = timedelta(days=28)`, enforced by `bookable`, SP5 (`from + days ≤ today + 28`) and SP6. `can_post_note` is true only for `requested`/`accepted` before `ends_at`, or `completed` until `ends_at + NOTE_POST_GRACE`. Never for `declined`/`cancelled`/`expired`/`no_show`, a blocked pair, a suspended tutor, or a booking under a safety freeze (SC-10). Reading and reporting stay allowed after closure.

**SC-9 [A] Parent visibility of notes; notifications with no text** (CS-2, CS-9). §b.4 row "New note": tutor-authored notes also notify every linked parent (`booking_note`, dedupe `"{booking_id}:note:{cairo_date}"`). Every `booking_note` title and body is fixed copy ("New note on your session with Sara M."); the payload holds ids only. The tutor composer always shows "This student's parents can read these notes." No tutor-facing DTO says whether a student has linked parents (schema test).

**SC-10 [A] Report pipeline** (CS-6). §a.2 queue index becomes `(state, (reason = 'safety_concern') DESC, created_at, id)`. A `safety_concern` report creates a `tutoring_report` inbox notice for every platform admin (new notification type and column). O12: any party to any booking with a tutor may report that tutor's profile in any listing state. A `safety_concern` report on a booking or note by a party to that booking sets `tutor_bookings.notes_frozen_at` until resolution. The report sheet includes "If someone is in danger, call 16000 (Child Helpline, Egypt)."

**SC-11 [A] Tutor-facing codes that reveal nothing** (CS-7). T20's 403 codes for tutors collapse `blocked`, `grant_revoked` and `tutor_suspended` into `access_ended` (the student's own `GrantDTO.status` keeps the detail). System cancel reasons shown to tutors read "Cancelled". After a block, notes stay readable and reportable by both sides and by parents.

**SC-12 [A] Reviewer anonymity** (ID-2, RF-6). `BookingDTO.review` is serialised only when the viewer is the booking's student (null for tutor and parent viewers). `tutor_review` notifications to tutors carry no booking or student id. `ReviewDTO.month` becomes `period` ("Jul–Sep 2026"). A review becomes visible to the tutor and the public only after `ends_at + NOTE_POST_GRACE` for its booking.

**SC-13 [A] Hardened outcome computation** (OS-1, OS-3, OS-4, OS-5). In ADR-T04 / §e.1 `tutor_outcomes`: (a) k counts `n_graded` and `n_paired`, and `n_without_grade` is None whenever its figure is insufficient. (b) A member counts only once closed: last completed session with this tutor in this subject ended at least `DURING_GRACE` ago. (c) The published member set is the first `floor(n_closed / k) * k` closed members by close time. (d) `OUTCOME_OPT_OUT_HOLD = 90 days`: the figure is insufficient while any member, or any student removed from the set, opted out within the hold. (e) A member counts only with `email_verified_at` and account age of at least 30 days at their first session. All computed at read time; no scheduler.

**SC-14 [U] Outcome suppression rules** (OS-2; replaces SPEC O-3). A figure is insufficient unless (i) the number of members who never held a grant to this tutor is 0 or at least k, and (ii) its largest bucket holds at most n−2. This adds conditions to locked row 8's "insufficient-data state below k". Without it, the tutor can compute the exact grades of students who never consented. **Recommended: adopt.**

**SC-15 [A] Verification gates and quotas** (RF-1, PP-2, EM-4, CS-10, BK-1). Require `email_verified_at` for SP2–SP5 reads, SP6, S6/S7, S9, R1 and T4 (409 `email_unverified`, precedent `deps.py:1010`). Tutoring email goes only to verified recipients (`skipped` otherwise). DB-backed per-requester quotas via COUNT over existing indexes: ≤ 10 booking creations and ≤ 10 cancellations per 24 h → 429 `too_many_requests`.

**SC-16 [A] Ratings counted per student** (RF-2). `rating_sum`/`rating_count`/`rank_score` count each student's latest non-removed review once (maintained in the same `FOR UPDATE` transaction). `RatingDTO.count` means distinct students, and C-22 reads "4.6 · 12 students". Row 7 is unchanged.

**SC-17 [A] Completion integrity** (RF-3, RF-4, BK-8). §a.3: `accepted → completed/no_show` by the tutor only when `now >= ends_at`. If the effective state is `awaiting_outcome` for more than 48 h, the student or requesting parent may mark `completed` (party recorded). New `reportreason` `disputed_outcome`; an admin may set `completed`. The ADR-T04 cohort counts bookings in `completed` **or** tutor-marked `no_show`.

**SC-18 [A] `noindex` that actually arrives** (PP-1). Replace O-8's placement. Cloudflare: `web/public/_headers` gets `/tutors` and `/tutors/*` → `X-Robots-Tag: noindex, nofollow`; if the SPA fallback does not apply `_headers`, add `/tutors*` to `run_worker_first` and set the header in `web/worker/index.ts`. nginx: `map $request_uri $robots_tag { ~^/tutors(/|$) "noindex, nofollow"; default ""; }` plus `add_header X-Robots-Tag $robots_tag always;` inside `location = /index.html` (an empty value omits the header). `robots.txt` must not disallow `/tutors`. A staging `curl -sI` check goes in the deploy checklist. Client-side `<meta name="robots" content="noindex">` on G-16/G-17.

**SC-19 [A] Block API identifiers** (PP-5). `BlockCreateDTO` becomes `{tutorId}` (student) or `{studentId}` (tutor). `BlockDTO` shows the tutor's public name and `tutorId`. B3 path is `/api/tutoring/blocks/{counterpart_id}`, resolved by role. A schema test: no PUBLIC, STUDENT, PARENT or STUDENT_OR_PARENT DTO contains a tutor's `users.id`.

**SC-20 [A] Data minimisation in the tutor view** (ID-9). `build_student_detail(..., viewer="tutor")` truncates `attempts[].recordedAt`, `trend[].recordedAt`, `engagement.lastActiveAt` and at-risk evidence timestamps to the Cairo date, and empties `weaknesses[].questionIds`. The parity test compares against `_student_detail_dto` after the same projection.

**SC-21 [A] Safeguarding retention** (CB-11). `tutor_bookings.tutor_profile_id`, `tutor_bookings.student_id`, `tutor_booking_notes.booking_id` and `tutoring_reports.*` FKs become `ON DELETE RESTRICT`. `tutor_profiles` gains `closed_at` (soft close). Document a retention period for notes and reports in `docs/deployment.md`.

**SC-22 [A] Evidence handling** (PP-8, ID-4). Evidence signed URLs use a dedicated `tutor_evidence_signed_url_ttl_seconds = 300`, with `response-content-disposition=attachment` and `response-content-type` from the DB row (extend `StorageBackend.create_signed_url` with an optional `disposition`). The upload sniffs magic bytes (precedent `looks_like_pdf`, `lemely/io/_scan_common.py:342`; `open_checked_pdf`) and re-encodes images, dropping metadata. Startup or test asserts the bucket is private. An orphan-object sweep note covers cascade deletes.

**SC-23 [A] Admin access log** (XT-5, CS-8). An append-only `tutoring_admin_access(admin_user_id, action ∈ {report_thread_view, evidence_open}, report_id, booking_id, tutor_profile_id, at)` written on A10 and A2. Resolves O-17 for the admin side.

**SC-24 [A] Booking-create correctness** (BK-2, BK-5). The pending limit counts `state='requested' AND starts_at > now()` under `FOR UPDATE` on the student's `users` row. `firstNote` on a parent-requested booking → 422 `note_not_allowed_for_parent`.

**SC-25 [A] Hardened email content** (EM-3, EM-5). §a.2: `public_first_name` CHECK plus service validation against the character allowlist in EM-3; `public_last_initial` must be one letter. Each template has a typed context schema (extra keys rejected). Links come only from `urljoin(settings.email.app_base_url, fixed_path(booking_id))`. `email_outbox.last_error` stores the provider status and message with the address removed.

**SC-26 [A] Caching rules** (CB-3, PP-7). `Cache-Control: private, no-store` on T19, T20, every notes route, and every route returning `BookingDTO`, `GrantDTO` or `AccessLogPageDTO`. `public, max-age=60` only on P1/P2. Replace O-9's mitigation with a Cloudflare WAF rate-limit rule on `/api/public/tutors*` (documented in `docs/deployment.md`) or a worker `caches.default` read-through for P1/P2 GETs. A vitest asserts no tutoring query key is on `persistAllowlist.ts`.

**SC-27 [A] Explicit object-level rules O18–O21** (ID-1, ID-3, ID-4, ID-6). Add to §c.3: **O18** the grant lookup is keyed on `for_user(auth.user_id).id`, never on any other profile id. **O19** report-target visibility is resolved server-side from the target's own parent rows (note → booking; reply → review → tutor). **O20** evidence delete and list are scoped `WHERE tutor_profile_id = :caller`. **O21** cursors carry sort-key values only, decoded with types, used as bound parameters; a cursor from another endpoint gets 422.

---

## 6. Recommended, not blocking (or for the user)

- **[U] O-1** (parent read-only grant and audit view) and **[U] O-2** (first-booking safety notice). Both are cheap and directly address rank 1 and CS-5. Strongly recommended, at least for in-person mode.
- **[U]** In-person requests need at least one linked parent with a verified email (CS-5).
- **[U]** A system safety item when a grant or in-person booking follows a parent unlink within 14 days (CB-1).
- **[U]** A logged, time-boxed safeguarding-investigation read of every thread of a reported tutor (CS-8).
- **[A]** A grant needs at least one accepted booking with that tutor (CB-9).
- **[A]** Hold stars from accounts under 14 days old (RF-1); cap pending requests from accounts under 7 days old per tutor (BK-1).
- **[A]** A conflict-of-interest declaration at approval; X-05 shows the applicant's school memberships (XT-3).
- **[A]** Accept only instants produced by `bookable_slots`; compare times with DB `now()` inside the compare-and-set; keep `tzdata` current (BK-7).
- **[A]** An opaque `entryId` on the access log (ID-5); governorate-level areas outside large cities, plus T-14 copy on identifiability (PP-4).
- Upgrade `react-router`/`react-router-dom` past GHSA-qwww-vcr4-c8h2. Install and run `pip-audit` in CI.

---

## 7. Tests that must exist

Named as authz, IDOR and race tests. Each must include a case that fails without the fix (proof that the check can go red). Files follow SPEC §e.4.

**IDOR / object-level (`tests/test_web_tutoring_authz.py`)**
- `test_idor_t20_other_tutors_grant_does_not_authorize` (O18) · `test_idor_t20_unknown_and_never_granted_are_identical_404`
- `test_idor_t10_booking_review_null_for_tutor_viewer` · `test_idor_pa2_booking_review_null_for_parent_viewer` · `test_idor_tutor_review_notification_has_no_booking_or_student_ref`
- `test_idor_report_note_visibility_resolved_from_note_booking` · `test_idor_report_reply_requires_visible_review` (O19)
- `test_idor_t7_cannot_delete_other_tutors_evidence` (O20) · `test_idor_a2_evidence_url_ttl_300_and_attachment`
- `test_idor_cursor_from_other_endpoint_422` · `test_idor_cursor_typed_decode_rejects_injection` (O21)
- `test_idor_t8_preview_omits_outcomes_when_suspended_or_rejected`
- `test_idor_no_public_student_parent_dto_contains_tutor_user_id` · `test_idor_b2_student_blocks_by_tutor_id`
- `test_idor_tutor_dto_never_reveals_parent_link_presence`
- `test_privacy_tutor_projection_truncates_timestamps_and_drops_question_ids`

**Authz / consent (`tests/test_web_tutoring_authz.py`, `tests/test_web_parent_tutoring.py`)**
- `test_authz_grant_invalid_when_listing_rejected` · `test_authz_reinstatement_does_not_restore_grants` · `test_authz_suspension_revokes_grants_with_reason`
- `test_authz_suspended_tutor_write_routes_409` (parametrised over T3–T7, T11–T15, T17, T18, B2) · `test_authz_suspended_tutor_cannot_post_note_on_completed_booking`
- `test_authz_accept_refused_when_blocked` · `test_authz_accept_refused_when_suspended`
- `test_authz_block_removes_school_less_class_enrolment` · `test_authz_block_keeps_school_class_enrolment` · `test_authz_suspension_removes_school_less_enrolments_of_tutoring_students` · `test_authz_student_can_leave_school_less_class_only`
- `test_authz_cross_gate_class_teacher_without_grant_t20_404` · `test_authz_cross_gate_granted_tutor_not_on_roster_teacher_route_403` (re-asserted)
- `test_authz_parent_unlink_notifies_parent` · `test_authz_new_parent_link_notifies_existing_parents` · `test_authz_parent_link_cap_409`
- `test_authz_parent_first_note_rejected` · `test_authz_parent_actions_refused_after_unlink` · `test_authz_parent_cancel_requires_requester`
- `test_authz_report_tutor_profile_allowed_for_participant_when_paused` · `test_authz_safety_report_freezes_thread_until_resolved`
- `test_authz_t20_reason_code_generic_access_ended` · `test_authz_block_keeps_notes_readable_and_reportable`
- `test_authz_verified_email_required_for_booking_review_grant_report_submit`
- `test_authz_complete_requires_ends_at` · `test_authz_student_may_complete_after_48h_awaiting_outcome`
- `test_authz_can_post_note_state_table` · `test_authz_booking_horizon_28_days`

**Race (`tests/test_concurrency.py`, own sessions, barrier start)**
- `test_race_block_vs_booking_create_no_active_booking_survives`
- `test_race_suspend_vs_booking_create_no_active_booking_survives`
- `test_race_suspend_vs_accept_exactly_one_outcome`
- `test_race_block_vs_note_post_no_note_after_block`
- `test_race_unlink_vs_parent_booking_create`
- `test_race_revoke_vs_t20_no_200_after_revoke_commit` (audit rows equal 200 responses)
- `test_race_grant_create_vs_block_grant_never_valid`
- `test_race_pending_limit_concurrent_requests_at_most_5`
- `test_race_two_reviews_same_student_aggregate_counts_once`
- Existing SPEC cases kept: slot race (8 threads), accept vs cancel, concurrent reviews, concurrent grants.

**Outcome privacy (`tests/test_core_tutor_outcomes.py`)**
- `test_outcomes_k_counts_n_graded_not_cohort` · `test_outcomes_insufficient_hides_n_without_grade`
- `test_outcomes_member_counts_only_after_window_closed` · `test_outcomes_published_set_moves_in_steps_of_k`
- `test_outcomes_single_completion_causes_no_visible_change` (differencing) · `test_outcomes_opt_out_hold_90_days`
- `test_outcomes_member_requires_verified_and_30_day_account` · `test_outcomes_no_show_does_not_remove_member`
- [U, if SC-14 adopted] `test_outcomes_never_granted_between_1_and_k_minus_1_suppresses` · `test_outcomes_largest_bucket_n_minus_1_suppresses`

**Notifications and email (`tests/test_email_outbox_repo.py`, `tests/test_tutoring_notify.py`)**
- `test_notify_inbox_and_outbox_roll_back_with_failed_transition` · `test_notify_grant_commit_implies_parent_inbox_rows`
- `test_notify_parent_notified_of_tutor_note_without_text` · `test_notify_note_notification_has_no_body_text`
- `test_email_mock_marks_skipped_not_sent` · `test_email_skipped_for_unverified_recipient` · `test_email_context_schema_rejects_extra_keys`
- `test_email_links_only_from_app_base_url` · `test_email_last_error_has_no_address` · `test_public_first_name_charset_rejects_digits_urls_bidi`
- `test_quota_booking_create_429_after_10_per_day`

**Input validation (`tests/test_core_contact_patterns.py`, `tests/test_web_tutoring_safety.py`)**
- `test_contact_patterns_egyptian_mobile_latin_and_arabic_indic_digits` · `test_contact_patterns_email_url_social_handles` · `test_contact_patterns_no_false_positive_on_grades_and_times`
- `test_free_text_fields_reject_contact_details` (parametrised over every SC-7 field) · `test_meeting_link_allowlist_rejects_userinfo_http_wa_me`

**Config and deploy (`tests/test_deploy_headers.py`, `web/tests/unit/`)**
- `test_nginx_index_html_sets_x_robots_tag_for_tutors` · `test_headers_file_has_tutors_noindex_rule` · `test_robots_txt_does_not_disallow_tutors`
- `test_tutoring_private_routes_send_no_store` · `test_public_routes_only_p1_p2_cacheable`
- `persistAllowlist.test.ts`: `excludes tutoring query keys`
- `test_tutor_profile_delete_restricted_when_bookings_exist` (SC-21)
- Deploy checklist: `curl -sI https://staging.lemelyig.com/tutors/x | grep -i x-robots-tag`

---

## 8. Not verified, and residual risk

- **XT-6:** whether teacher-console grading writes into the student's history (if so, school assessments flow to tutors through the grant).
- Whether Workers Static Assets applies `_headers` to SPA-fallback responses (SC-18 covers both outcomes).
- Whether a Cloudflare cache rule already exists for `/api/*` (F12 assumes none; the worker code sets none).
- `pip-audit` not run (not installed).
- **Residual after all fixes:** a minor can still, alone, share indefinite all-subject analytics and book in person (locked rows 2+3a, 3b, 4, 9). Outcome counting stays default-on (row 8). Moderation of notes stays reactive apart from the contact-pattern validation. A determined adult can evade regex validation with spelled-out numbers. These are the accepted risks recorded in ADR-T02 and ADR-T04. The fixes above stop them being *silent*, *unrecorded* or *bypassable through another door*.
