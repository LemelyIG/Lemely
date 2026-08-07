import { cn } from "@/lib/utils"

/*
 * P3.10 chunk c: the four foregrounds here were hand-picked oklch literals
 * from the pre-DESIGN.md mock and are now the semantic tokens they were
 * approximating. `accent` and `warn` collapse onto the same pair because the
 * mock's two values (lightness 0.44 and 0.42 at the same hue) were already
 * indistinguishable — the collapse is a faithful port, not a lost
 * distinction. Deliberately NOT remapped to the real amber `--warn`/
 * `--warn-bg` pair: that would be a design change, and all three of `accent`,
 * `err` and `warn` are in fact dead — every `<Avatar>` in the portal renders
 * `neutral`. (`tone="warn"`/`"err"`/`"ok"` elsewhere belong to `Chip`, a
 * different component.) Left as-is rather than pruned; deleting a
 * component's unused public variants is a simplification pass, not a token
 * retrofit.
 */
const TONE = {
  accent: "bg-accent-subtle text-accent-subtle-on",
  err: "bg-err-bg text-err",
  warn: "bg-accent-subtle text-accent-subtle-on",
  neutral: "bg-surface-2 text-t2",
} as const

/** Circular initials avatar, tinted per the mock's avBg / avFg palette. */
export function Avatar({
  initials,
  tone = "neutral",
  className,
}: {
  initials: string
  tone?: keyof typeof TONE
  className?: string
}) {
  return (
    <span
      className={cn(
        "flex-none rounded-full flex items-center justify-center font-semibold",
        TONE[tone],
        className,
      )}
    >
      {initials}
    </span>
  )
}
