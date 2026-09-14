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
 * P4.9 found the rest of it: the audit deleted the numbers and left the
 * sentences, and six claims were still live on the page after C1/C2/C3 were
 * closed. `marketing.test.ts`'s `bannedClaims` block pins every one of them so
 * they cannot reappear.
 *
 * Every bullet below now names something a reader can go and use. A claim
 * with no such comment does not belong in this file. When a feature ships,
 * add it here *with* its source.
 *
 * ── The proof band (deleted 2026-09) ───────────────────────────────────────
 * `proof` and `landingProofIntro` are gone. Their numbers (model-call count,
 * confidence floor, escalation threshold) are true and traceable, but they
 * read as a marketing statistic rather than as anything a 15-year-old visitor
 * can act on, and the redesign's honest-copy rule is narrower than "true": it
 * is "true, and worth a stranger's attention". Nothing replaces this band.
 */

export const landingHero = {
  eyebrow: "For CAIE IGCSE",
  /*
   * Role-neutral on purpose: the old hero named "teachers and their
   * students" before a reader had chosen which one they were. `BUILD/BRAND.md`
   * §5's own tagline candidate, used near-verbatim because it already passes
   * the voice test: specific, no hype word, and it is the actual benefit
   * rather than a description of the category.
   */
  headline: "Know where the marks went.",
  /*
   * `resolve_mark_scheme` (`lemely/web/routers/student.py:765`) has exactly
   * two sources: a `mark_scheme.pdf` uploaded beside the scan, or a scheme
   * already parsed into the local cache. "Checked against" is the claim that
   * survives however the scheme arrived.
   */
  subtext: "You upload a scanned paper. Every mark is checked against the official Cambridge mark scheme.",
  /* Object, not a bare string: the label is copy, the route is a fact about
     the product, and later work (Landing.tsx, Task 2) needs both. */
  primaryCta: { label: "Get started", to: "/signup" },
  /* Scrolls to the "how it works" section rather than navigating anywhere.
     `anchor` names the section id Task 2 wires this to. */
  secondaryCta: { label: "See how it works", anchor: "how-it-works" },
}

/*
 * The hero's result card. **Labelled as an example, in the card itself**, and
 * that label is not decoration: a marked script showing 38/40 in a hero reads
 * as somebody's real result, and the product has no customers whose result it
 * could be. `exampleLabel` renders as a tag on the card, not as a caption
 * underneath it, so it cannot be cropped away from the number it qualifies.
 *
 * Untouched by this rewrite: `marketing.test.ts` pins the 38/40 score, the 40
 * cells, the two dropped marks at Q2/Q34, and the "two marks dropped" note as
 * one consistent fact derived from `studentAnswers` below.
 */
export const heroExample = {
  exampleLabel: "Example",
  /*
   * Was "0625 / Paper 1 Variant 2 / May-June 2020". The mobile judge (Task
   * 2, evaluator run `ralph` iteration 2, AC-12) flagged "Variant" as
   * unglossed CAIE jargon for a 15-year-old, and a one-clause gloss ("the
   * second version of this paper") would make the meta line longer than the
   * fact is worth. Cutting the variant number is the honest fix: which of
   * the several variants this script is does not change what the card
   * demonstrates, and nothing in `marketing.test.ts` pins the old string.
   */
  meta: "0625 / Paper 1 / May-June 2020",
  score: "38",
  max: "/40",
  grade: "A",
  note: "Two marks dropped, both on reading a distance-time gradient. The practice that follows is built from that one shape.",
}

/* ── The example script's answer grid ───────────────────────────────────── */

/*
 * Forty answers, of which the scheme disagrees with two. Illustrative
 * marketing content: the two disagreements are what make the card internally
 * consistent, so score, grid and note are derived from one source and cannot
 * drift apart.
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

/* ── The loop / "How it works" ──────────────────────────────────────────── */

export interface LoopStep {
  step: string
  title: string
  body: string
}

/*
 * Three steps, each one a route that exists today:
 *   1. `/student/correct` -> `lemely/web/routers/student.py` (upload + mark).
 *   2. The marked paper's per-mark-point breakdown, working shown.
 *   3. `/student/practice/:code` -> `practice.py`, built from dropped marks.
 *
 * `step` used to hold "01"/"02"/"03". A verb reads better than a number and
 * needs no legend, so it carries the label instead.
 */
export const loopIntro = {
  title: "How it works",
  body: "One scan becomes the marking, the working behind it, and practice on what you missed.",
}

export const loopSteps: LoopStep[] = [
  {
    step: "Scan",
    title: "Lemely works out which paper it is",
    body: "A photo or a PDF works. Add the mark scheme if we do not have it yet.",
  },
  {
    step: "Mark",
    title: "See it marked against the real scheme",
    body: "Every mark is checked against the official Cambridge mark scheme, and the working is shown for each one.",
  },
  {
    step: "Practise",
    title: "Work on what you dropped",
    body: "The questions you missed become the next set you practise.",
  },
]

/* ── Who it serves ──────────────────────────────────────────────────────── */

export interface RoleTab {
  id: string
  label: string
  heading: string
  body: string
  cta: { label: string; to: string }
}

/*
 * Replaces `pillars`. Each register below traces to a shipped route:
 *   student -> `/signup/student`, and the marking loop above.
 *   parent  -> `/join`, the same destination the persistent header's own
 *              "Parents" link already uses (a parent account only ever comes
 *              from a child-issued invite, never from `/login`).
 *   teacher -> `/signup/teacher`, `teacher_paper_repo.py`'s low-confidence
 *              review queue (below `REVIEW_CONFIDENCE_THRESHOLD`, marks at or
 *              above it count unless flagged for structural review).
 */
export const roleTabs: RoleTab[] = [
  {
    id: "student",
    label: "Student",
    heading: "See exactly where the marks went",
    body: "Scan your paper on your phone. Get it marked against the real scheme, and practise the questions you dropped.",
    cta: { label: "Mark a paper", to: "/signup/student" },
  },
  {
    id: "parent",
    label: "Parent",
    heading: "See how your child is doing",
    body: "Your child sends you a code. Set a password, and see their grades and the topics that need work.",
    cta: { label: "Get parent access", to: "/join" },
  },
  {
    id: "teacher",
    label: "Teacher",
    heading: "Marking cited to the scheme, not guessed",
    body: "Every mark is cited to the official scheme. Anything the marker is unsure of comes to you instead of being guessed. The marking runs while you do something else.",
    cta: { label: "Mark a set", to: "/signup/teacher" },
  },
]

/*
 * I-1/I-6: the "who it serves" section intro and the "Subjects covered"
 * heading, moved here from `Landing.tsx` so every visible string on the page
 * is gated by `marketing.test.ts`'s `allCopy` check. Both are plain
 * restatements of what the roles/subjects data below already says.
 */
export const rolesIntro = {
  title: "One marked paper, three people it helps",
  body: "The student gets a study plan. The teacher gets a signal. The parent gets an answer.",
}

/* ── Subjects covered ───────────────────────────────────────────────────── */

export interface Subject {
  code: string
  name: string
}

export const subjectsTitle = "Subjects covered"

export const subjects: Subject[] = [
  { code: "0580", name: "Mathematics" },
  { code: "0606", name: "Additional Mathematics" },
  { code: "0625", name: "Physics" },
]

export const subjectsNote = "More subjects are coming."

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
 * Emptied 2026-08-13 (DESIGN-AUDIT C2) and still empty. PRODUCT.md records
 * pricing as explicitly undecided and payments as out of scope. Kept as an
 * empty list rather than deleted outright so the section keeps its slot on
 * the page: Landing renders `pricingPlaceholder` unconditionally while this
 * is empty (Task 4, F3/F3a), and `marketing.test.ts`'s
 * `expect(pricing).toHaveLength(0)` is what now enforces that, not a runtime
 * branch in the component.
 *
 * Task 3 left a second render path in `Landing.tsx` — a three-equal-card grid
 * for a populated `pricing` — reachable only once this array stopped being
 * empty. That is the exact card-grid family Task 3 exists to have removed
 * from the page, sitting dead in the branch the judge cannot see, and it
 * would have appeared the day a plan shipped with no one deciding to put it
 * there. It is gone (Task 4, F3): the moment real pricing is decided, the
 * layout for it gets designed then, deliberately, and it will not be three
 * equal cards.
 */
export const pricing: PricingPlan[] = []

/*
 * Section furniture, not placeholder content. `pricingTitle` is the section's
 * `<h2>` and is true in both states pricing can be in: undecided (today) or
 * decided (later, with `pricing` populated and its own layout designed then).
 * It used to be bound to `pricingPlaceholder.title` ("No price yet"), which
 * meant populating `pricing` left "No price yet" rendered directly above a
 * grid of priced tiers — a false heading, on the one page whose banner
 * comment in `Landing.tsx` exists because an earlier audit "deleted the
 * numbers and left the sentences" (Task 4, F2). A heading is state-neutral;
 * binding it to the empty state made the page's structure a function of its
 * own emptiness.
 */
export const pricingTitle = "What it costs"

/*
 * Folds in the "Lemely is still being built" line the hero used to carry as
 * its footnote: this is the one place on the page a reader expects to be
 * told what something costs, so it is the honest place to say nothing is
 * decided yet rather than the hero, which is about the product, not billing.
 *
 * Both fields render inside the section, under the stable `pricingTitle`
 * heading above — `title` as the direct statement ("No price yet"), `body`
 * as the one sentence of context. Neither is an eyebrow: the section's old
 * "Plans" kicker and the "Not announced" chip this used to carry alongside
 * the heading are both gone, and nothing replaces them, so this section still
 * spends none of the page's two-eyebrow allowance (BUILD/BRAND.md §5).
 */
export const pricingPlaceholder = {
  title: "No price yet",
  body: "Lemely is still being built. Nothing to pay while we build it.",
}

/* ── Close ──────────────────────────────────────────────────────────────── */

export const landingClose = {
  title: "Bring one paper",
  body: "Upload a script and read the marking back.",
  cta: "Get started",
  /* Marginalia (§8). Decorative: removing it costs the page nothing. */
  aside: "one script is enough to judge it",
}
