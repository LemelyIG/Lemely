/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Outlet } from "react-router-dom"
import { Eyebrow } from "@/components/ui/primitives"
import { SettingsNav, type SettingsNavItem } from "./SettingsFrame"

/*
 * The in-portal Settings section: `/teacher/settings/*` and
 * `/student/settings/*`, sitting inside each portal's own layout rather than
 * the top-level `/settings/*` lane `SettingsFrame` frames.
 *
 * ── Why a second frame, instead of reusing `SettingsFrame` ─────────────────
 *
 * `SettingsFrame` exists because `/settings/devices` and
 * `/settings/notifications` sit *outside* every portal, with no shared
 * chrome to paint around them (its own module header tells that story in
 * full) — so it supplies its own header, mark, breadcrumb and skip link.
 * A teacher or student reaching Settings through their own portal sidebar is
 * the opposite case: the portal shell already renders all of that. Wrapping
 * these routes in `SettingsFrame` too would double every piece of chrome —
 * two skip links, two "Lemely" marks, a breadcrumb repeating the sidebar's
 * own current-page state. This component is deliberately thin: an `<h1>`,
 * the same pill nav `SettingsFrame` uses, and an `<Outlet>`.
 *
 * ── Why the nav is shared rather than copied ────────────────────────────────
 *
 * `SettingsNav` is `SettingsFrame`'s own extracted pill nav (see that file).
 * Two hand-copies of the same markup is how the top-level lane and this one
 * end up with two different ideas of what an active pill looks like — the
 * same reasoning `SettingsFrame`'s header gives for having one frame in the
 * first place, just one level down.
 *
 * ── Why `basePath` is a prop rather than read from the route ────────────────
 *
 * The three destinations differ only by which portal is asking — the pill
 * targets, the profile section, the devices section and the notifications
 * section are otherwise identical between `/teacher/settings/*` and
 * `/student/settings/*`. A prop keeps that the only thing that varies,
 * rather than this component reaching into `useLocation()` to reconstruct a
 * fact its caller already knows.
 */

export interface PortalSettingsLayoutProps {
  /** The portal-scoped root Settings sits under. Everything the nav links to
   * is built from this, so a single prop is the only thing that changes
   * between the teacher and student mounts. */
  basePath: "/teacher/settings" | "/student/settings"
}

export function PortalSettingsLayout({ basePath }: PortalSettingsLayoutProps) {
  const items: SettingsNavItem[] = [
    { to: basePath, label: "Profile", end: true },
    { to: `${basePath}/devices`, label: "Account and devices" },
    { to: `${basePath}/notifications`, label: "Notifications" },
  ]

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Eyebrow>Account</Eyebrow>
        <h1 className="text-display-md text-ink">Settings</h1>
      </div>

      <SettingsNav items={items} />

      <Outlet />
    </div>
  )
}
