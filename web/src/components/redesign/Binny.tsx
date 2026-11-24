/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { CSSProperties } from "react"
import { cn } from "@/lib/utils"
import { resolveMotion, usePrefersReducedMotion } from "./motion"
import "./redesign.css"

export type BinnyMood = "happy" | "wink" | "open" | "thinking" | "sad"
export type BinnyMotion = "idle" | "hop" | "roam" | "pop" | "none"

export interface BinnyProps {
  mood: BinnyMood
  size?: number
  motion?: BinnyMotion
  className?: string
  "aria-hidden"?: boolean
  /** Roam only: how far Binny wanders each side. The zone reserves it, so he never overlaps content. */
  roamDistance?: number
  /** Teacher screens: the small head-and-shoulders crop (Binny.tsx `compact`), square, no paper, cheeks or mouth. */
  headCrop?: boolean
}

const EAR_L = "M66 102 L62 40 Q62 16 75 16 Q88 16 88 40 L84 102"
const EAR_R = "M116 102 L112 40 Q112 16 125 16 Q138 16 138 40 L134 102"
const ARC_L = "M68 143 Q78 130 88 143"
const ARC_R = "M112 143 Q122 130 132 143"

function OpenEye({ cx, pupilX, pupilY }: { cx: number; pupilX: number; pupilY: number }) {
  return (
    <>
      <ellipse cx={cx} cy="140" rx="11" ry="12" fill="var(--rd-bn-face)" />
      <circle className="rd-bn-pupil" cx={pupilX} cy={pupilY} r="6.5" />
    </>
  )
}

function ClosedEye({ d }: { d: string }) {
  return <path d={d} fill="none" stroke="var(--rd-bn-face)" strokeWidth="6" strokeLinecap="round" />
}

function Mouth({ mood }: { mood: BinnyMood }) {
  if (mood === "open") {
    return <path d="M86 160 H114 Q113 180 100 180 Q87 180 86 160Z" fill="var(--rd-bn-pupil)" stroke="var(--rd-bn-face)" strokeWidth="3" strokeLinejoin="round" />
  }
  const d = mood === "sad" ? "M90 172 Q100 163 110 172" : mood === "thinking" ? "M92 167 H108" : "M90 163 Q100 172 110 163"
  return <path d={d} fill="none" stroke="var(--rd-bn-face)" strokeWidth="4.5" strokeLinecap="round" />
}

/**
 * The official Binny (portals/marketing/Binny.tsx geometry) with the clipped
 * paper sheet and the sad mood (student-r2/h.js BIN), confirmed official Binny by the owner 2026-11-24. Student
 * screens only, once per screen. Under prefers-reduced-motion every motion is 'none'.
 */
export function Binny({ mood, size = 96, motion = "idle", className, "aria-hidden": ariaHidden = true, roamDistance = 48, headCrop = false }: BinnyProps) {
  const reduced = usePrefersReducedMotion()
  const resolved = resolveMotion(motion, reduced)
  // The zone follows the requested motion, not the resolved one, so reduced-motion and SSR layouts match.
  const dx = mood === "thinking" ? 4 : 0
  const dy = mood === "sad" ? 4 : 0
  const a11y = ariaHidden ? { "aria-hidden": true as const } : { role: "img", "aria-label": "Binny" }
  const eyes = (
    <g className="rd-bn-eyes">
      {mood === "happy" ? <ClosedEye d={ARC_L} /> : <OpenEye cx={78} pupilX={80 + dx} pupilY={141 + dy} />}
      {mood === "happy" || mood === "wink" ? <ClosedEye d={ARC_R} /> : <OpenEye cx={122} pupilX={124 + dx} pupilY={141 + dy} />}
    </g>
  )
  const svg = (
    <svg
      className={cn("rd-binny", className)}
      data-mood={mood}
      data-motion={resolved}
      data-crop={headCrop ? "head" : undefined}
      width={size}
      height={headCrop ? size : Math.round(size * 1.1)}
      viewBox={headCrop ? "30 10 140 140" : "0 0 200 220"}
      overflow="visible"
      focusable="false"
      {...a11y}
    >
      <g className="rd-bn-body">
        {headCrop ? null : (
          <rect x="54" y="168" width="92" height="48" rx="4" fill="var(--rd-bn-paper)" stroke="var(--rd-bn-paper-line)" strokeWidth="2" transform="rotate(-3 100 192)" />
        )}
        <g data-tilt={headCrop ? "l" : undefined} transform={headCrop ? "rotate(-6 75 100)" : undefined}>
          <g className="rd-bn-ear rd-bn-ear-l">
            <path d={EAR_L} fill="none" stroke="var(--binny-steel)" strokeWidth="8" strokeLinecap="round" strokeLinejoin="round" />
          </g>
        </g>
        <g data-tilt={headCrop ? "r" : undefined} transform={headCrop ? "rotate(6 125 100)" : undefined}>
          <g className="rd-bn-ear rd-bn-ear-r">
            <path d={EAR_R} fill="none" stroke="var(--binny-steel)" strokeWidth="8" strokeLinecap="round" strokeLinejoin="round" />
          </g>
        </g>
        <path d={headCrop ? "M40 104 H160 L154 150 H46 Z" : "M40 104 H160 L152 186 Q151 196 141 196 H59 Q49 196 48 186 Z"} fill="var(--rd-bn-body)" />
        <rect x="34" y="94" width="132" height="18" rx="8" fill="color-mix(in oklch, var(--rd-bn-body) 65%, black)" />
        {headCrop ? (
          <g transform="translate(0 -8)">{eyes}</g>
        ) : (
          <>
            <ellipse cx="62" cy="160" rx="9" ry="5.5" opacity=".55" fill="var(--binny-cheek)" />
            <ellipse cx="138" cy="160" rx="9" ry="5.5" opacity=".55" fill="var(--binny-cheek)" />
            {eyes}
            <Mouth mood={mood} />
          </>
        )}
      </g>
    </svg>
  )
  if (motion !== "roam") return svg
  return (
    <span className="rd-binny-zone" style={{ "--rd-roam": `${roamDistance}px` } as CSSProperties}>
      {svg}
    </span>
  )
}
