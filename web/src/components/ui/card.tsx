import type { HTMLAttributes } from "react"
import { cn } from "@/lib/utils"

/** Surface card matching the mock (surface bg, 1px border, ~14px radius). */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "bg-surface border border-border rounded-[14px]",
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
