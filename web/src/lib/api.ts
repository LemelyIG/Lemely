import type { ActivityEvent } from "./types"
import { clearSession, getSession, markSessionExpired, setSession } from "./auth/storage"
import { isTokenExpired } from "./auth/jwt"
import { parseRetryAfter } from "./routeError"

/*
 * Typed API client. Frontend-first this run: request() hits the FastAPI backend
 * (proxied at /api by Vite) and callers pass a stub fallback used when the
 * backend is unreachable, so screens render against mock data during dev.
 *
 * When the backend lands, delete the `fallback` args — the call sites stay the
 * same. SSE job streams (extract / grade / aggregate) are consumed via
 * streamActivity(), which parses the `data:` lines of an EventSourceResponse.
 */

const BASE = "/api"

export class ApiError extends Error {
  status: number
  /**
   * The raw `detail` value from a FastAPI error body, when present —
   * structured (e.g. placement's 409, whose `detail` is a full
   * `PlacementAvailabilityDTO` object, not a string) as well as scalar. A
   * caller that needs the machine-readable shape (P4.8's "start now" retry,
   * which must render the same honest unavailable-reason panel S-03 shows
   * on load, not a generic failure) reads this instead of parsing `message`.
   * `undefined` when the body wasn't JSON or carried no `detail` key.
   */
  detail?: unknown
  /**
   * Seconds to wait before retrying, parsed from a 429 (or 503)'s
   * `Retry-After` header via `parseRetryAfter` (`lib/routeError.ts`) — the
   * live countdown `RouteErrorScreen`/`PortalErrorFallback` show for
   * `too-many-requests` comes from here. `undefined` when the response
   * carried no such header, or a fourth argument was never passed (every
   * `ApiError` constructed outside `request()`/`streamActivity()`, and every
   * test in this codebase that builds one by hand).
   */
  retryAfter?: number
  constructor(status: number, message: string, detail?: unknown, retryAfter?: number) {
    super(message)
    this.status = status
    this.detail = detail
    this.retryAfter = retryAfter
  }
}

/** Build the base headers for a request: JSON content-type + bearer token
 * (when a session is persisted), ahead of any caller-supplied headers so a
 * caller can still override either if it ever needs to. Skips the JSON
 * content-type for a `FormData` body — the browser must set its own
 * multipart boundary, so a caller uploading a file (e.g. `uploadScan` in
 * `lib/hooks/useStudentApi.ts`) can pass a `FormData` body straight through. */
function authHeaders(isFormData = false, token = getSession()?.accessToken): HeadersInit {
  return {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

/*
 * Silent refresh.
 *
 * Access tokens are short-lived by design, so hitting an expired one is the
 * normal course of events, not an error: the client redeems its refresh token
 * for a new one and replays the request. What the user should never see is the
 * server's own words about it — before this existed, an hour into a session
 * every request came back 401 "Invalid access token: Signature has expired" and
 * every screen rendered that string verbatim, with the route guard still
 * cheerfully rendering the portal because a (dead) session object was in
 * localStorage.
 */

/** Path prefix whose 401s mean "wrong credential", never "stale token". */
const AUTH_PATH = "/auth/"

/**
 * The refresh currently in flight, shared by every caller that wants one.
 *
 * Single-flight matters: on the first load after a session goes stale, a dozen
 * queries fire at once and all get 401s. Without this they would each POST
 * their own refresh, and the server would be answering a thundering herd for
 * one user opening one page.
 */
let refreshInFlight: Promise<RefreshOutcome> | null = null

/** Shape of `/auth/refresh`'s reply — the same DTO every sign-in returns. */
interface RefreshedSession {
  accessToken: string
  refreshToken: string | null
  userId: string
  role: string
}

/**
 * Why a refresh ended, which is not the same question as whether we got a token.
 *
 * `refused` and `unavailable` both leave the caller without one, but only the
 * first means the session is over: the server looked at the refresh token and
 * said no. A request that never arrived says nothing about the session, and
 * signing someone out over a dropped connection would lose their place for no
 * reason — so the two must not collapse into a single `null`.
 */
type RefreshOutcome =
  | { status: "renewed"; accessToken: string }
  | { status: "refused" }
  | { status: "unavailable" }

async function performRefresh(): Promise<RefreshOutcome> {
  const session = getSession()
  // Nothing to redeem. Unrecoverable, but there is no server verdict behind it,
  // so it is the caller's 401 — not this — that ends the session.
  if (!session?.refreshToken) return { status: "unavailable" }
  let res: Response
  try {
    res = await fetch(`${BASE}${AUTH_PATH}refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refreshToken: session.refreshToken }),
    })
  } catch {
    return { status: "unavailable" }
  }
  if (res.status === 401) return { status: "refused" }
  if (!res.ok) return { status: "unavailable" }
  const body = (await res.json()) as RefreshedSession
  setSession({
    accessToken: body.accessToken,
    // The backend does not rotate refresh tokens, but it does echo one back;
    // keep ours if it ever answers without one rather than losing the session.
    refreshToken: body.refreshToken ?? session.refreshToken,
    userId: body.userId,
    role: body.role,
  })
  return { status: "renewed", accessToken: body.accessToken }
}

/**
 * Renew the access token, at most once concurrently.
 *
 * Resolves to the new token, or `null` when we still don't have one. If the
 * server actively refused, the session is cleared and flagged as expired here,
 * so `AuthContext` hears about it and `RequireAuth` moves the user to the
 * session-ended screen, which offers the sign-in for their role and carries
 * the page they were on, instead of leaving them inside a dead portal.
 */
async function refreshSession(): Promise<string | null> {
  refreshInFlight ??= performRefresh().finally(() => {
    refreshInFlight = null
  })
  const outcome = await refreshInFlight
  if (outcome.status === "renewed") return outcome.accessToken
  if (outcome.status === "refused") {
    // Read the role before clearing: `SessionEnded` sends a parent back to
    // `/login/parent`, not the email form, and only the dying session knows
    // which one this reader was.
    const role = getSession()?.role
    clearSession()
    markSessionExpired(role)
  }
  return null
}

/**
 * The bearer token to send, renewing it first if it has already expired.
 *
 * Pre-empting the 401 keeps a page-load after a long absence from firing a
 * screenful of requests that are all certain to fail before any of them
 * recovers.
 */
async function tokenForRequest(): Promise<string | undefined> {
  const session = getSession()
  if (!session) return undefined
  if (session.refreshToken && isTokenExpired(session.accessToken)) {
    return (await refreshSession()) ?? undefined
  }
  return session.accessToken
}

/**
 * Turn a failed response's body text into the `{message, detail}` pair
 * FastAPI's `{"detail": ...}` convention decodes to.
 *
 * Shared by `request()`, `streamActivity()` and `uploadWithProgress()` so
 * there is exactly one place that knows this shape instead of three that can
 * quietly drift apart — see `request()`'s own comment below for the full
 * story of why the `detail` handling looks the way it does. A non-empty
 * string `detail` becomes `message` verbatim; a structured `detail` (e.g.
 * placement's 409 `PlacementAvailabilityDTO`) is preserved in the return
 * value for `ApiError.detail` but left out of `message`, which falls back to
 * `${status} ${statusText}` — the same fallback a body that isn't JSON, or
 * isn't present at all, gets.
 */
function parseErrorBody(
  status: number,
  statusText: string,
  bodyText: string,
): { message: string; detail?: unknown } {
  let message = `${status} ${statusText}`
  let detail: unknown
  try {
    const body: unknown = JSON.parse(bodyText)
    if (body && typeof body === "object" && "detail" in body) {
      detail = (body as { detail: unknown }).detail
      if (typeof detail === "string" && detail.length > 0) {
        message = detail
      }
    }
  } catch {
    // Body wasn't JSON (or empty) — keep the generic status text.
  }
  return { message, detail }
}

export async function request<T>(
  path: string,
  init?: RequestInit,
  fallback?: T,
): Promise<T> {
  try {
    const isAuthCall = path.startsWith(AUTH_PATH)
    // `...init` FIRST, then headers. The other order — which this had — meant a
    // caller that passed any `headers` of its own replaced the merged object
    // wholesale, silently dropping the `Authorization` header with it. The three
    // `useNotificationPrefsApi` calls that set a `Content-Type` were going out
    // with no bearer token at all as a result.
    const send = (token: string | undefined): Promise<Response> =>
      fetch(`${BASE}${path}`, {
        ...init,
        headers: {
          ...authHeaders(init?.body instanceof FormData, token),
          ...init?.headers,
        },
      })

    let res = await send(isAuthCall ? getSession()?.accessToken : await tokenForRequest())
    if (res.status === 401 && !isAuthCall) {
      // Not necessarily a stale token — a device signed out from another
      // browser lands here too — but the recovery is identical: ask for a new
      // one, and if the server won't give us one, the session is over. Replayed
      // at most once, so a 401 that refreshing cannot fix (an unrecognised role,
      // say) surfaces as itself instead of looping.
      //
      // Safe to replay because every body this client sends is a JSON string or
      // a FormData, both of which fetch can read twice. A streaming body would
      // not be, and would need buffering here first.
      const renewed = await refreshSession()
      if (renewed) res = await send(renewed)
    }
    if (!res.ok) {
      // FastAPI's default exception handler responds `{"detail": "..."}` for
      // every `HTTPException` this backend raises — a 422's "Reason X is not
      // currently firing for this student" (T-06 acknowledge) or a 403's
      // real tenancy message, for example. This was previously discarded
      // entirely in favour of the generic `"422 Unprocessable Entity"`
      // status text, which every screen's `error.message` render (Overview,
      // Classes, ClassRoster, MarkSchemes, ...) then surfaced verbatim —
      // real backend detail thrown away, not just here. Falls back to the
      // status text when the body isn't JSON or carries no `detail` string
      // (e.g. a 204, or a non-FastAPI failure upstream).
      const { message, detail } = parseErrorBody(res.status, res.statusText, await res.clone().text().catch(() => ""))
      // `Retry-After` matters here specifically because this is the one path
      // a 429 or a 503 from every ordinary API call comes through — see the
      // field's own doc on `ApiError` above.
      const retryAfter = parseRetryAfter(res.headers.get("Retry-After"), new Date())
      throw new ApiError(res.status, message, detail, retryAfter ?? undefined)
    }
    // A 204 (e.g. `DELETE /classes/{id}`) has no body — `res.json()` would
    // throw on the empty string. `T` is `void` at every such call site.
    if (res.status === 204) return undefined as T
    return (await res.json()) as T
  } catch (err) {
    if (fallback !== undefined) return fallback
    throw err instanceof ApiError ? err : new ApiError(0, String(err))
  }
}

/**
 * GET a binary endpoint with the bearer token and return an object URL for it.
 *
 * Exists because `<img src>` / `<embed src>` cannot send an `Authorization`
 * header, so any image behind an authenticated route (e.g. a paper's scan
 * thumbnail, `GET /papers/{id}/preview`) has to be fetched by hand and handed to
 * the element as a blob. Putting the token in the query string instead would
 * write a credential into every proxy access log.
 *
 * The caller owns the returned URL and must `URL.revokeObjectURL` it — see
 * `useScanPreview` in `lib/hooks/useTeacherApi.ts` for the ownership pattern.
 *
 * Carries the same silent-refresh handling as `request()` — pre-emptive renewal
 * plus one replay on a 401. An image left out of that would be the one thing on
 * the screen still showing a stale-session failure after every other panel had
 * quietly recovered.
 */
export async function fetchBlobUrl(path: string, init?: RequestInit): Promise<string> {
  const send = (token: string | undefined): Promise<Response> =>
    fetch(`${BASE}${path}`, {
      ...init,
      headers: { ...authHeaders(false, token), ...init?.headers },
    })

  let res = await send(await tokenForRequest())
  if (res.status === 401) {
    const renewed = await refreshSession()
    if (renewed) res = await send(renewed)
  }
  if (!res.ok) {
    throw new ApiError(res.status, `${res.status} ${res.statusText}`)
  }
  return URL.createObjectURL(await res.blob())
}

/**
 * Consume an SSE job stream (POST + bearer works via fetch; native EventSource
 * cannot). Yields each parsed `data:` payload until a terminal [DONE] sentinel.
 */
export async function* streamActivity(
  path: string,
  init?: RequestInit,
): AsyncGenerator<ActivityEvent> {
  // Same ordering fix as `request()`: `...init` first so a caller's headers
  // merge with the auth header instead of replacing it.
  const open = (token: string | undefined): Promise<Response> =>
    fetch(`${BASE}${path}`, {
      method: "POST",
      ...init,
      headers: { ...authHeaders(false, token), ...init?.headers },
    })

  // Job streams are the longest-running thing the app does, so they are the
  // most likely to be started on a token that has just gone stale — and a
  // failure here is silent (no body, generator ends, the screen just never
  // shows progress). Same recovery as `request()`.
  let res = await open(await tokenForRequest())
  if (res.status === 401) {
    const renewed = await refreshSession()
    if (renewed) res = await open(renewed)
  }
  /*
   * A non-OK response is a failure, not an empty stream (P4.2).
   *
   * This check did not exist, and its absence was silent by construction: a
   * 500 or a 503 from FastAPI carries a JSON body, so `res.body` was truthy,
   * the reader found no `data:` lines in it, the generator ended, and the
   * caller's `for await` loop simply finished. On `CorrectPaper` that meant a
   * student pressed "Mark this paper", watched the panel sit there, and got
   * back "Ready when you are" with no error, no result, and no way to tell
   * that anything had gone wrong at all.
   *
   * `request()` and `fetchBlobUrl()` above both throw here; this was the one
   * transport of the three that did not, which is why it is written the same
   * way as `request()`'s branch rather than more cheaply — a caller that reads
   * `ApiError.detail` must get the same shape from all three.
   */
  if (!res.ok) {
    const { message, detail } = parseErrorBody(res.status, res.statusText, await res.clone().text().catch(() => ""))
    const retryAfter = parseRetryAfter(res.headers.get("Retry-After"), new Date())
    throw new ApiError(res.status, message, detail, retryAfter ?? undefined)
  }
  if (!res.body) return
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ""
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const frames = buf.split("\n\n")
    buf = frames.pop() ?? ""
    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data:"))
      if (!line) continue
      const data = line.slice(5).trim()
      if (data === "[DONE]") return
      try {
        yield JSON.parse(data) as ActivityEvent
      } catch {
        yield { type: "log", message: data }
      }
    }
  }
}

/**
 * Bytes moved so far and, when the browser can tell us, the total.
 *
 * `total` is `undefined` — never a guess — when the upload is not
 * length-computable (`ProgressEvent.lengthComputable === false`, which
 * happens for a chunked or otherwise size-unknown transfer). A caller that
 * wants a percentage divides `loaded / total` itself and has to handle that
 * `undefined` case; inventing a fake total here would let it render a bar
 * that lies.
 */
export interface UploadProgress {
  loaded: number
  total: number | undefined
}

/** What `sendXhr` resolves to: shaped like the pieces of a `fetch` `Response`
 * that `parseErrorBody`/`JSON.parse` and the success path below actually
 * need, so both can be written once and shared with `request()`. */
interface XhrOutcome {
  status: number
  statusText: string
  text: string
  getHeader: (name: string) => string | null
}

/**
 * One XHR round trip for `uploadWithProgress`, wrapped in a promise.
 *
 * Not `request()`'s `fetch`-based `send` helper, because none of this exists
 * on `fetch`: `xhr.upload.onprogress` is the entire reason this transport is
 * XHR at all (see the module this is called from). Everything else here is
 * XHR's more awkward way of getting the same things `fetch` gives `request()`
 * for free — a settled promise, response text, and header lookup — so the
 * caller (`uploadWithProgress`) can build the same `ApiError` shape from
 * either transport.
 */
function sendXhr(
  path: string,
  form: FormData,
  token: string | undefined,
  onProgress: ((progress: UploadProgress) => void) | undefined,
  signal: AbortSignal | undefined,
): Promise<XhrOutcome> {
  return new Promise((resolve, reject) => {
    // Handle a signal that arrived pre-aborted (the caller cancelled before
    // this ever got to run) without opening a connection at all.
    if (signal?.aborted) {
      reject(new DOMException("Upload cancelled", "AbortError"))
      return
    }

    const xhr = new XMLHttpRequest()
    xhr.open("POST", `${BASE}${path}`)
    // FormData body, so no `Content-Type` here — `authHeaders`'s `isFormData`
    // branch omits it and the browser sets its own multipart boundary. See
    // that function's doc comment; the rule is the same one `request()`
    // follows for a `FormData` body, just applied through `setRequestHeader`
    // instead of a fetch `headers` object.
    const headers = authHeaders(true, token) as Record<string, string>
    for (const [key, value] of Object.entries(headers)) {
      xhr.setRequestHeader(key, value)
    }

    const onAbort = (): void => xhr.abort()
    signal?.addEventListener("abort", onAbort)
    const cleanup = (): void => signal?.removeEventListener("abort", onAbort)

    xhr.upload.onprogress = (event) => {
      onProgress?.({
        loaded: event.loaded,
        total: event.lengthComputable ? event.total : undefined,
      })
    }
    // `upload.onprogress` is not guaranteed to deliver one last event at
    // exactly 100% — a browser can coalesce the tail of the transfer into the
    // response phase instead of reporting it as progress. Firing a final
    // progress callback here explicitly means the bar always reaches full
    // once the browser itself says the upload is done, rather than
    // occasionally sitting a few points short while FastAPI is already
    // writing the reply.
    xhr.upload.onload = (event) => {
      onProgress?.({
        loaded: event.loaded,
        total: event.lengthComputable ? event.total : undefined,
      })
    }

    xhr.onload = () => {
      cleanup()
      resolve({
        status: xhr.status,
        statusText: xhr.statusText,
        text: xhr.responseText,
        getHeader: (name) => xhr.getResponseHeader(name),
      })
    }
    xhr.onerror = () => {
      cleanup()
      // Mirrors the shape a dropped `fetch` produces downstream: `request()`'s
      // outer `catch` wraps a non-`ApiError` rejection as
      // `ApiError(0, String(err))`, and status 0 is this codebase's spelling
      // of "no response reached the server at all" —
      // `describeQueryFailure`/`studentLoadFailureMessage` (and
      // `classifyRouteError`) all key off exactly that status, so a dropped
      // upload must not read as a worse or different failure than any other
      // dropped request in the app.
      reject(new ApiError(0, "Failed to fetch"))
    }
    xhr.onabort = () => {
      cleanup()
      reject(new DOMException("Upload cancelled", "AbortError"))
    }

    // `send()` can throw synchronously (a malformed URL, a blocked scheme).
    // The `Promise` constructor turns that into a rejection on its own, but
    // it would leave the abort listener attached to the caller's signal and
    // the `xhr` alive with it, so the cleanup has to be explicit here.
    try {
      xhr.send(form)
    } catch (err) {
      cleanup()
      reject(err)
    }
  })
}

/**
 * POST multipart `FormData` via `XMLHttpRequest`, reporting upload progress
 * through `onProgress` as it goes. Everything else about this call is meant
 * to be indistinguishable from `request()` — same base URL, same auth
 * header, same pre-emptive refresh, same one-shot 401 replay, same `detail`
 * extraction, same `Retry-After` handling, same network-failure shape — see
 * `sendXhr` above for the parts XHR does differently to get there. The one
 * thing `request()` cannot offer at all is `onProgress`: `fetch` has no way
 * to report bytes sent for a request body, so `CorrectPaper.tsx`'s paper
 * upload — often several megabytes over a slow connection — used to sit
 * with nothing on screen moving until the whole thing landed.
 */
export async function uploadWithProgress<T>(
  path: string,
  form: FormData,
  options?: { onProgress?: (progress: UploadProgress) => void; signal?: AbortSignal },
): Promise<T> {
  const { onProgress, signal } = options ?? {}

  try {
    return await uploadOnce<T>(path, form, onProgress, signal)
  } catch (err) {
    // The same normalisation `request()` does at its own catch, and for the
    // same reason: without it a 2xx whose body is not JSON — a captive portal
    // or a misconfigured proxy answering `200 text/html` — throws a bare
    // `SyntaxError`, which `correctionFailureMessage` falls through to its
    // "any Error with a message" branch and prints verbatim. The student is
    // then shown `Unexpected token '<', "<!DOCTYPE "... is not valid JSON`
    // in the marking panel, which is exactly the engine wording
    // `correctionOutcome.ts`'s own header exists to keep off this screen.
    // An unguarded `res.json()` inside `refreshSession` reaches here the same
    // way.
    //
    // `AbortError` is deliberately let through as itself: a cancel is not a
    // failure, and a caller needs to tell the two apart.
    if (err instanceof ApiError) throw err
    if (err instanceof DOMException && err.name === "AbortError") throw err
    throw new ApiError(0, String(err))
  }
}

/** One `uploadWithProgress` attempt, unwrapped — see its caller for why the
 * normalisation lives one frame out. */
async function uploadOnce<T>(
  path: string,
  form: FormData,
  onProgress: ((progress: UploadProgress) => void) | undefined,
  signal: AbortSignal | undefined,
): Promise<T> {
  let result = await sendXhr(path, form, await tokenForRequest(), onProgress, signal)
  if (result.status === 401) {
    // Same replay-once rule as `request()` (see its own comment): safe here
    // because a `FormData` body is fully buffered by the browser before
    // `xhr.send()` even starts uploading it, so sending it a second time on a
    // renewed token reads it from the same buffer rather than needing the
    // original `File`s to still be around.
    const renewed = await refreshSession()
    if (renewed) result = await sendXhr(path, form, renewed, onProgress, signal)
  }
  if (result.status < 200 || result.status >= 300) {
    const { message, detail } = parseErrorBody(result.status, result.statusText, result.text)
    const retryAfter = parseRetryAfter(result.getHeader("Retry-After"), new Date())
    throw new ApiError(result.status, message, detail, retryAfter ?? undefined)
  }
  // Same 204 special-case as `request()` — `JSON.parse("")` would throw.
  if (result.status === 204) return undefined as T
  return JSON.parse(result.text) as T
}
