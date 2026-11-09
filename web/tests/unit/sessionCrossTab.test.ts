import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { clearActingLead, getActingLead, setActingLead } from "@/lib/actingTeacher"
import {
  handleSessionStorageEvent,
  sessionUserIdOf,
  subscribeToSession,
  type SessionCaches,
} from "@/lib/auth/storage"

/*
 * Another tab signs a different person in (or out): this tab must stop acting for a lead, drop its
 * query cache, and tell the auth context. A token refresh (same user id) must do none of it.
 * `auth/storage` reaches `indexedDB` through the default caches, which this Node runner lacks, so the
 * same two modules `sessionRefresh.test.ts` mocks are mocked here and the caches are injected.
 */
vi.mock("@/lib/offline/queryPersister", () => ({ persister: { removeClient: () => Promise.resolve() } }))
vi.mock("@/lib/offline/uploadQueue", () => ({ clearUploadQueue: () => Promise.resolve() }))

const session = (userId: string, accessToken = "t") => JSON.stringify({ accessToken, refreshToken: null, userId, role: "teacher" })
const LEAD = { leadId: "11111111-1111-4111-8111-111111111111", leadName: "Mr Hassan" }

let caches: SessionCaches & Record<keyof SessionCaches, ReturnType<typeof vi.fn>>
let stored: string | null

beforeEach(() => {
  stored = null
  vi.stubGlobal("localStorage", { getItem: () => stored, setItem: () => {}, removeItem: () => {} })
  caches = {
    clearQueries: vi.fn(),
    removePersistedQueries: vi.fn(() => Promise.resolve()),
    clearUploadQueue: vi.fn(() => Promise.resolve()),
  } as unknown as typeof caches
  setActingLead(LEAD)
})

afterEach(() => {
  clearActingLead()
  vi.unstubAllGlobals()
})

describe("sessionUserIdOf", () => {
  it("reads the user id, and is null for anything unreadable", () => {
    expect(sessionUserIdOf(session("u1"))).toBe("u1")
    expect(sessionUserIdOf(null)).toBeNull()
    expect(sessionUserIdOf("")).toBeNull()
    expect(sessionUserIdOf("{not json")).toBeNull()
    expect(sessionUserIdOf(JSON.stringify({ userId: 7 }))).toBeNull()
  })
})

describe("a storage event from another tab", () => {
  it("clears the acting lead and the cache when a different person signs in", () => {
    stored = session("u2")
    const heard = vi.fn()
    const off = subscribeToSession(heard)
    const acted = handleSessionStorageEvent({ key: "lemely.session", oldValue: session("u1"), newValue: session("u2") }, caches)
    off()
    expect(acted).toBe(true)
    expect(getActingLead()).toBeNull()
    expect(caches.clearQueries).toHaveBeenCalledTimes(1)
    expect(caches.removePersistedQueries).toHaveBeenCalledTimes(1)
    // The auth context is told, with the new session.
    expect(heard).toHaveBeenCalledWith(expect.objectContaining({ userId: "u2" }))
  })

  it("does the same when the session is removed (signed out elsewhere), telling the context there is none", () => {
    const heard = vi.fn()
    const off = subscribeToSession(heard)
    const acted = handleSessionStorageEvent({ key: "lemely.session", oldValue: session("u1"), newValue: null }, caches)
    off()
    expect(acted).toBe(true)
    expect(getActingLead()).toBeNull()
    expect(caches.clearQueries).toHaveBeenCalledTimes(1)
    expect(heard).toHaveBeenCalledWith(null)
  })

  it("does the same when someone signs in on a tab that had nobody", () => {
    stored = session("u2")
    expect(handleSessionStorageEvent({ key: "lemely.session", oldValue: null, newValue: session("u2") }, caches)).toBe(true)
    expect(getActingLead()).toBeNull()
    expect(caches.clearQueries).toHaveBeenCalledTimes(1)
  })

  it("treats the whole store being cleared as a change", () => {
    expect(handleSessionStorageEvent({ key: null, oldValue: null, newValue: null }, caches)).toBe(true)
    expect(getActingLead()).toBeNull()
    expect(caches.clearQueries).toHaveBeenCalledTimes(1)
  })

  it("leaves everything alone for a token refresh (same user id)", () => {
    const acted = handleSessionStorageEvent(
      { key: "lemely.session", oldValue: session("u1", "old"), newValue: session("u1", "new") },
      caches,
    )
    expect(acted).toBe(false)
    expect(getActingLead()).toEqual(LEAD)
    expect(caches.clearQueries).not.toHaveBeenCalled()
    expect(caches.removePersistedQueries).not.toHaveBeenCalled()
  })

  it("ignores every other key", () => {
    for (const key of ["lemely.deviceId", "lemely.acting-lead", "theme", "lemely.signup.next"]) {
      expect(handleSessionStorageEvent({ key, oldValue: "a", newValue: "b" }, caches)).toBe(false)
    }
    expect(getActingLead()).toEqual(LEAD)
    expect(caches.clearQueries).not.toHaveBeenCalled()
  })
})
