/*
 * TS interfaces mirroring lemely/web/schemas_school.py (camelCase).
 * `/api/school/*` is gated to `school_admin` alone, so — like meTypes.ts and
 * unlike teacherTypes.ts — this module is scoped by role rather than by
 * portal, even though the teacher portal is where it is consumed today
 * (App.tsx routes school_admin into the teacher portal).
 *
 * P4.7 built that seat-management surface (UI spec K-01…K-04), so the seat rows
 * this file's header used to say had no consumer now have one and are mirrored
 * below. The header's rule still holds and is worth keeping: a type here implies
 * a screen that reads it.
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

/** One class, inside this school, a seated student is enrolled in. */
export interface SeatClass {
  classId: string
  name: string
  teacherName: string | null
}

/** One occupied seat and the student on it (K-02).
 *
 * `classes` is a list because a student's enrolment within one school is not
 * exclusive. K-02 asks for a "class" column; the screen renders what is
 * actually there rather than picking a winner.
 *
 * `lastAttemptAt` is **not** "last active", and the column is labelled for what
 * it measures. No table records a session or a login, so the most recent
 * attempt is the only activity signal that exists. */
export interface SeatRow {
  seatId: string
  status: "available" | "assigned" | "revoked"
  assignedUserId: string | null
  assignedEmail: string | null
  assignedDisplayName: string | null
  assignedAt: string | null
  classes: SeatClass[]
  lastAttemptAt: string | null
}

/** A school's seat headroom plus its current (non-revoked) seats. */
export interface SeatUsage {
  schoolId: string
  schoolName: string
  quota: number
  used: number
  available: number
  seats: SeatRow[]
}

/** The full `GET /api/school/seats` payload the seats screen reads. */
export interface SeatUsageList {
  schools: SeatUsage[]
}

/** K-01's headline figures for one school.
 *
 * `averageLatestPercentage` is the mean of each student's latest grade-bearing
 * paper — the identical rule the class screens use, computed by the identical
 * backend function, so a school mean and a class mean cannot mean two different
 * things. `studentsWithAPaper` is its denominator and is rendered beside it: a
 * mean over 3 of 40 students is a different claim from a mean over 40.
 *
 * There is no subscription field. No school-level subscription exists anywhere
 * in the schema, so K-01's "subscription status" line has nothing honest to
 * read and the screen says so rather than inventing one. */
export interface SchoolOverview {
  schoolId: string
  schoolName: string
  quota: number
  seatsUsed: number
  seatsAvailable: number
  teacherCount: number
  classCount: number
  enrolledStudentCount: number
  studentsWithAPaper: number
  averageLatestPercentage: number | null
}

/** Response for `GET /api/school/overview`. */
export interface SchoolOverviewList {
  schools: SchoolOverview[]
}

/** One teacher on a school's staff (K-03). `studentCount` is distinct across
 * their classes here, so a student they teach twice counts once. */
export interface SchoolTeacher {
  userId: string
  email: string
  displayName: string | null
  classCount: number
  studentCount: number
}

/** One school's staff roster. */
export interface SchoolTeacherGroup {
  schoolId: string
  schoolName: string
  teachers: SchoolTeacher[]
}

/** Response for `GET /api/school/teachers`. */
export interface SchoolTeacherList {
  schools: SchoolTeacherGroup[]
}

/** Body for `POST /api/school/seats/invite`. */
export interface InviteStudentRequest {
  schoolId: string
  email: string
  displayName?: string | null
}

/** The created student, plus the one-time password when the backend made one.
 * There is no email provider in v1: the admin conveys it out of band, and the
 * screen shows it once. */
export interface InviteStudentResponse {
  userId: string
  seatId: string
  email: string
  temporaryPassword: string | null
}

/** Body for `POST /api/school/teachers/invite`. */
export interface InviteTeacherRequest {
  schoolId: string
  email: string
  displayName?: string | null
}

/** The created teacher, plus any generated one-time password. */
export interface InviteTeacherResponse {
  userId: string
  email: string
  temporaryPassword: string | null
}

/** Body for `POST /api/school/teachers/{id}/remove`.
 *
 * `reassignToTeacherId` is required whenever the teacher still owns classes;
 * omitting it is a 409 naming the count rather than an orphaning. */
export interface RemoveTeacherRequest {
  schoolId: string
  teacherId: string
  reassignToTeacherId?: string | null
}

/** How much staffing actually moved, so the screen can say so. */
export interface RemoveTeacherResponse {
  classesReassigned: number
}
