/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { SubjectDot, subjectDotColor } from "@/components/redesign"
import { QueryState } from "@/components/ui/query-state"
import { PageHeading } from "@/components/ui/page-heading"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { useToast } from "@/components/ui/toast"
import { useFlashcardDeck, useGenerationStatus, useRetryingDeckIds } from "@/lib/hooks/useFlashcardApi"
import { useSubjectName } from "@/lib/hooks/useReferenceApi"
import { useOverview } from "@/lib/hooks/useStudentApi"
import { CardSheet } from "./CardSheet"
import { DeckOptionsButton } from "./DeckMenu"
import { DeleteDeckSheet } from "./DeleteDeckSheet"
import { DecksRefreshNotice } from "./DecksStates"
import { cardFocusTarget, generationToast, keepCachedOnError, type CardCloseOutcome, type CardMode } from "./deckActions"
import { deckDetailView, type CardRowView } from "./deckView"
import { NewDeckSheet, type NewDeckSeed } from "./NewDeckSheet"
import { failedDeckSeed } from "./newDeckView"
import { DeckContent } from "./parts/DeckContent"
import { SKELETON_FILL } from "./parts/skeletonStyles"

/** FL-style loading: the header, the bar, three rows. One status line for the whole region. */
function DeckLoading() {
  return (
    <div className="grid w-full gap-3" role="status" aria-busy="true" aria-label="Loading this deck">
      <SkeletonBlock announce={false} className={`h-8 w-40 rounded-[10px] ${SKELETON_FILL}`} />
      <SkeletonBlock announce={false} className={`h-14 rounded-2xl ${SKELETON_FILL}`} />
      {[0, 1, 2].map((i) => <SkeletonBlock key={i} announce={false} className={`h-12 rounded-[14px] ${SKELETON_FILL}`} />)}
    </div>
  )
}

/**
 * The deck: header (h1 on the page, h2 in the side panel), then writing, failed, or ready. A failed
 * refetch keeps the deck on screen with a notice; only a first load with nothing cached is an error.
 */
export function DeckBody({
  deckId, variant, onDeleted,
}: { deckId: string; variant: "page" | "panel"; onDeleted: () => void }) {
  const navigate = useNavigate()
  const { toast } = useToast()
  const deck = useFlashcardDeck(deckId)
  const overview = useOverview()
  const subjectName = useSubjectName(deck.data?.subjectCode ?? "")
  const status = deck.data?.generationStatus
  const gen = useGenerationStatus(deckId, status === "writing" || status === "failed")
  const retrying = useRetryingDeckIds().has(deckId)
  // FGX: Try again on a failed deck reopens the new-deck sheet for it; the sheet owns the retry.
  const [retrySeed, setRetrySeed] = useState<NewDeckSeed | null>(null)
  const [cardSheet, setCardSheet] = useState<{ mode: CardMode; card: CardRowView | null } | null>(null)
  const [deleteFailed, setDeleteFailed] = useState(false)
  const [shortfall, setShortfall] = useState<string | null>(null)
  const opener = useRef<HTMLElement | null>(null)
  const addRef = useRef<HTMLButtonElement>(null)

  // The deck was writing, or had failed, and came back: say how many cards really arrived.
  const previous = useRef(gen.data?.status)
  useEffect(() => {
    const outcome = generationToast(previous.current, gen.data)
    if (outcome) {
      toast({ title: outcome.title, variant: outcome.variant })
      setShortfall(outcome.shortfall)
    }
    previous.current = gen.data?.status
  }, [gen.data, toast])

  const gate = keepCachedOnError({ status: deck.status, data: deck.data })
  const query = { status: gate.status, data: deck.data, error: deck.error, refetch: deck.refetch, fetchStatus: deck.fetchStatus }

  function openCard(mode: CardMode, card: CardRowView | null, from: HTMLElement) {
    opener.current = from
    setCardSheet({ mode, card })
  }
  const focusAfterCard = (outcome: CardCloseOutcome): HTMLElement | null =>
    cardFocusTarget(outcome, opener.current?.isConnected ?? false) === "opener" ? opener.current : addRef.current

  return (
    <div className={`flex w-full min-w-0 flex-col ${variant === "page" ? "gap-6" : "min-h-0 gap-3.5"}`}>
      {gate.refreshFailed ? <DecksRefreshNotice label="Couldn’t refresh this deck" onRetry={() => void deck.refetch()} /> : null}
      <QueryState
        query={query}
        skeleton={<DeckLoading />}
        error={{
          heading: "Couldn’t load this deck",
          retryLabel: "Try again",
          compact: variant === "panel",
          secondaryAction: variant === "page" ? { label: "Back to decks", onClick: () => navigate("/student/flashcards", { replace: true }) } : undefined,
        }}
      >
        {(data) => {
          const name = overview.data?.subjects.find((s) => s.code === data.subjectCode)?.name ?? subjectName
          const v = deckDetailView(data, name, subjectDotColor(data.subjectCode))
          const sub = (
            <span className="inline-flex items-center gap-1.5">
              <SubjectDot subject={data.subjectCode} />
              {v.sub}
            </span>
          )
          const options = (
            <DeckOptionsButton deckId={deckId} title={v.title} cardCount={data.cards.length} variant={variant} onDeleted={onDeleted} />
          )
          return (
            <>
              {variant === "page" ? (
                <header className="flex items-center gap-2.5">
                  <div className="min-w-0 flex-1 leading-tight">
                    <PageHeading repeatsTitle={false} className="font-display text-[28px] font-extrabold leading-[1.1] tracking-[-0.03em] text-primary [overflow-wrap:anywhere]">{v.title}</PageHeading>
                    <span className="text-[13px] font-medium text-on-surface-variant">{sub}</span>
                  </div>
                  {options}
                </header>
              ) : (
                <header className="flex items-center justify-between gap-2.5">
                  <div className="min-w-0 leading-tight">
                    <h2 className="font-sans text-[22px] font-extrabold text-on-surface [overflow-wrap:anywhere]">{v.title}</h2>
                    <span className="text-[13px] font-medium text-on-surface-variant">{sub}</span>
                  </div>
                  {options}
                </header>
              )}
              <DeckContent
                view={v} deck={data} variant={variant} shortfall={shortfall} retrying={retrying} addRef={addRef}
                onReview={() => navigate(`/student/flashcards/review?deck=${deckId}`)}
                onAdd={(from) => openCard("add", null, from)}
                onEdit={(card, from) => openCard("edit", card, from)}
                onRetry={() => setRetrySeed(failedDeckSeed(data, deckId))}
                onDeleteFailed={() => setDeleteFailed(true)}
              />
              <DeleteDeckSheet deckId={deckId} title={v.title} cardCount={data.cards.length} open={deleteFailed}
                onClose={() => setDeleteFailed(false)} onDeleted={onDeleted} />
            </>
          )
        }}
      </QueryState>
      <CardSheet deckId={deckId} mode={cardSheet?.mode ?? null} card={cardSheet?.card ?? null}
        onClose={() => setCardSheet(null)} restoreFocusTo={focusAfterCard} />
      <NewDeckSheet seed={retrySeed} onClose={() => setRetrySeed(null)} onStarted={() => setRetrySeed(null)} onDiscarded={onDeleted} />
    </div>
  )
}

/** FDD `.sside`: white r22, 20px padding, gap 14, soft shadow. It sticks while the cards scroll inside it. */
export function DeckPanel({ deckId, onDeleted }: { deckId: string; onDeleted: () => void }) {
  return (
    <div className="flex min-h-0 w-full flex-col self-start rounded-[22px] bg-surface-container-lowest p-5 shadow-[0_1px_3px_oklch(0.3_0.05_240/0.1)] lg:sticky lg:top-6 lg:max-h-[calc(100dvh-3rem)]">
      <DeckBody key={deckId} deckId={deckId} variant="panel" onDeleted={onDeleted} />
    </div>
  )
}
