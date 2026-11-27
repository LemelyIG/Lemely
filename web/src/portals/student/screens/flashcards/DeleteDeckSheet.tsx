/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V3 */
import { ERROR_ALERT } from "./parts/errorAlert"
import { useEffect } from "react"
import { useToast } from "@/components/ui/toast"
import { useDeleteDeck } from "@/lib/hooks/useFlashcardApi"
import { DELETE_DECK_ERROR, deleteControls, deleteDeckConfirm, submitDeleteDeck } from "./deckActions"
import { ALERT_BODY_ID, FcSheet } from "./parts/FcSheet"
import { DANGER_BTN, FOCUS } from "./parts/buttonStyles"


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
  const controls = deleteControls(del, view)
  return (
    <FcSheet open={open} onOpenChange={(o) => { if (!o && !del.isPending) onClose() }} title={view.title} alert dismissible={!del.isPending} restoreFocusTo={restoreFocusTo}>
      <p id={ALERT_BODY_ID} className="text-[14px] leading-[1.4] text-on-surface-variant">{view.body}</p>
      {del.isError ? <div role="alert" className={ERROR_ALERT}>{DELETE_DECK_ERROR}</div> : null}
      <button type="button" disabled={controls.confirmDisabled}
        onClick={() => submitDeleteDeck(deckId, del.mutate, {
          onClose,
          onDeleted: () => { toast({ title: `${title} deleted`, variant: "success" }); onDeleted() },
        })}
        className={DANGER_BTN}>
        {controls.confirmLabel}
      </button>
      <button type="button" autoFocus disabled={controls.keepDisabled} onClick={onClose}
        className={`min-h-11 justify-self-center px-3.5 text-[15px] font-bold text-primary disabled:opacity-60 ${FOCUS}`}>{view.keep}</button>
    </FcSheet>
  )
}
