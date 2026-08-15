import { cva, type VariantProps } from "class-variance-authority"
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react"
import { CircleNotch } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"

/**
 * The Study Notebook button (DESIGN.md §12).
 *
 * Four variants:
 *   - `primary`   accent fill, the one obvious action on a screen
 *   - `ink`       solid ink fill, for a dark panel or a teacher's primary CTA
 *   - `secondary` raised paper with a hairline rule, the default
 *   - `ghost`     no fill and no border, for Cancel and inline actions
 *
 * Rewritten in Phase 2 from the build-era version, which carried three real
 * defects against the new system rather than merely old colours:
 *
 * 1. **It focused with `outline-accent`.** DESIGN.md §3.9 requires the focus
 *    ring to be the blue `--focus-ring` precisely so it is distinguishable
 *    from the accent's own hover and selected states. An accent-coloured ring
 *    on an accent-filled button is very nearly invisible, which is the one
 *    situation a focus ring exists for. It now inherits the global
 *    `:focus-visible` rule in index.css instead of overriding it.
 * 2. **It pressed with `translate-y-px`.** The spec's press is `scale(0.98)`
 *    (§9.2). Both animate a transform so both are cheap, but a consistent
 *    press feel across the product is the point of specifying one.
 * 3. **It had no loading state**, so every call site invented its own
 *    disabled-plus-spinner arrangement. `loading` is now a prop: it disables
 *    the button, swaps in a spinner, keeps the label for layout stability so
 *    the button does not resize mid-submit, and marks it `aria-busy`.
 *
 * `disabled` deliberately uses `opacity-50` plus `pointer-events-none` rather
 * than a separate grey palette: a disabled control should read as the same
 * control, dimmed, not as a different component.
 */
const button = cva(
  [
    "inline-flex items-center justify-center gap-2 whitespace-nowrap",
    "cursor-pointer rounded-md font-sans",
    /*
     * §6.1's 44x44 touch floor, on a finger only.
     *
     * The global `(pointer: coarse)` rule in index.css reaches `<button>`, but
     * this recipe is also used on `<a>` elements through `buttonVariants` (the
     * 404 screen's way out, the landing CTAs), and an anchor is not a button
     * selector. P6.1 measured those anchors at 32-34px tall on every mobile
     * width. Stated here so both renderings of the same control agree.
     *
     * Safe as a min: the base is already `inline-flex items-center`, so the
     * label centres in the taller box rather than sitting at its top.
     */
    "pointer-coarse:min-h-11 pointer-coarse:min-w-11",
    // Colour-only transition, plus the transform used by the press. Never
    // `ease-in-out` or `linear` on a designed transition (DESIGN.md §9.1).
    "transition-[color,background-color,border-color,transform]",
    "duration-[var(--dur-fast)] ease-out-soft",
    "active:scale-[0.98]",
    "disabled:pointer-events-none disabled:opacity-50",
  ],
  {
    variants: {
      variant: {
        primary: "border-0 bg-accent text-accent-on hover:bg-accent-hover",
        /**
         * Alias of `primary`, kept because 26 existing call sites say
         * `variant="accent"`. DESIGN.md §12 names the ROLE "primary" and the
         * fill "accent", so `primary` is the canonical name and new code
         * should use it, but renaming is not worth breaking 26 screens
         * mid-redesign. Phase 4 migrates the call sites surface by surface and
         * this alias goes with the last one.
         */
        accent: "border-0 bg-accent text-accent-on hover:bg-accent-hover",
        ink: "border-0 bg-paper-inverse text-ink-inverse hover:bg-ink",
        secondary:
          "border border-rule bg-paper-raised text-ink hover:border-rule-strong hover:bg-paper-sunk",
        ghost: "border-0 bg-transparent text-ink-muted hover:bg-paper-sunk hover:text-ink",
      },
      size: {
        sm: "text-body-sm px-3 py-1.5 font-medium",
        md: "text-label px-4 py-2.5",
        lg: "text-body-lg px-5 py-3 font-medium",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
)

export interface ButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "color">,
    VariantProps<typeof button> {
  /**
   * In-flight action. Disables the button and shows a spinner while keeping
   * the label rendered, so the button does not change width mid-submit and
   * shift the layout around it.
   */
  loading?: boolean
  /** Icon rendered before the label. Decorative: pass `aria-label` if the button has no text. */
  icon?: ReactNode
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, loading, icon, children, disabled, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cn(button({ variant, size }), className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? (
        <CircleNotch className="animate-spin" size={16} aria-hidden />
      ) : icon ? (
        <span className="inline-flex shrink-0" aria-hidden>
          {icon}
        </span>
      ) : null}
      {children}
    </button>
  )
})

/**
 * The variant class recipe on its own, for the cases where the control has to
 * be an `<a>`/`<Link>` rather than a `<button>` and must still look identical.
 *
 * Exported in P3.1 for the 404 screen, whose only way out of a dead end is a
 * navigation. That wants to be a real link — right-clickable, openable in a
 * new tab, announced as a link — and rendering it as a `<button>` with an
 * `onClick` that navigates would take all of that away from the one screen in
 * the product least able to spare it.
 *
 * Use `<Button>` for anything that acts; use this only when the element must
 * genuinely be a link. It carries no `disabled` handling, because a disabled
 * link is not a thing.
 */
export { button as buttonVariants }
