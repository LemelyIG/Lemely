import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import type { PaperHistoryRow } from "@/lib/studentTypes"
import {
  DEFAULT_FILTERS,
  applyFilters,
  compareView,
  confidenceLine,
  emptyTip,
  filterOptions,
  filtersToParams,
  isAbsentSubject,
  papersHeading,
  papersLinks,
  papersMode,
  parseFilters,
  prunePicks,
  rowViews,
  sortSessions,
  toggleSelected,
  trayHasMore,
} from "@/portals/student/screens/papers/papersModel"

const NOW = new Date(2024, 10, 20, 10, 0)
const mk = (
  id: string,
  iso: string,
  paper: number,
  variant: number,
  session: string,
  awarded: number,
  maximum: number,
  grade: string,
  extra: Partial<PaperHistoryRow> = {},
): PaperHistoryRow => ({
  id,
  paper: `0580/${paper}${variant} · ${session}`,
  note: "",
  marks: `${awarded}/${maximum}`,
  pct: `${Math.round((awarded / maximum) * 100)}%`,
  grade,
  gradeColor: "ok",
  tab: `p${paper}`,
  awarded,
  maximum,
  recordedAt: iso,
  paperNumber: paper,
  label: `0580/${paper}${variant} · ${session}`,
  variant,
  session,
  confidence: null,
  teacherCorrected: 0,
  ...extra,
})
// Newest first, as the endpoint returns them.
const HISTORY: PaperHistoryRow[] = [
  mk("6", "2024-11-02T10:00:00+00:00", 4, 2, "May/Jun 2024", 61, 80, "A"),
  mk("5", "2024-09-15T10:00:00+00:00", 2, 1, "Feb/Mar 2024", 53, 70, "A", { confidence: { scored: 14, uncertain: 2, needsReview: 0 } }),
  mk("4", "2024-06-15T10:00:00+00:00", 4, 2, "Feb/Mar 2024", 50, 80, "B", { teacherCorrected: 3 }),
  mk("3", "2024-01-15T10:00:00+00:00", 4, 3, "Oct/Nov 2023", 48, 80, "B", { confidence: { scored: 10, uncertain: 0, needsReview: 0 } }),
  mk("0", "2023-10-15T10:00:00+00:00", 4, 1, "Oct/Nov 2023", 45, 80, "C"),
]
const ids = (rows: PaperHistoryRow[]) => rows.map((r) => r.id)

describe("papersMode: which data state the list is in", () => {
  it("is empty with no attempts, single with one, list with two or more", () => {
    expect(papersMode(0)).toBe("empty")
    expect(papersMode(1)).toBe("single")
    expect(papersMode(2)).toBe("list")
    expect(papersMode(40)).toBe("list")
  })
})

describe("isAbsentSubject: the endpoint's two explicit no-papers answers", () => {
  it("matches only a 404 carrying one of the two details for this code", () => {
    expect(isAbsentSubject(new ApiError(404, "No history for subject 0580", "No history for subject 0580"), "0580")).toBe(true)
    expect(isAbsentSubject(new ApiError(404, "No papers for subject 0580", "No papers for subject 0580"), "0580")).toBe(true)
    expect(isAbsentSubject(new ApiError(404, "Not found", "Not found"), "0580")).toBe(false)
    expect(isAbsentSubject(new ApiError(500, "No papers for subject 0580", "No papers for subject 0580"), "0580")).toBe(false)
    expect(isAbsentSubject(new ApiError(404, "No papers for subject 0606", "No papers for subject 0606"), "0580")).toBe(false)
    expect(isAbsentSubject(null, "0580")).toBe(false)
  })
})

describe("filters", () => {
  it("offers a filter only when the data has more than one value for it", () => {
    const o = filterOptions(HISTORY)
    expect(o.papers).toEqual([2, 4])
    expect(o.variants).toEqual([1, 2, 3])
    expect(o.sessions).toEqual(["May/Jun 2024", "Feb/Mar 2024", "Oct/Nov 2023"])
    const one = filterOptions([HISTORY[0], HISTORY[2]])
    expect(one.papers).toEqual([])
    expect(one.variants).toEqual([])
    expect(one.sessions).toEqual(["May/Jun 2024", "Feb/Mar 2024"])
  })
  it("filters by paper, variant and session, and combines them", () => {
    expect(ids(applyFilters(HISTORY, { ...DEFAULT_FILTERS, paper: 2 }, NOW))).toEqual(["5"])
    expect(ids(applyFilters(HISTORY, { ...DEFAULT_FILTERS, variant: 2 }, NOW))).toEqual(["6", "4"])
    expect(ids(applyFilters(HISTORY, { ...DEFAULT_FILTERS, session: "Oct/Nov 2023" }, NOW))).toEqual(["3", "0"])
    expect(ids(applyFilters(HISTORY, { ...DEFAULT_FILTERS, paper: 4, variant: 2, session: "Feb/Mar 2024" }, NOW))).toEqual(["4"])
  })
  it("filters by date window counted back from now", () => {
    expect(ids(applyFilters(HISTORY, { ...DEFAULT_FILTERS, period: "30d" }, NOW))).toEqual(["6"])
    expect(ids(applyFilters(HISTORY, { ...DEFAULT_FILTERS, period: "90d" }, NOW))).toEqual(["6", "5"])
    expect(ids(applyFilters(HISTORY, { ...DEFAULT_FILTERS, period: "365d" }, NOW))).toEqual(["6", "5", "4", "3"])
    expect(ids(applyFilters(HISTORY, DEFAULT_FILTERS, NOW))).toEqual(["6", "5", "4", "3", "0"])
  })
  it("returns nothing, not everything, when no attempt matches", () => {
    expect(applyFilters(HISTORY, { ...DEFAULT_FILTERS, paper: 4, variant: 3, session: "May/Jun 2024" }, NOW)).toEqual([])
  })
})

describe("sort is the student's choice", () => {
  it("newest first by default, and oldest, highest and lowest on request", () => {
    expect(ids(applyFilters(HISTORY, DEFAULT_FILTERS, NOW))).toEqual(["6", "5", "4", "3", "0"])
    expect(ids(applyFilters(HISTORY, { ...DEFAULT_FILTERS, sort: "oldest" }, NOW))).toEqual(["0", "3", "4", "5", "6"])
    expect(ids(applyFilters(HISTORY, { ...DEFAULT_FILTERS, sort: "highest" }, NOW))).toEqual(["6", "5", "4", "3", "0"])
    expect(ids(applyFilters(HISTORY, { ...DEFAULT_FILTERS, sort: "lowest" }, NOW))).toEqual(["0", "3", "4", "5", "6"])
  })
  it("breaks a tie on the mark by the newer attempt", () => {
    const rows = [mk("old", "2024-01-01T10:00:00+00:00", 2, 1, "S", 40, 80, "B"), mk("new", "2024-02-01T10:00:00+00:00", 2, 1, "S", 40, 80, "B")]
    expect(ids(applyFilters(rows, { ...DEFAULT_FILTERS, sort: "highest" }, NOW))).toEqual(["new", "old"])
    expect(ids(applyFilters(rows, { ...DEFAULT_FILTERS, sort: "lowest" }, NOW))).toEqual(["new", "old"])
  })
  it("ranks by percentage, so papers out of different totals compare fairly", () => {
    const rows = [mk("a", "2024-10-01T10:00:00+00:00", 2, 1, "S", 60, 70, "A"), mk("b", "2024-10-02T10:00:00+00:00", 4, 1, "S", 60, 80, "B")]
    expect(ids(applyFilters(rows, { ...DEFAULT_FILTERS, sort: "highest" }, NOW))).toEqual(["a", "b"])
  })
})

describe("filters live in the address, so back from a result keeps them", () => {
  it("round-trips and leaves defaults out", () => {
    const f = { paper: 4, variant: 2, session: "Feb/Mar 2024", period: "90d" as const, sort: "highest" as const }
    expect(parseFilters(filtersToParams(f))).toEqual(f)
    expect(filtersToParams(DEFAULT_FILTERS).toString()).toBe("")
  })
  it("ignores values it does not know", () => {
    const p = new URLSearchParams("paper=banana&variant=-1&period=forever&sort=random&session=")
    expect(parseFilters(p)).toEqual(DEFAULT_FILTERS)
  })
})

describe("rows", () => {
  const rows = rowViews(HISTORY, NOW)
  it("carry identity, mark, percent, grade, date and the exit to that paper's result", () => {
    expect(rows[0]).toMatchObject({
      id: "6",
      grade: "A",
      title: "0580/42 · May/Jun 2024",
      marks: "61/80",
      pct: "76%",
      to: "/student/result/6",
    })
    expect(rows[0].date).toMatch(/2 Nov 2024/)
  })
  it("say how sure the marker was only when evidence exists", () => {
    expect(rows[0].confidence).toBeNull()
    expect(rows[1].confidence).toBe("2 of 14 unsure")
    expect(rows[3].confidence).toBe("All 10 sure")
  })
  it("mark a teacher correction, and nothing otherwise", () => {
    expect(rows[2].corrected).toBe("Teacher re-marked 3 questions")
    expect(rows[0].corrected).toBeNull()
    expect(rowViews([mk("x", "2024-10-01T10:00:00+00:00", 2, 1, "S", 5, 10, "C", { teacherCorrected: 1 })], NOW)[0].corrected).toBe(
      "Teacher re-marked 1 question",
    )
  })
})

describe("confidenceLine", () => {
  it("is silent for no evidence and for an attempt nothing scored", () => {
    expect(confidenceLine(null)).toBeNull()
    expect(confidenceLine({ scored: 0, uncertain: 0, needsReview: 0 })).toBeNull()
  })
  it("counts the unsure ones, or says all are sure", () => {
    expect(confidenceLine({ scored: 14, uncertain: 1, needsReview: 0 })).toBe("1 of 14 unsure")
    expect(confidenceLine({ scored: 14, uncertain: 0, needsReview: 0 })).toBe("All 14 sure")
  })
  it("names the result screen's needs-review tier on its own, never as sure", () => {
    expect(confidenceLine({ scored: 14, uncertain: 0, needsReview: 1 })).toBe("1 of 14 needs review")
    expect(confidenceLine({ scored: 14, uncertain: 0, needsReview: 3 })).toBe("3 of 14 need review")
    expect(confidenceLine({ scored: 14, uncertain: 2, needsReview: 1 })).toBe("2 of 14 unsure, 1 needs review")
    expect(confidenceLine({ scored: 14, uncertain: 2, needsReview: 3 })).toBe("2 of 14 unsure, 3 need review")
  })
})

describe("session options follow exam order, not attempt order", () => {
  it("lists the newest session first even when an older one was attempted last", () => {
    expect(sortSessions(["Oct/Nov 2023", "May/Jun 2024", "Feb/Mar 2024", "Oct/Nov 2024", "May/Jun 2023"])).toEqual([
      "Oct/Nov 2024",
      "May/Jun 2024",
      "Feb/Mar 2024",
      "Oct/Nov 2023",
      "May/Jun 2023",
    ])
  })
  it("puts a label it cannot read last, in the order given", () => {
    expect(sortSessions(["Specimen", "Feb/Mar 2024", "Other"])).toEqual(["Feb/Mar 2024", "Specimen", "Other"])
  })
  it("is what the Session filter offers", () => {
    const old = mk("9", "2025-01-10T10:00:00+00:00", 4, 1, "Oct/Nov 2023", 40, 80, "C")
    expect(filterOptions([old, HISTORY[0], HISTORY[2]]).sessions).toEqual(["May/Jun 2024", "Feb/Mar 2024", "Oct/Nov 2023"])
  })
})

describe("picks follow the rows on screen", () => {
  it("drops the picks a filter hides and keeps the rest in their order", () => {
    expect(prunePicks(["6", "5"], [HISTORY[0], HISTORY[2]])).toEqual(["6"])
    expect(prunePicks(["5", "6"], [HISTORY[0], HISTORY[1]])).toEqual(["5", "6"])
    expect(prunePicks(["5", "6"], [])).toEqual([])
  })
})

describe("compare: two attempts, earlier first", () => {
  it("toggles a pick, holds two, and the third replaces the oldest pick", () => {
    expect(toggleSelected([], "a")).toEqual(["a"])
    expect(toggleSelected(["a"], "b")).toEqual(["a", "b"])
    expect(toggleSelected(["a", "b"], "a")).toEqual(["b"])
    expect(toggleSelected(["a", "b"], "c")).toEqual(["b", "c"])
  })
  it("orders by date whichever was picked first, and says what changed", () => {
    const c = compareView(HISTORY, ["6", "0"], NOW)
    expect(c).not.toBeNull()
    expect(c!.earlier.id).toBe("0")
    expect(c!.later.id).toBe("6")
    expect(c!.change).toBe("Up 20 points")
    expect(c!.grades).toBe("C to A")
    expect(c!.earlier.to).toBe("/student/result/0")
    expect(c!.later.to).toBe("/student/result/6")
  })
  it("says down, and no change, plainly", () => {
    const fell = [mk("p", "2024-01-01T10:00:00+00:00", 2, 1, "S", 64, 80, "A"), mk("q", "2024-02-01T10:00:00+00:00", 2, 1, "S", 40, 80, "B")]
    expect(compareView(fell, ["q", "p"], NOW)!.change).toBe("Down 30 points")
    expect(compareView(fell, ["q", "p"], NOW)!.grades).toBe("A to B")
    const same = [mk("p", "2024-01-01T10:00:00+00:00", 2, 1, "S", 40, 80, "B"), mk("q", "2024-02-01T10:00:00+00:00", 2, 1, "S", 40, 80, "B")]
    const c = compareView(same, ["p", "q"], NOW)!
    expect(c.change).toBe("No change")
    expect(c.grades).toBe("Both B")
  })
  it("is null until two picks that still exist are made", () => {
    expect(compareView(HISTORY, ["6"], NOW)).toBeNull()
    expect(compareView(HISTORY, ["6", "gone"], NOW)).toBeNull()
    expect(compareView(HISTORY, [], NOW)).toBeNull()
  })
})

describe("copy and links", () => {
  it("the heading names the subject and the paper count, and says nothing about a trend for one", () => {
    expect(papersHeading("Mathematics", 7)).toBe("Mathematics, 7 papers")
    expect(papersHeading("Mathematics", 1)).toBe("Mathematics, 1 paper")
  })
  it("links go to the Subject page, the result and scanning", () => {
    expect(papersLinks.subject("0580")).toBe("/student/subject/0580")
    expect(papersLinks.self("0580")).toBe("/student/subject/0580/papers")
  })
  it("the empty tip is Binny's two to four words and a scan action, with no exclamation mark", () => {
    const t = emptyTip("0580", "Mathematics")
    expect(t.line.split(" ").length).toBeGreaterThanOrEqual(2)
    expect(t.line.split(" ").length).toBeLessThanOrEqual(4)
    expect(t.line).not.toContain("!")
    expect(t.action.to).toContain("/student/correct?subject=0580")
    expect(t.action.label).toBe("Scan a Mathematics paper")
  })
})

describe("a filter tray fades its edge only when more runs past it", () => {
  it("a tray in a hidden panel has no box, so it has nothing past its end", () => {
    expect(trayHasMore({ scrollWidth: 0, clientWidth: 0, scrollLeft: 0 })).toBe(false)
  })
  it("a tray that fits does not fade", () => {
    expect(trayHasMore({ scrollWidth: 300, clientWidth: 300, scrollLeft: 0 })).toBe(false)
  })
  it("a tray with choices past its end fades, and the same tray measured before it had a box did not", () => {
    expect(trayHasMore({ scrollWidth: 0, clientWidth: 0, scrollLeft: 0 })).toBe(false)
    expect(trayHasMore({ scrollWidth: 1182, clientWidth: 347, scrollLeft: 0 })).toBe(true)
  })
  it("reaching the end drops the fade", () => {
    expect(trayHasMore({ scrollWidth: 1182, clientWidth: 347, scrollLeft: 835 })).toBe(false)
    expect(trayHasMore({ scrollWidth: 1182, clientWidth: 347, scrollLeft: 400 })).toBe(true)
  })
  it("a sub-pixel overhang is not more", () => {
    expect(trayHasMore({ scrollWidth: 301, clientWidth: 300, scrollLeft: 0 })).toBe(false)
  })
  it("reads right-to-left scrolling, which counts negative", () => {
    expect(trayHasMore({ scrollWidth: 1182, clientWidth: 347, scrollLeft: -835 })).toBe(false)
    expect(trayHasMore({ scrollWidth: 1182, clientWidth: 347, scrollLeft: -400 })).toBe(true)
  })
})
