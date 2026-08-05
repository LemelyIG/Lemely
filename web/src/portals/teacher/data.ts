/*
 * Teacher portal stub data, ported 1:1 from the Claude Design mock's
 * renderVals() (design/project/Lemely Teacher.dc.html). Real names and numbers
 * are preserved. Screens render from this file; no live fetch in this run.
 *
 * Colour semantics map to the shared token layer:
 *   accent (amber), ok (green), err (red / needs-review), t1/t2/t3 (text).
 * One-off oklch values from the mock that no token covers are kept inline via
 * arbitrary Tailwind classes at the call site, not here.
 */

import type { Grade } from "@/lib/types"

/* ── Sidebar ─────────────────────────────────────────────────────────────── */

export interface NavItem {
  to: string
  label: string
  /** Which phosphor icon renders in the sidebar. */
  icon: "overview" | "grading" | "classes" | "schemes" | "quizzes"
  /** Red count badge (Grading only in the mock). */
  badge?: string
  /** Index route match (Overview lives at /teacher). */
  end?: boolean
}

export const navItems: NavItem[] = [
  { to: "/teacher", label: "Overview", icon: "overview", end: true },
  { to: "/teacher/grading", label: "Grading", icon: "grading", badge: "12" },
  { to: "/teacher/classes", label: "Classes", icon: "classes" },
  { to: "/teacher/schemes", label: "Mark schemes", icon: "schemes" },
  { to: "/teacher/quizzes", label: "AI quizzes", icon: "quizzes" },
]

export interface RecentClass {
  label: string
  active: boolean
}

export const recentClasses: RecentClass[] = [
  { label: "Y11 · Physics", active: true },
  { label: "Y10 · Physics", active: false },
  { label: "Y11 · Chemistry", active: false },
]

/* ── Shared stat card ────────────────────────────────────────────────────── */

export interface StatCard {
  k: string
  v: string
  unit?: string
  foot?: string
  /** Semantic colour of the big number. */
  valueTone?: "t1" | "accent" | "err"
  /** Semantic colour of the footnote. */
  footTone?: "t2" | "ok" | "err"
}

/* ── Review (AI grading) ─────────────────────────────────────────────────── */

export type PointState = "ok" | "no" | "dep"

export interface MarkingPoint {
  code: string
  text: string
  note?: string
  conf: string
  award: string
  state: PointState
}

export interface WorkingLine {
  t: string
  /** Highlight the ambiguous line in red. */
  flagged: boolean
}

export interface FlaggedItem {
  initials: string
  name: string
  q: string
  page: string
  qLabel: string
  prompt: string
  working: WorkingLine[]
  marks: string
  conf: string
  /** 0-100 width for the confidence bar. */
  confW: number
  total: string
  points: MarkingPoint[]
  why: string
}

export const flagged: FlaggedItem[] = [
  {
    initials: "JA",
    name: "Jonas Akinyi",
    q: "Q5(b)",
    page: "Page 7",
    qLabel: "5 (b)",
    prompt:
      "The beam is in equilibrium. Calculate the force F applied at the 60 cm mark.",
    working: [
      { t: "clockwise = anticlockwise", flagged: false },
      { t: "200 = (2.0 x 10) + (F x 60)", flagged: false },
      { t: "F = 200 / 60", flagged: true },
      { t: "= 3.3 N", flagged: false },
    ],
    marks: "2/4",
    conf: "78%",
    confW: 78,
    total: "4 marks total",
    points: [
      { code: "C1", text: "(sum of) clockwise moments = (sum of) anticlockwise moments", conf: "97%", award: "+1", state: "ok" },
      { code: "C1", text: "200 = (2.0 x 10) + (F x 60)", conf: "95%", award: "+1", state: "ok" },
      { code: "C1", text: "F = (200 - 20) / 60 OR 180 / 60", note: "Student divided 200 by 60", conf: "88%", award: "0", state: "no" },
      { code: "A1", text: "(F =) 3.0 (N)", note: "Depends on the previous mark point - cannot award", conf: "78%", award: "0", state: "dep" },
    ],
    why: 'The student subtracted nothing before dividing, but the written line is ambiguous - "200" may be a corrected "180". The mark scheme requires the subtraction to be seen. Award C1 only if you read the original as 180.',
  },
  {
    initials: "DP",
    name: "Daniel Park",
    q: "Q12(c)",
    page: "Page 15",
    qLabel: "12 (c)",
    prompt:
      "The half-life of the source is 12 days. Calculate the mass remaining after 36 days.",
    working: [
      { t: "36 / 12 = 3 half-lives", flagged: false },
      { t: "36 / 6", flagged: true },
      { t: "= 6 mg", flagged: false },
    ],
    marks: "1/3",
    conf: "61%",
    confW: 61,
    total: "3 marks total",
    points: [
      { code: "C1", text: "idea of three half-lives", conf: "94%", award: "+1", state: "ok" },
      { code: "C1", text: "36 / 8", note: "Student wrote 36 / 6 - halved three times incorrectly", conf: "71%", award: "0", state: "no" },
      { code: "A1", text: "4.5 (mg)", note: "Answer given as 6 mg", conf: "61%", award: "0", state: "no" },
    ],
    why: "Handwriting on the divisor is unclear at 300 dpi - the character reads as either 6 or 8. If it is an 8, both remaining marks are earned. Sent to you rather than guessed.",
  },
  {
    initials: "AC",
    name: "Amelia Chen",
    q: "Q6(c)(ii)",
    page: "Page 9",
    qLabel: "6 (c) (ii)",
    prompt:
      "Explain why the two plates must be placed at equal distances from the heater.",
    working: [
      { t: "so the test is fair", flagged: false },
      { t: "both get the same heat", flagged: true },
    ],
    marks: "1/2",
    conf: "64%",
    confW: 64,
    total: "2 marks total",
    points: [
      { code: "B1", text: "(for a valid comparison all independent) variables must be the same", note: '"so the test is fair" - accepted as owtte', conf: "82%", award: "+1", state: "ok" },
      { code: "B1", text: "plates / discs should be equal distances (from heater) (owtte)", note: "Distance is never named explicitly", conf: "64%", award: "0", state: "no" },
    ],
    why: 'The second mark point needs distance to be stated. "Both get the same heat" implies it without saying it - this is exactly the kind of borderline wording a marker should decide, not a model.',
  },
]

export interface QueueRow {
  initials: string
  name: string
  meta: string
  conf: string
  marks: string
  /** Index into `flagged` this row opens. */
  target: number
}

export const queue: QueueRow[] = [
  { initials: "AC", name: "Amelia Chen", meta: "Q6(c)(ii) · Thermal", conf: "64%", marks: "1/2", target: 2 },
  { initials: "JA", name: "Jonas Akinyi", meta: "Q5(b) · Moments", conf: "78%", marks: "2/4", target: 0 },
  { initials: "YT", name: "Yuki Tanaka", meta: "Q8(a)(ii) · Waves", conf: "81%", marks: "0/1", target: 0 },
  { initials: "PS", name: "Priya Shah", meta: "Q3(a)(i) · Thermal", conf: "84%", marks: "1/2", target: 2 },
  { initials: "DP", name: "Daniel Park", meta: "Q12(c) · Radioactivity", conf: "61%", marks: "1/3", target: 1 },
]

export const reviewProgress = {
  autoGraded: "156 / 168",
  percent: 93,
  note: "93% AT CONFIDENCE >= 0.90",
}

/* ── Classes ─────────────────────────────────────────────────────────────── */

export const classStats: StatCard[] = [
  { k: "Class average", v: "74", unit: "%", foot: "+5.2 since May", valueTone: "t1", footTone: "ok" },
  { k: "Predicted A / A*", v: "11", unit: "of 24", foot: "46% of the group", valueTone: "t1", footTone: "t2" },
  { k: "At risk", v: "3", unit: "students", foot: "below D", valueTone: "err", footTone: "err" },
  { k: "Hours saved", v: "38", unit: "this month", foot: "auto-graded", valueTone: "t1", footTone: "t2" },
]

export interface MasteryRow {
  topic: string
  val: number
  nat: number
  /** Below the national average -> render red instead of amber. */
  below: boolean
}

export const mastery: MasteryRow[] = [
  ["Kinematics", 88, 84],
  ["Forces", 82, 80],
  ["Waves", 71, 74],
  ["Electricity", 76, 75],
  ["Atomic physics", 64, 70],
  ["Thermal physics", 58, 73],
].map(([topic, val, nat]) => ({
  topic: topic as string,
  val: val as number,
  nat: nat as number,
  below: (val as number) < (nat as number),
}))

export type DistributionTone = "ok" | "accent" | "b" | "err" | "muted"

export interface DistributionBar {
  g: Grade
  n: number
  /** 0-100 height percentage. */
  h: number
  tone: DistributionTone
}

const DIST: [Grade, number][] = [
  ["A*", 4],
  ["A", 7],
  ["B", 6],
  ["C", 4],
  ["D", 2],
  ["E", 1],
  ["U", 0],
]

export const distribution: DistributionBar[] = DIST.map(([g, n]) => ({
  g,
  n,
  h: Math.max(2, (n / 7) * 100),
  tone:
    g === "A*"
      ? "ok"
      : g === "A"
        ? "accent"
        : g === "B"
          ? "b"
          : g === "E"
            ? "err"
            : "muted",
}))

export interface BubbleStudent {
  name: string
  to: Grade
}

export const bubble: BubbleStudent[] = [
  { name: "Jonas A", to: "A" },
  { name: "Yuki T", to: "A" },
  { name: "Lina H", to: "A*" },
]

export interface StudentRow {
  name: string
  initials: string
  grade: Grade
  mark: string
  delta: string
  weak: string
  /** Falling delta -> red, otherwise green. */
  deltaDown: boolean
  /** D / E grades render the grade in red. */
  gradeAtRisk: boolean
}

function student(
  name: string,
  grade: Grade,
  mark: string,
  delta: string,
  weak: string,
): StudentRow {
  return {
    name,
    grade,
    mark,
    delta,
    weak,
    initials: name
      .split(" ")
      .map((w) => w[0])
      .join(""),
    deltaDown: delta.charAt(0) === "-",
    gradeAtRisk: grade === "D" || grade === "E",
  }
}

export const students: StudentRow[] = [
  student("Amelia Chen", "A*", "71/80", "+4", "Atomic physics"),
  student("Priya Shah", "A", "68/80", "+2", "Waves"),
  student("Yuki Tanaka", "A", "64/80", "+6", "Thermal physics"),
  student("Jonas Akinyi", "B", "58/80", "-1", "Moments"),
  student("Lina Hassan", "B", "56/80", "+3", "Thermal physics"),
  student("Daniel Park", "C", "49/80", "-5", "Radioactivity"),
  student("Ziad Rafik", "D", "38/80", "-13", "Thermal physics"),
]

/* ── AI quizzes ──────────────────────────────────────────────────────────── */

export type Difficulty = "E/D" | "C" | "B" | "A" | "A*"

export const difficulties: Difficulty[] = ["E/D", "C", "B", "A", "A*"]

export const difficultyNote =
  "Lemely will pick questions Yuki, Lina and Jonas are predicted to score 60-80% on."

/** Predicted class average per target difficulty. */
export const predictedAvg: Record<Difficulty, string> = {
  "E/D": "58%",
  C: "64%",
  B: "69%",
  A: "72%",
  "A*": "78%",
}

/** Default topic selections (1 = on) from the mock's initial state. */
export const defaultTopics: Record<string, boolean> = {
  "Specific heat capacity": true,
  "Latent heat": true,
  "Kinetic theory": true,
  "Conduction & convection": false,
  "Thermal expansion": false,
}

export interface QuestionPool {
  key: "past" | "ai" | "mine"
  label: string
  detail: string
}

export const pools: QuestionPool[] = [
  { key: "past", label: "Past papers · 2018-2024", detail: "472 questions · CAIE official" },
  { key: "ai", label: "AI-generated", detail: "Stylistically matched to CAIE" },
  { key: "mine", label: "My uploads", detail: "0 questions · upload .docx" },
]

/** Default pool selections from the mock's initial state. */
export const defaultPools: Record<QuestionPool["key"], boolean> = {
  past: true,
  ai: true,
  mine: false,
}

export interface PreviewQuestion {
  n: string
  source: string
  src: "past" | "ai"
  grade: Grade
  marks: number
  text: string
}

export const preview: PreviewQuestion[] = [
  { n: "Q1", source: "past · 0625/41 M22 Q3", src: "past", grade: "A", marks: 4, text: "A 0.50 kg copper block cools from 80 °C to 25 °C. Calculate the energy released." },
  { n: "Q2", source: "ai · CAIE-styled", src: "ai", grade: "B", marks: 2, text: "State what is meant by the specific latent heat of fusion." },
  { n: "Q3", source: "past · 0625/42 W23 Q5(b)", src: "past", grade: "A", marks: 3, text: "Explain, in terms of kinetic theory, why sweating cools the body." },
  { n: "Q4", source: "ai · CAIE-styled", src: "ai", grade: "A*", marks: 3, text: "Two metal blocks of equal mass receive the same energy. Block A rises further in temperature. What does this tell you about the two specific heat capacities?" },
]

/** ~2.5 min per question, matching the mock's estMinutes. */
export function estMinutes(qLen: number): string {
  return "~" + Math.round(qLen * 2.5) + " min"
}
