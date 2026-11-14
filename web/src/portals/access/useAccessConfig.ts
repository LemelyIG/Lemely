import { useQuery } from "@tanstack/react-query"
import { ACCESS_CONFIG_QUERY_KEY, getAccessConfig } from "@/lib/access-api"

/**
 * Whether sign-in is restricted right now (`GET /api/access/config`). One attempt, no retry:
 * the gate chooses what to show on failure and a slow retry would only delay it. A short
 * stale time keeps a visit to /login then /signup to one request while a deploy that flips
 * the flag still shows up within a minute.
 */
export function useAccessConfig() {
  const query = useQuery({
    queryKey: ACCESS_CONFIG_QUERY_KEY,
    queryFn: getAccessConfig,
    retry: 0,
    staleTime: 60_000,
  })
  return { restricted: query.data?.restricted, isPending: query.isPending, isError: query.isError }
}
