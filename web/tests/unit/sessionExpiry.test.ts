import { beforeEach, describe, expect, it, vi } from "vitest"
import { clearSession, markSessionExpired, peekSessionExpired, takeSessionExpired } from "@/lib/auth/storage"

/*
 * SHOULD-FIX 4 (adversarial review, PR 2) · the in-memory session-expiry
 * flag's lifecycle, pinned directly.
 *
 * `storage.ts` is importable under Node with no DOM (D3.20): `getDeviceId` /
 * `getSession` / `setSession` / `clearSession` touch `localStorage` only
 * inside their own function bodies, never at module scope, so importing the
 * module itself needs no stub. Calling `clearSession` in a test still does —
 * it touches `localStorage.removeItem` as part of dropping the session — so
 * every test below stubs a minimal in-memory implementation, the same shape
 * `sessionRefresh.test.ts` already uses for the identical reason.
 *
 * `markSessionExpired`/`takeSessionExpired`/`peekSessionExpired` hold their
 * state in module-level variables, not `localStorage` (see that file's own
 * doc comment on `expiredSignal` for why: a stale flag surfacing on a later
 * visit would be a lie). That means the flag persists across tests in this
 * file unless each one resets it, which `beforeEach` does below by taking
 * whatever a previous test (or this file's own import) left set.
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
  takeSessionExpired() // clear any flag a previous test left set
})

describe("markSessionExpired / peekSessionExpired / takeSessionExpired", () => {
  it("reports no expiry before anything has expired", () => {
    expect(peekSessionExpired()).toBe(false)
    expect(takeSessionExpired()).toEqual({ expired: false, role: undefined })
  })

  it("marks the flag and records the role it was given", () => {
    markSessionExpired("parent")
    expect(peekSessionExpired()).toBe(true)
    expect(takeSessionExpired()).toEqual({ expired: true, role: "parent" })
  })

  it("marks the flag with no role when the caller has none — api.ts's call shape", () => {
    // `role` is optional precisely so this still compiles and behaves as it
    // did before this fix: `lib/api.ts`'s silent-refresh-refusal path calls
    // `markSessionExpired()` bare (out of this PR's file scope to change —
    // see `storage.ts`'s own `expiredRole` doc comment).
    markSessionExpired()
    expect(peekSessionExpired()).toBe(true)
    expect(takeSessionExpired()).toEqual({ expired: true, role: undefined })
  })

  it("peek does not consume the flag — repeated peeks all still see it", () => {
    markSessionExpired("student")
    expect(peekSessionExpired()).toBe(true)
    expect(peekSessionExpired()).toBe(true)
    expect(peekSessionExpired()).toBe(true)
    // Still there for take, unconsumed by any of the three peeks above —
    // this is the exact property `RequireAuth` relies on to route a dead
    // session to /session-ended without deciding, on Login's/SessionEnded's
    // behalf, that the notice has been shown.
    expect(takeSessionExpired()).toEqual({ expired: true, role: "student" })
  })

  it("take consumes the flag — a later take or peek sees it cleared", () => {
    markSessionExpired("teacher")
    expect(takeSessionExpired()).toEqual({ expired: true, role: "teacher" })
    expect(peekSessionExpired()).toBe(false)
    expect(takeSessionExpired()).toEqual({ expired: false, role: undefined })
  })

  it("a fresh markSessionExpired overwrites a previously recorded role", () => {
    markSessionExpired("parent")
    markSessionExpired("platform_admin")
    expect(takeSessionExpired()).toEqual({ expired: true, role: "platform_admin" })
  })
})

describe("clearSession clears the expiry signal (SHOULD-FIX 4)", () => {
  it("a deliberate sign-out after an earlier expiry drops the stale flag", () => {
    // The exact scenario the finding describes: an earlier expiry left the
    // flag set, then the reader signs out on purpose in the same tab
    // (`clearSession()` is what a deliberate sign-out calls). The next
    // portal URL they open directly must not be told "you were signed out
    // to keep your account safe" for an expiry that is not why this
    // sign-out happened.
    markSessionExpired("student")
    expect(peekSessionExpired()).toBe(true)

    clearSession()

    expect(peekSessionExpired()).toBe(false)
    expect(takeSessionExpired()).toEqual({ expired: false, role: undefined })
  })

  it("clearSession with no prior expiry is a no-op on the flag", () => {
    clearSession()
    expect(peekSessionExpired()).toBe(false)
    expect(takeSessionExpired()).toEqual({ expired: false, role: undefined })
  })

  it("clearSession after an expiry it itself is recording (RequireAuth's own call order) still ends with the flag set", () => {
    // `RequireAuth` calls `clearSession()` and `markSessionExpired(role)`
    // together, in that order, for a session it just found stranded — this
    // pins that clearSession-then-mark (an expiry, not a sign-out) leaves
    // the flag set for the screen that is about to render, unlike a bare
    // clearSession on its own (the case above).
    clearSession()
    markSessionExpired("school_admin")
    expect(peekSessionExpired()).toBe(true)
    expect(takeSessionExpired()).toEqual({ expired: true, role: "school_admin" })
  })
})
