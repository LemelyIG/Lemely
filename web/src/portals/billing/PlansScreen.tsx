import { useParams } from "react-router-dom"
import { PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { billingPaths, type BillingScope } from "@/lib/billingPaths"
import { isLiveSubscription } from "@/lib/billingFormat"
import type { Audience } from "@/lib/billingTypes"
import { useBillingSummary } from "@/lib/hooks/useBillingApi"
import { PlansView } from "./PlansView"

/*
 * Route wrappers around `PlansView`: which audience, whose account, and where "back to
 * billing" is. A parent buys student plans for a linked child (spec §2.1); the backend
 * re-checks the `parent_child_links` relationship on every checkout.
 */

function SignedInPlans({ scope, audience, beneficiaryId }: { scope: BillingScope; audience: Audience; beneficiaryId: string | null }) {
  const summary = useBillingSummary(beneficiaryId)
  const paths = billingPaths(scope)
  return (
    <div className="flex flex-col gap-6">
      <h1 className="m-0 text-display-md text-on-surface">Plans and credits</h1>
      <QueryState
        query={summary}
        skeleton={<PageHeaderSkeleton />}
        error={{ heading: "Couldn't load your billing" }}
      >
        {(s) => (
          <>
            {beneficiaryId !== null && s.beneficiary.displayName ? (
              <p className="m-0 text-body-md text-on-surface-variant">Plans and credits for {s.beneficiary.displayName}.</p>
            ) : null}
            <PlansView
              audience={audience}
              beneficiaryId={beneficiaryId}
              paths={paths}
              currentTierId={isLiveSubscription(s.subscription?.status) ? (s.subscription?.tier.id ?? null) : null}
              hasLiveSubscription={isLiveSubscription(s.subscription?.status)}
              canManage={s.canManage}
              managedByName={s.managedByName}
            />
          </>
        )}
      </QueryState>
    </div>
  )
}

export function StudentPlans() {
  return <SignedInPlans scope={{ role: "student" }} audience="student" beneficiaryId={null} />
}

export function TeacherPlans() {
  return <SignedInPlans scope={{ role: "teacher" }} audience="teacher" beneficiaryId={null} />
}

export function ParentChildPlans() {
  const { childId = "" } = useParams<{ childId: string }>()
  return <SignedInPlans scope={{ role: "parent", childId }} audience="student" beneficiaryId={childId} />
}
