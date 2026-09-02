import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { ApiError, request } from "@/lib/api"
import { inviteFailureMessage } from "@/lib/authOutcome"
import type { InvitePreview } from "@/lib/authTypes"

/*
 * Task 18 (spec §1.2, §4.3, §4.4, D7.3) · React-query hooks over the two
 * client-reachable `/api/invites/*` routes (`lemely/web/routers/invites.py`),
 * plus the pure copy/classification logic G-08 (`portals/auth/JoinWithCode.tsx`)
 * needs to render its four states. Same one-hook-per-endpoint shape as
 * `useAdminApi.ts`/`useMeApi.ts`.
 *
 * Not folded into `AuthContext.tsx` (Task 13 deliberately left both mutations
 * out of it): neither call here mints a session the way login/signup/OTP-
 * verify do. `useInvitePreview` runs with no session at all — it backs G-08's
 * public, pre-account preview — and `useRedeemInvite` runs on a session that
 * already exists, so neither belongs beside `applySession`'s siblings.
 *
 * The pure functions below (normalisation, error classification, the
 * preview→signup handoff, the identity copy) live here rather than in
 * `JoinWithCode.tsx` for two reasons, not one:
 *
 *   1. **Fast Refresh.** oxlint's `react/only-export-components` flags a file
 *      that exports a component alongside anything else (`portals/student/
 *      index.tsx` already carries dozens of these warnings for exactly that
 *      reason). This module exports no component, so it is exempt outright —
 *      keeping every pure export here rather than on the screen file is the
 *      difference between zero new warnings and one per function.
 *   2. **It matches this codebase's own convention.** `authOutcome.ts`,
 *      `teacherOutcome.ts` and their siblings already keep copy-owning logic
 *      out of the screen that renders it. `JoinWithCode.tsx` cannot add a
 *      fourth `*Outcome.ts` file of its own (Task 18's file list is exactly
 *      two files plus an optional test), so this module is where that logic
 *      lives instead — layered on top of, never duplicating, `authOutcome.ts`'s
 *      own `inviteFailureMessage`.
 */

// ---------------------------------------------------------------------------
// Pure logic — normalisation, copy, error classification. No network, no
// React. Exported so `tests/unit/joinWithCode.test.ts` can exercise every
// branch directly, per this task's environment note that vitest here runs the
// node environment and cannot mount a component.
// ---------------------------------------------------------------------------

/**
 * Trim and uppercase a typed or deep-linked code.
 *
 * Both code families this resolves against are minted from all-uppercase,
 * non-ambiguous alphabets (`invite_repo.py`'s `_INVITE_CODE_ALPHABET`,
 * `class_repo.py`'s `_JOIN_CODE_ALPHABET` — neither contains a lowercase
 * letter), and both are matched with a case-sensitive `==` in SQL. So a
 * correctly-minted code is already a no-op under this function, and the only
 * effect this ever has is turning a holder's lowercase transcription of a
 * code read off a screen or a slip of paper into the one casing that can
 * actually match — silently failing that transcription as "not found" would
 * be a worse, unexplained failure than normalising it before the lookup.
 */
export function normalizeInviteCode(raw: string): string {
  return raw.trim().toUpperCase()
}

/**
 * The lines G-08's preview card renders, in priority order. Deliberately an
 * array of short lines rather than one joined sentence: the UI-spec's own
 * example phrasing ("Al-Nasr Language School — Mr Hassan's Physics 0625
 * class") is built on an em dash, which `check_copy.mjs` (REDESIGN-MISSION
 * §3.2 item 10) bans outright in real UI copy. Rendering the same three facts
 * as stacked lines instead keeps every fact this DTO carries, adds no
 * punctuation the mission forbids, and reads at least as clearly.
 *
 * Every branch reads only `InvitePreview`'s four fields — `role`,
 * `schoolName`, `className`, `teacherName` — nothing else, because that DTO
 * is the whole of what `GET /api/invites/{code}` is willing to say (public,
 * pre-account; `InviteService.preview`'s own binding rule 4 is explicit that
 * it exposes no id, no roster and no count). This function must not go
 * looking for more.
 */
export function describeInvitePreview(preview: InvitePreview): string[] {
  const lines: string[] = []
  if (preview.schoolName) lines.push(preview.schoolName)
  if (preview.className) {
    const possessive = preview.teacherName ? `${preview.teacherName}'s ` : ""
    lines.push(`${possessive}${preview.className} class`)
  } else if (preview.schoolName) {
    // A seat invite (`mint_seat_invite`) has a school and no class — the
    // school line above is the whole preview, so this second line names what
    // the seat itself is rather than leaving the card at one bare fact.
    lines.push(preview.role === "teacher" ? "A teacher place at this school" : "A student seat at this school")
  }
  if (lines.length === 0) {
    // Defensive only. `invites.ck_invites_target` (migration 0023) makes an
    // invite pointing at neither a school nor a class a rejected insert, and
    // the `classes.join_code` fallback `InviteService.preview` tries next
    // always resolves a class. Both preview fields being empty has never been
    // observed and the schema says it cannot be — a real line here beats a
    // silently blank card if that ever stops being true.
    lines.push("An invite to Lemely")
  }
  return lines
}

/** Where "confirm" sends a signed-out visitor: G-03 with the code retained
 * (§G-08, Task 15's own bullet). A query param, not router `state` — `state`
 * does not survive a refresh or a pasted/bookmarked URL, and `/join/:code`
 * itself already carries this same code as a URL segment, so a query param on
 * the handoff is the same mechanism, not a new one. `role` comes from the
 * *preview* (what the code provisions), never from a caller's own session —
 * there is no session yet on this branch. */
export function signupPathForInvite(code: string, role: "student" | "teacher"): string {
  return `/signup/${role}?code=${encodeURIComponent(code)}`
}

/**
 * Narrows an `ApiError.detail` onto a structured seat-quota-exceeded marker,
 * mirroring `isEmailUnverifiedError` (`authTypes.ts`) exactly: a field check
 * on a `code` string, never a search through server prose. `authOutcome.ts`'s
 * own note 1 is why — this codebase has already shipped one screen that
 * treated a machine string as a sentence, and the fix chosen there was
 * "match a stable field", not "read the words more carefully".
 *
 * **Honesty about reachability.** UI spec §G-08 names "seat quota full" as one
 * of four states, and this function exists so `JoinWithCode.tsx` can render
 * it correctly if the server ever reports it. As implemented today
 * (`lemely/db/invite_repo.py`), it cannot: `InviteQuotaExceededError` is
 * raised only by `mint_seat_invite`, at mint time — deliberately, per that
 * method's own binding rule 2, precisely so a redemption never has to fail on
 * quota — and `redeem_invite` (`lemely/web/routers/invites.py`) does not even
 * catch that exception, only `InviteNotFoundError`/`InviteAlreadyRedeemedError`.
 * A bare `classes.join_code` redemption (`ClassService.join_by_code`) has no
 * quota concept at all. So this predicate never matches a real response from
 * the live backend today, by design, not by omission — it is kept live and
 * tested (see `joinWithCode.test.ts`) rather than deleted, both because it
 * costs nothing to keep and because it is the shape a future defensive
 * re-check at redemption would need to use. Recorded here rather than
 * discovered later: see this task's report for the same note in full.
 */
export function isSeatQuotaExceededError(detail: unknown): boolean {
  if (typeof detail !== "object" || detail === null) return false
  return (detail as { code?: unknown }).code === "seat_quota_exceeded"
}

/** §G-08's required copy for the state above: "explain and tell them to
 * contact their school." Exported so the test file can assert
 * `redeemFailureMessage` returns exactly this string rather than duplicating
 * it as a second literal. */
export const SEAT_QUOTA_FULL_MESSAGE =
  "This school has no seats left right now. Contact your school so they can sort out access."

/**
 * Turn a failed `POST /api/invites/{code}/redeem` into a sentence.
 *
 * Checks the quota marker first, exactly the order `verificationFailureMessage`
 * checks `isEmailUnverifiedError` before its generic branches (`authOutcome.ts`)
 * — ahead of the generic 409 handling, because a plain 409 from this route
 * today only ever means `InviteAlreadyRedeemedError` (see
 * `isSeatQuotaExceededError`'s own docstring), and `inviteFailureMessage`
 * already has the right sentence for that case. This function adds the one
 * thing that module cannot: a 409 whose `detail` carries the structured
 * marker gets this task's own copy instead of the generic "already used" text.
 */
export function redeemFailureMessage(err: unknown): string {
  const detail = err instanceof ApiError ? err.detail : undefined
  if (isSeatQuotaExceededError(detail)) return SEAT_QUOTA_FULL_MESSAGE
  return inviteFailureMessage(err)
}

/**
 * Whether retrying the exact same redeem call could ever succeed.
 *
 * 404 (the code stopped resolving between preview and redeem) and 409
 * (already redeemed by someone else, or — see above — quota) are conflicts
 * with a *fact*, not a hiccup: pressing the same button again reproduces the
 * same refusal. `JoinWithCode.tsx` reads this to decide whether "join now"
 * stays on screen (a transient network/server failure, worth another try) or
 * is replaced by "enter a different code" (it will not be).
 */
export function isTerminalRedeemFailure(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 404 || err.status === 409)
}

/** Copy for the preview-lookup failure panel (`GET /api/invites/{code}`).
 *
 * That route raises exactly one domain error — `InviteNotFoundError`, a 404 —
 * and it is raised identically whether `code` never existed or existed and
 * expired: `InviteService._find_live_invite`'s own docstring is explicit that
 * "an expired invite reads identically to an unknown code... the caller is
 * anonymous, and 'this code once existed' is exactly the kind of fact it must
 * not learn." So "invalid code" and "expired code" (UI spec §G-08's first two
 * states) are, correctly, the *same* rendered panel here — not a gap in this
 * screen, a property of the anti-enumeration design one layer down, the exact
 * shape `AUTH_LINK_EXPIRED` already uses for verify/reset tokens
 * (`authOutcome.ts` note 5). Anything else (network loss, a 5xx) is a
 * different, retryable failure and gets a different heading and action.
 */
export function previewErrorCopy(err: unknown): {
  heading: string
  actionLabel: string
  retryable: boolean
} {
  const notFound = err instanceof ApiError && err.status === 404
  return {
    heading: notFound ? "We couldn't find that invite" : "Something went wrong",
    actionLabel: notFound ? "Try a different code" : "Try again",
    retryable: !notFound,
  }
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/** What redeeming a code produced (`RedeemInviteResponseDTO`). Not in
 * `authTypes.ts` — Task 13 defined `InvitePreview` there but no redeem-result
 * type, and this hook file is not that module to extend. */
export interface RedeemInviteResult {
  role: "student" | "teacher"
  schoolId: string | null
  classId: string | null
}

/**
 * `GET /api/invites/{code}` — G-08's preview. Public: works with no session
 * at all, and `request()` needs no special handling for that, since it only
 * ever *adds* a bearer token when one is stored (`lib/api.ts`'s
 * `authHeaders`) rather than requiring one.
 *
 * `enabled` is false for an empty code, both so mounting this screen with
 * nothing typed or deep-linked yet fires no request, and so the query key for
 * "nothing to look up" (`["invites", "preview", ""]`) never collides with a
 * real code's key. No `fallback`, matching every other read in this family
 * (`useAdminApi.ts`'s own note): a 404 must reach the screen as a real query
 * error to render the not-found panel, never resolve to a plausible-looking
 * empty preview.
 */
export function useInvitePreview(code: string): UseQueryResult<InvitePreview, Error> {
  const trimmed = code.trim()
  return useQuery({
    queryKey: ["invites", "preview", trimmed],
    queryFn: () => request<InvitePreview>(`/invites/${encodeURIComponent(trimmed)}`),
    enabled: trimmed.length > 0,
  })
}

/**
 * `POST /api/invites/{code}/redeem`. Authenticated — only ever called by
 * `JoinWithCode` once `useAuth().session` is already set; an unauthenticated
 * call would 401, which this hook does nothing special to prevent, mirroring
 * `AuthContext.tsx`'s own `resendVerification` (also assumes the caller
 * already checked).
 *
 * Invalidates the `"me"` query-key prefix on success rather than one exact
 * key: a signed-in caller redeeming a code is the seat/school-linking case
 * D1.10 anticipates, not only the fresh-signup one (the router's own
 * docstring calls `/invites/{code}/redeem` "role-agnostic" for exactly this
 * reason), and it changes that caller's own school/class membership. A
 * profile query cached from earlier in the session must not keep showing the
 * pre-redemption picture. `useMeApi.ts`'s exact key constants
 * (`STUDENT_PROFILE_KEY` etc.) are module-private and this task may not add
 * exports to that file, so this matches by the shared `"me"` prefix instead —
 * react-query's partial-key invalidation is built for exactly this.
 */
export function useRedeemInvite(): UseMutationResult<RedeemInviteResult, Error, { code: string }> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ code }: { code: string }) =>
      request<RedeemInviteResult>(`/invites/${encodeURIComponent(code.trim())}/redeem`, {
        method: "POST",
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["me"] })
    },
  })
}
