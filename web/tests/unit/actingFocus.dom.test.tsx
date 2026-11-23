// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { actingQueryHash, clearActingLead, storeLeadId } from "@/lib/actingTeacher"

vi.mock("@/lib/offline/queryPersister", () => ({ persister: { removeClient: () => Promise.resolve() } }))
vi.mock("@/lib/offline/uploadQueue", () => ({ clearUploadQueue: () => Promise.resolve() }))
vi.mock("@/components/ui/route-skeleton", () => ({ RouteSkeleton: () => h("div", { role: "status" }, "Loading") }))
vi.mock("@/lib/auth/AuthContext", () => ({ useAuth: () => ({ session: { role: "teacher" } }) }))

import { ActingTeacherProvider } from "@/components/acting/acting-context"
import { ActingSwitcher } from "@/components/acting/acting-switcher"

/*
 * Focus after a change of identity. The control that had focus goes with the old tree, so after
 * the person's own switch focus returns to `<main>`. Restoring the stored choice on page load
 * is not a switch: moving focus then makes `:focus-visible` match `<main>` and draws the global
 * focus ring under the top bar before anyone has touched anything.
 */

const HASSAN = "11111111-1111-4111-8111-111111111111"
const marker = {
  memberId: "m1",
  teacherId: HASSAN,
  teacherName: "Mr Hassan",
  role: "marker",
  effectivePermissions: ["mark", "regrade", "view_results"],
  available: true,
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, queryKeyHashFn: actingQueryHash } } })
  return render(
    h(
      QueryClientProvider,
      { client },
      h(
        MemoryRouter,
        { initialEntries: ["/teacher/classes"] },
        h(
          ActingTeacherProvider,
          null,
          h("main", { id: "main-content", tabIndex: -1 }, h("p", null, "content")),
          h(ActingSwitcher),
        ),
      ),
    ),
  )
}

const mainEl = () => document.getElementById("main-content")

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = String(url).endsWith("/teacher/team/memberships") ? { memberships: [marker] } : {}
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } })
    }),
  )
  // Node's own experimental `localStorage` shadows jsdom's and throws; the bearer token is read from it.
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => {}, removeItem: () => {} })
  window.sessionStorage.clear()
  clearActingLead()
})

afterEach(() => {
  clearActingLead()
  window.sessionStorage.clear()
  vi.unstubAllGlobals()
})

describe("focus on <main> after an identity change", () => {
  it("does not move focus when the stored acting identity is restored on mount", async () => {
    storeLeadId(HASSAN)
    mount()
    // The restore has finished once the switcher names the lead.
    await screen.findByRole("button", { name: /^Working as.*Hassan/ })
    expect(mainEl()).not.toBeNull()
    expect(document.activeElement).not.toBe(mainEl())
    expect(document.activeElement).toBe(document.body)
  })

  it("moves focus to <main> after the person switches identity themselves", async () => {
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole("button", { name: /^Working as/ }))
    await user.click(await screen.findByRole("menuitemradio", { name: /Hassan/ }))
    await waitFor(() => expect(document.activeElement).toBe(mainEl()))
  })

  it("moves focus to <main> after switching back to me, too", async () => {
    const user = userEvent.setup()
    storeLeadId(HASSAN)
    mount()
    await user.click(await screen.findByRole("button", { name: /^Working as.*Hassan/ }))
    await user.click(await screen.findByRole("menuitemradio", { name: "Me" }))
    await waitFor(() => expect(document.activeElement).toBe(mainEl()))
  })
})
