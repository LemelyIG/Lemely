import type { ReviewDecision } from "@/lib/reviewApi"
import type { Tally } from "./reviewQueueModel"

/** The mock's toast lifetimes: 5s for one decision (the undo window), 4s for bulk. */
export const UNDO_WINDOW_MS = 5000
export const BULK_TOAST_MS = 4000

export interface DecisionNotice {
  kind: "decided" | "bulk" | "error" | "info"
  text: string
  undo: boolean
}

export interface DecisionsState {
  /** Rows collapsed in this session: pending, in flight or committed. */
  hidden: string[]
  undoable: ReviewDecision | null
  tally: Tally
  notice: DecisionNotice | null
}

export const INITIAL_DECISIONS: DecisionsState = {
  hidden: [],
  undoable: null,
  tally: { decided: 0, changed: 0, dismissed: 0 },
  notice: null,
}

export type DecisionsAction =
  | { type: "decide"; decision: ReviewDecision }
  | { type: "undo" }
  | { type: "commit-start"; decision: ReviewDecision }
  | { type: "commit-ok"; decision: ReviewDecision }
  | { type: "commit-conflict"; decision: ReviewDecision }
  | { type: "commit-failed"; decision: ReviewDecision; message: string }
  | { type: "bulk-ok"; approved: string[]; skipped: number }
  | { type: "clear-notice" }

function bump(t: Tally, d: ReviewDecision, by: 1 | -1): Tally {
  return {
    decided: t.decided + by,
    changed: t.changed + (d.kind === "resolve" && d.changed ? by : 0),
    dismissed: t.dismissed + (d.kind === "dismiss" ? by : 0),
  }
}

function decidedText(d: ReviewDecision): string {
  if (d.kind === "dismiss") return `${d.label} dismissed.`
  return d.body.overrideMarks != null ? `${d.label} saved at ${d.body.overrideMarks}.` : `${d.label} accepted.`
}

export function decisionsReducer(s: DecisionsState, a: DecisionsAction): DecisionsState {
  switch (a.type) {
    case "decide":
      return {
        ...s,
        hidden: s.hidden.includes(a.decision.itemId) ? s.hidden : [...s.hidden, a.decision.itemId],
        undoable: a.decision,
        tally: bump(s.tally, a.decision, 1),
        notice: { kind: "decided", text: decidedText(a.decision), undo: true },
      }
    case "undo": {
      const d = s.undoable
      if (!d) return s
      return { ...s, hidden: s.hidden.filter((id) => id !== d.itemId), undoable: null, tally: bump(s.tally, d, -1), notice: null }
    }
    case "commit-start":
      return s.undoable?.itemId === a.decision.itemId
        ? { ...s, undoable: null, notice: s.notice ? { ...s.notice, undo: false } : null }
        : s
    case "commit-ok":
      return s
    case "commit-conflict":
      return {
        ...s,
        tally: bump(s.tally, a.decision, -1),
        undoable: s.undoable?.itemId === a.decision.itemId ? null : s.undoable,
        notice: { kind: "info", text: `${a.decision.label} was already decided.`, undo: false },
      }
    case "commit-failed":
      return {
        ...s,
        hidden: s.hidden.filter((id) => id !== a.decision.itemId),
        tally: bump(s.tally, a.decision, -1),
        undoable: s.undoable?.itemId === a.decision.itemId ? null : s.undoable,
        notice: { kind: "error", text: `Couldn't save ${a.decision.label}. ${a.message}`, undo: false },
      }
    case "bulk-ok":
      return {
        ...s,
        hidden: [...s.hidden, ...a.approved.filter((id) => !s.hidden.includes(id))],
        tally: { ...s.tally, decided: s.tally.decided + a.approved.length },
        notice: {
          kind: "bulk",
          text: a.skipped > 0 ? `${a.approved.length} approved · ${a.skipped} skipped.` : `${a.approved.length} approved.`,
          undo: false,
        },
      }
    case "clear-notice":
      return { ...s, notice: null }
  }
}
