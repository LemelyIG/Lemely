/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V3 */
import { useEffect } from "react"
import { useToast } from "@/components/ui/toast"
import { useDeleteDeck } from "@/lib/hooks/useFlashcardApi"
import { DELETE_DECK_ERROR, deleteDeckConfirm, submitDeleteDeck } from "./deckActions"
import { FcSheet } from "./parts/FcSheet"

const FOCUS = "focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary"

/**
 * FX. The consequence is on the sheet (what goes, that it can't come back) and Keep it is the way
 * out, so there is no undo to offer. On failure the deck stays and the sheet says so.
 */
export function DeleteDeckSheet({
  deckId, title, cardCount, open, onClose, onDeleted, restoreFocusTo,
}: {
  deckId: string
  title: string
  cardCount: number
  open: boolean
  onClose: () => void
  onDeleted: () => void
  restoreFocusTo?: () => HTMLElement | null
}) {
  const del = useDeleteDeck()
  const { toast } = useToast()
  useEffect(() => {
    if (open) del.reset()
    // Reset on open only; `del` changes identity every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
  const view = deleteDeckConfirm({ title, cardCount })
  return (
    <FcSheet open={open} onOpenChange={(o) => { if (!o && !del.isPending) onClose() }} title={view.title} alert restoreFocusTo={restoreFocusTo}>
      <p className="text-[14px] leading-[1.4] text-on-surface-variant">{view.body}</p>
      {del.isError ? <div role="alert" className="rounded-xl bg-error-container px-3 py-2.5 text-[13.5px] font-semibold text-on-error-container">{DELETE_DECK_ERROR}</div> : null}
      <button type="button" disabled={del.isPending}
        onClick={() => submitDeleteDeck(deckId, del.mutate, {
          onClose,
          onDeleted: () => { toast({ title: `${title} deleted`, variant: "success" }); onDeleted() },
        })}
        className={`min-h-[50px] w-full rounded-[18px] bg-on-error-container px-7 text-[15.5px] font-bold text-on-primary disabled:opacity-60 ${FOCUS}`}>
        {del.isPending ? view.pending : view.confirm}
      </button>
      <button type="button" onClick={onClose} className={`min-h-11 justify-self-center px-3.5 text-[15px] font-bold text-primary ${FOCUS}`}>{view.keep}</button>
    </FcSheet>
  )
}
