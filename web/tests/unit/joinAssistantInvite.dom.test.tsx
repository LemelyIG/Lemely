// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/offline/queryPersister", () => ({ persister: { removeClient: () => Promise.resolve() } }))
vi.mock("@/lib/offline/uploadQueue", () => ({ clearUploadQueue: () => Promise.resolve() }))

const auth = vi.hoisted(() => ({ session: null as null | { role: string } }))
vi.mock("@/lib/auth/AuthContext", () => ({ useAuth: () => ({ session: auth.session }) }))

import { JoinWithCode } from "@/portals/auth/JoinWithCode"

/*
 * A team invite (`role: "assistant"`) on the join screen. The preview names the lead teacher and
 * nothing else; a signed-in teacher joins through the team route; everyone else is told what they
 * need. Only `fetch` is replaced.
 */

const CODE = "7HKPX2WCQY"

const world = {
  redeem: { status: 200, body: { memberId: "m1", teacherId: "t1", teacherName: "Mr Hassan", role: "marker", effectivePermissions: [] } as unknown },
  calls: [] as { url: string; method: string; body: unknown }[],
}

beforeEach(() => {
  world.calls = []
  world.redeem = { status: 200, body: { memberId: "m1", teacherId: "t1", teacherName: "Mr Hassan", role: "marker", effectivePermissions: [] } }
  auth.session = null
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => {}, removeItem: () => {} })
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url)
      world.calls.push({ url: u, method: init?.method ?? "GET", body: init?.body ? JSON.parse(String(init.body)) : undefined })
      const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
      if (u.endsWith(`/invites/${CODE}`)) {
        return json({ role: "assistant", schoolName: null, className: null, teacherName: "Mr Hassan", childName: null })
      }
      if (u.endsWith("/teacher/team/assistants/redeem")) return json(world.redeem.body, world.redeem.status)
      return json({})
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

function Where() {
  const l = useLocation()
  return h("p", { "data-testid": "where" }, l.pathname + l.search)
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(h(QueryClientProvider, { client }, h(MemoryRouter, { initialEntries: [`/join/${CODE}`] }, h(Routes, null, h(Route, { path: "/join/:code", element: h(JoinWithCode) })), h(Where))))
}

describe("an assistant invite preview", () => {
  it("names the lead teacher and says what stays with them, with no school, class or child", async () => {
    mount()
    expect(await screen.findByText("Mr Hassan invited you to assist on their team")).toBeTruthy()
    expect(screen.getByText("Billing and seats stay with them.")).toBeTruthy()
    expect(screen.getByText("Team invite")).toBeTruthy()
    expect(screen.getByRole("heading", { name: "You're about to join a team" })).toBeTruthy()
    expect(screen.queryByText(/class$/)).toBeNull()
    expect(screen.queryByText(/Student invite|Parent invite|Teacher invite/)).toBeNull()
  })

  it("sends a signed-out visitor to a teacher signup that comes back here", async () => {
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole("button", { name: "Create a teacher account" }))
    expect(screen.getByTestId("where").textContent).toBe(`/signup/teacher?next=${encodeURIComponent(`/join/${CODE}`)}`)
    // Nothing was redeemed for someone with no account.
    expect(world.calls.some((c) => c.url.includes("redeem"))).toBe(false)
  })

  it("lets a signed-in teacher join through the team route and lands on the team page", async () => {
    const user = userEvent.setup()
    auth.session = { role: "teacher" }
    mount()
    await user.click(await screen.findByRole("button", { name: "Join now" }))
    await vi.waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/teacher/team"))
    const redeem = world.calls.find((c) => c.url.endsWith("/teacher/team/assistants/redeem"))
    expect(redeem?.method).toBe("POST")
    expect(redeem?.body).toEqual({ code: CODE })
    // Not the invites redeem route, which would only refuse a team code.
    expect(world.calls.some((c) => c.url.endsWith(`/invites/${CODE}/redeem`))).toBe(false)
  })

  it("tells a signed-in student or parent that only a teacher account can join, and offers no button", async () => {
    for (const role of ["student", "parent", "school_admin"]) {
      auth.session = { role }
      const view = mount()
      expect(await screen.findByText("Only teacher accounts can join a team. Sign out to use a teacher account.")).toBeTruthy()
      expect(screen.queryByRole("button", { name: "Join now" })).toBeNull()
      view.unmount()
    }
  })

  it("says in the team's own words when the code was already used, and stops offering to retry", async () => {
    const user = userEvent.setup()
    auth.session = { role: "teacher" }
    world.redeem = { status: 409, body: { detail: { code: "invite_already_redeemed", message: "x" } } }
    mount()
    await user.click(await screen.findByRole("button", { name: "Join now" }))
    expect(await screen.findByText("That code has already been used. Ask for a new one.")).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Join now" })).toBeNull()
  })
})
