/* Hallmark · pre-emit critique: P4 H3 E4 S4 R5 V3 */
import { cn } from "@/lib/utils"
import { RebuildGlyph } from "./icons"
import { COPY } from "./planCopy"

/*
 * The provenance line (`.based`): what the week was built from, and the one
 * action that rebuilds it. While rebuilding it waits, and the glyph turns
 * (still under reduced motion: the words carry the state).
 */
export function BasedOn({
  line,
  rebuilding,
  onRebuild,
  className,
}: {
  line: string
  rebuilding: boolean
  onRebuild: () => void
  className?: string
}) {
  return (
    <button
      type="button"
      onClick={onRebuild}
      disabled={rebuilding}
      aria-busy={rebuilding || undefined}
      className={cn(
        "flex min-h-11 items-center gap-1.5 rounded-[10px] text-start font-sans text-[13px] leading-[1.4] font-medium text-on-surface-variant",
        "focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary",
        "enabled:hover:[&_b]:underline enabled:hover:[&_b]:underline-offset-2",
        className,
      )}
    >
      <RebuildGlyph className={cn("shrink-0", rebuilding && "motion-safe:animate-spin")} />
      <span>
        {line} · <b className="font-bold text-primary">{rebuilding ? COPY.rebuilding : COPY.rebuild}</b>
      </span>
    </button>
  )
}
