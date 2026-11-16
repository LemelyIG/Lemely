import { GhostRows } from "@/components/redesign"

export function HomeSkeleton() {
  return (
    <div role="status" aria-label="Loading" className="flex flex-col gap-[22px] max-md:pt-3.5">
      <div className="flex gap-2">
        <span className="h-8 w-20 rounded-chip bg-surface-container-high" />
        <span className="h-8 w-36 rounded-chip bg-surface-container-high" />
      </div>
      <div className="grid justify-items-center gap-3.5">
        <span className="size-[150px] rounded-full bg-surface-container-high" />
        <span className="h-6 w-64 max-w-full rounded-bar bg-surface-container-high" />
        <span className="h-[54px] w-full max-w-[300px] rounded-inner bg-surface-container-high" />
      </div>
      <div className="grid grid-cols-7 gap-1 md:hidden">
        {Array.from({ length: 7 }, (_, i) => (
          <span key={i} className="mx-auto h-11 w-8 rounded-chip bg-surface-container-high" />
        ))}
      </div>
      <div className="grid grid-cols-3 border-y border-outline-variant py-3.5">
        {[0, 1, 2].map((i) => (
          <span key={i} className="mx-auto h-11 w-9 rounded-row bg-surface-container-high" />
        ))}
      </div>
      <GhostRows rows={3} />
      <div aria-hidden="true" className="hidden gap-10 border-t border-outline-variant pt-6 md:grid md:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="grid content-start gap-2">
            <span className="h-4 w-24 rounded-bar bg-surface-container-high" />
            <span className="h-11 w-full rounded-row bg-surface-container-high" />
            <span className="h-11 w-full rounded-row bg-surface-container-high" />
          </div>
        ))}
      </div>
    </div>
  )
}
