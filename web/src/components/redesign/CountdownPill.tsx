/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Link } from "react-router-dom"
import { countdownLabel, countdownTone, daysUntil } from "./countdown"
import { CalendarGlyph, SmallChevron } from "./icons"
import "./redesign.css"

export interface CountdownPillProps {
  examDate: string
  now?: Date
  /** "exams" (default), a subject name, or null for a bare "188 days". */
  subject?: string | null
  /** The pill opens the study plan's exam dates (mock top6). */
  to?: string
}

/** Neutral pill; inside 30 days of the exam it turns Tide. Nothing after the exam or on an unreadable date. */
export function CountdownPill({ examDate, now, subject = "exams", to }: CountdownPillProps) {
  const days = daysUntil(examDate, now)
  const text = countdownLabel(days, subject)
  if (text === null) return null
  const tone = countdownTone(examDate, now)
  const inner = (
    <>
      <CalendarGlyph />
      <span>{text}</span>
      {/* The bare "188 days" is the visible label; a reader still needs to hear what the days count down to. */}
      {subject === null && days > 0 ? <span className="sr-only"> to exams</span> : null}
      {to ? <SmallChevron /> : null}
    </>
  )
  return to ? (
    <Link to={to} className="rd-pill" data-tone={tone}>
      {inner}
    </Link>
  ) : (
    <span className="rd-pill" data-tone={tone}>
      {inner}
    </span>
  )
}
