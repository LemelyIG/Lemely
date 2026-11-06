import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { ShellTree } from "@/components/shell/ShellTree"
import { initialOpenIds, openOnNavigate, toggleOpen } from "@/components/shell/shellTree"

const ROWS = ["0580", "0606", "0625"]

describe("initialOpenIds", () => {
  it("opens the current route's row", () => {
    expect([...initialOpenIds(ROWS, "0606")]).toEqual(["0606"])
  })
  it("falls back to the fallback row when the route matches none", () => {
    expect([...initialOpenIds(ROWS, null, "0625")]).toEqual(["0625"])
    expect([...initialOpenIds(ROWS, "9999", "0625")]).toEqual(["0625"])
  })
  it("opens nothing when neither matches", () => {
    expect([...initialOpenIds(ROWS, null)]).toEqual([])
    expect([...initialOpenIds(ROWS, null, "9999")]).toEqual([])
  })
})

describe("toggleOpen (design A: each subject is its own disclosure)", () => {
  it("opens a closed row and keeps the others", () => {
    expect([...toggleOpen(new Set(["0580"]), "0606")].sort()).toEqual(["0580", "0606"])
  })
  it("closes an open row", () => {
    expect([...toggleOpen(new Set(["0580", "0606"]), "0580")]).toEqual(["0606"])
  })
  it("does not mutate its input", () => {
    const open = new Set(["0580"])
    toggleOpen(open, "0580")
    expect([...open]).toEqual(["0580"])
  })
})

describe("openOnNavigate", () => {
  it("opens the row the reader navigated into, without closing others", () => {
    expect([...openOnNavigate(new Set(["0580"]), "0625")].sort()).toEqual(["0580", "0625"])
  })
  it("never closes a row when the route leaves the subjects", () => {
    expect([...openOnNavigate(new Set(["0580"]), null)]).toEqual(["0580"])
  })
})

describe("ShellTree markup", () => {
  const rows = [
    {
      id: "0580",
      label: "Mathematics",
      title: "Mathematics · 0580",
      trailing: "0580",
      children: [{ id: "p", label: "Practice", to: "/student/practice/0580", icon: null }],
    },
    {
      id: "0606",
      label: "Add Maths",
      trailing: "0606",
      children: [{ id: "q", label: "Practice", to: "/student/practice/0606", icon: null }],
    },
  ]
  const html = renderToStaticMarkup(
    createElement(
      MemoryRouter,
      { initialEntries: ["/student/practice/0606"] },
      createElement(ShellTree, { labelledBy: "subj-h", rows, currentId: "0606" }),
    ),
  )

  it("labels the list by the group heading", () => {
    expect(html).toContain('aria-labelledby="subj-h"')
  })
  it("renders each row as a button that controls its own sub-list", () => {
    const buttons = html.match(/<button[^>]*>/g) ?? []
    expect(buttons).toHaveLength(2)
    for (const b of buttons) {
      expect(b).toContain('type="button"')
      expect(b).toMatch(/aria-controls="[^"]+"/)
    }
  })
  it("starts the current route's row expanded and the others collapsed (hidden sub-list)", () => {
    expect(html).toMatch(/aria-expanded="false"[^>]*title="Mathematics · 0580"|title="Mathematics · 0580"[^>]*aria-expanded="false"/)
    expect(html).toMatch(/<ul[^>]*hidden=""[^>]*>[\s\S]*?\/student\/practice\/0580/)
    expect(html).toContain('aria-expanded="true"')
  })
  it("renders the empty message when there are no rows", () => {
    const empty = renderToStaticMarkup(
      createElement(
        MemoryRouter,
        null,
        createElement(ShellTree, { labelledBy: "h", rows: [], currentId: null, empty: "Nothing here yet." }),
      ),
    )
    expect(empty).toContain("Nothing here yet.")
    expect(empty).not.toContain("<button")
  })
})
