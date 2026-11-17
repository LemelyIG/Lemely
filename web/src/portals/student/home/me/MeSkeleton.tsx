import { GhostRows } from "@/components/redesign"

export function MeSkeleton() {
  return (
    <div role="status" aria-label="Loading" className="flex flex-col gap-[22px]">
      <div className="flex items-center gap-3.5">
        <span className="size-[92px] rounded-full bg-surface-container-high" />
        <span className="grid flex-1 gap-2">
          <span className="h-8 w-40 rounded-bar bg-surface-container-high" />
          <span className="h-4 w-48 rounded-bar bg-surface-container-high" />
        </span>
      </div>
      <span className="h-[22px] w-full rounded-[6px] bg-surface-container-high" />
      <GhostRows rows={4} />
    </div>
  )
}
