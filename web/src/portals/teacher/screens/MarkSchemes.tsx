import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { StatCard } from "../components/StatCard"
import { schemeStats, schemes, type SchemeStatus } from "../data"

const STATUS_CHIP: Record<SchemeStatus, string> = {
  parsed: "bg-ok-bg text-[oklch(0.34_0.09_152)]",
  pending: "bg-accent-subtle text-[oklch(0.42_0.10_68)]",
  custom: "bg-[oklch(0.93_0.01_78)] text-t2",
}

const COLS = "grid grid-cols-[minmax(0,1.6fr)_84px_104px_62px_74px_92px] gap-[14px]"

export function MarkSchemes() {
  return (
    <div className="lm-screen flex flex-col gap-5">
      <div className="flex items-end gap-[18px] pb-[18px] border-b border-border flex-wrap gap-y-2.5">
        <div>
          <div className="font-mono text-[11px] tracking-[0.11em] uppercase text-t3">
            Library · Sources / · 214 documents
          </div>
          <div className="font-serif text-[34px] leading-[1.1] mt-1.5">
            Mark schemes
          </div>
        </div>
        <div className="flex-1" />
        <Button variant="secondary">Upload your own</Button>
        <Button variant="ink">Parse 6 pending</Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {schemeStats.map((s) => (
          <StatCard key={s.k} stat={s} />
        ))}
      </div>

      <div className="bg-surface border border-border rounded-[14px] overflow-hidden">
        <div
          className={cn(
            COLS,
            "px-[22px] py-2.5 bg-[oklch(0.965_0.012_78)] border-b border-border font-mono text-[10px] tracking-[0.09em] uppercase text-t3",
          )}
        >
          <div>Document</div>
          <div>Paper</div>
          <div>Session</div>
          <div>Marks</div>
          <div>Questions</div>
          <div>Status</div>
        </div>
        {schemes.map((m) => (
          <div
            key={m.doc}
            className={cn(
              COLS,
              "items-center px-[22px] py-[13px] border-b border-border",
            )}
          >
            <div className="font-mono text-[12.5px] min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">
              {m.doc}
            </div>
            <div className="text-[13px] text-t2">{m.paper}</div>
            <div className="text-[13px] text-t2">{m.session}</div>
            <div className="font-mono text-[12.5px]">{m.marks}</div>
            <div className="font-mono text-[12.5px] text-t2">{m.questions}</div>
            <div>
              <span
                className={cn(
                  "text-[11.5px] rounded-full px-[11px] py-[3px]",
                  STATUS_CHIP[m.status],
                )}
              >
                {m.status}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
