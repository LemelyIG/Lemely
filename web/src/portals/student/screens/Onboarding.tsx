/* Hallmark · pre-emit critique: P5 H4 E4 S5 R5 V4 */
import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Stepper } from "@/components/ui/stepper"
import { studentSaveFailureMessage } from "@/lib/studentOutcome"
import {
  useCompleteOnboarding,
  usePatchStudentProfile,
  usePutConfidenceRatings,
  usePutEnrolments,
  useStudentProfile,
} from "@/lib/hooks/useMeApi"
import {
  buildConfidenceRatingsPayload,
  buildEnrolmentPayload,
  buildProfilePatchPayload,
  buildQuestionnaireSteps,
  clampStepIndex,
  placementInviteSubject,
  toggleInSet,
  SUPPORTED_SUBJECTS,
  type QuestionnaireAnswers,
  type SubjectDraft,
} from "./onboarding/onboardingData"
import { SubjectsStep } from "./onboarding/SubjectsStep"
import { QuestionnaireStep } from "./onboarding/QuestionnaireStep"

/*
 * Onboarding (S-01 + S-02). The real multi-step wizard on the P4.3 backend
 * (`/api/me/student-profile/...`) — replaces the legacy single-step screen,
 * whose own docstring said "there is no multi-step wizard backend yet".
 * There is now (P4.3, D4.5).
 *
 * D4.5's rule governs every piece of local state here: a field the student
 * hasn't touched is `undefined`/absent, never a defaulted sentinel, and only
 * touched fields are ever included in a PATCH/PUT body (`onboardingData.ts`'s
 * `build*Payload` functions are the single enforcement point, unit-tested in
 * `web/tests/unit/onboarding.test.ts`).
 *
 * Existing profile/enrolment data (`GET /student-profile`) seeds local state
 * once on load, so a student resuming onboarding doesn't lose earlier
 * answers — including confidence ratings for topics outside this UI's
 * 2-3-per-subject display set, which are carried through untouched rather
 * than dropped by the PUT's full-replace semantics on Finish.
 *
 * One-directional: S-01 -> S-02, matching the UI spec's "Exits: S-02" (no
 * back-to-subjects nav) — going back would risk silently orphaning a
 * deselected subject's enrolment, since `/api/me` exposes no
 * delete-enrolment route to clean it up.
 *
 * ── P4.10, the Study Notebook pass ────────────────────────────────────────
 *
 * This flow is the first thing a new student sees, and it reached surface 10
 * still entirely in the build-era language: no surface in the Phase 4 ledger
 * ever claimed it, though MISSION §1 names "onboarding/placement test" in
 * scope outright. It was three screens of Material-3 tokens standing between a
 * new account and every screen that had been redesigned.
 *
 * **Both failure paths printed the server's own words.** The two `catch` arms
 * rendered `err.message`, and every `detail` these routes produce is machine
 * text: `f"{field} cannot be null."` (a JSON field name),
 * `f"Unknown session month: {value!r}"` (a Python repr), and
 * `str(StudentProfileValidationError(...))`. So a student picking subjects on
 * their first day could be shown a camelCase key. `lib/studentOutcome.ts` owns
 * the wording now, and its first sentence answers the question they actually
 * have: nothing you typed has been lost.
 */

type WizardStep = "subjects" | "questionnaire"

export function Onboarding() {
  const navigate = useNavigate()
  const { data: existing } = useStudentProfile()
  const patchProfile = usePatchStudentProfile()
  const putEnrolments = usePutEnrolments()
  const putConfidenceRatings = usePutConfidenceRatings()
  const completeOnboarding = useCompleteOnboarding()

  const [wizardStep, setWizardStep] = useState<WizardStep>("subjects")
  const [qualificationLevel, setQualificationLevel] = useState<string | null>(null)
  const [drafts, setDrafts] = useState<Record<string, SubjectDraft>>({})
  const [answers, setAnswers] = useState<QuestionnaireAnswers>({})
  const [confidenceBySubject, setConfidenceBySubject] = useState<
    Record<string, Record<string, number>>
  >({})
  const [questionnaireIndex, setQuestionnaireIndex] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const seeded = useRef(false)
  useEffect(() => {
    if (seeded.current || !existing) return
    seeded.current = true
    setQualificationLevel(existing.profile.qualificationLevel)
    const seededDrafts: Record<string, SubjectDraft> = {}
    const seededConfidence: Record<string, Record<string, number>> = {}
    for (const enrolment of existing.enrolments) {
      if (!SUPPORTED_SUBJECTS.some((s) => s.code === enrolment.subjectCode)) continue
      seededDrafts[enrolment.subjectCode] = {
        subjectCode: enrolment.subjectCode,
        papers: new Set(enrolment.papers),
        targetGrade: enrolment.targetGrade,
        sessionMonth: enrolment.sessionMonth,
        sessionYear: enrolment.sessionYear,
      }
      if (enrolment.confidenceRatings.length > 0) {
        seededConfidence[enrolment.subjectCode] = Object.fromEntries(
          enrolment.confidenceRatings.map((r) => [r.topic, r.rating]),
        )
      }
    }
    setDrafts(seededDrafts)
    setConfidenceBySubject(seededConfidence)
    setAnswers({
      schoolName: existing.profile.schoolName ?? undefined,
      hasExternalLessons: existing.profile.hasExternalLessons ?? undefined,
      weeklyStudyHours: existing.profile.weeklyStudyHours ?? undefined,
      gradeLevel: existing.profile.gradeLevel ?? undefined,
    })
  }, [existing])

  const questionnaireSteps = buildQuestionnaireSteps(Object.keys(drafts))

  function toggleSubject(code: string) {
    setDrafts((prev) => {
      const next = { ...prev }
      if (next[code]) {
        delete next[code]
      } else {
        next[code] = {
          subjectCode: code,
          papers: new Set(),
          targetGrade: null,
          sessionMonth: null,
          sessionYear: null,
        }
      }
      return next
    })
  }

  function togglePaper(code: string, paper: number) {
    setDrafts((prev) => {
      const draft = prev[code]
      if (!draft) return prev
      return { ...prev, [code]: { ...draft, papers: toggleInSet(draft.papers, paper) } }
    })
  }

  function updateDraft(code: string, patch: Partial<SubjectDraft>) {
    setDrafts((prev) => {
      const draft = prev[code]
      if (!draft) return prev
      return { ...prev, [code]: { ...draft, ...patch } }
    })
  }

  async function handleSubjectsContinue() {
    setError(null)
    try {
      if (qualificationLevel) {
        await patchProfile.mutateAsync(buildProfilePatchPayload({ qualificationLevel }))
      }
      await putEnrolments.mutateAsync({
        enrolments: buildEnrolmentPayload(Object.values(drafts)),
      })
      setQuestionnaireIndex(0)
      setWizardStep("questionnaire")
    } catch (err) {
      setError(studentSaveFailureMessage(err))
    }
  }

  function goToStep(index: number) {
    setQuestionnaireIndex(clampStepIndex(index, questionnaireSteps.length))
  }

  function advance() {
    goToStep(questionnaireIndex + 1)
  }

  /**
   * Unset the current question's answer, without moving.
   *
   * P4.10 split this out of `skipCurrent`, which was doing both at once behind
   * a button labelled "Skip for now" that only appeared once you had answered.
   * See `QuestionnaireStep`'s header for the full account.
   *
   * The confidence step is deliberately absent from this switch: its answer is
   * a set of per-topic slider ratings rather than one field, and `undefined`
   * for "no rating" is what `buildConfidenceRatingsPayload` already filters on,
   * so there is nothing here that could be unset without inventing a
   * "clear every topic" action nobody asked for. That step therefore never
   * offers the button, because `answered` is false until a slider moves and
   * true only for topics that really carry a rating.
   */
  function clearCurrent() {
    const step = questionnaireSteps[questionnaireIndex]
    if (step?.kind === "school") setAnswers((prev) => ({ ...prev, schoolName: undefined }))
    else if (step?.kind === "externalLessons")
      setAnswers((prev) => ({ ...prev, hasExternalLessons: undefined }))
    else if (step?.kind === "weeklyHours")
      setAnswers((prev) => ({ ...prev, weeklyStudyHours: undefined }))
    else if (step?.kind === "gradeLevel") setAnswers((prev) => ({ ...prev, gradeLevel: undefined }))
  }

  /**
   * Move past an unanswered question.
   *
   * Still clears before advancing rather than only advancing: a value seeded
   * from an existing profile can be `null`, and only an explicit `undefined`
   * keeps the field out of the PATCH body (D4.5).
   */
  function skipCurrent() {
    clearCurrent()
    advance()
  }

  function setConfidence(subjectCode: string, topic: string, rating: number) {
    setConfidenceBySubject((prev) => ({
      ...prev,
      [subjectCode]: { ...prev[subjectCode], [topic]: rating },
    }))
  }

  async function handleFinish() {
    setError(null)
    try {
      const patch = buildProfilePatchPayload(answers)
      if (Object.keys(patch).length > 0) {
        await patchProfile.mutateAsync(patch)
      }
      for (const [subjectCode, ratings] of Object.entries(confidenceBySubject)) {
        const payload = buildConfidenceRatingsPayload(ratings)
        if (Object.keys(payload).length > 0) {
          await putConfidenceRatings.mutateAsync({ subjectCode, ratings: payload })
        }
      }
      await completeOnboarding.mutateAsync()
      // S-02 -> S-03 (UI spec): the placement invite is per subject, so this
      // sends the student to the first subject they enrolled in, in the
      // order S-01 presented them. A student who selected nothing has no
      // subject to invite them into a placement test for — S-06 directly.
      // See `placementInviteSubject` for why this is not `Object.keys(...)[0]`.
      const firstSubject = placementInviteSubject(Object.keys(drafts))
      navigate(firstSubject ? `/student/placement/${firstSubject}` : "/student")
    } catch (err) {
      setError(studentSaveFailureMessage(err))
    }
  }

  const saving =
    patchProfile.isPending ||
    putEnrolments.isPending ||
    putConfidenceRatings.isPending ||
    completeOnboarding.isPending

  return (
    <div className="lm-screen mx-auto flex w-full max-w-190 flex-col gap-6">
      <Stepper
        steps={[
          { id: 1, label: "Subjects" },
          { id: 2, label: "Questionnaire" },
        ]}
        current={wizardStep === "subjects" ? 1 : 2}
        completed={wizardStep === "questionnaire" ? new Set([1]) : new Set()}
        onSelect={() => undefined}
        disabled
      />

      {wizardStep === "subjects" ? (
        <SubjectsStep
          qualificationLevel={qualificationLevel}
          onQualificationLevel={setQualificationLevel}
          drafts={drafts}
          onToggleSubject={toggleSubject}
          onTogglePaper={togglePaper}
          onTargetGrade={(code, grade) => updateDraft(code, { targetGrade: grade })}
          onSessionMonth={(code, month) => updateDraft(code, { sessionMonth: month })}
          onSessionYear={(code, year) => updateDraft(code, { sessionYear: year })}
          onContinue={handleSubjectsContinue}
          saving={saving}
          error={error}
        />
      ) : (
        <QuestionnaireStep
          steps={questionnaireSteps}
          stepIndex={questionnaireIndex}
          onBack={() => goToStep(questionnaireIndex - 1)}
          onSkip={skipCurrent}
          onClear={clearCurrent}
          onContinue={advance}
          onFinish={handleFinish}
          answers={answers}
          onSchoolName={(v) => setAnswers((prev) => ({ ...prev, schoolName: v }))}
          onExternalLessons={(v) => setAnswers((prev) => ({ ...prev, hasExternalLessons: v }))}
          onWeeklyHours={(v) => setAnswers((prev) => ({ ...prev, weeklyStudyHours: v }))}
          onGradeLevel={(v) => setAnswers((prev) => ({ ...prev, gradeLevel: v }))}
          confidenceBySubject={confidenceBySubject}
          onConfidence={setConfidence}
          saving={saving}
          error={error}
        />
      )}
    </div>
  )
}
