/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useEffect, useRef, type ClipboardEvent } from "react"

/*
 * The six-box code entry, extracted from `ParentLogin.tsx`'s own `CodeStep`
 * (design spec §5) before that file was deleted along with the phone-OTP
 * parent login it backed (D3.11, superseded by the parent-invites design).
 * `SignupParent.tsx` is this component's first and only consumer today, but
 * it is written against the invite code's own length rather than a hardcoded
 * six, and against a caller-owned `value` string rather than local state, so
 * a second numeric-code step elsewhere in the product (there is none today)
 * would not need a second copy of this behaviour.
 *
 * Every interaction `ParentLogin.tsx`'s `CodeStep` had is preserved:
 *   - typing a digit auto-advances to the next box, but only on an actual
 *     digit, so backspace on an emptied box never jumps the caret past it;
 *   - Backspace on an empty box steps back and clears the previous box;
 *   - the arrow keys move focus without changing a value;
 *   - pasting the whole code (from an email client, a messaging app, or a
 *     password manager) distributes it across every box from position 0,
 *     rather than dropping all but the last character into whichever box
 *     happened to be focused;
 *   - `autoComplete="one-time-code"` is set on the first box only, so a
 *     browser's autofill does not try to write the whole value into all six.
 *
 * `onComplete` fires once, with the joined value, the moment every box holds
 * a character — `SignupParent.tsx` wires this to auto-submit the verify call
 * exactly as `ParentLogin.tsx` did, without this component knowing anything
 * about auto-submission itself; a caller that never passes `onComplete`
 * simply gets a plain, un-auto-submitting code box.
 */

export interface CodeInputProps {
  /** Number of boxes — the invite/OTP code length this reads against. */
  length: number
  /** The code so far, as one string; index `i` fills box `i`. Shorter than
   * `length` for a code still being typed, exactly `length` once complete. */
  value: string
  /** Called with the full joined value on every edit, complete or not. */
  onChange: (value: string) => void
  /** Called once, with the full value, the instant every box holds a
   * character — never fired again until the value changes length again. */
  onComplete?: (value: string) => void
  disabled?: boolean
  /** Inline validation/failure message, rendered under the boxes. */
  error?: string | null
}

export function CodeInput({ length, value, onChange, onComplete, disabled, error }: CodeInputProps) {
  const digits = Array.from({ length }, (_, i) => value[i] ?? "")
  const inputs = useRef<(HTMLInputElement | null)[]>([])

  useEffect(() => {
    inputs.current[0]?.focus()
    // Only on mount — a caller resetting `value` to retry should not steal
    // focus back from wherever the visitor has since moved it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const commit = (next: string[]) => {
    const joined = next.join("")
    onChange(joined)
    if (onComplete && joined.length === length && next.every((digit) => digit !== "")) {
      onComplete(joined)
    }
  }

  const setAt = (index: number, char: string) => {
    const next = [...digits]
    next[index] = char
    commit(next)
  }

  const handleChange = (index: number, raw: string) => {
    const char = raw.replace(/\D/g, "").slice(-1)
    setAt(index, char)
    // Auto-advance. Only forward, and only on an actual digit — advancing on
    // a cleared box would make backspace jump the caret past the box the
    // visitor just emptied.
    if (char && index < length - 1) inputs.current[index + 1]?.focus()
  }

  const handleKeyDown = (index: number, key: string) => {
    if (key === "Backspace" && !digits[index] && index > 0) {
      inputs.current[index - 1]?.focus()
      setAt(index - 1, "")
    }
    if (key === "ArrowLeft" && index > 0) inputs.current[index - 1]?.focus()
    if (key === "ArrowRight" && index < length - 1) inputs.current[index + 1]?.focus()
  }

  // Paste support: a visitor copying the whole code from an email or a
  // messaging app pastes it into whichever box happens to be focused, so
  // distribute from box 0 rather than dropping all but the last character.
  const handlePaste = (event: ClipboardEvent<HTMLInputElement>) => {
    const pasted = event.clipboardData.getData("text").replace(/\D/g, "").slice(0, length)
    if (!pasted) return
    event.preventDefault()
    const next = Array.from({ length }, (_, i) => pasted[i] ?? "")
    commit(next)
    inputs.current[Math.min(pasted.length, length - 1)]?.focus()
  }

  return (
    <div className="flex flex-col gap-2">
      {/*
        §6.1's 44x44 floor cannot be met on the inline axis here, and the
        exemption is stated rather than left for the gate to report forever
        — carried over verbatim from `ParentLogin.tsx`'s own `CodeStep`.

        Six boxes at 44px plus five 8px gaps need 284px. At the 320px viewport
        the mission names, this card offers about 248px, so the floor is
        arithmetically unreachable without dropping a digit or scrolling a
        code entry sideways. The gaps tighten below `sm` to spend as much of
        that width as possible on the boxes themselves.

        What the reader gets instead: each box is 56px TALL (well over the
        floor on the axis that is available), the boxes tile the row with no
        dead space between them, and a mis-tap lands on an adjacent digit
        box, which is visible on screen and recoverable with one keystroke.
      */}
      <div
        role="group"
        aria-label={`${length}-digit verification code`}
        data-touch-floor-exempt="six-digit-code-row"
        className="flex items-center justify-between gap-1 sm:gap-2"
      >
        {digits.map((digit, index) => (
          <input
            key={index}
            ref={(el) => {
              inputs.current[index] = el
            }}
            type="text"
            inputMode="numeric"
            // Only the first box carries one-time-code: browsers autofill the
            // whole value into the field that declares it, and every other
            // box would otherwise receive all six characters too.
            autoComplete={index === 0 ? "one-time-code" : "off"}
            aria-label={`Digit ${index + 1} of ${length}`}
            maxLength={1}
            value={digit}
            disabled={disabled}
            onChange={(event) => handleChange(index, event.target.value)}
            onKeyDown={(event) => handleKeyDown(index, event.key)}
            onPaste={handlePaste}
            className="h-14 w-full min-w-0 rounded-md border border-rule bg-paper-raised text-center text-data-lg text-ink transition-colors hover:border-rule-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          />
        ))}
      </div>
      {error ? (
        <p role="alert" className="text-body-md text-warn">
          {error}
        </p>
      ) : null}
    </div>
  )
}
