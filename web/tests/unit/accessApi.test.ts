import { afterEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import {
  AccessConfigError,
  accessRestrictedReason,
  getAccessConfig,
  isAccessRestricted,
  isAccessRestrictedDetail,
} from "@/lib/access-api"

afterEach(() => {
  vi.unstubAllGlobals()
})

function stubFetch(response: Response | Error): ReturnType<typeof vi.fn> {
  const fn = vi.fn(async () => {
    if (response instanceof Error) throw response
    return response
  })
  vi.stubGlobal("fetch", fn)
  return fn
}

describe("getAccessConfig", () => {
  it("reads the restricted flag from the public endpoint", async () => {
    const fetchMock = stubFetch(new Response(JSON.stringify({ restricted: true }), { status: 200 }))
    await expect(getAccessConfig()).resolves.toEqual({ restricted: true })
    expect(fetchMock).toHaveBeenCalledWith("/api/access/config", expect.anything())
  })

  it("is open when the server says so", async () => {
    stubFetch(new Response(JSON.stringify({ restricted: false }), { status: 200 }))
    await expect(getAccessConfig()).resolves.toEqual({ restricted: false })
  })

  it("never reads a missing or non-boolean flag as restricted", async () => {
    stubFetch(new Response(JSON.stringify({ restricted: "yes" }), { status: 200 }))
    await expect(getAccessConfig()).resolves.toEqual({ restricted: false })
  })

  it("throws a typed error with the status on a non-2xx answer", async () => {
    stubFetch(new Response("nope", { status: 503 }))
    await expect(getAccessConfig()).rejects.toMatchObject({ name: "AccessConfigError", status: 503 })
  })

  it("throws status 0 when there is no response", async () => {
    stubFetch(new TypeError("Failed to fetch"))
    const error = await getAccessConfig().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(AccessConfigError)
    expect((error as AccessConfigError).status).toBe(0)
  })
})

describe("isAccessRestricted", () => {
  const refusal = (reason: string, status = 403) =>
    new ApiError(status, "403 Forbidden", { code: "access_restricted", reason })

  it("recognises the server's refusal and its reason", () => {
    expect(isAccessRestricted(refusal("domain"))).toBe(true)
    expect(accessRestrictedReason(refusal("domain"))).toBe("domain")
    expect(accessRestrictedReason(refusal("unverified"))).toBe("unverified")
  })

  it("does not take the other 403s for it", () => {
    expect(isAccessRestricted(new ApiError(403, "forbidden", { code: "email_unverified" }))).toBe(false)
    expect(isAccessRestricted(new ApiError(403, "Your role is not permitted"))).toBe(false)
    expect(isAccessRestricted(refusal("domain", 401))).toBe(false)
    expect(isAccessRestricted(new Error("access_restricted"))).toBe(false)
    expect(isAccessRestricted(null)).toBe(false)
  })

  it("gives no reason for an unknown one", () => {
    expect(accessRestrictedReason(refusal("something-new"))).toBeNull()
    expect(accessRestrictedReason(new ApiError(500, "boom"))).toBeNull()
  })

  it("narrows a bare detail", () => {
    expect(isAccessRestrictedDetail({ code: "access_restricted", reason: "domain" })).toBe(true)
    expect(isAccessRestrictedDetail("access_restricted")).toBe(false)
    expect(isAccessRestrictedDetail(undefined)).toBe(false)
  })
})
