/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 — the name's link covers the whole card and modes carry icon plus word; a generic directory card, so specificity is a 3. */
import { DotsThreeCircle, MapPin, Users, VideoCamera, type Icon } from "@phosphor-icons/react"
import { Link } from "react-router-dom"
import { Card } from "@/components/ui/card"
import { RatingSummary } from "@/components/ui/rating-summary"
import { SubjectTag } from "@/components/ui/subject-tag"
import { cn } from "@/lib/utils"
import type { TutorCard as TutorCardData, TutoringMode } from "@/lib/tutoringTypes"

/*
 * C-23 Tutor card (SPEC §d). One tutor in the directory: public name, headline,
 * rating (C-22), subject tags, the ways they meet (icon plus word, never an icon
 * alone) and the area.
 *
 * It shows only what the open web may see (`TutorCard`, decision-log row 5b), so
 * the same card is safe on G-16, S-33, P-07 and inside a booking. Every string
 * comes from the API as plain text and React renders it as text: a headline is
 * never parsed for links or markup (SC-7).
 *
 * When `to` is given the name is the link and its hit area is stretched over the
 * whole card, so the card is one target, not a card with a small link inside it.
 * Without `to` it is a static card (a booking's tutor, the profile header).
 */

const MODE: Record<TutoringMode, { label: string; icon: Icon }> = {
  virtual: { label: "Virtual", icon: VideoCamera },
  in_person: { label: "In person", icon: Users },
  other: { label: "Other", icon: DotsThreeCircle },
}

export interface TutorCardProps {
  tutor: TutorCardData
  /** Where the card goes when pressed. Omit for a static card. */
  to?: string
  /** The heading element for the tutor's name, to fit the page's outline. */
  headingAs?: "h2" | "h3" | "h4"
  className?: string
}

export function TutorCard({ tutor, to, headingAs: Heading = "h3", className }: TutorCardProps) {
  return (
    <Card
      className={cn(
        "relative flex flex-col gap-3 p-5",
        "transition-colors duration-[var(--dur-instant)] ease-out-soft",
        to && "hover:border-rule-strong focus-within:border-rule-strong active:bg-paper-sunk",
        className,
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
        <Heading className="m-0 min-w-0 text-display-sm text-ink">
          {to ? (
            <Link to={to} className="after:absolute after:inset-0">
              {tutor.publicName}
            </Link>
          ) : (
            tutor.publicName
          )}
        </Heading>
        <RatingSummary rating={tutor.rating} />
      </div>

      <p className="m-0 line-clamp-2 text-body-md text-ink-muted">{tutor.headline}</p>

      <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0" aria-label="Subjects">
        {tutor.subjects.map((subject) => (
          <li key={subject.code}>
            <SubjectTag subject={subject.name} />
          </li>
        ))}
      </ul>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-body-sm text-ink-muted">
        <ul className="m-0 flex list-none flex-wrap gap-x-3 gap-y-1 p-0" aria-label="Ways to meet">
          {tutor.modes.map((mode) => {
            const { label, icon: ModeIcon } = MODE[mode]
            return (
              <li key={mode} className="flex items-center gap-1">
                <ModeIcon size={14} aria-hidden />
                {label}
              </li>
            )
          })}
        </ul>
        <span className="flex items-center gap-1">
          <MapPin size={14} aria-hidden />
          <span className="sr-only">Area: </span>
          {tutor.area.name}
        </span>
      </div>
    </Card>
  )
}
