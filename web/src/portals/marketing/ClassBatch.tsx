/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 — design import, part B. */
import type { CSSProperties } from "react"
import { Chip } from "@/components/ui/chip"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import { CountUp } from "@/components/ui/celebration"
import { classBatch } from "./data"
import { useReveal, useRevealSelfClean } from "./motion"

/*
 * `ClassBatch` — design-import-spec.md, "Components to build". A `Table` of
 * six Example scripts, headed with a count that counts up to the fixture's
 * `total` (24) once the block scrolls into view, and rows that deal in on a
 * 75ms stagger.
 *
 * The count-up is gated on `isIn` rather than mounted unconditionally: only
 * render `<CountUp from={0}>` once this block has genuinely entered the
 * viewport, matching `CountUp`'s own rule (`components/ui/celebration.tsx`)
 * that `from` is reserved for a value that arrives while the reader is
 * watching. Before that, the head shows `classBatch.total` as a static
 * pre-reveal number, not "0" — the count-up is a progressive enhancement
 * over the honest total, not a substitute for it, so a reader who never
 * triggers the reveal (a stalled observer, `IntersectionObserver` absent)
 * still sees the true count rather than a page that visibly claims zero
 * scripts above a table of six rows. Under reduced motion, `useReveal`'s
 * `isIn` starts `true` (see motion.tsx), so the count is already 24 on first
 * render — CountUp's own reduced-motion check confirms it rather than
 * animating.
 */
export function ClassBatch() {
  const { ref, className, style, isIn, reduced } = useReveal()
  useRevealSelfClean(ref, isIn, reduced)

  return (
    <div className={className} style={style} ref={ref as never}>
      <div className="batch">
        <div className="batch__head">
          <span className="text-label">
            {classBatch.headPrefix}{" "}
            <span className="batch__count text-data-md">
              {isIn ? <CountUp value={classBatch.total} from={0} /> : classBatch.total}
            </span>{" "}
            {classBatch.headSuffix}
          </span>
          {/* Matches OpenedQuestion's and SchemeExcerpt's own "Example" chip
              — the 18-clean/6-flagged split below is illustrative fixture
              data, not a measured claim, and should say so the same way the
              other two specimens do. */}
          <Chip tone="neutral">Example</Chip>
        </div>
        <Table>
          <THead sticky={false}>
            <TR>
              <TH>Script</TH>
              <TH>Mark</TH>
              <TH>Status</TH>
            </TR>
          </THead>
          <TBody>
            {classBatch.rows.map((row, i) => (
              <TR className="batch__row" key={row.id} style={{ "--i": i } as CSSProperties}>
                <TD className="text-data-sm">{row.id}</TD>
                <TD>
                  <Chip tone="neutral">
                    <span className="text-data-sm">
                      {row.awarded}/{row.available}
                    </span>
                  </Chip>
                </TD>
                <TD>
                  <Chip tone={row.state === "clean" ? "ok" : "err"}>
                    {row.state === "clean" ? "Clean" : "Flagged"}
                  </Chip>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
        <p className="batch__note text-body-sm">{classBatch.note}</p>
      </div>
    </div>
  )
}
