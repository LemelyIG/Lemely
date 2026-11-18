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

export interface TopicEntry {
  topic: string
  state: TopicState
  pct?: number
}

/** Topics to show: when folding is on and not yet opened, secure ones are hidden (the "N secure" chip stands in). */
export function visibleTopics<T extends { state: TopicState }>(topics: readonly T[], foldSecure: boolean, open: boolean): T[] {
  const folded = foldSecure && !open && topics.some((t) => t.state === "secure")
  return folded ? topics.filter((t) => t.state !== "secure") : [...topics]
}

/** Focus goes to the chip's own button when it has one, else to its list item. */
export function focusTarget<T>(item: T | null | undefined, button: T | null | undefined): T | undefined {
  return button ?? item ?? undefined
}

/** Content signature: equal for rebuilt-but-identical topic lists. */
export function topicsSignature(topics: readonly { topic: string; state: TopicState }[]): string {
  return topics.map((t) => `${t.topic}:${t.state}`).join("|")
}

/** Keys from the full list (topic plus occurrence number), so they survive folding. */
export function topicKeys(topics: readonly { topic: string }[]): string[] {
  const seen = new Map<string, number>()
  return topics.map((t) => {
    const n = seen.get(t.topic) ?? 0
    seen.set(t.topic, n + 1)
    return `${t.topic}#${n}`
  })
}
