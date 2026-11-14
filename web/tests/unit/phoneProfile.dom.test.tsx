// @vitest-environment jsdom
import "./support/dom-setup"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fakeMutation, okQuery } from "./support/billingRender"

/*
 * The mobile number row on the profile card (UD-11), in a real DOM. The profile is a tiny external
 * store, so a save that updates it re-renders the row the way the real query cache does.
 */

const s = vi.hoisted(() => {
  const listeners = new Set<() => void>()
  return {
    profile: null as unknown,
    put: null as unknown,
    listeners,
    subscribe: (l: () => void) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    set(next: unknown) {
      s.profile = next
      listeners.forEach((l) => l())
    },
  }
})

vi.mock("@/lib/hooks/useMeApi", async () => {
  const { useSyncExternalStore } = await import("react")
  return {
    useProfile: () => useSyncExternalStore(s.subscribe, () => s.profile),
    useUploadAvatar: () => fakeMutation(),
    useRemoveAvatar: () => fakeMutation(),
    usePutTimezone: () => fakeMutation(),
    usePutPhone: () => s.put,
  }
})

import { ProfileSettingsSection } from "@/portals/settings/ProfileSettings"

const profile = (over: Record<string, unknown> = {}) =>
  okQuery({
    displayName: "Amina Farouk",
    email: "amina@example.com",
    role: "student",
    emailVerified: true,
    avatarUrl: null,
    timezone: "Africa/Cairo",
    timezoneIsExplicit: true,
    phone: null,
    phoneMissing: true,
    ...over,
  })

// `ProfileSettingsSection` types its props as an optional object, which `createElement` cannot infer.
const openSection = () => render(<ProfileSettingsSection appearance={false} />)

beforeEach(() => {
  s.profile = profile()
  s.put = fakeMutation()
})

describe("profile mobile number row", () => {
  it("asks for a mobile number when none is usable, and never claims there is one 'on file'", () => {
    openSection()
    expect(screen.getByText("Mobile number", { selector: "div" })).toBeTruthy()
    expect(screen.getByText(/Add a mobile number\./)).toBeTruthy()
    // A landline stored before the mobile-only rule reads as missing too; "None on file" would be false.
    expect(screen.queryByText(/None on file/)).toBeNull()
    expect(screen.queryByText(/phone number/i)).toBeNull()
    expect(screen.getByLabelText("Mobile number")).toBeTruthy()
  })

  it("shows the stored number with a Change button, and opens the form only on request", async () => {
    const user = userEvent.setup()
    s.profile = profile({ phone: "+201012345678", phoneMissing: false })
    openSection()
    expect(screen.getByText("+201012345678")).toBeTruthy()
    expect(screen.queryByLabelText("Mobile number")).toBeNull()
    await user.click(screen.getByRole("button", { name: "Change" }))
    expect(screen.getByLabelText("Mobile number")).toBeTruthy()
  })

  it("returns focus to Change after Cancel, instead of dropping it to the page", async () => {
    const user = userEvent.setup()
    s.profile = profile({ phone: "+201012345678", phoneMissing: false })
    openSection()
    await user.click(screen.getByRole("button", { name: "Change" }))
    await user.click(screen.getByRole("button", { name: "Cancel" }))
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Change" })))
  })

  it("returns focus to Change after a save, and says Saved.", async () => {
    const user = userEvent.setup()
    const put = fakeMutation()
    put.mutate.mockImplementation((phone: string, opts?: { onSuccess?: (st: unknown) => void }) => {
      // The hook merges the stored number into the cached profile before the caller's onSuccess runs.
      s.set(profile({ phone: "+201012345678", phoneMissing: false }))
      opts?.onSuccess?.({ phone: "+201012345678", phoneMissing: false })
      expect(phone).toBe("1012345678")
    })
    s.put = put
    openSection()
    await user.type(screen.getByLabelText("Mobile number"), "01012345678")
    await user.click(screen.getByRole("button", { name: "Save number" }))
    expect(await screen.findByText("Saved.")).toBeTruthy()
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Change" })))
  })
})
