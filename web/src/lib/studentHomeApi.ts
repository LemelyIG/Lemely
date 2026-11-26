import { request } from "@/lib/api"
import type { StudentHome } from "@/lib/studentHomeTypes"

// L1 · student Home hub (`lemely/web/routers/student_home.py`).
export const STUDENT_HOME_PATH = "/student/home"

/** No `fallback`: a failed read must surface as an error the screen renders. */
export function fetchStudentHome(): Promise<StudentHome> {
  return request<StudentHome>(STUDENT_HOME_PATH)
}
