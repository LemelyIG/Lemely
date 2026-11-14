import { beforeEach, describe, expect, it } from "vitest"
import {
  matchAccessRestricted,
  reportAccessRestricted,
  resetAccessRestrictedBurst,
  setAccessRestrictedHandler,
  type AccessRestrictedInfo,
} from "../../src/lib/accessRestricted.ts"
import { ApiError } from "../../src/lib/api.ts"
import { accessRestrictedReason, isAccessRestricted } from "../../src/lib/access-api.ts"

/* The transport-level matcher and the one-handler burst rule that `api.ts` calls on every non-OK path. */
const detail = (reason?: string) => ({ code: "access_restricted", ...(reason ? { reason } : {}) })

describe("matchAccessRestricted", () => {
  it("matches detail.code on a 403 and reads the reason", () => {
    expect(matchAccessRestricted(403, detail("domain"))).toEqual({ reason: "domain" })
    expect(matchAccessRestricted(403, detail("unverified"))).toEqual({ reason: "unverified" })
  })
  it("tolerates a top-level code in the body", () => {
    expect(matchAccessRestricted(403, undefined, { code: "access_restricted", reason: "unverified" })).toEqual({ reason: "unverified" })
  })
  it("treats an unknown or missing reason as domain", () => {
    expect(matchAccessRestricted(403, detail("weird"))).toEqual({ reason: "domain" })
    expect(matchAccessRestricted(403, detail())).toEqual({ reason: "domain" })
  })
  it("ignores other statuses, other codes and plain sentences", () => {
    expect(matchAccessRestricted(401, detail("domain"))).toBeNull()
    expect(matchAccessRestricted(403, "You do not have access to that class.")).toBeNull()
    expect(matchAccessRestricted(403, { code: "something_else" })).toBeNull()
    expect(matchAccessRestricted(500, undefined, undefined)).toBeNull()
  })
  it("agrees with the ApiError helpers, including a top-level code", () => {
    const flat = new ApiError(403, "Forbidden", undefined, undefined, { code: "access_restricted", reason: "unverified" })
    expect(isAccessRestricted(flat)).toBe(true)
    expect(accessRestrictedReason(flat)).toBe("unverified")
  })
})

describe("reportAccessRestricted", () => {
  let seen: AccessRestrictedInfo[]
  beforeEach(() => {
    seen = []
    resetAccessRestrictedBurst()
    setAccessRestrictedHandler((i) => seen.push(i))
  })

  it("calls the handler for a refusal and not for anything else", () => {
    reportAccessRestricted(403, "plain")
    reportAccessRestricted(500, detail("domain"))
    expect(seen).toEqual([])
    reportAccessRestricted(403, detail("domain"), undefined, 10_000)
    expect(seen).toEqual([{ reason: "domain" }])
  })
  it("fires once per burst, again after the window", () => {
    reportAccessRestricted(403, detail("domain"), undefined, 10_000)
    reportAccessRestricted(403, detail("domain"), undefined, 10_500)
    reportAccessRestricted(403, detail("domain"), undefined, 11_900)
    expect(seen).toHaveLength(1)
    reportAccessRestricted(403, detail("domain"), undefined, 12_100)
    expect(seen).toHaveLength(2)
  })
  it("debounces per reason: an unverified refusal does not swallow a domain cut-off", () => {
    reportAccessRestricted(403, detail("unverified"), undefined, 10_000)
    reportAccessRestricted(403, detail("domain"), undefined, 10_100)
    reportAccessRestricted(403, detail("unverified"), undefined, 10_200)
    reportAccessRestricted(403, detail("domain"), undefined, 10_300)
    expect(seen).toEqual([{ reason: "unverified" }, { reason: "domain" }])
  })
  it("does nothing once the handler is cleared", () => {
    setAccessRestrictedHandler(null)
    reportAccessRestricted(403, detail("domain"), undefined, 50_000)
    expect(seen).toEqual([])
  })
})
