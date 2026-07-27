import { railTicks } from "../data"

/*
 * Grade-boundary rail from the mock: a gradient track with grade ticks (U..A)
 * and a "you - N%" marker positioned by percentage. Real data-viz, so the track
 * and marker are built with divs as the mock does.
 */
export function BoundaryRail({ pct }: { pct: number }) {
  return (
    <div className="relative h-[58px] mt-5">
      <div
        className="absolute left-0 right-0 top-[26px] h-2 rounded-[5px]"
        style={{
          background:
            "linear-gradient(90deg, oklch(0.93 0.02 35), oklch(0.93 0.04 70), oklch(0.93 0.05 150))",
        }}
      />
      {railTicks.map((t) => (
        <div
          key={t.g}
          className="absolute top-0 flex flex-col items-center gap-1 -translate-x-1/2"
          style={{ left: `${t.left}%` }}
        >
          <div className="font-mono text-[10.5px] text-t3">{t.g}</div>
          <div className="w-px h-[38px] bg-border" />
        </div>
      ))}
      <div
        className="absolute top-1.5 -translate-x-1/2 flex flex-col items-center"
        style={{ left: `${pct}%` }}
      >
        <div className="bg-accent text-accent-on text-[11.5px] px-[9px] py-[3px] rounded-md font-mono whitespace-nowrap">
          you - {pct}%
        </div>
        <div className="w-0.5 h-7 bg-accent" />
      </div>
    </div>
  )
}
