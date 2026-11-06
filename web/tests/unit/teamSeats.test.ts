import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { formatBillingDate } from "@/lib/billingFormat"
import { fx } from "./support/billingFixtures"
import { errorQuery, fakeMutation, okQuery, pendingQuery, renderStatic } from "./support/billingRender"

const s = vi.hoisted(() => ({
  team: null as unknown,
  m: {} as Record<string, unknown>,
}))
vi.mock("@/lib/hooks/useTeamApi", () => ({
  useTeam: () => s.team,
  useSetSeatScope: () => s.m.scope,
  useSetMemberCap: () => s.m.cap,
  useRemoveSeat: () => s.m.remove,
}))
vi.mock("@/lib/hooks/useBillingApi", () => ({
  useSeatQuote: () => s.m.quote,
  useAddSeats: () => s.m.add,
  useReduceSeats: () => s.m.reduce,
  usePaymentStatus: () => Object.assign(okQuery(fx.payment), { pollingStopped: false }),
  invalidateBilling: () => undefined,
}))
vi.mock("@/components/ui/modal", () => ({
  Modal: (p: { open: boolean; title: unknown; children: unknown; footer?: unknown }) =>
    p.open ? h("div", { role: "dialog" }, h("h2", null, p.title as never), p.children as never, p.footer as never) : null,
}))

import { AddSeatsDialog, ReduceSeatsDialog } from "@/portals/teacher/screens/team/SeatCountDialogs"
import { RemoveSeatDialog, SeatEditorDialog } from "@/portals/teacher/screens/team/SeatEditorDialog"
import { SeatsPanel } from "@/portals/teacher/screens/team/SeatsPanel"
import { Team } from "@/portals/teacher/screens/team/Team"

beforeEach(() => {
  s.team = okQuery(fx.team)
  s.m = { scope: fakeMutation(), cap: fakeMutation(), remove: fakeMutation(), quote: fakeMutation(), add: fakeMutation(), reduce: fakeMutation() }
})

const quoted = { amountMinor: 4500, currency: "EGP", allowanceUnits: null, periodEnd: "2026-12-01T00:00:00Z" }
const addDialog = (savedCard = fx.team.savedCard) =>
  renderStatic(h(AddSeatsDialog, { open: true, onClose: () => undefined, subscriptionId: "sub-t", perSeatMinor: 3000, savedCard }))

describe("SeatsPanel", () => {
  it("shows capacity, the seat list and actions", () => {
    const html = renderStatic(h(SeatsPanel, { team: fx.team }))
    expect(html).toContain("1 of 22 seats used")
    expect(html).toContain("20 included with your plan, 2 extra")
    expect(html).toContain("Omar Hassan")
    expect(html).toContain("Mathematics · Paper marking, Self-review")
    expect(html).toContain("40%")
    expect(html).toContain("Add seats")
    expect(html).toContain("Remove extra seats")
  })

  it("never shows allowance units, only a share", () => {
    const html = renderStatic(h(SeatsPanel, { team: fx.team }))
    expect(html).not.toMatch(/allowance[^<]*\d+ (credits|units)/i)
    expect(html).toMatch(/aria-label="Omar Hassan&#x27;s seat use this month"/)
  })

  it("explains an inactive plan, a scheduled reduction and an empty list", () => {
    const html = renderStatic(h(SeatsPanel, { team: { ...fx.team, planActive: false, pendingExtraSeats: 0, seats: [] } }))
    expect(html).toMatch(/role="status"[^>]*>.*seats get no new monthly allowances/)
    expect(html).toContain('href="/teacher/billing/plans"')
    expect(html).toContain("Drops to 0 extra seats on")
    expect(html).toContain("No students hold a seat yet.")
  })

  it("says so when every seat is taken", () => {
    const html = renderStatic(h(SeatsPanel, { team: { ...fx.team, seatsUsed: 22 } }))
    expect(html).toContain("22 of 22 seats used")
    expect(html).toContain("Every seat is taken.")
  })

  it("offers no add or reduce controls without a plan or extra seats", () => {
    const html = renderStatic(h(SeatsPanel, { team: { ...fx.team, planActive: false, subscriptionId: null, extraSeats: 0 } }))
    expect(html).toMatch(/<button[^>]*disabled[^>]*>Add seats/)
    expect(html).not.toContain("Remove extra seats")
  })

  it("hides removal for a leaving seat", () => {
    const leaving = { ...fx.seat, status: "leaving" as const, leavesAt: "2026-11-30T23:59:59Z" }
    const html = renderStatic(h(SeatsPanel, { team: { ...fx.team, seats: [leaving] } }))
    expect(html).toContain(`Leaving on ${formatBillingDate("2026-11-30T23:59:59Z")}`)
    expect(html).not.toContain("Remove Omar Hassan")
  })

  it("shows overflow use and a seat that has not started its allowance", () => {
    const seat = { ...fx.seat, meterFraction: null, capUnits: 500, capUsedUnits: 120 }
    const html = renderStatic(h(SeatsPanel, { team: { ...fx.team, seats: [seat] } }))
    expect(html).toContain("Up to 500 of your credits a month (120 used)")
    expect(html).toContain("Not started")
  })
})

describe("Team screen", () => {
  it("has no eyebrow above its heading", () => {
    const html = renderStatic(h(Team))
    expect(html).toContain("Seats and assistants")
    expect(html).not.toContain("Your team")
  })

  it("tells an assistant that the lead teacher manages seats", () => {
    s.team = errorQuery(new ApiError(403, "x"))
    expect(renderStatic(h(Team))).toContain("managed by the lead teacher")
  })

  it("offers a retry on any other failure", () => {
    s.team = errorQuery(new ApiError(500, "x"))
    const html = renderStatic(h(Team))
    expect(html).toContain("Couldn&#x27;t load your team")
    expect(html).toContain("Check your connection")
  })

  it("shows a skeleton while loading", () => {
    s.team = pendingQuery()
    expect(renderStatic(h(Team))).not.toContain("Student seats")
  })
})

describe("SeatEditorDialog", () => {
  const render = (seat = fx.seat, subjects = [...fx.team.subjects, { code: "0625", name: "Physics" }]) =>
    renderStatic(h(SeatEditorDialog, { open: true, onClose: () => undefined, seat, subjects }))

  it("lists subjects and actions, study plans unchecked by default with its hint", () => {
    const html = render()
    expect(html).toContain("Mathematics")
    expect(html).toContain("Physics")
    expect(html).toContain("Weekly study plans")
    expect(html).toContain("Off by default.")
    expect(html).toMatch(/<input(?=[^>]*value="study_plan")(?![^>]*checked)[^>]*>/)
    expect(html).toMatch(/<input(?=[^>]*value="mark_paper")(?=[^>]*checked)[^>]*>/)
  })

  it("warns when a seat covers no subjects", () => {
    expect(render({ ...fx.seat, scopeSubjects: [] })).toContain("With no subjects, this seat pays for nothing.")
  })

  it("explains when the teacher's classes have no subject to choose", () => {
    expect(render({ ...fx.seat, scopeSubjects: [] }, [])).toContain("Add a subject to a class")
  })

  it("keeps a covered subject editable when no class teaches it any more", () => {
    expect(render({ ...fx.seat, scopeSubjects: ["0606"] }, [])).toMatch(/<input(?=[^>]*value="0606")(?=[^>]*checked)[^>]*>/)
  })

  it("starts with no overflow, and shows the cap fields when one is set", () => {
    expect(render()).toContain("No overflow.")
    const html = render({ ...fx.seat, capUnits: 500, capPeriod: "total" })
    expect(html).toContain("Up to (credits)")
    expect(html).toContain('value="500"')
    expect(html).toMatch(/<option value="total" selected/)
  })

  it("reports a failed save", () => {
    s.m.scope = fakeMutation({ isError: true, error: new ApiError(500, "x") })
    expect(render()).toContain('role="alert"')
  })
})

describe("RemoveSeatDialog", () => {
  it("states month-end release", () => {
    const html = renderStatic(h(RemoveSeatDialog, { open: true, onClose: () => undefined, seat: fx.seat }))
    expect(html).toContain("keeps the seat until")
    expect(html).toContain("Remove at month end")
  })
})

describe("seat count dialogs", () => {
  it("asks for a count before quoting", () => {
    const html = addDialog()
    expect(html).toContain("Get the price")
    expect(html).not.toContain("and add seats")
  })

  it("quotes and confirms extra seats against the saved card", () => {
    s.m.quote = fakeMutation({ isSuccess: true, data: quoted })
    const html = addDialog()
    expect(html).toMatch(/Pay EGP\s45\.00 and add seats/)
    expect(html).toMatch(/EGP\s30\.00 per seat/)
    expect(html).toContain("Mastercard")
  })

  it("refuses without a saved card", () => {
    s.m.quote = fakeMutation({ isSuccess: true, data: quoted })
    const html = addDialog(null)
    expect(html).toContain("Seats are charged to a saved card.")
    expect(html).not.toContain("and add seats")
  })

  it("follows the charge after confirming", () => {
    s.m.add = fakeMutation({ isSuccess: true, data: { paymentId: "pay1", status: "pending", amountMinor: 4500, currency: "EGP" } })
    expect(addDialog()).toContain("Confirming your payment")
  })

  it("reports a failed quote", () => {
    s.m.quote = fakeMutation({ isError: true, error: new ApiError(500, "x") })
    expect(addDialog()).toContain('role="alert"')
  })

  it("maps a seats-in-use refusal when reducing and reports the new total", () => {
    s.m.reduce = fakeMutation({ isError: true, error: new ApiError(409, "x", { error: "seats_in_use", message: "x" }) })
    const reduce = () =>
      renderStatic(h(ReduceSeatsDialog, { open: true, onClose: () => undefined, subscriptionId: "sub-t", extraSeats: 2 }))
    expect(reduce()).toContain("More students hold seats than this would leave.")
    s.m.reduce = fakeMutation({ isSuccess: true, data: { extraSeats: 2, pendingExtraSeats: 1 } })
    expect(reduce()).toContain("1 extra seat from the end of this period.")
  })
})
