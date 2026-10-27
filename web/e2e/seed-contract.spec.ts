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

/** A `SeedTutor`: an account plus its profile id, public name, headline and listing state.
 * (`indexable` is a boolean and is checked in its own test below.) */
function tutor(prefix: string): Record<string, "string"> {
  return {
    ...account(prefix),
    ...Object.fromEntries(
      ["tutorProfileId", "publicName", "headline", "listingState"].map((f) => [
        `${prefix}.${f}`,
        "string",
      ]),
    ),
  }
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

  "schoolWithSeats.schoolId": "string",
  "schoolWithSeats.name": "string",
  "schoolWithSeats.seatQuota": "number",
  ...account("schoolWithSeats.admin"),

  "class.classId": "string",
  "class.name": "string",
  "class.joinCode": "string",

  ...account("students.declining"),
  "students.declining.parentInviteCode": "string",
  ...account("students.inactive"),
  ...account("students.control"),
  ...account("students.correctedPaper"),
  ...account("students.selfReview"),
  ...account("students.belowTarget"),
  "students.belowTarget.targetGrade": "string",
  "students.belowTarget.predictedGrade": "string",
  "students.belowTarget.positionsBelow": "number",
  // This student's own second class, never `class` above.
  "students.belowTarget.classId": "string",
  "students.belowTarget.className": "string",
  // `correctedPaperId` is present on `students.correctedPaper` only, and
  // `expectedAtRiskReasons` is an array on all five — both are checked
  // separately below, since neither is a primitive leaf.

  ...account("parent"),
  "parent.linkedStudent": "string",

  // Deliberately no `emptyParent.linkedStudent` — the empty parent has no
  // linked child, and asserting one here would demand the seed fabricate it.
  ...account("emptyParent"),

  "reviewItem.itemId": "string",
  "reviewItem.attemptId": "string",
  "reviewItem.studentKey": "string",
  // Task #67: the second, verdict-free review-queue row. Not tied to a
  // `students` entry, so no `account(...)` spread accompanies these two.
  "reviewItem.legacyItemId": "string",
  "reviewItem.legacyAttemptId": "string",
  // Final-review coverage gap: a THIRD review-queue row carrying a marker's
  // rationale but no verdict. Not tied to a `students` entry either.
  "reviewItem.rationaleOnlyItemId": "string",
  "reviewItem.rationaleOnlyAttemptId": "string",

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

  ...account("engagement.deviceLimit"),
  "engagement.deviceLimit.deviceCount": "number",
  "engagement.deviceLimit.oldestDeviceLabel": "string",
  "engagement.leaderboard.classId": "string",
  // `weeklyXpByStudentKey` and `expectedOrderByStudentKey` are not primitive
  // leaves, and "is an object" is exactly the resolution at which an empty
  // board still looks correct. They get their own test below.

  "deletion.classId": "string",
  "deletion.className": "string",
  ...account("deletion.student"),
  "deletion.student.subjectCode": "string",
  // `deletion.student.attemptIds` (an array) is not a primitive leaf — its
  // own test below.
  ...account("deletion.integrityStudent"),
  "deletion.integrityStudent.subjectCode": "string",
  "deletion.integrityStudent.attemptId": "string",
  "deletion.integrityStudent.reviewItemId": "string",
  ...account("deletion.remarkStudent"),
  // `deletion.remarkStudent.attemptIds` (an array) is not a primitive leaf —
  // its own test below.
  "deletion.reviewItemId": "string",
  "deletion.consolePaperId": "string",

  // Tutoring marketplace (T29). The `outcomes.insufficient` counts are null by
  // design and the bookings/grants shapes beyond ids are checked below.
  "tutoring.subjectCode": "string",
  "tutoring.subjectName": "string",
  ...account("tutoring.platformAdmin"),
  ...tutor("tutoring.tutors.sufficient"),
  ...tutor("tutoring.tutors.insufficient"),
  ...tutor("tutoring.tutors.draft"),
  ...account("tutoring.student"),
  ...account("tutoring.discover.student"),
  ...account("tutoring.discover.rival"),
  "tutoring.bookings.requested": "string",
  "tutoring.bookings.accepted": "string",
  "tutoring.bookings.awaitingOutcome": "string",
  "tutoring.bookings.completed": "string",
  "tutoring.bookings.noShow": "string",
  "tutoring.bookings.declined": "string",
  "tutoring.bookings.cancelledByStudent": "string",
  "tutoring.bookings.cancelledByTutorLate": "string",
  "tutoring.bookings.expired": "string",
  "tutoring.bookings.child.childRequested": "string",
  "tutoring.bookings.child.parentAccepted": "string",
  "tutoring.bookings.child.awaitingOutcome": "string",
  "tutoring.grants.live.grantId": "string",
  "tutoring.grants.live.studentUserId": "string",
  "tutoring.grants.live.tutorProfileId": "string",
  "tutoring.grants.live.accessLogCount": "number",
  "tutoring.grants.ended.grantId": "string",
  "tutoring.grants.ended.studentUserId": "string",
  "tutoring.grants.ended.tutorProfileId": "string",
  "tutoring.grants.revocable.grantId": "string",
  "tutoring.grants.revocable.studentUserId": "string",
  "tutoring.grants.revocable.tutorProfileId": "string",
  "tutoring.reports.openSafety.reportId": "string",
  "tutoring.reports.openSafety.bookingId": "string",
  "tutoring.reports.resolved.reportId": "string",
  "tutoring.reports.resolved.tutorProfileId": "string",
  "tutoring.reviews.approvedReviewId": "string",
  "tutoring.reviews.pendingReviewId": "string",
  "tutoring.outcomes.sufficient.distributionState": "string",
  "tutoring.outcomes.sufficient.changeState": "string",
  "tutoring.outcomes.sufficient.nGraded": "number",
  "tutoring.outcomes.sufficient.nPaired": "number",
  "tutoring.outcomes.sufficient.higher": "number",
  "tutoring.outcomes.sufficient.same": "number",
  "tutoring.outcomes.sufficient.lower": "number",
  "tutoring.outcomes.insufficient.distributionState": "string",
  "tutoring.outcomes.insufficient.changeState": "string",
}

/** The 18 keys `build_result_payload` returns (scripts/seed_e2e.py). */
const TOP_LEVEL_KEYS = [
  "runTag",
  "generatedAt",
  "teacher",
  "schoolAdmin",
  "schoolWithSeats",
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
  "engagement",
  "deletion",
  "tutoring",
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
  for (const key of ["declining", "inactive", "control", "correctedPaper", "belowTarget"]) {
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
  // Exactly one reason, and specifically rule 2's: this account carries a
  // single recent attempt precisely so neither rule 1 (needs a 3-record
  // window) nor rule 3 (needs >=14 days of silence) can join the list.
  expect(resolve(seed, "students.belowTarget.expectedAtRiskReasons")).toEqual(["below_target"])

  // Optional on the interface, and genuinely only on this one student.
  expect(typeof resolve(seed, "students.correctedPaper.correctedPaperId")).toBe("string")
  expect(resolve(seed, "students.declining.correctedPaperId")).toBeUndefined()

  expect(typeof resolve(seed, "students.selfReview.selfReviewAttemptId")).toBe("string")
  expect(resolve(seed, "students.selfReview.expectedAtRiskReasons")).toEqual([])

  // The below-target student is in its OWN class, not the seeded roster class —
  // the whole reason a second class exists (see `seed.ts`). If these ever
  // become equal, `teacher-journey.spec.ts`'s roster figures are about to move.
  expect(resolve(seed, "students.belowTarget.classId")).not.toEqual(
    resolve(seed, "class.classId"),
  )

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

test("the engagement group can actually carry a leaderboard-ordering assertion", () => {
  const seed = readSeedRaw()

  // A `Record`/array typechecks as "object" in SHAPE above, which is exactly
  // the resolution at which an empty board still looks correct. These are the
  // properties the ordering assertion actually stands on, and every one of
  // them fails silently rather than loudly if the seed regresses: an empty
  // board renders as the honest "no XP earned here yet this week" state, and
  // tied totals render as a considered equal-rank decision.
  const order = resolve(seed, "engagement.leaderboard.expectedOrderByStudentKey") as string[]
  const xpByKey = resolve(seed, "engagement.leaderboard.weeklyXpByStudentKey") as Record<
    string,
    number
  >

  expect(Array.isArray(order), "expectedOrderByStudentKey should be an array").toBe(true)
  expect(order.length, "an ordering needs at least two rows to be an ordering").toBeGreaterThan(1)

  for (const key of order) {
    expect(resolve(seed, `students.${key}`), `"${key}" is not a seeded student`).toBeDefined()
    expect(typeof xpByKey[key], `"${key}" has no seeded XP total`).toBe("number")
  }

  // Strictly descending AND strictly distinct. Equal XP is equal rank by
  // design (D5.1, P5.3 chunk A), so a tie would make an ordering assertion
  // pass on a board it cannot actually distinguish.
  const totals = order.map((key) => xpByKey[key])
  expect(totals, "expectedOrderByStudentKey is not sorted highest-XP-first").toEqual(
    [...totals].sort((a, b) => b - a),
  )
  expect(new Set(totals).size, `seeded XP totals are not distinct: ${totals.join(", ")}`).toBe(
    totals.length,
  )

  // Every ranked student must be in the class the board is scoped to,
  // otherwise the assertion is reading a different board than the seed built.
  expect(resolve(seed, "engagement.leaderboard.classId")).toEqual(resolve(seed, "class.classId"))

  // Three full slots is what makes the next login from any fresh browser take
  // the G-10 challenge; MAX_DEVICES is 3 (device_repo.py).
  expect(resolve(seed, "engagement.deviceLimit.deviceCount")).toBe(3)
})

test("the deletion group's attemptId arrays keep their shapes (Task 18 e2e)", () => {
  const seed = readSeedRaw()

  // `deletion.student`: four distinct papers (paper_number 1..4, oldest to
  // newest) — `paper-deletion.spec.ts`'s P1..P4 index into this array
  // positionally.
  const studentAttemptIds = resolve(seed, "deletion.student.attemptIds")
  expect(Array.isArray(studentAttemptIds), "deletion.student.attemptIds").toBe(true)
  expect((studentAttemptIds as unknown[]).length).toBe(4)
  for (const id of studentAttemptIds as unknown[]) {
    expect(typeof id, "deletion.student.attemptIds entry").toBe("string")
  }

  // `deletion.remarkStudent`: one scan marked twice (R7) — two attempts
  // sharing one `upload_id`.
  const remarkAttemptIds = resolve(seed, "deletion.remarkStudent.attemptIds")
  expect(Array.isArray(remarkAttemptIds), "deletion.remarkStudent.attemptIds").toBe(true)
  expect((remarkAttemptIds as unknown[]).length).toBe(2)
  for (const id of remarkAttemptIds as unknown[]) {
    expect(typeof id, "deletion.remarkStudent.attemptIds entry").toBe("string")
  }

  // Kept off every other class/roster in this seed — see `seed.ts`'s own
  // `deletion` docstring.
  expect(resolve(seed, "deletion.classId")).not.toEqual(resolve(seed, "class.classId"))
})

test("the tutoring group can carry the journeys it was seeded for (T29)", () => {
  const seed = readSeedRaw()
  const at = (dotted: string): unknown => resolve(seed, `tutoring.${dotted}`)

  // Two listed tutors, one indexable and one opted out, and a draft: the three
  // listing states a journey needs, distinct profiles on distinct accounts.
  expect(at("tutors.sufficient.listingState")).toBe("listed")
  expect(at("tutors.insufficient.listingState")).toBe("listed")
  expect(at("tutors.draft.listingState")).toBe("draft")
  expect(at("tutors.sufficient.indexable")).toBe(true)
  expect(at("tutors.insufficient.indexable")).toBe(false)
  expect(typeof at("tutors.draft.indexable")).toBe("boolean")
  const profileIds = ["sufficient", "insufficient", "draft"].map((k) =>
    at(`tutors.${k}.tutorProfileId`),
  )
  expect(new Set(profileIds).size, "tutor profile ids are not distinct").toBe(3)
  const userIds = ["sufficient", "insufficient", "draft"].map((k) => at(`tutors.${k}.userId`))
  expect(new Set(userIds).size, "tutor accounts are not distinct").toBe(3)

  // The sufficient figure is a real one: counts that add up, and the hidden
  // figure's counts are null rather than zero (zero would read as "no students").
  const suff = at("outcomes.sufficient") as Record<string, unknown>
  expect(suff.distributionState).toBe("sufficient")
  expect(suff.changeState).toBe("sufficient")
  expect(suff.nGraded as number).toBeGreaterThanOrEqual(5)
  const buckets = suff.buckets as Record<string, number>
  expect(Object.keys(buckets)).toEqual(["A*", "A", "B", "C", "D", "E", "U"])
  expect(Object.values(buckets).reduce((a, b) => a + b, 0)).toBe(suff.nGraded)
  expect((suff.higher as number) + (suff.same as number) + (suff.lower as number)).toBe(
    suff.nPaired,
  )
  const insuff = at("outcomes.insufficient") as Record<string, unknown>
  expect(insuff.distributionState).toBe("insufficient")
  expect(insuff.changeState).toBe("insufficient")
  for (const field of ["nGraded", "nPaired", "higher", "same", "lower"]) {
    expect(insuff[field], `outcomes.insufficient.${field}`).toBeNull()
  }
  expect(insuff.buckets).toEqual({})

  // One booking per effective state (eight) plus the child's three, all distinct.
  const bookings = at("bookings") as Record<string, unknown>
  const own = Object.entries(bookings).filter(([k]) => k !== "child")
  expect(own.map(([k]) => k).sort()).toEqual(
    [
      "accepted",
      "awaitingOutcome",
      "cancelledByStudent",
      "cancelledByTutorLate",
      "completed",
      "declined",
      "expired",
      "noShow",
      "requested",
    ].sort(),
  )
  const child = bookings.child as Record<string, string>
  expect(Object.keys(child).sort()).toEqual(
    ["awaitingOutcome", "childRequested", "parentAccepted"].sort(),
  )
  const ids = [...own.map(([, v]) => v as string), ...Object.values(child)]
  expect(new Set(ids).size, "booking ids are not distinct").toBe(ids.length)

  // The live grant is the seeded parent's child's to the sufficient tutor, with a
  // log to show; the revocable one belongs to a different student so revoking it
  // leaves the first alone.
  expect(at("grants.live.studentUserId")).toEqual(resolve(seed, "students.declining.userId"))
  expect(at("grants.live.tutorProfileId")).toEqual(at("tutors.sufficient.tutorProfileId"))
  expect(at("grants.live.accessLogCount") as number).toBeGreaterThanOrEqual(1)
  expect(at("grants.ended.studentUserId")).toEqual(resolve(seed, "students.declining.userId"))
  expect(at("grants.revocable.studentUserId")).toEqual(at("student.userId"))
  expect(at("grants.revocable.studentUserId")).not.toEqual(at("grants.live.studentUserId"))
  expect(at("grants.revocable.grantId")).not.toEqual(at("grants.live.grantId"))

  // The open safety concern is on the booking the contract names as completed.
  expect(at("reports.openSafety.bookingId")).toEqual(at("bookings.completed"))
})
