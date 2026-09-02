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
})
