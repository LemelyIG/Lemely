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
 * Three things are therefore deliberately absent, and their absence is the
 * design rather than an oversight:
 *
 *   - No legal basis, no jurisdiction, no data-controller identity, no rights
 *     statement, no contact address. There is no operator in this repository to
 *     name and no inbox to promise a reply from. Inventing "privacy@lemely" is
 *     the dead-navigation defect (a link to nothing) wearing a serious face.
 *   - No retention period, because there is no retention machinery. See
 *     `notYetBuilt` below: nothing in `lemely/` purges, expires or anonymises
 *     anything, which was verified rather than assumed.
 *   - No terms of service at all. Nothing in this codebase implies a contract
 *     between anybody and anybody.
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
     * `lemely/db/models/attempts.py:24` (Upload): the file goes to Supabase
     * Storage (`lemely/io/storage.py`) and the row keeps storage_path,
     * original_filename, content_type, byte_size, page_count.
     *
     * The marks are a separate table, `attempts.py:53` (Attempt): awarded and
     * maximum marks, percentage, grade and predicted grade, boundary source,
     * confidence band. Grades are qualified because `Attempt`'s own docstring
     * records that a quiz attempt carries no grade at all rather than an
     * invented one.
     */
    body: "A scan is kept as a file in Supabase Storage, along with its original filename, its type, its size and how many pages it has. What Lemely works out from it is stored separately: the marks for each question, a total, a grade where the grade boundaries for that paper are known, and how confident the marker was about each mark.",
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
     * `lemely/db/models/…` class membership), and the review queue is
     * `lemely/web/routers/review.py`, fed by the `needs_teacher_review` flag on
     * `Attempt` (`attempts.py:103`).
     *
     * "Only for a child they are linked to" is the load-bearing half of the
     * first sentence: a parent screen that lists children is not the same claim
     * as a parent who can look up any student.
     */
    body: "A parent who is linked to a student account can see that student's marks, weak topics and at-risk flags, and only for a student they are linked to. A teacher can see the work of students in their own classes. When Lemely is unsure about a paper it marked, that paper is put in a queue for a teacher to look at.",
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
     * goes and stops, not a promise about retention: this page has no
     * retention machinery to describe (see `notYetBuilt` below), and a crash
     * report is no exception to that gap. The client IP is not something
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

/**
 * The gap, stated on the page rather than left out.
 *
 * Established by search across `lemely/` while preparing this page, and
 * recorded in D6.8: nothing purges, expires or anonymises a scan, an attempt or
 * an account, and no route deletes an account. `DELETE` routes exist for a
 * flashcard deck, a class, an announcement, a friendship and a device, and for
 * nothing else.
 *
 * Putting this in a labelled panel rather than a paragraph is §4's rule that a
 * caveat gets a chip rather than a colour: a reader skimming headings should
 * not be able to miss the one item here that is missing rather than present.
 */
export const notYetBuilt = {
  tag: "Not built yet",
  heading: "There is no way to delete any of this",
  body: "Lemely has no account deletion and no way to remove a scan you have uploaded. Nothing is deleted on a schedule either, so a paper uploaded today stays until someone removes it by hand. This is a real gap, and it is written here rather than left out.",
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
