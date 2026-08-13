import { useEffect, useRef, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { Chip } from "@/components/ui/chip"
import { Meter } from "@/components/ui/primitives"
import { ErrorState } from "@/components/ui/state-views"
import { useDueSession, useReviewCard } from "@/lib/hooks/useFlashcardApi"
import type { CardDTO, ReviewGrade, ReviewResultDTO } from "@/lib/flashcardTypes"
import { SUPPORTED_SUBJECTS } from "@/portals/student/screens/onboarding/onboardingData"
import {
  cardSourceLabel,
  dueStateView,
  gradeForKey,
  intervalChangeLabel,
  isRevealKey,
  nextDueMessage,
  sessionProgress,
  summarizeSession,
} from "./flashcardData"

/*
 * S-23 · Flashcard review session. A fast, repeated micro-interaction — the
 * spec calls out that friction here compounds, so the reveal and all four
 * grade buttons are real `<button>`s (native keyboard/AT semantics for
 * free) plus a window-level key handler for the numeric/space shortcuts
 * `gradeForKey`/`isRevealKey` define (P4.9 honesty rule 7). The end-of-
 * session summary reports only real facts `ReviewResultDTO` returned —
 * cards reviewed, the grade distribution, and each card's real interval
 * change — and deliberately never an XP number (honesty rule 5; see
 * `flashcardData.ts::SessionSummary`'s doc comment for why).
 */

const GRADE_BUTTONS: { grade: ReviewGrade; label: string; hint: string }[] = [
  { grade: "again", label: "Again", hint: "1" },
  { grade: "hard", label: "Hard", hint: "2" },
  { grade: "good", label: "Good", hint: "3" },
  { grade: "easy", label: "Easy", hint: "4" },
]

export function FlashcardReview() {
  const navigate = useNavigate()
  const { subjectCode = "" } = useParams<{ subjectCode: string }>()
  const subjectName = SUPPORTED_SUBJECTS.find((s) => s.code === subjectCode)?.name ?? subjectCode

  const dueQuery = useDueSession(subjectCode)
  const reviewCard = useReviewCard()

  // Snapshot the session's cards once, the moment they arrive — a `ref`
  // (not derived from `dueQuery.data` on every render) so a background
  // refetch (e.g. `useReviewCard`'s own invalidation) never reshuffles or
  // shortens the deck mid-session.
  const snapshotTaken = useRef(false)
  const [sessionCards, setSessionCards] = useState<CardDTO[] | null>(null)
  const [totalDue, setTotalDue] = useState(0)
  const [nextDueAt, setNextDueAt] = useState<string | null>(null)
  if (!snapshotTaken.current && dueQuery.data) {
    snapshotTaken.current = true
    const view = dueStateView(dueQuery.data)
    setSessionCards(view.kind === "due" ? view.cards : [])
    setTotalDue(view.totalDue)
    setNextDueAt(view.kind === "none" ? view.nextDueAt : null)
  }

  const [index, setIndex] = useState(0)
  const [revealed, setRevealed] = useState(false)
  const [results, setResults] = useState<ReviewResultDTO[]>([])

  const current = sessionCards?.[index] ?? null
  const finished = sessionCards !== null && index >= sessionCards.length

  function grade(g: ReviewGrade) {
    if (!current || reviewCard.isPending) return
    reviewCard.mutate(
      { cardId: current.id, grade: g },
      {
        onSuccess: (result) => {
          setResults((prev) => [...prev, result])
          setIndex((i) => i + 1)
          setRevealed(false)
        },
      },
    )
  }

  // Keyboard operability: Space/Enter reveals; 1-4 grade once revealed.
  // Real `<button>`s already give click/Enter/Space for free — this is the
  // additional fast-path the spec's "repeated micro-interaction" calls for.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (!current || finished) return
      if (!revealed) {
        if (isRevealKey(e.key)) {
          e.preventDefault()
          setRevealed(true)
        }
        return
      }
      const g = gradeForKey(e.key)
      if (g) {
        e.preventDefault()
        grade(g)
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, revealed, finished])

  if (dueQuery.isPending && !sessionCards) {
    return (
      <div className="lm-screen text-body-md text-t2">
        <h1 className="sr-only">Flashcard review — {subjectName}</h1>
        Loading your due cards…
      </div>
    )
  }

  if (dueQuery.isError && !sessionCards) {
    return (
      <>
        <h1 className="sr-only">Flashcard review — {subjectName}</h1>
        <ErrorState
          heading="Couldn't load your due cards"
          body={dueQuery.error?.message}
          action={{ label: "Try again", onClick: () => void dueQuery.refetch() }}
          className="lm-screen"
        />
      </>
    )
  }

  if (!sessionCards || sessionCards.length === 0) {
    return (
      <div className="lm-screen mx-auto flex max-w-[560px] flex-col items-center gap-4 py-16 text-center">
        <h1 className="text-body-lg font-medium text-t1 m-0">Nothing due today</h1>
        <p className="text-body-md text-t2">{nextDueMessage(nextDueAt)}</p>
        <Button variant="accent" onClick={() => navigate(`/student/flashcards/${subjectCode}`)}>
          Back to decks
        </Button>
      </div>
    )
  }

  if (finished) {
    const summary = summarizeSession(results)
    return (
      <div className="lm-screen mx-auto flex max-w-[560px] flex-col gap-6">
        <h1 className="font-serif text-display-md leading-display text-t1 m-0">
          Session complete
        </h1>
        <p className="text-body-md text-t2">
          {summary.reviewed} card{summary.reviewed === 1 ? "" : "s"} reviewed
          {totalDue > summary.reviewed
            ? ` — ${totalDue - summary.reviewed} still due today.`
            : "."}
        </p>

        <Card>
          <CardBody className="flex flex-col gap-3">
            <div className="text-dense-sm uppercase tracking-widest text-t3">Grades</div>
            <div className="flex flex-wrap gap-2">
              {GRADE_BUTTONS.map((g) => (
                <Chip key={g.grade} tone="neutral">
                  {g.label}: {summary.gradeCounts[g.grade]}
                </Chip>
              ))}
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardBody className="flex flex-col gap-2 p-0">
            {summary.intervalChanges.length === 0 ? (
              <p className="p-5 text-dense-sm text-t3">No cards were graded this session.</p>
            ) : (
              <ul className="flex flex-col">
                {summary.intervalChanges.map((change, i) => (
                  <li
                    key={change.cardId}
                    className="flex items-center justify-between gap-3 border-b border-border px-5 py-3 last:border-b-0"
                  >
                    <span className="text-dense-sm text-t2">Card {i + 1}</span>
                    <span className="font-mono text-dense-sm text-t1">
                      {intervalChangeLabel(change)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>

        <div className="flex flex-wrap gap-3">
          <Button
            variant="accent"
            size="lg"
            onClick={() => navigate(`/student/flashcards/${subjectCode}`)}
          >
            Back to decks
          </Button>
        </div>
      </div>
    )
  }

  const progress = sessionProgress(index + 1, sessionCards.length)

  return (
    <div className="lm-screen mx-auto flex max-w-[560px] flex-col gap-6">
      <h1 className="sr-only">Flashcard review — {subjectName}</h1>
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between text-dense-sm text-t2">
          <span>
            Card {progress.current} of {progress.total}
          </span>
          <span>{progress.remaining} remaining</span>
        </div>
        <Meter
          value={(progress.current / progress.total) * 100}
          label={`Reviewed ${progress.current} of ${progress.total} cards`}
        />
      </div>

      {current ? (
        <Card>
          <CardBody className="flex flex-col items-center gap-5 py-12 text-center">
            <Chip tone={current.source === "ai" ? "accent" : "neutral"}>
              {cardSourceLabel(current.source)}
            </Chip>
            <div className="text-display-md font-serif leading-display text-t1">
              {current.front}
            </div>

            {revealed ? (
              <div className="w-full border-t border-border pt-5 text-body-lg text-t1">
                {current.back}
              </div>
            ) : (
              <Button variant="secondary" size="lg" onClick={() => setRevealed(true)}>
                Reveal answer{" "}
                <span className="text-dense-sm text-t3">(Space)</span>
              </Button>
            )}
          </CardBody>
        </Card>
      ) : null}

      {revealed ? (
        <div className="grid grid-cols-2 gap-3 min-[480px]:grid-cols-4">
          {GRADE_BUTTONS.map((g) => (
            <Button
              key={g.grade}
              type="button"
              variant={g.grade === "again" ? "secondary" : "accent"}
              size="lg"
              disabled={reviewCard.isPending}
              onClick={() => grade(g.grade)}
            >
              <span className="flex flex-col items-center">
                {g.label}
                {/* No `opacity-70`: white at 70% over `--accent` measured
                    4.17:1 (serious axe violation, P4.9 chunk C) on the three
                    accent-variant buttons. `text-2xs` already de-emphasises the
                    shortcut against its label, and this hint is a keyboard
                    affordance — the one thing on this button that must not be
                    hard to read. */}
                <span className="text-2xs">({g.hint})</span>
              </span>
            </Button>
          ))}
        </div>
      ) : null}

      {reviewCard.isError ? (
        <p className="text-dense-sm text-err">We couldn't record that grade. Try again.</p>
      ) : null}
    </div>
  )
}
