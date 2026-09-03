import { describe, expect, it } from "vitest"
import type { CatalogueSubject } from "@/lib/referenceTypes"
import {
  buildConfidenceRatingsPayload,
  buildEnrolmentPayload,
  buildProfilePatchPayload,
  buildQuestionnaireSteps,
  clampStepIndex,
  placementInviteSubject,
  toggleInSet,
  type QuestionnaireAnswers,
  type SubjectDraft,
} from "@/portals/student/screens/onboarding/onboardingData"

function cat(code: string): CatalogueSubject {
  return { code, name: code, board: "caie", qualificationLevel: "igcse", papers: [], topics: [] }
}

// Catalogue order is `code` order now (spec D3 drops the display-order
// column), so the fixture is ordered the way `/api/reference` returns it.
const CATALOGUE = [cat("0580"), cat("0606"), cat("0625")]

describe("placementInviteSubject — S-02 → S-03 routing", () => {
  it("sends a single-subject student to that subject", () => {
    expect(placementInviteSubject(["0580"], CATALOGUE)).toBe("0580")
  })

  it("returns null when the student enrolled in nothing (S-06 instead)", () => {
    expect(placementInviteSubject([], CATALOGUE)).toBeNull()
  })

  it("orders by the fetched catalogue, not by the order the codes arrive in", () => {
    expect(placementInviteSubject(["0625", "0580"], CATALOGUE)).toBe("0580")
    expect(placementInviteSubject(["0580", "0625"], CATALOGUE)).toBe("0580")
  })

  it("does not depend on JS object key enumeration order", () => {
    // The regression this function exists for. `Object.keys` hoists
    // integer-like keys ahead of insertion order, so a syllabus code without a
    // leading zero silently jumps the queue. Today's codes all have one, which
    // is exactly why the bug was invisible.
    const drafts: Record<string, boolean> = {}
    drafts["0625"] = true
    drafts["9709"] = true
    expect(Object.keys(drafts)[0]).toBe("9709") // the trap, pinned
    expect(placementInviteSubject(Object.keys(drafts), CATALOGUE)).toBe("0625")
  })

  it("ignores a code that is not in the catalogue", () => {
    expect(placementInviteSubject(["9999"], CATALOGUE)).toBeNull()
  })

  it("returns null when the catalogue has not loaded", () => {
    // Guards the same failure `Onboarding.tsx`'s seeding effect guards: acting
    // on an empty catalogue must not silently mean "no subjects".
    expect(placementInviteSubject(["0625"], [])).toBeNull()
  })
})

describe("toggleInSet", () => {
  it("adds an item not yet present", () => {
    const result = toggleInSet(new Set(["0625"]), "0580")
    expect([...result].sort()).toEqual(["0580", "0625"])
  })

  it("removes an item already present (deselect)", () => {
    const result = toggleInSet(new Set(["0625", "0580"]), "0625")
    expect([...result]).toEqual(["0580"])
  })

  it("never mutates the input set", () => {
    const original = new Set(["0625"])
    toggleInSet(original, "0580")
    expect([...original]).toEqual(["0625"])
  })

  it("supports selecting more than one subject (multi-select)", () => {
    let selected = toggleInSet(new Set<string>(), "0625")
    selected = toggleInSet(selected, "0580")
    selected = toggleInSet(selected, "0606")
    expect([...selected].sort()).toEqual(["0580", "0606", "0625"])
  })
})

describe("buildEnrolmentPayload", () => {
  it("carries multi-select paper choices through as a sorted list", () => {
    const drafts: SubjectDraft[] = [
      {
        subjectCode: "0625",
        qualificationLevel: "igcse",
        papers: new Set([4, 2]),
        targetGrade: "A",
        sessionMonth: "may_june",
        sessionYear: 2027,
      },
    ]
    expect(buildEnrolmentPayload(drafts)).toEqual([
      {
        subjectCode: "0625",
        qualificationLevel: "igcse",
        targetGrade: "A",
        sessionMonth: "may_june",
        sessionYear: 2027,
        papers: [2, 4],
      },
    ])
  })

  it("passes skipped target grade/session through as null, never a fabricated default", () => {
    const drafts: SubjectDraft[] = [
      {
        subjectCode: "0580",
        qualificationLevel: null,
        papers: new Set(),
        targetGrade: null,
        sessionMonth: null,
        sessionYear: null,
      },
    ]
    const [entry] = buildEnrolmentPayload(drafts)
    expect(entry.targetGrade).toBeNull()
    expect(entry.sessionMonth).toBeNull()
    expect(entry.sessionYear).toBeNull()
    expect(entry.papers).toEqual([])
  })

  it("builds one entry per selected subject", () => {
    const drafts: SubjectDraft[] = [
      {
        subjectCode: "0625",
        qualificationLevel: null,
        papers: new Set([1]),
        targetGrade: null,
        sessionMonth: null,
        sessionYear: null,
      },
      {
        subjectCode: "0606",
        qualificationLevel: null,
        papers: new Set([2]),
        targetGrade: null,
        sessionMonth: null,
        sessionYear: null,
      },
    ]
    expect(buildEnrolmentPayload(drafts).map((e) => e.subjectCode)).toEqual(["0625", "0606"])
  })

  it("includes each subject's own qualificationLevel in the enrolment payload", () => {
    const drafts: SubjectDraft[] = [
      {
        subjectCode: "0625",
        qualificationLevel: "igcse",
        papers: new Set([1]),
        targetGrade: null,
        sessionMonth: null,
        sessionYear: null,
      },
    ]

    const payload = buildEnrolmentPayload(drafts)

    expect(payload[0].qualificationLevel).toBe("igcse")
  })
})

describe("buildProfilePatchPayload — D4.5 skip rule", () => {
  it("omits a skipped field entirely rather than sending a default", () => {
    const answers: QuestionnaireAnswers = {
      schoolName: "Greenwood International",
      // weeklyStudyHours intentionally left untouched (skipped)
    }
    const payload = buildProfilePatchPayload(answers)
    expect(payload).toEqual({ schoolName: "Greenwood International" })
    expect("weeklyStudyHours" in payload).toBe(false)
  })

  it("the skip path serialises with no trace of the skipped key (not 0, not null, absent)", () => {
    const payload = buildProfilePatchPayload({ weeklyStudyHours: undefined })
    const wire = JSON.stringify(payload)
    expect(wire).not.toContain("weeklyStudyHours")
    expect(payload).toEqual({})
  })

  it("an explicit null on a touched field is preserved (clearing an existing answer)", () => {
    const payload = buildProfilePatchPayload({ schoolName: null })
    expect(payload).toEqual({ schoolName: null })
  })

  it("a real falsy answer (hasExternalLessons: false) is sent, not mistaken for a skip", () => {
    const payload = buildProfilePatchPayload({ hasExternalLessons: false })
    expect(payload).toEqual({ hasExternalLessons: false })
  })

  it("every field skipped produces an empty payload", () => {
    expect(buildProfilePatchPayload({})).toEqual({})
  })
})

describe("buildConfidenceRatingsPayload — D4.5 skip rule", () => {
  it("drops a topic never rated", () => {
    const payload = buildConfidenceRatingsPayload({
      "1 Motion, forces and energy": 4,
      "2 Thermal physics": undefined,
    })
    expect(payload).toEqual({ "1 Motion, forces and energy": 4 })
    expect("2 Thermal physics" in payload).toBe(false)
  })

  it("an entirely unrated set produces an empty payload, never zeros", () => {
    expect(buildConfidenceRatingsPayload({})).toEqual({})
  })
})

describe("buildQuestionnaireSteps / clampStepIndex — step navigation", () => {
  it("builds the 4 fixed steps plus one confidence step per selected subject", () => {
    const steps = buildQuestionnaireSteps(["0625"])
    expect(steps).toHaveLength(5)
    expect(steps.at(-1)).toEqual({ id: "confidence-0625", kind: "confidence", subjectCode: "0625" })
  })

  it("adds one confidence step per subject, in S-01 selection order", () => {
    const steps = buildQuestionnaireSteps(["0580", "0606", "0625"])
    // 4 fixed + 3 confidence + 1 placementChoice (>1 subject enrolled).
    expect(steps).toHaveLength(8)
    expect(steps.slice(4, 7).map((s) => s.subjectCode)).toEqual(["0580", "0606", "0625"])
  })

  it("a student who enrolled in nothing still gets the 4 fixed steps", () => {
    expect(buildQuestionnaireSteps([])).toHaveLength(4)
  })

  it("clamps forward navigation at the last step", () => {
    expect(clampStepIndex(10, 6)).toBe(5)
  })

  it("clamps backward navigation at the first step", () => {
    expect(clampStepIndex(-3, 6)).toBe(0)
  })

  it("lets a normal in-range step through unchanged", () => {
    expect(clampStepIndex(2, 6)).toBe(2)
  })

  it("clamps to 0 for an empty step sequence rather than going negative", () => {
    expect(clampStepIndex(0, 0)).toBe(0)
  })
})

describe("buildQuestionnaireSteps — placement choice", () => {
  it("appends a placement-choice step when the student enrolled in more than one subject", () => {
    const steps = buildQuestionnaireSteps(["0580", "0625"])
    expect(steps[steps.length - 1]).toEqual({ id: "placementChoice", kind: "placementChoice" })
  })

  it("does not ask when there is only one subject to choose from", () => {
    // A question with one possible answer is not a question.
    const steps = buildQuestionnaireSteps(["0625"])
    expect(steps.some((s) => s.kind === "placementChoice")).toBe(false)
  })

  it("does not ask when the student enrolled in nothing", () => {
    expect(buildQuestionnaireSteps([]).some((s) => s.kind === "placementChoice")).toBe(false)
  })

  it("keeps the confidence steps before the choice", () => {
    const steps = buildQuestionnaireSteps(["0580", "0625"])
    const lastConfidence = steps.map((s) => s.kind).lastIndexOf("confidence")
    const choice = steps.map((s) => s.kind).indexOf("placementChoice")
    expect(choice).toBeGreaterThan(lastConfidence)
  })
})
