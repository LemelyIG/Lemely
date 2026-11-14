import { forwardRef, useEffect, useState, type ButtonHTMLAttributes, type ReactNode } from "react"
import { cn } from "@/lib/utils"

/*
 * The Android native frame's floating action button (M3): a 56px primary-container
 * container, 16px corners, bottom-end above the tab bar and clear of the safe areas
 * (`.lm-native-fab` in index.css owns the geometry). `extended` adds the label beside
 * the glyph; without it the label is the accessible name only. Rendered on Android
 * phones and nowhere else: iOS puts the same action in the large-title row, and
 * desktop keeps the top-bar button.
 */

/** M3: an extended FAB shrinks to a plain FAB while the page scrolls down and extends again on scroll up or at the top. */
export function useExtendedOnScroll(): boolean {
  const [extended, setExtended] = useState(true)
  useEffect(() => {
    let last = window.scrollY
    const onScroll = () => {
      const y = window.scrollY
      if (y <= 8) setExtended(true)
      else if (y > last + 4) setExtended(false)
      else if (y < last - 4) setExtended(true)
      last = y
    }
    window.addEventListener("scroll", onScroll, { passive: true })
    return () => window.removeEventListener("scroll", onScroll)
  }, [])
  return extended
}

export interface FabProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: ReactNode
  label: string
  extended?: boolean
}

/**
 * The FAB that follows the page scroll. The scroll listener and its state live here, so the shell
 * and the portal layout above it do not re-render on every extend or collapse.
 */
export const ScrollFab = forwardRef<HTMLButtonElement, Omit<FabProps, "extended">>(function ScrollFab(props, ref) {
  const extended = useExtendedOnScroll()
  return <Fab ref={ref} extended={extended} {...props} />
})

export const Fab = forwardRef<HTMLButtonElement, FabProps>(function Fab(
  { icon, label, extended = false, className, type = "button", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      data-extended={extended || undefined}
      className={cn(
        "lm-native-fab lm-press hidden native:android:inline-flex items-center justify-center bg-primary-container text-on-primary-container shadow-[var(--shadow-float)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
        className,
      )}
      {...props}
    >
      {icon}
      {/* The label stays mounted, so the accessible name never changes: a grid track animates its
          width between 0fr and 1fr (see .lm-native-fab-label in index.css). When collapsed the text
          is clipped, not removed, so it is still the button's name. */}
      <span className="lm-native-fab-label">
        <span className="text-label">{label}</span>
      </span>
    </button>
  )
})
