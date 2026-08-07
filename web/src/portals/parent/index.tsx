import type { RouteObject } from "react-router-dom"
import { Link, Outlet, useLocation, useNavigate, useParams } from "react-router-dom"
import { SignOut } from "@phosphor-icons/react"
import { useAuth } from "@/lib/auth/AuthContext"
import { useChildren } from "@/lib/hooks/useParentApi"
import { Children } from "./screens/Children"
import { ChildOverview } from "./screens/ChildOverview"

/*
 * Parent portal shell.
 *
 * UI spec §4.8: "Total depth from login to the answer a parent came for: two
 * taps. Design for navigation depth and no interest in learning an interface."
 * So there is no sidebar and no nav list — the portal is four read-only screens
 * reached by tapping the thing you want to read. The only persistent control is
 * the child switcher, which the spec asks for explicitly ("If only one child,
 * skip straight to P-02 and keep this as a switcher in the header").
 *
 * The switcher is a native <select>: familiar, keyboard- and screen-reader-
 * complete for free, and nothing to learn. It shares `useChildren()`'s cache
 * with P-01, so mounting it costs no extra request.
 */

/** Child switcher (P-01's "keep this as a switcher in the header").
 *
 * Renders only when there is a child context to switch *within*: on a child
 * route, and only when the parent has more than one child. With one child
 * there is nothing to choose, and on the children list the page itself is the
 * switcher — a second copy in the header would be two controls for one job. */
function ChildSwitcher() {
  const { childId } = useParams<{ childId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const { data } = useChildren()

  const children = data?.children ?? []
  if (!childId || children.length < 2) return null

  return (
    <label className="flex items-center gap-2 text-body-md text-t2">
      {/* The visible word is hidden at mobile for width, so the accessible
          name has to come from somewhere that is never hidden — otherwise the
          select is an unlabelled control below 640px. */}
      <span className="hidden sm:inline" aria-hidden="true">
        Viewing
      </span>
      <select
        aria-label="Choose which child to view"
        value={childId}
        onChange={(event) => {
          // Preserve where the parent is (overview / subject / weaknesses)
          // across the switch where the path still makes sense. A subject the
          // other child does not take would 404, so only the overview and
          // weaknesses tails carry over; everything else lands on the overview.
          const tail = location.pathname.endsWith("/weaknesses") ? "/weaknesses" : ""
          navigate(`/parent/children/${event.target.value}${tail}`)
        }}
        className="rounded border border-border bg-surface px-2.5 py-1.5 text-body-md text-t1"
      >
        {children.map((child) => (
          <option key={child.childId} value={child.childId}>
            {child.displayName}
          </option>
        ))}
      </select>
    </label>
  )
}

function Header() {
  const { logout } = useAuth()
  const navigate = useNavigate()

  return (
    <header className="border-b border-border bg-surface">
      <div className="mx-auto flex w-full max-w-240 items-center gap-4 px-container-mobile py-4">
        <Link to="/parent" className="flex items-center gap-2.5">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent font-serif text-body-lg italic text-accent-on">
            l
          </span>
          <span className="font-serif text-body-lg text-t1">Lemely</span>
        </Link>
        <div className="ml-auto flex items-center gap-3">
          <ChildSwitcher />
          {/* The label collapses to an icon at mobile, so `aria-label` carries
              the accessible name at every width — without it axe reports a
              serious `button-name` violation below 640px (found in
              verification, not by the standing gates: audit.mjs is still
              scoped to the four student routes, D2.10 / P3.10 item (a)). */}
          <button
            type="button"
            aria-label="Sign out"
            onClick={() => {
              logout()
              navigate("/login/parent", { replace: true })
            }}
            className="flex cursor-pointer items-center gap-1.5 rounded border-0 bg-transparent px-2 py-1.5 text-body-md text-t2 hover:text-t1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            <SignOut size={16} aria-hidden="true" />
            <span className="hidden sm:inline">Sign out</span>
          </button>
        </div>
      </div>
    </header>
  )
}

function ParentLayout() {
  return (
    <div data-portal="parent" className="flex min-h-screen flex-col bg-bg">
      <Header />
      <main className="mx-auto w-full min-w-0 max-w-240 flex-1 overflow-x-hidden px-container-mobile py-8">
        <Outlet />
      </main>
    </div>
  )
}

export const parentRoute: RouteObject = {
  path: "parent",
  element: <ParentLayout />,
  children: [
    { index: true, element: <Children /> },
    { path: "children/:childId", element: <ChildOverview /> },
  ],
}
