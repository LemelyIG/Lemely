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
  // `vite dev` never changes its build id, so "reloaded once for this id"
  // can never be reset by a deploy the way a real id's `RELOAD_KEY` is.
  // The dev id is bounded by a per-tab cooldown instead: one reload, then
  // none for `DEV_RELOAD_COOLDOWN_MS` (30 s), tracked in the per-tab storage
  // so it survives the reload it guards against and dies with the tab.
  const DEV_KEY = "lemely:stale-chunk-reload-dev"
  const clock = (start: number) => {
    let t = start
    return { now: () => t, advance: (ms: number) => (t += ms) }
  }

  it("cuts a fail-reload-fail chain on its second link — a fresh instance over the same per-tab storage is refused inside the cooldown", () => {
    const perTab = fakeStorage()
    const time = clock(1_000)
    const beforeReload = new StaleChunkGuard(fakeStorage(), { perTab, now: time.now })
    expect(beforeReload.tryReload("dev")).toBe(true)

    // The reload lands: a fresh JS context, a fresh guard, the same tab.
    time.advance(400)
    const afterReload = new StaleChunkGuard(fakeStorage(), { perTab, now: time.now })
    expect(afterReload.canReload("dev")).toBe(false)
    expect(afterReload.tryReload("dev")).toBe(false)
  })

  it("allows a later, unrelated dev chunk failure its own reload once the cooldown has passed", () => {
    const perTab = fakeStorage()
    const time = clock(1_000)
    const guard = new StaleChunkGuard(fakeStorage(), { perTab, now: time.now })
    expect(guard.tryReload("dev")).toBe(true)
    time.advance(29_999)
    expect(guard.canReload("dev")).toBe(false)
    time.advance(1)
    expect(guard.canReload("dev")).toBe(true)
    expect(guard.tryReload("dev")).toBe(true)
  })

  it("keeps the dev bound in the per-tab storage, never under RELOAD_KEY in the persistent one", () => {
    const storage = fakeStorage()
    const perTab = fakeStorage()
    const guard = new StaleChunkGuard(storage, { perTab, now: () => 5_000 })
    expect(guard.tryReload("dev")).toBe(true)
    expect(perTab.getItem(DEV_KEY)).toBe("5000")
    expect(storage.getItem(DEV_KEY)).toBeNull()
    expect(storage.getItem("lemely:stale-chunk-reload")).toBeNull()
    // A guard reading the same persistent storage for a REAL build id must
    // not see itself as already spent because of the dev reload above.
    const otherGuard = new StaleChunkGuard(storage)
    expect(otherGuard.canReload("build-a")).toBe(true)
    expect(otherGuard.tryReload("build-a")).toBe(true)
  })

  it("falls back to the persistent storage for the dev bound when no per-tab storage is supplied", () => {
    const storage = fakeStorage()
    const guard = new StaleChunkGuard(storage, { now: () => 5_000 })
    expect(guard.tryReload("dev")).toBe(true)
    expect(storage.getItem(DEV_KEY)).toBe("5000")
    expect(guard.canReload("dev")).toBe(false)
  })

  it("recovers from storage that was already poisoned by the pre-fix behaviour", () => {
    // Simulates a browser profile that hit the old bug and has
    // RELOAD_KEY = "dev" sitting in real localStorage already — the fixed
    // guard must not defer to that stale value for the dev id at all.
    const storage = fakeStorage()
    storage.setItem("lemely:stale-chunk-reload", "dev")
    const guard = new StaleChunkGuard(storage, { perTab: fakeStorage(), now: () => 1 })
    expect(guard.canReload("dev")).toBe(true)
    expect(guard.tryReload("dev")).toBe(true)
  })

  it("treats a malformed or throwing per-tab value as no recent reload", () => {
    const perTab = fakeStorage()
    perTab.setItem(DEV_KEY, "not-a-number")
    expect(new StaleChunkGuard(fakeStorage(), { perTab, now: () => 1 }).canReload("dev")).toBe(true)
    const throwing = new StaleChunkGuard(fakeStorage(), { perTab: fakeStorage({ throwing: true }), now: () => 1 })
    expect(throwing.canReload("dev")).toBe(true)
    expect(throwing.tryReload("dev")).toBe(true)
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
