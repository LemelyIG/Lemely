/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { useEffect, useId, useRef, useState, type ReactNode } from "react"
import type { UseMutationResult } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Modal } from "@/components/ui/modal"
import { Select } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import { confirmProblem } from "@/lib/catalogueImpact"
import {
  REASON_MAX,
  adminBillingFailureMessage,
  fieldErrors,
  isAmbiguousFailure,
  reasonError,
  tomorrowUtc,
  visibleFields,
  type FieldSpec,
  type FormValues,
} from "@/lib/adminBillingModel"

/*
 * Every admin money or catalogue write goes through this dialog: the fields, plus a required
 * reason that the server writes to `admin_audit_log` in the same transaction (spec §4.7, §8).
 *
 * One request per open dialog: Enter and the button share one submit path that ignores a second
 * submit while the first is pending, so a double click can never write two audit rows. Field
 * errors appear after the first attempt and then follow the input; the first invalid field takes
 * focus. A server refusal sits in the footer, next to the button that caused it.
 */

/**
 * What a form tells the admin about the customers it affects, as the values change. `warned` is
 * true while the warning shows: the dialog then asks for a tick before it saves, and the tick is
 * a form-only value that never reaches the request body.
 */
export interface ImpactView {
  warned: boolean
  node: ReactNode
  confirmLabel: string
}

const NO_IMPACT: ImpactView = { warned: false, node: null, confirmLabel: "" }
const useNoImpact = (): ImpactView => NO_IMPACT

/** Short fields pair up on wide dialogs; prose and names take the full row. */
const HALF: ReadonlySet<FieldSpec["kind"]> = new Set(["number", "decimal", "money", "date", "select"])

export function ReasonedFormDialog<TBody>({
  open,
  onClose,
  title,
  fields,
  initial,
  submitLabel,
  mutation,
  toBody,
  note,
  check,
  onSaved,
  rolledBackOn502 = false,
  reload,
  blocked = null,
  useImpact = useNoImpact,
}: {
  open: boolean
  onClose: () => void
  title: string
  fields: FieldSpec[]
  initial: FormValues
  submitLabel: string
  mutation: UseMutationResult<unknown, Error, TBody>
  toBody: (values: FormValues, reason: string) => TBody
  note?: ReactNode
  /** Cross-field rules the per-field specs cannot express; run once every field is valid. */
  check?: (values: FormValues) => string[]
  /** Runs after the server accepted the change, just before the dialog closes. */
  onSaved?: () => void
  /** True only where a Paymob failure is known to roll the whole write back (the plan sync). */
  rolledBackOn502?: boolean
  /** How the failure copy tells the admin to check what saved ("Reload this page"). */
  reload?: string
  /**
   * Why submitting is not offered right now (null = it is). Used after an ambiguous failure of a
   * write with no idempotency key: the screen must show fresh data before the admin may retry.
   */
  blocked?: string | null
  /**
   * A hook that reads the typed values and returns the customer-impact warning. It must be the
   * same hook for the whole life of the dialog (it is called on every render).
   */
  useImpact?: (values: FormValues) => ImpactView
}) {
  const formId = useId()
  const formRef = useRef<HTMLFormElement>(null)
  const [values, setValues] = useState<FormValues>(initial)
  const [reason, setReason] = useState("")
  const [attempts, setAttempts] = useState(0)

  const impact = useImpact(values)
  const perField = fieldErrors(fields, values)
  const reasonProblem = reasonError(reason)
  const confirmError = confirmProblem(impact.warned, values)
  const crossProblems = Object.keys(perField).length === 0 ? (check?.(values) ?? []) : []
  const valid = Object.keys(perField).length === 0 && reasonProblem === null && crossProblems.length === 0 && confirmError === null
  const showErrors = attempts > 0
  const set = (name: string, value: string | boolean) => setValues((v) => ({ ...v, [name]: value }))

  // A reopened dialog must not greet the admin with the previous attempt's refusal.
  const resetMutation = useRef(mutation.reset)
  useEffect(() => {
    resetMutation.current()
  }, [])

  // After a refused submit, put the cursor on the first thing to fix.
  useEffect(() => {
    if (attempts > 0) formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()
    // Only a new attempt moves focus; typing must not.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [attempts])

  const submit = () => {
    if (mutation.isPending || blocked) return
    setAttempts((n) => n + 1)
    if (!valid) return
    mutation.mutate(toBody(values, reason.trim()), {
      onSuccess: () => {
        onSaved?.()
        onClose()
      },
    })
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      dismissible={!mutation.isPending}
      footer={
        <div className="flex flex-col gap-3">
          {mutation.isError ? (
            // An answer that never arrived (dropped connection, 5xx) is not a refusal: the change
            // may have saved, so it is not painted as an error. Only a definite 4xx is crimson.
            <p role="alert" className={cn("m-0 text-body-sm", isAmbiguousFailure(mutation.error) ? "text-on-surface" : "text-error")}>
              {adminBillingFailureMessage(mutation.error, "save this change", { rolledBackOn502, reload })}
            </p>
          ) : null}
          {blocked ? (
            <p role="status" className="m-0 text-body-sm text-on-surface">
              {blocked}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose} disabled={mutation.isPending}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" form={formId} loading={mutation.isPending} disabled={blocked !== null}>
              {submitLabel}
            </Button>
          </div>
        </div>
      }
    >
      <form
        id={formId}
        ref={formRef}
        noValidate
        autoComplete="off"
        className="grid grid-cols-1 gap-3 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        {note ? <div className="sm:col-span-2">{note}</div> : null}
        {visibleFields(fields, values, mutation.error).map((f) => {
          const value = values[f.name]
          const span = HALF.has(f.kind) ? "" : "sm:col-span-2"
          const error = showErrors ? perField[f.name] : undefined
          if (f.kind === "checkbox") {
            return (
              <div key={f.name} className={span}>
                <Checkbox label={f.label} checked={value === true} onChange={(e) => set(f.name, e.target.checked)} />
              </div>
            )
          }
          if (f.kind === "notice") {
            return (
              <p key={f.name} role="note" className="m-0 rounded-md bg-surface-container-low px-3 py-2 text-body-sm text-on-surface sm:col-span-2">
                {f.text}
              </p>
            )
          }
          if (f.kind === "select") {
            return (
              <Select key={f.name} wrapperClassName={span} label={f.label} hint={f.hint} value={String(value ?? "")} onChange={(e) => set(f.name, e.target.value)}>
                {f.options.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            )
          }
          if (f.kind === "lines") {
            return (
              <Textarea
                key={f.name}
                wrapperClassName={span}
                label={f.label}
                hint={f.hint}
                rows={4}
                value={String(value ?? "")}
                onChange={(e) => set(f.name, e.target.value)}
              />
            )
          }
          return (
            <Input
              key={f.name}
              wrapperClassName={span}
              label={f.label}
              hint={f.hint}
              error={error}
              type={f.kind === "date" ? "date" : "text"}
              inputMode={f.kind === "money" || f.kind === "decimal" ? "decimal" : f.kind === "number" ? "numeric" : undefined}
              min={f.kind === "date" && f.future ? tomorrowUtc() : undefined}
              maxLength={f.kind === "text" ? f.maxLength : undefined}
              value={String(value ?? "")}
              onChange={(e) => set(f.name, e.target.value)}
            />
          )
        })}
        {showErrors && crossProblems.length > 0 ? (
          <div role="alert" className="sm:col-span-2">
            <ul className="m-0 flex flex-col gap-1 ps-4 text-body-sm text-error">
              {crossProblems.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {/* Mounted before it has content, so a warning that appears is announced. */}
        <div role="status" className={impact.warned ? "flex flex-col gap-2 rounded-md bg-surface-container-low px-3 py-3 text-body-sm text-on-surface sm:col-span-2" : "sr-only"}>
          {impact.warned ? impact.node : null}
        </div>
        {impact.warned ? (
          <div className="sm:col-span-2">
            <Checkbox
              label={impact.confirmLabel}
              checked={values.confirmImpact === true}
              error={showErrors ? (confirmError ?? undefined) : undefined}
              onChange={(e) => set("confirmImpact", e.target.checked)}
            />
          </div>
        ) : null}
        <Textarea
          wrapperClassName="sm:col-span-2"
          label="Reason"
          hint="Required. It is saved in the audit log with this change."
          error={showErrors && reasonProblem ? reasonProblem : undefined}
          rows={3}
          maxLength={REASON_MAX}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </form>
    </Modal>
  )
}
