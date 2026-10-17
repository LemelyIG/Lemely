import { readFileSync, readdirSync, statSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/*
 * C3e (Task 10): marketing cards turn the padding knob to `space-8` (32px),
 * matching DESIGN.md §12's note that marketing cards use the generous end of
 * §13's card-padding range rather than the in-app default (`p-6`, 24px).
 *
 * `DataHandling.tsx:79` was the one offender found by re-grepping
 * `<Card|lm-card` under `web/src/portals/marketing` (Landing.tsx has no
 * `<Card` usage at all — it was rebuilt on develop without one, exactly as
 * the plan warned it might be). This test scans the whole marketing portal
 * directory rather than pinning that one file, so a future `<Card
 * className="p-6">` anywhere under marketing fails the same way.
 */

const MARKETING_DIR = join(import.meta.dirname, "..", "..", "src", "portals", "marketing")

function sourceFiles(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) out.push(...sourceFiles(full))
    else if (entry.endsWith(".tsx") || entry.endsWith(".ts")) out.push(full)
  }
  return out.sort()
}

describe("marketing cards use the space-8 padding knob", () => {
  const files = sourceFiles(MARKETING_DIR)

  it("finds at least one source file to scan", () => {
    expect(files.length).toBeGreaterThan(0)
  })

  it("has no <Card className=\"p-6\"> under web/src/portals/marketing", () => {
    const offenders: string[] = []
    for (const file of files) {
      const text = readFileSync(file, "utf8")
      if (/<Card\s+className="p-6"/.test(text)) offenders.push(file)
    }
    expect(offenders).toEqual([])
  })

  it("DataHandling.tsx's not-yet-built panel Card uses p-8", () => {
    const text = readFileSync(join(MARKETING_DIR, "DataHandling.tsx"), "utf8")
    expect(text).toMatch(/<Card\s+className="p-8"/)
  })
})
