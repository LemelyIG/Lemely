import { describe, expect, it } from "vitest"
import { RUNS_LIMIT, practiceHubKeys, practiceHubPaths } from "@/lib/practiceHubKeys"

describe("practiceHubKeys", () => {
  it("shares the topics key with usePracticeTopics so one fetch serves hub and sheet", () => {
    expect(practiceHubKeys.topics("0625")).toEqual(["practice", "topics", "0625"])
  })

  it("nests every runs key under one prefix, so invalidating runsAll refreshes Recent", () => {
    expect(practiceHubKeys.runs(RUNS_LIMIT).slice(0, 2)).toEqual([...practiceHubKeys.runsAll])
  })

  it("keeps papers keyed per subject", () => {
    expect(practiceHubKeys.papers("0580")).not.toEqual(practiceHubKeys.papers("0625"))
  })
})

describe("practiceHubPaths", () => {
  it("builds the runs path with its limit", () => {
    expect(practiceHubPaths.runs(10)).toBe("/student/practice/runs?limit=10")
  })

  it("encodes path segments", () => {
    expect(practiceHubPaths.papers("06/25")).toBe("/student/practice/papers/06%2F25")
    expect(practiceHubPaths.createFromPaper("a b")).toBe("/student/practice/papers/a%20b")
  })

  it("has no homework entry: a teacher quiz has no take or result screen under Practice yet", () => {
    expect(practiceHubPaths).not.toHaveProperty("homework")
    expect(practiceHubKeys).not.toHaveProperty("homework")
  })
})
