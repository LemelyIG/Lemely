import { Link, Navigate } from "react-router-dom"
import { CaretRight, TrendDown, TrendUp } from "@phosphor-icons/react"
import { useChildren } from "@/lib/hooks/useParentApi"
import { ErrorState } from "@/components/ui/state-views"
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
      className="flex items-start gap-4 rounded-md border border-border bg-surface p-5 hover:border-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="text-body-lg font-medium text-t1">{child.displayName}</div>

        {child.classes.length > 0 ? (
          <div className="text-body-md text-t2">
            {child.classes
              .map((c) => (c.schoolName ? `${c.name} · ${c.schoolName}` : c.name))
              .join(" · ")}
          </div>
        ) : null}

        <p className="text-body-md text-t1">{child.statusLine}</p>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-body-md text-t2">
          {trend ? (
            <span className="flex items-center gap-1.5">
              {trend.up ? (
                <TrendUp size={15} className="text-ok" />
              ) : (
                <TrendDown size={15} className="text-warn" />
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
      <CaretRight size={18} className="mt-1 flex-none text-t3" aria-hidden="true" />
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
 * Step 2 says "the number you signed in with" rather than printing it back.
 * `ProfileDTO` carries no phone, and adding one to `/api/me/profile` to
 * sharpen a line of copy would put a second source beside the OTP flow that
 * already owns that fact — the same call P3.8 chunk d made about school
 * memberships. The parent typed the number moments ago; the generic phrasing
 * costs them nothing.
 */
function NoChildrenLinked() {
  return (
    <div className="mx-auto flex max-w-140 flex-col gap-5 rounded-md border border-border bg-surface p-6">
      <div className="flex flex-col gap-2">
        <h2 className="text-display-md text-t1">You're signed in — one step to go</h2>
        <p className="text-body-md text-t2">
          Nobody has shared their results with you yet. Your child adds you from their own
          Lemely account, so they stay in control of who sees their marks.
        </p>
      </div>

      <ol className="flex flex-col gap-3">
        {[
          "Ask your child to open Lemely and sign in.",
          "In their account, they add a parent using the phone number you just signed in with.",
          "Their results appear here straight away — no code to enter, nothing to accept.",
        ].map((step, index) => (
          <li key={index} className="flex items-start gap-3">
            <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-accent-subtle text-body-md font-medium text-t1">
              {index + 1}
            </span>
            <span className="text-body-md text-t1">{step}</span>
          </li>
        ))}
      </ol>

      <p className="text-body-md text-t2">
        Signing in first is what makes this work — your child can only add a parent who
        already has an account, so nobody can be added by mistake.
      </p>
    </div>
  )
}

export function Children() {
  const { data, isPending, isError, error } = useChildren()

  if (isPending) {
    return (
      <p role="status" aria-live="polite" className="text-body-md text-t2">
        Loading your children…
      </p>
    )
  }

  if (isError) {
    return (
      <ErrorState
        heading="We couldn't load your children"
        body={error instanceof Error ? error.message : "Please try again in a moment."}
        action={{ label: "Try again", onClick: () => window.location.reload() }}
      />
    )
  }

  const children = data.children

  // Spec: one child → skip this screen entirely. `replace` so the browser back
  // button returns to where the parent actually came from rather than bouncing
  // through a list they never saw.
  if (children.length === 1) {
    return <Navigate to={`/parent/children/${children[0].childId}`} replace />
  }

  if (children.length === 0) {
    return <NoChildrenLinked />
  }

  return (
    <div className="flex flex-col gap-5">
      <h1 className="text-display-md text-t1">Your children</h1>
      <div className="flex flex-col gap-3">
        {children.map((child) => (
          <ChildCard key={child.childId} child={child} />
        ))}
      </div>
    </div>
  )
}
