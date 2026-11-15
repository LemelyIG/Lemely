/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { ReactNode } from "react"
import { ringDash } from "@/components/ui/progress-ring"
import { clamp01, keyRingGeometry } from "./rings"
import "./redesign.css"

export interface KeyRingProps {
  value: number
  size?: number
  /** 'warn' is the error red (confidence under 70%); 'neutral' draws the track only, for "no score". */
  tone?: "tide" | "gold" | "ok" | "warn" | "neutral"
  center: ReactNode
  /** The accessible name; include the key number, because the centre is hidden from assistive tech. */
  label: string
}

/** The single big key-number ring (confidence, level). */
export function KeyRing({ value, size = 92, tone = "tide", center, label }: KeyRingProps) {
  const { r, stroke, circumference } = keyRingGeometry(size)
  const half = size / 2
  const ring = { r: r.toFixed(1), cx: half, cy: half, fill: "none", strokeWidth: stroke.toFixed(1) }
  return (
    <span className="rd-keyring" data-tone={tone} role="img" aria-label={label} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true" focusable="false">
        <circle {...ring} className="rd-ring-track" />
        {tone === "neutral" ? null : (
          <circle
            {...ring}
            className={`rd-ring-tone-${tone}`}
            strokeLinecap="round"
            strokeDasharray={ringDash(clamp01(value) * 100, circumference)}
            transform={`rotate(-90 ${half} ${half})`}
          />
        )}
      </svg>
      <span className="rd-ring-center" aria-hidden="true">
        {center}
      </span>
    </span>
  )
}
