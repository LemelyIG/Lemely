/* Hallmark · pre-emit critique: P3 H3 E4 S3 R4 V3 */
import { GhostRows } from "@/components/redesign"

const BLOCK = "bg-surface-container-high"

/* MeScreen's own column and order classes, so the skeleton splits into the same two columns at md and keeps the phone order. */
const GRID = "flex flex-col gap-[22px] md:grid md:grid-cols-2 md:items-start md:gap-12"
const COL = "contents md:flex md:min-w-0 md:flex-col md:gap-[18px]"

/** A section heading's slot: the same height as the loaded h2 (py-1 around an 18px line), so the rows below start where the real ones do. */
function Heading({ className }: { className?: string }) {
  return (
    <div className={`flex h-[35px] items-center ${className ?? ""}`}>
      <span className={`h-5 w-28 rounded-bar ${BLOCK}`} />
    </div>
  )
}

/**
 * Mirrors MeScreen's loaded layout: hero, streak strip, stats, badges and subjects in the first column; people,
 * activity and account in the second. Heights come from the loaded components' own sizes, so content swaps in
 * without a jump. One status region announces "Loading"; everything inside is silent.
 */
export function MeSkeleton() {
  return (
    <div role="status" aria-label="Loading" className={GRID}>
      <div className={COL}>
        <div className="order-1 flex items-center gap-3.5 md:order-none">
          <span className={`size-[92px] flex-none rounded-full ${BLOCK}`} />
          <span className="grid flex-1 gap-2">
            <span className={`h-8 w-40 max-w-full rounded-bar ${BLOCK}`} />
            <span className={`h-4 w-48 max-w-full rounded-bar ${BLOCK}`} />
          </span>
        </div>
        <div className="order-2 grid gap-2 md:order-none">
          <span className={`h-[22px] w-full rounded-[6px] ${BLOCK}`} />
          <span className="flex h-[22px] items-center">
            <span className={`h-4 w-48 max-w-full rounded-bar ${BLOCK}`} />
          </span>
        </div>
        <div className="order-3 grid grid-cols-3 border-y border-outline-variant py-3.5 md:order-none">
          {[0, 1, 2].map((i) => (
            <span key={i} className="grid justify-items-center gap-0.5">
              <span className={`h-[30px] w-12 rounded-bar ${BLOCK}`} />
              <span className={`h-[19px] w-16 rounded-bar ${BLOCK}`} />
            </span>
          ))}
        </div>
        <div className="order-5 grid min-w-0 gap-2 md:order-none">
          <div className="flex h-11 items-center">
            <span className={`h-5 w-20 rounded-bar ${BLOCK}`} />
          </div>
          <div className="flex gap-2.5 overflow-hidden md:justify-between md:gap-1">
            {[0, 1, 2, 3, 4].map((i) => (
              <span key={i} className="grid w-[76px] flex-none justify-items-center gap-1.5 md:w-[70px]">
                <span className={`size-[52px] rounded-full ${BLOCK}`} />
                <span className={`h-[14px] w-14 rounded-bar ${BLOCK}`} />
              </span>
            ))}
          </div>
        </div>
        <div className="order-6 grid gap-1.5 md:order-none">
          <Heading />
          <GhostRows rows={3} announce={false} />
        </div>
      </div>
      <div className={COL}>
        <div className="order-4 grid grid-cols-4 gap-1.5 md:order-none md:gap-3">
          {[0, 1, 2, 3].map((i) => (
            <span key={i} className="grid min-w-0 justify-items-center gap-1.5">
              <span className={`size-14 rounded-tile md:size-16 md:rounded-[22px] ${BLOCK}`} />
              <span className={`h-[19px] w-12 rounded-bar ${BLOCK}`} />
              <span className={`-mt-1 h-[14px] w-10 rounded-bar ${BLOCK}`} />
            </span>
          ))}
        </div>
        <div className="order-7 grid gap-1.5 md:order-none">
          <Heading />
          <div className="grid">
            {[0, 1, 2].map((i) => (
              <span key={i} className="grid h-[60px] grid-cols-[14px_minmax(0,1fr)_auto] items-center gap-3">
                <span className={`size-3.5 rounded-full ${BLOCK}`} />
                <span className="grid gap-1.5">
                  <span className={`h-4 w-3/5 rounded-bar ${BLOCK}`} />
                  <span className={`h-3 w-2/5 rounded-bar ${BLOCK}`} />
                </span>
                <span className={`h-3 w-10 rounded-bar ${BLOCK}`} />
              </span>
            ))}
          </div>
        </div>
        <div className="order-8 grid md:order-none">
          {[0, 1, 2, 3].map((i) => (
            <span key={i} className="flex h-[49px] items-center border-outline-variant px-0.5 [&+&]:border-t">
              <span className={`h-4 w-32 rounded-bar ${BLOCK}`} />
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}
