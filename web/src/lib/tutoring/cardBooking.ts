/*
 * G-16 / G-17 · what a public tutor page offers the reader who opens it.
 *
 * The public card and directory are open to everyone, including people who
 * already have a session. `/login` is wrapped in `LoginRoute`, which sends any
 * live session to its portal root and drops `?next=`, so "Sign in to book" for a
 * signed-in student or parent lost the tutor they had come for. The action
 * therefore depends on the session's role:
 *
 *   - signed out: `/login?next=/student/tutors/{id}` (a parent's login maps that
 *     to the parent's page, `parentNextTarget`);
 *   - student: straight to `/student/tutors/{id}`;
 *   - parent: straight to the parent's page for the same tutor;
 *   - any other role (teacher, school or platform admin): no link, one sentence.
 *
 * Pure, so the node-only runner tests it. The tutor id is the one the screen
 * validated against `classifyTutorPath`; it is checked again here, as a
 * lowercase UUID, because it goes into an address. Nothing else is interpolated,
 * so no input can make an open redirect.
 */

import { parentTutorHref } from "./parentTutoring"
import { PARENT_TUTORS_PATH } from "./parentNext"

const LOWERCASE_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

export const BOOKING_NOT_FOR_ROLE = "Booking is for students and their parents."

export type CardBooking =
  | { kind: "link"; label: "Sign in to book" | "Book a session"; to: string }
  | { kind: "note"; sentence: string }
  | { kind: "none" }

/** The booking action on G-17 for a reader with this role (null: signed out). */
export function cardBookingFor(role: string | null | undefined, tutorId: string): CardBooking {
  if (!LOWERCASE_UUID.test(tutorId)) return { kind: "none" }
  if (role === "student") return { kind: "link", label: "Book a session", to: `/student/tutors/${tutorId}` }
  if (role === "parent") return { kind: "link", label: "Book a session", to: parentTutorHref(tutorId) }
  if (role === null || role === undefined) {
    return {
      kind: "link",
      label: "Sign in to book",
      to: `/login?next=${encodeURIComponent(`/student/tutors/${tutorId}`)}`,
    }
  }
  return { kind: "note", sentence: BOOKING_NOT_FOR_ROLE }
}

export interface DirectoryLink {
  /** True when the reader already has a student or parent session. */
  signedIn: boolean
  to: string
}

/** Where G-16's one link goes: a student's or parent's own directory, otherwise sign-in. */
export function directoryLinkFor(role: string | null | undefined): DirectoryLink {
  if (role === "student") return { signedIn: true, to: "/student/tutors" }
  if (role === "parent") return { signedIn: true, to: PARENT_TUTORS_PATH }
  return { signedIn: false, to: "/login" }
}
