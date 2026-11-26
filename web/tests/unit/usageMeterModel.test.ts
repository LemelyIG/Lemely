import { describe, expect, it } from "vitest"
import {
  allowanceMeterModel,
  creditExpiryLines,
  debtSentence,
  seatMeterModel,
} from "@/lib/usageMeterModel"

const resetsAt = "2026-12-01T00:00:00Z"

describe("allowanceMeterModel", () => {
  it("labels usage with the reset date and bands the note", () => {
    expect(allowanceMeterModel({ fraction: 0.63, resetsAt }, "en-GB")).toEqual({
      percent: 63,
      barValue: 63,
      label: "Usage 63%, resets 1 Dec 2026",
      note: null,
      state: "ok",
    })
    expect(allowanceMeterModel({ fraction: 0.85, resetsAt }, "en-GB").state).toBe("high")
    expect(allowanceMeterModel({ fraction: 0.85, resetsAt }, "en-GB").note).toBe(
      "Most of this month's plan is used.",
    )
    const used = allowanceMeterModel({ fraction: 1.02, resetsAt }, "en-GB")
    expect(used).toMatchObject({ percent: 102, barValue: 100, state: "used_up" })
    expect(used.note).toBe("This month's plan is used up. Credits pay from here.")
  })
})

describe("seatMeterModel", () => {
  it("labels a seat meter without a teacher name (M4) and handles a seat not granted yet", () => {
    const m = seatMeterModel({ teacherMemberId: "m1", teacherUserId: "u9", fraction: 0.4, resetsAt }, "en-GB")
    expect(m.label).toBe("Seat from your teacher: 40% used")
    expect(m.note).toBe("Resets 1 Dec 2026.")
    const fresh = seatMeterModel({ teacherMemberId: "m1", teacherUserId: "u9", fraction: null, resetsAt: null }, "en-GB")
    expect(fresh).toMatchObject({ percent: 0, label: "Seat from your teacher: 0% used", note: "This month's seat allowance starts with your first job." })
  })
})

describe("creditExpiryLines", () => {
  const now = new Date("2026-11-05T00:00:00Z")

  it("sums buckets per expiry day, sorts soonest first, never-expiring last, and drops empties", () => {
    const lines = creditExpiryLines(
      [
        { key: "a", remaining: 300, expiresAt: "2027-10-02T10:00:00Z" },
        { key: "b", remaining: 200, expiresAt: "2027-10-02T18:00:00Z" },
        { key: "c", remaining: 50, expiresAt: null },
        { key: "d", remaining: 100, expiresAt: "2026-11-20T00:00:00Z" },
        { key: "e", remaining: 0, expiresAt: "2026-11-10T00:00:00Z" },
      ],
      now,
      "en-GB",
    )
    expect(lines).toEqual([
      { key: "2026-11-20", units: 100, label: "100 credits expire 20 Nov 2026", soon: true },
      { key: "2027-10-02", units: 500, label: "500 credits expire 2 Oct 2027", soon: false },
      { key: "never", units: 50, label: "50 credits never expire", soon: false },
    ])
  })
})

describe("debtSentence", () => {
  it("returns null with no debt and a role-voiced sentence otherwise", () => {
    expect(debtSentence(0, "student")).toBeNull()
    expect(debtSentence(12, "student")).toBe(
      "A recent job cost 12 credits more than your balance. New work that uses your own balance is paused until your next credit pack or plan renewal clears it.",
    )
    expect(debtSentence(1, "teacher")).toBe(
      "A recent job cost 1 credit more than the balance. New jobs on this balance are paused until the next pack or renewal clears it.",
    )
  })
})
