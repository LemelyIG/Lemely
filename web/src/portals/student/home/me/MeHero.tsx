/* Hallmark · pre-emit critique: P5 H5 E4 S5 R4 V4 */
import { Link } from "react-router-dom"
import { Binny, KeyRing } from "@/components/redesign"
import { Celebrate, CountUp } from "@/components/ui/celebration"
import type { XpProfile } from "@/lib/xpTypes"
import { cn } from "@/lib/utils"
import { FOCUS } from "../gradeClass"
import { homeRoutes } from "../routes"
import { levelLine, levelProgress } from "./meModel"

export function MeHero({ name, xp, avatarUrl, className }: { name: string; xp: XpProfile; avatarUrl: string | null; className?: string }) {
  const progress = levelProgress(xp)
  const avatar = avatarUrl ? (
    <img src={avatarUrl} alt="" className="size-[70px] rounded-full object-cover md:size-16" />
  ) : (
    <span className="grid size-[70px] place-items-center rounded-full bg-primary-container font-display text-[28px] font-extrabold text-primary md:size-16">
      {name.charAt(0).toUpperCase()}
    </span>
  )
  return (
    <div className={cn("relative flex items-center gap-3.5", className)}>
      <Link to={homeRoutes.settings} aria-label="Profile and settings" className={cn("relative flex-none rounded-full", FOCUS)}>
        <KeyRing
          value={progress / 100}
          size={92}
          tone="gold"
          label={`Level ${xp.level}, ${Math.round(progress)}% of the way to level ${xp.level + 1}`}
          center={avatar}
        />
        <Celebrate
          value={xp.level}
          className="absolute -end-0.5 bottom-1 grid h-7 min-w-7 place-items-center rounded-full bg-tertiary px-1 font-mono text-[14px] font-extrabold text-on-tertiary shadow-[0_0_0_3px_var(--md-surface)]"
        >
          <CountUp value={xp.level} />
        </Celebrate>
      </Link>
      <div className="min-w-0 flex-1">
        <h2 className="line-clamp-2 break-words font-display text-[32px] font-extrabold leading-[1.05] tracking-[-0.03em] text-primary md:text-[34px]">{name}</h2>
        <span className="text-[13px] text-on-surface-variant">{levelLine(xp)}</span>
      </div>
      <div className="-me-1 flex-none self-center">
        <Binny mood="wink" motion="idle" size={66} aria-hidden />
      </div>
    </div>
  )
}
