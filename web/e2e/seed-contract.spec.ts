import fs from "node:fs"
import { test, expect } from "@playwright/test"
import { seedFilePath } from "./seed"

/*
 * The drift pin for `seed.ts`'s `SeedContract`.
 *
 * `scripts/seed_e2e.py` and `seed.ts` are kept in lockstep by hand — nothing
 * generates one from the other — and `readSeed()` is an unchecked
 * `as SeedContract` cast. So a field renamed on the Python side still
 * *typechecks* on the TS side and arrives as `undefined` at runtime, inside
 * whichever spec happened to dereference it, as a confusing failure a long
 * way from the cause. (Worse for the `SeedAccount` fields: `undefined` filled
 * into a login form fails as a bad credential, which reads as an auth bug.)
 *
 * This spec closes that by re-reading the same JSON as `unknown` — never
 * through `readSeed()`, whose cast is the very thing under test — and
 * asserting every field the interface declares is actually there with the
 * declared primitive type.
 *
 * SHAPE below is a hand-maintained mirror of the interface, because TS types
 * are erased at runtime and deriving one from the other would mean pulling in
 * a schema library for a single fixture file. It is the second half of the
 * lockstep, not a replacement for it: **a field added to `SeedContract` must
 * be added here too.** What it buys is that drift against Python — the side
 * nobody can typecheck against — fails once, by name, in one place.
 *
 * Needs no browser; it asserts on the artefact `global-setup.ts` already
 * wrote for the rest of the suite.
 */

/** Every leaf `SeedAccount` carries these five. */
const ACCOUNT_FIELDS = ["userId", "email", "password", "displayName", "accessToken"] as const

function account(prefix: string): Record<string, "string"> {
  return Object.fromEntries(ACCOUNT_FIELDS.map((f) => [`${prefix}.${f}`, "string"]))
}

/**
 * Dotted path → expected `typeof`. Paths are exhaustive over `SeedContract`:
 * every declared leaf appears exactly once.
 */
const SHAPE: Record<string, "string" | "number"> = {
  runTag: "string",
  generatedAt: "string",

  ...account("teacher"),
  ...account("schoolAdmin"),
  ...account("emptyTeacher"),

  "class.classId": "string",
  "class.name": "string",
  "class.joinCode": "string",

  ...account("students.declining"),
  ...account("students.inactive"),
  ...account("students.control"),
  ...account("students.correctedPaper"),
  // `correctedPaperId` is present on `students.correctedPaper` only, and
  // `expectedAtRiskReasons` is an array on all four — both are checked
  // separately below, since neither is a primitive leaf.

  "parent.userId": "string",
  "parent.phone": "string",
  "parent.accessToken": "string",
  "parent.linkedStudent": "string",

  // Deliberately no `emptyParent.linkedStudent` — the empty parent has no
  // linked child, and asserting one here would demand the seed fabricate it.
  "emptyParent.userId": "string",
  "emptyParent.phone": "string",
  "emptyParent.accessToken": "string",

  "reviewItem.itemId": "string",
  "reviewItem.attemptId": "string",
  "reviewItem.studentKey": "string",

  "quiz.quizId": "string",
  "quiz.assignmentId": "string",
  "quiz.submissionId": "string",
  "quiz.submittedBy": "string",
  // Asserted as a non-empty string, never as the literal "marked": the seed
  // has a real marking-failure branch it does not fake.
  "quiz.status": "string",

  "placement.subjectCode": "string",
  "placement.paperNumber": "number",
  "placement.bankQuestionCount": "number",
  ...account("placement.students.unonboarded"),
  ...account("placement.students.available"),
  ...account("placement.students.inProgress"),
  "placement.students.inProgress.quizId": "string",
  "placement.students.inProgress.assignmentId": "string",
  "placement.students.inProgress.questionCount": "number",
  ...account("placement.students.completed"),
  "placement.students.completed.quizId": "string",
  "placement.students.completed.assignmentId": "string",
  "placement.students.completed.submissionId": "string",
  "placement.students.completed.awardedMarks": "number",
  "placement.students.completed.maximumMarks": "number",

  "practice.subjectCode": "string",
  ...account("practice.students.active"),
  "practice.students.active.unsubmittedAssignmentId": "string",
  "practice.students.active.markingAssignmentId": "string",
  "practice.students.active.markedAssignmentId": "string",
  "practice.students.active.deckId": "string",
  ...account("practice.students.settled"),
  "practice.students.settled.deckId": "string",
  ...account("practice.students.bare"),

  "studyPlan.subjectCode": "string",
  "studyPlan.activeSessionId": "string",
  "studyPlan.activeSessionTopic": "string",
  "studyPlan.activeSessionCount": "number",
  "studyPlan.completedSessionCount": "number",
}

/** The 14 keys `build_result_payload` returns (scripts/seed_e2e.py). */
const TOP_LEVEL_KEYS = [
  "runTag",
  "generatedAt",
  "teacher",
  "schoolAdmin",
  "class",
  "students",
  "parent",
  "reviewItem",
  "quiz",
  "emptyTeacher",
  "emptyParent",
  "placement",
  "practice",
  "studyPlan",
] as const

function resolve(root: unknown, dotted: string): unknown {
  let node: unknown = root
  for (const segment of dotted.split(".")) {
    if (typeof node !== "object" || node === null) return undefined
    node = (node as Record<string, unknown>)[segment]
  }
  return node
}

/** Read the artefact directly — NOT via `readSeed()`, whose cast is what
 * this spec exists to compensate for. */
function readSeedRaw(): unknown {
  const file = seedFilePath()
  if (!fs.existsSync(file)) {
    throw new Error(`No seed contract at ${file} — did global setup run?`)
  }
  return JSON.parse(fs.readFileSync(file, "utf-8")) as unknown
}

test("the seeded JSON carries every group SeedContract declares", () => {
  const seed = readSeedRaw()
  expect(typeof seed, "the seed artefact should parse to an object").toBe("object")

  const present = Object.keys(seed as Record<string, unknown>).sort()
  // Exact, not a superset: a key added on the Python side and never mirrored
  // into `SeedContract` is drift in the direction this file can still catch,
  // and it is the direction P4.11 found stale (three whole groups undeclared).
  expect(present, "top-level groups drifted from SeedContract").toEqual(
    [...TOP_LEVEL_KEYS].sort(),
  )
})

test("every field SeedContract declares is present with the declared type", () => {
  const seed = readSeedRaw()
  const wrong: string[] = []

  for (const [dotted, expectedType] of Object.entries(SHAPE)) {
    const value = resolve(seed, dotted)
    if (typeof value !== expectedType) {
      wrong.push(`${dotted}: expected ${expectedType}, got ${typeof value}`)
      continue
    }
    // An empty id or token typechecks as a string and then fails far away —
    // as a bad credential, or a 404 on a route built from a blank UUID.
    if (expectedType === "string" && (value as string).length === 0) {
      wrong.push(`${dotted}: empty string`)
    }
  }

  expect(wrong, `seed fields drifted from SeedContract:\n${wrong.join("\n")}`).toEqual([])
})

test("the at-risk reason arrays and the corrected-paper id keep their shapes", () => {
  const seed = readSeedRaw()

  // `SeedStudent.expectedAtRiskReasons` — the contract at-risk-flags.spec.ts
  // asserts against exactly. An array of strings on all four, and the seed's
  // own documented expectations are that `control`/`correctedPaper` are
  // empty; a non-empty one there would mean the seed drifted into flagging a
  // student it documents as clean.
  for (const key of ["declining", "inactive", "control", "correctedPaper"]) {
    const reasons = resolve(seed, `students.${key}.expectedAtRiskReasons`)
    expect(Array.isArray(reasons), `students.${key}.expectedAtRiskReasons`).toBe(true)
    for (const reason of reasons as unknown[]) {
      expect(typeof reason, `students.${key}.expectedAtRiskReasons entry`).toBe("string")
    }
  }
  expect(resolve(seed, "students.declining.expectedAtRiskReasons")).not.toEqual([])
  expect(resolve(seed, "students.inactive.expectedAtRiskReasons")).not.toEqual([])
  expect(resolve(seed, "students.control.expectedAtRiskReasons")).toEqual([])
  expect(resolve(seed, "students.correctedPaper.expectedAtRiskReasons")).toEqual([])

  // Optional on the interface, and genuinely only on this one student.
  expect(typeof resolve(seed, "students.correctedPaper.correctedPaperId")).toBe("string")
  expect(resolve(seed, "students.declining.correctedPaperId")).toBeUndefined()

  // The two "key into students" fields must actually resolve to a student.
  for (const dotted of ["reviewItem.studentKey", "quiz.submittedBy"]) {
    const key = resolve(seed, dotted) as string
    expect(resolve(seed, `students.${key}`), `${dotted} = "${key}" is not a seeded student`)
      .toBeDefined()
  }

  // Declared as carrying no student accounts — the four S-24/S-25 states live
  // under practice/placement. A spec written against `studyPlan.students`
  // would silently find nothing, so pin the absence rather than describe it.
  expect(resolve(seed, "studyPlan.students")).toBeUndefined()
})
