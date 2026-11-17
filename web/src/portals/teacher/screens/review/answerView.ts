import type { ReviewItemDetail } from "@/lib/teacherTypes"
import { clampNote, markPointsFrom, type MarkPoint } from "./markModel"
import { isConsolePaperItem, isIntegrityReason } from "./reviewLabels"
import { paperCode, paperLine, questionLabel, ringLabel } from "./reviewQueueModel"

/**
 * Everything the answer panel shows, as plain data. The review queue builds it
 * from `ReviewItemDetail`; L8 builds one from a student's marked question and
 * renders the same `AnswerPanel` read-only (`marking={null}`).
 */
export interface AnswerView {
  key: string
  title: string
  subtitle: string
  studentHref: string | null
  pageLabel: string | null
  hasScan: boolean
  transcription: string | null
  selfReview: { code: string; claim: string; evidence: string | null; judge: string }[]
  scheme: { expected: string | null; topic: string | null }
  notes: { reason: string | null; feedback: string | null }
  points: MarkPoint[]
  matchedPointIds: string[]
  maximumMarks: number | null
  lemelyMarks: number | null
  /** 0..1, for the big confidence ring. Null draws the track only. */
  confidenceScore: number | null
  /** Set whenever Lemely's mark was above the maximum and is shown clamped. */
  clampNote: string | null
  status: "open" | "resolved" | "dismissed"
  integrity: boolean
  canAdjust: boolean
  cannotAdjustReason: string | null
  correction: { marks: number | null; note: string | null; at: string | null } | null
  resolutionNote: string | null
}

const JUDGE: Record<string, string> = {
  accepted: "Lemely's judge agreed",
  rejected: "Lemely's judge disagreed",
  not_required: "No reason needed",
}

export function answerViewFromReviewItem(d: ReviewItemDetail): AnswerView {
  const console = isConsolePaperItem(d)
  const who = console ? "Grading console" : (d.className ?? "")
  const points = markPointsFrom(d.points)
  const codeOf = new Map(points.map((p) => [p.markPointId, p.code]))
  const canAdjust = d.questionResultId != null
  return {
    key: d.itemId,
    title: `${d.studentDisplayName} · ${questionLabel(d)}`,
    subtitle: [who, paperLine(d), ringLabel(d.confidenceScore)].filter(Boolean).join(" · "),
    studentHref: !console && d.studentId ? `/teacher/students/${d.studentId}` : null,
    pageLabel: d.hasSourceBox && d.sourcePage != null ? `Page ${d.sourcePage} · ${paperCode(d) ?? "scan"}` : null,
    hasScan: d.hasSourceBox,
    transcription: d.studentAnswer,
    selfReview: d.points
      .filter((p) => p.studentSelfmark !== null)
      .map((p) => ({
        code: codeOf.get(p.markPointId) ?? p.markPointId,
        claim: p.studentSelfmark ? "Claims earned" : "Claims not earned",
        evidence: p.studentEvidence,
        judge: p.evidenceVerdict ? (JUDGE[p.evidenceVerdict] ?? p.evidenceVerdict) : "Not yet judged",
      })),
    scheme: { expected: d.expectedAnswer, topic: d.topic },
    notes: { reason: d.reviewReason, feedback: d.feedback },
    points,
    matchedPointIds: d.matchedPointIds,
    maximumMarks: d.maximumMarks,
    lemelyMarks: d.aiAwardedMarks,
    confidenceScore: d.confidenceScore,
    clampNote: clampNote(d.aiAwardedMarks, d.maximumMarks),
    status: d.status === "resolved" || d.status === "dismissed" ? d.status : "open",
    integrity: isIntegrityReason(d.reason),
    canAdjust,
    cannotAdjustReason: canAdjust
      ? null
      : console
        ? "Papers marked in the grading console store no per-question result to record a new mark on. Accept as-is, or re-run the paper from the console."
        : "No mark data on this item to adjust",
    correction: d.isOverridden ? { marks: d.teacherAwardedMarks, note: d.teacherNote, at: d.overriddenAt } : null,
    resolutionNote: d.resolutionNote,
  }
}
