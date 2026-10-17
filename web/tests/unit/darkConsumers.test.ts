import { readFileSync, readdirSync } from "node:fs"
import { join, relative as pathRelative } from "node:path"
import { describe, expect, it } from "vitest"

/**
 * Task 14 (C5c): token-driven consumers actually stay token-driven once a
 * second theme exists.
 *
 * Three separate claims, three separate describe blocks:
 *
 *   1. `nivoTheme.ts` re-resolves its tokens when `data-theme` changes,
 *      rather than once at mount — a chart open across a theme toggle must
 *      not keep painting the old theme's colours. `chartTheme.test.ts` gates
 *      the *token names*; this file gates the *re-resolution mechanism*.
 *   2. The literal-colour sweep this phase's plan calls for
 *      (`rg -n "#[0-9a-fA-F]{6}|oklch\(|rgb\(" web/src -t tsx -t ts -g
 *      '!index.css'`), made repeatable instead of a one-off check — mirrors
 *      `chartTheme.test.ts`'s own "chart colours are never CSS variable
 *      strings" describe block: strip comments first (this file's own header
 *      and `Subject.tsx`'s history section both *discuss* `oklch()` in prose),
 *      then walk `src/` the way `chartTheme.test.ts`'s "every chart goes
 *      through the shared wrappers" describe block does.
 *   3. `audit.mjs` declares the five dark captures this phase's plan names,
 *      and `theme.spec.ts` no longer carries the `fixme` Task 13 left as a
 *      named placeholder for this task to fill in.
 */

const ROOT = join(import.meta.dirname, "..", "..")
const SRC = join(ROOT, "src")

function sourceOf(absolute: string): string {
  return readFileSync(absolute, "utf8")
}

function relativeTo(absolute: string): string {
  return pathRelative(ROOT, absolute).split("\\").join("/")
}

describe("nivoTheme re-resolves on theme change", () => {
  const source = sourceOf(join(SRC, "lib", "nivoTheme.ts"))

  it("watches document.documentElement for data-theme via a MutationObserver", () => {
    expect(source).toContain("MutationObserver")
    expect(source).toContain("data-theme")
  })
})

describe("literal-colour sweep: no hex/oklch/rgb/hsl literal outside index.css", () => {
  // The one permitted literal in a component source, carried over from
  // chartTheme.test.ts's own exception: the tooltip's ultra-diffuse shadow,
  // which §3.2 item 5 specifies as an opacity on black rather than as a
  // token.
  const PERMITTED = [/0 4px 16px rgba\(0,0,0,0\.05\)/g]

  function stripCommentsAndPermitted(code: string): string {
    let out = code.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "")
    for (const pattern of PERMITTED) out = out.replace(pattern, "")
    return out
  }

  const offenders: string[] = []

  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name)
      if (entry.isDirectory()) {
        walk(full)
        continue
      }
      if (!/\.tsx?$/.test(entry.name)) continue
      const code = stripCommentsAndPermitted(sourceOf(full))
      if (/#[0-9a-fA-F]{3,8}\b|\b(?:oklch|rgba?|hsla?)\s*\(/.test(code)) {
        offenders.push(relativeTo(full))
      }
    }
  }
  walk(SRC)

  it("finds none", () => {
    expect(offenders).toEqual([])
  })
})

describe("audit.mjs dark captures", () => {
  const source = sourceOf(join(ROOT, "scripts", "audit.mjs"))
  const slugs = [
    "student-overview-dark",
    "student-result-dark",
    "teacher-review-dark",
    "teacher-class-analytics-dark",
    "login-dark",
  ]

  it.each(slugs)("declares the %s dark slug", (slug) => {
    expect(source).toContain(slug)
  })

  it("emulates prefers-color-scheme via a colorScheme option, mirroring Task 11's media handling", () => {
    expect(source).toContain("colorScheme")
    expect(source).toContain("emulateMediaFeatures")
    expect(source).toContain("prefers-color-scheme")
  })
})

describe("theme.spec.ts carries no fixme", () => {
  const source = sourceOf(join(ROOT, "e2e", "theme.spec.ts"))

  it("has no fixme anywhere in the file", () => {
    expect(source).not.toMatch(/fixme/i)
  })
})
