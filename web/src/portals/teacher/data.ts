/*
 * Teacher portal stub data, ported 1:1 from the Claude Design mock's
 * renderVals() (design/project/Lemely Teacher.dc.html). Real names and numbers
 * are preserved. `Quizzes.tsx` (T-09, not yet built against a backend —
 * P3.8) is the only screen still rendering from this file.
 *
 * P3.7 chunk B moved Overview/Classes onto real data and deleted the mock
 * arrays only they consumed: `recentClasses` (sidebar), `classStats`/
 * `mastery`/`distribution`/`bubble`/`students` (the old Classes.tsx, which
 * actually rendered T-03/T-04 one-class analytics content, not a T-02
 * classes list) — none of it is a Quizzes.tsx dependency, so nothing here
 * was left behind for a screen this chunk doesn't own.
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
  icon: "overview" | "grading" | "classes" | "atRisk" | "schemes" | "quizzes"
  /** Index route match (Overview lives at /teacher). */
  end?: boolean
}

export const navItems: NavItem[] = [
  { to: "/teacher", label: "Overview", icon: "overview", end: true },
  { to: "/teacher/grading", label: "Grading", icon: "grading" },
  { to: "/teacher/classes", label: "Classes", icon: "classes" },
  { to: "/teacher/at-risk", label: "At-risk students", icon: "atRisk" },
  { to: "/teacher/schemes", label: "Mark schemes", icon: "schemes" },
  { to: "/teacher/quizzes", label: "AI quizzes", icon: "quizzes" },
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
