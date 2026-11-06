// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h } from "react"
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { PACK_UPDATE_FIELDS, packUpdateBody, packValues } from "@/lib/adminBillingModel"
import { fx } from "./support/billingFixtures"
import { fakeMutation, okQuery } from "./support/billingRender"

/*
 * Behaviour of the reasoned admin dialog and the catalogue's writes in a real DOM: what is sent,
 * what is not, and that a second submit never reaches the server.
 */

const s = vi.hoisted(() => ({
  catalogue: null as unknown,
  updateTier: null as unknown,
  syncTier: null as unknown,
  updateFree: null as unknown,
}))
vi.mock("@/lib/hooks/useAdminBillingApi", () => ({
  useAdminCatalogue: () => s.catalogue,
  useCreateTier: () => s.updateTier,
  useUpdateTier: () => s.updateTier,
  useSyncTier: () => s.syncTier,
  useCreatePack: () => s.updateTier,
  useUpdatePack: () => s.updateTier,
  useCreateRate: () => s.updateTier,
  useCreateEstimator: () => s.updateTier,
  useUpdateFreeAllowances: () => s.updateFree,
}))

import { Catalogue } from "@/portals/admin/screens/billing/Catalogue"
import { ReasonedFormDialog } from "@/portals/admin/screens/billing/ReasonedFormDialog"

type Fake = ReturnType<typeof fakeMutation>

/** Set the controlled reason field in one synchronous event: no per-key timing to race. */
const setReason = (text: string) => fireEvent.change(screen.getByLabelText("Reason"), { target: { value: text } })
const fake = (over: Parameters<typeof fakeMutation>[0] = {}): Fake => fakeMutation(over)

function wrap(el: ReturnType<typeof h>) {
  return h(QueryClientProvider, { client: new QueryClient() }, h(MemoryRouter, null, el))
}

function dialog(mutation: Fake, over: Record<string, unknown> = {}) {
  const toBody = vi.fn((v: Record<string, string | boolean>, reason: string) => packUpdateBody(v, reason))
  const onClose = vi.fn()
  const onSaved = vi.fn()
  render(
    wrap(
      h(ReasonedFormDialog, {
        open: true,
        onClose,
        onSaved,
        title: "Edit pack_500",
        fields: PACK_UPDATE_FIELDS,
        initial: packValues(fx.adminCatalogue.packs[0]),
        submitLabel: "Save pack",
        mutation: mutation as never,
        toBody: toBody as never,
        ...over,
      }),
    ),
  )
  return { toBody, onClose, onSaved }
}

describe("ReasonedFormDialog", () => {
  it("does not call the server for invalid input, shows the field's error and focuses it", async () => {
    const user = userEvent.setup()
    const m = fake()
    dialog(m, { initial: { ...packValues(fx.adminCatalogue.packs[0]), units: "0" } })
    setReason("valid reason here")
    await user.click(screen.getByRole("button", { name: "Save pack" }))
    expect(m.mutate).not.toHaveBeenCalled()
    expect(screen.getByText("Credits must be a whole number above zero.")).toBeTruthy()
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("Credits")))
  })

  it("refuses a short reason and moves focus to it when every field is valid", async () => {
    const user = userEvent.setup()
    const m = fake()
    dialog(m)
    setReason("no")
    await user.click(screen.getByRole("button", { name: "Save pack" }))
    expect(m.mutate).not.toHaveBeenCalled()
    expect(screen.getByText(/at least 5 characters/)).toBeTruthy()
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("Reason")))
  })

  it("sends the trimmed reason once and closes after the server accepts", async () => {
    const user = userEvent.setup()
    const m = fake()
    m.mutate.mockImplementation((_body: unknown, opts?: { onSuccess?: () => void }) => opts?.onSuccess?.())
    const { toBody, onClose, onSaved } = dialog(m)
    setReason("   price matched to Paymob   ")
    await user.click(screen.getByRole("button", { name: "Save pack" }))
    await waitFor(() => expect(m.mutate).toHaveBeenCalledTimes(1))
    expect(toBody).toHaveBeenCalledWith(expect.anything(), "price matched to Paymob")
    expect(onSaved).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it("ignores a second submit while the first is pending, from the button and from Enter", async () => {
    const m = fake({ isPending: true })
    dialog(m)
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "valid reason here" } })
    const submit = screen.getByRole("button", { name: "Save pack" }) as HTMLButtonElement
    expect(submit.disabled).toBe(true)
    expect(submit.getAttribute("aria-busy")).toBe("true")
    expect((screen.getByRole("button", { name: "Cancel" }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.submit(submit.form as HTMLFormElement)
    fireEvent.click(submit)
    expect(m.mutate).not.toHaveBeenCalled()
  })

  it("shows the server's refusal beside the buttons", () => {
    const error = new ApiError(409, "Conflict", { code: "code_taken", message: "A pack with code pack_500 exists." })
    dialog(fake({ isError: true, error }))
    expect(screen.getByRole("alert").textContent).toContain("A pack with code pack_500 exists.")
  })
})

describe("Catalogue writes", () => {
  beforeEach(() => {
    s.catalogue = okQuery(fx.adminCatalogue)
    s.updateTier = fake()
    s.syncTier = fake()
    s.updateFree = fake()
  })

  const reason = (text = "because the price changed") => setReason(text)

  it("sends a tier edit with its stored features carried through, not only the true lines", async () => {
    const tier = { ...fx.adminCatalogue.tiers[0], rawFeatures: { "Mark past papers": true, "Study plans": true, papers: "unlimited", beta: false } }
    s.catalogue = okQuery({ ...fx.adminCatalogue, tiers: [tier] })
    const user = userEvent.setup()
    render(wrap(h(Catalogue)))
    await user.click(screen.getAllByRole("button", { name: "Edit student_plus_m" })[0])
    expect(screen.getByText(/2 other feature settings .* kept as they are/)).toBeTruthy()
    reason()
    await user.click(screen.getByRole("button", { name: "Save tier" }))
    await waitFor(() => expect((s.updateTier as Fake).mutate).toHaveBeenCalledTimes(1))
    const [vars] = (s.updateTier as Fake).mutate.mock.calls[0]
    expect(vars.id).toBe("t-s-m")
    expect(vars.body.features).toEqual({ papers: "unlimited", beta: false, "Mark past papers": true, "Study plans": true })
    expect(vars.body.reason).toBe("because the price changed")
  })

  it("warns that syncing an in-sync tier only adds a plan, and names the action plainly", async () => {
    const user = userEvent.setup()
    render(wrap(h(Catalogue)))
    await user.click(screen.getAllByRole("button", { name: "Sync student_plus_m to Paymob" })[0])
    const dlg = screen.getByRole("dialog")
    expect(within(dlg).getByText(/already in sync/)).toBeTruthy()
    expect(within(dlg).getByText(/Subscriptions already running keep the plan they started on/)).toBeTruthy()
    expect(within(dlg).getByRole("button", { name: "Create a new plan anyway" })).toBeTruthy()
  })

  it("keeps the plain sync wording for a tier that differs from Paymob", async () => {
    s.catalogue = okQuery({ ...fx.adminCatalogue, tiers: [{ ...fx.adminCatalogue.tiers[0], drift: "Paymob plan differs from the catalogue", driftState: "drifted" }] })
    const user = userEvent.setup()
    render(wrap(h(Catalogue)))
    await user.click(screen.getAllByRole("button", { name: "Sync student_plus_m to Paymob" })[0])
    const dlg = screen.getByRole("dialog")
    expect(within(dlg).queryByText(/already in sync/)).toBeNull()
    reason()
    await user.click(within(dlg).getByRole("button", { name: "Sync to Paymob" }))
    await waitFor(() => expect((s.syncTier as Fake).mutate).toHaveBeenCalledTimes(1))
    expect((s.syncTier as Fake).mutate.mock.calls[0][0]).toEqual({ id: "t-s-m", body: { reason: "because the price changed" } })
  })

  it("sends only the free allowance that changed, and nothing when nothing changed", async () => {
    const user = userEvent.setup()
    render(wrap(h(Catalogue)))
    await user.click(screen.getByRole("button", { name: "Edit free allowances" }))
    reason()
    await user.click(screen.getByRole("button", { name: "Save allowances" }))
    expect((s.updateFree as Fake).mutate).not.toHaveBeenCalled()
    expect(screen.getByText(/Nothing has changed/)).toBeTruthy()
    const teacher = screen.getByLabelText("Teacher signup credits (units)")
    await user.clear(teacher)
    await user.type(teacher, "1200")
    await user.click(screen.getByRole("button", { name: "Save allowances" }))
    await waitFor(() => expect((s.updateFree as Fake).mutate).toHaveBeenCalledTimes(1))
    expect((s.updateFree as Fake).mutate.mock.calls[0][0]).toEqual([{ audience: "teacher", units: 1200, reason: "because the price changed" }])
  })

  it("shows an unset signup pack as Not set and requires a value for it", async () => {
    s.catalogue = okQuery({ ...fx.adminCatalogue, freeAllowances: { studentSignupUnits: null, teacherSignupUnits: 1000, teacherSignupExpiryDays: 30 } })
    const user = userEvent.setup()
    render(wrap(h(Catalogue)))
    expect(screen.getByText("Not set")).toBeTruthy()
    await user.click(screen.getByRole("button", { name: "Edit free allowances" }))
    reason()
    await user.click(screen.getByRole("button", { name: "Save allowances" }))
    expect((s.updateFree as Fake).mutate).not.toHaveBeenCalled()
    expect(screen.getByText("Student free allowance (units) is required.")).toBeTruthy()
  })
})
