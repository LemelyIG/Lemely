/* Hallmark · pre-emit critique: P4 H3 E4 S5 R5 V3 */
/*
 * The study plan's drawn glyphs, from the approved mock (`sp.js` IC/TK). One
 * stroke family: round caps, 1.7–2.2 stroke on a 16–22 box, currentColor so the
 * tile or row decides the colour. The calendar is the kit's own glyph, re-exported
 * rather than redrawn, so the exam pill and the move button share one drawing.
 */
export { CalendarGlyph } from "@/components/redesign/icons"

type GlyphProps = { size?: number }

export function ActivityGlyph({ activity, size = 20 }: GlyphProps & { activity: string }) {
  switch (activity) {
    case "flashcards":
      return (
        <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinejoin="round" aria-hidden focusable="false">
          <rect x={3} y={5} width={11} height={12} rx={2} />
          <path d="M7 3h8a2 2 0 0 1 2 2v9" />
        </svg>
      )
    case "past_paper":
      return (
        <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinejoin="round" strokeLinecap="round" aria-hidden focusable="false">
          <path d="M5 2.5h7l3.5 3.5v11.5h-10.5zM12 2.5V6h3.5M8 10h5M8 13h5" />
        </svg>
      )
    case "review":
      return <RebuildGlyph size={size} />
    default:
      return (
        <svg width={size} height={size} viewBox="0 0 22 22" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" aria-hidden focusable="false">
          <path d="M5 4h12v14H5zM8 8h6M8 12h6" />
        </svg>
      )
  }
}

/** The geometric, centred "digital" tick. */
export function TickGlyph({ size = 16 }: GlyphProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false">
      <path d="M3.5 8.3 6.5 11l6-6.5" />
    </svg>
  )
}

export function RebuildGlyph({ size = 16, className }: GlyphProps & { className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false" className={className}>
      <path d="M3.5 10a6.5 6.5 0 1 0 2-4.7M3.5 3v3.5H7" />
    </svg>
  )
}
