/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { Link } from "react-router-dom"
import { BinnyLine } from "@/components/redesign"
import { buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { TipView } from "./subjectModel"
import "./subject.css"

/** Binny's 2–4 words, then one button that names the action. Binny's only appearance on the screen. */
export function TipSection({ tip, size }: { tip: TipView; size: number }) {
  return (
    <section className="sj-tip" aria-label="Next step">
      <BinnyLine mood={tip.mood} line={tip.line} size={size} motion="idle" />
      <Link to={tip.action.to} className={cn(buttonVariants({ variant: "primary", size: "lg" }), "sj-go")}>
        {tip.action.label}
        {tip.action.detail ? <span> · {tip.action.detail}</span> : null}
      </Link>
      {tip.secondary ? (
        <Link to={tip.secondary.to} className="sj-upl">
          {tip.secondary.label}
        </Link>
      ) : null}
    </section>
  )
}
