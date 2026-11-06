import { billingPaths } from "@/lib/billingPaths"
import { AutoTopupCard } from "./AutoTopupCard"
import { BillingOverview } from "./BillingOverview"

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
    <BillingOverview
      scope={{ role: "teacher" }}
      audience="teacher"
      beneficiaryId={null}
      heading="Plan and billing"
      extra={<AutoTopupCard beneficiaryId={null} audience="teacher" packsHref={billingPaths({ role: "teacher" }).packs} />}
    />
  )
}
