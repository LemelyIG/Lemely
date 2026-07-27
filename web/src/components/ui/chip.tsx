import { cva, type VariantProps } from "class-variance-authority"
import type { HTMLAttributes } from "react"
import { cn } from "@/lib/utils"

/*
 * Rounded status chip from the mock. Tones map to the shared semantic tokens:
 *   ok = graded / parsed / correct, warn = pending / processing / attention,
 *   err = needs-review / dropped, neutral = queued / muted, accent = live.
 */
const chip = cva(
  "inline-flex items-center gap-1.5 rounded-full text-[11px] leading-none px-[9px] py-[3px] font-medium",
  {
    variants: {
      tone: {
        ok: "bg-ok-bg text-ok",
        warn: "bg-warn-bg text-warn",
        err: "bg-err-bg text-err",
        neutral: "bg-surface-2 text-t2",
        accent: "bg-accent-subtle text-accent",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
)

export interface ChipProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof chip> {}

export function Chip({ className, tone, ...props }: ChipProps) {
  return <span className={cn(chip({ tone }), className)} {...props} />
}
