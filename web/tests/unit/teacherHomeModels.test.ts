import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { atRiskRowModel, classCardModel, reviewQueueModel } from "@/portals/teacher/home/models"
import type { ClassSummary } from "@/lib/teacherTypes"

describe("reviewQueueModel", () => {
  it("scales bars to the largest bucket and marks bands under the server threshold as low", () => {
    const m = reviewQueueModel({ pendingReviewCount: 6, reviewConfidenceBuckets: [0, 0, 0, 0, 0, 2, 4, 0, 0, 0], reviewEstimateMinutes: 2, reviewConfidenceThreshold: 0.7 })
    expect(m.count).toBe(6)
    expect(m.bars[6]).toEqual({ band: 6, height: 1, low: true })
    expect(m.bars[5]).toEqual({ band: 5, height: 0.5, low: true })
    expect(m.bars[7].low).toBe(false)
    expect(m.estimate).toBe("about 2 min")
    expect(m.empty).toBe(false)
  })

  it("is empty with zero pending and shows no estimate", () => {
    const m = reviewQueueModel({ pendingReviewCount: 0, reviewConfidenceBuckets: Array(10).fill(0), reviewEstimateMinutes: 0 })
    expect(m.empty).toBe(true)
    expect(m.estimate).toBeNull()
    expect(m.bars.every((b) => b.height === 0)).toBe(true)
  })

  it("tolerates a short or missing bucket list from an older server", () => {
    const m = reviewQueueModel({ pendingReviewCount: 1, reviewConfidenceBuckets: [], reviewEstimateMinutes: 1, reviewConfidenceThreshold: 0.9 })
    expect(m.bars).toHaveLength(10)
    expect(m.lowCount).toBe(0)
  })

  it("derives the threshold band and low count from the DTO threshold", () => {
    const m = reviewQueueModel({ pendingReviewCount: 9, reviewConfidenceBuckets: [1, 0, 0, 0, 0, 2, 0, 0, 3, 2], reviewEstimateMinutes: 3, reviewConfidenceThreshold: 0.9 })
    expect(m.thresholdPct).toBe(90)
    expect(m.bars[8].low).toBe(true)
    expect(m.bars[9].low).toBe(false)
    // Below 90%: bands 0..8 = 1 + 2 + 3. The headline count stays the server's
    // pendingReviewCount, which also includes rows with no confidence score.
    expect(m.lowCount).toBe(6)
    expect(m.count).toBe(9)
  })

  it("says every answer is below the threshold only when the low count is the whole queue", () => {
    const all = reviewQueueModel({ pendingReviewCount: 3, reviewConfidenceBuckets: [0, 0, 0, 0, 0, 2, 1, 0, 0, 0], reviewEstimateMinutes: 1, reviewConfidenceThreshold: 0.7 })
    expect(all.allLow).toBe(true)
    // One pending row has no score in any band, so not every answer is below 70%.
    const some = reviewQueueModel({ pendingReviewCount: 4, reviewConfidenceBuckets: [0, 0, 0, 0, 0, 2, 1, 0, 0, 0], reviewEstimateMinutes: 1, reviewConfidenceThreshold: 0.7 })
    expect(some.allLow).toBe(false)
    expect(reviewQueueModel({ pendingReviewCount: 0, reviewConfidenceBuckets: [], reviewEstimateMinutes: 0 }).allLow).toBe(false)
  })

  it("follows a different server threshold", () => {
    const m = reviewQueueModel({ pendingReviewCount: 5, reviewConfidenceBuckets: [0, 0, 0, 0, 0, 2, 1, 1, 1, 0], reviewEstimateMinutes: 2, reviewConfidenceThreshold: 0.7 })
    expect(m.thresholdPct).toBe(70)
    expect(m.lowCount).toBe(3)
  })

  it("falls back to 90% when an older server omits the threshold", () => {
    const m = reviewQueueModel({ pendingReviewCount: 2, reviewConfidenceBuckets: [0, 0, 0, 0, 0, 0, 0, 0, 1, 1], reviewEstimateMinutes: 1 })
    expect(m.thresholdPct).toBe(90)
    expect(m.lowCount).toBe(1)
  })
})

describe("atRiskRowModel", () => {
  it("shows previous to current grade and the first flag summary", () => {
    const m = atRiskRowModel({ name: "Omar Hassan", grade: "D", previousGrade: "C", delta: -0.6, weakTopic: "Moments",
      flags: [{ reason: "declining", summary: "Down 0.6 over 3 papers", evidence: {}, acknowledged: null }] })
    expect(m).toEqual({ initials: "OH", name: "Omar Hassan", reason: "Down 0.6 over 3 papers", from: "C", to: "D", acknowledged: false, moreReasons: 0 })
  })

  it("has no trail when there is no grade yet", () => {
    const m = atRiskRowModel({ name: "Laila", grade: "", previousGrade: null, delta: null, weakTopic: null,
      flags: [{ reason: "inactive", summary: "No paper in 3 weeks", evidence: {}, acknowledged: null }] })
    expect(m.from).toBeNull()
    expect(m.to).toBeNull()
    expect(m.initials).toBe("L")
  })
})

describe("atRiskRowModel flags", () => {
  const ack = { acknowledgedBy: "t1", acknowledgedAt: "2026-11-01T00:00:00Z", note: null }
  const base = { name: "Omar Hassan", grade: "D", previousGrade: "C", delta: -0.6, weakTopic: null }

  it("tags an acknowledged flag and counts the other reasons", () => {
    const m = atRiskRowModel({ ...base, flags: [
      { reason: "declining", summary: "Down 0.6", evidence: {}, acknowledged: ack },
      { reason: "inactive", summary: "No paper in 3 weeks", evidence: {}, acknowledged: ack },
      { reason: "low_grade", summary: "Grade D", evidence: {}, acknowledged: ack },
    ] } as never)
    expect(m.acknowledged).toBe(true)
    expect(m.moreReasons).toBe(2)
  })

  it("shows an unacknowledged flag first and is not tagged", () => {
    const m = atRiskRowModel({ ...base, flags: [
      { reason: "declining", summary: "Down 0.6", evidence: {}, acknowledged: ack },
      { reason: "inactive", summary: "No paper in 3 weeks", evidence: {}, acknowledged: null },
    ] } as never)
    expect(m.reason).toBe("No paper in 3 weeks")
    expect(m.acknowledged).toBe(false)
    expect(m.moreReasons).toBe(1)
  })

  it("has no reasons to count when there are no flags", () => {
    const m = atRiskRowModel({ ...base, flags: [] })
    expect(m.acknowledged).toBe(false)
    expect(m.moreReasons).toBe(0)
  })
})

describe("classCardModel", () => {
  it("formats meta from real fields only", () => {
    const m = classCardModel({ id: "c1", label: "Year 11 Chemistry", studentCount: 52, average: 61.4, subjectCode: "0620",
      subjectName: "Chemistry", schoolId: null, joinCode: "K7M4QX", atRiskCount: 2, lastActivityAt: null, topWeakness: "Electrolysis" })
    expect(m).toMatchObject({ id: "c1", title: "Year 11 Chemistry", meta: "0620 · 52 students", average: "61%", weakTopic: "Electrolysis" })
  })

  it("omits what the class does not have", () => {
    const m = classCardModel({ id: "c2", label: "Physics group", studentCount: 1, average: null, subjectCode: null,
      subjectName: null, schoolId: null, joinCode: null, atRiskCount: null, lastActivityAt: null, topWeakness: null })
    expect(m.meta).toBe("1 student")
    expect(m.average).toBeNull()
    expect(m.grade).toBeNull()
    expect(m.trend).toBeNull()
    expect(m.meta2).toBeNull()
    expect(m.weakPct).toBeNull()
    expect(m.weakBar).toBeNull()
  })
})

describe("classCardModel grade and trend", () => {
  const base: ClassSummary = { id: "c3", label: "11P", studentCount: 3, average: 62, subjectCode: "0625", subjectName: "Physics",
    schoolId: null, joinCode: null, atRiskCount: 0, lastActivityAt: null, topWeakness: "Waves" }

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-11-05T12:00:00Z"))
  })
  afterEach(() => vi.useRealTimers())

  it("carries the median grade, a signed upward trend and the last paper with its date", () => {
    const m = classCardModel({ ...base, grade: "B", delta: 0.4, lastPaper: "P4", lastActivityAt: "2026-11-02T12:00:00Z" })
    expect(m.grade).toBe("B")
    expect(m.trend).toEqual({ text: "+0.4", tone: "up" })
    expect(m.meta2).toBe("P4 · 3d ago")
  })

  it("marks a fall as down without a plus sign and no change as flat", () => {
    expect(classCardModel({ ...base, delta: -2.25 }).trend).toEqual({ text: "-2.3", tone: "down" })
    expect(classCardModel({ ...base, delta: 0 }).trend).toEqual({ text: "0.0", tone: "flat" })
  })

  it("shows whichever of the paper and date exists", () => {
    expect(classCardModel({ ...base, lastPaper: "P2" }).meta2).toBe("P2")
    expect(classCardModel({ ...base, lastActivityAt: "2026-11-05T11:30:00Z" }).meta2).toBe("30m ago")
  })

  it("turns the weak topic accuracy into a percentage and a clamped bar", () => {
    const m = classCardModel({ ...base, topWeaknessAccuracy: 0.384 })
    expect(m.weakPct).toBe("38%")
    expect(m.weakBar).toBe(0.384)
    expect(classCardModel({ ...base, topWeaknessAccuracy: 1.2 }).weakBar).toBe(1)
  })

  it("drops a weak accuracy that has no topic to belong to", () => {
    const m = classCardModel({ ...base, topWeakness: null, topWeaknessAccuracy: 0.5 })
    expect(m.weakPct).toBeNull()
    expect(m.weakBar).toBeNull()
  })
})
