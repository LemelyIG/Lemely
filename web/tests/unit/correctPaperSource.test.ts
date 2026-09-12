import { describe, expect, it } from "vitest"
import { defaultScanSource } from "@/lib/scanSource"

/*
 * A4 · Which scan source `CorrectPaper` opens to first.
 *
 * A coarse pointer (touch — phone, tablet) means the device the student is
 * holding almost certainly has a camera and the workflow this screen exists
 * for is "photograph the paper you just corrected on paper", so that device
 * opens straight to the camera. A fine pointer (mouse/trackpad — a laptop)
 * opens to file upload, the workflow that made sense before this existed.
 * `matchMedia` is optional here the same way it is at the real call site:
 * older engines and non-browser environments may not have it at all.
 */

describe("defaultScanSource", () => {
  it("opens to the camera on a coarse (touch) pointer", () => {
    const matchMedia = (query: string) => {
      expect(query).toBe("(pointer: coarse)")
      return { matches: true } as MediaQueryList
    }
    expect(defaultScanSource(matchMedia)).toBe("camera")
  })

  it("opens to file upload on a fine (mouse/trackpad) pointer", () => {
    const matchMedia = () => ({ matches: false }) as MediaQueryList
    expect(defaultScanSource(matchMedia)).toBe("file")
  })

  it("opens to file upload when matchMedia is unavailable", () => {
    expect(defaultScanSource(undefined)).toBe("file")
  })
})
