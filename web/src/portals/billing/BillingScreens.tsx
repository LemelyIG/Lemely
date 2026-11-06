import { BillingOverview } from "./BillingOverview"

/* Route elements for `/student/billing` and `/teacher/billing`. */

export function StudentBilling() {
  return <BillingOverview scope={{ role: "student" }} audience="student" beneficiaryId={null} heading="Plan and billing" />
}

export function TeacherBilling() {
  return <BillingOverview scope={{ role: "teacher" }} audience="teacher" beneficiaryId={null} heading="Plan and billing" />
}
