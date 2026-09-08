/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useEffect, useRef, useState, type ClipboardEvent } from "react"
import {
  applyBackspace,
  applyDigitChange,
  applyPaste,
  digitsFromValue,
  isCodeComplete,
  joinDigits,
} from "./codeInputLogic"

/*
 * The six-box code entry, extracted from `ParentLogin.tsx`'s own `CodeStep`
 * (design spec §5) before that file was deleted along with the phone-OTP
 * parent login it backed (D3.11, superseded by the parent-invites design).
 * `SignupParent.tsx` is this component's first and only consumer today, but
 * it is written against the invite code's own length rather than a hardcoded
 * six, so a second numeric-code step elsewhere in the product (there is none
 * today) would not need a second copy of this behaviour.
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
 *
 * ── Review round 1, Important finding 1: positions are now real state ──────
 *
 * The first cut of this component held no state of its own — it derived its
 * boxes from a caller-owned `value: string` on every render
 * (`value[i] ?? ""`) and reported edits back by joining the boxes into a
 * string. That round trip cannot represent an empty box before a filled one:
 * `["1","2","","4","5","6"].join("")` is `"12456"`, and re-splitting that
 * five-character string back into six boxes shifts every digit after the gap
 * one place left. Correcting a middle digit — or clicking into an empty box
 * out of typing order — silently mangled the code, with no test to catch it
 * (this component cannot be rendered under this project's node-only vitest
 * config, per `vitest.config.ts`'s own header).
 *
 * The fix, matching what `ParentLogin.tsx`'s `CodeStep` actually did: the
 * digit array lives in this component's own `useState`, exactly like the
 * original held `digits` in its parent's state. `value` is now read exactly
 * once, as the lazy initial state on mount (`digitsFromValue`), never
 * resynced from a later prop change. A caller that needs to clear the boxes
 * mid-flow — a resend, a fresh code request — changes this component's
 * `key` instead, forcing React to remount it with fresh state, the same
 * technique `routes.tsx`'s `JoinWithCode` wrapper already uses to reset a
 * screen when the resource behind it changes. `SignupParent.tsx` does this
 * by keying `<CodeInput>` on the email plus a generation counter that bumps
 * on every successful `request-code` call, fresh send or resend alike.
 *
 * Every position-sensitive decision (which box to advance to, which box a
 * backspace clears, how a paste distributes) is a pure function in
 * `./codeInputLogic.ts`, tested directly in `codeInputLogic.test.ts` — this
 * file only wires those decisions to DOM events and focus calls.
 */

export interface CodeInputProps {
  /** Number of boxes — the invite/OTP code length this reads against. */
  length: number
  /** The value this box starts filled in with on mount. Read once, via a
   * lazy initializer — not resynced on a later change. To clear or replace
   * the code mid-flow, change this component's `key` instead, forcing a
   * real remount; see the module docstring's own note on why. */
  value: string
  /** Called with the full joined value on every edit, complete or not. */
  onChange: (value: string) => void
  /** Called once, with the full value, the instant every box holds a
   * character — never fired again until the code changes again. */
  onComplete?: (value: string) => void
  disabled?: boolean
  /** Inline validation/failure message, rendered under the boxes. */
  error?: string | null
}

export function CodeInput({ length, value, onChange, onComplete, disabled, error }: CodeInputProps) {
  const [digits, setDigits] = useState(() => digitsFromValue(value, length))
  const inputs = useRef<(HTMLInputElement | null)[]>([])

  useEffect(() => {
    inputs.current[0]?.focus()
    // Only on mount — a caller resetting the code via a fresh `key` gets a
    // freshly-mounted instance, which already re-runs this effect on its
    // own; this dependency array is deliberately not `[digits]`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const commit = (next: { digits: string[]; focusIndex: number }) => {
    setDigits(next.digits)
    onChange(joinDigits(next.digits))
    inputs.current[next.focusIndex]?.focus()
    if (onComplete && isCodeComplete(next.digits)) onComplete(joinDigits(next.digits))
  }

  const handleChange = (index: number, raw: string) => {
    commit(applyDigitChange(digits, index, raw))
  }

  const handleKeyDown = (index: number, key: string) => {
    if (key === "Backspace") {
      const result = applyBackspace(digits, index)
      if (result) commit(result)
      return
    }
    if (key === "ArrowLeft" && index > 0) inputs.current[index - 1]?.focus()
    if (key === "ArrowRight" && index < length - 1) inputs.current[index + 1]?.focus()
  }

  // Paste support: a visitor copying the whole code from an email or a
  // messaging app pastes it into whichever box happens to be focused, so
  // distribute from box 0 rather than dropping all but the last character.
  const handlePaste = (event: ClipboardEvent<HTMLInputElement>) => {
    const result = applyPaste(length, event.clipboardData.getData("text"))
    if (!result) return
    event.preventDefault()
    commit(result)
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
