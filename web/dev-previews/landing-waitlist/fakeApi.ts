/* Preview-only fake backend: just enough of /api/admin/waitlist for the real admin screen. */
import type { WaitlistApplicant, WaitlistPage, WaitlistQuery } from "@/lib/waitlist-api"
import { APPLICANTS } from "./data"

export type AdminMode = "data" | "loading" | "empty" | "error"

const rows: WaitlistApplicant[] = APPLICANTS.map((r) => ({ ...r }))
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })

function page(q: URLSearchParams, mode: AdminMode): WaitlistPage {
  const base = (mode === "empty" ? [] : rows).filter(
    (r) =>
      (!q.get("q") || r.email.includes(q.get("q")!.toLowerCase()) || (r.name ?? "").toLowerCase().includes(q.get("q")!.toLowerCase())) &&
      (!q.get("role") || r.role === q.get("role")) &&
      (!q.get("level") || r.levels.includes(q.get("level") as never)) &&
      (!q.get("subject") || r.subjects.includes(q.get("subject")!) || (q.get("subject") === "other" && r.otherSubjects.length > 0)) &&
      (!q.get("board") || r.examBoards.includes(q.get("board") as never)) &&
      (!q.get("session") || r.examSession === q.get("session")) &&
      (!q.get("emailConfirmed") || String(r.emailConfirmed) === q.get("emailConfirmed")) &&
      (!q.get("createdFrom") || r.createdAt.slice(0, 10) >= q.get("createdFrom")!),
  )
  const c = (f: (r: WaitlistApplicant) => boolean) => base.filter(f).length
  const counts = { all: base.length, new: c((r) => r.status === "new"), contacted: c((r) => r.status === "contacted"), invited: c((r) => r.status === "invited"), declined: c((r) => r.status === "declined"), partial: c((r) => r.partial) }
  const status = q.get("status") as WaitlistQuery["status"] | null
  const items = base.filter((r) => !status || (status === "partial" ? r.partial : r.status === status))
  const key = ({ created_at: "createdAt", email: "email", name: "name", role: "role", status: "status", exam_session: "examSession" } as const)[(q.get("sort") as never) ?? "created_at"]
  items.sort((a, b) => ((a[key] ?? "") < (b[key] ?? "") ? -1 : 1) * (q.get("order") === "asc" ? 1 : -1))
  return { items, total: items.length, page: 1, pageSize: 50, counts }
}

/** Replaces fetch for /api/me/profile and /api/admin/waitlist; every other /api call hangs. */
export function installFakeApi(mode: AdminMode) {
  const realFetch = window.fetch.bind(window)
  window.fetch = async (input, init) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, location.origin)
    const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase()
    if (url.pathname === "/api/me/profile")
      return json({ displayName: "Admin", email: "admin@example.com", role: "platform_admin", emailVerified: true, avatarUrl: null })
    if (url.pathname === "/api/admin/waitlist") {
      if (mode === "loading") return new Promise<Response>(() => {})
      if (mode === "error") return json({ detail: "boom" }, 500)
      return json(page(url.searchParams, mode))
    }
    const one = url.pathname.match(/^\/api\/admin\/waitlist\/([^/]+)$/)
    if (one && method === "PATCH") {
      const row = rows.find((r) => r.id === one[1])
      if (!row) return json({}, 404)
      Object.assign(row, JSON.parse(String(init?.body ?? "{}")))
      return json(row)
    }
    if (url.pathname.startsWith("/api/")) return new Promise<Response>(() => {})
    return realFetch(input, init)
  }
}
