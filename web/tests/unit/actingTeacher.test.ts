import { readFileSync } from "node:fs"
import { join } from "node:path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { hashKey } from "@tanstack/react-query"
import { ApiError, fetchBlobUrl, isTeamLeadUnavailable, isTeamPermissionDenied, teamDeniedText, request, streamActivity, uploadWithProgress } from "@/lib/api"
import {
  ACTING_TEACHER_HEADER,
  actingQueryHash,
  ADOPTED_ROUTES,
  clearActingLead,
  getActingLead,
  isActingPartitionHash,
  isActingRoute,
  looksLikeTeamLeadUnavailable,
  looksLikeTeamPermissionDenied,
  looksLikeTeamRefusal,
  teamLeadUnavailableMessage,
  readStoredLeadId,
  setActingLead,
  storeLeadId,
  switchActingLead,
  teamPermissionDeniedMessage,
} from "@/lib/actingTeacher"
import { leadAccess, OWN_ACCOUNT_PATH } from "@/lib/actingLeadState"
import { queryClient } from "@/lib/queryClient"
import { shouldPersistQuery } from "@/lib/offline/persistAllowlist"
import { describeQueryFailure } from "@/lib/queryFailure"
import { teacherMutationFailureMessage, classInviteCodeFailureMessage, classPaperActionFailureMessage } from "@/lib/teacherOutcome"

/*
 * The client's side of "an assistant acts for their lead teacher": which requests carry
 * `X-Lemely-Acting-Teacher`, how a refusal reads, and that the query cache never mixes two
 * people's data. `api.ts` reaches `indexedDB` through `endSession` on a refused refresh, which this
 * Node runner does not have, so the same two modules `sessionRefresh.test.ts` mocks are mocked here.
 */
vi.mock("@/lib/offline/queryPersister", () => ({ persister: { removeClient: () => Promise.resolve() } }))
vi.mock("@/lib/offline/uploadQueue", () => ({ clearUploadQueue: () => Promise.resolve() }))

const LEAD = { leadId: "11111111-1111-4111-8111-111111111111", leadName: "Mr Hassan" }
const OTHER = { leadId: "22222222-2222-4222-8222-222222222222", leadName: "Ms Ahmed" }

/** A route template with sample ids filled in: `/classes/:id/roster` becomes `/classes/c1/roster`. */
const sample = (template: string) => template.replace(/:[a-z]+/g, "abc123")

describe("the adopted-route allow-list", () => {
  it("allows every route the adoption table lists, with real-looking ids", () => {
    for (const template of ADOPTED_ROUTES) {
      expect(isActingRoute(sample(template)), template).toBe(true)
    }
  })

  // An exact snapshot. The list decides which requests carry the acting header, so changing it
  // should be a deliberate edit to this test as well, in the same diff a reviewer reads. The
  // pytest `tests/test_acting_routes_parity.py` checks the same list against the backend's adopted
  // routes, so a backend adoption that is not mirrored here fails there.
  it("is exactly this list", () => {
    expect([...ADOPTED_ROUTES]).toEqual([
    // teacher.py
    "/papers/upload",
    "/papers",
    "/papers/:id/regrade",
    "/papers/deleted",
    "/papers/:id",
    "/papers/:id/restore",
    "/papers/:id/preview",
    "/grading/queue",
    "/quizzes/pools",
    "/quizzes/preview",
    "/quizzes/generate",
    "/teacher/overview",
    "/teacher/students/:id",
    "/teacher/at-risk",
    "/teacher/at-risk/:id/acknowledge",
    "/teacher/at-risk/:id/acknowledge/:reason",
    // classes.py
    "/teacher/classes",
    "/classes",
    "/classes/:id",
    "/classes/:id/analytics",
    "/classes/:id/roster",
    "/classes/:id/enroll",
    "/classes/:id/students/:id",
    "/classes/:id/papers",
    "/classes/:id/papers/:id/unshare",
    "/school/classes/:id/invite-code",
    // quiz.py
    "/teacher/quizzes",
    "/teacher/quizzes/pool-count",
    "/teacher/quizzes/:id",
    "/teacher/quizzes/:id/status",
    "/teacher/quizzes/:id/questions/generate",
    "/teacher/quizzes/:id/questions/:ref",
    "/teacher/quizzes/:id/assignments",
    "/teacher/quizzes/:id/assignments/:id",
    "/teacher/quizzes/:id/assignments/:id/results",
    // review.py
    "/teacher/review",
    "/teacher/review/bulk-approve",
    "/teacher/review/:id",
    "/teacher/review/:id/crop",
    "/teacher/review/:id/resolve",
    "/teacher/review/:id/dismiss",
    // announcements.py
    "/teacher/announcements",
    "/teacher/announcements/:id",
    ])
  })

  it("has no duplicate or malformed entry", () => {
    expect(new Set(ADOPTED_ROUTES).size).toBe(ADOPTED_ROUTES.length)
    for (const template of ADOPTED_ROUTES) {
      expect(template.startsWith("/")).toBe(true)
      expect(template.includes("/api")).toBe(false)
      expect(template.includes("?")).toBe(false)
    }
  })

  // The routes that must NEVER carry the header. Every team route answers 403 `team_lead_only` to a
  // header naming someone else, billing is the caller's own, and the rest are not adopted.
  const NEVER = [
    "/teacher/team/memberships",
    "/teacher/team/seats",
    "/teacher/team/capacity",
    "/teacher/team/assistants",
    "/teacher/team/assistants/redeem",
    "/teacher/team/assistants/invites",
    "/teacher/team/invites",
    "/teacher/team/members/abc123/cap",
    "/billing/summary",
    "/billing/plans",
    "/billing/checkout",
    "/billing/receipts",
    "/billing/usage/history",
    "/billing/auto-topup",
    "/auth/login",
    "/auth/refresh",
    "/auth/logout",
    "/auth/signup",
    "/me/profile",
    "/me/devices",
    "/me/devices/abc123",
    "/notifications",
    "/notifications/counts",
    "/schemes",
    "/quizzes/topics",
    "/invites/7HKPX2WCQY",
    "/invites/7HKPX2WCQY/redeem",
    "/student/classes/join",
    "/student/attempts/deleted",
    "/tutor/profile",
    "/tutoring/sessions",
    "/admin/billing/plans",
    "/school/teachers/invite",
  ]

  it.each(NEVER)("does not allow %s", (path) => {
    expect(isActingRoute(path)).toBe(false)
  })

  it("ignores the query string and fragment when deciding, in both directions", () => {
    expect(isActingRoute("/teacher/classes?limit=5")).toBe(true)
    expect(isActingRoute("/teacher/review?status=open&limit=1")).toBe(true)
    // A path that merely mentions an adopted one in its query is still a team route.
    expect(isActingRoute("/teacher/team/memberships?next=/teacher/classes")).toBe(false)
    expect(isActingRoute("/billing/summary#/teacher/classes")).toBe(false)
  })

  it("matches whole paths only, not prefixes or look-alikes", () => {
    expect(isActingRoute("/teacher/classes/extra/segments")).toBe(false)
    expect(isActingRoute("/papers/abc123/preview/extra")).toBe(false)
    expect(isActingRoute("/papers/abc123/share")).toBe(false)
    expect(isActingRoute("/teacher/quizzes/abc123/unknown")).toBe(false)
    expect(isActingRoute("/teacherclasses")).toBe(false)
    expect(isActingRoute("/x/teacher/classes")).toBe(false)
    expect(isActingRoute("")).toBe(false)
    expect(isActingRoute("/")).toBe(false)
  })

  it("never lets a `:param` segment swallow a slash", () => {
    expect(isActingRoute("/classes/a/b")).toBe(false)
    expect(isActingRoute("/classes//roster")).toBe(false)
  })

  /*
   * Drift guard: the app's teacher hooks are the callers of these routes. When someone adds an
   * endpoint call there, it has to be on `ADOPTED_ROUTES` or named here as deliberately not
   * adopted. A silent miss would send an adopted route out as the assistant, with their own empty
   * data, and a silent hit on a team route would be a 403 for everyone.
   */
  it("classifies every path the teacher hooks call", () => {
    const NOT_ADOPTED = new Set(["/schemes"])
    const source = readFileSync(join(import.meta.dirname, "../../src/lib/hooks/useTeacherApi.ts"), "utf8")
    const call = /(?:request|fetchBlobUrl)\s*(?:<[^()]*?>)?\(\s*(?:`([^`]*)`|"([^"]*)")/g
    const paths = new Set<string>()
    for (const match of source.matchAll(call)) {
      const raw = (match[1] ?? match[2] ?? "").split("?")[0] ?? ""
      paths.add(raw.replace(/\$\{[^}]*\}/g, "abc123").replace(/\$\{.*$/, ""))
    }
    expect(paths.size).toBeGreaterThan(30)
    const unclassified = [...paths].filter((p) => !isActingRoute(p) && !NOT_ADOPTED.has(p))
    expect(unclassified).toEqual([])
    // And the exclusions really are excluded, so the set above cannot go stale in the other direction.
    for (const p of NOT_ADOPTED) expect(isActingRoute(p)).toBe(false)
  })
})

/* ── The header on the wire ─────────────────────────────────────────────────────────────────── */

let fetchMock: ReturnType<typeof vi.fn>

const ok = (body: unknown = {}) =>
  new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } })

/** The acting header of the nth fetch call, or `undefined` when it was not sent. */
function sentHeader(n = 0): string | undefined {
  const init = fetchMock.mock.calls[n]?.[1] as RequestInit | undefined
  const headers = (init?.headers ?? {}) as Record<string, string>
  return headers[ACTING_TEACHER_HEADER]
}

beforeEach(() => {
  fetchMock = vi.fn(async () => ok())
  vi.stubGlobal("fetch", fetchMock)
  // `localStorage` is read for the bearer token; there is no session in these tests.
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => {}, removeItem: () => {} })
  clearActingLead()
})

afterEach(() => {
  clearActingLead()
  queryClient.clear()
  vi.unstubAllGlobals()
})

describe("request()", () => {
  it("sends the header on an adopted route while acting for a lead", async () => {
    setActingLead(LEAD)
    await request("/teacher/classes")
    expect(sentHeader()).toBe(LEAD.leadId)
  })

  it("sends no header when nobody is being acted for", async () => {
    await request("/teacher/classes")
    expect(sentHeader()).toBeUndefined()
  })

  it("sends no header on team routes while acting", async () => {
    setActingLead(LEAD)
    for (const path of ["/teacher/team/memberships", "/teacher/team/seats", "/teacher/team/assistants/redeem"]) {
      fetchMock.mockClear()
      await request(path, { method: "POST", body: "{}" })
      expect(sentHeader(), path).toBeUndefined()
    }
  })

  it("sends no header on billing routes while acting", async () => {
    setActingLead(LEAD)
    for (const path of ["/billing/summary", "/billing/plans", "/billing/checkout", "/billing/receipts?limit=20"]) {
      fetchMock.mockClear()
      await request(path)
      expect(sentHeader(), path).toBeUndefined()
    }
  })

  it("sends no header on auth, account and device routes while acting", async () => {
    setActingLead(LEAD)
    for (const path of ["/auth/login", "/auth/refresh", "/me/profile", "/me/devices", "/notifications/counts"]) {
      fetchMock.mockClear()
      await request(path)
      expect(sentHeader(), path).toBeUndefined()
    }
  })

  it("honours asSelf on an adopted route, for own-account screens that read one", async () => {
    setActingLead(LEAD)
    await request("/teacher/classes", { asSelf: true })
    expect(sentHeader()).toBeUndefined()
  })

  it("keeps a caller's own headers and strips asSelf before fetch", async () => {
    setActingLead(LEAD)
    await request("/teacher/review/bulk-approve", { method: "POST", headers: { "X-Test": "1" }, asSelf: false })
    const init = fetchMock.mock.calls[0]?.[1] as Record<string, unknown>
    expect((init.headers as Record<string, string>)["X-Test"]).toBe("1")
    expect(sentHeader()).toBe(LEAD.leadId)
    expect("asSelf" in init).toBe(false)
  })

  it("sends the header that was current when the request started, even if the lead changes mid-flight", async () => {
    setActingLead(LEAD)
    const pending = request("/teacher/classes")
    setActingLead(OTHER)
    await pending
    expect(sentHeader()).toBe(LEAD.leadId)
  })

  it("stops sending it the moment acting stops", async () => {
    setActingLead(LEAD)
    await request("/teacher/classes")
    clearActingLead()
    fetchMock.mockClear()
    await request("/teacher/classes")
    expect(sentHeader()).toBeUndefined()
  })
})

describe("the other transports", () => {
  it("fetchBlobUrl sends it for a paper preview and a review crop, and not elsewhere", async () => {
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:x" }))
    fetchMock.mockImplementation(async () => new Response(new Blob(["x"]), { status: 200 }))
    setActingLead(LEAD)
    await fetchBlobUrl("/papers/abc123/preview")
    await fetchBlobUrl("/teacher/review/abc123/crop")
    await fetchBlobUrl("/billing/receipts/abc123/pdf")
    expect(sentHeader(0)).toBe(LEAD.leadId)
    expect(sentHeader(1)).toBe(LEAD.leadId)
    expect(sentHeader(2)).toBeUndefined()
  })

  it("streamActivity sends it on an adopted route and not on a billing one", async () => {
    fetchMock.mockImplementation(async () => new Response(null, { status: 200 }))
    setActingLead(LEAD)
    for await (const _ of streamActivity("/papers/abc123/regrade")) void _
    for await (const _ of streamActivity("/billing/checkout")) void _
    expect(sentHeader(0)).toBe(LEAD.leadId)
    expect(sentHeader(1)).toBeUndefined()
  })

  it("uploadWithProgress sends it for a paper upload and not for a student scan", async () => {
    const sent: Record<string, string>[] = []
    class FakeXHR {
      upload = { onprogress: null, onload: null }
      onload: (() => void) | null = null
      status = 200
      statusText = "OK"
      responseText = "{}"
      private headers: Record<string, string> = {}
      open() {}
      setRequestHeader(k: string, v: string) {
        this.headers[k] = v
      }
      getResponseHeader() {
        return null
      }
      send() {
        sent.push(this.headers)
        queueMicrotask(() => this.onload?.())
      }
    }
    vi.stubGlobal("XMLHttpRequest", FakeXHR)
    setActingLead(LEAD)
    await uploadWithProgress("/papers/upload", new FormData())
    await uploadWithProgress("/student/correct", new FormData())
    expect(sent[0]?.[ACTING_TEACHER_HEADER]).toBe(LEAD.leadId)
    expect(sent[1]?.[ACTING_TEACHER_HEADER]).toBeUndefined()
  })
})

/* ── The refusal ────────────────────────────────────────────────────────────────────────────── */

const denied = () =>
  new Response(
    JSON.stringify({
      detail: { code: "team_permission_denied", message: "You do not have permission to do this for that teacher." },
    }),
    { status: 403, headers: { "Content-Type": "application/json" } },
  )

describe("a refused action", () => {
  it("reads as the role's own sentence, naming the lead", async () => {
    setActingLead(LEAD)
    fetchMock.mockImplementation(async () => denied())
    const err = await request("/classes", { method: "POST", body: "{}" }).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).message).toBe("Your role on Mr Hassan's team doesn't allow this.")
    // The sentence the client wrote, for outcome modules, apart from anything the server said.
    expect((err as ApiError).readerMessage).toBe("Your role on Mr Hassan's team doesn't allow this.")
    expect((err as ApiError).status).toBe(403)
    // The server's structured detail is still there for anything that needs the code.
    expect(isTeamPermissionDenied(err)).toBe(true)
  })

  it("is what every screen-level outcome helper says, instead of its own 403 wording", async () => {
    setActingLead(LEAD)
    fetchMock.mockImplementation(async () => denied())
    const err = await request("/teacher/review/abc123/resolve", { method: "POST", body: "{}" }).catch((e: unknown) => e)
    const sentence = "Your role on Mr Hassan's team doesn't allow this."
    expect(describeQueryFailure(err)).toBe(sentence)
    expect(teacherMutationFailureMessage(err)).toBe(sentence)
    // These two used to turn any 403 into "this class is no longer available to you".
    expect(classInviteCodeFailureMessage(err)).toBe(sentence)
    expect(classPaperActionFailureMessage(err)).toBe(sentence)
  })

  it("is worded without a name when the lead's name is not known yet", async () => {
    setActingLead({ leadId: LEAD.leadId, leadName: null })
    fetchMock.mockImplementation(async () => denied())
    const err = await request("/classes", { method: "POST", body: "{}" }).catch((e: unknown) => e)
    expect((err as ApiError).message).toBe("Your role on this team doesn't allow this.")
  })

  it("leaves an ordinary 403 as the plain status line for everyone else", async () => {
    fetchMock.mockImplementation(async () => new Response(JSON.stringify({ detail: { code: "email_unverified" } }), { status: 403 }))
    const err = await request("/student/correct", { method: "POST", body: "{}" }).catch((e: unknown) => e)
    expect((err as ApiError).message).toMatch(/^403\b/)
    expect(isTeamPermissionDenied(err)).toBe(false)
    expect((err as ApiError).readerMessage).toBeUndefined()
    expect(describeQueryFailure(err)).toBe("You don't have access to this.")
  })

  it("leaves other 403s alone while acting", async () => {
    setActingLead(LEAD)
    fetchMock.mockImplementation(async () => new Response(JSON.stringify({ detail: "Caller does not own class" }), { status: 403 }))
    const err = await request("/classes/abc123").catch((e: unknown) => e)
    expect((err as ApiError).message).toBe("Caller does not own class")
    expect(isTeamPermissionDenied(err)).toBe(false)
  })

  it("has a sentence even before the lead's name is known", () => {
    expect(teamPermissionDeniedMessage(null)).toBe("Your role on this team doesn't allow this.")
  })
})

/* ── The cache ──────────────────────────────────────────────────────────────────────────────── */

describe("the query cache is partitioned by who is being acted for", () => {
  const KEY = ["teacher", "classes"] as const

  it("hashes exactly as the default when not acting", () => {
    expect(actingQueryHash(KEY)).toBe(hashKey(KEY))
    expect(isActingPartitionHash(actingQueryHash(KEY))).toBe(false)
  })

  it("gives each lead, and the caller, their own entry for the same key", () => {
    queryClient.setQueryData(KEY, { owner: "me" })
    setActingLead(LEAD)
    expect(queryClient.getQueryData(KEY)).toBeUndefined()
    queryClient.setQueryData(KEY, { owner: "hassan" })
    setActingLead(OTHER)
    expect(queryClient.getQueryData(KEY)).toBeUndefined()
    queryClient.setQueryData(KEY, { owner: "ahmed" })

    expect(queryClient.getQueryData(KEY)).toEqual({ owner: "ahmed" })
    setActingLead(LEAD)
    expect(queryClient.getQueryData(KEY)).toEqual({ owner: "hassan" })
    clearActingLead()
    expect(queryClient.getQueryData(KEY)).toEqual({ owner: "me" })
  })

  it("keeps a lead's data out of the caller's view after switching back", () => {
    setActingLead(LEAD)
    queryClient.setQueryData(["teacher", "overview"], { students: 120 })
    clearActingLead()
    expect(queryClient.getQueryData(["teacher", "overview"])).toBeUndefined()
  })

  it("leaves the membership list alone, so the switcher keeps its options", () => {
    const key = ["team", "memberships"]
    queryClient.setQueryData(key, [{ teacherId: LEAD.leadId }])
    setActingLead(LEAD)
    expect(queryClient.getQueryData(key)).toEqual([{ teacherId: LEAD.leadId }])
    expect(actingQueryHash(key)).toBe(hashKey(key))
  })

  it("never writes a lead's data to disk, whatever the key", () => {
    const own = { queryKey: KEY, queryHash: actingQueryHash(KEY), state: { status: "success" } }
    expect(shouldPersistQuery(own)).toBe(true)
    setActingLead(LEAD)
    const lead = { queryKey: KEY, queryHash: actingQueryHash(KEY), state: { status: "success" } }
    expect(shouldPersistQuery(lead)).toBe(false)
    // Even the one key the allow-list otherwise persists for a teacher.
    expect(shouldPersistQuery({ ...lead, queryKey: ["me", "profile"], queryHash: actingQueryHash(["me", "profile"]) })).toBe(false)
  })
})

describe("a refetch of an inactive entry cannot cross identities", () => {
  const KEY = ["teacher", "classes"] as const
  const load = () => queryClient.fetchQuery({ queryKey: KEY, queryFn: () => request<{ owner: string }>("/teacher/classes"), staleTime: 0 })

  beforeEach(() => {
    fetchMock.mockImplementation(async (_url: string, init?: RequestInit) => {
      const lead = ((init?.headers ?? {}) as Record<string, string>)[ACTING_TEACHER_HEADER]
      return ok({ owner: lead ? `lead:${lead}` : "me" })
    })
  })

  it("leaves no entry for another identity to refetch, and the caller's view never holds a lead's data", async () => {
    // The caller's own list, cached.
    expect(await load()).toEqual({ owner: "me" })
    // Switch to a lead the way the provider does, and load theirs.
    switchActingLead(queryClient, LEAD)
    expect(await load()).toEqual({ owner: `lead:${LEAD.leadId}` })

    // Something refetches every entry, active or not (`type: "all"`). With the caller's entry gone
    // there is nothing for it to fetch as the lead and write under the caller's key.
    fetchMock.mockClear()
    await queryClient.refetchQueries({ type: "all" })
    for (const call of fetchMock.mock.calls) {
      expect(((call[1] as RequestInit).headers as Record<string, string>)[ACTING_TEACHER_HEADER]).toBe(LEAD.leadId)
    }

    // Back to the caller: their entry was dropped, not poisoned.
    switchActingLead(queryClient, null)
    expect(queryClient.getQueryData(KEY)).toBeUndefined()
    expect(await load()).toEqual({ owner: "me" })
  })

  it("drops the previous lead's entries when the next lead is picked, and keeps the own-account roots", async () => {
    queryClient.setQueryData(["team", "memberships"], ["kept"])
    switchActingLead(queryClient, LEAD)
    queryClient.setQueryData(KEY, { owner: "hassan" })
    switchActingLead(queryClient, OTHER)
    expect(queryClient.getQueryData(KEY)).toBeUndefined()
    switchActingLead(queryClient, LEAD)
    expect(queryClient.getQueryData(KEY)).toBeUndefined()
    expect(queryClient.getQueryData(["team", "memberships"])).toEqual(["kept"])
  })

  it("cancels what is in flight for the old identity before it switches", async () => {
    let aborted = false
    fetchMock.mockImplementation(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            aborted = true
            reject(new DOMException("aborted", "AbortError"))
          })
        }),
    )
    const pending = queryClient.fetchQuery({ queryKey: KEY, queryFn: ({ signal }) => request("/teacher/classes", { signal }) }).catch(() => "cancelled")
    await Promise.resolve()
    switchActingLead(queryClient, LEAD)
    expect(await pending).toBe("cancelled")
    expect(aborted).toBe(true)
  })
})

/* ── The tab's remembered choice ────────────────────────────────────────────────────────────── */

describe("remembering the choice for this tab", () => {
  it("round-trips through sessionStorage", () => {
    const store = new Map<string, string>()
    vi.stubGlobal("window", {
      sessionStorage: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
        removeItem: (k: string) => void store.delete(k),
      },
    })
    expect(readStoredLeadId()).toBeNull()
    storeLeadId(LEAD.leadId)
    expect(readStoredLeadId()).toBe(LEAD.leadId)
    storeLeadId(null)
    expect(readStoredLeadId()).toBeNull()
  })

  it("survives storage that throws (private windows, blocked site data)", () => {
    const boom = () => {
      throw new Error("denied")
    }
    vi.stubGlobal("window", { sessionStorage: { getItem: boom, setItem: boom, removeItem: boom } })
    expect(readStoredLeadId()).toBeNull()
    expect(() => storeLeadId(LEAD.leadId)).not.toThrow()
    expect(() => storeLeadId(null)).not.toThrow()
    expect(() => clearActingLead()).not.toThrow()
  })

  it("survives there being no window at all", () => {
    expect(readStoredLeadId()).toBeNull()
    expect(() => storeLeadId(LEAD.leadId)).not.toThrow()
  })

  it("is forgotten when acting is cleared, so the next person on the tab starts as themselves", () => {
    const store = new Map<string, string>([["lemely.acting-lead", LEAD.leadId]])
    vi.stubGlobal("window", {
      sessionStorage: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
        removeItem: (k: string) => void store.delete(k),
      },
    })
    setActingLead(LEAD)
    clearActingLead()
    expect(getActingLead()).toBeNull()
    expect(readStoredLeadId()).toBeNull()
  })
})

/* ── A lead that cannot be worked for ───────────────────────────────────────────────────────── */

describe("the two refusals an assistant can get", () => {
  const denied403 = () => new ApiError(403, "x", { code: "team_permission_denied", message: "x" })
  const unavailable403 = () => new ApiError(403, "x", { code: "team_lead_unavailable", message: "x" })
  const hasView = { permissions: ["mark", "view_results"] as never[] }
  const noView = { permissions: ["mark"] as never[] }

  it("recognises each by shape, whatever built the error", () => {
    expect(looksLikeTeamPermissionDenied(denied403())).toBe(true)
    expect(looksLikeTeamLeadUnavailable(unavailable403())).toBe(true)
    expect(looksLikeTeamPermissionDenied(unavailable403())).toBe(false)
    expect(looksLikeTeamLeadUnavailable(denied403())).toBe(false)
    expect(looksLikeTeamRefusal(denied403())).toBe(true)
    expect(looksLikeTeamRefusal(unavailable403())).toBe(true)
    expect(looksLikeTeamLeadUnavailable({ status: 403, detail: { code: "team_lead_unavailable" } })).toBe(true)
    for (const other of [new ApiError(403, "x", { code: "email_unverified" }), new ApiError(403, "x", "Caller does not own class"), new ApiError(404, "x", { code: "team_lead_unavailable" }), null, "team_lead_unavailable"]) {
      expect(looksLikeTeamRefusal(other)).toBe(false)
    }
  })

  it("words the unavailable refusal as the lead's, and keeps it apart from the role's", async () => {
    setActingLead(LEAD)
    fetchMock.mockImplementation(async () => new Response(JSON.stringify({ detail: { code: "team_lead_unavailable", message: "x" } }), { status: 403 }))
    const err = await request("/teacher/classes").catch((e: unknown) => e)
    expect(isTeamLeadUnavailable(err)).toBe(true)
    expect(isTeamPermissionDenied(err)).toBe(false)
    expect((err as ApiError).message).toBe("Mr Hassan's team isn't available to you right now.")
    expect((err as ApiError).readerMessage).toBe("Mr Hassan's team isn't available to you right now.")
    expect(teamDeniedText(err)).toBe("Mr Hassan's team isn't available to you right now.")
    expect(describeQueryFailure(err)).toBe("Mr Hassan's team isn't available to you right now.")
    expect(teacherMutationFailureMessage(err)).toBe("Mr Hassan's team isn't available to you right now.")
    expect(classInviteCodeFailureMessage(err)).toBe("Mr Hassan's team isn't available to you right now.")
    expect(teamLeadUnavailableMessage(null)).toBe("This team isn't available to you right now.")
  })

  it("is 'unavailable' when the lead's class list is refused as unavailable, on the lead's pages", () => {
    for (const path of ["/teacher", "/teacher/classes/c1/roster", "/teacher/quizzes"]) {
      expect(leadAccess(hasView, unavailable403(), path), path).toBe("unavailable")
      // Whatever the role holds: a lead that cannot be reached is not about the role.
      expect(leadAccess(noView, unavailable403(), path), path).toBe("unavailable")
    }
  })

  it("is 'no-view' when the role lacks view_results and the class list is refused as denied", () => {
    expect(leadAccess(noView, denied403(), "/teacher")).toBe("no-view")
    expect(leadAccess(noView, denied403(), "/teacher/classes")).toBe("no-view")
  })

  it("treats a refusal that contradicts the role as the lead being unavailable until the list catches up", () => {
    // The role has view_results, yet the server says no: access changed after the list loaded.
    expect(leadAccess(hasView, denied403(), "/teacher")).toBe("unavailable")
  })

  it("is fine when not acting, when the failure is anything else, or when nothing failed", () => {
    expect(leadAccess(null, unavailable403(), "/teacher")).toBe("ok")
    expect(leadAccess(null, denied403(), "/teacher")).toBe("ok")
    expect(leadAccess(hasView, new ApiError(500, "x"), "/teacher")).toBe("ok")
    expect(leadAccess(hasView, new ApiError(0, "x"), "/teacher")).toBe("ok")
    expect(leadAccess(hasView, null, "/teacher")).toBe("ok")
  })

  it("leaves the caller's own pages reachable under either refusal", () => {
    for (const path of ["/teacher/team", "/teacher/billing", "/teacher/billing/plans", "/teacher/settings/profile", "/teacher/notifications", "/teacher/tutoring/availability"]) {
      expect(OWN_ACCOUNT_PATH.test(path), path).toBe(true)
      expect(leadAccess(hasView, unavailable403(), path), path).toBe("ok")
      expect(leadAccess(noView, denied403(), path), path).toBe("ok")
    }
    for (const path of ["/teacher/teamwork", "/teacher/billingx", "/teacher/classes", "/teacher"]) {
      expect(OWN_ACCOUNT_PATH.test(path), path).toBe(false)
    }
  })

  it("is never asked again: a server failure is retried once, neither refusal ever", () => {
    const retry = queryClient.getDefaultOptions().queries?.retry as (count: number, error: Error) => boolean
    expect(typeof retry).toBe("function")
    expect(retry(0, new ApiError(500, "x"))).toBe(true)
    expect(retry(0, new ApiError(0, "x"))).toBe(true)
    expect(retry(1, new ApiError(500, "x"))).toBe(false)
    expect(retry(0, denied403())).toBe(false)
    expect(retry(0, unavailable403())).toBe(false)
  })
})

