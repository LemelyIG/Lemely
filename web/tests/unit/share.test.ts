import { describe, expect, it, vi } from "vitest"
import { canWebShare, shareResult } from "@/lib/share"

/*
 * Task 7 (B5a) · Web Share with an honest copy-link fallback.
 *
 * `PaperResult.tsx` has no result download to fall back to at `c70dd38d`, so
 * `shareResult` never fails silently: it shares when the platform can, copies
 * the link and toasts when it can't, and reports `"unavailable"` only when
 * neither exists — never a thrown rejection the caller has to guard against.
 */

const DATA = { url: "https://lemelyig.com/student/result/abc", title: "Result", text: "63/80" }

describe("canWebShare", () => {
  it("is true when share exists and canShare says yes", () => {
    expect(canWebShare(DATA, { share: vi.fn(), canShare: () => true })).toBe(true)
  })

  it("is false when canShare says no", () => {
    expect(canWebShare(DATA, { share: vi.fn(), canShare: () => false })).toBe(false)
  })

  it("is false when share is absent", () => {
    expect(canWebShare(DATA, {})).toBe(false)
  })

  it("is true when share exists with no canShare to consult", () => {
    expect(canWebShare(DATA, { share: vi.fn() })).toBe(true)
  })
})

describe("shareResult", () => {
  it("shares when the platform can", async () => {
    const share = vi.fn().mockResolvedValue(undefined)
    const outcome = await shareResult(DATA, { nav: { share, canShare: () => true } })
    expect(share).toHaveBeenCalledWith(DATA)
    expect(outcome).toBe("shared")
  })

  it("copies the link and toasts when share is absent", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    const toast = vi.fn()
    const outcome = await shareResult(DATA, {
      nav: { clipboard: { writeText } },
      toast,
    })
    expect(writeText).toHaveBeenCalledWith(DATA.url)
    expect(toast).toHaveBeenCalledWith("Link copied")
    expect(outcome).toBe("copied")
  })

  it("reports unavailable when neither share nor clipboard exist", async () => {
    const outcome = await shareResult(DATA, { nav: {} })
    expect(outcome).toBe("unavailable")
  })

  it("falls back to copy-link when a native share is cancelled", async () => {
    const share = vi.fn().mockRejectedValue(new DOMException("cancelled", "AbortError"))
    const writeText = vi.fn().mockResolvedValue(undefined)
    const outcome = await shareResult(DATA, {
      nav: { share, canShare: () => true, clipboard: { writeText } },
    })
    expect(writeText).toHaveBeenCalledWith(DATA.url)
    expect(outcome).toBe("copied")
  })
})
