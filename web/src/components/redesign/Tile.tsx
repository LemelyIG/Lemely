/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { ElementType, ReactNode } from "react"
import { Link } from "react-router-dom"
import { cn } from "@/lib/utils"
import { Chevron } from "./icons"
import "./redesign.css"

export type TileTone = "tide" | "sea" | "gold" | "coral" | "violet" | "mint"

export interface TileProps {
  /** A Phosphor icon. */
  icon: ElementType
  title: string
  /** e.g. "Build your own · 10 min", or a node with a Mono count in <b>. */
  status?: ReactNode
  tone: TileTone
  /** The full-width row variant (the homework row). */
  big?: boolean
  to?: string
  onClick?: () => void
  disabled?: boolean
}

/** A tinted tile with a big faint icon (Practice tab C, mock ph.js gridC). */
export function Tile({ icon: Icon, title, status, tone, big = false, to, onClick, disabled = false }: TileProps) {
  const className = cn("rd-tile", big && "rd-tile-big")
  const body = big ? (
    <>
      <span className="rd-tile-ic" aria-hidden="true">
        <Icon size={22} />
      </span>
      <span className="rd-at">
        <b>{title}</b>
        {status !== undefined ? <span>{status}</span> : null}
      </span>
      <Chevron />
    </>
  ) : (
    <>
      <b className="rd-tile-title">{title}</b>
      {status !== undefined ? <span className="rd-tile-status">{status}</span> : null}
      <span className="rd-tile-art" aria-hidden="true">
        <Icon size={64} weight="light" />
      </span>
    </>
  )
  if (disabled) {
    return (
      <div className={className} data-tone={tone} aria-disabled="true">
        {body}
      </div>
    )
  }
  if (to) {
    return (
      <Link to={to} className={className} data-tone={tone}>
        {body}
      </Link>
    )
  }
  if (onClick) {
    return (
      <button type="button" className={className} data-tone={tone} onClick={onClick}>
        {body}
      </button>
    )
  }
  return (
    <div className={className} data-tone={tone}>
      {body}
    </div>
  )
}
