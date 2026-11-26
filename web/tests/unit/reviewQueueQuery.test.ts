import { describe, expect, it } from "vitest"
import {
  DEFAULT_SORT,
  EMPTY_FILTERS,
  filterKey,
  filtersActive,
  filtersFromSearch,
  filtersToSearch,
  reviewQueuePath,
} from "@/lib/reviewQueueQuery"

describe("reviewQueueQuery", () => {
  it("defaults to marks lost with nothing filtered", () => {
    expect(filtersFromSearch(new URLSearchParams())).toEqual(EMPTY_FILTERS)
    expect(EMPTY_FILTERS.sort).toBe(DEFAULT_SORT)
    expect(DEFAULT_SORT).toBe("lost")
  })

  it("reads repeated params, the search, age and sort", () => {
    const sp = new URLSearchParams(
      "q=layla&class_id=a&class_id=b&reason=low_confidence&subject=0580&min_age_hours=24&sort=confidence",
    )
    expect(filtersFromSearch(sp)).toEqual({
      q: "layla",
      classIds: ["a", "b"],
      reasons: ["low_confidence"],
      subjects: ["0580"],
      minAgeHours: 24,
      sort: "confidence",
    })
  })

  it("ignores an unknown sort and a non-numeric age", () => {
    const f = filtersFromSearch(new URLSearchParams("sort=newest&min_age_hours=soon"))
    expect(f.sort).toBe("lost")
    expect(f.minAgeHours).toBeNull()
  })

  it("round-trips and omits defaults", () => {
    const f = { ...EMPTY_FILTERS, classIds: ["a"], q: " x " }
    expect(filtersToSearch(f).toString()).toBe("q=x&class_id=a")
    expect(filtersFromSearch(filtersToSearch(f))).toEqual({ ...f, q: "x" })
    expect(filtersToSearch(EMPTY_FILTERS).toString()).toBe("")
  })

  it("keeps a non-default sort in the URL", () => {
    expect(filtersToSearch({ ...EMPTY_FILTERS, sort: "oldest" }).toString()).toBe("sort=oldest")
  })

  it("knows when filters are active (sort alone is not a filter)", () => {
    expect(filtersActive(EMPTY_FILTERS)).toBe(false)
    expect(filtersActive({ ...EMPTY_FILTERS, sort: "oldest" })).toBe(false)
    expect(filtersActive({ ...EMPTY_FILTERS, q: "a" })).toBe(true)
    expect(filtersActive({ ...EMPTY_FILTERS, minAgeHours: 6 })).toBe(true)
  })

  it("builds the API path with the sort always explicit, plus limit and cursor", () => {
    expect(reviewQueuePath(EMPTY_FILTERS, { limit: 50 })).toBe("/teacher/review?sort=lost&limit=50")
    expect(reviewQueuePath({ ...EMPTY_FILTERS, reasons: ["plagiarism_flag"] }, { limit: 50, cursor: "abc" })).toBe(
      "/teacher/review?reason=plagiarism_flag&sort=lost&limit=50&cursor=abc",
    )
  })

  it("gives order-independent filter keys", () => {
    const a = { ...EMPTY_FILTERS, classIds: ["b", "a"] }
    const b = { ...EMPTY_FILTERS, classIds: ["a", "b"] }
    expect(filterKey(a)).toBe(filterKey(b))
    expect(filterKey(a)).not.toBe(filterKey({ ...b, sort: "oldest" }))
  })
})
