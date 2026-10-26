/*
 * T22 · the client half of search indexing for the public tutor pages
 * (decision-log row 17, `docs/tutoring/SPEC.md` §b.5 "Client meta").
 *
 * The edge worker (`web/worker/robots.ts`) decides the `X-Robots-Tag` header
 * for `/tutors` and `/tutors/{id}`; this file decides the `<meta name="robots">`
 * that a crawler which renders JavaScript reads, and it must never say
 * something the header does not:
 *
 *   - G-16, the directory, is always `noindex, follow`. It lists tutors who
 *     opted out of search as well, so it is never indexed; `follow` lets a
 *     crawler reach the cards.
 *   - G-17, a card, is `noindex, nofollow` unless P2 answered with
 *     `indexable === true`, and also while P2 is loading or has failed. When
 *     the card is indexable the worker sends no header, so this returns null
 *     and the page renders no tag. Anything that is not the boolean `true`
 *     fails closed.
 *
 * ── The address guard ───────────────────────────────────────────────────────
 *
 * The worker lets a card be indexed only at the exact path `/tutors/{uuid}`
 * (the lowercase prefix, one segment). Every other path under `/tutors/`
 * (`/tutors/`, `/tutors/{id}/`, an id that is not a UUID) still reaches the
 * worker and gets `noindex, nofollow`. Only a case variant of the
 * prefix, such as `/Tutors`, is outside the worker's route patterns: it is
 * served as a plain static page with no robots header at all. The router is
 * more forgiving than either: it matches all of these spellings. So a page that
 * rendered a card at a variant the worker did not decide would be indexable
 * without the tutor's choice having been asked, or would carry a header that
 * says something the page does not. `classifyTutorPath` therefore answers, for
 * the raw pathname: render, redirect to the canonical spelling, or do not
 * render. The id keeps the case it came with: the worker accepts either case.
 */

/** The directory's tag. Compared with the worker's in `tutoringRobotsMeta.test.ts`. */
export const DIRECTORY_ROBOTS = "noindex, follow"
/** Every tutor page that is not a confirmed indexable card. */
export const NOINDEX_ROBOTS = "noindex, nofollow"

/** G-16: always the same. */
export function robotsForDirectory(): string {
  return DIRECTORY_ROBOTS
}

/** The part of P2's react-query result the tag depends on. */
export interface CardRobotsInput {
  status: "pending" | "error" | "success"
  data?: { indexable?: unknown } | null
}

/**
 * The tag for G-17, or null when the card is indexable and the page renders
 * none (the worker sends no header either). Only `status === "success"` with
 * `data.indexable === true` gets null: a loading or failed lookup, a refused
 * (404) card, an opted-out tutor and any payload that is not exactly `true` all
 * get `noindex, nofollow`.
 */
export function robotsForCard(query: CardRobotsInput): string | null {
  if (query.status === "success" && query.data?.indexable === true) return null
  return NOINDEX_ROBOTS
}

export type TutorPage =
  | { kind: "directory" }
  | { kind: "card"; tutorId: string }
  | { kind: "redirect"; to: string }
  | { kind: "not_found" }

// Exactly the worker's card pattern: one segment of canonical 8-4-4-4-12 hex, either case.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/**
 * What a raw pathname under `/tutors` may render. `directory` and `card` are
 * the two canonical spellings; `redirect` is a variant that names one of them
 * (different case of `tutors`, trailing slashes); everything else, including an
 * id that is not a UUID, is `not_found`. Percent-encoding is never decoded, so
 * an encoded lookalike is `not_found` too.
 */
export function classifyTutorPath(pathname: string): TutorPage {
  if (pathname === "/tutors") return { kind: "directory" }
  const card = /^\/tutors\/([^/]+)$/.exec(pathname)
  if (card && UUID.test(card[1])) return { kind: "card", tutorId: card[1] }

  const trimmed = pathname.replace(/\/+$/, "")
  const segments = trimmed.split("/")
  // ["", "tutors"] or ["", "tutors", id]
  if (segments[0] !== "" || segments[1]?.toLowerCase() !== "tutors") return { kind: "not_found" }
  if (segments.length === 2) return { kind: "redirect", to: "/tutors" }
  if (segments.length === 3 && UUID.test(segments[2])) {
    return { kind: "redirect", to: `/tutors/${segments[2]}` }
  }
  return { kind: "not_found" }
}
