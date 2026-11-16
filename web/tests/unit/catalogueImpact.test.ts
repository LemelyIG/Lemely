import { describe, expect, it } from "vitest"
import { packValues, tierUpdateBody, packUpdateBody, tierValues, TIER_UPDATE_FIELDS, PACK_UPDATE_FIELDS, fieldErrors } from "@/lib/adminBillingModel"
import {
  confirmProblem,
  packImpactLines,
  packPriceTarget,
  tierImpact,
  tierImpactLines,
  type TierImpactSettings,
} from "@/lib/catalogueImpact"
import type { AdminCreditPack, AdminPlanTier } from "@/lib/billingTypes"
import { fx } from "./support/billingFixtures"

const student: AdminPlanTier = { ...fx.adminCatalogue.tiers[0]!, liveSubscriptionCount: 14 }
const teacher: AdminPlanTier = {
  ...student,
  id: "t-t-m",
  code: "teacher_pro_m",
  audience: "teacher",
  priceMinor: 90000,
  includedSeats: 20,
  seatAllowanceUnits: 300,
  extraSeatPriceMinor: 3000,
}
const pack: AdminCreditPack = { ...fx.adminCatalogue.packs[0]!, autoTopupCount: 6 }
const settings: TierImpactSettings = { noticeDays: 30, amountUpdatable: true }

const edit = (t: AdminPlanTier, change: Record<string, string | boolean>) => ({ ...tierValues(t), ...change })

describe("tier impact: when a warning shows", () => {
  it("shows with subscribers and a changed price", () => {
    expect(tierImpact(student, edit(student, { priceMajor: "275.00" }), settings)).toMatchObject({ customers: 14 })
  })
  it("shows for each term: allowance, included seats, seat allowance, extra-seat price", () => {
    expect(tierImpact(student, edit(student, { allowanceUnits: "5000" }), settings)).not.toBeNull()
    expect(tierImpact(teacher, edit(teacher, { includedSeats: "15" }), settings)).not.toBeNull()
    expect(tierImpact(teacher, edit(teacher, { seatAllowanceUnits: "250" }), settings)).not.toBeNull()
    expect(tierImpact(teacher, edit(teacher, { extraSeatPriceMajor: "35.00" }), settings)).not.toBeNull()
  })
  it("does not show for a name, feature or on-sale edit", () => {
    expect(tierImpact(student, edit(student, { name: "Student Plus 2", features: "One line", isActive: false }), settings)).toBeNull()
  })
  it("does not show without subscribers", () => {
    const empty = { ...student, liveSubscriptionCount: 0 }
    expect(tierImpact(empty, edit(empty, { priceMajor: "275.00" }), settings)).toBeNull()
  })
  it("does not show for an unchanged price typed another way", () => {
    expect(tierImpact(student, edit(student, { priceMajor: "250" }), settings)).toBeNull()
  })
  it("ignores a half-typed number rather than warning on it", () => {
    expect(tierImpact(student, edit(student, { priceMajor: "2." }), settings)).toBeNull()
    expect(tierImpact(student, edit(student, { allowanceUnits: "" }), settings)).toBeNull()
  })
  it("ignores seat fields a student tier cannot have", () => {
    expect(tierImpact(student, edit(student, { includedSeats: "9" }), settings)).toBeNull()
  })
})

describe("tier impact: copy", () => {
  const lines = (t: AdminPlanTier, change: Record<string, string | boolean>, s: TierImpactSettings) =>
    tierImpactLines(tierImpact(t, edit(t, change), s)!)

  it("states the customer count and the configured notice days", () => {
    const [lead] = lines(student, { priceMajor: "275.00" }, { noticeDays: 45, amountUpdatable: true })
    expect(lead).toContain("14 customers are on this plan")
    expect(lead).toContain("after 45 days")
    expect(lead).not.toContain("30 days")
  })
  it("groups large counts", () => {
    const many = { ...student, liveSubscriptionCount: 1284 }
    expect(tierImpactLines(tierImpact(many, edit(many, { priceMajor: "275.00" }), settings)!)[0]).toContain("1,284 customers are on this plan")
    expect(packImpactLines({ autoTopupCount: 1284, capBelowPriceCount: 1000 })![1]).toContain("1,000 of them have")
  })
  it("reads right for one customer and one notice day", () => {
    const one = { ...student, liveSubscriptionCount: 1 }
    const [lead] = tierImpactLines(tierImpact(one, edit(one, { priceMajor: "275.00" }), { noticeDays: 1, amountUpdatable: true })!)
    expect(lead).toContain("1 customer is on this plan")
    expect(lead).toContain("after 1 day ")
  })
  it("adds the fixed-amount sentence only on the fallback and only when a price changes", () => {
    const fallback = { noticeDays: 30, amountUpdatable: false }
    expect(lines(student, { priceMajor: "275.00" }, fallback)).toHaveLength(2)
    expect(lines(student, { priceMajor: "275.00" }, fallback)[1]).toContain("Paymob can't change running renewals")
    expect(lines(student, { priceMajor: "275.00" }, fallback)[1]).toContain("waits 30 days for everyone")
    expect(lines(student, { priceMajor: "275.00" }, settings)).toHaveLength(1)
    expect(lines(student, { allowanceUnits: "5000" }, fallback)).toHaveLength(1)
    expect(lines(teacher, { extraSeatPriceMajor: "35.00" }, fallback)).toHaveLength(2)
    // A seat-price-only edit ends only plans that hold extra seats: the browser cannot say every plan ends.
    expect(tierImpact(teacher, edit(teacher, { extraSeatPriceMajor: "40.00" }), fallback)!.endsAtRenewal).toBe(false)
    expect(tierImpact(student, edit(student, { priceMajor: "275.00" }), fallback)!.endsAtRenewal).toBe(true)
  })
})

describe("pack price impact", () => {
  it("asks for a preview only when the price rises and auto top-ups exist", () => {
    expect(packPriceTarget(pack, { ...packValues(pack), priceMajor: "175.00" })).toBe(17500)
    expect(packPriceTarget(pack, { ...packValues(pack), priceMajor: "100.00" })).toBeNull()
    expect(packPriceTarget(pack, { ...packValues(pack), priceMajor: "150.00" })).toBeNull()
    expect(packPriceTarget({ ...pack, autoTopupCount: 0 }, { ...packValues(pack), priceMajor: "175.00" })).toBeNull()
  })
  it("does not ask for a price the server would refuse", () => {
    expect(packPriceTarget(pack, { ...packValues(pack), priceMajor: "1000000000.00" })).toBeNull()
    expect(packPriceTarget(pack, { ...packValues(pack), priceMajor: "17x" })).toBeNull()
  })
  it("counts what the preview says", () => {
    expect(packImpactLines({ autoTopupCount: 6, capBelowPriceCount: 2 })).toEqual([
      "6 customers top up automatically with this pack and will be charged the new price.",
      "2 of them have a monthly limit below it, so their auto top-up will stop until they raise the limit.",
    ])
  })
  it("drops the cap sentence when no limit is below the price", () => {
    expect(packImpactLines({ autoTopupCount: 6, capBelowPriceCount: 0 })).toHaveLength(1)
  })
  it("reads right for one customer", () => {
    expect(packImpactLines({ autoTopupCount: 1, capBelowPriceCount: 1 })).toEqual([
      "1 customer tops up automatically with this pack and will be charged the new price.",
      "1 of them has a monthly limit below it, so their auto top-up will stop until they raise the limit.",
    ])
  })
  it("says nothing when no auto top-up can charge", () => {
    expect(packImpactLines({ autoTopupCount: 0, capBelowPriceCount: 0 })).toBeNull()
  })
})

describe("confirm gate", () => {
  it("blocks until the box is ticked, only while a warning shows", () => {
    expect(confirmProblem(true, null, "a")).toBe("Tick the box to confirm.")
    expect(confirmProblem(true, "a", "a")).toBeNull()
    expect(confirmProblem(false, null, "")).toBeNull()
  })
  it("a tick confirms one warning: a different one is unconfirmed", () => {
    expect(confirmProblem(true, "a", "b")).toBe("Tick the box to confirm.")
  })
})

describe("payload shape", () => {
  it("sends the version the row was opened on", () => {
    expect(tierUpdateBody(tierValues(student), "Raise price", student.rawFeatures, student.version)).toMatchObject({ expectedVersion: 4, reason: "Raise price" })
    expect(packUpdateBody(packValues(pack), "Raise price", pack.version)).toMatchObject({ expectedVersion: 2, priceMinor: 15000 })
  })

})

describe("client limits match the server", () => {
  const err = (fields: typeof TIER_UPDATE_FIELDS, v: Record<string, string | boolean>) => fieldErrors(fields, v)
  it("tier price tops out at the INTEGER column, 21,474,836.47", () => {
    expect(err(TIER_UPDATE_FIELDS, edit(student, { priceMajor: "21474836.47" })).priceMajor).toBeUndefined()
    expect(err(TIER_UPDATE_FIELDS, edit(student, { priceMajor: "21474836.48" })).priceMajor).toContain("at most 21,474,836.47")
  })
  it("allowance units go to a trillion, seats to 10,000", () => {
    expect(err(TIER_UPDATE_FIELDS, edit(student, { allowanceUnits: "1000000000000" })).allowanceUnits).toBeUndefined()
    expect(err(TIER_UPDATE_FIELDS, edit(student, { allowanceUnits: "1000000000001" })).allowanceUnits).toBeDefined()
    expect(err(TIER_UPDATE_FIELDS, edit(teacher, { includedSeats: "10000" })).includedSeats).toBeUndefined()
    expect(err(TIER_UPDATE_FIELDS, edit(teacher, { includedSeats: "10001" })).includedSeats).toBeDefined()
  })
  it("pack price goes to 100,000,000.00 and credits to a trillion", () => {
    expect(err(PACK_UPDATE_FIELDS, { ...packValues(pack), priceMajor: "100000000.00" }).priceMajor).toBeUndefined()
    expect(err(PACK_UPDATE_FIELDS, { ...packValues(pack), priceMajor: "100000000.01" }).priceMajor).toBeDefined()
    expect(err(PACK_UPDATE_FIELDS, { ...packValues(pack), units: "1000000000000" }).units).toBeUndefined()
  })
})
