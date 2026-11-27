import { readFileSync } from "node:fs"
import { join } from "node:path"
import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { toPublicCatalogue } from "@/lib/billingAdapters"
import {
  chooseHref,
  chooseTarget,
  packsHref,
  packsTarget,
  planPath,
  planPreselect,
  publicCatalogueBody,
  publicCatalogueFailure,
  signupHref,
  tiersForInterval,
} from "@/lib/pricingModel"
import type { WirePublicCatalogue } from "@/lib/billingTypes"
import { errorQuery, okQuery, pendingQuery, renderStatic } from "./support/billingRender"

const wire: WirePublicCatalogue = {
  audience: "teacher",
  creditValidityMonths: 12,
  planTiers: [
    { code: "teacher_max_m", name: "Teacher Max", audience: "teacher", interval: "monthly", priceMinor: 150000, currency: "EGP", features: {}, includedSeats: 40, extraSeatPriceMinor: 3000 },
    { code: "teacher_pro_m", name: "Teacher Pro", audience: "teacher", interval: "monthly", priceMinor: 90000, currency: "EGP", features: { "Class analytics": true }, includedSeats: 20, extraSeatPriceMinor: 3000 },
    { code: "teacher_pro_y", name: "Teacher Pro", audience: "teacher", interval: "yearly", priceMinor: 900000, currency: "EGP", features: {}, includedSeats: 20, extraSeatPriceMinor: 30000 },
    { code: "legacy", name: "Legacy", audience: "teacher", interval: null, priceMinor: 0, currency: "EGP", features: {}, includedSeats: null, extraSeatPriceMinor: null },
  ],
  creditPacks: [{ code: "pack_500", name: "500 credits", units: 500, priceMinor: 15000, currency: "EGP" }],
}

const s = vi.hoisted(() => ({ catalogue: null as unknown, session: null as unknown }))
vi.mock("@/lib/auth/AuthContext", () => ({ useAuth: () => ({ session: s.session }) }))
vi.mock("@/lib/hooks/useBillingApi", () => ({ usePublicCatalogue: () => s.catalogue }))
vi.mock("@/portals/marketing", () => ({ MarketingFrame: (p: { children: unknown }) => h("main", null, p.children as never) }))

import { Pricing } from "@/portals/marketing/Pricing"

beforeEach(() => {
  s.catalogue = okQuery(toPublicCatalogue(wire))
  s.session = null
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

  it("drops tiers with an unknown audience or interval and nulls seat fields off teacher tiers", () => {
    const c = toPublicCatalogue({
      audience: "student",
      creditValidityMonths: 12,
      planTiers: [
        { code: "s", name: "S", audience: "student", interval: "monthly", priceMinor: 1, currency: "EGP", features: {}, includedSeats: 9, extraSeatPriceMinor: 9 },
        { code: "school", name: "School", audience: "school", interval: "monthly", priceMinor: 1, currency: "EGP", features: {}, includedSeats: 5, extraSeatPriceMinor: 5 },
        { code: "odd", name: "Odd", audience: "student", interval: "weekly" as never, priceMinor: 1, currency: "EGP", features: {}, includedSeats: null, extraSeatPriceMinor: null },
      ],
      creditPacks: [],
    })
    expect(c.tiers.map((t) => t.code)).toEqual(["s"])
    expect(c.tiers[0].includedSeats).toBeNull()
    expect(c.tiers[0].extraSeatPriceMinor).toBeNull()
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

  it("sends a signed-in visitor straight to the plans page, and packs to its packs anchor", () => {
    const tier = toPublicCatalogue(wire).tiers[1]
    expect(chooseTarget(tier, true)).toBe(planPath(tier))
    expect(chooseTarget(tier, false)).toBe(chooseHref(tier))
    expect(packsTarget("teacher", true)).toBe("/teacher/billing/plans#packs")
    expect(packsTarget("teacher", false)).toBe(packsHref("teacher"))
  })

  it("encodes the packs anchor into next", () => {
    expect(packsHref("student")).toBe("/login?next=%2Fstudent%2Fbilling%2Fplans%23packs")
  })

  it("encodes an awkward tier code once, and drops next when the path is not safe", () => {
    const base = toPublicCatalogue(wire).tiers[1]
    const odd = { ...base, code: "a b&c?d" }
    expect(planPath(odd)).toBe("/teacher/billing/plans?plan=a%20b%26c%3Fd&interval=month")
    expect(chooseHref(odd)).toBe(`/login?next=${encodeURIComponent(planPath(odd))}`)
    // safeNextPath caps a path at 500 characters; past that the link is a plain sign-in.
    const huge = { ...base, code: "x".repeat(600) }
    expect(chooseHref(huge)).toBe("/login")
    expect(signupHref("teacher", planPath(huge))).toBe("/signup/teacher")
  })

  it("orders a tied price by name, then code", () => {
    const t = (code: string, name: string, priceMinor: number) => ({ ...toPublicCatalogue(wire).tiers[1], code, name, priceMinor })
    const ordered = tiersForInterval([t("b2", "Beta", 100), t("c1", "Alpha", 100), t("b1", "Beta", 100), t("a", "Zed", 50), { ...t("y", "Year", 1), interval: "year" }], "month")
    expect(ordered.map((x) => x.code)).toEqual(["a", "c1", "b1", "b2"])
  })

  it("words the body under the heading without repeating it", () => {
    expect(publicCatalogueBody(new ApiError(0, "x"))).toBe("Check your connection and try again.")
    expect(publicCatalogueBody(new ApiError(429, "x"))).toBe("Too many requests. Try again in a minute.")
    expect(publicCatalogueBody(new ApiError(500, "x"))).not.toContain("Couldn")
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
    expect(html).toMatch(/Extra seats EGP\s30\.00 each, billed per month/)
    expect(html).not.toMatch(/EGP\s9,000\.00/)
    expect(html).toContain('id="packs"')
    expect(html).toContain("500 credits")
    expect(html).toContain(`href="${chooseHref(toPublicCatalogue(wire).tiers[1]).replace(/&/g, "&amp;")}"`)
    expect(html).toContain(`href="${signupHref("teacher")}"`)
    expect(html).toContain(`href="${signupHref("teacher", planPath(toPublicCatalogue(wire).tiers[1]))}"`)
    // The pack's sign-in link carries the packs anchor, encoded.
    expect(html).toContain('href="/login?next=%2Fteacher%2Fbilling%2Fplans%23packs"')
  })

  it("signed in: Choose plan and packs go straight to the plans page and the sign-up links are gone", () => {
    s.session = { role: "teacher" }
    const html = page("/pricing?audience=teacher")
    const pro = toPublicCatalogue(wire).tiers[1]
    expect(html).toContain(`href="${planPath(pro).replace(/&/g, "&amp;")}"`)
    expect(html).toContain('href="/teacher/billing/plans#packs"')
    expect(html).not.toContain("/login")
    expect(html).not.toContain("/signup/")
    expect(html).not.toContain("New to Lemely?")
    expect(html).toContain("Choose pack")
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

  it("renders a failure with the shared copy, one heading, a retry and no kicker", () => {
    s.catalogue = errorQuery(new ApiError(500, "x"))
    const html = page()
    expect(html.match(/Couldn&#x27;t load prices/g)?.length).toBe(1)
    expect(html).toContain("Try again")
    expect(html).not.toContain("Check your connection")
    expect(html).not.toContain('role="timer"')
    expect(html).not.toMatch(/>Error</)
  })

  it("says what to check when the connection dropped, with no kicker", () => {
    s.catalogue = errorQuery(new ApiError(0, "x"))
    const html = page()
    expect(html).toContain("Check your connection and try again.")
    expect(html.match(/Couldn&#x27;t load prices/g)?.length).toBe(1)
    expect(html).not.toMatch(/>Offline</)
  })

  it("a 429 without a wait goes through the shared view with the one-minute line", () => {
    s.catalogue = errorQuery(new ApiError(429, "x"))
    const html = page()
    expect(html).toContain("Too many requests. Try again in a minute.")
    expect(html).not.toContain('role="timer"')
  })

  it("keeps the kicker off a 204 that returned no data, too", () => {
    s.catalogue = okQuery(undefined)
    const html = page()
    expect(html).toContain("Couldn&#x27;t load prices")
    expect(html).not.toMatch(/>Error</)
  })

  it("keeps the empty state free of a kicker", () => {
    s.catalogue = okQuery({ audience: "student", tiers: [], packs: [] })
    expect(page()).not.toMatch(/>Empty</)
  })
})

describe("marketing chrome links to /pricing", () => {
  const src = (f: string) => readFileSync(join(import.meta.dirname, "..", "..", "src", "portals", "marketing", f), "utf8")

  it("has Pricing in the header's desktop and mobile navs and the footer's Product column", () => {
    expect(src("MarketingHeader.tsx").match(/to="\/pricing"/g)?.length).toBe(2)
    expect(src("MarketingFooter.tsx")).toContain('<Link to="/pricing">Pricing</Link>')
  })
})
