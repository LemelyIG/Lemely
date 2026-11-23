/* Hallmark · pre-emit critique: P4 H4 E3 S5 R4 V4 */
import { KeyRing } from "@/components/redesign"
import type { ReviewQueueItem } from "@/lib/teacherTypes"
import "./review.css"
import { plainWhy, ringLabel, ringText, ringTone, ringValue, rowSubtitle, selectable } from "./reviewQueueModel"
import { Tick } from "./Tick"

const DOT: Record<ReturnType<typeof ringTone>, string> = { warn: "bg-error", gold: "bg-tertiary", neutral: "bg-outline" }

export interface QueueRowProps {
  item: ReviewQueueItem
  focused: boolean
  gone: boolean
  selecting: boolean
  picked: boolean
  onOpen: (id: string) => void
  onPick: (id: string) => void
}

export function QueueRow({ item, focused, gone, selecting, picked, onOpen, onPick }: QueueRowProps) {
  const tone = ringTone(item.confidenceScore)
  const canPick = selectable(item)
  return (
    <li className="lm-rq-li">
      <button
        type="button"
        data-review-row={item.itemId}
        data-gone={gone || undefined}
        aria-current={!selecting && focused ? "true" : undefined}
        aria-pressed={selecting ? picked : undefined}
        aria-disabled={selecting && !canPick ? true : undefined}
        title={selecting && !canPick ? "Integrity flags aren't selectable for bulk-approve. Open this item instead" : undefined}
        onClick={() => (selecting ? canPick && onPick(item.itemId) : onOpen(item.itemId))}
        className={`lm-rq-row grid min-h-0 w-full items-center gap-2.5 rounded-[14px] p-3 text-start ${selecting ? "grid-cols-[auto_auto_1fr_auto]" : "grid-cols-[auto_1fr_auto]"} ${focused && !selecting ? "bg-surface-container-lowest shadow-[inset_0_0_0_2px_var(--color-primary)]" : "hover:bg-surface-container"} focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary`}
      >
        {selecting ? (
          <span className={`grid size-[22px] place-items-center rounded-[7px] text-on-primary ${picked ? "bg-primary" : "bg-surface-container-lowest shadow-[inset_0_0_0_1.5px_var(--color-outline)]"} ${canPick ? "" : "opacity-35"}`} aria-hidden="true">{picked ? <Tick /> : null}</span>
        ) : null}
        <KeyRing
          value={ringValue(item.confidenceScore)}
          size={52}
          tone={tone === "gold" ? "gold" : tone === "neutral" ? "neutral" : "warn"}
          label={ringLabel(item.confidenceScore)}
          center={<span className="font-mono text-[14px] font-semibold tabular-nums tracking-[-0.02em]">{ringText(item.confidenceScore)}{item.confidenceScore != null ? <small className="text-[12px]">%</small> : null}</span>}
        />
        <span className="grid min-w-0 gap-[3px]">
          <span className="flex min-w-0 flex-wrap items-baseline gap-x-1.5"><b className="max-w-full truncate text-[15px] font-bold leading-[1.25] tracking-[-0.005em]">{item.studentDisplayName}</b><span className="text-[13px] text-on-surface-variant">{rowSubtitle(item)}</span></span>
          <span className="flex items-start gap-[7px] text-[14px] leading-[1.35]"><i className={`mt-[5px] size-2 flex-none rounded-full ${DOT[tone]}`} aria-hidden="true" />{plainWhy(item)}</span>
        </span>
        <span className="font-display text-[28px] font-extrabold leading-none tracking-[-0.03em] tabular-nums" aria-label={`Lemely gave ${item.aiAwardedMarks ?? "none"} of ${item.maximumMarks ?? "unknown"}`}>
          {item.aiAwardedMarks ?? "–"}/{item.maximumMarks ?? "–"}
        </span>
      </button>
    </li>
  )
}
