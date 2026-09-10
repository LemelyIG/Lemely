import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { WIDGET_DATA_REPLY, type StudentWidgetData } from "@/sw/widgetBridge"
import { answerWidgetDataRequest } from "@/lib/widget/widgetClientBridge"

/**
 * Packet: wire the widget service-worker bridge (blocking, Phase A).
 *
 * The page half of the widget handshake — same shape as
 * `notifications.test.ts`'s `answerPushContentRequest` coverage: no jsdom
 * here (D3.20), so the real `navigator.serviceWorker` plumbing in
 * `registerWidgetClientBridge` is kept thin and pinned as a source-text
 * gate, while `answerWidgetDataRequest` — the actual decision — is
 * exercised directly with a fake fetcher.
 */

function widgetData(overrides: Partial<StudentWidgetData> = {}): StudentWidgetData {
  return { streak: 5, nextSession: null, ...overrides }
}

describe("answerWidgetDataRequest", () => {
  it("returns the reply when the fetch succeeds for a student", async () => {
    const reply = await answerWidgetDataRequest(
      () => Promise.resolve(widgetData({ streak: 9 })),
      "student",
    )
    expect(reply).toEqual({ type: WIDGET_DATA_REPLY, streak: 9, nextSession: null })
  })

  it("carries a real next session through", async () => {
    const nextSession = { title: "Momentum", startsAt: "2026-09-11T12:00:00Z" }
    const reply = await answerWidgetDataRequest(
      () => Promise.resolve(widgetData({ nextSession })),
      "student",
    )
    expect(reply?.nextSession).toEqual(nextSession)
  })

  it("returns null without fetching for a non-student role — GET /api/student/widget is student-only and would just 403", async () => {
    let fetched = false
    const reply = await answerWidgetDataRequest(() => {
      fetched = true
      return Promise.resolve(widgetData())
    }, "teacher")
    expect(reply).toBeNull()
    expect(fetched).toBe(false)
  })

  it("returns null without fetching when there is no session role at all", async () => {
    const reply = await answerWidgetDataRequest(() => Promise.resolve(widgetData()), undefined)
    expect(reply).toBeNull()
  })

  it("returns null instead of throwing when the fetch fails", async () => {
    // The worker's fallback (the static stub) already covers this; throwing
    // here would leave the worker's port un-answered and burn its whole
    // timeout instead of getting a prompt "nothing to say".
    const reply = await answerWidgetDataRequest(
      () => Promise.reject(new Error("network error")),
      "student",
    )
    expect(reply).toBeNull()
  })
})

describe("registerWidgetClientBridge source-text gate (wiring only — not exercised by a test, D3.20)", () => {
  const source = readFileSync(
    join(import.meta.dirname, "..", "..", "src", "lib", "widget", "widgetClientBridge.ts"),
    "utf8",
  )

  it("listens for the worker's WIDGET_DATA_REQUEST message", () => {
    expect(source).toMatch(/addEventListener\(\s*"message"/)
    expect(source).toMatch(/WIDGET_DATA_REQUEST/)
  })

  it("posts its answer back over the port the worker supplied", () => {
    expect(source).toMatch(/port\.postMessage\(/)
  })

  it("is a no-op when there is no service worker at all", () => {
    expect(source).toMatch(/"serviceWorker" in navigator/)
  })
})
