import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  request: vi.fn(),
}))

import { request } from "@/lib/api"
import { toTeamView } from "@/lib/billingAdapters"
import { formatBillingDate } from "@/lib/billingFormat"
import { teamApi } from "@/lib/hooks/useTeamApi"
import {
  CAP_MAX_UNITS,
  SEAT_ACTIONS,
  SEAT_ACTION_COPY,
  assistantCapText,
  capBody,
  capChanged,
  monthEndInstant,
  monthEndLabel,
  partialSaveMessage,
  planSeatSave,
  removableExtraSeats,
  scopeBody,
  scopeChanged,
  scopeSummary,
  seatActionsIn,
  seatCapParts,
  seatCapText,
  seatCapacityModel,
  seatCountValidation,
  seatStatusText,
  teamFailureMessage,
  teamRetry,
} from "@/lib/teamModel"
import { ApiError } from "@/lib/api"
import { fx } from "./support/billingFixtures"

const req = vi.mocked(request)
beforeEach(() => {
  req.mockReset()
  req.mockResolvedValue({})
})

describe("team fetchers (plan 03 routes; request() adds /api)", () => {
  it("hits every team route with the right method", async () => {
    await teamApi.seats()
    await teamApi.capacity()
    await teamApi.assistants()
    await teamApi.invites()
    await teamApi.memberships()
    await teamApi.setScope("m 1", { subjects: ["0580"], actions: ["mark_paper"] })
    await teamApi.setCap("m1", { capUnits: 500, capPeriod: "month" })
    await teamApi.removeSeat("m1")
    await teamApi.createInvite({ role: "marker", expiresInDays: 7 })
    await teamApi.revokeInvite("inv1")
    await teamApi.updateAssistant("m9", { role: "viewer", permissions: {} })
    await teamApi.removeAssistant("m9")
    await teamApi.redeem("AST-1")
    expect(req.mock.calls.map((c) => [c[0], (c[1] as RequestInit | undefined)?.method ?? "GET"])).toEqual([
      ["/teacher/team/seats", "GET"],
      ["/teacher/team/capacity", "GET"],
      ["/teacher/team/assistants", "GET"],
      ["/teacher/team/invites", "GET"],
      ["/teacher/team/memberships", "GET"],
      ["/teacher/team/seats/m%201/scope", "PUT"],
      ["/teacher/team/members/m1/cap", "PUT"],
      ["/teacher/team/seats/m1", "DELETE"],
      ["/teacher/team/assistants/invites", "POST"],
      ["/teacher/team/invites/inv1", "DELETE"],
      ["/teacher/team/assistants/m9", "PATCH"],
      ["/teacher/team/assistants/m9", "DELETE"],
      ["/teacher/team/assistants/redeem", "POST"],
    ])
  })
})

describe("toTeamView", () => {
  it("assembles seats, assistants, invites, plan fields from the summary and subjects from classes", () => {
    const view = toTeamView({
      seats: { seats: [fx.wireSeat] },
      capacity: { capacity: 22, used: 1, free: 21 },
      assistants: { assistants: [fx.wireAssistant] },
      invites: { invites: [fx.team.invites[0]] },
      summary: fx.wireTeacherSummary,
      classes: {
        classes: [
          { subjectCode: "0580", subjectName: "Mathematics" },
          { subjectCode: "0580", subjectName: "Mathematics" },
          { subjectCode: null, subjectName: null },
        ],
      },
    })
    expect(view).toEqual(fx.team)
  })

  it("reads a teacher with no plan as inactive with no extra seats", () => {
    const view = toTeamView({
      seats: { seats: [] },
      capacity: { capacity: 0, used: 0, free: 0 },
      assistants: { assistants: [] },
      invites: { invites: [] },
      summary: { ...fx.wireTeacherSummary, subscription: null, savedCard: null },
      classes: { classes: [] },
    })
    expect(view).toMatchObject({ planActive: false, subscriptionId: null, extraSeats: 0, extraSeatPriceMinor: null, savedCard: null })
  })
})

describe("team model", () => {
  it("summarises capacity", () => {
    expect(seatCapacityModel(fx.team)).toEqual({
      used: 1,
      capacity: 22,
      free: 21,
      barValue: 5,
      label: "1 of 22 seats used",
      detail: "20 included with your plan, 2 extra",
    })
  })

  it("is full at capacity and never negative", () => {
    expect(seatCapacityModel({ ...fx.team, seatsUsed: 22 })).toMatchObject({ free: 0, barValue: 100 })
    expect(seatCapacityModel({ ...fx.team, seatCapacity: 0, seatsUsed: 0 })).toMatchObject({ free: 0, barValue: 0 })
  })

  it("lists student seat actions with study plans explained", () => {
    expect(SEAT_ACTIONS).toEqual(["mark_paper", "self_review", "study_plan", "mark_quiz", "generate_flashcards"])
    expect(SEAT_ACTION_COPY.study_plan.hint).toContain("Off by default.")
  })

  it("describes status, caps and scope", () => {
    expect(seatStatusText(fx.seat)).toBe("Active")
    expect(seatStatusText({ ...fx.seat, status: "leaving", leavesAt: "2026-12-01T00:00:00Z" })).toBe(
      `Leaving on ${formatBillingDate("2026-12-01T00:00:00Z")}`,
    )
    expect(seatCapText(fx.seat)).toBe("No overflow")
    expect(seatCapText({ ...fx.seat, capUnits: 500, capPeriod: "month", capUsedUnits: 120 })).toBe(
      "Up to 500 of your credits a month (120 used)",
    )
    expect(assistantCapText({ ...fx.assistant, capUnits: null })).toBe("No limit")
    expect(assistantCapText(fx.assistant)).toBe("Up to 2,000 credits a month (300 used)")
    expect(scopeSummary(fx.seat, fx.team.subjects)).toBe("Mathematics · Paper marking, Self-review")
  })
})

describe("seat editor builders", () => {
  it("drops anything a seat cannot pay for and orders by the catalogue", () => {
    expect(scopeBody(["0580", "0580"], ["self_review", "regrade", "mark_paper", "mark_paper"])).toEqual({
      subjects: ["0580"],
      actions: ["mark_paper", "self_review"],
    })
    expect(seatActionsIn(["generate_quiz", "study_plan"])).toEqual(["study_plan"])
  })

  it("sees a scope change only when the sets differ", () => {
    expect(scopeChanged(fx.seat, { subjects: ["0580"], actions: ["self_review", "mark_paper"] })).toBe(false)
    expect(scopeChanged(fx.seat, { subjects: ["0580"], actions: ["mark_paper", "self_review", "study_plan"] })).toBe(true)
    expect(scopeChanged(fx.seat, { subjects: [], actions: ["mark_paper", "self_review"] })).toBe(true)
  })

  it("builds the cap body: none, zero, a limit, or a field error without coercion", () => {
    expect(capBody(false, "garbage", "total")).toEqual({ ok: true, body: { capUnits: null, capPeriod: "total" } })
    expect(capBody(true, "0", "month")).toEqual({ ok: true, body: { capUnits: 0, capPeriod: "month" } })
    expect(capBody(true, " 750 ", "month")).toEqual({ ok: true, body: { capUnits: 750, capPeriod: "month" } })
    for (const bad of ["", "  ", "-5", "1.5", "1e3", "abc"]) expect(capBody(true, bad, "month").ok, bad).toBe(false)
    expect(capBody(true, String(CAP_MAX_UNITS + 1), "month")).toMatchObject({ ok: false, error: expect.stringContaining("or fewer") })
    expect(capBody(true, String(CAP_MAX_UNITS), "month").ok).toBe(true)
  })

  it("sends the cap only when it changed", () => {
    expect(capChanged(fx.seat, { capUnits: null, capPeriod: "total" })).toBe(false)
    expect(capChanged(fx.seat, { capUnits: 0, capPeriod: "month" })).toBe(true)
    const capped = { ...fx.seat, capUnits: 500 }
    expect(capChanged(capped, { capUnits: 500, capPeriod: "month" })).toBe(false)
    expect(capChanged(capped, { capUnits: 500, capPeriod: "total" })).toBe(true)
    expect(capChanged(capped, { capUnits: null, capPeriod: "month" })).toBe(true)
  })

  it("formats used and limit alike", () => {
    expect(seatCapParts({ ...fx.seat, capUnits: 12000, capUsedUnits: 3400 })).toEqual({ limit: "12,000", used: "3,400", period: "a month" })
    expect(seatCapParts(fx.seat)).toBeNull()
    expect(assistantCapText({ ...fx.assistant, capUsedUnits: 1500 })).toBe("Up to 2,000 credits a month (1,500 used)")
  })
})

describe("seat counts", () => {
  it("accepts whole numbers in range and says what is wrong otherwise", () => {
    expect(seatCountValidation("3", 100)).toEqual({ ok: true, seats: 3 })
    expect(seatCountValidation(" 100 ", 100)).toEqual({ ok: true, seats: 100 })
    expect(seatCountValidation("150", 100)).toEqual({ ok: false, error: "Use 100 or fewer." })
    expect(seatCountValidation("0", 100)).toEqual({ ok: false, error: "Use at least 1." })
    expect(seatCountValidation("", 100)).toEqual({ ok: false, error: "Enter how many seats." })
    expect(seatCountValidation("2.5", 100)).toEqual({ ok: false, error: "Use a whole number." })
    expect(seatCountValidation("-1", 100)).toEqual({ ok: false, error: "Use a whole number." })
  })

  it("bounds removal by extra seats and by free seats", () => {
    expect(removableExtraSeats({ extraSeats: 5, seatCapacity: 25, seatsUsed: 20 })).toBe(5)
    expect(removableExtraSeats({ extraSeats: 5, seatCapacity: 25, seatsUsed: 23 })).toBe(2)
    expect(removableExtraSeats({ extraSeats: 5, seatCapacity: 25, seatsUsed: 25 })).toBe(0)
    expect(removableExtraSeats({ extraSeats: 0, seatCapacity: 20, seatsUsed: 0 })).toBe(0)
    expect(seatCountValidation("3", removableExtraSeats({ extraSeats: 5, seatCapacity: 25, seatsUsed: 23 }))).toEqual({
      ok: false,
      error: "Use 2 or fewer.",
    })
  })
})

describe("month end", () => {
  it("is the first instant of the next UTC month, like the backend", () => {
    expect(monthEndInstant(new Date("2026-11-06T12:00:00Z"))).toBe("2026-12-01T00:00:00.000Z")
    expect(monthEndInstant(new Date("2026-12-31T23:59:59Z"))).toBe("2027-01-01T00:00:00.000Z")
    expect(monthEndInstant(new Date("2026-01-31T23:59:59Z"))).toBe("2026-02-01T00:00:00.000Z")
  })

  it("names the month the removal happens in, in UTC", () => {
    expect(monthEndLabel(new Date("2026-11-06T12:00:00Z"), "en-GB")).toBe("the end of November")
    expect(monthEndLabel(new Date("2026-11-30T23:30:00Z"), "en-GB")).toBe("the end of November")
    expect(monthEndLabel(new Date("2026-12-01T00:00:00Z"), "en-GB")).toBe("the end of December")
  })
})

describe("teamFailureMessage", () => {
  const err = (status: number, code?: string) => new ApiError(status, "x", code ? { code, message: "x" } : undefined)
  it("speaks in seat terms and never claims a charge", () => {
    const all = [0, 403, 404, 409, 422, 429, 500].map((s) => teamFailureMessage(err(s), "save the seat"))
    for (const m of all) expect(m).not.toMatch(/charge/i)
    expect(teamFailureMessage(err(403), "x")).toBe("Only the lead teacher can change seats.")
    expect(teamFailureMessage(err(0), "x")).toContain("offline")
    expect(teamFailureMessage(err(404), "x")).toContain("isn't there any more")
    expect(teamFailureMessage(err(409, "conflict"), "x")).toContain("isn't possible right now")
    expect(teamFailureMessage(err(500), "save the seat")).toBe("Couldn't save the seat. Try again.")
  })

  it("maps the backend's 422 codes", () => {
    expect(teamFailureMessage(err(422, "invalid_scope"), "x")).toContain("subjects and actions listed")
    expect(teamFailureMessage(err(422, "invalid_cap"), "x")).toContain("zero or more")
    expect(teamFailureMessage(err(422), "save the seat")).toBe("Couldn't save the seat. Check the details and try again.")
  })
})

describe("teamRetry", () => {
  it("never retries a refusal or bad request, retries a server or network failure once", () => {
    for (const status of [400, 401, 403, 404, 409, 422, 429]) expect(teamRetry(0, new ApiError(status, "x")), String(status)).toBe(false)
    for (const status of [0, 500, 502, 503]) {
      expect(teamRetry(0, new ApiError(status, "x")), String(status)).toBe(true)
      expect(teamRetry(1, new ApiError(status, "x")), `${status} again`).toBe(false)
    }
    expect(teamRetry(0, new Error("boom"))).toBe(true)
    expect(teamRetry(1, new Error("boom"))).toBe(false)
  })
})

describe("planSeatSave", () => {
  const noCap = { capUnits: null, capPeriod: "month" as const }
  const same = { subjects: ["0580"], actions: ["mark_paper", "self_review"] }
  const plan = (over: Partial<Parameters<typeof planSeatSave>[0]["draft"]> = {}, savedScope = null as Parameters<typeof planSeatSave>[0]["savedScope"]) =>
    planSeatSave({ seat: fx.seat, draft: { ...same, cap: noCap, ...over }, savedScope })

  it("sends nothing when nothing changed", () => {
    expect(plan()).toEqual({ sendScope: null, sendCap: null })
  })

  it("sends only what changed", () => {
    expect(plan({ actions: ["mark_paper", "self_review", "study_plan"] })).toEqual({
      sendScope: { subjects: ["0580"], actions: ["mark_paper", "self_review", "study_plan"] },
      sendCap: null,
    })
    expect(plan({ cap: { capUnits: 0, capPeriod: "month" } })).toEqual({ sendScope: null, sendCap: { capUnits: 0, capPeriod: "month" } })
  })

  it("does not resend a scope it already saved, but does resend after it is reverted", () => {
    const saved = { subjects: ["0580"], actions: ["mark_paper", "self_review", "study_plan"] }
    const cap = { capUnits: 500, capPeriod: "month" as const }
    const draft = { ...saved, cap }
    expect(planSeatSave({ seat: fx.seat, draft, savedScope: saved })).toEqual({ sendScope: null, sendCap: cap })
    // Reverted to what the seat started with: the server now holds `saved`, so the original must go out again.
    expect(plan({ cap }, saved)).toEqual({ sendScope: { subjects: ["0580"], actions: ["mark_paper", "self_review"] }, sendCap: cap })
  })

  it("drops actions a seat cannot pay for before comparing", () => {
    expect(plan({ actions: ["mark_paper", "self_review", "regrade"] })).toEqual({ sendScope: null, sendCap: null })
  })
})

describe("partialSaveMessage", () => {
  it("says the scope was saved when the cap then failed", () => {
    const msg = partialSaveMessage(same, new ApiError(422, "x", { code: "invalid_cap", message: "x" }))
    expect(msg).toBe("Your subjects and actions were saved, but the credit limit wasn't. The credit limit must be a whole number, zero or more.")
  })

  it("is null when nothing was saved first or nothing failed", () => {
    expect(partialSaveMessage(null, new ApiError(500, "x"))).toBeNull()
    expect(partialSaveMessage(same, null)).toBeNull()
  })

  const same = { subjects: ["0580"], actions: ["mark_paper"] }
})
