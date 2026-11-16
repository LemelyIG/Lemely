import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

type Kids = { children: { childId: string; displayName: string }[] }
const state = vi.hoisted(() => ({ value: { data: undefined, isPending: false } as { data?: Kids; isPending: boolean } }))
vi.mock("@/lib/hooks/useParentApi", () => ({ useChildren: () => state.value }))

import { ChildSwitcher } from "@/portals/parent/ChildSwitcher"

const KIDS = [
  { childId: "c1", displayName: "Amira" },
  { childId: "c2", displayName: "Omar" },
]

function html(path: string): string {
  return renderToStaticMarkup(
    createElement(
      MemoryRouter,
      { initialEntries: [path] },
      createElement(
        Routes,
        null,
        createElement(Route, { path: "/parent/children/:childId/*", element: createElement(ChildSwitcher) }),
        createElement(Route, { path: "*", element: createElement(ChildSwitcher) }),
      ),
    ),
  )
}

describe("ChildSwitcher states (P2, P4, single child, loading, error)", () => {
  beforeEach(() => {
    state.value = { data: { children: KIDS }, isPending: false }
  })
  it("P4: two children render a select with the accessible name and every child", () => {
    const out = html("/parent/children/c1/topics")
    expect(out).toContain('aria-label="Choose which child to view"')
    expect(out).toContain("<select")
    expect(out).toContain("Amira")
    expect(out).toContain("Omar")
  })
  it("P2: nothing off a child route", () => {
    expect(html("/parent")).toBe("")
  })
  it("one child shows a static name pill and no control", () => {
    state.value = { data: { children: [KIDS[0]] }, isPending: false }
    const out = html("/parent/children/c1")
    expect(out).toContain("Amira")
    expect(out).not.toContain("<select")
  })
  it("the single-child pill carries no control ring, so it does not read as a button", () => {
    state.value = { data: { children: [KIDS[0]] }, isPending: false }
    const out = html("/parent/children/c1")
    expect(out).not.toContain("inset_0_0_0_1.5px")
    expect(out).not.toContain("cursor-pointer")
  })
  it("two children keep the ring that marks the control", () => {
    expect(html("/parent/children/c1")).toContain("inset_0_0_0_1.5px")
  })
  it("loading holds space, hidden from assistive tech, with no control", () => {
    state.value = { data: undefined, isPending: true }
    const out = html("/parent/children/c1")
    expect(out).toContain('aria-hidden="true"')
    expect(out).not.toContain("<select")
    expect(out).not.toContain("Amira")
  })
  it("error or an unknown child renders nothing", () => {
    state.value = { data: undefined, isPending: false }
    expect(html("/parent/children/c1")).toBe("")
    state.value = { data: { children: KIDS }, isPending: false }
    expect(html("/parent/children/zzz")).toBe("")
  })
})
