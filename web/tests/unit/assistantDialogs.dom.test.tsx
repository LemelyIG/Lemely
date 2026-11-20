// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h, type ReactElement } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { INVITE_CODE_ID, rolePresetId } from "@/lib/assistantRoles"
import { fx } from "./support/billingFixtures"

/*
 * Behaviour the static-markup tests cannot reach: focus after a control leaves the page, and the
 * request a dialog really sends. Only the network boundary (`request`) is replaced; the dialogs,
 * the react-query hooks and the Modal run as shipped.
 */

const net = vi.hoisted(() => ({ request: vi.fn() }))
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), request: net.request }))

import { InviteDialog, RoleDialog } from "@/portals/teacher/screens/team/AssistantDialogs"

const renderDialog = (el: ReactElement) =>
  render(
    h(
      QueryClientProvider,
      { client: new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }) },
      // Modal pushes a history entry, so it needs a router.
      h(MemoryRouter, null, el),
    ),
  )

beforeEach(() => {
  net.request.mockReset()
})

describe("RoleDialog focus", () => {
  // A marker whose toggles differ from the preset: Regrade off, See usage on.
  const custom = { ...fx.assistant, overrides: { regrade: false, view_usage: true }, permissions: ["mark", "view_results", "view_usage"] as typeof fx.assistant.permissions }

  it("keeps focus inside the dialog, on the preset, when Reset to preset leaves the page", async () => {
    const user = userEvent.setup()
    renderDialog(h(RoleDialog, { open: true, onClose: vi.fn(), assistant: custom }))
    const dialog = await screen.findByRole("dialog", { name: /Role for Sara Ali/ })

    const reset = within(dialog).getByRole("button", { name: "Reset to preset" })
    await user.click(reset)

    await waitFor(() => expect(within(dialog).queryByRole("button", { name: "Reset to preset" })).toBeNull())
    expect(document.activeElement).not.toBe(document.body)
    expect(document.activeElement?.id).toBe(rolePresetId("marker"))
    expect(dialog.contains(document.activeElement)).toBe(true)
    // The toggles are back on the preset.
    expect(within(dialog).getByRole("switch", { name: "Regrade papers" }).getAttribute("aria-checked")).toBe("true")
    expect(within(dialog).getByRole("switch", { name: "See usage" }).getAttribute("aria-checked")).toBe("false")
  })

  it("still closes on Escape after a reset", async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    renderDialog(h(RoleDialog, { open: true, onClose, assistant: custom }))
    await user.click(await screen.findByRole("button", { name: "Reset to preset" }))
    await user.keyboard("{Escape}")
    expect(onClose).toHaveBeenCalled()
  })
})

describe("InviteDialog focus", () => {
  it("moves focus to the code when the invite is created", async () => {
    const user = userEvent.setup()
    net.request.mockResolvedValue(fx.team.invites[0])
    renderDialog(h(InviteDialog, { open: true, onClose: vi.fn() }))

    await user.click(await screen.findByRole("button", { name: "Create invite code" }))

    const dialog = await screen.findByRole("dialog")
    await within(dialog).findByText(fx.team.invites[0]!.code)
    await waitFor(() => expect(document.activeElement?.id).toBe(INVITE_CODE_ID))
    expect(dialog.contains(document.activeElement)).toBe(true)
    // The request carries the preset and the expiry the form showed.
    expect(net.request).toHaveBeenCalledTimes(1)
    const [path, init] = net.request.mock.calls[0] as [string, RequestInit]
    expect(path).toBe("/teacher/team/assistants/invites")
    expect(init.method).toBe("POST")
    expect(JSON.parse(String(init.body))).toEqual({ role: "marker", expiresInDays: 7 })
  })
})

describe("RoleDialog save", () => {
  it("sends { role, permissions } with only the toggles that differ, and closes on success", async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    net.request.mockResolvedValue({ ...fx.wireAssistant, permissions: { view_usage: true } })
    renderDialog(h(RoleDialog, { open: true, onClose, assistant: fx.assistant }))
    const dialog = await screen.findByRole("dialog", { name: /Role for Sara Ali/ })

    // Nothing changed yet: nothing to save.
    const save = within(dialog).getByRole("button", { name: "Save role" })
    expect((save as HTMLButtonElement).disabled).toBe(true)

    await user.click(within(dialog).getByRole("switch", { name: "See usage" }))
    await user.click(within(dialog).getByRole("switch", { name: "Regrade papers" }))
    expect((save as HTMLButtonElement).disabled).toBe(false)
    await user.click(save)

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(net.request).toHaveBeenCalledTimes(1)
    const [path, init] = net.request.mock.calls[0] as [string, RequestInit]
    expect(path).toBe(`/teacher/team/assistants/${fx.assistant.memberId}`)
    expect(init.method).toBe("PATCH")
    expect(JSON.parse(String(init.body))).toEqual({ role: "marker", permissions: { regrade: false, view_usage: true } })
  })

  it("sends the new preset with no overrides after choosing another role", async () => {
    const user = userEvent.setup()
    net.request.mockResolvedValue({ ...fx.wireAssistant, role: "viewer" })
    renderDialog(h(RoleDialog, { open: true, onClose: vi.fn(), assistant: fx.assistant }))
    const dialog = await screen.findByRole("dialog")

    await user.click(within(dialog).getByRole("radio", { name: /Viewer/ }))
    await user.click(within(dialog).getByRole("button", { name: "Save role" }))

    await waitFor(() => expect(net.request).toHaveBeenCalledTimes(1))
    const [, init] = net.request.mock.calls[0] as [string, RequestInit]
    expect(JSON.parse(String(init.body))).toEqual({ role: "viewer", permissions: {} })
  })

  it("stays open and says why when the save fails", async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    const { ApiError } = await import("@/lib/api")
    net.request.mockRejectedValue(new ApiError(422, "x", { code: "invalid_permissions" }))
    renderDialog(h(RoleDialog, { open: true, onClose, assistant: fx.assistant }))
    const dialog = await screen.findByRole("dialog")

    await user.click(within(dialog).getByRole("switch", { name: "See usage" }))
    await user.click(within(dialog).getByRole("button", { name: "Save role" }))

    expect((await within(dialog).findByRole("alert")).textContent).toContain("Choose only the permissions listed")
    expect(onClose).not.toHaveBeenCalled()
  })
})
