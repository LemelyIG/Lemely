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
  "inline-flex items-center justify-center gap-2 font-sans whitespace-nowrap rounded-[10px] cursor-pointer transition-colors disabled:opacity-50 disabled:pointer-events-none active:translate-y-px focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
  {
    variants: {
      variant: {
        ink: "border-0 bg-ink text-accent-on hover:bg-ink-hover",
        accent: "border-0 bg-accent text-accent-on hover:bg-accent-hover",
        secondary:
          "border border-border bg-surface text-t1 hover:bg-surface-2",
        ghost: "border-0 bg-transparent text-t2 hover:bg-surface-2",
      },
      size: {
        sm: "text-[12.5px] font-medium px-[14px] py-[8px]",
        md: "text-[13px] font-medium px-[18px] py-[11px]",
        lg: "text-[13.5px] font-medium px-[22px] py-[12px]",
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
