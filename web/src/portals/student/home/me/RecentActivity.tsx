/* Hallmark · pre-emit critique: P4 H4 E3 S4 R4 V4 */
import { cn } from "@/lib/utils"
import type { activityVm } from "./meModel"

const DOT = { paper: "bg-primary", practice: "bg-primary", teacher: "bg-success" } as const

export function RecentActivity({ rows }: { rows: ReturnType<typeof activityVm> }) {
  return (
    <section aria-labelledby="me-activity" className="grid gap-1.5">
      <h2 id="me-activity" className="py-1 text-[18px] font-extrabold tracking-[-0.01em] text-on-surface">Recent activity</h2>
      {rows.length > 0 ? (
        <ul className="relative grid list-none">
          {rows.map((a, i) => (
            <li
              key={`${a.kind}-${i}`}
              className="relative grid grid-cols-[14px_minmax(0,1fr)_auto] items-start gap-3 py-[9px] before:absolute before:start-1.5 before:top-6 before:-bottom-[9px] before:w-0.5 before:bg-outline-variant before:content-[''] last:before:hidden"
            >
              <i aria-hidden="true" className={cn("mt-[3px] size-3.5 rounded-full", DOT[a.kind])} />
              <div className="min-w-0">
                <b className="block text-[15px] font-semibold text-on-surface">{a.title}</b>
                <span className="text-[13px] text-on-surface-variant">{a.sub}</span>
              </div>
              <small className="whitespace-nowrap text-[12.5px] font-medium text-on-surface-variant">{a.when}</small>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-on-surface-variant">Your activity shows up here.</p>
      )}
    </section>
  )
}
