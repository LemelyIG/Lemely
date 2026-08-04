import { createBrowserRouter, Navigate } from "react-router-dom"
import { teacherRoute } from "@/portals/teacher"
import { studentRoute } from "@/portals/student"
import { Login } from "@/portals/auth/Login"
import { useAuth } from "@/lib/auth/AuthContext"
import { RequireAuth, portalPathForRole } from "@/lib/auth/RequireAuth"

/*
 * One role-based app. The Teacher (amber) and Student (terracotta) portals are
 * route subtrees, each owning its own layout, nav, screens and stub data. The
 * active portal sets data-portal on its layout root so the token layer swaps
 * accent + neutrals (see index.css).
 *
 * Both portal subtrees are gated by RequireAuth: no session -> /login; wrong
 * role for the portal -> the portal that does match. Root "/" and "/login"
 * resolve against the session too (see Root/LoginRoute below).
 */

const STUDENT_ROLES = ["student"] as const
const TEACHER_ROLES = ["parent", "teacher", "school_admin", "platform_admin"] as const

function Root() {
  const { session } = useAuth()
  return <Navigate to={session ? portalPathForRole(session.role) : "/login"} replace />
}

function LoginRoute() {
  const { session } = useAuth()
  if (session) return <Navigate to={portalPathForRole(session.role)} replace />
  return <Login />
}

export const router = createBrowserRouter([
  { path: "/", element: <Root /> },
  { path: "/login", element: <LoginRoute /> },
  {
    ...teacherRoute,
    element: <RequireAuth allowedRoles={TEACHER_ROLES}>{teacherRoute.element}</RequireAuth>,
  },
  {
    ...studentRoute,
    element: <RequireAuth allowedRoles={STUDENT_ROLES}>{studentRoute.element}</RequireAuth>,
  },
])
