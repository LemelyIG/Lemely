import { beforeEach, describe, expect, it, vi } from "vitest"

/*
 * Every write that changes seats, scope, caps or assistants must refresh the team screen, and
 * a seat purchase or reduction must refresh billing as well. The hooks are driven with
 * react-query stubbed so each `onSuccess` is the real one.
 */
const qc = vi.hoisted(() => ({ invalidateQueries: vi.fn() }))
const captured = vi.hoisted(() => ({ options: null as null | { onSuccess?: () => unknown } }))
vi.mock("@tanstack/react-query", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-query")>()),
  useQueryClient: () => qc,
  useMutation: (options: { onSuccess?: () => unknown }) => {
    captured.options = options
    return {}
  },
}))

import { BILLING_SUCCESS_KEYS, useAddSeats, useReduceSeats } from "@/lib/hooks/useBillingApi"
import {
  TEAM_WRITE_KEYS,
  invalidateTeam,
  teamKeys,
  useCreateAssistantInvite,
  useJoinTeam,
  useRemoveAssistant,
  useRemoveSeat,
  useRevokeAssistantInvite,
  useSetAssistantRole,
  useSetMemberCap,
  useSetSeatScope,
} from "@/lib/hooks/useTeamApi"

const invalidated = () => qc.invalidateQueries.mock.calls.map((c) => (c[0] as { queryKey: readonly unknown[] }).queryKey)
beforeEach(() => {
  qc.invalidateQueries.mockReset()
  captured.options = null
})

describe("team writes", () => {
  it("refreshes the team key from the exported list", () => {
    expect(TEAM_WRITE_KEYS).toEqual([teamKeys.team])
    invalidateTeam(qc as never)
    expect(invalidated()).toEqual([["team"]])
  })

  const writes = {
    useSetSeatScope,
    useSetMemberCap,
    useRemoveSeat,
    useCreateAssistantInvite,
    useRevokeAssistantInvite,
    useSetAssistantRole,
    useRemoveAssistant,
    useJoinTeam,
  }
  for (const [name, hook] of Object.entries(writes)) {
    it(`${name} refreshes the team on success`, () => {
      hook()
      captured.options?.onSuccess?.()
      expect(invalidated()).toEqual([["team"]])
    })
  }
})

describe("seat purchases", () => {
  it("useReduceSeats refreshes billing and the team", () => {
    useReduceSeats()
    captured.options?.onSuccess?.()
    const keys = invalidated().map((k) => JSON.stringify(k))
    for (const k of BILLING_SUCCESS_KEYS) expect(keys).toContain(JSON.stringify(k))
    expect(keys).toContain(JSON.stringify(["team"]))
  })

  // Adding seats leaves for Paymob's checkout: nothing changes until the return page sees paid.
  it("useAddSeats refreshes nothing on success", () => {
    useAddSeats()
    expect(captured.options?.onSuccess).toBeUndefined()
    captured.options?.onSuccess?.()
    expect(invalidated()).toEqual([])
  })
})
