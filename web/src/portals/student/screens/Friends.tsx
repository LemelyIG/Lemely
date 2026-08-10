import { useState } from "react"
import { Card, CardBody } from "@/components/ui/card"
import { Chip } from "@/components/ui/chip"
import { Button } from "@/components/ui/button"
import { Eyebrow } from "@/components/ui/primitives"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { Fire, Lightning } from "@phosphor-icons/react"
import {
  useAcceptFriendRequest,
  useFriends,
  useRemoveFriend,
  useSendFriendRequest,
} from "@/lib/hooks/useFriendApi"
import type { Friend, FriendRequest } from "@/lib/friendTypes"

/*
 * S-30 · Friends (P5.8 chunk C).
 *
 * **"Add by username" is unbuildable as the UI spec writes it, and the
 * substitute is not a workaround.** `users` has no username column, and the
 * two obvious alternatives are both closed on purpose: display name is not
 * unique and searching it would let a student enumerate strangers, and email
 * is the exact leak D5.5 killed on the leaderboard. `users.friend_code` (D5.6)
 * is the built mechanism — 8 characters from an ambiguity-free alphabet,
 * minted lazily — and it serves both halves of the spec's sentence, the typed
 * code and the invite link, because they are the same string.
 *
 * **Decline, cancel and unfriend are one action** (D5.6 §3): all three delete
 * the same row, so there is one endpoint and no confirmation modal. The
 * mistake is cheap and recoverable — ask again — and a modal would cost more
 * than the error it prevents.
 *
 * **A friend's numbers can be absent, and absent is not zero** (D5.6 §5). An
 * opted-out friend stays in the list, because removing them would make them
 * unremovable, but their XP and streak come back `null`. The screen says so
 * rather than rendering a `0` neither of them earned.
 */

/* ── Formatting ─────────────────────────────────────────────────────────── */

export function formatFriendsSince(timestamp: string | null): string | null {
  if (timestamp === null) return null
  return new Date(timestamp).toLocaleDateString("en-GB", {
    month: "short",
    year: "numeric",
  })
}

/**
 * Whether a `POST /requests` response means "you are now friends".
 *
 * Read from the response's own `status`, never inferred from the call having
 * succeeded: when both parties had already asked, the backend accepts the
 * friendship outright and says so. Telling that student "request sent" would
 * leave them waiting for something that already happened.
 */
export function requestOutcomeMessage(request: FriendRequest): string {
  return request.status === "accepted"
    ? `You and ${request.displayName} are now friends — they had already asked.`
    : `Request sent to ${request.displayName}.`
}

/* ── Rows ───────────────────────────────────────────────────────────────── */

function FriendRow({
  friend,
  onRemove,
  removing,
}: {
  friend: Friend
  onRemove: (friendshipId: string) => void
  removing: boolean
}) {
  const since = formatFriendsSince(friend.friendsSince)
  return (
    <div className="flex flex-wrap items-center gap-3 py-3">
      <div className="min-w-0 flex-1">
        <p className="truncate text-body-md text-t1">{friend.displayName}</p>
        {since ? (
          <p className="text-3xs text-t3">Friends since {since}</p>
        ) : null}
      </div>

      {friend.optedOut ? (
        // Stated, not blanked: "we are not showing this" and "they scored
        // nothing" are different facts, and a silent gap reads as the second.
        <Chip tone="neutral">Hidden from boards</Chip>
      ) : (
        <div className="flex items-center gap-3">
          {friend.streak !== null ? (
            <span className="flex items-center gap-1 text-2xs text-t3">
              <Fire
                size={12}
                weight="fill"
                className="text-accent"
                aria-hidden="true"
              />
              {friend.streak}
              <span className="sr-only"> day streak</span>
            </span>
          ) : null}
          {friend.xp !== null ? (
            <span className="flex items-center gap-1 font-mono text-dense-lg text-t1">
              <Lightning
                size={12}
                weight="fill"
                className="text-accent"
                aria-hidden="true"
              />
              {friend.xp.toLocaleString()}
              <span className="text-3xs text-t3">XP</span>
            </span>
          ) : null}
        </div>
      )}

      <Button
        variant="ghost"
        size="sm"
        onClick={() => onRemove(friend.friendshipId)}
        disabled={removing}
      >
        Remove
      </Button>
    </div>
  )
}

function RequestRow({
  request,
  direction,
  onAccept,
  onRemove,
  busy,
}: {
  request: FriendRequest
  direction: "incoming" | "outgoing"
  onAccept: (friendshipId: string) => void
  onRemove: (friendshipId: string) => void
  busy: boolean
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 py-3">
      <p className="min-w-0 flex-1 truncate text-body-md text-t1">
        {request.displayName}
      </p>
      {direction === "incoming" ? (
        <>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => onAccept(request.friendshipId)}
            disabled={busy}
          >
            Accept
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onRemove(request.friendshipId)}
            disabled={busy}
          >
            Decline
          </Button>
        </>
      ) : (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onRemove(request.friendshipId)}
          disabled={busy}
        >
          Cancel
        </Button>
      )}
    </div>
  )
}

/* ── Add by code ────────────────────────────────────────────────────────── */

function AddFriend({ friendCode }: { friendCode: string }) {
  const [code, setCode] = useState("")
  const [notice, setNotice] = useState<string | null>(null)
  const send = useSendFriendRequest()

  function submit(event: React.FormEvent) {
    event.preventDefault()
    if (code.trim().length === 0) return
    setNotice(null)
    // The raw value goes to the server, which normalises it — see
    // `useSendFriendRequest`. Uppercasing here too would be a second
    // definition of the alphabet that could drift from the first.
    send.mutate(code, {
      onSuccess: (request) => {
        setNotice(requestOutcomeMessage(request))
        setCode("")
      },
    })
  }

  return (
    <Card>
      <CardBody className="flex flex-col gap-4">
        <div>
          <Eyebrow>Your friend code</Eyebrow>
          <p className="font-mono text-display-sm tracking-[0.14em] text-t1">
            {friendCode}
          </p>
          <p className="text-2xs text-t3">
            Share this with a friend and they can add you. It is the only way
            anyone can find you here — nobody can search for you by name or
            email.
          </p>
        </div>

        <form onSubmit={submit} className="flex flex-col gap-2">
          <label htmlFor="s30-code" className="text-2xs text-t2">
            Add someone by their code
          </label>
          <div className="flex flex-wrap gap-2">
            <input
              id="s30-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="e.g. K7P4RQ29"
              autoComplete="off"
              spellCheck={false}
              className="min-w-0 flex-1 rounded-md border border-border bg-surface px-3 py-2 font-mono text-body-md text-t1 placeholder:text-t3"
            />
            <Button
              type="submit"
              variant="accent"
              size="sm"
              disabled={send.isPending || code.trim().length === 0}
            >
              Send request
            </Button>
          </div>
          {/* The backend's own message is surfaced verbatim: it distinguishes
              "no such code" from "already friends" from "that is your own
              code", and each of those tells the student a different next step.
              A generic "could not add friend" would flatten all three. */}
          {send.isError ? (
            <p role="alert" className="text-2xs text-err">
              {send.error.message}
            </p>
          ) : null}
          {notice ? (
            <p role="status" className="text-2xs text-ok">
              {notice}
            </p>
          ) : null}
        </form>
      </CardBody>
    </Card>
  )
}

/* ── Screen ─────────────────────────────────────────────────────────────── */

export function Friends() {
  const { data, isPending, isError, refetch } = useFriends()
  const accept = useAcceptFriendRequest()
  const remove = useRemoveFriend()

  if (isPending) {
    return (
      <div className="flex flex-col gap-8">
        <div className="text-body-md text-t3">Loading your friends…</div>
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="flex flex-col gap-8">
        <ErrorState
          heading="Your friends could not be loaded"
          body="This is a connection problem, not an empty list."
          action={{ label: "Try again", onClick: () => void refetch() }}
        />
      </div>
    )
  }

  const busy = accept.isPending || remove.isPending

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-1">
        <Eyebrow>Friends</Eyebrow>
        <h1 className="text-display">Who you are studying with</h1>
        <p className="text-body-md text-t2">
          Friends see your display name, XP and streak. They never see your
          marks, your grades or which papers you have corrected.
        </p>
      </header>

      <AddFriend friendCode={data.friendCode} />

      {data.incoming.length > 0 ? (
        <section className="flex flex-col gap-3" aria-labelledby="s30-incoming">
          <h2 id="s30-incoming" className="text-body-lg font-medium text-t1">
            Wants to be your friend
          </h2>
          <Card>
            <CardBody className="divide-y divide-border py-0">
              {data.incoming.map((request) => (
                <RequestRow
                  key={request.friendshipId}
                  request={request}
                  direction="incoming"
                  onAccept={(id) => accept.mutate(id)}
                  onRemove={(id) => remove.mutate(id)}
                  busy={busy}
                />
              ))}
            </CardBody>
          </Card>
        </section>
      ) : null}

      <section className="flex flex-col gap-3" aria-labelledby="s30-friends">
        <h2 id="s30-friends" className="text-body-lg font-medium text-t1">
          Your friends
        </h2>
        <Card>
          <CardBody className={data.friends.length > 0 ? "divide-y divide-border py-0" : ""}>
            {data.friends.length === 0 ? (
              <EmptyState
                heading="No friends yet"
                body="Share your friend code above, or paste someone else's. Friends show up on your friends leaderboard."
              />
            ) : (
              data.friends.map((friend) => (
                <FriendRow
                  key={friend.friendshipId}
                  friend={friend}
                  onRemove={(id) => remove.mutate(id)}
                  removing={busy}
                />
              ))
            )}
          </CardBody>
        </Card>
      </section>

      {data.outgoing.length > 0 ? (
        <section className="flex flex-col gap-3" aria-labelledby="s30-outgoing">
          <h2 id="s30-outgoing" className="text-body-lg font-medium text-t1">
            Waiting on them
          </h2>
          <Card>
            <CardBody className="divide-y divide-border py-0">
              {data.outgoing.map((request) => (
                <RequestRow
                  key={request.friendshipId}
                  request={request}
                  direction="outgoing"
                  onAccept={(id) => accept.mutate(id)}
                  onRemove={(id) => remove.mutate(id)}
                  busy={busy}
                />
              ))}
            </CardBody>
          </Card>
        </section>
      ) : null}

      {remove.isError ? (
        <p role="alert" className="text-2xs text-err">
          {remove.error.message}
        </p>
      ) : null}
      {accept.isError ? (
        <p role="alert" className="text-2xs text-err">
          {accept.error.message}
        </p>
      ) : null}
    </div>
  )
}
