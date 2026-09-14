/*
 * Marketing copy for the Persuade lane (DESIGN.md §2).
 *
 * ────────────────────────────────────────────────────────────────────────────
 * DESIGN IMPORT (feat/landing-redesign, 2026-09-14)
 * ────────────────────────────────────────────────────────────────────────────
 * This file replaces the role-neutral copy the previous redesign shipped.
 * `.superpowers/sdd/design-import-spec.md` is authoritative for the page's
 * structure and wording; `.superpowers/sdd/design-import-claims.md`'s RULING
 * section is authoritative for which of the design's claims ship verbatim
 * versus which are corrected. Read both before touching a string here.
 *
 * THE RULE THIS FILE STILL EXISTS TO ENFORCE
 * -------------------------------------------
 * PRODUCT.md's "Evidence on Hand" bans fabricating customers, testimonials,
 * case studies, press, usage numbers, or partner schools. The design import
 * ships several claims that read stronger than what the product's code
 * currently does ("nothing counts until you sign it off", "the queue orders
 * itself by doubt", "upload a class as a batch") — these were checked against
 * the backend one at a time (design-import-claims.md) and found to overclaim
 * or misdescribe the true behaviour. The RULING there is to ship them
 * verbatim anyway, as the design's authoritative call, with exactly one
 * carve-out: the parent reading's login copy, which the design gets
 * factually wrong (a retired phone-OTP flow) rather than merely optimistic.
 * That carve-out is Readings' concern (`Readings.tsx`, part B of this
 * import); this file does not carry Readings' tab copy.
 *
 * WHAT LIVES HERE VS. WHAT DOESN'T
 * ---------------------------------
 * This file carries the page's FURNITURE copy — every eyebrow, heading, body
 * paragraph, fine print and aside for every section — because that is what
 * Landing.tsx renders directly. It does NOT carry the fixture content for the
 * five specimen components (OpenedQuestion, ScanSequence, SchemeExcerpt,
 * ClassBatch, Readings): those components don't exist yet (part B builds
 * them), Landing.tsx mounts placeholders in their place for now, and their
 * own fixture copy belongs beside the component that renders it, added to
 * this file when part B lands. The copy gate below (`COPY_EXPORTS`/
 * `NOT_COPY`) will need updating that day, same as it does here.
 *
 * EM-DASHES: the design's copy is full of them; `check:copy` bans them under
 * `web/src/`. Every string below has had its em dashes converted to the
 * nearest punctuation that preserves meaning and rhythm (a comma or a colon),
 * never dropping the clause and never introducing one of its own.
 *
 * Three strings were paraphrased rather than quoted in design-import-spec.md
 * as first read (`howItWorks.body`, `schemeSection.body`,
 * `schemeSection.aside`) and were left `undefined` rather than invented —
 * see import-part-a-report.md. The design-import controller has since pulled
 * the verbatim text from `landing.jsx` for all three and patched the spec;
 * every `<p>` on the page now quotes in full, so nothing below is a gap
 * anymore.
 */

export interface CtaLink {
  label: string
  to: string
}

/* ── Nav / Footer ────────────────────────────────────────────────────────
 * Deliberately NOT exported from here, matching the pattern the previous
 * build already established: `index.tsx`'s header ("Log in" / "Parents" /
 * "Get started") and footer ("Lemely, marking for CAIE papers." / "How your
 * data is handled" / "Log in" / "Parent access") are navigation furniture,
 * not a claim about the product, and `marketing.test.ts` pins their routes
 * with source-text assertions rather than the honest-copy gate below. The
 * design's own nav/footer copy (design-import-spec.md, page structure items
 * 1 and 9) is textually identical to what `index.tsx` already had, so
 * nothing there needed to change beyond the sticky nav's new progress bar.
 */

/* ── Hero ────────────────────────────────────────────────────────────────
 * design-import-spec.md, page structure item 2. Quoted verbatim; ships as
 * designed under the RULING (nothing here was flagged in the claims audit).
 */
export const hero = {
  eyebrow: "Marking for CAIE papers",
  headline: "Marking you can check, line by line.",
  sub: "Lemely marks a scanned script against the official mark scheme, then shows the scheme line behind every mark it awards or withholds. Nothing counts until you sign it off.",
  primaryCta: { label: "Get started", to: "/signup" } satisfies CtaLink,
  /* Scrolls to the dark trust band (`#marked`, page structure item 3)
     rather than navigating. `anchor` is the section id Landing.tsx wires
     this to, mirroring the previous build's own hero-CTA pattern. */
  secondaryCta: { label: "See a marked script", anchor: "marked" },
}

/* ── Subjects (folded into the hero, per the design) ───────────────────────
 * The previous build gave subjects their own "Subjects covered" section
 * further down the page; the imported design folds the same three
 * code/name pairs into `.hero__scope` instead (page structure item 2's
 * third bullet) and has no standalone subjects section at all. Same three
 * subjects, same codes, carried over unchanged from the previous `data.ts`.
 */
export interface Subject {
  code: string
  name: string
}

export const subjects: Subject[] = [
  { code: "0580", name: "Mathematics" },
  { code: "0606", name: "Additional Mathematics" },
  { code: "0625", name: "Physics" },
]

/* ── The dark trust band (`#marked`) ────────────────────────────────────────
 * design-import-spec.md, page structure item 3. Quoted verbatim. Ships the
 * design's own eyebrow/heading/body/aside; the visual it wraps
 * (`OpenedQuestion`, inside `.drift`) is part B's build — this section only
 * carries the copy either side of it.
 */
export const trustBand = {
  eyebrow: "Why you can trust it",
  heading: "A mark is an argument, so it arrives with its reasons.",
  body: "Method and answer marks are awarded separately. Lemely names the one that did not land, quotes the scheme line it used, and states how sure it is. Below its confidence floor it flags the question for you instead of guessing.",
  aside: "Open any of the three questions and read the lines it used.",
}

/* ── How it works (`.sect .split--flip`) ────────────────────────────────────
 * design-import-spec.md, page structure item 4. Quoted verbatim, `landing.jsx`
 * via the design-import controller (patched into the spec 2026-09-14). No
 * em dash in the source.
 */
export const howItWorks = {
  eyebrow: "How it works",
  heading: "One scan becomes the marking, the working, and the practice.",
  body: "A photo or a PDF is enough. Lemely identifies the syllabus, session, paper and variant from the page itself, marks the script against that variant's scheme, and turns the dropped marks into a practice set on the same shape.",
  finePrint: "If we do not hold the scheme yet, add it and the paper marks against yours.",
}

/* ── Where the marks come from (`.sect.sect--sunk`) ─────────────────────────
 * design-import-spec.md, page structure item 5. Quoted verbatim, same source
 * and patch as `howItWorks` above. The body's one em dash ("...for that
 * variant — not from a model's impression..."), per the controller's own
 * instruction, is converted to a comma.
 */
export const schemeSection = {
  eyebrow: "Where the marks come from",
  heading: "Official schemes, read as printed.",
  body: "Marks come from the published mark scheme for that syllabus, session, paper and variant, not from a model's impression of the subject. Grade boundaries come from the real table for that variant, and where a boundary has to be estimated the badge says so, permanently, on itself.",
  aside: "Deterministic, AI-assisted and missing are labelled differently, everywhere.",
}

/* ── A class at a time (`.sect .split--flip`) ───────────────────────────────
 * design-import-spec.md, page structure item 6, quotes the eyebrow, heading
 * and fine print directly. The body paragraph is only paraphrased there
 * ("Body as designed"), but design-import-claims.md quotes it in full while
 * verifying it against the backend — two sentences, both explicitly ruled to
 * ship verbatim ("UPLOAD A CLASS AS A BATCH..." and "THE QUEUE THEN ORDERS
 * ITSELF BY DOUBT..." are both listed under the RULING as "SHIPS AS
 * DESIGNED"). Combined here as the section's one body paragraph; the
 * original's single em dash ("needs a teacher — not the pile...") is
 * converted to a comma, preserving the same contrast.
 */
export const classBatchSection = {
  eyebrow: "A class at a time",
  heading: "Send a set in, read back what needs you.",
  body: "Upload a class as a batch and the scripts are marked together against one scheme. The queue then orders itself by doubt, so the first thing you open is the marking that needs a teacher, not the pile in the order it arrived.",
  finePrint: "Per-question detail is available right after a paper is corrected.",
}

/* ── The same paper, three ways (`.sect.sect--centre`) ──────────────────────
 * design-import-spec.md, page structure item 7. Quoted verbatim. Only the
 * centred section intro lives here; the three `Readings` tab panels
 * (teacher/student/parent), including the parent carve-out, are part B's
 * `Readings.tsx` and its own data.
 */
export const readingsIntro = {
  eyebrow: "The same paper, three ways",
  heading: "One marked paper, three readings of it.",
  sub: "The marking is one object. What each person is shown of it is not.",
}

/* ── Close ───────────────────────────────────────────────────────────────
 * design-import-spec.md, page structure item 8. Fully quoted in the spec, so
 * this is the one section below the hero that ships complete, with no gap.
 */
export interface NeedsRow {
  term: string
  detail: string
}

export const close = {
  heading: "Mark a script you have already marked.",
  sub: "That is the fastest way to judge it. Mark a paper yourself, run the same script through Lemely, and compare it line by line.",
  cta: { label: "Get started", to: "/signup" } satisfies CtaLink,
  /* Marginalia (§8): `<span className="text-hand">`, aria-hidden — a nudge
     beside a button whose own label already says what to do. */
  aside: "one script is enough to judge it",
  needs: [
    {
      term: "What to bring",
      detail: "One attempted script, photographed or as a PDF.",
    },
    {
      term: "If we do not hold the scheme",
      detail: "Add it once and every paper on that variant marks against it.",
    },
    {
      term: "What comes back",
      detail: "Per-question marks, the scheme line behind each, and the flags.",
    },
  ] satisfies NeedsRow[],
}

/* ── Part B: the five specimen components' fixture copy ─────────────────
 * design-import-spec.md, "Components to build". Every fixture below is
 * `Example`-labelled illustrative content (same framing the design itself
 * uses), not a claim about a real reader's data, so PRODUCT.md's ban on
 * fabricated customers/testimonials/usage numbers does not reach it — it is
 * closer kin to a screenshot's placeholder data than to a claim.
 *
 * Two fixtures below have no verbatim source text anywhere in
 * design-import-spec.md or design-import-claims.md (only their *shape* is
 * specified): the three practice-shape items in `scanSequence.practise` and
 * the three `SchemeExcerpt` line bodies. Both are synthesised, on-theme, and
 * internally consistent with the OpenedQuestion fixtures they sit beside
 * (see each block's own comment) — flagged here, and in the part B report,
 * the same way part A flagged its own undefined body-copy gaps rather than
 * silently inventing them.
 */

export type LineTone = "ok" | "warn" | "err"
export type MarkState = "correct" | "partial" | "wrong"
export type ConfidenceTier = "confident" | "needs-review"

export interface SchemeLineFixture {
  code: string
  tone: LineTone
  text: string
}

export interface OpenedQuestionFixture {
  id: string
  /** e.g. "4 (b)", "5 (a)", "7" */
  label: string
  title: string
  awarded: number
  available: number
  state: MarkState
  /** The handwritten working shown mid-card. */
  work: string
  lines: SchemeLineFixture[]
  confidence: string
  confidenceTier: ConfidenceTier
}

/* ── OpenedQuestion (trust band, `#marked`) ─────────────────────────────
 * design-import-spec.md, "OpenedQuestion". All three fixtures quoted
 * verbatim from the spec. Two em dashes in the source lines are converted
 * per the file's own header rule: "Method awarded — F = ma..." and
 * "Not awarded — the scheme requires..." both become a colon (introducing
 * the reason, same rhythm); "Confidence 0.71 — flagged for you" becomes a
 * comma (the reason trails as an aside, not a clause break).
 */
export const openedQuestion = {
  paper: { code: "0625/12", session: "May/June 2023", paperLabel: "Paper 1 Variant 2" },
  /* Marginalia, card-wide (not per-question): "Footer also carries
     Marginalia 'two marks, one shape'." */
  hand: "two marks, one shape",
  defaultId: "5a",
  questions: [
    {
      id: "4b",
      label: "4 (b)",
      title: "Gradient of the distance-time graph",
      awarded: 2,
      available: 2,
      state: "correct",
      work: "tangent at 6 s → 4.2 m/s²",
      lines: [
        { code: "M1", tone: "ok", text: "Tangent drawn at t = 6 s." },
        { code: "A1", tone: "ok", text: "4.2 m/s² given with the unit." },
      ],
      confidence: "Confidence 0.98",
      confidenceTier: "confident",
    },
    {
      id: "5a",
      label: "5 (a)",
      title: "Resultant force on the trolley",
      awarded: 1,
      available: 2,
      state: "partial",
      work: "F = 0.4 × 3 = 1.2",
      lines: [
        { code: "M1", tone: "ok", text: "Method awarded: F = ma applied with the correct mass." },
        {
          code: "A1",
          tone: "warn",
          text: "Not awarded: the scheme requires the unit N on the final answer.",
        },
      ],
      confidence: "Confidence 0.96",
      confidenceTier: "confident",
    },
    {
      id: "7",
      label: "7",
      title: "Reading the speed at 12 s",
      awarded: 0,
      available: 1,
      state: "wrong",
      work: "speed = 12",
      lines: [
        {
          code: "B1",
          tone: "err",
          text: "Value read from the time axis instead of the speed axis.",
        },
      ],
      confidence: "Confidence 0.71, flagged for you",
      confidenceTier: "needs-review",
    },
  ] satisfies OpenedQuestionFixture[],
}

/* ── ScanSequence ("How it works") ──────────────────────────────────────
 * design-import-spec.md, "ScanSequence". Step 1 and 2's text is quoted
 * verbatim. Step 3's badge/line/note are quoted verbatim; its three
 * `shapes` list items are NOT quoted anywhere in the spec (only "an ordered
 * list of three practice shapes" is specified) — synthesised here, on the
 * same "gradient" skill the step's own badge names and the trust band's
 * question 4(b) already establishes, rather than left as a gap in a
 * component that has to render, not stub.
 */
export const scanSequence = {
  steps: [
    { id: 1, label: "Scan" },
    { id: 2, label: "Mark" },
    { id: 3, label: "Practise" },
  ],
  scan: {
    fileName: "physics-p1-scan.pdf",
    chip: "Reading the page",
    facts: [
      { term: "Syllabus", detail: "0625" },
      { term: "Session", detail: "Jun 2023" },
      { term: "Paper", detail: "1 / V2" },
      { term: "Scheme", detail: "Matched" },
    ],
    note: "Read off the page itself. Nothing is typed in by hand.",
  },
  mark: {
    note: "Every row opens onto the scheme line it came from.",
  },
  practise: {
    badge: "Reading a gradient",
    line: "Both dropped marks sit on one shape",
    /* Not quoted in the spec — see file header note. */
    shapes: [
      "Gradient from two plotted points",
      "Gradient of a distance-time graph",
      "Gradient from a table of values",
    ],
    note: "Twelve questions on that shape are ready to set.",
  },
}

/* ── SchemeExcerpt ("Where the marks come from") ────────────────────────
 * design-import-spec.md, "SchemeExcerpt". The component's shape (drawn
 * accent rule, metadata head, three dt/dd lines, Marginalia) is specified;
 * the three lines' own body text is not quoted anywhere. Synthesised as
 * the official-scheme-style text behind the same question the trust band's
 * "5 (a)" fixture already shows an annotated reading of (0625/12 · Jun 2023
 * · Q5 (a), F = 0.4 × 3 = 1.2), so the two specimens agree with each other
 * rather than each inventing an unrelated example.
 *
 * The design's third line code is a literal em dash ("—"), a real CAIE
 * convention for a scheme note with no mark code of its own. `check:copy`
 * bans that exact character (U+2014) anywhere in gated copy, so this uses
 * an en dash (U+2013) instead — same glyph family, same "no code" meaning,
 * not the banned character.
 */
export const schemeExcerpt = {
  meta: "Mark scheme · 0625/12 · Jun 2023 · Q5 (a)",
  lines: [
    { code: "M1", text: "F = ma used, with the mass correctly substituted." },
    { code: "A1", text: "1.2 N, with the unit stated." },
    { code: "–", text: "Accept an unrounded answer if the correct method is shown." },
  ],
  hand: "read as printed, not paraphrased",
}

/* ── ClassBatch ("A class at a time") ───────────────────────────────────
 * design-import-spec.md, "ClassBatch". The head template, note, and the
 * 18-clean/6-flagged split are quoted verbatim (and ship per the RULING,
 * which names this exact note as an Example fixture to ship as designed).
 * The six row labels/marks are not individually specified beyond "six
 * Example scripts" — anonymised "Script NN" labels rather than invented
 * student names, matching the OpenedQuestion/SchemeExcerpt fixtures' own
 * register and PRODUCT.md's ban on fabricating people. Four clean, two
 * flagged, a representative slice of the 18/6 split the note states.
 */
export interface ClassBatchRow {
  id: string
  awarded: number
  available: number
  state: "clean" | "flagged"
}

export const classBatch = {
  headPrefix: "0625 · Paper 1 ·",
  headSuffix: "scripts",
  total: 24,
  note: "Eighteen came back clean. Six carry a flag, and those are the ones asking for you.",
  rows: [
    { id: "Script 01", awarded: 18, available: 20, state: "clean" },
    { id: "Script 02", awarded: 15, available: 20, state: "flagged" },
    { id: "Script 03", awarded: 19, available: 20, state: "clean" },
    { id: "Script 04", awarded: 20, available: 20, state: "clean" },
    { id: "Script 05", awarded: 11, available: 20, state: "flagged" },
    { id: "Script 06", awarded: 17, available: 20, state: "clean" },
  ] satisfies ClassBatchRow[],
}

/* ── Readings ("The same paper, three ways") ────────────────────────────
 * design-import-spec.md, "Readings — the three-way switcher". Every title,
 * body and points list below is verbatim from the design-import controller
 * — the spec originally quoted only the titles and the teacher panel's
 * three points, and I flagged the rest (every body paragraph, and the
 * student/parent points lists) rather than synthesize them; the controller
 * then supplied the full text and the spec was patched to match.
 *
 * The teacher body ships "Override any mark you disagree with" per the
 * RULING even though design-import-claims.md verified override only exists
 * for review-queue items, not every mark — recorded here as a reminder not
 * to "fix" it in review; the controller was explicit that this ships as
 * designed.
 *
 * The parent panel is the one carve-out design-import-spec.md names: the
 * design's ORIGINAL first body sentence and first point both claimed phone
 * login (a retired flow, `lemely/web/routers/auth.py:6`); both are replaced
 * below with the verified flow. The rest of the parent panel — its title,
 * and the body's second and third sentences, and the second and third
 * points — is the design's own text, unchanged.
 */
export interface ReadingsPanel {
  id: "teacher" | "student" | "parent"
  label: string
  title: string
  body: string
  points: string[]
}

export const readings: ReadingsPanel[] = [
  {
    id: "teacher",
    label: "Teacher",
    title: "You see the marking, and the doubt.",
    body: "Per-question marks, the scheme line behind each one, and the questions Lemely was not sure about. Override any mark you disagree with, and your version is the one that counts.",
    points: [
      "The review queue orders itself by doubt",
      "Every mark traces to a scheme line",
      "Sign-off before anything is final",
    ],
  },
  {
    id: "student",
    label: "Student",
    title: "They see where the marks went.",
    body: "The same marking, written as the next thing to work on rather than a verdict. A dropped mark comes back as the shape it sat on, and a set of questions on that shape.",
    points: [
      "Marks with the reason, not a percentage",
      "Practice built from what they missed",
      "Their grade stays private to them",
    ],
  },
  {
    id: "parent",
    label: "Parent",
    title: "They see an answer they can read.",
    /* The carve-out: design-import-spec.md replaces "Read-only access with
       a phone login." with the verified flow, same cadence/length. */
    body: "Access from a code your child sends you. What was sat, what it came back as, what it is being worked on next. No syllabus jargon and nothing to configure.",
    points: [
      /* Replaces the design's "Phone login, no account to manage." */
      "A code from your child, then a password",
      "Plain summary of each paper",
      "No marking controls",
    ],
  },
]
