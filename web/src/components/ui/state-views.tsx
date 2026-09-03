/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import type { HTMLAttributes, ReactNode } from "react"
import { Tray, WarningCircle, WifiSlash, type Icon } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { PageHeaderSkeleton, ListSkeleton, PanelSkeleton } from "@/components/ui/loading-shapes"
import { FullPageState, FullPageStateBody } from "@/portals/misc/FullPageState"

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
 *
 * ── The merge with `error-state.tsx` (loading/error primitives PR) ─────────
 *
 * The product carried two `ErrorState`s: this file's (amber default, `heading`
 * `/body`/`action`, product-wide) and a second, unimported one in
 * `error-state.tsx` (red-only, `title`/`message`/`onRetry`) that only the kit
 * preview page rendered. The decision is one component, this one, amber
 * default per PRODUCT.md's "avoid red-heavy error states." Two things from the
 * old file were real and worth keeping rather than losing at the merge:
 *
 *   - **`compact`**, a small inline slot for a single form field or table
 *     cell — 16px icon, tight padding, left-aligned, tone-wash background —
 *     rather than the centred full-panel treatment every other `kind` here
 *     uses. Its retry is an underlined text button, not `<Button>`: a filled
 *     button reads as too heavy a control for a cell-sized failure.
 *   - **`children`**, a trailing slot after the actions for a call site that
 *     needs to append something (a diagnostic id, a secondary link) the fixed
 *     prop set does not model.
 *
 * The old file's central rule about copy carries over unchanged: no default
 * `heading`, ever. A component that falls back to "Something went wrong" on
 * a missing prop teaches call sites to omit the one sentence a reader actually
 * needed, and every empty/error/offline panel in the product has to say what
 * specifically happened or specifically isn't here.
 *
 * `role` is new: `kind="error"` is `role="alert"` (an assertive live region —
 * a failure a reader did not cause and needs to hear about promptly) and
 * `kind="offline"` is `role="status"` (polite — connectivity dropping is a
 * fact of the moment, not an event to interrupt over). `kind="empty"` gets
 * neither; there is nothing to announce about content that was never going to
 * exist.
 *
 * `compact` narrows `kind="error"` to `role="status"` instead: `lazy-chart.tsx`
 * renders one `compact` `ErrorState` per failed chart, and a dashboard with
 * three broken panels would otherwise interrupt the reader three times with
 * `alert`'s assertive announcement for what is, from a single chart's own
 * layout box, a much smaller failure than a whole panel refusing to load. The
 * full, centred layout keeps `alert` — that one is always the reader's whole
 * reason for being on the page.
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
  /** Small inline slot for a single field or table cell instead of the
   * centred full panel: 16px icon, tight `px-3 py-2.5` padding, left-aligned,
   * tone-wash background. `action` renders as an underlined text button
   * rather than `<Button>` — a filled button is too heavy a control for a
   * cell-sized failure. Ported from the pre-merge `error-state.tsx`. */
  compact?: boolean
  className?: string
  /** Trailing slot after the actions, for anything the fixed prop set does
   * not model (a diagnostic id, a secondary link). */
  children?: ReactNode
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
  compact = false,
  className,
  children,
  ...props
}: StateViewProps) {
  const defaults = kindDefaults[kind]
  const resolvedTone = tone ?? defaults.tone
  const toneCls = toneClasses[resolvedTone]
  const Glyph = defaults.icon
  // `role` is computed from `kind`, not hardcoded per call site, so every
  // error panel in the product is announced the same way without every
  // screen having to remember to ask for it. `{...props}` still spreads after
  // this, so an unusual caller can override it via the ordinary HTML prop.
  // `compact` error is `status`, not `alert` — see the module header: three
  // `compact` chart fallbacks on one dashboard must not interrupt three times.
  const regionRole =
    kind === "error"
      ? compact
        ? "status"
        : "alert"
      : kind === "offline"
        ? "status"
        : undefined

  if (compact) {
    return (
      <div
        role={regionRole}
        className={cn(
          "flex items-start gap-2 rounded-md border border-rule px-3 py-2.5",
          toneCls.bg,
          className,
        )}
        {...props}
      >
        <div className="mt-0.5 shrink-0">
          {icon ?? <Glyph size={16} className={toneCls.icon} aria-hidden="true" />}
        </div>
        <div className="flex min-w-0 flex-col gap-1">
          {marginalia ? <p className="text-hand text-ink-muted">{marginalia}</p> : null}
          <p className="text-body-sm font-medium text-ink">{heading}</p>
          {body ? <p className="text-body-sm text-ink-muted">{body}</p> : null}
          {action || secondaryAction ? (
            <div className="mt-0.5 flex flex-wrap items-center gap-3">
              {action ? (
                <button
                  type="button"
                  onClick={action.onClick}
                  className={cn(
                    "self-start text-label text-accent-ink underline decoration-1 underline-offset-2 transition-colors",
                    "hover:text-accent-hover",
                  )}
                >
                  {action.label}
                </button>
              ) : null}
              {secondaryAction ? (
                <button
                  type="button"
                  onClick={secondaryAction.onClick}
                  className={cn(
                    "self-start text-label text-ink-muted underline decoration-1 underline-offset-2 transition-colors",
                    "hover:text-ink",
                  )}
                >
                  {secondaryAction.label}
                </button>
              ) : null}
            </div>
          ) : null}
          {children}
        </div>
      </div>
    )
  }

  return (
    <div
      role={regionRole}
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
      {children}
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
 * Route-chunk fallback (P6.1b -> PR 2 part B, the tier system). Deliberately
 * NOT a `StateView`: those three are terminal answers about the *data* ("there
 * is nothing here", "this failed"), with an icon, a heading and actions. This
 * is a wait for a lazy route chunk, which can be anywhere from imperceptible
 * to genuinely stuck, and DESIGN.md §12 gives it three tiers rather than one
 * "Loading…" line:
 *
 *   1. 0 to `--loading-tier-skeleton` (200ms): nothing visible. The old
 *      reasoning here — "a sub-second gap should not flash a heading" — still
 *      holds, and is now enforced by the delay itself rather than by a
 *      developer remembering to keep this component quiet: `role="status"`
 *      plus a visually hidden "Loading" is present from the first frame, so a
 *      screen-reader user hears something immediately even while sighted
 *      readers see nothing. Both `.lm-tier-skeleton` and `.lm-tier-slow`
 *      (tiers 2 and 3) also carry `visibility: hidden` until their own delay
 *      elapses (the `lm-appear` keyframe in index.css), so tier 3's heading
 *      and reload button are genuinely absent from the accessibility tree
 *      and the tab order during this window, not merely invisible —
 *      `opacity: 0` alone removes neither.
 *   2. `--loading-tier-skeleton` to `--loading-tier-slow` (5s): a skeleton
 *      matching the layout being waited for.
 *   3. after `--loading-tier-slow`: the brand mark drawing itself, "Still
 *      loading", and a reload button (`FullPageState`/`FullPageStateBody`,
 *      `variant="slow-load"`) — the point at which "still on its way" stops
 *      being the honest read and "tell the reader, offer a way out" starts.
 *
 * Both delays are CSS (`.lm-tier-skeleton`/`.lm-tier-slow` in index.css), not
 * a JS timer: see that file's comment for the zero-duration-animation-plus-
 * delay trick, which is also what stages the pre-mount shell in index.html
 * before this component's own JS has even downloaded.
 *
 * `frame` replaces the old bare `className`-only signature: the two shapes of
 * call site need genuinely different tier-2 content, not just different
 * spacing.
 *   - `"content"` (default) is the portal-boundary case this component always
 *     handled: a lazy screen loading inside an already-painted sidebar and
 *     header. Its tier-2 skeleton is the generic content-well shape almost
 *     every dashboard opens with — `PageHeaderSkeleton`, a three-row
 *     `ListSkeleton`, a two-up row of `PanelSkeleton`s — the same geometry
 *     `Overview.tsx` composes by hand for its own real loading state.
 *   - `"standalone"` is the top-level routes in `routes.tsx`: sign-in,
 *     sign-up, verify-email, reset, join, settings. No tier-2 skeleton at
 *     all — these are small forms with no chrome to promise, and a sidebar
 *     skeleton there would promise structure that never arrives. The
 *     pre-mount shell already covered the very first paint for these paths
 *     too (as "paper only", since they are not portal paths — see
 *     `preMountShell.ts`), so there is nothing tier 2 needs to add.
 *
 * It lives here rather than being redeclared in each router file because
 * Phase 2.5 fixed the rule that cross-cutting UI is composed from this library,
 * not re-invented per call site — four verbatim copies is how a "loading" state
 * drifts into four slightly different ones.
 *
 * Tier 2 and tier 3 occupy the same CSS grid cell (`col-start-1 row-start-1`)
 * rather than each running its own exit animation: `.lm-tier-slow`'s child
 * carries a `bg-paper`, so once it fades in at 5s it simply paints over
 * whatever tier 2 rendered underneath, in source order. That is one keyframe
 * (`lm-appear`, shared by both classes) instead of two, and no coordination
 * needed between a tier arriving and a previous one leaving — the simpler of
 * the two mechanisms DESIGN.md's brief allows, chosen over a second
 * `lm-vanish` keyframe for that reason.
 *
 * `className` still exists for the call sites that pass their own spacing
 * (`p-8`, dense-surface type). It lands on the outer `role="status"` grid, so
 * on `frame="standalone"` — where tier 2 renders nothing — it is mostly
 * padding around tier 3's own `FullPageState`, which already manages its own
 * `min-h-screen` layout; kept anyway so every existing call site keeps
 * compiling with no other change than the new `frame` prop.
 */
export function RouteFallback({
  className,
  frame = "content",
}: {
  className?: string
  frame?: "content" | "standalone"
}) {
  return (
    <div role="status" className={cn("grid", className)}>
      <span className="sr-only">Loading</span>
      <div
        aria-hidden="true"
        className="lm-tier-skeleton col-start-1 row-start-1 flex flex-col gap-8"
      >
        {frame === "content" ? (
          <>
            <PageHeaderSkeleton />
            <ListSkeleton rows={3} />
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <PanelSkeleton />
              <PanelSkeleton />
            </div>
          </>
        ) : null}
      </div>
      <div className="lm-tier-slow col-start-1 row-start-1 bg-paper">
        {frame === "content" ? (
          // `FullPageStateBody` has no `frame` prop — it is the frameless
          // content `FullPageState`'s own `frame="portal"` branch wraps in
          // exactly this container; reproduced here rather than adding a
          // `frame` prop to a component another PR owns.
          <div className="mx-auto flex w-full max-w-md flex-col items-center justify-center gap-6 py-12 text-center">
            <FullPageStateBody variant="slow-load" />
          </div>
        ) : (
          <FullPageState variant="slow-load" frame="standalone" />
        )}
      </div>
    </div>
  )
}
