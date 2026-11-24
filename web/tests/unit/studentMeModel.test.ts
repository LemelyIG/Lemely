import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import {
  accountRows,
  activityVm,
  deriveBadges,
  displayName,
  heroName,
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
    expect(standingsRank({ classes: undefined, board: undefined })).toBeUndefined()
    expect(standingsRank({ classes: undefined, board })).toBeUndefined()
    expect(standingsRank({ classes: 0, board: undefined })).toBeNull()
    expect(standingsRank({ classes: 2, board: undefined })).toBeUndefined()
    expect(standingsRank({ classes: 2, board })).toBe(3)
  })

  it("standingsRank: a student who has a class never reads Join a class, whatever is still loading or unranked", () => {
    const door = (input: Parameters<typeof standingsRank>[0]) =>
      peopleVm({ classes: input.classes, rank: standingsRank(input), rankingsOff: false, friends: 0, parents: 0 })[1]!.sub
    // classes still loading (the first transient wrong case), board not yet fetched, no XP this week (viewer rank null)
    expect(door({ classes: undefined, board: undefined })).toBeNull()
    expect(door({ classes: 2, board: undefined })).toBeNull()
    expect(door({ classes: 2, board: { viewer: { rank: null } } })).toBeNull()
    expect(door({ classes: 2, board: { viewer: null } })).toBeNull()
    expect(door({ classes: 2, board: { viewer: { rank: 1 } } })).toBe("1st")
    expect(door({ classes: 0, board: undefined })).toBe("Join a class")
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
    expect(screen).toContain("standingsRank({ classes: classes.data?.classes.length, board: board.data })")
    expect(screen).not.toMatch(/rank:\s*firstClass/)
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
