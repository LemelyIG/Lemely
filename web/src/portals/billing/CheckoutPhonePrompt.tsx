/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { PhoneEntryForm } from "@/components/phone-entry-form"
import { PHONE_CHECKOUT_BODY, PHONE_CHECKOUT_HEADING } from "@/lib/phone"

/*
 * UD-11 inside a dialog: checkout refused with 422 `phone_required`, which is a missing step, not
 * a failure. The field appears in place and `onSaved` retries the same request. Nothing was
 * charged: the server checks before it writes a payment row.
 */
export function CheckoutPhonePrompt({ onSaved }: { onSaved: () => void }) {
  return (
    <div className="flex flex-col gap-3 rounded-md border border-outline-variant bg-surface-container-low p-4">
      <div className="flex flex-col gap-1">
        <h3 className="m-0 text-display-xs text-on-surface">{PHONE_CHECKOUT_HEADING}</h3>
        <p className="m-0 text-body-sm text-on-surface-variant">{PHONE_CHECKOUT_BODY}</p>
      </div>
      <PhoneEntryForm autoFocus submitLabel="Save and continue" onSaved={() => onSaved()} />
    </div>
  )
}
