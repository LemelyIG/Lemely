import { CircleNotch } from "@phosphor-icons/react"
import { useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { ErrorState } from "@/components/ui/state-views"
import { WeaknessChip } from "@/components/ui/weakness-chip"
import { usePlacementResult } from "@/lib/hooks/usePlacementApi"
import { SUPPORTED_SUBJECTS } from "@/portals/student/screens/onboarding/onboardingData"
import { placementResultView } from "./placementData"

/*
 * S-05 · Placement results. Framed explicitly and warmly as a *baseline*,
 * never a grade (UI spec: "a bad placement result at onboarding is the
 * highest-churn moment in the product"). The whole render decision —
 * `marked: false` vs. a ranked result, and whether `spansMultipleBands`
 * permits a working-level estimate — is made once, in
 * `placementResultView` (`placementData.ts`, unit-tested directly since
 * `vitest.config.ts` runs unit-only, D3.20), not re-derived here from raw
 * fields: this screen only switches on `view.kind`.
 *   - `kind: "unmarked"` carries no topic lists and no marks field at all
 *     (by the type) — never a half result with zeros standing in for
 *     "unknown".
 *   - `showWorkingLevel: false` (== `spansMultipleBands: false`) means the
 *     sample was too narrow to estimate a working level at all; strongest/
 *     weakest topics only, no invented precision (UI spec §1.4).
 *   - a topic with `topic: null` on a question is unknown, not a topic —
 *     doesn't surface here since `topicBreakdown` entries always carry a
 *     real topic string by construction (only individually-topicless
 *     questions can be `null`, and this screen doesn't list per-question
 *     topics — see `questions` if that ever changes).
 */
function topicSeverity(accuracy: number): "minor" | "moderate" | "significant" {
  if (accuracy < 0.4) return "significant"
  if (accuracy < 0.7) return "moderate"
  return "minor"
}

export function PlacementResult() {
  const navigate = useNavigate()
  const { assignmentId = "" } = useParams<{ assignmentId: string }>()
  const { data, isPending, isError, error, refetch } = usePlacementResult(assignmentId)

  if (isPending) {
    return <div className="lm-screen text-body-md text-t2">Loading your results…</div>
  }

  if (isError || !data) {
    return (
      <ErrorState
        heading="Couldn't load your placement result"
        body={error?.message}
        action={{ label: "Try again", onClick: () => void refetch() }}
        className="lm-screen"
      />
    )
  }

  const subjectName = SUPPORTED_SUBJECTS.find((s) => s.code === data.subjectCode)?.name ?? data.subjectCode
  const view = placementResultView(data)

  if (view.kind === "unmarked") {
    return (
      <div className="lm-screen mx-auto flex max-w-[560px] flex-col items-center gap-4 py-16 text-center">
        <CircleNotch size={28} className="animate-spin text-accent" aria-hidden />
        <div className="text-body-lg font-medium text-t1">
          Marking your {subjectName} placement test
        </div>
        <p className="text-body-md text-t2">
          This usually only takes a moment. This page will update on its own — no need to refresh.
        </p>
        <Button variant="ghost" onClick={() => navigate("/student")}>
          Come back to this later
        </Button>
      </div>
    )
  }

  const { strongest, weakest, showWorkingLevel } = view

  return (
    <div className="lm-screen mx-auto flex max-w-[720px] flex-col gap-6">
      <div className="flex flex-col gap-2">
        <div className="font-serif text-display-md leading-display text-t1">
          Your {subjectName} starting picture
        </div>
        <p className="text-body-md text-t2">
          This is a baseline, not a grade — a snapshot of where you're starting from, so your
          study plan can target what actually needs work. It gets more accurate the more you
          practise.
        </p>
      </div>

      {!showWorkingLevel ? (
        <Card className="border-accent">
          <CardBody>
            <p className="text-dense-sm text-t2">
              This test covered a narrow slice of the syllabus, so we're not estimating a working
              level from it yet — just your strongest and weakest topics below. A wider sample
              (from practice and future papers) will sharpen this.
            </p>
          </CardBody>
        </Card>
      ) : null}

      <div className="grid grid-cols-1 gap-5 min-[720px]:grid-cols-2">
        <Card>
          <CardBody className="flex flex-col gap-3">
            <div className="text-dense-sm uppercase tracking-widest text-t3">Strongest topics</div>
            {strongest.length === 0 ? (
              <p className="text-dense-sm text-t3">Not enough data yet.</p>
            ) : (
              <div className="flex flex-col gap-2">
                {strongest.map((t) => (
                  <WeaknessChip
                    key={t.topic}
                    variant="list"
                    topic={t.topic}
                    severity="minor"
                    meta={`${Math.round(t.accuracy * 100)}% accuracy`}
                  />
                ))}
              </div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardBody className="flex flex-col gap-3">
            <div className="text-dense-sm uppercase tracking-widest text-t3">Weakest topics</div>
            {weakest.length === 0 ? (
              <p className="text-dense-sm text-t3">Not enough data yet.</p>
            ) : (
              <div className="flex flex-col gap-2">
                {weakest.map((t) => (
                  <WeaknessChip
                    key={t.topic}
                    variant="list"
                    topic={t.topic}
                    severity={topicSeverity(t.accuracy)}
                    meta={`${Math.round(t.accuracy * 100)}% accuracy · ${t.lostMarks} of ${t.maximumMarks} marks lost`}
                  />
                ))}
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      <div className="flex flex-wrap gap-3">
        <Button variant="accent" size="lg" onClick={() => navigate("/student/plan")}>
          See your study plan
        </Button>
        <Button variant="ghost" size="lg" onClick={() => navigate("/student")}>
          Back to dashboard
        </Button>
      </div>
    </div>
  )
}
