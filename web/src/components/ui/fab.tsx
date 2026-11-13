import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react"
import { cn } from "@/lib/utils"

/*
 * The Android native frame's floating action button (M3): a 56px primary-container
 * container, 16px corners, bottom-end above the tab bar and clear of the safe areas
 * (`.lm-native-fab` in index.css owns the geometry). `extended` adds the label beside
 * the glyph; without it the label is the accessible name only. Rendered on Android
 * phones and nowhere else: iOS puts the same action in the large-title row, and
 * desktop keeps the top-bar button.
 */
export interface FabProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: ReactNode
  label: string
  extended?: boolean
}

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
      <span className={extended ? "text-label" : "sr-only"}>{label}</span>
    </button>
  )
})
