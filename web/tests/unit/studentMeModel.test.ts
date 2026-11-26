import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import {
  accountRows,
  activityVm,
  deriveBadges,
  displayName,
  heroName,
  isBoardSettled,
  levelLine,
  ordinal,
  peopleVm,
  resolveRankingsOff,
  standingsRank,
  standingsSub,
  statsVm,
  streakLine,
  streakStrip,
  subjectsVm,
} from "@/portals/student/home/me/meModel"
import type { XpProfile } from "@/lib/xpTypes"
import { makeHome } from "./studentHomeFixture"

function xp(overrides: Partial<XpProfile> = {}): XpProfile {
  return {
    totalXp: 2240,
    level: 7,
    levelStartXp: 2000,
    nextLevelXp: 2500,
    streak: { current: 9, longest: 14, lastActiveOn: "2026-11-12", freezesAvailable: 1 },
    week: { total: 0, start: "2026-11-09", end: "2026-11-15", bySource: [] },
    calendar: [
      { day: "2026-11-12", xp: 30 },
      { day: "2026-11-11", xp: 10 },
    ],
    calendarStart: "2026-10-16",
    calendarEnd: "2026-11-12",
    ...overrides,
  } as XpProfile
}

describe("Me view model", () => {
  it("names the student with the live fallback chain", () => {
    expect(displayName({ displayName: "Mariam Adel", email: "m@x.com" })).toBe("Mariam Adel")
    expect(displayName({ displayName: null, email: "mariam@x.com" })).toBe("mariam")
    expect(displayName(undefined)).toBe("You")
  })

  it("shows only the first name in the hero so it never wraps at 390", () => {
    expect(heroName({ displayName: "Mariam Adel Hassan", email: "m@x.com" })).toBe("Mariam")
    expect(heroName({ displayName: null, email: "mariam@x.com" })).toBe("mariam")
    expect(heroName(undefined)).toBe("You")
  })

  it("level line reads the server's curve, never computes one", () => {
    expect(levelLine(xp())).toBe("Level 7 · 260 XP to level 8")
  })

  it("14-day streak strip ends today", () => {
    const strip = streakStrip(xp())
    expect(strip).toHaveLength(14)
    expect(strip[13]).toEqual({ day: "2026-11-12", on: true, now: true })
    expect(strip[12]).toEqual({ day: "2026-11-11", on: true, now: false })
    expect(strip[11]!.on).toBe(false)
    expect(streakLine(xp())).toEqual({ main: "9-day streak", best: "best 14" })
    expect(streakLine(xp({ streak: { current: 0, longest: 0, lastActiveOn: null, freezesAvailable: 0 } }))).toEqual({
      main: "Start a streak today",
      best: null,
    })
  })

  it("stats", () => {
    expect(statsVm(makeHome())).toEqual([
      { value: "22", label: "papers marked", to: "/student/subject/0580", grade: null },
      { value: "+64", label: "marks won back", to: "/student/practice/0580?topic=Vectors", grade: null },
      { value: "A", label: "best grade", to: "/student/subject/0580", grade: "A" },
    ])
    const fresh = makeHome({ stats: { papersMarked: 0, marksWonBack: 0, bestGrade: null }, recentPapers: [], floor: [], winBack: [] })
    expect(statsVm(fresh).map((s) => s.value)).toEqual(["0", "0", "–"])
  })

  it("badges are derived from real data only", () => {
    const badges = deriveBadges(makeHome(), xp())
    expect(badges.map((b) => [b.id, b.earned])).toEqual([
      ["first-paper", true],
      ["streak-7", true],
      ["grade-up", true],
      ["streak-30", false],
      ["a-star", false],
    ])
    const none = deriveBadges(
      makeHome({ stats: { papersMarked: 0, marksWonBack: 0, bestGrade: null }, floor: [] }),
      xp({ streak: { current: 0, longest: 0, lastActiveOn: null, freezesAvailable: 0 } }),
    )
    expect(none.every((b) => !b.earned)).toBe(true)
  })

  it("people doors", () => {
    expect(ordinal(1)).toBe("1st")
    expect(ordinal(3)).toBe("3rd")
    expect(ordinal(11)).toBe("11th")
    expect(ordinal(22)).toBe("22nd")
    const doors = peopleVm({ classes: 2, rank: 3, rankingsOff: false, friends: 4, parents: 1 })
    expect(doors.map((d) => [d.label, d.sub, d.to])).toEqual([
      ["Classes", "2 classes", "/student/classes"],
      ["Standings", "3rd", "/student/board"],
      ["Friends", "4 friends", "/student/friends"],
      ["Parents", "1 linked", "/student/parents"],
    ])
    expect(peopleVm({ classes: undefined, rank: null, rankingsOff: false, friends: 0, parents: 0 }).map((d) => d.sub)).toEqual([
      null,
      "Join a class",
      "Add a friend",
      "Invite a parent",
    ])
  })

  it("standings door: a student who turned rankings off sees Rankings off and the door opens the board that holds the switch", () => {
    const off = peopleVm({ classes: 2, rank: null, rankingsOff: true, friends: 4, parents: 1 })
    expect(off[1]).toMatchObject({ id: "standings", label: "Standings", sub: "Rankings off", to: "/student/board" })
  })

  it("standings door: a student with no class and rankings on still sees Join a class", () => {
    const noClass = peopleVm({ classes: 0, rank: null, rankingsOff: false, friends: 0, parents: 0 })
    expect(noClass[1]).toMatchObject({ id: "standings", sub: "Join a class", to: "/student/board" })
  })

  it("standings door: opting out wins over having no class, and over a stale rank", () => {
    expect(standingsSub(null, true)).toBe("Rankings off")
    expect(standingsSub(3, true)).toBe("Rankings off")
    expect(standingsSub(undefined, true)).toBe("Rankings off")
  })

  it("standingsSub: an unknown rank or an unread setting says nothing, a known rank reads as an ordinal", () => {
    expect(standingsSub(undefined, false)).toBeNull()
    expect(standingsSub(undefined, undefined)).toBeNull()
    expect(standingsSub(null, undefined)).toBeNull()
    expect(standingsSub(3, undefined)).toBe("3rd")
    expect(standingsSub(1, false)).toBe("1st")
  })

  it("standingsRank: null (Join a class) only once the classes have loaded and there are none", () => {
    const board = { viewer: { rank: 3 } }
    expect(standingsRank({ classes: undefined, board: undefined, boardSettled: true })).toBeUndefined()
    expect(standingsRank({ classes: undefined, board, boardSettled: true })).toBeUndefined()
    expect(standingsRank({ classes: 0, board: undefined, boardSettled: true })).toBeNull()
    expect(standingsRank({ classes: 2, board: undefined, boardSettled: true })).toBeUndefined()
    expect(standingsRank({ classes: 2, board, boardSettled: true })).toBe(3)
  })

  it("standingsRank: a student who has a class never reads Join a class, whatever is still loading or unranked", () => {
    const door = (input: Omit<Parameters<typeof standingsRank>[0], "boardSettled">) =>
      peopleVm({
        classes: input.classes,
        rank: standingsRank({ ...input, boardSettled: true }),
        rankingsOff: false,
        friends: 0,
        parents: 0,
      })[1]!.sub
    // classes still loading (the first transient wrong case), board not yet fetched: nothing is said
    expect(door({ classes: undefined, board: undefined })).toBeNull()
    expect(door({ classes: 2, board: undefined })).toBeNull()
    // the board is in and holds no rank for them (no XP this week): never Join a class
    expect(door({ classes: 2, board: { viewer: { rank: null } } })).not.toBe("Join a class")
    expect(door({ classes: 2, board: { viewer: null } })).not.toBe("Join a class")
    expect(door({ classes: 2, board: { viewer: { rank: 1 } } })).toBe("1st")
    expect(door({ classes: 0, board: undefined })).toBe("Join a class")
  })

  it("standingsRank: a classed student the loaded board has no rank for is unranked, a board still loading is unknown", () => {
    expect(standingsRank({ classes: 2, board: { viewer: { rank: null } }, boardSettled: true })).toBe("unranked")
    expect(standingsRank({ classes: 2, board: { viewer: null }, boardSettled: true })).toBe("unranked")
    expect(standingsRank({ classes: 2, board: undefined, boardSettled: true })).toBeUndefined()
    expect(standingsRank({ classes: undefined, board: { viewer: { rank: null } }, boardSettled: true })).toBeUndefined()
    expect(standingsRank({ classes: 0, board: { viewer: { rank: null } }, boardSettled: true })).toBeNull()
  })

  it("standingsSub: unranked reads Not ranked yet unless rankings are off or the setting is unread", () => {
    expect(standingsSub("unranked", false)).toBe("Not ranked yet")
    expect(standingsSub("unranked", true)).toBe("Rankings off")
    expect(standingsSub("unranked", undefined)).toBeNull()
  })

  it("standings door: all four states, from the inputs MeScreen has", () => {
    // Mirrors MeScreen: classes, board and the student's own opt-out go in; the Standings sub comes out.
    const standings = (input: {
      classes: number | undefined
      board: { viewer: { rank: number | null } | null; viewerOptedOut: boolean } | undefined
      optOut: boolean | undefined
      fetching?: boolean
    }) =>
      peopleVm({
        classes: input.classes,
        rank: standingsRank({ classes: input.classes, board: input.board, boardSettled: !(input.fetching ?? false) }),
        rankingsOff: resolveRankingsOff({
          profileOptOut: input.optOut,
          boardOptedOut: input.board?.viewerOptedOut,
          profileFailed: false,
        }),
        friends: 0,
        parents: 0,
      })[1]!
    // a class, rankings on, no XP this week: Not ranked yet
    expect(standings({ classes: 2, board: { viewer: { rank: null }, viewerOptedOut: false }, optOut: false })).toMatchObject({
      label: "Standings",
      sub: "Not ranked yet",
      to: "/student/board",
    })
    // opted out wins, with a class and no rank, and with no class at all
    expect(standings({ classes: 2, board: { viewer: { rank: null }, viewerOptedOut: true }, optOut: true }).sub).toBe("Rankings off")
    expect(standings({ classes: 0, board: undefined, optOut: true }).sub).toBe("Rankings off")
    // no class, rankings on: Join a class
    expect(standings({ classes: 0, board: undefined, optOut: false }).sub).toBe("Join a class")
    // loading: nothing
    expect(standings({ classes: undefined, board: undefined, optOut: undefined }).sub).toBeNull()
    expect(standings({ classes: 2, board: undefined, optOut: false }).sub).toBeNull()
    // ranked: the ordinal
    expect(standings({ classes: 2, board: { viewer: { rank: 4 }, viewerOptedOut: false }, optOut: false }).sub).toBe("4th")
  })

  it("standings door: a cached board with no rank, being fetched again, says nothing instead of Not ranked yet", () => {
    // After "Show me again" the cached class board is still the opted-out period's (viewer.rank null) while the profile
    // already says rankings are on. Until the refetch lands the door must not claim "Not ranked yet".
    const stale = { viewer: { rank: null }, viewerOptedOut: false }
    const standings = (fetching: boolean, board: { viewer: { rank: number | null } | null; viewerOptedOut: boolean }) =>
      peopleVm({
        classes: 2,
        rank: standingsRank({ classes: 2, board, boardSettled: !fetching }),
        rankingsOff: resolveRankingsOff({ profileOptOut: false, boardOptedOut: board.viewerOptedOut, profileFailed: false }),
        friends: 0,
        parents: 0,
      })[1]!.sub
    expect(standings(true, stale)).toBeNull()
    expect(standings(true, { viewer: null, viewerOptedOut: false })).toBeNull()
    // settled: the same board is a claim again
    expect(standings(false, stale)).toBe("Not ranked yet")
    expect(standings(false, { viewer: null, viewerOptedOut: false })).toBe("Not ranked yet")
    // a cached number is still a number while it refreshes
    expect(standings(true, { viewer: { rank: 4 }, viewerOptedOut: false })).toBe("4th")
  })

  it("rankings-off state reads the student's own setting first, then the board, then assumes on only after a failed read", () => {
    expect(resolveRankingsOff({ profileOptOut: true, boardOptedOut: false, profileFailed: false })).toBe(true)
    expect(resolveRankingsOff({ profileOptOut: false, boardOptedOut: true, profileFailed: false })).toBe(false)
    expect(resolveRankingsOff({ profileOptOut: undefined, boardOptedOut: true, profileFailed: false })).toBe(true)
    expect(resolveRankingsOff({ profileOptOut: undefined, boardOptedOut: undefined, profileFailed: false })).toBeUndefined()
    expect(resolveRankingsOff({ profileOptOut: undefined, boardOptedOut: undefined, profileFailed: true })).toBe(false)
  })

  it("MeScreen feeds the door from the student profile's leaderboardOptOut", () => {
    const screen = readFileSync(join(process.cwd(), "src/portals/student/home/me/MeScreen.tsx"), "utf8")
    expect(screen).toContain("useStudentProfile()")
    expect(screen).toContain("profileOptOut: studentProfile.data?.profile.leaderboardOptOut")
    expect(screen).toMatch(/rankingsOff,\s+friends:/)
  })

  it("MeScreen derives the rank from the loaded classes, never from firstClass alone", () => {
    const screen = readFileSync(join(process.cwd(), "src/portals/student/home/me/MeScreen.tsx"), "utf8")
    expect(screen).toContain("classes: classes.data?.classes.length")
    expect(screen).toContain("board: board.data")
    expect(screen).not.toMatch(/rank:\s*firstClass/)
  })

  it("isBoardSettled: only an idle query with no error is settled, so offline and a failed refetch stay unknown", () => {
    expect(isBoardSettled({ fetchStatus: "idle", isError: false })).toBe(true)
    expect(isBoardSettled({ fetchStatus: "fetching", isError: false })).toBe(false)
    // offline: the refetch is paused, isFetching is false, yet the cached board is still the stale one
    expect(isBoardSettled({ fetchStatus: "paused", isError: false })).toBe(false)
    // a failed refetch keeps its old data and goes idle with isError
    expect(isBoardSettled({ fetchStatus: "idle", isError: true })).toBe(false)
  })

  it("standings door: a stale opted-out board reads nothing while offline or after a failed refetch, Not ranked yet once settled", () => {
    const stale = { viewer: { rank: null }, viewerOptedOut: false }
    const sub = (query: { fetchStatus: "fetching" | "paused" | "idle"; isError: boolean }) =>
      peopleVm({
        classes: 2,
        rank: standingsRank({ classes: 2, board: stale, boardSettled: isBoardSettled(query) }),
        rankingsOff: resolveRankingsOff({ profileOptOut: false, boardOptedOut: stale.viewerOptedOut, profileFailed: false }),
        friends: 0,
        parents: 0,
      })[1]!.sub
    expect(sub({ fetchStatus: "paused", isError: false })).toBeNull()
    expect(sub({ fetchStatus: "idle", isError: true })).toBeNull()
    expect(sub({ fetchStatus: "fetching", isError: false })).toBeNull()
    expect(sub({ fetchStatus: "idle", isError: false })).toBe("Not ranked yet")
  })

  it("MeScreen tells standingsRank whether the class board has settled, from the query's fetchStatus and error", () => {
    const screen = readFileSync(join(process.cwd(), "src/portals/student/home/me/MeScreen.tsx"), "utf8")
    expect(screen).toContain("boardSettled: isBoardSettled(board)")
    expect(screen).not.toContain("board.isFetching")
  })

  it("subjects and activity", () => {
    expect(subjectsVm(makeHome())[2]).toEqual({
      grade: "B",
      title: "Additional Mathematics",
      sub: "0606 · 2 papers · 9 marks to A",
      to: "/student/subject/0606",
    })
    const home = makeHome({ activity: [{ kind: "paper", title: "Paper marked", sub: "Mathematics P4 · B", at: "2026-11-10T10:00:00+00:00" }] })
    expect(activityVm(home)).toEqual([{ kind: "paper", title: "Paper marked", sub: "Mathematics P4 · B", when: "2 days ago" }])
  })

  it("account rows keep tutoring, placement, settings, notifications and recently deleted", () => {
    const rows = accountRows({ deletedCount: 2, placementCode: "0580" })
    expect(rows.map((r) => [r.label, r.sub, r.to])).toEqual([
      ["Tutoring", "Book a session", "/student/tutors"],
      ["Placement test", "Find your starting level", "/student/placement/0580"],
      ["Profile and settings", null, "/student/settings"],
      ["Notifications", null, "/student/notifications"],
      ["Recently deleted", "2 papers", "/student/recently-deleted"],
    ])
    expect(accountRows({ deletedCount: 0, placementCode: null }).map((r) => r.label)).not.toContain("Placement test")
  })
})
