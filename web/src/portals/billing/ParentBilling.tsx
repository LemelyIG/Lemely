import { CaretRight } from "@phosphor-icons/react"
import { Link, useParams } from "react-router-dom"
import { billingPaths } from "@/lib/billingPaths"
import { useChildren } from "@/lib/hooks/useParentApi"
import { AutoTopupCard } from "./AutoTopupCard"
import { BillingOverview } from "./BillingOverview"

/*
 * A parent paying for a linked child (spec §2.1). The child owns the balance; the parent is
 * the payer, so the overview's payer-only actions and receipts appear here, scoped to the
 * child by `beneficiaryId`.
 */

export function ParentChildBilling() {
  const { childId = "" } = useParams<{ childId: string }>()
  const children = useChildren()
  const name = children.data?.children.find((c) => c.childId === childId)?.displayName
  return (
    <BillingOverview
      scope={{ role: "parent", childId }}
      audience="student"
      beneficiaryId={childId}
      heading={name ? `Plan and billing for ${name}` : "Plan and billing"}
      beneficiaryName={name}
      extra={<AutoTopupCard beneficiaryId={childId} audience="student" packsHref={billingPaths({ role: "parent", childId }).packs} />}
    />
  )
}

/** One quiet link on the child overview, beside "Tutoring". */
export function ChildBillingLink({ childId }: { childId: string }) {
  return (
    <Link
      to={billingPaths({ role: "parent", childId }).overview}
      className="mt-1 inline-flex w-fit items-center gap-1.5 rounded-md text-body-md text-on-primary-container underline underline-offset-4 transition-colors hover:text-primary-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-11"
    >
      Plan and billing
      <CaretRight size={14} aria-hidden="true" />
    </Link>
  )
}
