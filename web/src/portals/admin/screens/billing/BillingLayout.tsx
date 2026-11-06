/* Hallmark · pre-emit critique: P4 H4 E4 S3 R5 V3 */
import { Link, Outlet, useLocation } from "react-router-dom"
import { cn } from "@/lib/utils"

/*
 * `/platform/billing` and its areas (spec §8). One sidebar entry, a pill nav per area, so the
 * platform sidebar stays short. Tasks 15–16 append their areas to `BILLING_AREAS`.
 */

export const BILLING_AREAS: readonly { to: string; label: string; end?: boolean; also?: string }[] = [
  // A customer's page belongs to the Customers area, so its pill stays active there.
  { to: "/platform/billing", label: "Customers", end: true, also: "/platform/billing/customers/" },
  { to: "/platform/billing/catalogue", label: "Catalogue" },
]

/** An area is active on its own path, under it (unless `end`), or under its `also` prefix. */
export function areaActive(area: { to: string; end?: boolean; also?: string }, pathname: string): boolean {
  const path = pathname.replace(/\/+$/, "") || "/"
  if (path === area.to) return true
  if (area.also && path.startsWith(area.also)) return true
  return !area.end && path.startsWith(`${area.to}/`)
}

export function BillingLayout() {
  const { pathname } = useLocation()
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <h1 className="m-0 text-display-md text-on-surface">Billing</h1>
        <nav aria-label="Billing areas" className="flex flex-wrap gap-1">
          {BILLING_AREAS.map((a) => (
            <Link
              key={a.to}
              to={a.to}
              aria-current={areaActive(a, pathname) ? (pathname.replace(/\/+$/, "") === a.to ? "page" : "true") : undefined}
              className={cn(
                "rounded-md px-3 py-1.5 text-body-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:flex pointer-coarse:min-h-11 pointer-coarse:items-center",
                areaActive(a, pathname)
                  ? "bg-surface-container-low font-medium text-on-surface"
                  : "text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface",
              )}
            >
              {a.label}
            </Link>
          ))}
        </nav>
      </div>
      <Outlet />
    </div>
  )
}
