// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h } from "react"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { fakeMutation } from "./support/billingRender"

/*
 * The parent's last sign-up step, with its mobile number (UD-11), in a real DOM. The two code steps
 * before it are answered by fakes that succeed at once, so the test starts where the phone field is.
 */

const s = vi.hoisted(() => ({ parentSignup: null as unknown, request: null as unknown, verify: null as unknown }))
vi.mock("@/lib/auth/AuthContext", () => ({ useAuth: () => ({ parentSignup: s.parentSignup }) }))
vi.mock("@/lib/hooks/useParentSignupApi", () => ({
  useRequestParentCode: () => s.request,
  useVerifyParentCode: () => s.verify,
}))

import { SignupParent } from "@/portals/auth/SignupParent"

const phone422 = (code: string) => new ApiError(422, "422", { code, message: "server wording" })

async function reachFinalStep(user: ReturnType<typeof userEvent.setup>) {
  render(h(MemoryRouter, { initialEntries: ["/signup/parent?code=ABCDEFGHJK"] }, h(SignupParent)))
  await user.type(screen.getByLabelText("Email"), "parent@example.com")
  await user.click(screen.getByRole("button", { name: "Send code" }))
  await user.click(await screen.findByLabelText("Digit 1 of 6"))
  await user.keyboard("123456")
  await screen.findByRole("heading", { name: "Finish your account" })
}

beforeEach(() => {
  s.parentSignup = fakeMutation()
  const request = fakeMutation()
  request.mutate.mockImplementation((_b: unknown, o?: { onSuccess?: (r: unknown) => void }) => o?.onSuccess?.({ status: "sent", devCode: null }))
  s.request = request
  const verify = fakeMutation()
  verify.mutate.mockImplementation((_b: unknown, o?: { onSuccess?: (r: unknown) => void }) => o?.onSuccess?.({ proofToken: "proof-1" }))
  s.verify = verify
})

describe("parent sign-up, final step", () => {
  it("asks for the mobile number before the password, under a heading that fits both", async () => {
    await reachFinalStep(userEvent.setup())
    expect(screen.getByText(/Add your mobile number and choose a password/)).toBeTruthy()
    const labels = screen.getAllByText(/^(Mobile number|Password)$/).map((el) => el.textContent)
    expect(labels).toEqual(["Mobile number", "Password"])
    const field = screen.getByLabelText("Mobile number")
    expect(field.getAttribute("type")).toBe("tel")
    expect(field.getAttribute("autocomplete")).toBe("tel")
    expect(screen.queryByText("Set a password")).toBeNull()
  })

  it("will not submit without a number, and says so on the field", async () => {
    const user = userEvent.setup()
    await reachFinalStep(user)
    await user.type(screen.getByLabelText("Password"), "correct horse battery staple")
    await user.click(screen.getByRole("checkbox"))
    await user.click(screen.getByRole("button", { name: "Create account" }))
    expect(screen.getByText("Enter a mobile number.")).toBeTruthy()
    expect((s.parentSignup as ReturnType<typeof fakeMutation>).mutate).not.toHaveBeenCalled()
  })

  it("sends the proof token with the cleaned number, never blocking a pasted one", async () => {
    const user = userEvent.setup()
    await reachFinalStep(user)
    // Pasted from a contacts app: embedding marks around the number.
    await user.click(screen.getByLabelText("Mobile number"))
    await user.paste("‪+20 101 234 5678‬")
    await user.type(screen.getByLabelText("Password"), "correct horse battery staple")
    await user.click(screen.getByRole("checkbox"))
    await user.click(screen.getByRole("button", { name: "Create account" }))
    const mutate = (s.parentSignup as ReturnType<typeof fakeMutation>).mutate
    expect(mutate).toHaveBeenCalledTimes(1)
    expect(mutate.mock.calls[0][0]).toMatchObject({ proofToken: "proof-1", phone: "+20 101 234 5678", acceptedTerms: true })
  })

  it.each([
    ["phone_required", "Enter a mobile number."],
    ["phone_invalid", "Enter a valid mobile number, for example 01012345678 or +201012345678."],
  ])("shows the server's %s on the field, not in the form alert, and returns focus to it", async (code, sentence) => {
    const user = userEvent.setup()
    await reachFinalStep(user)
    s.parentSignup = fakeMutation({ isError: true, error: phone422(code) })
    // Re-render with the failed mutation, as the real hook does after the call.
    await user.type(screen.getByLabelText("Mobile number"), "0")
    expect(await screen.findByText(sentence)).toBeTruthy()
    expect(screen.queryByText("server wording")).toBeNull()
    expect(screen.queryByText(/couldn't create your account/i)).toBeNull()
    expect(screen.getByLabelText("Mobile number").getAttribute("aria-invalid")).toBe("true")
  })

  it("moves focus back to the field after a server refusal of the number", async () => {
    const user = userEvent.setup()
    await reachFinalStep(user)
    const failing = fakeMutation()
    failing.mutate.mockImplementation((_b: unknown, o?: { onError?: (e: unknown) => void }) => o?.onError?.(phone422("phone_invalid")))
    s.parentSignup = failing
    await user.type(screen.getByLabelText("Mobile number"), "01012345678")
    await user.type(screen.getByLabelText("Password"), "correct horse battery staple")
    await user.click(screen.getByRole("checkbox"))
    await user.click(screen.getByRole("button", { name: "Create account" }))
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("Mobile number")))
  })

  it("keeps the form-level alert for any other failure", async () => {
    const user = userEvent.setup()
    await reachFinalStep(user)
    s.parentSignup = fakeMutation({ isError: true, error: new ApiError(500, "500") })
    await user.type(screen.getByLabelText("Password"), "x")
    expect(await screen.findByRole("alert")).toBeTruthy()
    expect(screen.getByLabelText("Mobile number").getAttribute("aria-invalid")).toBeNull()
  })
})
