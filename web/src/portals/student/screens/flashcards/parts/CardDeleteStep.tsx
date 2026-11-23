/* Hallmark · pre-emit critique: P4 H3 E4 S3 R5 V3 */
import { CARD_DELETE_ERROR, cardDeleteConfirm, deleteControls, type CardSource } from "../deckActions"

const FOCUS = "focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary"

/**
 * The second step of Delete card, the body of the card sheet. The card's own front is the
 * consequence and Keep it is the way out, so it takes focus: the Delete card button that opened this
 * step has just gone, and the safe choice is where a keyboard should land. While the request is in
 * flight, and after it succeeds, neither button can be pressed (see `deleteControls`).
 */
export function CardDeleteStep({
  card, state, onConfirm, onKeep,
}: {
  card: Pick<CardSource, "front">
  state: { isPending: boolean; isSuccess: boolean; isError: boolean }
  onConfirm: () => void
  onKeep: () => void
}) {
  const copy = cardDeleteConfirm(card)
  const controls = deleteControls(state, copy)
  return (
    <>
      <p className="text-[14px] leading-[1.4] text-on-surface-variant">{copy.body}</p>
      {state.isError ? <div role="alert" className="rounded-xl bg-error-container px-3 py-2.5 text-[13.5px] font-semibold text-on-error-container">{CARD_DELETE_ERROR}</div> : null}
      <button type="button" disabled={controls.confirmDisabled} onClick={onConfirm}
        className={`min-h-[50px] w-full rounded-[18px] bg-on-error-container px-7 text-[15.5px] font-bold text-on-primary disabled:opacity-60 ${FOCUS}`}>
        {controls.confirmLabel}
      </button>
      <button type="button" autoFocus disabled={controls.keepDisabled} onClick={onKeep}
        className={`min-h-11 justify-self-center px-3.5 text-[15px] font-bold text-primary disabled:opacity-60 ${FOCUS}`}>{copy.keep}</button>
    </>
  )
}
