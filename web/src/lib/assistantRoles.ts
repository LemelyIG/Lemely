import { ApiError } from "@/lib/api"
import { billingErrorCode } from "@/lib/billingOutcome"
import {
  TEAM_PERMISSIONS,
  type AssistantInviteCreate,
  type AssistantRole,
  type AssistantRoleUpdate,
  type AssistantRow,
  type CapUpdate,
  type TeamPermission,
} from "@/lib/billingTypes"

/* Assistant role presets and per-permission toggles (spec §2.3). Billing and seats are never
 * permissions; the server enforces that, and the UI says it. */

export const ROLES: readonly AssistantRole[] = ["co_teacher", "marker", "viewer"]

export const ROLE_COPY: Record<AssistantRole, { label: string; description: string }> = {
  co_teacher: { label: "Co-teacher", description: "Everything except billing and seats." },
  marker: { label: "Marker", description: "Mark and regrade, and see the results they mark." },
  viewer: { label: "Viewer", description: "Read only." },
}

export const PERMISSION_COPY: Record<TeamPermission, string> = {
  mark: "Mark papers",
  regrade: "Regrade papers",
  generate_quiz: "Generate quizzes",
  manage_classes: "Manage classes",
  view_results: "See results",
  manage_students: "Manage students",
  view_usage: "See usage",
}

/** Frontend mirror of plan 03 `PRESET_PERMISSIONS` (no API serves it; update it with 03). */
export const PRESET_PERMISSIONS: Record<AssistantRole, TeamPermission[]> = {
  co_teacher: [...TEAM_PERMISSIONS],
  marker: ["mark", "regrade", "view_results"],
  viewer: ["view_results", "view_usage"],
}

export function effectivePermissions(
  preset: AssistantRole,
  overrides: Partial<Record<TeamPermission, boolean>>,
): TeamPermission[] {
  const base = new Set(PRESET_PERMISSIONS[preset])
  return TEAM_PERMISSIONS.filter((p) => overrides[p] ?? base.has(p))
}

export function overridesFor(preset: AssistantRole, selected: TeamPermission[]): Partial<Record<TeamPermission, boolean>> {
  const base = new Set(PRESET_PERMISSIONS[preset])
  const chosen = new Set(selected)
  const out: Partial<Record<TeamPermission, boolean>> = {}
  for (const p of TEAM_PERMISSIONS) {
    if (base.has(p) !== chosen.has(p)) out[p] = chosen.has(p)
  }
  return out
}

/* ── Role editor ─────────────────────────────────────────────────────────── */

/** The permissions in catalogue order, once each, whatever order the toggles were flipped in. */
export function orderedPermissions(selected: readonly TeamPermission[]): TeamPermission[] {
  return TEAM_PERMISSIONS.filter((p) => selected.includes(p))
}

/** Turn one permission on or off. */
export function togglePermission(selected: readonly TeamPermission[], permission: TeamPermission, on: boolean): TeamPermission[] {
  return orderedPermissions(on ? [...selected, permission] : selected.filter((p) => p !== permission))
}

/** What "Save role" sends: the preset, and only the toggles that differ from it. */
export function roleBody(preset: AssistantRole, selected: readonly TeamPermission[]): AssistantRoleUpdate {
  return { rolePreset: preset, overrides: overridesFor(preset, orderedPermissions(selected)) }
}

const sameList = (a: readonly string[], b: readonly string[]) => a.length === b.length && a.every((x) => b.includes(x))

/** True when the draft is not what the assistant already has. Save stays off until it is. */
export function roleChanged(row: AssistantRow, preset: AssistantRole, selected: readonly TeamPermission[]): boolean {
  return preset !== row.rolePreset || !sameList(orderedPermissions(selected), effectivePermissions(row.rolePreset, row.overrides))
}

/** True when the toggles no longer match the chosen preset. */
export function differsFromPreset(preset: AssistantRole, selected: readonly TeamPermission[]): boolean {
  return Object.keys(overridesFor(preset, orderedPermissions(selected))).length > 0
}

/* ── Spending cap ────────────────────────────────────────────────────────── */

/** True when the cap body differs from what is stored, so an unchanged cap is never resent. Zero is a valid limit. */
export function assistantCapChanged(row: AssistantRow, body: CapUpdate): boolean {
  return body.capUnits !== row.capUnits || (body.capUnits !== null && body.capPeriod !== row.capPeriod)
}

/* ── Invites ─────────────────────────────────────────────────────────────── */

export const INVITE_EXPIRY_DAYS = [1, 7, 14] as const

export type InviteDraft = { ok: true; body: AssistantInviteCreate } | { ok: false; error: string }

/** The create-invite request from the form's raw values; never coerces a bad value into a plausible one. */
export function inviteBody(role: string, days: string): InviteDraft {
  const r = ROLES.find((x) => x === role)
  if (!r) return { ok: false, error: "Choose a role." }
  const n = Number(days)
  const d = INVITE_EXPIRY_DAYS.find((x) => x === n)
  if (!d) return { ok: false, error: "Choose how long the code works." }
  return { ok: true, body: { role: r, expiresInDays: d } }
}

/* ── Joining a team ──────────────────────────────────────────────────────── */

/** Longest code the backend accepts (`RedeemAssistantInviteRequestDTO`). */
export const JOIN_CODE_MAX = 32

export type JoinDraft = { ok: true; code: string } | { ok: false; error: string }

/** Codes are pasted from messages, so surrounding whitespace goes; the code itself is sent as typed. */
export function joinCodeDraft(raw: string): JoinDraft {
  const code = raw.trim()
  if (code === "") return { ok: false, error: "Enter the code you were sent." }
  if (code.length > JOIN_CODE_MAX) return { ok: false, error: `Codes are ${JOIN_CODE_MAX} characters or fewer.` }
  return { ok: true, code }
}

export function joinedMessage(teacherName: string, role: AssistantRole): string {
  return `You're now on ${teacherName}'s team as ${ROLE_COPY[role].label.toLowerCase()}.`
}

/* ── Failure copy (none of these charge anything) ────────────────────────── */

const statusOf = (err: unknown) => (err instanceof ApiError ? err.status : -1)

export function assistantFailureMessage(err: unknown, action: string): string {
  const status = statusOf(err)
  if (status === 0) return "You're offline. Nothing was saved. Try again when you're back online."
  if (status === 403) return "Only the lead teacher can manage assistants."
  if (status === 404) return "That assistant or invite isn't there any more. Reload the page to see the current list."
  if (status === 429) return "Too many attempts. Wait a minute and try again."
  if (status === 422) {
    const code = billingErrorCode(err)
    if (code === "invalid_permissions") return "Choose only the permissions listed, then save again."
    if (code === "invalid_cap") return "The credit limit must be a whole number, zero or more."
    return `Couldn't ${action}. Check the details and try again.`
  }
  if (status === 409) {
    if (billingErrorCode(err) === "invite_limit") return "You have too many open invites. Revoke one you no longer need, then try again."
    return "That change isn't possible right now. Reload the page and try again."
  }
  return `Couldn't ${action}. Try again.`
}

export function joinFailureMessage(err: unknown): string {
  const status = statusOf(err)
  if (status === 404) return "That code isn't valid or has expired. Ask for a new one."
  if (status === 0) return "You're offline. Try again when you're back online."
  if (status === 403) return "Only teacher accounts can join a team."
  if (status === 429) return "Too many attempts. Wait a minute and try again."
  if (status === 409 && billingErrorCode(err) === "invite_already_redeemed") return "That code has already been used. Ask for a new one."
  return "Couldn't join that team. Check the code and try again."
}
