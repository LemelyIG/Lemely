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
  neutral: { icon: "text-t3", bg: "bg-surface-2" },
  warn: { icon: "text-warn", bg: "bg-warn-bg" },
  err: { icon: "text-err", bg: "bg-err-bg" },
}

export function StateView({
  kind,
  icon,
  tone,
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
        "mx-auto flex max-w-sm flex-col items-center gap-3 px-6 py-12 text-center",
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
        <div className="text-body-lg font-medium text-t1">{heading}</div>
        {body ? <p className="text-body-md text-t2">{body}</p> : null}
      </div>
      {action || secondaryAction ? (
        <div className="mt-2 flex items-center gap-2">
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
