import { readFileSync } from "node:fs"
import { join } from "node:path"
import { QueryClient } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError, request } from "@/lib/api"
import { isPersistableQueryKey } from "@/lib/offline/persistAllowlist"
import { tutoringKeys } from "@/lib/tutoring/queryKeys"
import { installAccessEndedGuard, tutoringQueryString } from "@/lib/hooks/useTutoringApi"

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
 */

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>()
  return { ...actual, request: vi.fn() }
})

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

/** `{tutor_id}` and `${tutorId}` both become `{}`: only the shape is compared. */
function shape(method: string, path: string): string {
  return `${method} ${path.replace(/^\/api/, "").replace(/\$\{[^}]*\}|\{[^}]*\}/g, "{}")}`
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
