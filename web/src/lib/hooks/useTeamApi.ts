import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request } from "@/lib/api"
import { toTeamView } from "@/lib/billingAdapters"
import type {
  AssistantInviteCreate,
  AssistantRole,
  AssistantRoleUpdate,
  CapUpdate,
  SeatScopeUpdate,
  TeamMembership,
  TeamView,
  WireAssistant,
  WireAssistantInvite,
  WireAssistantUpdate,
  WireMembership,
  WireSeat,
  WireSeatCapacity,
} from "@/lib/billingTypes"
import { billingApi } from "@/lib/hooks/useBillingApi"
import type { ClassList } from "@/lib/teacherTypes"
import { teamRetry } from "@/lib/teamModel"

/*
 * React-query hooks over `/api/teacher/team/*` (plan 03 Task 7). Lead teacher only: billing,
 * seats, caps and assistants are never assistant permissions (spec §2.3, §7). Every write
 * refetches the team, because seat counts, scope and caps are read together on one screen.
 */

const enc = encodeURIComponent
const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) })
const T = "/teacher/team"

export const teamApi = {
  seats: () => request<{ seats: WireSeat[] }>(`${T}/seats`),
  capacity: () => request<WireSeatCapacity>(`${T}/capacity`),
  assistants: () => request<{ assistants: WireAssistant[] }>(`${T}/assistants`),
  invites: () => request<{ invites: WireAssistantInvite[] }>(`${T}/invites`),
  memberships: () => request<{ memberships: WireMembership[] }>(`${T}/memberships`),
  setScope: (memberId: string, body: SeatScopeUpdate) => request<WireSeat>(`${T}/seats/${enc(memberId)}/scope`, json("PUT", body)),
  /** Returns the member's DTO, discriminated by `kind`. */
  setCap: (memberId: string, body: CapUpdate) => request<WireSeat | WireAssistant>(`${T}/members/${enc(memberId)}/cap`, json("PUT", body)),
  /** Starts month-end release: the seat comes back `leaving` with `leavesAt`. */
  removeSeat: (memberId: string) => request<WireSeat>(`${T}/seats/${enc(memberId)}`, { method: "DELETE" }),
  createInvite: (body: AssistantInviteCreate) => request<WireAssistantInvite>(`${T}/assistants/invites`, json("POST", body)),
  revokeInvite: (inviteId: string) => request<void>(`${T}/invites/${enc(inviteId)}`, { method: "DELETE" }),
  updateAssistant: (memberId: string, body: WireAssistantUpdate) =>
    request<WireAssistant>(`${T}/assistants/${enc(memberId)}`, json("PATCH", body)),
  removeAssistant: (memberId: string) => request<void>(`${T}/assistants/${enc(memberId)}`, { method: "DELETE" }),
  redeem: (code: string) => request<WireMembership>(`${T}/assistants/redeem`, json("POST", { code })),
}

export const teamKeys = { team: ["team"] as const }

/** What every team write refreshes. Seat counts, scope and caps are read together on one screen. */
export const TEAM_WRITE_KEYS = [teamKeys.team] as const

/** Call after anything that changes the team: a seat write, or a seat purchase settling. */
export function invalidateTeam(queryClient: Pick<QueryClient, "invalidateQueries">): void {
  for (const queryKey of TEAM_WRITE_KEYS) void queryClient.invalidateQueries({ queryKey })
}

export function useTeam(): UseQueryResult<TeamView, Error> {
  return useQuery({
    queryKey: teamKeys.team,
    // A refusal (an assistant opening the lead teacher's page) will not change on a retry.
    retry: teamRetry,
    queryFn: async () => {
      const [seats, capacity, assistants, invites, summary, classes] = await Promise.all([
        teamApi.seats(),
        teamApi.capacity(),
        teamApi.assistants(),
        teamApi.invites(),
        billingApi.summary(null),
        request<ClassList>("/teacher/classes"),
      ])
      return toTeamView({ seats, capacity, assistants, invites, summary, classes })
    },
  })
}

/** A team the signed-in teacher assists. Names only. */
export interface JoinedTeam {
  memberId: string
  teacherName: string
  role: AssistantRole
}

/**
 * Teams the signed-in teacher assists (`GET /memberships`). Keyed under `["team"]`, so joining a
 * team (which invalidates it) refreshes this list too. Any teacher may read their own memberships.
 */
export function useMemberships(): UseQueryResult<JoinedTeam[], Error> {
  return useQuery({
    queryKey: [...teamKeys.team, "memberships"],
    retry: teamRetry,
    queryFn: async () => {
      const { memberships } = await teamApi.memberships()
      return memberships.map((m) => ({ memberId: m.memberId, teacherName: m.teacherName, role: m.role }))
    },
  })
}

function useTeamWrite<TVars, TData>(fn: (vars: TVars) => Promise<TData>): UseMutationResult<TData, Error, TVars> {
  const qc = useQueryClient()
  return useMutation({ mutationFn: fn, onSuccess: () => invalidateTeam(qc) })
}

export const useSetSeatScope = () =>
  useTeamWrite((v: { memberId: string; body: SeatScopeUpdate }) => teamApi.setScope(v.memberId, v.body))
export const useSetMemberCap = () => useTeamWrite((v: { memberId: string; body: CapUpdate }) => teamApi.setCap(v.memberId, v.body))
export const useRemoveSeat = () => useTeamWrite((memberId: string) => teamApi.removeSeat(memberId))
export const useCreateAssistantInvite = () => useTeamWrite((body: AssistantInviteCreate) => teamApi.createInvite(body))
export const useRevokeAssistantInvite = () => useTeamWrite((inviteId: string) => teamApi.revokeInvite(inviteId))
export const useSetAssistantRole = () =>
  useTeamWrite((v: { memberId: string; body: AssistantRoleUpdate }) =>
    teamApi.updateAssistant(v.memberId, { role: v.body.rolePreset, permissions: v.body.overrides as Record<string, boolean> }),
  )
export const useRemoveAssistant = () => useTeamWrite((memberId: string) => teamApi.removeAssistant(memberId))
export const useJoinTeam = () =>
  useTeamWrite(async (code: string): Promise<TeamMembership> => {
    const m = await teamApi.redeem(code)
    return { teacherName: m.teacherName, role: m.role }
  })
