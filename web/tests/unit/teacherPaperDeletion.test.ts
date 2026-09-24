import { describe, expect, it } from "vitest"
import {
  deleteCountdown,
  reshareConsequence,
  teacherPaperCountdownLabel,
  unshareConsequence,
} from "@/lib/teacherPaperDeletion"

describe("teacherPaperCountdownLabel", () => {
  it("reads the closed window", () => {
    expect(teacherPaperCountdownLabel(0)).toBe("Restore window closed")
  })

  it("reads the singular day", () => {
    expect(teacherPaperCountdownLabel(1)).toBe("1 day left to restore")
  })

  it("reads the plural, matching the student screen's own wording", () => {
    expect(teacherPaperCountdownLabel(29)).toBe("29 days left to restore")
  })
})

describe("the re-exported deleteCountdown stays in step with the student flow", () => {
  it("floors to whole days, same as paperDeletion.ts's own test", () => {
    expect(deleteCountdown("2026-10-21T12:00:00Z", "2026-09-22T00:00:00Z")).toBe(29)
  })
})

describe("unshareConsequence — D9's rule that a student loses nothing", () => {
  const copy = unshareConsequence("0625 Paper 4, May/June 2024")

  it("names the paper", () => {
    expect(copy).toContain("0625 Paper 4, May/June 2024")
  })

  it("scopes the effect to this class only", () => {
    expect(copy).toMatch(/this class/i)
  })

  it("says the student's own copy is unchanged", () => {
    expect(copy).toMatch(/student's own copy is unchanged/i)
  })

  it("says a reshare is always possible, so nothing here reads as permanent", () => {
    expect(copy).toMatch(/reshare/i)
  })

  it("never implies the student loses anything — no delete/remove/gone language", () => {
    expect(copy).not.toMatch(/\bdelete(d)?\b|\bremove(d)?\b|\bgone\b|\blost\b/i)
  })
})

describe("reshareConsequence", () => {
  it("names the paper and says it counts again", () => {
    expect(reshareConsequence("0625 Paper 4, May/June 2024")).toBe(
      "0625 Paper 4, May/June 2024 will count in this class again.",
    )
  })
})
