import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

import { stripComments } from "./support/jsxSource"

/*
 * Task 11 (B6c) — source-text pins for the CorrectPaper chunk's
 * prefetch-on-intent wiring and its `pdf-lib` split.
 *
 * `vitest.config.ts` is Node, no jsdom (D3.20) — nothing that mounts
 * `StudentLayout`/`CameraCapture`/`CorrectPaper` is reachable from a unit
 * test here, so this pins the source text the way `navShells.test.ts` and
 * the other gate tests already do: the *shape* of the wiring, not a
 * rendered DOM.
 */

const SRC = fileURLToPath(new URL("../../src/", import.meta.url))

function read(relPath: string): string {
  return stripComments(readFileSync(join(SRC, relPath), "utf8"))
}

describe("portals/student/index.tsx prefetches CorrectPaper on intent", () => {
  const source = read("portals/student/index.tsx")

  it("defines a shared loadCorrectPaper loader", () => {
    expect(source).toMatch(/const\s+loadCorrectPaper\s*=\s*\(\)\s*=>\s*import\("\.\/screens\/CorrectPaper"\)/)
  })

  it("passes loadCorrectPaper to React.lazy", () => {
    expect(source).toMatch(/lazy\(\s*loadCorrectPaper\s*\)/)
  })

  it("wires loadCorrectPaper into prefetchOnIntent", () => {
    expect(source).toMatch(/prefetchOnIntent\(\s*loadCorrectPaper\s*\)/)
  })

  it("imports prefetchOnIntent from lib/prefetchOnIntent", () => {
    expect(source).toMatch(
      /import\s*\{[^}]*\bprefetchOnIntent\b[^}]*\}\s*from\s*"@\/lib\/prefetchOnIntent"/,
    )
  })
})

describe("pdf-lib is only ever reached through a dynamic import", () => {
  const files = ["components/CameraCapture.tsx", "portals/student/screens/CorrectPaper.tsx"]

  it.each(files)("%s has no static import from assemblePages", (file) => {
    const source = read(file)
    expect(source).not.toMatch(/^import\s*\{[^}]*assemblePagesToPdf[^}]*\}\s*from\s*"@\/lib\/pdf\/assemblePages"/m)
  })

  it.each(files)("%s dynamically imports assemblePages", (file) => {
    const source = read(file)
    expect(source).toMatch(/await\s+import\("@\/lib\/pdf\/assemblePages"\)/)
  })

  it.each(files)("%s has no static import naming pdf-lib itself", (file) => {
    const source = read(file)
    expect(source).not.toMatch(/^import[^\n]*from\s*"pdf-lib"/m)
  })
})

describe("check-bundle-budget.mjs default budget is 150KB (Phase B)", () => {
  const SCRIPTS = fileURLToPath(new URL("../../scripts/", import.meta.url))
  const source = readFileSync(join(SCRIPTS, "check-bundle-budget.mjs"), "utf8")

  it("DEFAULT_BUDGET_KB is 150", () => {
    expect(source).toMatch(/const\s+DEFAULT_BUDGET_KB\s*=\s*150/)
  })
})
