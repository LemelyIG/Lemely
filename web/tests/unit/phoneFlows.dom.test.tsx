// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h } from "react"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { billingPaths } from "@/lib/billingPaths"
import { fx } from "./support/billingFixtures"
import { fakeMutation, okQuery } from "./support/billingRender"

/*
 * UD-11 in the two places the server can refuse a number after the form has passed it: the
 * sign-up screen (422 on the field) and checkout (422 `phone_required`, which asks for the number
 * in place and then retries the same checkout).
 */

const s = vi.hoisted(() => ({
  signup: null as unknown,
  put: null as unknown,
  catalogue: null as unknown,
  subCheckout: null as unknown,
  packCheckout: null as unknown,
}))

vi.mock("@/lib/auth/AuthContext", () => ({ useAuth: () => ({ signup: s.signup, session: null }) }))
vi.mock("@/lib/hooks/useInvitesApi", () => ({ useRedeemInvite: () => ({ mutate: vi.fn(), isPending: false }) }))
vi.mock("@/lib/hooks/useMeApi", () => ({ usePutPhone: () => s.put }))
vi.mock("@/lib/hooks/useBillingApi", () => ({
  useCatalogue: () => s.catalogue,
  useStartSubscriptionCheckout: () => s.subCheckout,
  useStartPackCheckout: () => s.packCheckout,
}))

import { SignupDetails } from "@/portals/auth/SignupDetails"
import { PlansView } from "@/portals/billing/PlansView"

const phone422 = (code: string) => new ApiError(422, "422", { code, message: "server wording" })

describe("sign-up phone field", () => {
  const open = () => render(h(MemoryRouter, null, h(SignupDetails, { role: "student" })))
  const fill = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.type(screen.getByLabelText("Name"), "Amina Farouk")
    await user.type(screen.getByLabelText("Email"), "amina@example.com")
    await user.type(screen.getByLabelText("Phone number"), "01012345678")
    await user.type(screen.getByLabelText("Password"), "correct horse battery staple")
    await user.click(screen.getByRole("checkbox"))
  }

  beforeEach(() => {
    s.signup = fakeMutation()
  })

  it("asks for a required phone number between the email and the password", () => {
    open()
    const labels = screen.getAllByText(/^(Name|Email|Phone number|Password)$/).map((el) => el.textContent)
    expect(labels).toEqual(["Name", "Email", "Phone number", "Password"])
    expect((screen.getByLabelText("Phone number") as HTMLInputElement).required).toBe(true)
  })

  it("will not submit without a number, and says so on the field", async () => {
    const user = userEvent.setup()
    open()
    await user.type(screen.getByLabelText("Name"), "Amina Farouk")
    await user.type(screen.getByLabelText("Email"), "amina@example.com")
    await user.type(screen.getByLabelText("Password"), "correct horse battery staple")
    await user.click(screen.getByRole("checkbox"))
    await user.click(screen.getByRole("button", { name: "Create account" }))
    expect(screen.getByText("Enter a phone number.")).toBeTruthy()
    expect((s.signup as ReturnType<typeof fakeMutation>).mutate).not.toHaveBeenCalled()
  })

  it("sends the number as typed with the rest of the payload", async () => {
    const user = userEvent.setup()
    open()
    await fill(user)
    await user.click(screen.getByRole("button", { name: "Create account" }))
    const mutate = (s.signup as ReturnType<typeof fakeMutation>).mutate
    expect(mutate).toHaveBeenCalledTimes(1)
    // The field tidied the leading zero away on blur; the server reads it the same way.
    expect(mutate.mock.calls[0][0]).toMatchObject({ role: "student", phone: "1012345678", acceptedTerms: true })
  })

  it.each([
    ["phone_required", "Enter a phone number."],
    ["phone_invalid", "Enter a valid phone number, for example 01012345678 or +201012345678."],
  ])("shows the server's %s on the field and not in the form-level alert", async (code, sentence) => {
    s.signup = fakeMutation({ isError: true, error: phone422(code) })
    open()
    expect(screen.getByText(sentence)).toBeTruthy()
    expect(screen.queryByText("server wording")).toBeNull()
    expect(screen.queryByText(/couldn't create your account/i)).toBeNull()
    expect(screen.getByLabelText("Phone number").getAttribute("aria-invalid")).toBe("true")
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("Phone number")))
  })

  it("keeps the form-level alert for every other failure", () => {
    s.signup = fakeMutation({ isError: true, error: new ApiError(500, "500") })
    open()
    expect(screen.getByRole("alert")).toBeTruthy()
    expect(screen.getByLabelText("Phone number").getAttribute("aria-invalid")).toBeNull()
  })
})

describe("checkout asks for the phone number in place", () => {
  const paths = billingPaths({ role: "student" })
  const open = () =>
    render(
      h(
        MemoryRouter,
        null,
        h(PlansView, {
          audience: "student",
          beneficiaryId: null,
          paths,
          currentTierId: null,
          hasLiveSubscription: false,
          canManage: true,
          managedByName: null,
        }),
      ),
    )

  beforeEach(() => {
    s.catalogue = okQuery(fx.studentCatalogue)
    s.subCheckout = fakeMutation()
    s.packCheckout = fakeMutation()
    s.put = fakeMutation()
  })

  it("shows the plain sentence and a phone field instead of a generic error, for a plan", () => {
    s.subCheckout = fakeMutation({ isError: true, error: phone422("phone_required") })
    open()
    expect(screen.getByRole("heading", { name: "Add your phone number to continue" })).toBeTruthy()
    expect(screen.getByLabelText("Phone number")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Save and continue" })).toBeTruthy()
    expect(screen.queryByText(/Check the details/)).toBeNull()
    expect(screen.queryByText(/Couldn't start checkout/)).toBeNull()
  })

  it("shows it under the credit packs when a pack was the one that stopped", () => {
    s.packCheckout = fakeMutation({ isError: true, error: phone422("phone_required") })
    open()
    const heading = screen.getByRole("heading", { name: "Add your phone number to continue" })
    expect(heading.closest("section")?.id).toBe("packs")
  })

  it("keeps the ordinary failure line for any other checkout error", () => {
    s.subCheckout = fakeMutation({ isError: true, error: new ApiError(503, "503") })
    open()
    expect(screen.queryByRole("heading", { name: "Add your phone number to continue" })).toBeNull()
    expect(screen.getByRole("alert").textContent).toMatch(/Payments are unavailable/)
  })

  it("saves the number, then retries the same plan checkout", async () => {
    const user = userEvent.setup()
    const variables = { planTierId: "t-s-m", audience: "student", successUrl: "x" }
    const sub = fakeMutation({ isError: true, error: phone422("phone_required") })
    ;(sub as unknown as { variables: unknown }).variables = variables
    s.subCheckout = sub
    const put = fakeMutation()
    put.mutate.mockImplementation((_p: string, opts?: { onSuccess?: (st: unknown) => void }) =>
      opts?.onSuccess?.({ phone: "+201012345678", phoneMissing: false }),
    )
    s.put = put
    open()
    await user.type(screen.getByLabelText("Phone number"), "01012345678")
    await user.click(screen.getByRole("button", { name: "Save and continue" }))
    expect(put.mutate.mock.calls[0][0]).toBe("1012345678")
    expect(sub.mutate).toHaveBeenCalledTimes(1)
    expect(sub.mutate.mock.calls[0][0]).toBe(variables)
  })

  it("saves the number, then retries the same pack checkout", async () => {
    const user = userEvent.setup()
    const variables = { creditPackId: "pk1" }
    const pack = fakeMutation({ isError: true, error: phone422("phone_required") })
    ;(pack as unknown as { variables: unknown }).variables = variables
    s.packCheckout = pack
    const put = fakeMutation()
    put.mutate.mockImplementation((_p: string, opts?: { onSuccess?: (st: unknown) => void }) =>
      opts?.onSuccess?.({ phone: "+201012345678", phoneMissing: false }),
    )
    s.put = put
    open()
    await user.type(screen.getByLabelText("Phone number"), "+201012345678")
    await user.click(screen.getByRole("button", { name: "Save and continue" }))
    expect(pack.mutate).toHaveBeenCalledTimes(1)
    expect(pack.mutate.mock.calls[0][0]).toBe(variables)
  })

  it("does not retry when the number is refused, and shows why on the field", async () => {
    const user = userEvent.setup()
    const sub = fakeMutation({ isError: true, error: phone422("phone_required") })
    ;(sub as unknown as { variables: unknown }).variables = { planTierId: "t-s-m" }
    s.subCheckout = sub
    const put = fakeMutation()
    put.mutate.mockImplementation((_p: string, opts?: { onError?: (e: unknown) => void }) =>
      opts?.onError?.(phone422("phone_invalid")),
    )
    s.put = put
    open()
    await user.type(screen.getByLabelText("Phone number"), "01012345678")
    await user.click(screen.getByRole("button", { name: "Save and continue" }))
    expect(screen.getByText(/Enter a valid phone number/)).toBeTruthy()
    expect(sub.mutate).not.toHaveBeenCalled()
  })
})
