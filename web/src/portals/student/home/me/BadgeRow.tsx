import { CaretRight, Clock, Fire, FileText, Star, TrendUp } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { FOCUS, HIT } from "../gradeClass"
import type { BadgeId, deriveBadges } from "./meModel"

export const BADGE_ICON: Record<BadgeId, typeof Star> = {
  "first-paper": FileText,
  "streak-7": Fire,
  "grade-up": TrendUp,
  "streak-30": Clock,
  "a-star": Star,
}

export function BadgeRow({ badges, onAll }: { badges: ReturnType<typeof deriveBadges>; onAll: () => void }) {
  return (
    <section aria-labelledby="me-badges" className="grid gap-2">
      {/* Opens a sheet, not a route, so SectionLink (a Link) does not fit; same look. */}
      <h2 id="me-badges" className="m-0">
        <button
          type="button"
          onClick={onAll}
          className={cn("inline-flex min-h-8 items-center gap-1 rounded-row font-display text-[17px] font-extrabold tracking-[-0.01em] text-on-surface", HIT, FOCUS)}
        >
          Badges
          <CaretRight size={16} weight="bold" className="text-on-surface-variant" aria-hidden="true" />
        </button>
      </h2>
      <ul className="relative -mx-[18px] flex gap-2.5 overflow-x-auto px-[18px] [scrollbar-width:none] md:mx-0 md:justify-between md:gap-1 md:overflow-visible md:px-0">
        {badges.map((b) => {
          const Icon = BADGE_ICON[b.id]
          return (
            <li key={b.id} className="grid w-[76px] flex-none justify-items-center gap-1.5 text-center md:w-[70px]">
              <span className={cn("grid size-[52px] place-items-center rounded-full", b.earned ? "bg-tertiary-container text-on-tertiary-container" : "bg-surface-container-high text-outline")}>
                <Icon size={24} aria-hidden="true" />
              </span>
              <small className={cn("text-[12px] font-semibold leading-[1.2]", b.earned ? "text-on-surface" : "text-on-surface-variant")}>
                {b.label}
                <span className="sr-only">{b.earned ? ", earned" : ", not earned yet"}</span>
              </small>
            </li>
          )
        })}
        <li className="grid w-[76px] flex-none justify-items-center gap-1.5 text-center md:w-[70px]">
          <button type="button" onClick={onAll} className={cn("grid size-[52px] place-items-center rounded-full text-primary ring-[1.5px] ring-inset ring-outline", FOCUS)} aria-label="All badges">
            <CaretRight size={14} weight="bold" aria-hidden="true" />
          </button>
          <small className="text-[12px] font-semibold leading-[1.2] text-on-surface-variant">All badges</small>
        </li>
      </ul>
    </section>
  )
}
