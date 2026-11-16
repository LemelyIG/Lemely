import type { ReactNode } from "react"
import { formatUtc } from "@/lib/adminBillingModel"

/* Pieces the catalogue's panels share: the titled section and the empty line. */

export function Section({ title, hint, action, children }: { title: string; hint?: string; action: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="m-0 text-display-sm text-on-surface">{title}</h2>
          {hint ? <p className="m-0 max-w-prose text-body-sm text-on-surface-variant">{hint}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="m-0 rounded-lg border border-dashed border-outline-variant px-4 py-6 text-body-sm text-on-surface-variant">{children}</p>
  )
}

/** "Changed 12 Nov 2026, 09:30 UTC by 3f2a91c4": the server names the admin by id. */
export function ChangedBy({ at, by }: { at: string; by: string | null }) {
  return (
    <span className="text-body-sm text-on-surface-variant">
      Changed {formatUtc(at)}
      {by ? (
        <>
          {" "}
          by <span className="text-data-sm" title={by}>{by.slice(0, 8)}</span>
        </>
      ) : null}
    </span>
  )
}
