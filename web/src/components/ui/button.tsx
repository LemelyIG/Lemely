import { cva, type VariantProps } from "class-variance-authority"
import type { ButtonHTMLAttributes } from "react"
import { cn } from "@/lib/utils"

/*
 * Button variants ported from the mock's inline button styles.
 *   - ink:       dark solid (teacher primary CTA, student dark panels)
 *   - accent:    accent solid (student primary CTA)
 *   - secondary: bordered surface (both portals' secondary actions)
 *   - ghost:     borderless, hover tint
 * Tactile :active feedback + WCAG-AA foregrounds are baked in.
 */
const button = cva(
  // DESIGN.md "Buttons & Inputs: Use a consistent 0.5rem (8px) radius" —
  // `rounded` (--radius: 0.5rem) is the exact token, not rounded-[10px].
  "inline-flex items-center justify-center gap-2 font-sans whitespace-nowrap rounded cursor-pointer transition-colors disabled:opacity-50 disabled:pointer-events-none active:translate-y-px focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
  {
    variants: {
      variant: {
        ink: "border-0 bg-ink text-accent-on hover:bg-ink-hover",
        accent: "border-0 bg-accent text-accent-on hover:bg-accent-hover",
        secondary:
          "border border-border bg-surface text-t1 hover:bg-surface-2",
        ghost: "border-0 bg-transparent text-t2 hover:bg-surface-2",
      },
      // Sizes use the .btn-text(-sm/-lg) type-scale utilities (index.css,
      // deliberately NOT named text-*, see the comment above that class)
      // instead of bare text-[…] + font-medium — those classes already
      // bundle the DESIGN.md button-text family/weight/line-height,
      // font-medium was redundant. px/py use Tailwind's exact-multiple
      // spacing utilities (px-3.5 = 14px, py-2 = 8px, py-3 = 12px) or the
      // new named --spacing-*px / existing --spacing-container-mobile
      // tokens where no exact multiple exists.
      size: {
        sm: "btn-text-sm px-3.5 py-2",
        md: "btn-text px-18px py-11px",
        lg: "btn-text-lg px-container-mobile py-3",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
)

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof button> {}

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return <button className={cn(button({ variant, size }), className)} {...props} />
}
