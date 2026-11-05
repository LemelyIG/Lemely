/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { ClassSummary, Overview } from "@/lib/teacherTypes"

/**
 * A UI nudge, not a product rule: below this many students on a class roster the
 * home suggests sharing the join code. Nothing in the backend enforces it.
 */
export const ROSTER_NUDGE = 10

export type UnlockKey = "average" | "weakest" | "trend" | "atrisk"

export interface Unlock {
  key: UnlockKey
  title: string
  done: boolean
  /** What makes it appear, shown while it is still locked. */
  how: string
}

export type NextKind = "create" | "share" | "upload" | "second" | "class"

export interface NextAction {
  kind: NextKind
  title: string
  /** The sentence that says what the action buys the teacher. */
  body: string
  cta: string
  /** Route for create and upload actions. */
  to?: string
  /** Join code to copy, for the share action. */
  code?: string
}

export interface GrowthModel {
  unlocks: Unlock[]
  /** The single best next action, or null when there is nothing left to suggest. */
  next: NextAction | null
  /** Every unlock is done and there is no next action. */
  complete: boolean
}

const has = (n: number | null | undefined): n is number => typeof n === "number" && Number.isFinite(n)

/** A trend is computable once any class has two marked papers to compare. */
export const hasTrends = (classes: Pick<ClassSummary, "delta">[]): boolean => classes.some((c) => has(c.delta))

export function growthModel(
  classes: Pick<ClassSummary, "id" | "label" | "studentCount" | "joinCode" | "average" | "topWeakness" | "delta">[],
  overview: Pick<Overview, "paperCount" | "atRisk">,
): GrowthModel {
  const trends = hasTrends(classes)
  const unlocks: Unlock[] = [
    { key: "average", title: "Class average and grade", done: classes.some((c) => has(c.average)), how: "Mark your first paper." },
    { key: "weakest", title: "Weakest topic for each class", done: classes.some((c) => !!c.topWeakness), how: "Shows once marked answers are sorted by topic." },
    { key: "trend", title: "Trend since the last paper", done: trends, how: "Needs a second marked paper for the same class." },
    { key: "atrisk", title: "At-risk alerts", done: trends || overview.atRisk.length > 0, how: "These follow from trends, so a second marked paper comes first." },
  ]

  let next: NextAction | null = null
  const thin = classes.find((c) => c.studentCount < ROSTER_NUDGE && !!c.joinCode)
  if (classes.length === 0) {
    next = { kind: "create", title: "Create your first class", body: "A class gives you a join code and a place for every paper you mark.", cta: "Create a class", to: "/teacher/first-class" }
  } else if (thin) {
    const n = thin.studentCount
    next = {
      kind: "share",
      title: `Share the join code for ${thin.label}`,
      body: `${n} ${n === 1 ? "student has" : "students have"} joined so far. Averages, weak topics and trends get more useful with every student who joins.`,
      cta: "Copy join code",
      code: thin.joinCode!,
    }
  } else if (overview.paperCount === 0) {
    next = { kind: "upload", title: "Upload your first papers", body: "One marked paper shows you the class average and grade, and the weakest topic.", cta: "Upload papers", to: "/teacher/grading" }
  } else if (!trends) {
    next = { kind: "second", title: "Upload a second paper", body: "Trends compare each paper with the one before it. A second marked paper turns them on, and at-risk alerts follow.", cta: "Upload a paper", to: "/teacher/grading" }
  } else if (classes.length === 1) {
    next = { kind: "class", title: "Add another class", body: "Each class gets its own average, weakest topic and trend, so you can compare them side by side.", cta: "Create a class", to: "/teacher/first-class" }
  }

  return { unlocks, next, complete: next === null && unlocks.every((u) => u.done) }
}
