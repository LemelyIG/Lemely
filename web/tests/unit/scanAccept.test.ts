import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { SCAN_ACCEPT, SCHEME_ACCEPT } from "@/lib/scanAccept"

/*
 * Final review, item 10 and #276 item 3 · The upload pickers offer only what
 * the server takes.
 *
 * The server refuses every image format outside its allowlist
 * (`lemely/io/scan_limits.py` `SCAN_IMAGE_FORMATS`: JPEG, PNG, TIFF, WebP,
 * BMP), so `accept="application/pdf,image/*"` let a student or teacher pick a
 * GIF or HEIC only to have the upload refused. The pickers name the accepted
 * types instead, from one constant, and no upload input is left on
 * `image/*`.
 *
 * The mark scheme is narrower again: the server parses it as a PDF only
 * (`DeterministicMarkSchemeParser`), so the two scheme pickers take
 * `SCHEME_ACCEPT` and every other picker takes `SCAN_ACCEPT`.
 */

const screens = [
  ["src", "portals", "student", "screens", "CorrectPaper.tsx"],
  ["src", "portals", "teacher", "screens", "Grading.tsx"],
] as const

const schemeInputs = new Set(["scheme-file", "grading-scheme-file"])

const readScreen = (parts: readonly string[]) =>
  readFileSync(join(import.meta.dirname, "..", "..", ...parts), "utf8")

/** Each `<input` / `<FileDrop` opening tag's `id` and `accept` expression. */
const pickers = (source: string) =>
  [...source.matchAll(/<(?:input|FileDrop)\b[^>]*?>/gs)].map((tag) => ({
    id: /\bid="([^"]+)"/.exec(tag[0])?.[1],
    accept: /\baccept=\{?([^\s>}]+)\}?/.exec(tag[0])?.[1],
  }))

describe("SCAN_ACCEPT", () => {
  it("names PDF and the five allowlisted image types, and nothing else", () => {
    expect(SCAN_ACCEPT).toBe(
      "application/pdf,image/jpeg,image/png,image/tiff,image/webp,image/bmp",
    )
  })
})

describe("SCHEME_ACCEPT", () => {
  it("is PDF only, because the mark scheme is parsed as a PDF", () => {
    expect(SCHEME_ACCEPT).toBe("application/pdf")
  })
})

describe("upload pickers", () => {
  it.each(screens)("%s/%s/%s/%s/%s names its accept list from the constants", (...parts) => {
    const source = readScreen(parts)
    expect(source).not.toContain("image/*")
    const withAccept = pickers(source).filter((picker) => picker.accept !== undefined)
    expect(withAccept.length).toBeGreaterThan(0)
    for (const picker of withAccept) {
      const expected = schemeInputs.has(picker.id ?? "") ? "SCHEME_ACCEPT" : "SCAN_ACCEPT"
      expect(picker.accept, `picker ${picker.id}`).toBe(expected)
    }
  })

  it("covers both mark-scheme pickers", () => {
    const ids = screens.flatMap((parts) => pickers(readScreen(parts)).map((picker) => picker.id))
    for (const id of schemeInputs) expect(ids).toContain(id)
  })
})
