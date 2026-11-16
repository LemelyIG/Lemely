/* Small copy helpers shared by the Practice tab models (L4). Pure; no `.tsx` imports. */

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`
}

const NUMBERING = /^\d+(?:\.\d+)*\s+/

/** "1.2 Motion" -> "Motion". Keeps the raw string if stripping would empty it. */
export function topicLabel(topic: string): string {
  const stripped = topic.replace(NUMBERING, "").trim()
  return stripped.length > 0 ? stripped : topic
}

/** The "try another subject" sentence for a subject with no questions yet. */
export function tryOthers(names: readonly string[]): string {
  if (names.length === 0) return "We're adding them. Check back soon."
  if (names.length === 1) return `We're adding them. Try ${names[0]} for now.`
  return `We're adding them. Try ${names.slice(0, -1).join(", ")} or ${names[names.length - 1]} for now.`
}

/* Nearest existing tokens to the mock's subject dots (no token changes allowed). */
const DOT_COLORS = [
  "var(--color-grade-a)",
  "var(--color-primary)",
  "var(--color-on-tertiary-container)",
] as const

export function subjectDotColor(code: string, orderedCodes: readonly string[]): string {
  const index = orderedCodes.indexOf(code)
  return index >= 0 && index < DOT_COLORS.length ? DOT_COLORS[index] : "var(--color-outline)"
}
