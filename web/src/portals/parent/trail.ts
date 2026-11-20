import type { Crumb } from "@/components/ui/breadcrumbs"

/*
 * The payer's receipts sit above any one child, so the child-scoped `ParentTrail` has no
 * `:childId` to hang a trail on. With several children the way back is the list; with one,
 * `/parent` would only redirect to that child, so the trail points at the child's overview
 * instead. While the child list is pending the trail is omitted (a missing crumb for a frame
 * beats one that leads somewhere circular). Any other path is not this arm's: `null`.
 */
export const PARENT_RECEIPTS_PATH = "/parent/billing/receipts"

export function receiptsTrail(pathname: string, children: { childId: string }[] | undefined): Crumb[] | null {
  if (pathname.replace(/\/+$/, "") !== PARENT_RECEIPTS_PATH) return null
  const first = children?.[0]
  if (!first) return null
  const back: Crumb =
    (children?.length ?? 0) > 1
      ? { label: "Your children", to: "/parent" }
      : { label: "Overview", to: `/parent/children/${first.childId}` }
  return [back, { label: "Receipts" }]
}
