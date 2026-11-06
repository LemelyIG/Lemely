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
  invalidateTeam: () => undefined,
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

/** Rendered text with the markup stripped, so figures set in their own span read as one sentence. */
const text = (html: string) => html.replace(/<[^>]+>/g, "").replace(/&#x27;/g, "'")

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

  it("sets overflow figures in the data face and formats them alike", () => {
    const seat = { ...fx.seat, capUnits: 12000, capUsedUnits: 3400 }
    const html = renderStatic(h(SeatsPanel, { team: { ...fx.team, seats: [seat] } }))
    expect(html).toContain('<span class="text-data-sm">12,000</span>')
    expect(html).toContain('<span class="text-data-sm">3,400</span>')
  })

  it("offers no second reduction while one is pending", () => {
    const html = renderStatic(h(SeatsPanel, { team: { ...fx.team, pendingExtraSeats: 1 } }))
    expect(html).toContain("Drops to 1 extra seat on")
    expect(html).not.toContain("Remove extra seats")
  })

  it("hides removal for a leaving seat", () => {
    const leaving = { ...fx.seat, status: "leaving" as const, leavesAt: "2026-12-01T00:00:00Z" }
    const html = renderStatic(h(SeatsPanel, { team: { ...fx.team, seats: [leaving] } }))
    expect(html).toContain(`Leaving on ${formatBillingDate("2026-12-01T00:00:00Z")}`)
    expect(html).not.toContain("Remove Omar Hassan")
  })

  it("shows overflow use and a seat that has not started its allowance", () => {
    const seat = { ...fx.seat, meterFraction: null, capUnits: 500, capUsedUnits: 120 }
    const html = renderStatic(h(SeatsPanel, { team: { ...fx.team, seats: [seat] } }))
    expect(text(html)).toContain("Up to 500 of your credits a month (120 used)")
    expect(html).toContain("Not started")
  })
})

describe("Team screen", () => {
  it("has no eyebrow above its heading", () => {
    const html = renderStatic(h(Team))
    expect(html).toContain("Seats and assistants")
    expect(html).not.toContain("Your team")
  })

  it("tells an assistant that the lead teacher manages seats, with no retry", () => {
    s.team = errorQuery(new ApiError(403, "x"))
    const html = renderStatic(h(Team))
    expect(html).toContain("managed by the lead teacher")
    expect(html).not.toContain("Try again")
  })

  it("offers a retry on any other failure", () => {
    s.team = errorQuery(new ApiError(500, "x"))
    const html = renderStatic(h(Team))
    expect(html).toContain("Couldn&#x27;t load your team")
    expect(html).toContain("Check your connection")
    expect(html).toContain("Try again")
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

  it("offers only the actions a seat can pay for, whatever the row carries", () => {
    const html = render({ ...fx.seat, scopeActions: ["mark_paper", "regrade"] as never })
    expect(html).toMatch(/<input(?=[^>]*value="mark_paper")(?=[^>]*checked)[^>]*>/)
    expect(html).not.toContain('value="regrade"')
  })

  it("allows a limit of zero", () => {
    const html = render({ ...fx.seat, capUnits: 0 })
    expect(html).toMatch(/<input(?=[^>]*min="0")(?=[^>]*value="0")[^>]*>/)
    expect(html).not.toContain("Enter a credit limit.")
  })

  it("reports a failed scope save in seat terms, never as a charge", () => {
    s.m.scope = fakeMutation({ isError: true, error: new ApiError(422, "x", { code: "invalid_scope", message: "x" }) })
    const html = render()
    expect(html).toContain('role="alert"')
    expect(html).toContain("Choose only the subjects and actions listed")
    expect(html).not.toContain("charged")
  })

  it("reports a failed cap save", () => {
    s.m.cap = fakeMutation({ isError: true, error: new ApiError(422, "x", { code: "invalid_cap", message: "x" }) })
    expect(render()).toContain("The credit limit must be a whole number, zero or more.")
  })
})

describe("RemoveSeatDialog", () => {
  it("states month-end release with the date the list will show", () => {
    vi.useFakeTimers({ now: new Date("2026-11-06T12:00:00Z") })
    try {
      const html = renderStatic(h(RemoveSeatDialog, { open: true, onClose: () => undefined, seat: fx.seat }))
      expect(html).toContain("keeps the seat until the end of")
      expect(html).toContain(formatBillingDate("2026-12-01T00:00:00Z"))
      expect(html).toContain("Remove at month end")
    } finally {
      vi.useRealTimers()
    }
  })

  it("reports a refused removal in seat terms", () => {
    s.m.remove = fakeMutation({ isError: true, error: new ApiError(403, "x") })
    const html = renderStatic(h(RemoveSeatDialog, { open: true, onClose: () => undefined, seat: fx.seat }))
    expect(html).toContain("Only the lead teacher can change seats.")
    expect(html).not.toContain("charged")
  })
})

describe("seat count dialogs", () => {
  it("asks for a count before quoting", () => {
    const html = addDialog()
    expect(html).toContain("Get the price")
    expect(html).toContain("Between 1 and 100.")
    expect(html).not.toContain("Pay EGP")
  })

  it("quotes and confirms extra seats against the saved card", () => {
    s.m.quote = fakeMutation({ isSuccess: true, data: quoted })
    const html = addDialog()
    expect(html).toMatch(/Pay EGP\s45\.00 for 1 seat</)
    expect(text(html)).toMatch(/For 1 seat you pay EGP\s45\.00 now/)
    expect(text(html)).toMatch(/EGP\s30\.00 per seat/)
    expect(html).toContain("Mastercard")
  })

  it("refuses without a saved card", () => {
    s.m.quote = fakeMutation({ isSuccess: true, data: quoted })
    const html = addDialog(null)
    expect(html).toContain("Seats are charged to a saved card.")
    expect(html).not.toContain("Pay EGP")
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
      renderStatic(h(ReduceSeatsDialog, { open: true, onClose: () => undefined, subscriptionId: "sub-t", extraSeats: 2, removable: 2 }))
    expect(reduce()).toContain("More students hold seats than this would leave.")
    s.m.reduce = fakeMutation({ isSuccess: true, data: { extraSeats: 2, pendingExtraSeats: 1 } })
    expect(reduce()).toContain("1 extra seat from the end of this period.")
  })

  it("names the seats being removed and the most that can go", () => {
    s.m.reduce = fakeMutation()
    const html = renderStatic(
      h(ReduceSeatsDialog, { open: true, onClose: () => undefined, subscriptionId: "sub-t", extraSeats: 5, removable: 2 }),
    )
    expect(html).toContain("Remove 1 seat at period end")
    expect(html).toContain("Up to 2 can go.")
  })

  it("says so, with no way to submit, when students hold every extra seat", () => {
    s.m.reduce = fakeMutation()
    const html = renderStatic(
      h(ReduceSeatsDialog, { open: true, onClose: () => undefined, subscriptionId: "sub-t", extraSeats: 2, removable: 0 }),
    )
    expect(html).toContain("Students hold every seat you could remove.")
    expect(html).not.toContain('name="How many')
    expect(html).toMatch(/<button[^>]*disabled[^>]*>[^<]*at period end/)
  })
})
