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
  SEAT_ACTIONS,
  SEAT_ACTION_COPY,
  assistantCapText,
  scopeSummary,
  seatCapText,
  seatCapacityModel,
  seatStatusText,
} from "@/lib/teamModel"
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
    expect(seatStatusText({ ...fx.seat, status: "leaving", leavesAt: "2026-11-30T23:59:59Z" })).toBe(
      `Leaving on ${formatBillingDate("2026-11-30T23:59:59Z")}`,
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
