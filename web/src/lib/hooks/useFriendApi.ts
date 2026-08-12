import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request } from "@/lib/api"
import type {
  Friend,
  FriendRequest,
  FriendRequestCreate,
  FriendsPage,
} from "@/lib/friendTypes"

/*
 * React-query hooks over `/api/student/friends` (P5.4 chunk B, S-30).
 *
 * Follows useDeviceApi.ts's conventions: one hook per endpoint and no
 * `fallback` passed to `request()` — an empty friends list is a claim ("you
 * have nobody"), and a swallowed fetch failure that renders it would be both
 * wrong and discouraging.
 *
 * **Every mutation invalidates both the friends page and the leaderboard.**
 * The `friends` scope ranks exactly the accepted friendships this page edits,
 * so accepting a request while a friends board is on screen must not leave the
 * board a person short. They are the same fact rendered twice.
 */

const FRIENDS_KEY = ["student", "friends"] as const
const LEADERBOARD_KEY = ["student", "leaderboard"] as const

export function useFriends(): UseQueryResult<FriendsPage, Error> {
  return useQuery({
    queryKey: FRIENDS_KEY,
    queryFn: () => request<FriendsPage>("/student/friends"),
  })
}

function useFriendMutation<TData, TVars>(
  mutationFn: (vars: TVars) => Promise<TData>,
): UseMutationResult<TData, Error, TVars> {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: FRIENDS_KEY })
      void queryClient.invalidateQueries({ queryKey: LEADERBOARD_KEY })
    },
  })
}

/**
 * Send a request to the holder of a friend code.
 *
 * The raw typed value is sent as-is: the backend normalises with
 * `.strip().upper()` already, so a code copied out of a screenshot in
 * lowercase works. Re-implementing that here would be a second definition of
 * the alphabet that could drift from the first.
 *
 * The resolved `FriendRequest.status` is `"accepted"`, not `"pending"`, when
 * the other party had already asked. Read it — do not assume "request sent"
 * from a successful call.
 */
export function useSendFriendRequest(): UseMutationResult<
  FriendRequest,
  Error,
  string
> {
  return useFriendMutation((friendCode: string) =>
    request<FriendRequest>("/student/friends/requests", {
      method: "POST",
      body: JSON.stringify({ friendCode } satisfies FriendRequestCreate),
    }),
  )
}

export function useAcceptFriendRequest(): UseMutationResult<
  Friend,
  Error,
  string
> {
  return useFriendMutation((friendshipId: string) =>
    request<Friend>(`/student/friends/${friendshipId}/accept`, {
      method: "POST",
    }),
  )
}

/**
 * Decline, cancel, or unfriend — one endpoint, because they are one database
 * act (D5.6 §3). The screen supplies the wording; the API does not need three.
 */
export function useRemoveFriend(): UseMutationResult<void, Error, string> {
  return useFriendMutation((friendshipId: string) =>
    request<void>(`/student/friends/${friendshipId}`, { method: "DELETE" }),
  )
}
