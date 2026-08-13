import type {
  HTMLAttributes,
  KeyboardEvent as ReactKeyboardEvent,
  TdHTMLAttributes,
  ThHTMLAttributes,
} from "react"
import { cn } from "@/lib/utils"

/*
 * DESIGN.md §12 "Tables": `--paper-sunk` header, `--rule` row dividers,
 * tabular-nums on every numeric column, right-aligned numbers, sticky header
 * at `z-sticky`. This file is the primitive layer only — `Table`/`THead`/
 * `TBody`/`TR`/`TH`/`TD` compose into a real table the way a screen needs it
 * (marks grids, class rosters, paper listings); it does not know about
 * pagination, sorting, or virtualisation.
 *
 * Numbers use `text-data-md` rather than relying on the caller to remember
 * the mono/tabular face (§3 gate: "every number uses a `text-data-*` class").
 * A caller only has to pass `numeric`, never re-derive the right type class
 * per cell, which is also what keeps a column of marks visually aligned
 * without every screen re-deciding it.
 */

/**
 * Scroll container + `<table>` root. The wrapper (not the `<table>` itself)
 * owns the border/radius/surface, because `border-collapse` on the table
 * would otherwise clip a rounded corner against the header row's own border.
 * `overflow-x-auto` is what keeps a wide marks grid usable on a phone without
 * the page itself scrolling horizontally (index.css's `overflow-x: clip` on
 * `html body` depends on every scrollable region containing its own scroll).
 */
export function Table({ className, children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "w-full overflow-x-auto rounded-lg border border-rule bg-paper-raised",
        className,
      )}
      {...props}
    >
      <table className="w-full border-collapse text-start">{children}</table>
    </div>
  )
}

/**
 * Header group. Sticky by default (`position: sticky; top: 0`) at `z-sticky`
 * so a long marks grid keeps its column headings visible while scrolling —
 * turn it off for a table that always renders short enough to not need it,
 * since a sticky header inside a component that is itself inside a scroll
 * container can otherwise stick to the wrong ancestor.
 */
export function THead({
  className,
  sticky = true,
  ...props
}: HTMLAttributes<HTMLTableSectionElement> & {
  /** Defaults to true. Set false when this table never scrolls under its own
   * header (e.g. always short, or already inside a scrolling panel with its
   * own sticky header). */
  sticky?: boolean
}) {
  return (
    <thead
      className={cn(
        "bg-paper-sunk",
        sticky && "sticky top-0 z-[var(--z-index-sticky)]",
        className,
      )}
      {...props}
    />
  )
}

/** Body group. No styling of its own; row dividers live on `TR` so a `TBody`
 * can be swapped for a `SkeletonBlock`-filled placeholder without carrying
 * divider logic along with it. */
export function TBody(props: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody {...props} />
}

export interface TRProps extends HTMLAttributes<HTMLTableRowElement> {
  /** Marks this row as the current selection (e.g. the paper being reviewed).
   * Uses the accent wash rather than a border, so a selected row reads as
   * "highlighted" and not as "in an error state". */
  selected?: boolean
  /** Row cannot be interacted with. Dims the row and blocks pointer events;
   * `onClick`, if supplied, is not wired up while disabled. */
  disabled?: boolean
}

/**
 * Row. Hairline divider on every row per §12 ("`--rule` row dividers"), plus
 * the four interactive states (hover, focus-visible, active, disabled) when
 * `onClick` is supplied — a static data row has no hover/focus/active state
 * because nothing happens when you point at or press it, so those are only
 * wired up for a genuinely clickable row (e.g. "open this paper").
 */
export function TR({ className, selected, disabled, onClick, onKeyDown, ...props }: TRProps) {
  const interactive = Boolean(onClick) && !disabled

  function handleKeyDown(event: ReactKeyboardEvent<HTMLTableRowElement>) {
    onKeyDown?.(event)
    if (!interactive || event.defaultPrevented) return
    // Native <tr> has no built-in activation key; Enter/Space are the two a
    // keyboard user expects from anything carrying role="button"-like intent.
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      ;(onClick as unknown as (e: typeof event) => void)(event)
    }
  }

  return (
    <tr
      className={cn(
        "border-b border-rule last:border-b-0",
        interactive &&
          cn(
            "cursor-pointer transition-colors duration-[var(--dur-instant)] ease-out-soft",
            "hover:bg-paper-sunk/60 active:bg-paper-sunk",
            "focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-focus-ring",
          ),
        selected && "bg-accent-wash hover:bg-accent-wash",
        disabled && "pointer-events-none opacity-50",
        className,
      )}
      onClick={disabled ? undefined : onClick}
      onKeyDown={interactive ? handleKeyDown : onKeyDown}
      tabIndex={interactive ? 0 : undefined}
      role={interactive ? "button" : undefined}
      aria-disabled={disabled || undefined}
      aria-selected={selected || undefined}
      {...props}
    />
  )
}

export interface THProps extends ThHTMLAttributes<HTMLTableCellElement> {
  /** Right-aligns the header and marks it tabular, so a numeric column's
   * heading sits directly above the digits it labels rather than the label
   * text's own (shorter) width. Does not switch to the mono data face — the
   * heading is a word ("Marks"), not a number, and setting it in
   * `text-data-*` would read as a typo of the column's actual values. */
  numeric?: boolean
}

/** Header cell. `text-eyebrow` matches the tracked-uppercase label register
 * used for every other column/section heading in the product. */
export function TH({ className, numeric, scope = "col", ...props }: THProps) {
  return (
    <th
      scope={scope}
      className={cn(
        "whitespace-nowrap px-4 py-3 text-eyebrow text-ink-muted",
        numeric ? "text-end tabular-nums" : "text-start",
        className,
      )}
      {...props}
    />
  )
}

export interface TDProps extends TdHTMLAttributes<HTMLTableCellElement> {
  /** Right-aligns the cell and renders its contents in `text-data-md`
   * (JetBrains Mono, tabular-nums), so every numeric column in the product
   * gets the "column of marks always aligns, a counting score never
   * jitters" guarantee by construction rather than by the caller
   * remembering to wrap the value themselves. */
  numeric?: boolean
}

/** Data cell. */
export function TD({ className, numeric, children, ...props }: TDProps) {
  return (
    <td
      className={cn(
        "px-4 py-3 text-body-md text-ink",
        numeric ? "text-end text-data-md" : "text-start",
        className,
      )}
      {...props}
    >
      {children}
    </td>
  )
}
