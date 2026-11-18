/* Hallmark · pre-emit critique: P3 H3 E4 S3 R4 V3 */
import { Link } from "react-router-dom"
import { CaretRight } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import type { BackgroundState } from "@/lib/nav/backgroundLocation"
import { FOCUS, ROW_PRESS } from "../gradeClass"
import type { accountRows } from "./meModel"

export function AccountRows({ rows, overlayState, className }: { rows: ReturnType<typeof accountRows>; overlayState: BackgroundState; className?: string }) {
  return (
    <ul aria-label="Help and account" className={cn("grid", className)}>
      {rows.map((r) => (
        <li key={r.id} className="[&+&]:border-t [&+&]:border-outline-variant">
          <Link
            to={r.to}
            state={r.overlay ? overlayState : undefined}
            className={cn("grid grid-cols-[auto_minmax(0,1fr)_18px] items-center gap-2.5 px-0.5 py-[13px] text-on-surface", ROW_PRESS, FOCUS)}
          >
            <b className="text-[15px] font-semibold">{r.label}</b>
            <span className="text-end text-[13px] text-on-surface-variant">{r.sub}</span>
            <CaretRight size={18} className="text-on-surface-variant" aria-hidden="true" />
          </Link>
        </li>
      ))}
    </ul>
  )
}
