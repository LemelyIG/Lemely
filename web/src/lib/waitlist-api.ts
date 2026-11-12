/**
 * Landing-page waitlist client: the public two-step flow and the platform-admin queue.
 *
 * The vocabularies below (roles, levels, boards, subjects) are the server's wire values
 * (`lemely/core/waitlist.py`); `tests/test_waitlist_client_vocab.py` fails if they drift.
 *
 * The public calls are deliberately not `request` from `@/lib/api`: the visitor is signed
 * out, and that helper attaches a bearer token, refreshes it on 401 and can end the session.
 * They are plain fetches that throw `WaitlistError` on any non-2xx. The admin calls use
 * `request`, so they carry the platform admin's token.
 */

import { fetchBlobUrl, request } from '@/lib/api'

// ---------------------------------------------------------------------------
// Vocabularies
// ---------------------------------------------------------------------------

export const WAITLIST_ROLES = ['student', 'teacher', 'parent', 'centre_admin'] as const
export type WaitlistRole = (typeof WAITLIST_ROLES)[number]

export const WAITLIST_ROLE_LABELS: Record<WaitlistRole, string> = {
  student: 'Student',
  teacher: 'Teacher',
  parent: 'Parent',
  centre_admin: 'Centre administrator',
}

export const WAITLIST_LEVELS = ['o_level', 'as_level', 'a_level'] as const
export type WaitlistLevel = (typeof WAITLIST_LEVELS)[number]

export const WAITLIST_LEVEL_LABELS: Record<WaitlistLevel, string> = {
  o_level: 'O-Level',
  as_level: 'AS',
  a_level: 'A-Level',
}

export const WAITLIST_BOARDS = ['caie', 'edexcel', 'oxford_aqa', 'other'] as const
export type WaitlistBoard = (typeof WAITLIST_BOARDS)[number]

export const WAITLIST_BOARD_LABELS: Record<WaitlistBoard, string> = {
  caie: 'CAIE',
  edexcel: 'Edexcel',
  oxford_aqa: 'Oxford AQA',
  other: 'Other',
}

export const WAITLIST_STATUSES = ['new', 'contacted', 'invited', 'declined'] as const
export type WaitlistStatus = (typeof WAITLIST_STATUSES)[number]

/** The status chips: the four statuses plus `partial` (email and role only). */
export type WaitlistStatusFilter = WaitlistStatus | 'partial'

/** Common Cambridge IGCSE / O-Level / AS & A-Level subjects, one per subject name, A-Z. */
export const ALL_SUBJECTS = [
  { value: 'accounting', label: 'Accounting' },
  { value: 'additional_mathematics', label: 'Additional Mathematics' },
  { value: 'agriculture', label: 'Agriculture' },
  { value: 'arabic', label: 'Arabic' },
  { value: 'art_and_design', label: 'Art & Design' },
  { value: 'biology', label: 'Biology' },
  { value: 'business', label: 'Business' },
  { value: 'chemistry', label: 'Chemistry' },
  { value: 'chinese', label: 'Chinese' },
  { value: 'classical_studies', label: 'Classical Studies' },
  { value: 'computer_science', label: 'Computer Science' },
  { value: 'design_and_technology', label: 'Design & Technology' },
  { value: 'drama', label: 'Drama' },
  { value: 'economics', label: 'Economics' },
  { value: 'english', label: 'English' },
  { value: 'english_literature', label: 'English Literature' },
  { value: 'environmental_management', label: 'Environmental Management' },
  { value: 'food_and_nutrition', label: 'Food & Nutrition' },
  { value: 'french', label: 'French' },
  { value: 'further_mathematics', label: 'Further Mathematics' },
  { value: 'geography', label: 'Geography' },
  { value: 'german', label: 'German' },
  { value: 'global_perspectives', label: 'Global Perspectives' },
  { value: 'hindi', label: 'Hindi' },
  { value: 'history', label: 'History' },
  { value: 'ict', label: 'ICT' },
  { value: 'islamic_studies', label: 'Islamic Studies' },
  { value: 'italian', label: 'Italian' },
  { value: 'japanese', label: 'Japanese' },
  { value: 'latin', label: 'Latin' },
  { value: 'law', label: 'Law' },
  { value: 'marine_science', label: 'Marine Science' },
  { value: 'mathematics', label: 'Mathematics' },
  { value: 'media_studies', label: 'Media Studies' },
  { value: 'music', label: 'Music' },
  { value: 'physical_education', label: 'Physical Education' },
  { value: 'physics', label: 'Physics' },
  { value: 'portuguese', label: 'Portuguese' },
  { value: 'psychology', label: 'Psychology' },
  { value: 'religious_studies', label: 'Religious Studies' },
  { value: 'russian', label: 'Russian' },
  { value: 'sociology', label: 'Sociology' },
  { value: 'spanish', label: 'Spanish' },
  { value: 'statistics', label: 'Statistics' },
  { value: 'thinking_skills', label: 'Thinking Skills' },
  { value: 'travel_and_tourism', label: 'Travel & Tourism' },
  { value: 'urdu', label: 'Urdu' },
] as const
export type WaitlistSubject = (typeof ALL_SUBJECTS)[number]['value']

/** Shown first in the form, in this order; each is also in `ALL_SUBJECTS`. */
export const TOP_SUBJECT_VALUES = [
  'mathematics',
  'physics',
  'chemistry',
  'biology',
  'english',
  'additional_mathematics',
  'computer_science',
  'business',
] as const satisfies readonly WaitlistSubject[]

export const TOP_SUBJECTS: { value: WaitlistSubject; label: string }[] = TOP_SUBJECT_VALUES.map(
  (value) => ({ value, label: ALL_SUBJECTS.find((s) => s.value === value)?.label ?? value }),
)

/** Alias kept for the first cut of this module. */
export const WAITLIST_SUBJECTS = ALL_SUBJECTS

export function waitlistSubjectLabel(value: string): string {
  return ALL_SUBJECTS.find((s) => s.value === value)?.label ?? value
}

/** `otherSubjects`: subjects not in `ALL_SUBJECTS`, free text, trimmed server-side. */
export const MAX_OTHER_SUBJECTS = 5
export const MAX_OTHER_SUBJECT_LENGTH = 60

/** Length caps the server enforces. */
export const WAITLIST_LIMITS = { name: 100, centreName: 120, adminNote: 2000 } as const

/**
 * The next four sittings, soonest first, mirroring the server's window
 * (`exam_session_options`): a sitting is offered while its first day (1 May for May/June,
 * 1 October for Oct/Nov) is still ahead, so in November 2026 the first option is May/June 2027.
 * The value is what `PATCH /api/waitlist` validates (`2027-mj`, `2027-on`).
 */
export function examSessionOptions(now: Date = new Date()): { value: string; label: string }[] {
  const starts = [
    { code: 'mj', month: 4, label: 'May/June' },
    { code: 'on', month: 9, label: 'Oct/Nov' },
  ] as const
  // UTC on both sides: the server validates against its UTC date (and accepts a day either way).
  const todayUtc = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
  const options: { value: string; label: string }[] = []
  for (let year = now.getUTCFullYear(); options.length < 4; year += 1) {
    for (const { code, month, label } of starts) {
      if (Date.UTC(year, month, 1) > todayUtc) {
        options.push({ value: `${year}-${code}`, label: `${label} ${year}` })
      }
    }
  }
  return options.slice(0, 4)
}

// ---------------------------------------------------------------------------
// Consent (server-owned wording)
// ---------------------------------------------------------------------------

/**
 * The consent wording is versioned and owned by the server (`lemely/core/waitlist.py`
 * `CONSENT_VERSIONS`): the client names a version, and the server stores that version's canonical
 * text. Render `WAITLIST_CONSENT_TEXT` under the submit button and send `WAITLIST_CONSENT_VERSION`.
 * `getWaitlistConfig()` returns the server's current pair; use it when you can, and these
 * constants are the same pair for a first paint. `tests/test_waitlist_client_vocab.py` fails if
 * they drift from the server.
 */
export const WAITLIST_CONSENT_VERSION = '2026-11-v1'
export const WAITLIST_CONSENT_TEXT = 'Applying opts you in to Lemely emails.'

// ---------------------------------------------------------------------------
// Phone (same rules as the server; `tests/fixtures/waitlist_phone_cases.json` pins both)
// ---------------------------------------------------------------------------

export const WAITLIST_PHONE_MESSAGE =
  'Enter a mobile number: Egypt numbers start 01, or add a + and the country code.'

const EGYPT_MOBILE = /^\+201[0125]\d{8}$/
const E164 = /^\+[1-9]\d{7,14}$/

/**
 * The E.164 form of `raw`, or `null` when it is not a plausible number. No `+`/`00` prefix means
 * Egypt (+20, leading national 0 dropped); Egyptian numbers must be mobiles (01[0125]...).
 */
export function normaliseWaitlistPhone(raw: string): string | null {
  const cleaned = raw.replace(/[\s().-]/g, '')
  if (!cleaned || !/^\+?\d+$/.test(cleaned)) return null
  let number: string
  if (cleaned.startsWith('+')) number = cleaned
  else if (cleaned.startsWith('00')) number = `+${cleaned.slice(2)}`
  else if (cleaned.startsWith('0')) number = `+20${cleaned.slice(1)}`
  else number = `+20${cleaned}`
  if (number.startsWith('+20')) return EGYPT_MOBILE.test(number) ? number : null
  return E164.test(number) ? number : null
}

/** The name as the server stores it: trimmed, inner whitespace collapsed. */
export function normaliseWaitlistName(raw: string): string {
  return raw.trim().replace(/\s+/g, ' ')
}

export const WAITLIST_NAME_REQUIRED = 'Enter your full name.'
export const WAITLIST_NAME_TOO_LONG = `Use ${WAITLIST_LIMITS.name} characters or fewer.`

/** An error message for the name field, or `null` when it is 1 to 100 characters after trimming. */
export function validateWaitlistName(raw: string): string | null {
  const name = normaliseWaitlistName(raw)
  if (name === '') return WAITLIST_NAME_REQUIRED
  return [...name].length > WAITLIST_LIMITS.name ? WAITLIST_NAME_TOO_LONG : null
}

/** The first word of a name, for a greeting; `''` when there is none. */
export function waitlistFirstName(raw: string): string {
  return normaliseWaitlistName(raw).split(' ')[0] ?? ''
}

/** An error message for the phone field, or `null` when blank (it is optional) or valid. */
export function validateWaitlistPhone(raw: string): string | null {
  if (raw.trim() === '') return null
  return normaliseWaitlistPhone(raw) === null ? WAITLIST_PHONE_MESSAGE : null
}

// ---------------------------------------------------------------------------
// Public flow
// ---------------------------------------------------------------------------

export class WaitlistError extends Error {
  status: number
  /** Seconds to wait before retrying, from `Retry-After` on a 429. */
  retryAfter?: number
  /** On a 422: the server's message per camelCase field name (`phone`, `subjects`, ...). */
  fieldErrors: Record<string, string>
  /** A machine-readable string detail, e.g. `turnstile_failed` on a 403. */
  code?: string

  constructor(
    status: number,
    retryAfter?: number,
    fieldErrors: Record<string, string> = {},
    code?: string,
  ) {
    super(`Waitlist request failed with status ${status}`)
    this.name = 'WaitlistError'
    this.status = status
    this.retryAfter = retryAfter
    this.fieldErrors = fieldErrors
    this.code = code
  }
}

/**
 * Turn a FastAPI 422 body (`{detail: [{loc: ['body', 'phone'], msg: 'Value error, ...'}]}`) into
 * `{phone: '...'}`: the first message per top-level field, `Value error, ` stripped.
 */
export function parseFieldErrors(body: unknown): Record<string, string> {
  const out: Record<string, string> = {}
  const detail = (body as { detail?: unknown } | null)?.detail
  if (!Array.isArray(detail)) return out
  for (const item of detail as { loc?: unknown; msg?: unknown }[]) {
    const loc = Array.isArray(item.loc) ? item.loc : []
    const field = loc[0] === 'body' ? loc[1] : loc[0]
    if (typeof field !== 'string' || typeof item.msg !== 'string') continue
    if (!(field in out)) out[field] = item.msg.replace(/^Value error,\s*/, '')
  }
  return out
}

/** The per-field messages of a failed call (empty unless it was a 422). */
export function waitlistFieldErrors(error: unknown): Record<string, string> {
  return error instanceof WaitlistError ? error.fieldErrors : {}
}

export interface WaitlistUtm {
  utmSource?: string | null
  utmMedium?: string | null
  utmCampaign?: string | null
  utmContent?: string | null
  utmTerm?: string | null
}

export interface WaitlistStep1 extends WaitlistUtm {
  email: string
  /** Full name, required: 1 to 100 characters after trimming (`validateWaitlistName`). */
  name: string
  role: WaitlistRole
  /** `WAITLIST_CONSENT_VERSION`: the server stores that version's canonical wording. */
  consentVersion: string
  /** Cloudflare Turnstile token; required when the server enforces it (`getWaitlistConfig`). */
  turnstileToken?: string
  /** Honeypot: leave unset. A visually hidden field a person never fills. */
  website?: string
}

/** `already_listed` carries no token: skip step 2. */
export type WaitlistStep1Result =
  | { status: 'created'; token: string }
  | { status: 'already_listed' }

export interface WaitlistStep2 {
  token: string
  levels?: WaitlistLevel[]
  /** Values from `ALL_SUBJECTS`. May be empty when `otherSubjects` names at least one. */
  subjects: WaitlistSubject[]
  /** Free-text subjects not in the list: at most 5, each at most 60 characters. */
  otherSubjects?: string[]
  examBoards?: WaitlistBoard[]
  /** A value from `examSessionOptions()`; ignored for centre administrators. */
  examSession?: string | null
  /** National (Egypt, +20 default) or international; validated server-side. */
  phone?: string | null
  phoneHasWhatsapp?: boolean
  /** Kept for centre administrators only. */
  centreName?: string | null
  website?: string
}

/** A string `detail` (`turnstile_failed`) or the `code` inside an object `detail` (`{code: 'expired_token'}`). */
function detailCode(detail: unknown): string | undefined {
  if (typeof detail === 'string') return detail
  const code = (detail as { code?: unknown } | null)?.code
  return typeof code === 'string' ? code : undefined
}

async function publicCall<T>(method: 'GET' | 'POST' | 'PATCH', path: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new WaitlistError(0)
  }
  if (!res.ok) {
    const retryAfter = Number(res.headers.get('Retry-After'))
    let parsed: unknown = null
    try {
      parsed = await res.json()
    } catch {
      // Not JSON (a proxy error page): the status alone is the answer.
    }
    const detail = (parsed as { detail?: unknown } | null)?.detail
    throw new WaitlistError(
      res.status,
      Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : undefined,
      res.status === 422 ? parseFieldErrors(parsed) : {},
      detailCode(detail),
    )
  }
  return (await res.json()) as T
}

export interface WaitlistConfig {
  /** Present only when the server enforces Turnstile; render the widget with it. */
  turnstileSiteKey: string | null
  consentVersion: string
  consentText: string
}

/** The server's public settings for the form. */
export function getWaitlistConfig(): Promise<WaitlistConfig> {
  return publicCall<WaitlistConfig>('GET', '/api/waitlist/config')
}

/** Step 1: creates the applicant. Throws `WaitlistError` (status 0 = no response, 429 = rate limited). */
export function joinWaitlist(input: WaitlistStep1): Promise<WaitlistStep1Result> {
  return publicCall<WaitlistStep1Result>('POST', '/api/waitlist', input)
}

/** Step 2: completes the applicant. A 400 means the token expired or was already used. */
export async function completeWaitlist(input: WaitlistStep2): Promise<void> {
  await publicCall<{ status: 'completed' }>('PATCH', '/api/waitlist', input)
}

/** `POST /api/waitlist/confirm`: the link in the confirmation email carries the token. */
export type WaitlistConfirmResult = { status: 'confirmed' | 'already_confirmed' }

/** Confirms the applicant's email. A 400 carries `invalid_token` or `expired_token`. */
export function confirmWaitlist(token: string): Promise<WaitlistConfirmResult> {
  return publicCall<WaitlistConfirmResult>('POST', '/api/waitlist/confirm', { token })
}

/** What went wrong confirming, in the terms the page speaks. A missing token is `invalid` before any call. */
export type WaitlistConfirmFailure = 'invalid' | 'expired' | 'rate' | 'network' | 'other'

export function classifyConfirmFailure(error: unknown): WaitlistConfirmFailure {
  if (!(error instanceof WaitlistError)) return 'network'
  if (error.status === 0) return 'network'
  if (error.status === 429) return 'rate'
  if (error.status === 400 && error.code === 'expired_token') return 'expired'
  if (error.status === 400) return 'invalid'
  return 'other'
}

/** What the visitor reads after a failed call. */
export function waitlistFailureCopy(error: unknown): string {
  if (error instanceof WaitlistError) {
    if (error.status === 429) return 'Too many tries. Please wait a few minutes and try again.'
  }
  return "Couldn't save that. Try again, or email contact@lemelyig.com."
}

// ---------------------------------------------------------------------------
// Admin queue (platform admin; bearer token via `request`)
// ---------------------------------------------------------------------------

export interface WaitlistApplicant {
  id: string
  email: string
  /** `null` on rows from before the name field existed. */
  name: string | null
  role: WaitlistRole
  centreName: string | null
  levels: WaitlistLevel[]
  subjects: string[]
  otherSubjects: string[]
  examBoards: WaitlistBoard[]
  examSession: string | null
  /** E.164. Platform admins only; never in the digest. */
  phone: string | null
  phoneHasWhatsapp: boolean
  /** True once the applicant opened the confirmation link. */
  emailConfirmed: boolean
  /** When they did, or `null`. */
  emailConfirmedAt?: string | null
  consentVersion: string
  consentText: string
  consentAt: string
  status: WaitlistStatus
  adminNote: string | null
  utmSource: string | null
  utmMedium: string | null
  utmCampaign: string | null
  utmContent: string | null
  utmTerm: string | null
  completedAt: string | null
  /** `true` until step 2 completes (email and role only). */
  partial: boolean
  createdAt: string
  updatedAt: string
}

export interface WaitlistCounts {
  all: number
  new: number
  contacted: number
  invited: number
  declined: number
  /** Overlaps the statuses: a partial applicant is also `new`. */
  partial: number
}

export type WaitlistSort = 'created_at' | 'email' | 'name' | 'role' | 'status' | 'exam_session'

export interface WaitlistQuery {
  role?: WaitlistRole
  level?: WaitlistLevel
  subject?: string
  board?: WaitlistBoard
  session?: string
  status?: WaitlistStatusFilter
  /** Filter by whether the address was confirmed (none are yet). */
  emailConfirmed?: boolean
  /** Inclusive, `YYYY-MM-DD`. */
  createdFrom?: string
  createdTo?: string
  /** Email or name substring. */
  q?: string
  sort?: WaitlistSort
  order?: 'asc' | 'desc'
  page?: number
  /** 1 to 200; default 50. */
  pageSize?: number
}

export interface WaitlistPage {
  items: WaitlistApplicant[]
  total: number
  page: number
  pageSize: number
  /** Counts over the filtered set, ignoring `status` itself. */
  counts: WaitlistCounts
}

export interface WaitlistUpdate {
  status?: WaitlistStatus
  /** `null` clears the note; omit to leave it unchanged. */
  adminNote?: string | null
}

function queryString(query: WaitlistQuery, exclude: ReadonlyArray<keyof WaitlistQuery> = []): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query) as [keyof WaitlistQuery, unknown][]) {
    if (value === undefined || value === null || value === '' || exclude.includes(key)) continue
    params.set(key, String(value))
  }
  const text = params.toString()
  return text ? `?${text}` : ''
}

export function listWaitlist(query: WaitlistQuery = {}): Promise<WaitlistPage> {
  return request<WaitlistPage>(`/admin/waitlist${queryString(query)}`)
}

export function getWaitlistApplicant(id: string): Promise<WaitlistApplicant> {
  return request<WaitlistApplicant>(`/admin/waitlist/${encodeURIComponent(id)}`)
}

export function updateWaitlistApplicant(
  id: string,
  update: WaitlistUpdate,
): Promise<WaitlistApplicant> {
  return request<WaitlistApplicant>(`/admin/waitlist/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(update),
  })
}

/**
 * The filtered set as CSV, fetched with the bearer token. Resolves to an object URL: point a
 * download link at it, then `URL.revokeObjectURL` it. Paging options are ignored (every row).
 */
export function exportWaitlistCsv(query: WaitlistQuery = {}): Promise<string> {
  return fetchBlobUrl(`/admin/waitlist/export.csv${queryString(query, ['page', 'pageSize'])}`)
}
