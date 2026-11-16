import { describe, expect, it } from "vitest"
import type { StudentExamCalendar } from "@/lib/announcementTypes"
import {
  activityLabel,
  addDays,
  basedOnLine,
  daysAgo,
  examLine,
  formatMinutes,
  nextExamForSubject,
  reasonLine,
  refusalCopy,
  spokenMinutes,
  startAction,
  weekdayLong,
  weekdayShort,
  whyBody,
  whyTopicsHint,
} from "@/portals/student/screens/studyplan/planCopy"

const calendar = (entries: { code: string; paper: number; dates: string[] }[]): StudentExamCalendar => ({
  availability: "available",
  entries: entries.map((e) => ({
    subjectCode: e.code,
    sessionMonth: null,
    sessionYear: null,
    paperNumber: e.paper,
    availability: "dated",
    dates: e.dates.map((d) => ({ paperVariant: "42", examDate: d, startsAtLocal: null, durationMinutes: null, source: "t" })),
  })),
})
const THU = new Date("2026-08-06T12:00:00")

describe("labels and minutes", () => {
  it("labels activities and keeps an unknown one verbatim", () => {
    expect(activityLabel("practice")).toBe("Practice set")
    expect(activityLabel("flashcards")).toBe("Flashcards")
    expect(activityLabel("past_paper")).toBe("Past paper")
    expect(activityLabel("review")).toBe("Review")
    expect(activityLabel("mystery")).toBe("mystery")
  })
  it("formats minutes", () => {
    expect(formatMinutes(0)).toBe("0 min")
    expect(formatMinutes(10)).toBe("10 min")
    expect(formatMinutes(60)).toBe("1 h")
    expect(formatMinutes(115)).toBe("1 h 55 min")
    expect(spokenMinutes(1)).toBe("1 minute")
    expect(spokenMinutes(15)).toBe("15 minutes")
    expect(spokenMinutes(75)).toBe("1 h 15 min")
  })
})

describe("dates", () => {
  it("names weekdays from bare ISO dates without a timezone shift", () => {
    expect(weekdayShort("2026-08-06")).toBe("Thu")
    expect(weekdayLong("2026-08-06")).toBe("Thursday")
    expect(weekdayShort("not-a-date")).toBe("not-a-date")
  })
  it("adds days across a month end", () => {
    expect(addDays("2026-08-31", 1)).toBe("2026-09-01")
    expect(addDays("2026-08-06", -3)).toBe("2026-08-03")
  })
  it("says how long ago", () => {
    expect(daysAgo(0)).toBe("today")
    expect(daysAgo(1)).toBe("yesterday")
    expect(daysAgo(9)).toBe("9 days ago")
  })
})

describe("reasons", () => {
  it("writes the short row line per kind, singular and plural", () => {
    expect(reasonLine({ kind: "marks_lost", count: 9 })).toBe("Cost you 9 marks")
    expect(reasonLine({ kind: "marks_lost", count: 1 })).toBe("Cost you 1 mark")
    expect(reasonLine({ kind: "cards_due", count: 12 })).toBe("12 cards due")
    expect(reasonLine({ kind: "cards_due", count: 1 })).toBe("1 card due")
    expect(reasonLine({ kind: "last_paper", count: 9 })).toBe("Your last paper was 9 days ago")
    expect(reasonLine(null)).toBeNull()
  })
  it("writes the sheet's why, never guessing when there is no reason", () => {
    expect(whyBody({ reason: { kind: "marks_lost", count: 9 }, topic: "Vectors", targetGrade: "A*" })).toBe(
      "Vectors has cost you 9 marks so far. Win them back on the way to your A*.",
    )
    expect(whyBody({ reason: { kind: "marks_lost", count: 9 }, topic: "Vectors", targetGrade: null })).toBe(
      "Vectors has cost you 9 marks so far.",
    )
    expect(whyBody({ reason: { kind: "cards_due", count: 12 }, topic: "Waves", targetGrade: null })).toBe(
      "12 Waves cards are due today.",
    )
    expect(whyBody({ reason: { kind: "cards_due", count: 1 }, topic: "Waves", targetGrade: null })).toBe(
      "1 Waves card is due today.",
    )
    expect(whyBody({ reason: { kind: "last_paper", count: 9 }, topic: "x", targetGrade: null })).toBe(
      "A full paper keeps your timing sharp. Your last one was 9 days ago.",
    )
    expect(whyBody({ reason: null, topic: "x", targetGrade: "A" })).toBe(
      "Picked from your placement test or your topic ratings.",
    )
  })
})

describe("startAction", () => {
  it("routes each activity and offers nothing for review", () => {
    expect(startAction("practice", "0580", { kind: "marks_lost", count: 9 })).toEqual({
      label: "Start · +9 marks",
      path: "/student/practice/0580",
    })
    expect(startAction("practice", "0580", { kind: "marks_lost", count: 1 })?.label).toBe("Start · +1 mark")
    expect(startAction("practice", "0580", null)).toEqual({ label: "Start", path: "/student/practice/0580" })
    expect(startAction("flashcards", "0625", { kind: "cards_due", count: 12 })).toEqual({
      label: "Start · 12 cards",
      path: "/student/flashcards/0625",
    })
    expect(startAction("past_paper", "0625", null)).toEqual({ label: "Start", path: "/student/correct" })
    expect(startAction("review", "0625", { kind: "marks_lost", count: 3 })).toBeNull()
  })
})

describe("exams", () => {
  it("finds the soonest future date for one subject", () => {
    const cal = calendar([
      { code: "0580", paper: 2, dates: ["2027-03-01"] },
      { code: "0580", paper: 4, dates: ["2027-02-10", "2026-07-01"] },
      { code: "0625", paper: 4, dates: ["2026-09-01"] },
    ])
    expect(nextExamForSubject(cal, "0580", THU)).toEqual({ date: "2027-02-10", paperNumber: 4 })
    expect(nextExamForSubject(cal, "0606", THU)).toBeNull()
    expect(nextExamForSubject(undefined, "0580", THU)).toBeNull()
  })
  it("words the countdown", () => {
    expect(examLine({ date: "2027-02-10", paperNumber: 4 }, THU)).toBe("Paper 4 in 188 days")
    expect(examLine({ date: "2026-08-06", paperNumber: 2 }, THU)).toBe("Paper 2 today")
    expect(examLine({ date: "2026-08-07", paperNumber: 2 }, THU)).toBe("Paper 2 tomorrow")
  })
})

describe("plan lines", () => {
  it("says what the plan is built from", () => {
    expect(basedOnLine(4)).toBe("Built from your 4 papers and weak topics")
    expect(basedOnLine(1)).toBe("Built from your 1 paper and weak topics")
    expect(basedOnLine(0)).toBe("Built from your weak topics and ratings")
    expect(whyTopicsHint("Mathematics", 4)).toBe("Your weakest Mathematics topics from 4 papers.")
    expect(whyTopicsHint("Mathematics", 0)).toBe("Your weakest Mathematics topics so far.")
  })
  it("words each refusal, naming the unknown one rather than hiding it", () => {
    expect(refusalCopy("no_signal").heading).toBe("I need a paper first")
    expect(refusalCopy("quota").heading).toBe("I couldn’t plan this week")
    expect(refusalCopy(null).heading).toBe("I couldn’t plan this week")
  })
})
