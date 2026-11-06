/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { ErrorState } from "@/components/ui/state-views"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import { humanize, isForbidden } from "@/lib/adminBillingModel"
import type { CustomerHit } from "@/lib/billingTypes"
import { useCustomerSearch } from "@/lib/hooks/useAdminBillingApi"

/* Customer search (spec §8.2): name, email, user id, payment id or Paymob order id. The query
 * lives in the URL so a search can be shared with another admin. */

const MATCHED: Record<CustomerHit["matchedOn"], string> = {
  user_id: "User id",
  payment_id: "Payment id",
  paymob_order: "Paymob order",
  email: "Email",
  name: "Name",
}

export function Customers() {
  const [params, setParams] = useSearchParams()
  const q = params.get("q") ?? ""
  const [draft, setDraft] = useState(q)
  const search = useCustomerSearch(q)
  const searched = q.trim().length >= 2

  return (
    <div className="flex flex-col gap-4">
      <form
        className="flex flex-wrap items-end gap-3"
        role="search"
        aria-label="Find a customer"
        onSubmit={(e) => {
          e.preventDefault()
          setParams(draft.trim() ? { q: draft.trim() } : {})
        }}
      >
        <div className="min-w-64 flex-1">
          <Input
            label="Find a customer"
            hint="Name, email, user id, payment id or Paymob order id"
            type="search"
            autoComplete="off"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
        </div>
        <Button type="submit" variant="primary">
          Search
        </Button>
      </form>
      {!searched ? (
        <p className="m-0 text-body-sm text-on-surface-variant">Type at least two characters.</p>
      ) : search.status === "error" && isForbidden(search.error) ? (
        <ErrorState kicker={null} heading="You can't search customers" body="Billing is for platform admins. Ask one to look this customer up." />
      ) : (
        <QueryState
          query={search}
          skeleton={<ListSkeleton />}
          error={{ heading: "Couldn't search customers" }}
          isEmpty={(d) => d.hits.length === 0}
          empty={<p className="m-0 text-body-md text-on-surface-variant">No customer matches that search.</p>}
        >
          {(d) => (
            <Table density="operate" tabIndex={0} role="region" aria-label="Customer matches">
              <caption className="sr-only">Customers matching {q.trim()}</caption>
              <THead>
                <TR>
                  <TH>Name</TH>
                  <TH>Email</TH>
                  <TH>Role</TH>
                  <TH>Matched on</TH>
                </TR>
              </THead>
              <TBody>
                {d.hits.map((c) => (
                  <TR key={c.userId}>
                    <TD>
                      <Link to={`/platform/billing/customers/${c.userId}`} className="font-medium text-primary underline-offset-2 hover:underline">
                        {c.displayName ?? c.email}
                      </Link>
                    </TD>
                    <TD>{c.email}</TD>
                    <TD>{humanize(c.role)}</TD>
                    <TD>{MATCHED[c.matchedOn]}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </QueryState>
      )}
    </div>
  )
}
