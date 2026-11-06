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
    blockSource: null,
    retry: () => undefined,
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

  it("keeps a persistent polite status region, even for an estimate-driven block", () => {
    expect(render(gate({}))).toMatch(/^<div role="status">/)
    const blocked = render(gate({ block: { reason: "insufficient_credits", estimate: null }, blockSource: "estimate" }))
    expect(blocked).toMatch(/^<div role="status">/)
    expect(blocked).not.toContain('role="alert"')
  })

  it("alerts only for a 402 returned by the start action, outside the status region", () => {
    const html = render(gate({ block: { reason: "insufficient_credits", estimate: null }, blockSource: "start" }))
    expect(html).toContain('role="alert"')
    expect(html).not.toContain('role="status"')
  })

  it("offers Try again on a blocked notice", () => {
    expect(render(gate({ block: { reason: "insufficient_credits", estimate: null }, blockSource: "estimate" }))).toContain("Try again")
  })

  it("omits the seat sentence for a seat or no payer", () => {
    for (const payer of ["seat", "none"] as const) {
      state.estimate = okQuery({ ...fx.estimate, payer })
      expect(render(gate({}), { subjectUnknown: true })).not.toContain("seat pays first")
    }
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

  it("uses a configurable heading level and live role, and Try again only when asked", () => {
    const html = notice("insufficient_credits", { headingLevel: 2, live: "status" })
    expect(html).toContain("<h2 ")
    expect(html).toContain('role="status"')
    expect(html).not.toContain("Try again")
    expect(notice("insufficient_credits", { onRetry: () => undefined })).toContain("Try again")
  })

  it("points outstanding debt at credits", () => {
    expect(notice("outstanding_debt")).toContain(`href="${paths.packs}"`)
  })

  it("names the manager for any reason that would otherwise link", () => {
    expect(notice("no_active_plan", { managedByName: "Mona" })).toContain("Ask Mona to add credits.")
    expect(notice("outstanding_debt", { managedByName: "Mona" })).not.toContain("href=")
  })

  it("asks the lead teacher even when links are available", () => {
    const html = renderStatic(
      h(UsageBlockedNotice, { block: { reason: "out_of_seat_scope", estimate: null }, audience: "teacher", paths, managedByName: null }),
    )
    expect(html).toContain("Ask your lead teacher to raise it.")
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
