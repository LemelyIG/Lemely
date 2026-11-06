import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import {
  ESTIMATOR_FIELDS,
  PACK_FIELDS,
  RATE_FIELDS,
  TIER_FIELDS,
  TIER_UPDATE_FIELDS,
  adminBillingFailureMessage,
  adminRetry,
  estimatorBody,
  estimatorErrors,
  fieldErrors,
  freeBody,
  isoDay,
  majorFromMinor,
  minorFromMajor,
  packBody,
  packUpdateBody,
  rateBody,
  reasonError,
  tierBody,
  tierUpdateBody,
  tierValues,
  tomorrowUtc,
  validateFields,
  versionRows,
  visibleFields,
  paymobState,
} from "@/lib/adminBillingModel"
import { fx } from "./support/billingFixtures"

describe("admin billing model", () => {
  it("requires a real reason", () => {
    expect(reasonError("")).toBe("Give a reason of at least 5 characters. It is saved in the audit log.")
    expect(reasonError("  ok  ")).not.toBeNull()
    expect(reasonError("refund for duplicate charge")).toBeNull()
  })

  it("converts EGP to piasters and back, and dates to ISO datetimes", () => {
    expect(minorFromMajor("250")).toBe(25000)
    expect(minorFromMajor("250.5")).toBe(25050)
    expect(minorFromMajor("-1")).toBeNull()
    expect(minorFromMajor("abc")).toBeNull()
    expect(majorFromMinor(25050)).toBe("250.50")
    expect(isoDay("2026-12-01")).toBe("2026-12-01T00:00:00Z")
  })

  it("builds plan 07's create body and its full update body from the form", () => {
    const tier = fx.adminCatalogue.tiers[0]
    const v = tierValues(tier)
    expect(tierBody(v, "price check")).toEqual({
      code: tier.code,
      name: tier.name,
      audience: "student",
      interval: "monthly",
      priceMinor: tier.priceMinor,
      currency: "EGP",
      allowanceUnits: tier.allowanceUnits,
      includedSeats: 0,
      seatAllowanceUnits: 0,
      extraSeatPriceMinor: 0,
      features: { "Mark past papers": true, "Study plans": true },
      isActive: true,
      reason: "price check",
    })
    expect(tierUpdateBody(v, "price check")).toEqual({
      name: tier.name,
      priceMinor: tier.priceMinor,
      allowanceUnits: tier.allowanceUnits,
      includedSeats: 0,
      seatAllowanceUnits: 0,
      extraSeatPriceMinor: 0,
      features: { "Mark past papers": true, "Study plans": true },
      isActive: true,
      reason: "price check",
    })
  })

  it("validates required text and non-negative numbers", () => {
    const values = { ...tierValues(null), code: "", priceMajor: "-3" }
    const errors = validateFields(TIER_FIELDS, values)
    expect(errors).toContain("Code is required.")
    expect(errors).toContain("Price (EGP) must be zero or more.")
    expect(validateFields(PACK_FIELDS, { code: "pack_p", name: "P", units: "500", priceMajor: "150", isActive: true })).toEqual([])
  })

  it("builds pack, rate, estimator and free-allowance bodies", () => {
    const pack = { code: "pack_p", name: "P", units: "500", priceMajor: "150", isActive: true }
    expect(packBody(pack, "new pack")).toEqual({ code: "pack_p", name: "P", units: 500, priceMinor: 15000, currency: "EGP", isActive: true, reason: "new pack" })
    expect(packUpdateBody(pack, "edit pack")).toEqual({ name: "P", units: 500, priceMinor: 15000, isActive: true, reason: "edit pack" })
    expect(rateBody({ action: "regrade", unitsPerUsd: "1200", effectiveFrom: "2026-12-01" }, "rate")).toEqual({
      action: "regrade", unitsPerUsd: 1200, effectiveFrom: "2026-12-01T00:00:00Z", reason: "rate",
    })
    expect(rateBody({ action: "regrade", unitsPerUsd: "1200", effectiveFrom: "" }, "rate").effectiveFrom).toBeNull()
    expect(
      estimatorBody({ action: "mark_paper", inputKind: "none", baseLow: "2", baseHigh: "4", perInputLow: "0", perInputHigh: "0", effectiveFrom: "" }, "tune"),
    ).toMatchObject({ inputKind: "none", baseLow: 2, baseHigh: 4, effectiveFrom: null })
    expect(freeBody({ studentSignupUnits: "300", teacherSignupUnits: "1000" }, "free")).toEqual([
      { audience: "student", units: 300, reason: "free" },
      { audience: "teacher", units: 1000, reason: "free" },
    ])
  })
})

const NOW = new Date("2026-11-06T10:00:00Z")

describe("admin billing model: what the server would refuse is refused first", () => {
  it("caps the reason at the server's 2000 characters", () => {
    expect(reasonError("x".repeat(2000))).toBeNull()
    expect(reasonError("x".repeat(2001))).toBe("Keep the reason under 2,000 characters.")
    expect(reasonError("   ab   ")).not.toBeNull()
  })

  it("names the field and rule for each invalid value", () => {
    const e = fieldErrors(PACK_FIELDS, { code: "Pack One", name: "", units: "0", priceMajor: "0", isActive: true })
    expect(e.code).toBe("Code must be 2 to 64 lowercase letters, digits or underscores.")
    expect(e.name).toBe("Name is required.")
    expect(e.units).toBe("Credits must be a whole number above zero.")
    expect(e.priceMajor).toBe("Price (EGP) must be more than zero.")
    expect(fieldErrors(PACK_FIELDS, { code: "x".repeat(65), name: "ok", units: "1", priceMajor: "1", isActive: true }).code).toBe("Code must be at most 64 characters.")
    expect(fieldErrors(PACK_FIELDS, { code: "pack_ok", name: "ok", units: "1.5", priceMajor: "1.234", isActive: true })).toEqual({
      units: "Credits must be a whole number above zero.",
      priceMajor: "Price (EGP) must be an amount like 250 or 250.50.",
    })
    expect(fieldErrors(TIER_UPDATE_FIELDS, { ...tierValues(null), name: "Plus", priceMajor: "0", allowanceUnits: "1" })).toEqual({})
  })

  it("keeps seat fields to teacher tiers and sends zero seats for a student tier", () => {
    const student = { ...tierValues(null), audience: "student", includedSeats: "20", seatAllowanceUnits: "9", extraSeatPriceMajor: "5" }
    expect(visibleFields(TIER_FIELDS, student).map((f) => f.name)).not.toContain("includedSeats")
    expect(fieldErrors(TIER_FIELDS, { ...student, includedSeats: "abc" })).not.toHaveProperty("includedSeats")
    expect(tierBody(student, "r")).toMatchObject({ includedSeats: 0, seatAllowanceUnits: 0, extraSeatPriceMinor: 0 })
    const teacher = { ...student, audience: "teacher" }
    expect(visibleFields(TIER_FIELDS, teacher).map((f) => f.name)).toEqual(expect.arrayContaining(["includedSeats", "seatAllowanceUnits", "extraSeatPriceMajor"]))
    expect(fieldErrors(TIER_FIELDS, { ...teacher, includedSeats: "-1" }).includedSeats).toMatch(/whole number/)
    expect(tierBody(teacher, "r")).toMatchObject({ audience: "teacher", includedSeats: 20, seatAllowanceUnits: 9, extraSeatPriceMinor: 500 })
  })

  it("refuses a dated version that starts today or earlier, and lets an empty day mean now", () => {
    expect(tomorrowUtc(NOW)).toBe("2026-11-07")
    const base = { action: "regrade", unitsPerUsd: "1200" }
    expect(fieldErrors(RATE_FIELDS, { ...base, effectiveFrom: "" }, NOW)).toEqual({})
    expect(fieldErrors(RATE_FIELDS, { ...base, effectiveFrom: "2026-11-07" }, NOW)).toEqual({})
    expect(fieldErrors(RATE_FIELDS, { ...base, effectiveFrom: "2026-11-06" }, NOW).effectiveFrom).toMatch(/can't start today or in the past/)
    expect(fieldErrors(RATE_FIELDS, { ...base, effectiveFrom: "2026-02-31x" }, NOW).effectiveFrom).toBe("Effective from must be a date.")
    expect(fieldErrors(RATE_FIELDS, { ...base, unitsPerUsd: "0" }, NOW).unitsPerUsd).toMatch(/above zero/)
  })

  it("applies the estimator's cross-field rules", () => {
    const ok = { action: "mark_paper", inputKind: "pages", baseLow: "2", baseHigh: "4", perInputLow: "1", perInputHigh: "2", effectiveFrom: "" }
    expect(estimatorErrors(ok)).toEqual([])
    expect(estimatorErrors({ ...ok, baseLow: "5" })).toEqual(["Base low can't be above base high."])
    expect(estimatorErrors({ ...ok, perInputLow: "3" })).toEqual(["Per input low can't be above per input high."])
    expect(estimatorErrors({ ...ok, inputKind: "none" })[0]).toMatch(/need a counted input/)
    expect(estimatorErrors({ ...ok, inputKind: "none", perInputLow: "0", perInputHigh: "0" })).toEqual([])
    expect(fieldErrors(ESTIMATOR_FIELDS, ok, NOW)).toEqual({})
  })

  it("marks the rate in force, the scheduled ones and the replaced ones per action", () => {
    const row = (action: string, version: number, effectiveFrom: string) => ({ id: `${action}${version}`, action, version, effectiveFrom })
    const rows = versionRows(
      [
        row("regrade", 1, "2026-09-01T00:00:00Z"),
        row("mark_paper", 1, "2026-09-01T00:00:00Z"),
        row("regrade", 3, "2026-12-01T00:00:00Z"),
        row("regrade", 2, "2026-10-15T00:00:00Z"),
      ],
      NOW,
    ).map((r) => `${r.row.action} v${r.row.version} ${r.status}`)
    expect(rows).toEqual([
      "mark_paper v1 current",
      "regrade v3 scheduled",
      "regrade v2 current",
      "regrade v1 superseded",
    ])
  })

  it("never raises a drift alarm for a free tier or a tier nobody can buy", () => {
    const tier = { ...fx.adminCatalogue.tiers[0], drift: "Paymob amount is 240.00" }
    expect(paymobState(tier)).toMatchObject({ tone: "attention", canSync: true })
    expect(paymobState({ ...tier, isActive: false })).toMatchObject({ tone: "muted", canSync: true })
    expect(paymobState({ ...tier, priceMinor: 0, drift: "Not synced to Paymob yet" })).toMatchObject({ tone: "free", canSync: false })
    expect(paymobState({ ...tier, drift: null })).toMatchObject({ tone: "ok" })
  })
})

describe("admin billing failures", () => {
  const api = (status: number, detail?: unknown) => new ApiError(status, "x", detail)

  it("shows the server's own sentence for a refused value", () => {
    expect(adminBillingFailureMessage(api(409, { code: "code_taken", message: "A tier with code pack_500 exists." }), "save")).toBe(
      "A tier with code pack_500 exists.",
    )
    expect(adminBillingFailureMessage(api(422, { code: "effective_from_in_past", message: "A new version cannot start in the past." }), "save")).toMatch(
      /Pick a later day/,
    )
    expect(adminBillingFailureMessage(api(422, [{ loc: ["body", "name"], msg: "x" }]), "save")).toMatch(/Check each field/)
  })

  it("says what is and is not known when the outcome is unclear", () => {
    expect(adminBillingFailureMessage(api(502, { code: "paymob_plan_create_failed", message: "boom" }), "sync")).toBe(
      "Paymob didn't accept this request, so nothing was changed. Try again in a minute.",
    )
    expect(adminBillingFailureMessage(api(403), "save")).toMatch(/Only platform admins/)
    expect(adminBillingFailureMessage(api(0), "save")).toMatch(/may not have been saved/)
    expect(adminBillingFailureMessage(api(500), "save this change")).toMatch(/check whether it saved/)
    expect(adminBillingFailureMessage(new Error("raw"), "save")).not.toContain("raw")
  })

  it("retries a dropped request but never a refusal", () => {
    expect(adminRetry(0, api(403))).toBe(false)
    expect(adminRetry(0, api(422))).toBe(false)
    expect(adminRetry(0, api(500))).toBe(true)
    expect(adminRetry(2, api(500))).toBe(false)
  })
})
