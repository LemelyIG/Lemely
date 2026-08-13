import {
  forwardRef,
  useCallback,
  useId,
  useRef,
  type ChangeEvent,
  type MutableRefObject,
  type TextareaHTMLAttributes,
} from "react"
import { CircleNotch, WarningCircle } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import type { FieldState } from "@/components/ui/input"

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string
  hint?: string
  error?: string
  state?: FieldState
  wrapperClassName?: string
  labelClassName?: string
  /**
   * Grows the field to fit its content instead of scrolling internally.
   * Off by default: most callers (short comments, single-line-ish answers)
   * want a predictable fixed footprint so a page's layout does not jump as
   * the user types, and `rows` stays the honest contract for that case.
   * Turn it on for genuinely open-ended long-form fields (feedback notes,
   * essay answers) where a scrollbar inside a small box is the worse UX.
   */
  autoResize?: boolean
}

/**
 * Multi-line counterpart to `Input`, same label/hint/error/state contract.
 *
 * `autoResize` is implemented with a plain DOM height reset-then-measure on
 * every change rather than a ResizeObserver or a hidden mirror `<div>`: the
 * field is the only thing whose size changes here, there is no layout it
 * could be observing other than its own scrollHeight, and a mirror element
 * would have to stay in exact sync with the textarea's font/padding/border
 * box or the two silently drift. Resetting to `height: auto` before reading
 * `scrollHeight` is required — skipping it means a shrink (deleting a line)
 * never registers, because the old, taller `scrollHeight` is still cached.
 */
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  {
    label,
    hint,
    error,
    state,
    className,
    wrapperClassName,
    labelClassName,
    id,
    disabled,
    autoResize = false,
    onChange,
    ...props
  },
  ref,
) {
  const generatedId = useId()
  const inputId = id ?? generatedId
  const hintId = hint && !error ? `${inputId}-hint` : undefined
  const errorId = error ? `${inputId}-error` : undefined

  const resolvedState: FieldState | undefined = error ? "error" : state
  const isLoading = resolvedState === "loading"

  const localRef = useRef<HTMLTextAreaElement | null>(null)

  const resize = useCallback((el: HTMLTextAreaElement | null) => {
    if (!el) return
    el.style.height = "auto"
    el.style.height = `${el.scrollHeight}px`
  }, [])

  // Merge the caller's forwarded ref with the local one the resize logic
  // needs, without pulling in a ref-merging dependency for one field.
  const setRefs = useCallback(
    (el: HTMLTextAreaElement | null) => {
      localRef.current = el
      if (typeof ref === "function") ref(el)
      else if (ref) (ref as MutableRefObject<HTMLTextAreaElement | null>).current = el
      if (autoResize) resize(el)
    },
    [ref, autoResize, resize],
  )

  const handleChange = useCallback(
    (event: ChangeEvent<HTMLTextAreaElement>) => {
      if (autoResize) resize(event.currentTarget)
      onChange?.(event)
    },
    [autoResize, resize, onChange],
  )

  return (
    <div className={cn("flex flex-col gap-1.5", wrapperClassName)}>
      <label htmlFor={inputId} className={cn("text-label text-ink", labelClassName)}>
        {label}
      </label>
      <div className="relative">
        <textarea
          ref={setRefs}
          id={inputId}
          disabled={disabled || isLoading}
          aria-invalid={resolvedState === "error" || undefined}
          aria-busy={isLoading || undefined}
          aria-describedby={cn(errorId, hintId) || undefined}
          onChange={handleChange}
          rows={props.rows ?? 4}
          className={cn(
            "w-full rounded-md border bg-paper-raised px-3 py-2 text-body-md text-ink placeholder:text-ink-faint",
            "transition-colors duration-[var(--dur-instant)] ease-out-soft",
            "border-rule hover:border-rule-strong focus-visible:border-rule-strong active:border-rule-strong",
            "disabled:cursor-not-allowed disabled:bg-paper-sunk disabled:text-ink-faint disabled:hover:border-rule",
            autoResize ? "resize-none overflow-hidden" : "resize-y",
            (isLoading || resolvedState === "error") && "pe-9",
            resolvedState === "error" && "border-err hover:border-err focus-visible:border-err",
            resolvedState === "success" && "border-ok hover:border-ok focus-visible:border-ok",
            className,
          )}
          {...props}
        />
        {isLoading ? (
          <CircleNotch
            aria-hidden
            className="pointer-events-none absolute end-3 top-3 h-4 w-4 animate-spin text-ink-faint"
          />
        ) : resolvedState === "error" ? (
          <WarningCircle
            aria-hidden
            weight="regular"
            className="pointer-events-none absolute end-3 top-3 h-4 w-4 text-err"
          />
        ) : null}
      </div>
      {error ? (
        <p id={errorId} className="text-body-sm text-err">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-body-sm text-ink-muted">
          {hint}
        </p>
      ) : null}
    </div>
  )
})
