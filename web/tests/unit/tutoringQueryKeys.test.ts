import { readFileSync } from "node:fs"
import { join } from "node:path"
import {
  MutationObserver,
  QueryClient,
  QueryObserver,
  dehydrate,
  onlineManager,
} from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError, request } from "@/lib/api"
import { isPersistableQueryKey, shouldPersistQuery } from "@/lib/offline/persistAllowlist"
import { tutoringKeys } from "@/lib/tutoring/queryKeys"
import * as tutoringApi from "@/lib/hooks/useTutoringApi"
import {
  AUDITED_READ,
  blockInvalidationKeys,
  installAccessEndedGuard,
  tutoringQueryString,
} from "@/lib/hooks/useTutoringApi"

/*
 * T11: one react-query hook per tutoring route (SPEC §b.2 / §c.1), query keys
 * kept out of the persisted cache (SPEC §b.5, F32), and the one cache rule the
 * tutor's student-detail screen needs (T20: 403 `access_ended` drops the cached
 * detail).
 *
 * The expected side of every comparison is read out of `docs/tutoring/SPEC.md`
 * as text, never written out again here: §c.1's `("METHOD", "/path"): GUARD,`
 * rows are the spine (exactly 70, asserted before anything is compared against
 * them), §b.2's route tables cross-check them, and the hooks file is read as
 * text and scanned for the `call<T>("METHOD", "/path")` each hook makes.
 *
 * The hooks are also CALLED here, as plain functions: `useQuery` and
 * `useMutation` are replaced by identity functions, so a hook returns the
 * options it would have handed to react-query, and `useQueryClient` returns
 * whatever `harness.client` is. That runs every query function, mutation
 * function and `onSuccess` for real, without a DOM or a React renderer.
 */

const harness = vi.hoisted(() => ({ client: undefined as unknown }))

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>()
  return { ...actual, request: vi.fn() }
})

vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query")>()
  return {
    ...actual,
    useQuery: (options: unknown) => options,
    useMutation: (options: unknown) => options,
    useQueryClient: () => harness.client,
  }
})

/** What a hook returns once `useQuery` and `useMutation` are identities. */
interface HookOptions {
  queryKey?: readonly unknown[]
  queryFn?: () => Promise<unknown>
  mutationFn?: (variables: unknown) => Promise<unknown>
  onSuccess?: (data: unknown, variables: unknown, ...rest: unknown[]) => unknown
  networkMode?: string
  staleTime?: number
  gcTime?: number
  refetchOnMount?: string
  refetchOnReconnect?: boolean
  retry?: (failureCount: number, error: Error) => boolean
}

type HookFn = (...args: unknown[]) => HookOptions

/**
 * A refusal that arrives on a later macrotask, like a real response. A mock that
 * rejects on a microtask would let a refetch loop starve the timers the tests
 * wait on, and hang the run instead of failing it.
 */
function refuseLater(error: Error): () => Promise<never> {
  return () => new Promise((_resolve, reject) => setTimeout(() => reject(error), 1))
}

/** Call the exported hook `name` as a plain function. */
function runHook(name: string, ...args: unknown[]): HookOptions {
  const hook = (tutoringApi as unknown as Record<string, HookFn>)[name]
  return hook(...args)
}

const ROOT = join(import.meta.dirname, "..", "..", "..")
const SPEC = readFileSync(join(ROOT, "docs", "tutoring", "SPEC.md"), "utf8")
const HOOKS_SOURCE = readFileSync(
  join(ROOT, "web", "src", "lib", "hooks", "useTutoringApi.ts"),
  "utf8",
)

const SPEC_ROUTE_COUNT = 70

interface SpecRoute {
  method: string
  path: string
  guard: string
}

/** Every `("METHOD", "/path"): GUARD,` row between `### c.1` and `### c.2`
 * (the section's first code block is the guard constants, the second the rows). */
function parseSpecRoutes(spec: string): SpecRoute[] {
  const start = spec.indexOf("### c.1")
  const end = spec.indexOf("### c.2")
  expect(start, "SPEC section c.1 not found").toBeGreaterThan(-1)
  expect(end, "SPEC section c.2 not found").toBeGreaterThan(start)
  const rows: SpecRoute[] = []
  for (const line of spec.slice(start, end).split("\n")) {
    const match = /^\s*\("(GET|POST|PUT|PATCH|DELETE)",\s*"([^"]+)"\):\s*([A-Z_]+),\s*$/.exec(line)
    if (match) rows.push({ method: match[1], path: match[2], guard: match[3] })
  }
  return rows
}

function camelToSnake(name: string): string {
  return name.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`)
}

function snakeToCamel(name: string): string {
  return name.replace(/_([a-z])/g, (_m, c: string) => c.toUpperCase())
}

/**
 * A route as `METHOD /path` with its parameter NAMES kept, in order. The SPEC's
 * `{tutor_id}` stays `{tutor_id}`; a hook's `${encodeURIComponent(tutorId)}`
 * becomes `{tutor_id}`. A path id that is not wrapped in `encodeURIComponent`
 * becomes `{BARE}`, which no SPEC path contains, so it never matches.
 */
function shape(method: string, path: string): string {
  const named = path
    .replace(/^\/api/, "")
    .replace(/\$\{encodeURIComponent\((\w+)\)\}/g, (_m, name: string) => `{${camelToSnake(name)}}`)
    .replace(/\$\{[^}]*\}/g, "{BARE}")
  return `${method} ${named}`
}

/** §b.2's route tables: `| P1 | \`GET /api/public/tutors\` **C** | … |`. */
function parseB2Routes(spec: string): string[] {
  const start = spec.indexOf("### b.2 Routes")
  const end = spec.indexOf("### b.3 DTOs")
  expect(start).toBeGreaterThan(-1)
  expect(end).toBeGreaterThan(start)
  const shapes: string[] = []
  for (const line of spec.slice(start, end).split("\n")) {
    if (!line.startsWith("|")) continue
    const cells = line.split(/(?<!\\)\|/).map((cell) => cell.trim())
    if (!/^(?:P|SP|S|T|PA|R|B|A)\d+$/.test(cells[1] ?? "")) continue
    const route = /`(GET|POST|PUT|PATCH|DELETE) (\/api\/\S+?)`/.exec(cells[2] ?? "")
    expect(route, `no route in row ${cells[1]}`).not.toBeNull()
    shapes.push(shape(route![1], route![2]))
  }
  return shapes
}

interface Hook {
  name: string
  body: string
  calls: { method: string; path: string }[]
  queryKeys: string[]
}

/** Every `export function useXxx` in the hooks file, with the API calls and
 * query-key factories its body names. */
function scanHooks(source: string): Hook[] {
  const chunks = source.split(/^export function /m).slice(1)
  const hooks: Hook[] = []
  for (const chunk of chunks) {
    const name = /^(\w+)/.exec(chunk)?.[1] ?? ""
    if (!/^use[A-Z]/.test(name)) continue
    const calls = [...chunk.matchAll(/\bcall<[^(]*?>\(\s*"(GET|POST|PUT|PATCH|DELETE)",\s*([`"])(.*?)\2/g)]
    const keys = [...chunk.matchAll(/\bqueryKey:\s*tutoringKeys\.(\w+)/g)]
    hooks.push({
      name,
      body: chunk,
      calls: calls.map((c) => ({ method: c[1], path: c[3] })),
      queryKeys: keys.map((k) => k[1]),
    })
  }
  return hooks
}

const SPEC_ROUTES = parseSpecRoutes(SPEC)
const HOOKS = scanHooks(HOOKS_SOURCE)

describe("SPEC route list (the spine)", () => {
  it("parses exactly 70 rows from §c.1", () => {
    expect(SPEC_ROUTES.length).toBe(SPEC_ROUTE_COUNT)
  })

  it("has no repeated (method, path) row", () => {
    const shapes = SPEC_ROUTES.map((r) => shape(r.method, r.path))
    expect(new Set(shapes).size).toBe(SPEC_ROUTE_COUNT)
  })

  it("agrees with the per-guard tally §b.2 states in prose", () => {
    const tally = /\*\*Route count: 70\*\* \(([^)]*)\)/.exec(SPEC)
    expect(tally, "Route count sentence not found").not.toBeNull()
    const stated = new Map<string, number>()
    for (const part of tally![1].split(",")) {
      const m = /^\s*([A-Z_]+) (\d+)\s*$/.exec(part)
      expect(m, `unreadable tally part ${part}`).not.toBeNull()
      stated.set(m![1], Number(m![2]))
    }
    const parsed = new Map<string, number>()
    for (const row of SPEC_ROUTES) parsed.set(row.guard, (parsed.get(row.guard) ?? 0) + 1)
    expect(stated.size).toBe(8)
    expect(Object.fromEntries(parsed)).toEqual(Object.fromEntries(stated))
  })

  it("lists the same routes as the §b.2 tables", () => {
    const b2 = parseB2Routes(SPEC)
    expect(b2.length).toBe(SPEC_ROUTE_COUNT)
    expect([...b2].sort()).toEqual(SPEC_ROUTES.map((r) => shape(r.method, r.path)).sort())
  })
})

describe("every SPEC route has exactly one hook", () => {
  it("scans 70 hooks, each making exactly one API call", () => {
    expect(HOOKS.length).toBe(SPEC_ROUTE_COUNT)
    for (const hook of HOOKS) {
      expect(hook.calls.length, `${hook.name} must make exactly one call`).toBe(1)
    }
  })

  it("covers each (method, path) once, with nothing extra", () => {
    const expected = SPEC_ROUTES.map((r) => shape(r.method, r.path)).sort()
    const actual = HOOKS.flatMap((h) => h.calls.map((c) => shape(c.method, `/api${c.path}`))).sort()
    const missing = expected.filter((s) => !actual.includes(s))
    const extra = actual.filter((s) => !expected.includes(s))
    expect({ missing, extra }).toEqual({ missing: [], extra: [] })
    expect(new Set(actual).size).toBe(actual.length)
  })

  it("gives no two hooks one name", () => {
    expect(new Set(HOOKS.map((h) => h.name)).size).toBe(HOOKS.length)
  })

  it("installs the access_ended guard in the hook that reads T20", () => {
    const t20 = HOOKS.filter((h) => h.calls[0]?.path.startsWith("/tutor/students/"))
    expect(t20.length).toBe(1)
    expect(t20[0].body).toContain("installAccessEndedGuard(")
  })

  it("wraps every path id in encodeURIComponent", () => {
    const withIds = HOOKS.filter((h) => h.calls[0].path.includes("${"))
    expect(withIds.length).toBeGreaterThan(40)
    for (const hook of withIds) {
      expect(hook.calls[0].path.match(/\$\{(?!encodeURIComponent\()/g), hook.name).toBeNull()
    }
  })

  it("names the path ids as the SPEC does, in the SPEC's order", () => {
    // `shape` keeps parameter names: `${encodeURIComponent(childId)}` is `{child_id}`.
    const specParams = SPEC_ROUTES.map((r) => shape(r.method, r.path)).filter((s) => s.includes("{"))
    const hookParams = HOOKS.map((h) => shape(h.calls[0].method, `/api${h.calls[0].path}`)).filter((s) =>
      s.includes("{"),
    )
    expect(specParams.length).toBeGreaterThan(40)
    expect(hookParams.sort()).toEqual(specParams.sort())
  })

  it("runs all 70 hooks against the SPEC path and method, with every id encoded", async () => {
    harness.client = new QueryClient()
    const idNames = new Set<string>()
    for (const route of SPEC_ROUTES) {
      for (const m of route.path.matchAll(/\{(\w+)\}/g)) idNames.add(m[1])
    }
    expect(idNames.size).toBeGreaterThanOrEqual(10)
    const variables: Record<string, unknown> = {
      body: {},
      file: new Blob(["x"]),
      description: "d",
    }
    for (const name of idNames) variables[snakeToCamel(name)] = `${snakeToCamel(name)}/x`

    let ran = 0
    for (const hook of HOOKS) {
      const route = SPEC_ROUTES.find(
        (r) => shape(r.method, r.path) === shape(hook.calls[0].method, `/api${hook.calls[0].path}`),
      )
      expect(route, hook.name).toBeDefined()
      const names = [...route!.path.matchAll(/\{(\w+)\}/g)].map((m) => m[1])
      const options = runHook(hook.name, "p1/x", "p2/x", "p3/x")
      vi.mocked(request).mockReset()
      vi.mocked(request).mockResolvedValue(undefined)
      if (options.queryFn) {
        await options.queryFn()
      } else {
        await options.mutationFn!(variables)
      }
      const [url, init] = vi.mocked(request).mock.calls[0] as [string, RequestInit]
      const expected = route!.path
        .replace(/^\/api/, "")
        .replace(/\{(\w+)\}/g, (_m, name: string) => {
          const sentinel = options.queryFn
            ? `p${names.indexOf(name) + 1}/x`
            : `${snakeToCamel(name)}/x`
          return encodeURIComponent(sentinel)
        })
      expect(url.split("?")[0], hook.name).toBe(expected)
      expect(init.method, hook.name).toBe(route!.method)
      ran++
    }
    expect(ran).toBe(SPEC_ROUTE_COUNT)
  })

  it("builds each read's key from its own ids, in path order, with a factory that takes them", () => {
    harness.client = new QueryClient()
    let checked = 0
    for (const hook of HOOKS.filter((h) => h.calls[0].method === "GET")) {
      const idCount = [...hook.calls[0].path.matchAll(/\$\{/g)].length
      const options = runHook(hook.name, "p1/x", "p2/x", "p3/x")
      const flat = JSON.stringify(options.queryKey)
      let from = 0
      for (let i = 1; i <= idCount; i++) {
        const at = flat.indexOf(`"p${i}/x"`, from)
        expect(at, `${hook.name}: id ${i} missing or out of order in ${flat}`).toBeGreaterThanOrEqual(0)
        from = at + 1
      }
      const factory = (tutoringKeys as unknown as Record<string, (...a: unknown[]) => readonly unknown[]>)[
        hook.queryKeys[0]
      ]
      expect(JSON.stringify(factory("p1/x", "p2/x", "p3/x").slice(0, 1)), hook.name).toBe('["tutoring"]')
      expect(factory.length, hook.name).toBeGreaterThanOrEqual(idCount)
      checked++
    }
    expect(checked).toBe(SPEC_ROUTES.filter((r) => r.method === "GET").length)
  })
})

describe("tutoring query keys", () => {
  /** Route keys are the factories that are neither `all` nor a `…Scope` prefix. */
  const routeKeyNames = Object.keys(tutoringKeys).filter(
    (name) => name !== "all" && !name.endsWith("Scope"),
  )
  const getCount = SPEC_ROUTES.filter((r) => r.method === "GET").length

  /** Run a factory with distinct string arguments (ids, params). */
  function sample(name: string): readonly unknown[] {
    const factory = (tutoringKeys as unknown as Record<string, (...args: string[]) => readonly unknown[]>)[name]
    return factory("a1", "b2", "c3")
  }

  it("has one key factory per GET route (34 on 2026-10-26)", () => {
    expect(getCount).toBeGreaterThan(30)
    expect(routeKeyNames.length).toBe(getCount)
  })

  it("makes every GET hook use its own key factory and no other key", () => {
    const getHooks = HOOKS.filter((h) => h.calls[0]?.method === "GET")
    expect(getHooks.length).toBe(getCount)
    const used = getHooks.map((h) => {
      expect(h.queryKeys.length, `${h.name} must name exactly one tutoringKeys factory`).toBe(1)
      return h.queryKeys[0]
    })
    expect(new Set(used).size).toBe(used.length)
    expect([...used].sort()).toEqual([...routeKeyNames].sort())
  })

  it("names no queryKey in the hooks file that does not come from tutoringKeys", () => {
    const all = [...HOOKS_SOURCE.matchAll(/\bqueryKey:\s*([^\n]*)/g)].map((m) => m[1])
    expect(all.length).toBe(getCount)
    for (const text of all) expect(text.startsWith("tutoringKeys.")).toBe(true)
  })

  it("starts every key with the tutoring root and keeps the keys distinct", () => {
    const serialised = routeKeyNames.map((name) => JSON.stringify(sample(name)))
    expect(serialised.length).toBe(getCount)
    expect(new Set(serialised).size).toBe(getCount)
    for (const name of routeKeyNames) expect(sample(name)[0]).toBe("tutoring")
  })

  it("keeps every key, and every scope prefix, off the persisted cache", () => {
    for (const name of Object.keys(tutoringKeys)) {
      const value = (tutoringKeys as unknown as Record<string, unknown>)[name]
      const key = typeof value === "function" ? sample(name) : (value as readonly unknown[])
      expect(isPersistableQueryKey(key), name).toBe(false)
    }
  })

  it("lets a scope prefix match every key beneath it", () => {
    const prefix = tutoringKeys.studentBookingsScope()
    const list = tutoringKeys.studentBookings({ when: "upcoming" })
    const detail = tutoringKeys.studentBooking("b1")
    for (const key of [list, detail]) {
      expect(key.slice(0, prefix.length)).toEqual([...prefix])
    }
  })
})

describe("tutoringQueryString", () => {
  it("skips empty values and repeats array values", () => {
    expect(
      tutoringQueryString({ mode: ["virtual", "in_person"], subject: undefined, cursor: null, limit: 20 }),
    ).toBe("?mode=virtual&mode=in_person&limit=20")
  })

  it("is empty when nothing is set", () => {
    expect(tutoringQueryString({})).toBe("")
    expect(tutoringQueryString(undefined)).toBe("")
  })

  it("encodes values", () => {
    expect(tutoringQueryString({ cursor: "a b&c" })).toBe("?cursor=a+b%26c")
  })
})

describe("403 access_ended drops the tutor's cached student detail", () => {
  const STUDENT = "11111111-1111-4111-8111-111111111111"
  const OTHER = "22222222-2222-4222-8222-222222222222"
  const DETAIL = { detail: { sentinel: true }, grantId: "g", grantedAt: "t", accessRecordedAt: "t" }

  let client: QueryClient
  beforeEach(() => {
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    installAccessEndedGuard(client)
    vi.mocked(request).mockReset()
    client.setQueryData(tutoringKeys.tutorStudent(STUDENT), DETAIL)
    client.setQueryData(tutoringKeys.tutorStudent(OTHER), DETAIL)
  })

  /** Re-fetch a student's detail while the mocked API refuses with `error`. */
  async function refuse(studentId: string, error: ApiError): Promise<void> {
    vi.mocked(request).mockRejectedValue(error)
    await expect(
      client.fetchQuery({
        queryKey: tutoringKeys.tutorStudent(studentId),
        queryFn: () => request("/tutor/students/" + studentId),
        staleTime: 0,
      }),
    ).rejects.toBe(error)
    // The cache notifies subscribers on a scheduled flush.
    await new Promise((resolve) => setTimeout(resolve, 10))
  }

  it("clears that student's cached data on 403 access_ended, leaving the error", async () => {
    await refuse(STUDENT, new ApiError(403, "403 Forbidden", { code: "access_ended" }))
    expect(client.getQueryData(tutoringKeys.tutorStudent(STUDENT))).toBeUndefined()
    const state = client.getQueryState(tutoringKeys.tutorStudent(STUDENT))
    expect(state?.status).toBe("error")
    expect(state?.data).toBeUndefined()
  })

  it("does not remove the query, so a mounted screen does not rebuild and refetch it", async () => {
    await refuse(STUDENT, new ApiError(403, "403 Forbidden", { code: "access_ended" }))
    expect(
      client.getQueryCache().find({ queryKey: tutoringKeys.tutorStudent(STUDENT), exact: true }),
    ).toBeDefined()
  })

  it("does not clear the entry on the 409 access_ended an accept gets (T11)", async () => {
    await refuse(STUDENT, new ApiError(409, "409 Conflict", { code: "access_ended" }))
    expect(client.getQueryData(tutoringKeys.tutorStudent(STUDENT))).toEqual(DETAIL)
  })

  it("leaves every other student's entry alone", async () => {
    await refuse(STUDENT, new ApiError(403, "403 Forbidden", { code: "access_ended" }))
    expect(client.getQueryData(tutoringKeys.tutorStudent(OTHER))).toEqual(DETAIL)
  })

  it("keeps the entry on a 404", async () => {
    await refuse(STUDENT, new ApiError(404, "404 Not Found", { code: "not_found" }))
    expect(client.getQueryData(tutoringKeys.tutorStudent(STUDENT))).toEqual(DETAIL)
  })

  it("keeps the entry on a different 403", async () => {
    await refuse(STUDENT, new ApiError(403, "403 Forbidden", { code: "email_unverified" }))
    expect(client.getQueryData(tutoringKeys.tutorStudent(STUDENT))).toEqual(DETAIL)
  })

  it("keeps the entry when the failure is a network error", async () => {
    await refuse(STUDENT, new ApiError(0, "TypeError: Failed to fetch"))
    expect(client.getQueryData(tutoringKeys.tutorStudent(STUDENT))).toEqual(DETAIL)
  })

  it("marks the tutor's student list stale", async () => {
    const list = tutoringKeys.tutorStudents({})
    client.setQueryData(list, { items: [], nextCursor: null })
    await refuse(STUDENT, new ApiError(403, "403 Forbidden", { code: "access_ended" }))
    expect(client.getQueryState(list)?.isInvalidated).toBe(true)
  })

  it("installs once per client", () => {
    const cache = client.getQueryCache()
    const before = (cache as unknown as { listeners: Set<unknown> }).listeners.size
    installAccessEndedGuard(client)
    installAccessEndedGuard(client)
    expect((cache as unknown as { listeners: Set<unknown> }).listeners.size).toBe(before)
  })
})

describe("a mounted T20 screen whose grant has ended", () => {
  const STUDENT = "33333333-3333-4333-8333-333333333333"
  const DETAIL = { detail: { sentinel: true }, grantId: "g", grantedAt: "t", accessRecordedAt: "t" }

  /** Mount `useTutorStudent`'s options on a real observer, the way React does. */
  async function mountOnEndedGrant(seed: boolean): Promise<{
    client: QueryClient
    observer: QueryObserver
    stop: () => void
  }> {
    const client = new QueryClient()
    harness.client = client
    vi.mocked(request).mockReset()
    vi.mocked(request).mockImplementation(
      refuseLater(new ApiError(403, "403 Forbidden", { code: "access_ended" })),
    )
    if (seed) client.setQueryData(tutoringKeys.tutorStudent(STUDENT), DETAIL)
    const observer = new QueryObserver(client, runHook("useTutorStudent", STUDENT) as never)
    const stop = observer.subscribe(() => {})
    await new Promise((resolve) => setTimeout(resolve, 150))
    return { client, observer, stop }
  }

  it("asks the server exactly once, however the guard reacts", async () => {
    const { stop } = await mountOnEndedGrant(false)
    stop()
    expect(vi.mocked(request)).toHaveBeenCalledTimes(1)
  })

  it("asks exactly once even when the screen re-renders with fresh options", async () => {
    const { observer, stop } = await mountOnEndedGrant(false)
    // React calls `observer.setOptions` on every render with a new options object.
    observer.setOptions(runHook("useTutorStudent", STUDENT) as never)
    observer.setOptions(runHook("useTutorStudent", STUDENT) as never)
    await new Promise((resolve) => setTimeout(resolve, 150))
    stop()
    expect(vi.mocked(request)).toHaveBeenCalledTimes(1)
  })

  it("ends in the error state with the student's data gone", async () => {
    const { client, observer, stop } = await mountOnEndedGrant(true)
    stop()
    const result = observer.getCurrentResult()
    expect(result.status).toBe("error")
    expect(result.data).toBeUndefined()
    expect(client.getQueryData(tutoringKeys.tutorStudent(STUDENT))).toBeUndefined()
  })

  it("marks only the student LIST stale, never the detail's own prefix", async () => {
    const client = new QueryClient()
    installAccessEndedGuard(client)
    const spy = vi.spyOn(client, "invalidateQueries")
    client.setQueryData(tutoringKeys.tutorStudent(STUDENT), DETAIL)
    vi.mocked(request).mockReset()
    vi.mocked(request).mockImplementation(
      refuseLater(new ApiError(403, "403 Forbidden", { code: "access_ended" })),
    )
    await expect(
      client.fetchQuery({
        queryKey: tutoringKeys.tutorStudent(STUDENT),
        queryFn: () => request("/tutor/students/x"),
      }),
    ).rejects.toBeInstanceOf(ApiError)
    await new Promise((resolve) => setTimeout(resolve, 50))
    const keys = spy.mock.calls.map((call) => call[0]?.queryKey)
    expect(keys).toEqual([tutoringKeys.tutorStudentsListScope()])
    // The detail key must not sit under what was invalidated.
    const detail = tutoringKeys.tutorStudent(STUDENT)
    const invalidated = tutoringKeys.tutorStudentsListScope()
    expect(detail.slice(0, invalidated.length)).not.toEqual([...invalidated])
  })
})

describe("tutoring mutations are never persisted (R2)", () => {
  const MUTATION_HOOKS = HOOKS.filter((h) => h.calls[0].method !== "GET")
  const universal = {
    body: {},
    file: new Blob(["x"]),
    description: "d",
    bookingId: "b",
    reviewId: "r",
    replyId: "rp",
    grantId: "g",
    classId: "c",
    evidenceId: "e",
    counterpartId: "cp",
    reportId: "rep",
    tutorId: "t",
    childId: "ch",
  }

  afterEach(() => {
    onlineManager.setOnline(true)
  })

  it("finds the 36 write routes", () => {
    expect(MUTATION_HOOKS.length).toBe(SPEC_ROUTES.filter((r) => r.method !== "GET").length)
    expect(MUTATION_HOOKS.length).toBe(36)
  })

  it("sets networkMode always on every mutation, so none can pause", () => {
    harness.client = new QueryClient()
    for (const hook of MUTATION_HOOKS) {
      expect(runHook(hook.name).networkMode, hook.name).toBe("always")
    }
  })

  it("leaves nothing for the app's dehydrate to write when every mutation runs offline", async () => {
    const main = readFileSync(join(ROOT, "web", "src", "main.tsx"), "utf8")
    expect(main).toContain("shouldDehydrateQuery: shouldPersistQuery")
    // The app overrides the query predicate only; mutations dehydrate while paused (the library default).
    expect(main).not.toContain("shouldDehydrateMutation")

    const client = new QueryClient()
    harness.client = client
    onlineManager.setOnline(false)
    vi.mocked(request).mockReset()
    vi.mocked(request).mockReturnValue(new Promise(() => {}))
    for (const hook of MUTATION_HOOKS) {
      const observer = new MutationObserver(client, runHook(hook.name) as never)
      void observer.mutate(universal as never).catch(() => {})
    }
    await new Promise((resolve) => setTimeout(resolve, 50))
    const all = client.getMutationCache().getAll()
    expect(all.length).toBe(36)
    expect(all.filter((m) => m.state.isPaused).length).toBe(0)
    expect(dehydrate(client, { shouldDehydrateQuery: shouldPersistQuery }).mutations).toEqual([])
  })

  it("would catch a paused mutation (control)", async () => {
    const client = new QueryClient()
    harness.client = client
    onlineManager.setOnline(false)
    vi.mocked(request).mockReset()
    vi.mocked(request).mockReturnValue(new Promise(() => {}))
    const { networkMode: _dropped, ...withoutNetworkMode } = runHook("useCreateBooking")
    void new MutationObserver(client, withoutNetworkMode as never)
      .mutate({ tutorId: "t" } as never)
      .catch(() => {})
    await new Promise((resolve) => setTimeout(resolve, 50))
    const dehydrated = dehydrate(client, { shouldDehydrateQuery: shouldPersistQuery }).mutations
    expect(dehydrated.length).toBe(1)
  })
})

describe("audited reads are never served from cache (R3)", () => {
  const auditedShapes = (() => {
    const start = SPEC.indexOf("### b.2 Routes")
    const end = SPEC.indexOf("### b.3 DTOs")
    const found: string[] = []
    for (const line of SPEC.slice(start, end).split("\n")) {
      if (!line.startsWith("|") || !/\bWrites one\b/.test(line)) continue
      const cells = line.split(/(?<!\\)\|/).map((cell) => cell.trim())
      const route = /`(GET|POST|PUT|PATCH|DELETE) (\/api\/\S+?)`/.exec(cells[2] ?? "")
      if (route) found.push(shape(route[1], route[2]))
    }
    return found.sort()
  })()

  it("finds the four audited reads in the SPEC (T19, T20, A2, A10)", () => {
    expect(auditedShapes).toEqual([
      "GET /admin/tutoring/reports/{report_id}",
      "GET /admin/tutors/{tutor_id}",
      "GET /tutor/students",
      "GET /tutor/students/{student_id}",
    ])
  })

  it("gives exactly those hooks the AUDITED_READ spread", () => {
    const spread = HOOKS.filter((h) => h.body.includes("...AUDITED_READ"))
    expect(spread.length).toBe(4)
    const shapes = spread.map((h) => shape(h.calls[0].method, `/api${h.calls[0].path}`)).sort()
    expect(shapes).toEqual(auditedShapes)
  })

  it("defines AUDITED_READ as never stale, never kept, always refetched, not on reconnect", () => {
    expect(AUDITED_READ).toEqual({
      staleTime: 0,
      gcTime: 0,
      refetchOnMount: "always",
      refetchOnReconnect: false,
    })
  })

  it("hands exactly those four hooks' options to react-query with those settings", () => {
    harness.client = new QueryClient()
    const withSettings = HOOKS.filter((h) => {
      if (h.calls[0].method !== "GET") return false
      const options = runHook(h.name, "a", "b", "c")
      return options.gcTime === 0 && options.refetchOnReconnect === false
    })
    expect(withSettings.length).toBe(4)
  })

  it("seeds no read from anything but the server", () => {
    for (const word of ["placeholderData", "initialData", "keepPreviousData"]) {
      expect(HOOKS_SOURCE.includes(word), word).toBe(false)
    }
  })
})

describe("what a block refreshes (R5)", () => {
  const expectedKeys = (tutorId: string | null): string[] =>
    [
      tutoringKeys.blocks(),
      tutoringKeys.directoryScope(),
      tutoringKeys.studentGrants(),
      tutoringKeys.studentBookingsScope(),
      tutoringKeys.studentClassAccess(),
      ["student", "classes"],
      tutoringKeys.ownBookingsScope(),
      tutoringKeys.tutorStudentsListScope(),
      ...(tutorId === null ? [] : [tutoringKeys.tutorProfile(tutorId)]),
    ]
      .map((key) => JSON.stringify(key))
      .sort()

  it("lists blocks, directory, grants, bookings, class access, classes, own bookings, student list and the tutor's profile", () => {
    expect(blockInvalidationKeys({ tutorId: "T1" }).map((k) => JSON.stringify(k)).sort()).toEqual(
      expectedKeys("T1"),
    )
  })

  it("leaves the tutor profile out when a tutor blocks a student", () => {
    expect(blockInvalidationKeys({ studentId: "S1" }).map((k) => JSON.stringify(k)).sort()).toEqual(
      expectedKeys(null),
    )
  })

  it("is what the B2 hook invalidates after a block", () => {
    const invalidateQueries = vi.fn()
    harness.client = { invalidateQueries }
    const options = runHook("useCreateTutoringBlock")
    options.onSuccess!({}, { tutorId: "T1" }, undefined, undefined)
    const sent = invalidateQueries.mock.calls.map((c) => JSON.stringify(c[0].queryKey)).sort()
    expect(sent).toEqual(expectedKeys("T1"))
  })
})

describe("A11 only updates a report detail that is already cached (R6)", () => {
  const REPORT = "44444444-4444-4444-8444-444444444444"
  const resolved = { reportId: REPORT, resolution: "dismissed" }

  it("creates no entry when none exists", () => {
    const client = new QueryClient()
    harness.client = client
    runHook("useResolveTutoringReport").onSuccess!(resolved, { reportId: REPORT, body: {} })
    expect(client.getQueryCache().find({ queryKey: tutoringKeys.adminReport(REPORT) })).toBeUndefined()
    expect(client.getQueryCache().getAll()).toEqual([])
  })

  it("replaces the data of an entry that exists, and no other", () => {
    const client = new QueryClient()
    harness.client = client
    client.setQueryData(tutoringKeys.adminReport(REPORT), { old: true })
    client.setQueryData(tutoringKeys.adminReport("other"), { old: true })
    runHook("useResolveTutoringReport").onSuccess!(resolved, { reportId: REPORT, body: {} })
    expect(client.getQueryData(tutoringKeys.adminReport(REPORT))).toEqual(resolved)
    expect(client.getQueryData(tutoringKeys.adminReport("other"))).toEqual({ old: true })
  })
})

describe("a booking action always sends a body (R7)", () => {
  const withReason: [string, unknown[]][] = [
    ["useCancelStudentBooking", []],
    ["useDeclineTutorBooking", []],
    ["useCancelTutorBooking", []],
    ["useCancelParentChildBooking", []],
  ]

  it.each(withReason)("%s sends {} when no reason is given", async (name) => {
    harness.client = new QueryClient()
    vi.mocked(request).mockReset()
    vi.mocked(request).mockResolvedValue(undefined)
    await runHook(name).mutationFn!({ bookingId: "b1", childId: "c1" })
    const init = vi.mocked(request).mock.calls[0][1] as RequestInit
    expect(init.method).toBe("POST")
    expect(init.body).toBe("{}")
  })

  it.each(withReason)("%s sends the reason it is given", async (name) => {
    harness.client = new QueryClient()
    vi.mocked(request).mockReset()
    vi.mocked(request).mockResolvedValue(undefined)
    await runHook(name).mutationFn!({ bookingId: "b1", childId: "c1", body: { reason: "Ill" } })
    const init = vi.mocked(request).mock.calls[0][1] as RequestInit
    expect(init.body).toBe('{"reason":"Ill"}')
  })
})
