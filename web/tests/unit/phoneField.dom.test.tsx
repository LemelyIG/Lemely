// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h, useState } from "react"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { fakeMutation } from "./support/billingRender"

/*
 * The phone field, its save form and the banner, in a real DOM (UD-11). The hooks are replaced
 * with fakes: what is pinned here is what the person sees and what the form sends, not the wire.
 */

const s = vi.hoisted(() => ({ put: null as unknown, profile: null as unknown }))
vi.mock("@/lib/hooks/useMeApi", () => ({
  usePutPhone: () => s.put,
  useProfile: () => s.profile,
}))

import { PhoneInput } from "@/components/ui/phone-input"
import { PhoneEntryForm } from "@/components/phone-entry-form"
import { PhoneBanner, PhoneBannerView } from "@/components/ui/phone-banner"

function Controlled({ onBlur }: { onBlur?: (v: string) => void }) {
  const [value, setValue] = useState("")
  return h(PhoneInput, { value, onValueChange: setValue, onBlur })
}

const phone422 = (code: string) => new ApiError(422, "422", { code, message: "server wording" })

describe("PhoneInput", () => {
  it("is a labelled telephone field with the keypad and autofill hints", () => {
    render(h(Controlled))
    const field = screen.getByLabelText("Phone number")
    expect(field.getAttribute("type")).toBe("tel")
    expect(field.getAttribute("inputmode")).toBe("tel")
    expect(field.getAttribute("autocomplete")).toBe("tel")
  })

  it("states the default country and the exception in a hint tied to the field", () => {
    render(h(Controlled))
    const field = screen.getByLabelText("Phone number")
    const hint = screen.getByText(/Egypt \(\+20\) is assumed/)
    expect(hint.textContent).toMatch(/start with \+ and the country code/)
    expect(field.getAttribute("aria-describedby")).toBe(hint.id)
  })

  it("shows +20 in front, and takes it away when the person types their own code", async () => {
    const user = userEvent.setup()
    render(h(Controlled))
    expect(screen.getByText("+20")).toBeTruthy()
    await user.type(screen.getByLabelText("Phone number"), "+44 7700 900123")
    expect(screen.queryByText("+20")).toBeNull()
  })

  it("drops a leading national zero on blur and hands the tidied value to onBlur", async () => {
    const user = userEvent.setup()
    const onBlur = vi.fn()
    render(h(Controlled, { onBlur }))
    const field = screen.getByLabelText("Phone number") as HTMLInputElement
    await user.type(field, "01012345678")
    await user.tab()
    expect(field.value).toBe("1012345678")
    expect(onBlur).toHaveBeenCalledWith("1012345678")
  })
})

describe("PhoneEntryForm", () => {
  beforeEach(() => {
    s.put = fakeMutation()
  })

  it("refuses an empty number on the field without calling the server", async () => {
    const user = userEvent.setup()
    render(h(PhoneEntryForm))
    await user.click(screen.getByRole("button", { name: "Save number" }))
    const field = screen.getByLabelText("Phone number")
    expect(screen.getByText("Enter a phone number.")).toBeTruthy()
    expect(field.getAttribute("aria-invalid")).toBe("true")
    expect((s.put as ReturnType<typeof fakeMutation>).mutate).not.toHaveBeenCalled()
  })

  it("refuses an obvious non-number, then clears the message when the person edits", async () => {
    const user = userEvent.setup()
    render(h(PhoneEntryForm))
    await user.type(screen.getByLabelText("Phone number"), "call me")
    await user.click(screen.getByRole("button", { name: "Save number" }))
    expect(screen.getByText(/Enter a valid phone number/)).toBeTruthy()
    await user.type(screen.getByLabelText("Phone number"), "1")
    expect(screen.queryByText(/Enter a valid phone number/)).toBeNull()
  })

  it("sends the number as typed, trimmed, and reports the stored one through onSaved", async () => {
    const user = userEvent.setup()
    const onSaved = vi.fn()
    const put = fakeMutation()
    put.mutate.mockImplementation((_phone: string, opts?: { onSuccess?: (s: unknown) => void }) =>
      opts?.onSuccess?.({ phone: "+201012345678", phoneMissing: false }),
    )
    s.put = put
    render(h(PhoneEntryForm, { onSaved, submitLabel: "Save and continue" }))
    await user.type(screen.getByLabelText("Phone number"), "+20 101 234 5678 ")
    await user.click(screen.getByRole("button", { name: "Save and continue" }))
    expect(put.mutate).toHaveBeenCalledTimes(1)
    expect(put.mutate.mock.calls[0][0]).toBe("+20 101 234 5678")
    expect(onSaved).toHaveBeenCalledWith("+201012345678")
  })

  it.each([
    ["phone_required", "Enter a phone number."],
    ["phone_invalid", "Enter a valid phone number, for example 01012345678 or +201012345678."],
  ])("puts the server's %s on the field, in our words, and returns focus to it", async (code, sentence) => {
    const user = userEvent.setup()
    const put = fakeMutation()
    put.mutate.mockImplementation((_phone: string, opts?: { onError?: (e: unknown) => void }) =>
      opts?.onError?.(phone422(code)),
    )
    s.put = put
    render(h(PhoneEntryForm))
    await user.type(screen.getByLabelText("Phone number"), "01012345678")
    await user.click(screen.getByRole("button", { name: "Save number" }))
    expect(screen.getByText(sentence)).toBeTruthy()
    expect(screen.queryByText("server wording")).toBeNull()
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("Phone number")))
  })

  it("reports a failure that retyping cannot fix under the button, not on the field", async () => {
    const user = userEvent.setup()
    const put = fakeMutation()
    put.mutate.mockImplementation((_phone: string, opts?: { onError?: (e: unknown) => void }) =>
      opts?.onError?.(new ApiError(0, "offline")),
    )
    s.put = put
    render(h(PhoneEntryForm))
    await user.type(screen.getByLabelText("Phone number"), "01012345678")
    await user.click(screen.getByRole("button", { name: "Save number" }))
    expect(screen.getByRole("alert").textContent).toMatch(/connection|offline|network/i)
    expect(screen.getByLabelText("Phone number").getAttribute("aria-invalid")).toBeNull()
  })

  it("disables the field and shows the button busy while saving", () => {
    s.put = fakeMutation({ isPending: true })
    render(h(PhoneEntryForm))
    expect((screen.getByLabelText("Phone number") as HTMLInputElement).disabled).toBe(true)
    expect(screen.getByRole("button", { name: "Save number" }).getAttribute("aria-busy")).toBe("true")
  })

  it("can keep the label for assistive technology only, when the row already shows it", () => {
    render(h(PhoneEntryForm, { hideLabel: true }))
    const label = screen.getByText("Phone number", { selector: "label" })
    expect(label.className).toContain("sr-only")
    expect(screen.getByLabelText("Phone number")).toBeTruthy()
  })

  it("offers Cancel only when asked to", async () => {
    const user = userEvent.setup()
    const onCancel = vi.fn()
    const { rerender } = render(h(PhoneEntryForm))
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull()
    rerender(h(PhoneEntryForm, { onCancel }))
    await user.click(screen.getByRole("button", { name: "Cancel" }))
    expect(onCancel).toHaveBeenCalled()
  })
})

describe("PhoneBanner", () => {
  const profile = (over: Record<string, unknown>) => ({ data: { role: "student", phoneMissing: true, phone: null, ...over } })
  const open = (path = "/student/overview") => render(h(MemoryRouter, { initialEntries: [path] }, h(PhoneBanner)))

  beforeEach(() => {
    window.sessionStorage.clear()
  })

  it("says what the number is for and links to the card for this role", () => {
    s.profile = profile({})
    open()
    expect(screen.getByRole("status").textContent).toMatch(/Add your phone number\./)
    expect(screen.getByRole("status").textContent).toMatch(/pay for a plan or credits/)
    expect(screen.getByRole("link", { name: "Add phone number" }).getAttribute("href")).toBe("/student/settings")
  })

  it("links a parent to the top-level profile screen", () => {
    s.profile = profile({ role: "parent" })
    open("/parent")
    expect(screen.getByRole("link", { name: "Add phone number" }).getAttribute("href")).toBe("/settings/profile")
  })

  it("renders nothing, and no margin, when the number is present or the profile is unknown", () => {
    s.profile = profile({ phoneMissing: false, phone: "+201012345678" })
    const first = open()
    expect(first.container.innerHTML).toBe("")
    first.unmount()
    s.profile = { data: undefined }
    expect(open().container.innerHTML).toBe("")
  })

  it("steps aside on the profile screen", () => {
    s.profile = profile({})
    expect(open("/student/settings").container.innerHTML).toBe("")
  })

  it("can be dismissed for the visit, and stays dismissed on remount", async () => {
    const user = userEvent.setup()
    s.profile = profile({})
    const first = open()
    await user.click(screen.getByRole("button", { name: "Dismiss the phone reminder" }))
    expect(screen.queryByRole("status")).toBeNull()
    first.unmount()
    expect(open().container.innerHTML).toBe("")
  })

  it("the view shows no dismiss control when it is given no handler", () => {
    render(h(MemoryRouter, null, h(PhoneBannerView, { to: "/settings/profile" })))
    expect(screen.queryByRole("button")).toBeNull()
  })
})
