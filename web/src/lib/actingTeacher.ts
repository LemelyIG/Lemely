import { hashKey, type QueryKey } from "@tanstack/react-query"
import { useSyncExternalStore } from "react"

/*
 * Acting for a lead teacher (paymob billing, phase 03 follow-up).
 *
 * An assistant works on the lead teacher's classes, papers and quizzes by sending
 * `X-Lemely-Acting-Teacher: <lead user id>` on a request. The server runs that request as the
 * lead, but only on the routes that adopted `require_team_permission`, and only when the
 * assistant's role allows the action (403 `team_permission_denied` otherwise). This module is the
 * client's whole side of that contract, kept in one place so the rule "which requests carry the
 * header" can be read, and tested, in one file.
 *
 * ── The header goes on an allow-list, never a deny-list ─────────────────────────────────────────
 *
 * `ADOPTED_ROUTES` mirrors the endpoint to permission table in
 * `.superpowers/sdd/p03-constraints.md` row for row. A route that is not listed does not get the
 * header, which is the safe direction to be wrong in: an unlisted adopted route simply answers as
 * the assistant themselves (their own empty data, or a 403), while a route that wrongly carried
 * the header could act on a lead's team where it must not. Team, billing, auth, account, devices
 * and tutoring routes are lead-only or own-account by rule, and none of them is on the list.
 * `tests/unit/actingTeacher.test.ts` pins the list, pins the exclusions, and fails when the app
 * starts calling a teacher endpoint nobody has classified.
 *
 * ── Who you are acting as lives in memory, not in storage ──────────────────────────────────────
 *
 * The request layer reads `getActingLead()`, a module variable, and nothing here reads
 * `sessionStorage` on its own. The teacher portal's provider restores a stored choice only after
 * it has checked it against the live membership list, so a stale id (a removed assistant, another
 * account that signed in on the same tab) can never reach a request. The choice is remembered per
 * tab in `sessionStorage` so a reload keeps it, and a second tab starts as yourself.
 *
 * ── The query cache is partitioned by who you act as ───────────────────────────────────────────
 *
 * `actingQueryHash` is the client's `queryKeyHashFn`: while acting for a lead it appends the lead
 * id to every query's hash, so `["teacher", "classes"]` for you and for each lead are different
 * cache entries, in memory and in the persisted copy. Partitioning by hash rather than by editing
 * ~70 query keys means a hook written next month is partitioned without anyone remembering to
 * do it. Own-account roots (`OWN_ACCOUNT_ROOTS`) are the one exception: the membership list that
 * drives the switcher must not vanish when you pick someone.
 */

/** The request header the backend reads (`lemely/web/deps.py`, `ACTING_TEACHER_HEADER`). */
export const ACTING_TEACHER_HEADER = "X-Lemely-Acting-Teacher"

/**
 * Every route that honours the header, as a path under `/api` with `:param` for an id segment.
 * Mirrors the adoption table (52 rows). Keep in step with `tests/test_team_permission_adoption.py`.
 */
export const ADOPTED_ROUTES: readonly string[] = [
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
]

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")

const ADOPTED_PATTERNS: readonly RegExp[] = ADOPTED_ROUTES.map(
  (template) =>
    new RegExp(
      `^${template
        .split("/")
        .map((segment) => (segment.startsWith(":") ? "[^/]+" : escapeRegExp(segment)))
        .join("/")}$`,
    ),
)

/** Whether a request path (relative to `/api`, query and fragment ignored) is an adopted route. */
export function isActingRoute(path: string): boolean {
  const bare = path.split(/[?#]/, 1)[0] ?? ""
  return ADOPTED_PATTERNS.some((pattern) => pattern.test(bare))
}

/* ── Who is being acted for ──────────────────────────────────────────────────────────────────── */

/** The lead teacher an assistant is working for right now. */
export interface ActingLead {
  /** The lead's user id: the header value. */
  leadId: string
  /** For the refusal message only; `null` until the membership list has loaded. */
  leadName: string | null
}

let current: ActingLead | null = null
const listeners = new Set<() => void>()

export function getActingLead(): ActingLead | null {
  return current
}

/** Start, change or stop acting. Passing the same lead again is a no-op. */
export function setActingLead(lead: ActingLead | null): void {
  if (current?.leadId === lead?.leadId && current?.leadName === lead?.leadName) return
  current = lead
  for (const listener of listeners) listener()
}

export function subscribeActingLead(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** React view of `getActingLead`. */
export function useActingLead(): ActingLead | null {
  return useSyncExternalStore(subscribeActingLead, getActingLead, getActingLead)
}

/**
 * The lead a request to `path` should act for, or `null` when it should go out as the caller:
 * not acting, `asSelf` (a call on an own-account screen that happens to use an adopted route), or
 * a route that is not on the allow-list.
 */
export function actingLeadFor(path: string, asSelf = false): ActingLead | null {
  if (current === null || asSelf || !isActingRoute(path)) return null
  return current
}

/** The header to merge into a request for `lead`. Empty when the request goes out as the caller. */
export function actingHeaders(lead: ActingLead | null): Record<string, string> {
  return lead ? { [ACTING_TEACHER_HEADER]: lead.leadId } : {}
}

/* ── Remembering the choice for this tab ─────────────────────────────────────────────────────── */

const STORAGE_KEY = "lemely.acting-lead"

/** The lead id this tab last chose, or `null`. Storage can be missing or throw (private windows). */
export function readStoredLeadId(): string | null {
  try {
    const value = window.sessionStorage.getItem(STORAGE_KEY)
    return value && value.trim() !== "" ? value : null
  } catch {
    return null
  }
}

export function storeLeadId(leadId: string | null): void {
  try {
    if (leadId === null) window.sessionStorage.removeItem(STORAGE_KEY)
    else window.sessionStorage.setItem(STORAGE_KEY, leadId)
  } catch {
    // The choice just won't survive a reload. Nothing else depends on it.
  }
}

/** Forget everything about acting: the in-memory lead and this tab's stored choice. */
export function clearActingLead(): void {
  setActingLead(null)
  storeLeadId(null)
}

/* ── Cache partitioning ──────────────────────────────────────────────────────────────────────── */

/** What `actingQueryHash` appends. Also how the persister recognises a partitioned entry. */
const PARTITION_MARK = "@acting:"

/**
 * Query-key roots that belong to the caller's own account whoever they act for. The membership
 * list is read through `["team", "memberships"]`; if that were partitioned too, picking a lead
 * would swap the observer onto an empty entry and the switcher would lose its own options.
 * Every route under these roots is lead-only or own-account, so none is on `ADOPTED_ROUTES`.
 */
export const OWN_ACCOUNT_ROOTS: ReadonlySet<unknown> = new Set(["team"])

/**
 * The client's `queryKeyHashFn`. Identical to the default when not acting, so everything that
 * reads the cache by key (`getQueryData`, `invalidateQueries`, tests) behaves as before.
 */
export function actingQueryHash(queryKey: QueryKey): string {
  const base = hashKey(queryKey)
  if (current === null || OWN_ACCOUNT_ROOTS.has(queryKey[0])) return base
  return `${base}${PARTITION_MARK}${current.leadId}`
}

/** True for a cache entry that holds a lead's data. Those are never written to disk. */
export function isActingPartitionHash(queryHash: string): boolean {
  return queryHash.includes(PARTITION_MARK)
}

/**
 * Pages that are about the caller's own account whoever they act for: team, billing, settings, the
 * notification inbox and the tutoring marketplace. They stay reachable when a lead is unavailable.
 */
export const OWN_ACCOUNT_PATH = /^\/teacher\/(team|billing|settings|notifications|tutoring)(\/|$)/

/* ── Recognising the refusal ─────────────────────────────────────────────────────────────────── */

/**
 * True for the server's 403 `team_permission_denied`, judged by shape so modules that cannot import
 * `api.ts` (the query client: `api` reaches `auth/storage`, which reaches the client) can use it.
 * `isTeamPermissionDenied` in `api.ts` is this plus an `ApiError` check.
 */
export function looksLikeTeamPermissionDenied(err: unknown): boolean {
  if (typeof err !== "object" || err === null) return false
  const { status, detail } = err as { status?: unknown; detail?: unknown }
  return (
    status === 403 &&
    typeof detail === "object" &&
    detail !== null &&
    (detail as { code?: unknown }).code === "team_permission_denied"
  )
}

/**
 * Whether the lead being acted for should be treated as unavailable: the server refused the lead's
 * class list itself, on a page that is about the lead's work. It answers a removed assistant, a lead
 * on a plan that does not allow it, and a role with nothing the same way, so this does not say
 * which; it says there is nothing to work on here and offers the way back.
 */
export function isLeadUnavailable(lead: unknown, classListError: unknown, pathname: string): boolean {
  return lead !== null && looksLikeTeamPermissionDenied(classListError) && !OWN_ACCOUNT_PATH.test(pathname)
}

/* ── Copy ────────────────────────────────────────────────────────────────────────────────────── */

/**
 * The sentence for a refused action: what the server's 403 `team_permission_denied` means to
 * the person who pressed the button. Also the reason shown beside a control the role lacks.
 */
export function teamPermissionDeniedMessage(leadName: string | null): string {
  return leadName
    ? `Your role on ${leadName}'s team doesn't allow this.`
    : "Your role on this team doesn't allow this."
}
