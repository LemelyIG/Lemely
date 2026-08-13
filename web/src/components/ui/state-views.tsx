/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V3 */
import type { HTMLAttributes, ReactNode } from "react"
import { Tray, WarningCircle, WifiSlash, type Icon } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

/*
 * C-11 · Empty / error / offline state family (G-15, S-06 first-run, S-09
 * empty, T-07 empty queue, etc.) — one shared layout (icon slot, heading,
 * body, up to two actions) documented with three named wrappers around a
 * single `StateView` primitive, so every empty/error/offline panel in the
 * product looks like the same designed thing rather than three one-offs.
 *
 * Tone: PRODUCT.md's accessibility section is explicit — "avoid red-heavy
 * error states; prefer amber/neutral for 'needs attention'" — so the
 * `error` kind defaults to the warn (amber) token, not err (red). `err` is
 * still available via the `tone` override for a caller that genuinely needs
 * it (e.g. a destructive/blocking failure), but nothing here defaults to it.
 *
 * P4.2 moved the colour names off the build-era `text-t1`/`bg-surface-2`
 * aliases onto the names DESIGN.md defines (identical values), and added the
 * optional `marginalia` line. §12 is specific about what an empty state is
 * made of — "a line of Caveat marginalia, a one-sentence explanation, and the
 * action that fills it" — and this component had the second and third and no
 * way to supply the first, which is why `ChartFrame` grew its own
 * `emptyMarginalia` rather than reusing this. It is optional, not defaulted:
 * per §4.1 Caveat decorates and never carries, so a state view without one is
 * still complete, and a generic default ("Nothing here yet") on every empty
 * state in the product would be decoration pretending to be voice.
 */

export type StateViewKind = "empty" | "error" | "offline"
export type StateViewTone = "neutral" | "warn" | "err"

export interface StateViewAction {
  label: string
  onClick: () => void
}

export interface StateViewProps extends HTMLAttributes<HTMLDivElement> {
  kind: StateViewKind
  /** Override the default icon for this kind. */
  icon?: ReactNode
  /** Override the default tone (icon/badge color) for this kind. */
  tone?: StateViewTone
  /** Optional Caveat line above the heading (§12). Decorative: never put
   * anything here that the reader would lose by not seeing it (§4.1). */
  marginalia?: string
  heading: string
  body?: string
  action?: StateViewAction
  secondaryAction?: StateViewAction
  className?: string
}

const kindDefaults: Record<StateViewKind, { icon: Icon; tone: StateViewTone }> = {
  empty: { icon: Tray, tone: "neutral" },
  error: { icon: WarningCircle, tone: "warn" },
  offline: { icon: WifiSlash, tone: "neutral" },
}

const toneClasses: Record<StateViewTone, { icon: string; bg: string }> = {
  neutral: { icon: "text-ink-faint", bg: "bg-paper-sunk" },
  warn: { icon: "text-warn", bg: "bg-warn-wash" },
  err: { icon: "text-err", bg: "bg-err-wash" },
}

export function StateView({
  kind,
  icon,
  tone,
  marginalia,
  heading,
  body,
  action,
  secondaryAction,
  className,
  ...props
}: StateViewProps) {
  const defaults = kindDefaults[kind]
  const resolvedTone = tone ?? defaults.tone
  const toneCls = toneClasses[resolvedTone]
  const Glyph = defaults.icon

  return (
    <div
      className={cn(
        // `w-full` is load-bearing, not decoration: `max-w-sm` alone leaves the
        // box its intrinsic 384px, which is wider than the 380px breakpoint the
        // responsive gate checks, so every state view overflowed on the
        // narrowest phone.
        "mx-auto flex w-full max-w-sm flex-col items-center gap-3 px-6 py-12 text-center",
        className,
      )}
      {...props}
    >
      <div
        className={cn(
          "flex h-12 w-12 items-center justify-center rounded-full",
          toneCls.bg,
        )}
      >
        {icon ?? <Glyph size={22} className={toneCls.icon} />}
      </div>
      <div className="flex flex-col gap-1.5">
        {marginalia ? <p className="text-hand text-ink-muted">{marginalia}</p> : null}
        <div className="text-body-lg font-medium text-ink">{heading}</div>
        {body ? <p className="text-body-md text-ink-muted">{body}</p> : null}
      </div>
      {action || secondaryAction ? (
        // Two actions with `whitespace-nowrap` labels ("Take the placement
        // test" + "Rebuild this week's plan") cannot sit side by side at 380px.
        // Wrapping is the honest fix; truncating would hide what the button does.
        <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
          {action ? (
            <Button variant="accent" size="sm" onClick={action.onClick}>
              {action.label}
            </Button>
          ) : null}
          {secondaryAction ? (
            <Button variant="ghost" size="sm" onClick={secondaryAction.onClick}>
              {secondaryAction.label}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

export function EmptyState(props: Omit<StateViewProps, "kind">) {
  return <StateView kind="empty" {...props} />
}

export function ErrorState(props: Omit<StateViewProps, "kind">) {
  return <StateView kind="error" {...props} />
}

export function OfflineState(props: Omit<StateViewProps, "kind">) {
  return <StateView kind="offline" {...props} />
}

/*
 * Route-chunk fallback (P6.1b). Deliberately NOT a `StateView`: those three are
 * terminal answers about the *data* ("there is nothing here", "this failed"),
 * with an icon, a heading and actions. This is a sub-second gap while a lazy
 * route chunk downloads, and dressing that up as a full panel makes a fast
 * navigation flash a heading the reader never needed to read.
 *
 * It lives here rather than being redeclared in each router file because
 * Phase 2.5 fixed the rule that cross-cutting UI is composed from this library,
 * not re-invented per call site — four verbatim copies is how a "loading" state
 * drifts into four slightly different ones.
 *
 * `role="status"` (an aria-live polite region) rather than silence: without it
 * a screen-reader user navigating to a lazily-loaded route hears nothing at all
 * between activating the link and the screen arriving.
 *
 * `className` exists because the call sites genuinely differ: the portal
 * boundaries render inside a padded content area and on dense surfaces
 * (`text-dense-lg`), while the top-level routes in `App.tsx` have no layout
 * around them and supply their own padding. That is one component with a
 * documented override, not four components — `cn` is tailwind-merge-backed and
 * knows our type-scale classes are font-sizes, so a passed `text-*` correctly
 * replaces the default rather than stacking with it.
 */
export function RouteFallback({ className }: { className?: string }) {
  return (
    <div role="status" className={cn("text-body-md text-ink-muted", className)}>
      Loading…
    </div>
  )
}
