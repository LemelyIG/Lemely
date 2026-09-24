import { describe, expect, it } from "vitest"
import { deleteCountdown, deletionRefusal, formatDay } from "@/lib/paperDeletion"

function iso(s: string): string {
  return s
}

describe("formatDay", () => {
  it("reads day-then-month, no year, regardless of host locale", () => {
    expect(formatDay(iso("2026-10-21T00:00:00Z"))).toBe("21 October")
  })
})

describe("deleteCountdown", () => {
  it("floors to whole days", () => {
    expect(deleteCountdown(iso("2026-10-21T12:00:00Z"), iso("2026-09-22T00:00:00Z"))).toBe(29)
  })

  it("reads a past deadline as gone, never as negative", () => {
    expect(deleteCountdown(iso("2026-09-01T00:00:00Z"), iso("2026-09-22T00:00:00Z"))).toBe(0)
  })

  it("reads the exact deadline instant as gone", () => {
    expect(deleteCountdown(iso("2026-09-22T00:00:00Z"), iso("2026-09-22T00:00:00Z"))).toBe(0)
  })
})

describe("deletionRefusal", () => {
  it("renders the hold with its date and no reason", () => {
    const copy = deletionRefusal({
      detail: "This paper can't be deleted yet.",
      deletableFrom: "2026-10-21T00:00:00Z",
    })
    expect(copy).toBe("This paper can't be deleted yet. You'll be able to delete it from 21 October.")
    expect(copy).not.toMatch(/review|flag|plagiar|integrity|score/i)
  })

  it("renders the non-hold refusal with no date sentence appended", () => {
    const copy = deletionRefusal({ detail: "Only uploaded papers can be deleted." })
    expect(copy).toBe("Only uploaded papers can be deleted.")
  })

  it("the forbidden-word check would catch a leak", () => {
    expect("flagged for plagiarism").toMatch(/review|flag|plagiar|integrity|score/i)
  })
})
