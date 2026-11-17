import { describe, expect, it } from "vitest"
import type { ReviewQueueItem } from "@/lib/teacherTypes"
import { EMPTY_FILTERS } from "@/lib/reviewQueueQuery"
import {
  CLEAR_CONFIDENCE,
  SORT_OPTIONS,
  binnyFor,
  bulkButton,
  clearedSummary,
  clearFilters,
  filterCategories,
  filterChips,
  filterValues,
  headerTitle,
  isClearItem,
  marksLost,
  nextFocusAfter,
  overlayOpen,
  focusAfterDecision,
  paperLine,
  plainWhy,
  positionOf,
  progressOf,
  queueScreenState,
  removeFilter,
  ringLabel,
  ringText,
  ringTone,
  ringValue,
  rowSubtitle,
  selectable,
  sessionShort,
  shownLine,
  sortLabel,
  toggleFilter,
} from "@/portals/teacher/screens/review/reviewQueueModel"

function item(over: Partial<ReviewQueueItem> = {}): ReviewQueueItem {
  return {
    itemId: "i1",
    source: "student_attempt",
    attemptId: "a1",
    paperId: null,
    questionResultId: "qr1",
    studentId: "s1",
    studentDisplayName: "Layla Hassan",
    classId: "c1",
    className: "10B",
    subjectCode: "0580",
    paperNumber: 4,
    paperVariant: 2,
    sessionMonth: "May/June",
    sessionYear: 2025,
    questionId: "4(b)",
    reason: "low_confidence",
    status: "open",
    createdAt: "2026-11-14T10:00:00Z",
    waitingHours: 3,
    aiAwardedMarks: 4,
    maximumMarks: 5,
    confidenceScore: 0.64,
    reviewReason: null,
    ...over,
  }
}

const OPTS = {
  classes: [
    { id: "c1", label: "10B" },
    { id: "c2", label: "11C" },
  ],
  subjects: ["0580", "0625"],
  subjectName: (code: string) => ({ "0580": "Mathematics", "0625": "Physics" })[code] ?? code,
}

describe("ring", () => {
  it("is red under 70%, gold from 70%, neutral without a score", () => {
    expect(CLEAR_CONFIDENCE).toBe(0.7)
    expect(ringTone(0.69)).toBe("warn")
    expect(ringTone(0.7)).toBe("gold")
    expect(ringTone(null)).toBe("neutral")
  })
  it("shows a whole percent, or a dash", () => {
    expect(ringText(0.644)).toBe("64")
    expect(ringText(null)).toBe("–")
    expect(ringValue(null)).toBe(0)
    expect(ringValue(0.64)).toBe(0.64)
    expect(ringLabel(0.64)).toBe("64% sure")
    expect(ringLabel(null)).toBe("No confidence score")
  })
})

describe("row copy", () => {
  it("abbreviates the session and builds the paper code", () => {
    expect(sessionShort("May/June")).toBe("m/j")
    expect(sessionShort("Oct/Nov")).toBe("o/n")
    expect(sessionShort("Feb/Mar")).toBe("f/m")
    expect(sessionShort(null)).toBeNull()
    expect(paperLine(item())).toBe("0580/42 · m/j 2025")
    expect(paperLine(item({ subjectCode: null }))).toBe("Quiz question")
  })
  it("puts class and question under the name, and says Grading console for console rows (K7)", () => {
    expect(rowSubtitle(item())).toBe("10B · Q4(b)")
    expect(rowSubtitle(item({ source: "console_paper", className: null, questionId: "9" }))).toBe("Grading console · Q9")
    expect(rowSubtitle(item({ questionId: null }))).toBe("10B · Question")
  })
  it("turns reasons into one short plain line", () => {
    expect(plainWhy(item({ reason: "plagiarism_flag" }))).toBe("Matches mark-scheme wording")
    expect(plainWhy(item({ reason: "student_evidence_unjudged" }))).toBe("Student challenged a mark")
    expect(plainWhy(item({ reviewReason: "missing answer" }))).toBe("No answer found")
    expect(plainWhy(item({ reviewReason: "invalid MCQ answer" }))).toBe("Unclear choice")
    expect(plainWhy(item({ reviewReason: "mark scheme has no mcq_answer for this question" }))).toBe(
      "Scheme has no answer key",
    )
    expect(plainWhy(item({ reviewReason: "unverified accuracy mark(s): A1" }))).toBe("Final answer not confirmed")
    expect(plainWhy(item({ reviewReason: "extraction confidence 0.41 below review threshold 0.90" }))).toBe(
      "Hard to read",
    )
    expect(plainWhy(item({ reviewReason: "2 mark(s) awarded but point_verdicts is empty" }))).toBe(
      "Marks and points don't match",
    )
    expect(plainWhy(item({ reviewReason: "confidence 0.62 below review threshold 0.90" }))).toBe("Lemely wasn't sure")
    expect(plainWhy(item({ reviewReason: null }))).toBe("Lemely wasn't sure")
  })
  it("falls back sensibly for a reason it has no line for (L7 adds student_challenge)", () => {
    expect(plainWhy(item({ reason: "student_challenge" }))).toBe("Student challenge")
    expect(plainWhy(item({ reason: "" }))).toBe("Needs a look")
  })
  it("computes marks lost", () => {
    expect(marksLost(item())).toBe(1)
    expect(marksLost(item({ aiAwardedMarks: null }))).toBeNull()
  })
})

describe("bulk", () => {
  it("treats only non-integrity answers at 70% or more as clear", () => {
    expect(isClearItem(item({ confidenceScore: 0.72 }))).toBe(true)
    expect(isClearItem(item({ confidenceScore: 0.69 }))).toBe(false)
    expect(isClearItem(item({ confidenceScore: null }))).toBe(false)
    expect(isClearItem(item({ confidenceScore: 0.95, reason: "plagiarism_flag" }))).toBe(false)
  })
  it("never lets an integrity flag be selected (K6)", () => {
    expect(selectable(item())).toBe(true)
    expect(selectable(item({ reason: "plagiarism_flag" }))).toBe(false)
  })
  it("labels the bulk button for both modes", () => {
    expect(bulkButton({ selecting: false, picked: 0, clearCount: 3, pending: false })).toEqual({
      label: "Approve 3 clear",
      disabled: false,
    })
    expect(bulkButton({ selecting: false, picked: 0, clearCount: 0, pending: false })).toEqual({
      label: "No clear answers",
      disabled: true,
    })
    expect(bulkButton({ selecting: true, picked: 0, clearCount: 3, pending: false })).toEqual({
      label: "Pick answers to approve",
      disabled: true,
    })
    expect(bulkButton({ selecting: true, picked: 2, clearCount: 3, pending: false })).toEqual({
      label: "Approve 2 selected",
      disabled: false,
    })
    expect(bulkButton({ selecting: true, picked: 2, clearCount: 3, pending: true })).toEqual({
      label: "Approving…",
      disabled: true,
    })
  })
})

describe("screen state", () => {
  const base = {
    status: "success" as const,
    visibleCount: 3,
    openTotal: 3,
    filtersActive: false,
    hasHistory: true,
    decidedThisSession: 0,
  }
  it("loads, errors, then picks the queue", () => {
    expect(queueScreenState({ ...base, status: "pending" })).toBe("loading")
    expect(queueScreenState({ ...base, status: "error" })).toBe("error")
    expect(queueScreenState(base)).toBe("queue")
  })
  it("shows first run only to a teacher with no history", () => {
    expect(queueScreenState({ ...base, visibleCount: 0, openTotal: 0, hasHistory: false })).toBe("first-run")
    expect(queueScreenState({ ...base, visibleCount: 0, openTotal: 0 })).toBe("nothing-waiting")
  })
  it("celebrates only after decisions made here", () => {
    expect(queueScreenState({ ...base, visibleCount: 0, openTotal: 0, decidedThisSession: 2 })).toBe("cleared")
  })
  it("tells no-match from empty", () => {
    expect(queueScreenState({ ...base, visibleCount: 0, openTotal: 0, filtersActive: true })).toBe("no-match")
  })
  it("calls a single unfiltered answer sparse", () => {
    expect(queueScreenState({ ...base, visibleCount: 1, openTotal: 1 })).toBe("sparse")
    expect(queueScreenState({ ...base, visibleCount: 1, openTotal: 1, filtersActive: true })).toBe("queue")
  })
  it("gives Binny only to calm states", () => {
    expect(binnyFor("first-run")).toEqual({ mood: "open" })
    expect(binnyFor("nothing-waiting")).toEqual({ mood: "happy" })
    expect(binnyFor("cleared")).toEqual({ mood: "happy" })
    for (const s of ["loading", "error", "queue", "sparse", "no-match"] as const) expect(binnyFor(s)).toBeNull()
  })
})

describe("header and summary", () => {
  it("says answers left and done", () => {
    expect(headerTitle(1, 0)).toBe("answer left · 0 done")
    expect(headerTitle(6, 2)).toBe("answers left · 2 done")
    expect(progressOf(6, 2)).toBeCloseTo(0.25)
    expect(progressOf(0, 0)).toBe(0)
  })
  it("summarises the session", () => {
    expect(clearedSummary({ decided: 6, changed: 1, dismissed: 0 })).toBe("6 decided · 1 mark changed · 0 dismissed")
    expect(clearedSummary({ decided: 2, changed: 2, dismissed: 1 })).toBe("2 decided · 2 marks changed · 1 dismissed")
    expect(shownLine(3, 6)).toBe("Showing 3 of 6")
  })
})

describe("filters", () => {
  it("lists the four categories with counts", () => {
    const f = { ...EMPTY_FILTERS, reasons: ["low_confidence"] }
    expect(filterCategories(f)).toEqual([
      { key: "reason", label: "Reason", count: 1 },
      { key: "class", label: "Class", count: 0 },
      { key: "paper", label: "Paper", count: 0 },
      { key: "waiting", label: "Waiting", count: 0 },
    ])
  })
  it("offers only producible reasons (K2), the teacher's classes (K4), queue subjects and ages (K3)", () => {
    expect(filterValues("reason", EMPTY_FILTERS, OPTS).map((v) => v.label)).toEqual([
      "Low confidence",
      "Matches mark-scheme wording",
      "Student challenged a mark",
    ])
    expect(filterValues("class", EMPTY_FILTERS, OPTS).map((v) => v.label)).toEqual(["10B", "11C"])
    expect(filterValues("paper", EMPTY_FILTERS, OPTS).map((v) => v.label)).toEqual(["0580 Mathematics", "0625 Physics"])
    expect(filterValues("waiting", EMPTY_FILTERS, OPTS).map((v) => v.label)).toEqual([
      "6+ hours",
      "24+ hours",
      "3+ days",
      "7+ days",
    ])
  })
  it("toggles multi-value categories and makes waiting single-choice", () => {
    let f = toggleFilter(EMPTY_FILTERS, "class", "c1")
    f = toggleFilter(f, "class", "c2")
    expect(f.classIds).toEqual(["c1", "c2"])
    f = toggleFilter(f, "class", "c1")
    expect(f.classIds).toEqual(["c2"])
    f = toggleFilter(f, "waiting", "24")
    expect(f.minAgeHours).toBe(24)
    f = toggleFilter(f, "waiting", "72")
    expect(f.minAgeHours).toBe(72)
    f = toggleFilter(f, "waiting", "72")
    expect(f.minAgeHours).toBeNull()
  })
  it("builds removable chips and removes them", () => {
    const f = { ...EMPTY_FILTERS, reasons: ["plagiarism_flag"], classIds: ["c2"], subjects: ["0625"], minAgeHours: 6 }
    const chips = filterChips(f, OPTS)
    expect(chips.map((c) => c.label)).toEqual([
      "Reason: Matches mark-scheme wording",
      "Class: 11C",
      "Paper: 0625 Physics",
      "Waiting: 6+ hours",
    ])
    expect(removeFilter(f, "class", "c2").classIds).toEqual([])
    expect(removeFilter(f, "waiting", "6").minAgeHours).toBeNull()
    expect(clearFilters({ ...f, sort: "oldest" })).toEqual({ ...EMPTY_FILTERS, sort: "oldest" })
  })
  it("names the sorts in the mock's order", () => {
    expect(SORT_OPTIONS.map((s) => s.label)).toEqual(["Marks lost", "Confidence", "Oldest"])
    expect(sortLabel("confidence")).toBe("Confidence")
  })
})

describe("focus", () => {
  it("moves to the next row after a decision, else the previous, else nothing", () => {
    expect(nextFocusAfter(["a", "b", "c"], "b")).toBe("c")
    expect(nextFocusAfter(["a", "b", "c"], "c")).toBe("b")
    expect(nextFocusAfter(["a"], "a")).toBeNull()
    expect(nextFocusAfter(["a", "b"], "zz")).toBe("a")
  })
  it("reports a 1-based position", () => {
    expect(positionOf(["a", "b", "c"], "b")).toEqual({ pos: 2, total: 3 })
    expect(positionOf(["a"], "x")).toEqual({ pos: 0, total: 1 })
  })
})

describe("shortcuts and focus helpers", () => {
  const rootWith = (found: Record<string, { focus: () => void }>) => ({
    querySelector: ((sel: string) => found[sel] ?? null) as ParentNode["querySelector"],
  })
  it("detects an open menu or sheet", () => {
    expect(overlayOpen(rootWith({ '[role="menu"], [role="dialog"]': { focus() {} } }))).toBe(true)
    expect(overlayOpen(rootWith({}))).toBe(false)
  })
  it("focuses the next row, else the heading, and reports a row not yet rendered", () => {
    const calls: string[] = []
    const root = rootWith({
      '[data-review-row="b"]': { focus: () => calls.push("row") },
      "[data-review-heading]": { focus: () => calls.push("heading") },
    })
    expect(focusAfterDecision(root, "b")).toBe(true)
    expect(focusAfterDecision(root, null)).toBe(true)
    expect(focusAfterDecision(root, "zz")).toBe(false)
    expect(calls).toEqual(["row", "heading"])
  })
})
