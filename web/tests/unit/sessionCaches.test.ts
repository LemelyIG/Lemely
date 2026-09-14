import { beforeEach, describe, expect, it, vi } from "vitest"
import { endSession, getSession, setSession } from "@/lib/auth/storage"

/*
 * H1/H2 (security review, offline/persistence work) — a shared device's
 * second sign-in must not inherit the first reader's persisted react-query
 * cache (H1: `queryPersister.ts`'s IndexedDB blob, keyed by a fixed,
 * not-user-scoped `"lemely-query-cache"`) or their still-queued exam scans
 * (H2: `uploadQueue.ts`'s IndexedDB store). `endSession` is the single
 * function every session-end path — `AuthContext.tsx`'s `logout`,
 * `RequireAuth.tsx`'s stranded-session redirect, and `api.ts`'s refused
 * silent refresh — now calls instead of the bare `clearSession()` each used
 * to call individually (only `logout` also remembered the upload queue;
 * nothing cleared the persisted query cache at all).
 *
 * Exercised here against injected fakes for the same reason `uploadQueue.ts`'s
 * own `UploadQueueAdapter`/`DrainUploadQueueDeps` are: the real caches reach
 * `indexedDB`, which this suite's Node environment (`vitest.config.ts`) does
 * not have.
 */

beforeEach(() => {
  const store = new Map<string, string>()
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value)
    },
    removeItem: (key: string) => {
      store.delete(key)
    },
  })
})

function fakeCaches() {
  return {
    clearQueries: vi.fn(),
    removePersistedQueries: vi.fn().mockResolvedValue(undefined),
    clearUploadQueue: vi.fn().mockResolvedValue(undefined),
  }
}

describe("endSession", () => {
  it("drops the persisted session, same as clearSession", () => {
    setSession({ accessToken: "t", refreshToken: "r", userId: "u", role: "student" })

    endSession(fakeCaches())

    expect(getSession()).toBeNull()
  })

  it("clears the in-memory query cache synchronously (H1)", () => {
    const caches = fakeCaches()

    endSession(caches)

    expect(caches.clearQueries).toHaveBeenCalledTimes(1)
  })

  it("removes the persisted IndexedDB query cache (H1)", () => {
    const caches = fakeCaches()

    endSession(caches)

    expect(caches.removePersistedQueries).toHaveBeenCalledTimes(1)
  })

  it("clears the offline upload queue's raw scan bytes (H2)", () => {
    const caches = fakeCaches()

    endSession(caches)

    expect(caches.clearUploadQueue).toHaveBeenCalledTimes(1)
  })

  it("does not wait on the async cache clears — fire-and-forget, like the pre-existing clearUploadQueue call", () => {
    let resolveRemove: () => void = () => {}
    const caches = {
      clearQueries: vi.fn(),
      removePersistedQueries: vi.fn(
        () => new Promise<void>((resolve) => (resolveRemove = resolve)),
      ),
      clearUploadQueue: vi.fn().mockResolvedValue(undefined),
    }

    // endSession() must return synchronously even though
    // removePersistedQueries's promise is still pending — nothing on any of
    // the three call sites (a sign-out click, a redirect render, a refused
    // refresh) should block on it.
    endSession(caches)

    expect(getSession()).toBeNull()
    resolveRemove()
  })
})
