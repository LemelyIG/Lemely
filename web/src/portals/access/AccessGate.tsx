/* Hallmark · pre-emit critique: P4 H3 E4 S4 R5 V3 */
import type { ReactNode } from "react"
import { useSearchParams } from "react-router-dom"
import { RouteSkeleton } from "@/components/ui/route-skeleton"
import { useAuth } from "@/lib/auth/AuthContext"
import { ComingSoon } from "./ComingSoon"
import { useAccessConfig } from "./useAccessConfig"

/**
 * Shows `children` unless access is restricted, in which case the visitor sees the
 * coming-soon screen instead of the form.
 *
 * - `failClosed` (signup, invite entry): if the config call fails, show coming soon.
 * - Otherwise (login): if it fails, show the form; the backend still enforces the allow-list.
 * - A visitor who already has a session sees `children`: the backend let them in.
 * - `allowTeam` (login only): `?team=1` always shows the form. That is a convenience for
 *   staff, not security: an address outside the allow-list is refused by the backend anyway.
 */
export function AccessGate({
  children,
  failClosed = false,
  allowTeam = false,
}: {
  children: ReactNode
  failClosed?: boolean
  allowTeam?: boolean
}) {
  const [params] = useSearchParams()
  const { session } = useAuth()
  const { restricted, isPending, isError } = useAccessConfig()
  // A live session already passed the backend allow-list (a refused one is signed out on 403).
  if (session) return <>{children}</>
  if (allowTeam && params.get("team") === "1") return <>{children}</>
  if (isPending) return <RouteSkeleton />
  if (restricted === true || (isError && failClosed)) return <ComingSoon />
  return <>{children}</>
}
