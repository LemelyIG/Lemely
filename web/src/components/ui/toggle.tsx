/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V3 */
import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"
import { Toggle as TogglePrimitive } from "radix-ui"

const toggleVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium whitespace-nowrap transition-[color,box-shadow] hover:bg-surface-container hover:text-on-surface-variant active:bg-surface-container focus-visible:border-primary focus-visible:ring-[3px] focus-visible:ring-primary/50 disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-error aria-invalid:ring-error/20 data-[state=on]:bg-primary-container data-[state=on]:text-on-primary-container dark:aria-invalid:ring-error/40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-transparent",
        outline:
          "border border-outline bg-transparent shadow-xs active:bg-primary-container hover:bg-primary-container hover:text-on-primary-container",
        /**
         * A selectable option in a wrapping set (the waitlist form's levels, subjects,
         * boards, sessions). Filled primary when on, so "picked" survives a glance and never
         * reads as hover. Pair with `size="chip"`.
         */
        choice:
          "border border-outline bg-surface-container-lowest text-on-surface shadow-none hover:border-primary hover:bg-surface-container-low hover:text-on-surface active:bg-surface-container data-[state=on]:border-primary data-[state=on]:bg-primary data-[state=on]:text-on-primary data-[state=on]:hover:bg-primary-hover",
      },
      size: {
        default: "h-9 min-w-9 px-2",
        sm: "h-8 min-w-8 px-1.5",
        lg: "h-10 min-w-10 px-2.5",
        /** 44px touch target, 12px radius: the wrapping choice-chip row. */
        chip: "min-h-11 min-w-11 gap-1.5 rounded-xl px-4 text-body-sm font-semibold",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Toggle({
  className,
  variant,
  size,
  ...props
}: React.ComponentProps<typeof TogglePrimitive.Root> &
  VariantProps<typeof toggleVariants>) {
  return (
    <TogglePrimitive.Root
      data-slot="toggle"
      className={cn(toggleVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Toggle, toggleVariants }
