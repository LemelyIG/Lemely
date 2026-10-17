import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/*
 * Task 5 (B4a) · these hooks share `useDragGesture`'s rule (its own header
 * comment, `lib/gestures/useDragGesture.ts`): a drag/press fires many times a
 * frame, so every transient pointer coordinate lives in a ref, never
 * `useState` — re-rendering the component on each pointermove is exactly the
 * class of thing `react-best-practices` (`rerender-use-ref-transient-values`)
 * exists to prevent. None of these hooks are mountable under this suite's
 * DOM-less Node environment (`vitest.config.ts`, D3.20), so the rule is
 * pinned as a source-text gate instead — same reasoning as
 * `routeErrorWiring.test.ts`.
 */

const ROOT = join(import.meta.dirname, "..", "..")

const FILES = [
  "src/lib/gestures/useDragGesture.ts",
  "src/lib/gestures/usePullToRefresh.ts",
  "src/lib/gestures/useLongPress.ts",
]

function readSource(relativePath: string): string {
  return readFileSync(join(ROOT, relativePath), "utf8")
}

describe("gesture hooks keep transient pointer coordinates out of useState", () => {
  it.each(FILES)("%s has no useState of a coordinate value", (relativePath) => {
    const source = readSource(relativePath)
    const matches = source.match(/useState[^\n]*\b(dx|dy|startX|startY)\b/g) ?? []
    expect(matches).toEqual([])
  })

  it.each(FILES)("%s uses useRef for its transient state", (relativePath) => {
    const source = readSource(relativePath)
    expect(source).toContain("useRef")
  })
})
