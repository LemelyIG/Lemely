/*
 * Wire types for the device surfaces G-10 and G-11, mirroring
 * `lemely/web/schemas_devices.py` field for field.
 *
 * There is no `location` field here and there must never be one: the backend
 * stores no IP address and this build has no geo-IP source, so a location could
 * only be guessed — and it is the field a user would base "sign this one out" on
 * (D5.12 §5, UI spec §1.4).
 */

export interface Device {
  deviceId: string
  label: string | null
  /** Raw `User-Agent` captured at login; `null` for a session registered without one. */
  userAgent: string | null
  /** ISO-8601 timestamp of the last request seen from this device. */
  lastActiveAt: string
  isCurrent: boolean
}

export interface DeviceList {
  devices: Device[]
  maxDevices: number
}

export interface DeviceRevoked {
  removed: boolean
  /** True when the device just signed out was the caller's own — stop using the token. */
  wasCurrent: boolean
}

/**
 * The body of the 409 a login answers when it would consume a fourth device
 * slot (D5.12). It arrives as `ApiError.detail`, not as a resolved response —
 * a challenge is a refusal, and nothing is minted or evicted until the user
 * confirms.
 */
export interface DeviceLimitChallenge {
  reason: "device_limit_reached"
  maxDevices: number
  devices: Device[]
  /** The device a confirmed retry will sign out — named by the server, never re-derived here. */
  oldestDeviceId: string
}

/** Narrow an `ApiError.detail` onto the challenge shape. */
export function isDeviceLimitChallenge(
  detail: unknown,
): detail is DeviceLimitChallenge {
  if (typeof detail !== "object" || detail === null) return false
  const candidate = detail as Partial<DeviceLimitChallenge>
  return (
    candidate.reason === "device_limit_reached" &&
    Array.isArray(candidate.devices)
  )
}
