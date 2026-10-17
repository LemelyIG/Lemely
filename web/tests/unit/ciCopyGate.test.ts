import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/*
 * C4 (Task 11): CI runs the copy gate (`npm run check:copy`) on every push,
 * not just locally/on demand. Source-text assertion against the workflow
 * YAML — nothing about a GitHub Actions run is exercisable from this unit
 * runner.
 */

const ROOT = join(import.meta.dirname, "..", "..", "..")
const ciYml = readFileSync(join(ROOT, ".github/workflows/ci.yml"), "utf8")

describe("ci.yml web job", () => {
  it("runs the copy gate", () => {
    expect(ciYml).toMatch(/run:\s*npm run check:copy/)
  })

  it("runs the copy gate inside the web job (working-directory: web)", () => {
    const webJobMatch = ciYml.match(/\n  web:\n[\s\S]*/)
    expect(webJobMatch).not.toBeNull()
    expect(webJobMatch?.[0]).toMatch(/run:\s*npm run check:copy/)
  })
})
