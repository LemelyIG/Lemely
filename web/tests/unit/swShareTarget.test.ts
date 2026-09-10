import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  SHARE_CACHE,
  SHARE_KEY,
  handleShareTargetFetch,
  type ShareTargetFetchEvent,
} from "../../src/sw/shareTarget.ts"

/**
 * Packet A6 — the Web Share Target POST handler.
 *
 * `handleShareTargetFetch` takes a `ShareTargetFetchEvent` (just `.request`),
 * not the real global `FetchEvent`: the real type is WebWorker-only and this
 * test runs under `vitest.config.ts`'s `environment: "node"` (no WebWorker
 * lib), so a fake object with the one member the handler actually reads is
 * how it stays testable without a real service worker. `caches` is not a
 * Node global either (it's a browser/worker Cache Storage API), so it is
 * stubbed here the same way.
 */

function fakeRequest(file: File | null): Request {
  const form = new FormData()
  if (file) form.set("scan", file)
  return new Request("https://lemely.test/share-target", { method: "POST", body: form })
}

describe("handleShareTargetFetch", () => {
  let put: ReturnType<typeof vi.fn>
  let match: ReturnType<typeof vi.fn>
  let open: ReturnType<typeof vi.fn>

  beforeEach(() => {
    put = vi.fn().mockResolvedValue(undefined)
    match = vi.fn().mockResolvedValue(undefined)
    open = vi.fn().mockResolvedValue({ put, match })
    vi.stubGlobal("caches", { open })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("stashes the shared file into the SHARE_CACHE cache under SHARE_KEY", async () => {
    const file = new File(["fake image bytes"], "scan.jpg", { type: "image/jpeg" })
    const event: ShareTargetFetchEvent = { request: fakeRequest(file) }

    await handleShareTargetFetch(event)

    expect(open).toHaveBeenCalledWith(SHARE_CACHE)
    expect(put).toHaveBeenCalledTimes(1)
    const [key, stashed] = put.mock.calls[0] as [string, Response]
    expect(key).toBe(SHARE_KEY)
    expect(stashed.headers.get("content-type")).toBe("image/jpeg")
    expect(stashed.headers.get("x-shared-name")).toBe("scan.jpg")
    expect(stashed.headers.get("x-shared-at")).not.toBeNull()
    // A real ISO-8601 timestamp, not just "some string".
    expect(new Date(stashed.headers.get("x-shared-at") ?? "").toString()).not.toBe("Invalid Date")
  })

  it("returns a 303 redirect to /student/correct", async () => {
    const file = new File(["x"], "scan.png", { type: "image/png" })
    const event: ShareTargetFetchEvent = { request: fakeRequest(file) }

    const response = await handleShareTargetFetch(event)

    expect(response.status).toBe(303)
    expect(new URL(response.headers.get("location") ?? "", "https://lemely.test").pathname).toBe(
      "/student/correct",
    )
  })

  it("still redirects, without stashing, when the form carries no file", async () => {
    const event: ShareTargetFetchEvent = { request: fakeRequest(null) }

    const response = await handleShareTargetFetch(event)

    expect(put).not.toHaveBeenCalled()
    expect(response.status).toBe(303)
  })
})
