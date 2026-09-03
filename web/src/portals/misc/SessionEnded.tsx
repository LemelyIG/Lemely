/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useState } from "react"
import { useSearchParams } from "react-router-dom"
import { FullPageState } from "./FullPageState"
import { safeNextPath } from "@/lib/nextPath"
import { peekExpiredRole, takeSessionExpired } from "@/lib/auth/storage"

/*
 * PR 2 part A2 · `/session-ended`, the destination `RequireAuth` sends a dead
 * session to. Guarded against a reader who still has a live session by
 * `SessionEndedRoute` in `routes.tsx` (adversarial review NIT) — by the time
 * this component itself renders, `useAuth()`'s session is already gone,
 * whether that is really true (the usual case) or this reader's session was
 * live and got sent onward before reaching here.
 *
 * A distinct screen from `/login` rather than a query flag on it, because the
 * two stories are genuinely different: `/login` with no notice is "sign in",
 * `/login?expired` (the old behaviour) is "sign in, and by the way something
 * happened", and this screen leads with the thing that happened —
 * `fullPageStateCopy.ts`'s `session-ended` variant, "You were signed out to
 * keep your account safe" — before it ever asks for a password again.
 *
 * `?next=` is read and re-validated here, not trusted from `RequireAuth`'s own
 * redirect: a URL is a URL once it reaches the browser, and this component has
 * no way to tell "the app's own `<Navigate>` put this here" apart from "a
 * reader typed or followed a link to this exact address" — the second is
 * exactly as untrusted as the `?next=` `Login.tsx` reads directly. `safeNextPath`
 * is the same same-origin-path allowlist either way (`lib/nextPath.ts`).
 * `FullPageState`'s own `sign-in` action then carries `returnTo` on to
 * `/login?next=…` or `/login/parent?next=…`, so the reader lands back where
 * they started only after they have actually signed in again.
 *
 * SHOULD-FIX 3/4 (adversarial review, PR 2): this screen used to leave the
 * expiry flag `RequireAuth` set entirely to `Login.tsx` to consume, which
 * meant two bugs at once. The flag went stale — a reader who *chose* to sign
 * out, then later opened a portal URL directly, still got told "you were
 * signed out to keep your account safe" for an unrelated, possibly much
 * older expiry (fixed at the source: `clearSession()` in `lib/auth/storage.ts`
 * now clears the flag too, since a deliberate sign-out is never an expiry).
 * And this screen had no way to know *which* role had expired, so its own
 * `sign-in` action could only ever point a parent at the password form they
 * cannot use (SHOULD-FIX 3, `loginPathForRole`). Reading the flag here on
 * mount fixes both: `peekExpiredRole()` first, since `takeSessionExpired`
 * clears the role together with the boolean flag it returns (see both
 * functions' own doc comments in `storage.ts` — `takeSessionExpired` itself
 * keeps its existing `boolean` return, unchanged, for `Login.tsx`'s sake),
 * then `takeSessionExpired()` to actually consume the flag so a later
 * remount of either screen does not show the notice twice for the same
 * expiry. The role goes to `FullPageState` as `expiredRole`, since
 * `useAuth()`'s own `session` is `null` by the time this renders and has no
 * role left to read it from directly.
 */
export function SessionEnded() {
  const [searchParams] = useSearchParams()
  const next = safeNextPath(searchParams.get("next"))
  const [role] = useState(() => {
    const expiredRole = peekExpiredRole()
    takeSessionExpired()
    return expiredRole
  })

  return (
    <FullPageState
      variant="session-ended"
      frame="standalone"
      returnTo={next ?? undefined}
      expiredRole={role}
    />
  )
}
