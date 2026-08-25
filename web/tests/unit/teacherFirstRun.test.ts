import { describe, expect, it } from "vitest"

import { teacherFirstClassRedirect } from "@/portals/teacher"

/*
 * D7.10 · the teacher first-class gate, pinned in both directions — the
 * role-symmetric counterpart to `onboardingGate.test.ts` (D7.9). A freshly
 * self-registered independent teacher (D7.1/D7.2) lands on a dashboard with
 * no classes, no students and no papers: every panel is correctly empty,
 * which on screen is indistinguishable from a broken product. Worse, the
 * review queue, the at-risk list and class analytics have nothing to scope
 * to without a class, and the join code a teacher needs to hand to students
 * does not exist until one does. That is the defect this gate exists to
 * close, by sending a zero-class teacher to `/teacher/first-class` instead.
 *
 * As with D7.9, the four states below are not four equally-likely cases
 * gathered for coverage's sake. Two of them exist specifically to disprove a
 * gate that looks right but fires on the wrong thing: a gate that redirects
 * a resolved, empty class list is the easy half to write and the easy half
 * to demo. A gate that does NOT also fire while the query is still pending,
 * or after it has errored, is the half that keeps a returning teacher with
 * real classes from being bounced into the create-first-class step on every
 * cold load, or trapped there whenever `GET /teacher/classes` hiccups. An
 * assertion written only for "should redirect" is a gate that could be
 * permanently closed (redirect unconditionally) and still pass every test in
 * this file but that one. Every branch below is therefore asserted against
 * the specific input that would make a wrong implementation redirect.
 */
describe("teacherFirstClassRedirect — D7.10", () => {
  const ELSEWHERE = "/teacher"
  const FIRST_CLASS = "/teacher/first-class"

  it("1. does not redirect while the classes query is pending", () => {
    // The dangerous wrong implementation here is one that reads `classCount`
    // before checking `status`, since a query with no data yet and a query
    // that resolved to zero classes both look like "0" to a careless check.
    // `status` must be the thing that decides — `TeacherLayout` never even
    // calls this function while pending (it returns the route fallback
    // first, see `../../src/portals/teacher/index.tsx`), but the function's
    // own contract has to hold regardless of who calls it or in what order,
    // which is exactly why it takes `status` explicitly rather than
    // inferring "resolved" from the shape of a count.
    expect(teacherFirstClassRedirect("pending", 0, ELSEWHERE)).toBeNull()
  })

  it("2. does not redirect when the classes query has errored", () => {
    // Same defence, same reason: a `/teacher/classes` hiccup must degrade to
    // "the portal renders as normal", never to "the account is stuck on the
    // first-class step until the network recovers".
    expect(teacherFirstClassRedirect("error", 0, ELSEWHERE)).toBeNull()
  })

  it("3. does not redirect once the teacher has at least one class", () => {
    expect(teacherFirstClassRedirect("success", 1, ELSEWHERE)).toBeNull()
  })

  it("does not redirect with many classes either", () => {
    // Not one of the four named states, but the same "don't fire on a value
    // that merely isn't zero" discipline applied at the other end of the
    // range — a boundary bug at classCount === 1 would not show up above.
    expect(teacherFirstClassRedirect("success", 12, ELSEWHERE)).toBeNull()
  })

  it("4. redirects a resolved, empty class list to /teacher/first-class", () => {
    expect(teacherFirstClassRedirect("success", 0, ELSEWHERE)).toBe(FIRST_CLASS)
  })

  /*
   * Not one of the plan's four named states, but the same "both directions"
   * discipline applied to the third guard in `teacherFirstClassRedirect`
   * (the pathname check), and it is what makes the gate a redirect rather
   * than a trap. Without it, a resolved, still-empty teacher standing ON
   * `/teacher/first-class` — which is every such teacher, immediately after
   * the gate above has already sent them there once — would be told to
   * redirect to the exact page they are already on, on every render.
   * `replace` doesn't turn that into an error React Router surfaces; it just
   * re-fires silently, and a screen re-navigating to itself is not a screen
   * its own create-class form can be trusted to work on.
   */
  it("does not redirect a resolved, empty class list that is already on /teacher/first-class", () => {
    expect(teacherFirstClassRedirect("success", 0, FIRST_CLASS)).toBeNull()
  })

  it("redirects from anywhere in the portal, matching D7.10's rationale that every other teacher screen has nothing to scope to without a class", () => {
    for (const pathname of [
      "/teacher",
      "/teacher/grading",
      "/teacher/review",
      "/teacher/classes",
      "/teacher/at-risk",
      "/teacher/schemes",
      "/teacher/quizzes",
      "/teacher/announcements",
    ]) {
      expect(teacherFirstClassRedirect("success", 0, pathname), pathname).toBe(FIRST_CLASS)
    }
  })

  /*
   * `/teacher/first-class` stays reachable even for a teacher who is not
   * being gated to it — see the routing comment in `../../src/portals/teacher/
   * index.tsx`: this function only ever decides whether to send a teacher
   * *to* the step, it does not gate the step itself. A teacher opening it
   * directly (e.g. to create a second class the same way) with classes
   * already on the books must not be bounced elsewhere.
   */
  it("does not redirect away from /teacher/first-class when classes already exist", () => {
    expect(teacherFirstClassRedirect("success", 3, FIRST_CLASS)).toBeNull()
  })
})
