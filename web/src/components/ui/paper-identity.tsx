import type { HTMLAttributes } from "react"
import { cn } from "@/lib/utils"

/*
 * C-7 Paper identity line. The compact, consistent way a paper is named
 * everywhere: "0580/42 · May/June 2023 · Paper 4 Variant 2". Set in
 * text-metadata (JetBrains Mono) — DESIGN.md reserves mono for exam codes
 * specifically. The subject/paper code reads slightly stronger (t2) than the
 * session and paper label (t3) since it's the field that determines which
 * mark scheme was used.
 */

export interface PaperIdentityProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  /** e.g. "0580/42" */
  code: string
  /** e.g. "May/June 2023" */
  session: string
  /** e.g. "Paper 4 Variant 2" */
  paperLabel: string
}

export function PaperIdentity({
  code,
  session,
  paperLabel,
  className,
  ...props
}: PaperIdentityProps) {
  return (
    <div
      className={cn("flex items-center gap-1.5 flex-wrap text-metadata", className)}
      {...props}
    >
      <span className="text-t2">{code}</span>
      <span className="text-t3" aria-hidden>
        ·
      </span>
      <span className="text-t3">{session}</span>
      <span className="text-t3" aria-hidden>
        ·
      </span>
      <span className="text-t3">{paperLabel}</span>
    </div>
  )
}
