import type { Overview } from "@/lib/teacherTypes"

export interface SetupProgress {
  created: boolean
  uploaded: boolean
  reviewed: boolean
  done: number
  complete: boolean
}

type Status = "pending" | "error" | "success"
export type HomeView = "loading" | "error" | "setup" | "overview"

export function teacherHomeView(
  classesStatus: Status, classCount: number, overviewStatus: Status,
  overview: Pick<Overview, "paperCount" | "pendingReviewCount"> | undefined,
): HomeView {
  if (classesStatus === "error" || overviewStatus === "error") return "error"
  if (classesStatus === "pending" || overviewStatus === "pending" || !overview) return "loading"
  const s = deriveSetup(classCount, overview)
  return s.created && s.uploaded ? "overview" : "setup"
}

/** Setup steps derived from account data only (spec: no tracking field, no localStorage). */
export function deriveSetup(classCount: number, overview: Pick<Overview, "paperCount" | "pendingReviewCount">): SetupProgress {
  const created = classCount > 0
  const uploaded = overview.paperCount > 0
  const reviewed = uploaded && overview.pendingReviewCount === 0
  const done = [created, uploaded, reviewed].filter(Boolean).length
  return { created, uploaded, reviewed, done, complete: done === 3 }
}
