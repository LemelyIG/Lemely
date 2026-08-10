/*
 * Wire types for S-30, mirroring `lemely/web/schemas_friends.py` field for
 * field.
 *
 * **Friends are added by friend code, never by username or email** (D5.6).
 * `users` has no username column, searching by display name is not unique and
 * would let a student enumerate strangers, and searching by email is the exact
 * leak D5.5 killed on the leaderboard. There is deliberately no search type in
 * this file, because there is deliberately no search endpoint.
 *
 * `xp`/`streak` are `number | null` and that is not laziness (D5.6 §5). An
 * opted-out friend stays in the list — removing them would make them
 * unremovable — but their numbers come back `null` with `optedOut: true`, so
 * the screen states the fact rather than rendering a fabricated `0`.
 */

export interface Friend {
  friendshipId: string
  userId: string
  displayName: string
  /** Lifetime total XP — no window, unlike the weekly leaderboard. `null` iff
   * `optedOut`. */
  xp: number | null
  /** Current streak length. `null` iff `optedOut`. */
  streak: number | null
  optedOut: boolean
  /** When the friendship was accepted. */
  friendsSince: string | null
}

export interface FriendRequest {
  friendshipId: string
  /** The *other* party: the requester for an incoming request, the addressee
   * for an outgoing one. Never the caller. */
  userId: string
  displayName: string
  requestedAt: string
  /**
   * The friendship's real status after the call that produced this.
   *
   * Load-bearing on `POST /requests`: when both parties had already asked,
   * the backend returns the **accepted** row and says so here, so the screen
   * reports "you are now friends" from the response rather than inferring
   * "request sent" from the 201.
   */
  status: "pending" | "accepted"
}

/** `GET /api/student/friends` — everything S-30 needs in one call. */
export interface FriendsPage {
  /** The caller's own code, minted on first read. Serves both the typed code
   * and the invite link (D5.6). */
  friendCode: string
  friends: Friend[]
  incoming: FriendRequest[]
  outgoing: FriendRequest[]
}

/** `POST /api/student/friends/requests` body. The server normalises with
 * `.strip().upper()`, so the screen does not re-implement that and cannot
 * drift from it. */
export interface FriendRequestCreate {
  friendCode: string
}
