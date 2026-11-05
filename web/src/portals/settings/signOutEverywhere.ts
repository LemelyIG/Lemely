/*
 * The order "Sign out everywhere" revokes devices in.
 *
 * There is no bulk endpoint, so each device goes through
 * `DELETE /me/devices/{id}`. This device goes last: revoking it first would
 * invalidate the token every later request needs, leaving the other devices
 * signed in behind a screen that can no longer reach the server.
 */
export function signOutOrder(devices: readonly { deviceId: string; isCurrent: boolean }[]): string[] {
  const others = devices.filter((device) => !device.isCurrent).map((device) => device.deviceId)
  const current = devices.filter((device) => device.isCurrent).map((device) => device.deviceId)
  return [...others, ...current]
}
