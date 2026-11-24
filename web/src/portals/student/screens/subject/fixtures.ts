/*
 * The approved mock's Mathematics data (`.impeccable/mocks/student-r2/sjf.js`)
 * as `Subject` DTOs. Tests only; dates are mid-month UTC so month labels are
 * the same in every time zone.
 */
import type { PaperAttempt, PaperHistoryRow, Subject, TopicTile } from "@/lib/studentTypes"

export const NOW = new Date(2024, 10, 20, 10, 0) // 2024-11-20 local

const at = (id: string, recordedAt: string, grade: string, awarded: number, maximum: number, label: string): PaperAttempt => ({
  id,
  recordedAt,
  grade,
  awarded,
  maximum,
  label,
})

const P4: PaperAttempt[] = [
  at("0", "2023-10-15T10:00:00+00:00", "C", 45, 80, "0580/41 · Oct/Nov 2023"),
  at("3", "2024-01-15T10:00:00+00:00", "B", 48, 80, "0580/43 · Oct/Nov 2023"),
  at("4", "2024-02-15T10:00:00+00:00", "B", 50, 80, "0580/42 · Feb/Mar 2024"),
  at("6", "2024-04-15T10:00:00+00:00", "A", 61, 80, "0580/42 · May/Jun 2024"),
]
const P2: PaperAttempt[] = [
  at("1", "2023-11-15T10:00:00+00:00", "B", 44, 70, "0580/22 · Oct/Nov 2023"),
  at("2", "2023-12-15T10:00:00+00:00", "B", 47, 70, "0580/22 · Oct/Nov 2023"),
  at("5", "2024-03-15T10:00:00+00:00", "A", 53, 70, "0580/21 · Feb/Mar 2024"),
]

const row = (a: PaperAttempt, paperNumber: number): PaperHistoryRow => ({
  id: a.id,
  paper: a.label,
  note: "",
  marks: `${a.awarded}/${a.maximum}`,
  pct: `${Math.round((a.awarded / a.maximum) * 100)}%`,
  grade: a.grade,
  gradeColor: "ok",
  tab: `p${paperNumber}`,
  awarded: a.awarded,
  maximum: a.maximum,
  recordedAt: a.recordedAt,
  paperNumber,
  label: a.label,
  variant: Number(a.label.split(" · ")[0].slice(-1)),
  session: a.label.split(" · ")[1],
  confidence: null,
  teacherCorrected: 0,
})

const topic = (name: string, accuracy: number, marksToWin: number): TopicTile => ({
  name,
  acc: `${accuracy}%`,
  color: accuracy >= 80 ? "ok" : accuracy >= 70 ? "accent" : "warn",
  weak: accuracy < 70,
  accuracy,
  marksToWin,
})

export const MATHS_TOPICS: TopicTile[] = [
  topic("C7 Vectors", 41, 9),
  topic("C2 Algebra", 58, 7),
  topic("C6 Trigonometry", 62, 5),
  topic("C5 Mensuration", 69, 4),
  topic("C3 Functions", 71, 3),
  topic("C9 Statistics", 74, 2),
  topic("C3.5 Coordinate geometry", 77, 1),
  topic("C4 Geometry", 80, 1),
  topic("C1 Number", 82, 1),
  topic("C8 Probability", 88, 1),
]

export const MATHS: Subject = {
  header: {
    name: "Mathematics",
    code: "0580",
    qualificationLevel: "igcse",
    intro: "7 papers corrected.",
    forecast: "A",
    weightedMean: "70",
    weightedMeanDelta: "+16 since first paper",
  },
  papersBreakdown: [
    {
      title: "Paper 2", sub: "70 marks", mean: "69%", boundary: "A* line 60/70", position: "53/70 - A", positionOk: true,
      bars: [], paperNumber: 2, outOf: 70, attempts: P2,
      goal: { grade: "A*", marks: 60, outOf: 70, source: "subject_default", sourceLabel: "Average of past boundaries" },
    },
    {
      title: "Paper 4", sub: "80 marks", mean: "64%", boundary: "A* line 68/80", position: "61/80 - A", positionOk: true,
      bars: [], paperNumber: 4, outOf: 80, attempts: P4,
      goal: { grade: "A*", marks: 68, outOf: 80, source: "exact", sourceLabel: "May/Jun 2024 boundary" },
    },
  ],
  topicMap: MATHS_TOPICS,
  paperHistory: [P4[3], P2[2], P4[2], P4[1], P2[1], P2[0], P4[0]].map((a) =>
    row(a, P4.includes(a) ? 4 : 2),
  ),
}

const ONE: PaperAttempt = at("0", "2024-04-15T10:00:00+00:00", "A", 61, 80, "0580/42 · May/Jun 2024")

export const MATHS_ONE: Subject = {
  ...MATHS,
  header: { ...MATHS.header, intro: "1 papers corrected.", weightedMeanDelta: "+0 since first paper" },
  papersBreakdown: [{ ...MATHS.papersBreakdown[1], attempts: [ONE] }],
  topicMap: [topic("C7 Vectors", 41, 9), topic("C2 Algebra", 58, 7), topic("C6 Trigonometry", 62, 5), topic("C1 Number", 82, 1)],
  paperHistory: [row(ONE, 4)],
}
