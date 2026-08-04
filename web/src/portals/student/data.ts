/*
 * Student portal stub data, ported 1:1 from the Claude Design mock's
 * renderVals() (design/project/Lemely Student.dc.html). Names, numbers and copy
 * are the real content. The mock's raw CSS vars / oklch values are translated to
 * the shared token layer where a semantic token exists; genuine one-off data-viz
 * colours are kept as arbitrary Tailwind classes. Frontend-first: screens render
 * from these constants, no live fetch.
 */

import type { Grade, Tone } from "@/lib/types"

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
      { to: "/student/plan", label: "Study plan" },
      { to: "/student/board", label: "Standings" },
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
  "/student/result": "Home / Physics / Paper result",
  "/student/correct": "Marking / Correct a paper",
  "/student/plan": "Home / Study plan",
  "/student/board": "Home / Standings",
  "/student/onboard": "Onboarding",
  "/student/landing": "lemely.com",
  "/student/directions": "Design directions",
}

export const studentName = "Maya Rahman"
export const firstName = studentName.split(" ")[0]
export const studentMeta = "Year 11 - Helwan Science Centre"

/* ── Overview ───────────────────────────────────────────────────────────── */

export interface SubjectRow {
  code: string
  name: string
  detail: string
  pct: number
  papers: number
  trend: string
  grade: Grade
  barColor: VizColor
  trendUp: boolean
}

export const subjects: SubjectRow[] = [
  { code: "0625", name: "Physics", detail: "Extended - Mr Sabry - 7 papers corrected", pct: 81, papers: 7, trend: "+6", grade: "A" },
  { code: "0580", name: "Mathematics", detail: "Extended - self-study - 9 papers corrected", pct: 91, papers: 9, trend: "+2", grade: "A*" },
  { code: "0620", name: "Chemistry", detail: "Extended - Ms Farida - 6 papers corrected", pct: 68, papers: 6, trend: "-4", grade: "B" },
  { code: "0610", name: "Biology", detail: "Extended - Ms Farida - 5 papers corrected", pct: 84, papers: 5, trend: "+1", grade: "A" },
  { code: "0500", name: "First Language English", detail: "Ms Amal - 4 papers corrected", pct: 72, papers: 4, trend: "+3", grade: "B" },
].map((x) => ({
  ...x,
  grade: x.grade as Grade,
  barColor: (x.pct >= 80 ? "ok" : x.pct >= 70 ? "accent" : "warn") as VizColor,
  trendUp: x.trend.charAt(0) !== "-",
}))

export const overviewForecast = "A A B A* B"

export interface NextUpItem {
  badge: string
  title: string
  body: string
}

export const nextUp: NextUpItem[] = [
  { badge: "5b", title: "Rearranging moment equations", body: "You lose the final mark on equilibrium questions four times out of five. Twelve targeted questions are ready." },
  { badge: "0620", title: "Chemistry is drifting", body: "Down four points across two papers, all in mole calculations. Worth twenty minutes on Wednesday." },
  { badge: "Q34", title: "Distance-time gradients", body: "The same misread appeared in your last two Paper 1 attempts." },
]

export interface AgendaItem {
  when: string
  what: string
  tag: string
  tone: Tone
}

export const agenda: AgendaItem[] = [
  { when: "Mon", what: "Physics classified worksheet - moments", tag: "plan", tone: "neutral" },
  { when: "Tue", what: "Mr Sabry - live session, Helwan centre", tag: "class", tone: "accent" },
  { when: "Wed", what: "Chemistry quiz - 0620 moles, grade C level", tag: "quiz", tone: "warn" },
  { when: "Fri", what: "Mock Paper 4 - 0625 - 75 minutes", tag: "mock", tone: "neutral" },
]

/* Momentum sparkline: percentage per corrected paper, all subjects. */
const momentumSeries = [64, 68, 66, 72, 70, 75, 79, 74, 81, 84, 88, 95]
const mx = (i: number) => (i / (momentumSeries.length - 1)) * 300
const my = (v: number) => 88 - ((v - 55) / 45) * 78
const momentumPath = momentumSeries
  .map((v, i) => `${i ? "L" : "M"}${mx(i).toFixed(1)} ${my(v).toFixed(1)}`)
  .join(" ")

export const momentum = {
  path: momentumPath,
  area: `${momentumPath} L300 88 L0 88 Z`,
  lastX: mx(momentumSeries.length - 1).toFixed(1),
  lastY: my(momentumSeries[momentumSeries.length - 1]).toFixed(1),
  labels: ["Feb", "Apr", "Jun", "now"],
}

export interface WeakThread {
  topic: string
  acc: string
  width: number
  color: VizColor
}

export const weakGlobal: WeakThread[] = [
  { topic: "Thermal physics", acc: "54%", width: 54, color: "accent" },
  { topic: "Moles & stoichiometry", acc: "61%", width: 61, color: "accent" },
  { topic: "Waves", acc: "72%", width: 72, color: "warn" },
  { topic: "Electricity", acc: "86%", width: 86, color: "ok" },
]

export const igCalculator = {
  title: "IG Calculator",
  target: "Target: Engineering, Cairo University",
  projected: "88.4%",
  note: "You clear the 85% threshold with 3.4 points of headroom. Losing a grade in Chemistry drops you to 83.1% - below the line.",
}

/* ── Subject (Physics) ──────────────────────────────────────────────────── */

export interface PaperBar {
  value: number
  label: string
  highlight: boolean
}

export interface PaperBreakdown {
  title: string
  sub: string
  mean: string
  boundary: string
  position: string
  positionOk: boolean
  bars: PaperBar[]
}

const makeBars = (values: number[]): PaperBar[] =>
  values.map((v, i) => ({ value: v, label: `p${i + 1}`, highlight: i === values.length - 1 }))

export const papersBreakdown: PaperBreakdown[] = [
  { title: "Paper 1", sub: "multiple choice - 40 marks", mean: "92%", boundary: "A >= 32/40", position: "38/40 - A", positionOk: true, bars: makeBars([78, 84, 80, 88, 90, 92, 95]) },
  { title: "Paper 4", sub: "extended theory - 80 marks", mean: "73%", boundary: "A >= 62/80", position: "61/80 - B", positionOk: false, bars: makeBars([62, 68, 64, 71, 70, 76, 76]) },
]

export interface PaperHistoryRow {
  paper: string
  note: string
  marks: string
  pct: string
  grade: Grade
  gradeColor: VizColor
  /** which result sub-view to open when the row is clicked */
  tab: "p1" | "p3"
}

export const paperHistory: PaperHistoryRow[] = [
  { paper: "0625/12 - s20", note: "Multiple choice - deterministic", marks: "38/40", pct: "95%", grade: "A", gradeColor: "ok", tab: "p1" },
  { paper: "0625/31 - s20", note: "Theory core - 1 question escalated", marks: "61/80", pct: "76%", grade: "B", gradeColor: "accent", tab: "p3" },
  { paper: "0625/42 - w24", note: "Extended theory", marks: "58/80", pct: "73%", grade: "B", gradeColor: "accent", tab: "p1" },
  { paper: "0625/62 - w24", note: "Alternative to practical", marks: "48/60", pct: "80%", grade: "A", gradeColor: "ok", tab: "p1" },
  { paper: "0625/11 - w23", note: "Multiple choice - deterministic", marks: "33/40", pct: "83%", grade: "A", gradeColor: "ok", tab: "p1" },
  { paper: "0625/41 - w23", note: "Extended theory - teacher-adjusted", marks: "52/80", pct: "65%", grade: "C", gradeColor: "warn", tab: "p1" },
]

export interface TopicTile {
  name: string
  acc: string
  color: VizColor
  weak: boolean
}

export const topicMap: TopicTile[] = [
  { name: "Motion & forces", acc: "88%", color: "ok", weak: false },
  { name: "Density & pressure", acc: "81%", color: "ok", weak: false },
  { name: "Moments", acc: "58%", color: "accent", weak: true },
  { name: "Thermal physics", acc: "54%", color: "accent", weak: true },
  { name: "Waves", acc: "72%", color: "warn", weak: false },
  { name: "Light", acc: "79%", color: "warn", weak: false },
  { name: "Electricity", acc: "86%", color: "ok", weak: false },
  { name: "Radioactivity", acc: "63%", color: "accent", weak: true },
]

export const subjectHeader = {
  meta: "0625 - Physics - Extended",
  title: "Physics",
  intro: "Seven papers corrected across two sessions. Paper 1 is comfortably ahead of Paper 4 - the gap is almost entirely in extended-response marks, not recall.",
  forecast: "A",
  weightedMean: "81",
  weightedMeanDelta: "+6 since May",
}

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

export const proof: ProofStat[] = [
  { n: "41s", l: "median time to mark a 40-question paper" },
  { n: "0", l: "model calls on multiple choice" },
  { n: "0.70", l: "confidence floor before a human is asked" },
  { n: "19.5h", l: "saved per teacher, per month" },
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

export const pricing: PricingPlan[] = [
  { name: "Student", price: "Free", who: "Everything you need to mark your own practice papers.", dark: false, feats: ["5 papers a month", "Grade prediction", "Weakness report", "Basic study plan"], cta: "Start free", ctaAccent: false },
  { name: "Student Plus", price: "EGP 180", who: "Per month. Free for every student of a partnered teacher.", dark: true, feats: ["Unlimited papers", "Classified worksheets and flashcards", "Adaptive study plan", "Marketplace booking"], cta: "Start 14-day trial", ctaAccent: true },
  { name: "Teacher & Centre", price: "Revenue share", who: "No fee. Lemely takes a cut of marketplace bookings only.", dark: false, feats: ["Free Plus for all your students", "Automated correction and custom schemes", "CMS, sub-accounts, QR attendance", "Payments and course booking"], cta: "Talk to us", ctaAccent: false },
]

/* ── Directions (A/B/C) ─────────────────────────────────────────────────── */

export const directionsIntro = {
  title: "Three ways to open a result",
  body: "The result header is the emotional moment of the product - it is the screen a student opens after a mock. The app now uses A and B together: the ledger reading, with the boundary rail underneath it. C is kept here as the softest alternative.",
}
