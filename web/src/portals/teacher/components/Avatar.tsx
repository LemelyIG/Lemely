import { cn } from "@/lib/utils"

const TONE = {
  accent: "bg-accent-subtle text-[oklch(0.44_0.10_68)]",
  err: "bg-err-bg text-[oklch(0.40_0.10_22)]",
  warn: "bg-accent-subtle text-[oklch(0.42_0.10_68)]",
  neutral: "bg-[oklch(0.93_0.01_78)] text-t2",
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
