/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V3 */
import { useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { ChartFrame } from "@/components/ui/chart-frame"
import { Input } from "@/components/ui/input"
import { BarChart } from "@/components/ui/lazy-chart"
import { PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import { ErrorState } from "@/components/ui/state-views"
import { isForbidden } from "@/lib/adminBillingModel"
import { cn } from "@/lib/utils"
import { formatCredits, formatMoney, formatPercent } from "@/lib/billingFormat"
import type { MarginReport } from "@/lib/billingTypes"
import { useMarginReport } from "@/lib/hooks/useAdminBillingApi"
import {
  accuracyFlag,
  costByActionBars,
  MAX_RANGE_DAYS,
  defaultRange,
  loadRate,
  formatShare,
  formatUsd,
  marginShare,
  rangeProblem,
  rateParam,
  rateProblem,
  saveRate,
  revenueBars,
  type DayRange,
} from "@/lib/marginModel"

/*
 * Money and margin (spec §8.4). Revenue against LLM cost, estimate accuracy, and the standing
 * money risks. Every figure is a counted fact from the report: the figures are a definition
 * strip (DESIGN.md names metric cards as the anti-reference), the charts and tables carry the
 * breakdowns, and nothing is derived that the server did not send except the margin share.
 *
 * Plan 07 has no per-month series, so there is no revenue-against-cost line over time.
 *
 * A null `costMinor` / `marginMinor` means the server has no USD to EGP rate. It is stated
 * as such and never rendered as 0 or as a margin.
 */

const CUR = "EGP"
const NO_RATE = "No USD to EGP rate set"

/* Room the charts' left axes need. The chart's default is built for short numbers; a
 * currency value and an action name (`generate_flashcards`) are not. Names are capped so the
 * bars keep room on a phone. */
const REVENUE_AXIS_PX = 104
const NAME_PX_PER_CHAR = 7
const NAME_AXIS_MAX_PX = 150
const VALUE_LABEL_SPILL_PX = 24
const categoryAxisPx = (bars: readonly { label: string }[]) =>
  Math.min(NAME_AXIS_MAX_PX, Math.max(...bars.map((b) => b.label.length), 0) * NAME_PX_PER_CHAR + 16)

/* The hairlines are the grid's gap showing the border colour through, so every strip must
 * fill its grid: a short last row would show as a grey block. `cols` is a whole class name
 * so Tailwind can see it. */
function Strip({ label, cols, children }: { label: string; cols: string; children: ReactNode }) {
  return (
    <dl aria-label={label} className={`m-0 grid gap-px overflow-hidden rounded-lg border border-outline-variant bg-outline-variant ${cols}`}>
      {children}
    </dl>
  )
}

function Fig({ label, children, wide }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className={`flex min-w-0 flex-col gap-1 bg-surface-container-lowest p-3 ${wide ? "col-span-2 md:col-span-1" : ""}`}>
      <dt className="text-body-sm text-on-surface-variant">{label}</dt>
      <dd className="m-0 break-words text-data-md text-on-surface">{children}</dd>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-4">
      <h2 className="m-0 text-display-sm text-on-surface">{title}</h2>
      {children}
    </section>
  )
}

function EmptyRow({ cols, children }: { cols: number; children: string }) {
  return (
    <TR>
      <TD colSpan={cols} className="text-body-sm text-on-surface-variant">
        {children}
      </TD>
    </TR>
  )
}

function Money({ r }: { r: MarginReport }) {
  const share = marginShare(r)
  const noRate = r.costMinor === null || r.marginMinor === null
  return (
    <Section title="Money">
      <Strip label="Revenue" cols="grid-cols-2 md:grid-cols-4">
        <Fig label="Net revenue">{formatMoney(r.revenue.netMinor, CUR)}</Fig>
        <Fig label="Recurring">{formatMoney(r.revenue.recurringMinor, CUR)}</Fig>
        <Fig label="Credit packs">{formatMoney(r.revenue.packsMinor, CUR)}</Fig>
        <Fig label="Refunded">{formatMoney(r.revenue.refundedMinor, CUR)}</Fig>
      </Strip>
      <Strip label="Cost and margin" cols="grid-cols-2 md:grid-cols-4">
        <Fig label="LLM cost">{formatUsd(r.cost.totalUsd)}</Fig>
        <Fig label="LLM cost in EGP">{r.costMinor === null ? "Not available" : formatMoney(r.costMinor, CUR)}</Fig>
        <Fig label="Margin">{r.marginMinor === null ? "Not available" : formatMoney(r.marginMinor, CUR)}</Fig>
        <Fig label="Margin share of net revenue">{share === null ? "Not available" : formatShare(share)}</Fig>
      </Strip>
      <p className="m-0 text-body-sm text-on-surface-variant">
        {noRate ? (
          <>
            {NO_RATE}. Enter an EGP per USD rate above to work out cost in EGP and margin.
          </>
        ) : (
          <>
            Cost converted at 1 USD = {r.egpPerUsd} EGP.
            {share === null ? " Margin share needs positive net revenue." : ""}
          </>
        )}
      </p>
    </Section>
  )
}

function Charts({ r }: { r: MarginReport }) {
  const bars = costByActionBars(r)
  // The axis shares this formatter, and `USD 10.00` ticks collide on a phone: the title says USD.
  const usdFigure = (v: number) => formatUsd(v).replace("USD ", "")
  const egp = (v: number) => formatMoney(Math.round(v * 100), CUR)
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <ChartFrame
        headingLevel={3}
        title="Revenue"
        subtitle="EGP, this range"
        isEmpty={r.revenue.recurringMinor + r.revenue.packsMinor + r.revenue.refundedMinor === 0}
        emptyBody="No payments were taken or refunded in this range."
      >
        <BarChart data={revenueBars(r)} formatValue={egp} leftMargin={REVENUE_AXIS_PX} ariaLabel="Revenue by kind" />
      </ChartFrame>
      <ChartFrame
        headingLevel={3}
        title="LLM cost by action"
        subtitle="USD, this range"
        isEmpty={r.cost.byAction.length === 0}
        emptyBody="No metered jobs settled in this range."
      >
        <BarChart data={bars} horizontal formatValue={usdFigure} leftMargin={categoryAxisPx(bars)} valueTickCount={2} rightMargin={VALUE_LABEL_SPILL_PX} ariaLabel="LLM cost by action, in USD" />
      </ChartFrame>
    </div>
  )
}

function Breakdowns({ r }: { r: MarginReport }) {
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <Table density="operate" tabIndex={0} role="region" aria-label="Revenue by plan">
        <caption className="p-3 text-start text-label text-on-surface">Revenue by plan</caption>
        <THead>
          <TR>
            <TH>Plan</TH>
            <TH numeric>Revenue</TH>
          </TR>
        </THead>
        <TBody>
          {r.revenue.byPlan.length === 0 ? (
            <EmptyRow cols={2}>No plan revenue in this range.</EmptyRow>
          ) : (
            r.revenue.byPlan.map((p) => (
              <TR key={p.key}>
                <TD>
                  <span className="text-data-sm">{p.key}</span>
                </TD>
                <TD numeric>{formatMoney(p.minor, CUR)}</TD>
              </TR>
            ))
          )}
        </TBody>
      </Table>
      <Table density="operate" tabIndex={0} role="region" aria-label="Cost by plan">
        <caption className="p-3 text-start text-label text-on-surface">Cost by plan</caption>
        <THead>
          <TR>
            <TH>Plan</TH>
            <TH numeric>Jobs</TH>
            <TH numeric>Cost</TH>
          </TR>
        </THead>
        <TBody>
          {r.cost.byPlan.length === 0 ? (
            <EmptyRow cols={3}>No metered jobs in this range.</EmptyRow>
          ) : (
            r.cost.byPlan.map((p) => (
              <TR key={p.key ?? "none"}>
                <TD>
                  <span className="text-data-sm">{p.key ?? "No plan"}</span>
                </TD>
                <TD numeric>{p.jobs}</TD>
                <TD numeric>{formatUsd(p.costUsd)}</TD>
              </TR>
            ))
          )}
        </TBody>
      </Table>
      <Table density="operate" tabIndex={0} role="region" aria-label="Cost by model">
        <caption className="p-3 text-start text-label text-on-surface">Cost by model</caption>
        <THead>
          <TR>
            <TH>Model</TH>
            <TH numeric>Cost</TH>
          </TR>
        </THead>
        <TBody>
          {r.cost.byModel.map((m) => (
            <TR key={m.model}>
              <TD>
                <span className="text-data-sm">{m.model}</span>
              </TD>
              <TD numeric>{formatUsd(m.costUsd)}</TD>
            </TR>
          ))}
          <TR>
            <TD>Unattributed</TD>
            <TD numeric>{formatUsd(r.cost.unattributedModelUsd)}</TD>
          </TR>
        </TBody>
      </Table>
    </div>
  )
}

function Accuracy({ r }: { r: MarginReport }) {
  return (
    <Section title="Estimate accuracy">
      <p className="m-0 max-w-prose text-body-sm text-on-surface-variant">
        How often a job&apos;s real cost landed outside the range we showed before it ran. An estimator with more than 20% of jobs outside
        its range is marked Retune.
      </p>
      {r.accuracy.length === 0 ? (
        <p className="m-0 text-body-sm text-on-surface-variant">No settled jobs in this range, so there is nothing to score.</p>
      ) : (
        <Table density="operate" tabIndex={0} role="region" aria-label="Estimate accuracy by action and estimator version">
          <caption className="sr-only">Estimate accuracy by action and estimator version</caption>
          <THead>
            <TR>
              <TH>Action</TH>
              <TH numeric>Estimator</TH>
              <TH numeric>Jobs</TH>
              <TH numeric>Below</TH>
              <TH numeric>Above</TH>
              <TH numeric>Outside range</TH>
              <TH numeric>Mean overrun</TH>
              <TH>Flag</TH>
            </TR>
          </THead>
          <TBody>
            {r.accuracy.map((a) => (
              <TR key={`${a.action}-${a.estimatorVersion}`}>
                <TD>
                  <span className="text-data-sm">{a.action}</span>
                </TD>
                <TD numeric>v{a.estimatorVersion}</TD>
                <TD numeric>{a.jobs}</TD>
                <TD numeric>{a.below}</TD>
                <TD numeric>{a.above}</TD>
                <TD numeric>{formatPercent(a.shareOutside)}</TD>
                <TD numeric>{a.meanOverrunUnits === null ? "None" : `${a.meanOverrunUnits.toFixed(1)} credits`}</TD>
                <TD>{accuracyFlag(a) === null ? null : <Badge tone="info">Retune</Badge>}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
    </Section>
  )
}

function Exposure({ r }: { r: MarginReport }) {
  const x = r.exposure
  return (
    <Section title="Exposure">
      <Strip label="Debt and limits" cols="grid-cols-2 md:grid-cols-3">
        <Fig label="Outstanding debt">
          {formatCredits(x.outstandingDebtUnits)} · {x.debtors} {x.debtors === 1 ? "account" : "accounts"}
        </Fig>
        <Fig label="Users at their limit">{x.usersAtLimit}</Fig>
        <Fig label="Expired jobs" wide>
          {x.expiredJobs.count} · {formatUsd(x.expiredJobs.costUsd)}
        </Fig>
      </Strip>
      <Strip label="Credits unused" cols="grid-cols-1 md:grid-cols-2">
        <Fig label="Expiring unused, next 30 days">
          {formatCredits(x.creditsExpiring30dUnits)} · {x.creditsExpiring30dOwners} {x.creditsExpiring30dOwners === 1 ? "owner" : "owners"}
        </Fig>
        <Fig label="Already expired unused">{formatCredits(x.creditsExpiredUnusedUnits)}</Fig>
      </Strip>
      {x.topDebtors.length === 0 ? (
        <p className="m-0 text-body-sm text-on-surface-variant">Nobody owes credits.</p>
      ) : (
        <Table density="operate" tabIndex={0} role="region" aria-label="Top debtors">
          <caption className="p-3 text-start text-label text-on-surface">Top debtors</caption>
          <THead>
            <TR>
              <TH>Account</TH>
              <TH numeric>Outstanding</TH>
            </TR>
          </THead>
          <TBody>
            {x.topDebtors.map((d) => (
              <TR key={d.userId}>
                <TD>
                  <Link to={`/platform/billing/customers/${d.userId}`} className="text-primary underline-offset-2 hover:underline">
                    {d.email}
                  </Link>
                </TD>
                <TD numeric>{formatCredits(d.outstanding)}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
    </Section>
  )
}

export function Margin() {
  // What the fields show, and the last value of each that was valid. Only valid values are sent.
  const [draft, setDraft] = useState<DayRange>(() => defaultRange(new Date()))
  const [applied, setApplied] = useState<DayRange>(draft)
  const [rateText, setRateText] = useState(loadRate)
  const [appliedRate, setAppliedRate] = useState<string | null>(() => rateParam(rateText))
  const problem = rangeProblem(draft)
  const rateError = rateProblem(rateText)
  const report = useMarginReport(applied.from, applied.to, appliedRate)
  const forbidden = report.status === "error" && isForbidden(report.error)

  function edit(next: DayRange) {
    setDraft(next)
    if (rangeProblem(next) === null) setApplied(next)
  }

  function editRate(text: string) {
    setRateText(text)
    if (rateProblem(text) === null) {
      setAppliedRate(rateParam(text))
      saveRate(text)
    }
  }

  return (
    <div className="flex flex-col gap-8">
      {forbidden ? (
        <ErrorState kicker={null} heading="You can't see money and margin" body="Billing is for platform admins. Ask one to look at this." />
      ) : (
        <>
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-start gap-3">
              <div className="w-48">
                <Input label="From" type="date" value={draft.from} max={draft.to || undefined} error={problem?.field === "from" ? problem.message : undefined} onChange={(e) => edit({ ...draft, from: e.target.value })} />
              </div>
              <div className="w-48">
                <Input label="To" type="date" value={draft.to} min={draft.from || undefined} error={problem?.field === "to" ? problem.message : undefined} onChange={(e) => edit({ ...draft, to: e.target.value })} />
              </div>
              <div className="w-48">
                <Input label="EGP per USD" inputMode="decimal" autoComplete="off" value={rateText} error={rateError ?? undefined} onChange={(e) => editRate(e.target.value)} />
              </div>
            </div>
            <p className="m-0 max-w-prose text-body-sm text-on-surface-variant">
              Whole UTC days, both included, up to {MAX_RANGE_DAYS} days. Defaults to the last 90 days. The rate turns LLM cost into EGP; it is kept in this
              browser, not on the server.
            </p>
          </div>
          <QueryState query={report} skeleton={<PageHeaderSkeleton />} error={{ heading: "Couldn't load money and margin" }}>
            {(r) => (
              <div className={cn("flex flex-col gap-8 transition-opacity", report.isPlaceholderData && "opacity-60")} aria-busy={report.isPlaceholderData === true}>
                {report.isPlaceholderData ? (
                  <p role="status" className="m-0 text-body-sm text-on-surface-variant">
                    Updating for the new range or rate.
                  </p>
                ) : null}
                <Money r={r} />
                <Charts r={r} />
                <Breakdowns r={r} />
                <Accuracy r={r} />
                <Exposure r={r} />
              </div>
            )}
          </QueryState>
        </>
      )}
    </div>
  )
}
