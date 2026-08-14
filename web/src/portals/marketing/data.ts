/*
 * Marketing copy for the Persuade lane (DESIGN.md §2).
 *
 * ────────────────────────────────────────────────────────────────────────────
 * THE RULE THIS FILE EXISTS TO ENFORCE
 * ────────────────────────────────────────────────────────────────────────────
 * PRODUCT.md's "Evidence on Hand" closes with the list of things that must not
 * be fabricated: **no customers, no testimonials, no case studies, no press,
 * no pricing, no live deployment, no usage numbers, no partner schools.**
 *
 * DESIGN-AUDIT C1/C2/C3 applied that rule to the two places it was easiest to
 * see — the proof band's statistics and the pricing tiers — and stopped there.
 * P4.9 found the rest of it, and the pattern is worth stating because it will
 * recur: **the audit deleted the numbers and left the sentences.** Six claims
 * were still live on the page after C1/C2/C3 were closed:
 *
 *   1. `cardMeta` read "marked in 41s". That is the *exact figure* C1 deleted
 *      from the proof band for having no source. It was removed from one slot
 *      and left standing in another, four sections up the same file.
 *   2. The hero footnote read "Free for every student of a partnered teacher -
 *      No card to start". Partner schools are named in PRODUCT.md's must-not-
 *      fabricate list, and this promised both a partner programme and a
 *      billing arrangement, sitting a screen above the placeholder that says
 *      pricing is genuinely undecided. That is C2's fabrication, in prose.
 *   3. "QR attendance with face or 2FA check". There is no QR code, no facial
 *      check and no 2FA anywhere in this repository, and
 *      `lemely/web/schemas_teacher.py:7` records attendance itself as a screen
 *      field with **no backend source**.
 *   4. "Lesson retention down to the replayed minute". Same file, same line:
 *      `retention` is structurally empty by construction.
 *   5. "Results by WhatsApp the moment marking ends". WhatsApp appeared
 *      nowhere in the product except this sentence. Notifications are web push
 *      and an in-app inbox (`lemely/web/routers/notifications.py`).
 *   6. "Course payments in the same place". PRODUCT.md:74 puts payment
 *      processing out of scope outright.
 *
 * Every bullet below now names something a reader can go and use, and carries
 * the module that implements it. A claim with no such comment does not belong
 * in this file. When a feature ships, add it here *with* its source.
 */

export const landingHero = {
  eyebrow: "For CAIE teachers and their students",
  /*
   * Kept from the build era, deliberately, while its neighbours went. This is
   * a statement of the job the product is for (taking a teacher's Sunday back)
   * rather than a measurement: no unit, no rate, nothing that claims to have
   * been observed. The lines around it are what had to change.
   */
  titleTop: "Thirty papers marked",
  titleBottom: "before Sunday lunch.",
  /*
   * "pulls the official mark scheme" was the previous wording and it was not
   * true. `resolve_mark_scheme` (`lemely/web/routers/student.py:616`) has
   * exactly two sources: a `mark_scheme.pdf` uploaded beside the scan, or a
   * scheme already parsed into the local cache. There is no download path in
   * the codebase (BLOCKERS.md B1 established this). "Marks it against" is the
   * claim that survives, because that part is true however the scheme arrived.
   */
  body: "Lemely reads a scanned paper, works out the session and variant, and marks it against the official Cambridge mark scheme question by question, showing its working and its confidence for every mark it gives.",
  /* "Mark a paper free" was the old label. Pricing is undecided, so "free" is
     a pricing claim the product cannot make. The action is the same. */
  primaryCta: "Mark a paper",
  secondaryCta: "For centres and teachers",
  /*
   * The replacement for the partner-teacher fabrication. It says the one true
   * reassuring thing in its place: there is no billing to walk into, because
   * payment processing does not exist yet (PRODUCT.md:74).
   */
  footnote: "Lemely is still being built. There is no pricing yet, and no card to enter.",
}

/*
 * The hero's result card. **Labelled as an example, in the card itself**, and
 * that label is not decoration: a marked script showing 38/40 in a hero reads
 * as somebody's real result, and the product has no customers whose result it
 * could be. `exampleLabel` renders as a tag on the card, not as a caption
 * underneath it, so it cannot be cropped away from the number it qualifies.
 */
export const heroExample = {
  exampleLabel: "Example",
  meta: "0625 / Paper 1 Variant 2 / May-June 2020",
  score: "38",
  max: "/40",
  grade: "A",
  note: "Two marks dropped, both on reading a distance-time gradient. The practice set that follows is twelve questions of that one shape.",
}

/* ── The example script's answer grid ───────────────────────────────────── */

/*
 * Forty answers, of which the scheme disagrees with two. Moved here from
 * `portals/student/data.ts` with the rest of the landing block: it is
 * illustrative marketing content, and it had no consumer inside the student
 * portal at all.
 *
 * The two disagreements are what make the card internally consistent — the
 * grid renders exactly two cells in the dropped tone, the score reads 38/40,
 * and `heroExample.note` says "two marks dropped". A hero whose picture and
 * whose number disagree is the same defect class as the parent portal's card
 * that printed "1d ago" above "2 days ago", and it is worth keeping the three
 * derived from one source so they cannot drift apart.
 */
const studentAnswers = [
  "A", "A", "A", "D", "C", "D", "A", "A", "B", "C",
  "B", "B", "D", "A", "A", "C", "A", "C", "B", "A",
  "D", "A", "A", "A", "C", "D", "C", "A", "A", "D",
  "D", "D", "A", "C", "B", "C", "B", "B", "A", "B",
] as const

// The scheme differs from the student on Q2 and Q34 (two dropped marks).
const expectedAnswers = studentAnswers.map((a, i) => (i === 1 ? "B" : i === 33 ? "D" : a))

export interface McqCell {
  id: number
  ans: string
  correct: boolean
  title: string
}

export const mcq: McqCell[] = studentAnswers.map((ans, i) => ({
  id: i + 1,
  ans,
  correct: ans === expectedAnswers[i],
  title: `Q${i + 1}, you answered ${ans}, the scheme says ${expectedAnswers[i]}`,
}))

/* ── The loop (§2's "the loop" section) ─────────────────────────────────── */

export interface LoopStep {
  step: string
  title: string
  body: string
}

/*
 * Three steps, each one a route that exists today:
 *   1. `/student/correct` -> `lemely/web/routers/student.py` (upload + mark).
 *   2. The marked paper's per-mark-point breakdown and topic classification.
 *   3. `/student/practice/:code`, `/student/flashcards/:code`,
 *      `/student/plan/:code` -> `practice.py`, `flashcards.py`,
 *      `study_plan.py`.
 */
export const loopIntro = {
  title: "One paper in, three things out",
  body: "The marking is not the end of it. The same corrected script becomes the thing you practise next, the thing you revise, and the week you have planned.",
}

export const loopSteps: LoopStep[] = [
  {
    step: "01",
    title: "Upload the script",
    body: "A photo or a scan of the paper, with its mark scheme. Lemely identifies the syllabus, session and variant from the page itself.",
  },
  {
    step: "02",
    title: "Read the marking",
    body: "Every mark is traced to a mark point, with the working that earned it and a confidence score beside it. Anything the marker is unsure of is flagged rather than quietly counted.",
  },
  {
    step: "03",
    title: "Work on what fell over",
    body: "Dropped marks are classified by topic, and the topics become a practice set, a flashcard deck and a study plan you can actually work through.",
  },
]

/* ── Who it serves ──────────────────────────────────────────────────────── */

export interface Pillar {
  kicker: string
  title: string
  body: string
  bullets: string[]
}

/*
 * Every bullet here traces to a shipped route. The five that did not are
 * listed in this file's header with the reason each one went.
 */
export const pillars: Pillar[] = [
  {
    kicker: "Student",
    title: "Feedback that names the next move",
    body: "Every dropped mark is traced to a mark point and a topic, and the topics turn into questions that look exactly like the ones that fell over.",
    bullets: [
      // `BoundaryBar` (C-3) against the scraped CAIE grade-boundary table.
      "A predicted grade against real Cambridge boundaries",
      // routers/practice.py and routers/flashcards.py.
      "Practice sets and flashcard decks built from your own weak topics",
      // routers/study_plan.py.
      "A study plan by week, with the sessions laid out",
    ],
  },
  {
    kicker: "Teacher",
    title: "A class you can see through",
    body: "The marking runs while you do something else, and what comes back is a class you can read: who is falling, and which topic the whole room got wrong.",
    bullets: [
      // routers/review.py + REVIEW_CONFIDENCE_THRESHOLD. The floor is 0.90 and
      // is not operator-tunable.
      "Every mark below the confidence floor queued for your eye, never guessed",
      // routers/teacher.py, at-risk by trajectory (not by a single result).
      "Students whose trajectory is falling, surfaced before the exam",
      // routers/quiz.py. `_pool_count_message` exists precisely so the builder
      // reports an empty pool honestly rather than silently producing nothing.
      "A quiz builder that tells you how many questions the pool really holds",
    ],
  },
  {
    kicker: "Parent",
    title: "One honest answer",
    body: "A phone number is the whole login. No account to keep, no password to lose, and the same marked paper the teacher is looking at.",
    bullets: [
      // routers/auth.py OTP flow, /login/parent. No password is ever set.
      "A phone number and a code, and you are in",
      // routers/parent.py: children, overview, subject drilldown.
      "Grades by subject, without waiting for a parent-teacher meeting",
      // routers/parent.py weaknesses endpoint.
      "The topics that need work, named",
    ],
  },
]

/* ── Proof band ─────────────────────────────────────────────────────────── */

export const landingProofIntro = {
  title: "Accuracy you can argue with",
  body: "Multiple choice is marked deterministically, with no model involved at all. Theory answers are marked against the official mark points, and every mark carries a confidence score. Anything below the floor goes to a teacher rather than being guessed at.",
}

export interface ProofStat {
  n: string
  l: string
}

/*
 * Every number here must be traceable to a constant in this repo. Nothing on
 * this band is a measurement, an average, or a projection — those need a
 * published method before they can be shown to a prospective user.
 *
 * Removed 2026-08-13 (DESIGN-AUDIT C1) because they had no source at all:
 *   "41s"   median time to mark a 40-question paper
 *   "19.5h" saved per teacher, per month
 * The accuracy harness (`reports/accuracy-real/REPORT.md`) is n=1 per paper
 * across two papers, which is a test result, not a marketing statistic, so it
 * is deliberately not substituted in here either.
 *
 * Also corrected: the confidence floor read "0.70", which was simply the wrong
 * number — the human-review threshold is 0.90 and is not operator-tunable.
 *
 * P4.9 note: "41s" was deleted from this list in C1 and left live in the hero
 * card's metadata line, where it survived until this surface. Deleting a
 * figure from the place it was noticed is not the same as deleting the claim.
 */
export const proof: ProofStat[] = [
  // `lemely/core/correction.py::correct_mcq_answers` compares against the
  // official answer key deterministically; `lemely/io/integrity.py` skips both
  // integrity checks for MCQ, so no Gemini call is made on this path at all.
  { n: "0", l: "model calls on multiple choice" },
  // `lemely/core/schemas.py::REVIEW_CONFIDENCE_THRESHOLD`.
  { n: "0.90", l: "confidence floor before a teacher is asked to look" },
  // `GeminiSettings.escalation_confidence_threshold`, lemely/runtime/config.py.
  { n: "0.80", l: "confidence below which a stronger model re-marks first" },
]

/* ── Plans ──────────────────────────────────────────────────────────────── */

export interface PricingPlan {
  name: string
  price: string
  who: string
  dark: boolean
  feats: string[]
  cta: string
  ctaAccent: boolean
}

/*
 * Emptied 2026-08-13 (DESIGN-AUDIT C2). The three tiers shipped here carried
 * four separate fabrications on two lines: a price ("EGP 180"), a trial that
 * has never existed ("Start 14-day trial"), a partner-teacher free tier, and a
 * marketplace revenue-share arrangement. PRODUCT.md records pricing as
 * explicitly undecided, payments as out of scope, and partner schools among
 * the things that must not be fabricated.
 *
 * Kept as an empty list rather than deleted outright so the section keeps its
 * slot on the page: Landing renders `pricingPlaceholder` while this is empty,
 * and the moment real pricing is decided it goes back in here with no layout
 * work. The `PricingPlan` shape above is retained for that reason.
 */
export const pricing: PricingPlan[] = []

export const pricingPlaceholder = {
  label: "Not announced",
  title: "We have not set a price yet",
  body: "Lemely is still being built, and what it costs is genuinely undecided. When there is a plan to show you it will appear here. There is no trial to sign up for in the meantime.",
}

/* ── Close ──────────────────────────────────────────────────────────────── */

export const landingClose = {
  title: "Bring one paper",
  body: "Upload a script and its mark scheme, and read the marking back. That is the whole of the first go.",
  cta: "Mark a paper",
  /* Marginalia (§8). Decorative: removing it costs the page nothing. */
  aside: "one script is enough to judge it",
}
