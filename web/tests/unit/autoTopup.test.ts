import { readFileSync } from "node:fs"
import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { disabledNotice, fieldErrors, formFromSettings, reconcileForm, toUpdate, validateAutoTopup } from "@/lib/autoTopupForm"
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

describe("monthly cap", () => {
  const base = { ...formFromSettings(fx.autoTopup), creditPackId: "p1", thresholdUnits: "100", savedCardId: "card1" }

  it("asks for a limit when enabling with an empty one, and checks the pack price only for a typed value", () => {
    expect(validateAutoTopup({ ...base, enabled: true, monthlyCapMajor: "" }, packs)).toEqual(["Set a monthly limit."])
    expect(fieldErrors({ ...base, enabled: true, monthlyCapMajor: "" }, packs).monthlyCapMajor).toBe("Set a monthly limit.")
    expect(validateAutoTopup({ ...base, enabled: true, monthlyCapMajor: "10" }, packs)[0]).toMatch(/must cover at least one pack/)
    expect(validateAutoTopup({ ...base, enabled: true, monthlyCapMajor: "150" }, packs)).toEqual([])
  })

  it("keeps the saved cap when saving switched off with the field empty, else sends 0", () => {
    expect(toUpdate({ ...base, enabled: false, monthlyCapMajor: "" }, null, 60000).monthlyCapMinor).toBe(60000)
    expect(toUpdate({ ...base, enabled: false, monthlyCapMajor: "" }, null, null).monthlyCapMinor).toBe(0)
    expect(toUpdate({ ...base, enabled: false, monthlyCapMajor: "200" }, null, 60000).monthlyCapMinor).toBe(20000)
  })

  it("shows a saved cap of 0 as an empty field", () => {
    expect(formFromSettings({ ...fx.autoTopup, monthlyCapMinor: 0 }).monthlyCapMajor).toBe("")
  })
})

describe("reconcileForm", () => {
  const server = formFromSettings({ ...fx.autoTopup, enabled: true, thresholdUnits: 100, creditPackId: "p1", savedCardId: "card1", monthlyCapMinor: 60000 })

  it("adopts a changed server copy while the form is unedited", () => {
    const next = formFromSettings({ ...fx.autoTopup, enabled: true, thresholdUnits: 100, creditPackId: "p1", savedCardId: "card1", monthlyCapMinor: 70000 })
    expect(reconcileForm(server, server, next)).toEqual({ form: next, baseline: next })
  })

  it("keeps in-progress edits when a background refetch changes the server copy", () => {
    const edited = { ...server, thresholdUnits: "250" }
    const next = formFromSettings({ ...fx.autoTopup, enabled: true, thresholdUnits: 100, creditPackId: "p1", savedCardId: "card1", monthlyCapMinor: 70000 })
    expect(reconcileForm(edited, server, next).form).toBe(edited)
  })

  it("does nothing when the server copy is unchanged", () => {
    const edited = { ...server, thresholdUnits: "250" }
    expect(reconcileForm(edited, server, { ...server })).toEqual({ form: edited, baseline: server })
  })
})

describe("disabledNotice", () => {
  it("names a failed charge, gives any other reason a generic notice, and says nothing otherwise", () => {
    expect(disabledNotice("charge_failed")).toBe("charge_failed")
    expect(disabledNotice("card_expired")).toBe("other")
    expect(disabledNotice(null)).toBeNull()
  })
})

describe("AutoTopupCard", () => {
  it("does not remount the form on a refetch, so the save result can show", () => {
    const html = readFileSync("src/portals/billing/AutoTopupCard.tsx", "utf8")
    expect(html).not.toContain("JSON.stringify(settings.data)")
  })

  it("links a failed-charge notice to buying a pack with a new card", () => {
    s.settings = okQuery({ ...fx.autoTopup, disabledReason: "charge_failed" })
    expect(card()).toContain('href="/student/billing/plans#packs"')
  })

  it("gives an unknown switch-off reason a generic notice", () => {
    s.settings = okQuery({ ...fx.autoTopup, disabledReason: "card_expired" })
    expect(card()).toContain("Auto top-up was switched off.")
  })

  it("asks for a new pack when the saved one left the catalogue", () => {
    s.settings = okQuery({ ...fx.autoTopup, creditPackId: "gone", thresholdUnits: 100 })
    expect(card()).toContain("no longer available")
  })

  it("makes no payer queries path for a non-payer", () => {
    s.summary = okQuery({ ...fx.summary, canManage: false, managedByName: "Mona" })
    s.settings = null
    expect(card()).toBe("")
  })

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
