/* Hallmark · pre-emit critique: P3 H4 E4 S3 R5 V3 */
/* Route wiring only: no visible UI of its own, so P/S are inherited from BillingOverview. The two wrappers differ by one prop on purpose; merging them would hide which route owns which audience. */
import { billingPaths } from "@/lib/billingPaths"
import { AutoTopupCard } from "./AutoTopupCard"
import { BillingOverview } from "./BillingOverview"
import { OwnAccountNote } from "@/components/acting/own-account-note"

/* Route elements for `/student/billing` and `/teacher/billing`. */

export function StudentBilling() {
  return (
    <BillingOverview
      scope={{ role: "student" }}
      audience="student"
      beneficiaryId={null}
      heading="Plan and billing"
      extra={<AutoTopupCard beneficiaryId={null} audience="student" packsHref={billingPaths({ role: "student" }).packs} />}
    />
  )
}

export function TeacherBilling() {
  return (
    <>
      {/* Billing is the caller's own account whoever they are working as. */}
      <OwnAccountNote />
      <BillingOverview
        scope={{ role: "teacher" }}
        audience="teacher"
        beneficiaryId={null}
        heading="Plan and billing"
        extra={<AutoTopupCard beneficiaryId={null} audience="teacher" packsHref={billingPaths({ role: "teacher" }).packs} />}
      />
    </>
  )
}
