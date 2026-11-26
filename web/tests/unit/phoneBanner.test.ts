import { describe, expect, it } from "vitest"
import {
  PHONE_BANNER_DISMISS_KEY,
  isProfileSettingsPath,
  phoneBannerState,
  profileSettingsPath,
  readPhoneBannerDismissed,
  writePhoneBannerDismissed,
} from "@/lib/phoneBanner"

/*
 * When the phone banner shows. Modelled on `verifyEmailBanner.test.ts`: a pure function, because
 * the web runner has no jsdom for the node-environment suite.
 */

const state = (over: Partial<Parameters<typeof phoneBannerState>[0]> = {}) =>
  phoneBannerState({ phoneMissing: true, pathname: "/student/overview", dismissed: false, ...over })

describe("phoneBannerState", () => {
  it("shows a dismissible banner when the profile says the phone is missing", () => {
    expect(state()).toBe("dismissible")
  })
  it("shows nothing once there is a number", () => {
    expect(state({ phoneMissing: false })).toBe("hidden")
  })
  it("shows nothing while the profile is unknown (pending or errored)", () => {
    expect(state({ phoneMissing: undefined })).toBe("hidden")
  })
  it("stays hidden once dismissed this session", () => {
    expect(state({ dismissed: true })).toBe("hidden")
  })
  it("is never pinned: nothing is locked for want of a phone, so it is always dismissible", () => {
    for (const pathname of ["/student/correct", "/student/placement/0580", "/billing", "/student/billing/plans"]) {
      expect(state({ pathname })).toBe("dismissible")
    }
  })
  it("steps aside on the profile screen, where the card is the prompt", () => {
    for (const pathname of ["/student/settings", "/student/settings/", "/teacher/settings", "/settings/profile"]) {
      expect(state({ pathname }), pathname).toBe("hidden")
    }
  })
  it("does not step aside on sibling settings tabs", () => {
    expect(state({ pathname: "/student/settings/notifications" })).toBe("dismissible")
    expect(state({ pathname: "/settings/devices" })).toBe("dismissible")
  })
})

describe("profile settings paths", () => {
  it("links each role to the screen that actually renders the card, with no redirect hop", () => {
    expect(profileSettingsPath("student")).toBe("/student/settings")
    expect(profileSettingsPath("teacher")).toBe("/teacher/settings")
    for (const role of ["parent", "school_admin", "platform_admin", undefined]) {
      expect(profileSettingsPath(role)).toBe("/settings/profile")
    }
  })
  it("agrees with isProfileSettingsPath", () => {
    for (const role of ["student", "teacher", "parent", "school_admin", "platform_admin"]) {
      expect(isProfileSettingsPath(profileSettingsPath(role))).toBe(true)
    }
  })
})

describe("dismissal storage", () => {
  const fake = () => {
    const map = new Map<string, string>()
    return { map, getItem: (k: string) => map.get(k) ?? null, setItem: (k: string, v: string) => void map.set(k, v) }
  }
  it("round-trips, under a key of its own so it never reads the verify-email dismissal", () => {
    const storage = fake()
    expect(readPhoneBannerDismissed(storage)).toBe(false)
    writePhoneBannerDismissed(storage)
    expect(readPhoneBannerDismissed(storage)).toBe(true)
    expect(PHONE_BANNER_DISMISS_KEY).not.toContain("verify-email")
    storage.map.clear()
    storage.map.set("lemely:verify-email-banner-dismissed", "1")
    expect(readPhoneBannerDismissed(storage)).toBe(false)
  })
  it("treats any other stored value as not dismissed", () => {
    const storage = fake()
    storage.map.set(PHONE_BANNER_DISMISS_KEY, "true")
    expect(readPhoneBannerDismissed(storage)).toBe(false)
  })
  it("never throws: no storage, or storage that refuses", () => {
    expect(readPhoneBannerDismissed(undefined)).toBe(false)
    expect(() => writePhoneBannerDismissed(undefined)).not.toThrow()
    const hostile = {
      getItem: () => {
        throw new Error("denied")
      },
      setItem: () => {
        throw new Error("denied")
      },
    }
    expect(readPhoneBannerDismissed(hostile)).toBe(false)
    expect(() => writePhoneBannerDismissed(hostile)).not.toThrow()
  })
})
