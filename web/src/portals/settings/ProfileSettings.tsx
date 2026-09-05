/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useRef, useState, type ChangeEvent } from "react"
import { Avatar } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { PanelSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { validateAvatarFile } from "@/lib/avatarUpload"
import { useProfile, useRemoveAvatar, useUploadAvatar } from "@/lib/hooks/useMeApi"
import {
  settingsLoadFailureMessage,
  settingsSaveFailureMessage,
} from "@/lib/settingsOutcome"
import { SettingsFrame } from "./SettingsFrame"

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
 * The section this screen renders, with no frame around it — mounted inside
 * `PortalSettingsLayout` for the in-portal lane, in addition to the framed
 * `ProfileSettings` below for the top-level `/settings/profile` lane.
 */
export function ProfileSettingsSection() {
  const profile = useProfile()
  const upload = useUploadAvatar()
  const remove = useRemoveAvatar()
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
      <section aria-labelledby="identity-heading" className="flex flex-col gap-4">
        <h2 id="identity-heading" className="text-display-sm text-ink">
          Your profile
        </h2>

        {/* No `srHeading`: the page's own `<h1>` is rendered above this
            section unconditionally, whether by `SettingsFrame` (the
            top-level lane) or `PortalSettingsLayout` (the in-portal one), in
            every query state — an sr-only heading here would duplicate it. */}
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
              <div className="flex items-center gap-3 rounded-lg border border-rule bg-paper-raised p-4 sm:p-5">
                <Avatar name={name} src={data.avatarUrl ?? undefined} size="lg" />
                <div className="min-w-0">
                  <p className="truncate text-body-lg font-medium text-ink">{name}</p>
                  <p className="truncate text-body-sm text-ink-muted">{data.email}</p>
                  <p className="text-body-sm text-ink-faint">{roleLabel(data.role)}</p>
                </div>
              </div>
            )
          }}
        </QueryState>
      </section>

      <section aria-labelledby="picture-heading" className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <h2 id="picture-heading" className="text-display-sm text-ink">
            Profile picture
          </h2>
          <p className="max-w-[65ch] text-body-sm text-ink-muted">
            PNG, JPEG, or WEBP, up to 5 MB. Shown next to your name in the sidebar.
          </p>
        </div>

        <div className="flex flex-col gap-3 rounded-lg border border-rule bg-paper-raised p-4 sm:p-5">
          <div className="flex flex-wrap items-center gap-4">
            <Avatar
              name={profile.data ? (profile.data.displayName ?? profile.data.email.split("@")[0]) : undefined}
              src={previewUrl ?? profile.data?.avatarUrl ?? undefined}
              size="lg"
            />
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="secondary"
                onClick={handleChoose}
                loading={upload.isPending}
                disabled={remove.isPending}
              >
                {profile.data?.avatarUrl ? "Change picture" : "Choose a picture"}
              </Button>
              {profile.data?.avatarUrl ? (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={handleRemove}
                  loading={remove.isPending}
                  disabled={upload.isPending}
                >
                  Remove picture
                </Button>
              ) : null}
            </div>
            {/* `hidden` rather than `sr-only`: this input is never the target
                of a direct interaction, only `fileInputRef.current?.click()`
                above — the two `Button`s are the whole accessible surface for
                this control, so it needs no name or focus stop of its own. */}
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              disabled={busy}
              onChange={handleFileSelected}
            />
          </div>

          {/* Adjacent to the control that produced it, same as the other two
              settings screens' row-level notices. */}
          {validationError ? (
            <p role="status" className="text-body-sm text-err">
              {validationError}
            </p>
          ) : null}
          {actionError ? (
            <p role="status" className="text-body-sm text-err">
              {actionError}
            </p>
          ) : null}
        </div>
      </section>
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
