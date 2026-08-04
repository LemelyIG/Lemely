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

/** "What we read from the paper" chips on Correct-a-paper (all 40, neutral). */
export const readChips = studentAnswers.map((ans, i) => ({
  id: i + 1,
  ans,
}))

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
      { to: "/student/result", label: "Paper result" },
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

export interface IntegrityRow {
  mark: "check" | "dash" | "bang"
  color: VizColor
  label: string
  detail: string
}

export interface ResultData {
  code: string
  paper: string
  session: string
  markerLabel: string
  headline: string
  summary: string
  awarded: number
  max: number
  pct: number
  grade: Grade
  boundaryYear: string
  railLeft: number
  railFoot: string
  railNote: string
  integrity: IntegrityRow[]
  provenance: string
}

export const resultP1: ResultData = {
  code: "0625",
  paper: "Paper 1 - Variant 2",
  session: "May/June 2020",
  markerLabel: "deterministic",
  headline: "Thirty-eight out of forty.",
  summary: "Every mark on this paper was awarded by exact match against the official 0625/12 mark scheme - no model judgement involved. Two single-mark questions were dropped.",
  awarded: 38,
  max: 40,
  pct: 95,
  grade: "A",
  boundaryYear: "2020",
  railLeft: 95,
  railFoot: "A boundary sat at 32/40",
  railNote: "Fifteen marks of headroom above the A boundary. Even a bad day keeps you inside the band.",
  integrity: [
    { mark: "check", color: "ok", label: "Mark scheme matched", detail: "0625_s20_ms_12.json - fetched automatically" },
    { mark: "check", color: "ok", label: "No verbatim copying", detail: "Answers checked against the scheme text" },
    { mark: "dash", color: "t2", label: "AI-writing check skipped", detail: "Not applicable to multiple choice" },
    { mark: "check", color: "ok", label: "Extraction verified", detail: "40 / 40 answers above 0.90 confidence" },
  ],
  provenance: "scan: 0625_m20_qp_12_solved.pdf\nreport: outputs/0625/MayJune_2020/\n0625_MayJune_2020_p12__2026-07-27-140214",
}

export const resultP3: ResultData = {
  code: "0625",
  paper: "Paper 3 - Variant 1",
  session: "May/June 2020",
  markerLabel: "hybrid - 14 AI-marked",
  headline: "Sixty-one out of eighty.",
  summary: "Recall and substitution marks are solid. Marks were lost in the final step of multi-stage calculations - the method was right in every case.",
  awarded: 61,
  max: 80,
  pct: 76,
  grade: "B",
  boundaryYear: "2020",
  railLeft: 76,
  railFoot: "A boundary sat at 62/80",
  railNote: "Five marks short of an A - roughly the two dropped in 5(b) and one of the half-life marks.",
  integrity: [
    { mark: "check", color: "ok", label: "Mark scheme matched", detail: "0625_s20_ms_31.json - 12 questions, 80 marks" },
    { mark: "check", color: "ok", label: "No verbatim copying", detail: "0% overlap with scheme wording" },
    { mark: "check", color: "ok", label: "No AI-generated prose detected", detail: "Checked on all extended responses" },
    { mark: "bang", color: "warn", label: "One question escalated", detail: "12(c) at 0.61 confidence - queued for review" },
  ],
  provenance: "scan: 0625_s20_qp_31_maya.pdf\nreport: outputs/0625/MayJune_2020/\n0625_MayJune_2020_p31__2026-07-27-141930",
}

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

/* Paper 1 dropped-marks detail. */
export interface DroppedItem {
  id: string
  you: string
  right: string
  region: string
  note: string
}

export const dropped: DroppedItem[] = [
  { id: "2", you: "A", right: "B", region: "page 2, q2", note: "A distance-time graph read as speed-time. The same slip appears in your November paper - the gradient of a distance-time line is the speed, not the acceleration." },
  { id: "34", you: "C", right: "D", region: "page 17, q34", note: "Half-life counting. You stopped one half-life early; the sample decays through three, not two, over 36 days." },
]

/* Paper 3 theory questions with marking points. */
export interface MarkPoint {
  mark: "check" | "dot"
  id: string
  text: string
  got: boolean
}

export interface TheoryQuestion {
  id: string
  topic: string
  marker: string
  conf: string
  confColor: VizColor
  marks: string
  markOk: boolean
  cardWeak: boolean
  points: MarkPoint[]
  feedback: string
  feedbackTone: "ok" | "accent" | "warn"
}

const mp = (mark: "check" | "dot", id: string, text: string, got: boolean): MarkPoint => ({ mark, id, text, got })

export const theory: TheoryQuestion[] = [
  {
    id: "4(a)", topic: "Motion - speed from distance and time", marker: "AI-marked", conf: "0.94", confColor: "ok", marks: "3/3", markOk: true, cardWeak: false,
    points: [mp("check", "p1", "(s =) d / t in any form", true), mp("check", "p2", "(s =) 200 / 6.4", true), mp("check", "p3", "(s =) 31 (m / s)", true)],
    feedback: "Clean three-step method. Formula stated, substitution shown, answer to two significant figures with the unit - exactly what the C1 C1 A1 structure rewards.",
    feedbackTone: "ok",
  },
  {
    id: "5(b)", topic: "Moments - principle of equilibrium", marker: "AI-marked", conf: "0.78", confColor: "warn", marks: "2/4", markOk: false, cardWeak: false,
    points: [mp("check", "p1", "(sum of) clockwise moments = (sum of) anticlockwise moments", true), mp("check", "p2", "200 = (2.0 x 10) + (F x 60)", true), mp("dot", "p3", "F = (200 - 20) / 60 OR 180 / 60", false), mp("dot", "p4", "(F =) 3.0 (N)", false)],
    feedback: "You set the equation up correctly and then rearranged it wrong - you divided 200 by 60 instead of subtracting the 20 N.cm first. The physics is right; the algebra cost you two marks.",
    feedbackTone: "accent",
  },
  {
    id: "11(b)", topic: "Transformers - turns ratio", marker: "AI-marked", conf: "0.91", confColor: "ok", marks: "3/3", markOk: true, cardWeak: false,
    points: [mp("check", "p1", "Vs / Vp = Ns / Np in any form", true), mp("check", "p2", "(Vs =) (64 x 240) / 960", true), mp("check", "p3", "16 (V)", true)],
    feedback: "Ratio written the right way round on the first attempt - that is the step most candidates lose here.",
    feedbackTone: "ok",
  },
  {
    id: "12(c)", topic: "Radioactivity - half-life", marker: "AI-marked", conf: "0.61", confColor: "warn", marks: "1/3", markOk: false, cardWeak: true,
    points: [mp("check", "p1", "idea of three half-lives", true), mp("dot", "p2", "36 / 8", false), mp("dot", "p3", "4.5 (mg)", false)],
    feedback: "Your working stops after identifying three half-lives, and the handwriting on the final line could not be read with confidence. Sent to Mr Sabry rather than guessed.",
    feedbackTone: "warn",
  },
]

export interface TheoryWeakRow {
  topic: string
  marks: string
  width: number
  color: VizColor
}

export const theoryWeak: TheoryWeakRow[] = [
  { topic: "Moments & equilibrium", marks: "2 lost", width: 50, color: "accent" },
  { topic: "Radioactivity", marks: "2 lost", width: 67, color: "accent" },
  { topic: "Thermal physics", marks: "6 lost", width: 55, color: "accent" },
  { topic: "Electricity & transformers", marks: "1 lost", width: 12, color: "ok" },
]

export interface PaperTab {
  id: "p1" | "p3"
  label: string
}

export const paperTabs: PaperTab[] = [
  { id: "p1", label: "0625/12 - Paper 1" },
  { id: "p3", label: "0625/31 - Theory" },
]

/* ── Correct a paper ────────────────────────────────────────────────────── */

export interface DetectedField {
  k: string
  v: string
}

export const detected: DetectedField[] = [
  { k: "Subject", v: "Physics" },
  { k: "Code", v: "0625" },
  { k: "Session", v: "May/June 2020" },
  { k: "Paper", v: "Paper 1" },
  { k: "Variant", v: "2" },
]

export const scanMeta = {
  filename: "0625_m20_qp_12_solved.pdf",
  detail: "20 pages - uploaded at 14:02 - we recognised this exam from the front page",
  thumbLabel: "scanned page 1",
}

/** Pipeline steps for the Correct-a-paper progress panel. */
export interface ProgressStep {
  title: string
  detail: string
}

export const progressSteps: ProgressStep[] = [
  { title: "Read the front page", detail: "Physics 0625, Paper 1 Variant 2, May/June 2020" },
  { title: "Found the official mark scheme", detail: "The Cambridge scheme for this exact variant" },
  { title: "Read every answer", detail: "All forty came through clearly" },
  { title: "Checked for copying", detail: "Nothing lifted from the mark scheme" },
  { title: "Marked the paper", detail: "38 out of 40 - grade A" },
]

export const reassure: { t: string }[] = [
  { t: "Multiple choice is matched letter for letter against the official Cambridge scheme. No judgement, no model - the same answer key a marker would use." },
  { t: "Written answers are marked point by point, and anything the system is unsure about is handed to you rather than guessed at." },
  { t: "Set your own paper and your own mark scheme, and it will be marked to the same standard." },
]

/* ── Study plan ─────────────────────────────────────────────────────────── */

export interface PlanDay {
  label: string
  date: string
}

export const days: PlanDay[] = [
  { label: "Mon", date: "3" },
  { label: "Tue", date: "4" },
  { label: "Wed", date: "5" },
  { label: "Thu", date: "6" },
  { label: "Fri", date: "7" },
  { label: "Sat", date: "8" },
  { label: "Sun", date: "9" },
]

export type PlanKind = "focus" | "light" | "live" | "empty"

export interface PlanCell {
  title: string
  detail: string
  kind: PlanKind
}

export interface PlanRow {
  time: string
  cells: PlanCell[]
}

const cell = (title: string, detail: string, kind: PlanKind): PlanCell => ({ title, detail, kind })

export const planRows: PlanRow[] = [
  {
    time: "16:00",
    cells: [
      cell("Physics", "moments worksheet - 40 min", "focus"),
      cell("Mr Sabry", "live - Helwan centre", "live"),
      cell("Chemistry", "moles drill - 30 min", "focus"),
      cell("", "", "empty"),
      cell("Physics", "mock paper 4 - 75 min", "focus"),
      cell("", "", "empty"),
      cell("Review", "week recap - 20 min", "light"),
    ],
  },
  {
    time: "18:00",
    cells: [
      cell("Maths", "past paper 0580/42", "light"),
      cell("", "", "empty"),
      cell("Biology", "transport in plants", "light"),
      cell("English", "directed writing", "light"),
      cell("", "", "empty"),
      cell("Flashcards", "48 cards due", "light"),
      cell("", "", "empty"),
    ],
  },
  {
    time: "20:00",
    cells: [
      cell("", "", "empty"),
      cell("Flashcards", "22 cards due", "light"),
      cell("", "", "empty"),
      cell("Chemistry", "quiz - grade C level", "focus"),
      cell("", "", "empty"),
      cell("", "", "empty"),
      cell("Rest", "no blocks scheduled", "light"),
    ],
  },
]

export interface PlanCard {
  kicker: string
  title: string
  body: string
}

export const planCards: PlanCard[] = [
  { kicker: "Why this week", title: "Moments before thermal", body: "Moments appears on both Paper 4 and the alternative-to-practical, so it earns the first slot. Thermal physics moves to next week when Mr Sabry covers it in class." },
  { kicker: "Your inputs", title: "11 hours, two live sessions", body: "You told us Tuesdays and Thursdays are taken by the centre, and that you study best before dinner. Nothing is scheduled after 21:30." },
  { kicker: "Adapting", title: "Rewritten 4 times this month", body: "Every corrected paper reshapes the next fortnight. The Friday mock was added when Chemistry slipped two grades in a week." },
]

export const planHeader = {
  title: "Your week",
  intro: "Built from 11 free hours, five subjects, Mr Sabry's Tuesday session, and the topics you have been losing marks on. It rewrites itself every time a paper is corrected.",
  weekOf: "week of 3 Aug",
}

/* ── Standings (leaderboard) ────────────────────────────────────────────── */

export type LeaderboardScope = "friends" | "school" | "global"

export interface BoardRow {
  rank: string
  name: string
  initials: string
  detail: string
  pts: string
}

export const boards: Record<LeaderboardScope, BoardRow[]> = {
  friends: [
    { rank: "1", name: "Yassin K.", initials: "YK", detail: "8 papers this week", pts: "4,180" },
    { rank: "2", name: "Maya Rahman", initials: "MR", detail: "6 papers this week", pts: "3,940" },
    { rank: "3", name: "Nadine A.", initials: "NA", detail: "5 papers this week", pts: "3,610" },
    { rank: "4", name: "Omar T.", initials: "OT", detail: "4 papers this week", pts: "2,980" },
    { rank: "5", name: "Hana S.", initials: "HS", detail: "3 papers this week", pts: "2,410" },
  ],
  school: [
    { rank: "12", name: "Farid M.", initials: "FM", detail: "Year 11 - 0580 specialist", pts: "5,120" },
    { rank: "13", name: "Layla H.", initials: "LH", detail: "Year 11", pts: "4,860" },
    { rank: "14", name: "Maya Rahman", initials: "MR", detail: "Year 11", pts: "3,940" },
    { rank: "15", name: "Ziad R.", initials: "ZR", detail: "Year 12", pts: "3,880" },
    { rank: "16", name: "Salma E.", initials: "SE", detail: "Year 11", pts: "3,700" },
  ],
  global: [
    { rank: "1,204", name: "Ananya P.", initials: "AP", detail: "Mumbai", pts: "9,340" },
    { rank: "1,205", name: "Tarek B.", initials: "TB", detail: "Amman", pts: "9,180" },
    { rank: "1,206", name: "Maya Rahman", initials: "MR", detail: "Cairo", pts: "3,940" },
    { rank: "1,207", name: "Chidi O.", initials: "CO", detail: "Lagos", pts: "3,905" },
    { rank: "1,208", name: "Wei L.", initials: "WL", detail: "Shenzhen", pts: "3,890" },
  ],
}

export const scopes: { id: LeaderboardScope; label: string }[] = [
  { id: "friends", label: "Friends" },
  { id: "school", label: "School" },
  { id: "global", label: "Global" },
]

/** 28 streak cells: first 4 empty, two banked rest days, rising intensity. */
export interface StreakCell {
  kind: "empty" | "rest" | "active"
  intensity: number
}

export const streakCells: StreakCell[] = Array.from({ length: 28 }, (_, i) => {
  if (i < 4) return { kind: "empty", intensity: 0 }
  if (i === 9 || i === 17) return { kind: "rest", intensity: 0 }
  return { kind: "active", intensity: 0.86 - (i / 28) * 0.16 }
})

export interface SubjectRank {
  code: string
  name: string
  rank: string
  color: VizColor
}

export const subjectRanks: SubjectRank[] = [
  { code: "0580", name: "Mathematics", rank: "#3 of 214", color: "ok" },
  { code: "0625", name: "Physics", rank: "#11 of 198", color: "t1" },
  { code: "0610", name: "Biology", rank: "#24 of 176", color: "t1" },
  { code: "0500", name: "English", rank: "#41 of 230", color: "t2" },
  { code: "0620", name: "Chemistry", rank: "#63 of 188", color: "warn" },
]

export const boardHeader = {
  title: "Standings",
  intro: "Points come from corrected papers and completed plan blocks - not from opening the app.",
  streakTitle: "24-day streak",
  streakSub: "Longest this year. Two rest days banked.",
}

/* ── Onboarding ─────────────────────────────────────────────────────────── */

export const onboardHeader = {
  step: "Step 3 of 5 - about 2 minutes left",
  title: "How does each subject actually feel right now?",
  intro: "Be honest rather than optimistic - the plan is built from this, and nobody else sees it.",
}

/** 5 step segments, first 3 complete. */
export const onboardSteps = [1, 2, 3, 4, 5].map((i) => ({ done: i <= 3 }))

export interface OnboardSlider {
  label: string
  code: string
  word: string
  pct: number
  low: string
  high: string
}

export const sliders: OnboardSlider[] = [
  { label: "Physics", code: "0625", word: "fairly confident", pct: 72, low: "lost", high: "confident" },
  { label: "Chemistry", code: "0620", word: "shaky", pct: 34, low: "lost", high: "confident" },
  { label: "Hours you can actually study each week", code: "", word: "11 hours", pct: 46, low: "2", high: "25" },
  { label: "How exams have been feeling", code: "", word: "some pressure", pct: 58, low: "calm", high: "overwhelming" },
]

export interface OnboardChip {
  label: string
  active: boolean
}

export const onboardChips: OnboardChip[] = [
  { label: "I ran out of time", active: true },
  { label: "I revised the wrong topics", active: true },
  { label: "I understood but lost method marks", active: true },
  { label: "I panicked in the room", active: false },
  { label: "I did not revise much", active: false },
  { label: "I had no plan", active: true },
  { label: "It went fine", active: false },
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
