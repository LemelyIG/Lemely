/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { createPortal } from "react-dom"
import {
  CheckCircle,
  Info,
  WarningCircle,
  X,
  type Icon,
} from "@phosphor-icons/react"
import { cn } from "@/lib/utils"

/*
 * Toast primitive + provider. A toast is a transient, non-blocking
 * notification ("Saved", "We couldn't save your changes") — it must never be
 * the only place critical information lives, since it disappears on its own
 * and a screen-reader user who isn't looking at that moment can miss it
 * entirely (mitigated, not solved, by `aria-live`).
 *
 * `role="status"` + `aria-live="polite"` (DESIGN.md §12 gate 8): announces
 * the toast without interrupting whatever the screen reader is already
 * reading, unlike `aria-live="assertive"`/`role="alert"` which would cut in.
 * A polite announcement matches a toast's own non-blocking intent.
 *
 * Auto-dismiss pauses on hover/focus so a reader mid-sentence doesn't have
 * the toast vanish under their cursor — timer math tracks elapsed time
 * across pause/resume cycles rather than just clearing and restarting at
 * full duration, so hovering repeatedly can't keep a toast alive forever
 * through timer resets alone... it can, deliberately: a user actively
 * reading it is exactly who auto-dismiss should defer to.
 */

export type ToastVariant = "default" | "success" | "error" | "info"

export interface ToastOptions {
  title: string
  description?: string
  variant?: ToastVariant
  /** ms before auto-dismiss. `0` disables auto-dismiss (the toast stays
   * until closed). Defaults to 5000. */
  duration?: number
}

interface ToastRecord extends ToastOptions {
  id: string
}

interface ToastContextValue {
  toast: (options: ToastOptions) => string
  dismiss: (id: string) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

/** Read the nearest `ToastProvider`'s `toast`/`dismiss` API. Throws if no
 * provider is mounted, so a missing provider fails loudly at the call site
 * rather than silently swallowing every toast. */
export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) {
    throw new Error("useToast must be used within a ToastProvider")
  }
  return ctx
}

const DEFAULT_DURATION = 5000

const variantMeta: Record<ToastVariant, { icon: Icon; iconClassName: string }> = {
  default: { icon: Info, iconClassName: "text-ink-muted" },
  success: { icon: CheckCircle, iconClassName: "text-ok" },
  error: { icon: WarningCircle, iconClassName: "text-err" },
  info: { icon: Info, iconClassName: "text-info" },
}

let idCounter = 0
function nextId(): string {
  idCounter += 1
  return `toast-${idCounter}`
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastRecord[]>([])

  const dismiss = useCallback((id: string) => {
    setToasts((current) => current.filter((t) => t.id !== id))
  }, [])

  const toast = useCallback((options: ToastOptions) => {
    const id = nextId()
    setToasts((current) => [...current, { id, ...options }])
    return id
  }, [])

  const value = useMemo(() => ({ toast, dismiss }), [toast, dismiss])

  return (
    <ToastContext.Provider value={value}>
      {children}
      {createPortal(
        <div
          className={cn(
            "pointer-events-none fixed end-4 bottom-4 z-toast",
            "flex w-full max-w-sm flex-col gap-2",
          )}
        >
          {toasts.map((record) => (
            <ToastItem key={record.id} record={record} onDismiss={dismiss} />
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  )
}

function ToastItem({
  record,
  onDismiss,
}: {
  record: ToastRecord
  onDismiss: (id: string) => void
}) {
  const duration = record.duration ?? DEFAULT_DURATION

  const remainingRef = useRef(duration)
  const startedAtRef = useRef<number>(Date.now())
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const startTimer = useCallback(
    (ms: number) => {
      clearTimer()
      if (ms <= 0) return
      startedAtRef.current = Date.now()
      timerRef.current = setTimeout(() => onDismiss(record.id), ms)
    },
    [clearTimer, onDismiss, record.id],
  )

  useEffect(() => {
    if (duration > 0) startTimer(duration)
    return clearTimer
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function handlePause() {
    if (duration <= 0) return
    const elapsed = Date.now() - startedAtRef.current
    remainingRef.current = Math.max(0, remainingRef.current - elapsed)
    clearTimer()
  }

  function handleResume() {
    if (duration <= 0) return
    startTimer(remainingRef.current)
  }

  return (
    <ToastCard
      title={record.title}
      description={record.description}
      variant={record.variant}
      onDismiss={() => onDismiss(record.id)}
      onPause={handlePause}
      onResume={handleResume}
    />
  )
}

/**
 * The toast's markup on its own: no timer, no provider, no portal. `ToastItem`
 * above owns the auto-dismiss clock and renders this; the dev-preview kit
 * renders it directly so a toast's copy can be looked at without firing one.
 * `onPause`/`onResume` are the hover/focus hooks that clock needs; a static
 * render simply leaves them off.
 */
export function ToastCard({
  title,
  description,
  variant = "default",
  onDismiss,
  onPause,
  onResume,
}: {
  title: string
  description?: string
  variant?: ToastVariant
  onDismiss: () => void
  onPause?: () => void
  onResume?: () => void
}) {
  const meta = variantMeta[variant]
  const Glyph = meta.icon

  return (
    <div
      role="status"
      aria-live="polite"
      onMouseEnter={onPause}
      onMouseLeave={onResume}
      onFocus={onPause}
      onBlur={onResume}
      className={cn(
        "pointer-events-auto flex items-start gap-2.5 rounded-lg border border-rule bg-paper-raised p-3.5 shadow-[var(--shadow-float)]",
        "motion-safe:animate-[lm-in_var(--dur-base)_var(--ease-spring)_both]",
      )}
    >
      <Glyph
        size={18}
        className={cn("mt-0.5 shrink-0", meta.iconClassName)}
        aria-hidden="true"
      />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <p className="text-body-sm font-medium text-ink">{title}</p>
        {description ? (
          <p className="text-body-sm text-ink-muted">{description}</p>
        ) : null}
      </div>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss notification"
        className={cn(
          "-me-1 -mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ink-faint transition-colors",
          "hover:bg-paper-sunk hover:text-ink",
          "active:scale-[0.98]",
        )}
      >
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  )
}
