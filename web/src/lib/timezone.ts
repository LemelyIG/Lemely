/*
 * Per-user time zones (push-delivery spec §3), the page half.
 *
 * `PUT /api/me/timezone` takes one of three bodies and the server owns what
 * each means: an explicit write is the user's choice and wins; a device write
 * (`explicit: false` with a zone) is stored only while nothing was chosen; a
 * null zone with `explicit: false` clears the choice so the device is followed
 * again. This module builds those bodies and nothing else, so the one thing the
 * client can get wrong — which flag it sends — is pinned by a unit test rather
 * than discovered by a reader whose deliberate choice got undone on a plane.
 *
 * Nothing here touches `Intl` directly except `deviceTimezone`, which takes the
 * resolver as a parameter for the reason every `lib/*.ts` module does: the web
 * runner is `environment: "node"` and a global reached for inside a function
 * could only be checked by reading its source.
 */

import type { TimezoneState, TimezoneUpdate } from "@/lib/meTypes"

/** The picker's value for "follow this device", and the one value the
 * `<select>` has that is not an IANA name. */
export const FOLLOW_DEVICE_VALUE = ""

/** "Follow this device": clears an earlier choice. The caller sends the device
 * zone right after, which the server then accepts. */
export const FOLLOW_DEVICE_UPDATE: TimezoneUpdate = { timezone: null, explicit: false }

/** The device's IANA zone, or null when the browser reports none. Wrapped:
 * some embedded engines throw from `Intl.DateTimeFormat()`. */
export function deviceTimezone(
  resolve: () => { timeZone?: string } = () => Intl.DateTimeFormat().resolvedOptions(),
): string | null {
  try {
    const zone = resolve().timeZone
    return typeof zone === "string" && zone.trim() !== "" ? zone : null
  } catch {
    return null
  }
}

/** The app-boot write. Null when there is no zone to send; the server's rule
 * (stored only while nothing was chosen) is not repeated here on purpose. */
export function deviceTimezoneUpdate(zone: string | null): TimezoneUpdate | null {
  if (zone === null || zone.trim() === "") return null
  return { timezone: zone, explicit: false }
}

/** The settings picker's write: a choice, which wins over the device. */
export function explicitTimezoneUpdate(zone: string): TimezoneUpdate {
  return { timezone: zone, explicit: true }
}

/** What the picker shows: the chosen zone, or "follow this device" for both a
 * device-sourced zone and an unset one. A device-sourced name is deliberately
 * not shown as if it were chosen — that is the state the server will happily
 * overwrite on the next boot, and the control should say so. */
export function pickerValue(profile: TimezoneState | undefined): string {
  if (profile === undefined || !profile.timezoneIsExplicit || profile.timezone === null) {
    return FOLLOW_DEVICE_VALUE
  }
  return profile.timezone
}

/** The `<select>` options: the browser's list plus any zone that has to be
 * representable even if the browser does not list it (the stored one, the
 * device's). Sorted so the list is scannable; deduped so a zone in both sets
 * appears once. */
export function timezoneOptions(
  supported: readonly string[],
  ...extra: (string | null | undefined)[]
): string[] {
  const names = new Set<string>(supported)
  for (const zone of extra) {
    if (typeof zone === "string" && zone.trim() !== "") names.add(zone)
  }
  return [...names].sort((a, b) => a.localeCompare(b))
}

/** The browser's zone list, or an empty list where `Intl.supportedValuesOf`
 * is missing; `timezoneOptions` adds the zones that must be present anyway. */
export function browserTimezones(): string[] {
  try {
    return typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : []
  } catch {
    return []
  }
}
