import { readFileSync } from "node:fs"
import { join } from "node:path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import worker, { type Env } from "../../worker/index.ts"

/*
 * T08: the edge half of decision row 17 (SPEC §b.5 rev 3, THREAT-MODEL SC-18,
 * SC-26). A tutor's public card is indexable by default and the tutor can opt
 * out, so the worker asks P2 about every card and fails closed on anything
 * but a 200 whose JSON says `indexable === true`. The directory is never
 * indexed. `/api/public/tutors*` and `/api/public/tutoring-areas` get a
 * 60-second `caches.default` read-through; nothing else under `/api/*` does.
 *
 * Node environment, as SPEC §b.5 says: `ASSETS`, `fetch` and `caches` are
 * stubbed and the worker's default export is driven directly. Every expected
 * value comes from somewhere other than the worker source: header values,
 * the timeout, the TTL, the lookup path and the `run_worker_first` list are
 * parsed out of SPEC §b.5's own text, and the five security headers out of
 * `public/_headers`.
 */

/*
 * The Workers runtime names the worker source uses. The worker project
 * (`worker/tsconfig.json`) typechecks them against @cloudflare/workers-types;
 * this project compiles with the DOM lib, whose globals conflict with that
 * package (see the worker tsconfig's own comment), so it declares the slices
 * the stubs below provide instead.
 */
declare global {
  interface CacheStorage {
    readonly default: Cache
  }
  interface Fetcher {
    fetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response>
  }
  interface ExportedHandler<Env = unknown> {
    fetch?: (request: Request, env: Env) => Response | Promise<Response>
  }
}

const WEB = join(import.meta.dirname, "..", "..")
const REPO = join(WEB, "..")
const read = (root: string, path: string): string => readFileSync(join(root, path), "utf8")

// ── SPEC §b.5, parsed ───────────────────────────────────────────────────────

const SPEC_B5 = (() => {
  const spec = read(REPO, "docs/tutoring/SPEC.md")
  const start = spec.indexOf("### b.5 ")
  const end = spec.indexOf("\n## ", start)
  if (start < 0 || end < 0) throw new Error("SPEC §b.5 not found in docs/tutoring/SPEC.md")
  return spec.slice(start, end)
})()

function fromSpec(pattern: RegExp, what: string): string {
  const match = pattern.exec(SPEC_B5)
  if (!match) throw new Error(`SPEC §b.5 no longer states ${what}; move this parser with the text`)
  return match[1]
}

const DIRECTORY_TAG = fromSpec(
  /\*\*Directory `\/tutors`:\*\*[^\n]*?`X-Robots-Tag: ([^`]+)`/,
  "the directory's X-Robots-Tag",
)
const CARD_NOINDEX_TAG = fromSpec(
  /Every other outcome sends `X-Robots-Tag: ([^`]+)`/,
  "the card's fail-closed X-Robots-Tag",
)
const LOOKUP_TIMEOUT_MS = Number(fromSpec(/with a (\d+) ms timeout/, "the lookup timeout"))
const CACHE_TTL_SECONDS = Number(fromSpec(/keyed on the full URL, (\d+) s\./, "the read-through TTL"))
const LOOKUP_PATH_TEMPLATE = fromSpec(
  /look up `GET \{BACKEND_URL\}(\/api\/public\/tutors\/\{id\})`/,
  "the lookup's path template",
)
const RUN_WORKER_FIRST = JSON.parse(
  fromSpec(/`run_worker_first` becomes `(\[[^`]+\])`/, "the run_worker_first list"),
) as string[]

// ── public/_headers, parsed ─────────────────────────────────────────────────

/** The `/*` block of `public/_headers`: every `  Name: value` line under it. */
const SECURITY_HEADERS: [string, string][] = (() => {
  const lines = read(WEB, "public/_headers").split("\n")
  const start = lines.findIndex((line) => line.trim() === "/*")
  if (start < 0) throw new Error("public/_headers has no /* block")
  const out: [string, string][] = []
  for (const line of lines.slice(start + 1)) {
    const match = /^ {2}([A-Za-z-]+): (.+)$/.exec(line)
    if (!match) break
    out.push([match[1], match[2].trim()])
  }
  return out
})()

// ── stubs ───────────────────────────────────────────────────────────────────

const ORIGIN = "https://lemelyig.test"
const BACKEND = "https://lemely-api-staging.a.run.app"
const TUTOR_ID = "3f2b8c1e-9a4d-4e6f-8b7a-1c2d3e4f5a6b"
const SHELL = "<!doctype html><html><head><title>Lemely</title></head><body></body></html>"
const SHELL_CACHE_CONTROL = "public, max-age=0, must-revalidate"

interface SeenRequest {
  url: string
  method: string
  headers: Headers
  redirect: RequestRedirect
  signal: AbortSignal
  body: string | null
}

function asRequest(input: RequestInfo | URL, init?: RequestInit): Request {
  return input instanceof Request && init === undefined ? input : new Request(input, init)
}

/** An in-memory `caches.default`: keyed on the key's URL, GET only, and a
 * stored response is read back as a fresh copy, as the platform does. */
class MemoryCache {
  readonly stored = new Map<string, { body: ArrayBuffer; status: number; headers: [string, string][] }>()
  readonly keys: SeenRequest[] = []

  readonly match = vi.fn(async (key: RequestInfo | URL): Promise<Response | undefined> => {
    const request = asRequest(key)
    this.keys.push(await snapshot(request))
    const hit = request.method === "GET" ? this.stored.get(request.url) : undefined
    return hit && new Response(hit.body, { status: hit.status, headers: hit.headers })
  })

  readonly put = vi.fn(async (key: RequestInfo | URL, response: Response): Promise<void> => {
    const request = asRequest(key)
    this.keys.push(await snapshot(request))
    if (request.method !== "GET") throw new TypeError("Cache.put accepts GET requests only")
    this.stored.set(request.url, {
      body: await response.arrayBuffer(),
      status: response.status,
      headers: [...response.headers],
    })
  })
}

async function snapshot(request: Request): Promise<SeenRequest> {
  return {
    url: request.url,
    method: request.method,
    headers: new Headers(request.headers),
    redirect: request.redirect,
    signal: request.signal,
    body: request.body === null ? null : await request.clone().text(),
  }
}

let cache: MemoryCache
let backendCalls: SeenRequest[]
let respond: (request: Request) => Response | Promise<Response>
let assetsFetch: ReturnType<typeof vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>>
let env: Env

const backendFetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const request = asRequest(input, init)
  backendCalls.push(await snapshot(request))
  return respond(request)
})

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "public, max-age=60" },
  })
}

function card(indexable: unknown): Record<string, unknown> {
  return { tutorId: TUTOR_ID, publicName: "Mona S.", headline: "Physics and maths", indexable }
}

function page(path: string, init?: RequestInit): Request {
  return new Request(`${ORIGIN}${path}`, init)
}

function shell(extraHeaders: Record<string, string> = {}): Response {
  return new Response(SHELL, {
    status: 200,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": SHELL_CACHE_CONTROL,
      ...extraHeaders,
    },
  })
}

beforeEach(() => {
  cache = new MemoryCache()
  backendCalls = []
  respond = () => new Response("no backend response configured", { status: 599 })
  backendFetch.mockClear()
  assetsFetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => shell())
  env = { BACKEND_URL: BACKEND, ASSETS: { fetch: assetsFetch } }
  vi.stubGlobal("fetch", backendFetch)
  vi.stubGlobal("caches", { default: cache })
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const lookupUrl = (id: string): string => `${BACKEND}${LOOKUP_PATH_TEMPLATE.replace("{id}", id)}`

// ── the parsed sources are what this file thinks they are ───────────────────

describe("expectations parsed from SPEC §b.5 and public/_headers", () => {
  it("found every value it needs (non-vacuity)", () => {
    expect(DIRECTORY_TAG).toMatch(/^noindex\b/)
    expect(CARD_NOINDEX_TAG).toMatch(/^noindex\b/)
    expect(CARD_NOINDEX_TAG).not.toBe(DIRECTORY_TAG)
    expect(LOOKUP_TIMEOUT_MS).toBeGreaterThan(0)
    expect(CACHE_TTL_SECONDS).toBeGreaterThan(0)
    expect(LOOKUP_PATH_TEMPLATE).toContain("{id}")
    expect(RUN_WORKER_FIRST.length).toBe(3)
    // SPEC §b.5: "the five security headers".
    expect(SECURITY_HEADERS.length).toBe(5)
  })
})

// ── tutor pages ─────────────────────────────────────────────────────────────

describe("tutor pages (row 17)", () => {
  it("serves the SPA shell for /tutors with noindex, follow", async () => {
    for (const path of ["/tutors", "/tutors?subject=physics&mode=online"]) {
      assetsFetch.mockClear()
      const request = page(path)
      const res = await worker.fetch(request, env)

      expect(res.status).toBe(200)
      expect(await res.text()).toBe(SHELL)
      expect(res.headers.get("content-type")).toBe("text/html; charset=utf-8")
      expect(res.headers.get("X-Robots-Tag"), path).toBe(DIRECTORY_TAG)
      // The body is always ASSETS.fetch(request), and Cache-Control is left
      // as Static Assets returned it.
      expect(assetsFetch).toHaveBeenCalledTimes(1)
      expect(assetsFetch.mock.calls[0][0]).toBe(request)
      expect(res.headers.get("cache-control")).toBe(SHELL_CACHE_CONTROL)
    }
    // The directory decision needs no lookup.
    expect(backendFetch).not.toHaveBeenCalled()
  })

  it("omits X-Robots-Tag for a card whose lookup says indexable", async () => {
    respond = () => json(card(true))
    // An upper-case id is the same UUID, and HEAD is what `curl -sI` sends.
    const cases: [string, RequestInit | undefined][] = [
      [`/tutors/${TUTOR_ID}`, undefined],
      [`/tutors/${TUTOR_ID.toUpperCase()}`, undefined],
      [`/tutors/${TUTOR_ID}`, { method: "HEAD" }],
    ]
    for (const [path, init] of cases) {
      cache.stored.clear()
      const res = await worker.fetch(page(path, init), env)
      expect(res.status).toBe(200)
      expect(res.headers.get("content-type")).toBe("text/html; charset=utf-8")
      expect(res.headers.has("X-Robots-Tag"), `${init?.method ?? "GET"} ${path}`).toBe(false)
    }
    expect(backendFetch).toHaveBeenCalledTimes(cases.length)

    // Even if the platform ever applied a header rule to the asset response,
    // an indexable card still leaves without X-Robots-Tag.
    assetsFetch.mockImplementation(async () => shell({ "X-Robots-Tag": "noindex" }))
    const res = await worker.fetch(page(`/tutors/${TUTOR_ID}`), env)
    expect(res.headers.has("X-Robots-Tag")).toBe(false)
    expect(await res.text()).toBe(SHELL)
  })

  it("sends noindex, nofollow when the tutor opted out", async () => {
    respond = () => json(card(false))
    const res = await worker.fetch(page(`/tutors/${TUTOR_ID}`), env)

    expect(res.headers.get("X-Robots-Tag")).toBe(CARD_NOINDEX_TAG)
    expect(res.status).toBe(200)
    expect(await res.text()).toBe(SHELL)
    expect(backendFetch).toHaveBeenCalledTimes(1)
  })

  it("sends noindex, nofollow when the lookup 404s", async () => {
    // P2's one predicate: unknown, unlisted, paused, suspended and closed all
    // answer the same 404 body.
    respond = () => json({ detail: "Not Found" }, 404)
    const res = await worker.fetch(page(`/tutors/${TUTOR_ID}`), env)

    expect(res.headers.get("X-Robots-Tag")).toBe(CARD_NOINDEX_TAG)
    // The page itself is still the SPA shell; the SPA renders its own 404.
    expect(res.status).toBe(200)
    expect(await res.text()).toBe(SHELL)
    expect(backendFetch).toHaveBeenCalledTimes(1)
  })

  it("fails closed on lookup error, timeout, non-JSON and a missing or non-boolean field", async () => {
    const outcomes: [string, (request: Request) => Response | Promise<Response>][] = [
      ["network error", () => Promise.reject(new TypeError("fetch failed"))],
      ["500", () => json({ detail: "boom" }, 500)],
      ["503 with indexable true", () => json(card(true), 503)],
      ["302 redirect", () => new Response(null, { status: 302, headers: { location: "/elsewhere" } })],
      ["non-JSON", () => new Response("<html>not json</html>", { status: 200, headers: { "content-type": "text/html" } })],
      ["empty body", () => new Response("", { status: 200 })],
      ["missing field", () => json({ tutorId: TUTOR_ID, publicName: "Mona S." })],
      ["string field", () => json(card("true"))],
      ["number field", () => json(card(1))],
      ["null field", () => json(card(null))],
      ["JSON null", () => json(null)],
      ["JSON array", () => json([card(true)])],
      ["JSON true", () => json(true)],
    ]
    for (const [name, outcome] of outcomes) {
      cache.stored.clear()
      backendFetch.mockClear()
      respond = outcome
      const res = await worker.fetch(page(`/tutors/${TUTOR_ID}`), env)
      expect(res.headers.get("X-Robots-Tag"), name).toBe(CARD_NOINDEX_TAG)
      expect(await res.text(), name).toBe(SHELL)
      expect(backendFetch, name).toHaveBeenCalledTimes(1)
    }

    // Timeout: a lookup that never answers is abandoned at the SPEC's limit,
    // not before, and the subrequest is cancelled.
    cache.stored.clear()
    backendCalls = []
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] })
    respond = (request) =>
      new Promise<Response>((_resolve, reject) => {
        request.signal.addEventListener("abort", () => reject(new Error("aborted")))
      })
    let settled = false
    const pending = worker.fetch(page(`/tutors/${TUTOR_ID}`), env).then((res) => {
      settled = true
      return res
    })
    await vi.advanceTimersByTimeAsync(LOOKUP_TIMEOUT_MS - 1)
    expect(settled, "the page answered before the lookup timed out").toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    const res = await pending
    expect(res.headers.get("X-Robots-Tag"), "timeout").toBe(CARD_NOINDEX_TAG)
    expect(await res.text()).toBe(SHELL)
    expect(backendCalls).toHaveLength(1)
    expect(backendCalls[0].signal.aborted, "the timed-out lookup was not cancelled").toBe(true)
  })

  it("fails closed for a non-UUID id or a deeper path without calling the backend", async () => {
    respond = () => json(card(true))
    const paths = [
      "/tutors/not-a-uuid",
      "/tutors/",
      `/tutors/${TUTOR_ID}/`,
      `/tutors/${TUTOR_ID}/reviews`,
      `/tutors/${TUTOR_ID}x`,
      `/tutors/x${TUTOR_ID}`,
      `/tutors/${TUTOR_ID.replaceAll("-", "")}`,
      `/tutors/{${TUTOR_ID}}`,
      `/tutors//${TUTOR_ID}`,
      `/tutors/%33${TUTOR_ID.slice(1)}`,
      `/tutors/${TUTOR_ID.slice(0, -1)}g`,
      "/tutors/1",
    ]
    for (const path of paths) {
      assetsFetch.mockClear()
      const res = await worker.fetch(page(path), env)
      expect(res.headers.get("X-Robots-Tag"), path).toBe(CARD_NOINDEX_TAG)
      expect(await res.text(), path).toBe(SHELL)
      expect(assetsFetch, path).toHaveBeenCalledTimes(1)
    }
    expect(backendFetch).not.toHaveBeenCalled()
    expect(cache.match).not.toHaveBeenCalled()
  })

  it("the lookup carries no cookie or authorization and targets only /api/public/tutors/{id}", async () => {
    respond = () => json(card(true))
    const inbound = page(`/tutors/${TUTOR_ID}?ref=search&utm_source=x`, {
      headers: {
        cookie: "sb-access-token=secret; theme=dark",
        authorization: "Bearer eyJhbGciOiJIUzI1NiJ9.e30.sig",
        "CF-Connecting-IP": "203.0.113.7",
        "x-forwarded-for": "203.0.113.7",
        "user-agent": "Googlebot/2.1",
        "accept-language": "ar-EG",
        "if-none-match": '"abc"',
        referer: "https://example.com/",
      },
    })
    // The inbound request really carries what the lookup must not forward.
    expect(inbound.headers.get("cookie")).not.toBeNull()
    expect(inbound.headers.get("authorization")).not.toBeNull()

    const res = await worker.fetch(inbound, env)
    expect(res.headers.has("X-Robots-Tag")).toBe(false)

    expect(backendCalls).toHaveLength(1)
    const lookup = backendCalls[0]
    expect(lookup.method).toBe("GET")
    expect(lookup.url).toBe(lookupUrl(TUTOR_ID))
    expect(lookup.headers.get("cookie")).toBeNull()
    expect(lookup.headers.get("authorization")).toBeNull()
    // Built from scratch: no client header of any kind.
    expect([...lookup.headers.keys()]).toEqual([])
    expect(lookup.body).toBeNull()
    // One request to one path: a redirect is an answer, not a hop.
    expect(lookup.redirect).toBe("manual")

    // The cache key is a bare GET of the public P2 URL: no client header can
    // shape what the cache answers.
    expect(cache.keys.length).toBeGreaterThan(0)
    for (const key of cache.keys) {
      expect(key.method).toBe("GET")
      expect(key.url).toBe(`${ORIGIN}${LOOKUP_PATH_TEMPLATE.replace("{id}", TUTOR_ID)}`)
      expect([...key.headers.keys()]).toEqual([])
    }
  })

  it("sets the five security headers on /tutors responses", async () => {
    respond = (request) => json(card(!request.url.endsWith(TUTOR_ID.replace("3f", "4f"))))
    const optedOut = TUTOR_ID.replace("3f", "4f")
    for (const path of ["/tutors", `/tutors/${TUTOR_ID}`, `/tutors/${optedOut}`, "/tutors/not-a-uuid"]) {
      const res = await worker.fetch(page(path), env)
      expect(await res.text(), path).toBe(SHELL)
      for (const [name, value] of SECURITY_HEADERS) {
        expect(res.headers.get(name), `${name} on ${path}`).toBe(value)
      }
    }
  })
})

// ── deploy config ───────────────────────────────────────────────────────────

/** JSONC to JSON: drops `//` and `/* *\/` comments outside string literals
 * (wrangler.jsonc has URLs such as "https://..." inside strings). */
function stripJsonComments(source: string): string {
  let out = ""
  let inString = false
  for (let i = 0; i < source.length; i++) {
    const ch = source[i]
    if (inString) {
      out += ch
      if (ch === "\\") {
        out += source[++i] ?? ""
      } else if (ch === '"') {
        inString = false
      }
    } else if (ch === '"') {
      inString = true
      out += ch
    } else if (ch === "/" && source[i + 1] === "/") {
      while (i < source.length && source[i] !== "\n") i++
      out += "\n"
    } else if (ch === "/" && source[i + 1] === "*") {
      i = source.indexOf("*/", i + 2) + 1
      if (i === 0) throw new Error("unterminated block comment in wrangler.jsonc")
    } else {
      out += ch
    }
  }
  return out
}

describe("wrangler.jsonc", () => {
  it("wrangler run_worker_first lists /api/*, /tutors and /tutors/*", () => {
    const config = JSON.parse(stripJsonComments(read(WEB, "wrangler.jsonc"))) as {
      assets: { binding: string; not_found_handling: string; run_worker_first: string[] }
      env: Record<string, { assets?: unknown }>
    }
    expect(config.assets.run_worker_first).toEqual(RUN_WORKER_FIRST)
    // SPEC §b.5: the SPA shell comes from the ASSETS binding's SPA fallback.
    expect(config.assets.binding).toBe("ASSETS")
    expect(config.assets.not_found_handling).toBe("single-page-application")
    // No deploy target replaces the top-level assets block.
    const targets = Object.entries(config.env)
    expect(targets.map(([name]) => name).sort()).toEqual(["production", "staging"])
    for (const [name, target] of targets) {
      expect(target.assets, `env.${name} overrides assets`).toBeUndefined()
    }
  })
})

// ── /api/* ──────────────────────────────────────────────────────────────────

describe("/api/* proxy", () => {
  it("/api/* proxying is unchanged", async () => {
    respond = () =>
      new Response("created", { status: 201, statusText: "Created", headers: { "x-backend": "yes" } })
    const inbound = new Request(`${ORIGIN}/api/student/uploads?draft=1`, {
      method: "POST",
      body: "payload-bytes",
      headers: {
        host: "lemelyig.test",
        authorization: "Bearer token",
        cookie: "a=b",
        "content-type": "text/plain",
        "CF-Connecting-IP": "198.51.100.4",
      },
    })
    const res = await worker.fetch(inbound, env)

    expect(backendCalls).toHaveLength(1)
    const proxied = backendCalls[0]
    expect(proxied.url).toBe(`${BACKEND}/api/student/uploads?draft=1`)
    expect(proxied.method).toBe("POST")
    expect(proxied.body).toBe("payload-bytes")
    expect(proxied.headers.get("authorization")).toBe("Bearer token")
    expect(proxied.headers.get("cookie")).toBe("a=b")
    expect(proxied.headers.get("content-type")).toBe("text/plain")
    expect(proxied.headers.get("host")).toBeNull()
    expect(proxied.headers.get("X-Real-IP")).toBe("198.51.100.4")
    expect(proxied.headers.get("X-Forwarded-For")).toBe("198.51.100.4")
    expect(proxied.headers.get("X-Forwarded-Proto")).toBe("https")

    expect(res.status).toBe(201)
    expect(res.statusText).toBe("Created")
    expect(res.headers.get("x-backend")).toBe("yes")
    expect(await res.text()).toBe("created")
    for (const [name, value] of SECURITY_HEADERS) {
      expect(res.headers.get(name), name).toBe(value)
    }
    expect(assetsFetch).not.toHaveBeenCalled()
    expect(cache.match).not.toHaveBeenCalled()
    expect(cache.put).not.toHaveBeenCalled()
  })

  it("/api/public/tutors read-through serves the cached response on the second call", async () => {
    let served = 0
    respond = (request) => {
      served += 1
      return json({ url: new URL(request.url).pathname + new URL(request.url).search, served })
    }
    const paths = [
      "/api/public/tutors?subject=physics&mode=online",
      `/api/public/tutors/${TUTOR_ID}`,
      "/api/public/tutoring-areas",
    ]
    for (const path of paths) {
      backendFetch.mockClear()
      const first = await worker.fetch(new Request(`${ORIGIN}${path}`, { headers: { authorization: "Bearer a" } }), env)
      const second = await worker.fetch(new Request(`${ORIGIN}${path}`), env)
      expect(backendFetch, path).toHaveBeenCalledTimes(1)

      const firstBody = await first.text()
      expect(await second.text(), path).toBe(firstBody)
      expect(second.status).toBe(200)
      expect(second.headers.get("content-type")).toBe("application/json")
      for (const [name, value] of SECURITY_HEADERS) {
        expect(first.headers.get(name), `${name} on ${path} (miss)`).toBe(value)
        expect(second.headers.get(name), `${name} on ${path} (hit)`).toBe(value)
      }
      // Keyed on the full URL, kept for the SPEC's TTL.
      const entry = cache.stored.get(`${ORIGIN}${path}`)
      expect(entry, path).toBeDefined()
      expect(new Headers(entry?.headers).get("cache-control")).toBe(`public, max-age=${CACHE_TTL_SECONDS}`)
    }

    // A different query string is a different key.
    backendFetch.mockClear()
    await worker.fetch(new Request(`${ORIGIN}/api/public/tutors?subject=chemistry`), env)
    expect(backendFetch).toHaveBeenCalledTimes(1)

    // The card lookup reads through the same cache as P2: the page view after
    // the P2 call above needs no backend request of its own.
    respond = () => json(card(true))
    cache.stored.clear()
    backendFetch.mockClear()
    await worker.fetch(new Request(`${ORIGIN}/api/public/tutors/${TUTOR_ID}`), env)
    const cardPage = await worker.fetch(page(`/tutors/${TUTOR_ID}`), env)
    expect(cardPage.headers.has("X-Robots-Tag")).toBe(false)
    expect(backendFetch).toHaveBeenCalledTimes(1)
  })

  it("/api/* other paths are not cached", async () => {
    respond = () => json({ ok: true })
    const requests: [string, RequestInit | undefined][] = [
      // The logged-in directory hides blocked tutors per caller: never shared.
      ["/api/tutors", undefined],
      [`/api/tutors/${TUTOR_ID}`, undefined],
      ["/api/me", undefined],
      ["/api/public/tutors", { method: "POST", body: "{}" }],
      ["/api/public/tutors", { method: "HEAD" }],
    ]
    for (const [path, init] of requests) {
      backendFetch.mockClear()
      await worker.fetch(new Request(`${ORIGIN}${path}`, init), env)
      await worker.fetch(new Request(`${ORIGIN}${path}`, init), env)
      expect(backendFetch, `${init?.method ?? "GET"} ${path}`).toHaveBeenCalledTimes(2)
    }
    expect(cache.match).not.toHaveBeenCalled()
    expect(cache.put).not.toHaveBeenCalled()

    // A public path is stored only when it answered 200 and did not mark
    // itself private.
    const refused: [string, () => Response][] = [
      ["500", () => json({ detail: "boom" }, 500)],
      ["422", () => json({ detail: "bad cursor" }, 422)],
      [
        "private",
        () => new Response("{}", { status: 200, headers: { "cache-control": "private, no-store" } }),
      ],
    ]
    for (const [name, outcome] of refused) {
      respond = outcome
      backendFetch.mockClear()
      await worker.fetch(new Request(`${ORIGIN}/api/public/tutors?case=${name}`), env)
      await worker.fetch(new Request(`${ORIGIN}/api/public/tutors?case=${name}`), env)
      expect(backendFetch, name).toHaveBeenCalledTimes(2)
    }
    expect(cache.stored.size).toBe(0)
  })
})
