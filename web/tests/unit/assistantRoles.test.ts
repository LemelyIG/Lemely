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
  INVITE_CODE_ID,
  differsFromPreset,
  effectivePermissions,
  focusTargetId,
  inviteBody,
  joinCodeDraft,
  joinFailureMessage,
  joinedMessage,
  overridesFor,
  roleBody,
  roleChanged,
  roleDraftBody,
  roleDraftFor,
  rolePresetId,
  roleReducer,
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

  it("keeps Save off until the draft differs from what the server holds", () => {
    const row = fx.assistant
    expect(roleChanged(row, roleDraftFor(row))).toBe(false)
    expect(roleChanged(row, { preset: "marker", selected: ["view_results", "mark", "regrade"] })).toBe(false)
    expect(roleChanged(row, { preset: "viewer", selected: PRESET_PERMISSIONS.viewer })).toBe(true)
    expect(roleChanged(row, { preset: "marker", selected: ["mark", "view_results"] })).toBe(true)
    // The same permissions under another preset are still a different role.
    expect(roleChanged({ ...row, rolePreset: "co_teacher" }, { preset: "marker", selected: ["mark", "regrade", "view_results"] })).toBe(true)
  })

  it("tells when the toggles no longer match the preset", () => {
    expect(differsFromPreset("marker", ["mark", "regrade", "view_results"])).toBe(false)
    expect(differsFromPreset("marker", ["mark"])).toBe(true)
  })
})

describe("role dialog draft", () => {
  const row = fx.assistant

  it("opens on the server's effective permissions, not on the frontend preset mirror", () => {
    // The backend says this marker can also generate quizzes (no override stored); the frontend mirror alone would say it cannot.
    const served = { ...row, permissions: ["mark", "regrade", "generate_quiz", "view_results"] as typeof row.permissions, overrides: {} }
    expect(roleDraftFor(served)).toEqual({ preset: "marker", selected: ["mark", "regrade", "generate_quiz", "view_results"] })
    expect(roleChanged(served, roleDraftFor(served))).toBe(false)
    // Overrides are still worked out against the preset.
    expect(roleDraftBody(roleDraftFor(served))).toEqual({ rolePreset: "marker", overrides: { generate_quiz: true } })
  })

  it("switching preset resets the toggles to that preset", () => {
    const custom = roleReducer(roleDraftFor(row), { type: "toggle", permission: "view_usage", on: true })
    expect(roleReducer(custom, { type: "preset", preset: "viewer" })).toEqual({ preset: "viewer", selected: ["view_results", "view_usage"] })
    expect(roleReducer(custom, { type: "preset", preset: "co_teacher" }).selected).toEqual([...TEAM_PERMISSIONS])
  })

  it("a toggle changes one permission and keeps catalogue order", () => {
    const d = roleReducer(roleReducer(roleDraftFor(row), { type: "toggle", permission: "view_usage", on: true }), { type: "toggle", permission: "regrade", on: false })
    expect(d).toEqual({ preset: "marker", selected: ["mark", "view_results", "view_usage"] })
    expect(differsFromPreset(d.preset, d.selected)).toBe(true)
    expect(roleChanged(row, d)).toBe(true)
  })

  it("reset puts the toggles back on the chosen preset and keeps the preset", () => {
    const custom = roleReducer(roleDraftFor(row), { type: "toggle", permission: "manage_classes", on: true })
    const back = roleReducer(custom, { type: "reset" })
    expect(back).toEqual({ preset: "marker", selected: ["mark", "regrade", "view_results"] })
    expect(differsFromPreset(back.preset, back.selected)).toBe(false)
    expect(roleChanged(row, back)).toBe(false)
  })

  it("the save body is the preset and only the toggles that differ", () => {
    const d = roleReducer(roleReducer(roleDraftFor(row), { type: "toggle", permission: "view_usage", on: true }), { type: "toggle", permission: "regrade", on: false })
    expect(roleDraftBody(d)).toEqual({ rolePreset: "marker", overrides: { regrade: false, view_usage: true } })
    expect(roleDraftBody(roleReducer(d, { type: "reset" }))).toEqual({ rolePreset: "marker", overrides: {} })
  })
})

describe("focus targets", () => {
  it("sends focus to the code once an invite is created", () => {
    expect(focusTargetId({ kind: "invite-created" })).toBe(INVITE_CODE_ID)
  })

  it("sends focus to the chosen preset after a reset", () => {
    expect(focusTargetId({ kind: "role-reset", preset: "marker" })).toBe(rolePresetId("marker"))
    expect(focusTargetId({ kind: "role-reset", preset: "viewer" })).not.toBe(focusTargetId({ kind: "role-reset", preset: "marker" }))
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
    expect(joinedMessage("Ms Nour", "marker")).toBe("You're now on Ms Nour's team as Marker.")
    expect(joinedMessage("Ms Nour", "co_teacher")).toBe("You're now on Ms Nour's team as Co-teacher.")
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
    expect(joinFailureMessage(err(409))).toBe("You can't join that team. You may already be on it.")
    expect(joinFailureMessage(err(403))).toContain("teacher accounts")
    expect(joinFailureMessage(err(429))).toContain("Too many attempts")
    expect(joinFailureMessage(err(0))).toContain("offline")
    expect(joinFailureMessage(err(500))).toBe("Couldn't join that team. Check the code and try again.")
    expect(joinFailureMessage(new Error("boom"))).toBe("Couldn't join that team. Check the code and try again.")
  })
})
