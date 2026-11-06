import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { toPublicCatalogue } from "@/lib/billingAdapters"
import { chooseHref, planPath, planPreselect, publicCatalogueFailure, signupHref } from "@/lib/pricingModel"
import type { WirePublicCatalogue } from "@/lib/billingTypes"
import { errorQuery, okQuery, pendingQuery, renderStatic } from "./support/billingRender"

const wire: WirePublicCatalogue = {
  audience: "teacher",
  planTiers: [
    { code: "teacher_max_m", name: "Teacher Max", audience: "teacher", interval: "monthly", priceMinor: 150000, currency: "EGP", features: {}, includedSeats: 40, extraSeatPriceMinor: 3000 },
    { code: "teacher_pro_m", name: "Teacher Pro", audience: "teacher", interval: "monthly", priceMinor: 90000, currency: "EGP", features: { "Class analytics": true }, includedSeats: 20, extraSeatPriceMinor: 3000 },
    { code: "teacher_pro_y", name: "Teacher Pro", audience: "teacher", interval: "yearly", priceMinor: 900000, currency: "EGP", features: {}, includedSeats: 20, extraSeatPriceMinor: 30000 },
    { code: "legacy", name: "Legacy", audience: "teacher", interval: null, priceMinor: 0, currency: "EGP", features: {}, includedSeats: null, extraSeatPriceMinor: null },
  ],
  creditPacks: [{ code: "pack_500", name: "500 credits", units: 500, priceMinor: 15000, currency: "EGP" }],
}

const s = vi.hoisted(() => ({ catalogue: null as unknown }))
vi.mock("@/lib/hooks/useBillingApi", () => ({ usePublicCatalogue: () => s.catalogue }))
vi.mock("@/portals/marketing", () => ({ MarketingFrame: (p: { children: unknown }) => h("main", null, p.children as never) }))

import { Pricing } from "@/portals/marketing/Pricing"

beforeEach(() => {
  s.catalogue = okQuery(toPublicCatalogue(wire))
})

describe("toPublicCatalogue", () => {
  it("maps intervals and features and drops interval-less tiers", () => {
    const c = toPublicCatalogue(wire)
    expect(c.tiers.map((t) => t.code)).toEqual(["teacher_max_m", "teacher_pro_m", "teacher_pro_y"])
    expect(c.tiers[1]).toEqual({
      code: "teacher_pro_m", name: "Teacher Pro", audience: "teacher", interval: "month", priceMinor: 90000, currency: "EGP",
      features: ["Class analytics"], includedSeats: 20, extraSeatPriceMinor: 3000,
    })
    expect(c.packs).toEqual(wire.creditPacks)
  })
})

describe("pricing model", () => {
  it("sends Choose plan through sign-in to the plans page with the tier code", () => {
    const tier = toPublicCatalogue(wire).tiers[1]
    expect(planPath(tier)).toBe("/teacher/billing/plans?plan=teacher_pro_m&interval=month")
    expect(chooseHref(tier)).toBe(`/login?next=${encodeURIComponent(planPath(tier))}`)
    expect(signupHref("teacher", planPath(tier))).toBe(`/signup/teacher?next=${encodeURIComponent(planPath(tier))}`)
    expect(signupHref("student")).toBe(`/signup/student?next=${encodeURIComponent("/student/billing/plans")}`)
  })

  it("reads a preselection only when both parts are valid", () => {
    expect(planPreselect(new URLSearchParams("plan=teacher_pro_m&interval=year"))).toEqual({ code: "teacher_pro_m", interval: "year" })
    expect(planPreselect(new URLSearchParams("plan=teacher_pro_m"))).toEqual({ code: "teacher_pro_m", interval: null })
    expect(planPreselect(new URLSearchParams("interval=week"))).toEqual({ code: null, interval: null })
  })

  it("words a rate limit with its countdown and other failures plainly", () => {
    expect(publicCatalogueFailure(new ApiError(429, "x", undefined, 30))).toBe("Too many requests. Try again in 30 seconds.")
    expect(publicCatalogueFailure(new ApiError(429, "x"))).toBe("Too many requests. Try again in a minute.")
    expect(publicCatalogueFailure(new ApiError(0, "x"))).toBe("Couldn't load prices. Check your connection and try again.")
  })

  it("says one second in the singular and treats a zero or junk Retry-After as absent", () => {
    expect(publicCatalogueFailure(new ApiError(429, "x", undefined, 1))).toBe("Too many requests. Try again in 1 second.")
    expect(publicCatalogueFailure(new ApiError(429, "x", undefined, 0))).toBe("Too many requests. Try again in a minute.")
    expect(publicCatalogueFailure(new ApiError(429, "x", undefined, Number.NaN))).toBe("Too many requests. Try again in a minute.")
  })
})

describe("Pricing", () => {
  const page = (path = "/pricing") => renderStatic(h(Pricing), path)

  it("shows monthly tiers cheapest first with seats, and packs", () => {
    const html = page("/pricing?audience=teacher")
    expect(html.indexOf("Teacher Pro")).toBeLessThan(html.indexOf("Teacher Max"))
    expect(html).toContain("20 student seats included")
    expect(html).toMatch(/Extra seats EGP\s30\.00 each per month/)
    expect(html).not.toMatch(/EGP\s9,000\.00/)
    expect(html).toContain('id="packs"')
    expect(html).toContain("500 credits")
    expect(html).toContain(`href="${chooseHref(toPublicCatalogue(wire).tiers[1]).replace(/&/g, "&amp;")}"`)
    expect(html).toContain(`href="${signupHref("teacher")}"`)
    expect(html).toContain(`href="${signupHref("teacher", planPath(toPublicCatalogue(wire).tiers[1]))}"`)
  })

  it("has one h1 and the two toggles", () => {
    const html = page()
    expect(html.match(/<h1/g)?.length).toBe(1)
    expect(html).toContain('aria-label="Who is this for"')
    expect(html).toContain('aria-label="Billing interval"')
  })

  it("renders loading, rate-limit and empty states", () => {
    s.catalogue = pendingQuery()
    expect(page()).toContain('aria-label="Loading"')
    s.catalogue = errorQuery(new ApiError(429, "x", undefined, 12))
    expect(page()).toContain("Try again in 12 seconds.")
    s.catalogue = okQuery({ audience: "student", tiers: [], packs: [] })
    expect(page()).toContain("No plans are on sale right now.")
  })

  it("renders a plain failure with a retry, and no countdown, for a non-429 error", () => {
    s.catalogue = errorQuery(new ApiError(500, "x"))
    const html = page()
    expect(html).toContain("Prices unavailable")
    expect(html).toContain("Couldn&#x27;t load prices. Check your connection and try again.")
    expect(html).toContain("Try again")
    expect(html).not.toContain('role="timer"')
    // No eyebrow above the heading: the state view's mono kicker is switched off.
    expect(html).not.toMatch(/>Error</)
  })

  it("says offline, and keeps the empty state free of a kicker too", () => {
    s.catalogue = errorQuery(new ApiError(0, "x"))
    const offline = page()
    expect(offline).toContain("You&#x27;re offline")
    expect(offline).not.toMatch(/>Offline</)
    s.catalogue = okQuery({ audience: "student", tiers: [], packs: [] })
    expect(page()).not.toMatch(/>Empty</)
  })
})
