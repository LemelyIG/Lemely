import { beforeEach, describe, expect, it } from "vitest"
import {
  clearUploadQueue,
  drainUploadQueue,
  enqueueUpload,
  listQueuedUploads,
  markUploaded,
  removeQueued,
  type QueuedUpload,
  type UploadQueueAdapter,
} from "@/lib/offline/uploadQueue"

/**
 * Task 10 (B6b). Exercises the store against an injected in-memory
 * `idb-keyval`-shaped adapter — `uploadQueue.ts` takes `{ get, set, del,
 * keys }` with the real `idb-keyval` as its default, so nothing here touches
 * `indexedDB` at all (this suite runs under vitest's node environment, no
 * jsdom — see `vitest.config.ts`).
 */
function memoryStore(): UploadQueueAdapter {
  const backing = new Map<string, unknown>()
  return {
    get: async <T>(key: string) => backing.get(key) as T | undefined,
    set: async <T>(key: string, value: T) => {
      backing.set(key, value)
    },
    del: async (key: string) => {
      backing.delete(key)
    },
    keys: async () => [...backing.keys()],
  }
}

function baseEntry(id: string): Omit<QueuedUpload, "attempts" | "status"> {
  return {
    id,
    idempotencyKey: `key-${id}`,
    scan: new Blob(["scan-bytes"]),
    scanName: "scan.pdf",
    markScheme: null,
    createdAt: Date.now(),
  }
}

describe("uploadQueue store", () => {
  let store: UploadQueueAdapter

  beforeEach(() => {
    store = memoryStore()
  })

  it("enqueues an entry with attempts 0 and status queued", async () => {
    const entry = baseEntry("a")
    await enqueueUpload(entry, store)
    const listed = await listQueuedUploads(store)
    expect(listed).toEqual([{ ...entry, attempts: 0, status: "queued" }])
  })

  it("lists multiple entries", async () => {
    await enqueueUpload(baseEntry("a"), store)
    await enqueueUpload(baseEntry("b"), store)
    const listed = await listQueuedUploads(store)
    expect(listed.map((e) => e.id).sort()).toEqual(["a", "b"])
  })

  it("marks an entry uploaded with its paperId", async () => {
    await enqueueUpload(baseEntry("a"), store)
    await markUploaded("a", "paper-1", store)
    const [listed] = await listQueuedUploads(store)
    expect(listed).toMatchObject({ status: "uploaded", paperId: "paper-1" })
  })

  it("marking an absent entry uploaded is a no-op", async () => {
    await markUploaded("ghost", "paper-1", store)
    expect(await listQueuedUploads(store)).toEqual([])
  })

  it("removes a queued entry", async () => {
    await enqueueUpload(baseEntry("a"), store)
    await removeQueued("a", store)
    expect(await listQueuedUploads(store)).toEqual([])
  })

  it("clears every queued entry, leaving unrelated keys alone", async () => {
    await enqueueUpload(baseEntry("a"), store)
    await enqueueUpload(baseEntry("b"), store)
    await store.set("unrelated-key", "keep-me")
    await clearUploadQueue(store)
    expect(await listQueuedUploads(store)).toEqual([])
    expect(await store.get("unrelated-key")).toBe("keep-me")
  })
})

describe("drainUploadQueue", () => {
  let store: UploadQueueAdapter

  beforeEach(() => {
    store = memoryStore()
  })

  it("uploads a queued entry, corrects it, then removes it", async () => {
    await enqueueUpload(baseEntry("a"), store)
    const uploaded: string[] = []
    const corrected: string[] = []
    const result = await drainUploadQueue({
      store,
      upload: async (entry) => {
        uploaded.push(entry.id)
        return { paperId: "paper-a" }
      },
      correct: async (paperId) => {
        corrected.push(paperId)
      },
    })
    expect(uploaded).toEqual(["a"])
    expect(corrected).toEqual(["paper-a"])
    expect(result).toEqual({ drained: ["a"], failed: [] })
    expect(await listQueuedUploads(store)).toEqual([])
  })

  it("resumes an entry that already uploaded by calling correct only", async () => {
    await enqueueUpload(baseEntry("a"), store)
    await markUploaded("a", "paper-a", store)
    const uploadCalls: string[] = []
    const result = await drainUploadQueue({
      store,
      upload: async (entry) => {
        uploadCalls.push(entry.id)
        return { paperId: "should-not-happen" }
      },
      correct: async () => {},
    })
    expect(uploadCalls).toEqual([])
    expect(result.drained).toEqual(["a"])
  })

  it("bumps attempts and keeps the entry queued when upload fails", async () => {
    await enqueueUpload(baseEntry("a"), store)
    const result = await drainUploadQueue({
      store,
      upload: async () => {
        throw new Error("offline")
      },
      correct: async () => {},
    })
    expect(result).toEqual({ drained: [], failed: ["a"] })
    const [listed] = await listQueuedUploads(store)
    expect(listed.attempts).toBe(1)
    expect(listed.status).toBe("queued")
  })

  it("drops an entry older than 24h without attempting it", async () => {
    await enqueueUpload({ ...baseEntry("a"), createdAt: 0 }, store)
    let called = false
    const now = 25 * 60 * 60 * 1000
    const originalNow = Date.now
    Date.now = () => now
    try {
      const result = await drainUploadQueue({
        store,
        upload: async () => {
          called = true
          return { paperId: "x" }
        },
        correct: async () => {},
      })
      expect(called).toBe(false)
      expect(result).toEqual({ drained: [], failed: [] })
    } finally {
      Date.now = originalNow
    }
    expect(await listQueuedUploads(store)).toEqual([])
  })

  it("drops an entry that has already hit 5 attempts", async () => {
    await enqueueUpload(baseEntry("a"), store)
    await store.set("lemely-upload:a", { ...baseEntry("a"), attempts: 5, status: "queued" })
    const result = await drainUploadQueue({
      store,
      upload: async () => {
        throw new Error("should not be called")
      },
      correct: async () => {},
    })
    expect(result).toEqual({ drained: [], failed: [] })
    expect(await listQueuedUploads(store)).toEqual([])
  })

  it("drains multiple independent entries", async () => {
    await enqueueUpload(baseEntry("a"), store)
    await enqueueUpload(baseEntry("b"), store)
    const result = await drainUploadQueue({
      store,
      upload: async (entry) => ({ paperId: `paper-${entry.id}` }),
      correct: async () => {},
    })
    expect(result.drained.sort()).toEqual(["a", "b"])
    expect(await listQueuedUploads(store)).toEqual([])
  })
})
