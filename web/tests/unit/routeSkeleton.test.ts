import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { skeletonForMatches } from "@/components/ui/route-skeleton"
import { stripComments } from "./support/jsxSource"

/*
 * Packet B1 · route-declared skeletons (DESIGN.md §12).
 *
 * `RouteFallback` used to be the route-chunk fallback everywhere: a top-level
 * auth form got the same "generic content well" tier-2 skeleton a teacher
 * dashboard did, and `frame="standalone"` was something every call site had
 * to remember to pass rather than something the route table stated. Every
 * `<RouteSkeleton />` call site instead reads the shape off the deepest
 * matched route's `handle.skeleton` (`skeletonForMatches`, mirroring
 * `pageMetaFromMatches`'s own "deepest wins" walk), so a route that forgets to
 * declare one is a route this file's pairing checks catch, not a screen that
 * silently renders the wrong tier-2 shape.
 *
 * `ROOT` is `web/`, since `import.meta.dirname` here is `web/tests/unit`.
 */
const ROOT = join(import.meta.dirname, "..", "..")

describe("skeletonForMatches", () => {
  it("returns the deepest match's declared skeleton", () => {
    expect(
      skeletonForMatches([{ handle: { skeleton: "list" } }, { handle: { title: "x" } }]),
    ).toBe("list")
  })

  it("returns 'standalone' for an empty match chain", () => {
    expect(skeletonForMatches([])).toBe("standalone")
  })

  it("defaults to 'page-header' for a portal chain where nothing declares one", () => {
    expect(
      skeletonForMatches([{ handle: undefined }, { handle: { title: "x" } }]),
    ).toBe("page-header")
  })
})

/*
 * Every `handle:` block in the five route tables below is required to also
 * carry a `skeleton:` field. This is scoped to `handle:` blocks rather than
 * every `path:`/`index: true` token in the file: every route in these five
 * files that has a `path`/`index: true` already carries a `handle: { title:
 * ... }` (P6.5), so the two counts coincide for every route that actually
 * needs one — and scoping to `handle:` blocks, rather than a raw `path:` text
 * count, correctly skips route objects assembled via `{ ...someRoute, path:
 * "..." }` spreads (`routes.tsx`'s `/landing` and `/data`), whose own
 * `handle` — and so its `skeleton` — is declared once, at the spread's source
 * file, not re-declared at every place the object is spread into.
 */
function handleBlocks(source: string): string[] {
  const blocks: string[] = []
  const pattern = /handle:\s*\{/g
  let match: RegExpExecArray | null
  while ((match = pattern.exec(source))) {
    const braceStart = source.indexOf("{", match.index)
    let depth = 0
    let end = -1
    for (let i = braceStart; i < source.length; i++) {
      if (source[i] === "{") depth++
      else if (source[i] === "}") {
        depth--
        if (depth === 0) {
          end = i
          break
        }
      }
    }
    if (end === -1) continue
    blocks.push(source.slice(braceStart, end + 1))
  }
  return blocks
}

describe.each([
  "src/routes.tsx",
  "src/portals/student/index.tsx",
  "src/portals/teacher/index.tsx",
  "src/portals/parent/index.tsx",
  "src/portals/admin/index.tsx",
])("%s: every handle: block also declares skeleton:", (relPath) => {
  const source = stripComments(readFileSync(join(ROOT, relPath), "utf8"))
  const blocks = handleBlocks(source)

  it("has at least one handle: block", () => {
    expect(blocks.length).toBeGreaterThan(0)
  })

  it("has no handle: block missing skeleton:", () => {
    const missing = blocks.filter((block) => !block.includes("skeleton:"))
    expect(missing).toEqual([])
  })
})

describe("routes.tsx: zero <RouteFallback, at least 15 <RouteSkeleton", () => {
  const source = stripComments(readFileSync(join(ROOT, "src/routes.tsx"), "utf8"))

  it("has no <RouteFallback call site", () => {
    expect(source).not.toMatch(/<RouteFallback\b/)
  })

  it("has at least 15 <RouteSkeleton call sites", () => {
    const calls = source.match(/<RouteSkeleton\b/g) ?? []
    expect(calls.length).toBeGreaterThanOrEqual(15)
  })
})

describe("portal Outlet boundaries: no <RouteFallback left as a Suspense fallback", () => {
  it.each([
    "src/portals/student/index.tsx",
    "src/portals/teacher/index.tsx",
    "src/portals/admin/index.tsx",
    "src/portals/parent/index.tsx",
    "src/portals/marketing/index.tsx",
  ])("%s has no <RouteFallback call site", (relPath) => {
    const source = stripComments(readFileSync(join(ROOT, relPath), "utf8"))
    expect(source).not.toMatch(/<RouteFallback\b/)
  })
})

describe("state-views.tsx: the tier-2 wrapper is observable", () => {
  const source = readFileSync(join(ROOT, "src/components/ui/state-views.tsx"), "utf8")

  it('carries data-tier="skeleton"', () => {
    expect(source).toContain('data-tier="skeleton"')
  })
})
