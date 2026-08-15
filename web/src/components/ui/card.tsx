/* Hallmark · pre-emit critique: P4 H3 E4 S5 R4 V3 */
import type { HTMLAttributes } from "react"
import { cn } from "@/lib/utils"

/**
 * The standard card: `--paper-raised`, a 1px `--rule` hairline, `radius-lg`,
 * and **no shadow, ever** (DESIGN.md §7 — depth in this system comes from
 * tonal layering and hairlines, not elevation).
 *
 * P4.1 migrated the token names off the build-era `bg-surface`/`border-border`
 * aliases. The values are identical; these are the names DESIGN.md defines.
 * The docstring also claimed "a 1rem (16px) radius", quoting the build-era
 * DESIGN.md — `rounded-lg` resolves to `--radius-lg`, which is **12px**, and
 * 12px is what §6 specifies for a card. The comment had outlived the file it
 * cited and was describing a radius this component has never rendered.
 */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "bg-paper-raised border border-rule rounded-lg",
        className,
      )}
      {...props}
    />
  )
}

/** Card with default interior padding (18–20px in the mock). */
export function CardBody({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-5", className)} {...props} />
}
