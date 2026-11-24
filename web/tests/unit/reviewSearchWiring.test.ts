import { readFileSync } from "node:fs"
import { join } from "node:path"
import type { ReactElement } from "react"
import { describe, expect, it, vi } from "vitest"
import { EMPTY_FILTERS } from "@/lib/reviewQueueQuery"

/*
 * The `/` shortcut and Enter-to-search, wired through the kit `Input`.
 *
 * The runner has no DOM, so there is nothing to type into. Instead the hooks are stubbed (state is
 * frozen at its initial value, effects never run) so `FilterBar` and the kit `Input` can be called
 * as plain functions and the element trees they return inspected: that shows which ref lands on the
 * native `<input>` and what its Enter handler does. This is the only file that stubs `react`; it is
 * separate from the markup tests because server rendering needs the real hooks.
 */
vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>()
  return {
    ...actual,
    useState: (init: unknown) => [typeof init === "function" ? (init as () => unknown)() : init, () => {}],
    useEffect: () => {},
    useRef: () => ({ current: null }),
    useId: () => "id-1",
  }
})

const { FilterBar } = await import("@/portals/teacher/screens/review/FilterBar")
const { Input } = await import("@/components/ui/input")

const DIR = join(import.meta.dirname, "../../src/portals/teacher/screens/review")

function find(node: unknown, pred: (el: ReactElement) => boolean): ReactElement | null {
  if (!node || typeof node !== "object") return null
  if (Array.isArray(node)) {
    for (const n of node) {
      const hit = find(n, pred)
      if (hit) return hit
    }
    return null
  }
  const el = node as ReactElement<{ children?: unknown }>
  if (pred(el)) return el
  return find(el.props?.children, pred)
}

const props = (over: Partial<Parameters<typeof FilterBar>[0]> = {}) => ({
  filters: { ...EMPTY_FILTERS, q: "sample" },
  options: { classes: [], subjects: [], subjectName: (c: string) => c },
  shownLine: null,
  onSearch: vi.fn(),
  onSort: vi.fn(),
  onToggle: vi.fn(),
  onRemove: vi.fn(),
  searchRef: { current: null } as React.RefObject<HTMLInputElement | null>,
  ...over,
})

describe("review search wiring", () => {
  it("hands the screen's search ref to the kit Input", () => {
    const p = props()
    const tree = FilterBar(p) as ReactElement
    const input = find(tree, (el) => el.type === Input) as ReactElement<{ ref: unknown }>
    expect(input.props.ref).toBe(p.searchRef)
  })
  it("the kit Input forwards that ref to the native input, so focus() reaches it", () => {
    const ref = { current: null }
    const render = (Input as unknown as { render: (p: object, r: unknown) => ReactElement }).render
    const out = render({ label: "Search", type: "search" }, ref)
    const native = find(out, (el) => el.type === "input") as ReactElement & { ref?: unknown; props: { ref?: unknown } }
    expect(native.props.ref ?? native.ref).toBe(ref)
  })
  it("Enter searches the current text at once; other keys do not", () => {
    const p = props()
    const tree = FilterBar(p) as ReactElement
    const input = find(tree, (el) => el.type === Input) as ReactElement<{ onKeyDown: (e: { key: string }) => void }>
    input.props.onKeyDown({ key: "a" })
    expect(p.onSearch).not.toHaveBeenCalled()
    input.props.onKeyDown({ key: "Enter" })
    expect(p.onSearch).toHaveBeenCalledWith("sample")
  })
  it("`/` on the screen focuses the forwarded ref and swallows the key", () => {
    const src = readFileSync(join(DIR, "ReviewQueue.tsx"), "utf8")
    expect(src).toMatch(/e\.key === "\/"\) \{ e\.preventDefault\(\); searchRef\.current\?\.focus\(\)/)
    expect(src).toMatch(/searchRef=\{searchRef\}/)
  })
  it("does not hijack `/` typed into a field", () => {
    const src = readFileSync(join(DIR, "ReviewQueue.tsx"), "utf8")
    expect(src).toMatch(/\["INPUT", "TEXTAREA", "SELECT"\]\.includes\(t\.tagName\)/)
  })
})
