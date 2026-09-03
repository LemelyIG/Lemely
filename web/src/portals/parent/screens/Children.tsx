/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { Link, Navigate } from "react-router-dom"
import { CaretRight, TrendDown, TrendUp } from "@phosphor-icons/react"
import { useChildren } from "@/lib/hooks/useParentApi"
import { QueryState } from "@/components/ui/query-state"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { parentLoadFailureMessage } from "@/lib/parentOutcome"
import { relativeTime } from "@/lib/utils"
import type { ChildSummary } from "@/lib/parentTypes"

/*
 * P-01 · Parent home / children.
 *
 * One card per linked child: name, their classes, the backend's plain-language
 * status line, trend, and last activity. Every value is rendered as the backend
 * supplied it — `statusLine` in particular is composed server-side
 * (`parent.py::_status_line`) from the child's real grade-bearing records and
 * fired at-risk rules, so it is displayed verbatim rather than reassembled from
 * parts here. A second client-side phrasing would be a second source for the
 * same claim, which is how the "same label, two numbers" divergence
 * D3.3/D3.4/D3.5 each had to fix once gets started.
 */

/** Spec: "If only one child, skip straight to P-02 and keep this as a switcher
 * in the header." The switcher lives in the shell (`../index.tsx`) and hides
 * itself at one child — there is nothing to switch between — so this screen is
 * simply not a stop on the journey for a single-child parent. */
function trendLabel(trend: number | null): { text: string; up: boolean } | null {
  if (trend === null || trend === 0) return null
  const rounded = Math.round(Math.abs(trend))
  // A sub-1pp move rounds to "0 points", which reads as no change while
  // claiming a direction. Below the rounding floor, say nothing.
  if (rounded === 0) return null
  return {
    text: `${trend > 0 ? "Up" : "Down"} ${rounded} points on their last paper`,
    up: trend > 0,
  }
}

function ChildCard({ child }: { child: ChildSummary }) {
  const trend = trendLabel(child.trend)

  return (
    <Link
      to={`/parent/children/${child.childId}`}
      className="group flex items-start gap-4 rounded-lg border border-rule bg-paper-raised p-6 transition-colors hover:border-rule-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
    >
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="text-display-sm text-ink">{child.displayName}</div>

        {child.classes.length > 0 ? (
          <div className="text-body-sm text-ink-faint">
            {child.classes
              .map((c) => (c.schoolName ? `${c.name} · ${c.schoolName}` : c.name))
              .join(" · ")}
          </div>
        ) : null}

        <p className="text-body-md text-ink">{child.statusLine}</p>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-body-sm text-ink-muted">
          {trend ? (
            // Direction is never colour alone: the icon differs in shape and
            // the sentence names it ("Up" / "Down") in words.
            <span className="flex items-center gap-1.5">
              {trend.up ? (
                <TrendUp size={15} className="text-ok" aria-hidden="true" />
              ) : (
                <TrendDown size={15} className="text-warn" aria-hidden="true" />
              )}
              {trend.text}
            </span>
          ) : null}
          {/* null means "never active", which is not "active 0 days ago". */}
          <span>
            {child.lastActivityAt
              ? `Last worked ${relativeTime(child.lastActivityAt)}`
              : "No work recorded yet"}
          </span>
        </div>
      </div>
      {/* 1px inline shift on hover, per §9.2 — transform and colour only, and
          the arrow is the thing that moves rather than the whole card, so a
          long status line never reflows under the pointer. */}
      <CaretRight
        size={18}
        className="mt-1 flex-none text-ink-faint transition-transform ease-out-soft group-hover:translate-x-px"
        aria-hidden="true"
      />
    </Link>
  )
}

/**
 * The no-children state. The spec is explicit that this must "explain how to
 * link (invite from the child, or via the school) rather than showing an empty
 * list", and P3.6 chunk a deliberately shipped the API returning a plain empty
 * list with no copy, handing that explanation here.
 *
 * The flow described is D3.11's real one and nothing else: the parent logs in
 * by phone **first** (they just did — that is why they are reading this), and
 * then the child sends the invite from their own account. There is no
 * parent-initiated request to offer, because no such route exists; inventing a
 * "Request access" button that posts nowhere would be the exact failure mode
 * this build has fixed repeatedly.
 *
 * "Or via the school" is likewise omitted rather than stubbed — D3.11 rejected
 * school-side linking outright (no school child-registry surface exists), so
 * naming it here would promise a path a parent cannot take.
 *
 * P3.2 reviewed this as the parent role's first-run flow and deliberately left
 * its structure alone. It is already the composed getting-started view that
 * phase asks for, and it does NOT become the shared `GettingStarted` component
 * the student and teacher dashboards now use: that component models steps the
 * reader performs, each with a route to go to, and every step here is an action
 * somebody else takes on another device. Forcing it into a shape built around
 * "here is your next button" would mean either three inert steps or three
 * buttons that go nowhere.
 *
 * Step 2 says "the number you signed in with" rather than printing it back.
 * `ProfileDTO` carries no phone, and adding one to `/api/me/profile` to
 * sharpen a line of copy would put a second source beside the OTP flow that
 * already owns that fact — the same call P3.8 chunk d made about school
 * memberships. The parent typed the number moments ago; the generic phrasing
 * costs them nothing.
 *
 * P4.6 changed the surface and not the structure: tokens, the margin rule
 * (§8.5), the step numbers on the data face, and one line of Caveat marginalia
 * (§12). The marginalia is the only decorative element and it carries nothing:
 * remove it and the screen still says everything it said.
 */
function NoChildrenLinked() {
  return (
    <div className="mx-auto flex max-w-140 flex-col gap-6 rounded-lg border border-rule bg-paper-raised p-8">
      <div className="margin-rule flex flex-col gap-2">
        <p className="text-hand text-ink-muted">Almost there</p>
        {/* `h1`, not `h2`: in this state it IS the page's heading, and there is
            no other one on the screen — so as an `h2` the empty state shipped
            with no level-one heading at all (axe `page-has-heading-one`, found
            by P3.10 chunk e2a's per-state pass). */}
        <h1 className="text-display-lg text-ink">You're signed in. One step to go.</h1>
        <p className="text-body-md text-ink-muted">
          Nobody has shared their results with you yet. Your child adds you from their own
          Lemely account, so they stay in control of who sees their marks.
        </p>
      </div>

      <ol className="flex flex-col gap-4">
        {[
          "Ask your child to open Lemely and sign in.",
          "In their account, they add a parent using the phone number you just signed in with.",
          "Their results appear here straight away. There is no code to enter and nothing to accept.",
        ].map((step, index) => (
          <li key={index} className="flex items-start gap-3">
            <span
              aria-hidden="true"
              className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-accent-wash text-data-sm text-accent-ink"
            >
              {index + 1}
            </span>
            <span className="text-body-md text-ink">{step}</span>
          </li>
        ))}
      </ol>

      <p className="rounded-md bg-paper-sunk p-4 text-body-sm text-ink-muted">
        Signing in first is what makes this work. Your child can only add a parent who
        already has an account, so nobody can be added by mistake.
      </p>
    </div>
  )
}

export function Children() {
  const query = useChildren()

  return (
    <div className="flex flex-col gap-6">
      <QueryState
        query={query}
        srHeading="Your children"
        // Skeletons, not a line of text (§12): the shape below is the heading plus
        // the card list this screen resolves to, so nothing jumps when it arrives.
        skeleton={
          <>
            <PageHeaderSkeleton />
            <ListSkeleton rows={2} />
          </>
        }
        error={{ heading: "We couldn't load your children", body: parentLoadFailureMessage }}
      >
        {(data) => {
          const children = data.children

          // Spec: one child → skip this screen entirely. `replace` so the browser
          // back button returns to where the parent actually came from rather than
          // bouncing through a list they never saw. Stays inside `children` rather
          // than `QueryState`'s `isEmpty`/`empty` (which only cover a single empty
          // treatment): this screen branches three ways on the loaded payload —
          // redirect, the no-children explainer, or the list — and only the last
          // is this component's own render.
          if (children.length === 1) {
            return <Navigate to={`/parent/children/${children[0].childId}`} replace />
          }

          if (children.length === 0) {
            return <NoChildrenLinked />
          }

          return (
            <>
              <div className="margin-rule flex flex-col gap-1">
                <h1 className="text-display-lg text-ink">Your children</h1>
                <p className="text-body-md text-ink-muted">Tap a name to see how they're doing.</p>
              </div>
              <div className="flex flex-col gap-3">
                {children.map((child) => (
                  <ChildCard key={child.childId} child={child} />
                ))}
              </div>
            </>
          )
        }}
      </QueryState>
    </div>
  )
}
