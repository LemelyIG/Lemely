/* Hallmark · pre-emit critique: P4 H3 E4 S3 R5 V3 */
import { DotsThree } from "@phosphor-icons/react"
import { useLayoutEffect, useRef, useState } from "react"
import { Popover } from "@/components/ui/popover"
import { QueryState } from "@/components/ui/query-state"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { useFlashcardDeck } from "@/lib/hooks/useFlashcardApi"
import { DECK_MENU_ITEMS, firstConnected, keepCachedOnError } from "./deckActions"
import { DeleteDeckSheet } from "./DeleteDeckSheet"
import { RenameDeckSheet } from "./RenameDeckSheet"
import { FOCUS } from "./parts/buttonStyles"
import { FcSheet } from "./parts/FcSheet"
import { SKELETON_FILL } from "./parts/skeletonStyles"

const ITEM = `block min-h-11 w-full rounded-md px-3 py-2 text-start text-[15px] font-semibold hover:bg-surface-container-low ${FOCUS}`
const itemTone = (destructive: boolean) => (destructive ? "text-on-error-container" : "text-on-surface")

type Which = "rename" | "delete" | null

/**
 * Where focus lands when the element it should return to has left the page (a deleted deck's menu
 * button, or the row that was held): the list's selected row, else its heading. Null off the list.
 */
const listAnchor = (): HTMLElement | null => firstConnected(
  document.querySelector<HTMLElement>("[data-fc-selected-row]"),
  document.querySelector<HTMLElement>("[data-fc-heading]"),
)

/**
 * The DOTS button in a deck header (fc.js `.icl.nd` on a page, plain `.icl` in the side panel) with
 * a Rename / Delete deck popover. The deck's name and card count come from the caller, which has
 * already loaded it. Both sheets give focus back to this button, because the menu item that opened
 * them is gone by then.
 */
export function DeckOptionsButton({
  deckId, title, cardCount, variant, onDeleted,
}: {
  deckId: string
  title: string
  cardCount: number
  variant: "page" | "panel"
  onDeleted: () => void
}) {
  const [open, setOpen] = useState(false)
  const [which, setWhich] = useState<Which>(null)
  const trigger = useRef<HTMLElement | null>(null)
  // After a delete the deck's screen, and this button with it, can be gone by the time focus returns.
  const back = () => firstConnected(trigger.current) ?? listAnchor()
  return (
    <>
      <Popover label="Deck options" open={open} onOpenChange={setOpen} align="end"
        renderTrigger={({ triggerProps }) => (
          <button {...triggerProps} type="button" aria-label="Deck options"
            ref={(node) => { trigger.current = node; triggerProps.ref(node) }}
            className={`grid size-11 flex-none place-items-center rounded-[14px] ${FOCUS} ${variant === "page" ? "bg-primary text-on-primary" : "bg-primary-container text-primary"}`}>
            <DotsThree size={20} weight="bold" aria-hidden />
          </button>
        )}>
        {DECK_MENU_ITEMS.map((item) => (
          <button key={item.id} type="button" className={`${ITEM} ${itemTone(item.destructive)}`}
            onClick={() => { setOpen(false); setWhich(item.id) }}>{item.label}</button>
        ))}
      </Popover>
      <RenameDeckSheet deckId={deckId} title={title} open={which === "rename"} onClose={() => setWhich(null)} restoreFocusTo={back} />
      <DeleteDeckSheet deckId={deckId} title={title} cardCount={cardCount} open={which === "delete"}
        onClose={() => setWhich(null)} onDeleted={onDeleted} restoreFocusTo={back} />
    </>
  )
}

/**
 * Long-press menu from the decks list (live K15). It only has an id, so it loads the deck for the
 * name and the card count the two sheets need; the menu body shows rows while that loads and a
 * retry if it cannot. The id is kept after the menu closes so the sheet it opened still has its deck.
 * Focus returns to the row that was held.
 */
export function DeckMenu({ deckId, onClose, onDeleted }: {
  deckId: string | null
  onClose: () => void
  /** Told which deck went, so the screen can leave a panel that was showing it. */
  onDeleted?: (deckId: string) => void
}) {
  const lastId = useRef<string | null>(deckId)
  if (deckId) lastId.current = deckId
  const [which, setWhich] = useState<Which>(null)
  // Only fetch while the menu or one of its sheets is on screen.
  const deck = useFlashcardDeck(deckId ?? (which ? lastId.current ?? "" : ""))
  const opener = useRef<HTMLElement | null>(null)
  // Layout effect: it runs before the sheet's own passive focus move, so this is still the held row.
  useLayoutEffect(() => {
    if (!deckId) return
    const active = document.activeElement
    // A touch long-press may leave focus on body; then there is no row to give it back to.
    opener.current = active instanceof HTMLElement && active !== document.body ? active : null
  }, [deckId])
  // No held row to return to (a touch hold leaves none) stays null; a held row that has since left
  // the list, because its deck was deleted, hands focus to the list instead of dropping it on body.
  const back = () => (opener.current ? firstConnected(opener.current) ?? listAnchor() : null)
  // Keep the last loaded deck so the sheets still have a name and a count while they slide out.
  const lastDeck = useRef(deck.data)
  if (deck.data) lastDeck.current = deck.data
  const shownDeck = deck.data ?? lastDeck.current
  const gate = keepCachedOnError({ status: deck.status, data: deck.data })
  const query = { status: gate.status, data: deck.data, error: deck.error, refetch: deck.refetch, fetchStatus: deck.fetchStatus }
  const id = lastId.current
  return (
    <>
      <FcSheet open={deckId !== null} onOpenChange={(o) => { if (!o) onClose() }} title={deck.data?.title ?? "Deck"}>
        <QueryState
          query={query}
          skeleton={<div className="grid gap-2" role="status" aria-label="Loading deck">
            <SkeletonBlock announce={false} className={`h-11 rounded-md ${SKELETON_FILL}`} /><SkeletonBlock announce={false} className={`h-11 rounded-md ${SKELETON_FILL}`} />
          </div>}
          error={{ heading: "Couldn’t load this deck", retryLabel: "Try again", compact: true }}
        >
          {() => DECK_MENU_ITEMS.map((item) => (
            <button key={item.id} type="button" className={`${ITEM} ${itemTone(item.destructive)}`}
              onClick={() => { setWhich(item.id); onClose() }}>{item.label}</button>
          ))}
        </QueryState>
      </FcSheet>
      {id && shownDeck ? (
        <>
          <RenameDeckSheet deckId={id} title={shownDeck.title} open={which === "rename"} onClose={() => setWhich(null)} restoreFocusTo={back} />
          <DeleteDeckSheet deckId={id} title={shownDeck.title} cardCount={shownDeck.cards.length} open={which === "delete"}
            onClose={() => setWhich(null)} onDeleted={() => onDeleted?.(id)} restoreFocusTo={back} />
        </>
      ) : null}
    </>
  )
}
