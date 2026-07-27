import { createBrowserRouter, Navigate } from "react-router-dom"
import { teacherRoute } from "@/portals/teacher"
import { studentRoute } from "@/portals/student"

/*
 * One role-based app. The Teacher (amber) and Student (terracotta) portals are
 * route subtrees, each owning its own layout, nav, screens and stub data. The
 * active portal sets data-portal on its layout root so the token layer swaps
 * accent + neutrals (see index.css).
 */
export const router = createBrowserRouter([
  { path: "/", element: <Navigate to="/teacher" replace /> },
  teacherRoute,
  studentRoute,
])
