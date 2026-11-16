/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { ReactNode } from "react"
import { clamp01, goldRingDone, goldRingGeometry } from "./rings"
import "./redesign.css"

export interface GoldRingProps {
  parts: [number, number, number]
  size?: number
  label?: string
  center?: ReactNode
}

const f = (n: number) => n.toFixed(2)

/** The gold three-part ring (mock ring4 / gring2). Gold only when a part is complete. */
export function GoldRing({ parts, size = 32, label, center }: GoldRingProps) {
  const { r, stroke, circumference, third, dash } = goldRingGeometry(size)
  const half = size / 2
  return (
    <span className="rd-goldring" role="img" aria-label={label ?? `${goldRingDone(parts)} of 3 done`} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true" focusable="false">
        {parts.map((raw, i) => {
          const v = clamp01(raw)
          const ring = {
            r: f(r),
            cx: half,
            cy: half,
            fill: "none",
            strokeWidth: f(stroke),
            strokeLinecap: "round" as const,
            strokeDashoffset: f(-i * third),
            transform: `rotate(-90 ${half} ${half})`,
          }
          return (
            <g key={i} data-part={v >= 1 ? "done" : v > 0 ? "partial" : "empty"}>
              <circle {...ring} className={v >= 1 ? "rd-ring-gold" : "rd-ring-track"} strokeDasharray={`${f(dash)} ${f(circumference - dash)}`} />
              {v > 0 && v < 1 ? (
                <circle {...ring} className="rd-ring-partial" strokeDasharray={`${f(dash * v)} ${f(circumference - dash * v)}`} />
              ) : null}
            </g>
          )
        })}
      </svg>
      {center !== undefined ? (
        <span className="rd-ring-center" aria-hidden="true">
          {center}
        </span>
      ) : null}
    </span>
  )
}
