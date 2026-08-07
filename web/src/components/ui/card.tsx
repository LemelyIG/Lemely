import type { HTMLAttributes } from "react"
import { cn } from "@/lib/utils"

/** Surface card matching the mock (surface bg, 1px border, DESIGN.md
 * "Primary Cards: Use a 1rem (16px) radius" — `rounded-lg` is the exact
 * token, not rounded-lg). */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "bg-surface border border-border rounded-lg",
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
