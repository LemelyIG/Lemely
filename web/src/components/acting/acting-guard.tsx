/* Hallmark · pre-emit critique: P4 H4 E4 S5 R5 V3 */
/*
 * ── The critique those six digits came from ────────────────────────────────
 * Axes are Hallmark's six (Philosophy, Hierarchy, Execution, Specificity, Restraint, Variety).
 * It has no markup of its own; the two panels it chooses between are scored in
 * `acting-unavailable.tsx` from the 380, 768 and 1440 captures (`acting-lead-unavailable`,
 * `acting-no-view`).
 *
 * P · philosophy — 4. One question per screen: can this role work for this lead at all? If not,
 *   say which of the two reasons it is (the lead cannot be reached, or the role cannot see classes)
 *   once, instead of letting every panel below fail in its own words.
 * H · hierarchy — 4. The page content is the default; the panel replaces it only on a refusal.
 * E · execution — 4. Lazy-loaded and used only while acting, so the 150KB entry chunk does not pay
 *   for it; the page content passes through untouched when access is fine.
 * S · specificity — 5. Two reasons, two headings, one button.
 * R · restraint — 5. No retry: neither refusal changes on a second ask.
 * V · variety — 3. A wrapper.
 */
import type { ReactNode } from "react"
import { leadAccess } from "@/lib/actingLeadState"
import type { TeamPermission } from "@/lib/billingTypes"
import { ActingNoViewView, ActingUnavailableView } from "./acting-unavailable"

/**
 * Renders `children` (the page) unless the server refused the lead's class list, in which case it
 * renders the panel that says why. The caller's own pages (team, billing, settings) always render.
 */
export function ActingGuard({
  lead,
  classListError,
  pathname,
  onSwitchBack,
  children,
}: {
  lead: { teacherName: string; permissions: readonly TeamPermission[] }
  classListError: unknown
  pathname: string
  onSwitchBack: () => void
  children: ReactNode
}) {
  const access = leadAccess(lead, classListError, pathname)
  if (access === "unavailable") return <ActingUnavailableView leadName={lead.teacherName} onSwitchBack={onSwitchBack} />
  if (access === "no-view") return <ActingNoViewView leadName={lead.teacherName} onSwitchBack={onSwitchBack} />
  return <>{children}</>
}
