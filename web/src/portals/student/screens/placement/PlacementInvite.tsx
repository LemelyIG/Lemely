import { useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { ErrorState } from "@/components/ui/state-views"
import { ApiError } from "@/lib/api"
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
 */
export function PlacementInvite() {
  const navigate = useNavigate()
  const { subjectCode = "" } = useParams<{ subjectCode: string }>()
  const { data, isPending, isError, error, refetch } = usePlacementAvailability(subjectCode)
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
        void refetch()
      }
    }
  }

  function handleLater() {
    navigate("/student")
  }

  /* The `sr-only` h1 on the loading and error branches follows the P3
   * pattern (ReviewItem/StudentDetail/QuizResults): every branch of a screen
   * is still a page and still owes a level-one heading, and `ErrorState`
   * renders its own heading as a non-heading element (a Phase-2.5 gap
   * recorded in that phase's report §8). */
  if (isPending) {
    return (
      <div className="lm-screen text-body-md text-t2">
        <h1 className="sr-only">Placement test</h1>
        Checking availability…
      </div>
    )
  }

  if (isError || !data) {
    return (
      <>
        <h1 className="sr-only">Placement test</h1>
        <ErrorState
          heading="Couldn't check placement-test availability"
          body={error?.message}
          action={{ label: "Try again", onClick: () => void refetch() }}
          className="lm-screen"
        />
      </>
    )
  }

  const effective = raceUnavailable ?? data
  const view = placementInviteView(effective)

  if (view.kind === "unavailable") {
    return (
      <div className="lm-screen mx-auto flex max-w-[560px] flex-col gap-6">
        <h1 className="font-serif text-display-md leading-display text-t1 m-0">{subjectName}</h1>
        <Card>
          <CardBody className="flex flex-col gap-3">
            <div className="text-body-lg font-medium text-t1">{view.message.heading}</div>
            <p className="text-body-md text-t2">{view.message.body}</p>
          </CardBody>
        </Card>
        <Button variant="secondary" onClick={handleLater} className="self-start">
          Back to dashboard
        </Button>
      </div>
    )
  }

  return (
    <div className="lm-screen mx-auto flex max-w-[560px] flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="font-serif text-display-md leading-display text-t1 m-0">
          Get a real starting picture in {subjectName}
        </h1>
        <p className="text-body-md text-t2">
          A short placement test built from real past-paper questions across the syllabus gives
          us a much better starting picture than a guess — strongest and weakest topics, not a
          grade.
        </p>
      </div>

      <Card>
        <CardBody className="flex flex-col gap-2">
          <div className="text-dense-sm text-t3">This test</div>
          <div className="text-body-lg font-medium text-t1">{view.estimate}</div>
          <p className="text-dense-sm text-t2">
            You can take it any time from this subject's screen — there's no rush.
          </p>
        </CardBody>
      </Card>

      {createPlacement.isError && !raceUnavailable ? (
        <p className="text-dense-sm text-err">We couldn't start the test. Try again.</p>
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
    </div>
  )
}
