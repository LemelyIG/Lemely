import type { HTMLAttributes } from "react"
import { cn } from "@/lib/utils"

/*
 * A single keyboard key, for documenting a shortcut inline in copy ("press
 * `Esc` to close") or in a shortcuts-reference panel. Mono face because a key
 * cap is data about the machine, not prose — the same reasoning `--fs-data-*`
 * uses for marks and IDs — and a hairline border rather than the `shadow-float`
 * "key cap" look some systems use, since DESIGN.md §7 keeps this system flat
 * and reserves shadow for floating layers, which a key glyph is not.
 *
 * Not interactive: this renders the native `<kbd>` element, which carries its
 * own semantic meaning to assistive tech without needing a role. There is
 * nothing to click, hover meaningfully, or disable, so this component only
 * has the one state its content already implies.
 */

export type KbdSize = "sm" | "md"

const sizeClasses: Record<KbdSize, string> = {
  sm: "min-w-[18px] h-[18px] px-1 text-data-sm",
  md: "min-w-[22px] h-[22px] px-1.5 text-data-md",
}

export interface KbdProps extends HTMLAttributes<HTMLElement> {
  size?: KbdSize
}

export function Kbd({ size = "sm", className, ...props }: KbdProps) {
  return (
    <kbd
      className={cn(
        "inline-flex items-center justify-center rounded-sm border border-rule bg-paper-raised leading-none text-ink-muted",
        sizeClasses[size],
        className,
      )}
      {...props}
    />
  )
}
