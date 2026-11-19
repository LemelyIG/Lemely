import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { request, fetchBlobUrl, streamActivity, ApiError } from "../../src/lib/api.ts"
import {
  resetAccessRestrictedBurst,
  setAccessRestrictedHandler,
  type AccessRestrictedInfo,
} from "../../src/lib/accessRestricted.ts"

/*
 * The cut-off must fire from the transport itself, not from a react-query cache: a plain
 * `request()` / `fetchBlobUrl()` / `streamActivity()` call refused with 403 `access_restricted`
 * reaches the one registered handler exactly once.
 */
const refusal = (reason = "domain") =>
  new Response(JSON.stringify({ detail: { code: "access_restricted", reason } }), {
    status: 403,
    headers: { "Content-Type": "application/json" },
  })

let seen: AccessRestrictedInfo[]

beforeEach(() => {
  const store = new Map<string, string>()
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  })
  seen = []
  resetAccessRestrictedBurst()
  setAccessRestrictedHandler((info) => seen.push(info))
})

afterEach(() => {
  setAccessRestrictedHandler(null)
  vi.unstubAllGlobals()
})

describe("api.ts reports 403 access_restricted to the handler", () => {
  it("from request(), exactly once, and still throws the ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => refusal()))
    await expect(request("/student/papers")).rejects.toBeInstanceOf(ApiError)
    expect(seen).toEqual([{ reason: "domain" }])
  })

  it("once for a burst of parallel refused calls", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => refusal()))
    await Promise.allSettled([request("/a"), request("/b"), request("/c")])
    expect(seen).toHaveLength(1)
  })

  it("passes the unverified reason through", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => refusal("unverified")))
    await request("/me").catch(() => undefined)
    expect(seen).toEqual([{ reason: "unverified" }])
  })

  it("from fetchBlobUrl()", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => refusal()))
    await fetchBlobUrl("/papers/1/preview").catch(() => undefined)
    expect(seen).toHaveLength(1)
  })

  it("from streamActivity()", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => refusal()))
    await (async () => {
      for await (const _ of streamActivity("/student/correct")) void _
    })().catch(() => undefined)
    expect(seen).toHaveLength(1)
  })

  it("not for an ordinary 403, a 500 or a success", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "Not your class." }), { status: 403 })))
    await request("/classes/1").catch(() => undefined)
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 500 })))
    await request("/x").catch(() => undefined)
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })))
    await request("/y")
    expect(seen).toEqual([])
  })

  it("not from /auth/* calls: the sign-in and sign-up forms show the refusal inline", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => refusal()))
    for (const path of ["/auth/login", "/auth/signup", "/auth/verify-email/code"]) {
      await expect(request(path, { method: "POST" })).rejects.toBeInstanceOf(ApiError)
    }
    expect(seen).toEqual([])
    await request("/student/papers").catch(() => undefined)
    expect(seen).toHaveLength(1)
  })

  it("still from the refresh of an existing session: that is the cut-off case", async () => {
    const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url")
    localStorage.setItem(
      "lemely.session",
      JSON.stringify({ accessToken: `${b64({ alg: "none" })}.${b64({ exp: 4102444800 })}.x`, refreshToken: "r", userId: "u", role: "student" }),
    )
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => (String(url).endsWith("/auth/refresh") ? refusal() : new Response("{}", { status: 401 }))),
    )
    await request("/student/papers").catch(() => undefined)
    expect(seen).toEqual([{ reason: "domain" }])
  })
})
