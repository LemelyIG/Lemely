/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useState } from "react"
import { SmallChevron, TopicGlyph } from "./icons"
import { TopicChip } from "./TopicChip"
import { TOPIC_STATE_LABEL, type TopicState } from "./topics"
import "./redesign.css"

export interface TopicChipsProps {
  /** Order is the caller's (weakest first on student screens). */
  topics: { topic: string; state: TopicState; pct?: number }[]
  /** Phone and tablet: secure topics fold into one "N secure" chip that expands in place. */
  foldSecure?: boolean
  onSelect?: (topic: string) => void
}

const ORDER: TopicState[] = ["work", "getting", "secure"]

export function TopicChips({ topics, foldSecure = false, onSelect }: TopicChipsProps) {
  const [open, setOpen] = useState(false)
  const secureCount = topics.filter((t) => t.state === "secure").length
  const folded = foldSecure && !open && secureCount > 0
  const shown = folded ? topics.filter((t) => t.state !== "secure") : topics
  return (
    <div className="rd-chips-wrap">
      <ul className="rd-chips">
        {shown.map((t) => (
          <li key={t.topic}>
            <TopicChip topic={t.topic} state={t.state} pct={t.pct} onClick={onSelect ? () => onSelect(t.topic) : undefined} />
          </li>
        ))}
        {folded ? (
          <li>
            <button type="button" className="rd-chip rd-chip-more" data-state="secure" aria-expanded="false" onClick={() => setOpen(true)}>
              <TopicGlyph state="secure" />
              <span>{`${secureCount} secure`}</span>
              <SmallChevron />
            </button>
          </li>
        ) : null}
      </ul>
      <p className="rd-chip-legend" aria-hidden="true">
        {ORDER.map((s) => (
          <span key={s}>
            <TopicGlyph state={s} />
            {TOPIC_STATE_LABEL[s]}
          </span>
        ))}
      </p>
    </div>
  )
}
