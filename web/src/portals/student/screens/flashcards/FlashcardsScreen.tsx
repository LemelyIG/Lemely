/* Hallmark · pre-emit critique: P4 H4 E3 S4 R4 V4 */
import { Plus } from "@phosphor-icons/react"
import { useMemo, useState } from "react"
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { Binny, HairRows, SubjectDot } from "@/components/redesign"
import { QueryState } from "@/components/ui/query-state"
import { useToast } from "@/components/ui/toast"
import { useDueSession, useFlashcardDecks, useRetryGeneration, useRetryingDeckIds, useWeakTopics } from "@/lib/hooks/useFlashcardApi"
import { useReference } from "@/lib/hooks/useReferenceApi"
import { useOverview } from "@/lib/hooks/useStudentApi"
import { isOfflineFailure } from "@/lib/offlineFailure"
import { subjectNameFor } from "@/lib/reference"
import { clearsSelection } from "./deckActions"
import { DecksError, DecksLoading, DecksRefreshNotice, EmptyShelf, SparseExtras } from "./DecksStates"
import { DeckMenu } from "./DeckMenu"
import { DeckPanel } from "./DeckBody"
import { NewDeckSheet, type NewDeckSeed } from "./NewDeckSheet"
import { decksScreenView, resolveSelectedDeck, searchWithoutDeck } from "./flashcardsView"
import { DeckRow } from "./parts/DeckRow"
import { isWide, useIsWide } from "./isWide"
import "./flashcards.css"

const FOCUS = "focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary"
const PRIMARY_BTN = `min-h-[50px] rounded-[18px] bg-primary px-7 text-[15.5px] font-bold text-on-primary shadow-[0_14px_24px_-16px_oklch(0.3_0.07_242/0.7)] ${FOCUS}`

export function FlashcardsScreen() {
  const navigate = useNavigate()
  const location = useLocation()
  const { subjectCode } = useParams<{ subjectCode?: string }>()
  // `?deck=` only seeds the selection (deep links). Later picks live in history state because
  // ScreenOutlet is keyed on pathname + search and would remount the screen on a param change.
  const [params] = useSearchParams()
  const filterSubject = subjectCode ?? null

  const decks = useFlashcardDecks()
  const due = useDueSession({ subjectCode: filterSubject })
  const weak = useWeakTopics()
  const overview = useOverview()
  const reference = useReference()
  const { toast } = useToast()
  // Hook-level onError: every deck's failed retry toasts, not only the latest one's.
  const retry = useRetryGeneration(() =>
    toast({ variant: "error", title: "Couldn’t retry that deck", description: "Try again in a moment." }),
  )
  const retrying = useRetryingDeckIds()
  const wide = useIsWide()

  // A failed refetch keeps the cached shelf (TanStack v5 leaves `data` set under status "error").
  // The full error state is for a first load with nothing to show; over a shelf it is an inline notice.
  const refetchFailed = decks.status === "error" && decks.data !== undefined
  const firstLoadFailed = decks.status === "error" && decks.data === undefined
  const shelfQuery = {
    status: refetchFailed ? ("success" as const) : decks.status,
    data: decks.data,
    error: decks.error,
    refetch: decks.refetch,
    fetchStatus: decks.fetchStatus,
  }

  const [sheet, setSheet] = useState<NewDeckSeed | null>(null)
  const [menuDeckId, setMenuDeckId] = useState<string | null>(null)

  const subjectOrder = useMemo(() => (overview.data?.subjects ?? []).map((s) => s.code), [overview.data])
  const subjectName = (code: string) =>
    overview.data?.subjects.find((s) => s.code === code)?.name ?? subjectNameFor(reference.data, code)

  const view = decksScreenView({
    decks: decks.data,
    decksStatus: decks.status,
    due: due.data,
    dueStatus: due.status,
    weakTopics: weak.data ?? [],
    subjectName,
    subjectOrder,
    filterSubject,
    now: new Date(),
  })

  const picked = (location.state as { deck?: string } | null)?.deck ?? params.get("deck")
  const selectedId = resolveSelectedDeck(view, picked)
  const reviewTo = filterSubject
    ? `/student/flashcards/review?subject=${encodeURIComponent(filterSubject)}`
    : "/student/flashcards/review"
  const defaultSubject = filterSubject ?? weak.data?.[0]?.subjectCode ?? subjectOrder[0] ?? ""

  // Clearing drops `?deck=` too, or the deep link would re-seed a deck that no longer exists.
  function selectInPlace(id: string | null) {
    const search = id ? location.search : searchWithoutDeck(location.search)
    navigate(`${location.pathname}${search}`, { replace: true, state: id ? { deck: id } : null })
  }
  function retryDeck(id: string) {
    if (!retrying.has(id)) retry.mutate(id)
  }
  function openDeck(id: string) {
    if (isWide()) selectInPlace(id)
    else navigate(`/student/flashcards/deck/${id}`)
  }

  const header = view.kind === "ready" ? view.header : { title: "Flashcards", sub: view.kind === "empty" ? "No decks yet" : "" }

  return (
    <div className="mx-auto flex w-full max-w-[640px] flex-col lg:max-w-none">
      <header className="flex items-center gap-2.5 px-4 pb-1.5 pt-3.5 lg:gap-5 lg:px-10 lg:pb-2 lg:pt-6">
        <div className="grid min-w-0 flex-1">
          <h1 tabIndex={-1} data-fc-heading className="font-display text-[28px] font-extrabold leading-[1.1] tracking-[-0.03em] text-primary outline-none lg:text-[32px]">{header.title}</h1>
          {header.sub ? <span className="text-[13px] font-medium text-on-surface-variant">{header.sub}</span> : null}
        </div>
        {view.kind === "ready" && view.hero.reviewLabel ? (
          <button type="button" onClick={() => navigate(reviewTo)} className={`hidden lg:inline-block ${PRIMARY_BTN}`}>
            {view.hero.reviewLabel}
          </button>
        ) : null}
        <button type="button" aria-label="New deck" onClick={() => setSheet({ mode: null, subjectCode: defaultSubject, topic: null })}
          className={`grid size-11 flex-none place-items-center rounded-[14px] bg-primary text-on-primary ${FOCUS}`}>
          <Plus size={18} weight="bold" aria-hidden />
        </button>
      </header>

      <div className="flex flex-col gap-6 px-[18px] pb-24 pt-2 lg:px-10">
        {refetchFailed ? <DecksRefreshNotice onRetry={() => void decks.refetch()} /> : null}
        {firstLoadFailed && !isOfflineFailure(decks.error) ? (
          <DecksError onRetry={() => void decks.refetch()} />
        ) : (
        <QueryState
          query={shelfQuery}
          skeleton={<DecksLoading />}
          error={{
            heading: "We couldn’t load your decks",
            secondaryAction: { label: "Back to Home", onClick: () => navigate("/student") },
          }}
        >
          {() => (
            <>
              {view.kind === "empty" ? (
                <EmptyShelf weakHint={view.weakHint} onPick={(mode) => setSheet({ mode, subjectCode: defaultSubject, topic: null })} />
              ) : null}
              {view.kind === "ready" ? (
                <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_320px] lg:gap-6 xl:grid-cols-[minmax(0,1fr)_340px] xl:gap-10">
                  <div className="flex flex-col gap-6">
                    <section className="flex items-center gap-3">
                      <Binny mood={view.hero.mood} size={64} motion="idle" />
                      <div className="grid gap-0.5">
                        <b className="font-display text-[28px] font-extrabold leading-[1.1] tracking-[-0.02em] text-primary">{view.hero.headline}</b>
                        <span className="text-[14px] font-medium text-on-surface-variant">{view.hero.sub}</span>
                      </div>
                    </section>
                    {view.hero.reviewLabel ? (
                      <button type="button" onClick={() => navigate(reviewTo)} className={`w-full lg:hidden ${PRIMARY_BTN}`}>
                        {view.hero.reviewLabel}
                      </button>
                    ) : null}
                    {view.groups.map((g) => (
                      <section key={g.subjectCode} className="grid">
                        <h2 className="flex items-center font-sans text-[18px] font-extrabold tracking-[-0.01em] text-on-surface">
                          <SubjectDot subject={g.subjectCode} />
                          {g.subjectName}
                        </h2>
                        <HairRows aria-label={`${g.subjectName} decks`}>
                          {g.decks.map((row) => (
                            <DeckRow key={row.id} row={row} selected={wide && row.id === selectedId}
                              onOpen={() => openDeck(row.id)} onLongPress={() => setMenuDeckId(row.id)}
                              onRetry={() => retryDeck(row.id)}
                              retrying={retrying.has(row.id)} />
                          ))}
                        </HairRows>
                      </section>
                    ))}
                    {view.sparse ? (
                      <SparseExtras tip={view.sparse.tip}
                        onMakeTip={() => view.sparse?.tip && setSheet({ mode: "weakness", subjectCode: view.sparse.tip.subjectCode, topic: view.sparse.tip.topic })} />
                    ) : null}
                  </div>
                  {wide && selectedId ? (
                    <aside className="hidden min-h-0 lg:flex" aria-label="Deck">
                      <DeckPanel deckId={selectedId} onDeleted={() => selectInPlace(null)} />
                    </aside>
                  ) : null}
                </div>
              ) : null}
            </>
          )}
        </QueryState>
        )}
      </div>

      <NewDeckSheet seed={sheet} onClose={() => setSheet(null)}
        onStarted={() => setSheet(null)} />
      <DeckMenu deckId={menuDeckId} onClose={() => setMenuDeckId(null)}
        onDeleted={(id) => { if (clearsSelection(id, selectedId)) selectInPlace(null) }} />
    </div>
  )
}
