/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V3 */
import { CaretRight } from "@phosphor-icons/react"
import { useLongPress } from "@/lib/gestures/useLongPress"
import type { DeckRowView } from "../flashcardsView"
import { DueCount } from "./DueCount"
import { MasteryBar } from "./MasteryBar"
import { OriginTag } from "./OriginTag"

/**
 * fc.css `.dkr`: grid [1fr auto 18px], gap 12, padding 12px 0, hairline above; selected = `.dkr.on`
 * (primary-container, r14, inline padding 12, no hairline), desktop only: on a phone the row opens a
 * screen, so the caller passes `selected` only at lg. Long-press opens the deck menu (live K15).
 * Retry is inert while its request is in flight, so a second tap cannot send a second retry.
 */
export function DeckRow({
  row, selected = false, onOpen, onLongPress, onRetry, retrying = false,
}: {
  row: DeckRowView
  selected?: boolean
  onOpen: () => void
  onLongPress: () => void
  onRetry?: () => void
  retrying?: boolean
}) {
  const longPress = useLongPress({ onLongPress })
  return (
    <li className={`flex items-center gap-1 [&+li]:shadow-[0_-1px_0_var(--color-outline-variant)] ${selected ? "lg:!shadow-none" : ""}`}>
      <button
        type="button"
        onClick={onOpen}
        aria-current={selected ? "true" : undefined}
        data-fc-selected-row={selected ? "" : undefined}
        {...longPress}
        className={[
          "group grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_auto_18px] items-center gap-3 py-3 text-start text-on-surface",
          "focus-visible:!rounded-[14px] focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary",
          selected ? "lg:rounded-[14px] lg:bg-primary-container lg:px-3" : "",
        ].join(" ")}
      >
        <span className="grid gap-1 leading-tight">
          <b className="text-[15px] font-bold transition-colors group-hover:text-primary">{row.title}</b>
          {row.statusLine ? (
            <span className={row.status === "failed" ? "text-[13px] font-semibold text-on-error-container" : "text-[13px] text-on-surface-variant"}>
              {row.statusLine}
            </span>
          ) : (
            <>
              <OriginTag icon={row.originIcon}>{row.meta}</OriginTag>
              <MasteryBar mastery={row.mastery} />
            </>
          )}
        </span>
        {row.status === "ready" ? <DueCount due={row.due} /> : <span />}
        <CaretRight size={18} weight="bold" aria-hidden className="text-on-surface" />
      </button>
      {row.canRetry && onRetry ? (
        <button
          type="button"
          onClick={retrying ? undefined : onRetry}
          aria-disabled={retrying || undefined}
          aria-label={`${retrying ? "Retrying" : "Retry"} ${row.title}`}
          className="min-h-11 flex-none rounded-[14px] px-3.5 text-[14px] font-bold text-primary focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary"
        >
          {retrying ? "Retrying…" : "Retry"}
        </button>
      ) : null}
    </li>
  )
}
