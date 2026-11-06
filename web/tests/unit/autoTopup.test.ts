import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { formFromSettings, toUpdate, validateAutoTopup } from "@/lib/autoTopupForm"
import { fx } from "./support/billingFixtures"
import { fakeMutation, okQuery, renderStatic } from "./support/billingRender"

const s = vi.hoisted(() => ({
  settings: null as unknown,
  cards: null as unknown,
  catalogue: null as unknown,
  summary: null as unknown,
  save: null as unknown,
}))
vi.mock("@/lib/hooks/useBillingApi", () => ({
  useAutoTopup: () => s.settings,
  useSavedCards: () => s.cards,
  useCatalogue: () => s.catalogue,
  useBillingSummary: () => s.summary,
  useSaveAutoTopup: () => s.save,
}))

import { AutoTopupCard } from "@/portals/billing/AutoTopupCard"

const packs = fx.studentCatalogue.packs
const card = () => renderStatic(h(AutoTopupCard, { beneficiaryId: null, audience: "student", packsHref: "/student/billing/plans#packs" }))

beforeEach(() => {
  s.settings = okQuery(fx.autoTopup)
  s.cards = okQuery({ cards: [fx.summary.savedCard] })
  s.catalogue = okQuery(fx.studentCatalogue)
  s.summary = okQuery(fx.summary)
  s.save = fakeMutation()
})

describe("auto top-up form", () => {
  it("round-trips settings, converting the cap between EGP and piasters", () => {
    const form = formFromSettings({ ...fx.autoTopup, monthlyCapMinor: 50000 })
    expect(form.monthlyCapMajor).toBe("500")
    expect(toUpdate({ ...form, monthlyCapMajor: "250.5" }, "c1")).toMatchObject({ beneficiaryId: "c1", monthlyCapMinor: 25050 })
  })

  it("always needs a pack and a threshold, and a card and a covering cap when enabled", () => {
    const off = formFromSettings(fx.autoTopup)
    expect(off).toMatchObject({ thresholdUnits: "", monthlyCapMajor: "", creditPackId: null })
    expect(validateAutoTopup(off, packs)).toEqual(["Choose a pack to buy.", "Set a threshold of at least 1 credit."])
    expect(validateAutoTopup({ ...off, creditPackId: "p1", thresholdUnits: "100" }, packs)).toEqual([])
    const on = { ...off, enabled: true, creditPackId: null, savedCardId: null, thresholdUnits: "0", monthlyCapMajor: "100" }
    expect(validateAutoTopup(on, packs)).toEqual([
      "Choose a pack to buy.",
      "Set a threshold of at least 1 credit.",
      "Choose a saved card.",
    ])
    const lowCap = { ...on, creditPackId: "p1", savedCardId: "card1", thresholdUnits: "50", monthlyCapMajor: "100" }
    expect(validateAutoTopup(lowCap, packs)[0]).toMatch(/^The monthly limit must cover at least one pack \(EGP\s150\.00\)\.$/)
  })
})

describe("AutoTopupCard", () => {
  it("renders the switch, threshold, pack, card and cap fields with spend so far", () => {
    const html = card()
    expect(html).toContain('role="switch"')
    expect(html).toContain("When credits fall below")
    expect(html).toContain("500 credits")
    expect(html).toContain("2346")
    expect(html).toContain("Spent this month")
  })

  it("explains a missing card and disables the switch", () => {
    s.cards = okQuery({ cards: [] })
    const html = card()
    expect(html).toContain("Auto top-up needs a saved card.")
    // Attribute order is React's, so match the switch's tag with lookaheads.
    expect(html).toMatch(/<button(?=[^>]*role="switch")(?=[^>]*disabled)[^>]*>/)
  })

  it("reports a failed charge that switched top-up off", () => {
    s.settings = okQuery({ ...fx.autoTopup, disabledReason: "charge_failed" })
    expect(card()).toMatch(/role="status"[^>]*>.*last charge failed/)
  })

  it("is hidden from a non-payer", () => {
    s.summary = okQuery({ ...fx.summary, canManage: false, managedByName: "Mona" })
    expect(card()).toBe("")
  })

  it("shows save success and failure", () => {
    s.save = fakeMutation({ isSuccess: true })
    expect(card()).toContain("Saved.")
    s.save = fakeMutation({ isError: true, error: new ApiError(409, "x", { code: "no_saved_card" }) })
    expect(card()).toContain('role="alert"')
  })
})
