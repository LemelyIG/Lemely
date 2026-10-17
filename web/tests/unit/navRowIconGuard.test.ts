import { createElement, isValidElement } from "react"
import { describe, expect, it } from "vitest"
import { House } from "@phosphor-icons/react"

/*
 * Regression for the `/student` portal crash (React error #31: "Objects are
 * not valid as a React child"): `NavRow` (portals/student/index.tsx) takes
 * `icon: Icon | ReactElement` — a bare Phosphor component for every ordinary
 * row, or an already-rendered `<SubjectGlyph>` for the one row that needs its
 * own tone/size. It used to tell the two apart with `typeof icon ===
 * "function"`, rendering `<Glyph .../>` on true and the value as-is on false.
 *
 * Every Phosphor icon is `React.forwardRef`-wrapped, so `typeof House` is
 * `"object"` (`{ $$typeof, render, displayName }`), never `"function"` — the
 * guard picked the *else* branch for the common case and rendered the bare
 * icon object as a child, which is exactly error #31's payload shape. The fix
 * is `isValidElement`, which correctly separates "a component to invoke" from
 * "an element already built".
 */
describe("NavRow's icon-or-element guard", () => {
  it("a bare Phosphor icon is not typeof function", () => {
    expect(typeof House).not.toBe("function")
  })

  it("isValidElement is false for a bare Phosphor icon", () => {
    expect(isValidElement(House)).toBe(false)
  })

  it("isValidElement is true for an already-rendered element", () => {
    expect(isValidElement(createElement(House, { size: 16 }))).toBe(true)
  })
})
