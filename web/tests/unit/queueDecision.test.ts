import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import { nextQueueAction, shouldQueueUpload } from "@/lib/offline/queueDecision"
import type { QueuedUpload } from "@/lib/offline/uploadQueue"

/**
 * Task 10 (B6b) — pure offline-queue decision logic. Both functions are
 * intentionally dumb: `shouldQueueUpload` only ever sees the *shape* `lib/
 * api.ts` already normalises every transport failure into (`isOfflineFailure`'s
 * own contract — status 0 means "never reached the server"), and
 * `nextQueueAction` only ever sees a `QueuedUpload` record, never a live
 * network call.
 */
describe("shouldQueueUpload", () => {
  it("queues a genuine offline failure (ApiError status 0)", () => {
    expect(shouldQueueUpload(new ApiError(0, "Failed to fetch"))).toBe(true)
  })

  it("never queues a real 4xx from the server", () => {
    expect(shouldQueueUpload(new ApiError(422, "Malformed Idempotency-Key header"))).toBe(false)
  })

  it("never queues a real 5xx from the server", () => {
    expect(shouldQueueUpload(new ApiError(500, "Internal Server Error"))).toBe(false)
  })

  it("never queues a non-ApiError", () => {
    expect(shouldQueueUpload(new Error("boom"))).toBe(false)
    expect(shouldQueueUpload("boom")).toBe(false)
    expect(shouldQueueUpload(undefined)).toBe(false)
  })
})

function entry(overrides: Partial<QueuedUpload> = {}): QueuedUpload {
  return {
    id: "q1",
    idempotencyKey: "abc123",
    scan: new Blob(["x"]),
    scanName: "scan.pdf",
    markScheme: null,
    createdAt: 0,
    attempts: 0,
    status: "queued",
    ...overrides,
  }
}

const DAY_MS = 24 * 60 * 60 * 1000

describe("nextQueueAction", () => {
  it("uploads a fresh, never-attempted queued entry", () => {
    expect(nextQueueAction(entry(), 1000)).toBe("upload")
  })

  it("corrects an entry that already uploaded and has a paperId", () => {
    expect(nextQueueAction(entry({ status: "uploaded", paperId: "p1" }), 1000)).toBe("correct")
  })

  it("drops an entry older than 24h", () => {
    expect(nextQueueAction(entry({ createdAt: 0 }), DAY_MS + 1)).toBe("drop")
  })

  it("keeps an entry exactly at the 24h boundary", () => {
    expect(nextQueueAction(entry({ createdAt: 0 }), DAY_MS)).toBe("upload")
  })

  it("drops an entry that has hit 5 attempts", () => {
    expect(nextQueueAction(entry({ attempts: 5 }), 1000)).toBe("drop")
  })

  it("keeps an entry at 4 attempts", () => {
    expect(nextQueueAction(entry({ attempts: 4 }), 1000)).toBe("upload")
  })

  it("age drop takes priority over an uploaded-but-stale entry", () => {
    expect(
      nextQueueAction({ ...entry({ status: "uploaded", paperId: "p1" }), createdAt: 0 }, DAY_MS + 1),
    ).toBe("drop")
  })
})
