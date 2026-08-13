import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError, request } from "@/lib/api"
import { getSession, setSession, takeSessionExpired } from "@/lib/auth/storage"

/*
 * Silent token refresh in the API client (P6, the session-expiry fix).
 *
 * The defect: access tokens last an hour, nothing renewed them, and no code
 * anywhere in `web/src` looked at a 401. An hour into a session every request
 * failed, `request()` lifted the server's `detail` into `ApiError.message`, and
 * each screen rendered "Invalid access token: Signature has expired" verbatim —
 * inside a portal the route guard kept rendering, because it only ever checked
 * that *a* session object was in localStorage.
 *
 * These pin the recovery. They are pure logic over stubbed `fetch` and
 * `localStorage`, which is what this Node-environment runner is for (D3.20);
 * the redirect that follows a cleared session is the Playwright suite's job.
 */

function encode(payload: Record<string, unknown>): string {
  return `header.${Buffer.from(JSON.stringify(payload)).toString("base64url")}.signature`
}

/** A token that is valid for another hour. */
function live(): string {
  return encode({ exp: Math.floor(Date.now() / 1000) + 3600 })
}

/** A token whose `exp` has already passed. */
function dead(): string {
  return encode({ exp: Math.floor(Date.now() / 1000) - 3600 })
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

/** The 401 the backend actually returns for an expired bearer token. */
function expiredTokenResponse(): Response {
  return json(401, { detail: "Invalid access token: Signature has expired" })
}

function refreshedSession(accessToken: string): Response {
  return json(200, {
    accessToken,
    refreshToken: "refresh-token",
    userId: "user-1",
    role: "student",
  })
}

let fetchMock: ReturnType<typeof vi.fn>

/** Every `fetch` call's URL, in order. */
function calledPaths(): string[] {
  return fetchMock.mock.calls.map((call) => String(call[0]))
}

function refreshCallCount(): number {
  return calledPaths().filter((url) => url.endsWith("/auth/refresh")).length
}

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
  fetchMock = vi.fn()
  vi.stubGlobal("fetch", fetchMock)
  takeSessionExpired() // clear any flag left by a previous test
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("recovering from an expired access token", () => {
  it("refreshes and replays the request, so the caller never sees the 401", async () => {
    setSession({
      accessToken: live(), // not obviously stale — the 401 is the first hint
      refreshToken: "refresh-token",
      userId: "user-1",
      role: "student",
    })
    fetchMock
      .mockResolvedValueOnce(expiredTokenResponse())
      .mockResolvedValueOnce(refreshedSession("renewed-token"))
      .mockResolvedValueOnce(json(200, { ok: true }))

    const result = await request<{ ok: boolean }>("/me/profile")

    expect(result).toEqual({ ok: true })
    expect(calledPaths()).toEqual([
      "/api/me/profile",
      "/api/auth/refresh",
      "/api/me/profile",
    ])
  })

  it("sends the renewed token on the replay, not the dead one", async () => {
    const stale = live()
    setSession({
      accessToken: stale,
      refreshToken: "refresh-token",
      userId: "user-1",
      role: "student",
    })
    fetchMock
      .mockResolvedValueOnce(expiredTokenResponse())
      .mockResolvedValueOnce(refreshedSession("renewed-token"))
      .mockResolvedValueOnce(json(200, {}))

    await request("/me/profile")

    const replayHeaders = fetchMock.mock.calls[2][1].headers as Record<string, string>
    expect(replayHeaders.Authorization).toBe("Bearer renewed-token")
    expect(getSession()?.accessToken).toBe("renewed-token")
  })

  it("renews once for a screenful of simultaneous 401s", async () => {
    // The realistic case: a portal loads and a dozen queries fire together, all
    // holding the same stale token. Without single-flighting, one user opening
    // one page would put a dozen refreshes on the server at once.
    setSession({
      accessToken: live(),
      refreshToken: "refresh-token",
      userId: "user-1",
      role: "student",
    })
    fetchMock.mockImplementation((url: string, init: RequestInit) => {
      if (String(url).endsWith("/auth/refresh")) {
        return Promise.resolve(refreshedSession("renewed-token"))
      }
      const headers = init.headers as Record<string, string>
      return Promise.resolve(
        headers.Authorization === "Bearer renewed-token"
          ? json(200, { ok: true })
          : expiredTokenResponse(),
      )
    })

    const results = await Promise.all(
      ["/a", "/b", "/c", "/d", "/e"].map((path) => request<{ ok: boolean }>(path)),
    )

    expect(results).toEqual(Array.from({ length: 5 }, () => ({ ok: true })))
    expect(refreshCallCount()).toBe(1)
  })

  it("refreshes before sending when the token is already known to be expired", async () => {
    // No point spending a round trip to be told what the `exp` claim already
    // says — especially when a whole screen's worth of queries would each spend
    // one on first load after a long absence.
    setSession({
      accessToken: dead(),
      refreshToken: "refresh-token",
      userId: "user-1",
      role: "student",
    })
    fetchMock
      .mockResolvedValueOnce(refreshedSession("renewed-token"))
      .mockResolvedValueOnce(json(200, { ok: true }))

    await request("/me/profile")

    expect(calledPaths()).toEqual(["/api/auth/refresh", "/api/me/profile"])
  })
})

describe("when the session cannot be saved", () => {
  it("clears it and flags the expiry, so the guard can explain itself", async () => {
    setSession({
      accessToken: live(),
      refreshToken: "revoked-token",
      userId: "user-1",
      role: "student",
    })
    fetchMock
      .mockResolvedValueOnce(expiredTokenResponse())
      .mockResolvedValueOnce(json(401, { detail: "Refresh token rejected" }))

    await expect(request("/me/profile")).rejects.toBeInstanceOf(ApiError)

    expect(getSession()).toBeNull()
    expect(takeSessionExpired()).toBe(true)
  })

  it("keeps the session when the refresh could not be delivered at all", async () => {
    // A dropped connection says nothing about whether the session is still
    // good. Signing the user out over it would lose their place for no reason.
    setSession({
      accessToken: live(),
      refreshToken: "refresh-token",
      userId: "user-1",
      role: "student",
    })
    fetchMock
      .mockResolvedValueOnce(expiredTokenResponse())
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))

    await expect(request("/me/profile")).rejects.toBeInstanceOf(ApiError)

    expect(getSession()?.refreshToken).toBe("refresh-token")
    expect(takeSessionExpired()).toBe(false)
  })

  it("gives up after one replay rather than looping", async () => {
    // A 401 that refreshing cannot fix — an unrecognised role, say — must
    // surface as itself instead of driving an endless refresh/retry cycle.
    setSession({
      accessToken: live(),
      refreshToken: "refresh-token",
      userId: "user-1",
      role: "student",
    })
    fetchMock.mockImplementation((url: string) =>
      Promise.resolve(
        String(url).endsWith("/auth/refresh")
          ? refreshedSession("renewed-token")
          : json(401, { detail: "Access token is missing a recognised role" }),
      ),
    )

    await expect(request("/me/profile")).rejects.toMatchObject({
      status: 401,
      message: "Access token is missing a recognised role",
    })
    expect(refreshCallCount()).toBe(1)
  })
})

describe("building the request", () => {
  it("still sends the bearer token when the caller supplies its own headers", async () => {
    // Regression: `...init` used to be spread *after* `headers`, so a caller
    // passing any header of its own replaced the merged object and lost the
    // `Authorization` entry with it. The three `useNotificationPrefsApi` calls
    // that set a `Content-Type` were going out entirely unauthenticated.
    const token = live()
    setSession({ accessToken: token, refreshToken: "r", userId: "user-1", role: "student" })
    fetchMock.mockResolvedValueOnce(json(200, { ok: true }))

    await request("/me/notification-preferences", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: false }),
    })

    const [, init] = fetchMock.mock.calls[0]
    const headers = init.headers as Record<string, string>
    expect(headers.Authorization).toBe(`Bearer ${token}`)
    expect(headers["Content-Type"]).toBe("application/json")
    expect(init.method).toBe("PUT")
  })
})

describe("the sign-in endpoints themselves", () => {
  it("does not try to refresh a failed login", async () => {
    // A 401 from `/auth/login` means the password was wrong. Treating it as a
    // stale token would fire a pointless refresh and — worse — could clear the
    // session of someone who was already signed in and just mistyped.
    setSession({
      accessToken: live(),
      refreshToken: "refresh-token",
      userId: "user-1",
      role: "student",
    })
    fetchMock.mockResolvedValueOnce(json(401, { detail: "Invalid credentials" }))

    await expect(
      request("/auth/login", { method: "POST", body: JSON.stringify({}) }),
    ).rejects.toMatchObject({ status: 401, message: "Invalid credentials" })

    expect(refreshCallCount()).toBe(0)
    expect(getSession()).not.toBeNull()
    expect(takeSessionExpired()).toBe(false)
  })
})
