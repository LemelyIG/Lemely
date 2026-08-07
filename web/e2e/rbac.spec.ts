import { test, expect } from "@playwright/test"
import { readSeed } from "./seed"

const BACKEND_URL = "http://127.0.0.1:8000"

/*
 * Cross-role / cross-tenant denial matrix (BUILD/MISSION.md §4: per-role E2E
 * "student A must 403 on student B's data — assert it"), driven through the
 * real API with the seeded tokens. Real status codes, not just "not 200":
 * `require_role` (lemely/web/deps.py) always 403s an authenticated caller
 * whose role isn't allowed (never 401 — the token itself is valid), and
 * `_authorized_child` (lemely/web/routers/parent.py) 403s a parent reaching
 * a child who exists but isn't linked to them.
 */

test.describe("cross-role denial", () => {
  test("a student token is denied the teacher overview", async ({ playwright }) => {
    const seed = readSeed()
    const request = await playwright.request.newContext()
    const res = await request.get(`${BACKEND_URL}/api/teacher/overview`, {
      headers: { Authorization: `Bearer ${seed.students.declining.accessToken}` },
    })
    expect(res.status()).toBe(403)
    await request.dispose()
  })

  test("a parent token is denied a child they are not linked to", async ({ playwright }) => {
    const seed = readSeed()
    const request = await playwright.request.newContext()
    // "control" is a real, seeded student — just not the parent's linked
    // child (only "declining" is linked, by scripts/seed_e2e.py). A 403
    // here, not a 404, is the documented "exists but not linked" case.
    const res = await request.get(
      `${BACKEND_URL}/api/parent/children/${seed.students.control.userId}`,
      { headers: { Authorization: `Bearer ${seed.parent.accessToken}` } },
    )
    expect(res.status()).toBe(403)
    await request.dispose()
  })

  test("a parent token is denied a teacher route", async ({ playwright }) => {
    const seed = readSeed()
    const request = await playwright.request.newContext()
    const res = await request.get(`${BACKEND_URL}/api/teacher/overview`, {
      headers: { Authorization: `Bearer ${seed.parent.accessToken}` },
    })
    expect(res.status()).toBe(403)
    await request.dispose()
  })

  test("a school_admin token has no view into the teacher's class (strictly teacher_id-scoped)", async ({
    playwright,
  }) => {
    const seed = readSeed()
    const request = await playwright.request.newContext()

    // The school_admin *role* itself is allowed on /api/teacher/classes
    // (require_role admits teacher + school_admin + platform_admin) — this
    // is not a role-gate denial, it's a tenancy-scope one: scripts/
    // seed_e2e.py's `create_class` call passes no schoolId, and this
    // school_admin holds no SchoolMembership anywhere, so
    // ClassService.list_classes (lemely/db/class_repo.py) returns nothing
    // for them — the same "still strictly teacher_id-scoped" property
    // BUILD/STATE.md's P3.8 chunk F2 note records for the quiz-results
        // route (`test_school_admin_has_no_view_into_a_quizs_results`).
    const asAdmin = await request.get(`${BACKEND_URL}/api/teacher/classes`, {
      headers: { Authorization: `Bearer ${seed.schoolAdmin.accessToken}` },
    })
    expect(asAdmin.status()).toBe(200)
    const adminBody = (await asAdmin.json()) as { classes: unknown[] }
    expect(adminBody.classes).toEqual([])

    // Same endpoint, the teacher's own token: their class IS there — proves
    // the empty result above is real tenancy scoping, not a route/seed bug.
    const asTeacher = await request.get(`${BACKEND_URL}/api/teacher/classes`, {
      headers: { Authorization: `Bearer ${seed.teacher.accessToken}` },
    })
    const teacherBody = (await asTeacher.json()) as { classes: { id: string }[] }
    expect(teacherBody.classes.some((c) => c.id === seed.class.classId)).toBe(true)

    await request.dispose()
  })
})
