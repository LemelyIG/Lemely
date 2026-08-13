/*
 * Student portal stub data, ported 1:1 from the Claude Design mock's
 * renderVals() (design/project/Lemely Student.dc.html). Names, numbers and copy
 * are the real content. The mock's raw CSS vars / oklch values are translated to
 * the shared token layer where a semantic token exists; genuine one-off data-viz
 * colours are kept as arbitrary Tailwind classes. Frontend-first: screens render
 * from these constants, no live fetch.
 */

/** Semantic colour keys used by data-viz rows/bars, resolved to tokens per use. */
export type VizColor = "accent" | "ok" | "warn" | "t1" | "t2" | "t3"

/* ── MCQ answer grid (Paper 1) ─────────────────────────────────────────── */

const studentAnswers = [
  "A", "A", "A", "D", "C", "D", "A", "A", "B", "C",
  "B", "B", "D", "A", "A", "C", "A", "C", "B", "A",
  "D", "A", "A", "A", "C", "D", "C", "A", "A", "D",
  "D", "D", "A", "C", "B", "C", "B", "B", "A", "B",
] as const

// The scheme differs from the student on Q2 and Q34 (two dropped marks).
const expectedAnswers = studentAnswers.map((a, i) =>
  i === 1 ? "B" : i === 33 ? "D" : a,
)

export interface McqCell {
  id: number
  ans: string
  correct: boolean
  title: string
}

export const mcq: McqCell[] = studentAnswers.map((ans, i) => {
  const correct = ans === expectedAnswers[i]
  return {
    id: i + 1,
    ans,
    correct,
    title: `Q${i + 1} - you: ${ans} - scheme: ${expectedAnswers[i]}`,
  }
})

/* ── Sidebar nav groups ─────────────────────────────────────────────────── */

export interface NavItem {
  to: string
  label: string
  tag?: string
  end?: boolean
}

export interface NavGroup {
  label: string
  items: NavItem[]
}

export const navGroups: NavGroup[] = [
  {
    label: "Student",
    items: [
      { to: "/student", label: "Overview", end: true },
      { to: "/student/subject/0625", label: "Physics", tag: "0625" },
      { to: "/student/practice/0625", label: "Practice", tag: "0625" },
      { to: "/student/flashcards/0625", label: "Flashcards", tag: "0625" },
      { to: "/student/plan/0625", label: "Study plan", tag: "0625" },
      { to: "/student/board", label: "Standings" },
      { to: "/student/friends", label: "Friends" },
      { to: "/student/profile", label: "Your profile" },
      { to: "/student/announcements", label: "Announcements" },
      { to: "/student/parents", label: "Your parents" },
    ],
  },
  {
    label: "Marking",
    items: [{ to: "/student/correct", label: "Correct a paper" }],
  },
  {
    label: "Elsewhere",
    items: [
      { to: "/student/onboard", label: "Onboarding" },
      { to: "/student/landing", label: "Landing page" },
      { to: "/student/directions", label: "Directions", tag: "A/B/C" },
    ],
  },
]

/** Breadcrumb per route path (matches the mock's crumb map). */
export const crumbs: Record<string, string> = {
  "/student": "Home",
  "/student/subject": "Home / Physics 0625",
  "/student/practice": "Home / Practice",
  "/student/flashcards": "Home / Flashcards",
  "/student/result": "Home / Physics / Paper result",
  "/student/correct": "Marking / Correct a paper",
  // `/student/plan` is deliberately absent: P4.10 made the route
  // subject-scoped (`/student/plan/:subjectCode`), so it is resolved by a
  // pattern arm in `resolveCrumb` alongside practice and flashcards. Leaving
  // the bare key here would be a lookup no pathname can ever hit.
  "/student/board": "Home / Standings",
  "/student/friends": "Home / Friends",
  "/student/profile": "Home / Your profile",
  "/student/announcements": "Home / Announcements",
  "/student/parents": "Home / Your parents",
  "/student/onboard": "Onboarding",
  "/student/landing": "lemely.com",
  "/student/directions": "Design directions",
}

/**
 * Resolve the breadcrumb for a pathname: exact static lookup first (the
 * `crumbs` map), falling back to pattern matching for routes with a dynamic
 * segment that can't be enumerated in that map ahead of time.
 *
 * Lives here rather than in `index.tsx` so it is a pure function the unit
 * suite can exercise. It was unreachable from a test while it sat inside the
 * React module, which is how P4.10's subject-scoped `/student/plan/:code`
 * came to fall through every arm and render a bare "Home": a wrong-but-valid
 * breadcrumb trips no typecheck, no axe rule and no threshold.
 */
export function resolveCrumb(pathname: string): string {
  const exact = crumbs[pathname]
  if (exact) return exact

  const subjectMatch = pathname.match(/^\/student\/subject\/([^/]+)$/)
  if (subjectMatch) return `Home / ${subjectMatch[1]}`

  const resultMatch = pathname.match(/^\/student\/result\/([^/]+)$/)
  if (resultMatch) return `Home / Result ${resultMatch[1]}`

  const practiceGeneratorMatch = pathname.match(/^\/student\/practice\/([^/]+)$/)
  if (practiceGeneratorMatch) return `Home / Practice / ${practiceGeneratorMatch[1]}`

  if (pathname.match(/^\/student\/practice\/set\//)) return "Home / Practice / Set"
  if (pathname.match(/^\/student\/practice\/result\//)) return "Home / Practice / Result"
  if (pathname.match(/^\/student\/practice\/print\//)) return "Home / Practice / Print"

  const flashcardReviewMatch = pathname.match(/^\/student\/flashcards\/review\/([^/]+)$/)
  if (flashcardReviewMatch) return `Home / Flashcards / Review ${flashcardReviewMatch[1]}`

  const flashcardDecksMatch = pathname.match(/^\/student\/flashcards\/([^/]+)$/)
  if (flashcardDecksMatch) return `Home / Flashcards / ${flashcardDecksMatch[1]}`

  // The study plan gained a subject segment in P4.10, so it stopped matching
  // the exact `crumbs` lookup and fell through to the bare "Home" default.
  // The session route needs its own arm for the same reason: `planMatch` is
  // anchored, so S-25 would have repeated the chunk-A defect exactly.
  const planSessionMatch = pathname.match(/^\/student\/plan\/([^/]+)\/session\/([^/]+)$/)
  if (planSessionMatch) return `Home / Study plan / ${planSessionMatch[1]} / Session`

  const planMatch = pathname.match(/^\/student\/plan\/([^/]+)$/)
  if (planMatch) return `Home / Study plan / ${planMatch[1]}`

  return "Home"
}

// `studentName`/`studentMeta` ("Maya Rahman" / "Year 11 - Helwan Science
// Centre") were removed in P3.10 chunk c. They were the student-side twin of
// the fabricated teacher identity P3.7 chunk b deleted, and no field anywhere
// in the API supplies either one. The sidebar now renders the real caller via
// `useProfile()` — see `UserBlock` in `portals/student/index.tsx`.

/* ── Paper Result (flagship) ────────────────────────────────────────────── */

export interface RailTick {
  g: string
  left: number
}

export const railTicks: RailTick[] = [
  { g: "U", left: 6 },
  { g: "E", left: 24 },
  { g: "D", left: 38 },
  { g: "C", left: 52 },
  { g: "B", left: 66 },
  { g: "A", left: 80 },
]

/* ── Correct a paper ────────────────────────────────────────────────────── */

export const reassure: { t: string }[] = [
  { t: "Multiple choice is matched letter for letter against the official Cambridge scheme. No judgement, no model - the same answer key a marker would use." },
  { t: "Written answers are marked point by point, and anything the system is unsure about is handed to you rather than guessed at." },
  { t: "Set your own paper and your own mark scheme, and it will be marked to the same standard." },
]

/* ── Landing ────────────────────────────────────────────────────────────── */

export const landingHero = {
  eyebrow: "For CAIE teachers and their students",
  titleTop: "Thirty papers marked",
  titleBottom: "before Sunday lunch.",
  body: "Lemely reads a scanned paper, identifies the session and variant, pulls the official mark scheme, and marks it question by question - showing its working, and its confidence, for every mark it gives.",
  primaryCta: "Mark a paper free",
  secondaryCta: "For centres & teachers",
  footnote: "Free for every student of a partnered teacher - No card to start",
  cardMeta: "0625/12 - May/June 2020 - marked in 41s",
  cardScore: "38",
  cardMax: "/40",
  cardGrade: "A",
  cardNote: "Two marks dropped, both on interpreting a distance-time gradient. A worksheet of twelve similar questions is already waiting.",
}

export interface Pillar {
  kicker: string
  title: string
  body: string
  bullets: string[]
}

export const pillars: Pillar[] = [
  { kicker: "Student", title: "Feedback that names the next move", body: "Every dropped mark is traced to a mark point and a topic, then turned into a worksheet of questions that look exactly like it.", bullets: ["Predicted grade against real boundaries", "Classified worksheets and flashcards", "A study plan that rewrites itself"] },
  { kicker: "Teacher", title: "A group you can see through", body: "At-risk students surface by trajectory. Class-wide weak topics surface before the exam, not after it.", bullets: ["Marking that takes minutes, not Sundays", "Lesson retention down to the replayed minute", "QR attendance with face or 2FA check"] },
  { kicker: "Parent", title: "One honest answer", body: "A phone number is the whole login. Grades, attendance and payments, without a parent-teacher meeting.", bullets: ["Results by WhatsApp the moment marking ends", "Missed-attendance alert one hour after class", "Course payments in the same place"] },
]

export const landingProofIntro = {
  title: "Accuracy you can argue with",
  body: "Multiple choice is marked deterministically - no model involved. Theory answers are marked against the official mark points, and every mark carries a confidence score. Anything below threshold goes to the teacher rather than being guessed.",
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

export const pillarsIntro = {
  title: "One engine, three people served",
  body: "The same corrected paper becomes a study plan for the student, a teaching signal for the teacher, and a plain answer for the parent who asks \"how is she doing?\"",
}

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

/* ── Directions (A/B/C) ─────────────────────────────────────────────────── */

export const directionsIntro = {
  title: "Three ways to open a result",
  body: "The result header is the emotional moment of the product - it is the screen a student opens after a mock. The app now uses A and B together: the ledger reading, with the boundary rail underneath it. C is kept here as the softest alternative.",
}
