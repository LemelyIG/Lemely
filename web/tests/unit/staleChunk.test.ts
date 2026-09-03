import { describe, expect, it } from "vitest"
import {
  isChunkLoadError,
  StaleChunkGuard,
  type ChunkGuardStorage,
} from "@/lib/staleChunk"

/*
 * PR 2 part C (stale-chunk recovery), pinned.
 *
 * `installStaleChunkReload`/`handleChunkError`'s side-effecting halves
 * (`window.addEventListener`, `location.reload()`) are deliberately not
 * exercised here — this suite runs under Node with no DOM
 * (`vitest.config.ts`, D3.20). Everything worth pinning is reachable
 * through the two pure/injectable pieces this module is split for exactly
 * that reason: the classifier (`isChunkLoadError`) and the guard
 * (`StaleChunkGuard`, storage injected).
 */

describe("isChunkLoadError", () => {
  it.each([
    ["Chromium's failed module fetch", "Failed to fetch dynamically imported module: https://x/y.js"],
    ["Firefox's failed module script", "Importing a module script failed"],
    ["Safari's failed module load", "error loading dynamically imported module"],
    ["Vite's failed CSS preload", "Unable to preload CSS for /assets/y.css"],
  ])("recognises %s", (_label, message) => {
    expect(isChunkLoadError(new Error(message))).toBe(true)
  })

  it("matches case-insensitively", () => {
    expect(isChunkLoadError(new Error("FAILED TO FETCH DYNAMICALLY IMPORTED MODULE"))).toBe(true)
  })

  it("recognises a TypeError whose message mentions 'dynamically imported module' but isn't one of the four pinned phrases", () => {
    const error = new TypeError("dynamically imported module 'x' rejected")
    expect(isChunkLoadError(error)).toBe(true)
  })

  it("does not recognise a plain (non-TypeError) Error mentioning the same phrase loosely", () => {
    // Only a TypeError gets the broad "mentions the phrase" net; every other
    // Error subclass must match one of the four pinned phrases exactly.
    const error = new RangeError("something about a dynamically imported module, but not that shape")
    expect(isChunkLoadError(error)).toBe(false)
  })

  it("returns false for an ordinary application error", () => {
    expect(isChunkLoadError(new Error("subject fetch failed"))).toBe(false)
  })

  it.each([
    ["a string", "just a string"],
    ["a number", 42],
    ["a plain object", { code: "E_BAD" }],
    ["undefined", undefined],
    ["null", null],
  ])("returns false for a non-Error, non-string throwable (%s)", (_label, thrown) => {
    expect(isChunkLoadError(thrown)).toBe(false)
  })

  it("returns true for a bare string that matches a pinned phrase", () => {
    expect(isChunkLoadError("Failed to fetch dynamically imported module")).toBe(true)
  })
})

/** A minimal, throwing-on-demand fake of the storage slice `StaleChunkGuard`
 * needs, so the guard's own defensiveness (storage failures treated as
 * "unset") is pinned without touching a real `localStorage`. */
function fakeStorage(opts: { throwing?: boolean } = {}): ChunkGuardStorage {
  const data = new Map<string, string>()
  if (opts.throwing) {
    return {
      getItem: () => {
        throw new Error("storage unavailable")
      },
      setItem: () => {
        throw new Error("storage unavailable")
      },
      removeItem: () => {
        throw new Error("storage unavailable")
      },
    }
  }
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => {
      data.set(key, value)
    },
    removeItem: (key: string) => {
      data.delete(key)
    },
  }
}

describe("StaleChunkGuard.tryReload", () => {
  it("reloads on the first call for a build", () => {
    const guard = new StaleChunkGuard(fakeStorage())
    expect(guard.tryReload("build-a")).toBe(true)
  })

  it("refuses a second call for the same build (the loop guard)", () => {
    const guard = new StaleChunkGuard(fakeStorage())
    expect(guard.tryReload("build-a")).toBe(true)
    expect(guard.tryReload("build-a")).toBe(false)
  })

  it("reloads again once a new build id shows up", () => {
    const guard = new StaleChunkGuard(fakeStorage())
    expect(guard.tryReload("build-a")).toBe(true)
    expect(guard.tryReload("build-a")).toBe(false)
    expect(guard.tryReload("build-b")).toBe(true)
  })

  it("treats a throwing storage as unset — every call succeeds rather than throwing", () => {
    const guard = new StaleChunkGuard(fakeStorage({ throwing: true }))
    expect(guard.tryReload("build-a")).toBe(true)
    // A real storage would remember "build-a" was already tried; a throwing
    // one can't persist anything, so the guard degrades to "always allow"
    // rather than failing outright.
    expect(guard.tryReload("build-a")).toBe(true)
  })
})

describe("StaleChunkGuard.canReload", () => {
  it("agrees with tryReload's own guard decision without writing anything", () => {
    const storage = fakeStorage()
    const guard = new StaleChunkGuard(storage)
    expect(guard.canReload("build-a")).toBe(true)
    // A pure read: calling it repeatedly must never itself consume the guard.
    expect(guard.canReload("build-a")).toBe(true)
    expect(guard.canReload("build-a")).toBe(true)

    expect(guard.tryReload("build-a")).toBe(true)
    expect(guard.canReload("build-a")).toBe(false)
    expect(guard.canReload("build-a")).toBe(false)
  })

  it("treats a throwing storage as unset, same as tryReload", () => {
    const guard = new StaleChunkGuard(fakeStorage({ throwing: true }))
    expect(guard.canReload("build-a")).toBe(true)
  })
})

describe('StaleChunkGuard and the "dev" build id (SHOULD-FIX 8)', () => {
  it("is not permanently poisoned by a single reload — the same guard can reload for \"dev\" again once bounded per instance is respected", () => {
    // Before the fix, `tryReload("dev")` behaved exactly like any other
    // build id: it wrote RELOAD_KEY = "dev" to storage and every later call
    // on that origin — including a fresh page load in a fresh `vite dev`
    // session, since the id never changes — read that same key back and
    // refused forever.
    const storage = fakeStorage()
    const guard = new StaleChunkGuard(storage)
    expect(guard.tryReload("dev")).toBe(true)

    // The bound is per guard instance ("this page load"), not per persisted
    // key: a fresh instance over the SAME storage (simulating the reload
    // that just happened landing on a fresh JS context) is allowed again.
    const guardAfterReload = new StaleChunkGuard(storage)
    expect(guardAfterReload.canReload("dev")).toBe(true)
    expect(guardAfterReload.tryReload("dev")).toBe(true)
  })

  it("is still bounded to once per page load — a second dev chunk failure on the SAME instance is refused", () => {
    const guard = new StaleChunkGuard(fakeStorage())
    expect(guard.tryReload("dev")).toBe(true)
    expect(guard.tryReload("dev")).toBe(false)
    expect(guard.canReload("dev")).toBe(false)
  })

  it("never persists RELOAD_KEY for the dev build id, unlike a real build id", () => {
    const storage = fakeStorage()
    const guard = new StaleChunkGuard(storage)
    expect(guard.tryReload("dev")).toBe(true)
    // A guard reading the same storage for a REAL build id must not see
    // itself as already-spent because of the dev reload above — proof that
    // RELOAD_KEY was never written to "dev" in the first place.
    const otherGuard = new StaleChunkGuard(storage)
    expect(otherGuard.canReload("build-a")).toBe(true)
    expect(otherGuard.tryReload("build-a")).toBe(true)
  })

  it("recovers from storage that was already poisoned by the pre-fix behaviour", () => {
    // Simulates a browser profile that hit the old bug and has
    // RELOAD_KEY = "dev" sitting in real localStorage already — the fixed
    // guard must not defer to that stale value for the dev id at all.
    const storage = fakeStorage()
    storage.setItem("lemely:stale-chunk-reload", "dev")
    const guard = new StaleChunkGuard(storage)
    expect(guard.canReload("dev")).toBe(true)
    expect(guard.tryReload("dev")).toBe(true)
  })
})

describe("StaleChunkGuard.consumeReloadNotice", () => {
  it("returns false when no reload is pending", () => {
    const guard = new StaleChunkGuard(fakeStorage())
    expect(guard.consumeReloadNotice("build-b")).toBe(false)
  })

  it("returns true exactly once after a reload this guard caused, given the new build id", () => {
    const guard = new StaleChunkGuard(fakeStorage())
    expect(guard.tryReload("build-a")).toBe(true)
    // The realistic flow: the reload lands on a genuinely different build.
    expect(guard.consumeReloadNotice("build-b")).toBe(true)
    expect(guard.consumeReloadNotice("build-b")).toBe(false)
  })

  it("does not announce an update when the reload lands back on the same build id (nothing actually changed)", () => {
    const guard = new StaleChunkGuard(fakeStorage())
    expect(guard.tryReload("build-a")).toBe(true)
    expect(guard.consumeReloadNotice("build-a")).toBe(false)
    // Still consumed, even though it read as "no announcement" — a later
    // check must not resurrect it.
    expect(guard.consumeReloadNotice("build-b")).toBe(false)
  })

  it("treats a throwing storage as unset — never throws, always reports nothing pending", () => {
    const guard = new StaleChunkGuard(fakeStorage({ throwing: true }))
    expect(guard.consumeReloadNotice("build-a")).toBe(false)
  })

  describe("SHOULD-FIX 8: clears the reload guard on a confirmed recovery", () => {
    it("clears RELOAD_KEY once the build id has genuinely changed, so a later distinct failure isn't blocked by stale state", () => {
      const storage = fakeStorage()
      const guard = new StaleChunkGuard(storage)
      expect(guard.tryReload("build-a")).toBe(true)
      expect(guard.canReload("build-a")).toBe(false) // still guarded, pre-recovery

      expect(guard.consumeReloadNotice("build-b")).toBe(true) // recovered: build-a -> build-b

      // A fresh guard instance over the same storage (a later page load) is
      // no longer blocked for build-a — the recovery cleared it.
      const later = new StaleChunkGuard(storage)
      expect(later.canReload("build-a")).toBe(true)
    })

    it("leaves RELOAD_KEY alone when the reload did NOT recover (same build id both times)", () => {
      const storage = fakeStorage()
      const guard = new StaleChunkGuard(storage)
      expect(guard.tryReload("build-a")).toBe(true)
      expect(guard.consumeReloadNotice("build-a")).toBe(false) // not recovered

      // build-a is still guarded — a still-broken build must keep failing
      // through to the "new version" screen, not loop.
      const later = new StaleChunkGuard(storage)
      expect(later.canReload("build-a")).toBe(false)
    })
  })
})
