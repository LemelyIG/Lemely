/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useEffect, useMemo, useRef, useState, type ElementType } from 'react'
import {
  ArrowLeft,
  ArrowRight,
  CaretDown,
  Check,
  Link as LinkIcon,
  ShareNetwork,
  WarningCircle,
  X,
} from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { Toggle, toggleVariants } from '@/components/ui/toggle'
import { Input } from '@/components/ui/input'
import { RadioGroup, Radio } from '@/components/ui/radio'
import { Switch } from '@/components/ui/switch'
import {
  WAITLIST_BOARDS,
  WAITLIST_BOARD_LABELS,
  WAITLIST_LEVELS,
  WAITLIST_LEVEL_LABELS,
  MAX_OTHER_SUBJECTS,
  TOP_SUBJECTS,
  WAITLIST_CONSENT_TEXT,
  WAITLIST_CONSENT_VERSION,
  WAITLIST_ROLES,
  WAITLIST_ROLE_LABELS,
  WaitlistError,
  completeWaitlist,
  examSessionOptions,
  getWaitlistConfig,
  normaliseWaitlistName,
  normaliseWaitlistPhone,
  validateWaitlistName,
  validateWaitlistPhone,
  waitlistFirstName,
  WAITLIST_LIMITS,
  waitlistFieldErrors,
  type WaitlistConfig,
  joinWaitlist,
  waitlistFailureCopy,
  waitlistSubjectLabel,
  type WaitlistBoard,
  type WaitlistLevel,
  type WaitlistRole,
  type WaitlistStep1,
  type WaitlistStep1Result,
  type WaitlistStep2,
  type WaitlistSubject,
} from '@/lib/waitlist-api'
import { Binny } from '../Binny'
import { CONFIG_FAILED_COPY, EXPIRED_COPY, TURNSTILE_FAILED_COPY, classifyStep2Failure, continueStep1, withRetry } from './flow'
import { SubjectPicker } from './SubjectPicker'
import { useTurnstile } from './turnstile'
import { readWaitlistUtm } from './utm'

export const WAITLIST_SHARE_URL = () =>
  `${window.location.origin}/?utm_source=waitlist_share`

export interface WaitlistClient {
  join: (input: WaitlistStep1) => Promise<WaitlistStep1Result>
  complete: (input: WaitlistStep2) => Promise<void>
  /** The server's public settings (Turnstile site key). Failure means "render without it". */
  config: () => Promise<WaitlistConfig>
}
export const liveWaitlistClient: WaitlistClient = {
  join: joinWaitlist,
  complete: completeWaitlist,
  config: getWaitlistConfig,
}

type Status = 'idle' | 'submitting' | 'network' | 'rate' | 'failed'
type FieldErrors = Partial<Record<'email' | 'name' | 'role' | 'subjects' | 'phone' | 'centre', string>>

/** Initial state, so a state can be shown without clicking through to it (preview gallery, tests). */
export interface WaitlistSeed {
  step: 1 | 2 | 'done'
  role?: WaitlistRole
  email?: string
  name?: string
  status?: Status
  errors?: FieldErrors
  duplicate?: boolean
  levels?: WaitlistLevel[]
  subjects?: WaitlistSubject[]
  otherSubjects?: string[]
  boards?: WaitlistBoard[]
  session?: string
  phone?: string
  whatsapp?: boolean
  centre?: string
  pickerOpen?: boolean
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/

const HEADLINE: Record<WaitlistRole | 'none', string> = {
  none: 'Get on the list',
  student: 'From paper to A*.',
  teacher: 'Every mark, explained.',
  parent: 'Turn past papers into progress.',
  centre_admin: 'Turn past papers into progress.',
}
const LEAD: Record<WaitlistRole | 'none', string> = {
  none: "Tell us who you are and we'll email you when access opens.",
  student: 'Snap a past paper, see every lost mark, know what to do next.',
  teacher: 'Marked against the official scheme, with the reasoning shown.',
  parent: 'See where your child loses marks, and what to practise next.',
  centre_admin: 'Mark class sets against the official scheme and see where a group slips.',
}
const LEVEL_Q: Record<WaitlistRole, string> = {
  student: 'Which level are you studying?',
  teacher: 'Which levels do you teach?',
  parent: 'Which level is your child studying?',
  centre_admin: 'Which levels do you prepare students for?',
}
const SUBJECT_Q: Record<WaitlistRole, string> = {
  student: 'Which subjects do you study?',
  teacher: 'Which subjects do you teach?',
  parent: 'Which subjects does your child study?',
  centre_admin: 'Which subjects do you teach?',
}
const ROLE_HINT: Partial<Record<WaitlistRole, string>> = {
  centre_admin: 'Runs or manages an IG education centre',
}

function Choice({
  on,
  children,
  onClick,
  ...props
}: { on: boolean; children: React.ReactNode } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <Toggle variant="choice" size="chip" pressed={on} onPressedChange={() => {}} onClick={onClick} {...props}>
      {on ? <Check size={14} weight="bold" aria-hidden /> : null}
      {children}
    </Toggle>
  )
}

function Group({
  legend,
  hint,
  error,
  children,
}: {
  legend: string
  hint?: string
  error?: string
  children: React.ReactNode
}) {
  return (
    <fieldset className="m-0 flex min-w-0 flex-col gap-2 border-0 p-0">
      <legend className="lw-legend mb-2 p-0">
        {legend}
        {hint ? <span className="ms-2 font-normal text-on-surface-variant">{hint}</span> : null}
      </legend>
      {children}
      {error ? (
        <p className="m-0 flex items-center gap-1.5 text-body-sm text-error" role="alert">
          <WarningCircle size={16} weight="fill" aria-hidden />
          {error}
        </p>
      ) : null}
    </fieldset>
  )
}

function toggle<T>(list: T[], v: T): T[] {
  return list.includes(v) ? list.filter((x) => x !== v) : [...list, v]
}

export function WaitlistPanel({
  seed = { step: 1 },
  Title = 'h2',
  onClose,
  mobile,
  client = liveWaitlistClient,
  escapeGuard,
}: {
  seed?: WaitlistSeed
  Title?: ElementType
  onClose?: () => void
  mobile?: boolean
  client?: WaitlistClient
  /** The dialog consults this before Esc closes it: the subject picker takes the key first. */
  escapeGuard?: { current: (() => boolean) | null }
}) {
  const [step, setStep] = useState<WaitlistSeed['step']>(seed.step)
  const [role, setRole] = useState<WaitlistRole | undefined>(seed.role)
  const [email, setEmail] = useState(seed.email ?? '')
  const [name, setName] = useState(seed.name ?? '')
  const [status, setStatus] = useState<Status>(seed.status ?? 'idle')
  const [failure, setFailure] = useState('')
  const [errors, setErrors] = useState<FieldErrors>(seed.errors ?? {})
  const [dup, setDup] = useState(!!seed.duplicate)
  const [token, setToken] = useState('')
  const [expired, setExpired] = useState(false)
  const [siteKey, setSiteKey] = useState<string | null>(null)
  const [waiting, setWaiting] = useState(false)
  // The site key comes from the server. Submitting before it is known would skip the challenge
  // and be refused for good, so a submit waits for it (`pendingCfg`) and a failed load is retried.
  const [cfg, setCfg] = useState<'loading' | 'ready' | 'failed'>('loading')
  const [cfgTry, setCfgTry] = useState(0)
  const [pendingCfg, setPendingCfg] = useState(false)
  const tsBox = useRef<HTMLDivElement>(null)
  const ts = useTurnstile(step === 1 && !token ? siteKey : null, tsBox)
  const heading = useRef<HTMLElement>(null)
  const shown = useRef({ step: seed.step, dup: !!seed.duplicate, expired: false })
  const [levels, setLevels] = useState<WaitlistLevel[]>(seed.levels ?? [])
  const [subjects, setSubjects] = useState<WaitlistSubject[]>(seed.subjects ?? [])
  const [others, setOthers] = useState<string[]>(seed.otherSubjects ?? [])
  const [boards, setBoards] = useState<WaitlistBoard[]>(seed.boards ?? [])
  const [session, setSession] = useState(seed.session ?? '')
  const [phone, setPhone] = useState(seed.phone ?? '')
  const [wa, setWa] = useState(!!seed.whatsapp)
  const [centre, setCentre] = useState(seed.centre ?? '')
  const [pickerOpen, setPickerOpen] = useState(!!seed.pickerOpen)
  const [copied, setCopied] = useState(false)
  const [honeypot, setHoneypot] = useState('')
  const sessions = useMemo(() => examSessionOptions(), [])
  const body = useRef<HTMLDivElement>(null)
  const r = role ?? 'none'
  const firstName = waitlistFirstName(name)
  const topValues: readonly string[] = TOP_SUBJECTS.map((x) => x.value)
  const extraSubjects = subjects.filter((v) => !topValues.includes(v))
  const title = dup ? "You're already on the list" : HEADLINE[r]
  const lead = expired ? EXPIRED_COPY : dup ? `${email} is already on the list. We've sent a fresh link: check your inbox to confirm your email.` : LEAD[r]

  useEffect(() => {
    let live = true
    withRetry(() => client.config())
      .then((c) => {
        if (!live) return
        setSiteKey(c.turnstileSiteKey)
        setCfg('ready')
      })
      .catch(() => live && setCfg('failed'))
    return () => {
      live = false
    }
  }, [client, cfgTry])

  function reloadConfig() {
    setCfg('loading')
    setCfgTry((n) => n + 1)
  }

  useEffect(() => {
    body.current?.scrollTo({ top: 0 })
  }, [step])

  // Move focus to the new heading on a step change, a duplicate, an expired link and success,
  // so a screen reader announces where it is. Not on first render: the email field keeps focus.
  useEffect(() => {
    const was = shown.current
    if (was.step === step && was.dup === dup && was.expired === expired) return
    shown.current = { step, dup, expired }
    heading.current?.focus({ preventScroll: true })
  }, [step, dup, expired])

  function fail(error: unknown) {
    if (step === 2 && classifyStep2Failure(error) === 'expired') {
      setStatus('idle')
      return setExpired(true)
    }
    // A 422 names the fields at fault: show each one inline, on the step it lives on.
    const fieldErrors = waitlistFieldErrors(error)
    if (Object.keys(fieldErrors).length) {
      const mapped: FieldErrors = {}
      if (fieldErrors.email) mapped.email = fieldErrors.email
      if (fieldErrors.name) mapped.name = fieldErrors.name
      if (fieldErrors.role) mapped.role = fieldErrors.role
      if (fieldErrors.subjects || fieldErrors.otherSubjects) mapped.subjects = fieldErrors.subjects ?? fieldErrors.otherSubjects
      if (fieldErrors.phone) mapped.phone = fieldErrors.phone
      if (fieldErrors.centreName) mapped.centre = fieldErrors.centreName
      if (Object.keys(mapped).length) {
        setErrors(mapped)
        return setStatus('idle')
      }
      setFailure(Object.values(fieldErrors)[0])
      return setStatus('failed')
    }
    if (error instanceof WaitlistError && error.status === 403 && error.code === 'turnstile_failed') {
      // The challenge was missing or refused: fetch the config again so the widget can render.
      reloadConfig()
      setFailure(TURNSTILE_FAILED_COPY)
      return setStatus('failed')
    }
    if (error instanceof WaitlistError && error.status === 0) return setStatus('network')
    if (error instanceof WaitlistError && error.status === 429) return setStatus('rate')
    setFailure(waitlistFailureCopy(error))
    setStatus('failed')
  }

  async function attemptJoin(): Promise<WaitlistStep1Result | null> {
    const e: FieldErrors = {}
    if (!EMAIL_RE.test(email.trim())) e.email = 'Enter an email like name@school.com.'
    const nameError = validateWaitlistName(name)
    if (nameError) e.name = nameError
    if (!role) e.role = 'Pick the option that fits you.'
    setErrors(e)
    if (Object.keys(e).length || !role) return null
    if (cfg !== 'ready') {
      // Wait for the site key (or load it again if it failed) before going to the server.
      if (cfg === 'failed') reloadConfig()
      setPendingCfg(true)
      setStatus('submitting')
      return null
    }
    if (ts.required) {
      if (ts.state === 'error') {
        ts.reset()
        return null
      }
      if (!ts.token) {
        // The challenge is still running in the background; submit as soon as it hands over a token.
        setWaiting(true)
        setStatus('submitting')
        return null
      }
    }
    setStatus('submitting')
    return client.join({
      email: email.trim(),
      name: normaliseWaitlistName(name),
      role,
      consentVersion: WAITLIST_CONSENT_VERSION,
      website: honeypot,
      turnstileToken: ts.token || undefined,
      ...readWaitlistUtm(),
    })
  }

  async function next() {
    try {
      const out = await continueStep1(token, attemptJoin)
      if (out.kind === 'step-2') return setStep(2)
      if (out.kind === 'stopped') return
      setStatus('idle')
      if (out.result.status === 'already_listed') setDup(true)
      else {
        setToken(out.result.token)
        setStep(2)
      }
    } catch (error) {
      ts.reset()
      fail(error)
    }
  }

  useEffect(() => {
    if (waiting && ts.token) {
      setWaiting(false)
      void next()
    }
    if (pendingCfg && cfg === 'ready') {
      setPendingCfg(false)
      void next()
    }
    if (pendingCfg && cfg === 'failed') {
      setPendingCfg(false)
      setFailure(CONFIG_FAILED_COPY)
      setStatus('failed')
    }
    if (waiting && ts.state === 'error') {
      setWaiting(false)
      setStatus('idle')
    }
  }) // eslint-disable-line react-hooks/exhaustive-deps

  async function join() {
    const e: FieldErrors = {}
    if (!subjects.length && !others.length) e.subjects = 'Pick at least one subject.'
    const phoneError = validateWaitlistPhone(phone)
    if (phoneError) e.phone = phoneError
    setErrors(e)
    if (Object.keys(e).length) return
    setStatus('submitting')
    try {
      await client.complete({
        token,
        levels,
        subjects,
        otherSubjects: others,
        examBoards: boards,
        examSession: role === 'centre_admin' ? null : session || null,
        phone: normaliseWaitlistPhone(phone),
        phoneHasWhatsapp: phone.trim() ? wa : false,
        centreName: role === 'centre_admin' ? centre.trim() || null : null,
        website: honeypot,
      })
      setStatus('idle')
      setStep('done')
    } catch (error) {
      fail(error)
    }
  }

  function addOther(text: string) {
    const value = text.trim()
    if (!value || others.length >= MAX_OTHER_SUBJECTS) return
    if (!others.some((o) => o.toLowerCase() === value.toLowerCase())) setOthers([...others, value])
    setErrors((x) => ({ ...x, subjects: undefined }))
  }

  async function share() {
    const url = WAITLIST_SHARE_URL()
    try {
      if (mobile && navigator.share) {
        await navigator.share({ url, title: 'Lemely' })
        return
      }
      await navigator.clipboard?.writeText(url)
    } catch {
      /* the user dismissed the native sheet, or the clipboard is blocked */
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 2400)
  }

  const busy = status === 'submitting'
  const retry = status === 'network' || status === 'rate' || status === 'failed' || (step === 1 && ts.state === 'error')
  const banner =
    status === 'network' ? (
      <p className="lw-banner err m-0" role="alert">
        <WarningCircle size={18} weight="fill" className="mt-px shrink-0" aria-hidden />
        <span>
          We couldn't reach Lemely. Check your connection and try again, or email{' '}
          <a href="mailto:contact@lemelyig.com">contact@lemelyig.com</a>.
        </span>
      </p>
    ) : status === 'rate' ? (
      <p className="lw-banner err m-0" role="alert">
        <WarningCircle size={18} weight="fill" className="mt-px shrink-0" aria-hidden />
        <span>Too many tries from this connection. Try again in a few minutes.</span>
      </p>
    ) : status === 'failed' ? (
      <p className="lw-banner err m-0" role="alert">
        <WarningCircle size={18} weight="fill" className="mt-px shrink-0" aria-hidden />
        <span>{failure}</span>
      </p>
    ) : null

  const consent = (
    <p className="m-0 text-center text-body-sm text-on-surface-variant">
      {WAITLIST_CONSENT_TEXT}{' '}
      <a className="font-semibold text-primary underline underline-offset-4" href="/data">
        How your data is handled
      </a>
    </p>
  )

  return (
    <div className="lw-panel relative flex min-h-0 flex-1 flex-col">
      <div
        ref={body}
        className="lw-scrollbody flex min-h-0 flex-1 flex-col gap-6 px-5 pb-4 pt-6 sm:px-8 sm:pt-8"
      >
        <header className="flex flex-col gap-2 pe-10">
          <Title ref={heading} tabIndex={-1} className="lw-title">{title}</Title>
          {step === 'done' ? null : (
            <p className="m-0 max-w-[44ch] text-body-md text-on-surface-variant">{lead}</p>
          )}
        </header>

        {step === 1 && !dup && !expired ? (
          <form
            id="lw-form"
            noValidate
            onSubmit={(e) => {
              e.preventDefault()
              void next()
            }}
            className="flex flex-col gap-5"
          >
            {/* Honeypot: a field no person fills. A name browsers do not autofill. The wrapper is
                aria-hidden so a screen reader skips the label too. */}
            <div aria-hidden="true">
            <Input
              label="Leave this field empty"
              wrapperClassName="sr-only"
              name="wl_reference_code"
              tabIndex={-1}
              autoComplete="off"
              value={honeypot}
              onChange={(e) => setHoneypot(e.target.value)}
            />
            </div>
            {token && role ? (
              <>
                <dl className="m-0 grid grid-cols-[64px_1fr] items-baseline gap-x-3 gap-y-2 text-body-md">
                  <dt className="lw-label">Email</dt>
                  <dd className="m-0 break-all font-semibold">{email}</dd>
                  <dt className="lw-label">Name</dt>
                  <dd className="m-0 font-semibold">{normaliseWaitlistName(name)}</dd>
                  <dt className="lw-label">Role</dt>
                  <dd className="m-0 font-semibold">{WAITLIST_ROLE_LABELS[role]}</dd>
                </dl>
                <p className="m-0 text-body-sm text-on-surface-variant">
                  Your email and name are saved, so these can't change here.
                </p>
              </>
            ) : (
              <>
            <Input
              label="Email"
              className="min-h-11"
              type="email"
              autoComplete="email"
              inputMode="email"
              placeholder="you@school.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              error={errors.email}
              onBlur={() =>
                email &&
                !EMAIL_RE.test(email.trim()) &&
                setErrors((x) => ({ ...x, email: 'Enter an email like name@school.com.' }))
              }
            />
            <Input
              label="Full name"
              className="min-h-11"
              autoComplete="name"
              placeholder="Your Name"
              maxLength={WAITLIST_LIMITS.name * 2}
              value={name}
              onChange={(e) => {
                setName(e.target.value)
                if (errors.name) setErrors((x) => ({ ...x, name: undefined }))
              }}
              error={errors.name}
              onBlur={() => {
                // An empty field is only flagged on submit, so tabbing past it stays quiet.
                const message = name.trim() ? validateWaitlistName(name) : null
                if (message) setErrors((x) => ({ ...x, name: message }))
              }}
            />
            <div className="lw-roles">
              <RadioGroup
                label="I am a…"
                value={role}
                onValueChange={(v) => {
                  setRole(v as WaitlistRole)
                  setErrors((x) => ({ ...x, role: undefined }))
                }}
                error={errors.role}
              >
                {WAITLIST_ROLES.map((id) => (
                  <Radio
                    key={id}
                    value={id}
                    label={WAITLIST_ROLE_LABELS[id]}
                    description={ROLE_HINT[id]}
                  />
                ))}
              </RadioGroup>
            </div>
              </>
            )}
            {ts.required ? <div ref={tsBox} /> : null}
            {ts.state === 'error' ? (
              <p className="lw-banner err m-0" role="alert">
                <WarningCircle size={18} weight="fill" className="mt-px shrink-0" aria-hidden />
                <span>We couldn't check that you're a person. Try again.</span>
              </p>
            ) : null}
            {banner}
          </form>
        ) : null}

        {step === 1 && dup ? (
          <p className="lw-banner info m-0">
            <Check size={18} weight="bold" className="mt-px shrink-0" aria-hidden />
            <span>Nothing more to do. We only email you when there is news.</span>
          </p>
        ) : null}

        {step === 2 && role && !expired ? (
          <form
            id="lw-form"
            noValidate
            onSubmit={(e) => {
              e.preventDefault()
              void join()
            }}
            className="flex flex-col gap-6"
          >
            <Group
              legend={LEVEL_Q[role]}
              hint={role === 'centre_admin' || role === 'teacher' ? 'Pick all that apply' : undefined}
            >
              <div className="flex flex-wrap gap-2">
                {WAITLIST_LEVELS.map((l) => (
                  <Choice key={l} on={levels.includes(l)} onClick={() => setLevels(toggle(levels, l))}>
                    {WAITLIST_LEVEL_LABELS[l]}
                  </Choice>
                ))}
              </div>
            </Group>

            <Group
              legend={SUBJECT_Q[role]}
              hint={subjects.length + others.length ? `${subjects.length + others.length} picked` : undefined}
              error={errors.subjects}
            >
              <div className="flex flex-wrap gap-2" role="group" aria-label="Subjects">
                {TOP_SUBJECTS.map((x) => (
                  <Choice
                    key={x.value}
                    on={subjects.includes(x.value)}
                    onClick={() => {
                      setSubjects(toggle(subjects, x.value))
                      setErrors((e) => ({ ...e, subjects: undefined }))
                    }}
                  >
                    {x.label}
                  </Choice>
                ))}
                <button
                  type="button"
                  className={toggleVariants({ variant: 'choice', size: 'chip' })}
                  data-state={pickerOpen ? 'on' : 'off'}
                  aria-expanded={pickerOpen}
                  onClick={() => setPickerOpen(!pickerOpen)}
                >
                  Other
                  <CaretDown size={12} weight="bold" aria-hidden className={pickerOpen ? 'rotate-180' : undefined} />
                </button>
                {extraSubjects.map((v) => (
                  <Choice key={v} on aria-label={`Remove ${waitlistSubjectLabel(v)}`} onClick={() => setSubjects(subjects.filter((x) => x !== v))}>
                    {waitlistSubjectLabel(v)}
                    <X size={12} weight="bold" aria-hidden />
                  </Choice>
                ))}
                {others.map((o) => (
                  <Choice key={o} on aria-label={`Remove ${o}`} onClick={() => setOthers(others.filter((x) => x !== o))}>
                    {o}
                    <X size={12} weight="bold" aria-hidden />
                  </Choice>
                ))}
              </div>
              {pickerOpen ? (
                <SubjectPicker
                  selected={subjects}
                  others={others}
                  escapeGuard={escapeGuard}
                  onToggle={(v) => {
                    setSubjects(toggle(subjects, v))
                    setErrors((e) => ({ ...e, subjects: undefined }))
                  }}
                  onAddOther={addOther}
                  onClose={() => setPickerOpen(false)}
                />
              ) : null}
            </Group>

            <div className="lw-optional">
              <p className="lw-label m-0">Optional. Skip any of these.</p>
              {role === 'centre_admin' ? (
                <Input
                  label="Centre name"
                  error={errors.centre}
                  value={centre}
                  maxLength={WAITLIST_LIMITS.centreName}
                  onChange={(e) => setCentre(e.target.value)}
                  autoComplete="organization"
                />
              ) : null}
              <Group legend="Exam board">
                <div className="flex flex-wrap gap-2">
                  {WAITLIST_BOARDS.map((b) => (
                    <Choice key={b} on={boards.includes(b)} onClick={() => setBoards(toggle(boards, b))}>
                      {WAITLIST_BOARD_LABELS[b]}
                    </Choice>
                  ))}
                </div>
              </Group>
              {role !== 'centre_admin' ? (
                <Group legend="Next exam session">
                  <div className="flex flex-wrap gap-2">
                    {sessions.map((s) => (
                      <Choice
                        key={s.value}
                        on={session === s.value}
                        onClick={() => setSession(session === s.value ? '' : s.value)}
                      >
                        {s.label}
                      </Choice>
                    ))}
                  </div>
                </Group>
              ) : null}
              <div className="flex flex-col gap-3">
                <Input
                  label="Mobile number"
                  className="min-h-11"
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  placeholder="01x xxxx xxxx"
                  hint="Egypt numbers start 01. For another country, add + and the code."
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  error={errors.phone}
                />
                <Switch label="This number has WhatsApp" wrapperClassName="min-h-11 justify-center" className="aria-[checked=false]:border-on-surface-variant aria-[checked=false]:bg-surface-container-high" checked={wa} onCheckedChange={setWa} />
              </div>
            </div>
            {banner}
          </form>
        ) : null}

        {step === 'done' ? (
          <div className="flex flex-col gap-5">
            {role === 'student' ? (
              <span
                className="marketing-brand inline-block self-start"
                style={{ minHeight: 0, width: 102, height: 112, background: 'transparent' }}
                aria-hidden
              >
                <Binny mood="happy" className="h-28 w-auto" />
              </span>
            ) : null}
            <div className="flex flex-col gap-1">
              <p className="m-0 flex items-center gap-2 text-body-lg font-bold text-on-surface">
                <span className="flex size-6 items-center justify-center rounded-full bg-success text-on-primary">
                  <Check size={14} weight="bold" aria-hidden />
                </span>
                {firstName ? `You're on the list, ${firstName}` : "You're on the list"}
              </p>
              <p className="m-0 max-w-[44ch] text-body-md text-on-surface-variant">
                We sent a link to <span className="font-semibold text-on-surface">{email}</span>. Check
                your inbox and open it to confirm your email. We'll email you when access opens.
              </p>
            </div>
          </div>
        ) : null}
      </div>

      <div
        className="flex flex-col gap-3 border-t border-outline-variant px-5 pb-5 pt-4 sm:px-8 sm:pb-7"
        style={{ paddingBottom: 'max(20px, env(safe-area-inset-bottom))' }}
      >
        {step === 1 && !dup && !expired ? (
          <>
            <Button form="lw-form" type="submit" variant="primary" size="lg" loading={busy} className="min-h-12 w-full">
              {retry ? (
                'Try again'
              ) : (
                <>
                  Continue <ArrowRight size={18} aria-hidden />
                </>
              )}
            </Button>
            <span className="lw-step" role="img" aria-label="Step 1 of 2">
              <i data-on="true" />
              <i />1 of 2
            </span>
            {consent}
          </>
        ) : null}
        {step === 2 && !expired ? (
          <>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="secondary"
                size="lg"
                className="min-h-12"
                onClick={() => setStep(1)}
                disabled={busy}
                aria-label="Back to email and role"
              >
                <ArrowLeft size={18} aria-hidden />
              </Button>
              <Button form="lw-form" type="submit" variant="primary" size="lg" loading={busy} className="min-h-12 flex-1">
                {retry ? 'Try again' : 'Join the waitlist'}
              </Button>
            </div>
            <span className="lw-step" role="img" aria-label="Step 2 of 2">
              <i data-on="true" />
              <i data-on="true" />2 of 2
            </span>
            {consent}
          </>
        ) : null}
        {expired ? (
          <Button type="button" variant="primary" size="lg" className="min-h-12 w-full" onClick={onClose}>
            Done
          </Button>
        ) : null}
        {step === 'done' || dup ? (
          <div className="flex flex-col gap-2 sm:flex-row-reverse">
            <Button type="button" variant="primary" size="lg" className="min-h-12 flex-1" onClick={onClose}>
              Done
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="lg"
              className="min-h-12 flex-1"
              onClick={share}
              icon={
                copied ? (
                  <Check size={18} weight="bold" />
                ) : mobile ? (
                  <ShareNetwork size={18} />
                ) : (
                  <LinkIcon size={18} />
                )
              }
            >
              <span aria-live="polite">
                {copied ? 'Link copied' : mobile ? 'Share Lemely' : 'Copy link to share'}
              </span>
            </Button>
          </div>
        ) : null}
      </div>
      {onClose ? (
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute end-3 top-3 flex size-11 items-center justify-center rounded-full text-on-surface-variant transition-colors hover:bg-surface-container-low hover:text-on-surface"
        >
          <X size={20} aria-hidden />
        </button>
      ) : null}
    </div>
  )
}
