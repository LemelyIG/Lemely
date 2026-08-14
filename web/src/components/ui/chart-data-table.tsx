/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { cn } from "@/lib/utils"

/*
 * The visually-hidden data table that stands behind every chart (P6.4).
 *
 * ── Why this exists, and what it replaces ──────────────────────────────────
 *
 * `line-chart.tsx` and `bar-chart.tsx` both asked Nivo for per-datum
 * accessibility (`isFocusable` + `pointAriaLabel`/`barAriaLabel`), and the
 * intent was right: §11 requires exact values, and a tooltip gives them only to
 * a reader who can hover. The implementation Nivo provides for it is not valid,
 * and the audit is unambiguous about why:
 *
 *     <rect ... focusable="true" tabindex="0" aria-label="18 Jul: 0. No XP earned">
 *     <g    ... focusable="true" tabindex="0" aria-label="Aug 8: 82%">
 *
 * `aria-label` is **prohibited** on an element with no role — a bare `<rect>`
 * or `<g>` exposes none — so axe reports `aria-prohibited-attr`, 42 nodes
 * across three routes. The label is not merely invalid, it is *unreliable*:
 * whether it is announced at all is down to how a given screen reader treats an
 * unlabellable SVG shape, so the feature the docstrings claimed was never
 * dependable in the first place. (Nivo emits `aria-label` whenever the prop is
 * passed, independently of `isFocusable` — read off its compiled source, not
 * assumed, because the two look coupled and are not.)
 *
 * **The second half of the problem is one no rule reported.** `student-profile`
 * carried 28 of those nodes, which is 28 sequential tab stops on one XP panel,
 * each announcing one bar. A keyboard reader trying to get past the chart to
 * the content under it pressed Tab 28 times. Making that markup merely *valid*
 * would have kept it.
 *
 * So the per-datum labels are gone from the SVG and the same information is
 * rendered here instead, as a real table: `<caption>`, `<th scope>`, one row
 * per datum. A screen reader user gets table navigation — read a column, jump a
 * row, hear the header with each cell — over the exact values, and a keyboard
 * user gets one tab stop for the whole panel rather than one per bar. The chart
 * keeps `role="img"` and its summary label, which is what makes the SVG a
 * single labelled object rather than an anonymous one.
 *
 * ── Why `sr-only` and not `aria-hidden` on the chart ──────────────────────
 *
 * The table is visually hidden because the chart is the sighted reader's copy
 * of it — two visible renderings of the same numbers is noise, and §11 already
 * requires the tooltip to carry exact values for that reader. It is not
 * `hidden`, and it is not `display: none`: both remove it from the
 * accessibility tree, which is the one place it needs to be.
 */

export interface ChartDataTableProps {
  /**
   * The table's `<caption>`.
   *
   * Callers pass the chart's own `ariaLabel`, so the summary a screen reader
   * hears for the plot and the caption on the data behind it cannot drift
   * apart into two descriptions of one panel.
   */
  caption: string
  /** Column headers, including the leading category/x column. */
  columns: readonly string[]
  /**
   * One array per row, already formatted for reading.
   *
   * Formatting belongs to the caller because the chart's own `formatValue` is
   * what a sighted reader sees on the axis and in the tooltip; a table that
   * formatted numbers its own way would tell two readers of the same panel two
   * different things. Cells are strings for the same reason — there is no
   * second rounding step in here to disagree with the first.
   */
  rows: readonly (readonly string[])[]
  className?: string
}

export function ChartDataTable({ caption, columns, rows, className }: ChartDataTableProps) {
  // An empty series renders nothing rather than a header with no body: a table
  // announcing "0 rows" is worse than absent, and the chart's own empty state
  // (§11) is what speaks for that case.
  if (rows.length === 0) return null

  return (
    <table className={cn("sr-only", className)}>
      <caption>{caption}</caption>
      <thead>
        <tr>
          {columns.map((column, i) => (
            /* `scope="col"` on every header including the first: the leading
               column holds the category (a date, a grade band), so it is a
               column header like any other, and the row headers are marked
               separately below.

               Keyed by index, not by text: two series may legitimately carry
               the same name, and a duplicate key would drop a column. */
            <th key={i} scope="col">
              {column}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, rowIndex) => (
          /* Keyed by index rather than by the row's own label, for the same
             reason as the columns: a category axis may repeat a label (two
             papers marked the same day), and losing one of those rows would
             silently drop a datum from the only copy a screen reader gets. */
          <tr key={rowIndex}>
            {row.map((cell, i) =>
              /* The first cell of each row names the datum, so it is the row's
                 header — that is what lets a screen reader say "18 Jul, 40 XP"
                 when reading the value cell, instead of a bare "40". */
              i === 0 ? (
                <th key={i} scope="row">
                  {cell}
                </th>
              ) : (
                <td key={i}>{cell}</td>
              ),
            )}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
