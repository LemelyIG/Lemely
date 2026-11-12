import { describe, expect, it } from "vitest"
import {
  FOLLOW_DEVICE_UPDATE,
  deviceTimezone,
  deviceTimezoneUpdate,
  explicitTimezoneUpdate,
  pickerValue,
  timezoneOptions,
} from "@/lib/timezone"

/*
 * Per-user time zones (push-delivery spec §3), the page half. The server owns
 * the rule that a device write never overwrites a choice; what the client has
 * to get right is which of the three bodies it sends, because the wrong flag
 * either lets a plane undo a choice or stops a choice from ever being made.
 */

describe("explicitTimezoneUpdate", () => {
  it("marks a picked zone as the user's choice", () => {
    expect(explicitTimezoneUpdate("America/Los_Angeles")).toEqual({
      timezone: "America/Los_Angeles",
      explicit: true,
    })
  })
})

describe("FOLLOW_DEVICE_UPDATE", () => {
  it("clears the choice with a null zone and explicit false", () => {
    expect(FOLLOW_DEVICE_UPDATE).toEqual({ timezone: null, explicit: false })
  })
})

describe("deviceTimezoneUpdate", () => {
  it("sends the device zone as a non-explicit write", () => {
    expect(deviceTimezoneUpdate("Europe/Paris")).toEqual({
      timezone: "Europe/Paris",
      explicit: false,
    })
  })

  it("sends nothing when the device has no zone to report", () => {
    expect(deviceTimezoneUpdate(null)).toBeNull()
    expect(deviceTimezoneUpdate("")).toBeNull()
  })
})

describe("deviceTimezone", () => {
  it("reads Intl's resolved zone", () => {
    expect(deviceTimezone(() => ({ timeZone: "Asia/Tokyo" }))).toBe("Asia/Tokyo")
  })

  it("is null when Intl reports none, or throws", () => {
    expect(deviceTimezone(() => ({}))).toBeNull()
    expect(
      deviceTimezone(() => {
        throw new RangeError("no Intl")
      }),
    ).toBeNull()
  })
})

describe("pickerValue", () => {
  it("shows the chosen zone when one was chosen", () => {
    expect(pickerValue({ timezone: "Africa/Cairo", timezoneIsExplicit: true })).toBe("Africa/Cairo")
  })

  it("shows follow-this-device when the zone came from the device or is unset", () => {
    expect(pickerValue({ timezone: "Africa/Cairo", timezoneIsExplicit: false })).toBe("")
    expect(pickerValue({ timezone: null, timezoneIsExplicit: false })).toBe("")
    expect(pickerValue(undefined)).toBe("")
  })
})

describe("timezoneOptions", () => {
  it("includes the current and device zones even when the browser does not list them", () => {
    expect(timezoneOptions(["Africa/Cairo"], "Mars/Base", null, undefined)).toEqual([
      "Africa/Cairo",
      "Mars/Base",
    ])
  })

  it("sorts and dedupes", () => {
    expect(
      timezoneOptions(["Europe/Paris", "Africa/Cairo", "Europe/Paris"], "Africa/Cairo"),
    ).toEqual(["Africa/Cairo", "Europe/Paris"])
  })
})
