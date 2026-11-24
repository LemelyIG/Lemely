/* Hallmark · pre-emit critique: P3 H3 E4 S4 R4 V3 */
/*
 * Practice tab icons. Paths are copied from the approved mock (ph.js `IC`,
 * `TK`; t.js `CHEV`) so the drawn weight matches it; every icon is decorative
 * (aria-hidden) and takes its colour from the text around it.
 */
import type { CSSProperties, ReactNode, SVGProps } from "react"
import { cn } from "@/lib/utils"

export type PracticeIconProps = SVGProps<SVGSVGElement> & { size?: number }

function Svg({ size = 22, viewBox, children, ...rest }: PracticeIconProps & { viewBox: string; children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox={viewBox}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  )
}

export function SetIcon(p: PracticeIconProps) {
  return (
    <Svg viewBox="0 0 22 22" {...p}>
      <path d="M5 4h12v14H5zM8 8h6M8 12h4" />
      <path d="m12.5 15 1.5 1.5 3-3.5" />
    </Svg>
  )
}

export function CardsIcon(p: PracticeIconProps) {
  return (
    <Svg viewBox="0 0 20 20" strokeWidth={1.7} {...p}>
      <rect x={3} y={5} width={11} height={12} rx={2} />
      <path d="M7 3h8a2 2 0 0 1 2 2v9" />
    </Svg>
  )
}

export function PaperIcon(p: PracticeIconProps) {
  return (
    <Svg viewBox="0 0 20 20" strokeWidth={1.7} {...p}>
      <path d="M5 2.5h7l3.5 3.5v11.5h-10.5zM12 2.5V6h3.5M8 10h5M8 13h5" />
    </Svg>
  )
}

export function TestIcon(p: PracticeIconProps) {
  return (
    <Svg viewBox="0 0 20 20" strokeWidth={1.7} {...p}>
      <circle cx={10} cy={10} r={7} />
      <path d="m12.8 7.2-1.8 3.8-3.8 1.8 1.8-3.8z" />
    </Svg>
  )
}

export function ResumeIcon(p: PracticeIconProps) {
  return (
    <Svg viewBox="0 0 18 18" size={18} fill="currentColor" stroke="none" {...p}>
      <path d="M6 4.2v9.6L13.5 9z" />
    </Svg>
  )
}

export function PrintIcon(p: PracticeIconProps) {
  return (
    <Svg viewBox="0 0 18 18" size={18} strokeWidth={1.7} {...p}>
      <path d="M5 7V2.5h8V7M5 13H3V7h12v6h-2M5 10.5h8v5H5z" />
    </Svg>
  )
}

export function ClockIcon(p: PracticeIconProps) {
  return (
    <Svg viewBox="0 0 18 18" size={18} strokeWidth={1.7} {...p}>
      <circle cx={9} cy={9.5} r={6} />
      <path d="M9 6.5v3l2 1.5M7 2h4" />
    </Svg>
  )
}

export function TickIcon(p: PracticeIconProps) {
  return (
    <Svg viewBox="0 0 16 16" size={16} strokeWidth={2.2} {...p}>
      <path d="M3.5 8.3 6.5 11l6-6.5" />
    </Svg>
  )
}

export function ChevronIcon(p: PracticeIconProps) {
  return (
    <Svg viewBox="0 0 18 18" size={18} {...p}>
      <path d="M7 4l5 5-5 5" />
    </Svg>
  )
}

/** `.spin`: 14px ring, outline track, primary head, .8s linear; static under reduced motion. */
export function SpinnerRing() {
  return (
    <span
      aria-hidden="true"
      className="inline-block size-3.5 flex-none animate-spin rounded-full border-2 border-outline border-t-primary [animation-duration:.8s] [animation-timing-function:linear] motion-reduce:animate-none"
    />
  )
}

export function SubjectDot({ color, className }: { color: string; className?: string }) {
  const style: CSSProperties = { background: color }
  return <i aria-hidden="true" style={style} className={cn("me-1.5 inline-block size-2 flex-none rounded-full align-[1px]", className)} />
}
