/* Hallmark · pre-emit critique: P4 H3 E4 S5 R4 V3 */
import { useId, type ComponentProps, type HTMLAttributes, type ReactNode } from "react"
import { useNativeFrame } from "@/lib/useNativeFrame"
import { cn } from "@/lib/utils"

/**
 * The standard card: `--paper-raised`, a 1px `--rule` hairline, `radius-lg`,
 * and **no shadow, ever** (DESIGN.md §7 — depth in this system comes from
 * tonal layering and hairlines, not elevation).
 *
 * P4.1 migrated the token names off the build-era `bg-surface-container-lowest`/`border-outline-variant`
 * aliases. The values are identical; these are the names DESIGN.md defines.
 * The docstring also claimed "a 1rem (16px) radius", quoting the build-era
 * DESIGN.md — `rounded-lg` resolves to `--radius-lg`, which is **12px**, and
 * 12px is what §6 specifies for a card. The comment had outlived the file it
 * cited and was describing a radius this component has never rendered.
 */
export function Card({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "bg-surface-container-lowest border border-outline-variant rounded-lg lm-native-card",
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
  return <div className={cn("lm-native-card-body p-5", className)} {...props} />
}

/**
 * A card whose heading is part of its section. Desktop, tablet and `other` keep the heading inside the
 * card (display-md). On the native frame the heading steps out of the surface and becomes a mono
 * section label above it (preview `.a-sec-h`), so a grouped surface holds content only.
 */
export function TitledCard({
  title,
  className,
  children,
  ...props
}: Omit<ComponentProps<"div">, "title"> & { title: ReactNode }) {
  const { native } = useNativeFrame()
  const id = useId()
  if (native) {
    return (
      <section aria-labelledby={id} className="flex flex-col">
        <h2 id={id} className="lm-native-section-label text-eyebrow">{title}</h2>
        <Card className={className} {...props}>
          {children}
        </Card>
      </section>
    )
  }
  return (
    <Card className={className} {...props}>
      <h2 className="px-6 pt-5 pb-4 text-display-md text-on-surface">{title}</h2>
      {children}
    </Card>
  )
}
