/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 */
import { ArrowLeft, ArrowRight, X } from "@phosphor-icons/react"
import { useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { ComboChip, SubjectDot } from "@/components/redesign"
import { PageHeading } from "@/components/ui/page-heading"
import { ConfirmModal } from "@/components/ui/confirm-modal"
import { Kbd } from "@/components/ui/kbd"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { applyGradeOutcome, beginRetry, newClientReviewId, registerGrade, startSession, type FlashcardSessionState, type FailedGrade } from "@/lib/flashcardSession"
import { QueryState } from "@/components/ui/query-state"
import { useSubjectName } from "@/lib/hooks/useReferenceApi"
import { canGradeCard, isEditableTarget, isForeignControl } from "./reviewProgression"
import type { CardDTO, ReviewGrade } from "@/lib/flashcardTypes"
import { haptic } from "@/lib/haptics"
import { useDueSession, useFlashcardDeck, useReviewCard } from "@/lib/hooks/useFlashcardApi"
import { ReviewCard } from "./ReviewCard"
import { ReviewDone } from "./ReviewDone"
import { comingBackLine, topicName } from "./flashcardsView"
import { doneView, gradeButtons, progressView, reviewKeyAction, syncBannerText } from "./reviewView"
import { PRIMARY_BTN } from "./parts/buttonStyles"
import { PAGE_SKELETON } from "./parts/skeletonStyles"

const GRADE_TONE: Record<ReviewGrade, string> = {
  again: "bg-error-container text-on-error-container",
  hard: "bg-tertiary-container text-on-tertiary-container",
  good: "bg-success-container text-on-success-container",
  easy: "bg-primary-container text-primary",
}

export function ReviewScreen() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const deckId = params.get("deck")
  const subjectCode = params.get("subject")
  const due = useDueSession(deckId ? { deckId } : subjectCode ? { subjectCode } : {})
  const deck = useFlashcardDeck(deckId ?? "")
  const subjectName = useSubjectName(subjectCode ?? "")
  const reviewCard = useReviewCard()
  const backTo = deckId ? `/student/flashcards/deck/${deckId}` : "/student/flashcards"

  // R1: snapshot once; a background refetch never reshuffles the session.
  const snapshotTaken = useRef(false)
  const [cards, setCards] = useState<CardDTO[] | null>(null)
  const [meta, setMeta] = useState({ totalDue: 0, nextDueAt: null as string | null, againDelay: 10 })
  if (!snapshotTaken.current && due.data) {
    snapshotTaken.current = true
    setCards(due.data.cards)
    setMeta({ totalDue: due.data.totalDue, nextDueAt: due.data.nextDueAt, againDelay: due.data.againDelayMinutes })
  }

  const [index, setIndex] = useState(0)
  const [revealed, setRevealed] = useState(false)
  const [session, setSession] = useState<FlashcardSessionState>(startSession)
  const sessionRef = useRef(session)
  function updateSession(update: (s: FlashcardSessionState) => FlashcardSessionState) {
    const next = update(sessionRef.current)
    sessionRef.current = next
    setSession(next)
  }
  // C-24: leaving with unsaved ratings asks in the product's own dialog, never window.confirm.
  const [exitModalOpen, setExitModalOpen] = useState(false)
  function leaveReview() {
    // Read the ref, not state: a grade can settle between the last render and this press.
    const latest = sessionRef.current
    if (latest.failed.length > 0 || latest.inFlight > 0) {
      setExitModalOpen(true)
      return
    }
    navigate(backTo)
  }
  function confirmLeave() {
    setExitModalOpen(false)
    navigate(backTo)
  }
  const current = cards?.[index] ?? null
  const finished = cards !== null && cards.length > 0 && index >= cards.length

  const graded = useRef(new Set<string>())
  const retrying = useRef(false)
  function send(entry: FailedGrade) {
    void reviewCard.mutateAsync({ cardId: entry.cardId, grade: entry.grade, clientReviewId: entry.clientReviewId })
      .then((result) => updateSession((s) => applyGradeOutcome(s, { kind: "settled", result })))
      .catch(() => updateSession((s) => applyGradeOutcome(s, { kind: "failed", ...entry })))
  }

  // Advance immediately, but reserve this card synchronously against repeated input.
  function grade(g: ReviewGrade) {
    if (!current || !canGradeCard(current.id, revealed, graded.current)) return
    const card = current
    graded.current.add(card.id)
    const entry = { cardId: card.id, front: card.front, grade: g, clientReviewId: newClientReviewId() }
    setIndex((i) => i + 1)
    setRevealed(false)
    updateSession((s) => registerGrade(s, g))
    send(entry)
  }

  function retryAll() {
    if (retrying.current) return
    retrying.current = true
    const { state, retries } = beginRetry(sessionRef.current)
    updateSession(() => state)
    for (const entry of retries) send(entry)
  }
  useEffect(() => { retrying.current = false }, [session.failed])

  const celebrated = useRef(false)
  useEffect(() => {
    if (finished && !celebrated.current) { celebrated.current = true; haptic("success") }
  }, [finished])

  // R7: Space/Enter flip; 1-4 rate after the flip.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!current || finished || exitModalOpen || e.ctrlKey || e.metaKey || e.altKey || e.repeat) return
      const target = e.target as Element | null
      if (isEditableTarget(target)) return
      const action = reviewKeyAction(e.key, revealed)
      if (!action) return
      if (action.kind === "reveal" && isForeignControl(target)) return
      e.preventDefault()
      if (action.kind === "reveal") setRevealed(true)
      else grade(action.grade)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, revealed, finished, exitModalOpen])

  // Focus follows the review: the primary action on each new card, then the card itself once flipped.
  // (ReviewCard focuses itself on the flip, so a second Space never lands on a grade button.)
  const actionRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!revealed) actionRef.current?.focus()
  }, [index, revealed, cards])

  const bannerText = syncBannerText(session.failed.length)
  const withStatus = (content: React.ReactNode) => (
    <>
      <div role="status" data-testid="review-sync-status" className="sr-only">{bannerText}</div>
      {content}
      <ConfirmModal
        open={exitModalOpen}
        title="Leave review?"
        consequence="Some ratings may not be saved yet."
        confirmLabel="Leave review"
        cancelLabel="Keep reviewing"
        onConfirm={confirmLeave}
        onCancel={() => setExitModalOpen(false)}
      />
    </>
  )
  const banner = bannerText ? (
    <div className="mx-2 mt-2 flex items-center justify-between lg:mx-[22px] gap-2.5 rounded-xl bg-tertiary-container px-3 text-[13.5px] font-semibold text-on-tertiary-container">
      <span>{bannerText}</span>
      <button type="button" onClick={retryAll} className="min-h-11 min-w-11 px-2 font-bold text-primary">Retry</button>
    </div>
  ) : null

  if (!cards) {
    return withStatus(<QueryState query={due} srHeading="Review flashcards"
      skeleton={<div className="grid gap-4 p-5" aria-busy="true" aria-label="Loading your cards"><SkeletonBlock className={`h-2 rounded ${PAGE_SKELETON}`} /><SkeletonBlock className={`h-[360px] rounded-[28px] ${PAGE_SKELETON}`} /></div>}
      error={{ heading: "Couldn’t load your cards", secondaryAction: { label: "Back to decks", onClick: () => navigate(backTo) } }}>
      {() => null}
    </QueryState>)
  }

  if (cards.length === 0) {
    return withStatus(
      <div className="grid flex-1 content-center justify-items-center gap-3 px-6 text-center">
        <PageHeading repeatsTitle={false} className="font-display text-[28px] font-extrabold text-primary">Nothing due</PageHeading>
        <p className="text-[15px] text-on-surface-variant">{comingBackLine(due.data?.upcoming ?? [], meta.nextDueAt, new Date())}</p>
        <button type="button" onClick={() => navigate(backTo)} className={`${PRIMARY_BTN} max-w-[300px]`}>Back to decks</button>
      </div>
    )
  }

  if (finished) {
    const d = deck.data
    const practice = d && d.origin === "weakness" && d.topic && d.marksLost
      ? { subjectCode: d.subjectCode, topicName: topicName(d.topic), marksLost: d.marksLost }
      : null
    const view = doneView({
      session, totalCards: cards.length, stillDue: Math.max(meta.totalDue - cards.length, 0),
      upcoming: due.data?.upcoming ?? [], now: new Date(), practice,
    })
    return withStatus(<ReviewDone view={view} onBack={leaveReview} today={null} banner={banner} />)
  }

  const progress = progressView(index, cards.length)
  const buttons = current ? gradeButtons(current, meta.againDelay) : []
  const deckLabel = deckId ? deck.data?.title : subjectCode ? subjectName : null
  const labelSubject = deckId ? deck.data?.subjectCode : subjectCode

  return withStatus(
    <div className="fc-review-fill flex flex-col lg:mx-auto lg:w-full lg:max-w-[640px] lg:pt-3">
      <h1 className="sr-only">Review flashcards</h1>
      {/* `.prtop`: end, progress bar, count */}
      <div className="flex items-center gap-3 px-0.5 pb-1.5 pt-4 lg:px-4">
        <button type="button" aria-label="End review" onClick={leaveReview} className="grid size-11 place-items-center rounded-[14px] bg-primary-container text-primary"><X size={20} aria-hidden /></button>
        <div className="h-2 flex-1 overflow-hidden rounded bg-surface-container-high" role="progressbar" aria-valuemin={0} aria-valuemax={cards.length} aria-valuenow={index} aria-label="Cards reviewed">
          <i className="block h-full origin-left rounded bg-primary transition-transform duration-300 ease-out motion-reduce:transition-none" style={{ transform: `scaleX(${progress.fraction})` }} />
        </div>
        <span className="font-mono text-[13px] font-bold leading-tight text-on-surface-variant">{progress.label}</span>
      </div>
      {/* `.prmeta`: combo + deck */}
      <div className="flex items-center gap-2.5 px-1 pb-1 pt-1.5 lg:px-[18px] text-[13px] font-medium leading-tight text-on-surface-variant">
        <ComboChip count={session.combo} />
        {deckLabel ? (
          <span className="ml-auto inline-flex items-center gap-1.5 text-[13px] font-semibold">
            {labelSubject ? <SubjectDot subject={labelSubject} /> : null}
            {deckLabel}
          </span>
        ) : null}
      </div>
      {banner}
      {current ? <ReviewCard key={current.id} card={current} revealed={revealed} onReveal={() => setRevealed(true)} onGrade={grade} /> : null}
      {revealed ? (
        <div className="grid grid-cols-4 gap-2 px-1 pb-[26px] pt-2 lg:px-[18px]" role="group" aria-label="How well did you know it?">
          {buttons.map((b) => (
            <button key={b.grade} type="button" aria-keyshortcuts={b.key} onClick={() => grade(b.grade)}
              className={`grid !min-h-[62px] content-center justify-items-center gap-0.5 rounded-2xl leading-tight transition-transform duration-150 ease-out active:scale-[0.96] motion-reduce:transition-none motion-reduce:active:scale-100 focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary ${GRADE_TONE[b.tone]}`}>
              <b className="text-[15px] font-bold">{b.label} <Kbd size="md" aria-hidden className="ml-1 hidden bg-black/10 text-current lg:inline">{b.key}</Kbd></b>
              <span className="text-[12px] font-medium">{b.interval}</span>
            </button>
          ))}
        </div>
      ) : (
        <>
          <div aria-hidden className="flex justify-between px-4 text-[13px] leading-tight lg:px-[30px] font-semibold text-on-surface-variant"><span className="flex items-center gap-1"><ArrowLeft /> Again</span><span className="flex items-center gap-1">Good <ArrowRight /></span></div>
          <div className="px-1 pb-[26px] pt-2.5 lg:px-[18px]">
            <button ref={actionRef} data-review-primary="" type="button" aria-label={`Show answer: ${current?.front ?? ""}`} onClick={() => setRevealed(true)} className={PRIMARY_BTN}>Show answer</button>
          </div>
        </>
      )}
      <p className="hidden pb-6 text-center text-[13px] font-medium text-on-surface-variant lg:block">
        Press <Kbd size="md">Space</Kbd> to flip · <Kbd size="md">1</Kbd>–<Kbd size="md">4</Kbd> to rate
      </p>
    </div>
  )
}
