/*
 * Copy for "How Lemely handles your data" (P6.5, D6.8 option A).
 *
 * ────────────────────────────────────────────────────────────────────────────
 * WHY THIS PAGE IS A DESCRIPTION AND NOT A POLICY
 * ────────────────────────────────────────────────────────────────────────────
 * §5's Phase 6.5 closeout list ends with "legal links", and the footer had none
 * and said so. D6.8 asked the human which of three things to do about that, and
 * the reasoning behind the default is the reason this file exists:
 *
 *   **Facts about this product can be derived from this repository. Promises
 *   cannot.** A privacy policy and a terms of service are mostly promises: they
 *   say what an operator undertakes to do, who is accountable, and under whose
 *   law. None of that is in the code, so writing it here would be inventing
 *   content in the one category where invention has legal consequences. That is
 *   a different act from inventing a testimonial, and a worse one.
 *
 * So every sentence below is a statement about behaviour that can be checked by
 * reading a named module, and each one carries that module in a comment beside
 * it. This is `./data.ts`'s rule, applied to a page where the cost of breaking
 * it is higher: **a claim with no source comment does not ship.**
 *
 * Two things are therefore deliberately absent, and their absence is the
 * design rather than an oversight:
 *
 *   - No legal basis, no jurisdiction, no data-controller identity, no rights
 *     statement, no contact address. There is no operator in this repository to
 *     name and no inbox to promise a reply from. Inventing "privacy@lemely" is
 *     the dead-navigation defect (a link to nothing) wearing a serious face.
 *   - No terms of service at all. Nothing in this codebase implies a contract
 *     between anybody and anybody.
 *
 * A retention period used to be on this list of absences: earlier versions of
 * this file said there was no retention machinery to describe. That stopped
 * being true once paper deletion shipped. `RETENTION_DAYS` in
 * `lemely/core/deletion.py` is the one number behind the window described in
 * `deletion` below, and it is the actual restore window and the actual
 * integrity hold, not a figure chosen for this page.
 *
 * If a sentence here stops being true, that is a defect in this file, and the
 * fix is to change the sentence rather than to soften it.
 */

/** The page's own heading and standfirst. */
export const dataHandlingIntro = {
  eyebrow: "How your data is handled",
  title: "What Lemely does with your work",
  /*
   * The frame the whole page hangs off. It claims exactly one thing (that this
   * describes the software as built) and explicitly disclaims the two things a
   * reader might otherwise assume a footer link of this kind is: an agreement,
   * and a promise about the future.
   */
  standfirst:
    "This page describes what the software does today, as built. Every point below can be checked against the code that does it. It is a description of behaviour, not an agreement, and it does not promise anything about the future.",
}

export interface DataHandlingSection {
  heading: string
  body: string
}

export const dataHandlingSections: DataHandlingSection[] = [
  {
    heading: "What an account holds",
    /*
     * `lemely/db/models/users.py:16` is the whole list: email, role,
     * display_name, phone (nullable), locale, friend_code (nullable, minted
     * lazily on first use of the friends feature, per its own docstring).
     *
     * "Lemely does not hold your password" is not a promise, it is the shape of
     * the schema: there is no password column on that model, and
     * `lemely/auth/gotrue.py` hands sign-in to Supabase Auth, whose id the
     * `users.id` column mirrors (the model docstring says so in as many words).
     */
    body: "An account is one row: an email address, whether you are a student, a parent, a teacher or an administrator, a display name, a phone number if you gave one, and a language code. There is no password on it. Signing in is handled by Supabase Auth, which is where the credential lives.",
  },
  {
    heading: "The devices you are signed in on",
    /*
     * `lemely/db/models/users.py:180` (Device): client_device_id,
     * device_label, user_agent, last_seen_at, revoked_at. The three-device
     * policy is `MAX_DEVICES` in `lemely/db/device_repo.py`, surfaced by
     * `lemely/web/routers/me.py:406`, and the revoke route is
     * `DELETE /me/devices/{device_id}` at `me.py:424`.
     *
     * This section exists because it is the one item on the page a reader can
     * act on today, and saying so is more useful than any assurance.
     */
    body: "Each sign-in records a device: a name for it, the identifying string your browser sends, and when it was last used. Three can be signed in at once, and signing in on a fourth revokes the oldest. You can revoke any of them yourself from the devices screen in settings.",
  },
  {
    heading: "The papers you upload",
    /*
     * `lemely/db/models/attempts.py:24` (Upload): the file goes to Google
     * Cloud Storage (`lemely/io/storage.py`) and the row keeps storage_path,
     * original_filename, content_type, byte_size, page_count.
     *
     * The marks are a separate table, `attempts.py:53` (Attempt): awarded and
     * maximum marks, percentage, grade and predicted grade, boundary source,
     * confidence band. Grades are qualified because `Attempt`'s own docstring
     * records that a quiz attempt carries no grade at all rather than an
     * invented one.
     */
    body: "A scan is kept as a file in Google Cloud Storage, along with its original filename, its type, its size and how many pages it has. What Lemely works out from it is stored separately: the marks for each question, a total, a grade where the grade boundaries for that paper are known, and how confident the marker was about each mark. You can delete a paper you have uploaded; see below for what that removes and what it keeps.",
  },
  {
    heading: "Your scan is sent to Google",
    /*
     * The most important sentence on the page, so it is stated first and
     * plainly rather than folded into a list of "service providers".
     *
     * `lemely/io/answer_extraction.py:125` passes the scan's path as
     * `file_paths=[scan_path]`, and `lemely/io/gemini.py:374` resolves that to
     * `self._client.files.upload(file=fp)`. The file itself goes to Google,
     * which is materially different from sending text extracted locally, and a
     * reader cannot infer which one from a phrase like "we use AI".
     *
     * The second sentence is deliberately broad rather than a list, because the
     * same client is also used by mark-scheme parsing
     * (`lemely/io/mark_schemes.py`), marking (`lemely/io/correction_ai.py`),
     * question and flashcard generation, and study plans. Naming four of six
     * would read as a complete list and be wrong.
     */
    body: "Reading handwriting is done by Google Gemini, and the uploaded file itself is sent to Google, not just text taken from it on this side. Other features that generate or interpret text, including parsing a mark scheme, marking, making practice questions and building a study plan, send that text to the same service.",
  },
  {
    heading: "Who else can see your work",
    /*
     * Parent access is link-gated: `_authorized_child` in
     * `lemely/web/routers/parent.py:114` guards every parent route, and the
     * link itself is `ParentChildLink` (`lemely/db/models/users.py:72`).
     * Teacher access is class-scoped (`lemely/web/routers/teacher.py`,
     * `lemely/db/models/…` class membership). Two roles see more (issue 243):
     * `teacher_paper_visible` in `lemely/db/teacher_paper_repo.py` grants a
     * `school_admin` every paper their schools' teachers upload and a
     * `platform_admin` every console paper, and `ClassService`
     * (`lemely/db/class_repo.py`) gives a `school_admin` every class in their
     * schools. The review queue is
     * `lemely/web/routers/review.py`, fed by the `needs_teacher_review` flag on
     * `Attempt` (`attempts.py:103`).
     *
     * "Only for a child they are linked to" is the load-bearing half of the
     * first sentence: a parent screen that lists children is not the same claim
     * as a parent who can look up any student.
     */
    body: "A parent who is linked to a student account can see that student's marks, weak topics and at-risk flags, and only for a student they are linked to. A teacher can see the work of students in their own classes. A school administrator can see the work of students in classes at their school, and the papers their school's teachers upload. Lemely's own platform administrators can open papers uploaded to the grading console, for support. When Lemely is unsure about a paper it marked, that paper is put in a queue for a teacher to look at.",
  },
  {
    heading: "What this site does not do",
    /*
     * Was "verified by search rather than asserted: no analytics,
     * advertising, session-recording or error-reporting script appears
     * anywhere in `web/src`". PR 1B (client error reporting) made that
     * search stale rather than the sentence merely aging: `lib/clientErrors.ts`
     * now exists, `main.tsx` wires it to `window`'s "error" and
     * "unhandledrejection" listeners, and every portal's `ErrorBoundary`
     * (`components/ui/error-boundary.tsx`) calls it from
     * `componentDidCatch`. So this panel now names that path explicitly
     * instead of continuing to claim it does not exist — see the section
     * below. Payment processing is still out of scope outright
     * (PRODUCT.md:74), which is also why the landing page's plans section
     * renders a placeholder rather than tiers, and analytics, advertising
     * and session-recording scripts are still genuinely absent — this
     * sentence was re-verified against `web/src`, `web/index.html` and
     * `web/package.json` for this change, not carried over unread.
     *
     * The last sentence is phrased as a fact about code paths, not as an
     * undertaking. "We will never sell your data" is a promise and cannot be
     * derived from a repository; "no code path sends it anywhere else" is a
     * property of the code and can. It now excepts the crash-report path
     * named below by cross-reference rather than by silently no longer being
     * true.
     */
    body: "It loads no analytics, advertising or session-recording scripts. There is no payment processing anywhere in the product, so there is nothing to enter a card into. Beyond the services named on this page and the crash reports described next, no code path sends any of this to anyone.",
  },
  {
    heading: "If something breaks while you are using it",
    /*
     * `lib/clientErrors.ts` is the whole of this: `buildClientErrorReport()`
     * defines the exact wire body (message, stack, componentStack, route,
     * buildId, kind, userAgent, occurredAt), `redactRoute()` is what keeps a
     * password-reset or invite-code token in the URL out of it, and the
     * module's own comment is where "sent only when something breaks" comes
     * from: it fires from `ErrorBoundary.componentDidCatch`
     * (`components/ui/error-boundary.tsx`) and from the two `window`
     * listeners `main.tsx` installs ("error", "unhandledrejection"), and
     * from nowhere else in the client.
     *
     * "Lemely's backend" and "Google Cloud Logging" name where the report
     * goes and stops, not a promise about how long Cloud Logging keeps it:
     * that is Google's retention, not a rule this codebase sets, and it is a
     * different thing from the 30-day paper retention `deletion` describes
     * below, which this backend does control. The client IP is not something
     * this client sends; it is what every HTTP request carries and what
     * Cloud Logging records the request as having arrived from, the same as
     * it would for any other route this backend serves.
     *
     * "Does not include your answers, your marks or your session data" is the
     * negative space worth stating plainly: `buildClientErrorReport()` never
     * reads `localStorage`/`sessionStorage` (its own comment says so), takes
     * no form field or answer text as input, and the fields it does send are
     * about the failure, not about you.
     */
    body: "If a screen breaks, Lemely sends a small report to help fix it: what went wrong, the technical detail of where in the code that happened, which screen you were on, your browser's user agent string and when it happened. That report goes to Lemely's own backend, which writes it to Google Cloud Logging alongside the network address the report arrived from, the same as any other request this backend receives. It is sent only when something breaks, never on an ordinary visit, and it does not include your answers, your marks, or anything stored in your session.",
  },
]

/*
 * The tutoring marketplace (SPEC `docs/tutoring/SPEC.md` section f, release
 * groupings 1, 2 and 4, plus the review and report data of groupings 3 and 5).
 *
 * These sections follow the rule at the top of this file: each sentence
 * describes behaviour and names the module that does it, and a claim with no
 * source comment does not ship. They are a separate export, not part of
 * `dataHandlingSections`, because two of the original guards in
 * `dataHandling.test.ts` apply to that array only: the "no retention number
 * outside the deletion panel" test, and the original six headings. Every number
 * below is pinned to the Python constant behind it by the last describe in
 * that test file, so a changed constant turns the test red rather than leaving
 * the page stale.
 *
 * Where an item is an accepted limit rather than a feature, the sentence says
 * so in plain words (SPEC section i.3, i.8, i.9; `docs/tutoring/adr/`).
 */
export const tutoringSections: DataHandlingSection[] = [
  {
    heading: "Tutors on the public directory",
    /*
     * `lemely/web/schemas_tutoring.py`: `TutorCardDTO` is "the only tutor
     * fields the open web ever sees" (publicName, headline, subjects, modes,
     * area, rating), and `tutorId` is `tutor_profiles.id`, never `users.id`.
     * `PublicTutorCardDTO.indexable` is the one extra boolean the edge reads.
     * `web/worker/robots.ts`: `handleTutorPage` sends `noindex, nofollow` for
     * anything but a 200 with `indexable === true` (a failed or slow lookup
     * counts), `DIRECTORY_ROBOTS_TAG` keeps the directory page itself out of
     * the index, and `PUBLIC_CACHE_TTL_SECONDS` (60) is the delay before an
     * opt-out reaches the edge. A search engine's own re-crawl is outside this
     * repository, so the sentence says "when it next visits" and gives no date.
     */
    body: "A tutor's public card shows a first name and last initial, a headline, subjects, teaching modes, a city area and a rating summary. It carries a tutor identifier, not the account identifier. Search engines can list a card unless the tutor turns that off in their profile, and the directory page itself is marked not to be indexed. If the edge cannot check a card, the card is marked not to be indexed. An opt-out reaches Lemely's edge within a minute, but a search engine drops a card only when it next visits it.",
  },
  {
    heading: "Documents a tutor uploads",
    /*
     * `lemely/db/tutor_evidence_repo.py`: `MAX_EVIDENCE_FILES` (5), and
     * `open_for_admin` signs each file's URL and writes one `evidence_open`
     * row per URL (`TutoringAdminAction` in `lemely/db/models/enums.py`,
     * table `TutoringAdminAccess` in `lemely/db/models/tutoring.py`).
     * `lemely/io/evidence_files.py`: `MAX_EVIDENCE_BYTES` (10 MiB).
     * `lemely/runtime/config.py`: `tutor_evidence_bucket` is its own private
     * bucket; `tutor_evidence_signed_url_ttl_seconds` (300).
     * `documents_seen_at` is cleared by any evidence change
     * (`tutor_evidence_repo.py`). "Documents seen" is that timestamp and
     * nothing else: no identity, issuer or records check exists in this code.
     */
    body: "A tutor can upload up to 5 files of up to 10 MiB each as evidence of their qualifications. They are kept in a separate private bucket in Google Cloud Storage and are opened only by a Lemely platform administrator, through a link that lasts 300 seconds. Each open is logged. \"Documents seen\" means an administrator looked at them. It is not an identity check, a check with whoever issued the qualification, or a criminal-records check. Changing the documents removes the badge until an administrator looks again.",
  },
  {
    heading: "Booking a session",
    /*
     * `lemely/db/models/tutoring.py` (`TutorBooking`) holds the student, the
     * tutor, subject, mode, start and end, the requesting party, the state,
     * the decline and cancel reasons and the meeting link or place.
     * `lemely/core/booking.py`: `CANCEL_CUTOFF` (24 hours) is the point after
     * which only the tutor may cancel, with a reason the student and linked
     * parents see (`ck_tutor_bookings_late_cancel_reason`). A request whose
     * start has passed is shown as expired by `EFFECTIVE_STATE_SQL`
     * (`lemely/db/tutoring_predicates.py`) when read; no job rewrites it.
     */
    body: "A booking records the student, the tutor, the subject, the mode, the start and end, who requested it (the student or a linked parent), its state, and any reason given and any meeting link or place the tutor entered. A student or parent cannot cancel inside 24 hours of the start. The tutor can, with a reason that the student and linked parents see. A request whose start time has passed is shown as expired when it is read. Nothing changes it in the database until that student next requests that tutor.",
  },
  {
    heading: "Notes between a student and a tutor",
    /*
     * `lemely/db/booking_repo.py`: notes are posted by the booking's student or
     * tutor only; a linked parent reads and cannot post. `NOTE_POST_GRACE` in
     * `lemely/core/booking.py` (7 days) is how long after the session notes
     * stay open. `lemely/core/contact_patterns.py` checks free text for phone
     * numbers, emails, links and handles when it is posted.
     * `lemely/web/routers/admin_tutoring_reports.py` is the only route that
     * returns a thread to an administrator, and it writes a
     * `report_thread_view` row (`TutoringAdminAction`) each time. Nothing
     * else in this code reads note text, which is why the sentence says
     * "only when a note is reported".
     */
    body: "Each booking has a notes thread between the student and the tutor. Notes can be posted for 7 days after the session. Linked parents can read the notes and cannot post. When a note is posted, the text is checked for phone numbers, email addresses, links and social handles, and a determined person can still spell one out. Lemely staff read a thread only when a note is reported, and each time a platform administrator opens a reported thread, that view is logged.",
  },
  {
    heading: "Emails about bookings",
    /*
     * `lemely/web/tutoring_email.py`: a queued row in `email_outbox`
     * (`lemely/db/email_outbox_repo.py`) is handled once, by the 60-second
     * sweeper. A placeholder address, an unconfirmed recipient or a switched-off
     * notice type is `skipped`; with the mock provider a row is `skipped` with
     * `last_error='mock_provider'` and never `sent`; a failed send is never
     * retried. `lemely/runtime/config.py`: `TutoringSettings.email_daily_cap`
     * (60). `lemely/io/notify_email.py` is the provider seam.
     */
    body: "Booking and safeguarding events queue an email, and the same job that sends other notifications delivers it once. Emails go only to addresses the recipient has confirmed, and at most 60 a day are sent. If no email provider key is set, queued emails are recorded as skipped and nothing is sent. A failed email is not retried. An email can wait in the queue while no server is running, and a crash at the wrong moment can send one twice.",
  },
  {
    heading: "Reviews of a tutor",
    /*
     * `lemely/db/tutor_review_repo.py` and `TutorReview` in
     * `lemely/db/models/tutoring.py`: one review per completed booking, by that
     * booking's student. `lemely/core/tutor_ratings.py`: `REVIEW_EDIT_WINDOW`
     * (14 days) and `REVIEW_MIN_ACCOUNT_AGE` (14 days). Review text and a
     * tutor's reply are held until an administrator approves them
     * (`lemely/web/routers/admin_tutoring_moderation.py`). The public reviewer
     * label is the fixed "A student" (`ReviewDTO` in
     * `lemely/web/schemas_tutoring.py`); the count shown is distinct students,
     * so a tutor with few students can still sometimes guess a reviewer.
     */
    body: "A student who completed a session can review it once and edit the review for 14 days. Review text, and the tutor's one reply, are read by a Lemely administrator before they are public. A review shows \"A student\" and a season, not a name or a date, but a tutor with few students can sometimes guess who wrote it. Any signed-in student with a confirmed email address can read reviews.",
  },
  {
    heading: "Parent links and class joins",
    /*
     * `lemely/db/parent_repo.py`: `ParentLinkService.unlink` writes a
     * `parent_link_events` row and tells the unlinked parent once;
     * `MAX_LINKED_PARENTS` (4) is the cap, enforced in `link_in_session`.
     * `lemely/db/invite_repo.py` (`_redeem_parent_invite`) tells the parents
     * already linked when another links. `lemely/db/class_repo.py`
     * (`join_by_code_outcome`): joining a class that has no school and whose
     * teacher holds a tutor profile sends the student's linked parents a
     * notice. These notices are information, not approvals.
     */
    body: "A student can remove a parent link at any time. The parent is told once, when it happens, and nothing after that. A child can have at most 4 linked parents, and parents already linked are told when another links. When a student joins a class that has no school and is taught by someone who is also a tutor, the student's linked parents are told. These notices are not approvals, and a parent cannot stop the join.",
  },
  {
    heading: "Sharing your progress with a tutor",
    /*
     * `lemely/core/tutor_grants.py` and `lemely/db/tutor_grant_repo.py`: a
     * grant is made by the student alone, minors included, covers all subjects
     * and lasts until the student stops it; validity is computed when read.
     * `lemely/web/student_detail_view.py` (`project_for_tutor`): derived
     * analytics only, dates without times of day, no question ids, no answer
     * sheets. `TutorAccessAudit` in `lemely/db/models/tutoring.py` is the
     * append-only log of every read, shown to the student;
     * `lemely/web/routers/parent_tutor_access.py` shows linked parents the
     * grants and the log, read-only, with no revoke. Decision rows 3b and 10
     * (`BUILD/tutoring/decision-log.md`) and ADR-T02 record that this is
     * allowed without a parent's approval.
     */
    body: "Only the student can share their progress with a listed tutor, at any age, and only the student can stop it. Sharing covers all subjects until it is stopped. The tutor sees derived figures such as grades, predicted and target grades, marks, weak topics, trend, warnings and the days the student was active. They never see answer sheets or the time of day a student used Lemely. Every time a tutor looks, a record is kept that the student can read. Linked parents can see who the student shares with and each time a tutor looked, but they cannot stop it.",
  },
  {
    heading: "Past-student results and counting",
    /*
     * `lemely/core/tutor_outcomes.py`: `OUTCOME_K_MIN` (5), `DURING_WINDOW`
     * (120 days from the first session), `BEFORE_LOOKBACK` (180 days) and
     * `OPT_CHANGE_HOLD` (90 days). `lemely/db/tutor_outcomes_repo.py` builds
     * the cohort; `StudentTutoringPreferences.outcome_stats_opt_out` defaults
     * to counted. Grades worked out from estimated boundaries are left out
     * (ADR-T04). The caveats are the ones the profile screen shows; the
     * residual that a tutor can sometimes compare a figure over time is
     * decision row 13 and ADR-T04 R5, stated in `docs/tutoring/SPEC.md`
     * section g (5.7), so it is stated here too.
     */
    body: "A tutor's profile can show grades of past students, without names. A student who has a session with that tutor is counted unless they opt out. Grades come from papers uploaded in the 120 days from the first session, compared with the latest grade before it. A figure appears only when at least 5 students have a marked paper, and only when no single student's grade could be worked out from it. It is hidden for 90 days after anyone's counting choice changes. The grades come from Lemely's automatic marking and leave out grades from estimated boundaries. The figure does not show what the tutor caused, because students choose their tutors. A tutor can sometimes work out one student's grade by comparing the figure over time, and this is an accepted limit.",
  },
  {
    heading: "Reports and blocks",
    /*
     * `lemely/db/tutoring_reports_repo.py`: a report keeps a snapshot of what
     * was reported (`TutoringReport.target_snapshot`), `safety_concern` reports
     * freeze the notes of the booking, and a platform administrator resolves
     * them. `lemely/db/tutoring_blocks_repo.py`: a student or a tutor can block
     * the other; a block ends any sharing and cancels sessions between them
     * (`lemely/db/tutoring_sweeps.py`). Rows are never deleted
     * (`TutoringBlock` in `lemely/db/models/tutoring.py`), so a past block
     * stays on record.
     */
    body: "Students, linked parents and tutors can report what they can see in tutoring, such as a tutor profile, a booking, a note, a review or a reply. A report keeps a copy of what was reported, and a platform administrator reads it and the thread it came from. A safety concern pauses the notes of that booking until it is resolved. A student or a tutor can block the other: a block ends sharing and cancels upcoming sessions between them. Block and report records are kept and not deleted.",
  },
  {
    heading: "Teachers who can see your progress through a class",
    /*
     * A class teacher sees a student through the roster gate described under
     * "Who else can see your work"; the tutor grant is a separate gate and
     * never unions with it (ADR-T03). `lemely/web/routers/student_tutor_access.py`
     * (S16, S17) lists the classes whose teacher also has a tutor profile and
     * lets a student leave a class that has no school. A class at a school is
     * left through the school, so the screen says to ask the school.
     */
    body: "If a student is in a class taught by a teacher who is also a tutor, that teacher can see the student's progress through the class, as any class teacher can, even when the student has not shared anything as a tutoring student. A student can leave a class that has no school from the tutoring data screen. A class at a school is left through the school.",
  },
]

/** The public shape of the deletion feature, for `DataHandlingDeletion` below. */
export interface DataHandlingDeletion {
  tag: string
  heading: string
  removes: string
  keeps: string
  window: string
  hold: string
}

/**
 * What deleting a paper actually does, stated the same way as every other
 * panel on this page: as a description of behaviour, checked against a named
 * module.
 *
 * This replaces a panel that used to say the opposite: that nothing could be
 * deleted, and nothing purged on a schedule. Once paper deletion shipped, that
 * panel was no longer a gap being disclosed, it was a claim contradicted by
 * the code beside it. Keeping it as a labelled panel rather than folding it
 * into a paragraph is still §4's rule that a caveat, or here a load-bearing
 * fact, gets a chip rather than a colour.
 *
 * There is still no account deletion (no route removes a `users` row), so
 * that absence is not restated here; this panel is about a paper, which is
 * the thing a reader who found this page is likeliest to be asking about.
 */
export const deletion: DataHandlingDeletion = {
  tag: "Deletion",
  heading: "Deleting a paper",
  /*
   * `PaperDeletionService.delete` (`lemely/db/deletion_repo.py`) is the whole
   * of this: the unit is the upload (R7, §13), so deleting one attempt
   * deletes every attempt marked from that scan, the upload row, and (per
   * `lemely/web/purge.py`'s own comment) the scan and a student's own
   * uploaded mark-scheme scan kept beside it. `WeaknessRecord.attempt_id`
   * (`lemely/db/models/attempts.py`) cascades on the attempt, so a weakness
   * worked out from a deleted paper goes with it.
   */
  removes:
    "Deleting a paper removes the scan, and a mark-scheme scan you uploaded alongside it, the upload record, every marking run made from that scan, the marks and per-question history from each of those runs, and the weaknesses worked out from them.",
  /*
   * Mark-scheme reference data: `lemely/web/purge.py`'s module docstring
   * names this exactly, "the `mark_schemes` table is shared reference data
   * and is never touched". XP and streak history: a separate table
   * (`lemely/db/xp_repo.py`), untouched by `PaperDeletionService` or the
   * purge job. The review-queue notice: `NotificationType.review_withdrawn`,
   * sent from `lemely/web/routers/student_deletion.py` when a deleted paper
   * had an open review item, so a teacher who was reviewing it is told it
   * was withdrawn rather than being left looking at a queue item for a paper
   * that quietly vanished. A parent linked to the student keeps seeing that
   * student's ongoing history; nothing on a parent's screen shows that a
   * paper was deleted.
   */
  keeps:
    "It keeps the mark scheme itself, since that is shared reference data other students use, and it keeps your XP and streak history. If the paper was in a teacher's review queue, the teacher keeps a notice that a review item was withdrawn, a record that a paper existed without the paper itself. A parent linked to the student still sees that student's ongoing history, with nothing shown about a deletion.",
  /*
   * `RETENTION_DAYS` in `lemely/core/deletion.py` is 30, and its own
   * docstring says it is deliberately one number for both the restore window
   * and D8's integrity hold, so this page never states a second one. The
   * file staying in Google Cloud Storage during the window, rather than
   * being removed immediately, is `purge.py`'s "GCS first, the row as the
   * record of intent": nothing is destroyed until the window has passed.
   * Teacher console uploads (R2) purge on the same cutoff, via
   * `purge_expired_teacher_papers` in the same module.
   */
  window:
    "A deleted paper can be restored for 30 days from a Recently Deleted list, and the file stays in Google Cloud Storage for that window so restoring it brings back the same scan. After 30 days it is removed for good. A teacher who deletes a paper they uploaded through the grading console works to the same 30-day terms. A teacher can also unshare a paper from one class, so it stops appearing in that class's view and analytics; the student's own copy is unchanged.",
  /*
   * The integrity hold (D8), worded without a reason: `PaperDeletionService`
   * and `BUILD/QUALITY-BAR.md` both say the flags behind it are teacher-only
   * and must never reach a student-facing surface, so this sentence names
   * the wait and the date and stops there, on the owner's ruling (R5/R9)
   * rather than by omission.
   */
  hold: "In some cases a paper can't be deleted for up to 30 days after it was marked; Lemely tells you the date when that applies.",
}

/**
 * The page's closing line.
 *
 * It tells the reader what to do with a sentence above that looks wrong, which
 * is the only honest thing this page can offer in place of a contact address it
 * does not have.
 */
export const dataHandlingClose =
  "Lemely is still being built. If something on this page stops matching what the product does, the page is the thing that is wrong."
