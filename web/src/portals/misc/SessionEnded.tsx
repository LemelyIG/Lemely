/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useSearchParams } from "react-router-dom"
import { FullPageState } from "./FullPageState"
import { safeNextPath } from "@/lib/nextPath"

/*
 * PR 2 part A2 · `/session-ended`, the destination `RequireAuth` sends a dead
 * session to.
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
 * `/login?next=…`, so the reader lands back where they started only after
 * they have actually signed in again.
 */
export function SessionEnded() {
  const [searchParams] = useSearchParams()
  const next = safeNextPath(searchParams.get("next"))

  return <FullPageState variant="session-ended" frame="standalone" returnTo={next ?? undefined} />
}
