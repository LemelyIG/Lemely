import { useSearchParams } from "react-router-dom"

/** Staff reach the real sign-in and sign-up forms while access is restricted through `?team=1`. */
export const TEAM_SIGN_IN_PATH = "/login?team=1"
export const TEAM_SIGN_UP_PATH = "/signup?team=1"

/** `"?team=1"` while the visitor is on the team path, otherwise `""`: appended to the links between the
 * team sign-in and sign-up screens so the bypass survives moving between them. Not security: the backend
 * refuses any address that is not allowed. */
export function useTeamSuffix(): string {
  const [params] = useSearchParams()
  return params.get("team") === "1" ? "?team=1" : ""
}
