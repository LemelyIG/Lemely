import { CaretRight } from "@phosphor-icons/react"
import { useLongPress } from "@/lib/gestures/useLongPress"
import type { DeckRowView } from "../flashcardsView"
import { DueCount } from "./DueCount"
import { MasteryBar } from "./MasteryBar"
import { OriginTag } from "./OriginTag"

/**
 * fc.css `.dkr`: grid [1fr auto 18px], gap 12, padding 12px 0, hairline above; selected = `.dkr.on`
 * (primary-container, r14, inline padding 12). Long-press opens the deck menu (live K15).
 */
export function DeckRow({
  row, selected = false, onOpen, onLongPress,
}: { row: DeckRowView; selected?: boolean; onOpen: () => void; onLongPress: () => void }) {
  const longPress = useLongPress({ onLongPress })
  return (
    <li className="[&+li>button]:shadow-[0_-1px_0_var(--color-outline-variant)]">
      <button
        type="button"
        onClick={onOpen}
        aria-current={selected ? "true" : undefined}
        {...longPress}
        className={[
          "group grid w-full grid-cols-[minmax(0,1fr)_auto_18px] items-center gap-3 py-3 text-start text-on-surface",
          "focus-visible:rounded-[14px] focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary",
          selected ? "rounded-[14px] bg-primary-container px-3 !shadow-none" : "",
        ].join(" ")}
      >
        <span className="grid gap-1">
          <b className="text-[15px] font-bold group-hover:text-primary">{row.title}</b>
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
        <CaretRight size={18} aria-hidden className="text-on-surface-variant" />
      </button>
    </li>
  )
}
