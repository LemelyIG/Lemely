import { useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { CaretDown, CheckCircle, CircleHalf, XCircle, type Icon } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { MarkDisplay } from "./mark-display"
import { ConfidenceIndicator, type ConfidenceTier } from "./confidence-indicator"
import { Popover } from "./popover"
import { useLongPress } from "@/lib/gestures/useLongPress"

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
  /** Task 6 (B4b): long-press menu item "Practice this topic", a `Link` to
   * the practice generator prefilled with this question's topic. Omitted
   * (the menu item does not render) when the caller cannot build one — a
   * question with no recorded topic has nothing to practice toward. */
  practiceHref?: string
  /** Task 6 (B4b): long-press menu item "Share", wired by the caller (Task
   * 7's `shareResult`). Omitted (the menu item does not render) when the
   * caller has nothing shareable to offer. */
  onShare?: () => void
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
  practiceHref,
  onShare,
}: QuestionRowProps) {
  const [internalOpen, setInternalOpen] = useState(false)
  const open = expanded ?? internalOpen
  const meta = stateMeta[state]
  const Icon = meta.icon

  const toggle = onToggle ?? (() => setInternalOpen((o) => !o))

  // Task 6 (B4b): long-press → secondary actions. `useLongPress`'s own
  // `INTERACTIVE_SELECTOR` already skips a press that starts on the
  // toggle/confidence buttons below, so this never races the row's
  // existing tap targets. Only attached when there is at least one real
  // menu item — a row with neither prop gets no listener at all, not a
  // menu that opens empty.
  const hasMenu = Boolean(practiceHref || onShare)
  const [menuOpen, setMenuOpen] = useState(false)
  const longPress = useLongPress({ onLongPress: () => setMenuOpen(true) })

  return (
    <Popover
      open={hasMenu && menuOpen}
      onOpenChange={setMenuOpen}
      className="block"
      renderTrigger={() => (
        <div
          className={cn("border-b border-border last:border-b-0", className)}
          {...(hasMenu ? longPress : {})}
        >
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
                "flex-1 min-w-0 flex items-center gap-3 text-start rounded-md cursor-pointer",
                "hover:bg-surface-2 active:scale-[0.98] transition-[background-color,transform]",
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
            <span className="ms-auto flex items-center gap-2 flex-none">
              <ConfidenceIndicator tier={confidence} />
              <button
                type="button"
                onClick={toggle}
                aria-expanded={open}
                aria-label={open ? "Collapse question detail" : "Expand question detail"}
                className={cn(
                  "p-1.5 rounded-md text-t3 hover:bg-surface-2 hover:text-t2 active:scale-[0.98] transition-[background-color,color,transform] cursor-pointer",
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
      )}
    >
      {practiceHref ? (
        <Link
          to={practiceHref}
          onClick={() => setMenuOpen(false)}
          className="block rounded-md px-3 py-2 text-body-sm text-ink transition-[background-color,transform] hover:bg-paper-sunk active:scale-[0.98]"
        >
          Practice this topic
        </Link>
      ) : null}
      {onShare ? (
        <button
          type="button"
          onClick={() => {
            setMenuOpen(false)
            onShare()
          }}
          className="block w-full rounded-md px-3 py-2 text-start text-body-sm text-ink transition-[background-color,transform] hover:bg-paper-sunk active:scale-[0.98]"
        >
          Share
        </button>
      ) : null}
    </Popover>
  )
}
