import { useEffect, useRef, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { Kbd } from "@/components/ui/kbd"
import { PageHeaderSkeleton, PanelSkeleton } from "@/components/ui/loading-shapes"
import { ProgressBar } from "@/components/ui/progress-bar"
import { EmptyState } from "@/components/ui/state-views"
import { QueryState } from "@/components/ui/query-state"
import { useDueSession, useReviewCard } from "@/lib/hooks/useFlashcardApi"
import type { CardDTO, ReviewGrade, ReviewResultDTO } from "@/lib/flashcardTypes"
import { SUPPORTED_SUBJECTS } from "@/portals/student/screens/onboarding/onboardingData"
import { studentLoadFailureMessage } from "@/lib/studentOutcome"
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

/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */

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
 *
 * P4.3 (Study Notebook). This is the most literally paper-like screen in the
 * product — one card, centred, nothing else — so it is where the Read lane's
 * texture allowance (§8, §13) is actually spent: ruled paper behind the card
 * face, and nowhere else on the surface. Two things beyond styling:
 *
 *   1. **The keyboard shortcuts were prose.** "(Space)" and "(1)" were plain
 *      spans inside the button labels, so the one affordance that makes this
 *      screen fast was typographically indistinguishable from the label it
 *      annotated. C-19 `Kbd` exists for exactly this and was unused.
 *   2. **A failed grade stranded the session.** `reviewCard.isError` printed a
 *      line at the bottom of the page and left the same card on screen with
 *      all four grade buttons live — so the natural response (press it again)
 *      looked identical to the press that had just failed. The message now
 *      sits with the buttons and names the card that did not record.
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

  /*
   * `dueQuery`'s pending/error states only matter before the snapshot above
   * has ever run — once `sessionCards` is set, this screen deliberately
   * stops looking at `dueQuery.status` at all (see the snapshot comment):
   * `useReviewCard`'s own `onSuccess` invalidates the due-session query, and
   * a background refetch of it failing mid-session must not blank out the
   * card the student is looking at. `<QueryState>` renders its `children`
   * whenever `status === "success"`, which would fire on every one of those
   * background refetches too — so rather than let `<QueryState>` own the
   * whole render (which would reintroduce exactly that bug), it is scoped to
   * this one `!sessionCards` gate, matching what the two branches it
   * replaces already did by hand.
   *
   * The `children` callback below can still be invoked once, on the very
   * render where `dueQuery` first succeeds — but by then the snapshot effect
   * above has already called `setSessionCards` earlier in that same
   * function call, and React restarts a component synchronously when it
   * sees a state update during render, discarding whatever that render
   * would have returned. So this function exists only to satisfy
   * `<QueryState>`'s contract; nothing it returns is ever the render a
   * reader sees, because the next (real) pass has `sessionCards` set and
   * exits through this `if` before `<QueryState>` is even constructed.
   */
  if (!sessionCards) {
    return (
      <div className="lm-screen lm-read flex flex-col gap-6">
        <QueryState
          query={dueQuery}
          srHeading={`Flashcard review for ${subjectName}`}
          skeleton={
            <>
              <PageHeaderSkeleton />
              <PanelSkeleton bodyClassName="h-40" />
            </>
          }
          error={{
            heading: "Couldn't load your due cards",
            body: studentLoadFailureMessage,
          }}
        >
          {() => null}
        </QueryState>
      </div>
    )
  }

  if (sessionCards.length === 0) {
    return (
      <>
        <h1 className="sr-only">Flashcard review for {subjectName}</h1>
        <EmptyState
          marginalia="All caught up"
          heading="Nothing due today"
          body={nextDueMessage(nextDueAt)}
          action={{
            label: "Back to decks",
            onClick: () => navigate(`/student/flashcards/${subjectCode}`),
          }}
          className="lm-screen"
        />
      </>
    )
  }

  if (finished) {
    const summary = summarizeSession(results)
    return (
      <div className="lm-screen lm-read flex flex-col gap-6">
        <div className="flex flex-col gap-2">
          <h1 className="text-display-lg text-ink">Session complete</h1>
          <p className="lm-prose text-body-lg text-ink-muted">
            <span className="text-data-md text-ink">{summary.reviewed}</span> card
            {summary.reviewed === 1 ? "" : "s"} reviewed
            {totalDue > summary.reviewed
              ? `, ${totalDue - summary.reviewed} still due today.`
              : "."}
          </p>
        </div>

        <Card>
          <CardBody className="flex flex-col gap-3">
            <h2 className="text-eyebrow text-ink-faint">Grades</h2>
            <div className="flex flex-wrap gap-2">
              {GRADE_BUTTONS.map((g) => (
                <span key={g.grade} className="flex items-center gap-1.5">
                  <Badge tone="sage">{g.label}</Badge>
                  <span className="text-data-md text-ink">{summary.gradeCounts[g.grade]}</span>
                </span>
              ))}
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardBody className="flex flex-col gap-2 p-0">
            {summary.intervalChanges.length === 0 ? (
              <p className="p-5 text-body-sm text-ink-faint">
                No cards were graded this session.
              </p>
            ) : (
              <ul className="flex flex-col">
                {summary.intervalChanges.map((change, i) => (
                  <li
                    key={change.cardId}
                    className="flex items-center justify-between gap-3 border-b border-rule px-5 py-3 last:border-b-0"
                  >
                    <span className="text-body-sm text-ink-muted">Card {i + 1}</span>
                    <span className="text-data-md text-ink">
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
    /* Vertically centred from `md` up. A review session is one card at a time
       and nothing else, so on a desktop well the content occupied the top
       third and left two-thirds empty below it — the same shape as D4.2's
       integrity-sidebar finding, and on the screen least able to carry it,
       since the card face IS the screen.
       `min-h` rather than `h`, so a long question still grows the column
       instead of overflowing a fixed box; and `md:` only, because on a phone
       the content already fills the viewport and centring would push the
       grade buttons below the fold. */
    <div className="lm-screen lm-read flex flex-col gap-6 md:min-h-[68vh] md:justify-center">
      <h1 className="sr-only">Flashcard review for {subjectName}</h1>
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between text-body-sm text-ink-muted">
          <span>
            Card <span className="text-data-md text-ink">{progress.current}</span> of{" "}
            <span className="text-data-md text-ink">{progress.total}</span>
          </span>
          <span>{progress.remaining} remaining</span>
        </div>
        {/* C-24 ProgressBar rather than `Meter`: the bar and the study plan's
            week bar are the same object on the same surface and were two
            different components, one of which animated `width` (§9.2 forbids
            animating anything but transform and opacity). */}
        <ProgressBar
          value={(progress.current / progress.total) * 100}
          ariaLabel={`Reviewed ${progress.current} of ${progress.total} cards`}
        />
      </div>

      {current ? (
        <Card>
          {/* `ruled-bg`: DESIGN.md §8 item 2 names ruled paper for the Read
              lane, and this card face is the one place in the product that is
              literally a piece of paper with a question on it. It is the only
              texture element on the viewport, well inside §8's budget of two. */}
          <CardBody className="ruled-bg flex flex-col items-center gap-5 py-12 text-center">
            <Badge tone={current.source === "ai" ? "lilac" : "sage"}>
              {cardSourceLabel(current.source)}
            </Badge>
            <div className="lm-prose text-display-md text-ink">{current.front}</div>

            {revealed ? (
              /* `display-sm`, not `body-lg`. The answer is the entire payload
                 of a reveal — it is the thing a student came here to check
                 themselves against — and at body weight under a `display-md`
                 question it was the quietest element on the card. It stays a
                 rung below the question, because the question is what orients
                 you, but it is no longer an afterthought. */
              <div className="lm-prose w-full border-t border-rule pt-5 text-display-sm text-ink">
                {current.back}
              </div>
            ) : (
              <Button variant="secondary" size="lg" onClick={() => setRevealed(true)}>
                Reveal answer <Kbd>Space</Kbd>
              </Button>
            )}
          </CardBody>
        </Card>
      ) : null}

      {revealed ? (
        <div className="flex flex-col gap-3">
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
                <span className="flex flex-col items-center gap-1">
                  {g.label}
                  {/* No `opacity-70`: white at 70% over `--accent` measured
                      4.17:1 (serious axe violation, P4.9 chunk C) on the three
                      accent-variant buttons. This hint is a keyboard
                      affordance — the one thing on this button that must not be
                      hard to read — so it is a real `Kbd` at full contrast. */}
                  <Kbd className="border-current/40 bg-transparent text-current">{g.hint}</Kbd>
                </span>
              </Button>
            ))}
          </div>

          {/* Sits with the buttons, not at the foot of the page. A grade that
              failed to record leaves the SAME card on screen, so without this
              adjacency the student cannot tell a failed press from a press
              they imagined. */}
          {reviewCard.isError ? (
            <p className="text-body-sm text-err">
              We couldn't record that grade, so this card is still waiting. Try again.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
