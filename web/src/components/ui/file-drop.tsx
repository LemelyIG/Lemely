/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useCallback, useId, useRef, useState, type DragEvent, type ReactNode } from "react"
import { CheckCircle, FilePlus, WarningCircle } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

/*
 * C-21 · File drop — a labelled drop target that is also a real file input.
 *
 * Built in P4.2 (Phase 4, surface 2) for the correct-a-paper flow, whose own
 * page copy has said "Scan or drop the paper" since the build era while the
 * screen offered a bare `<input type="file">` and no drop target of any kind.
 * That is the same class of defect the redesign keeps turning up — a sentence
 * describing a product that was never built — and it is fixed here rather than
 * by deleting the promise, because dropping a scan is genuinely the fastest
 * path on the desktop half of this flow.
 *
 * WHAT MAKES THIS ACCESSIBLE RATHER THAN A STYLED DIV.
 * The interactive element is the `<input type="file">` itself, visually hidden
 * but focusable, with a real `<label>` bound to it. Keyboard users tab to a
 * control that announces its own name and opens the native picker on Enter or
 * Space; screen-reader users get the label, the hint, and any error through
 * `aria-describedby`. Drag-and-drop is layered on top as a pointer-only
 * enhancement, which is the correct direction: a drop zone that is only a drop
 * zone is unusable without a mouse, and phones cannot drop at all.
 *
 * The focus ring is drawn on the *label* via `peer-focus-visible`, because the
 * input it belongs to is the thing that is hidden. Without that, focus moves
 * into this control and disappears — DESIGN.md §3.9 ("never removed, on any
 * element, for any reason").
 *
 * The eight states (§12, gate 4):
 *   default          hairline rule on paper-raised
 *   hover            rule firms to `--rule-strong`
 *   focus-visible    blue focus ring on the label, from the peer input
 *   active           `dragging` — accent rule + accent wash while a file is over it
 *   disabled         dimmed, pointer-events off, input disabled
 *   loading          `busy` — dimmed and non-interactive while the caller works
 *   error            `--err` rule and message, wired to `aria-describedby`
 *   success          `selected` — a named file, an ok glyph, and a way to replace it
 */

export interface FileDropProps {
  /** Stable id for the input. One is generated when omitted. */
  id?: string
  /** Visible label. Always rendered: never placeholder-as-label (§12). */
  label: string
  /** Short qualifier beside the label, e.g. "required" or "optional". */
  labelNote?: string
  /** `accept` for the underlying input, e.g. "application/pdf,image/*". */
  accept?: string
  /** The currently chosen file, or null. This component is controlled. */
  file: File | null
  onFileChange: (file: File | null) => void
  /** Helper text under the control, shown when there is no error. */
  hint?: ReactNode
  /** Inline, field-adjacent error (§12). Replaces `hint` while set. */
  error?: string | null
  disabled?: boolean
  /** In-flight: the caller is working and the control must not change. */
  busy?: boolean
  /** Label for the button that clears a chosen file. */
  clearLabel?: string
  /**
   * Density. `compact` is a shorter target with a single line of prompt copy,
   * for a field that is genuinely secondary — an optional upload sitting under
   * a required one. Two identically-sized drop zones stacked give a reader no
   * way to see which one the screen actually needs, which is what the first
   * capture round of the correct-a-paper surface showed.
   */
  size?: "default" | "compact"
  /** Overrides the prompt line, e.g. "Drop the official scheme here". */
  prompt?: string
  className?: string
}

/** Human file size. Kept to one decimal so a 1.5 MB scan does not read "2 MB". */
export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return ""
  if (bytes < 1024) return `${bytes} B`
  const kb = bytes / 1024
  if (kb < 1024) return `${Math.round(kb)} KB`
  return `${(kb / 1024).toFixed(1)} MB`
}

export function FileDrop({
  id,
  label,
  labelNote,
  accept,
  file,
  onFileChange,
  hint,
  error,
  disabled = false,
  busy = false,
  clearLabel = "Choose a different file",
  size = "default",
  prompt = "Drop a file here, or choose one",
  className,
}: FileDropProps) {
  const generatedId = useId()
  const inputId = id ?? generatedId
  const describedById = `${inputId}-description`
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  const locked = disabled || busy
  const hasError = Boolean(error)
  const glyph = size === "compact" ? 20 : 24

  /*
   * `dragenter`/`dragover` fire continuously and on every descendant, so the
   * flag is set rather than toggled, and `dragleave` is only honoured when the
   * pointer has actually left the container — `relatedTarget` is the element
   * being entered, so a move from the label onto its own icon reports a leave
   * that must be ignored. Without that check the accent wash flickers on every
   * pixel of movement inside the zone.
   */
  const onDragOver = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      if (locked) return
      event.preventDefault()
      setDragging(true)
    },
    [locked],
  )

  const onDragLeave = useCallback((event: DragEvent<HTMLDivElement>) => {
    const next = event.relatedTarget
    if (next instanceof Node && event.currentTarget.contains(next)) return
    setDragging(false)
  }, [])

  const onDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      if (locked) return
      event.preventDefault()
      setDragging(false)
      const dropped = event.dataTransfer?.files?.[0]
      if (dropped) onFileChange(dropped)
    },
    [locked, onFileChange],
  )

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="flex items-baseline gap-2">
        <label htmlFor={inputId} className="text-label text-ink">
          {label}
        </label>
        {labelNote ? <span className="text-body-sm text-ink-faint">{labelNote}</span> : null}
      </div>

      <div
        onDragEnter={onDragOver}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        className={cn(
          "relative rounded-lg border border-dashed transition-colors",
          "duration-[var(--dur-instant)] ease-out-soft",
          locked
            ? "cursor-not-allowed border-rule bg-paper-raised opacity-60"
            : dragging
              ? "border-accent bg-accent-wash"
              : hasError
                ? "border-err bg-paper-raised hover:border-err"
                : file
                  ? "border-rule-strong bg-paper-raised"
                  : "border-rule bg-paper-raised hover:border-rule-strong hover:bg-paper-sunk",
        )}
      >
        {/*
         * Visually hidden, NOT `display:none` and NOT `hidden`: either of
         * those removes the input from the tab order, which would make the
         * only way to reach this control a mouse drag. `sr-only` keeps it
         * focusable, and `peer` lets the label below draw the focus ring for
         * it.
         */}
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          accept={accept}
          disabled={locked}
          aria-describedby={hint || error ? describedById : undefined}
          aria-invalid={hasError || undefined}
          className="peer sr-only"
          onChange={(event) => onFileChange(event.target.files?.[0] ?? null)}
        />

        <label
          htmlFor={inputId}
          className={cn(
            "flex flex-col items-center gap-2 rounded-lg text-center",
            size === "compact" ? "px-4 py-4" : "px-6 py-8",
            "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2",
            "peer-focus-visible:outline-focus-ring",
            locked ? "cursor-not-allowed" : "cursor-pointer",
          )}
        >
          {file ? (
            <CheckCircle size={glyph} weight="fill" className="text-ok" aria-hidden="true" />
          ) : hasError ? (
            <WarningCircle size={glyph} className="text-err" aria-hidden="true" />
          ) : (
            <FilePlus size={glyph} className="text-ink-faint" aria-hidden="true" />
          )}

          {file ? (
            <span className="flex flex-col items-center gap-0.5">
              <span className="max-w-full truncate text-body-md font-medium text-ink">
                {file.name}
              </span>
              <span className="text-data-sm text-ink-faint">{formatFileSize(file.size)}</span>
            </span>
          ) : (
            <span className="flex flex-col items-center gap-0.5">
              {/* Not a claim about the drop target on a phone, where there is
                  nothing to drop from: the prompt offers the picker as the
                  equal path rather than the fallback. */}
              <span
                className={
                  size === "compact"
                    ? "text-body-sm text-ink-muted"
                    : "text-body-md font-medium text-ink"
                }
              >
                {prompt}
              </span>
              {size === "compact" ? null : (
                <span className="text-body-sm text-ink-muted">PDF or photo</span>
              )}
            </span>
          )}
        </label>

        {file && !locked ? (
          <div className="flex justify-center border-t border-rule px-4 py-3">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                onFileChange(null)
                // The native input keeps its own value, so re-picking the same
                // file after clearing would fire no `change` event at all.
                if (inputRef.current) inputRef.current.value = ""
              }}
            >
              {clearLabel}
            </Button>
          </div>
        ) : null}
      </div>

      {error ? (
        <p id={describedById} className="text-body-sm text-err">
          {error}
        </p>
      ) : hint ? (
        <p id={describedById} className="text-body-sm text-ink-muted">
          {hint}
        </p>
      ) : null}
    </div>
  )
}
