import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * Task 1 (C1a) · `BrandLockup` replaces seven hand-rolled "mark + wordmark"
 * copies scattered across the portal shells (`x-brandlockup-duplicated-5x` —
 * the ledger's count was wrong; the real count, re-verified in Task 0, is
 * seven). Source-text pins only: D3.20 forbids jsdom/`.test.tsx`, so this
 * cannot render the component and inspect the DOM — it reads the files the
 * way the other kit-migration tests do (`screenEntrance.test.ts`).
 */

const ROOT = join(process.cwd())

function sourceOf(relativePath: string): string {
  return stripComments(readFileSync(join(ROOT, relativePath), "utf8"))
}

const BRAND_LOCKUP_FILE = "src/components/ui/brand-lockup.tsx"

const LOCKUP_SITES = [
  "src/portals/student/index.tsx",
  "src/portals/teacher/index.tsx",
  "src/portals/parent/index.tsx",
  "src/portals/admin/index.tsx",
  "src/portals/settings/SettingsFrame.tsx",
  "src/portals/auth/Login.tsx",
  "src/portals/marketing/MarketingHeader.tsx",
  "src/portals/marketing/MarketingFooter.tsx",
] as const

describe("brand-lockup.tsx", () => {
  const source = sourceOf(BRAND_LOCKUP_FILE)

  it("exports BrandLockup", () => {
    expect(source).toContain("export function BrandLockup")
  })

  it("marks the mark aria-hidden", () => {
    // The wordmark beside it already says "Lemely" — describing the mark too
    // would make a screen reader announce the brand twice.
    expect(source).toContain('aria-hidden="true"')
  })

  it("renders both wordmark casings", () => {
    expect(source).toContain('"Lemely"')
    expect(source).toContain('"lemely"')
  })

  it("draws the Clip Letters wordmark inline", () => {
    // v5: the notebook BrandMark is retired; the lockup carries its own clip SVG
    // (DESIGN.md "Logo: Clip Letters") and renders no BrandMark component.
    expect(source).toContain("wordmark-letters")
    expect(source).toContain('viewBox="28 4 46 94"')
    expect(source).not.toContain("<BrandMark")
  })
})

describe("portal lockups reuse the shared brand component", () => {
  it.each(LOCKUP_SITES)(
    "%s carries no raw <BrandMark",
    (relativePath) => {
      expect(sourceOf(relativePath)).not.toContain("<BrandMark")
    },
  )
})

describe("every lockup site renders <BrandLockup", () => {
  it.each(LOCKUP_SITES)("%s", (relativePath) => {
    expect(sourceOf(relativePath)).toContain("<BrandLockup")
  })
})
