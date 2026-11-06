import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { fx } from "./support/billingFixtures"
import { errorQuery, fakeMutation, okQuery, pendingQuery, renderStatic } from "./support/billingRender"

const s = vi.hoisted(() => ({ catalogue: null as unknown }))
vi.mock("@/lib/hooks/useAdminBillingApi", () => ({
  useAdminCatalogue: () => s.catalogue,
  useCreateTier: () => fakeMutation(),
  useUpdateTier: () => fakeMutation(),
  useSyncTier: () => fakeMutation(),
  useCreatePack: () => fakeMutation(),
  useUpdatePack: () => fakeMutation(),
  useCreateRate: () => fakeMutation(),
  useCreateEstimator: () => fakeMutation(),
  useUpdateFreeAllowances: () => fakeMutation(),
}))
vi.mock("@/components/ui/modal", () => ({
  Modal: (p: { open: boolean; title: unknown; children: unknown; footer?: unknown }) =>
    p.open ? h("div", { role: "dialog" }, h("h2", null, p.title as never), p.children as never, p.footer as never) : null,
}))

import { Catalogue } from "@/portals/admin/screens/billing/Catalogue"
import { ReasonedFormDialog } from "@/portals/admin/screens/billing/ReasonedFormDialog"
import { PACK_FIELDS, TIER_FIELDS, estimatorErrors, packValues, tierValues } from "@/lib/adminBillingModel"

beforeEach(() => {
  s.catalogue = okQuery(fx.adminCatalogue)
})

describe("Catalogue", () => {
  it("shows tiers with hidden allowance units, packs, rates, estimators and free allowances", () => {
    const html = renderStatic(h(Catalogue))
    expect(html).toContain("student_plus_m")
    expect(html).toContain("4,000")
    expect(html).toContain("pack_500")
    expect(html).toContain("Units per USD")
    expect(html).toContain("none")
    expect(html).toContain("Student free allowance")
  })

  it("has no eyebrow above its headings and names each section", () => {
    const html = renderStatic(h(Catalogue))
    // The kit's table headers and badges use the eyebrow type; no label may sit above a heading.
    expect(html).not.toMatch(/text-eyebrow[^"]*"[^>]*>[^<]*<\/(?:div|p|span)><h[12]/)
    for (const heading of ["Plan tiers", "Credit packs", "Free allowances", "Usage rates", "Estimators"]) expect(html).toContain(`>${heading}</h2>`)
  })

  it("shows a teacher tier's seats and a student tier as seatless", () => {
    const teacher = { ...fx.adminCatalogue.tiers[0], id: "t-t", code: "teacher_pro_m", audience: "teacher" as const, includedSeats: 20, seatAllowanceUnits: 300, extraSeatPriceMinor: 3000 }
    s.catalogue = okQuery({ ...fx.adminCatalogue, tiers: [fx.adminCatalogue.tiers[0], teacher] })
    const html = renderStatic(h(Catalogue))
    expect(html).toContain("No seats")
    expect(html).toContain("20 seats")
    expect(html).toContain("units each")
    expect(html).toContain("Extra")
  })

  it("marks versions in force, scheduled and replaced", () => {
    s.catalogue = okQuery({
      ...fx.adminCatalogue,
      rates: [
        { id: "r1", version: 1, action: "mark_paper", unitsPerUsd: 1000, effectiveFrom: "2020-01-01T00:00:00Z" },
        { id: "r2", version: 2, action: "mark_paper", unitsPerUsd: 1100, effectiveFrom: "2021-01-01T00:00:00Z" },
        { id: "r3", version: 3, action: "mark_paper", unitsPerUsd: 1200, effectiveFrom: "2099-01-01T00:00:00Z" },
      ],
    })
    const html = renderStatic(h(Catalogue))
    expect(html).toContain("In force")
    expect(html).toContain("Scheduled")
    expect(html).toContain("Replaced")
  })

  it("says so when a list is empty", () => {
    s.catalogue = okQuery({ ...fx.adminCatalogue, tiers: [], packs: [], rates: [], estimators: [] })
    const html = renderStatic(h(Catalogue))
    expect(html).toContain("No plan tiers yet")
    expect(html).toContain("No credit packs yet")
    expect(html).toContain("No usage rates yet")
    expect(html).toContain("No estimators yet")
    expect(html).toContain("New tier")
  })

  it("shows a free tier without a sync action or a drift alarm", () => {
    s.catalogue = okQuery({ ...fx.adminCatalogue, tiers: [{ ...fx.adminCatalogue.tiers[0], priceMinor: 0, paymobPlanId: null, drift: "Not synced to Paymob yet" }] })
    const html = renderStatic(h(Catalogue))
    expect(html).toContain("Free tier, no Paymob plan")
    expect(html).not.toContain("Sync to Paymob")
    expect(html).not.toContain('role="note"')
  })

  it("loads with a skeleton, fails with a retry, and refuses a non-admin plainly", () => {
    s.catalogue = pendingQuery()
    expect(renderStatic(h(Catalogue))).toContain('aria-label="Loading"')
    s.catalogue = errorQuery(new ApiError(500, "boom"))
    const failed = renderStatic(h(Catalogue))
    expect(failed).toContain("Couldn")
    expect(failed).toContain("Try again")
    expect(failed).not.toContain("boom")
    s.catalogue = errorQuery(new ApiError(403, "Forbidden"))
    const forbidden = renderStatic(h(Catalogue))
    expect(forbidden).toContain("open the billing catalogue")
    expect(forbidden).not.toContain("Try again")
  })

  it("warns about Paymob drift and offers a sync", () => {
    s.catalogue = okQuery({ ...fx.adminCatalogue, tiers: [{ ...fx.adminCatalogue.tiers[0], drift: "Paymob amount is 240.00" }] })
    const html = renderStatic(h(Catalogue))
    expect(html).toContain("Paymob amount is 240.00")
    expect(html).toContain("Sync to Paymob")
  })
})

describe("ReasonedFormDialog", () => {
  it("always asks for a reason and names the audit log", () => {
    const html = renderStatic(
      h(ReasonedFormDialog, {
        open: true,
        onClose: () => undefined,
        title: "Edit pack",
        fields: PACK_FIELDS,
        initial: packValues(fx.adminCatalogue.packs[0]),
        submitLabel: "Save pack",
        // Test files are typechecked; a fake passed straight in as a prop is cast.
        mutation: fakeMutation() as never,
        toBody: () => ({}) as never,
      }),
    )
    expect(html).toContain("Reason")
    expect(html).toContain("saved in the audit log")
    expect(html).toContain("Save pack")
  })
})

function dialog(over: Record<string, unknown> = {}) {
  return renderStatic(
    h(ReasonedFormDialog, {
      open: true,
      onClose: () => undefined,
      title: "Edit tier",
      fields: TIER_FIELDS,
      initial: tierValues(fx.adminCatalogue.tiers[0]),
      submitLabel: "Save tier",
      mutation: fakeMutation() as never,
      toBody: () => ({}) as never,
      ...over,
    }),
  )
}

describe("ReasonedFormDialog states", () => {
  it("hides the seat fields on a student tier and shows them on a teacher tier", () => {
    expect(dialog()).not.toContain("Included seats")
    const teacher = { ...tierValues(fx.adminCatalogue.tiers[0]), audience: "teacher" }
    const html = dialog({ initial: teacher })
    expect(html).toContain("Included seats")
    expect(html).toContain("Seat allowance per month")
    expect(html).toContain("Extra seat price")
  })

  it("disables the submit button while the request is pending, and blocks closing", () => {
    const html = dialog({ mutation: fakeMutation({ isPending: true }) as never })
    const submit = html.match(/<button[^>]*form="[^"]*"[^>]*>/)?.[0] ?? ""
    expect(submit).toContain("disabled")
    expect(submit).toContain('aria-busy="true"')
    expect(html.match(/<button[^>]*>Cancel<\/button>/)?.[0]).toContain("disabled")
  })

  it("shows the server's refusal in an alert beside the buttons", () => {
    const error = new ApiError(409, "Conflict", { code: "code_taken", message: "A tier with code student_plus_m exists." })
    const html = dialog({ mutation: fakeMutation({ isError: true, error }) as never })
    expect(html).toContain('role="alert"')
    expect(html).toContain("A tier with code student_plus_m exists.")
  })

  it("states an estimator's cross-field rule", () => {
    expect(estimatorErrors({ inputKind: "none", baseLow: "1", baseHigh: "2", perInputLow: "1", perInputHigh: "1" })).toHaveLength(1)
  })

  it("explains the sync before it is confirmed", () => {
    const html = dialog({ fields: [], initial: {}, title: "Sync student_plus_m to Paymob", submitLabel: "Sync to Paymob", note: "Creates a new Paymob plan" })
    expect(html).toContain("Creates a new Paymob plan")
    expect(html).toContain("saved in the audit log")
  })
})
