/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useRef, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { PhoneInput } from "@/components/ui/phone-input"
import { usePutPhone } from "@/lib/hooks/useMeApi"
import { cleanPhoneInput, phoneErrorCode, phoneErrorMessage, validatePhoneField } from "@/lib/phone"
import { settingsSaveFailureMessage } from "@/lib/settingsOutcome"

/*
 * The one place a signed-in person adds or changes their phone number (UD-11). Mounted where the
 * prompt lives: the profile card, and inline when checkout stops for want of a number. It is a
 * small form of its own, not a field in a larger one, so each caller keeps its own layout around
 * it and only the field, the save and the errors are shared.
 *
 * Validation follows the sign-up screens' rule: on blur and on submit, never per keystroke. A
 * refusal from the server (`phone_required`, `phone_invalid`, matched on the code) lands on the
 * field, not in a banner, and moves focus back to it. Any other failure (offline, a 5xx) is a
 * line under the button, because retyping the number would not help.
 *
 * `onSaved` receives the stored E.164 number after `PUT /me/phone` succeeds. The cached profile
 * has already been updated by then (`usePutPhone`), so the banner is gone by the time it runs.
 *
 * Self-critique:
 * P · pattern 4: `PhoneInput` plus the house `Button`, in the settings and sign-up error voice.
 * H · hierarchy 4: one field, one button; the button is the only filled control in the form.
 * E · economy 4: no cancel and no success toast here; the caller decides what saved looks like.
 *   One withheld because both callers repeat a "Saved." line the form could own.
 * S · system fidelity 5: tokens and kit components only.
 * R · responsive 4: stacked at every width, field capped at 24rem so it never stretches on desktop.
 * V · voice 4: errors name the problem and the fix; the button says what it does.
 */

export interface PhoneEntryFormProps {
  /** Called with the stored number once it is saved. */
  onSaved?: (phone: string) => void
  /** The button's label. Names the outcome in the caller's context. */
  submitLabel?: string
  /** Move focus into the field on mount. For an inline prompt the person just arrived at. */
  autoFocus?: boolean
  /** Shown instead of the default hint, e.g. when the surrounding copy already explains why. */
  hint?: string
  /** Keep the label for assistive technology but not on screen, when the surrounding row already
   * shows the same words as its own label (the profile card). */
  hideLabel?: boolean
  /** When given, a quiet Cancel sits beside the button. For changing a number that is already set. */
  onCancel?: () => void
  className?: string
}

export function PhoneEntryForm({
  onSaved,
  submitLabel = "Save number",
  autoFocus = false,
  hint,
  hideLabel = false,
  onCancel,
  className,
}: PhoneEntryFormProps) {
  const put = usePutPhone()
  const [value, setValue] = useState("")
  const [error, setError] = useState<string | undefined>(undefined)
  const [failure, setFailure] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Focus moves after the next frame: while a save is in flight the field is disabled, and a
  // disabled field cannot take focus.
  const fail = (message: string) => {
    setError(message)
    requestAnimationFrame(() => inputRef.current?.focus())
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setFailure(null)
    const problem = validatePhoneField(value)
    if (problem) return fail(problem)
    put.mutate(cleanPhoneInput(value), {
      onSuccess: (state) => onSaved?.(state.phone),
      onError: (err) => {
        const code = phoneErrorCode(err)
        if (code) fail(phoneErrorMessage(code))
        else setFailure(settingsSaveFailureMessage(err))
      },
    })
  }

  return (
    <form onSubmit={handleSubmit} noValidate className={className ?? "flex w-full max-w-sm flex-col gap-3"}>
      <PhoneInput
        ref={inputRef}
        value={value}
        onValueChange={(next) => {
          setValue(next)
          setError(undefined)
          setFailure(null)
        }}
        onBlur={(tidy) => setError(validatePhoneField(tidy))}
        error={error}
        hint={hint}
        labelClassName={hideLabel ? "sr-only" : undefined}
        required
        disabled={put.isPending}
        autoFocus={autoFocus}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" variant="primary" loading={put.isPending}>
          {submitLabel}
        </Button>
        {onCancel ? (
          <Button type="button" variant="ghost" onClick={onCancel} disabled={put.isPending}>
            Cancel
          </Button>
        ) : null}
      </div>
      {failure ? (
        <p role="alert" className="m-0 text-body-sm text-error">
          {failure}
        </p>
      ) : null}
    </form>
  )
}
