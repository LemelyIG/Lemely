/* Hallmark · pre-emit critique: P5 H5 E4 S5 R5 V4 */
import { CircleNotch } from "@phosphor-icons/react"
import { useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { EmptyState } from "@/components/ui/state-views"
import { PanelSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { WeaknessChip } from "@/components/ui/weakness-chip"
import { studentLoadFailureMessage } from "@/lib/studentOutcome"
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
 *
 * ── P4.10, the Study Notebook pass ────────────────────────────────────────
 *
 * **The load failure printed the server's own words**, same as S-03 and for
 * the same reason: `placement.py` answers every 4xx with `str(exc)`, and those
 * exceptions read `f"Unknown assignment: {uuid}"`. On the screen the UI spec
 * calls "the highest-churn moment in the product", a failed load could show a
 * fifteen-year-old a raw UUID.
 *
 * **The waiting panel's claim was checked rather than trusted.** It tells the
 * student "this page will update on its own, so there is no need to refresh",
 * which is the kind of sentence this build has repeatedly found to be
 * decorative. It is true: `usePlacementResult` sets `refetchInterval` to 4s
 * while `marked === false` and stops the moment it flips. The spinner stays
 * for the same reason — this is work in progress, not content loading, and a
 * skeleton would imply the shape of a result that does not exist yet.
 *
 * **The "narrow sample" note was in the alert register.** It sat in an
 * accent-bordered card, and on this palette accent is how the product says
 * something is wrong (recorded on surfaces 5 and 6). The sentence is a
 * limitation of the sample, not a problem with the student, and it is now in
 * the neutral notice register that exists for exactly that.
 */
function topicSeverity(accuracy: number): "minor" | "moderate" | "significant" {
  if (accuracy < 0.4) return "significant"
  if (accuracy < 0.7) return "moderate"
  return "minor"
}

export function PlacementResult() {
  const navigate = useNavigate()
  const { assignmentId = "" } = useParams<{ assignmentId: string }>()
  const query = usePlacementResult(assignmentId)

  return (
    <div className="lm-screen mx-auto flex w-full max-w-180 flex-col gap-6">
      <QueryState
        query={query}
        /* Deliberately worded "starting picture", never "result" or "score":
         * S-05 is a baseline, and the heading a screen reader announces
         * first should not imply a grade the rest of the screen then walks
         * back. */
        srHeading="Your placement starting picture"
        skeleton={<PanelSkeleton />}
        /* `usePlacementResult` disables itself (`enabled: !!assignmentId`)
           rather than fetching an empty id — reachable only from a malformed
           link missing its assignment segment. */
        idle={
          <EmptyState
            marginalia="Nothing to show"
            heading="No test selected"
            body="This link is missing which placement test to show. Go back and open your result from the dashboard."
            action={{ label: "Back to dashboard", onClick: () => navigate("/student") }}
          />
        }
        error={{
          heading: "We couldn't load your starting picture",
          body: studentLoadFailureMessage,
        }}
      >
        {(data) => {
          const subjectName =
            SUPPORTED_SUBJECTS.find((s) => s.code === data.subjectCode)?.name ?? data.subjectCode
          const view = placementResultView(data)

          if (view.kind === "unmarked") {
            return (
              <div className="mx-auto flex w-full max-w-140 flex-col items-center gap-4 py-16 text-center">
                {/* A spinner, not a skeleton, and deliberately: the marking
                    has not finished, so there is no shape to reserve.
                    `animate-spin` is a transform, which is the only thing
                    §9.2 permits. */}
                <CircleNotch size={28} className="animate-spin text-ink-faint" aria-hidden="true" />
                <h1 className="text-body-lg font-medium text-ink">
                  Marking your {subjectName} placement test
                </h1>
                <p className="max-w-[55ch] text-body-md text-ink-muted">
                  This usually only takes a moment. This page will update on its own, so there is
                  no need to refresh.
                </p>
                <Button variant="ghost" onClick={() => navigate("/student")}>
                  Come back to this later
                </Button>
              </div>
            )
          }

          const { strongest, weakest, showWorkingLevel } = view

          return (
            <>
              <div className="flex flex-col gap-2">
                <h1 className="text-display-md text-ink">Your {subjectName} starting picture</h1>
                <p className="max-w-[65ch] text-body-md text-ink-muted">
                  This is a baseline, not a grade. It is a snapshot of where you're starting from,
                  so your study plan can target what actually needs work. It gets more accurate
                  the more you practise.
                </p>
              </div>

              {!showWorkingLevel ? (
                // `info`, not the accent border it used to carry: this is a fact
                // about how wide the sample was, and on this palette accent
                // reads as alarm.
                <Card className="border-info bg-info-wash">
                  <CardBody>
                    <p className="max-w-[65ch] text-body-sm text-ink-muted">
                      This test covered a narrow slice of the syllabus, so we're not estimating a
                      working level from it yet. Your strongest and weakest topics are below. A
                      wider sample, from practice and future papers, will sharpen this.
                    </p>
                  </CardBody>
                </Card>
              ) : null}

              <div className="grid grid-cols-1 gap-5 min-[720px]:grid-cols-2">
                <Card>
                  <CardBody className="flex flex-col gap-3">
                    <div className="text-eyebrow text-ink-faint">Strongest topics</div>
                    {strongest.length === 0 ? (
                      <p className="text-body-sm text-ink-faint">Not enough data yet.</p>
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
                    <div className="text-eyebrow text-ink-faint">Weakest topics</div>
                    {weakest.length === 0 ? (
                      <p className="text-body-sm text-ink-faint">Not enough data yet.</p>
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
                {/* Subject-scoped since the build's P4.10 — `data.subjectCode`
                    is the subject this placement was actually taken in. */}
                <Button
                  variant="accent"
                  size="lg"
                  onClick={() => navigate(`/student/plan/${data.subjectCode}`)}
                >
                  See your study plan
                </Button>
                <Button variant="ghost" size="lg" onClick={() => navigate("/student")}>
                  Back to dashboard
                </Button>
              </div>
            </>
          )
        }}
      </QueryState>
    </div>
  )
}
