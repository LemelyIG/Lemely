/* Hallmark · pre-emit critique: P4 H4 E5 S5 R4 V4 */
import { forwardRef } from "react"
import { Input, type InputProps } from "@/components/ui/input"
import { DEFAULT_PHONE_PREFIX, tidyPhoneInput, usesDefaultPrefix } from "@/lib/phone"
import { cn } from "@/lib/utils"

/*
 * C-25 · Phone input. A labelled `Input` with a "+20" default country code shown in front of the
 * number until the person types their own (a leading "+" or "00"), so an Egyptian number needs no
 * country code and any other country is one keystroke away. There is no country picker: a list of
 * 200 dial codes is a second control to learn for a field most people fill once.
 *
 * It composes `Input` rather than copying it, so the label, hint, error row, status glyph and the
 * border-colour ladder stay in one place. The prefix goes in `Input`'s own `leadingIcon` slot,
 * which is decorative and aria-hidden by design, so the default country is carried to assistive
 * technology by the hint instead ("Egypt (+20) is assumed ..."), which `Input` already ties to the
 * field with `aria-describedby`.
 *
 * `type="tel"`, `inputMode="tel"` and `autoComplete="tel"` are fixed here rather than left to
 * callers: they are what bring up the phone keypad and offer the saved number, and every phone
 * field in the product should do both. A browser-filled "+201012345678" hides the prefix on its
 * own because the value then starts with "+".
 *
 * On blur a leading national zero is dropped from view ("01012345678" becomes "1012345678"), since
 * "+20 01012345678" would read as two zeros. The server reads both identically. The tidied value is
 * handed to `onBlur`, so the caller validates what is now on screen.
 *
 * Validation stays with the caller (`validatePhoneField` in `lib/phone.ts`), for the same reason
 * `Input` leaves it there: sign-up validates on blur and on submit, the profile card on save.
 *
 * Self-critique, written out because the stamp above is otherwise six bare digits:
 * P · pattern 4: reuses `Input` and its leading slot instead of a new field language. One withheld
 *   because the prefix appearing and disappearing is a small behaviour no other field has.
 * H · hierarchy 4: label, field, one hint line, error replaces the hint. Nothing competes.
 * E · economy 5: no picker, no flags, no format mask, no extra control.
 * S · system fidelity 5: tokens only; padding and the prefix size come from the same scale as `Input`.
 * R · responsive 4: the field is full width and the prefix is 3ch; checked at 380, 768 and 1440.
 * V · voice 4: the hint states the default and the one exception in plain words.
 */

export interface PhoneInputProps
  extends Omit<
    InputProps,
    "type" | "inputMode" | "autoComplete" | "leadingIcon" | "value" | "onChange" | "onBlur" | "label"
  > {
  value: string
  onValueChange: (value: string) => void
  /** Receives the value as it is after the leading-zero tidy, so a caller validates what is shown. */
  onBlur?: (value: string) => void
  label?: string
}

const DEFAULT_HINT = `Egypt (${DEFAULT_PHONE_PREFIX}) is assumed. Elsewhere, start with + and the country code.`

export const PhoneInput = forwardRef<HTMLInputElement, PhoneInputProps>(function PhoneInput(
  { value, onValueChange, onBlur, label = "Mobile number", hint = DEFAULT_HINT, className, ...props },
  ref,
) {
  const showPrefix = usesDefaultPrefix(value)
  return (
    <Input
      ref={ref}
      label={label}
      hint={hint}
      type="tel"
      inputMode="tel"
      autoComplete="tel"
      autoCapitalize="off"
      autoCorrect="off"
      spellCheck={false}
      value={value}
      onChange={(event) => onValueChange(event.target.value)}
      onBlur={() => {
        const tidy = tidyPhoneInput(value)
        if (tidy !== value) onValueChange(tidy)
        onBlur?.(tidy)
      }}
      leadingIcon={
        showPrefix ? (
          <span className="text-field tabular-nums text-on-surface-variant">{DEFAULT_PHONE_PREFIX}</span>
        ) : undefined
      }
      className={cn(
        showPrefix ? "ps-12" : undefined,
        "transition-[padding-inline-start,border-color] duration-[var(--dur-instant)] ease-out-soft",
        className,
      )}
      {...props}
    />
  )
})
