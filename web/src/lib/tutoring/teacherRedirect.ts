/*
 * Where the teacher portal's first-class gate (D7.10, `teacherFirstClassRedirect`
 * in `portals/teacher/index.tsx`) stands aside.
 *
 * A tutor is a teacher with no class: a `tutor_profiles` row 1:1 with a teacher
 * user, who may never create one (SPEC decision log). Without this exemption a
 * tutor with zero classes was sent to "Create your first class" from every
 * tutoring screen (T-15 to T-21), so the tutoring product was unreachable.
 *
 * Pure, so the rule is testable without mounting the layout.
 */

const TUTORING_ROOT = "/teacher/tutoring"

/**
 * Whether `pathname` is `/teacher/tutoring` or a path under it. The match is on a
 * whole segment: `/teacher/tutoringx` is not a tutoring path. A trailing slash is
 * ignored and the comparison is case-insensitive, as the router's own matching is.
 */
export function skipsFirstClassRedirect(pathname: string): boolean {
  const path = pathname.toLowerCase()
  return path === TUTORING_ROOT || path.startsWith(`${TUTORING_ROOT}/`)
}
