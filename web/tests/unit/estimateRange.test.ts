import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { billingPaths } from "@/lib/billingPaths"
import { fx } from "./support/billingFixtures"
import { errorQuery, okQuery, pendingQuery, renderStatic } from "./support/billingRender"

const state = vi.hoisted(() => ({ estimate: null as unknown }))
vi.mock("@/lib/hooks/useUsageApi", () => ({ useUsageEstimate: () => state.estimate }))

import { EstimateRange } from "@/components/billing/estimate-range"
import { UsageBlockedNotice } from "@/components/billing/usage-blocked-notice"
import type { MeteredGate } from "@/lib/meteredGate"

const paths = billingPaths({ role: "student" })
const req = { action: "regrade" as const, paperId: "p1" }

function gate(over: Partial<MeteredGate>): MeteredGate {
  return {
    request: req,
    estimate: state.estimate as MeteredGate["estimate"],
    block: null,
    captureError: () => false,
    clear: () => undefined,
    ...over,
  }
}

const render = (g: MeteredGate, extra: Partial<Parameters<typeof EstimateRange>[0]> = {}) =>
  renderStatic(h(EstimateRange, { gate: g, audience: "student", paths, managedByName: null, ...extra }))

beforeEach(() => {
  state.estimate = okQuery(fx.estimate)
})

describe("EstimateRange", () => {
  it("renders nothing without a request", () => {
    expect(render(gate({ request: null }))).toBe("")
  })

  it("announces the loading state", () => {
    state.estimate = pendingQuery()
    expect(render(gate({}))).toMatch(/role="status"[^>]*>.*Working out the cost/)
  })

  it("lets the user start when the estimate fails", () => {
    state.estimate = errorQuery(new ApiError(500, "x"))
    expect(render(gate({}))).toContain("You can still start")
  })

  it("states the range and that the actual cost is charged", () => {
    const html = render(gate({}))
    expect(html).toContain('data-testid="estimate-range"')
    expect(html).toContain("2–4% of your monthly plan")
    expect(html).toContain("charged the actual cost")
  })

  it("warns that a seat may pay when the subject is not known yet", () => {
    state.estimate = okQuery({ ...fx.estimate, payer: "credits" })
    expect(render(gate({}), { subjectUnknown: true })).toContain("seat pays first")
  })

  it("swaps to the blocked notice when blocked", () => {
    const html = render(gate({ block: { reason: "insufficient_credits", estimate: null } }))
    expect(html).toContain('data-testid="usage-blocked-notice"')
    expect(html).not.toContain('data-testid="estimate-range"')
  })
})

describe("UsageBlockedNotice", () => {
  const notice = (
    reason: Parameters<typeof UsageBlockedNotice>[0]["block"]["reason"],
    extra: Partial<Parameters<typeof UsageBlockedNotice>[0]> = {},
  ) =>
    renderStatic(h(UsageBlockedNotice, { block: { reason, estimate: null }, audience: "student", paths, managedByName: null, ...extra }))

  it("is an alert with a next step per reason", () => {
    expect(notice("insufficient_credits")).toContain('role="alert"')
    expect(notice("insufficient_credits")).toContain(`href="${paths.packs}"`)
    expect(notice("no_active_plan")).toContain(`href="${paths.plans}"`)
    const limit = notice("usage_limit_reached")
    expect(limit).toContain(`href="${paths.packs}"`)
    expect(limit).toContain(`href="${paths.plans}"`)
  })

  it("asks the payer instead of linking when someone else manages billing", () => {
    const html = notice("insufficient_credits", { managedByName: "Mona" })
    expect(html).toContain("Ask Mona to add credits.")
    expect(html).not.toContain("href=")
  })

  it("asks the lead teacher for an assistant's cap and shows no links without paths", () => {
    const html = renderStatic(
      h(UsageBlockedNotice, { block: { reason: "out_of_seat_scope", estimate: null }, audience: "teacher", paths: null, managedByName: null }),
    )
    expect(html).toContain("Ask your lead teacher to raise it.")
    expect(html).not.toContain("href=")
  })
})
