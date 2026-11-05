/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useState } from "react"
import { Link } from "react-router-dom"
import { Button, buttonVariants } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { ConfirmModal } from "@/components/ui/confirm-modal"
import { PanelSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { useAuth } from "@/lib/auth/AuthContext"
import { resetFailureMessage } from "@/lib/authOutcome"
import { useDevices, useRevokeDevice } from "@/lib/hooks/useDeviceApi"
import { useProfile } from "@/lib/hooks/useMeApi"
import { settingsLoadFailureMessage, settingsSaveFailureMessage } from "@/lib/settingsOutcome"
import { cn } from "@/lib/utils"
import { DeviceSettingsSection } from "./DeviceSettings"
import { SettingsCard, SettingsRow, SettingsSection, SettingsStatus } from "./SettingsRows"
import { signOutOrder } from "./signOutEverywhere"

/*
 * The teacher dialog's "Account and devices" tab: sign-in details, the
 * device list, and sign out everywhere, in that order, with the one
 * destructive action last and set apart.
 *
 * Everything here is backed by an endpoint that exists today:
 *   - email and verification state: `GET /me/profile`;
 *   - password: there is no signed-in "change password" route, so the row
 *     sends the same reset link the sign-in screen does
 *     (`POST /auth/password-reset/request`) to the account's own address;
 *   - devices: `GET /me/devices` and `DELETE /me/devices/{id}`;
 *   - sign out everywhere: no bulk endpoint exists, so it revokes each
 *     device through the per-device route, other devices first and this one
 *     last (`signOutOrder`), then clears the local session.
 * There is no delete-account or data-export endpoint, so neither appears.
 */

function AccountDetailsSection() {
  const profile = useProfile()
  const { requestPasswordReset } = useAuth()
  const [resetSentTo, setResetSentTo] = useState<string | null>(null)
  const [resetError, setResetError] = useState<string | null>(null)

  return (
    <SettingsSection
      title="Sign-in details"
      description="The email you sign in with, and how to change your password."
    >
      <QueryState
        query={profile}
        skeleton={<PanelSkeleton />}
        error={{ heading: "We couldn't load your account", body: settingsLoadFailureMessage }}
      >
        {(data) => (
          <SettingsCard>
            <SettingsRow
              label={
                <span className="flex flex-wrap items-center gap-2">
                  Email
                  {data.emailVerified ? <Chip>Verified</Chip> : <Chip>Not verified</Chip>}
                </span>
              }
              description={
                <span className="break-all text-body-sm text-on-surface">{data.email}</span>
              }
              control={
                data.emailVerified ? null : (
                  <Link to="/verify-email" className={cn(buttonVariants({ variant: "secondary" }))}>
                    Verify your email
                  </Link>
                )
              }
            />
            <SettingsRow
              label="Password"
              description="We email you a link to set a new one."
              control={
                <Button
                  type="button"
                  variant="secondary"
                  loading={requestPasswordReset.isPending}
                  onClick={() => {
                    setResetError(null)
                    setResetSentTo(null)
                    requestPasswordReset.mutate(
                      { email: data.email },
                      {
                        onSuccess: () => setResetSentTo(data.email),
                        onError: (error) => setResetError(resetFailureMessage(error)),
                      },
                    )
                  }}
                >
                  Send reset link
                </Button>
              }
              status={
                resetError ? (
                  <SettingsStatus tone="error">{resetError}</SettingsStatus>
                ) : resetSentTo ? (
                  <SettingsStatus>Sent. Check {resetSentTo} for the link.</SettingsStatus>
                ) : null
              }
            />
          </SettingsCard>
        )}
      </QueryState>
    </SettingsSection>
  )
}

function SignOutEverywhereSection() {
  const { logout } = useAuth()
  const devices = useDevices()
  const revoke = useRevokeDevice()
  const [confirming, setConfirming] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const signOutEverywhere = async () => {
    const list = devices.data?.devices
    if (!list) return
    setPending(true)
    setError(null)
    try {
      for (const deviceId of signOutOrder(list)) {
        await revoke.mutateAsync(deviceId)
      }
      // This device's token is revoked by now (or it held no listed
      // session); either way the local session goes too.
      logout()
    } catch (err) {
      setError(settingsSaveFailureMessage(err))
      setPending(false)
      setConfirming(false)
    }
  }

  return (
    <SettingsSection
      tone="danger"
      title="Sign out everywhere"
      description="For when you think someone else is using your account."
    >
      <SettingsCard tone="danger">
        <SettingsRow
          label="Sign out of every device"
          description="Ends every session on this account, this one included. You sign in again on each device you use."
          control={
            <Button
              type="button"
              variant="secondary"
              className="border-error/40 text-error transition-colors hover:border-error hover:bg-error-container hover:text-on-error-container"
              disabled={!devices.data || pending}
              onClick={() => setConfirming(true)}
            >
              Sign out everywhere
            </Button>
          }
          status={error ? <SettingsStatus tone="error">{error}</SettingsStatus> : null}
        />
      </SettingsCard>

      <ConfirmModal
        open={confirming}
        title="Sign out everywhere?"
        description="Every device signed in to this account will be signed out, including this one."
        // Overridden: the default claims the action cannot be undone, and
        // signing in again undoes it. What it costs is every open session.
        consequence="You will need to sign in again on each device you use."
        confirmLabel="Sign out everywhere"
        pendingLabel="Signing out…"
        cancelLabel="Stay signed in"
        pending={pending}
        onConfirm={() => void signOutEverywhere()}
        onCancel={() => setConfirming(false)}
      />
    </SettingsSection>
  )
}

export function AccountSettingsSection() {
  return (
    <>
      <AccountDetailsSection />
      <DeviceSettingsSection />
      <SignOutEverywhereSection />
    </>
  )
}
