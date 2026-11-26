import { readFileSync } from "node:fs"
import { join } from "node:path"
import { QueryClient } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"
import { invalidateAfterStudentProfileChange } from "@/lib/hooks/useMeApi"
import { stripComments } from "./support/jsxSource"

/*
 * Me's Standings door reads the viewer's class rank. A class board holds no rank for an opted-out student
 * (`viewer.rank: null`), so after "Show me again" a cached board still says "no rank" until it is fetched again.
 * Changing the student profile therefore has to invalidate every cached leaderboard, not only the profile.
 */

const BOARD = ["student", "leaderboard", "class", "total", "c1"] as const
const PROFILE = ["me", "student-profile"] as const

function seeded(): QueryClient {
  const qc = new QueryClient()
  qc.setQueryData(BOARD, { viewer: { rank: null }, viewerOptedOut: true })
  qc.setQueryData(["student", "leaderboard", "friends", "week", null], { viewer: null })
  qc.setQueryData(PROFILE, { profile: { leaderboardOptOut: false } })
  qc.setQueryData(["student", "classes"], { classes: [] })
  return qc
}

describe("student profile change refreshes the boards", () => {
  it("marks every cached leaderboard and the profile stale, and nothing else", () => {
    const qc = seeded()
    invalidateAfterStudentProfileChange(qc)
    expect(qc.getQueryState(BOARD)?.isInvalidated).toBe(true)
    expect(qc.getQueryState(["student", "leaderboard", "friends", "week", null])?.isInvalidated).toBe(true)
    expect(qc.getQueryState(PROFILE)?.isInvalidated).toBe(true)
    expect(qc.getQueryState(["student", "classes"])?.isInvalidated).toBe(false)
  })

  it("usePatchStudentProfile runs it on success, and boards are cached under the key it invalidates", () => {
    const root = join(import.meta.dirname, "..", "..")
    const me = stripComments(readFileSync(join(root, "src/lib/hooks/useMeApi.ts"), "utf8"))
    const patch = /export function usePatchStudentProfile[\s\S]*?\n}\n/.exec(me)?.[0] ?? ""
    expect(patch).toContain("invalidateAfterStudentProfileChange(queryClient)")
    const board = stripComments(readFileSync(join(root, "src/lib/hooks/useLeaderboardApi.ts"), "utf8"))
    expect(board).toContain("queryKey: [...LEADERBOARD_KEY, scope, basis, classId ?? null]")
    expect(board).toContain('export const LEADERBOARD_KEY = ["student", "leaderboard"] as const')
  })
})
