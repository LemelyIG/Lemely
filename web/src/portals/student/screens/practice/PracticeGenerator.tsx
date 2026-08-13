import { useRef, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { ErrorState } from "@/components/ui/state-views"
import { Slider } from "@/components/ui/slider"
import { ApiError } from "@/lib/api"
import { useCreatePractice, usePracticePreview, usePracticeTopics } from "@/lib/hooks/usePracticeApi"
import type { CreatePracticeResponse, PracticeFilterSet, PracticePreview } from "@/lib/practiceTypes"
import { SUPPORTED_SUBJECTS } from "@/portals/student/screens/onboarding/onboardingData"
import {
  groupTopicsBySyllabusGroup,
  practiceAvailabilityView,
  practiceUnavailableMessage,
  weakTopicPrefill,
} from "./practiceData"

/*
 * S-20 · Practice generator. Filter set (count, topics, weak-topics-only,
 * difficulty) lives entirely in this screen's own state; `usePracticePreview`
 * re-fetches the live match count on every change (no write) so the create
 * button always reflects reality. Topic chips are grouped by
 * `syllabusGroup` (`groupTopicsBySyllabusGroup`) rather than a flat list —
 * see that function's docstring for why a flat list would be actively
 * misleading. Weak-topic prefill comes from the server's own
 * `PracticeTopicsDTO.weakTopics` (`weakPrefilled` ref below), never derived
 * locally.
 */

const DIFFICULTY_BANDS = ["foundation", "standard", "challenge"] as const

export function PracticeGenerator() {
  const navigate = useNavigate()
  const { subjectCode = "" } = useParams<{ subjectCode: string }>()
  const subjectName = SUPPORTED_SUBJECTS.find((s) => s.code === subjectCode)?.name ?? subjectCode

  const topicsQuery = usePracticeTopics(subjectCode)
  const createPractice = useCreatePractice()

  const [count, setCount] = useState(10)
  const [selectedTopics, setSelectedTopics] = useState<Set<string>>(new Set())
  const [weakTopicsOnly, setWeakTopicsOnly] = useState(false)
  const [difficultyBands, setDifficultyBands] = useState<Set<string>>(new Set())
  const [raceUnavailable, setRaceUnavailable] = useState<PracticePreview | null>(null)
  const [created, setCreated] = useState<CreatePracticeResponse | null>(null)

  // Prefill selected topics from the server's `weakTopics` exactly once,
  // the moment they arrive — a `ref` (not a `useEffect` on every render)
  // so a student who has already deselected a weak topic never has that
  // choice silently reverted by a background refetch.
  //
  // Only the weak topics that actually have a chip here are prefilled:
  // `weakTopics` and `topics` are resolved independently server-side and the
  // first is not a subset of the second, so prefilling verbatim would apply
  // a filter with no visible control (see `weakTopicPrefill`). What was
  // dropped is kept and shown rather than silently swallowed.
  const weakPrefilled = useRef(false)
  const [droppedWeakTopics, setDroppedWeakTopics] = useState<string[]>([])
  if (!weakPrefilled.current && topicsQuery.data) {
    weakPrefilled.current = true
    const prefill = weakTopicPrefill(topicsQuery.data.weakTopics, topicsQuery.data.topics)
    if (prefill.selected.length > 0) setSelectedTopics(new Set(prefill.selected))
    if (prefill.dropped.length > 0) setDroppedWeakTopics(prefill.dropped)
  }

  const filters: PracticeFilterSet = {
    subjectCode,
    count,
    topics: [...selectedTopics],
    weakTopicsOnly,
    difficultyBands: [...difficultyBands],
    source: null,
  }
  const previewQuery = usePracticePreview(filters)

  function toggleTopic(topic: string) {
    setRaceUnavailable(null)
    setSelectedTopics((prev) => {
      const next = new Set(prev)
      if (next.has(topic)) next.delete(topic)
      else next.add(topic)
      return next
    })
  }

  function toggleBand(band: string) {
    setRaceUnavailable(null)
    setDifficultyBands((prev) => {
      const next = new Set(prev)
      if (next.has(band)) next.delete(band)
      else next.add(band)
      return next
    })
  }

  async function handleCreate() {
    setRaceUnavailable(null)
    try {
      const result = await createPractice.mutateAsync(filters)
      setCreated(result)
    } catch (err) {
      // 409: the pool became non-viable between this screen's last preview
      // and the click — the error's `.detail` carries the identical preview
      // shape, so this reuses the same honest availability panel rather
      // than a generic failure (mirrors `PlacementInvite`'s race handling).
      if (err instanceof ApiError && err.status === 409 && err.detail) {
        setRaceUnavailable(err.detail as PracticePreview)
      } else {
        void previewQuery.refetch()
      }
    }
  }

  if (topicsQuery.isPending) {
    return (
      <div className="lm-screen text-body-md text-t2">
        <h1 className="sr-only">Practice — {subjectName}</h1>
        Loading topics…
      </div>
    )
  }

  if (topicsQuery.isError || !topicsQuery.data) {
    return (
      <>
        <h1 className="sr-only">Practice — {subjectName}</h1>
        <ErrorState
          heading="Couldn't load practice topics"
          body={topicsQuery.error?.message}
          action={{ label: "Try again", onClick: () => void topicsQuery.refetch() }}
          className="lm-screen"
        />
      </>
    )
  }

  if (created) {
    return (
      <div className="lm-screen mx-auto flex max-w-[560px] flex-col gap-6">
        <div className="flex flex-col gap-2">
          <h1 className="font-serif text-display-md leading-display text-t1 m-0">
            Your {subjectName} practice set is ready
          </h1>
          <p className="text-body-md text-t2">
            {created.questionCount} question{created.questionCount === 1 ? "" : "s"} —
            {created.reason === "insufficient_pool"
              ? ` fewer than the ${created.requestedCount} you asked for, since that's all that matched.`
              : " ready to go."}
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button
            variant="accent"
            size="lg"
            onClick={() => navigate(`/student/practice/set/${created.assignmentId}`)}
          >
            Start now
          </Button>
          <Button
            variant="secondary"
            size="lg"
            onClick={() => navigate(`/student/practice/print/${created.assignmentId}`)}
          >
            Print instead
          </Button>
        </div>
      </div>
    )
  }

  const groups = groupTopicsBySyllabusGroup(topicsQuery.data.topics)
  const untopicedCount = topicsQuery.data.untopicedCount
  const effectivePreview = raceUnavailable ?? previewQuery.data ?? null
  const view = effectivePreview ? practiceAvailabilityView(effectivePreview) : null

  return (
    <div className="lm-screen mx-auto flex max-w-[720px] flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="font-serif text-display-md leading-display text-t1 m-0">
          Practice — {subjectName}
        </h1>
        <p className="text-body-md text-t2">
          Build a set of real past-paper questions from the topics and difficulty you choose.
        </p>
      </div>

      <Card>
        <CardBody className="flex flex-col gap-3">
          <label className="text-dense-sm text-t2" htmlFor="practice-count">
            Number of questions: {count}
          </label>
          <Slider
            id="practice-count"
            value={count}
            onValueChange={setCount}
            min={5}
            max={30}
            step={5}
            aria-label="Number of practice questions"
          />
        </CardBody>
      </Card>

      <Card>
        <CardBody className="flex flex-col gap-3">
          <Checkbox
            label="Weak topics only"
            checked={weakTopicsOnly}
            onChange={(e) => {
              setRaceUnavailable(null)
              setWeakTopicsOnly(e.target.checked)
            }}
          />
          <p className="text-dense-sm text-t3">
            Draws only from topics recorded as weak for you. Your topic selection below is ignored
            while this is on.
          </p>
        </CardBody>
      </Card>

      {/* No card-wide dim while `weakTopicsOnly` is on: `opacity-50` here also
          dimmed this card's "Topics" heading and its two explanatory
          paragraphs, measuring 2.28:1 (serious axe violation, P4.9 chunk C).
          The disabled affordance now comes from C-14 Checkbox's own
          `has-disabled:` rule, which the `<fieldset disabled>` below drives —
          so only the genuinely-inactive controls dim, and the prose that
          explains *why* they are inactive stays readable. */}
      <Card>
        <CardBody className="flex flex-col gap-5">
          <div className="text-dense-sm uppercase tracking-widest text-t3">Topics</div>
          {groups.length === 0 ? (
            <p className="text-dense-sm text-t3">No servable topics for this subject yet.</p>
          ) : (
            <fieldset disabled={weakTopicsOnly} className="flex flex-col gap-5">
              <legend className="sr-only">Choose topics to practise</legend>
              {groups.map((group) => (
                <div key={group.syllabusGroup} className="flex flex-col gap-2">
                  <div className="text-dense-sm font-medium text-t1">{group.syllabusGroup}</div>
                  <div className="flex flex-col gap-1.5 pl-1">
                    {group.topics.map((t) => (
                      <Checkbox
                        key={t.topic}
                        label={`${t.topic} (${t.availableCount})`}
                        checked={selectedTopics.has(t.topic)}
                        onChange={() => toggleTopic(t.topic)}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </fieldset>
          )}
          {droppedWeakTopics.length > 0 ? (
            <p className="text-dense-sm text-t3">
              {droppedWeakTopics.length === 1 ? "One of your weak topics" : `${droppedWeakTopics.length} of your weak topics`}{" "}
              ({droppedWeakTopics.join(", ")}) {droppedWeakTopics.length === 1 ? "isn't" : "aren't"} in
              the question bank for this subject yet, so {droppedWeakTopics.length === 1 ? "it wasn't" : "they weren't"} pre-selected.
            </p>
          ) : null}
          {untopicedCount > 0 ? (
            <p className="text-dense-sm text-t3">
              {untopicedCount} more question{untopicedCount === 1 ? "" : "s"} in the bank {untopicedCount === 1 ? "isn't" : "aren't"} tagged to a topic — included automatically when no topic filter is set.
            </p>
          ) : null}
        </CardBody>
      </Card>

      <Card>
        <CardBody className="flex flex-col gap-3">
          <div className="text-dense-sm uppercase tracking-widest text-t3">Difficulty</div>
          <div className="flex flex-wrap gap-2">
            {DIFFICULTY_BANDS.map((band) => {
              const active = difficultyBands.has(band)
              return (
                <Button
                  key={band}
                  type="button"
                  variant={active ? "accent" : "secondary"}
                  size="sm"
                  aria-pressed={active}
                  onClick={() => toggleBand(band)}
                >
                  {band[0].toUpperCase() + band.slice(1)}
                </Button>
              )
            })}
          </div>
          <p className="text-dense-sm text-t3">No bands selected means no filter on difficulty.</p>
        </CardBody>
      </Card>

      {view ? (
        <Card className={view.kind === "unavailable" ? "border-warn" : undefined}>
          <CardBody className="flex flex-col gap-3">
            {view.kind === "unavailable" ? (
              (() => {
                const msg = practiceUnavailableMessage(view.reason)
                return (
                  <>
                    <div className="text-body-lg font-medium text-t1">{msg.heading}</div>
                    <p className="text-body-md text-t2">{msg.body}</p>
                  </>
                )
              })()
            ) : view.kind === "shortfall" ? (
              <>
                <div className="text-body-lg font-medium text-t1">
                  Only {view.availableCount} of {view.requestedCount} requested questions match
                </div>
                <p className="text-body-md text-t2">
                  You can still create a shorter set with what's available, or broaden your topic
                  or difficulty selection to reach the full count.
                </p>
              </>
            ) : (
              <div className="text-body-lg font-medium text-t1">
                {view.availableCount} question{view.availableCount === 1 ? "" : "s"} match — ready
                to create
              </div>
            )}

            {createPractice.isError && !raceUnavailable ? (
              <p className="text-dense-sm text-err">We couldn't create this set. Try again.</p>
            ) : null}

            <div className="flex flex-wrap gap-3">
              <Button
                variant="accent"
                size="lg"
                disabled={view.kind === "unavailable" || createPractice.isPending}
                onClick={() => void handleCreate()}
              >
                {createPractice.isPending
                  ? "Creating…"
                  : view.kind === "shortfall"
                    ? `Create anyway (${view.availableCount})`
                    : "Create practice set"}
              </Button>
            </div>
          </CardBody>
        </Card>
      ) : previewQuery.isPending ? (
        <p className="text-dense-sm text-t3">Checking what matches…</p>
      ) : previewQuery.isError ? (
        <p className="text-dense-sm text-err">We couldn't check availability. Try changing a filter.</p>
      ) : null}
    </div>
  )
}
