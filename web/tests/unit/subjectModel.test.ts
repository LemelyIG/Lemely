import { describe, expect, it } from "vitest"
import {
  barHeight,
  defaultPaper,
  gradeArticle,
  gradeColorVar,
  links,
  monthLabel,
  monthYearLabel,
  nextExamDate,
  paperRows,
  paperTabs,
  plural,
  resolvePaper,
  selectScreenState,
  stepsFor,
  subtitleFor,
  tierLabel,
  topicName,
  trendFor,
  visiblePapers,
} from "@/portals/student/screens/subject/subjectModel"
import { MATHS, MATHS_ONE, NOW } from "@/portals/student/screens/subject/fixtures"
import type { StudentExamCalendar } from "@/lib/announcementTypes"
import type { CatalogueSubject } from "@/lib/referenceTypes"

const p4 = MATHS.papersBreakdown.find((p) => p.paperNumber === 4)!
const p2 = MATHS.papersBreakdown.find((p) => p.paperNumber === 2)!

describe("selectScreenState", () => {
  it("is loading while pending", () => {
    expect(selectScreenState({ status: "pending", errorStatus: null, paperCount: 0 })).toBe("loading")
  })
  it("treats a 404 as first run, not an error (K2)", () => {
    expect(selectScreenState({ status: "error", errorStatus: 404, paperCount: 0 })).toBe("first-run")
  })
  it("treats any other failure as an error", () => {
    expect(selectScreenState({ status: "error", errorStatus: 500, paperCount: 0 })).toBe("error")
    expect(selectScreenState({ status: "error", errorStatus: null, paperCount: 0 })).toBe("error")
  })
  it("is first run on a 200 with no papers, sparse with one, full with two or more", () => {
    expect(selectScreenState({ status: "success", errorStatus: null, paperCount: 0 })).toBe("first-run")
    expect(selectScreenState({ status: "success", errorStatus: null, paperCount: 1 })).toBe("sparse")
    expect(selectScreenState({ status: "success", errorStatus: null, paperCount: 7 })).toBe("full")
  })
})

describe("small helpers", () => {
  it("maps grades to the grade tokens, unknown to U", () => {
    expect(gradeColorVar("A*")).toBe("var(--grade-a-star)")
    expect(gradeColorVar("B")).toBe("var(--grade-b)")
    expect(gradeColorVar("?")).toBe("var(--grade-u)")
  })
  it("picks the article a grade letter is read with", () => {
    expect(gradeArticle("A")).toBe("an")
    expect(gradeArticle("A*")).toBe("an")
    expect(gradeArticle("E")).toBe("an")
    expect(gradeArticle("F")).toBe("an")
    expect(gradeArticle("B")).toBe("a")
    expect(gradeArticle("U")).toBe("a")
  })
  it("reads a 9-1 grade 8 with an", () => {
    expect(gradeArticle("8")).toBe("an")
    expect(gradeArticle("7")).toBe("a")
  })
  it("strips the syllabus code from a topic label", () => {
    expect(topicName("C7 Vectors")).toBe("Vectors")
    expect(topicName("C3.5 Coordinate geometry")).toBe("Coordinate geometry")
    expect(topicName("Vectors")).toBe("Vectors")
    expect(topicName("unknown")).toBe("unknown")
  })
  it("leaves a topic whose first word merely contains a digit alone", () => {
    expect(topicName("2D shapes")).toBe("2D shapes")
    expect(topicName("E1.2 Number")).toBe("Number")
  })
  it("pluralises marks", () => {
    expect(plural(1, "mark")).toBe("1 mark")
    expect(plural(7, "mark")).toBe("7 marks")
  })
  it("adds the year to a month only when it is not this year", () => {
    expect(monthYearLabel("2024-04-15T10:00:00+00:00", NOW)).toBe("Apr")
    expect(monthYearLabel("2023-10-15T10:00:00+00:00", NOW)).toBe("Oct 2023")
  })
  it("gives an empty month for an unreadable date instead of throwing", () => {
    expect(monthLabel("not a date")).toBe("")
    expect(monthYearLabel("", NOW)).toBe("")
  })
  it("builds every link the screen uses", () => {
    expect(links.scan("0580")).toBe("/student/correct?subject=0580")
    expect(links.upload("0580")).toBe("/student/correct?subject=0580&source=file")
    expect(links.practice("0580")).toBe("/student/practice/0580")
    expect(links.practice("0580", "C7 Vectors")).toBe("/student/practice/0580?topic=C7%20Vectors")
    expect(links.flashcards("0580", "d1")).toBe("/student/flashcards/0580?deck=d1")
    expect(links.plan("0580")).toBe("/student/plan/0580")
    expect(links.result("6")).toBe("/student/result/6")
    expect(links.home).toBe("/student")
  })
})

describe("barHeight", () => {
  it("runs from 40% of the marks (0) to the A* line (100)", () => {
    expect(barHeight(32, 80, 68)).toBe(0)
    expect(barHeight(68, 80, 68)).toBe(100)
    expect(barHeight(61, 80, 68)).toBe(81)
    expect(barHeight(45, 80, 68)).toBe(36)
  })
  it("clamps below the floor and above the line", () => {
    expect(barHeight(10, 80, 68)).toBe(0)
    expect(barHeight(75, 80, 68)).toBe(100)
  })
  it("is full height when the line sits at or below the floor", () => {
    expect(barHeight(20, 80, 30)).toBe(100)
  })
})

describe("stepsFor", () => {
  it("draws the last four attempts with the latest one current", () => {
    const steps = stepsFor(p4)
    expect(steps.bars.map((b) => [b.grade, b.marks, b.month, b.heightPct, b.current])).toEqual([
      ["C", 45, "Oct", 36, false],
      ["B", 48, "Jan", 44, false],
      ["B", 50, "Feb", 50, false],
      ["A", 61, "Apr", 81, true],
    ])
    expect(steps.bars[3].resultTo).toBe("/student/result/6")
    expect(steps.bars[3].colorVar).toBe("var(--grade-a)")
    expect(steps.ghosts).toBe(0)
  })
  it("puts the real A* line and the gap in the goal block", () => {
    const goal = stepsFor(p4).goal!
    expect(goal).toMatchObject({ grade: "A*", marks: 68, outOf: 80, gap: 7, gapLabel: "7 to go" })
    expect(goal.sourceLabel).toBe("May/Jun 2024 boundary")
    expect(goal.ariaLabel).toBe("A* line, 68 out of 80. 7 marks to go")
  })
  it("says the line is reached once the latest attempt clears it", () => {
    const over = { ...p4, attempts: [...p4.attempts, { ...p4.attempts[3], id: "9", awarded: 70 }] }
    const goal = stepsFor(over).goal!
    expect(goal.gap).toBe(-2)
    expect(goal.gapLabel).toBe("Reached")
  })
  it("keeps only the last STEP_WINDOW attempts", () => {
    const many = { ...p4, attempts: [...p4.attempts, { ...p4.attempts[3], id: "9" }] }
    expect(stepsFor(many).bars.map((b) => b.id)).toEqual(["3", "4", "6", "9"])
  })
  it("adds ghost slots for the sparse path", () => {
    expect(stepsFor(MATHS_ONE.papersBreakdown[0], { ghosts: 3 }).ghosts).toBe(3)
  })
  it("describes the whole path for screen readers", () => {
    expect(stepsFor(p2).groupLabel).toBe(
      "Paper 2 marks so far: B, 44 out of 70 in Nov; B, 47 out of 70 in Dec; A, 53 out of 70 in Mar. The A* line is 60, 7 marks to go.",
    )
  })
  it("has no goal block when the paper has no boundary", () => {
    expect(stepsFor({ ...p4, goal: null }).goal).toBeNull()
  })
  it("scales bars to full marks and drops the line sentence when there is no boundary", () => {
    const steps = stepsFor({ ...p4, goal: null })
    // 40% of 80 is 32, so 61/80 sits (61-32)/(80-32) of the way up.
    expect(steps.bars.map((b) => b.heightPct)).toEqual([27, 33, 38, 60])
    expect(steps.groupLabel).not.toContain("line")
    expect(steps.groupLabel.endsWith("in Apr.")).toBe(true)
  })
  it("scales the line to each attempt's own maximum", () => {
    const mixed = { ...p4, attempts: [{ ...p4.attempts[0], awarded: 34, maximum: 40 }, p4.attempts[3]] }
    // The line is 68/80, so 34/40 on a 40-mark attempt clears it.
    expect(stepsFor(mixed).bars[0].heightPct).toBe(100)
  })
  it("words an empty path without a dangling list", () => {
    const steps = stepsFor({ ...p4, attempts: [] })
    expect(steps.bars).toEqual([])
    expect(steps.goal).toBeNull()
    expect(steps.groupLabel).toBe("Paper 4: no marks yet.")
  })
  it("drops the month from the words when the date is unreadable", () => {
    const odd = { ...p4, attempts: [{ ...p4.attempts[3], recordedAt: "" }] }
    const bar = stepsFor(odd).bars[0]
    expect(bar.month).toBe("")
    expect(bar.ariaLabel).toBe("A, 61 out of 80. Open this paper")
  })
})

describe("trendFor", () => {
  it("carries the forecast and the change since the first attempt, in marks", () => {
    expect(trendFor(p4, "A", 7)).toEqual({
      kind: "trend",
      forecast: "A",
      article: "an",
      colorVar: "var(--grade-a)",
      change: "up 16 marks since Oct",
    })
    expect(trendFor(p2, "A", 7)).toMatchObject({ change: "up 9 marks since Nov" })
  })
  it("words a decline and no change plainly (K8)", () => {
    const down = { ...p4, attempts: [p4.attempts[3], { ...p4.attempts[0], recordedAt: "2024-05-15T10:00:00+00:00" }] }
    expect(trendFor(down, "B", 7)).toMatchObject({ change: "down 16 marks since Apr", article: "a" })
    const level = { ...p4, attempts: [p4.attempts[0], { ...p4.attempts[0], id: "8" }] }
    expect(trendFor(level, "C", 7)).toMatchObject({ change: "level since Oct" })
  })
  it("compares in the latest attempt's marks when the maximum changed", () => {
    const mixed = { ...p2, attempts: [{ ...p2.attempts[0], awarded: 45, maximum: 80 }, p2.attempts[2]] }
    // 45/80 is 39 on 70 marks; the latest is 53/70.
    expect(trendFor(mixed, "A", 7)).toMatchObject({ change: "up 14 marks since Nov" })
  })
  it("says since your first paper when the first date is unreadable", () => {
    const odd = { ...p4, attempts: [{ ...p4.attempts[0], recordedAt: "" }, p4.attempts[3]] }
    expect(trendFor(odd, "A", 7)).toMatchObject({ change: "up 16 marks since your first paper" })
  })
  it("uses the sparse line when the subject has one paper", () => {
    expect(trendFor(MATHS_ONE.papersBreakdown[0], "A", 1)).toEqual({
      kind: "single",
      text: "One step so far. Two more papers show your trend.",
    })
  })
  it("names the paper when only this paper has a single attempt", () => {
    const single = { ...p2, attempts: [p2.attempts[0]] }
    expect(trendFor(single, "A", 5)).toEqual({ kind: "single", text: "One Paper 2 so far." })
  })
})

describe("paper switch", () => {
  it("orders tabs Paper 4 then Paper 2 like the mock", () => {
    expect(paperTabs(MATHS.papersBreakdown)).toEqual([
      { paperNumber: 4, name: "Paper 4" },
      { paperNumber: 2, name: "Paper 2" },
    ])
  })
  it("does not reorder the caller's array", () => {
    const papers = [...MATHS.papersBreakdown]
    paperTabs(papers)
    expect(papers.map((p) => p.paperNumber)).toEqual([2, 4])
  })
  it("defaults to the paper with the most recent attempt", () => {
    expect(defaultPaper(MATHS.papersBreakdown)).toBe(4)
  })
  it("honours a valid ?paper= and ignores a bad one", () => {
    expect(resolvePaper(MATHS.papersBreakdown, "2")).toBe(2)
    expect(resolvePaper(MATHS.papersBreakdown, "7")).toBe(4)
    expect(resolvePaper(MATHS.papersBreakdown, "")).toBe(4)
    expect(resolvePaper(MATHS.papersBreakdown, null)).toBe(4)
    expect(resolvePaper([], null)).toBeNull()
  })
})

describe("papers", () => {
  it("builds rows newest first with marks and month, linking to the result (K13)", () => {
    const rows = paperRows(MATHS.paperHistory, NOW)
    expect(rows[0]).toEqual({
      id: "6",
      grade: "A",
      colorVar: "var(--grade-a)",
      title: "0580/42 · May/Jun 2024",
      sub: "61/80 · Apr",
      to: "/student/result/6",
    })
    expect(rows.at(-1)!.sub).toBe("45/80 · Oct 2023")
  })
  it("shows marks alone when the date is unreadable", () => {
    const rows = paperRows([{ ...MATHS.paperHistory[0], recordedAt: "" }], NOW)
    expect(rows[0].sub).toBe("61/80")
  })
  it("shows 4 rows below 1280px, 5 at desktop, all once expanded", () => {
    expect(visiblePapers(7, false, false)).toBe(4)
    expect(visiblePapers(7, true, false)).toBe(5)
    expect(visiblePapers(7, false, true)).toBe(7)
    expect(visiblePapers(2, true, false)).toBe(2)
  })
})

describe("header", () => {
  const catalogue: CatalogueSubject = {
    code: "0580",
    name: "Mathematics",
    board: "caie",
    qualificationLevel: "igcse",
    papers: [
      { number: 2, name: "Paper 2", tier: "extended", practical: false },
      { number: 1, name: "Paper 1", tier: "core", practical: false },
      { number: 9, name: "Paper 9", tier: null, practical: false },
    ],
    topics: [],
  }
  it("reads the tier of the selected paper", () => {
    expect(tierLabel(catalogue, 2)).toBe("Extended")
    expect(tierLabel(catalogue, 1)).toBe("Core")
    expect(tierLabel(catalogue, 9)).toBeNull()
    expect(tierLabel(undefined, 2)).toBeNull()
    expect(tierLabel(catalogue, null)).toBeNull()
  })
  it("joins level, code and tier", () => {
    expect(subtitleFor("IGCSE · 0580", "Extended")).toBe("IGCSE · 0580 · Extended")
    expect(subtitleFor("0580", null)).toBe("0580")
    expect(subtitleFor("", null)).toBe("")
  })
})

describe("nextExamDate", () => {
  const calendar = (dates: string[], availability: "dated" | "no_timetable" = "dated"): StudentExamCalendar => ({
    availability: "available",
    entries: [
      {
        subjectCode: "0580",
        sessionMonth: "may_june",
        sessionYear: 2025,
        paperNumber: 4,
        availability,
        dates: dates.map((examDate) => ({ paperVariant: "2", examDate, startsAtLocal: null, durationMinutes: 150, source: "CAIE" })),
      },
      {
        subjectCode: "0625",
        sessionMonth: "may_june",
        sessionYear: 2025,
        paperNumber: 4,
        availability: "dated",
        dates: [{ paperVariant: "2", examDate: "2024-11-25", startsAtLocal: null, durationMinutes: 75, source: "CAIE" }],
      },
    ],
  })
  it("is the earliest future date for this subject", () => {
    expect(nextExamDate(calendar(["2025-05-27", "2025-05-12"]), "0580", NOW)).toBe("2025-05-12")
  })
  it("skips past dates and undated papers, and is null without a calendar", () => {
    expect(nextExamDate(calendar(["2024-11-01"]), "0580", NOW)).toBeNull()
    expect(nextExamDate(calendar([], "no_timetable"), "0580", NOW)).toBeNull()
    expect(nextExamDate(undefined, "0580", NOW)).toBeNull()
  })
  it("counts today and skips an unreadable date", () => {
    expect(nextExamDate(calendar(["garbage", "2024-11-20"]), "0580", NOW)).toBe("2024-11-20")
  })
})
