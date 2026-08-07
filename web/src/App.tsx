import { createBrowserRouter, Navigate } from "react-router-dom"
import { teacherRoute } from "@/portals/teacher"
import { studentRoute } from "@/portals/student"
import { parentRoute } from "@/portals/parent"
import { Login } from "@/portals/auth/Login"
import { ParentLogin } from "@/portals/auth/ParentLogin"
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
