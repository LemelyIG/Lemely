/* Hallmark · pre-emit critique: P4 H4 E4 S3 R5 V3 */
import { Link } from "react-router-dom"
import { CaretRight } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { FOCUS, HIT, LINK_FEEDBACK, PRESS } from "./gradeClass"

/** A section heading that is also its door: the title, then a caret. */
export function SectionLink({ id, title, to, className }: { id: string; title: string; to: string; className?: string }) {
  return (
    <h2 id={id} className={cn("m-0", className)}>
      <Link
        to={to}
        className={cn(
          "group inline-flex min-h-8 items-center gap-1 rounded-row font-display text-[17px] font-extrabold tracking-[-0.01em] text-on-surface",
          HIT,
          PRESS,
          LINK_FEEDBACK,
          FOCUS,
        )}
      >
        {title}
        <CaretRight size={16} weight="bold" className="text-on-surface-variant transition-colors group-hover:text-primary" aria-hidden="true" />
      </Link>
    </h2>
  )
}
