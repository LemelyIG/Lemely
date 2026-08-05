import type { ActivityEvent } from "./types"
import { getSession } from "./auth/storage"

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
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** Build the base headers for a request: JSON content-type + bearer token
 * (when a session is persisted), ahead of any caller-supplied headers so a
 * caller can still override either if it ever needs to. Skips the JSON
 * content-type for a `FormData` body — the browser must set its own
 * multipart boundary, so a caller uploading a file (e.g. `uploadScan` in
 * `lib/hooks/useStudentApi.ts`) can pass a `FormData` body straight through. */
function authHeaders(isFormData = false): HeadersInit {
  const token = getSession()?.accessToken
  return {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

export async function request<T>(
  path: string,
  init?: RequestInit,
  fallback?: T,
): Promise<T> {
  try {
    const res = await fetch(`${BASE}${path}`, {
      headers: { ...authHeaders(init?.body instanceof FormData), ...init?.headers },
      ...init,
    })
    if (!res.ok) throw new ApiError(res.status, `${res.status} ${res.statusText}`)
    return (await res.json()) as T
  } catch (err) {
    if (fallback !== undefined) return fallback
    throw err instanceof ApiError ? err : new ApiError(0, String(err))
  }
}

/**
 * Consume an SSE job stream (POST + bearer works via fetch; native EventSource
 * cannot). Yields each parsed `data:` payload until a terminal [DONE] sentinel.
 */
export async function* streamActivity(
  path: string,
  init?: RequestInit,
): AsyncGenerator<ActivityEvent> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { ...authHeaders(), ...init?.headers },
    ...init,
  })
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
