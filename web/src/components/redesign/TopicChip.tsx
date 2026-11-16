/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { TopicGlyph } from "./icons"
import { TOPIC_STATE_LABEL, type TopicState } from "./topics"
import "./redesign.css"

export interface TopicChipProps {
  topic: string
  state: TopicState
  onClick?: () => void
  pct?: number
}

/** A topic chip with its state icon (mock .tm): Work on, Getting there, Secure. */
export function TopicChip({ topic, state, onClick, pct }: TopicChipProps) {
  const inner = (
    <>
      <TopicGlyph state={state} />
      <span>{topic}</span>
      <span className="sr-only">{`, ${TOPIC_STATE_LABEL[state]}`}</span>
      {pct !== undefined ? <b>{`${pct}%`}</b> : null}
    </>
  )
  return onClick ? (
    <button type="button" className="rd-chip" data-state={state} onClick={onClick}>
      {inner}
    </button>
  ) : (
    <span className="rd-chip" data-state={state}>
      {inner}
    </span>
  )
}
