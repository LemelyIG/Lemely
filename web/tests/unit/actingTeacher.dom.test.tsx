// @vitest-environment jsdom
import "./support/dom-setup"
import { createElement as h, type ReactNode } from "react"
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query"
import { act, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { request } from "@/lib/api"
import { ACTING_TEACHER_HEADER, actingQueryHash, clearActingLead, getActingLead, readStoredLeadId, setActingLead, storeLeadId } from "@/lib/actingTeacher"

vi.mock("@/lib/offline/queryPersister", () => ({ persister: { removeClient: () => Promise.resolve() } }))
vi.mock("@/lib/offline/uploadQueue", () => ({ clearUploadQueue: () => Promise.resolve() }))

// The real skeleton reads route matches, which need a data router; its shape is not under test.
vi.mock("@/components/ui/route-skeleton", () => ({ RouteSkeleton: () => h("div", { role: "status" }, "Loading") }))

const auth = vi.hoisted(() => ({ role: "teacher" }))
vi.mock("@/lib/auth/AuthContext", () => ({ useAuth: () => ({ session: { role: auth.role } }) }))

import { ActingTeacherProvider } from "@/components/acting/acting-context"
import { ActingBanner } from "@/components/acting/acting-banner"
import { ActingSwitcher } from "@/components/acting/acting-switcher"
import { OwnAccountNote } from "@/components/acting/own-account-note"
import { PermissionGate } from "@/components/acting/permission-gate"
import { CreateSheet } from "@/portals/teacher/components/TopBarSheets"
import { ActingUnavailableView } from "@/components/acting/acting-unavailable"
import { ActingGuard } from "@/components/acting/acting-guard"
import { ClassesSettingsSection } from "@/portals/settings/ClassesSettings"
import { useActingTeacher } from "@/components/acting/acting-state"

/*
 * The acting-teacher context end to end in a real DOM: the provider, the switcher, the banner, the
 * gating, and the request layer underneath. Only `fetch` is replaced, so the header, the partitioned
 * cache and the refusal wording all run as shipped.
 */

const HASSAN = "11111111-1111-4111-8111-111111111111"
const AHMED = "22222222-2222-4222-8222-222222222222"

const marker = { memberId: "m1", teacherId: HASSAN, teacherName: "Mr Hassan", role: "marker", effectivePermissions: ["mark", "regrade", "view_results"], available: true }
const coTeacher = { memberId: "m2", teacherId: AHMED, teacherName: "Ms Ahmed", role: "co_teacher", effectivePermissions: ["mark", "regrade", "generate_quiz", "manage_classes", "view_results", "manage_students", "view_usage"], available: true }
const SCHOOL = "33333333-3333-4333-8333-333333333333"
// A lead who holds school data: assistants cannot act for them right now (`available: false`).
const schoolLead = { memberId: "m3", teacherId: SCHOOL, teacherName: "Dr Nasr", role: "co_teacher", effectivePermissions: ["mark", "view_results"], available: false }

const world = {
  memberships: [marker, coTeacher] as unknown[],
  membershipsStatus: 200,
  /** When set, the membership list never answers. */
  holdMemberships: false,
  /** When set, the lead's class list is refused with this code (while the lead header is sent). */
  classesRefusal: null as null | "team_permission_denied" | "team_lead_unavailable",
  calls: [] as { url: string; header: string | undefined }[],
}

function respond(url: string, init: RequestInit | undefined): Response {
  const headers = (init?.headers ?? {}) as Record<string, string>
  const header = headers[ACTING_TEACHER_HEADER]
  world.calls.push({ url, header })
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
  if (url.endsWith("/teacher/team/memberships")) {
    return world.membershipsStatus === 200 ? json({ memberships: world.memberships }) : json({ detail: "boom" }, world.membershipsStatus)
  }
  if (url.endsWith("/teacher/classes")) {
    if (header && world.classesRefusal) return json({ detail: { code: world.classesRefusal, message: "x" } }, 403)
    return json({ classes: [{ label: header === HASSAN ? "Hassan Y11 Physics" : header === AHMED ? "Ahmed Y9 Maths" : "My Y10 Chemistry" }] })
  }
  return json({})
}

function Probe() {
  const q = useQuery({ queryKey: ["teacher", "classes"], queryFn: () => request<{ classes: { label: string }[] }>("/teacher/classes") })
  return h("p", { "data-testid": "classes" }, q.data ? q.data.classes.map((c) => c.label).join(", ") : "loading")
}

function Where() {
  return h("p", { "data-testid": "where" }, useLocation().pathname)
}

let client: QueryClient

function mount(entry = "/teacher/classes", extra?: ReactNode) {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, queryKeyHashFn: actingQueryHash } } })
  return render(
    h(
      QueryClientProvider,
      { client },
      h(
        MemoryRouter,
        { initialEntries: [entry] },
        h(
          ActingTeacherProvider,
          null,
          h("main", { id: "main-content", tabIndex: -1 }, h(ActingBanner), h(OwnAccountNote), h(Probe), h(Where)),
          h(ActingSwitcher),
          h(PermissionGate, { permission: "manage_classes", mode: "hide", children: h("button", null, "Delete class") }),
          h(PermissionGate, { permission: "mark", children: h("button", null, "Upload and grade") }),
          h(PermissionGate, { permission: "generate_quiz", children: h("button", null, "Create draft") }),
          extra,
        ),
      ),
    ),
  )
}

const classesCalls = () => world.calls.filter((c) => c.url.endsWith("/teacher/classes"))

async function pickLead(user: ReturnType<typeof userEvent.setup>, name: RegExp) {
  await user.click(await screen.findByRole("button", { name: /^Working as/ }))
  await user.click(await screen.findByRole("menuitemradio", { name }))
}

beforeEach(() => {
  auth.role = "teacher"
  world.memberships = [marker, coTeacher]
  world.membershipsStatus = 200
  world.holdMemberships = false
  world.classesRefusal = null
  world.calls = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (world.holdMemberships && String(url).endsWith("/teacher/team/memberships")) await new Promise(() => {})
      return respond(String(url), init)
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

describe("a teacher who assists nobody", () => {
  it("sees nothing new: no switcher, no banner, every action in place", async () => {
    world.memberships = []
    mount()
    expect(await screen.findByText("My Y10 Chemistry")).toBeTruthy()
    expect(screen.queryByText("Working as")).toBeNull()
    expect(screen.queryByTestId("acting-banner")).toBeNull()
    expect(screen.queryByTestId("own-account-note")).toBeNull()
    expect(screen.getByRole("button", { name: "Delete class" })).toBeTruthy()
    expect((screen.getByRole("button", { name: "Upload and grade" }) as HTMLButtonElement).disabled).toBe(false)
    expect((screen.getByRole("button", { name: "Create draft" }) as HTMLButtonElement).disabled).toBe(false)
    expect(classesCalls().every((c) => c.header === undefined)).toBe(true)
  })

  it("does not even ask for memberships when the account is not a teacher (a school admin in the portal)", async () => {
    auth.role = "school_admin"
    mount()
    expect(await screen.findByText("My Y10 Chemistry")).toBeTruthy()
    expect(world.calls.some((c) => c.url.endsWith("/teacher/team/memberships"))).toBe(false)
    expect(screen.queryByText("Working as")).toBeNull()
  })
})

describe("the switcher", () => {
  it("offers Me and each team, with the role, and starts on Me", async () => {
    const user = userEvent.setup()
    mount()
    const trigger = await screen.findByRole("button", { name: "Working as Me" })
    expect(screen.getByText("Working as")).toBeTruthy()
    await user.click(trigger)
    const menu = await screen.findByRole("menu", { name: "Work as" })
    const items = within(menu).getAllByRole("menuitemradio").map((i) => i.textContent)
    expect(items).toEqual(["Me", "Mr Hassan (Marker)", "Ms Ahmed (Co-teacher)"])
    expect(within(menu).getByRole("menuitemradio", { name: "Me" }).getAttribute("aria-checked")).toBe("true")
  })

  it("keeps Me selected and shows no banner until a team is picked", async () => {
    mount()
    await screen.findByRole("button", { name: "Working as Me" })
    expect(screen.queryByTestId("acting-banner")).toBeNull()
    expect(getActingLead()).toBeNull()
  })
})

describe("acting for a lead", () => {
  it("shows the banner naming the lead, the role, and what the role can't do", async () => {
    const user = userEvent.setup()
    mount()
    await pickLead(user, /Mr Hassan/)
    const banner = await screen.findByTestId("acting-banner")
    expect(banner.getAttribute("role")).toBe("status")
    expect(banner.textContent).toContain("Working as Mr Hassan")
    expect(banner.textContent).toContain("(Marker)")
    expect(banner.textContent).toContain("Everything you do here happens on their account.")
    expect(banner.textContent).toContain("Your role can't generate quizzes, manage classes or manage students.")
    expect(within(banner).getByRole("button", { name: "Switch back to me" })).toBeTruthy()
  })

  it("says nothing about missing permissions when the role has them all", async () => {
    const user = userEvent.setup()
    mount()
    await pickLead(user, /Ms Ahmed/)
    const banner = await screen.findByTestId("acting-banner")
    expect(banner.textContent).toContain("Working as Ms Ahmed")
    expect(banner.textContent).not.toContain("Your role can't")
  })

  it("loads the lead's classes with the header, and never shows the caller's under them", async () => {
    const user = userEvent.setup()
    mount()
    expect(await screen.findByText("My Y10 Chemistry")).toBeTruthy()
    await pickLead(user, /Mr Hassan/)
    expect(await screen.findByText("Hassan Y11 Physics")).toBeTruthy()
    expect(screen.queryByText("My Y10 Chemistry")).toBeNull()
    const last = classesCalls().at(-1)
    expect(last?.header).toBe(HASSAN)
  })

  it("never sends the header on the membership request itself", async () => {
    const user = userEvent.setup()
    mount()
    await pickLead(user, /Mr Hassan/)
    await screen.findByText("Hassan Y11 Physics")
    for (const c of world.calls.filter((c) => c.url.includes("/teacher/team/"))) expect(c.header).toBeUndefined()
  })

  it("remembers the choice for the tab and goes to the portal home", async () => {
    const user = userEvent.setup()
    mount("/teacher/classes/some-class")
    await pickLead(user, /Mr Hassan/)
    await screen.findByText("Hassan Y11 Physics")
    expect(readStoredLeadId()).toBe(HASSAN)
    expect(screen.getByTestId("where").textContent).toBe("/teacher")
  })

  it("moves focus to the page content after switching", async () => {
    const user = userEvent.setup()
    mount()
    await pickLead(user, /Mr Hassan/)
    await screen.findByText("Hassan Y11 Physics")
    await waitFor(() => expect(document.activeElement?.id).toBe("main-content"))
  })

  it("says, on own-account pages, that they belong to the caller", async () => {
    const user = userEvent.setup()
    mount()
    await pickLead(user, /Mr Hassan/)
    const note = await screen.findByTestId("own-account-note")
    expect(note.textContent).toBe("This page is about your own account, not Mr Hassan's. Working as Mr Hassan doesn't change it.")
  })

  it("goes back to being the caller from the banner, and clears the remembered choice", async () => {
    const user = userEvent.setup()
    mount()
    await pickLead(user, /Mr Hassan/)
    await screen.findByText("Hassan Y11 Physics")
    await user.click(within(await screen.findByTestId("acting-banner")).getByRole("button", { name: "Switch back to me" }))
    expect(await screen.findByText("My Y10 Chemistry")).toBeTruthy()
    expect(screen.queryByText("Hassan Y11 Physics")).toBeNull()
    expect(screen.queryByTestId("acting-banner")).toBeNull()
    expect(readStoredLeadId()).toBeNull()
    expect(getActingLead()).toBeNull()
    expect(classesCalls().at(-1)?.header).toBeUndefined()
  })

  it("keeps each person's classes apart across a round trip of switches", async () => {
    const user = userEvent.setup()
    mount()
    expect(await screen.findByText("My Y10 Chemistry")).toBeTruthy()
    await pickLead(user, /Mr Hassan/)
    expect(await screen.findByText("Hassan Y11 Physics")).toBeTruthy()
    await pickLead(user, /Ms Ahmed/)
    expect(await screen.findByText("Ahmed Y9 Maths")).toBeTruthy()
    expect(screen.queryByText("Hassan Y11 Physics")).toBeNull()
    await user.click(within(await screen.findByTestId("acting-banner")).getByRole("button", { name: "Switch back to me" }))
    expect(await screen.findByText("My Y10 Chemistry")).toBeTruthy()
    expect(screen.queryByText("Ahmed Y9 Maths")).toBeNull()
    expect(screen.queryByText("Hassan Y11 Physics")).toBeNull()
  })
})

describe("permission-aware controls", () => {
  it("hides row actions and disables forms the role lacks, with the reason", async () => {
    const user = userEvent.setup()
    mount()
    await pickLead(user, /Mr Hassan/)
    await screen.findByText("Hassan Y11 Physics")

    // manage_classes: a row-level action, hidden outright.
    expect(screen.queryByRole("button", { name: "Delete class" })).toBeNull()
    // generate_quiz: kept, disabled, with the server's own sentence above it.
    const create = screen.getByRole("button", { name: "Create draft" }) as HTMLButtonElement
    // Disabled by its fieldset, which is what `:disabled` (and the browser's click handling) sees.
    expect(create.matches(":disabled")).toBe(true)
    expect(screen.getByText("Your role on Mr Hassan's team doesn't allow this.")).toBeTruthy()
    expect(create.closest("fieldset")?.disabled).toBe(true)
    // mark: the marker's own permission, left alone.
    expect((screen.getByRole("button", { name: "Upload and grade" }) as HTMLButtonElement).disabled).toBe(false)
  })

  it("leaves everything in place for a role that has every permission", async () => {
    const user = userEvent.setup()
    mount()
    await pickLead(user, /Ms Ahmed/)
    await screen.findByText("Ahmed Y9 Maths")
    expect(screen.getByRole("button", { name: "Delete class" })).toBeTruthy()
    expect((screen.getByRole("button", { name: "Create draft" }) as HTMLButtonElement).disabled).toBe(false)
    expect(screen.queryByText(/doesn't allow this/)).toBeNull()
  })

  it("brings the controls back when the caller switches back to themselves", async () => {
    const user = userEvent.setup()
    mount()
    await pickLead(user, /Mr Hassan/)
    await screen.findByText("Hassan Y11 Physics")
    expect(screen.queryByRole("button", { name: "Delete class" })).toBeNull()
    await user.click(within(await screen.findByTestId("acting-banner")).getByRole("button", { name: "Switch back to me" }))
    expect(await screen.findByRole("button", { name: "Delete class" })).toBeTruthy()
    expect((screen.getByRole("button", { name: "Create draft" }) as HTMLButtonElement).disabled).toBe(false)
  })
})

describe("a remembered choice", () => {
  it("is held behind a skeleton and checked before any request carries it", async () => {
    storeLeadId(HASSAN)
    mount()
    // Nothing of the portal renders, and no adopted route has been called, until the list answers.
    expect(screen.queryByTestId("classes")).toBeNull()
    expect(classesCalls()).toHaveLength(0)
    expect(await screen.findByText("Hassan Y11 Physics")).toBeTruthy()
    expect(world.calls[0]?.url.endsWith("/teacher/team/memberships")).toBe(true)
    expect(classesCalls().every((c) => c.header === HASSAN)).toBe(true)
    expect(screen.getByTestId("acting-banner").textContent).toContain("Working as Mr Hassan")
  })

  it("resets, with a notice, when that membership no longer exists", async () => {
    storeLeadId("99999999-9999-4999-8999-999999999999")
    mount()
    expect(await screen.findByText("My Y10 Chemistry")).toBeTruthy()
    const notice = screen.getByTestId("acting-notice")
    expect(notice.textContent).toBe("Your access to that team has ended, so you're working as yourself again.")
    expect(readStoredLeadId()).toBeNull()
    expect(getActingLead()).toBeNull()
    expect(screen.queryByTestId("acting-banner")).toBeNull()
    // Nothing was ever sent as the stale lead.
    expect(world.calls.every((c) => c.header === undefined)).toBe(true)
  })

  it("lets the notice be dismissed", async () => {
    const user = userEvent.setup()
    storeLeadId("99999999-9999-4999-8999-999999999999")
    mount()
    await screen.findByTestId("acting-notice")
    await user.click(screen.getByRole("button", { name: "Dismiss" }))
    expect(screen.queryByTestId("acting-notice")).toBeNull()
  })

  it("resets, and says it could not check, when the membership list cannot be read", async () => {
    storeLeadId(HASSAN)
    world.membershipsStatus = 500
    mount()
    // A server failure is retried once (`teamRetry`), a second later, before it counts as failed.
    expect(await screen.findByText("My Y10 Chemistry", {}, { timeout: 4000 })).toBeTruthy()
    expect(screen.getByTestId("acting-notice").textContent).toContain("We couldn't confirm your access to that team")
    expect(getActingLead()).toBeNull()
    expect(readStoredLeadId()).toBeNull()
    expect(world.calls.every((c) => c.header === undefined)).toBe(true)
  })

  it("is ignored for an account that is not a teacher", async () => {
    auth.role = "school_admin"
    storeLeadId(HASSAN)
    mount()
    expect(await screen.findByText("My Y10 Chemistry")).toBeTruthy()
    expect(getActingLead()).toBeNull()
    expect(world.calls.every((c) => c.header === undefined)).toBe(true)
  })
})

describe("a membership that goes away while selected", () => {
  it("resets to the caller, goes home, says why, and stops sending the header", async () => {
    const user = userEvent.setup()
    mount("/teacher/classes")
    await pickLead(user, /Mr Hassan/)
    expect(await screen.findByText("Hassan Y11 Physics")).toBeTruthy()

    // The lead removes this assistant; the next read of the membership list no longer has them.
    world.memberships = [coTeacher]
    await act(async () => {
      await client.invalidateQueries({ queryKey: ["team"] })
    })

    expect(await screen.findByTestId("acting-notice")).toBeTruthy()
    expect(screen.getByTestId("acting-notice").textContent).toBe("Your access to Mr Hassan's team has ended, so you're working as yourself again.")
    expect(await screen.findByText("My Y10 Chemistry")).toBeTruthy()
    expect(screen.queryByText("Hassan Y11 Physics")).toBeNull()
    expect(screen.queryByTestId("acting-banner")).toBeNull()
    expect(getActingLead()).toBeNull()
    expect(readStoredLeadId()).toBeNull()
    expect(classesCalls().at(-1)?.header).toBeUndefined()
    expect(screen.getByTestId("where").textContent).toBe("/teacher")
  })
})

describe("the Create sheet in the top bar", () => {
  // Its two visually-hidden-by-CSS labels make the accessible name unstable in a CSS-less DOM, so find it by slot.
  const openCreateTrigger = async () => {
    await screen.findByRole("button", { name: /Working as/ })
    return document.querySelector('[data-slot="sheet-trigger"]') as HTMLElement
  }
  const titles = () => screen.queryAllByRole("link").map((l) => l.querySelector("span.block")?.textContent)

  it("offers every action to the caller", async () => {
    const user = userEvent.setup()
    mount("/teacher", h(CreateSheet, { triggerClassName: "" }))
    await user.click(await openCreateTrigger())
    expect(titles()).toEqual(["Add a mark scheme", "AI quiz", "Announcement", "Class"])
  })

  it("offers only what the role may do while acting, and keeps shared mark schemes", async () => {
    const user = userEvent.setup()
    mount("/teacher", h(CreateSheet, { triggerClassName: "" }))
    await pickLead(user, /Mr Hassan/)
    await screen.findByText("Hassan Y11 Physics")
    await user.click(await openCreateTrigger())
    // A marker: no quizzes (generate_quiz), no announcements or classes (manage_classes).
    expect(titles()).toEqual(["Add a mark scheme"])
  })

  it("offers everything to a role that has every permission", async () => {
    const user = userEvent.setup()
    mount("/teacher", h(CreateSheet, { triggerClassName: "" }))
    await pickLead(user, /Ms Ahmed/)
    await screen.findByText("Ahmed Y9 Maths")
    await user.click(await openCreateTrigger())
    expect(titles()).toEqual(["Add a mark scheme", "AI quiz", "Announcement", "Class"])
  })
})

describe("a lead that cannot be worked for", () => {
  function Unavailable() {
    const { lead, choose } = useActingTeacher()
    return lead ? h(ActingUnavailableView, { leadName: lead.teacherName, onSwitchBack: () => choose(null) }) : null
  }

  it("says so once, names the lead, and offers the way back to the caller", async () => {
    const user = userEvent.setup()
    mount("/teacher", h(Unavailable))
    await pickLead(user, /Mr Hassan/)
    expect(await screen.findByText("You can't work for Mr Hassan right now")).toBeTruthy()
    expect(screen.getByText(/nothing was changed/)).toBeTruthy()
    // No retry button: a second ask cannot change the answer.
    expect(screen.queryByRole("button", { name: /try again|retry/i })).toBeNull()

    const calls = classesCalls().length
    // The harness also mounts the banner (the real shell hides it while this panel shows), so the
    // panel's button is the last one.
    await user.click(screen.getAllByRole("button", { name: "Switch back to me" }).at(-1)!)
    expect(await screen.findByText("My Y10 Chemistry")).toBeTruthy()
    expect(screen.queryByText(/You can't work for/)).toBeNull()
    expect(getActingLead()).toBeNull()
    expect(classesCalls().at(-1)?.header).toBeUndefined()
    expect(classesCalls().length).toBeGreaterThan(calls)
  })
})

describe("acting for someone who is not on the list", () => {
  it("can do nothing: no lead resolved must not read as working as yourself", async () => {
    // The module says a lead is being acted for, but the membership list has not (or never will)
    // confirm them. Every gated control must stay off in the meantime.
    world.holdMemberships = true
    setActingLead({ leadId: "99999999-9999-4999-8999-999999999999", leadName: "Nobody" })
    mount()
    expect(screen.queryByRole("button", { name: "Delete class" })).toBeNull()
    const upload = (await screen.findByRole("button", { name: "Upload and grade" })) as HTMLButtonElement
    expect(upload.matches(":disabled")).toBe(true)
    expect((screen.getByRole("button", { name: "Create draft" }) as HTMLButtonElement).matches(":disabled")).toBe(true)
  })
})

describe("Settings, an own-account page, while acting", () => {
  it("lists the caller's own classes, not the lead's, with no links into the lead's class pages", async () => {
    const user = userEvent.setup()
    mount("/teacher/settings/classes", h(ClassesSettingsSection))
    expect(await screen.findByText("My Y10 Chemistry")).toBeTruthy()
    // As oneself: the class opens.
    expect(screen.getByRole("link", { name: "Open My Y10 Chemistry" })).toBeTruthy()

    await pickLead(user, /Mr Hassan/)
    await screen.findByText("Hassan Y11 Physics")
    // The page body re-mounted for the lead; Settings is still the caller's.
    const settings = (await screen.findAllByText("My Y10 Chemistry")).at(-1)!
    expect(settings).toBeTruthy()
    expect(screen.queryAllByText("Y11 Physics B")).toHaveLength(0)
    expect(screen.queryByRole("link", { name: /^Open (My|Y1)/ })).toBeNull()
    expect(screen.queryByRole("link", { name: "Go to Classes" })).toBeNull()
    expect(screen.getAllByTestId("own-account-note").length).toBeGreaterThan(0)
    expect(screen.getByText("Your own classes. Switch back to Me to open one.")).toBeTruthy()
    // The settings request carried no acting header.
    const own = world.calls.filter((c) => c.url.endsWith("/teacher/classes"))
    expect(own.some((c) => c.header === undefined)).toBe(true)
  })
})

describe("a lead assistants cannot reach (available: false)", () => {
  it("is listed in the switcher, disabled, with the reason, and cannot be picked", async () => {
    const user = userEvent.setup()
    world.memberships = [marker, schoolLead]
    mount()
    await user.click(await screen.findByRole("button", { name: /^Working as/ }))
    const item = await screen.findByRole("menuitemradio", { name: /Dr Nasr/ })
    expect(item.getAttribute("aria-disabled")).toBe("true")
    expect(item.textContent).toContain("Not available right now")
    await user.click(item)
    expect(getActingLead()).toBeNull()
    expect(screen.queryByTestId("acting-banner")).toBeNull()
    expect(readStoredLeadId()).toBeNull()
    // The menu is still open (nothing was chosen), and a real lead can still be picked.
    await user.click(screen.getByRole("menuitemradio", { name: /Mr Hassan/ }))
    expect(await screen.findByText("Hassan Y11 Physics")).toBeTruthy()
  })

  it("cannot be chosen through the context either, whatever the menu does", async () => {
    const user = userEvent.setup()
    world.memberships = [marker, schoolLead]
    function Direct() {
      const { choose, memberships } = useActingTeacher()
      return memberships.length ? h("button", { onClick: () => choose(SCHOOL) }, "pick the school lead") : null
    }
    mount("/teacher", h(Direct))
    await user.click(await screen.findByRole("button", { name: "pick the school lead" }))
    expect(getActingLead()).toBeNull()
    expect(readStoredLeadId()).toBeNull()
    expect(screen.queryByTestId("acting-banner")).toBeNull()
    expect(world.calls.every((c) => c.header === undefined)).toBe(true)
  })

  it("drops a remembered choice of such a lead before any request carries it, and says why", async () => {
    world.memberships = [marker, schoolLead]
    storeLeadId(SCHOOL)
    mount()
    expect(await screen.findByText("My Y10 Chemistry")).toBeTruthy()
    expect(screen.getByTestId("acting-notice").textContent).toBe("Dr Nasr's team isn't available to you right now, so you're working as yourself.")
    expect(getActingLead()).toBeNull()
    expect(readStoredLeadId()).toBeNull()
    expect(world.calls.every((c) => c.header === undefined)).toBe(true)
  })

  it("resets, with a notice and the portal home, when the selected lead becomes unavailable", async () => {
    const user = userEvent.setup()
    mount("/teacher/classes")
    await pickLead(user, /Mr Hassan/)
    expect(await screen.findByText("Hassan Y11 Physics")).toBeTruthy()
    // A school comes into the lead's picture; the next read of the list says so.
    world.memberships = [{ ...marker, available: false }, coTeacher]
    await act(async () => {
      await client.invalidateQueries({ queryKey: ["team"] })
    })
    expect((await screen.findByTestId("acting-notice")).textContent).toBe("Mr Hassan's team isn't available to you right now, so you're working as yourself.")
    expect(await screen.findByText("My Y10 Chemistry")).toBeTruthy()
    expect(getActingLead()).toBeNull()
    expect(readStoredLeadId()).toBeNull()
    expect(classesCalls().at(-1)?.header).toBeUndefined()
    expect(screen.getByTestId("where").textContent).toBe("/teacher")
  })
})

describe("the lead's class list being refused", () => {
  /** What the shell does: the class list's error and the path decide, the guard shows one panel. */
  function Shell({ path, children }: { path: string; children?: ReactNode }) {
    const { lead, choose } = useActingTeacher()
    const classes = useQuery({ queryKey: ["teacher", "classes"], queryFn: () => request<{ classes: { label: string }[] }>("/teacher/classes"), retry: false })
    return h(
      "div",
      null,
      h(ActingBanner, { classListError: classes.error, pathname: path }),
      lead
        ? h(ActingGuard, { lead, classListError: classes.error, pathname: path, onSwitchBack: () => choose(null), children: children ?? h("p", null, "page content") })
        : h("p", null, "page content"),
    )
  }
  const bannerCount = () => screen.queryAllByTestId("acting-banner").length

  it("says the lead cannot be reached, once, when the server says team_lead_unavailable", async () => {
    const user = userEvent.setup()
    world.classesRefusal = "team_lead_unavailable"
    mount("/teacher", h(Shell, { path: "/teacher" }))
    await pickLead(user, /Mr Hassan/)
    expect(await screen.findByText("You can't work for Mr Hassan right now")).toBeTruthy()
    expect(screen.queryByText("page content")).toBeNull()
    // One of the two banners is the harness's own (it takes no props); the shell's stood aside.
    expect(bannerCount()).toBe(1)
    // Asked once, not retried.
    expect(classesCalls().filter((c) => c.header === HASSAN)).toHaveLength(1)
  })

  it("gives a role without view_results its own state, not the unavailable panel", async () => {
    const user = userEvent.setup()
    world.memberships = [{ ...marker, effectivePermissions: ["mark"] }, coTeacher]
    world.classesRefusal = "team_permission_denied"
    mount("/teacher", h(Shell, { path: "/teacher" }))
    await pickLead(user, /Mr Hassan/)
    expect(await screen.findByText("Your role can't view Mr Hassan's classes")).toBeTruthy()
    expect(screen.queryByText(/You can't work for/)).toBeNull()
    expect(screen.queryByText("page content")).toBeNull()
    expect(bannerCount()).toBe(1)
  })

  it("lets the caller's own pages through whichever refusal it is, and the page through when nothing is refused", async () => {
    const user = userEvent.setup()
    world.classesRefusal = "team_lead_unavailable"
    mount("/teacher/billing", h(Shell, { path: "/teacher/billing" }))
    await pickLead(user, /Mr Hassan/)
    expect(await screen.findByText("page content")).toBeTruthy()
    expect(screen.queryByText(/You can't work for/)).toBeNull()
    // The banner stays while the page is the caller's own.
    expect(bannerCount()).toBe(2)
  })

  it("shows the page when the class list loads", async () => {
    const user = userEvent.setup()
    mount("/teacher", h(Shell, { path: "/teacher" }))
    await pickLead(user, /Mr Hassan/)
    expect(await screen.findByText("page content")).toBeTruthy()
    expect(bannerCount()).toBe(2)
  })
})
