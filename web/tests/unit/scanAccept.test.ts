import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { SCAN_ACCEPT } from "@/lib/scanAccept"

/*
 * Final review, item 10 · The upload pickers offer only what the server takes.
 *
 * The server refuses every image format outside its allowlist
 * (`lemely/io/scan_limits.py` `SCAN_IMAGE_FORMATS`: JPEG, PNG, TIFF, WebP,
 * BMP), so `accept="application/pdf,image/*"` let a student or teacher pick a
 * GIF or HEIC only to have the upload refused. The pickers name the accepted
 * types instead, from one constant, and no upload input is left on
 * `image/*`.
 */

const screens = [
  ["src", "portals", "student", "screens", "CorrectPaper.tsx"],
  ["src", "portals", "teacher", "screens", "Grading.tsx"],
] as const

describe("SCAN_ACCEPT", () => {
  it("names PDF and the five allowlisted image types, and nothing else", () => {
    expect(SCAN_ACCEPT).toBe(
      "application/pdf,image/jpeg,image/png,image/tiff,image/webp,image/bmp",
    )
  })

  it.each(screens)("is the only accept list on the %s/%s/%s/%s/%s upload inputs", (...parts) => {
    const source = readFileSync(join(import.meta.dirname, "..", "..", ...parts), "utf8")
    expect(source).not.toContain("image/*")
    const accepts = [...source.matchAll(/accept=\{?([^\s>}]+)\}?/g)].map((match) => match[1])
    expect(accepts.length).toBeGreaterThan(0)
    for (const accept of accepts) expect(accept).toBe("SCAN_ACCEPT")
  })
})
