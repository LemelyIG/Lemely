import { useState } from "react"
import { Button } from "@/components/ui/button"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import {
  llmConfirmChecks,
  llmPriceBody,
  llmPriceChecks,
  llmPriceClearBody,
  llmPriceFields,
  llmPriceValues,
  staleBlock,
  usdPerMtok,
} from "@/lib/adminRatesModel"
import { useClearLlmPrice, useLlmPrices, useSetLlmPrice } from "@/lib/hooks/useAdminBillingApi"
import type { LlmModelPrice, LlmRates } from "@/lib/billingTypes"
import { ChangedBy, Empty, Section } from "./CataloguePanels"
import { ReasonedFormDialog } from "./ReasonedFormDialog"

/* AI token prices (UD-13 D): what the code charges per model, and the admin's override of it.
 * A customer pays cost x units per USD, so an override moves what they are charged. */

type Dialog = { kind: "set" | "clear"; model: LlmModelPrice } | null

const DAY = new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" })
const n = (v: number) => new Intl.NumberFormat("en-US").format(v)

/** Input and output, then whichever cache and tier prices exist. Numbers in mono, words not. */
function Rates({ r }: { r: LlmRates }) {
  const cache = [
    r.cachedInputUsdPerMtok !== null ? (["Cached", r.cachedInputUsdPerMtok] as const) : null,
    r.cacheWrite5mUsdPerMtok !== null ? (["Write 5m", r.cacheWrite5mUsdPerMtok] as const) : null,
    r.cacheWrite1hUsdPerMtok !== null ? (["Write 1h", r.cacheWrite1hUsdPerMtok] as const) : null,
  ].filter((x) => x !== null)
  return (
    <div className="flex flex-col gap-0.5 text-body-sm">
      <span>
        In <span className="text-data-sm">{usdPerMtok(r.inputUsdPerMtok)}</span>, out <span className="text-data-sm">{usdPerMtok(r.outputUsdPerMtok)}</span>
      </span>
      {cache.length > 0 ? (
        <span className="text-on-surface-variant">
          {cache.map(([label, v], i) => (
            <span key={label}>
              {i > 0 ? ", " : ""}
              {label} <span className="text-data-sm">{usdPerMtok(v)}</span>
            </span>
          ))}
        </span>
      ) : null}
      {r.tierThresholdTokens !== null && r.tier2InputUsdPerMtok !== null ? (
        <span className="text-on-surface-variant">
          Above <span className="text-data-sm">{n(r.tierThresholdTokens)}</span> tokens: in <span className="text-data-sm">{usdPerMtok(r.tier2InputUsdPerMtok)}</span>, out{" "}
          <span className="text-data-sm">{usdPerMtok(r.tier2OutputUsdPerMtok)}</span>
        </span>
      ) : null}
    </div>
  )
}

function BuiltIn({ m }: { m: LlmModelPrice }) {
  const d = m.codeDefault
  if (d === null) {
    return <span className="text-body-sm text-on-surface-variant">No built-in price. Calls to this model are not priced without an override.</span>
  }
  return (
    <div className="flex flex-col gap-1">
      <Rates r={d} />
      <span className="text-body-sm text-on-surface-variant">
        Source {d.source}
        {d.readOn ? `, read ${DAY.format(new Date(`${d.readOn}T00:00:00Z`))}` : ""}
      </span>
    </div>
  )
}

function Override({ m }: { m: LlmModelPrice }) {
  const o = m.override
  if (o === null) return <span className="text-body-sm text-on-surface-variant">None</span>
  const flat = m.codeDefault?.tiered === true && o.tier2InputUsdPerMtok === null
  return (
    <div className="flex flex-col gap-1">
      <Rates r={o} />
      {flat ? <span className="text-body-sm text-on-surface-variant">Same rate at every prompt length.</span> : null}
      <ChangedBy at={o.updatedAt} by={o.updatedBy} />
    </div>
  )
}

function Used({ m }: { m: LlmModelPrice }) {
  return <span className="text-body-sm text-on-surface-variant">{m.seenInLast30Days ? "Used in the last 30 days" : "Not used in the last 30 days"}</span>
}

function Actions({ m, open }: { m: LlmModelPrice; open: (d: Dialog) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      <Button size="sm" variant="secondary" onClick={() => open({ kind: "set", model: m })} aria-label={`${m.override ? "Edit" : "Set"} override for ${m.model}`}>
        {m.override ? "Edit override" : "Set override"}
      </Button>
      {m.override ? (
        <Button size="sm" variant="ghost" onClick={() => open({ kind: "clear", model: m })} aria-label={`Clear override for ${m.model}`}>
          Clear
        </Button>
      ) : null}
    </div>
  )
}

function Models({ models, open }: { models: LlmModelPrice[]; open: (d: Dialog) => void }) {
  return (
    <>
      <div className="hidden lg:block">
        <Table density="operate">
          <caption className="sr-only">AI token prices, USD per million tokens</caption>
          <THead>
            <TR>
              <TH>Model</TH>
              <TH>Built-in</TH>
              <TH>Override</TH>
              <TH>
                <span className="sr-only">Actions</span>
              </TH>
            </TR>
          </THead>
          <TBody>
            {models.map((m) => (
              <TR key={m.model}>
                <TD>
                  <div className="flex flex-col gap-0.5">
                    <span className="text-data-sm">{m.model}</span>
                    <span className="text-body-sm text-on-surface-variant">{m.provider}</span>
                    <Used m={m} />
                  </div>
                </TD>
                <TD>
                  <BuiltIn m={m} />
                </TD>
                <TD>
                  <Override m={m} />
                </TD>
                <TD>
                  <Actions m={m} open={open} />
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </div>
      <ul className="m-0 grid list-none grid-cols-1 gap-3 p-0 md:grid-cols-2 lg:hidden">
        {models.map((m) => (
          <li key={m.model} className="flex flex-col gap-3 rounded-lg border border-outline-variant bg-surface-container-lowest p-4">
            <div className="flex min-w-0 flex-col gap-0.5">
              <h3 className="m-0 break-all text-data-md font-medium text-on-surface">{m.model}</h3>
              <span className="text-body-sm text-on-surface-variant">{m.provider}</span>
              <Used m={m} />
            </div>
            <dl className="m-0 flex flex-col gap-3 text-body-sm">
              <div>
                <dt className="text-on-surface-variant">Built-in</dt>
                <dd className="m-0">
                  <BuiltIn m={m} />
                </dd>
              </div>
              <div>
                <dt className="text-on-surface-variant">Override</dt>
                <dd className="m-0">
                  <Override m={m} />
                </dd>
              </div>
            </dl>
            <Actions m={m} open={open} />
          </li>
        ))}
      </ul>
    </>
  )
}

export function LlmPrices({ saved }: { saved: (what: string) => () => void }) {
  const query = useLlmPrices()
  const setPrice = useSetLlmPrice()
  const clearPrice = useClearLlmPrice()
  const [dialog, setDialog] = useState<Dialog>(null)
  const close = () => setDialog(null)

  return (
    <Section
      title="AI token prices"
      hint="USD per million tokens. A customer pays cost × units per USD, so a lower price lowers what they are charged."
      action={null}
    >
      <QueryState
        query={query}
        skeleton={<ListSkeleton rows={3} />}
        error={{ heading: "Couldn't load the AI prices" }}
        isEmpty={(models) => models.length === 0}
        empty={<Empty>No models yet. A model appears here once the product prices or uses it.</Empty>}
      >
        {(models) => <Models models={models} open={setDialog} />}
      </QueryState>
      {dialog?.kind === "set" ? (
        <ReasonedFormDialog
          key={`${dialog.model.model}:${dialog.model.override?.version ?? 0}`}
          open
          onClose={close}
          title={`${dialog.model.override ? "Edit" : "Set"} override for ${dialog.model.model}`}
          fields={llmPriceFields(dialog.model)}
          initial={llmPriceValues(dialog.model)}
          submitLabel="Save override"
          mutation={setPrice}
          toBody={(v, r) => ({ model: dialog.model.model, body: llmPriceBody(v, r, dialog.model) })}
          check={(v) => [...llmPriceChecks(v), ...llmConfirmChecks(v, dialog.model)]}
          note={
            <p className="m-0 text-body-sm text-on-surface-variant">
              Starts from the current price. Applies to calls costed after the next refresh, within a minute.
            </p>
          }
          blocked={staleBlock(setPrice.error)}
          reload="Reload this page"
          onSaved={saved(`Saved the override for ${dialog.model.model}.`)}
        />
      ) : null}
      {dialog?.kind === "clear" && dialog.model.override ? (
        <ReasonedFormDialog
          open
          onClose={close}
          title={`Clear override for ${dialog.model.model}`}
          fields={[]}
          initial={{}}
          submitLabel="Clear override"
          mutation={clearPrice}
          toBody={(_v, r) => ({ model: dialog.model.model, body: llmPriceClearBody(r, dialog.model.override!) })}
          note={
            <p className="m-0 text-body-sm text-on-surface">
              {dialog.model.codeDefault === null
                ? "This model has no built-in price. Once cleared, calls to it are not priced."
                : "Calls go back to the built-in price."}
            </p>
          }
          blocked={staleBlock(clearPrice.error)}
          reload="Reload this page"
          onSaved={saved(`Cleared the override for ${dialog.model.model}.`)}
        />
      ) : null}
    </Section>
  )
}
