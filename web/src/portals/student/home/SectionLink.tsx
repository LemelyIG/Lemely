/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Link } from "react-router-dom"
import { CaretRight } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { FOCUS, HIT } from "./gradeClass"

/** A section heading that is also its door: the title, then a caret. */
export function SectionLink({ id, title, to, className }: { id: string; title: string; to: string; className?: string }) {
  return (
    <h2 id={id} className={cn("m-0", className)}>
      <Link
        to={to}
        className={cn(
          "inline-flex min-h-8 items-center gap-1 rounded-row font-display text-[17px] font-extrabold tracking-[-0.01em] text-on-surface",
          HIT,
          FOCUS,
        )}
      >
        {title}
        <CaretRight size={16} weight="bold" className="text-on-surface-variant" aria-hidden="true" />
      </Link>
    </h2>
  )
}
