import { readFileSync } from "node:fs"
import { join } from "node:path"
import { afterEach, describe, expect, it } from "vitest"
import { getUnsubmittedScanSnapshot, setHasUnsubmittedScan } from "../../src/lib/activeScanGuard.ts"

/**
 * `readSharedScan()` (`sharedScan.ts`) deletes its Cache Storage entry as
 * part of reading it, so once read, a shared scan lives only in
 * `CorrectPaper.tsx`'s (or `Grading.tsx`'s) React state. `UpdateToast.tsx`'s
 * "Reload" action persists indefinitely (`duration: 0`) and, until this
 * guard, would call `applyUpdate()` unconditionally — reloading before the
 * reader submits loses the file with no recovery path. This module is the
 * shared flag those two sides read/write.
 */
describe("activeScanGuard", () => {
  afterEach(() => {
    setHasUnsubmittedScan(false)
  })

  it("defaults to false", () => {
    expect(getUnsubmittedScanSnapshot()).toBe(false)
  })

  it("reflects the most recently set value", () => {
    setHasUnsubmittedScan(true)
    expect(getUnsubmittedScanSnapshot()).toBe(true)

    setHasUnsubmittedScan(false)
    expect(getUnsubmittedScanSnapshot()).toBe(false)
  })
})

describe("activeScanGuard wiring (source-text gate — component rendering is out of scope, D3.20)", () => {
  const correctPaperSource = readFileSync(
    join(import.meta.dirname, "..", "..", "src", "portals", "student", "screens", "CorrectPaper.tsx"),
    "utf8",
  )
  const gradingSource = readFileSync(
    join(import.meta.dirname, "..", "..", "src", "portals", "teacher", "screens", "Grading.tsx"),
    "utf8",
  )
  const updateToastSource = readFileSync(
    join(import.meta.dirname, "..", "..", "src", "components", "UpdateToast.tsx"),
    "utf8",
  )

  it("CorrectPaper reports its scan to the guard", () => {
    expect(correctPaperSource).toMatch(/setHasUnsubmittedScan\(/)
  })

  it("Grading reports its scan to the guard", () => {
    expect(gradingSource).toMatch(/setHasUnsubmittedScan\(/)
  })

  it("Grading also picks up a shared/launched scan, same as CorrectPaper", () => {
    expect(gradingSource).toMatch(/readSharedScan\(/)
  })

  it("UpdateToast checks the guard before applying the update", () => {
    expect(updateToastSource).toMatch(/getUnsubmittedScanSnapshot\(/)
  })
})
