/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useEffect, useRef, useState } from "react"
import { SmallChevron, TopicGlyph } from "./icons"
import { TopicChip } from "./TopicChip"
import { TOPIC_STATE_LABEL, visibleTopics, type TopicState } from "./topics"
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
  const [seen, setSeen] = useState(topics)
  const listRef = useRef<HTMLUListElement>(null)
  const justOpened = useRef(false)
  // A new topics list starts folded again (adjusted during render, no effect needed).
  if (seen !== topics) {
    setSeen(topics)
    setOpen(false)
  }
  const secureCount = topics.filter((t) => t.state === "secure").length
  const folded = foldSecure && !open && secureCount > 0
  const shown = visibleTopics(topics, foldSecure, open)
  const firstSecure = shown.findIndex((t) => t.state === "secure")

  // The fold button unmounts on activation: hand focus to the first revealed secure chip.
  useEffect(() => {
    if (!open || !justOpened.current) return
    justOpened.current = false
    const target = listRef.current?.querySelector<HTMLElement>("[data-first-revealed]")
    target?.querySelector<HTMLElement>("button")?.focus() ?? target?.focus()
  }, [open])

  return (
    <div className="rd-chips-wrap">
      <ul className="rd-chips" role="list" ref={listRef}>
        {shown.map((t, i) => (
          <li
            key={`${t.topic}-${i}`}
            {...(open && foldSecure && i === firstSecure ? { "data-first-revealed": "", tabIndex: -1 } : {})}
          >
            <TopicChip topic={t.topic} state={t.state} pct={t.pct} onClick={onSelect ? () => onSelect(t.topic) : undefined} />
          </li>
        ))}
        {folded ? (
          <li>
            <button
              type="button"
              className="rd-chip rd-chip-more"
              data-state="secure"
              aria-expanded={open}
              onClick={() => {
                justOpened.current = true
                setOpen(true)
              }}
            >
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
