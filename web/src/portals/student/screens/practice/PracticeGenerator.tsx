/* Hallmark · pre-emit critique: P4 H4 E5 S5 R5 V3 */
import { useRef, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { ListSkeleton, PageHeaderSkeleton, PanelSkeleton } from "@/components/ui/loading-shapes"
import { EmptyState } from "@/components/ui/state-views"
import { QueryState } from "@/components/ui/query-state"
import { Slider } from "@/components/ui/slider"
import { ApiError } from "@/lib/api"
import { useCreatePractice, usePracticePreview, usePracticeTopics } from "@/lib/hooks/usePracticeApi"
import type { CreatePracticeResponse, PracticeFilterSet, PracticePreview } from "@/lib/practiceTypes"
import { useReference, useSubjectName } from "@/lib/hooks/useReferenceApi"
import { studentLoadFailureMessage } from "@/lib/studentOutcome"
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

export function PracticeGenerator() {
  const navigate = useNavigate()
  const { subjectCode = "" } = useParams<{ subjectCode: string }>()
  const subjectName = useSubjectName(subjectCode)
  const referenceQuery = useReference()
  const availableDifficultyBands = referenceQuery.data?.difficultyBands ?? []

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
  // Independent of `topicsQuery` below and left hand-rolled rather than
  // nested in its own `<QueryState>`: it drives a single inline line of live
  // feedback ("Checking what matches…" / a one-line failure) beside the
  // filter controls, not a panel-sized loading/error treatment.
  // `QueryState`'s `error` always renders the full centred `ErrorState`
  // panel, which would visually balloon this filter-adjacent line into a
  // page-sized block every time a preview refetch fails — exactly the
  // layout shift §12 exists to prevent, just introduced by the wrapper
  // rather than avoided by it.
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

  return (
    <div className="lm-screen lm-read flex flex-col gap-6">
      <QueryState
        query={topicsQuery}
        srHeading={`Practice for ${subjectName}`}
        skeleton={
          <>
            <PageHeaderSkeleton />
            <PanelSkeleton />
            <ListSkeleton rows={4} />
          </>
        }
        /* `usePracticeTopics` disables itself (`enabled: !!subjectCode`)
           rather than fetching an empty subject code — reachable only from a
           malformed link missing its subject segment. */
        idle={
          <EmptyState
            marginalia="Nothing to build from"
            heading="No subject selected"
            body="This link is missing which subject to practise. Go back and open practice from a subject's own page."
            action={{ label: "Back to dashboard", onClick: () => navigate("/student") }}
          />
        }
        error={{
          heading: "Couldn't load practice topics",
          body: studentLoadFailureMessage,
        }}
      >
        {(data) => {
          if (created) {
            return (
              <>
                <div className="flex flex-col gap-2">
                  <h1 className="text-display-lg text-ink">
                    Your {subjectName} practice set is ready
                  </h1>
                  <p className="lm-prose text-body-lg text-ink-muted">
                    <span className="text-data-md text-ink">{created.questionCount}</span>{" "}
                    question
                    {created.questionCount === 1 ? "" : "s"}
                    {created.reason === "insufficient_pool"
                      ? `, fewer than the ${created.requestedCount} you asked for, since that's all that matched.`
                      : ", ready to go."}
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
              </>
            )
          }

          const groups = groupTopicsBySyllabusGroup(data.topics)
          const untopicedCount = data.untopicedCount
          const effectivePreview = raceUnavailable ?? previewQuery.data ?? null
          const view = effectivePreview ? practiceAvailabilityView(effectivePreview) : null

          return (
            <>
              <div className="flex flex-col gap-2">
                <h1 className="text-display-lg text-ink">Practice for {subjectName}</h1>
                <p className="lm-prose text-body-lg text-ink-muted">
                  Build a set of real past-paper questions from the topics and difficulty you
                  choose.
                </p>
              </div>

              <Card>
                <CardBody className="flex flex-col gap-3">
                  <label className="text-label text-ink" htmlFor="practice-count">
                    Number of questions: <span className="text-data-md text-ink">{count}</span>
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
                  <p className="text-body-sm text-ink-faint">
                    Draws only from topics recorded as weak for you. Your topic selection below is
                    ignored while this is on.
                  </p>
                </CardBody>
              </Card>

              {/* No card-wide dim while `weakTopicsOnly` is on: `opacity-50`
                  here also dimmed this card's "Topics" heading and its two
                  explanatory paragraphs, measuring 2.28:1 (serious axe
                  violation, P4.9 chunk C). The disabled affordance now comes
                  from C-14 Checkbox's own `has-disabled:` rule, which the
                  `<fieldset disabled>` below drives — so only the
                  genuinely-inactive controls dim, and the prose that
                  explains *why* they are inactive stays readable. */}
              <Card>
                <CardBody className="flex flex-col gap-5">
                  <h2 className="text-eyebrow text-ink-faint">Topics</h2>
                  {groups.length === 0 ? (
                    <p className="text-body-sm text-ink-faint">
                      No servable topics for this subject yet.
                    </p>
                  ) : (
                    <fieldset disabled={weakTopicsOnly} className="flex flex-col gap-5">
                      <legend className="sr-only">Choose topics to practise</legend>
                      {groups.map((group) => (
                        <div key={group.syllabusGroup} className="flex flex-col gap-2">
                          <h3 className="text-label text-ink">{group.syllabusGroup}</h3>
                          <div className="flex flex-col gap-1.5 ps-1">
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
                    <p className="text-body-sm text-ink-faint">
                      {droppedWeakTopics.length === 1
                        ? "One of your weak topics"
                        : `${droppedWeakTopics.length} of your weak topics`}{" "}
                      ({droppedWeakTopics.join(", ")}){" "}
                      {droppedWeakTopics.length === 1 ? "isn't" : "aren't"} in the question bank
                      for this subject yet, so{" "}
                      {droppedWeakTopics.length === 1 ? "it wasn't" : "they weren't"} pre-selected.
                    </p>
                  ) : null}
                  {untopicedCount > 0 ? (
                    <p className="text-body-sm text-ink-faint">
                      {untopicedCount} more question{untopicedCount === 1 ? "" : "s"} in the bank{" "}
                      {untopicedCount === 1 ? "isn't" : "aren't"} tagged to a topic.{" "}
                      {untopicedCount === 1 ? "It's" : "They're"} included automatically when no
                      topic filter is set.
                    </p>
                  ) : null}
                </CardBody>
              </Card>

              <Card>
                <CardBody className="flex flex-col gap-3">
                  <h2 className="text-eyebrow text-ink-faint">Difficulty</h2>
                  <div className="flex flex-wrap gap-2">
                    {availableDifficultyBands.map((band) => {
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
                  <p className="text-body-sm text-ink-faint">
                    No bands selected means no filter on difficulty.
                  </p>
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
                            <h2 className="text-display-sm text-ink">{msg.heading}</h2>
                            <p className="text-body-md text-ink-muted">{msg.body}</p>
                          </>
                        )
                      })()
                    ) : view.kind === "shortfall" ? (
                      <>
                        <h2 className="text-display-sm text-ink">
                          Only {view.availableCount} of {view.requestedCount} requested questions
                          match
                        </h2>
                        <p className="text-body-md text-ink-muted">
                          You can still create a shorter set with what's available, or broaden
                          your topic or difficulty selection to reach the full count.
                        </p>
                      </>
                    ) : (
                      <h2 className="text-display-sm text-ink">
                        {view.availableCount} question{view.availableCount === 1 ? "" : "s"}{" "}
                        match, ready to create
                      </h2>
                    )}

                    {createPractice.isError && !raceUnavailable ? (
                      <p className="text-body-sm text-err">
                        We couldn't create this set. Try again.
                      </p>
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
                <p className="text-body-sm text-ink-faint">Checking what matches…</p>
              ) : previewQuery.isError ? (
                <p className="text-body-sm text-err">
                  We couldn't check availability. Try changing a filter.
                </p>
              ) : null}
            </>
          )
        }}
      </QueryState>
    </div>
  )
}
