/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { PencilSimple, Plus } from "@phosphor-icons/react"
import type { Ref } from "react"
import type { DeckDetailDTO } from "@/lib/flashcardTypes"
import { GENERATION_FAILED_TEXT } from "../newDeckView"
import { failedDeckView } from "../deckActions"
import type { CardRowView, DeckDetailView } from "../deckView"
import { WritingState } from "../WritingState"
import { AiMark } from "./AiMark"
import { MasteryBar, MasteryLegend } from "./MasteryBar"
import { OriginTag } from "./OriginTag"

const FOCUS = "focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary"
const PRIMARY_BTN = `min-h-[50px] w-full rounded-[18px] bg-primary px-7 text-[15.5px] font-bold text-on-primary shadow-[0_14px_24px_-16px_oklch(0.3_0.07_242/0.7)] disabled:cursor-not-allowed disabled:bg-surface-container-high disabled:text-on-surface-variant disabled:shadow-none ${FOCUS}`

/** fc.css `.cdr`: [1fr auto], gap 12, padding 10 0, hairline above (not on the first row). */
function CardRow({ card, onEdit }: { card: CardRowView; onEdit: (card: CardRowView, opener: HTMLElement) => void }) {
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 py-2.5 [&+li]:shadow-[0_-1px_0_var(--color-outline-variant)]">
      <span className="grid min-w-0 gap-0.5">
        <b className="text-[15px] font-bold text-on-surface [overflow-wrap:anywhere]">{card.front}</b>
        <span className="text-[13px] text-on-surface-variant [overflow-wrap:anywhere]">{card.back}</span>
        {card.ai ? <AiMark label={card.sourceLabel} /> : null}
      </span>
      <button type="button" aria-label={`Edit card: ${card.front}`} onClick={(e) => onEdit(card, e.currentTarget)}
        className={`grid size-11 place-items-center rounded-[14px] text-on-surface-variant ${FOCUS}`}>
        <PencilSimple size={16} aria-hidden />
      </button>
    </li>
  )
}

/**
 * Everything below a deck's header: writing, failed, or the ready deck (FV and the FDD side panel).
 * No hooks and no router, so each state can be rendered and checked on its own.
 */
export function DeckContent({
  view, deck, variant, shortfall, retrying, addRef,
  onReview, onAdd, onEdit, onRetry, onDeleteFailed,
}: {
  view: DeckDetailView
  deck: Pick<DeckDetailDTO, "topic" | "origin" | "requestedCount">
  variant: "page" | "panel"
  /** The "9 of 12 cards written" line, only after a deck came back short. */
  shortfall: string | null
  retrying: boolean
  addRef?: Ref<HTMLButtonElement>
  onReview: () => void
  onAdd: (opener: HTMLElement) => void
  onEdit: (card: CardRowView, opener: HTMLElement) => void
  onRetry: () => void
  onDeleteFailed: () => void
}) {
  if (view.state === "writing") return <WritingState deck={deck} variant={variant} />

  if (view.state === "failed") {
    const failed = failedDeckView(retrying)
    return (
      <div className="grid gap-3">
        <div role="alert" className="rounded-xl bg-error-container px-3 py-2.5 text-[13.5px] font-semibold text-on-error-container">{GENERATION_FAILED_TEXT}</div>
        <button type="button" disabled={failed.retryDisabled} onClick={onRetry} className={PRIMARY_BTN}>{failed.retryLabel}</button>
        <button type="button" onClick={onDeleteFailed}
          className={`min-h-11 justify-self-center px-3.5 text-[15px] font-bold text-on-error-container ${FOCUS}`}>Delete deck</button>
      </div>
    )
  }

  return (
    <>
      <div className="grid gap-2">
        <OriginTag icon={view.originIcon}>{view.originLine}</OriginTag>
        <MasteryBar mastery={view.mastery} size="detail" />
        <MasteryLegend legend={view.legend} />
        {shortfall ? <span className="text-[13px] font-medium text-on-surface-variant">{shortfall}</span> : null}
      </div>
      <button type="button" disabled={!view.review.enabled} onClick={onReview} className={PRIMARY_BTN}>{view.review.label}</button>
      <section className={variant === "panel" ? "grid min-h-0 grid-rows-[auto_minmax(0,1fr)]" : "grid"}>
        <div className="flex items-center justify-between gap-2.5">
          <h2 className="font-sans text-[18px] font-extrabold tracking-[-0.01em] text-on-surface">Cards</h2>
          <button type="button" ref={addRef} onClick={(e) => onAdd(e.currentTarget)}
            className={`inline-flex min-h-11 items-center gap-1.5 rounded-[14px] px-1 text-[14px] font-bold text-primary ${FOCUS}`}>
            <Plus size={18} weight="bold" aria-hidden /> Add card
          </button>
        </div>
        {view.emptyCards ? (
          <p className="py-2 text-[14px] leading-[1.4] text-on-surface-variant">No cards in this deck yet. Add the first one.</p>
        ) : (
          <ul aria-label="Cards" className={variant === "panel" ? "min-h-0 overflow-auto [scrollbar-width:none]" : ""}>
            {view.cards.map((c) => <CardRow key={c.id} card={c} onEdit={onEdit} />)}
          </ul>
        )}
      </section>
    </>
  )
}
