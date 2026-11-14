/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useEffect, useRef, useState, type ChangeEvent } from "react"
import { Avatar } from "@/components/ui/avatar"
import { PhoneEntryForm } from "@/components/phone-entry-form"
import { Button } from "@/components/ui/button"
import { PanelSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Select } from "@/components/ui/select"
import { validateAvatarFile } from "@/lib/avatarUpload"
import { useProfile, usePutTimezone, useRemoveAvatar, useUploadAvatar } from "@/lib/hooks/useMeApi"
import {
  FOLLOW_DEVICE_UPDATE,
  FOLLOW_DEVICE_VALUE,
  browserTimezones,
  deviceTimezone,
  deviceTimezoneUpdate,
  explicitTimezoneUpdate,
  pickerValue,
  timezoneOptions,
} from "@/lib/timezone"
import {
  settingsLoadFailureMessage,
  settingsSaveFailureMessage,
} from "@/lib/settingsOutcome"
import { AppearanceSettingsSection } from "./AppearanceSettings"
import { SettingsFrame } from "./SettingsFrame"
import { SettingsCard, SettingsRow, SettingsSection, SettingsStatus } from "./SettingsRows"

/*
 * Profile — the third screen in the settings lane, alongside `DeviceSettings`
 * and `NotificationSettings`. Mounted at `/teacher/settings` and
 * `/student/settings` (the `end: true` root of `PortalSettingsLayout`'s nav)
 * as well as the top-level `/settings/profile` (parent and admin's only path
 * to it, same as the other two screens — see `SettingsFrame`'s module header
 * for why that lane is role-agnostic).
 *
 * The name/email/role identity block mirrors `UserBlock` in
 * `portals/teacher/index.tsx` (and its student/admin siblings) exactly:
 * `displayName` is nullable, so the fallback is the email's local part, never
 * a fabricated name, and the role label title-cases the raw `role` string
 * rather than inventing a department or affiliation nothing in the account
 * actually carries.
 *
 * The picture upload is a plain file input, not a drag-and-drop zone like
 * `FileDrop` (used for paper scans in `CorrectPaper.tsx`): a profile picture
 * is a single deliberate choice made once in a while, not the primary action
 * of a whole screen, so the heavier affordance would overstate its
 * importance. Client-side checks (`validateAvatarFile`) exist to give a fast,
 * specific answer before a bad file ever leaves the browser; the 5 MiB and
 * type limits are not enforced only here; `POST /me/avatar` re-checks both
 * and remains the actual authority; see that module's own header.
 */

/** Same title-casing `UserBlock` uses for a raw role string — no invented
 * affiliation, just the platform role this account actually carries. */
function roleLabel(role: string): string {
  return role
    .split("_")
    .filter((word) => word.length > 0)
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(" ")
}

/**
 * The mobile number row (UD-11). With none on file the form is the row: this is the card the phone
 * banner and the rest of the app send people to, so it should not need a click to start. With one
 * on file it reads as a value with a Change button, the same as the other rows, and the form opens
 * in place only on request. Saving updates the cached profile (`usePutPhone`), so the banner
 * disappears without a reload and this row flips from the form to the value.
 */
function PhoneRow({ phone }: { phone: string | null }) {
  const [editing, setEditing] = useState(false)
  const [saved, setSaved] = useState(false)
  const missing = !phone
  // Saving or cancelling unmounts the field that held focus, which would drop it to the page. It goes
  // to the Change button instead, once the value view has rendered.
  const changeRef = useRef<HTMLButtonElement>(null)
  const [returnFocus, setReturnFocus] = useState(false)
  useEffect(() => {
    if (!returnFocus || editing || !phone) return
    changeRef.current?.focus()
    setReturnFocus(false)
  }, [returnFocus, editing, phone])

  if (missing || editing) {
    return (
      <SettingsRow
        label="Mobile number"
        stacked
        description={
          missing
            ? "Add a mobile number. You'll need one to pay for a plan or credits."
            : "Your number is shared with our payment provider when you pay."
        }
        control={
          <PhoneEntryForm
            hideLabel
            onSaved={() => {
              setEditing(false)
              setSaved(true)
              setReturnFocus(true)
            }}
            onCancel={
              missing
                ? undefined
                : () => {
                    setEditing(false)
                    setReturnFocus(true)
                  }
            }
          />
        }
      />
    )
  }

  return (
    <SettingsRow
      label="Mobile number"
      description="Used for payments. It is not checked by text message."
      control={
        <>
          <span className="text-body-md tabular-nums text-on-surface">{phone}</span>
          <Button
            ref={changeRef}
            type="button"
            variant="secondary"
            onClick={() => {
              setSaved(false)
              setEditing(true)
            }}
          >
            Change
          </Button>
        </>
      }
      status={saved ? <SettingsStatus>Saved.</SettingsStatus> : null}
    />
  )
}

/**
 * The section this screen renders, with no frame around it — mounted inside
 * `PortalSettingsLayout` for the in-portal lane, in addition to the framed
 * `ProfileSettings` below for the top-level `/settings/profile` lane.
 */
export function ProfileSettingsSection({
  appearance = true,
}: {
  /** Render the theme choice inside this section. The teacher Settings
   * dialog passes `false`: it has an Appearance tab of its own. */
  appearance?: boolean
} = {}) {
  const profile = useProfile()
  const upload = useUploadAvatar()
  const remove = useRemoveAvatar()
  const putTimezone = usePutTimezone()
  const [timezoneError, setTimezoneError] = useState<string | null>(null)
  const [timezoneSaved, setTimezoneSaved] = useState(false)
  const device = deviceTimezone()
  const zoneOptions = timezoneOptions(browserTimezones(), profile.data?.timezone, device)

  const handleTimezoneChange = (event: ChangeEvent<HTMLSelectElement>) => {
    setTimezoneError(null)
    setTimezoneSaved(false)
    const value = event.target.value
    if (value === FOLLOW_DEVICE_VALUE) {
      // Clear the choice first, then send the device zone: the server
      // accepts a device write only once nothing is chosen.
      putTimezone.mutate(FOLLOW_DEVICE_UPDATE, {
        onError: (error) => setTimezoneError(settingsSaveFailureMessage(error)),
        onSuccess: () => {
          setTimezoneSaved(true)
          const update = deviceTimezoneUpdate(device)
          if (update !== null) putTimezone.mutate(update)
        },
      })
      return
    }
    putTimezone.mutate(explicitTimezoneUpdate(value), {
      onError: (error) => setTimezoneError(settingsSaveFailureMessage(error)),
      onSuccess: () => setTimezoneSaved(true),
    })
  }
  const fileInputRef = useRef<HTMLInputElement>(null)
  /** A local object URL shown while a chosen file is uploading, so the
   * picture the reader just picked appears immediately rather than waiting
   * on a round trip and a fresh signed URL. Revoked as soon as the upload
   * settles either way — `profile.data.avatarUrl` takes over from there. */
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  /** A rejected file, from `validateAvatarFile` — never sent to the server. */
  const [validationError, setValidationError] = useState<string | null>(null)
  /** A failed upload or removal, from the server. Kept separate from
   * `validationError` because they answer different questions: one says the
   * file you picked cannot work, the other says the one that could didn't
   * save. */
  const [actionError, setActionError] = useState<string | null>(null)

  const handleChoose = () => {
    setValidationError(null)
    setActionError(null)
    fileInputRef.current?.click()
  }

  const handleFileSelected = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null
    // Reset immediately so choosing the same file again still fires a change
    // event — without this a reader who picks a file, sees it rejected, and
    // picks the identical file again (having genuinely changed nothing about
    // it) would see nothing happen at all.
    event.target.value = ""
    if (!file) return

    const message = validateAvatarFile(file)
    if (message) {
      setValidationError(message)
      return
    }
    setValidationError(null)
    setActionError(null)

    const objectUrl = URL.createObjectURL(file)
    setPreviewUrl(objectUrl)
    upload.mutate(file, {
      onError: (error) => setActionError(settingsSaveFailureMessage(error)),
      onSettled: () => {
        URL.revokeObjectURL(objectUrl)
        setPreviewUrl(null)
      },
    })
  }

  const handleRemove = () => {
    setValidationError(null)
    setActionError(null)
    remove.mutate(undefined, {
      onError: (error) => setActionError(settingsSaveFailureMessage(error)),
    })
  }

  const busy = upload.isPending || remove.isPending

  return (
    <>
      <SettingsSection
        title="Your profile"
        description="Your name and email come from your account. With no name set, Lemely shows the first part of your email."
      >
        {/* No `srHeading`: the page's own `<h1>` (page lane) or the dialog
            title (teacher Settings dialog) sits above this section in every
            query state, so an sr-only heading here would duplicate it. */}
        <QueryState
          query={profile}
          skeleton={<PanelSkeleton />}
          error={{
            heading: "We couldn't load your profile",
            body: settingsLoadFailureMessage,
          }}
        >
          {(data) => {
            const name = data.displayName ?? data.email.split("@")[0]
            return (
              <SettingsCard>
                <SettingsRow
                  label="Profile picture"
                  description="PNG, JPEG or WEBP, up to 5 MB. Shown next to your name."
                  control={
                    <>
                      <Avatar name={name} src={previewUrl ?? data.avatarUrl ?? undefined} size="lg" />
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={handleChoose}
                        loading={upload.isPending}
                        disabled={remove.isPending}
                      >
                        {data.avatarUrl ? "Change" : "Choose a picture"}
                      </Button>
                      {data.avatarUrl ? (
                        <Button
                          type="button"
                          variant="ghost"
                          onClick={handleRemove}
                          loading={remove.isPending}
                          disabled={upload.isPending}
                        >
                          Remove
                        </Button>
                      ) : null}
                    </>
                  }
                  status={
                    <>
                      {/* Adjacent to the control that produced it. */}
                      {validationError ? (
                        <SettingsStatus tone="error">{validationError}</SettingsStatus>
                      ) : null}
                      {actionError ? <SettingsStatus tone="error">{actionError}</SettingsStatus> : null}
                      {upload.isPending ? <SettingsStatus>Uploading your picture…</SettingsStatus> : null}
                    </>
                  }
                />
                <SettingsRow
                  label="Name"
                  control={<span className="truncate text-body-md text-on-surface">{name}</span>}
                />
                <SettingsRow
                  label="Email"
                  control={
                    <span className="truncate text-body-md text-on-surface">{data.email}</span>
                  }
                />
                <PhoneRow phone={data.phone} />
                <SettingsRow
                  label="Role"
                  control={
                    <span className="text-body-md text-on-surface">{roleLabel(data.role)}</span>
                  }
                />
              </SettingsCard>
            )
          }}
        </QueryState>
        {/* `hidden` rather than `sr-only`: this input is never the target
            of a direct interaction, only `fileInputRef.current?.click()`
            above, so the buttons are the whole accessible surface for this
            control and it needs no name or focus stop of its own. */}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="hidden"
          disabled={busy}
          onChange={handleFileSelected}
          data-kit-field="file"
        />
      </SettingsSection>

      <SettingsSection
        title="Time zone"
        description="Quiet hours, streak days and daily reminders follow this. Following your device keeps it right when you travel."
      >
        <SettingsCard>
          <div className="flex flex-col gap-3 px-4 py-4 sm:px-5">
            <Select
              label="Your time zone"
              value={pickerValue(profile.data)}
              onChange={handleTimezoneChange}
              disabled={profile.isPending || putTimezone.isPending}
              state={putTimezone.isPending ? "loading" : undefined}
              error={timezoneError ?? undefined}
              hint={timezoneSaved && !putTimezone.isPending ? "Saved." : undefined}
            >
              <option value={FOLLOW_DEVICE_VALUE}>
                {device ? `Follow this device (${device})` : "Follow this device"}
              </option>
              {zoneOptions.map((zone) => (
                <option key={zone} value={zone}>
                  {zone}
                </option>
              ))}
            </Select>
          </div>
        </SettingsCard>
      </SettingsSection>

      {appearance ? <AppearanceSettingsSection /> : null}
    </>
  )
}

/** The top-level `/settings/profile` route (parent and admin reach this
 * screen only through here — see `SettingsFrame`'s module header for why the
 * lane is role-agnostic). */
export function ProfileSettings() {
  return (
    <SettingsFrame
      title="Profile"
      intro="Your name, email, and the picture other people see next to them."
    >
      <ProfileSettingsSection />
    </SettingsFrame>
  )
}
