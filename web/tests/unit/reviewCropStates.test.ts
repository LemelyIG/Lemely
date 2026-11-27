import { createElement, useState } from "react"
import { MemoryRouter } from "react-router-dom"
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import type { AnswerView } from "@/portals/teacher/screens/review"
import { byText, click, find, findAll, fire, installFakeDom, mount, type FakeDom, type FakeNode } from "./support/fakeDom"

/*
 * The crop and page states of the review answer panel, behaviourally. The real
 * `AnswerPanel`, `useAnswerImages` and `useReviewItemImage` run under real React
 * effects over an in-memory DOM (support/fakeDom.ts, D3.20: no jsdom). Only the
 * network call is replaced, so a fetch that rejects (useTeacherApi's catch) and a
 * decode that fails (`onDecodeError`) are both driven for real.
 */
const fetchBlobUrl = vi.hoisted(() => vi.fn())
vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/api")>()), fetchBlobUrl }))

import { AnswerPanel, useAnswerImages } from "@/portals/teacher/screens/review"

const CROP_ALT = "The region of the student's scan this question's answer was read from"
const PAGE_ALT = "The whole page this answer is on"
const SCAN_FAILED = "Couldn't show the scan."
const PAGE_FAILED = "Couldn't show the page."
const SCAN_ANNOUNCED = "Couldn't show the scan. Lemely's reading is below."

function view(over: Partial<AnswerView> = {}): AnswerView {
  return {
    key: "i1", title: "Layla Hassan · Q4(b)", subtitle: "10B · 0580/42", studentHref: null,
    pageLabel: null, hasScan: true, transcription: "x = 3", selfReview: [],
    scheme: { expected: null, topic: null }, notes: { reason: null, feedback: null },
    points: [], matchedPointIds: [], maximumMarks: 2, lemelyMarks: 1,
    clampNote: null, status: "open", integrity: false, canAdjust: true, cannotAdjustReason: null,
    correction: null, resolutionNote: null, confidenceScore: 0.64,
    ...over,
  }
}

/** The queue's own wiring: the real image hook feeding the real panel, with a button that moves to the next item. */
function Host() {
  const [id, setId] = useState("item-1")
  const images = useAnswerImages(id, true)
  return createElement("div", null,
    createElement("button", { type: "button", "aria-label": "Move on", onClick: () => setId("item-2") }, "Move on"),
    createElement(AnswerPanel, { view: view({ key: id }), images, marking: null }))
}

let dom: FakeDom
beforeAll(() => { dom = installFakeDom() })
afterAll(() => dom.restore())
beforeEach(() => {
  fetchBlobUrl.mockReset()
  fetchBlobUrl.mockImplementation(async (path: string) => `blob:test${path}`)
})

async function settle() {
  const { act } = await import("react")
  await act(async () => { await Promise.resolve(); await Promise.resolve() })
}
async function open() {
  const mounted = await mount(dom, createElement(MemoryRouter, null, createElement(Host)))
  await settle()
  return mounted
}
const img = (root: FakeNode, alt: string) => find(root, (n) => n.nodeName === "IMG" && n.getAttribute("alt") === alt)
const requested = () => fetchBlobUrl.mock.calls.map((c) => c[0])
const live = (root: FakeNode) => find(root, (n) => n.getAttribute("aria-live") === "polite")
const skeleton = (root: FakeNode, label: string) => find(root, (n) => n.getAttribute("aria-label") === label)
/** Text a screen reader would meet in the frame: aria-hidden nodes are skipped. */
const visibleMessages = (root: FakeNode, text: string) =>
  findAll(root, (n) => n.nodeName === "P" && n.textContent.trim() === text && n.getAttribute("aria-hidden") === "true")

describe("the scan frame while the crop loads", () => {
  it("shows the loading skeleton, not a failure, and announces nothing", async () => {
    fetchBlobUrl.mockImplementation(() => new Promise(() => {}))
    const view = await open()
    expect(skeleton(view.container, "Loading the scan")).not.toBeNull()
    expect(view.container.textContent).not.toContain(SCAN_FAILED)
    expect(live(view.container)?.textContent).toBe("")
    expect(requested()).toEqual(["/teacher/review/item-1/crop"])
    await view.unmount()
  })
})

describe("the scan frame once the crop loads", () => {
  it("shows the crop with Lemely's reading as its caption, and announces nothing", async () => {
    const view = await open()
    expect(img(view.container, CROP_ALT)?.getAttribute("src")).toBe("blob:test/teacher/review/item-1/crop")
    expect(skeleton(view.container, "Loading the scan")).toBeNull()
    expect(view.container.textContent).toContain("Lemely read")
    expect(view.container.textContent).toContain("x = 3")
    expect(live(view.container)?.textContent).toBe("")
    await view.unmount()
  })
})

describe("the scan frame when the crop fails", () => {
  it("leaves loading and says so, once, when the fetch is rejected", async () => {
    fetchBlobUrl.mockRejectedValue(new Error("404"))
    const view = await open()
    expect(skeleton(view.container, "Loading the scan")).toBeNull()
    expect(find(view.container, (n) => n.nodeName === "IMG")).toBeNull()
    expect(visibleMessages(view.container, SCAN_FAILED)).toHaveLength(1)
    expect(live(view.container)?.textContent).toBe(SCAN_ANNOUNCED)
    await view.unmount()
  })

  it("says so when the bytes arrive but will not decode, and keeps Lemely's reading", async () => {
    const view = await open()
    const crop = img(view.container, CROP_ALT) as FakeNode
    const region = live(view.container) as FakeNode
    expect(region.textContent).toBe("")
    await fire(crop, "error")
    expect(img(view.container, CROP_ALT)).toBeNull()
    expect(skeleton(view.container, "Loading the scan")).toBeNull()
    expect(visibleMessages(view.container, SCAN_FAILED)).toHaveLength(1)
    // The same region node that was silent a moment ago now carries the message, so it is announced.
    expect(live(view.container)).toBe(region)
    expect(region.textContent).toBe(SCAN_ANNOUNCED)
    expect(view.container.textContent).toContain("Lemely read")
    expect(view.container.textContent).toContain("x = 3")
    await view.unmount()
  })

  it("does not carry a failure over to the next item, which is still loading", async () => {
    fetchBlobUrl.mockImplementation((path: string) => (path.includes("item-1") ? Promise.reject(new Error("404")) : new Promise(() => {})))
    const view = await open()
    expect(live(view.container)?.textContent).toBe(SCAN_ANNOUNCED)
    await click(find(view.container, byText("button", "Move on")) as FakeNode)
    await settle()
    expect(skeleton(view.container, "Loading the scan")).not.toBeNull()
    expect(view.container.textContent).not.toContain(SCAN_FAILED)
    expect(live(view.container)?.textContent).toBe("")
    await view.unmount()
  })
})

describe("the whole-page frame", () => {
  const openPage = async (view: { container: FakeNode }) => {
    await click(find(view.container, byText("button", "Whole page")) as FakeNode)
    await settle()
  }

  it("asks for the page only when its tab opens, then shows it, silently", async () => {
    const view = await open()
    expect(requested()).toEqual(["/teacher/review/item-1/crop"])
    await openPage(view)
    expect(requested()).toEqual(["/teacher/review/item-1/crop", "/teacher/review/item-1/page"])
    expect(img(view.container, PAGE_ALT)?.getAttribute("src")).toBe("blob:test/teacher/review/item-1/page")
    expect(live(view.container)?.textContent).toBe("")
    await view.unmount()
  })

  it("leaves loading and announces the failure when the page fetch is rejected", async () => {
    fetchBlobUrl.mockImplementation((path: string) => (path.endsWith("/page") ? Promise.reject(new Error("422")) : Promise.resolve(`blob:test${path}`)))
    const view = await open()
    const region = live(view.container) as FakeNode
    await openPage(view)
    expect(skeleton(view.container, "Loading the page")).toBeNull()
    expect(visibleMessages(view.container, PAGE_FAILED)).toHaveLength(1)
    expect(live(view.container)).toBe(region)
    expect(region.textContent).toBe(PAGE_FAILED)
    await view.unmount()
  })

  it("announces the failure when the page bytes will not decode", async () => {
    const view = await open()
    await openPage(view)
    await fire(img(view.container, PAGE_ALT) as FakeNode, "error")
    expect(img(view.container, PAGE_ALT)).toBeNull()
    expect(skeleton(view.container, "Loading the page")).toBeNull()
    expect(visibleMessages(view.container, PAGE_FAILED)).toHaveLength(1)
    expect(live(view.container)?.textContent).toBe(PAGE_FAILED)
    await view.unmount()
  })

  it("asks for the page of the next item instead of claiming it failed", async () => {
    const view = await open()
    await openPage(view)
    await click(find(view.container, byText("button", "Move on")) as FakeNode)
    await settle()
    expect(requested()).toContain("/teacher/review/item-2/page")
    expect(view.container.textContent).not.toContain(PAGE_FAILED)
    expect(img(view.container, PAGE_ALT)?.getAttribute("src")).toBe("blob:test/teacher/review/item-2/page")
    await view.unmount()
  })
})
