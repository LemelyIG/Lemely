import type { AnswerView } from "./answerView"
import type { MarkPoint } from "./markModel"

/* The one made-up answer behind "See a sample answer" (states-r1 RQ1). Static: no request, nothing saved.
   It is the mock's own answer (RQ2 and the t.js panel: density, 54 / 20, unit missing), with a made-up student. */

const point = (n: number, code: string, text: string, awarded: boolean, note: string | null): MarkPoint => ({
  markPointId: `sample-${n}`,
  code,
  text,
  tariff: 1,
  groupKey: null,
  groupMaxMarks: null,
  awarded,
  verdictLabel: null,
  note,
  ecf: false,
})

export const SAMPLE_VIEW: AnswerView = {
  key: "sample",
  title: "Sample student · Q8",
  subtitle: "Class 10B · 0625/42 · Paper 4",
  studentHref: null,
  pageLabel: null,
  hasScan: false,
  transcription: "ρ = m / V = 54 / 20\n= 2.7\nanswer: 2.7",
  selfReview: [{ code: "B1", claim: "Claims earned", evidence: "g/cm³ in the working", judge: "Lemely's judge disagreed" }],
  scheme: { expected: "2.7 g/cm³", topic: "Density and units" },
  notes: { reason: null, feedback: "The method and the value are right. The unit g/cm³ is not written with the final answer." },
  points: [
    point(1, "M1", "correct method m ÷ V", true, null),
    point(2, "A1", "2.7", true, null),
    point(3, "B1", "unit g/cm³", false, "No unit after 2.7"),
    point(4, "B1", "3 s.f. or better", false, null),
  ],
  matchedPointIds: [],
  maximumMarks: 4,
  lemelyMarks: 2,
  confidenceScore: 0.58,
  clampNote: null,
  status: "open",
  integrity: false,
  canAdjust: true,
  cannotAdjustReason: null,
  correction: null,
  resolutionNote: null,
}
