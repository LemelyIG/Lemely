import { describe, expect, it } from "vitest"

import { studentOnboardingRedirect } from "@/portals/student"

/*
 * D7.9 · the student onboarding gate, pinned in both directions.
 *
 * The wizard at `/student/onboard` is fully built and was, before this,
 * reachable from exactly one place — an action button on Announcements.
 * Every downstream surface (study plan, placement invites, subject pages,
 * the exam calendar) reads enrolment data that only onboarding writes, so a
 * student who never finds that button meets correctly-empty screens
 * everywhere and reasonably concludes the product is broken. That is the
 * defect this gate exists to close.
 *
 * The states below are not four equally-likely cases pointed at one
 * function for coverage's sake. Two of them exist specifically to disprove
 * a gate that looks right but fires on the wrong thing: a gate that
 * redirects a resolved-and-incomplete profile is the easy half to write and
 * the easy half to demo. A gate that does NOT also fire while the query is
 * still pending, or after it has errored, is the half that keeps a
 * returning, already-onboarded student's cold load — or a
 * `/me/student-profile` hiccup — from bouncing them into onboarding they
 * either finished already or never got a chance to load. An assertion
 * written only for "should redirect" is a gate that could be permanently
 * closed (redirect unconditionally) and still pass every test in this file
 * but that one, which is exactly the shape of bug D7.9's own risk register
 * calls out by name. Every branch below is therefore asserted against the
 * specific input that would make a wrong implementation redirect.
 */
describe("studentOnboardingRedirect — D7.9", () => {
  const ELSEWHERE = "/student"
  const ONBOARD = "/student/onboard"

  it("1. does not redirect while the profile query is pending", () => {
    // The dangerous wrong implementation here is one that reads
    // `onboardingCompletedAt` before checking `status`, since a query with
    // no data yet and a query that resolved to "not onboarded" both look
    // like `null`/`undefined` to a careless `== null` check. `status` must
    // be the thing that decides. `StudentLayout` never even calls this
    // function while pending (it returns the route fallback first), but the
    // function's own contract has to hold regardless of who calls it or in
    // what order — that is the entire reason it takes `status` explicitly
    // rather than inferring "resolved" from the shape of a value.
    expect(studentOnboardingRedirect("pending", null, ELSEWHERE)).toBeNull()
  })

  it("2. does not redirect when the profile query has errored", () => {
    // Same defence, same reason: a profile-endpoint hiccup must degrade to
    // "the portal renders as normal", never to "the account is stuck on
    // /student/onboard until the network recovers".
    expect(studentOnboardingRedirect("error", null, ELSEWHERE)).toBeNull()
  })

  it("3. does not redirect once onboarding is complete", () => {
    expect(studentOnboardingRedirect("success", "2026-08-20T09:00:00Z", ELSEWHERE)).toBeNull()
  })

  it("4. redirects a resolved, incomplete profile to /student/onboard", () => {
    expect(studentOnboardingRedirect("success", null, ELSEWHERE)).toBe(ONBOARD)
  })

  /*
   * Not one of the plan's four named states, but the same "both directions"
   * discipline applied to the third guard in `studentOnboardingRedirect`
   * (the pathname check), and it is what makes the gate a redirect rather
   * than a trap. Without it, a resolved-and-incomplete student standing ON
   * `/student/onboard` — which is every such student, immediately after the
   * gate above has already sent them there once — would be told to redirect
   * to the exact page they are already on, on every render. `replace`
   * doesn't turn that into an error React Router surfaces; it just re-fires
   * silently, and a screen re-navigating to itself is not a screen its own
   * "Skip for now" control (per-question, inside the wizard — see
   * `screens/Onboarding.tsx`) can be trusted to work on.
   */
  it("does not redirect a resolved, incomplete profile that is already on /student/onboard", () => {
    expect(studentOnboardingRedirect("success", null, ONBOARD)).toBeNull()
  })

  it("redirects from anywhere in the portal, matching D7.9's own wording ('from anywhere')", () => {
    for (const pathname of [
      "/student",
      "/student/board",
      "/student/subject/0625",
      "/student/plan/0625",
      "/student/correct",
      "/student/friends",
    ]) {
      expect(studentOnboardingRedirect("success", null, pathname), pathname).toBe(ONBOARD)
    }
  })
})
