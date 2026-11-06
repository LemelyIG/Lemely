import { ApiError } from "@/lib/api"
import { billingErrorCode } from "@/lib/billingOutcome"
import { METERED_ACTIONS } from "@/lib/billingTypes"
import type {
  AdminCreditPack,
  AdminPlanTier,
  Audience,
  EstimatorCreate,
  EstimatorInputKind,
  FreeAllowances,
  FreeAllowanceUpdate,
  MeteredAction,
  PackCreate,
  PackUpdate,
  RateCreate,
  TierCreate,
  TierUpdate,
} from "@/lib/billingTypes"

/* Pure form models for the admin billing console. Every write carries a reason (spec §8). Bodies
 * match plan 07's request models exactly (`lemely/web/schemas_admin_billing.py`). */

/** The server accepts 3 to 2000 characters after trimming; the console asks for a real sentence. */
export const REASON_MIN = 5
export const REASON_MAX = 2000

const MAX_UNITS = 1_000_000_000
const MAX_MINOR = 1_000_000_000

export function reasonError(reason: string): string | null {
  const length = reason.trim().length
  if (length < REASON_MIN) return "Give a reason of at least 5 characters. It is saved in the audit log."
  if (length > REASON_MAX) return "Keep the reason under 2,000 characters."
  return null
}

export function minorFromMajor(text: string): number | null {
  if (!/^\d+(\.\d{1,2})?$/.test(text.trim())) return null
  return Math.round(Number(text) * 100)
}

export function majorFromMinor(minor: number): string {
  return (minor / 100).toFixed(2)
}

/** A date input's `YYYY-MM-DD` as the ISO datetime the routes take (UTC midnight). */
export function isoDay(date: string): string {
  return `${date}T00:00:00Z`
}

/** Today's calendar day in UTC, as `YYYY-MM-DD` (the routes read whole UTC days). */
export function utcDay(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10)
}

/** The first day a dated version can start on: the server refuses a start in the past. */
export function tomorrowUtc(now: Date = new Date()): string {
  return utcDay(new Date(now.getTime() + 24 * 60 * 60 * 1000))
}

type FieldBase = {
  name: string
  label: string
  hint?: string
  /** Shown (and validated) only while the form's `audience` value matches. */
  audience?: Audience
}

export type FieldSpec = FieldBase &
  (
    | { kind: "text"; optional?: boolean; maxLength?: number; pattern?: RegExp; patternMessage?: string }
    | { kind: "date"; optional?: boolean; future?: boolean }
    | { kind: "number"; optional?: boolean; positive?: boolean }
    | { kind: "money"; optional?: boolean; positive?: boolean }
    | { kind: "select"; options: { value: string; label: string }[] }
    | { kind: "checkbox" }
    | { kind: "lines" }
  )

export type FormValues = Record<string, string | boolean>

const str = (v: FormValues, k: string) => String(v[k] ?? "").trim()
const num = (v: FormValues, k: string) => Number(str(v, k))
const intOrZero = (v: FormValues, k: string) => (str(v, k) === "" ? 0 : Number(str(v, k)))
const dayOrNull = (v: FormValues, k: string) => (str(v, k) === "" ? null : isoDay(str(v, k)))
const moneyOrZero = (v: FormValues, k: string) => (str(v, k) === "" ? 0 : (minorFromMajor(str(v, k)) ?? 0))
/** Seat fields belong to teacher tiers; the server refuses them on a student tier. */
const isTeacher = (v: FormValues) => str(v, "audience") === "teacher"
/** M2 convention: each feature line is a key set to `true`. */
const featureDict = (v: FormValues) =>
  Object.fromEntries(
    str(v, "features")
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean)
      .map((l) => [l, true] as const),
  )

/** The feature lines typed into the form. */
export function featureLinesOf(v: FormValues): string[] {
  return Object.keys(featureDict(v))
}

/**
 * The `features` object to send. The form edits only the lines that are `true`; every other
 * stored key (a limit like `"papers": "unlimited"`, a `false` flag) is carried back untouched,
 * because the update replaces the whole dict. A `true` line the admin removed is dropped; a line
 * typed for a key that is stored as something else turns it on.
 */
export function mergeFeatures(raw: Record<string, unknown> | undefined, lines: string[]): Record<string, unknown> {
  const merged: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(raw ?? {})) if (value !== true) merged[key] = value
  for (const line of lines) merged[line] = true
  return merged
}

/** Stored feature keys the form cannot show (not `true`), so a note can say they are kept. */
export function hiddenFeatureCount(raw: Record<string, unknown>): number {
  return Object.values(raw).filter((v) => v !== true).length
}

/** The fields a form actually shows for these values (audience-specific ones drop out). */
export function visibleFields(fields: FieldSpec[], values: FormValues): FieldSpec[] {
  return fields.filter((f) => f.audience === undefined || f.audience === str(values, "audience"))
}

const grouped = (n: number) => new Intl.NumberFormat("en-US").format(n)

/** One message per invalid field, keyed by field name. `now` is injectable for the date rule. */
export function fieldErrors(fields: FieldSpec[], values: FormValues, now: Date = new Date()): Record<string, string> {
  const errors: Record<string, string> = {}
  for (const f of visibleFields(fields, values)) {
    const raw = str(values, f.name)
    if (f.kind === "text") {
      if (raw === "") {
        if (!f.optional) errors[f.name] = `${f.label} is required.`
      } else if (f.maxLength !== undefined && raw.length > f.maxLength) {
        errors[f.name] = `${f.label} must be at most ${f.maxLength} characters.`
      } else if (f.pattern && !f.pattern.test(raw)) {
        errors[f.name] = f.patternMessage ?? `${f.label} is not valid.`
      }
    } else if (f.kind === "date") {
      if (raw === "") {
        if (!f.optional) errors[f.name] = `${f.label} is required.`
      } else if (!/^\d{4}-\d{2}-\d{2}$/.test(raw) || Number.isNaN(Date.parse(isoDay(raw)))) {
        errors[f.name] = `${f.label} must be a date.`
      } else if (f.future && raw < tomorrowUtc(now)) {
        errors[f.name] = "A new version can't start today or in the past. Pick a later day, or leave this empty to start now."
      }
    } else if (f.kind === "number") {
      if (raw === "") {
        if (!f.optional) errors[f.name] = `${f.label} is required.`
      } else if (!/^\d+$/.test(raw)) {
        errors[f.name] = f.positive ? `${f.label} must be a whole number above zero.` : `${f.label} must be a whole number, zero or more.`
      } else if (f.positive && Number(raw) === 0) {
        errors[f.name] = `${f.label} must be a whole number above zero.`
      } else if (Number(raw) > MAX_UNITS) {
        errors[f.name] = `${f.label} must be at most ${grouped(MAX_UNITS)}.`
      }
    } else if (f.kind === "money") {
      const minor = minorFromMajor(raw)
      if (raw === "") {
        if (!f.optional) errors[f.name] = `${f.label} is required.`
      } else if (raw.startsWith("-")) {
        errors[f.name] = `${f.label} must be zero or more.`
      } else if (minor === null) {
        errors[f.name] = `${f.label} must be an amount like 250 or 250.50.`
      } else if (f.positive && minor === 0) {
        errors[f.name] = `${f.label} must be more than zero.`
      } else if (minor > MAX_MINOR) {
        errors[f.name] = `${f.label} must be at most ${grouped(MAX_MINOR / 100)}.`
      }
    }
  }
  return errors
}

export function validateFields(fields: FieldSpec[], values: FormValues, now: Date = new Date()): string[] {
  return Object.values(fieldErrors(fields, values, now))
}

const ACTION_OPTIONS = METERED_ACTIONS.map((a) => ({ value: a, label: a }))

/** Editable after creation (07 `PlanTierUpdateDTO`). Seat fields only exist on teacher tiers. */
export const TIER_UPDATE_FIELDS: FieldSpec[] = [
  { name: "name", label: "Name", kind: "text", maxLength: 120 },
  { name: "priceMajor", label: "Price (EGP)", kind: "money", hint: "Per billing period. Zero makes a free tier." },
  { name: "allowanceUnits", label: "Allowance per period (units)", kind: "number" },
  { name: "includedSeats", label: "Included seats", kind: "number", optional: true, audience: "teacher" },
  { name: "seatAllowanceUnits", label: "Seat allowance per month (units)", kind: "number", optional: true, audience: "teacher" },
  { name: "extraSeatPriceMajor", label: "Extra seat price (EGP)", kind: "money", optional: true, audience: "teacher" },
  { name: "features", label: "Feature lines", kind: "lines", hint: "One per line. Each line is shown to buyers." },
  { name: "isActive", label: "On sale", kind: "checkbox" },
]

/** Creation also fixes code, audience and interval (07 `PlanTierCreateDTO`; currency is EGP). */
export const TIER_FIELDS: FieldSpec[] = [
  {
    name: "code",
    label: "Code",
    kind: "text",
    maxLength: 64,
    pattern: /^[a-z0-9_]{2,64}$/,
    patternMessage: "Code must be 2 to 64 lowercase letters, digits or underscores.",
    hint: "Fixed once created.",
  },
  { name: "audience", label: "Audience", kind: "select", options: [{ value: "student", label: "Student" }, { value: "teacher", label: "Teacher" }] },
  { name: "interval", label: "Interval", kind: "select", options: [{ value: "monthly", label: "Monthly" }, { value: "yearly", label: "Yearly" }] },
  ...TIER_UPDATE_FIELDS,
]

export function tierValues(t: AdminPlanTier | null): FormValues {
  return {
    code: t?.code ?? "",
    name: t?.name ?? "",
    audience: t?.audience ?? "student",
    interval: t?.interval === "year" ? "yearly" : "monthly",
    priceMajor: t ? majorFromMinor(t.priceMinor) : "",
    allowanceUnits: t ? String(t.allowanceUnits) : "",
    includedSeats: t?.includedSeats != null ? String(t.includedSeats) : "",
    seatAllowanceUnits: t?.seatAllowanceUnits != null ? String(t.seatAllowanceUnits) : "",
    extraSeatPriceMajor: t?.extraSeatPriceMinor != null ? majorFromMinor(t.extraSeatPriceMinor) : "",
    features: (t?.features ?? []).join("\n"),
    isActive: t?.isActive ?? true,
  }
}

export function tierUpdateBody(v: FormValues, reason: string, rawFeatures?: Record<string, unknown>): TierUpdate {
  const teacher = isTeacher(v)
  return {
    name: str(v, "name"),
    priceMinor: minorFromMajor(str(v, "priceMajor")) ?? 0,
    allowanceUnits: num(v, "allowanceUnits"),
    includedSeats: teacher ? intOrZero(v, "includedSeats") : 0,
    seatAllowanceUnits: teacher ? intOrZero(v, "seatAllowanceUnits") : 0,
    extraSeatPriceMinor: teacher ? moneyOrZero(v, "extraSeatPriceMajor") : 0,
    features: mergeFeatures(rawFeatures, featureLinesOf(v)),
    isActive: v.isActive === true,
    reason,
  }
}

export function tierBody(v: FormValues, reason: string): TierCreate {
  const { name, priceMinor, allowanceUnits, includedSeats, seatAllowanceUnits, extraSeatPriceMinor, features, isActive } = tierUpdateBody(v, reason)
  return {
    code: str(v, "code"),
    name,
    audience: isTeacher(v) ? "teacher" : "student",
    interval: str(v, "interval") === "yearly" ? "yearly" : "monthly",
    priceMinor,
    currency: "EGP",
    allowanceUnits,
    includedSeats,
    seatAllowanceUnits,
    extraSeatPriceMinor,
    features,
    isActive,
    reason,
  }
}

/** Packs are bought, so a pack with no credits or no price is refused (07 `Positive`). */
export const PACK_UPDATE_FIELDS: FieldSpec[] = [
  { name: "name", label: "Name", kind: "text", maxLength: 120 },
  { name: "units", label: "Credits", kind: "number", positive: true },
  { name: "priceMajor", label: "Price (EGP)", kind: "money", positive: true },
  { name: "isActive", label: "On sale", kind: "checkbox" },
]

export const PACK_FIELDS: FieldSpec[] = [
  {
    name: "code",
    label: "Code",
    kind: "text",
    maxLength: 64,
    pattern: /^[a-z0-9_]{2,64}$/,
    patternMessage: "Code must be 2 to 64 lowercase letters, digits or underscores.",
    hint: "Fixed once created.",
  },
  ...PACK_UPDATE_FIELDS,
]

export function packValues(p: AdminCreditPack | null): FormValues {
  return {
    code: p?.code ?? "",
    name: p?.name ?? "",
    units: p ? String(p.units) : "",
    priceMajor: p ? majorFromMinor(p.priceMinor) : "",
    isActive: p?.isActive ?? true,
  }
}

export function packUpdateBody(v: FormValues, reason: string): PackUpdate {
  return { name: str(v, "name"), units: num(v, "units"), priceMinor: minorFromMajor(str(v, "priceMajor")) ?? 0, isActive: v.isActive === true, reason }
}

export function packBody(v: FormValues, reason: string): PackCreate {
  const { name, units, priceMinor, isActive } = packUpdateBody(v, reason)
  return { code: str(v, "code"), name, units, priceMinor, currency: "EGP", isActive, reason }
}

/** A dated version starts now when the day is left empty (07 `effectiveFrom: null`). */
const EFFECTIVE_FROM: FieldSpec = {
  name: "effectiveFrom",
  label: "Effective from",
  kind: "date",
  optional: true,
  future: true,
  hint: "Leave empty to start now. A chosen day starts at 00:00 UTC.",
}

export const RATE_FIELDS: FieldSpec[] = [
  { name: "action", label: "Action", kind: "select", options: ACTION_OPTIONS },
  { name: "unitsPerUsd", label: "Units per USD", kind: "number", positive: true },
  EFFECTIVE_FROM,
]

export function rateBody(v: FormValues, reason: string): RateCreate {
  return { action: str(v, "action") as MeteredAction, unitsPerUsd: num(v, "unitsPerUsd"), effectiveFrom: dayOrNull(v, "effectiveFrom"), reason }
}

export const ESTIMATOR_FIELDS: FieldSpec[] = [
  { name: "action", label: "Action", kind: "select", options: ACTION_OPTIONS },
  {
    name: "inputKind",
    label: "Counted input",
    kind: "select",
    options: ["none", "pages", "marks", "questions"].map((k) => ({ value: k, label: k })),
  },
  { name: "baseLow", label: "Base low (units)", kind: "number" },
  { name: "baseHigh", label: "Base high (units)", kind: "number" },
  { name: "perInputLow", label: "Per input low (units)", kind: "number" },
  { name: "perInputHigh", label: "Per input high (units)", kind: "number" },
  EFFECTIVE_FROM,
]

/** The cross-field rules the server enforces (`low_above_high`, `per_input_without_input_kind`). */
export function estimatorErrors(v: FormValues): string[] {
  const errors: string[] = []
  const [baseLow, baseHigh, perLow, perHigh] = ["baseLow", "baseHigh", "perInputLow", "perInputHigh"].map((k) => num(v, k))
  if (baseLow > baseHigh) errors.push("Base low can't be above base high.")
  if (perLow > perHigh) errors.push("Per input low can't be above per input high.")
  if (str(v, "inputKind") === "none" && (perLow > 0 || perHigh > 0)) {
    errors.push("Per input units need a counted input. Choose pages, marks or questions, or set both to 0.")
  }
  return errors
}

export function estimatorBody(v: FormValues, reason: string): EstimatorCreate {
  return {
    action: str(v, "action") as MeteredAction,
    inputKind: str(v, "inputKind") as EstimatorInputKind,
    baseLow: num(v, "baseLow"),
    baseHigh: num(v, "baseHigh"),
    perInputLow: num(v, "perInputLow"),
    perInputHigh: num(v, "perInputHigh"),
    effectiveFrom: dayOrNull(v, "effectiveFrom"),
    reason,
  }
}

/** 07's free-allowance update carries units only; the teacher credits' validity is read-only. */
export const FREE_FIELDS: FieldSpec[] = [
  { name: "studentSignupUnits", label: "Student free allowance (units)", kind: "number" },
  { name: "teacherSignupUnits", label: "Teacher signup credits (units)", kind: "number" },
]

export function freeValues(f: FreeAllowances): FormValues {
  return {
    studentSignupUnits: f.studentSignupUnits === null ? "" : String(f.studentSignupUnits),
    teacherSignupUnits: f.teacherSignupUnits === null ? "" : String(f.teacherSignupUnits),
  }
}

/** The two `FreeAllowanceUpdateDTO` bodies the form produces. */
export function freeBody(v: FormValues, reason: string): FreeAllowanceUpdate[] {
  return [
    { audience: "student", units: num(v, "studentSignupUnits"), reason },
    { audience: "teacher", units: num(v, "teacherSignupUnits"), reason },
  ]
}

/**
 * Only the audiences whose value differs from what the catalogue holds now (an unset one always
 * differs), so a retry after a partial save never re-sends, and re-audits, the one that saved.
 */
export function freeChanges(v: FormValues, reason: string, current: FreeAllowances): FreeAllowanceUpdate[] {
  return freeBody(v, reason).filter((b) => b.units !== (b.audience === "student" ? current.studentSignupUnits : current.teacherSignupUnits))
}

// ── Versioned rows ──────────────────────────────────────────────────────────

export type VersionStatus = "current" | "scheduled" | "superseded"

interface Versioned {
  action: string
  version: number
  effectiveFrom: string
}

/**
 * Rates and estimators are append-only. The one in force for an action is the row with the
 * latest start that has begun (ties: the higher version); later starts are scheduled; the rest
 * are history. Newest version first inside each action.
 */
export function versionRows<T extends Versioned>(rows: T[], now: Date = new Date()): { row: T; status: VersionStatus }[] {
  const t = now.getTime()
  const current = new Map<string, T>()
  for (const r of rows) {
    if (Date.parse(r.effectiveFrom) > t) continue
    const best = current.get(r.action)
    if (!best || Date.parse(r.effectiveFrom) > Date.parse(best.effectiveFrom) || (r.effectiveFrom === best.effectiveFrom && r.version > best.version)) {
      current.set(r.action, r)
    }
  }
  return [...rows]
    .sort((a, b) => (a.action === b.action ? b.version - a.version : a.action.localeCompare(b.action)))
    .map((row) => ({
      row,
      status: Date.parse(row.effectiveFrom) > t ? "scheduled" : current.get(row.action) === row ? "current" : "superseded",
    }))
}

// ── Paymob plan state ───────────────────────────────────────────────────────

export interface PaymobState {
  /** `neutral`: not checked yet, which is a prompt to sync, not a fault. */
  tone: "free" | "ok" | "attention" | "neutral" | "muted"
  text: string
  /** A free tier has no Paymob plan to create. */
  canSync: boolean
}

/**
 * What the Paymob column says. Crimson (`attention`) is for a tier on sale whose plan is missing
 * or differs. A plan nobody checked yet (`unverified`) is a neutral prompt to sync; drift on a
 * tier nobody can buy is history; a free tier never has a plan (the server answers 422
 * `not_billable` to a sync).
 */
export function paymobState(t: AdminPlanTier): PaymobState {
  if (t.priceMinor === 0) return { tone: "free", text: "Free tier, no Paymob plan", canSync: false }
  if (t.drift === null) return { tone: "ok", text: "In sync", canSync: true }
  if (t.driftState === "unverified") return { tone: "neutral", text: `${t.drift}. Sync to confirm it matches.`, canSync: true }
  return { tone: t.isActive ? "attention" : "muted", text: t.drift, canSync: true }
}

/** An instant for an administrator: the day, the time and the zone the server reads it in. */
export function formatUtc(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const text = new Intl.DateTimeFormat("en-GB", {
    timeZone: "UTC",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(d)
  return `${text} UTC`
}

// ── Failures ────────────────────────────────────────────────────────────────

/** A refusal or a malformed request will not change on a retry; a dropped request may. */
export function adminRetry(failureCount: number, error: Error): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
  return failureCount < 2
}

export function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403
}

const FRIENDLY: Record<string, string> = {
  effective_from_in_past: "A new version can't start in the past. Pick a later day, or leave the date empty to start now.",
  low_above_high: "Each low bound must be at or below its high bound.",
  per_input_without_input_kind: "Per input units need a counted input. Choose pages, marks or questions, or set both to 0.",
  seat_fields_on_student_tier: "Student tiers carry no seats. Set the seat fields to 0.",
  not_billable: "A free tier has no Paymob plan to sync.",
}

function serverMessage(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null
  const d = err.detail as { message?: unknown } | undefined
  return d && typeof d === "object" && typeof d.message === "string" && d.message.trim() !== "" ? d.message.trim() : null
}

/**
 * A multi-request write that saved some parts and then failed. `saved` and `failed` are
 * human labels, so the message can say exactly what is and is not in the catalogue.
 */
export class PartialSaveError extends Error {
  readonly saved: string[]
  readonly failed: string
  readonly original: unknown
  constructor(saved: string[], failed: string, original: unknown) {
    super("partial save")
    this.name = "PartialSaveError"
    this.saved = saved
    this.failed = failed
    this.original = original
  }
}

/**
 * What an administrator is told when a catalogue write fails. The server's `{code, message}`
 * sentences are written for administrators ("A tier with code x exists."), so a known 404, 409
 * or 422 shows them. Every write is one transaction, but only the Paymob sync is known to roll
 * back on a Paymob failure (`rolledBackOn502`); anything else with an unclear outcome says so,
 * because a blind retry could add a second audit row.
 */
export function adminBillingFailureMessage(err: unknown, action: string, opts: { rolledBackOn502?: boolean } = {}): string {
  if (err instanceof PartialSaveError) {
    const saved = err.saved.join(" and ")
    return `${saved} ${err.saved.length > 1 ? "were" : "was"} saved, but ${err.failed} was not. ${adminBillingFailureMessage(err.original, action, opts)}`
  }
  const status = err instanceof ApiError ? err.status : -1
  if (status === 0) return "The connection dropped. This change may not have been saved. Reload the catalogue to check before trying again."
  if (status === 401) return "Your session has expired. Sign in again. Nothing was saved."
  if (status === 403) return "Only platform admins can change billing. Nothing was saved."
  if (status === 429) return "Too many attempts. Wait a minute and try again. Nothing was saved."
  if (status === 502) {
    return opts.rolledBackOn502
      ? "Paymob didn't accept this request, so nothing was changed. Try again in a minute."
      : "Paymob didn't answer cleanly, so the outcome is unknown. Reload the catalogue to check, then try again if it did not save."
  }
  if (status === 404) return serverMessage(err) ?? "That row no longer exists. Reload the catalogue."
  if (status === 409 || status === 422) {
    const code = billingErrorCode(err)
    if (code && FRIENDLY[code]) return FRIENDLY[code]
    return serverMessage(err) ?? "The server refused these values. Check each field and try again. Nothing was saved."
  }
  return `Couldn't ${action}. Reload the catalogue to check whether it saved before trying again.`
}
