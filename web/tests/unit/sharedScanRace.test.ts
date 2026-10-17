import { afterEach, describe, expect, it, vi } from "vitest"
import { installFileHandlerBridge, readSharedScan } from "@/lib/sharedScan"

/*
 * A6 review follow-up (FIX 1) · the file-handler stash/read race.
 *
 * `installFileHandlerBridge`'s `launchQueue` consumer stashes a launched
 * file through several async hops (`getFile()` -> `caches.open` ->
 * `cache.put`, real production code — `stashSharedFile` in
 * `src/sw/shareTarget.ts`) that a multi-MB photo makes non-trivial. Nothing
 * used to synchronize that with `CorrectPaper.tsx`'s `readSharedScan()` on
 * mount — both are independent async flows kicked off around the same
 * moment (the OS launch, and React's own render of `/file-handler` ->
 * `Navigate` -> `RequireAuth` -> `CorrectPaper`), so a reader that ran first
 * found nothing in the cache and the launched file was silently dropped
 * with no retry.
 *
 * This constructs that exact ordering: fire the launch consumer, then
 * immediately (same tick, before the stash's `getFile()` has even resolved)
 * call `readSharedScan()`, and prove it still returns the file rather than
 * racing past an empty cache. The ordering is deterministic, not a timing
 * gamble: `readSharedScan`'s own pre-fix path (`caches.open` then
 * `cache.match`, two hops) is strictly shorter than the stash's
 * (`getFile().then` then `caches.open` then `cache.put`, three-plus hops)
 * and starts strictly earlier, so on unpatched code it reliably wins the
 * microtask race every run.
 */

/** A promise this test resolves by hand, to control exactly when
 * `getFile()` "completes" relative to `readSharedScan()`'s own call. */
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

/** One in-memory Cache Storage entry, shared between the stash half
 * (`stashSharedFile`, real production code) and the read half
 * (`readSharedScan`) exactly like the real `caches.open(SHARE_CACHE)` does —
 * both resolve to the SAME object. */
function stubSharedCache() {
  const store = new Map<string, Response>()
  const cache = {
    put: vi.fn(async (key: string, response: Response) => {
      store.set(key, response)
    }),
    match: vi.fn(async (key: string) => store.get(key)),
    delete: vi.fn(async (key: string) => store.delete(key)),
  }
  vi.stubGlobal("caches", { open: vi.fn().mockResolvedValue(cache) })
  return cache
}

/** Captures the `launchQueue` consumer `installFileHandlerBridge` registers
 * on `window`, so the test can invoke it directly — the same "no real
 * browser API, no problem" approach `sharedScanConsumer.test.ts` takes for
 * `caches`. `window` is not a Node global under this suite's
 * `environment: "node"` (`vitest.config.ts`), so it has to be stubbed too. */
function stubLaunchQueue() {
  let consumer: ((params: LaunchParams) => void) | null = null
  vi.stubGlobal("window", {
    launchQueue: {
      setConsumer: (cb: (params: LaunchParams) => void) => {
        consumer = cb
      },
    },
  })
  return {
    fire: (params: LaunchParams) => {
      if (!consumer) throw new Error("installFileHandlerBridge did not register a consumer")
      consumer(params)
    },
  }
}

function fakeFileHandle(getFile: () => Promise<File>): FileSystemHandle {
  return { kind: "file", getFile } as unknown as FileSystemHandle
}

describe("the launch-then-immediate-read race (A6 follow-up FIX 1)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("readSharedScan waits for an in-flight stash instead of racing past an empty cache", async () => {
    stubSharedCache()
    const launchQueue = stubLaunchQueue()
    installFileHandlerBridge()

    const getFile = deferred<File>()
    launchQueue.fire({
      targetURL: "https://lemely.example/file-handler",
      files: [fakeFileHandle(() => getFile.promise)],
    })

    // Fires in the SAME tick the launch consumer ran in — before `getFile()`
    // has resolved, let alone `cache.put` — which is exactly the ordering
    // that dropped the file pre-fix.
    const readPromise = readSharedScan()

    getFile.resolve(new File(["fake image bytes"], "scan.jpg", { type: "image/jpeg" }))

    const file = await readPromise
    expect(file).not.toBeNull()
    expect(file?.name).toBe("scan.jpg")
    expect(file?.type).toBe("image/jpeg")
  })
})
