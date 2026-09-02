/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useEffect, useMemo, useRef, useState, type ClipboardEvent, type FormEvent } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { ArrowLeft } from "@phosphor-icons/react"
import { useAuth } from "@/lib/auth/AuthContext"
import { portalPathForRole } from "@/lib/auth/RequireAuth"
import { Button } from "@/components/ui/button"
import { otpRequestFailureMessage, otpVerifyFailureMessage } from "@/lib/authOutcome"
import { safeNextPath } from "@/lib/nextPath"
import { AuthFrame } from "./Login"

/*
 * G-05 · Parent log in (phone + OTP).
 *
 * "The lowest-friction entry in the product; many parents are not confident
 * users" (UI spec §G-05). Two steps, one decision each, and nothing on screen
 * that isn't required to make the next tap.
 *
 * Backed by the real endpoints (P1.4): POST /auth/otp/request and
 * POST /auth/otp/verify, both already wrapped as mutations in AuthContext —
 * this screen is their first consumer, it does not add a second OTP client.
 *
 * ── Two spec states that do not exist here, and why ──────────────────────────
 *
 * "No account found for this number" is **unreachable by construction**.
 * `AuthService.verify_otp` auto-creates the `role=parent` user on first
 * successful verify, keyed by phone (D3.11) — every verified number ends up
 * with an account, so there is no lookup that can fail. Its honest equivalent
 * is P-01's no-children-linked empty state, which carries the "ask your child
 * to invite you" explanation the spec wanted to put here. Rendering a
 * dead error branch would claim a check the backend does not perform.
 *
 * "Expired code" is not a distinct client branch either: the backend raises
 * one `AuthError` → 401 for wrong, expired, and out-of-attempts, distinguished
 * by an `OtpResult` member inside the detail.
 *
 * **That claim used to end "so the parent reads the actual reason rather than a
 * client-side guess at which it was", and it was half wrong in the way that
 * matters.** The distinction was real; the words were not. `verify_otp` raises
 * `AuthError(f"OTP verification failed: {result.value}")`, so what this screen
 * rendered verbatim was `OTP verification failed: wrong_code` — an enum member,
 * to the reader PRODUCT.md calls the least confident user of the product.
 * `lib/authOutcome.ts` maps the four members to four sentences, which keeps the
 * distinction the docstring was right about and fixes the vocabulary it was
 * wrong about. The 429 on the *request* path is untouched, because there the
 * backend really did write a sentence for a human ("OTP already sent; retry in
 * 12s.") and nothing here could improve on it.
 */

/** Dial codes offered by the country selector. Egypt first and default —
 * MISSION §1 launches there; the rest are the region a Cambridge-syllabus
 * family plausibly logs in from. Not a claim of availability, just a keypad. */
const COUNTRIES = [
  { code: "EG", dial: "+20", label: "Egypt" },
  { code: "SA", dial: "+966", label: "Saudi Arabia" },
  { code: "AE", dial: "+971", label: "United Arab Emirates" },
  { code: "KW", dial: "+965", label: "Kuwait" },
  { code: "QA", dial: "+974", label: "Qatar" },
  { code: "JO", dial: "+962", label: "Jordan" },
  { code: "GB", dial: "+44", label: "United Kingdom" },
] as const

/** Matches `Settings.auth.otp_length` (default 6). */
const CODE_LENGTH = 6

/** Display-only mirror of `Settings.auth.otp_min_resend_seconds` (default 30).
 * The server stays authoritative: an early resend is a real 429 whose `detail`
 * already names the remaining seconds, and that message is what gets rendered.
 * This countdown only stops the parent tapping a button that cannot work yet. */
const RESEND_COOLDOWN_SECONDS = 30

/**
 * Assemble E.164 from the dial code and the locally-typed number.
 *
 * Strips separators and a single leading zero: Egyptian mobiles are written
 * `010 1234 5678` locally but are `+2010…` in E.164, so pasting the number as
 * printed on a phone would otherwise produce `+200101…` and fail to match the
 * parent's own account on the next login.
 */
function toE164(dial: string, local: string): string {
  const digits = local.replace(/\D/g, "").replace(/^0+/, "")
  return `${dial}${digits}`
}

function localDigits(local: string): string {
  return local.replace(/\D/g, "").replace(/^0+/, "")
}

function PhoneStep({
  dial,
  setDial,
  phone,
  setPhone,
  onSubmit,
  isPending,
  error,
}: {
  dial: string
  setDial: (value: string) => void
  phone: string
  setPhone: (value: string) => void
  onSubmit: () => void
  isPending: boolean
  error: string | null
}) {
  // Client-side validity is deliberately loose — a length floor, not a
  // per-country regex. The point is to catch an obvious typo before spending a
  // round trip, not to become a second, drifting authority on what numbers
  // exist. Anything that passes this goes to the server, which decides.
  const digits = localDigits(phone)
  const tooShort = digits.length > 0 && digits.length < 7

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (digits.length < 7) return
    onSubmit()
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <h1 className="text-display-lg text-ink">Check on your child</h1>
        <p className="text-body-md text-ink-muted">
          Enter your phone number and we'll text you a code. No password to remember.
        </p>
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor="parent-country" className="text-body-md font-medium text-ink">
          Country
        </label>
        <select
          id="parent-country"
          value={dial}
          onChange={(event) => setDial(event.target.value)}
          className="rounded-md border border-rule bg-paper-raised px-3 py-3 text-body-md text-ink transition-colors hover:border-rule-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
        >
          {COUNTRIES.map((country) => (
            <option key={country.code} value={country.dial}>
              {country.label} ({country.dial})
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor="parent-phone" className="text-body-md font-medium text-ink">
          Phone number
        </label>
        <div className="flex items-stretch gap-2">
          <span
            aria-hidden="true"
            className="flex items-center rounded-md border border-rule bg-paper-sunk px-3 text-data-md text-ink-muted"
          >
            {dial}
          </span>
          <input
            id="parent-phone"
            type="tel"
            inputMode="tel"
            autoComplete="tel-national"
            required
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            aria-describedby={tooShort ? "parent-phone-hint" : undefined}
            aria-invalid={tooShort || undefined}
            className="min-w-0 flex-1 rounded-md border border-rule bg-paper-raised px-3 py-3 text-data-md text-ink transition-colors hover:border-rule-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          />
        </div>
        {tooShort ? (
          <p id="parent-phone-hint" className="text-body-md text-warn">
            That looks too short. Check the number and try again.
          </p>
        ) : null}
      </div>

      {error ? (
        <p role="alert" className="text-body-md text-warn">
          {error}
        </p>
      ) : null}

      <Button
        type="submit"
        variant="accent"
        size="lg"
        disabled={isPending || digits.length < 7}
      >
        {isPending ? "Sending…" : "Send code"}
      </Button>
    </form>
  )
}

function CodeStep({
  e164,
  digits,
  setDigits,
  onChangeNumber,
  onResend,
  isPending,
  isResending,
  error,
  cooldown,
  devCode,
}: {
  e164: string
  digits: string[]
  setDigits: (next: string[]) => void
  onChangeNumber: () => void
  onResend: () => void
  isPending: boolean
  isResending: boolean
  error: string | null
  cooldown: number
  devCode: string | null
}) {
  const inputs = useRef<(HTMLInputElement | null)[]>([])

  useEffect(() => {
    inputs.current[0]?.focus()
  }, [])

  const setAt = (index: number, value: string) => {
    const next = [...digits]
    next[index] = value
    setDigits(next)
  }

  const handleChange = (index: number, raw: string) => {
    const value = raw.replace(/\D/g, "").slice(-1)
    setAt(index, value)
    // Auto-advance. Only forward, and only on an actual digit — advancing on a
    // cleared box would make backspace jump the caret past the box the parent
    // just emptied.
    if (value && index < CODE_LENGTH - 1) inputs.current[index + 1]?.focus()
  }

  const handleKeyDown = (index: number, key: string) => {
    if (key === "Backspace" && !digits[index] && index > 0) {
      inputs.current[index - 1]?.focus()
      setAt(index - 1, "")
    }
    if (key === "ArrowLeft" && index > 0) inputs.current[index - 1]?.focus()
    if (key === "ArrowRight" && index < CODE_LENGTH - 1) inputs.current[index + 1]?.focus()
  }

  // Paste support: a parent copying the whole code from their SMS app pastes
  // it into whichever box happens to be focused, so distribute from box 0
  // rather than dropping five of the six characters.
  const handlePaste = (event: ClipboardEvent<HTMLInputElement>) => {
    const pasted = event.clipboardData.getData("text").replace(/\D/g, "").slice(0, CODE_LENGTH)
    if (!pasted) return
    event.preventDefault()
    const next = Array.from({ length: CODE_LENGTH }, (_, i) => pasted[i] ?? "")
    setDigits(next)
    inputs.current[Math.min(pasted.length, CODE_LENGTH - 1)]?.focus()
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <h1 className="text-display-lg text-ink">Enter your code</h1>
        <p className="text-body-md text-ink-muted">
          We sent a {CODE_LENGTH}-digit code to <span className="text-data-md text-ink">{e164}</span>.
        </p>
      </div>

      {/*
        §6.1's 44x44 floor cannot be met on the inline axis here, and the
        exemption is stated rather than left for the gate to report forever.

        Six boxes at 44px plus five 8px gaps need 284px. At the 320px viewport
        the mission names, this card offers about 248px, so the floor is
        arithmetically unreachable without dropping a digit or scrolling a code
        entry sideways. The gaps tighten below `sm` to spend as much of that
        width as possible on the boxes themselves.

        What the reader gets instead: each box is 56px TALL (well over the
        floor on the axis that is available), the six tile the row with no dead
        space between them, and a mis-tap lands on an adjacent digit box, which
        is visible on screen and recoverable with one keystroke. The audit
        reports these as `exempt` with this reason attached, so the carve-out
        appears in every run's summary instead of hiding in this file.
      */}
      <div
        role="group"
        aria-label={`${CODE_LENGTH}-digit verification code`}
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
            // whole value into the field that declares it, and six of them
            // would each receive all six characters.
            autoComplete={index === 0 ? "one-time-code" : "off"}
            aria-label={`Digit ${index + 1} of ${CODE_LENGTH}`}
            maxLength={1}
            value={digit}
            disabled={isPending}
            onChange={(event) => handleChange(index, event.target.value)}
            onKeyDown={(event) => handleKeyDown(index, event.key)}
            onPaste={handlePaste}
            className="h-14 w-full min-w-0 rounded-md border border-rule bg-paper-raised text-center text-data-lg text-ink transition-colors hover:border-rule-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          />
        ))}
      </div>

      <p role="status" aria-live="polite" className="min-h-5 text-body-md">
        {isPending ? (
          <span className="text-ink-muted">Checking your code…</span>
        ) : error ? (
          <span className="text-warn">{error}</span>
        ) : null}
      </p>

      {/*
       * §G-05's mandated developer affordance (D3.16). Present only when the
       * backend says the configured SMS provider does not deliver out of band
       * — with a real gateway `devCode` is null and this panel does not exist.
       * The client does not decide; it renders what the backend disclosed.
       */}
      {devCode ? (
        <div className="rounded-md border border-dashed border-rule bg-paper-sunk p-4">
          <div className="text-eyebrow text-ink-faint">
            Developer only · no SMS was sent
          </div>
          <div className="mt-1.5 text-data-lg text-ink">{devCode}</div>
          <p className="mt-1.5 text-body-sm text-ink-muted">
            This appears because Lemely is running with the offline mock SMS provider.
            With a real provider configured, the code is never shown here.
          </p>
        </div>
      ) : null}

      <div className="flex flex-col gap-3">
        <Button
          type="button"
          variant="secondary"
          size="md"
          onClick={onResend}
          disabled={isResending || cooldown > 0}
        >
          {cooldown > 0
            ? `Resend code in ${cooldown}s`
            : isResending
              ? "Sending…"
              : "Resend code"}
        </Button>
        <Button type="button" variant="ghost" size="md" onClick={onChangeNumber}>
          Change number
        </Button>
      </div>
    </div>
  )
}

export function ParentLogin() {
  const { requestOtp, verifyOtp } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  // PR 2 part A2: same `?next=` handling as `Login.tsx`'s own success
  // handler — see that component's comment for why it is re-validated here
  // rather than trusted from whichever screen sent this reader on.
  const next = safeNextPath(searchParams.get("next"))

  const [dial, setDial] = useState<string>(COUNTRIES[0].dial)
  const [phone, setPhone] = useState("")
  const [sentTo, setSentTo] = useState<string | null>(null)
  const [devCode, setDevCode] = useState<string | null>(null)
  const [digits, setDigits] = useState<string[]>(() => Array(CODE_LENGTH).fill(""))
  const [cooldown, setCooldown] = useState(0)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [verifyError, setVerifyError] = useState<string | null>(null)

  const code = useMemo(() => digits.join(""), [digits])

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = window.setTimeout(() => setCooldown((n) => n - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [cooldown])

  const send = (e164: string) => {
    setRequestError(null)
    requestOtp.mutate(
      { phone: e164 },
      {
        onSuccess: (result) => {
          setSentTo(e164)
          setDevCode(result.devCode)
          setDigits(Array(CODE_LENGTH).fill(""))
          setVerifyError(null)
          setCooldown(RESEND_COOLDOWN_SECONDS)
        },
        // The backend's real `detail` — a 429 already names the seconds left,
        // so there is nothing better to say than what it said.
        onError: (err) => setRequestError(otpRequestFailureMessage(err)),
      },
    )
  }

  // Auto-submit the moment the code is complete (spec: "Code auto-submits when
  // complete"). Guarded on `isPending` and on the code having changed since the
  // last failure, so a wrong code doesn't resubmit itself in a loop while the
  // parent is still looking at the error.
  const lastAttempted = useRef<string | null>(null)
  useEffect(() => {
    if (!sentTo) return
    if (code.length !== CODE_LENGTH) return
    if (verifyOtp.isPending) return
    if (lastAttempted.current === code) return
    lastAttempted.current = code
    setVerifyError(null)
    verifyOtp.mutate(
      { phone: sentTo, code },
      {
        onSuccess: (result) => navigate(next ?? portalPathForRole(result.role), { replace: true }),
        onError: (err) => setVerifyError(otpVerifyFailureMessage(err)),
      },
    )
  }, [code, sentTo, verifyOtp, navigate, next])

  return (
    /*
     * The frame is `AuthFrame`, shared with the password screen. The mark it
     * renders is the real one, which retires audit finding M9's **fourth**
     * stamp — the finding was written as "stamped in three places", and the
     * accent-circle-with-an-italic-l was here too, in the one signed-out screen
     * the audit reached by grep rather than by rendering. It was also this
     * file's only two `font-serif` call sites (D4.1), so the placeholder was
     * not even drawing in the face it reached for.
     *
     * P7.1: that first sentence was not true when it was written. This screen
     * carried its own copy of the frame's markup — identical `<main>`, identical
     * mark-and-wordmark block — because `AuthFrame` took no prop for the
     * `data-portal="parent"` it needs. It takes one now, so the sentence and
     * the code finally agree, and M12's fix landed in one place rather than
     * being applied twice and drifting later.
     */
    <AuthFrame dataPortal="parent">
      <div className="flex w-full max-w-100 flex-col gap-6">
        <div className="rounded-lg border border-rule bg-paper-raised p-8">
          {sentTo === null ? (
            <PhoneStep
              dial={dial}
              setDial={setDial}
              phone={phone}
              setPhone={setPhone}
              onSubmit={() => send(toE164(dial, phone))}
              isPending={requestOtp.isPending}
              error={requestError}
            />
          ) : (
            <CodeStep
              e164={sentTo}
              digits={digits}
              setDigits={setDigits}
              onChangeNumber={() => {
                setSentTo(null)
                setDevCode(null)
                setVerifyError(null)
                lastAttempted.current = null
              }}
              onResend={() => send(sentTo)}
              isPending={verifyOtp.isPending}
              isResending={requestOtp.isPending}
              error={verifyError ?? requestError}
              cooldown={cooldown}
              devCode={devCode}
            />
          )}
        </div>

        <Link
          to="/login"
          className="flex items-center gap-1.5 self-start rounded-sm pointer-coarse:min-h-11 text-body-sm text-ink-muted transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
        >
          {/* Direction-dependent: this arrow points at the reading start and
              must mirror under `dir="rtl"` (P3.4). */}
          <ArrowLeft size={14} aria-hidden="true" className="rtl:-scale-x-100" />
          Sign in with an email instead
        </Link>
      </div>
    </AuthFrame>
  )
}
