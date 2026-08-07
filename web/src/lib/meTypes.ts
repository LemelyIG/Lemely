/*
 * TS interfaces mirroring lemely/web/schemas_me.py field-for-field (camelCase).
 * `/api/me/*` is reachable by every authenticated role (teacher, student,
 * parent, school_admin, platform_admin) — unlike teacherTypes.ts/studentTypes.ts,
 * this module isn't scoped to one portal.
 */

/**
 * Response for `GET /api/me/profile` (mirrors `ProfileDTO`). `displayName` is
 * nullable — a caller who never set one — and must be rendered as an honest
 * absence (e.g. the email's local part, or the role), never a fabricated name.
 */
export interface Profile {
  displayName: string | null
  email: string
  role: string
}
