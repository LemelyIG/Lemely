import { describe, expect, it } from "vitest"
import {
  backgroundState,
  isWithinBase,
  overlayCloseAction,
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

describe("overlayCloseAction", () => {
  const base = { overlayBase: BASE, fallbackPath: "/teacher" }

  it("steps back when the page underneath is the previous history entry", () => {
    expect(overlayCloseAction({ ...base, state: backgroundState(classes), historyIndex: 3 })).toEqual({
      kind: "back",
    })
  })

  it("replaces with the background page when there is nothing to step back to", () => {
    expect(overlayCloseAction({ ...base, state: backgroundState(classes), historyIndex: 0 })).toEqual({
      kind: "replace",
      to: "/teacher/classes?sort=name",
    })
    expect(
      overlayCloseAction({ ...base, state: backgroundState(classes), historyIndex: null }),
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
        state: backgroundState({ pathname: BASE, search: "", hash: "" }),
        historyIndex: 2,
      }),
    ).toEqual({ kind: "replace", to: "/teacher" })
  })
})
