export type TopicState = "work" | "getting" | "secure"

export const TOPIC_STATE_LABEL: Record<TopicState, string> = {
  work: "Work on",
  getting: "Getting there",
  secure: "Secure",
}

/**
 * The one shared source for mastery thresholds (mock sjf.js `lvl`, pr.css lvl3 zones),
 * as fractions of the marks. Every lane reads these; none hard-codes 60 or 75.
 */
export const MASTERY = { getting: 0.6, secure: 0.75 } as const

/** A topic's state from its percentage (0..100). */
export function topicState(pct: number): TopicState {
  const fraction = pct / 100
  if (fraction >= MASTERY.secure) return "secure"
  if (fraction >= MASTERY.getting) return "getting"
  return "work"
}
