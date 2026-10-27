import type { ChildSummary } from "@/lib/parentTypes"
import type { Booking, EffectiveState, Grant } from "@/lib/tutoringTypes"
import { GRANT_STATUS_VIEW, type GrantStatusView } from "./accessView"
import { formatTutorDate } from "./sessionView"

/*
 * T27 · the pure half of the parent's tutoring screens (P-05 child's tutoring,
 * P-06 session detail, P-07 find and book a tutor, P-08 who the child shares
 * progress with; SPEC §d Parent). Nothing here touches the DOM, so the
 * node-only runner tests it (`parentTutoring.test.ts`).
 *
 * ── Three rules this file keeps ─────────────────────────────────────────────
 *
 * 1. The child is always a member of the parent's LINKED LIST. SP6 answers 404
 *    for a hidden tutor and for an unknown child alike, so a free-text or
 *    address-supplied child id would turn "not found" into a guess about which
 *    one it was. `resolveLinkedChild` and `preselectedChild` only ever return
 *    an element of the list they were given; an id that is not in it is
 *    ignored, never trusted.
 * 2. P-08 is read-only and says everything about the child in the third person.
 *    The student's grant sentences ("You stopped sharing") are second person
 *    and carry a stop control; `parentGrantRowView` reuses their icons and
 *    tones and writes its own words, and has no stop field at all.
 * 3. A block is never named. A grant a tutor ended (block, suspension, close)
 *    reads "Sharing ended" in every case, as it does for the student (SPEC
 *    §i.8).
 */

// ── Addresses ──────────────────────────────────────────────────────────────

export const PARENT_TUTORS_PATH = "/parent/tutors"

const enc = encodeURIComponent

/** A tutor's page in the parent shell (P-07), optionally remembering the child (`?child=`). */
export function parentTutorHref(tutorId: string, childId?: string | null): string {
  const base = `${PARENT_TUTORS_PATH}/${enc(tutorId)}`
  return childId ? `${base}?child=${enc(childId)}` : base
}

/** The booking step, optionally with a child already chosen (`?child=`). */
export function parentBookHref(tutorId: string, childId?: string | null): string {
  const base = `${PARENT_TUTORS_PATH}/${enc(tutorId)}/book`
  return childId ? `${base}?child=${enc(childId)}` : base
}

/** The directory, optionally remembering which child the parent is looking for. */
export function parentDirectoryHref(childId?: string | null): string {
  return childId ? `${PARENT_TUTORS_PATH}?child=${enc(childId)}` : PARENT_TUTORS_PATH
}

/** P-05. */
export function parentChildTutoringHref(childId: string): string {
  return `/parent/children/${enc(childId)}/tutoring`
}

/** P-06. */
export function parentSessionHref(childId: string, bookingId: string): string {
  return `/parent/children/${enc(childId)}/sessions/${enc(bookingId)}`
}

/** P-08. */
export function parentTutorAccessHref(childId: string): string {
  return `/parent/children/${enc(childId)}/tutor-access`
}

/**
 * G-17's "Sign in to book" carries `?next=/student/tutors/{id}`, because the
 * public page cannot know who will sign in. `postLoginTarget` keeps a `next`
 * only when it sits inside the signed-in role's own portal, so a parent who
 * followed that link would land on the parent home and lose the tutor. A parent's
 * login maps the student tutor page to the parent's page for the same tutor;
 * every other address is returned as it came (the portal check still applies).
 * Only the exact tutor page maps: the student's booking step is not a parent's.
 */
export function parentNextTarget(next: string | null): string | null {
  if (next === null) return null
  const match = /^\/student\/tutors\/([^/?#]+)$/.exec(next)
  return match ? `${PARENT_TUTORS_PATH}/${match[1]}` : next
}

// ── The linked child ───────────────────────────────────────────────────────

/** The linked child with this id, or null. Never an id the list does not hold. */
export function resolveLinkedChild(children: readonly ChildSummary[], childId: string): ChildSummary | null {
  if (childId === "") return null
  return children.find((child) => child.childId === childId) ?? null
}

/**
 * The child the booking step starts with: the one the address asked for if that
 * child is linked, otherwise the only child if there is exactly one, otherwise
 * nobody (the parent chooses). Always an element of `children`.
 */
export function preselectedChild(children: readonly ChildSummary[], requested: string | null): ChildSummary | null {
  const asked = requested === null ? null : resolveLinkedChild(children, requested)
  if (asked) return asked
  return children.length === 1 ? children[0] : null
}

// ── P-05 · the child's tutors, from bookings ───────────────────────────────

/** A booking that never became a relationship does not make its tutor "the child's tutor". */
const NOT_A_TUTOR: readonly EffectiveState[] = ["declined", "cancelled", "expired"]

export interface ParentTutorRow {
  tutorId: string
  tutorName: string
  href: string
  /** The subjects of their sessions, "Mathematics, Physics". */
  subjectLine: string
}

/**
 * The tutors in these bookings, once each, in the order first seen (pass the
 * newest list first). A tutor whose only bookings were declined, expired or
 * cancelled is left out; a waiting request counts.
 */
export function tutorsFromBookings(bookings: readonly Booking[]): ParentTutorRow[] {
  const byTutor = new Map<string, { name: string; subjects: string[] }>()
  for (const booking of bookings) {
    if (NOT_A_TUTOR.includes(booking.effectiveState)) continue
    const entry = byTutor.get(booking.tutor.tutorId) ?? { name: booking.tutor.publicName, subjects: [] }
    if (!entry.subjects.includes(booking.subject.name)) entry.subjects.push(booking.subject.name)
    byTutor.set(booking.tutor.tutorId, entry)
  }
  return [...byTutor].map(([tutorId, entry]) => ({
    tutorId,
    tutorName: entry.name,
    href: parentTutorHref(tutorId),
    subjectLine: entry.subjects.join(", "),
  }))
}

// ── Fixed copy (SPEC §d P-05 to P-08) ──────────────────────────────────────

export function whoSharesLinkLabel(childName: string): string {
  return `Who ${childName} shares progress with`
}

export function findTutorLinkLabel(childName: string): string {
  return `Find a tutor for ${childName}`
}

export function noSessionsLine(childName: string): string {
  return `${childName} has no tutoring sessions.`
}

/** P-08's line under the heading: the child decides, and a parent can report. */
export function parentSharingLine(childName: string): string {
  return `${childName} decides who can see their progress. Only ${childName} can stop sharing. If something worries you, report it.`
}

export function noGrantsLine(childName: string): string {
  return `${childName} isn't sharing their progress with any tutor.`
}

export function noLogLine(childName: string): string {
  return `No tutor has looked at ${childName}'s progress.`
}

// ── P-08 · a grant row, in the third person ────────────────────────────────

export interface ParentGrantStatusView extends Pick<GrantStatusView, "icon" | "tone" | "live"> {
  label: string
  detail: string
}

export interface ParentGrantRowView {
  grantId: string
  tutorId: string
  tutorName: string
  tutorHref: string
  sinceLine: string
  status: ParentGrantStatusView
  /** The accessible name of the row's Report button. */
  reportLabel: string
}

function statusFor(grant: Pick<Grant, "status">, childName: string): ParentGrantStatusView {
  const base = GRANT_STATUS_VIEW[grant.status]
  const cannotSee = `They can't see ${childName}'s progress through Lemely's tutoring pages.`
  const words: Record<Grant["status"], { label: string; detail: string }> = {
    active: {
      label: "Sharing",
      detail: `This tutor can see ${childName}'s progress through Lemely's tutoring pages.`,
    },
    revoked: { label: "Sharing stopped", detail: cannotSee },
    expired: { label: "Sharing expired", detail: cannotSee },
    blocked: { label: "Sharing ended", detail: `Sharing ended when ${childName} blocked this tutor.` },
    // A tutor-side ending reads one way whatever caused it (SPEC §i.8).
    tutor_unavailable: { label: "Sharing ended", detail: cannotSee },
    tutor_suspended: { label: "Sharing ended", detail: cannotSee },
    tutor_closed: { label: "Sharing ended", detail: cannotSee },
  }
  return { icon: base.icon, tone: base.tone, live: base.live, ...words[grant.status] }
}

/** One of the child's grants as P-08 draws it: read-only, with no way to stop it. */
export function parentGrantRowView(grant: Grant, childName: string): ParentGrantRowView {
  const status = statusFor(grant, childName)
  const since = `Since ${formatTutorDate(grant.createdAt)}`
  const ended = grant.revokedAt !== null && !status.live ? `, ended ${formatTutorDate(grant.revokedAt)}` : ""
  return {
    grantId: grant.grantId,
    tutorId: grant.tutor.tutorId,
    tutorName: grant.tutor.publicName,
    tutorHref: parentTutorHref(grant.tutor.tutorId),
    sinceLine: `${since}${ended}`,
    status,
    reportLabel: `Report ${grant.tutor.publicName}`,
  }
}
