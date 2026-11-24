/* Hallmark · pre-emit critique: P4 H3 E4 S3 R5 V3 */
import { ERROR_ALERT } from "./parts/errorAlert"
import { useEffect, useState } from "react"
import { useRenameDeck } from "@/lib/hooks/useFlashcardApi"
import { DECK_TITLE_MAX, RENAME_ERROR, renameControls, renameTitle, submitRename } from "./deckActions"
import { FcSheet } from "./parts/FcSheet"
import { FOCUS, PRIMARY_BTN } from "./parts/buttonStyles"


/** One step, no confirm: a rename is undone by renaming again. Save stays off until the name differs. */
export function RenameDeckSheet({
  deckId, title, open, onClose, restoreFocusTo,
}: {
  deckId: string
  title: string
  open: boolean
  onClose: () => void
  restoreFocusTo?: () => HTMLElement | null
}) {
  const rename = useRenameDeck()
  const [value, setValue] = useState(title)
  useEffect(() => {
    if (open) { setValue(title); rename.reset() }
    // Reset on open only; `rename` changes identity every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
  const valid = renameTitle(title, value) !== null
  const controls = renameControls({ valid, pending: rename.isPending })
  const submit = () => { if (!rename.isPending) submitRename(deckId, title, value, rename.mutate, onClose) }
  return (
    <FcSheet open={open} onOpenChange={(o) => { if (!o && !rename.isPending) onClose() }} title="Rename deck" restoreFocusTo={restoreFocusTo}>
      <label className="grid gap-1.5 text-[13px] font-semibold leading-tight text-on-surface-variant">
        <span>Name</span>
        <input autoFocus maxLength={DECK_TITLE_MAX} value={value} onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && valid) { e.preventDefault(); submit() } }}
          className="rounded-2xl bg-surface-container-lowest px-3.5 py-3 text-[16px] font-medium text-on-surface shadow-[inset_0_0_0_1.5px_var(--color-outline)] outline-none focus:shadow-[inset_0_0_0_2px_var(--color-primary)]" />
      </label>
      {rename.isError ? <div role="alert" className={ERROR_ALERT}>{RENAME_ERROR}</div> : null}
      <button type="button" disabled={controls.saveDisabled} onClick={submit}
        className={PRIMARY_BTN}>
        {controls.saveLabel}
      </button>
      <button type="button" disabled={controls.cancelDisabled} onClick={onClose}
        className={`min-h-11 justify-self-center px-3.5 text-[15px] font-bold text-primary disabled:opacity-60 ${FOCUS}`}>Cancel</button>
    </FcSheet>
  )
}
