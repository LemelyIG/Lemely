/*
 * TS interfaces mirroring lemely/web/schemas_school.py (camelCase).
 * `/api/school/*` is gated to `school_admin` alone, so — like meTypes.ts and
 * unlike teacherTypes.ts — this module is scoped by role rather than by
 * portal, even though the teacher portal is where it is consumed today
 * (App.tsx routes school_admin into the teacher portal).
 *
 * Only the fields the announcement composer actually needs are mirrored: the
 * seat rows `SeatUsageDTO` also carries belong to a seat-management surface
 * this build has not reached, and mirroring them here would imply a consumer
 * that does not exist.
 */

/** One school the authenticated admin administers, from
 * `GET /api/school/seats` (mirrors the identifying half of `SeatUsageDTO`).
 * Ownership is inherent to the route — it returns only schools the caller
 * holds a `school_admin` membership for, so no school id is ever supplied by
 * the client. */
export interface AdminSchool {
  schoolId: string
  schoolName: string
}

/** Response for `GET /api/school/seats` (mirrors `SeatUsageListDTO`).
 * Empty for an admin who administers nothing — not an error. */
export interface AdminSchoolList {
  schools: AdminSchool[]
}
