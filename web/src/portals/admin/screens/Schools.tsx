/* Hallmark · pre-emit critique: P4 H4 E3 S4 R4 V4 */
import { useState } from "react"
import { Card, CardBody } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Modal } from "@/components/ui/modal"
import { Badge } from "@/components/ui/badge"
import { Eyebrow } from "@/components/ui/primitives"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import { EmptyState } from "@/components/ui/state-views"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import {
  adminLoadFailureMessage,
  adminMutationFailureMessage,
  schoolAdminCreateFailureMessage,
  schoolUpdateFailureMessage,
} from "@/lib/adminOutcome"
import {
  useCreateSchool,
  useCreateSchoolAdmin,
  useSchools,
  useUpdateSchool,
} from "@/lib/hooks/useAdminApi"
import type { SchoolSummary } from "@/lib/adminTypes"

/**
 * Task 22 · Platform-admin Schools screen (D7.8).
 *
 * Reads `GET /api/admin/schools`; writes through `POST /admin/schools`,
 * `PATCH /admin/schools/{id}` and `POST /admin/schools/{id}/admins`.
 *
 * ── Why this screen exists ──────────────────────────────────────────────────
 *
 * Spec §1.1: tracing the account graph found that `platform_admin -> School ->
 * school_admin -> teacher` had no first link. `POST /api/school/teachers/invite`
 * was fully built, tested and gated to `school_admin` — and unreachable in any
 * real deployment, because no production code path created either a `School`
 * row or a `school_admin` account. Only `seed.py` and eighteen test files ever
 * constructed either. This screen is that first link: a platform admin creates
 * a school with a real seat quota, then creates the school_admin who runs it.
 * D4.10 answered "what do the admin surfaces get" with "fully build the
 * required screens and completely wire them" (D7.8) — shipping the four routes
 * alone would have recreated exactly the unreachable-endpoint pattern this
 * issue exists to fix.
 *
 * ── The one-time password ───────────────────────────────────────────────────
 *
 * `CreateSchoolAdminModal` never collects a password: every school_admin this
 * screen creates gets a backend-generated one, shown exactly once in the
 * success panel. That panel says two things plainly, per Task 22's binding
 * rule — it will not be shown again, and no email has been sent for it. Both
 * are load-bearing, not disclaimers: the backend generates and returns the
 * password once *because* no email provider delivers anything in v1 (D7.6),
 * so a screen that stayed silent about the second half would let a platform
 * admin reasonably assume a mail went out when nothing did.
 *
 * ── The quota-below-assigned 409 ────────────────────────────────────────────
 *
 * `EditSchoolModal` can be refused with a 409 naming both the quota that was
 * requested and the seats already assigned (Task 12,
 * `school_provisioning_repo.QuotaBelowAssignedSeatsError`). Both numbers are
 * surfaced — `schoolUpdateFailureMessage` builds the sentence from the
 * screen's own state rather than the server's prose; see that function in
 * `adminOutcome.ts` for why parsing the server's sentence would be the wrong
 * fix even though it also contains both numbers.
 */
export function Schools() {
  const query = useSchools()

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1.5">
        <Eyebrow>Platform admin</Eyebrow>
        <h1 className="text-display-lg text-ink">Schools</h1>
        <p className="max-w-prose text-body-md text-ink-muted">
          Every school on the platform: its seat quota, how many seats are already assigned, and
          who administers it. Create a school here first. A school_admin needs one to exist
          before they can be given the console that runs it.
        </p>
      </header>

      <QueryState
        query={query}
        skeleton={
          <>
            <PageHeaderSkeleton />
            <ListSkeleton rows={5} />
          </>
        }
        error={{ heading: "We couldn't load the schools list", body: adminLoadFailureMessage }}
      >
        {(data) => (
          <>
            {/* The "no schools yet" empty view stays inside `children` rather
                than going through `isEmpty`/`empty`: `CreateSchoolPanel` must
                render alongside the empty state (it is the way out of it), and
                `empty` renders in place of `children` entirely. */}
            <CreateSchoolPanel />
            {data.schools.length === 0 ? (
              <EmptyState
                marginalia="an empty campus"
                heading="No schools yet"
                body="Create one above. Once it has a seat quota, add a school_admin to run it."
              />
            ) : (
              <SchoolsTable schools={data.schools} />
            )}
          </>
        )}
      </QueryState>
    </div>
  )
}

/**
 * Create a school with an initial seat quota.
 *
 * The quota is a required field on the wire (`CreateSchoolRequest.seatQuota`,
 * no default) rather than something this form could leave at an implicit
 * zero: D7.2 is the reason self-service signup never creates a school at all
 * — a visitor-created one would carry a quota of 0 and sit unusable until a
 * platform admin intervened anyway, so that intervention happens here, up
 * front, instead of being deferred to a second screen.
 */
function CreateSchoolPanel() {
  const [name, setName] = useState("")
  const [seatQuota, setSeatQuota] = useState("")
  const [quotaError, setQuotaError] = useState<string | null>(null)
  const create = useCreateSchool()

  function parsedQuota(): number | null {
    const quota = Number(seatQuota)
    if (seatQuota.trim() === "" || !Number.isInteger(quota) || quota < 0) return null
    return quota
  }

  return (
    <Card>
      <CardBody className="flex flex-col gap-4">
        <Eyebrow>Create a school</Eyebrow>
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            const trimmedName = name.trim()
            const quota = parsedQuota()
            if (quota === null) {
              setQuotaError("Enter a whole number, zero or more.")
              return
            }
            if (!trimmedName) return
            setQuotaError(null)
            create.mutate(
              { name: trimmedName, seatQuota: quota },
              {
                onSuccess: () => {
                  setName("")
                  setSeatQuota("")
                },
              },
            )
          }}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <Input
              label="School name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              autoComplete="off"
            />
            <Input
              label="Seat quota"
              type="number"
              inputMode="numeric"
              min={0}
              step={1}
              value={seatQuota}
              onChange={(event) => {
                setSeatQuota(event.target.value)
                setQuotaError(null)
              }}
              error={quotaError ?? undefined}
              hint={
                quotaError
                  ? undefined
                  : "How many student seats this school starts with. You can change it later."
              }
            />
          </div>
          {create.isError ? (
            <p className="text-body-sm text-err">{adminMutationFailureMessage(create.error)}</p>
          ) : null}
          <div>
            <Button type="submit" variant="primary" loading={create.isPending}>
              Create this school
            </Button>
          </div>
        </form>
      </CardBody>
    </Card>
  )
}

function SchoolsTable({ schools }: { schools: SchoolSummary[] }) {
  const [editing, setEditing] = useState<SchoolSummary | null>(null)
  const [addingAdminTo, setAddingAdminTo] = useState<SchoolSummary | null>(null)

  return (
    <>
      <Table>
        <THead>
          <tr>
            <TH>School</TH>
            <TH numeric>Seat quota</TH>
            <TH numeric>Seats assigned</TH>
            <TH>School admins</TH>
            <TH>
              <span className="sr-only">Actions</span>
            </TH>
          </tr>
        </THead>
        <TBody>
          {schools.map((school) => {
            // Same guard `Seats.tsx` uses for its own "at capacity" cue: a
            // school with a quota of 0 and nothing assigned reads as
            // "not provisioned yet", not as "full".
            const atQuota = school.seatQuota > 0 && school.seatsAvailable === 0
            return (
              <TR key={school.schoolId}>
                <TD>
                  <span className="text-body-sm text-ink">{school.name}</span>
                </TD>
                <TD numeric>{school.seatQuota}</TD>
                <TD numeric>
                  <div className="flex flex-col items-end gap-1">
                    <span>{school.seatsAssigned}</span>
                    {atQuota ? <Badge tone="warn">At capacity</Badge> : null}
                  </div>
                </TD>
                <TD>
                  {school.admins.length === 0 ? (
                    <span className="text-body-sm text-ink-faint">No school_admin yet</span>
                  ) : (
                    <ul className="flex flex-col gap-0.5">
                      {school.admins.map((admin) => (
                        <li key={admin.userId} className="text-body-sm text-ink-muted">
                          {admin.displayName ?? admin.email}
                        </li>
                      ))}
                    </ul>
                  )}
                </TD>
                <TD>
                  <div className="flex flex-wrap justify-end gap-2">
                    <Button size="sm" onClick={() => setEditing(school)}>
                      Edit
                    </Button>
                    <Button size="sm" onClick={() => setAddingAdminTo(school)}>
                      Add admin
                    </Button>
                  </div>
                </TD>
              </TR>
            )
          })}
        </TBody>
      </Table>

      {editing ? <EditSchoolModal school={editing} onClose={() => setEditing(null)} /> : null}
      {addingAdminTo ? (
        <CreateSchoolAdminModal school={addingAdminTo} onClose={() => setAddingAdminTo(null)} />
      ) : null}
    </>
  )
}

/**
 * Rename a school and/or change its seat quota.
 *
 * `lastSubmittedQuota` is deliberately not the same value as the live
 * `seatQuota` field: if a 409 comes back and the reader edits the field again
 * before re-submitting, the error sentence must still name the number that
 * was actually refused, not whatever is currently sitting unsent in the
 * input.
 */
function EditSchoolModal({ school, onClose }: { school: SchoolSummary; onClose: () => void }) {
  const [name, setName] = useState(school.name)
  const [seatQuota, setSeatQuota] = useState(String(school.seatQuota))
  const [quotaError, setQuotaError] = useState<string | null>(null)
  const [lastSubmittedQuota, setLastSubmittedQuota] = useState<number | null>(null)
  const update = useUpdateSchool()

  function parsedQuota(): number | null {
    const quota = Number(seatQuota)
    if (seatQuota.trim() === "" || !Number.isInteger(quota) || quota < 0) return null
    return quota
  }

  function handleSubmit() {
    const trimmedName = name.trim()
    const quota = parsedQuota()
    if (quota === null) {
      setQuotaError("Enter a whole number, zero or more.")
      return
    }
    if (!trimmedName) return
    setQuotaError(null)
    setLastSubmittedQuota(quota)
    update.mutate(
      { schoolId: school.schoolId, body: { name: trimmedName, seatQuota: quota } },
      { onSuccess: onClose },
    )
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={`Edit ${school.name}`}
      description="Rename this school or change how many seats it holds."
      size="sm"
      footer={
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="secondary" onClick={onClose} disabled={update.isPending}>
            Cancel
          </Button>
          <Button variant="primary" loading={update.isPending} onClick={handleSubmit}>
            Save changes
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <Input
          label="School name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          autoComplete="off"
        />
        <Input
          label="Seat quota"
          type="number"
          inputMode="numeric"
          min={0}
          step={1}
          value={seatQuota}
          onChange={(event) => {
            setSeatQuota(event.target.value)
            setQuotaError(null)
          }}
          error={quotaError ?? undefined}
          hint={
            quotaError
              ? undefined
              : `${school.seatsAssigned} ${
                  school.seatsAssigned === 1 ? "seat is" : "seats are"
                } already assigned here.`
          }
        />
        {update.isError && lastSubmittedQuota !== null ? (
          <p className="text-body-sm text-err">
            {schoolUpdateFailureMessage(update.error, lastSubmittedQuota, school.seatsAssigned)}
          </p>
        ) : null}
      </div>
    </Modal>
  )
}

/**
 * Create a school_admin and bind them to this school.
 *
 * No password field: every account created here gets a backend-generated
 * one. `dismissible`/`hideCloseButton` flip to closed-only once the account
 * exists — a stray Escape or scrim click must not be how a platform admin
 * loses the only copy of a credential that is never shown again, the same
 * reasoning `ConfirmModal` and `RemoveTeacherDialog` already apply to their
 * own irreversible moments.
 */
function CreateSchoolAdminModal({
  school,
  onClose,
}: {
  school: SchoolSummary
  onClose: () => void
}) {
  const [email, setEmail] = useState("")
  const [displayName, setDisplayName] = useState("")
  const create = useCreateSchoolAdmin()

  return (
    <Modal
      open
      onClose={onClose}
      title={`Add a school admin to ${school.name}`}
      description={
        create.isSuccess
          ? undefined
          : "They will be able to manage this school's seats, teachers and quota. Adding a school admin uses no seats. Seats are for students."
      }
      size="sm"
      dismissible={!create.isSuccess}
      hideCloseButton={create.isSuccess}
      footer={
        create.isSuccess ? (
          <Button variant="primary" onClick={onClose}>
            Done
          </Button>
        ) : (
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" onClick={onClose} disabled={create.isPending}>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={create.isPending}
              onClick={() => {
                const trimmedEmail = email.trim()
                if (!trimmedEmail) return
                create.mutate({
                  schoolId: school.schoolId,
                  body: { email: trimmedEmail, displayName: displayName.trim() || null },
                })
              }}
            >
              Add this school admin
            </Button>
          </div>
        )
      }
    >
      {create.isSuccess ? (
        // Shown once, said plainly (Task 22's binding rule): the backend
        // generates this password and returns it exactly here because no
        // email provider delivers anything in v1 (D7.6) — the copy must not
        // let a reader assume a mail went out when none did.
        <div className="flex flex-col gap-3">
          <p className="text-body-md text-ink">
            {create.data.email} can sign in to {school.name} now.
          </p>
          {create.data.temporaryPassword ? (
            <div className="flex flex-col gap-1.5 rounded-md border border-rule bg-paper-sunk p-3">
              <p className="text-body-sm text-ink">
                This password won&rsquo;t be shown again, and no email has been sent for it. Copy
                it now and share it with them yourself.
              </p>
              <code className="w-fit rounded-sm bg-paper-raised px-1.5 py-0.5 text-data-sm text-ink">
                {create.data.temporaryPassword}
              </code>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <Input
            label="Email address"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="off"
          />
          <Input
            label="Name (optional)"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            hint="Shown on this school's staff list."
            autoComplete="off"
          />
          {create.isError ? (
            <p className="text-body-sm text-err">{schoolAdminCreateFailureMessage(create.error)}</p>
          ) : null}
        </div>
      )}
    </Modal>
  )
}
