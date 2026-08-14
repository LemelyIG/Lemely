/* Hallmark · pre-emit critique: P5 H4 E4 S5 R5 V4 */
import type { ReactNode } from "react"
import { Link, NavLink } from "react-router-dom"
import { useAuth } from "@/lib/auth/AuthContext"
import { portalPathForRole } from "@/lib/auth/RequireAuth"
import { Breadcrumbs } from "@/components/ui/breadcrumbs"
import { SkipLink, MAIN_CONTENT_ID } from "@/components/ui/skip-link"
import { cn } from "@/lib/utils"

/*
 * P4.10 · The frame both settings screens sit in.
 *
 * ── Why a frame exists at all ──────────────────────────────────────────────
 *
 * `/settings/devices` and `/settings/notifications` are top-level routes,
 * outside every portal subtree, and that is correct: the device limit applies
 * per account regardless of role, and the at-risk-alert preference belongs to
 * teachers and parents, so neither screen can live inside one portal without
 * putting itself out of reach of roles it applies to (see `routes.tsx`).
 *
 * The cost of that decision was never paid until now. Being outside every
 * portal meant being outside every portal's *chrome*: no mark, no navigation,
 * no breadcrumb, no skip link, no texture. Four entry points lead here — the
 * teacher sidebar, the parent header, the student profile screen and the
 * student notifications inbox — and every one of them dropped the reader onto
 * a bare white column with a `←` character for a back link and no indication
 * of which product they were still in.
 *
 * So the two screens now share a frame, for the same reason `AuthFrame` exists
 * for the two signed-out screens (P4.7): three copies of a frame is how three
 * screens end up with three different ideas of where the logo goes.
 *
 * ── Role-aware, because the reader is any role ─────────────────────────────
 *
 * The mark links to the reader's own portal, and the trail names it, because
 * this lane's whole premise is that all five roles arrive here. A hardcoded
 * "Back to your dashboard" would be the same shape of defect as the four
 * screens P3.10 found hardcoding a greeting.
 *
 * ── The lane nav replaces the reciprocal links ─────────────────────────────
 *
 * Each screen used to carry a plain text link to the other, added in P5.9
 * chunk D so that one nav entry per portal could reach both. That worked and
 * read as an afterthought: two links in a row, one of which was the page you
 * were already on nowhere, with no indication that these two screens are one
 * section. A route-linked segmented nav says both things at once — what else
 * is in here, and where you are.
 *
 * `NavLink` rather than the kit's `Tabs`: `Tabs` owns `aria-selected` panels
 * within a single page, and these are two routes. Using it here would claim a
 * tabpanel relationship that the router does not implement, which is worse for
 * a screen reader than plain navigation links with `aria-current`.
 */

export interface SettingsFrameProps {
  /** Page title, rendered as the `<h1>`. */
  title: string
  /** One-line statement of what the page is for, under the title. */
  intro: string
  children: ReactNode
}

/** The two screens in this lane, in the order they appear in the nav. */
const SETTINGS_NAV = [
  { to: "/settings/devices", label: "Account and devices" },
  { to: "/settings/notifications", label: "Notifications" },
] as const

/**
 * A human name for the portal a role goes back to.
 *
 * Kept beside `portalPathForRole`'s own mapping rather than derived from the
 * path: "/teacher" serves three roles, and a school admin reading "Back to
 * teacher" would reasonably wonder whose dashboard they were being sent to.
 */
function portalLabelForRole(role: string): string {
  if (role === "student") return "Your dashboard"
  if (role === "parent") return "Your children"
  return "Your classes"
}

export function SettingsFrame({ title, intro, children }: SettingsFrameProps) {
  const { session } = useAuth()
  const home = session ? portalPathForRole(session.role) : "/login"
  const homeLabel = session ? portalLabelForRole(session.role) : "Sign in"

  return (
    <div className="paper-grain flex min-h-screen flex-col bg-paper">
      <SkipLink />

      <header className="border-b border-rule bg-paper-raised">
        <div className="mx-auto flex w-full max-w-200 items-center gap-4 px-4 py-4 md:px-8">
          <Link
            to={home}
            className="flex items-center gap-2.5 rounded-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          >
            {/* `alt=""` and `aria-hidden`: the wordmark beside it already says
                "Lemely", so describing the mark too announces the brand twice
                (the same treatment as the parent header). */}
            <img src="/brand/mark.svg" alt="" aria-hidden="true" className="h-6 w-6 shrink-0" />
            <span className="text-display-sm text-ink">Lemely</span>
          </Link>
        </div>
      </header>

      <main
        id={MAIN_CONTENT_ID}
        tabIndex={-1}
        className="mx-auto flex w-full max-w-200 flex-1 flex-col gap-8 px-4 py-8 focus:outline-none md:px-8 md:py-10"
      >
        <div className="flex flex-col gap-4">
          <Breadcrumbs items={[{ label: homeLabel, to: home }, { label: title }]} />

          <div className="flex flex-col gap-2">
            <h1 className="text-display-md text-ink">{title}</h1>
            <p className="max-w-[65ch] text-body-md text-ink-muted">{intro}</p>
          </div>

          {/* `aria-label` rather than a visible heading: the nav's two items
              name the section between them, and a "Settings sections" heading
              above two links is chrome nobody reads. */}
          <nav aria-label="Settings" className="flex flex-wrap gap-1">
            {SETTINGS_NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-3 py-1.5 text-body-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring",
                    isActive
                      ? "bg-paper-sunk font-medium text-ink"
                      : "text-ink-muted hover:bg-paper-sunk hover:text-ink",
                  )
                }
                // `aria-current="page"` is what tells a screen reader which of
                // the two you are on. The weight-and-fill treatment is the
                // sighted half of the same fact, never the whole of it.
                end
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>

        {children}
      </main>
    </div>
  )
}
