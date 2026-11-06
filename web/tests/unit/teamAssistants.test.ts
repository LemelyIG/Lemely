import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { INVITE_CODE_ID, rolePresetId } from "@/lib/assistantRoles"
import { fx } from "./support/billingFixtures"
import { errorQuery, fakeMutation, okQuery, pendingQuery, renderStatic } from "./support/billingRender"

const m = vi.hoisted(() => ({} as Record<string, unknown>))
vi.mock("@/lib/hooks/useTeamApi", () => ({
  useCreateAssistantInvite: () => m.invite,
  useRevokeAssistantInvite: () => m.revoke,
  useSetAssistantRole: () => m.role,
  useSetMemberCap: () => m.cap,
  useRemoveAssistant: () => m.remove,
  useJoinTeam: () => m.join,
  useMemberships: () => m.memberships,
}))
vi.mock("@/components/ui/modal", () => ({
  Modal: (p: { open: boolean; title: unknown; children: unknown; footer?: unknown }) =>
    p.open ? h("div", { role: "dialog" }, h("h2", null, p.title as never), p.children as never, p.footer as never) : null,
}))

import { AssistantCapDialog, InviteDialog, RemoveAssistantDialog, RoleDialog } from "@/portals/teacher/screens/team/AssistantDialogs"
import { AssistantsPanel } from "@/portals/teacher/screens/team/AssistantsPanel"
import { JoinTeamCard } from "@/portals/teacher/screens/team/JoinTeamCard"

beforeEach(() => {
  for (const k of ["invite", "revoke", "role", "cap", "remove", "join"]) m[k] = fakeMutation()
  m.memberships = okQuery([])
})

const noop = () => undefined
/** Rendered text with the markup stripped, so figures and apostrophes read as the sentence they are. */
const text = (html: string) => html.replace(/<[^>]+>/g, "").replace(/&#x27;/g, "'")
/** The `<button>` opening tags that carry `needle`, so a disabled state can be asserted on one control. */
const button = (html: string, needle: string) => html.match(new RegExp(`<button[^>]*>(?=[^<]*${needle})[^<]*`))?.[0] ?? ""

describe("AssistantsPanel", () => {
  it("lists assistants with role, permissions and cap, and pending invites", () => {
    const html = renderStatic(h(AssistantsPanel, { team: fx.team }))
    expect(html).toContain("Sara Ali")
    expect(html).toContain("Marker")
    expect(html).toContain("Mark papers, Regrade papers, See results")
    expect(html).toContain("Up to 2,000 credits a month (300 used)")
    expect(html).toContain("AST-7KQ2")
    expect(html).toContain("Revoke")
  })

  it("offers the three row actions and names the assistant for each", () => {
    const html = renderStatic(h(AssistantsPanel, { team: fx.team }))
    expect(html).toContain('aria-label="Edit role for Sara Ali"')
    expect(html).toContain('aria-label="Set cap for Sara Ali"')
    expect(html).toContain('aria-label="Remove Sara Ali"')
  })

  it("shows names only, never an email", () => {
    expect(renderStatic(h(AssistantsPanel, { team: fx.team }))).not.toMatch(/@/)
  })

  it("says an assistant with no limit has no limit, and one with no permissions has none", () => {
    const html = renderStatic(
      h(AssistantsPanel, { team: { ...fx.team, assistants: [{ ...fx.assistant, capUnits: null, permissions: [] }] } }),
    )
    expect(html).toContain("No limit")
    expect(html).toContain("No permissions")
  })

  it("states that assistants are free and take no seat", () => {
    expect(text(renderStatic(h(AssistantsPanel, { team: fx.team })))).toContain("Free and unlimited. They don't take a seat.")
  })

  it("explains an empty team", () => {
    const html = renderStatic(h(AssistantsPanel, { team: { ...fx.team, assistants: [], invites: [] } }))
    expect(html).toContain("No assistants yet.")
    expect(html).toContain("Invite an assistant")
  })

  it("points at the code when only invites exist", () => {
    const html = renderStatic(h(AssistantsPanel, { team: { ...fx.team, assistants: [] } }))
    expect(html).toContain("Nobody has joined yet.")
    expect(html).not.toContain("No assistants yet.")
    expect(html).toContain("AST-7KQ2")
  })

  it("lets a pending code be copied or revoked, and says what happens when revoking fails", () => {
    expect(renderStatic(h(AssistantsPanel, { team: fx.team }))).toContain('aria-label="Copy Viewer invite code"')
    m.revoke = fakeMutation({ isError: true, error: new ApiError(404, "x") })
    expect(text(renderStatic(h(AssistantsPanel, { team: fx.team })))).toContain("isn't there any more")
  })
})

describe("RoleDialog", () => {
  const render = (assistant = fx.assistant) => renderStatic(h(RoleDialog, { open: true, onClose: noop, assistant }))

  it("shows the presets, the toggles and the billing rule", () => {
    const html = render()
    expect(html).toContain("Co-teacher")
    expect(html).toContain("Everything except billing and seats.")
    expect(html).toContain("Billing, plans and seats always stay with you.")
    expect(html.match(/role="switch"/g)?.length).toBe(7)
  })

  it("starts on the assistant's preset with their effective permissions switched on", () => {
    const html = render({ ...fx.assistant, overrides: { view_usage: true, regrade: false }, permissions: ["mark", "view_results", "view_usage"] })
    expect(html).toMatch(/<input(?=[^>]*value="marker")(?=[^>]*checked)[^>]*>/)
    const on = (label: string) => new RegExp(`aria-checked="true"[^>]*>(?:(?!</button>).)*</button><label[^>]*><span[^>]*>${label}<`).test(html)
    expect(on("Mark papers")).toBe(true)
    expect(on("See usage")).toBe(true)
    expect(on("Regrade papers")).toBe(false)
  })

  it("gives each preset the id focus returns to after a reset", () => {
    const html = render()
    for (const r of ["co_teacher", "marker", "viewer"] as const) expect(html).toContain(`id="${rolePresetId(r)}"`)
  })

  it("opens on the permissions the server reports", () => {
    const html = render({ ...fx.assistant, permissions: ["mark", "regrade", "generate_quiz", "view_results"], overrides: {} })
    expect(html).toMatch(/aria-checked="true"[^>]*>(?:(?!<\/button>).)*<\/button><label[^>]*><span[^>]*>Generate quizzes</)
    expect(text(html)).toContain("Changed from the Marker preset.")
  })

  it("flags toggles that differ from the preset and offers a reset", () => {
    expect(render()).not.toContain("Reset to preset")
    const html = render({ ...fx.assistant, overrides: { view_usage: true }, permissions: ["mark", "regrade", "view_results", "view_usage"] })
    expect(text(html)).toContain("Changed from the Marker preset.")
    expect(html).toContain("Reset to preset")
  })

  it("keeps Save role off until something changes", () => {
    expect(button(render(), "Save role")).toContain("disabled")
  })

  it("warns when every permission is off", () => {
    const html = render({ ...fx.assistant, rolePreset: "viewer", overrides: { view_results: false, view_usage: false }, permissions: [] })
    expect(text(html)).toContain("With every permission off, this assistant can't do anything.")
  })

  it("names the failure and keeps it announced", () => {
    m.role = fakeMutation({ isError: true, error: new ApiError(422, "x", { code: "invalid_permissions" }) })
    expect(render()).toMatch(/role="alert"[^>]*>Choose only the permissions listed/)
  })
})

describe("AssistantCapDialog", () => {
  const render = (assistant = fx.assistant) => renderStatic(h(AssistantCapDialog, { open: true, onClose: noop, assistant }))

  it("shows the current limit and period, with Save off until it changes", () => {
    const html = render()
    expect(html).toContain('value="2000"')
    expect(html).toContain("Limit how much they can use")
    expect(button(html, "Save cap")).toContain("disabled")
  })

  it("hides the limit fields for an assistant with no limit", () => {
    const html = render({ ...fx.assistant, capUnits: null })
    expect(html).not.toContain("Up to (credits)")
    expect(text(html)).toContain("No limit.")
  })

  it("shows a field error for an invalid limit, and accepts zero", () => {
    expect(render({ ...fx.assistant, capUnits: 2_000_000 }).toString()).toContain("1,000,000 or fewer")
    const zero = render({ ...fx.assistant, capUnits: 0 })
    expect(zero).toContain('value="0"')
    expect(zero).not.toContain("Enter a credit limit.")
  })

  it("names the failure", () => {
    m.cap = fakeMutation({ isError: true, error: new ApiError(409, "x") })
    expect(text(render())).toContain("isn't possible right now")
  })
})

describe("InviteDialog", () => {
  const render = () => renderStatic(h(InviteDialog, { open: true, onClose: noop }))

  it("offers each role with what it allows, and 1, 7 or 14 days", () => {
    const html = render()
    expect(html).toContain("Marker")
    expect(html).toContain("Read only.")
    expect(html).toContain('value="1"')
    expect(html).toContain('value="7"')
    expect(html).toContain('value="14"')
    expect(html).toContain("Create invite code")
    expect(html).not.toContain('value="30"')
  })

  it("shows the created code with its expiry, a single-use note and a copy control", () => {
    m.invite = fakeMutation({ isSuccess: true, data: fx.team.invites[0] })
    const html = render()
    expect(html).toContain("AST-7KQ2")
    expect(html).toContain("Copy code")
    expect(html).toContain("It works once")
    expect(html).not.toContain("Create invite code")
    // The code is where focus lands, so its element carries the id the focus helper names.
    expect(html).toMatch(new RegExp(`id="${INVITE_CODE_ID}"[^>]*tabindex="-1"`))
  })

  it("names the failure when there are too many open invites", () => {
    m.invite = fakeMutation({ isError: true, error: new ApiError(409, "x", { code: "invite_limit" }) })
    expect(text(render())).toContain("too many open invites")
  })
})

describe("RemoveAssistantDialog", () => {
  it("states that access ends straight away", () => {
    const html = renderStatic(h(RemoveAssistantDialog, { open: true, onClose: noop, assistant: fx.assistant }))
    expect(html).toContain("loses access to your classes straight away")
    expect(html).toContain("Remove assistant")
  })

  it("names a failed removal", () => {
    m.remove = fakeMutation({ isError: true, error: new ApiError(500, "x") })
    expect(text(renderStatic(h(RemoveAssistantDialog, { open: true, onClose: noop, assistant: fx.assistant })))).toContain(
      "Couldn't remove this assistant. Try again.",
    )
  })
})

describe("JoinTeamCard", () => {
  it("explains what to enter", () => {
    const html = text(renderStatic(h(JoinTeamCard)))
    expect(html).toContain("Join a team")
    expect(html).toContain("Joining someone else's team? Enter the assistant code they sent you.")
    expect(html).toContain("Assistant code")
  })

  it("confirms a joined team and maps an invalid code", () => {
    m.join = fakeMutation({ isSuccess: true, data: { teacherName: "Ms Nour", role: "marker" } })
    expect(renderStatic(h(JoinTeamCard))).toMatch(/role="status"[^>]*>.*Ms Nour/)
    m.join = fakeMutation({ isError: true, error: new ApiError(404, "x") })
    expect(renderStatic(h(JoinTeamCard))).toContain("That code isn")
  })

  it("maps a used code and any other failure to a sentence that names the next step", () => {
    m.join = fakeMutation({ isError: true, error: new ApiError(409, "x", { code: "invite_already_redeemed" }) })
    expect(text(renderStatic(h(JoinTeamCard)))).toContain("already been used")
    m.join = fakeMutation({ isError: true, error: new ApiError(500, "x") })
    expect(text(renderStatic(h(JoinTeamCard)))).toContain("Couldn't join that team. Check the code and try again.")
  })

  it("lists the teams you assist, names and roles only", () => {
    m.memberships = okQuery([{ memberId: "mm1", teacherName: "Ms Hoda Ibrahim", role: "marker" }, { memberId: "mm2", teacherName: "Mr Adel", role: "co_teacher" }])
    const html = renderStatic(h(JoinTeamCard))
    expect(html).toContain("Teams you assist")
    expect(html).toContain("Ms Hoda Ibrahim")
    expect(html).toContain("Marker")
    expect(html).toContain("Co-teacher")
    expect(html).not.toMatch(/Leave|Remove/)
    expect(html).not.toMatch(/@/)
  })

  it("shows no list while loading or when there are no teams, and does not block joining when it fails", () => {
    for (const q of [pendingQuery(), okQuery([])]) {
      m.memberships = q
      expect(renderStatic(h(JoinTeamCard))).not.toContain("Teams you assist")
    }
    m.memberships = errorQuery(new ApiError(500, "x"))
    const html = text(renderStatic(h(JoinTeamCard)))
    expect(html).toContain("Couldn't load the teams you assist. You can still join one.")
    expect(html).toContain("Join team")
  })

  it("capitalises the role in the confirmation", () => {
    m.join = fakeMutation({ isSuccess: true, data: { teacherName: "Ms Nour", role: "marker" } })
    expect(text(renderStatic(h(JoinTeamCard)))).toContain("You're now on Ms Nour's team as Marker.")
  })

  it("names a conflict on joining (already on the team, or your own code)", () => {
    m.join = fakeMutation({ isError: true, error: new ApiError(409, "x") })
    expect(text(renderStatic(h(JoinTeamCard)))).toContain("You can't join that team. You may already be on it.")
  })

  it("announces a join politely and failures as alerts", () => {
    m.join = fakeMutation({ isError: true, error: new ApiError(404, "x") })
    expect(renderStatic(h(JoinTeamCard))).toContain('role="alert"')
  })
})
