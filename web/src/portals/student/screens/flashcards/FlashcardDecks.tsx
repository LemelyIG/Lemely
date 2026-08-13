import { useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { CaretDown, CaretUp, PencilSimple, Trash } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { Chip } from "@/components/ui/chip"
import { ErrorState } from "@/components/ui/state-views"
import { ApiError } from "@/lib/api"
import {
  useAddCard,
  useCreateDeck,
  useDeleteCard,
  useDeleteDeck,
  useDueSession,
  useEditCard,
  useFlashcardDeck,
  useFlashcardDecks,
  useGenerateDeck,
} from "@/lib/hooks/useFlashcardApi"
import type { CardDTO, DeckOrigin, GenerateDeckResponseDTO } from "@/lib/flashcardTypes"
import { SUPPORTED_SUBJECTS } from "@/portals/student/screens/onboarding/onboardingData"
import {
  cardSourceLabel,
  dueStateView,
  flashcardUnavailableMessage,
  generateDeckSummary,
  groupDecksByTopic,
  manualDeckRequest,
  nextDueMessage,
} from "./flashcardData"

/*
 * S-22 · Flashcard decks. Decks grouped by topic (`groupDecksByTopic`), each
 * showing its real `cardCount`/`dueCount`. "Review due cards" goes to S-23
 * scoped to this subject. "Edit" expands a deck inline to add, reword and
 * remove cards (S-22 names all of that as one "edit" action, not a separate
 * screen, so no new route is invented for it)
 * — `CardDTO.source` stays visible on every card row for its whole life
 * (P4.9 honesty rule 1); there is no control anywhere that could relabel an
 * AI card as the student's own, matching the API's own missing `source`
 * field on the edit request.
 */

const NEW_DECK_MODES = [
  { value: "manual" as const, label: "Write my own" },
  { value: "topic" as const, label: "Generate for a topic" },
  { value: "weakness" as const, label: "Generate from a weakness" },
]

function DeckOriginChip({ origin }: { origin: DeckOrigin }) {
  if (origin === "weakness") return <Chip tone="warn">From a weakness</Chip>
  if (origin === "topic") return <Chip tone="accent">Topic-generated</Chip>
  return <Chip tone="neutral">Manual</Chip>
}

const CARD_INPUT_CLASS =
  "border border-border bg-surface rounded-lg px-3 py-2 text-sm text-t1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"

/*
 * One card row in the deck editor, with S-22's "edit" action: reword in
 * place. Kept as its own component so each row owns its draft state — a
 * single shared draft on the parent would carry one card's text into the
 * next row the student opened.
 *
 * Rewording never touches provenance. `EditCardRequest` has no `source`
 * field (the API offers no relabel at all), so an AI card the student
 * rewrites stays chipped "AI-written" — the honesty rule is that the label
 * describes who *wrote* the card, and editing text is not authorship. The
 * chip stays rendered while the row is in edit mode for exactly that reason.
 */
function CardRow({
  card,
  editCard,
  deleteCard,
}: {
  card: CardDTO
  editCard: ReturnType<typeof useEditCard>
  deleteCard: ReturnType<typeof useDeleteCard>
}) {
  const [editing, setEditing] = useState(false)
  const [draftFront, setDraftFront] = useState(card.front)
  const [draftBack, setDraftBack] = useState(card.back)

  function startEditing() {
    setDraftFront(card.front)
    setDraftBack(card.back)
    setEditing(true)
  }

  return (
    <li className="flex items-start justify-between gap-3 rounded-lg border border-border bg-bg p-3">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-center gap-2">
          <Chip tone={card.source === "ai" ? "accent" : "neutral"}>
            {cardSourceLabel(card.source)}
          </Chip>
          <span className="text-dense-sm text-t3">
            due {new Date(card.dueAt).toLocaleDateString()}
          </span>
        </div>
        {editing ? (
          <form
            className="flex flex-col gap-2 pt-1"
            onSubmit={(e) => {
              e.preventDefault()
              if (!draftFront.trim() || !draftBack.trim()) return
              editCard.mutate(
                {
                  cardId: card.id,
                  body: { front: draftFront.trim(), back: draftBack.trim() },
                },
                { onSuccess: () => setEditing(false) },
              )
            }}
          >
            <label className="flex flex-col gap-1 text-dense-sm text-t2">
              Front
              <input
                required
                autoFocus
                value={draftFront}
                onChange={(e) => setDraftFront(e.target.value)}
                className={CARD_INPUT_CLASS}
              />
            </label>
            <label className="flex flex-col gap-1 text-dense-sm text-t2">
              Back
              <input
                required
                value={draftBack}
                onChange={(e) => setDraftBack(e.target.value)}
                className={CARD_INPUT_CLASS}
              />
            </label>
            {editCard.isError ? (
              <p className="text-dense-sm text-err">We couldn't save that change. Try again.</p>
            ) : null}
            <div className="flex gap-2">
              <Button type="submit" variant="secondary" size="sm" disabled={editCard.isPending}>
                {editCard.isPending ? "Saving…" : "Save"}
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={() => setEditing(false)}>
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <>
            <div className="text-dense-sm font-medium text-t1 truncate">{card.front}</div>
            <div className="text-dense-sm text-t2 truncate">{card.back}</div>
          </>
        )}
      </div>
      {editing ? null : (
        <div className="flex shrink-0 gap-1">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label={`Edit card: ${card.front}`}
            onClick={startEditing}
          >
            <PencilSimple size={16} aria-hidden />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label={`Delete card: ${card.front}`}
            onClick={() => deleteCard.mutate(card.id)}
          >
            <Trash size={16} aria-hidden />
          </Button>
        </div>
      )}
    </li>
  )
}

function DeckCardEditor({ deckId }: { deckId: string }) {
  const deckQuery = useFlashcardDeck(deckId)
  const addCard = useAddCard(deckId)
  const editCard = useEditCard(deckId)
  const deleteCard = useDeleteCard(deckId)
  const [front, setFront] = useState("")
  const [back, setBack] = useState("")

  if (deckQuery.isPending) {
    return <p className="text-dense-sm text-t3 px-5 pb-4">Loading cards…</p>
  }
  if (deckQuery.isError || !deckQuery.data) {
    return (
      <div className="px-5 pb-4">
        <ErrorState
          heading="Couldn't load this deck's cards"
          body={deckQuery.error?.message}
          action={{ label: "Try again", onClick: () => void deckQuery.refetch() }}
        />
      </div>
    )
  }

  const { cards } = deckQuery.data

  return (
    <div className="flex flex-col gap-3 px-5 pb-5">
      {cards.length === 0 ? (
        <p className="text-dense-sm text-t3">No cards in this deck yet.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {cards.map((card) => (
            <CardRow key={card.id} card={card} editCard={editCard} deleteCard={deleteCard} />
          ))}
        </ul>
      )}

      <form
        className="flex flex-col gap-2 border-t border-border pt-3"
        onSubmit={(e) => {
          e.preventDefault()
          if (!front.trim() || !back.trim()) return
          addCard.mutate(
            { front: front.trim(), back: back.trim() },
            { onSuccess: () => { setFront(""); setBack("") } },
          )
        }}
      >
        <label className="flex flex-col gap-1 text-dense-sm text-t2">
          Front
          <input
            required
            value={front}
            onChange={(e) => setFront(e.target.value)}
            placeholder="Question or prompt"
            className={CARD_INPUT_CLASS}
          />
        </label>
        <label className="flex flex-col gap-1 text-dense-sm text-t2">
          Back
          <input
            required
            value={back}
            onChange={(e) => setBack(e.target.value)}
            placeholder="Answer"
            className={CARD_INPUT_CLASS}
          />
        </label>
        {addCard.isError ? (
          <p className="text-dense-sm text-err">We couldn't add that card. Try again.</p>
        ) : null}
        <div>
          <Button type="submit" variant="secondary" size="sm" disabled={addCard.isPending}>
            {addCard.isPending ? "Adding…" : "Add card"}
          </Button>
        </div>
      </form>
    </div>
  )
}

export function FlashcardDecks() {
  const navigate = useNavigate()
  const { subjectCode = "" } = useParams<{ subjectCode: string }>()
  const subjectName = SUPPORTED_SUBJECTS.find((s) => s.code === subjectCode)?.name ?? subjectCode

  const decksQuery = useFlashcardDecks(subjectCode)
  const dueQuery = useDueSession(subjectCode)
  const createDeck = useCreateDeck()
  const generateDeck = useGenerateDeck()
  const deleteDeck = useDeleteDeck()

  const [expandedDeckId, setExpandedDeckId] = useState<string | null>(null)
  const [mode, setMode] = useState<(typeof NEW_DECK_MODES)[number]["value"]>("manual")
  const [title, setTitle] = useState("")
  const [topic, setTopic] = useState("")
  const [count, setCount] = useState(10)
  const [refusal, setRefusal] = useState<string | null | undefined>(undefined)
  const [generated, setGenerated] = useState<GenerateDeckResponseDTO | null>(null)

  if (decksQuery.isPending) {
    return (
      <div className="lm-screen text-body-md text-t2">
        <h1 className="sr-only">Flashcards — {subjectName}</h1>
        Loading your decks…
      </div>
    )
  }

  if (decksQuery.isError || !decksQuery.data) {
    return (
      <>
        <h1 className="sr-only">Flashcards — {subjectName}</h1>
        <ErrorState
          heading="Couldn't load your flashcard decks"
          body={decksQuery.error?.message}
          action={{ label: "Try again", onClick: () => void decksQuery.refetch() }}
          className="lm-screen"
        />
      </>
    )
  }

  const groups = groupDecksByTopic(decksQuery.data)
  const due = dueQuery.data ? dueStateView(dueQuery.data) : null

  async function handleNewDeck() {
    setRefusal(undefined)
    setGenerated(null)
    try {
      if (mode === "manual") {
        // The provenance decision lives in `manualDeckRequest`, not here, so
        // it is pinned by a unit test rather than by reading JSX.
        await createDeck.mutateAsync(manualDeckRequest(subjectCode, subjectName, title, topic))
        setTitle("")
        setTopic("")
      } else {
        const result = await generateDeck.mutateAsync({
          subjectCode,
          origin: mode,
          count,
          topic: mode === "topic" ? topic.trim() || null : null,
          title: title.trim() || null,
        })
        setGenerated(result)
        setTitle("")
        setTopic("")
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.detail) {
        const detail = err.detail as { reason?: string }
        setRefusal(detail.reason ?? null)
      }
    }
  }

  return (
    <div className="lm-screen mx-auto flex max-w-[840px] flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="font-serif text-display-md leading-display text-t1 m-0">
          Flashcards — {subjectName}
        </h1>
        <p className="text-body-md text-t2">
          Decks grouped by topic. Cards you write yourself and cards Lemely generates both live
          here — every card always shows which one it is.
        </p>
      </div>

      <Card className={due?.kind === "none" ? "border-warn" : undefined}>
        <CardBody className="flex flex-col gap-3">
          {dueQuery.isPending ? (
            <p className="text-dense-sm text-t3">Checking what's due…</p>
          ) : dueQuery.isError ? (
            <p className="text-dense-sm text-err">We couldn't check what's due. Try again.</p>
          ) : due?.kind === "due" ? (
            <>
              <div className="text-body-lg font-medium text-t1">
                {due.totalDue} card{due.totalDue === 1 ? "" : "s"} due today
              </div>
              <div>
                <Button
                  variant="accent"
                  size="lg"
                  onClick={() => navigate(`/student/flashcards/review/${subjectCode}`)}
                >
                  Review due cards
                </Button>
              </div>
            </>
          ) : due?.kind === "none" ? (
            <>
              <div className="text-body-lg font-medium text-t1">Nothing due today</div>
              <p className="text-body-md text-t2">{nextDueMessage(due.nextDueAt)}</p>
            </>
          ) : null}
        </CardBody>
      </Card>

      <Card>
        <CardBody className="flex flex-col gap-4">
          <div className="text-dense-sm uppercase tracking-widest text-t3">New deck</div>
          <div className="flex flex-wrap gap-2">
            {NEW_DECK_MODES.map((m) => (
              <Button
                key={m.value}
                type="button"
                variant={mode === m.value ? "accent" : "secondary"}
                size="sm"
                aria-pressed={mode === m.value}
                onClick={() => {
                  setMode(m.value)
                  setRefusal(undefined)
                  setGenerated(null)
                }}
              >
                {m.label}
              </Button>
            ))}
          </div>

          <div className="flex flex-col gap-3">
            <label className="flex flex-col gap-1.5 text-dense-sm text-t2">
              Title {mode !== "manual" ? "(optional)" : ""}
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={`e.g. ${subjectName} revision`}
                className={CARD_INPUT_CLASS}
              />
            </label>

            {mode !== "weakness" ? (
              <label className="flex flex-col gap-1.5 text-dense-sm text-t2">
                Topic {mode === "manual" ? "(optional)" : ""}
                <input
                  required={mode === "topic"}
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  placeholder="e.g. 1.2 Motion"
                  className={CARD_INPUT_CLASS}
                />
              </label>
            ) : (
              <p className="text-dense-sm text-t3">
                The topic is chosen automatically from your own weakest recorded topic for this
                subject — there's no topic field to fill in.
              </p>
            )}

            {mode !== "manual" ? (
              <label className="flex flex-col gap-1.5 text-dense-sm text-t2">
                Number of cards: {count}
                <input
                  type="range"
                  min={1}
                  max={50}
                  step={1}
                  value={count}
                  onChange={(e) => setCount(Number(e.target.value))}
                  aria-label="Number of cards to generate"
                  className="accent-accent"
                />
              </label>
            ) : null}
          </div>

          {refusal !== undefined ? (
            (() => {
              const msg = flashcardUnavailableMessage(refusal)
              return (
                <div className="rounded-lg border border-warn bg-warn-bg p-3">
                  <div className="text-body-lg font-medium text-t1">{msg.heading}</div>
                  <p className="text-body-md text-t2">{msg.body}</p>
                </div>
              )
            })()
          ) : null}

          {generated ? (
            (() => {
              const summary = generateDeckSummary(generated)
              return (
                <div className="rounded-lg border border-border bg-bg p-3">
                  <div className="text-body-lg font-medium text-t1">{summary.headline}</div>
                  {summary.shortfall ? (
                    <p className="text-body-md text-t2">
                      The model returned fewer cards than requested — nothing was padded to make
                      up the difference.
                    </p>
                  ) : null}
                </div>
              )
            })()
          ) : null}

          {(createDeck.isError && refusal === undefined) ||
          (generateDeck.isError && refusal === undefined) ? (
            <p className="text-dense-sm text-err">We couldn't create that deck. Try again.</p>
          ) : null}

          <div>
            <Button
              type="button"
              variant="accent"
              size="lg"
              disabled={
                createDeck.isPending ||
                generateDeck.isPending ||
                (mode === "topic" && !topic.trim())
              }
              onClick={() => void handleNewDeck()}
            >
              {createDeck.isPending || generateDeck.isPending
                ? "Creating…"
                : mode === "manual"
                  ? "Create deck"
                  : "Generate deck"}
            </Button>
          </div>
        </CardBody>
      </Card>

      {groups.length === 0 ? (
        <Card>
          <CardBody>
            <p className="text-body-md text-t2">
              No decks yet for {subjectName}. Create one above to get started.
            </p>
          </CardBody>
        </Card>
      ) : (
        groups.map((group) => (
          <div key={group.topic ?? "untopiced"} className="flex flex-col gap-2">
            <div className="text-dense-sm font-medium text-t1">{group.topic ?? "Untopiced"}</div>
            <div className="flex flex-col gap-2">
              {group.decks.map((deck) => {
                const expanded = expandedDeckId === deck.id
                return (
                  <Card key={deck.id}>
                    <CardBody className="flex flex-col gap-2">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="flex flex-col gap-1">
                          <div className="text-body-lg font-medium text-t1">{deck.title}</div>
                          <div className="flex flex-wrap items-center gap-2">
                            <DeckOriginChip origin={deck.origin} />
                            <span className="text-dense-sm text-t3">
                              {deck.cardCount} card{deck.cardCount === 1 ? "" : "s"}
                            </span>
                            <span className="text-dense-sm text-t3">
                              {deck.dueCount} due
                            </span>
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <Button
                            type="button"
                            variant="secondary"
                            size="sm"
                            aria-expanded={expanded}
                            onClick={() => setExpandedDeckId(expanded ? null : deck.id)}
                          >
                            {expanded ? (
                              <>
                                Edit <CaretUp size={14} aria-hidden />
                              </>
                            ) : (
                              <>
                                Edit <CaretDown size={14} aria-hidden />
                              </>
                            )}
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            aria-label={`Delete deck: ${deck.title}`}
                            onClick={() => {
                              if (expandedDeckId === deck.id) setExpandedDeckId(null)
                              deleteDeck.mutate(deck.id)
                            }}
                          >
                            <Trash size={16} aria-hidden />
                          </Button>
                        </div>
                      </div>
                    </CardBody>
                    {expanded ? <DeckCardEditor deckId={deck.id} /> : null}
                  </Card>
                )
              })}
            </div>
          </div>
        ))
      )}
    </div>
  )
}
