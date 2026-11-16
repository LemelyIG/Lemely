import { describe, expect, it } from "vitest"
import type { PastPaper } from "@/lib/practiceHubTypes"
import {
  emptyPapersCopy,
  formatDuration,
  paperGroups,
  paperRow,
  paperSheetView,
  papersState,
} from "@/portals/student/screens/practice/papers/papersModel"

const paper = (over: Partial<PastPaper>): PastPaper => ({
  paperId: "p1",
  code: "0580/42",
  subjectCode: "0580",
  paperNumber: 4,
  paperVariant: 2,
  sessionLabel: "May/June 2025",
  durationMinutes: 150,
  totalMarks: 80,
  questionCount: 18,
  awardedMarks: 52,
  maximumMarks: 80,
  ...over,
})

describe("formatDuration", () => {
  it("matches the mock's '2 h 30' style", () => {
    expect(formatDuration(150)).toBe("2 h 30")
    expect(formatDuration(90)).toBe("1 h 30")
    expect(formatDuration(60)).toBe("1 h")
    expect(formatDuration(45)).toBe("45 min")
    expect(formatDuration(65)).toBe("1 h 05")
  })
})

describe("paperRow", () => {
  it("done paper shows its score", () => {
    expect(paperRow(paper({}))).toEqual({
      paperId: "p1",
      title: "0580/42 · May/June 2025",
      sub: "Paper 4 · 2 h 30",
      score: "52/80",
      done: true,
    })
  })

  it("undone paper has no score; a paper with no timing shows no duration", () => {
    const row = paperRow(paper({ awardedMarks: null, maximumMarks: null, durationMinutes: null }))
    expect(row).toMatchObject({ sub: "Paper 4", score: null, done: false })
  })
})

describe("paperGroups", () => {
  it("groups by paper number, highest first, keeping server order inside a group", () => {
    const groups = paperGroups([
      paper({ paperId: "a", paperNumber: 2 }),
      paper({ paperId: "b", paperNumber: 4 }),
      paper({ paperId: "c", paperNumber: 4 }),
    ])
    expect(groups.map((g) => [g.heading, g.rows.map((r) => r.paperId)])).toEqual([
      ["Paper 4", ["b", "c"]],
      ["Paper 2", ["a"]],
    ])
  })
})

describe("papersState", () => {
  it("covers loading, error, empty and ready", () => {
    expect(papersState("pending", undefined)).toBe("loading")
    expect(papersState("error", undefined)).toBe("error")
    expect(papersState("success", [])).toBe("empty")
    expect(papersState("success", [paper({})])).toBe("ready")
  })
})

describe("paperSheetView", () => {
  it("offers timed first when the syllabus gives a duration", () => {
    const v = paperSheetView(paper({}), "Maths")
    expect(v.title).toBe("0580/42 · May/June 2025")
    expect(v.sub).toBe("Maths · Paper 4 · 80 marks")
    expect(v.options.map((o) => o.key)).toEqual(["timed", "print"])
    expect(v.options[0].body).toBe("2 h 30 on paper, then type your answers in")
    expect(v.defaultOption).toBe("timed")
    expect(v.hint).toBe("Prints 18 questions. Lemely marks the answers you type in.")
  })

  it("never offers a timed option without a real duration", () => {
    const v = paperSheetView(paper({ durationMinutes: null, totalMarks: null }), "Maths")
    expect(v.options.map((o) => o.key)).toEqual(["print"])
    expect(v.defaultOption).toBe("print")
    expect(v.sub).toBe("Maths · Paper 4")
  })

  it("a done paper with nothing printable cannot be printed", () => {
    expect(paperSheetView(paper({ questionCount: 0 }), "Maths").printable).toBe(false)
  })
})

describe("emptyPapersCopy", () => {
  it("follows the no-questions pattern", () => {
    expect(emptyPapersCopy("Maths", ["Physics"])).toEqual({
      heading: "No Maths papers to print yet",
      body: "We're adding them. Try Physics for now.",
    })
  })
})
