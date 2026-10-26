/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 — five plain steps with the live open-web card beside the first one, the search notice stated before its switch, no step gated except by what it needs; not yet seen in a browser. */
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { CheckCircle, FilePdf, ImageSquare, WarningCircle } from "@phosphor-icons/react"
import { Button, buttonVariants } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { ConfirmModal } from "@/components/ui/confirm-modal"
import { FileDrop, formatFileSize } from "@/components/ui/file-drop"
import { Input } from "@/components/ui/input"
import { PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState, type QueryStateQuery } from "@/components/ui/query-state"
import { Select } from "@/components/ui/select"
import { SkeletonBlock, SkeletonLine } from "@/components/ui/skeleton"
import { Stepper } from "@/components/ui/stepper"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { TutorCard } from "@/components/ui/tutor-card"
import {
  useCreateTutorProfile,
  useDeleteTutorEvidence,
  useOwnTutorProfile,
  usePublicTutoringAreas,
  useSubmitTutorProfile,
  useUpdateTutorProfile,
  useUploadTutorEvidence,
} from "@/lib/hooks/useTutoringApi"
import { useProfile } from "@/lib/hooks/useMeApi"
import { useReference } from "@/lib/hooks/useReferenceApi"
import { useOnlineStatus } from "@/lib/online"
import { isTutoringError, tutoringErrorOf } from "@/lib/tutoring/apiErrors"
import {
  EMPTY_PROFILE_VALUES,
  EVIDENCE_ACCEPT,
  EVIDENCE_BADGE_LINE,
  EVIDENCE_MAX_FILES,
  EVIDENCE_NO_ID_LINE,
  FIELD_LIMITS,
  IDENTIFY_LINE,
  MAX_SUBJECTS,
  SEARCH_NOTICE,
  UNDER_REVIEW_LINE,
  availabilitySummary,
  buildCreateBody,
  buildUpdateBody,
  canAddEvidence,
  evidenceFileError,
  evidenceUploadStatusMessage,
  listingBanner,
  profileErrorField,
  profileMode,
  reReviewNotice,
  stepsFor,
  submitBlockers,
  toggleBody,
  validateProfile,
  valuesFromProfile,
  type ProfileField,
  type ProfileFormValues,
  type StepId,
} from "@/lib/tutoring/profileSteps"
import { tutorActionFailureMessage, tutorLoadFailureMessage } from "@/lib/tutoring/tutorSessionActions"
import { cn, relativeTime } from "@/lib/utils"
import type { Evidence, TutorCard as TutorCardData, TutorOwnProfile, TutoringMode } from "@/lib/tutoringTypes"

/*
 * T-16 · Tutor profile and onboarding (`/teacher/tutoring/profile`, SPEC §d,
 * §a.3, row 17).
 *
 * Five steps (C-15 Stepper): Public card, About, Evidence, Availability, Submit.
 * The current step is the `?step=` parameter, so a step has an address and
 * Back works. Everything the rules say lives in `lib/tutoring/profileSteps.ts`
 * (tested): what each step checks, what a save sends (only what changed), and
 * whether a save sends a listed profile back to review.
 *
 *   - Step 1 saves the draft (T2). The form shows a live preview of the card the
 *     open web will see, the PP-4 line about being recognisable, and the search
 *     notice (row 17) stated in full above the "Show my card in search engines"
 *     switch. That switch and "Pause my listing" take effect at once on their own
 *     (T3 with one field), so they can never carry a moderated edit and never
 *     send a profile back to review.
 *   - A listed profile is edited in place, one Save for the text steps. When a
 *     save would send it back to review the SPEC's line says so before the
 *     button is pressed, and the result says it again after.
 *   - Evidence takes up to five PDF, JPEG or PNG files; the screen does not
 *     serve them back (O17). Changing them clears the "Documents seen" badge, and
 *     the step says so.
 *   - Submit lists what is still missing, each with a way to the right step, and
 *     asks for a confirmed email address (the server is the judge).
 *   - A suspended or closed profile is read-only with the admin's note.
 *
 * States: loading (skeleton), error and offline (`QueryState`), no profile (the
 * form for step 1), draft, under review, listed, rejected with its note, suspended
 * and closed. Reference lists (subjects, areas) load and fail on their own
 * without taking the form down.
 *
 * Validation shows on blur and on every save, never before the tutor has touched
 * a field; the first problem takes focus. A refusal from the server lands on the
 * field it is about when the code says which.
 */

// ── Field plumbing ──────────────────────────────────────────────────────────

const FIELD_ORDER: readonly ProfileField[] = [
  "publicFirstName",
  "publicLastInitial",
  "headline",
  "subjectCodes",
  "modes",
  "areaCode",
  "bio",
  "qualificationNote",
  "otherModeNote",
]

const ABOUT_FIELDS: readonly ProfileField[] = ["bio", "qualificationNote", "otherModeNote"]

function focusField(field: ProfileField): void {
  // A group (subjects, ways to meet) is a fieldset: focus its first box, not the fieldset.
  const target =
    document.querySelector<HTMLElement>(`#f-${field} input`) ?? document.querySelector<HTMLElement>(`#f-${field}`)
  target?.focus()
}

interface ServerProblem {
  field: ProfileField | null
  message: string
}

interface FormApi {
  values: ProfileFormValues
  set: <K extends keyof ProfileFormValues>(key: K, value: ProfileFormValues[K]) => void
  /** The problem to show under a field, if the tutor has reached it. */
  error: (field: ProfileField) => string | undefined
  touch: (field: ProfileField) => void
  disabled: boolean
}

function describedBy(field: ProfileField, hasError: boolean): string | undefined {
  return hasError ? `e-${field}` : undefined
}

function GroupError({ field, message }: { field: ProfileField; message: string | undefined }) {
  if (!message) return null
  return (
    <p id={`e-${field}`} role="alert" className="m-0 flex items-start gap-1.5 text-body-sm text-err">
      <WarningCircle size={16} className="mt-0.5 shrink-0" aria-hidden />
      {message}
    </p>
  )
}

// ── Step 1 · Public card ────────────────────────────────────────────────────

const MODES: readonly { mode: TutoringMode; key: "offersVirtual" | "offersInPerson" | "offersOther"; label: string }[] = [
  { mode: "virtual", key: "offersVirtual", label: "Virtual, by video link" },
  { mode: "in_person", key: "offersInPerson", label: "In person" },
  { mode: "other", key: "offersOther", label: "Another way" },
]

function previewCard(
  values: ProfileFormValues,
  profile: TutorOwnProfile | null,
  subjectNames: Map<string, string>,
  areaNames: Map<string, string>,
): TutorCardData {
  const first = values.publicFirstName.trim()
  const initial = values.publicLastInitial.trim().toUpperCase()
  return {
    tutorId: profile?.tutorId ?? "preview",
    publicName: first === "" ? "Your name" : initial ? `${first} ${initial}.` : first,
    headline: values.headline.trim() === "" ? "Your headline appears here." : values.headline.trim(),
    subjects: values.subjectCodes.map((code) => ({ code, name: subjectNames.get(code) ?? code })),
    modes: MODES.filter((m) => values[m.key]).map((m) => m.mode),
    area: { code: values.areaCode, name: areaNames.get(values.areaCode) ?? "Your area" },
    rating: profile?.rating ?? { state: "new", average: null, count: 0 },
  }
}

function SubjectsField({ form }: { form: FormApi }) {
  const reference = useReference()
  const error = form.error("subjectCodes")
  const chosen = new Set(form.values.subjectCodes)
  return (
    <fieldset
      id="f-subjectCodes"
      className="m-0 flex min-w-0 flex-col gap-2 border-0 p-0"
      aria-describedby={describedBy("subjectCodes", Boolean(error))}
    >
      <legend className="mb-2 p-0 text-label text-ink">Subjects you teach</legend>
      <QueryState
        query={reference}
        skeleton={
          <div className="flex flex-col gap-2">
            <SkeletonLine announce={false} width="40%" />
            <SkeletonLine announce={false} width="55%" />
            <SkeletonLine announce={false} width="35%" />
          </div>
        }
        error={{ heading: "Couldn't load the subjects", body: tutorLoadFailureMessage, compact: true }}
      >
        {(data) => (
          <div className="flex flex-col gap-2">
            {data.subjects.map((subject) => {
              const checked = chosen.has(subject.code)
              return (
                <Checkbox
                  key={subject.code}
                  label={`${subject.name} (${subject.code})`}
                  checked={checked}
                  disabled={form.disabled || (!checked && chosen.size >= MAX_SUBJECTS)}
                  onBlur={() => form.touch("subjectCodes")}
                  onChange={() => {
                    form.set(
                      "subjectCodes",
                      checked
                        ? form.values.subjectCodes.filter((code) => code !== subject.code)
                        : [...form.values.subjectCodes, subject.code],
                    )
                    form.touch("subjectCodes")
                  }}
                />
              )
            })}
          </div>
        )}
      </QueryState>
      <GroupError field="subjectCodes" message={error} />
    </fieldset>
  )
}

function AreaField({ form }: { form: FormApi }) {
  const areas = usePublicTutoringAreas()
  return (
    <QueryState
      query={areas}
      skeleton={<SkeletonBlock announce={false} className="h-16" />}
      error={{ heading: "Couldn't load the areas", body: tutorLoadFailureMessage, compact: true }}
    >
      {(list) => (
        <Select
          id="f-areaCode"
          label="Area"
          hint="The city or district students see. Not your address."
          value={form.values.areaCode}
          disabled={form.disabled}
          error={form.error("areaCode")}
          onBlur={() => form.touch("areaCode")}
          onChange={(event) => form.set("areaCode", event.target.value)}
        >
          <option value="">Choose your area</option>
          {list.items.map((area) => (
            <option key={area.code} value={area.code}>
              {area.name}
            </option>
          ))}
        </Select>
      )}
    </QueryState>
  )
}

function CardPreview({ form, profile }: { form: FormApi; profile: TutorOwnProfile | null }) {
  const reference = useReference()
  const areas = usePublicTutoringAreas()
  const subjectNames = new Map((reference.data?.subjects ?? []).map((s) => [s.code, s.name]))
  const areaNames = new Map((areas.data?.items ?? []).map((a) => [a.code, a.name]))
  return (
    <section aria-labelledby="card-preview-title" className="flex flex-col gap-3 lg:sticky lg:top-6">
      <h3 id="card-preview-title" className="m-0 text-label text-ink">
        Your card on the open web
      </h3>
      <TutorCard tutor={previewCard(form.values, profile, subjectNames, areaNames)} headingAs="h4" />
      <p className="m-0 text-body-sm text-ink-muted">{IDENTIFY_LINE}</p>
    </section>
  )
}

function Visibility({
  profile,
  indexableDraft,
  onIndexableDraft,
  disabled,
}: {
  profile: TutorOwnProfile | null
  indexableDraft: boolean
  onIndexableDraft: (value: boolean) => void
  disabled: boolean
}) {
  const toggle = useUpdateTutorProfile()
  const online = useOnlineStatus()
  const [pending, setPending] = useState<"indexable" | "paused" | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const state = profile?.listingState ?? null
  const canPause = state === "listed" || state === "pending_review"
  const failure = toggle.isError
    ? tutorActionFailureMessage(toggle.error, "We couldn't save that. Try again.")
    : null

  async function change(field: "indexable" | "paused", value: boolean) {
    setDone(null)
    setPending(field)
    try {
      await toggle.mutateAsync(toggleBody(field, value))
      setDone(
        field === "indexable"
          ? value
            ? "Search engines may list your card."
            : "Your card is off search engines. They can take a few weeks to drop it."
          : value
            ? "Your listing is paused."
            : "Your listing is live again.",
      )
    } catch {
      // Shown below.
    } finally {
      setPending(null)
    }
  }

  return (
    <section aria-labelledby="visibility-title" className="flex flex-col gap-4 rounded-lg border border-rule bg-paper-raised p-4">
      <h3 id="visibility-title" className="m-0 text-display-sm text-ink">
        Who can find your card
      </h3>
      <p id="search-notice" className="m-0 max-w-prose text-body-md text-ink">
        {SEARCH_NOTICE}
      </p>
      <Switch
        label="Show my card in search engines"
        aria-describedby="search-notice"
        checked={profile ? profile.indexable : indexableDraft}
        disabled={disabled || (profile !== null && !online)}
        state={pending === "indexable" ? "loading" : undefined}
        onCheckedChange={(value) => {
          if (profile) void change("indexable", value)
          else onIndexableDraft(value)
        }}
      />
      {canPause && profile ? (
        <Switch
          label="Pause my listing"
          description="While paused, students can't find you or request new sessions. Sessions already booked stay as they are."
          checked={profile.paused}
          disabled={disabled || !online}
          state={pending === "paused" ? "loading" : undefined}
          onCheckedChange={(value) => void change("paused", value)}
        />
      ) : null}
      <div aria-live="polite" className="flex flex-col gap-1">
        {done ? <p className="m-0 text-body-sm text-ok">{done}</p> : null}
        {failure ? (
          <p role="alert" className="m-0 text-body-sm text-err">
            {failure}
          </p>
        ) : null}
        {profile === null ? (
          <p className="m-0 text-body-sm text-ink-muted">This choice is saved with your draft.</p>
        ) : null}
      </div>
    </section>
  )
}

function CardStep({
  form,
  profile,
  indexableDraft,
  onIndexableDraft,
}: {
  form: FormApi
  profile: TutorOwnProfile | null
  indexableDraft: boolean
  onIndexableDraft: (value: boolean) => void
}) {
  const modesError = form.error("modes")
  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-5">
      <div className="flex flex-col gap-5 min-w-0 lg:col-span-3">
        <div className="flex flex-wrap items-start gap-4">
          <Input
            id="f-publicFirstName"
            label="First name"
            autoComplete="given-name"
            value={form.values.publicFirstName}
            disabled={form.disabled}
            maxLength={FIELD_LIMITS.firstName + 10}
            error={form.error("publicFirstName")}
            onBlur={() => form.touch("publicFirstName")}
            onChange={(event) => form.set("publicFirstName", event.target.value)}
            wrapperClassName="min-w-0 flex-1"
          />
          <Input
            id="f-publicLastInitial"
            label="Last initial"
            hint="One letter, optional."
            autoComplete="off"
            maxLength={2}
            value={form.values.publicLastInitial}
            disabled={form.disabled}
            error={form.error("publicLastInitial")}
            onBlur={() => form.touch("publicLastInitial")}
            onChange={(event) => form.set("publicLastInitial", event.target.value)}
            wrapperClassName="w-32"
          />
        </div>

        <Input
          id="f-headline"
          label="Headline"
          hint={`A short line on your card. Up to ${FIELD_LIMITS.headline} characters.`}
          value={form.values.headline}
          disabled={form.disabled}
          error={form.error("headline")}
          onBlur={() => form.touch("headline")}
          onChange={(event) => form.set("headline", event.target.value)}
        />

        <SubjectsField form={form} />

        <fieldset
          id="f-modes"
          className="m-0 flex min-w-0 flex-col gap-2 border-0 p-0"
          aria-describedby={describedBy("modes", Boolean(modesError))}
        >
          <legend className="mb-2 p-0 text-label text-ink">Ways to meet</legend>
          <div className="flex flex-col gap-2">
            {MODES.map((m) => (
              <Checkbox
                key={m.key}
                label={m.label}
                checked={form.values[m.key]}
                disabled={form.disabled}
                onChange={(event) => {
                  form.set(m.key, event.target.checked)
                  form.touch("modes")
                }}
              />
            ))}
          </div>
          <GroupError field="modes" message={modesError} />
        </fieldset>

        <AreaField form={form} />

        <Visibility
          profile={profile}
          indexableDraft={indexableDraft}
          onIndexableDraft={onIndexableDraft}
          disabled={form.disabled}
        />
      </div>

      <div className="min-w-0 lg:col-span-2">
        <CardPreview form={form} profile={profile} />
      </div>
    </div>
  )
}

// ── Step 2 · About ──────────────────────────────────────────────────────────

function AboutStep({ form }: { form: FormApi }) {
  return (
    <div className="flex max-w-2xl flex-col gap-5">
      <Textarea
        id="f-bio"
        label="About you"
        hint={`Signed-in students and parents read this. Phone numbers, email addresses and chat handles are not allowed. Up to ${FIELD_LIMITS.bio} characters.`}
        rows={6}
        value={form.values.bio}
        disabled={form.disabled}
        error={form.error("bio")}
        onBlur={() => form.touch("bio")}
        onChange={(event) => form.set("bio", event.target.value)}
      />
      <Textarea
        id="f-qualificationNote"
        label="Qualifications and experience"
        hint="Optional. Degrees, exams you took, years of teaching."
        rows={3}
        value={form.values.qualificationNote}
        disabled={form.disabled}
        error={form.error("qualificationNote")}
        onBlur={() => form.touch("qualificationNote")}
        onChange={(event) => form.set("qualificationNote", event.target.value)}
      />
      {form.values.offersOther ? (
        <Input
          id="f-otherModeNote"
          label="How you meet in another way"
          hint={`Optional. Students see it when they pick "Another way". Up to ${FIELD_LIMITS.otherModeNote} characters.`}
          value={form.values.otherModeNote}
          disabled={form.disabled}
          error={form.error("otherModeNote")}
          onBlur={() => form.touch("otherModeNote")}
          onChange={(event) => form.set("otherModeNote", event.target.value)}
        />
      ) : null}
    </div>
  )
}

// ── Step 3 · Evidence ───────────────────────────────────────────────────────

function EvidenceStep({ profile }: { profile: TutorOwnProfile }) {
  const upload = useUploadTutorEvidence()
  const remove = useDeleteTutorEvidence()
  const online = useOnlineStatus()
  const [file, setFile] = useState<File | null>(null)
  const [description, setDescription] = useState("")
  const [clientError, setClientError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<Evidence | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const listRef = useRef<HTMLHeadingElement>(null)
  const full = !canAddEvidence(profile.evidence)

  function choose(next: File | null) {
    setFile(next)
    setMessage(null)
    upload.reset()
    setClientError(next ? evidenceFileError(next, profile.evidence) : null)
  }

  async function send() {
    if (!file) return
    const problem = evidenceFileError(file, profile.evidence)
    if (problem) {
      setClientError(problem)
      return
    }
    try {
      await upload.mutateAsync({ file, description: description.trim() || undefined })
      setFile(null)
      setDescription("")
      setMessage("File uploaded. Lemely will look at it when your profile is reviewed.")
    } catch {
      // Shown under the picker.
    }
  }

  async function confirmDelete() {
    if (!deleting) return
    try {
      await remove.mutateAsync({ evidenceId: deleting.evidenceId })
      setMessage("File deleted.")
      setDeleting(null)
      listRef.current?.focus()
    } catch {
      // The dialog shows the error.
    }
  }

  const uploadFailure = upload.isError
    ? (evidenceUploadStatusMessage(upload.error) ??
      tutorActionFailureMessage(upload.error, "We couldn't upload that file. Try again."))
    : null

  return (
    <div className="flex max-w-2xl flex-col gap-5">
      <div className="flex flex-col gap-1">
        <p className="m-0 text-body-md text-ink">
          Upload up to {EVIDENCE_MAX_FILES} files that show who you are as a teacher, such as a degree certificate or a
          teaching letter. PDF, JPEG or PNG, up to 10 MB each.
        </p>
        <p className="m-0 text-body-md text-ink">{EVIDENCE_NO_ID_LINE}</p>
        <p className="m-0 text-body-sm text-ink-muted">{EVIDENCE_BADGE_LINE}</p>
      </div>

      <div className="flex flex-col gap-2">
        <h3 ref={listRef} tabIndex={-1} className="m-0 text-label text-ink focus:outline-none">
          Your files ({profile.evidence.length} of {EVIDENCE_MAX_FILES})
        </h3>
        {profile.evidence.length === 0 ? (
          <p className="m-0 text-body-md text-ink-muted">No files yet.</p>
        ) : (
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {profile.evidence.map((item) => {
              const Glyph = item.contentType === "application/pdf" ? FilePdf : ImageSquare
              return (
                <li
                  key={item.evidenceId}
                  className="flex items-start gap-3 rounded-lg border border-rule bg-paper-raised p-3"
                >
                  <Glyph size={22} className="mt-0.5 shrink-0 text-ink-muted" aria-hidden />
                  <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="break-all text-label text-ink">{item.filename}</span>
                    <span className="text-body-sm text-ink-muted">
                      {item.contentType === "application/pdf" ? "PDF" : "Image"}, {formatFileSize(item.sizeBytes)}, added{" "}
                      {relativeTime(item.uploadedAt)}
                    </span>
                    {item.description ? (
                      <span className="break-words text-body-sm text-ink">{item.description}</span>
                    ) : null}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={!online}
                    aria-label={`Delete ${item.filename}`}
                    onClick={() => {
                      remove.reset()
                      setDeleting(item)
                    }}
                  >
                    Delete
                  </Button>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      {full ? (
        <p className="m-0 text-body-sm text-ink-muted">
          You have uploaded the most files allowed. Delete one to add another.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          <FileDrop
            label="Add a file"
            accept={EVIDENCE_ACCEPT}
            file={file}
            onFileChange={choose}
            busy={upload.isPending}
            disabled={!online}
            error={clientError ?? uploadFailure}
            hint="PDF, JPEG or PNG, up to 10 MB."
          />
          <Input
            label="What is this? (optional)"
            maxLength={200}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            hint="Up to 200 characters. Phone numbers and email addresses are not allowed."
          />
          <div>
            <Button
              variant="primary"
              loading={upload.isPending}
              disabled={!file || clientError !== null || !online}
              onClick={() => void send()}
            >
              Upload file
            </Button>
          </div>
        </div>
      )}
      <div aria-live="polite">{message ? <p className="m-0 text-body-sm text-ok">{message}</p> : null}</div>

      <ConfirmModal
        open={deleting !== null}
        title="Delete this file?"
        description={deleting?.filename}
        consequence={`This cannot be undone. ${EVIDENCE_BADGE_LINE}`}
        confirmLabel="Delete file"
        pendingLabel="Deleting"
        cancelLabel="Keep it"
        pending={remove.isPending}
        error={tutorActionFailureMessage(remove.error, "We couldn't delete that file. Try again.")}
        onConfirm={() => void confirmDelete()}
        onCancel={() => setDeleting(null)}
      />
    </div>
  )
}

// ── Step 4 · Availability ───────────────────────────────────────────────────

function AvailabilityStep({ profile }: { profile: TutorOwnProfile }) {
  return (
    <div className="flex max-w-2xl flex-col gap-4">
      <p className="m-0 text-body-md text-ink">
        Students can only book the weekly times you set, in {profile.zoneLabel}.
      </p>
      <p className="m-0 text-body-md text-ink-muted" aria-live="polite">
        {availabilitySummary(profile.availability)}
      </p>
      <div>
        <Link to="/teacher/tutoring/availability" className={buttonVariants({ variant: "secondary", size: "md" })}>
          {profile.availability.length === 0 ? "Add weekly times" : "Edit weekly times"}
        </Link>
      </div>
    </div>
  )
}

// ── Step 5 · Submit ─────────────────────────────────────────────────────────

function SubmitStep({
  profile,
  onGo,
}: {
  profile: TutorOwnProfile
  onGo: (step: StepId) => void
}) {
  const submit = useSubmitTutorProfile()
  const me = useProfile()
  const online = useOnlineStatus()
  const resultRef = useRef<HTMLHeadingElement>(null)
  const blockers = submitBlockers({
    headline: profile.headline,
    subjects: profile.subjects,
    modes: profile.modes,
    areaCode: profile.area.code,
    availabilityCount: profile.availability.length,
  })
  const unconfirmed = me.data?.emailVerified === false
  const resubmit = profile.listingState === "rejected"

  useEffect(() => {
    if (submit.isSuccess) resultRef.current?.focus()
  }, [submit.isSuccess])

  if (submit.isSuccess || profile.listingState === "pending_review") {
    return (
      <div className="flex max-w-2xl flex-col gap-3">
        <h3 ref={resultRef} tabIndex={-1} className="m-0 flex items-center gap-2 text-display-sm text-ink focus:outline-none">
          <CheckCircle size={22} weight="bold" className="text-ok" aria-hidden />
          {submit.isSuccess ? "Sent for review" : "Under review"}
        </h3>
        <p className="m-0 text-body-md text-ink">{UNDER_REVIEW_LINE}</p>
        <div>
          <Link to="/teacher/tutoring" className={buttonVariants({ variant: "secondary", size: "md" })}>
            Back to tutoring
          </Link>
        </div>
      </div>
    )
  }

  const failure = submit.isError
    ? tutorActionFailureMessage(submit.error, "We couldn't send your profile. Try again.")
    : null

  return (
    <div className="flex max-w-2xl flex-col gap-4">
      {resubmit && profile.reviewNote ? (
        <p className="m-0 rounded-md border border-rule bg-warn-wash px-3 py-2.5 text-body-md text-ink">
          Lemely's note: {profile.reviewNote}
        </p>
      ) : null}
      {blockers.length > 0 ? (
        <div className="flex flex-col gap-2">
          <h3 className="m-0 text-label text-ink">Before you can send it</h3>
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {blockers.map((blocker) => (
              <li key={blocker.text} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-body-md text-ink">
                <span className="flex min-w-0 items-start gap-2">
                  <WarningCircle size={18} className="mt-0.5 shrink-0 text-warn" aria-hidden />
                  {blocker.text}
                </span>
                <Button variant="ghost" size="sm" onClick={() => onGo(blocker.step)}>
                  Go to this step
                </Button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="m-0 flex items-center gap-2 text-body-md text-ink">
          <CheckCircle size={18} weight="bold" className="shrink-0 text-ok" aria-hidden />
          Everything Lemely needs is in place.
        </p>
      )}
      {unconfirmed ? (
        <p className="m-0 text-body-md text-ink">
          Confirm your email address before you send your profile.{" "}
          <Link to="/verify-email" className="rounded-sm text-accent-ink underline underline-offset-2 transition-colors hover:text-accent">
            Confirm your email
          </Link>
        </p>
      ) : null}
      {failure ? (
        <p role="alert" className="m-0 text-body-sm text-err">
          {failure}
        </p>
      ) : null}
      {!online ? <p className="m-0 text-body-sm text-ink-muted">You're offline. Reconnect to send your profile.</p> : null}
      <div>
        <Button
          variant="primary"
          loading={submit.isPending}
          disabled={blockers.length > 0 || unconfirmed || !online}
          onClick={() => void submit.mutateAsync().catch(() => undefined)}
        >
          {resubmit ? "Resubmit for review" : "Send for review"}
        </Button>
      </div>
    </div>
  )
}

// ── Read-only (suspended or closed) ─────────────────────────────────────────

function ReadOnlyProfile({ profile }: { profile: TutorOwnProfile }) {
  const rows: [string, ReactNode][] = [
    ["Name on your card", profile.publicName],
    ["Headline", profile.headline],
    ["Subjects", profile.subjects.map((s) => s.name).join(", ")],
    ["Area", profile.area.name],
    ["Search engines", profile.indexable ? "May list your card" : "Off"],
  ]
  return (
    <dl className="m-0 grid max-w-2xl grid-cols-1 gap-4 sm:grid-cols-2">
      {rows.map(([label, value]) => (
        <div key={label} className="flex min-w-0 flex-col gap-0.5">
          <dt className="text-body-sm text-ink-muted">{label}</dt>
          <dd className="m-0 break-words text-body-md text-ink">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

// ── The editor ──────────────────────────────────────────────────────────────

const TONE_WASH = { ok: "bg-ok-wash", info: "bg-info-wash", warn: "bg-warn-wash", neutral: "bg-paper-sunk" } as const

function Editor({ profile }: { profile: TutorOwnProfile | null }) {
  const state = profile?.listingState ?? null
  const mode = profileMode(state)
  const steps = stepsFor(state)
  const [params, setParams] = useSearchParams()
  const requested = params.get("step")
  const current = steps.find((step) => step.id === requested) ?? steps[0]
  const saved = profile ? valuesFromProfile(profile) : EMPTY_PROFILE_VALUES
  const [values, setValues] = useState<ProfileFormValues>(saved)
  const [touched, setTouched] = useState<Set<ProfileField>>(new Set())
  const [attempted, setAttempted] = useState(false)
  const [server, setServer] = useState<ServerProblem | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [indexableDraft, setIndexableDraft] = useState(true)
  const create = useCreateTutorProfile()
  const save = useUpdateTutorProfile()
  const toggle = useUpdateTutorProfile()
  const online = useOnlineStatus()
  const headingRef = useRef<HTMLHeadingElement>(null)
  const shownStep = useRef(current.id)
  const pending = create.isPending || save.isPending || toggle.isPending

  const banner = listingBanner(state, { paused: profile?.paused ?? false, reviewNote: profile?.reviewNote ?? null })
  const readOnly = mode === "readonly"
  const clientErrors = validateProfile(values)

  function goTo(step: StepId) {
    const next = new URLSearchParams(params)
    next.set("step", step)
    setParams(next)
  }

  // A new step takes focus on its heading, so a keyboard user starts at the top of it.
  useEffect(() => {
    if (shownStep.current === current.id) return
    shownStep.current = current.id
    headingRef.current?.focus()
  }, [current.id])

  const form: FormApi = {
    values,
    set: (key, value) => {
      setValues((existing) => ({ ...existing, [key]: value }))
      setNotice(null)
      if (server?.field && (server.field === key || (server.field === "modes" && String(key).startsWith("offers")))) {
        setServer(null)
      }
    },
    touch: (field) => setTouched((existing) => new Set(existing).add(field)),
    error: (field) => {
      if (server?.field === field) return server.message
      return attempted || touched.has(field) ? clientErrors[field] : undefined
    },
    disabled: readOnly || pending,
  }

  function focusFirst(errors: Partial<Record<ProfileField, string>>) {
    const first = FIELD_ORDER.find((field) => errors[field])
    if (!first) return
    const owner: StepId = ABOUT_FIELDS.includes(first) ? "about" : "card"
    if (owner !== current.id) goTo(owner)
    window.setTimeout(() => focusField(first), 0)
  }

  function explain(error: unknown, fallback: string): void {
    const typed = tutoringErrorOf(error)
    const field = typed ? profileErrorField(typed.code) : null
    const message = tutorActionFailureMessage(error, fallback) ?? fallback
    setServer({ field, message })
    if (field) window.setTimeout(() => focusField(field), 0)
  }

  /** Saves the text steps. Returns whether the profile is now saved. */
  async function persist(): Promise<boolean> {
    setAttempted(true)
    const errors = validateProfile(values)
    // While setting up, only the step in hand is judged; About can be filled in next.
    const inScope =
      mode === "onboarding"
        ? FIELD_ORDER.filter((field) => ABOUT_FIELDS.includes(field) === (current.id === "about"))
        : FIELD_ORDER
    const judged: Partial<Record<ProfileField, string>> = {}
    for (const field of inScope) if (errors[field]) judged[field] = errors[field]
    if (Object.keys(judged).length > 0) {
      focusFirst(judged)
      return false
    }
    setServer(null)
    setNotice(null)
    try {
      if (profile === null) {
        await create.mutateAsync(buildCreateBody(values))
        if (!indexableDraft) {
          try {
            await toggle.mutateAsync(toggleBody("indexable", false))
          } catch {
            setServer({
              field: null,
              message:
                "Your draft is saved, but we couldn't save your search engine choice. Check the switch and try again.",
            })
            return false
          }
        }
        setAttempted(false)
        setNotice("Draft saved.")
        return true
      }
      const diff = buildUpdateBody(saved, values)
      if (Object.keys(diff).length === 0) return true
      const result = await save.mutateAsync(diff)
      setAttempted(false)
      setNotice(
        result.reReviewRequired
          ? "Saved. Your profile is back in review and hidden until Lemely approves it."
          : "Changes saved.",
      )
      return true
    } catch (error) {
      explain(error, "We couldn't save your profile. Try again.")
      return false
    }
  }

  async function onSave(event: FormEvent, next?: StepId) {
    event.preventDefault()
    const ok = await persist()
    if (ok && next) goTo(next)
  }

  const index = steps.findIndex((step) => step.id === current.id)
  const previous = steps[index - 1]
  const following = steps[index + 1]
  const textStep = current.id === "card" || current.id === "about"
  const reReview = reReviewNotice(state, saved, values)
  const completed = new Set<number>()
  if (profile) {
    steps.forEach((step) => {
      const done =
        step.id === "card" ||
        (step.id === "about" && profile.bio.trim() !== "") ||
        (step.id === "evidence" && profile.evidence.length > 0) ||
        (step.id === "availability" && profile.availability.length > 0)
      if (done) completed.add(step.number)
    })
  }

  const needsProfile = profile === null && current.id !== "card"

  return (
    <div className="flex flex-col gap-6 min-w-0">
      <div className="flex flex-col gap-2 border-b border-rule pb-5">
        <Link
          to="/teacher/tutoring"
          className="inline-flex w-fit items-center gap-1 py-1 text-body-sm text-ink-muted transition-colors hover:text-ink"
        >
          Back to tutoring
        </Link>
        <h1 className="m-0 text-display-md text-ink">Tutor profile</h1>
        <p
          className={cn(
            "m-0 flex flex-col gap-0.5 rounded-md border border-rule px-3 py-2.5 text-body-md text-ink",
            TONE_WASH[banner.tone],
          )}
        >
          <strong className="font-medium">{banner.title}</strong>
          <span>{banner.body}</span>
        </p>
      </div>

      {readOnly && profile ? (
        <ReadOnlyProfile profile={profile} />
      ) : (
        <>
          <Stepper
            label="Profile steps"
            steps={steps.map((step) => ({ id: step.number, label: step.label }))}
            current={current.number}
            completed={completed}
            onSelect={(number) => {
              const target = steps.find((step) => step.number === number)
              if (target) goTo(target.id)
            }}
          />

          <h2
            ref={headingRef}
            tabIndex={-1}
            className="m-0 text-display-sm text-ink focus:outline-none"
          >
            {current.number}. {current.label}
          </h2>

          {needsProfile ? (
            <div className="flex max-w-2xl flex-col gap-3">
              <p className="m-0 text-body-md text-ink">
                Save your public card first. The other steps belong to your profile, which is created when you save it.
              </p>
              <div>
                <Button variant="secondary" onClick={() => goTo("card")}>
                  Go to Public card
                </Button>
              </div>
            </div>
          ) : (
            <>
              {textStep ? (
                <form
                  noValidate
                  onSubmit={(event) => void onSave(event, mode === "onboarding" ? following?.id : undefined)}
                  className="flex flex-col gap-6"
                >
                  {current.id === "card" ? (
                    <CardStep
                      form={form}
                      profile={profile}
                      indexableDraft={indexableDraft}
                      onIndexableDraft={setIndexableDraft}
                    />
                  ) : (
                    <AboutStep form={form} />
                  )}
                  <div className="flex flex-col gap-3 border-t border-rule pt-5">
                    {reReview ? (
                      <p className="m-0 flex items-start gap-2 rounded-md border border-rule bg-warn-wash px-3 py-2.5 text-body-md text-ink">
                        <WarningCircle size={18} className="mt-0.5 shrink-0 text-warn" aria-hidden />
                        {reReview}
                      </p>
                    ) : null}
                    <div className="flex flex-wrap items-center gap-3">
                      {mode === "onboarding" && previous ? (
                        <Button type="button" variant="ghost" onClick={() => goTo(previous.id)} disabled={pending}>
                          Back
                        </Button>
                      ) : null}
                      <Button type="submit" variant="primary" loading={pending} disabled={!online}>
                        {mode === "onboarding" ? "Save and continue" : "Save changes"}
                      </Button>
                    </div>
                    <div aria-live="polite" className="flex flex-col gap-1">
                      {notice ? <p className="m-0 text-body-sm text-ok">{notice}</p> : null}
                      {!online ? (
                        <p className="m-0 text-body-sm text-ink-muted">You're offline. Reconnect to save.</p>
                      ) : null}
                    </div>
                    {server && server.field === null ? (
                      <p role="alert" className="m-0 text-body-sm text-err">
                        {server.message}
                      </p>
                    ) : null}
                  </div>
                </form>
              ) : (
                <div className="flex flex-col gap-6">
                  {current.id === "evidence" && profile ? <EvidenceStep profile={profile} /> : null}
                  {current.id === "availability" && profile ? <AvailabilityStep profile={profile} /> : null}
                  {current.id === "submit" && profile ? <SubmitStep profile={profile} onGo={goTo} /> : null}
                  {mode === "onboarding" ? (
                    <div className="flex flex-wrap items-center gap-3 border-t border-rule pt-5">
                      {previous ? (
                        <Button type="button" variant="ghost" onClick={() => goTo(previous.id)}>
                          Back
                        </Button>
                      ) : null}
                      {following ? (
                        <Button type="button" variant="primary" onClick={() => goTo(following.id)}>
                          Continue
                        </Button>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  )
}

function EditorSkeleton() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeaderSkeleton />
      <SkeletonBlock announce={false} className="h-10" />
      <SkeletonBlock announce={false} className="h-64" />
    </div>
  )
}

export function TutorProfileEditor() {
  const profileQuery = useOwnTutorProfile()
  const noProfile = isTutoringError(profileQuery.error, "no_tutor_profile")
  // No profile is not a failure: it is the first step of setting one up. It is
  // presented to `QueryState` as a successful read of nothing, so the editor
  // stays mounted at the same place when the draft is created.
  const query: QueryStateQuery<TutorOwnProfile | null> = noProfile
    ? { status: "success", data: null, error: null, refetch: profileQuery.refetch }
    : profileQuery
  return (
    <div className="flex flex-col gap-5 min-w-0">
      <QueryState
        query={query}
        srHeading="Tutor profile"
        skeleton={<EditorSkeleton />}
        error={{ heading: "Couldn't load your profile", body: tutorLoadFailureMessage }}
      >
        {(profile) => <Editor profile={profile} />}
      </QueryState>
    </div>
  )
}
