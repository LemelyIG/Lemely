/* Hallmark · pre-emit critique: P4 H3 E4 S3 R5 V3 */
import { PencilSimple, Sparkle, Target } from "@phosphor-icons/react"
import type { ReactNode } from "react"
import type { OriginIcon } from "../flashcardsView"

const ICON = { target: Target, sparkle: Sparkle, pen: PencilSimple } as const

/** fc.css `.og`: 500 13px, gap 5px, variant colour, 14px glyph. */
export function OriginTag({ icon, children }: { icon: OriginIcon; children: ReactNode }) {
  const Glyph = ICON[icon]
  return (
    <span className="inline-flex items-center gap-[5px] text-[13px] font-medium text-on-surface-variant">
      <Glyph size={14} weight="bold" aria-hidden />
      {children}
    </span>
  )
}
