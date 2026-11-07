/*
 * Student portal stub data, ported 1:1 from the Claude Design mock's
 * renderVals() (design/project/Lemely Student.dc.html). Names, numbers and copy
 * are the real content. The mock's raw CSS vars / oklch values are translated to
 * the shared token layer where a semantic token exists; genuine one-off data-viz
 * colours are kept as arbitrary Tailwind classes. Frontend-first: screens render
 * from these constants, no live fetch.
 */

import { CalendarCheck, Gear, GraduationCap, type Icon } from "@phosphor-icons/react"

import type { Crumb } from "@/components/ui/breadcrumbs"
import type { ShellIconName } from "@/components/shell/icons"

/** Semantic colour keys used by data-viz rows/bars, resolved to tokens per use. */
export type VizColor = "accent" | "ok" | "warn" | "t1" | "t2" | "t3"

/* ── Sidebar nav groups ─────────────────────────────────────────────────── */

export interface NavGroup {
  label: string
  items: NavItem[]
}

export interface NavItem {
  to: string
  label: string
  tag?: string
  end?: boolean
  /** A design A shell icon by name, or a Phosphor glyph for rows design A has no icon for. */
  icon: ShellIconName | Icon
}

/** The sidebar rows: design A's four, then the two `develop` rows design A has
 * no place for (Task 0 decision 2; drift logged). */
export const studentNavItems: NavItem[] = [
  { to: "/student", label: "Overview", end: true, icon: "home" },
  { to: "/student/classes", label: "Your classes", icon: "class" },
  { to: "/student/board", label: "Standings", icon: "trophy" },
  { to: "/student/friends", label: "Friends", icon: "friends" },
  { to: "/student/tutors", label: "Tutors", icon: GraduationCap },
  // S-38 ("Tutors & your data") has no nav entry of its own (SPEC C-13); Sessions links to it.
  { to: "/student/sessions", label: "Sessions", icon: CalendarCheck },
]

/** The account panel's links (design A `.as-links`), before Sign out. */
export const studentAccountLinks: NavItem[] = [
  { to: "/student/profile", label: "Your profile", icon: "user" },
  { to: "/student/parents", label: "Your parents", icon: "heart" },
  { to: "/student/recently-deleted", label: "Recently deleted", icon: "trash" },
]

/** The bell panel's footer links (design A `.as-pop-foot`). */
export const studentInboxLinks: NavItem[] = [
  { to: "/student/notifications", label: "All notifications", icon: "bell" },
  { to: "/student/announcements", label: "Announcements", icon: "mega" },
]

export const STUDENT_INBOX_EMPTY = "Nothing yet. Marked papers and messages from your teachers land here."

/**
 * Every destination the student shell links to, grouped by where it sits.
 * `navigation.test.ts` checks each one is a mounted route with a real
 * breadcrumb, so a renamed screen breaks a test rather than a link.
 */
export const navGroups: NavGroup[] = [
  { label: "Sidebar", items: studentNavItems },
  { label: "Account", items: studentAccountLinks },
  { label: "Inbox", items: studentInboxLinks },
  { label: "Marking", items: [{ to: "/student/correct", label: "Upload a paper", icon: "up" }] },
  { label: "Settings", items: [{ to: "/student/settings", label: "Settings", icon: Gear }] },
]

/**
 * The enrolled subject a pathname is currently inside, or null. Drives which
 * subject's accordion row starts open in the sidebar. Mirrors the
 * route-parameter arms `resolveCrumb` below already matches — kept as its
 * own function (not folded into `resolveCrumb`) because it answers a
 * different question ("which subject nav row") than that one does ("what
 * breadcrumb string").
 *
 * Deliberately narrower than a blanket `/student/(practice|flashcards)/`
 * match: `practice/set/:assignmentId`, `practice/result/:assignmentId`,
 * `practice/print/:assignmentId` and `flashcards/review/:subjectCode` all
 * have a non-subject segment in the position a subject code would sit, and
 * the `$`-anchored arms below exclude them rather than misreading that
 * segment as a syllabus code.
 */
export function currentSubjectCode(pathname: string): string | null {
  const exactArms = [
    /^\/student\/subject\/([^/]+)$/,
    /^\/student\/practice\/([^/]+)$/,
    /^\/student\/flashcards\/([^/]+)$/,
  ]
  for (const arm of exactArms) {
    const match = pathname.match(arm)
    if (match) return match[1]
  }
  // Not `$`-anchored: also matches the session sub-route
  // (`plan/:subjectCode/session/:sessionId`), where the subject code is
  // still the segment right after `plan/`.
  const planMatch = pathname.match(/^\/student\/plan\/([^/]+)/)
  return planMatch ? planMatch[1] : null
}

/**
 * Breadcrumb per route path. **Exact pathnames only** — anything with a route
 * parameter in it is resolved by a pattern arm in `resolveCrumb` instead.
 *
 * P3.1 removed four keys from this map: `/student/subject`,
 * `/student/practice`, `/student/flashcards` and `/student/result`. All four
 * were dead lookups. Every one of those routes is parameterised
 * (`subject/:code`, `practice/:subjectCode`, `flashcards/:subjectCode`,
 * `result/:paperId`), so no pathname the router can produce ever equals the
 * bare key, and `resolveCrumb` was already answering all four from its pattern
 * arms below. This is the same defect the note about `/student/plan` describes
 * having deliberately avoided when P4.10 parameterised that route; its four
 * siblings kept theirs. Behaviour is unchanged — unreachable entries cannot
 * change what anything renders — but a map with dead keys in it is a map the
 * next person edits the wrong half of.
 *
 * Found by `tests/unit/navigation.test.ts`, which asserts that every key here
 * matches a route the router actually mounts.
 */
export const crumbs: Record<string, string> = {
  "/student": "Home",
  "/student/correct": "Marking / Correct a paper",
  "/student/classes": "Home / Your classes",
  "/student/tutors": "Home / Tutors",
  "/student/sessions": "Home / Sessions",
  "/student/tutor-access": "Home / Tutors & your data",
  "/student/board": "Home / Standings",
  "/student/friends": "Home / Friends",
  "/student/profile": "Home / Your profile",
  // Absent until P3.1, and silently so: with no nav entry the only way onto
  // this route was a push deep link, and a wrong-but-valid breadcrumb ("Home")
  // trips no typecheck and no axe rule — the exact failure mode `resolveCrumb`
  // is documented below as having already had once. Giving the route a nav
  // entry (D1.3) without giving it a crumb would have repeated it.
  "/student/notifications": "Home / Notifications",
  "/student/announcements": "Home / Announcements",
  "/student/parents": "Home / Your parents",
  "/student/recently-deleted": "Home / Recently deleted",
  "/student/settings": "Home / Settings",
  "/student/settings/devices": "Home / Settings / Account and devices",
  "/student/settings/notifications": "Home / Settings / Notifications",
  "/student/onboard": "Onboarding",
  "/student/landing": "lemely.com",
}

/**
 * Resolve the breadcrumb for a pathname: exact static lookup first (the
 * `crumbs` map), falling back to pattern matching for routes with a dynamic
 * segment that can't be enumerated in that map ahead of time.
 *
 * Lives here rather than in `index.tsx` so it is a pure function the unit
 * suite can exercise. It was unreachable from a test while it sat inside the
 * React module, which is how P4.10's subject-scoped `/student/plan/:code`
 * came to fall through every arm and render a bare "Home": a wrong-but-valid
 * breadcrumb trips no typecheck, no axe rule and no threshold.
 */
export function resolveCrumb(pathname: string): string {
  const exact = crumbs[pathname]
  if (exact) return exact

  // Like a result, a tutor is "This tutor", never an id (S-34, S-35).
  if (/^\/student\/tutors\/[^/]+$/.test(pathname)) return "Home / Tutors / This tutor"
  if (/^\/student\/tutors\/[^/]+\/book$/.test(pathname)) return "Home / Tutors / This tutor / Book"

  // A session's id is never in the crumb (see "This result" below).
  if (/^\/student\/sessions\/[^/]+$/.test(pathname)) return "Home / Sessions / This session"

  const subjectMatch = pathname.match(/^\/student\/subject\/([^/]+)$/)
  if (subjectMatch) return `Home / ${subjectMatch[1]}`

  // "This result", not `Result ${paperId}`. The teacher portal's `resolveTrail`
  // states the rule and a test enforces it there: no crumb interpolates an id,
  // because a UUID in a breadcrumb is noise and fetching a name to replace it
  // would make navigation chrome depend on a request that can lag or fail. The
  // student portal was doing exactly that on `/student/result/:paperId` — the
  // product's flagship screen — and it showed. The header's own comment
  // recorded "Home / Result <uuid>" as the longest string on the row, i.e. the
  // one that forced the responsive fix, without anyone asking what it was for.
  //
  // The subject/practice/flashcard/plan arms below keep their parameter on
  // purpose: a syllabus code is a short, meaningful, reader-facing identifier,
  // which an opaque paper id is not.
  if (/^\/student\/result\/[^/]+$/.test(pathname)) return "Home / This result"

  const practiceGeneratorMatch = pathname.match(/^\/student\/practice\/([^/]+)$/)
  if (practiceGeneratorMatch) return `Home / Practice / ${practiceGeneratorMatch[1]}`

  if (pathname.match(/^\/student\/practice\/set\//)) return "Home / Practice / Set"
  if (pathname.match(/^\/student\/practice\/result\//)) return "Home / Practice / Result"
  if (pathname.match(/^\/student\/practice\/print\//)) return "Home / Practice / Print"

  const flashcardReviewMatch = pathname.match(/^\/student\/flashcards\/review\/([^/]+)$/)
  if (flashcardReviewMatch) return `Home / Flashcards / Review ${flashcardReviewMatch[1]}`

  const flashcardDecksMatch = pathname.match(/^\/student\/flashcards\/([^/]+)$/)
  if (flashcardDecksMatch) return `Home / Flashcards / ${flashcardDecksMatch[1]}`

  // The study plan gained a subject segment in P4.10, so it stopped matching
  // the exact `crumbs` lookup and fell through to the bare "Home" default.
  // The session route needs its own arm for the same reason: `planMatch` is
  // anchored, so S-25 would have repeated the chunk-A defect exactly.
  const planSessionMatch = pathname.match(/^\/student\/plan\/([^/]+)\/session\/([^/]+)$/)
  if (planSessionMatch) return `Home / Study plan / ${planSessionMatch[1]} / Session`

  const planMatch = pathname.match(/^\/student\/plan\/([^/]+)$/)
  if (planMatch) return `Home / Study plan / ${planMatch[1]}`

  return "Home"
}

/**
 * The same breadcrumb as a structured trail, for `<Breadcrumbs>` (P4.1).
 *
 * D1.5 gave the teacher and parent portals a real trail with a working back
 * path. The student portal was left rendering `resolveCrumb`'s flat string as
 * inert mono text, so on every drilled-into student screen — a subject, a
 * result, a practice set, a plan session — the only way back was the browser's
 * own back gesture. That is the exact hole D1.5 was raised to close, and the
 * student portal is the one the mission says lives on a phone, where that
 * gesture is inconsistent across browsers and absent from an installed PWA.
 *
 * Derived from `resolveCrumb` rather than replacing it, deliberately: one
 * function decides what a pathname is called, so the two forms cannot drift
 * into disagreeing about the same route. `resolveCrumb` keeps its exported
 * string contract and its existing tests.
 *
 * Only "Home" is linked. The other leading segments this map produces
 * ("Marking", "Practice", "Flashcards", "Study plan") are grouping labels with
 * no route of their own — `/student/practice` is not a mounted path, and
 * linking it would manufacture a dead end to fix a missing back path.
 * `Breadcrumbs` supports an unlinked intermediate crumb and collapses to the
 * nearest *linked* ancestor below `sm`, so those rows still get a working back
 * tap to Home.
 */
export function resolveCrumbTrail(pathname: string): Crumb[] {
  const parts = resolveCrumb(pathname).split(" / ")
  return parts.map((label, i) => {
    // The page you are already on is never a link (`Breadcrumbs` renders the
    // final crumb as `aria-current`).
    if (i === parts.length - 1) return { label }
    return label === "Home" ? { label, to: "/student" } : { label }
  })
}

const ROOT_CRUMBS = new Set(["Home", "Marking"])

/** The top bar's trail: the crumb trail without its root ("Home" / "Marking"),
 * so a section is one crumb (title only) and only a drilled-in page has
 * breadcrumbs, as design A shows. */
export function studentShellTrail(pathname: string): Crumb[] {
  const trail = resolveCrumbTrail(pathname)
  return ROOT_CRUMBS.has(trail[0]?.label ?? "") ? trail.slice(1) : trail
}

/** The top bar's title. A subject page shows the subject's name when known. */
export function studentPageTitle(pathname: string, subjects: readonly { code: string; name: string }[] = []): string {
  const subject = pathname.match(/^\/student\/subject\/([^/]+)$/)
  if (subject) return subjects.find((s) => s.code === subject[1])?.name ?? subject[1]
  const trail = studentShellTrail(pathname)
  return trail[trail.length - 1]?.label ?? "Overview"
}

/** The line under the student's name (sidebar user block and account panel). */
export function studentDetailLine(qualificationLabel: string | null, subjectCount: number): string {
  const count = subjectCount === 0 ? "no subjects yet" : subjectCount === 1 ? "1 subject" : `${subjectCount} subjects`
  return qualificationLabel ? `${qualificationLabel} · ${count}` : count
}

// `studentName`/`studentMeta` ("Maya Rahman" / "Year 11 - Helwan Science
// Centre") were removed in P3.10 chunk c. They were the student-side twin of
// the fabricated teacher identity P3.7 chunk b deleted, and no field anywhere
// in the API supplies either one. The sidebar now renders the real caller via
// `useProfile()` — see `UserBlock` in `portals/student/index.tsx`.

/* ── Paper Result (flagship) ────────────────────────────────────────────── */

export interface RailTick {
  g: string
  left: number
}

export const railTicks: RailTick[] = [
  { g: "U", left: 6 },
  { g: "E", left: 24 },
  { g: "D", left: 38 },
  { g: "C", left: 52 },
  { g: "B", left: 66 },
  { g: "A", left: 80 },
]

/* ── Correct a paper ────────────────────────────────────────────────────── */

export const reassure: { t: string }[] = [
  // The spaced hyphen here was a dash used as punctuation (audit N1), which
  // the copy gate's own classifier flags. Restructured into two sentences
  // rather than swapped for a middle dot: a dot separates a label from a
  // value, and this is a clause.
  { t: "Multiple choice is matched letter for letter against the official Cambridge scheme. No judgement and no model, just the same answer key a marker would use." },
  { t: "Written answers are marked point by point, and anything the system is unsure about is handed to you rather than guessed at." },
  { t: "Set your own paper and your own mark scheme, and it will be marked to the same standard." },
]

/* ── Landing ────────────────────────────────────────────────────────────── */

/*
 * The landing block moved to `portals/marketing/data.ts` in P4.9, along with
 * the MCQ answer-grid fixture that only the hero card ever consumed.
 *
 * It was never student data. It lived here because the marketing page was
 * mounted inside this portal, behind the student auth guard, where nobody it
 * was written for could read it — the finding written up in
 * `portals/marketing/index.tsx`. Nothing in the student portal imported any of
 * it, which is the tell: a data module for a page that belongs to a different
 * lane. Do not add marketing copy back to this file.
 */

/* ── Directions (A/B/C) ─────────────────────────────────────────────────── */

export const directionsIntro = {
  title: "Three ways to open a result",
  body: "The result header is the emotional moment of the product - it is the screen a student opens after a mock. The app now uses A and B together: the ledger reading, with the boundary rail underneath it. C is kept here as the softest alternative.",
}
