import { describe, expect, it } from "vitest"
import type { ReviewDecision } from "@/lib/reviewApi"
import { INITIAL_DECISIONS, decisionsReducer } from "@/portals/teacher/screens/review/pendingDecisions"

const accept: ReviewDecision = { kind: "resolve", itemId: "a", label: "Q4(b)", changed: false, body: {} }
const change: ReviewDecision = { kind: "resolve", itemId: "b", label: "Q8", changed: true, body: { overrideMarks: 3 } }
const dismiss: ReviewDecision = { kind: "dismiss", itemId: "c", label: "Q9", body: {} }

describe("decisionsReducer", () => {
  it("hides the row, counts it and makes it undoable", () => {
    const s = decisionsReducer(INITIAL_DECISIONS, { type: "decide", decision: change })
    expect(s.hidden).toEqual(["b"])
    expect(s.undoable).toBe(change)
    expect(s.tally).toEqual({ decided: 1, changed: 1, dismissed: 0 })
    expect(s.notice).toEqual({ kind: "decided", text: "Q8 saved at 3.", undo: true })
  })
  it("undo restores the row and the tally", () => {
    let s = decisionsReducer(INITIAL_DECISIONS, { type: "decide", decision: dismiss })
    expect(s.notice?.text).toBe("Q9 dismissed.")
    s = decisionsReducer(s, { type: "undo" })
    expect(s.hidden).toEqual([])
    expect(s.undoable).toBeNull()
    expect(s.tally).toEqual({ decided: 0, changed: 0, dismissed: 0 })
    expect(s.notice).toBeNull()
  })
  it("starting the commit ends the undo window", () => {
    let s = decisionsReducer(INITIAL_DECISIONS, { type: "decide", decision: accept })
    expect(s.notice?.text).toBe("Q4(b) accepted.")
    s = decisionsReducer(s, { type: "commit-start", decision: accept })
    expect(s.undoable).toBeNull()
    expect(s.hidden).toEqual(["a"])
  })
  it("a failed commit brings the row back with an error", () => {
    let s = decisionsReducer(INITIAL_DECISIONS, { type: "decide", decision: change })
    s = decisionsReducer(s, { type: "commit-start", decision: change })
    s = decisionsReducer(s, { type: "commit-failed", decision: change, message: "Offline." })
    expect(s.hidden).toEqual([])
    expect(s.tally.decided).toBe(0)
    expect(s.notice).toEqual({ kind: "error", text: "Couldn't save Q8. Offline.", undo: false })
  })
  it("a conflict keeps the row hidden but uncounted", () => {
    let s = decisionsReducer(INITIAL_DECISIONS, { type: "decide", decision: accept })
    s = decisionsReducer(s, { type: "commit-conflict", decision: accept })
    expect(s.hidden).toEqual(["a"])
    expect(s.tally.decided).toBe(0)
    expect(s.notice).toEqual({ kind: "info", text: "Q4(b) was already decided.", undo: false })
  })
  it("bulk approval hides and counts every approved id, with no undo", () => {
    const s = decisionsReducer(INITIAL_DECISIONS, { type: "bulk-ok", approved: ["x", "y"], skipped: 1 })
    expect(s.hidden).toEqual(["x", "y"])
    expect(s.tally.decided).toBe(2)
    expect(s.notice).toEqual({ kind: "bulk", text: "2 approved · 1 skipped.", undo: false })
  })
})
