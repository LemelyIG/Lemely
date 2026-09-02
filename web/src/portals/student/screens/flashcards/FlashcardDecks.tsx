import { useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { CaretDown, CaretUp, PencilSimple, Trash } from "@phosphor-icons/react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { ListSkeleton, PageHeaderSkeleton, PanelSkeleton } from "@/components/ui/loading-shapes"
import { ConfirmModal } from "@/components/ui/confirm-modal"
import { Slider } from "@/components/ui/slider"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
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
import { useSubjectName } from "@/lib/hooks/useReferenceApi"
import { studentLoadFailureMessage } from "@/lib/studentOutcome"
import {
  cardSourceLabel,
  dueStateView,
  flashcardUnavailableMessage,
  generateDeckSummary,
  groupDecksByTopic,
  manualDeckRequest,
  nextDueMessage,
} from "./flashcardData"

/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */

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
 *
 * P4.3 (Study Notebook, Read lane). Two things here were not styling:
 *
 *   1. **Deleting a deck was unconfirmed AND silent on failure.** One tap on a
 *      Trash glyph destroyed a deck and every card in it with no confirmation
 *      step, and `useDeleteDeck`/`useDeleteCard` both expose `isError` that
 *      nothing rendered — so a failed delete left the deck on screen with no
 *      way to tell whether it had gone. `addCard.isError` and
 *      `editCard.isError` were both rendered; the two *destructive* mutations
 *      were the two that were not. Both now confirm through `ConfirmModal`
 *      and both report their own failure.
 *   2. **The card editor hand-rolled its inputs.** `CARD_INPUT_CLASS` was a
 *      local border/padding/focus string on six raw `<input>`s, which also
 *      pinned focus to the accent where DESIGN.md §3.9 makes it deliberately
 *      blue. They are C-6 `Input`s now, so the eight states, the label rule
 *      and the focus ring come from the kit.
 */

const NEW_DECK_MODES = [
  { value: "manual" as const, label: "Write my own" },
  { value: "topic" as const, label: "Generate for a topic" },
  { value: "weakness" as const, label: "Generate from a weakness" },
]

function DeckOriginBadge({ origin }: { origin: DeckOrigin }) {
  if (origin === "weakness") return <Badge tone="amber">From a weakness</Badge>
  if (origin === "topic") return <Badge tone="lilac">Topic-generated</Badge>
  return <Badge tone="sage">Manual</Badge>
}

/*
 * One card row in the deck editor, with S-22's "edit" action: reword in
 * place. Kept as its own component so each row owns its draft state — a
 * single shared draft on the parent would carry one card's text into the
 * next row the student opened.
 *
 * Rewording never touches provenance. `EditCardRequest` has no `source`
 * field (the API offers no relabel at all), so an AI card the student
 * rewrites stays badged "AI-written" — the honesty rule is that the label
 * describes who *wrote* the card, and editing text is not authorship. The
 * badge stays rendered while the row is in edit mode for exactly that reason.
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
  const [confirming, setConfirming] = useState(false)
  const [draftFront, setDraftFront] = useState(card.front)
  const [draftBack, setDraftBack] = useState(card.back)

  const deletingThis = deleteCard.isPending && deleteCard.variables === card.id
  const deleteFailedHere = deleteCard.isError && deleteCard.variables === card.id

  function startEditing() {
    setDraftFront(card.front)
    setDraftBack(card.back)
    setEditing(true)
  }

  return (
    <li className="flex items-start justify-between gap-3 rounded-lg border border-rule bg-paper p-3">
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex items-center gap-2">
          <Badge tone={card.source === "ai" ? "lilac" : "sage"}>
            {cardSourceLabel(card.source)}
          </Badge>
          <span className="text-data-sm text-ink-faint">
            due {new Date(card.dueAt).toLocaleDateString()}
          </span>
        </div>
        {editing ? (
          <form
            className="flex flex-col gap-3 pt-1"
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
            <Input
              required
              autoFocus
              label="Front"
              value={draftFront}
              onChange={(e) => setDraftFront(e.target.value)}
            />
            <Input
              required
              label="Back"
              value={draftBack}
              onChange={(e) => setDraftBack(e.target.value)}
              error={editCard.isError ? "We couldn't save that change. Try again." : undefined}
            />
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
            <div className="truncate text-body-md font-medium text-ink">{card.front}</div>
            <div className="truncate text-body-sm text-ink-muted">{card.back}</div>
            {deleteFailedHere ? (
              <p className="text-body-sm text-err">
                We couldn't delete that card. It's still here, so you can try again.
              </p>
            ) : null}
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
            onClick={() => setConfirming(true)}
          >
            <Trash size={16} aria-hidden />
          </Button>
        </div>
      )}
      <ConfirmModal
        open={confirming}
        title="Delete this card?"
        description={card.front}
        confirmLabel="Delete card"
        pendingLabel="Deleting…"
        pending={deletingThis}
        error={
          deleteFailedHere ? "We couldn't delete that card. Try again." : null
        }
        onCancel={() => setConfirming(false)}
        onConfirm={() =>
          deleteCard.mutate(card.id, { onSuccess: () => setConfirming(false) })
        }
      />
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
    return (
      <div className="px-5 pb-5">
        <ListSkeleton rows={3} />
      </div>
    )
  }
  if (deckQuery.isError || !deckQuery.data) {
    return (
      <div className="px-5 pb-4">
        <ErrorState
          heading="Couldn't load this deck's cards"
          body={studentLoadFailureMessage(deckQuery.error)}
          action={{ label: "Try again", onClick: () => void deckQuery.refetch() }}
        />
      </div>
    )
  }

  const { cards } = deckQuery.data

  return (
    <div className="flex flex-col gap-4 px-5 pb-5">
      {cards.length === 0 ? (
        <p className="text-body-sm text-ink-faint">No cards in this deck yet.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {cards.map((card) => (
            <CardRow key={card.id} card={card} editCard={editCard} deleteCard={deleteCard} />
          ))}
        </ul>
      )}

      <form
        className="flex flex-col gap-3 border-t border-rule pt-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (!front.trim() || !back.trim()) return
          addCard.mutate(
            { front: front.trim(), back: back.trim() },
            { onSuccess: () => { setFront(""); setBack("") } },
          )
        }}
      >
        <Input
          required
          label="Front"
          placeholder="Question or prompt"
          value={front}
          onChange={(e) => setFront(e.target.value)}
        />
        <Input
          required
          label="Back"
          placeholder="Answer"
          value={back}
          onChange={(e) => setBack(e.target.value)}
          error={addCard.isError ? "We couldn't add that card. Try again." : undefined}
        />
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
  const subjectName = useSubjectName(subjectCode)

  const decksQuery = useFlashcardDecks(subjectCode)
  const dueQuery = useDueSession(subjectCode)
  const createDeck = useCreateDeck()
  const generateDeck = useGenerateDeck()
  const deleteDeck = useDeleteDeck()

  const [expandedDeckId, setExpandedDeckId] = useState<string | null>(null)
  const [deckPendingDelete, setDeckPendingDelete] = useState<{ id: string; title: string } | null>(
    null,
  )
  const [mode, setMode] = useState<(typeof NEW_DECK_MODES)[number]["value"]>("manual")
  const [title, setTitle] = useState("")
  const [topic, setTopic] = useState("")
  const [count, setCount] = useState(10)
  const [refusal, setRefusal] = useState<string | null | undefined>(undefined)
  const [generated, setGenerated] = useState<GenerateDeckResponseDTO | null>(null)

  if (decksQuery.isPending) {
    return (
      <div className="lm-screen lm-read flex flex-col gap-6">
        <h1 className="sr-only">Flashcards for {subjectName}</h1>
        {/* Shaped like what replaces it (§12): the header, the "what's due"
            panel, then the deck list. A single "Loading your decks…" line was
            what stood here, which reserves none of that height and shifts the
            whole column when the real content lands. */}
        <PageHeaderSkeleton />
        <PanelSkeleton />
        <ListSkeleton rows={3} />
      </div>
    )
  }

  if (decksQuery.isError || !decksQuery.data) {
    return (
      <>
        <h1 className="sr-only">Flashcards for {subjectName}</h1>
        <ErrorState
          heading="Couldn't load your flashcard decks"
          body={studentLoadFailureMessage(decksQuery.error)}
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
    <div className="lm-screen lm-read flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-display-lg text-ink">Flashcards for {subjectName}</h1>
        <p className="lm-prose text-body-lg text-ink-muted">
          Decks grouped by topic. Cards you write yourself and cards Lemely generates both live
          here, and every card always shows which one it is.
        </p>
      </div>

      {/* No `border-warn` on the "nothing due" case any more. A warn border said
          "something needs your attention" about a student who is completely up
          to date, which is the one state on this screen that needs nothing from
          them (§3.6: a semantic colour states a fact, it does not decorate). */}
      <Card>
        <CardBody className="flex flex-col gap-3">
          {dueQuery.isPending ? (
            <p className="text-body-sm text-ink-faint">Checking what's due…</p>
          ) : dueQuery.isError ? (
            <p className="text-body-sm text-err">We couldn't check what's due. Try again.</p>
          ) : due?.kind === "due" ? (
            <>
              <div className="flex items-baseline gap-2">
                <span className="text-data-lg text-ink">{due.totalDue}</span>
                <span className="text-body-lg text-ink-muted">
                  card{due.totalDue === 1 ? "" : "s"} due today
                </span>
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
              <div className="text-display-sm text-ink">Nothing due today</div>
              <p className="text-body-md text-ink-muted">{nextDueMessage(due.nextDueAt)}</p>
            </>
          ) : null}
        </CardBody>
      </Card>

      <Card>
        <CardBody className="flex flex-col gap-4">
          <h2 className="text-eyebrow text-ink-faint">New deck</h2>
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

          <div className="flex flex-col gap-4">
            <Input
              label={mode === "manual" ? "Title" : "Title (optional)"}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={`e.g. ${subjectName} revision`}
            />

            {mode !== "weakness" ? (
              <Input
                required={mode === "topic"}
                label={mode === "manual" ? "Topic (optional)" : "Topic"}
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="e.g. 1.2 Motion"
              />
            ) : (
              <p className="text-body-sm text-ink-faint">
                The topic is chosen automatically from your own weakest recorded topic for this
                subject, so there's no topic field to fill in.
              </p>
            )}

            {mode !== "manual" ? (
              <div className="flex flex-col gap-2">
                <label className="text-label text-ink" htmlFor="new-deck-count">
                  Number of cards: <span className="text-data-md text-ink">{count}</span>
                </label>
                {/* C-15 Slider, not a raw `<input type="range">`. The practice
                    generator on this same surface already used the kit control;
                    this screen had its own, so one surface shipped two different
                    sliders with two different focus and track treatments. */}
                <Slider
                  id="new-deck-count"
                  value={count}
                  onValueChange={setCount}
                  min={1}
                  max={50}
                  step={1}
                  aria-label="Number of cards to generate"
                />
              </div>
            ) : null}
          </div>

          {refusal !== undefined ? (
            (() => {
              const msg = flashcardUnavailableMessage(refusal)
              return (
                <div className="rounded-lg border border-warn bg-warn-wash p-4">
                  <div className="text-display-sm text-ink">{msg.heading}</div>
                  <p className="mt-1 text-body-md text-ink-muted">{msg.body}</p>
                </div>
              )
            })()
          ) : null}

          {generated ? (
            (() => {
              const summary = generateDeckSummary(generated)
              return (
                <div className="rounded-lg border border-rule bg-paper p-4">
                  <div className="text-display-sm text-ink">{summary.headline}</div>
                  {summary.shortfall ? (
                    <p className="mt-1 text-body-md text-ink-muted">
                      The model returned fewer cards than requested, and nothing was padded to make
                      up the difference.
                    </p>
                  ) : null}
                </div>
              )
            })()
          ) : null}

          {(createDeck.isError && refusal === undefined) ||
          (generateDeck.isError && refusal === undefined) ? (
            <p className="text-body-sm text-err">We couldn't create that deck. Try again.</p>
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

      {deleteDeck.isError ? (
        <p className="text-body-sm text-err">
          We couldn't delete that deck. It's still in your list, so you can try again.
        </p>
      ) : null}

      {groups.length === 0 ? (
        <EmptyState
          marginalia="Nothing on the shelf yet"
          heading={`No decks yet for ${subjectName}`}
          body="Write your own cards, or let Lemely build a deck from a topic or from a weakness it has already recorded for you. Either way, every card says where it came from."
        />
      ) : (
        groups.map((group) => (
          <section key={group.topic ?? "untopiced"} className="flex flex-col gap-2">
            {/* The margin rule (§8 item 5): one hairline at the content's inline
                start, the cheapest and most on-brand texture in the system, and
                here it also does real work — it is what visually binds a topic's
                decks to the topic heading above them. */}
            <h2 className="text-display-sm text-ink">{group.topic ?? "Untopiced"}</h2>
            <div className="margin-rule flex flex-col gap-2">
              {group.decks.map((deck) => {
                const expanded = expandedDeckId === deck.id
                return (
                  <Card key={deck.id}>
                    <CardBody className="flex flex-col gap-2">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="flex flex-col gap-1.5">
                          <div className="text-body-lg font-medium text-ink">{deck.title}</div>
                          <div className="flex flex-wrap items-center gap-2">
                            <DeckOriginBadge origin={deck.origin} />
                            {/* One span with an explicit separator, not two
                                adjacent ones. As two siblings a gap apart, the
                                counts rendered as "18 cards 6 due" and scanned
                                as a single run-on string rather than two
                                separate facts about the deck. */}
                            <span className="text-data-sm text-ink-faint">
                              {deck.cardCount} card{deck.cardCount === 1 ? "" : "s"} ·{" "}
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
                            onClick={() =>
                              setDeckPendingDelete({ id: deck.id, title: deck.title })
                            }
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
          </section>
        ))
      )}

      <ConfirmModal
        open={deckPendingDelete !== null}
        title="Delete this deck?"
        description={
          deckPendingDelete
            ? `"${deckPendingDelete.title}" and every card in it.`
            : ""
        }
        confirmLabel="Delete deck"
        pendingLabel="Deleting…"
        pending={deleteDeck.isPending}
        error={deleteDeck.isError ? "We couldn't delete that deck. Try again." : null}
        onCancel={() => setDeckPendingDelete(null)}
        onConfirm={() => {
          if (!deckPendingDelete) return
          if (expandedDeckId === deckPendingDelete.id) setExpandedDeckId(null)
          deleteDeck.mutate(deckPendingDelete.id, {
            onSuccess: () => setDeckPendingDelete(null),
          })
        }}
      />
    </div>
  )
}
