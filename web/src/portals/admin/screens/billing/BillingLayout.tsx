/* Hallmark · pre-emit critique: P4 H4 E4 S3 R5 V3 */
import { NavLink, Outlet } from "react-router-dom"
import { cn } from "@/lib/utils"

/*
 * `/platform/billing` and its areas (spec §8). One sidebar entry, a pill nav per area, so the
 * platform sidebar stays short. Tasks 15–16 append their areas to `BILLING_AREAS`.
 */

export const BILLING_AREAS: readonly { to: string; label: string; end?: boolean }[] = [
  { to: "/platform/billing", label: "Customers", end: true },
  { to: "/platform/billing/catalogue", label: "Catalogue" },
]

export function BillingLayout() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <h1 className="m-0 text-display-md text-on-surface">Billing</h1>
        <nav aria-label="Billing areas" className="flex flex-wrap gap-1">
          {BILLING_AREAS.map((a) => (
            <NavLink
              key={a.to}
              to={a.to}
              end={a.end}
              className={({ isActive }) =>
                cn(
                  "rounded-md px-3 py-1.5 text-body-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:flex pointer-coarse:min-h-11 pointer-coarse:items-center",
                  isActive
                    ? "bg-surface-container-low font-medium text-on-surface"
                    : "text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface",
                )
              }
            >
              {a.label}
            </NavLink>
          ))}
        </nav>
      </div>
      <Outlet />
    </div>
  )
}
