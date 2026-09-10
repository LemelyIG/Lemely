import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { SHARE_CACHE, SHARE_KEY } from "../../src/sw/shareTarget.ts"
import { readSharedScan } from "../../src/lib/sharedScan.ts"

/**
 * Packet A6 — the page-context counterpart to `swShareTarget.test.ts`:
 * `readSharedScan` picks up what the worker's `handleShareTargetFetch`
 * stashed, once `CorrectPaper.tsx` mounts. `caches` is stubbed the same way
 * (not a Node global); no real service worker or cache storage involved.
 */

function stashedResponse(sharedAtIso: string): Response {
  return new Response(new Blob(["fake image bytes"], { type: "image/jpeg" }), {
    headers: {
      "content-type": "image/jpeg",
      "x-shared-name": "scan.jpg",
      "x-shared-at": sharedAtIso,
    },
  })
}

describe("readSharedScan", () => {
  let match: ReturnType<typeof vi.fn>
  let deleteEntry: ReturnType<typeof vi.fn>
  let open: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-01-01T12:00:00.000Z"))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  function stubCache(response: Response | undefined) {
    match = vi.fn().mockResolvedValue(response)
    deleteEntry = vi.fn().mockResolvedValue(true)
    open = vi.fn().mockResolvedValue({ match, delete: deleteEntry })
    vi.stubGlobal("caches", { open })
  }

  it("returns a File built from a fresh entry (within the 10-minute TTL)", async () => {
    stubCache(stashedResponse("2026-01-01T11:55:00.000Z")) // 5 minutes old

    const file = await readSharedScan()

    expect(open).toHaveBeenCalledWith(SHARE_CACHE)
    expect(match).toHaveBeenCalledWith(SHARE_KEY)
    expect(file).not.toBeNull()
    expect(file?.name).toBe("scan.jpg")
    expect(file?.type).toBe("image/jpeg")
  })

  it("consumes (deletes) the cache entry once read", async () => {
    stubCache(stashedResponse("2026-01-01T11:55:00.000Z"))

    await readSharedScan()

    expect(deleteEntry).toHaveBeenCalledWith(SHARE_KEY)
  })

  it("returns null and deletes the entry for one older than 10 minutes", async () => {
    stubCache(stashedResponse("2026-01-01T11:49:00.000Z")) // 11 minutes old

    const file = await readSharedScan()

    expect(file).toBeNull()
    expect(deleteEntry).toHaveBeenCalledWith(SHARE_KEY)
  })

  it("returns null without touching the cache when there is no entry at all", async () => {
    stubCache(undefined)

    const file = await readSharedScan()

    expect(file).toBeNull()
    expect(deleteEntry).not.toHaveBeenCalled()
  })
})
