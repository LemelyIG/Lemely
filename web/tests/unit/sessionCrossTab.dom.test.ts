// @vitest-environment jsdom
import "./support/dom-setup"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { clearActingLead, getActingLead, setActingLead } from "@/lib/actingTeacher"
import { queryClient } from "@/lib/queryClient"

const removeClient = vi.hoisted(() => vi.fn(() => Promise.resolve()))
vi.mock("@/lib/offline/queryPersister", () => ({ persister: { removeClient } }))
vi.mock("@/lib/offline/uploadQueue", () => ({ clearUploadQueue: () => Promise.resolve() }))

// Importing the module installs its `storage` listener on `window`, as the app does at startup.
import "@/lib/auth/storage"

beforeEach(() => {
  // Node's own experimental `localStorage` shadows jsdom's and throws; `getSession` reads it.
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => {}, removeItem: () => {} })
})

afterEach(() => {
  vi.unstubAllGlobals()
  clearActingLead()
  queryClient.clear()
  removeClient.mockClear()
})

const session = (userId: string) => JSON.stringify({ accessToken: "t", refreshToken: null, userId, role: "teacher" })

describe("the installed storage listener", () => {
  it("clears the acting lead and the real query cache when the signed-in user changes in another tab", () => {
    setActingLead({ leadId: "11111111-1111-4111-8111-111111111111", leadName: "Mr Hassan" })
    queryClient.setQueryData(["teacher", "classes"], { classes: [] })
    window.dispatchEvent(new StorageEvent("storage", { key: "lemely.session", oldValue: session("u1"), newValue: session("u2") }))
    expect(getActingLead()).toBeNull()
    expect(queryClient.getQueryData(["teacher", "classes"])).toBeUndefined()
    expect(removeClient).toHaveBeenCalledTimes(1)
  })

  it("does nothing for a refresh of the same user's token", () => {
    setActingLead({ leadId: "11111111-1111-4111-8111-111111111111", leadName: "Mr Hassan" })
    queryClient.setQueryData(["teacher", "classes"], { classes: [] })
    window.dispatchEvent(new StorageEvent("storage", { key: "lemely.session", oldValue: session("u1"), newValue: session("u1") }))
    expect(getActingLead()).not.toBeNull()
    expect(queryClient.getQueryData(["teacher", "classes"])).toEqual({ classes: [] })
  })
})
