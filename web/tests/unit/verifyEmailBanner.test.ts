import { describe, expect, it } from "vitest"
import {
  CORRECTION_PATH,
  verifyEmailBannerState,
  type VerifyEmailBannerState,
} from "@/lib/verifyEmailBanner"

/*
 * Every rule about when the verify-email banner appears. It lives in a pure
 * function rather than in the component because the web runner is
 * `environment: "node"` with no jsdom and collects only `.test.ts`, so a rule
 * inside a component could only be checked by reading its source.
 */

function state(
  over: Partial<Parameters<typeof verifyEmailBannerState>[0]> = {},
): VerifyEmailBannerState {
  return verifyEmailBannerState({
    emailVerified: false,
    pathname: "/student/overview",
    dismissed: false,
    ...over,
  })
}

describe("verifyEmailBannerState", () => {
  it("shows a dismissible banner to an unverified reader", () => {
    expect(state()).toBe("dismissible")
  })

  it("shows nothing to a verified reader", () => {
    expect(state({ emailVerified: true })).toBe("hidden")
  })

  it("shows nothing while the profile is still unknown", () => {
    // `useProfile()` pending, or errored. A nag that flashes at someone whose
    // profile has not loaded accuses them of something the app cannot yet
    // know, which is worse than saying nothing.
    expect(state({ emailVerified: undefined })).toBe("hidden")
  })

  it("stays hidden once dismissed this session", () => {
    expect(state({ dismissed: true })).toBe("hidden")
  })

  it("pins the banner on the correction screen", () => {
    expect(state({ pathname: CORRECTION_PATH })).toBe("pinned")
  })

  it("ignores an earlier dismissal on the correction screen", () => {
    // The one screen the gate actually blocks. A dismissal made on the
    // overview must not hide the reason the marking button is disabled here.
    expect(state({ pathname: CORRECTION_PATH, dismissed: true })).toBe("pinned")
  })

  it("does not pin for a verified reader on the correction screen", () => {
    expect(state({ pathname: CORRECTION_PATH, emailVerified: true })).toBe("hidden")
  })

  it("does not pin while the profile is unknown on the correction screen", () => {
    expect(state({ pathname: CORRECTION_PATH, emailVerified: undefined })).toBe("hidden")
  })

  it("does not pin on a path that merely starts with the correction path", () => {
    // A future `/student/correction-history` must not inherit the pinned
    // behaviour by accident.
    expect(state({ pathname: "/student/correcting" })).toBe("dismissible")
    expect(state({ pathname: `${CORRECTION_PATH}/history` })).toBe("dismissible")
  })
})
