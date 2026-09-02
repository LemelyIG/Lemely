/* Hallmark · pre-emit critique: P4 H4 E5 S4 R3 V4 */
import { Link } from "react-router-dom"
import {
  CaretRight,
  ChalkboardTeacher,
  GraduationCap,
  Ticket,
  UsersFour,
  type Icon,
} from "@phosphor-icons/react"
import { AuthFrame } from "./Login"

/*
 * G-02 · Sign up, role selection (UI spec §G-02; plan Task 14; design spec
 * §4.4 and D7.2).
 *
 * "Branch by role before asking for anything" (spec's own Purpose line). This
 * screen asks nothing and stores nothing: three destinations, a secondary
 * route for someone who already has a code, and a way back to sign in. There
 * is no field and no submission, so there is no failure of its own for
 * `authOutcome.ts` to own, and no loading/empty/error/offline state to
 * design, the same way G-01 (Landing) needed none — "None special" is the
 * honest answer for a screen with no async operation behind it, not an
 * omission.
 *
 * ── Links, not a radio group with a Continue button (Task 14, explicit) ────
 *
 * Each choice is its own `<Link>`, not a selectable option that then needs a
 * second tap to confirm. There is nothing to validate and nothing to hold in
 * state between the tap and the next screen, so a radio-plus-button pattern
 * would spend a second interaction on a decision that only ever has one right
 * answer once made. The card shape reuses the idiom `ChildCard`
 * (`portals/parent/screens/Children.tsx`) already established: a card's full
 * class recipe applied directly to the `<Link>` itself, not the kit's
 * `<Card>` nested inside one, which would draw two borders around the same
 * tap target.
 *
 * ── Parent routes to /login/parent, not a fourth /signup/* (spec, D7.2) ────
 *
 * This is the spec's own exit, stated twice. G-02's "Interactions" line reads
 * "Parent → G-05 (parents authenticate by phone, so they skip the email
 * form)", and the design spec's §3.1 lists "Parent sign-up" as explicitly out
 * of scope: "Nothing changes for them beyond G-02 routing them to
 * /login/parent." There is no parent signup form to route to in the first
 * place — `AuthService` creates the `role=parent` row on first verified OTP
 * (D3.11), so the phone screen this links to (`ParentLogin.tsx`, G-05) *is*
 * the parent's account creation. Sending them anywhere else would be a detour
 * to a form that cannot exist without duplicating that auto-creation here.
 *
 * ── Why the teacher line never mentions a school ────────────────────────────
 *
 * D7.2: "A self-registered teacher is always independent. No school field on
 * the signup form, no `School` row, no membership." The description below is
 * written to stay true on day one for every teacher who taps it, so it
 * promises only what G-03's teacher variant can actually deliver — speed and
 * the final word on a mark (PRODUCT.md's Product Principle 4) — nothing about
 * a roster or a school a self-serve signup never creates.
 *
 * ── Copy is sourced, not invented ───────────────────────────────────────────
 *
 * Every one-liner traces to a claim PRODUCT.md already makes, not a new one
 * coined for this screen: the student line is the core loop (§1.1 and
 * Positioning #1); the teacher line is the "corrects 30 papers in the time it
 * used to take 5" success framing plus the override-authority principle; the
 * parent line reuses the exact idea `ParentLogin.tsx`'s own phone step
 * already states ("No password to remember"), so a parent reading this
 * screen and then G-05 is not told the same fact twice in different words.
 *
 * ── Ordering ─────────────────────────────────────────────────────────────
 *
 * Student, teacher, parent — matching this plan's Task 14, which states that
 * order twice (its bullet list and its routing line). The UI spec's prose
 * lists the three inside one sentence ("student, parent, teacher or tutor"),
 * not as a numbered sequence, and G-02's own spec section never calls visual
 * order a requirement the way it explicitly calls out links-over-radio — so
 * this reads as the plan's ordering choice to honour, not a conflict with the
 * spec to resolve in the spec's favour.
 *
 * ── Frame ────────────────────────────────────────────────────────────────
 *
 * `AuthFrame` (`Login.tsx`) supplies the mark, the paper grain, and the
 * top-biased column every signed-out screen shares; see its own docstring for
 * what a third copy of that markup costs. No `dataPortal` is passed — this
 * screen precedes every portal, the same way `Login` itself carries none.
 */

interface RoleChoice {
  to: string
  icon: Icon
  title: string
  description: string
}

const ROLE_CHOICES: RoleChoice[] = [
  {
    to: "/signup/student",
    icon: GraduationCap,
    title: "I'm a student",
    description:
      "Get your past papers marked like an examiner, and see exactly what to study next.",
  },
  {
    to: "/signup/teacher",
    icon: ChalkboardTeacher,
    title: "I'm a teacher or tutor",
    description: "Mark papers fast, and keep the final say on every grade.",
  },
  {
    // Not a typo: parents never sign up here. See the docstring above — G-05
    // (phone + OTP) both authenticates and creates the account on first
    // verified code, so it is this role's only destination.
    to: "/login/parent",
    icon: UsersFour,
    title: "I'm a parent",
    description: "Check on your child's progress. No password, just your phone number.",
  },
]

/** One large tappable choice. Title and description both sit inside the
 * `<Link>` so a screen reader announces them as one thing — the same
 * composition `ChildCard` uses for "name, then status, then arrow". */
function RoleChoiceLink({ to, icon: Glyph, title, description }: RoleChoice) {
  return (
    <Link
      to={to}
      className="group flex items-start gap-4 rounded-lg border border-rule bg-paper-raised p-6 transition-colors hover:border-rule-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
    >
      <Glyph size={24} className="mt-1 flex-none text-ink-muted" aria-hidden="true" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="text-display-sm text-ink">{title}</div>
        <p className="text-body-md text-ink-muted">{description}</p>
      </div>
      {/* The arrow is what moves on hover, not the whole card (§9.2) — a 1px
          inline shift, transform-only, matching ChildCard's own trailing
          caret rather than inventing a second hover idiom for the same job. */}
      <CaretRight
        size={18}
        className="mt-1 flex-none text-ink-faint transition-transform ease-out-soft group-hover:translate-x-px"
        aria-hidden="true"
      />
    </Link>
  )
}

export function SignupRoleSelect() {
  return (
    <AuthFrame
      footer={
        <p className="text-body-sm text-ink-muted">
          Already have an account?{" "}
          <Link
            to="/login"
            className="rounded-sm text-accent-ink underline underline-offset-2 transition-colors hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          >
            Sign in
          </Link>
        </p>
      }
    >
      <div className="flex w-full max-w-100 flex-col gap-6">
        <div className="flex flex-col gap-1.5">
          <h1 className="text-display-lg text-ink">Tell us who you are</h1>
          <p className="text-body-md text-ink-muted">We'll take it from there.</p>
        </div>

        <div className="flex flex-col gap-3">
          {ROLE_CHOICES.map((choice) => (
            <RoleChoiceLink key={choice.to} {...choice} />
          ))}
        </div>

        {/* Secondary, not a fourth peer of the three choices above: the spec
            calls this a "Secondary link", so it reads smaller and quieter,
            styled after the equivalent utility link in ParentLogin.tsx rather
            than as a fourth role card. */}
        <Link
          to="/join"
          className="flex items-center gap-1.5 self-start rounded-sm pointer-coarse:min-h-11 text-body-sm text-ink-muted transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
        >
          <Ticket size={16} aria-hidden="true" />
          I have an invite code from my school
        </Link>
      </div>
    </AuthFrame>
  )
}
