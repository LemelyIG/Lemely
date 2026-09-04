import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError, uploadWithProgress, type UploadProgress } from "@/lib/api"
import { setSession } from "@/lib/auth/storage"
import { uploadScan } from "@/lib/hooks/useStudentApi"

/*
 * PR 4 of the loading/error-screens programme — `uploadWithProgress()`.
 *
 * `request()` is `fetch`-based, and `fetch` cannot report upload progress, so
 * a multipart scan upload used to sit with nothing on screen moving until the
 * whole file landed. `XMLHttpRequest` can report it via `xhr.upload.onprogress`,
 * which is the entire reason this function exists on a different transport —
 * see `lib/api.ts`'s doc comment on `uploadWithProgress`.
 *
 * The risk with a second transport is a second, drifting copy of everything
 * `request()` already gets right: the auth header, pre-emptive refresh, the
 * one-shot 401 replay, FastAPI `detail` extraction, `Retry-After`, and the
 * network-failure shape `describeQueryFailure`/`studentLoadFailureMessage`
 * key off. Every describe block below pins one of those against a hand-rolled
 * `FakeXHR`, following the same stubbed-globals pattern
 * `tests/unit/sessionRefresh.test.ts` uses for `fetch`/`localStorage`; this
 * runner has no DOM (`vitest.config.ts`, D3.20), so `XMLHttpRequest` does not
 * exist here either and has to be stubbed the same way.
 *
 * `uploadWithProgress` reaches its XHR through at least one microtask
 * boundary (`await tokenForRequest()` runs first), so a test can never assume
 * the instance exists the instant it calls the function — `waitForXhr(n)`
 * below polls until the expected number of instances has been constructed,
 * the same way `vi.waitFor` is meant to be used against async, event-driven
 * code with no single "the work is done" promise to await in between steps.
 */

function encode(payload: Record<string, unknown>): string {
  return `header.${Buffer.from(JSON.stringify(payload)).toString("base64url")}.signature`
}

/** A token that is valid for another hour. */
function live(): string {
  return encode({ exp: Math.floor(Date.now() / 1000) + 3600 })
}

/** A token whose `exp` has already passed. */
function dead(): string {
  return encode({ exp: Math.floor(Date.now() / 1000) - 3600 })
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

/** A minimal event shape matching the bits of `ProgressEvent` this module
 * reads (`loaded`, `total`, `lengthComputable`). */
interface FakeProgressEvent {
  loaded: number
  total: number
  lengthComputable: boolean
}

type ProgressHandler = ((event: FakeProgressEvent) => void) | null

/**
 * A hand-rolled `XMLHttpRequest` stand-in, test-driven rather than
 * network-driven: `respond`/`networkError`/`progress`/`uploadComplete` are
 * called directly by each test to fire the same events a real browser would,
 * in whatever order the test wants to pin.
 */
class FakeXHR {
  static instances: FakeXHR[] = []

  method = ""
  url = ""
  readonly headers: Record<string, string> = {}
  readonly upload: { onprogress: ProgressHandler; onload: ProgressHandler } = {
    onprogress: null,
    onload: null,
  }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  onabort: (() => void) | null = null
  status = 0
  statusText = ""
  responseText = ""
  sentBody: FormData | null = null
  private responseHeaders: Record<string, string> = {}
  private aborted = false

  constructor() {
    FakeXHR.instances.push(this)
  }

  open(method: string, url: string): void {
    this.method = method
    this.url = url
  }

  setRequestHeader(key: string, value: string): void {
    this.headers[key] = value
  }

  getResponseHeader(name: string): string | null {
    const key = Object.keys(this.responseHeaders).find(
      (k) => k.toLowerCase() === name.toLowerCase(),
    )
    return key ? this.responseHeaders[key] : null
  }

  send(body: FormData): void {
    this.sentBody = body
  }

  abort(): void {
    this.aborted = true
    this.onabort?.()
  }

  wasAborted(): boolean {
    return this.aborted
  }

  // ── test-driven event firing ─────────────────────────────────────────────

  respond(
    status: number,
    statusText: string,
    body: string,
    headers: Record<string, string> = {},
  ): void {
    this.status = status
    this.statusText = statusText
    this.responseText = body
    this.responseHeaders = headers
    this.onload?.()
  }

  networkError(): void {
    this.onerror?.()
  }

  progress(loaded: number, total: number | undefined): void {
    this.upload.onprogress?.({
      loaded,
      total: total ?? 0,
      lengthComputable: total !== undefined,
    })
  }

  uploadComplete(loaded: number, total: number | undefined): void {
    this.upload.onload?.({
      loaded,
      total: total ?? 0,
      lengthComputable: total !== undefined,
    })
  }
}

/** Wait until exactly `n` `FakeXHR` instances have been constructed, then
 * return the most recent one. */
async function waitForXhr(n: number): Promise<FakeXHR> {
  await vi.waitFor(() => {
    if (FakeXHR.instances.length < n) throw new Error(`only ${FakeXHR.instances.length} so far`)
  })
  const xhr = FakeXHR.instances[n - 1]
  if (!xhr) throw new Error(`no FakeXHR instance #${n} was constructed`)
  return xhr
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  const store = new Map<string, string>()
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value)
    },
    removeItem: (key: string) => {
      store.delete(key)
    },
  })
  fetchMock = vi.fn()
  vi.stubGlobal("fetch", fetchMock)
  FakeXHR.instances = []
  vi.stubGlobal("XMLHttpRequest", FakeXHR as unknown as typeof XMLHttpRequest)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function session(overrides: Partial<Parameters<typeof setSession>[0]> = {}): void {
  setSession({
    accessToken: live(),
    refreshToken: "refresh-token",
    userId: "user-1",
    role: "student",
    ...overrides,
  })
}

describe("transport basics", () => {
  it("posts to the base URL with the given path", async () => {
    session()
    const promise = uploadWithProgress<{ paperId: string }>("/student/uploads", new FormData())
    const xhr = await waitForXhr(1)
    expect(xhr.method).toBe("POST")
    expect(xhr.url).toBe("/api/student/uploads")
    xhr.respond(200, "OK", JSON.stringify({ paperId: "p1" }))
    await expect(promise).resolves.toEqual({ paperId: "p1" })
  })

  it("sends the bearer token but sets no Content-Type, so the browser picks the multipart boundary", async () => {
    const token = live()
    session({ accessToken: token })
    const promise = uploadWithProgress("/student/uploads", new FormData())
    const xhr = await waitForXhr(1)
    expect(xhr.headers.Authorization).toBe(`Bearer ${token}`)
    expect(xhr.headers["Content-Type"]).toBeUndefined()
    xhr.respond(200, "OK", "{}")
    await promise
  })

  it("sends the FormData body untouched", async () => {
    session()
    const form = new FormData()
    form.append("scan", "fake-file-contents")
    const promise = uploadWithProgress("/student/uploads", form)
    const xhr = await waitForXhr(1)
    expect(xhr.sentBody).toBe(form)
    xhr.respond(200, "OK", "{}")
    await promise
  })
})

describe("progress semantics", () => {
  it("delivers loaded/total to onProgress as XHR reports them", async () => {
    session()
    const events: UploadProgress[] = []
    const promise = uploadWithProgress("/student/uploads", new FormData(), {
      onProgress: (p) => events.push(p),
    })
    const xhr = await waitForXhr(1)
    xhr.progress(50, 200)
    xhr.progress(150, 200)
    xhr.respond(200, "OK", "{}")
    await promise
    expect(events).toEqual([
      { loaded: 50, total: 200 },
      { loaded: 150, total: 200 },
    ])
  })

  it("reports total: undefined when the transfer is not length-computable, never a guessed value", async () => {
    session()
    const events: UploadProgress[] = []
    const promise = uploadWithProgress("/student/uploads", new FormData(), {
      onProgress: (p) => events.push(p),
    })
    const xhr = await waitForXhr(1)
    xhr.progress(1024, undefined)
    xhr.respond(200, "OK", "{}")
    await promise
    expect(events).toEqual([{ loaded: 1024, total: undefined }])
  })

  it("fires a final progress callback on upload completion, so the UI does not sit short of 100%", async () => {
    // Regular `onprogress` stops at 97 of a 100-byte body — never itself
    // claiming completion — and only `upload.onload` (fired by the browser
    // once the upload phase is done) reports the last few bytes.
    session()
    const events: UploadProgress[] = []
    const promise = uploadWithProgress("/student/uploads", new FormData(), {
      onProgress: (p) => events.push(p),
    })
    const xhr = await waitForXhr(1)
    xhr.progress(97, 100)
    xhr.uploadComplete(100, 100)
    xhr.respond(200, "OK", "{}")
    await promise
    expect(events).toEqual([
      { loaded: 97, total: 100 },
      { loaded: 100, total: 100 },
    ])
  })

  it("does not require onProgress to be supplied", async () => {
    session()
    const promise = uploadWithProgress("/student/uploads", new FormData())
    const xhr = await waitForXhr(1)
    xhr.progress(10, 20)
    xhr.respond(200, "OK", "{}")
    await expect(promise).resolves.toEqual({})
  })
})

describe("pre-emptive refresh", () => {
  it("refreshes before sending when the access token is already known to be expired", async () => {
    session({ accessToken: dead() })
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        accessToken: "renewed-token",
        refreshToken: "refresh-token",
        userId: "user-1",
        role: "student",
      }),
    )

    const promise = uploadWithProgress("/student/uploads", new FormData())
    // The refresh is awaited before the XHR is ever opened.
    const xhr = await waitForXhr(1)
    expect(xhr.headers.Authorization).toBe("Bearer renewed-token")
    xhr.respond(200, "OK", "{}")
    await promise
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe("401 replay", () => {
  it("refreshes and replays exactly once, so the caller never sees the 401", async () => {
    session()
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        accessToken: "renewed-token",
        refreshToken: "refresh-token",
        userId: "user-1",
        role: "student",
      }),
    )

    const promise = uploadWithProgress<{ paperId: string }>("/student/uploads", new FormData())
    const first = await waitForXhr(1)
    first.respond(401, "Unauthorized", JSON.stringify({ detail: "expired" }))

    const second = await waitForXhr(2)
    expect(second.headers.Authorization).toBe("Bearer renewed-token")
    second.respond(200, "OK", JSON.stringify({ paperId: "p1" }))

    await expect(promise).resolves.toEqual({ paperId: "p1" })
    expect(fetchMock).toHaveBeenCalledTimes(1) // exactly one refresh
    expect(FakeXHR.instances).toHaveLength(2) // exactly one replay, never a loop
  })

  it("surfaces as an ApiError, not an infinite loop, when the refresh itself fails", async () => {
    session()
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { detail: "Refresh token rejected" }))

    const promise = uploadWithProgress("/student/uploads", new FormData())
    const xhr = await waitForXhr(1)
    xhr.respond(
      401,
      "Unauthorized",
      JSON.stringify({ detail: "Invalid access token: Signature has expired" }),
    )

    await expect(promise).rejects.toMatchObject({
      status: 401,
      message: "Invalid access token: Signature has expired",
    })
    expect(fetchMock).toHaveBeenCalledTimes(1) // one refresh attempt, no retry loop
    expect(FakeXHR.instances).toHaveLength(1) // never replayed with no renewed token
  })
})

describe("error fidelity", () => {
  it("extracts a FastAPI string detail as the ApiError message", async () => {
    session()
    const promise = uploadWithProgress("/student/uploads", new FormData())
    const xhr = await waitForXhr(1)
    xhr.respond(
      422,
      "Unprocessable Entity",
      JSON.stringify({ detail: "No mark scheme available for this paper" }),
    )
    await expect(promise).rejects.toMatchObject({
      status: 422,
      message: "No mark scheme available for this paper",
    })
  })

  it("preserves a structured detail on ApiError.detail without flattening it into the message", async () => {
    session()
    const promise = uploadWithProgress("/student/uploads", new FormData())
    const xhr = await waitForXhr(1)
    xhr.respond(
      409,
      "Conflict",
      JSON.stringify({ detail: { reason: "already-marking", paperId: "p1" } }),
    )
    let caught: unknown
    try {
      await promise
    } catch (err) {
      caught = err
    }
    expect(caught).toBeInstanceOf(ApiError)
    const err = caught as ApiError
    expect(err.message).toBe("409 Conflict")
    expect(err.detail).toEqual({ reason: "already-marking", paperId: "p1" })
  })

  it("falls back to the status text for a non-JSON body", async () => {
    session()
    const promise = uploadWithProgress("/student/uploads", new FormData())
    const xhr = await waitForXhr(1)
    xhr.respond(500, "Internal Server Error", "<html>not json</html>")
    await expect(promise).rejects.toMatchObject({
      status: 500,
      message: "500 Internal Server Error",
    })
  })

  it("falls back to the status text for an empty body", async () => {
    session()
    const promise = uploadWithProgress("/student/uploads", new FormData())
    const xhr = await waitForXhr(1)
    xhr.respond(413, "Payload Too Large", "")
    await expect(promise).rejects.toMatchObject({
      status: 413,
      message: "413 Payload Too Large",
    })
  })
})

describe("Retry-After", () => {
  it("lands the parsed seconds on the ApiError", async () => {
    session()
    const promise = uploadWithProgress("/student/uploads", new FormData())
    const xhr = await waitForXhr(1)
    xhr.respond(429, "Too Many Requests", JSON.stringify({ detail: "Slow down" }), {
      "Retry-After": "30",
    })
    await expect(promise).rejects.toMatchObject({ status: 429, retryAfter: 30 })
  })

  it("leaves retryAfter undefined when the header is absent", async () => {
    session()
    const promise = uploadWithProgress("/student/uploads", new FormData())
    const xhr = await waitForXhr(1)
    xhr.respond(429, "Too Many Requests", JSON.stringify({ detail: "Slow down" }))
    await expect(promise).rejects.toMatchObject({ status: 429, retryAfter: undefined })
  })
})

describe("network failure", () => {
  it("rejects with the same ApiError(0, …) shape a dropped fetch produces, so downstream classification matches", async () => {
    session()
    const promise = uploadWithProgress("/student/uploads", new FormData())
    const xhr = await waitForXhr(1)
    xhr.networkError()

    let caught: unknown
    try {
      await promise
    } catch (err) {
      caught = err
    }
    expect(caught).toBeInstanceOf(ApiError)
    // status 0 is exactly what `describeQueryFailure`/`studentLoadFailureMessage`
    // both key off to classify "no response reached the server at all" —
    // see `lib/queryFailure.ts` and `lib/studentOutcome.ts`.
    expect((caught as ApiError).status).toBe(0)
  })
})

describe("abort", () => {
  it("rejects without ever opening a connection when the signal is already aborted", async () => {
    session()
    const controller = new AbortController()
    controller.abort()

    await expect(
      uploadWithProgress("/student/uploads", new FormData(), { signal: controller.signal }),
    ).rejects.toMatchObject({ name: "AbortError" })
    expect(FakeXHR.instances).toHaveLength(0)
  })

  it("aborts the in-flight XHR and rejects when the signal fires mid-upload", async () => {
    session()
    const controller = new AbortController()
    const promise = uploadWithProgress("/student/uploads", new FormData(), {
      signal: controller.signal,
    })
    const xhr = await waitForXhr(1)

    controller.abort()

    await expect(promise).rejects.toMatchObject({ name: "AbortError" })
    expect(xhr.wasAborted()).toBe(true)
  })

  it("detaches its abort listener once the upload has settled", async () => {
    // Without this the suite could not tell a cleaned-up listener from a
    // leaked one: every other assertion passes either way. A leaked listener
    // keeps the caller's signal holding the `xhr` alive, and worse, aborting
    // later for an unrelated reason would call `abort()` on a request that
    // already finished.
    session()
    const controller = new AbortController()
    const promise = uploadWithProgress<{ paperId: string }>(
      "/student/uploads",
      new FormData(),
      { signal: controller.signal },
    )
    const xhr = await waitForXhr(1)
    xhr.respond(200, "OK", JSON.stringify({ paperId: "p1" }))
    await promise

    controller.abort()

    expect(xhr.wasAborted()).toBe(false)
  })
})

describe("response body", () => {
  it("returns undefined for a 204, rather than parsing an empty body", async () => {
    // Same special case `request()` carries: `JSON.parse("")` throws, so a
    // no-content reply has to short-circuit before it.
    session()
    const promise = uploadWithProgress("/student/uploads", new FormData())
    const xhr = await waitForXhr(1)
    xhr.respond(204, "No Content", "")

    await expect(promise).resolves.toBeUndefined()
  })

  it("reports a 2xx whose body is not JSON as a network-shaped failure", async () => {
    // A captive portal or a misconfigured proxy answering `200 text/html` for
    // an API path. Before the normalisation this threw a bare `SyntaxError`,
    // which `correctionFailureMessage` prints verbatim — the student was
    // shown `Unexpected token '<', "<!DOCTYPE "... is not valid JSON` in the
    // marking panel. `ApiError(0)` is what every other transport reports for
    // "nothing usable came back", and what the failure-copy modules classify.
    session()
    const promise = uploadWithProgress("/student/uploads", new FormData())
    const xhr = await waitForXhr(1)
    xhr.respond(200, "OK", "<!DOCTYPE html><html><body>Sign in to the wifi</body></html>")

    let caught: unknown
    try {
      await promise
    } catch (err) {
      caught = err
    }
    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as ApiError).status).toBe(0)
  })
})

describe("uploadScan (useStudentApi)", () => {
  it("builds the FormData FastAPI expects and posts it to /student/uploads", async () => {
    session()
    const scan = new File(["scan-bytes"], "scan.jpg", { type: "image/jpeg" })
    const markScheme = new File(["ms-bytes"], "ms.pdf", { type: "application/pdf" })

    const promise = uploadScan(scan, markScheme)
    const xhr = await waitForXhr(1)
    expect(xhr.url).toBe("/api/student/uploads")
    const sent = xhr.sentBody
    expect(sent).toBeInstanceOf(FormData)
    expect((sent as FormData).get("scan")).toBe(scan)
    expect((sent as FormData).get("mark_scheme")).toBe(markScheme)

    xhr.respond(200, "OK", JSON.stringify({ paperId: "p1" }))
    await expect(promise).resolves.toEqual({ paperId: "p1" })
  })

  it("omits mark_scheme entirely when none is given", async () => {
    session()
    const scan = new File(["scan-bytes"], "scan.jpg", { type: "image/jpeg" })

    const promise = uploadScan(scan)
    const xhr = await waitForXhr(1)
    const sent = xhr.sentBody as FormData
    expect(sent.has("mark_scheme")).toBe(false)

    xhr.respond(200, "OK", JSON.stringify({ paperId: "p1" }))
    await promise
  })

  it("forwards onProgress through to the XHR upload events", async () => {
    session()
    const events: UploadProgress[] = []
    const scan = new File(["scan-bytes"], "scan.jpg", { type: "image/jpeg" })

    const promise = uploadScan(scan, undefined, { onProgress: (p) => events.push(p) })
    const xhr = await waitForXhr(1)
    xhr.progress(5, 10)
    xhr.respond(200, "OK", JSON.stringify({ paperId: "p1" }))
    await promise

    expect(events).toEqual([{ loaded: 5, total: 10 }])
  })
})
