import type { StudentHome } from "@/lib/studentHomeTypes"

/** A loaded Home for a student with three subjects, mirroring the mock's Mariam. */
export function makeHome(overrides: Partial<StudentHome> = {}): StudentHome {
  return {
    studentName: "Mariam Adel",
    localDate: "2026-11-12",
    localHour: 9,
    moments: [],
    goals: { practice: false, flashcards: false, paperThisWeek: false },
    todaySessions: [],
    week: [
      { day: "2026-11-09", label: "Vectors", done: true, isToday: false },
      { day: "2026-11-10", label: "Waves", done: true, isToday: false },
      { day: "2026-11-11", label: "Flashcards", done: true, isToday: false },
      { day: "2026-11-12", label: "Vectors", done: false, isToday: true },
      { day: "2026-11-13", label: "Paper 4", done: false, isToday: false },
      { day: "2026-11-14", label: null, done: false, isToday: false },
      { day: "2026-11-15", label: null, done: false, isToday: false },
    ],
    streak: { current: 9, longest: 14, lastActiveOn: "2026-11-11", freezesAvailable: 0 },
    nextExamOn: "2027-05-11",
    floor: [
      { code: "0580", name: "Mathematics", grade: "B", previousGrade: "C", nextGrade: "A", pointsToNext: 4, papers: 3 },
      { code: "0625", name: "Physics", grade: "C", previousGrade: null, nextGrade: "B", pointsToNext: 6, papers: 1 },
      { code: "0606", name: "Additional Mathematics", grade: "B", previousGrade: "B", nextGrade: "A", pointsToNext: 9, papers: 2 },
    ],
    winBack: [
      { topic: "Vectors", subjectCode: "0580", subjectName: "Mathematics", marks: 9 },
      { topic: "Waves", subjectCode: "0625", subjectName: "Physics", marks: 7 },
      { topic: "Quadratic inequalities", subjectCode: "0606", subjectName: "Additional Mathematics", marks: 6 },
    ],
    recentPapers: [
      { paperId: "5", subjectCode: "0580", subjectName: "Mathematics", paperNumber: 4, awarded: 61, maximum: 80, grade: "B", recordedAt: "2026-11-10T10:00:00+00:00" },
      { paperId: "3", subjectCode: "0625", subjectName: "Physics", paperNumber: 6, awarded: 27, maximum: 40, grade: "C", recordedAt: "2026-11-04T10:00:00+00:00" },
      { paperId: "1", subjectCode: "0606", subjectName: "Additional Mathematics", paperNumber: 2, awarded: 52, maximum: 80, grade: "B", recordedAt: "2026-10-29T10:00:00+00:00" },
    ],
    lastPaperAt: "2026-11-10T10:00:00+00:00",
    teacherReplies: [
      { reviewId: "r1", teacherName: "Ms. Hanna", questionId: "7", subjectCode: "0580", subjectName: "Mathematics", paperNumber: 4, marksAdded: 1, paperId: "5", resolvedAt: "2026-11-11T12:00:00+00:00" },
    ],
    homework: [
      { assignmentId: "a1", title: "Trigonometry set", subjectCode: "0580", teacherName: "Ms. Hanna", dueAt: "2026-11-13T15:00:00+00:00", questionCount: 12, isOverdue: false },
    ],
    classCount: 2,
    stats: { papersMarked: 22, marksWonBack: 64, bestGrade: { grade: "A", subjectCode: "0580" } },
    activity: [],
    ...overrides,
  }
}
