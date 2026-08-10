import { createBrowserRouter, Navigate } from "react-router-dom"
import { teacherRoute } from "@/portals/teacher"
import { studentRoute } from "@/portals/student"
import { parentRoute } from "@/portals/parent"
import { Login } from "@/portals/auth/Login"
import { ParentLogin } from "@/portals/auth/ParentLogin"
import { DeviceSettings } from "@/portals/settings/DeviceSettings"
import { NotificationSettings } from "@/portals/settings/NotificationSettings"
import { useAuth } from "@/lib/auth/AuthContext"
import { RequireAuth, portalPathForRole } from "@/lib/auth/RequireAuth"

/*
 * One role-based app. The Teacher (teal), Student (terracotta) and Parent
 * (muted rose) portals are route subtrees, each owning its own layout, nav and
 * screens. The active portal sets data-portal on its layout root so the token
 * layer swaps accent + neutrals (see index.css).
 *
 * Every portal subtree is gated by RequireAuth: no session -> /login; wrong
 * role for the portal -> the portal that does match. Root "/" and both login
 * routes resolve against the session too (see Root/LoginRoute below).
 */

const STUDENT_ROLES = ["student"] as const
const PARENT_ROLES = ["parent"] as const
/* `parent` was in this list until P3.9 — every /api/teacher/* route is gated
 * teacher+school_admin, so a parent who signed in landed in a console where
 * every panel 403'd. school_admin/platform_admin genuinely hold those roles and
 * stay; their own surfaces (K-01, X-01) are later phases. */
const TEACHER_ROLES = ["teacher", "school_admin", "platform_admin"] as const
/* G-11 is "All" in the UI spec, and the device limit is enforced per account
 * regardless of role, so its guard admits every role and only excludes callers
 * with no session at all. */
const ALL_ROLES = [...STUDENT_ROLES, ...PARENT_ROLES, ...TEACHER_ROLES] as const

function Root() {
  const { session } = useAuth()
  return <Navigate to={session ? portalPathForRole(session.role) : "/login"} replace />
}

function LoginRoute({ children }: { children: React.ReactNode }) {
  const { session } = useAuth()
  if (session) return <Navigate to={portalPathForRole(session.role)} replace />
  return children
}

export const router = createBrowserRouter([
  { path: "/", element: <Root /> },
  { path: "/login", element: <LoginRoute><Login /></LoginRoute> },
  // G-05. A separate route rather than a tab on /login: the parent flow shares
  // no field with email/password, and the spec's whole framing for it is
  // "the lowest-friction entry in the product".
  { path: "/login/parent", element: <LoginRoute><ParentLogin /></LoginRoute> },
  // G-11 (devices section). Top-level rather than inside a portal subtree: the
  // 3-device limit applies to every account, so all five roles reach the same
  // screen — the same reason `/api/me/devices` is role-agnostic (P5.7).
  {
    path: "/settings/devices",
    element: <RequireAuth allowedRoles={ALL_ROLES}><DeviceSettings /></RequireAuth>,
  },
  // G-12. Top-level for the same reason, and one it does not share: the
  // at-risk-alert preference belongs to the **teacher and the parent**
  // (`routers/me.py` gates it to those two roles), so mounting this inside the
  // student portal would have put a toggle out of reach of the only roles it
  // applies to.
  {
    path: "/settings/notifications",
    element: <RequireAuth allowedRoles={ALL_ROLES}><NotificationSettings /></RequireAuth>,
  },
  {
    ...teacherRoute,
    element: <RequireAuth allowedRoles={TEACHER_ROLES}>{teacherRoute.element}</RequireAuth>,
  },
  {
    ...studentRoute,
    element: <RequireAuth allowedRoles={STUDENT_ROLES}>{studentRoute.element}</RequireAuth>,
  },
  {
    ...parentRoute,
    element: <RequireAuth allowedRoles={PARENT_ROLES}>{parentRoute.element}</RequireAuth>,
  },
])
