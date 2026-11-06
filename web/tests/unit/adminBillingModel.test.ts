import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import {
  ADJUST_FIELDS,
  CANCEL_FIELDS,
  EXTEND_FIELDS,
  FORGIVE_FIELDS,
  GRANT_FIELDS,
  REFUND_FIELDS,
  activatableTiers,
  activationBody,
  activationFields,
  adjustBody,
  canVoid,
  cancelBody,
  extendBody,
  forgiveBody,
  grantBody,
  humanize,
  paymentActionState,
  refundAmountErrors,
  refundBody,
  refundOutcome,
  refundableMinor,
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
  PartialSaveError,
  featureLinesOf,
  formatUtc,
  freeChanges,
  freeValues,
  hiddenFeatureCount,
  mergeFeatures,
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

  it("raises the crimson drift alarm only for a tier on sale that is missing or differs", () => {
    const tier = { ...fx.adminCatalogue.tiers[0], drift: "Paymob plan differs from the catalogue", driftState: "drifted" as const }
    expect(paymobState(tier)).toMatchObject({ tone: "attention", canSync: true })
    expect(paymobState({ ...tier, driftState: "not_synced", drift: "Not synced to Paymob yet" })).toMatchObject({ tone: "attention" })
    expect(paymobState({ ...tier, isActive: false })).toMatchObject({ tone: "muted", canSync: true })
    expect(paymobState({ ...tier, priceMinor: 0, driftState: "not_synced", drift: "Not synced to Paymob yet" })).toMatchObject({ tone: "free", canSync: false })
    expect(paymobState({ ...tier, drift: null, driftState: "in_sync" })).toMatchObject({ tone: "ok" })
  })

  it("treats a plan nobody checked as a neutral prompt to sync, not a fault", () => {
    const state = paymobState({ ...fx.adminCatalogue.tiers[0], drift: "Paymob plan not checked", driftState: "unverified" })
    expect(state.tone).toBe("neutral")
    expect(state.canSync).toBe(true)
    expect(state.text).toMatch(/Sync to confirm/)
  })

  it("round-trips a tier's stored features: unknown keys and false flags survive an edit", () => {
    const raw = { "Mark past papers": true, "Study plans": true, papers: "unlimited", beta: false, tiers: 3 }
    const tier = { ...fx.adminCatalogue.tiers[0], features: ["Mark past papers", "Study plans"], rawFeatures: raw }
    const v = tierValues(tier)
    expect(featureLinesOf(v)).toEqual(["Mark past papers", "Study plans"])
    // Untouched form: identical features come back.
    expect(tierUpdateBody(v, "r", raw).features).toEqual(raw)
    // Remove one true line, add one: non-true keys stay, the removed line goes, the new one is true.
    const edited = { ...v, features: "Mark past papers\nClass analytics" }
    expect(tierUpdateBody(edited, "r", raw).features).toEqual({ papers: "unlimited", beta: false, tiers: 3, "Mark past papers": true, "Class analytics": true })
    // Typing the name of a stored-false key turns it on.
    expect(mergeFeatures({ beta: false }, ["beta"])).toEqual({ beta: true })
    expect(hiddenFeatureCount(raw)).toBe(3)
    // Without raw features (a new tier) only the typed lines are sent.
    expect(tierUpdateBody(v, "r").features).toEqual({ "Mark past papers": true, "Study plans": true })
  })

  it("sends only the free allowances that changed, and an unset one always counts as changed", () => {
    const current = { studentSignupUnits: 300, teacherSignupUnits: 1000, teacherSignupExpiryDays: 30 }
    expect(freeChanges(freeValues(current), "r", current)).toEqual([])
    expect(freeChanges({ ...freeValues(current), teacherSignupUnits: "1200" }, "r", current)).toEqual([{ audience: "teacher", units: 1200, reason: "r" }])
    const unset = { studentSignupUnits: null, teacherSignupUnits: 1000, teacherSignupExpiryDays: 30 }
    expect(freeValues(unset).studentSignupUnits).toBe("")
    expect(fieldErrors([{ name: "studentSignupUnits", label: "Student free allowance (units)", kind: "number" }], freeValues(unset))).toEqual({
      studentSignupUnits: "Student free allowance (units) is required.",
    })
    expect(freeChanges({ ...freeValues(unset), studentSignupUnits: "0" }, "r", unset)).toEqual([{ audience: "student", units: 0, reason: "r" }])
  })

  it("shows an effective-from instant with its time in UTC", () => {
    expect(formatUtc("2026-12-01T00:00:00Z")).toBe("1 Dec 2026, 00:00 UTC")
    expect(formatUtc("2026-10-15T13:05:00+02:00")).toBe("15 Oct 2026, 11:05 UTC")
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

  it("claims 'nothing was changed' on a 502 only for the plan sync", () => {
    const e = api(502, { code: "paymob_plan_create_failed", message: "boom" })
    expect(adminBillingFailureMessage(e, "sync", { rolledBackOn502: true })).toBe("Paymob didn't accept this request, so nothing was changed. Try again in a minute.")
    const other = adminBillingFailureMessage(e, "save this change")
    expect(other).toMatch(/outcome is unknown/)
    expect(other).not.toMatch(/nothing was changed/)
  })

  it("says which allowance saved when the second request fails", () => {
    const partial = new PartialSaveError(["the student free allowance"], "the teacher signup credits", api(422, { code: "units_rejected", message: "The database refused these units." }))
    expect(adminBillingFailureMessage(partial, "save")).toBe("the student free allowance was saved, but the teacher signup credits was not. The database refused these units.")
  })

  it("says what is and is not known when the outcome is unclear", () => {
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

describe("customer action bodies", () => {
  it("builds plan 07's grant, adjust, forgive, activation, extend, cancel and refund bodies", () => {
    expect(grantBody({ units: "200", validDays: "" }, "goodwill", "rq1")).toEqual({ units: 200, validDays: null, requestId: "rq1", reason: "goodwill" })
    expect(grantBody({ units: "200", validDays: "90" }, "goodwill", "rq1").validDays).toBe(90)
    expect(adjustBody({ units: "-40" }, "correction", "rq2")).toEqual({ units: -40, requestId: "rq2", reason: "correction" })
    expect(forgiveBody({ units: "" }, "forgive all")).toEqual({ units: null, reason: "forgive all" })
    expect(forgiveBody({ units: "12" }, "forgive part")).toEqual({ units: 12, reason: "forgive part" })
    expect(activationBody({ planTierId: "t1", periodDays: "30" }, "complimentary")).toEqual({ planTierId: "t1", periodDays: 30, reason: "complimentary" })
    expect(extendBody({ days: "7" }, "outage")).toEqual({ days: 7, reason: "outage" })
    expect(cancelBody({ immediate: true }, "fraud")).toEqual({ when: "now", reason: "fraud" })
    expect(cancelBody({ immediate: false }, "asked")).toEqual({ when: "period_end", reason: "asked" })
    expect(refundBody({ amountMajor: "150" }, "duplicate")).toEqual({ amountMinor: 15000, reason: "duplicate" })
    expect(refundBody({ amountMajor: "" }, "full")).toEqual({ amountMinor: null, reason: "full" })
  })

  it("never lets a non-number reach a ledger body", () => {
    for (const bad of ["", "abc", "0", "-0", "1.5", "- 4", "12e3"]) {
      expect(Object.keys(fieldErrors(ADJUST_FIELDS, { units: bad })), `adjust ${bad}`).toEqual(["units"])
    }
    expect(fieldErrors(ADJUST_FIELDS, { units: "-40" })).toEqual({})
    expect(fieldErrors(ADJUST_FIELDS, { units: "40" })).toEqual({})
    expect(Object.keys(fieldErrors(GRANT_FIELDS, { units: "0", validDays: "" }))).toEqual(["units"])
    expect(Object.keys(fieldErrors(GRANT_FIELDS, { units: "5", validDays: "0" }))).toEqual(["validDays"])
    expect(fieldErrors(FORGIVE_FIELDS, { units: "" })).toEqual({})
    expect(Object.keys(fieldErrors(FORGIVE_FIELDS, { units: "0" }))).toEqual(["units"])
    expect(Object.keys(fieldErrors(EXTEND_FIELDS, { days: "0" }))).toEqual(["days"])
    expect(fieldErrors(CANCEL_FIELDS, { immediate: false })).toEqual({})
    expect(Object.keys(fieldErrors(activationFields([]), { planTierId: "t", periodDays: "0" }))).toEqual(["periodDays"])
    expect(Object.keys(fieldErrors(REFUND_FIELDS, { amountMajor: "0" }))).toEqual(["amountMajor"])
    expect(fieldErrors(REFUND_FIELDS, { amountMajor: "" })).toEqual({})
  })
})

describe("refunds that may not have happened", () => {
  const base = { id: "r1", kind: "refund" as const, amountMinor: 15000, reason: "dup", adminUserId: "a", clawedBackUnits: 0, createdAt: "", updatedAt: "" }

  it("calls an unknown outcome unknown, never a failure, and a refusal a refusal", () => {
    const unknown = refundOutcome({ ...base, status: "unknown" }, "EGP")
    expect(unknown.label).toMatch(/outcome unknown/)
    expect(unknown.detail).toMatch(/may have gone through/)
    expect(`${unknown.label} ${unknown.detail}`.toLowerCase()).not.toMatch(/fail|declin|nothing was/)
    expect(unknown.tone).toBe("attention")
    const failed = refundOutcome({ ...base, status: "failed" }, "EGP")
    expect(failed.label).toMatch(/declined/)
    expect(failed.tone).toBe("error")
    expect(refundOutcome({ ...base, status: "succeeded", clawedBackUnits: 300 }, "EGP").detail).toMatch(/300 unspent units taken back/)
    expect(refundOutcome({ ...base, kind: "void", status: "requested" }, "EGP").label).toMatch(/^Void of/)
  })

  it("offers only the check while a refund is open, and nothing once the payment is settled", () => {
    const p = { status: "paid" as const, refunds: [] as never[], refundedMinor: 0, amountMinor: 25000 }
    expect(paymentActionState(p)).toBe("open")
    expect(paymentActionState({ ...p, refunds: [{ ...base, status: "unknown" }] })).toBe("settling")
    expect(paymentActionState({ ...p, refunds: [{ ...base, status: "requested" }] })).toBe("settling")
    expect(paymentActionState({ ...p, refunds: [{ ...base, status: "failed" }] })).toBe("open")
    expect(paymentActionState({ ...p, status: "refunded" })).toBe("closed")
    expect(paymentActionState({ ...p, status: "pending" })).toBe("closed")
    expect(paymentActionState({ ...p, status: "partially_refunded" })).toBe("open")
  })

  it("voids only a payment nothing has been taken back from, and caps a refund at what is left", () => {
    expect(canVoid({ status: "paid", refundedMinor: 0 })).toBe(true)
    expect(canVoid({ status: "partially_refunded", refundedMinor: 1000 })).toBe(false)
    expect(refundableMinor({ amountMinor: 25000, refundedMinor: 4000 })).toBe(21000)
    expect(refundAmountErrors({ amountMajor: "210.01" }, 21000, "EGP")).toHaveLength(1)
    expect(refundAmountErrors({ amountMajor: "210" }, 21000, "EGP")).toEqual([])
    expect(refundAmountErrors({ amountMajor: "" }, 21000, "EGP")).toEqual([])
  })

  it("words a dropped connection on a customer action for that page, not the catalogue", () => {
    const err = new ApiError(0, "net", undefined)
    expect(adminBillingFailureMessage(err, "forgive this debt", { reload: "Reload this page" })).toMatch(/^The connection dropped.*Reload this page to check before trying again\.$/)
    expect(adminBillingFailureMessage(err, "save")).toMatch(/Reload the catalogue/)
    expect(adminBillingFailureMessage(new ApiError(409, "x", { code: "refund_in_flight" }), "refund")).toMatch(/waiting on Paymob/)
  })
})

describe("customer view helpers", () => {
  it("humanizes codes and lists only plans that can be activated for the customer's role", () => {
    expect(humanize("pending_first_payment")).toBe("Pending first payment")
    const tier = (id: string, audience: "student" | "teacher", isActive = true, priceMinor = 25000) =>
      ({ id, code: id, name: id, audience, isActive, priceMinor }) as never
    const tiers = [tier("s", "student"), tier("t", "teacher"), tier("old", "student", false), tier("free", "student", true, 0)]
    expect(activatableTiers(tiers, "student").map((t: { id: string }) => t.id)).toEqual(["s"])
    expect(activatableTiers(tiers, "teacher").map((t: { id: string }) => t.id)).toEqual(["t"])
    expect(activatableTiers(tiers, "parent").map((t: { id: string }) => t.id)).toEqual(["s", "t"])
  })
})
