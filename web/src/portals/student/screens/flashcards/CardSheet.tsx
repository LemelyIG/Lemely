/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { useEffect, useRef, useState } from "react"
import { useAddCard, useDeleteCard, useEditCard } from "@/lib/hooks/useFlashcardApi"
import {
  cardDeleteConfirm, cardDraftFor, cardSave, cardSaveError, cardSaveLabel, cardSheetTitle,
  submitCard, submitCardDelete, type CardCloseOutcome, type CardMode, type CardMutators,
} from "./deckActions"
import type { CardRowView } from "./deckView"
import { CardDeleteStep } from "./parts/CardDeleteStep"
import { FcSheet } from "./parts/FcSheet"
import { FOCUS, PRIMARY_BTN } from "./parts/buttonStyles"

/** pr.css `.fld textarea`: Mono 16/1.5, r16, 1.5px outline, primary 2px on focus. The border is the focus ring. */
const FIELD = "rounded-2xl bg-surface-container-lowest px-3.5 py-3 font-mono text-[16px] font-medium leading-[1.5] text-on-surface shadow-[inset_0_0_0_1.5px_var(--color-outline)] outline-none resize-none focus:shadow-[inset_0_0_0_2px_var(--color-primary)]"
const ERROR = "rounded-xl bg-error-container px-3 py-2.5 text-[13.5px] font-semibold text-on-error-container"

/**
 * FC (edit), add, and the second step of Delete card, in one sheet so the move between them keeps
 * focus and does not flash a second sheet in. The content holds its last mode and card while the
 * sheet slides out, so it never blanks mid-exit.
 */
export function CardSheet({
  deckId, card, mode, onClose, restoreFocusTo,
}: {
  deckId: string
  card: CardRowView | null
  mode: CardMode | null
  onClose: () => void
  /** Called as the sheet closes, with how it ended, to name the element focus should return to. */
  restoreFocusTo?: (outcome: CardCloseOutcome) => HTMLElement | null
}) {
  const add = useAddCard(deckId)
  const edit = useEditCard(deckId)
  const remove = useDeleteCard(deckId)
  const shown = useRef<{ mode: CardMode; card: CardRowView | null }>({ mode: "add", card: null })
  if (mode) shown.current = { mode, card }
  const { mode: shownMode, card: shownCard } = shown.current
  const [draft, setDraft] = useState(cardDraftFor(card))
  const [confirming, setConfirming] = useState(false)
  const outcome = useRef<CardCloseOutcome>("dismissed")

  useEffect(() => {
    if (!mode) return
    setDraft(cardDraftFor(card))
    setConfirming(false)
    outcome.current = "dismissed"
    add.reset(); edit.reset(); remove.reset()
    // The mutation objects change identity every render; only a new open should reset the form.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, card?.id])

  const mutators: CardMutators = { add: add.mutate, edit: edit.mutate, remove: remove.mutate }
  const finish = (how: CardCloseOutcome) => () => { outcome.current = how; onClose() }
  const saving = add.isPending || edit.isPending
  const canSave = cardSave(shownMode, shownCard, draft) !== null

  const sheetProps = {
    open: mode !== null,
    onOpenChange: (open: boolean) => { if (!open && !saving && !remove.isPending) finish("dismissed")() },
    restoreFocusTo: () => restoreFocusTo?.(outcome.current) ?? null,
  }

  if (confirming && shownCard) {
    return (
      <FcSheet {...sheetProps} title={cardDeleteConfirm(shownCard).title} alert>
        <CardDeleteStep card={shownCard} state={remove}
          onConfirm={() => submitCardDelete(shownCard, mutators, finish("deleted"))}
          onKeep={() => { remove.reset(); setConfirming(false) }} />
      </FcSheet>
    )
  }

  const failed = add.isError || edit.isError
  return (
    <FcSheet {...sheetProps} title={cardSheetTitle(shownMode)}>
      <label className="grid gap-1.5 text-[13px] font-semibold leading-tight text-on-surface-variant">
        <span>Front</span>
        <textarea rows={2} required value={draft.front} onChange={(e) => setDraft((d) => ({ ...d, front: e.target.value }))} className={FIELD} />
      </label>
      <label className="grid gap-1.5 text-[13px] font-semibold leading-tight text-on-surface-variant">
        <span>Back</span>
        <textarea rows={2} required value={draft.back} onChange={(e) => setDraft((d) => ({ ...d, back: e.target.value }))} className={FIELD} />
      </label>
      {failed ? <div role="alert" className={ERROR}>{cardSaveError(shownMode)}</div> : null}
      <button type="button" disabled={!canSave || saving}
        onClick={() => submitCard(shownMode, shownCard, draft, mutators, finish("saved"))} className={PRIMARY_BTN}>
        {cardSaveLabel(shownMode, saving)}
      </button>
      {shownMode === "edit" ? (
        <button type="button" onClick={() => setConfirming(true)}
          className={`min-h-11 justify-self-center px-3.5 text-[15px] font-bold text-on-error-container ${FOCUS}`}>Delete card</button>
      ) : null}
    </FcSheet>
  )
}
