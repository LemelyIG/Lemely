import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import {
  INVITE_EXPIRY_DAYS,
  JOIN_CODE_MAX,
  PERMISSION_COPY,
  PRESET_PERMISSIONS,
  ROLE_COPY,
  assistantCapChanged,
  assistantFailureMessage,
  differsFromPreset,
  effectivePermissions,
  inviteBody,
  joinCodeDraft,
  joinFailureMessage,
  joinedMessage,
  overridesFor,
  roleBody,
  roleChanged,
  togglePermission,
} from "@/lib/assistantRoles"
import { TEAM_PERMISSIONS } from "@/lib/billingTypes"
import { fx } from "./support/billingFixtures"

describe("assistant roles", () => {
  it("labels every role and permission", () => {
    expect(ROLE_COPY.co_teacher.description).toBe("Everything except billing and seats.")
    expect(ROLE_COPY.marker.description).toBe("Mark and regrade, and see the results they mark.")
    expect(ROLE_COPY.viewer.description).toBe("Read only.")
    for (const p of TEAM_PERMISSIONS) expect(PERMISSION_COPY[p].length).toBeGreaterThan(0)
  })

  it("mirrors plan 03's presets", () => {
    expect(PRESET_PERMISSIONS.co_teacher).toEqual([...TEAM_PERMISSIONS])
    expect(PRESET_PERMISSIONS.marker).toEqual(["mark", "regrade", "view_results"])
    expect(PRESET_PERMISSIONS.viewer).toEqual(["view_results", "view_usage"])
  })

  it("never offers billing or seats as a permission", () => {
    for (const p of TEAM_PERMISSIONS) expect(p).not.toMatch(/billing|seat|plan/)
  })

  it("applies overrides on top of a preset", () => {
    expect(effectivePermissions("marker", {})).toEqual(["mark", "regrade", "view_results"])
    expect(effectivePermissions("marker", { regrade: false, view_usage: true })).toEqual(["mark", "view_results", "view_usage"])
  })

  it("sends only the differences from the preset", () => {
    expect(overridesFor("marker", ["mark", "regrade", "view_results"])).toEqual({})
    expect(overridesFor("marker", ["mark", "view_results", "view_usage"])).toEqual({ regrade: false, view_usage: true })
  })
})

describe("role editor builders", () => {
  it("builds the PATCH input from a preset and the toggles, in any toggle order", () => {
    expect(roleBody("marker", ["view_usage", "mark", "view_results"])).toEqual({
      rolePreset: "marker",
      overrides: { regrade: false, view_usage: true },
    })
    expect(roleBody("viewer", ["view_usage", "view_results"])).toEqual({ rolePreset: "viewer", overrides: {} })
    expect(roleBody("co_teacher", [])).toEqual({
      rolePreset: "co_teacher",
      overrides: Object.fromEntries(TEAM_PERMISSIONS.map((p) => [p, false])),
    })
  })

  it("a round trip through overrides gives the same permissions back", () => {
    const body = roleBody("marker", ["mark", "generate_quiz", "view_results"])
    expect(effectivePermissions(body.rolePreset, body.overrides)).toEqual(["mark", "generate_quiz", "view_results"])
  })

  it("toggles one permission and keeps catalogue order", () => {
    expect(togglePermission(["mark", "view_results"], "regrade", true)).toEqual(["mark", "regrade", "view_results"])
    expect(togglePermission(["mark", "regrade"], "mark", false)).toEqual(["regrade"])
    expect(togglePermission(["mark"], "mark", true)).toEqual(["mark"])
  })

  it("keeps Save off until the draft differs from what is stored", () => {
    const row = fx.assistant
    expect(roleChanged(row, "marker", ["view_results", "mark", "regrade"])).toBe(false)
    expect(roleChanged(row, "viewer", PRESET_PERMISSIONS.viewer)).toBe(true)
    expect(roleChanged(row, "marker", ["mark", "view_results"])).toBe(true)
    // The same effective permissions held as overrides on another preset are still a different role.
    expect(roleChanged({ ...row, rolePreset: "co_teacher", overrides: { manage_classes: false } }, "marker", ["mark", "regrade", "view_results"])).toBe(true)
  })

  it("tells when the toggles no longer match the preset", () => {
    expect(differsFromPreset("marker", ["mark", "regrade", "view_results"])).toBe(false)
    expect(differsFromPreset("marker", ["mark"])).toBe(true)
  })
})

describe("assistant cap", () => {
  it("is changed only by a different limit, or a different period under a limit", () => {
    const row = fx.assistant
    expect(assistantCapChanged(row, { capUnits: 2000, capPeriod: "month" })).toBe(false)
    expect(assistantCapChanged(row, { capUnits: 2000, capPeriod: "total" })).toBe(true)
    expect(assistantCapChanged(row, { capUnits: 0, capPeriod: "month" })).toBe(true)
    expect(assistantCapChanged(row, { capUnits: null, capPeriod: "month" })).toBe(true)
    const open = { ...row, capUnits: null }
    expect(assistantCapChanged(open, { capUnits: null, capPeriod: "total" })).toBe(false)
  })
})

describe("invite form", () => {
  it("builds the request for each expiry", () => {
    expect([...INVITE_EXPIRY_DAYS]).toEqual([1, 7, 14])
    expect(inviteBody("marker", "7")).toEqual({ ok: true, body: { role: "marker", expiresInDays: 7 } })
    expect(inviteBody("co_teacher", "14")).toEqual({ ok: true, body: { role: "co_teacher", expiresInDays: 14 } })
  })

  it("refuses a role or expiry it does not offer instead of coercing it", () => {
    expect(inviteBody("owner", "7")).toEqual({ ok: false, error: "Choose a role." })
    expect(inviteBody("viewer", "")).toEqual({ ok: false, error: "Choose how long the code works." })
    expect(inviteBody("viewer", "30")).toEqual({ ok: false, error: "Choose how long the code works." })
    expect(inviteBody("viewer", "abc")).toEqual({ ok: false, error: "Choose how long the code works." })
  })
})

describe("join code", () => {
  it("trims what was pasted and sends the rest as typed", () => {
    expect(joinCodeDraft("  AST-7kq2\n")).toEqual({ ok: true, code: "AST-7kq2" })
  })

  it("explains a blank or overlong code", () => {
    expect(joinCodeDraft("   ")).toEqual({ ok: false, error: "Enter the code you were sent." })
    expect(joinCodeDraft("x".repeat(JOIN_CODE_MAX + 1)).ok).toBe(false)
    expect(joinCodeDraft("x".repeat(JOIN_CODE_MAX)).ok).toBe(true)
  })

  it("names the joined team and role", () => {
    expect(joinedMessage("Ms Nour", "marker")).toBe("You're now on Ms Nour's team as marker.")
    expect(joinedMessage("Ms Nour", "co_teacher")).toBe("You're now on Ms Nour's team as co-teacher.")
  })
})

describe("failure copy", () => {
  const err = (status: number, code?: string) => new ApiError(status, "x", code ? { code } : undefined)

  it("maps an assistant write by status and code, and never mentions a charge", () => {
    expect(assistantFailureMessage(err(0), "remove this assistant")).toContain("offline")
    expect(assistantFailureMessage(err(403), "x")).toBe("Only the lead teacher can manage assistants.")
    expect(assistantFailureMessage(err(404), "x")).toContain("Reload the page")
    expect(assistantFailureMessage(err(429), "x")).toContain("Too many attempts")
    expect(assistantFailureMessage(err(422, "invalid_permissions"), "x")).toContain("permissions listed")
    expect(assistantFailureMessage(err(422, "invalid_cap"), "x")).toContain("whole number")
    expect(assistantFailureMessage(err(409, "invite_limit"), "x")).toContain("too many open invites")
    expect(assistantFailureMessage(err(409), "x")).toContain("isn't possible right now")
    expect(assistantFailureMessage(err(500), "create the invite")).toBe("Couldn't create the invite. Try again.")
    for (const s of [0, 403, 404, 409, 422, 429, 500]) expect(assistantFailureMessage(err(s), "x")).not.toMatch(/charge/i)
  })

  it("maps joining by status and code", () => {
    expect(joinFailureMessage(err(404))).toBe("That code isn't valid or has expired. Ask for a new one.")
    expect(joinFailureMessage(err(409, "invite_already_redeemed"))).toContain("already been used")
    expect(joinFailureMessage(err(403))).toContain("teacher accounts")
    expect(joinFailureMessage(err(429))).toContain("Too many attempts")
    expect(joinFailureMessage(err(0))).toContain("offline")
    expect(joinFailureMessage(err(500))).toBe("Couldn't join that team. Check the code and try again.")
    expect(joinFailureMessage(new Error("boom"))).toBe("Couldn't join that team. Check the code and try again.")
  })
})
