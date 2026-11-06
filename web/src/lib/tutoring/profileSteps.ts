/*
 * T-15, T-16, T-21 · pure logic of the tutor's own profile screens (SPEC §d,
 * §a.2, §a.3, row 17).
 *
 * What lives here, so the node-only test runner can check it:
 *   - the steps of the onboarding editor and which of them a profile shows;
 *   - the form values, what changes a save sends (`buildUpdateBody` sends only
 *     what changed), and whether a change sends a listed profile back to review;
 *   - validation that mirrors the column limits and the name allowlist (the
 *     server stays authoritative, and a refusal is mapped back to its field);
 *   - the listing banner of T-15 and the moderation words of T-21;
 *   - the fixed copy of these screens, which the test parses out of the SPEC.
 *
 * **Review.** SPEC §a.3: editing a moderated field of a `listed` profile sends
 * it back to `pending_review`. The moderated fields are exactly the six in
 * `MODERATED_FIELDS` (the repository's list, compared by the test). Subjects,
 * ways of meeting, area and availability are not, and neither are the two
 * toggles `paused` and `indexable`; those are saved on their own and never
 * carry a moderated edit (`toggleBody`). Only a real change counts: the server
 * trims text before it compares, so a whitespace difference is no change here
 * either.
 *
 * Copy is plain English in the SPEC's own words and never uses the two words
 * the tutoring copy rule bans.
 */

import { ApiError } from "@/lib/api"
import type {
  AvailabilityRule,
  Evidence,
  TutorOwnProfile,
  TutorProfileCreate,
  TutorProfileUpdate,
  TutorReviewItem,
  TutoringMode,
} from "@/lib/tutoringTypes"

export type ListingState = TutorOwnProfile["listingState"]

// ── Fixed copy (SPEC §d) ────────────────────────────────────────────────────

/** Row 17: always shown above the search toggle. */
export const SEARCH_NOTICE =
  "Your public card is on the open web, and search engines such as Google can list it. You can turn this off here at any time. After you turn it off, search engines can take a few weeks to drop your card."

/** PP-4: beside the live preview of the open-web card. */
export const IDENTIFY_LINE =
  "Your first name, initial, city and subjects can identify you to people who know you."

/** Shown when a save would send a listed profile back to review. */
export const RE_REVIEW_LINE = "Saving sends your profile back for review and hides it until approved."

/** T-15, under review. */
export const UNDER_REVIEW_LINE = "Lemely is reviewing your profile. You'll get a notification."

/** T-16, step 3. */
export const EVIDENCE_NO_ID_LINE = "Don't upload identity documents."
export const EVIDENCE_BADGE_LINE =
  "Changing your documents removes the 'Documents seen' badge until Lemely looks again."

/** S-34, as the preview shows it. */
export const DOCUMENTS_SEEN_LABEL = "Documents seen by Lemely"
export const DOCUMENTS_SEEN_DISCLOSURE =
  "A Lemely admin looked at documents this tutor uploaded. This is not a background check."

/** T-21. */
export const REPLY_CHECKED_LINE = "Replies are checked by Lemely before students see them."

/** The caption under both outcome figures (S-34), with this tutor's two windows. */
export function OUTCOMES_CAPTION(duringWindowDays: number, beforeLookbackDays: number): string {
  return (
    `Grades from papers uploaded in the ${duringWindowDays} days from each student's first session with this tutor, ` +
    `compared with their latest grade in the ${beforeLookbackDays} days before it. ` +
    "Grades worked out from estimated grade boundaries are left out. " +
    "These grades come from Lemely's automatic marking, which is not as accurate as an examiner. " +
    "Students choose their tutors, so this doesn't show what the tutor caused."
  )
}

// ── Limits (SPEC §a.2 column sizes) ─────────────────────────────────────────

export const FIELD_LIMITS = {
  firstName: 40,
  headline: 160,
  bio: 2000,
  qualificationNote: 1000,
  otherModeNote: 200,
} as const

export const MAX_SUBJECTS = 10
export const EVIDENCE_MAX_FILES = 5
export const EVIDENCE_MAX_BYTES = 10_485_760
export const REPLY_MAX = 1000
/** What the evidence picker offers; the server decides from the file's bytes (SC-22). */
export const EVIDENCE_ACCEPT = "application/pdf,image/jpeg,image/png"

// ── Steps ───────────────────────────────────────────────────────────────────

export type StepId = "card" | "about" | "evidence" | "availability" | "submit"

export interface ProfileStep {
  id: StepId
  /** 1-based, as the SPEC numbers them. */
  number: number
  label: string
}

const STEP_LABELS: Record<StepId, string> = {
  card: "Public card",
  about: "About",
  evidence: "Evidence",
  availability: "Availability",
  submit: "Submit",
}

export type ProfileMode = "onboarding" | "edit" | "readonly"

/**
 * No profile, a draft or a rejected profile is still being set up and can be
 * sent for review; a listed or waiting profile is edited in place; a suspended
 * or closed profile is read-only (T3 answers 409 for both).
 */
export function profileMode(state: ListingState | null): ProfileMode {
  if (state === null || state === "draft" || state === "rejected") return "onboarding"
  if (state === "suspended" || state === "closed") return "readonly"
  return "edit"
}

export function stepsFor(state: ListingState | null): ProfileStep[] {
  // Submit stays while a profile waits for review, where it reads "Under review"; a listed
  // profile has nothing left to submit.
  const ids: StepId[] =
    state === "listed" || profileMode(state) === "readonly"
      ? ["card", "about", "evidence", "availability"]
      : ["card", "about", "evidence", "availability", "submit"]
  return ids.map((id, index) => ({ id, number: index + 1, label: STEP_LABELS[id] }))
}

// ── Form values ─────────────────────────────────────────────────────────────

export interface ProfileFormValues {
  publicFirstName: string
  publicLastInitial: string
  headline: string
  subjectCodes: string[]
  offersVirtual: boolean
  offersInPerson: boolean
  offersOther: boolean
  areaCode: string
  bio: string
  qualificationNote: string
  otherModeNote: string
}

export const EMPTY_PROFILE_VALUES: ProfileFormValues = {
  publicFirstName: "",
  publicLastInitial: "",
  headline: "",
  subjectCodes: [],
  offersVirtual: false,
  offersInPerson: false,
  offersOther: false,
  areaCode: "",
  bio: "",
  qualificationNote: "",
  otherModeNote: "",
}

/** The text fields whose edit sends a listed profile back to review (SPEC §a.3). */
export const MODERATED_FIELDS: readonly (keyof ProfileFormValues)[] = [
  "publicFirstName",
  "publicLastInitial",
  "headline",
  "bio",
  "qualificationNote",
  "otherModeNote",
]

type FormOrToggle = keyof ProfileFormValues | "paused" | "indexable"

/** Whether changing this field sends a listed profile back to review. */
export function changeNeedsReview(field: FormOrToggle): boolean {
  return (MODERATED_FIELDS as readonly string[]).includes(field)
}

export function valuesFromProfile(
  profile: Pick<
    TutorOwnProfile,
    | "publicName"
    | "headline"
    | "subjects"
    | "modes"
    | "area"
    | "bio"
    | "qualificationNote"
    | "otherModeNote"
  >,
): ProfileFormValues {
  const { first, initial } = splitPublicName(profile)
  return {
    publicFirstName: first,
    publicLastInitial: initial,
    headline: profile.headline,
    subjectCodes: profile.subjects.map((s) => s.code),
    offersVirtual: profile.modes.includes("virtual"),
    offersInPerson: profile.modes.includes("in_person"),
    offersOther: profile.modes.includes("other"),
    areaCode: profile.area.code,
    bio: profile.bio,
    qualificationNote: profile.qualificationNote ?? "",
    otherModeNote: profile.otherModeNote ?? "",
  }
}

/**
 * The profile DTO carries the joined public name ("Amira K."), not the two
 * parts, so the editor splits it back: a trailing single letter and a full
 * stop is the initial. The server accepts only that shape (`display_name`).
 */
function splitPublicName(profile: { publicName: string }): { first: string; initial: string } {
  const match = /^(.*\S)\s+(\p{L})\.$/u.exec(profile.publicName.trim())
  if (match) return { first: match[1], initial: match[2] }
  return { first: profile.publicName.trim(), initial: "" }
}

function clean(value: string): string {
  return value.trim()
}

/**
 * The initial as the card shows it: upper case when that stays one character.
 * Mirrors `public_name` in `lemely/core/tutor_directory.py`: "ß" upper-cases to
 * "SS", which the server refuses as two letters, so it is kept as typed.
 */
export function displayInitial(raw: string): string {
  const initial = raw.trim()
  const upper = initial.toUpperCase()
  return [...upper].length === 1 ? upper : initial
}

/** The server shows the initial in upper case, so it is compared and sent that way. */
function initialOf(values: ProfileFormValues): string {
  return displayInitial(values.publicLastInitial)
}

/** The note only exists for a tutor who offers another way to meet. */
function effectiveOtherNote(values: ProfileFormValues): string {
  return values.offersOther ? clean(values.otherModeNote) : ""
}

function sameSet(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false
  const left = [...a].sort()
  const right = [...b].sort()
  return left.every((code, i) => code === right[i])
}

function moderatedValue(values: ProfileFormValues, field: keyof ProfileFormValues): string {
  if (field === "otherModeNote") return effectiveOtherNote(values)
  if (field === "publicLastInitial") return initialOf(values)
  const value = values[field]
  return typeof value === "string" ? clean(value) : ""
}

/** The moderated fields whose trimmed value differs, in `MODERATED_FIELDS` order. */
export function moderatedFieldsChanged(
  saved: ProfileFormValues,
  edited: ProfileFormValues,
): (keyof ProfileFormValues)[] {
  return MODERATED_FIELDS.filter((field) => moderatedValue(saved, field) !== moderatedValue(edited, field))
}

/** The line to show beside Save: only a listed profile is sent back, and only for a real change. */
export function reReviewNotice(
  state: ListingState | null,
  saved: ProfileFormValues,
  edited: ProfileFormValues,
): string | null {
  if (state !== "listed") return null
  return moderatedFieldsChanged(saved, edited).length > 0 ? RE_REVIEW_LINE : null
}

export function buildCreateBody(values: ProfileFormValues): TutorProfileCreate {
  return {
    publicFirstName: clean(values.publicFirstName),
    publicLastInitial: initialOf(values) || null,
    headline: clean(values.headline),
    bio: clean(values.bio),
    qualificationNote: clean(values.qualificationNote) || null,
    subjectCodes: values.subjectCodes,
    offersVirtual: values.offersVirtual,
    offersInPerson: values.offersInPerson,
    offersOther: values.offersOther,
    otherModeNote: effectiveOtherNote(values) || null,
    areaCode: values.areaCode,
  }
}

/** PATCH body with only the fields that changed. `paused` and `indexable` are never in it. */
export function buildUpdateBody(saved: ProfileFormValues, edited: ProfileFormValues): TutorProfileUpdate {
  const body: TutorProfileUpdate = {}
  if (clean(saved.publicFirstName) !== clean(edited.publicFirstName)) {
    body.publicFirstName = clean(edited.publicFirstName)
  }
  if (initialOf(saved) !== initialOf(edited)) {
    body.publicLastInitial = initialOf(edited) || null
  }
  if (clean(saved.headline) !== clean(edited.headline)) body.headline = clean(edited.headline)
  if (clean(saved.bio) !== clean(edited.bio)) body.bio = clean(edited.bio)
  if (clean(saved.qualificationNote) !== clean(edited.qualificationNote)) {
    body.qualificationNote = clean(edited.qualificationNote) || null
  }
  if (!sameSet(saved.subjectCodes, edited.subjectCodes)) body.subjectCodes = edited.subjectCodes
  if (saved.offersVirtual !== edited.offersVirtual) body.offersVirtual = edited.offersVirtual
  if (saved.offersInPerson !== edited.offersInPerson) body.offersInPerson = edited.offersInPerson
  if (saved.offersOther !== edited.offersOther) body.offersOther = edited.offersOther
  if (effectiveOtherNote(saved) !== effectiveOtherNote(edited)) {
    body.otherModeNote = effectiveOtherNote(edited) || null
  }
  if (saved.areaCode !== edited.areaCode) body.areaCode = edited.areaCode
  return body
}

/** The two toggles are saved alone, immediately, and never send a profile back to review. */
export function toggleBody(field: "paused" | "indexable", value: boolean): TutorProfileUpdate {
  return field === "paused" ? { paused: value } : { indexable: value }
}

// ── Validation ──────────────────────────────────────────────────────────────

export type ProfileField = keyof ProfileFormValues | "modes"
export type FieldErrors = Partial<Record<ProfileField, string>>

/** Letters (Arabic included) with up to two marks each, single separators, ending on a letter or mark. */
const FIRST_NAME = /^(?:\p{L}\p{M}{0,2})+(?:[ '’-](?:\p{L}\p{M}{0,2})+)*$/u
const INITIAL = /^\p{L}$/u

function length(value: string): number {
  return [...value].length
}

/** Length in code points, the unit `validateReply` and the server's limit use. */
export function replyLength(value: string): number {
  return length(value)
}

function nameErrors(values: ProfileFormValues, errors: FieldErrors): void {
  const first = clean(values.publicFirstName)
  if (first === "") errors.publicFirstName = "Enter your first name."
  else if (length(first) > FIELD_LIMITS.firstName) {
    errors.publicFirstName = `Use ${FIELD_LIMITS.firstName} characters or fewer.`
  } else if (!FIRST_NAME.test(first)) {
    errors.publicFirstName = "Use letters only, with a single space, hyphen or apostrophe between names."
  }
  const initial = clean(values.publicLastInitial)
  if (initial !== "" && !INITIAL.test(initial)) {
    errors.publicLastInitial = "Use a single letter, or leave this empty."
  }
}

function cardErrors(values: ProfileFormValues): FieldErrors {
  const errors: FieldErrors = {}
  nameErrors(values, errors)
  const headline = clean(values.headline)
  if (headline === "") errors.headline = "Add a short headline students will see on your card."
  else if (length(headline) > FIELD_LIMITS.headline) {
    errors.headline = `Shorten the headline to ${FIELD_LIMITS.headline} characters or fewer.`
  }
  if (values.subjectCodes.length === 0) errors.subjectCodes = "Choose at least one subject."
  else if (values.subjectCodes.length > MAX_SUBJECTS) {
    errors.subjectCodes = `Choose up to ${MAX_SUBJECTS} subjects.`
  }
  if (!values.offersVirtual && !values.offersInPerson && !values.offersOther) {
    errors.modes = "Choose at least one way to meet."
  }
  if (values.areaCode === "") errors.areaCode = "Choose your area."
  return errors
}

function aboutErrors(values: ProfileFormValues): FieldErrors {
  const errors: FieldErrors = {}
  if (length(clean(values.bio)) > FIELD_LIMITS.bio) {
    errors.bio = `Shorten your bio to ${FIELD_LIMITS.bio} characters or fewer.`
  }
  if (length(clean(values.qualificationNote)) > FIELD_LIMITS.qualificationNote) {
    errors.qualificationNote = `Shorten this to ${FIELD_LIMITS.qualificationNote} characters or fewer.`
  }
  if (length(effectiveOtherNote(values)) > FIELD_LIMITS.otherModeNote) {
    errors.otherModeNote = `Shorten this note to ${FIELD_LIMITS.otherModeNote} characters or fewer.`
  }
  return errors
}

export function validateStep(step: StepId | string, values: ProfileFormValues): FieldErrors {
  if (step === "card") return cardErrors(values)
  if (step === "about") return aboutErrors(values)
  return {}
}

export function validateProfile(values: ProfileFormValues): FieldErrors {
  return { ...cardErrors(values), ...aboutErrors(values) }
}

/** The field a server refusal is about, when the code says so. */
export function profileErrorField(code: string): ProfileField | null {
  switch (code) {
    case "invalid_public_name":
      return "publicFirstName"
    case "invalid_subjects":
      return "subjectCodes"
    case "invalid_modes":
      return "modes"
    case "invalid_area":
      return "areaCode"
    default:
      return null
  }
}

// ── Submit ──────────────────────────────────────────────────────────────────

export interface SubmitBlocker {
  step: StepId
  text: string
}

/** What the profile still lacks before T4 will take it (SPEC §a.3, draft to pending_review). */
export function submitBlockers(profile: {
  headline: string
  subjects: readonly unknown[]
  modes: readonly TutoringMode[]
  areaCode: string
  availabilityCount: number
}): SubmitBlocker[] {
  const blockers: SubmitBlocker[] = []
  if (profile.headline.trim() === "") blockers.push({ step: "card", text: "Add a headline." })
  if (profile.subjects.length === 0) blockers.push({ step: "card", text: "Choose at least one subject." })
  if (profile.modes.length === 0) blockers.push({ step: "card", text: "Choose at least one way to meet." })
  if (profile.areaCode === "") blockers.push({ step: "card", text: "Choose your area." })
  if (profile.availabilityCount === 0) {
    blockers.push({ step: "availability", text: "Add at least one weekly time so students can book." })
  }
  return blockers
}

// ── T-15 · the listing banner ───────────────────────────────────────────────

export type BannerTone = "ok" | "info" | "warn" | "neutral"

export interface ListingBanner {
  tone: BannerTone
  title: string
  body: string
}

function withNote(lead: string, note: string | null): string {
  const text = note?.trim()
  return text ? `${lead} Lemely's note: ${text}` : lead
}

export function listingBanner(
  state: ListingState | null,
  options: { paused: boolean; reviewNote: string | null },
): ListingBanner {
  switch (state) {
    case null:
      return {
        tone: "info",
        title: "Set up your tutor profile",
        body: "Add your details, your documents and the hours you teach. Lemely reviews every profile before students can find it.",
      }
    case "draft":
      return {
        tone: "info",
        title: "Your profile is a draft",
        body: "Finish the steps, then send it to Lemely for review. Students can't see it yet.",
      }
    case "pending_review":
      return { tone: "info", title: "Under review", body: UNDER_REVIEW_LINE }
    case "listed":
      return options.paused
        ? {
            tone: "neutral",
            title: "Your profile is paused",
            body: "Students can't find you or request new sessions. Sessions already booked stay as they are.",
          }
        : {
            tone: "ok",
            title: "Your profile is listed",
            body: "Students can find you and request sessions.",
          }
    case "rejected":
      return {
        tone: "warn",
        title: "Changes needed",
        body: withNote(
          "Lemely didn't list this profile. Update it, then send it again.",
          options.reviewNote,
        ),
      }
    case "suspended":
      return {
        tone: "warn",
        title: "Your profile is suspended",
        body: withNote(
          "Students can't find you or book you, and you can't edit your profile.",
          options.reviewNote,
        ),
      }
    case "closed":
      return {
        tone: "neutral",
        title: "Your profile is closed",
        body: withNote("This profile is closed and can't be opened again.", options.reviewNote),
      }
  }
}

// ── T-16 · evidence ─────────────────────────────────────────────────────────

/** Whether another file can be added: the limit is five (SPEC §a.2). */
export function canAddEvidence(files: readonly Evidence[]): boolean {
  return files.length < EVIDENCE_MAX_FILES
}

/** A reason a chosen file will not be sent, or null. The server checks the bytes. */
export function evidenceFileError(file: { size: number }, existing: readonly Evidence[]): string | null {
  if (!canAddEvidence(existing)) return "You can upload up to five files. Delete one to add another."
  if (file.size <= 0) return "That file is empty. Choose another."
  if (file.size > EVIDENCE_MAX_BYTES) return "That file is over 10 MB. Choose a smaller one."
  return null
}

/**
 * Why an evidence upload failed. `fileSize` is the size of the file that was sent,
 * when the caller knows it. 413, 415 and 503 are the statuses of T6 that carry
 * no code `tutoringErrorOf` knows, so they are read from the status; the typed
 * refusals (`evidence_limit`, a suspended profile) are the caller's to word.
 */
export function evidenceUploadStatusMessage(error: unknown, fileSize?: number): string | null {
  if (!(error instanceof ApiError)) return null
  if (error.status === 413) {
    // The router also sends 413 when the check worker runs out of memory, so a
    // file under the limit was refused for its complexity, not its size.
    return fileSize !== undefined && fileSize <= EVIDENCE_MAX_BYTES
      ? "That file is too large or complex to check. Try a smaller or simpler file."
      : "That file is over 10 MB. Choose a smaller one."
  }
  if (error.status === 415) return "Lemely can read PDF, JPEG and PNG files. Choose one of those."
  if (error.status === 503) return "We couldn't check or store that file just now. Try again in a minute."
  return null
}

// ── T-21 · reviews and replies ──────────────────────────────────────────────

export interface ModerationView {
  tone: BannerTone
  label: string
  detail: string
}

/** The moderation state of the tutor's own reply, in words. */
export function replyStateView(state: "pending" | "approved" | "rejected"): ModerationView {
  switch (state) {
    case "pending":
      return {
        tone: "info",
        label: "Waiting for Lemely",
        detail: "Students will see your reply once Lemely has checked it.",
      }
    case "approved":
      return { tone: "ok", label: "Shown to students", detail: "Students can read your reply." }
    case "rejected":
      return {
        tone: "warn",
        label: "Not shown",
        detail: "Lemely didn't approve this reply, so students can't see it. You can't send another.",
      }
  }
}

/** A line about the student's words when they are not shown to the tutor, or null. */
export function reviewTextNote(state: TutorReviewItem["textState"]): string | null {
  switch (state) {
    case "pending":
      return "The student's words are being checked by Lemely. Only the stars show for now."
    case "rejected":
      return "The student's words weren't approved, so only the stars show."
    default:
      return null
  }
}

/** A reply the tutor may send: not blank, within the column. Null when fine. */
export function validateReply(body: string): string | null {
  const text = body.trim()
  if (text === "") return "Write a reply first."
  if (length(text) > REPLY_MAX) return `Shorten your reply to ${REPLY_MAX} characters or fewer.`
  return null
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const

/** "2026-07" as "Jul 2026"; null stays null (a profile never listed has no date). */
export function formatListedSince(value: string | null): string | null {
  if (value === null) return null
  const match = /^(\d{4})-(\d{2})$/.exec(value)
  if (!match) return null
  const month = MONTHS[Number(match[2]) - 1]
  return month ? `${month} ${match[1]}` : null
}

/** The number of weekly rules, for the Availability step's summary. */
export function availabilitySummary(rules: readonly AvailabilityRule[]): string {
  if (rules.length === 0) return "No times yet."
  return `${rules.length} ${rules.length === 1 ? "weekly time" : "weekly times"} set.`
}
