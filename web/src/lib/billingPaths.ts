/*
 * Where each role's billing screens live. Parents reach a child's billing under the child; the
 * child's usage history has no parent route (M6: `/usage/history` serves the caller only), and
 * receipts belong to the payer, so a parent's receipts are one list across all children.
 */

export type BillingScope = { role: "student" } | { role: "teacher" } | { role: "parent"; childId: string }

export interface BillingPaths {
  overview: string
  plans: string
  packs: string
  history: string | null
  receipts: string
}

export function billingPaths(scope: BillingScope): BillingPaths {
  if (scope.role === "parent") {
    const base = `/parent/children/${scope.childId}/billing`
    return { overview: base, plans: `${base}/plans`, packs: `${base}/plans#packs`, history: null, receipts: "/parent/billing/receipts" }
  }
  const base = `/${scope.role}/billing`
  return { overview: base, plans: `${base}/plans`, packs: `${base}/plans#packs`, history: `${base}/history`, receipts: `${base}/receipts` }
}
