import type { Crumb } from "@/components/ui/breadcrumbs"

/*
 * Pure parent shell logic (F1). The four tabs come from the approved parent mock
 * (student-r2/pa.js `ptab`); the trail is ParentTrail's rules, moved out of the
 * old header so the shared shell's top bar can render it.
 */

export type ParentTabId = "overview" | "topics" | "inbox" | "tutoring"

export interface ParentTab {
  id: ParentTabId
  label: string
  to: string
  end: boolean
}

const childBase = (childId: string) => `/parent/children/${encodeURIComponent(childId)}`

/** With no child (none linked yet, or still loading) the child tabs go to the children list, matched exactly. */
export function parentTabs(childId: string | null): ParentTab[] {
  const base = childId ? childBase(childId) : null
  return [
    { id: "overview", label: "Overview", to: base ?? "/parent", end: true },
    { id: "topics", label: "Topics", to: base ? `${base}/topics` : "/parent", end: !base },
    { id: "inbox", label: "Inbox", to: "/parent/notifications", end: false },
    { id: "tutoring", label: "Tutoring", to: base ? `${base}/tutoring` : "/parent", end: !base },
  ]
}

/** The child the tabs follow: the URL's, else the last one viewed, else the first linked child. */
export function resolveChildId(param: string | null, childIds: readonly string[], last: string | null): string | null {
  if (param) return param
  if (last && childIds.includes(last)) return last
  return childIds[0] ?? null
}

const clean = (path: string) => path.replace(/\/+$/, "") || "/"

export function topicsActive(path: string): boolean {
  return /\/(topics|weaknesses)$/.test(clean(path))
}

export function parentShellTrail(
  path: string,
  { childId, hasChildList, subjectLabel }: { childId: string | null; hasChildList: boolean; subjectLabel: string | null },
): Crumb[] {
  if (!childId) return []
  const p = clean(path)
  const overview = childBase(childId)
  const trail: Crumb[] = hasChildList ? [{ label: "Your children", to: "/parent" }] : []
  if (p === overview) trail.push({ label: "Overview" })
  else if (topicsActive(p)) trail.push({ label: "Overview", to: overview }, { label: "Topics" })
  else if (p.endsWith("/tutoring")) trail.push({ label: "Overview", to: overview }, { label: "Tutoring" })
  else if (p.endsWith("/tutor-access"))
    trail.push({ label: "Overview", to: overview }, { label: "Tutoring", to: `${overview}/tutoring` }, { label: "Who they share with" })
  else if (/\/sessions\/[^/]+$/.test(p))
    trail.push({ label: "Overview", to: overview }, { label: "Tutoring", to: `${overview}/tutoring` }, { label: "Session" })
  else if (/\/subjects\/([^/]+)$/.test(p)) {
    const code = decodeURIComponent(p.split("/").pop() ?? "")
    trail.push({ label: "Overview", to: overview }, { label: subjectLabel ?? (code || "This subject") })
  } else trail.push({ label: "Overview", to: overview })
  return trail
}

/** The top bar title; route handle titles where they exist, the subject's name on a subject page. */
export function parentPageTitle(path: string, subjectLabel: string | null): string {
  const p = clean(path)
  if (p === "/parent") return "Your children"
  if (p === "/parent/notifications") return "Notifications"
  if (p === "/parent/tutors") return "Tutors"
  if (/^\/parent\/tutors\/[^/]+\/book$/.test(p)) return "Book a session"
  if (/^\/parent\/tutors\/[^/]+$/.test(p)) return "Tutor profile"
  if (/^\/parent\/children\/[^/]+$/.test(p)) return "Overview"
  if (topicsActive(p)) return "Topics to work on"
  if (p.endsWith("/tutor-access")) return "Who they share with"
  if (p.endsWith("/tutoring")) return "Tutoring"
  if (/\/sessions\/[^/]+$/.test(p)) return "Session details"
  const subject = p.match(/\/subjects\/([^/]+)$/)
  if (subject) return subjectLabel ?? decodeURIComponent(subject[1])
  return "Page not found"
}

const KEPT_TAILS = ["/topics", "/weaknesses", "/tutoring", "/tutor-access"]

/** Switching child keeps the parent's place where the path still makes sense; a subject the other child does not take would 404, so it lands on the overview. */
export function switchChildPath(pathname: string, nextChildId: string): string {
  const tail = KEPT_TAILS.find((t) => clean(pathname).endsWith(t)) ?? ""
  return `${childBase(nextChildId)}${tail}`
}
