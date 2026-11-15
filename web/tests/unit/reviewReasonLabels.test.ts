import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { REASON_LABEL, reasonLabel } from "@/portals/teacher/screens/Review"

/** The backend's ReviewReason members, read from the enum itself so a new reason cannot ship unlabelled. */
const ENUMS = readFileSync(join(import.meta.dirname, "..", "..", "..", "lemely", "db", "models", "enums.py"), "utf8")
const block = ENUMS.slice(ENUMS.indexOf("class ReviewReason"))
const members = [...block.slice(0, block.search(/\nclass (?!ReviewReason)/)).matchAll(/^    ([a-z_]+) = "/gm)].map((m) => m[1])

describe("every review reason has reader-facing copy", () => {
  it("reads the enum", () => {
    expect(members).toContain("low_confidence")
    expect(members.length).toBeGreaterThanOrEqual(5)
  })
  it.each(members)("%s is labelled and never shown raw", (reason) => {
    expect(REASON_LABEL[reason], reason).toBeTruthy()
    expect(reasonLabel(reason)).not.toMatch(/_/)
  })
})
