import { useState, type ReactNode } from "react"
import { CaretDown, CheckCircle, CircleHalf, XCircle, type Icon } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { MarkDisplay } from "./mark-display"
import { ConfidenceIndicator, type ConfidenceTier } from "./confidence-indicator"

/*
 * C-6 Question row. Question number (in a small boxed mark-scheme-style cell,
 * borrowing the "mark in a small box" exam grammar from DESIGN.md/UI-spec
 * 1.6), marks awarded/available (C-2), correct/partial/wrong state, the
 * per-question confidence chip (C-4 compact variant), and an expand/collapse
 * affordance for question detail.
 *
 * correct/partial/wrong is exactly the kind of state QUALITY-BAR forbids
 * being color-only: each state gets its own icon shape (check / half-circle /
 * cross) on top of the mark-* color tokens, so it survives greyscale.
 */

export type MarkState = "correct" | "partial" | "wrong"

interface StateMeta {
  icon: Icon
  text: string
  label: string
}

const stateMeta: Record<MarkState, StateMeta> = {
  correct: { icon: CheckCircle, text: "text-mark-correct", label: "Correct" },
  partial: { icon: CircleHalf, text: "text-mark-partial", label: "Partial credit" },
  wrong: { icon: XCircle, text: "text-mark-wrong", label: "Incorrect" },
}

export interface QuestionRowProps {
  number: number | string
  awarded: number
  available: number
  state: MarkState
  confidence: ConfidenceTier
  topic?: string
  /** Controlled expand state. Omit to let the row manage its own toggle. */
  expanded?: boolean
  onToggle?: () => void
  /** Detail content rendered when expanded (question stem, working, mark scheme, etc.). */
  children?: ReactNode
  className?: string
}

export function QuestionRow({
  number,
  awarded,
  available,
  state,
  confidence,
  topic,
  expanded,
  onToggle,
  children,
  className,
}: QuestionRowProps) {
  const [internalOpen, setInternalOpen] = useState(false)
  const open = expanded ?? internalOpen
  const meta = stateMeta[state]
  const Icon = meta.icon

  const toggle = onToggle ?? (() => setInternalOpen((o) => !o))

  return (
    <div className={cn("border-b border-border last:border-b-0", className)}>
      <div className="flex items-center gap-3 py-3 px-2 -mx-2">
        {/*
         * The row's toggle is its own button and stops short of the
         * confidence chip, which owns its own tap-to-expand button (C-4) —
         * a button cannot contain another button (invalid HTML, breaks
         * keyboard/AT semantics), so the two controls sit side by side
         * instead of nested.
         */}
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          className={cn(
            "flex-1 min-w-0 flex items-center gap-3 text-left rounded-md cursor-pointer",
            "hover:bg-surface-2 transition-colors",
            "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
          )}
        >
          <span className="font-mono text-metadata w-8 h-8 flex-none flex items-center justify-center border border-border rounded-md text-t2">
            {number}
          </span>
          <Icon weight="fill" className={cn("w-5 h-5 flex-none", meta.text)} aria-hidden />
          <span className="sr-only">{meta.label}.</span>
          <MarkDisplay awarded={awarded} available={available} size="inline" />
          {topic && (
            <span className="hidden sm:inline text-sm text-t3 truncate min-w-0">{topic}</span>
          )}
        </button>
        <span className="ml-auto flex items-center gap-2 flex-none">
          <ConfidenceIndicator tier={confidence} />
          <button
            type="button"
            onClick={toggle}
            aria-expanded={open}
            aria-label={open ? "Collapse question detail" : "Expand question detail"}
            className={cn(
              "p-1.5 rounded-md text-t3 hover:bg-surface-2 hover:text-t2 transition-colors cursor-pointer",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
            )}
          >
            <CaretDown
              className={cn("w-4 h-4 transition-transform", open && "rotate-180")}
              aria-hidden
            />
          </button>
        </span>
      </div>
      {open && children && <div className="pb-4 px-2">{children}</div>}
    </div>
  )
}
