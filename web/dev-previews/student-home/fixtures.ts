/*
 * Demo data for the student home preview. Not product data: every page that
 * uses it says "Demo data". Real CAIE subject codes, plausible paper labels.
 * "Today" is fixed at 2026-11-05 10:00 local so states never drift.
 */
import type { BinnyMood, HomeFacts, LatestResult, NextActionKind, XpDay } from "@/portals/student/home/model"

export const STATES = [
  "populated", "result-in", "new", "one-paper", "marking", "no-plan", "no-exams", "streak-zero", "loading", "error",
] as const
export type StateId = (typeof STATES)[number]

export const NOW = new Date(2026, 10, 5, 10, 0)

/** Nine-day streak ending today. */
const NINE_DAYS: XpDay[] = [
  { day: "2026-10-28", xp: 40 }, { day: "2026-10-29", xp: 25 }, { day: "2026-10-30", xp: 60 },
  { day: "2026-10-31", xp: 20 }, { day: "2026-11-01", xp: 35 }, { day: "2026-11-02", xp: 50 },
  { day: "2026-11-03", xp: 30 }, { day: "2026-11-04", xp: 120 }, { day: "2026-11-05", xp: 25 },
]

// Yesterday 18:00, 16 h before NOW: grade A, up from B.
const POPULATED_RESULT: LatestResult = {
  subjectCode: "0580",
  grade: "A",
  paperId: "p-0580-42",
  paperLabel: "0580/42 · m/j 2024",
  seen: true,
  recordedAt: new Date(2026, 10, 4, 18, 0).toISOString(),
}

const populated: HomeFacts = {
  now: NOW,
  activeUpload: null,
  subjects: [
    { code: "0580", papers: 14, grade: "A", previousGrade: "B", nextExamOn: "2027-05-12" },
    { code: "0606", papers: 6, grade: "B", previousGrade: "B", nextExamOn: "2027-05-18" },
    { code: "0625", papers: 2, grade: "C", previousGrade: "D", nextExamOn: "2027-05-04" },
  ],
  upcomingSessions: [
    { sessionId: "s1", subjectCode: "0606", title: "Quadratic inequalities", minutes: 25, scheduledFor: "2026-11-05" },
    { sessionId: "s2", subjectCode: "0580", title: "Vectors", minutes: 20, scheduledFor: "2026-11-06" },
  ],
  weakTopics: [
    { topic: "Waves", subjectCode: "0625", acc: 54 },
    { topic: "Quadratic inequalities", subjectCode: "0606", acc: 58 },
    { topic: "Vectors", subjectCode: "0580", acc: 63 },
    { topic: "Moments", subjectCode: "0625", acc: 66 },
  ],
  latestResult: POPULATED_RESULT,
  calendar: NINE_DAYS,
}

type Fixture = { facts: HomeFacts; expected: { action: NextActionKind; mood: BinnyMood } }

export const FIXTURES: Record<StateId, Fixture> = {
  populated: { facts: populated, expected: { action: "session", mood: "grade-improved" } },
  "result-in": {
    facts: { ...populated, latestResult: { ...POPULATED_RESULT, seen: false } },
    expected: { action: "result", mood: "grade-improved" },
  },
  new: {
    facts: { now: NOW, activeUpload: null, subjects: [], upcomingSessions: [], weakTopics: [], latestResult: null, calendar: [] },
    expected: { action: "first-paper", mood: "idle" },
  },
  "one-paper": {
    facts: {
      now: NOW,
      activeUpload: null,
      subjects: [{ code: "0580", papers: 1, grade: "B", previousGrade: null, nextExamOn: "2027-05-12" }],
      upcomingSessions: [],
      weakTopics: [{ topic: "Vectors", subjectCode: "0580", acc: 50 }],
      latestResult: {
        subjectCode: "0580",
        grade: "B",
        paperId: "p-0580-42",
        paperLabel: "0580/42 · m/j 2024",
        seen: true,
        recordedAt: new Date(2026, 10, 2, 17, 0).toISOString(),
      },
      calendar: [{ day: "2026-11-02", xp: 50 }],
    },
    expected: { action: "practice", mood: "idle" },
  },
  marking: {
    facts: { ...populated, activeUpload: { paperLabel: "0625/42" } },
    expected: { action: "marking", mood: "marking" },
  },
  "no-plan": { facts: { ...populated, upcomingSessions: [] }, expected: { action: "practice", mood: "grade-improved" } },
  "no-exams": {
    facts: { ...populated, subjects: populated.subjects.map((s) => ({ ...s, nextExamOn: null })) },
    expected: { action: "session", mood: "grade-improved" },
  },
  "streak-zero": {
    facts: {
      ...populated,
      latestResult: {
        subjectCode: "0580",
        grade: "A",
        paperId: "p-0580-42",
        paperLabel: "0580/42 · m/j 2024",
        seen: true,
        recordedAt: new Date(2026, 10, 1, 18, 0).toISOString(),
      },
      calendar: NINE_DAYS.filter((d) => d.day <= "2026-11-03"),
    },
    expected: { action: "session", mood: "idle" },
  },
  // Loading and error render their own blocks; the facts only keep the
  // controller's code path uniform.
  loading: { facts: populated, expected: { action: "session", mood: "grade-improved" } },
  error: { facts: populated, expected: { action: "session", mood: "grade-improved" } },
}
