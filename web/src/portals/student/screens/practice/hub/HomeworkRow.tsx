/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { Link } from "react-router-dom"
import { ChevronIcon, HomeworkIcon } from "../practiceIcons"
import type { HomeworkView } from "./hubModel"
import { MonoNumbers } from "./MonoNumbers"

/** `.hwr`: the only tinted row on the hub, shown on top only when homework is set. */
export function HomeworkRow({ homework }: { homework: HomeworkView }) {
  return (
    <Link
      to={homework.to}
      className="group grid min-h-[60px] grid-cols-[40px_minmax(0,1fr)_18px] items-center gap-3 rounded-2xl bg-primary-container px-3 py-2.5 text-on-surface focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary lg:max-w-[560px]"
    >
      <span className="grid size-10 place-items-center rounded-[13px] bg-primary text-on-primary">
        <HomeworkIcon />
      </span>
      <span className="grid min-w-0 gap-0.5">
        <b className="truncate text-[15px] font-bold transition-colors group-hover:text-primary">{homework.title}</b>
        <span className="truncate text-[13px] text-on-surface-variant"><MonoNumbers text={homework.sub} /></span>
      </span>
      <ChevronIcon className="text-on-surface-variant" />
    </Link>
  )
}
