import { describe, expect, it } from "vitest"
import {
  daysUntil,
  formatCountdown,
  nextExam,
  readStateFor,
} from "@/portals/student/screens/Announcements"
import { applyOptimisticRead } from "@/lib/hooks/useAnnouncementApi"
import type {
  ExamDate,
  StudentAnnouncement,
  StudentAnnouncementsPage,
  StudentExamCalendar,
  StudentExamEntry,
} from "@/lib/announcementTypes"

/*
 * S-28's date logic (P5.8 chunk B).
 *
 * Everything pinned here is a place the screen could quietly invent or misstate
 * a fact a student plans revision around. The countdown is the most prominent
 * number on the screen; if it is off by a day, or counts to an exam that has
 * already happened, it is worse than absent.
 */

function examDate(overrides: Partial<ExamDate> = {}): ExamDate {
  return {
    paperVariant: "42",
    examDate: "2026-05-12",
    startsAtLocal: null,
    durationMinutes: null,
    source: "Cambridge June 2026 timetable",
    ...overrides,
  }
}

function entry(overrides: Partial<StudentExamEntry> = {}): StudentExamEntry {
  return {
    subjectCode: "0625",
    sessionMonth: "May/June",
    sessionYear: 2026,
    paperNumber: 4,
    availability: "dated",
    dates: [examDate()],
    ...overrides,
  }
}

function calendar(entries: StudentExamEntry[]): StudentExamCalendar {
  return { availability: "available", entries }
}

function announcement(
  overrides: Partial<StudentAnnouncement> = {},
): StudentAnnouncement {
  return {
    announcementId: "ann-1",
    scope: "class",
    classId: "class-1",
    schoolId: null,
    title: "Mock exam next week",
    body: "Bring a calculator.",
    publishedAt: "2026-05-01T09:00:00Z",
    readAt: null,
    authorId: "teacher-1",
    ...overrides,
  }
}

function page(announcements: StudentAnnouncement[]): StudentAnnouncementsPage {
  return { announcements }
}

describe("daysUntil", () => {
  it("counts whole calendar days, not elapsed hours", () => {
    // The defect this prevents: a student checking at 23:00 and again at 01:00
    // watching "3 days" become "2 days" overnight when the exam is the same
    // calendar distance away.
    const lateEvening = new Date(2026, 4, 9, 23, 30)
    const smallHours = new Date(2026, 4, 10, 1, 15)
    expect(daysUntil("2026-05-12", lateEvening)).toBe(3)
    expect(daysUntil("2026-05-12", smallHours)).toBe(2)
  })

  it("is 0 on the day of the exam", () => {
    expect(daysUntil("2026-05-12", new Date(2026, 4, 12, 6, 0))).toBe(0)
  })

  it("goes negative once the exam has passed", () => {
    expect(daysUntil("2026-05-12", new Date(2026, 4, 13, 6, 0))).toBe(-1)
  })

  it("counts across a month boundary", () => {
    expect(daysUntil("2026-06-02", new Date(2026, 4, 31, 12, 0))).toBe(2)
  })
})

describe("formatCountdown", () => {
  it("says Today and Tomorrow rather than a bare number", () => {
    expect(formatCountdown(0)).toBe("Today")
    expect(formatCountdown(1)).toBe("Tomorrow")
  })

  it("pluralises everything else", () => {
    expect(formatCountdown(2)).toBe("2 days")
    expect(formatCountdown(41)).toBe("41 days")
  })
})

describe("nextExam", () => {
  const today = new Date(2026, 4, 1, 9, 0)

  it("is null when there is no calendar at all", () => {
    expect(nextExam(undefined, today)).toBeNull()
  })

  it("is null when every declared paper is undated", () => {
    // The normal case while `exam_dates` ships empty. The countdown must render
    // nothing rather than a placeholder hero.
    const undated = entry({ availability: "no_timetable", dates: [] })
    expect(nextExam(calendar([undated]), today)).toBeNull()
  })

  it("picks the soonest future date across every paper", () => {
    const later = entry({
      paperNumber: 4,
      dates: [examDate({ examDate: "2026-05-20", paperVariant: "42" })],
    })
    const sooner = entry({
      paperNumber: 2,
      dates: [examDate({ examDate: "2026-05-06", paperVariant: "22" })],
    })
    const result = nextExam(calendar([later, sooner]), today)
    expect(result?.entry.paperNumber).toBe(2)
    expect(result?.date.paperVariant).toBe("22")
    expect(result?.days).toBe(5)
  })

  it("picks the soonest variant within one paper", () => {
    // A paper number can map to several variants on different days (the
    // timetable's grain is the variant), so the search must descend into the
    // dates list rather than take the first one.
    const multi = entry({
      dates: [
        examDate({ examDate: "2026-05-20", paperVariant: "42" }),
        examDate({ examDate: "2026-05-14", paperVariant: "41" }),
      ],
    })
    expect(nextExam(calendar([multi]), today)?.date.paperVariant).toBe("41")
  })

  it("skips exams that have already happened", () => {
    // Counting down to a past date is the one failure mode worse than showing
    // no countdown at all.
    const past = entry({
      paperNumber: 2,
      dates: [examDate({ examDate: "2026-04-20", paperVariant: "22" })],
    })
    const future = entry({
      paperNumber: 4,
      dates: [examDate({ examDate: "2026-05-14", paperVariant: "41" })],
    })
    const result = nextExam(calendar([past, future]), today)
    expect(result?.date.paperVariant).toBe("41")
    expect(result?.days).toBeGreaterThan(0)
  })

  it("is null when every date is in the past", () => {
    const past = entry({ dates: [examDate({ examDate: "2026-04-20" })] })
    expect(nextExam(calendar([past]), today)).toBeNull()
  })

  it("still counts an exam happening today", () => {
    // 0 is a real countdown ("Today"), not an absence — the boundary must not
    // be filtered out along with the past ones.
    const todayExam = entry({ dates: [examDate({ examDate: "2026-05-01" })] })
    expect(nextExam(calendar([todayExam]), today)?.days).toBe(0)
  })
})

describe("readStateFor", () => {
  // This is the exact decision that used to be conflated with the card's
  // expand toggle: "read" is a fact about `readAt`, not about whether the
  // body happens to be expanded right now.
  it("is unread with no read label when readAt is null", () => {
    expect(readStateFor(announcement({ readAt: null }))).toEqual({
      unread: true,
      readLabel: null,
    })
  })

  it("is read with a formatted label when readAt is set", () => {
    expect(readStateFor(announcement({ readAt: "2026-05-02T08:30:00Z" }))).toEqual({
      unread: false,
      readLabel: "Read on 2 May 2026",
    })
  })
})

describe("applyOptimisticRead", () => {
  it("stamps readAt on the matching announcement only", () => {
    const before = page([
      announcement({ announcementId: "ann-1", readAt: null }),
      announcement({ announcementId: "ann-2", readAt: null }),
    ])
    const after = applyOptimisticRead(before, "ann-1", "2026-05-03T10:00:00Z")
    expect(after.announcements[0].readAt).toBe("2026-05-03T10:00:00Z")
    expect(after.announcements[1].readAt).toBeNull()
  })

  it("does not overwrite an existing readAt with a later optimistic guess", () => {
    // The receipt endpoint is idempotent and first-read-only; if the mutation
    // somehow re-applies (a duplicate click before the first settles), the
    // optimistic write must not push the original timestamp forward.
    const before = page([
      announcement({ announcementId: "ann-1", readAt: "2026-05-02T00:00:00Z" }),
    ])
    const after = applyOptimisticRead(before, "ann-1", "2026-05-03T10:00:00Z")
    expect(after.announcements[0].readAt).toBe("2026-05-02T00:00:00Z")
  })

  it("leaves announcements not matching the id untouched", () => {
    const before = page([announcement({ announcementId: "ann-1", readAt: null })])
    const after = applyOptimisticRead(before, "ann-does-not-exist", "2026-05-03T10:00:00Z")
    expect(after).toEqual(before)
  })
})
