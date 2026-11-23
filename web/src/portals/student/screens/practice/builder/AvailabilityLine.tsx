/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V3 */
/* L4 · the live "what matches" line (the mock's `avl`, `avl.wait`, `avl.no`, plus the check-failed case). */
import { cn } from "@/lib/utils"
import { SpinnerRing, TickIcon } from "../practiceIcons"
import type { AvailabilityLine as Line } from "./builderModel"

const TONE: Record<Line["tone"], string> = {
  ok: "text-success-text",
  wait: "text-on-surface-variant",
  short: "text-on-tertiary-container",
  none: "text-on-tertiary-container",
  error: "text-error",
}

export function AvailabilityLine({ line }: { line: Line }) {
  return (
    <p role="status" className={cn("m-0 flex items-center gap-1.5 text-[13.5px] font-semibold", TONE[line.tone])}>
      {line.tone === "ok" ? <TickIcon /> : null}
      {line.tone === "wait" ? <SpinnerRing /> : null}
      {line.text}
    </p>
  )
}
