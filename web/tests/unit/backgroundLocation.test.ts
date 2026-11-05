import { describe, expect, it } from "vitest"
import {
  backgroundState,
  historyIndexOf,
  isWithinBase,
  overlayCloseAction,
  planOverlayOutlet,
  readBackgroundIdx,
  readBackgroundLocation,
  resolveBackground,
} from "@/lib/nav/backgroundLocation"

const BASE = "/teacher/settings"
const classes = { pathname: "/teacher/classes", search: "?sort=name", hash: "" }

describe("isWithinBase", () => {
  it("matches the base and anything below it, not siblings sharing a prefix", () => {
    expect(isWithinBase(BASE, BASE)).toBe(true)
    expect(isWithinBase(`${BASE}/`, BASE)).toBe(true)
    expect(isWithinBase(`${BASE}/notifications`, BASE)).toBe(true)
    expect(isWithinBase("/teacher/settingsx", BASE)).toBe(false)
    expect(isWithinBase("/teacher", BASE)).toBe(false)
  })
})

describe("readBackgroundLocation", () => {
  it("reads a well-formed background location", () => {
    expect(readBackgroundLocation(backgroundState(classes))).toEqual(classes)
  })

  it("fills a missing search or hash with empty strings", () => {
    expect(readBackgroundLocation({ backgroundLocation: { pathname: "/teacher" } })).toEqual({
      pathname: "/teacher",
      search: "",
      hash: "",
    })
  })

  it.each([
    null,
    undefined,
    "x",
    {},
    { backgroundLocation: null },
    { backgroundLocation: { pathname: 4 } },
    { backgroundLocation: { pathname: "relative" } },
  ])("rejects %j", (state) => {
    expect(readBackgroundLocation(state)).toBeNull()
  })
})

describe("resolveBackground", () => {
  const base = { overlayBase: BASE, fallbackPath: "/teacher" }

  it("prefers the location carried in router state", () => {
    const result = resolveBackground({
      ...base,
      state: backgroundState(classes),
      remembered: { pathname: "/teacher/review", search: "", hash: "" },
    })
    expect(result).toEqual({ location: classes, source: "state" })
  })

  it("falls back to the last page shown when a plain link opened the overlay", () => {
    const remembered = { pathname: "/teacher/review", search: "", hash: "" }
    expect(resolveBackground({ ...base, state: null, remembered })).toEqual({
      location: remembered,
      source: "remembered",
    })
  })

  it("falls back to the portal home on a direct load", () => {
    expect(resolveBackground({ ...base, state: null, remembered: null })).toEqual({
      location: { pathname: "/teacher", search: "", hash: "" },
      source: "fallback",
    })
  })

  it("never uses the overlay itself as its own background", () => {
    const result = resolveBackground({
      ...base,
      state: backgroundState({ pathname: `${BASE}/devices`, search: "", hash: "" }),
      remembered: { pathname: BASE, search: "", hash: "" },
    })
    expect(result.source).toBe("fallback")
  })
})

describe("readBackgroundIdx / historyIndexOf", () => {
  it("reads a recorded background index and rejects junk", () => {
    expect(readBackgroundIdx(backgroundState(classes, 4))).toBe(4)
    expect(readBackgroundIdx(backgroundState(classes))).toBeNull()
    expect(readBackgroundIdx({ backgroundIdx: -1 })).toBeNull()
    expect(readBackgroundIdx({ backgroundIdx: 1.5 })).toBeNull()
    expect(readBackgroundIdx({ backgroundIdx: "2" })).toBeNull()
    expect(readBackgroundIdx(null)).toBeNull()
  })

  it("reads react-router's idx from history.state", () => {
    expect(historyIndexOf({ usr: null, key: "k", idx: 7 })).toBe(7)
    expect(historyIndexOf({ key: "k" })).toBeNull()
    expect(historyIndexOf(null)).toBeNull()
  })
})

describe("overlayCloseAction", () => {
  const base = { overlayBase: BASE, fallbackPath: "/teacher" }

  it("walks back to the recorded background entry", () => {
    expect(
      overlayCloseAction({ ...base, state: backgroundState(classes, 3), historyIndex: 4 }),
    ).toEqual({ kind: "go", delta: -1 })
  })

  it("walks back past entries visited since opening (out to page B and Back again)", () => {
    // Opened at idx 5 over idx 4; tab switches replace, but a detour that
    // pushed entries and came back still lands on idx 4, not on the detour.
    expect(
      overlayCloseAction({ ...base, state: backgroundState(classes, 4), historyIndex: 7 }),
    ).toEqual({ kind: "go", delta: -3 })
  })

  it("replaces when the recorded index is not behind the current entry", () => {
    for (const historyIndex of [3, 2]) {
      expect(
        overlayCloseAction({ ...base, state: backgroundState(classes, 3), historyIndex }),
      ).toEqual({ kind: "replace", to: "/teacher/classes?sort=name" })
    }
  })

  it("replaces with the background page when no index was recorded", () => {
    expect(overlayCloseAction({ ...base, state: backgroundState(classes), historyIndex: 3 })).toEqual({
      kind: "replace",
      to: "/teacher/classes?sort=name",
    })
    expect(
      overlayCloseAction({ ...base, state: backgroundState(classes, 2), historyIndex: null }),
    ).toEqual({ kind: "replace", to: "/teacher/classes?sort=name" })
  })

  it("goes to the fallback on a deep link with no background", () => {
    expect(overlayCloseAction({ ...base, state: null, historyIndex: 5 })).toEqual({
      kind: "replace",
      to: "/teacher",
    })
  })

  it("ignores a background that points inside the overlay", () => {
    expect(
      overlayCloseAction({
        ...base,
        state: backgroundState({ pathname: BASE, search: "", hash: "" }, 1),
        historyIndex: 2,
      }),
    ).toEqual({ kind: "replace", to: "/teacher" })
  })
})

describe("planOverlayOutlet", () => {
  const base = { overlayBase: BASE, fallbackPath: "/teacher" }
  const home = { pathname: "/teacher", search: "", hash: "" }
  const at = (pathname: string, state: unknown = null, search = "") => ({
    pathname,
    search,
    hash: "",
    state,
  })

  it("outside the overlay, the page slot matches the current location", () => {
    const plan = planOverlayOutlet({
      ...base,
      location: at("/teacher/classes", null, "?sort=name"),
      remembered: classes,
      rememberedIdx: 2,
    })
    expect(plan).toEqual({
      inOverlay: false,
      screenLocation: classes,
      background: null,
      replaceState: null,
    })
  })

  it("opening keeps the same screen location, so the page is not remounted", () => {
    const closed = planOverlayOutlet({
      ...base,
      location: at("/teacher/classes", null, "?sort=name"),
      remembered: classes,
      rememberedIdx: 2,
    })
    const open = planOverlayOutlet({
      ...base,
      location: at(BASE, backgroundState(classes, 2)),
      remembered: classes,
      rememberedIdx: 2,
    })
    expect(open.inOverlay).toBe(true)
    expect(open.screenLocation).toEqual(closed.screenLocation)
  })

  it("deep link: falls back to the portal home and writes nothing", () => {
    const plan = planOverlayOutlet({
      ...base,
      location: at(`${BASE}/devices`),
      remembered: null,
      rememberedIdx: null,
    })
    expect(plan.screenLocation).toEqual(home)
    expect(plan.background?.source).toBe("fallback")
    expect(plan.replaceState).toBeNull()
  })

  it("refresh: the background in state survives with no remembered page", () => {
    const plan = planOverlayOutlet({
      ...base,
      location: at(BASE, backgroundState(classes, 2)),
      remembered: null,
      rememberedIdx: null,
    })
    expect(plan.screenLocation).toEqual(classes)
    expect(plan.replaceState).toBeNull()
  })

  it("plain link: writes the remembered page and its index into state", () => {
    const plan = planOverlayOutlet({
      ...base,
      location: at(BASE),
      remembered: classes,
      rememberedIdx: 6,
    })
    expect(plan.screenLocation).toEqual(classes)
    expect(plan.replaceState).toEqual(backgroundState(classes, 6))
  })

  it("after that write, the next render plans no further write", () => {
    const plan = planOverlayOutlet({
      ...base,
      location: at(BASE, backgroundState(classes, 6)),
      remembered: classes,
      rememberedIdx: 6,
    })
    expect(plan.replaceState).toBeNull()
  })

  it("a link state without an index gains the index of the page just shown", () => {
    const plan = planOverlayOutlet({
      ...base,
      location: at(BASE, backgroundState(classes)),
      remembered: classes,
      rememberedIdx: 3,
    })
    expect(plan.replaceState).toEqual(backgroundState(classes, 3))
  })

  it("a link state for a different page than the one shown gets no guessed index", () => {
    const plan = planOverlayOutlet({
      ...base,
      location: at(BASE, backgroundState(classes)),
      remembered: home,
      rememberedIdx: 3,
    })
    expect(plan.screenLocation).toEqual(classes)
    expect(plan.replaceState).toBeNull()
  })
})
