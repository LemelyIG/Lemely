/* Hallmark · pre-emit critique: P4 H4 E3 S4 R4 V3 */
import { GhostRows } from "@/components/redesign"

const BLOCK = "bg-surface-container-high"

/* Mirrors HomeScreen's grid (1 / 2 / 3 columns, band with a start border at xl) so nothing shifts on load. */
export function HomeSkeleton() {
  return (
    <div role="status" aria-label="Loading" className="flex flex-col gap-[22px] max-md:pt-3.5">
      <div className="flex gap-2 @[900px]/home:justify-end">
        <span className={`h-8 w-20 rounded-chip ${BLOCK}`} />
        <span className={`h-8 w-36 rounded-chip ${BLOCK}`} />
      </div>
      <div className="flex flex-col gap-[22px] md:grid md:grid-cols-2 md:items-start md:gap-x-9 md:gap-y-6 @[900px]/home:grid-cols-[minmax(0,.95fr)_minmax(0,1.1fr)_minmax(0,.95fr)]">
        <div className="grid justify-items-center gap-3.5 md:pt-2">
          <span className={`size-[150px] rounded-full @[900px]/home:size-[200px] ${BLOCK}`} />
          <span className={`h-6 w-64 max-w-full rounded-bar ${BLOCK}`} />
          <span className={`h-[54px] w-full max-w-[300px] rounded-inner ${BLOCK}`} />
        </div>
        <div className="flex flex-col gap-[22px] md:gap-6 md:pt-4">
          <div className="grid grid-cols-7 gap-1 md:hidden">
            {Array.from({ length: 7 }, (_, i) => (
              <span key={i} className={`mx-auto h-11 w-8 rounded-chip ${BLOCK}`} />
            ))}
          </div>
          <div className="grid grid-cols-3 border-y border-outline-variant py-3.5">
            {[0, 1, 2].map((i) => (
              <span key={i} className={`mx-auto h-11 w-9 rounded-row ${BLOCK}`} />
            ))}
          </div>
          <GhostRows rows={3} announce={false} />
        </div>
        <div
          aria-hidden="true"
          className="hidden gap-x-10 gap-y-6 border-t border-outline-variant pt-6 md:col-span-2 md:grid md:grid-cols-2 @[900px]/home:col-span-1 @[900px]/home:grid-cols-1 @[900px]/home:gap-6 @[900px]/home:border-s @[900px]/home:border-t-0 @[900px]/home:ps-8 @[900px]/home:pt-4"
        >
          <div className="grid content-start gap-2 md:col-span-2 @[900px]/home:col-span-1">
            <span className={`h-4 w-24 rounded-bar ${BLOCK}`} />
            {/* Same container and wrap rule as WeekStrip: a column under 320px wraps to two rows (one 55px row plus 2px gap more). */}
            <div className="@container/week md:max-w-[26rem] @[900px]/home:max-w-none">
              <span className={`block h-[68px] w-full rounded-row @[900px]/home:@max-[319.9px]/week:h-[125px] ${BLOCK}`} />
            </div>
          </div>
          {[0, 1].map((i) => (
            <div key={i} className="grid content-start gap-2">
              <span className={`h-4 w-24 rounded-bar ${BLOCK}`} />
              <span className={`h-11 w-full rounded-row ${BLOCK}`} />
              <span className={`h-11 w-full rounded-row ${BLOCK}`} />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
