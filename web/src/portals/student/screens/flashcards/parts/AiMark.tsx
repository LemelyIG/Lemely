import { Sparkle } from "@phosphor-icons/react"

/** Marks an AI-written card (P4.9 honesty rule 1). Visible glyph + "AI", full label for AT. */
export function AiMark({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-[12px] font-semibold text-on-surface-variant">
      <Sparkle size={12} weight="fill" aria-hidden />
      <span aria-hidden>AI</span>
      <span className="sr-only">{label}</span>
    </span>
  )
}
