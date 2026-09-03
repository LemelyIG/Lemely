/* Hallmark · pre-emit critique: P5 H4 E4 S5 R5 V4 */
import { useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { EmptyState } from "@/components/ui/state-views"
import { PanelSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { ApiError } from "@/lib/api"
import { studentLoadFailureMessage } from "@/lib/studentOutcome"
import { useCreatePlacement, usePlacementAvailability } from "@/lib/hooks/usePlacementApi"
import type { PlacementAvailability } from "@/lib/placementTypes"
import { SUPPORTED_SUBJECTS } from "@/portals/student/screens/onboarding/onboardingData"
import { placementInviteView } from "./placementData"

/*
 * S-03 · Placement invite. Reachable both from the S-02 onboarding exit and
 * "any time from the subject screen" (UI spec S-03) — this screen only
 * needs `subjectCode`, no onboarding-in-progress state.
 *
 * The available/unavailable render decision is `placementInviteView`
 * (`placementData.ts`), a pure discriminated union unit-tested directly —
 * `available: false` yields `kind: "unavailable"` with a real, per-`reason`
 * message (0580/0606 genuinely have zero ingested questions today, D4.6
 * §5, and this must say so plainly, never hide the subject or fake
 * availability); `available: true` yields `kind: "available"`, pinned as
 * the inverse so the invite panel is never silently skipped.
 *
 * ── P4.10, the Study Notebook pass ────────────────────────────────────────
 *
 * **The load failure printed the server's own words.** `body={error?.message}`
 * on a route whose every `detail` is `str(exc)`, and whose exceptions read
 * `f"Unknown assignment: {uuid}"` — so a student whose availability check
 * failed could be shown a bare UUID. `studentLoadFailureMessage` owns it now.
 *
 * **The 409 stays hand-read, deliberately.** It is the one response in this
 * whole flow whose `detail` is structured rather than a string: a full
 * `PlacementAvailabilityDTO`, which is why `ApiError` keeps `detail` at all.
 * Flattening it into `studentLoadFailureMessage` would throw away the only
 * machine-readable failure information the placement API produces, and with it
 * the honest per-reason panel below. See `lib/studentOutcome.ts`'s header.
 */
export function PlacementInvite() {
  const navigate = useNavigate()
  const { subjectCode = "" } = useParams<{ subjectCode: string }>()
  const query = usePlacementAvailability(subjectCode)
  const createPlacement = useCreatePlacement()
  const [raceUnavailable, setRaceUnavailable] = useState<PlacementAvailability | null>(null)

  const subjectName = SUPPORTED_SUBJECTS.find((s) => s.code === subjectCode)?.name ?? subjectCode

  async function handleStartNow() {
    setRaceUnavailable(null)
    try {
      const created = await createPlacement.mutateAsync({ subjectCode })
      navigate(`/student/placement/test/${created.assignmentId}`)
    } catch (err) {
      // 409: assembly became non-viable between this screen's load and the
      // click (e.g. a concurrent placement exhausted the pool) — the error's
      // `.detail` carries the identical availability shape, so this reuses
      // the same honest per-reason panel rather than a generic failure.
      if (err instanceof ApiError && err.status === 409 && err.detail) {
        setRaceUnavailable(err.detail as PlacementAvailability)
      } else {
        void query.refetch()
      }
    }
  }

  function handleLater() {
    navigate("/student")
  }

  return (
    <div className="lm-screen mx-auto flex w-full max-w-140 flex-col gap-6">
      <QueryState
        query={query}
        srHeading="Placement test"
        /* A skeleton in the shape of the panel that follows, not a sentence:
           the standing Phase-4 rule, applied as this screen's geometry
           settled. */
        skeleton={<PanelSkeleton />}
        /* `usePlacementAvailability` disables itself (`enabled: !!subjectCode`)
           rather than fetching an empty subject code — reachable only from a
           malformed link missing its subject segment, since every route that
           renders this screen supplies one. A skeleton there would wait on a
           fetch nothing schedules, so this names the actual problem instead. */
        idle={
          <EmptyState
            marginalia="Nothing to check"
            heading="No subject selected"
            body="This link is missing which subject to check for a placement test. Go back and open it from a subject's own page."
            action={{ label: "Back to dashboard", onClick: handleLater }}
          />
        }
        error={{
          heading: "We couldn't check whether a placement test is ready",
          body: studentLoadFailureMessage,
        }}
      >
        {(data) => {
          const effective = raceUnavailable ?? data
          const view = placementInviteView(effective)

          if (view.kind === "unavailable") {
            return (
              <>
                <h1 className="text-display-md text-ink">{subjectName}</h1>
                <Card>
                  <CardBody className="flex flex-col gap-3">
                    <div className="text-body-lg font-medium text-ink">
                      {view.message.heading}
                    </div>
                    <p className="text-body-md text-ink-muted">{view.message.body}</p>
                  </CardBody>
                </Card>
                <Button variant="secondary" onClick={handleLater} className="self-start">
                  Back to dashboard
                </Button>
              </>
            )
          }

          return (
            <>
              <div className="flex flex-col gap-2">
                <h1 className="text-display-md text-ink">
                  Get a real starting picture in {subjectName}
                </h1>
                <p className="text-body-md text-ink-muted">
                  A short placement test built from real past-paper questions across the syllabus
                  gives us a much better starting picture than a guess. It finds your strongest
                  and weakest topics, not a grade.
                </p>
              </div>

              <Card>
                <CardBody className="flex flex-col gap-2">
                  <div className="text-eyebrow text-ink-faint">This test</div>
                  <div className="text-body-lg font-medium text-ink">{view.estimate}</div>
                  <p className="text-body-sm text-ink-muted">
                    You can take it any time from this subject's screen. There's no rush.
                  </p>
                </CardBody>
              </Card>

              {/* Directly above the button that produced it (§12). */}
              {createPlacement.isError && !raceUnavailable ? (
                <p role="alert" className="text-body-sm text-err">
                  We couldn't start the test. Nothing has been used up, so trying again is safe.
                </p>
              ) : null}

              <div className="flex flex-wrap gap-3">
                <Button
                  variant="accent"
                  size="lg"
                  disabled={createPlacement.isPending}
                  onClick={() => void handleStartNow()}
                >
                  {createPlacement.isPending ? "Starting…" : "Start now"}
                </Button>
                <Button variant="ghost" size="lg" onClick={handleLater}>
                  Later
                </Button>
              </div>
            </>
          )
        }}
      </QueryState>
    </div>
  )
}
