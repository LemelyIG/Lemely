import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Stepper } from "@/components/ui/stepper"
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
      setError(err instanceof Error ? err.message : "Couldn't save your subjects.")
    }
  }

  function goToStep(index: number) {
    setQuestionnaireIndex(clampStepIndex(index, questionnaireSteps.length))
  }

  function advance() {
    goToStep(questionnaireIndex + 1)
  }

  function skipCurrent() {
    const step = questionnaireSteps[questionnaireIndex]
    if (step?.kind === "school") setAnswers((prev) => ({ ...prev, schoolName: undefined }))
    else if (step?.kind === "externalLessons")
      setAnswers((prev) => ({ ...prev, hasExternalLessons: undefined }))
    else if (step?.kind === "weeklyHours")
      setAnswers((prev) => ({ ...prev, weeklyStudyHours: undefined }))
    else if (step?.kind === "gradeLevel") setAnswers((prev) => ({ ...prev, gradeLevel: undefined }))
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
      navigate("/student")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save your answers.")
    }
  }

  const saving =
    patchProfile.isPending ||
    putEnrolments.isPending ||
    putConfidenceRatings.isPending ||
    completeOnboarding.isPending

  return (
    <div className="lm-screen max-w-[760px] mx-auto flex flex-col gap-6">
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
