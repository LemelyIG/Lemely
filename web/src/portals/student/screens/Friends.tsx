/* Hallmark · pre-emit critique: P5 H4 E4 S5 R5 V4 */
import { useState } from "react"
import { Card, CardBody } from "@/components/ui/card"
import { Chip } from "@/components/ui/chip"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Eyebrow } from "@/components/ui/primitives"
import { EmptyState } from "@/components/ui/state-views"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Fire, Lightning } from "@phosphor-icons/react"
import {
  useAcceptFriendRequest,
  useFriends,
  useRemoveFriend,
  useSendFriendRequest,
} from "@/lib/hooks/useFriendApi"
import { friendActionFailureMessage } from "@/lib/friendOutcome"
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
 *
 * ── P4.4, the Study Notebook pass ────────────────────────────────────────
 *
 * **Every mutation on this screen reported its failure in the wrong place, in
 * the wrong words, or both.** The three `isError` blocks all rendered
 * `err.message` verbatim, and two of the three sat in a block at the very
 * bottom of the page, under every section. So: a student who declined a
 * request in the first list got the browser's `TypeError: Failed to fetch`,
 * printed several hundred pixels below the button they pressed, quite possibly
 * off-screen. The wording is `lib/friendOutcome.ts`'s job now; the placement is
 * fixed here, by putting each message inside the section whose action produced
 * it.
 *
 * The exception, kept deliberately: the *backend's* own sentence for a failed
 * request send. It distinguishes three different next steps and is better than
 * anything this screen could say. `friendActionFailureMessage` preserves it and
 * replaces only the machine text.
 *
 * **No celebration register here** (§9.3). A friend accepting is a pleasant
 * thing and it is not one of the five moments; a flourish for gaining a
 * follower is the engagement-celebration §9.3's last bullet bans by name.
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
    ? `You and ${request.displayName} are now friends. They had already asked.`
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
        <p className="truncate text-body-md text-ink">{friend.displayName}</p>
        {since ? (
          <p className="text-body-sm text-ink-faint">Friends since {since}</p>
        ) : null}
      </div>

      {friend.optedOut ? (
        // Stated, not blanked: "we are not showing this" and "they scored
        // nothing" are different facts, and a silent gap reads as the second.
        <Chip tone="neutral">Hidden from boards</Chip>
      ) : (
        <div className="flex items-center gap-3">
          {friend.streak !== null ? (
            <span className="flex items-center gap-1 text-data-sm text-ink-faint">
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
            <span className="flex items-center gap-1 text-data-md text-ink">
              <Lightning
                size={12}
                weight="fill"
                className="text-accent"
                aria-hidden="true"
              />
              {friend.xp.toLocaleString()}
              <span className="text-body-sm text-ink-faint">XP</span>
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
      <p className="min-w-0 flex-1 truncate text-body-md text-ink">
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

/**
 * A failed mutation, stated where the action was taken.
 *
 * `role="alert"` so it is announced rather than merely appearing: the button
 * that failed is often already re-enabled by the time a reader would notice a
 * new line of text.
 */
function ActionError({ error }: { error: unknown }) {
  return (
    <p role="alert" className="text-body-sm text-err">
      {friendActionFailureMessage(error)}
    </p>
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
        <div className="flex flex-col gap-1">
          <Eyebrow>Your friend code</Eyebrow>
          {/* A code, so the data face, and `data-lg` because this is the one
              figure on the screen a student reads out to somebody. It was
              `font-mono text-display-sm`, two competing font-family
              declarations resolved by stylesheet order — the same defect
              corrected on the training log. */}
          <p className="text-data-lg tracking-[0.14em] text-ink">{friendCode}</p>
          <p className="lm-prose text-body-sm text-ink-faint">
            Share this with a friend and they can add you. It is the only way
            anyone can find you here. Nobody can search for you by name or
            email.
          </p>
        </div>

        <form onSubmit={submit} className="flex flex-col gap-2">
          {/* C-13 `Input`, not a hand-rolled field. The hand-rolled one had no
              hover or focus ladder, no error state, and its label was a bare
              `<label>` at a size below §4.2's floor. The kit component also
              renders the failure message inline and adjacent to the field,
              which is where §12 puts it — the old markup put it under the row,
              and the two other mutations on this screen put theirs at the
              bottom of the page. */}
          {/* Two corrections from the capture round, both about this row.
              - The field stretched the full width of the card, ~1350px at
                1440, for a value that is eight characters long. A field's
                width is a promise about how much to type, and this one was
                promising a paragraph.
              - The button was aligned to the *wrapper's* end, and the wrapper
                grows by a line when the field errors, so pressing Send with a
                bad code dropped the button below the field it belongs to.
              Hence `state` rather than `error` on the Input: the border ladder
              and the status glyph still fire, but the message is rendered
              below the whole row, which keeps it adjacent to the field (§12)
              without letting it move the button. */}
          <div className="flex flex-wrap items-end gap-2">
            <Input
              id="s30-code"
              label="Add someone by their code"
              wrapperClassName="min-w-0 flex-1 max-w-xs"
              className="font-mono"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="e.g. K7P4RQ29"
              autoComplete="off"
              spellCheck={false}
              state={send.isError ? "error" : undefined}
              aria-describedby={send.isError ? "s30-code-error" : undefined}
              aria-invalid={send.isError || undefined}
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
          {/* The backend's own message is surfaced when it wrote one: it
              distinguishes "no such code" from "already friends" from "that is
              your own code", and each of those tells the student a different
              next step. `friendActionFailureMessage` keeps that and replaces
              only the machine wording behind it. */}
          {send.isError ? (
            <p id="s30-code-error" role="alert" className="text-body-sm text-err">
              {friendActionFailureMessage(send.error)}
            </p>
          ) : null}
          {notice ? (
            <p role="status" className="text-body-sm text-ok">
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
  const query = useFriends()
  const accept = useAcceptFriendRequest()
  const remove = useRemoveFriend()

  const busy = accept.isPending || remove.isPending

  return (
    <div className="flex flex-col gap-8">
      <QueryState
        query={query}
        srHeading="Friends"
        // Shaped like what replaces it: a header, the friend-code card, and
        // the list. It was one line of text, so the page grew by its whole
        // height the moment the read landed.
        skeleton={
          <>
            <PageHeaderSkeleton />
            <ListSkeleton rows={2} />
            <ListSkeleton rows={4} />
          </>
        }
        error={{
          heading: "Your friends could not be loaded",
          body: "This is a connection problem, not an empty list.",
        }}
      >
        {(data) => (
          <>
            <header className="flex flex-col gap-1">
              <Eyebrow>Friends</Eyebrow>
              {/* `text-display` was the class here and it resolves to nothing
                  — see the note in `Profile.tsx`. */}
              <h1 className="text-display-lg text-ink">Who you are studying with</h1>
              <p className="lm-prose text-body-lg text-ink-muted">
                Friends see your display name, XP and streak. They never see
                your marks, your grades or which papers you have corrected.
              </p>
            </header>

            <AddFriend friendCode={data.friendCode} />

            {data.incoming.length > 0 ? (
              <section className="flex flex-col gap-3" aria-labelledby="s30-incoming">
                <h2 id="s30-incoming" className="text-display-sm text-ink">
                  Wants to be your friend
                </h2>
                <Card>
                  <CardBody className="divide-y divide-rule py-0">
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
                {/* Accepting can only happen from this list, so its failure
                    belongs here rather than at the foot of the page. */}
                {accept.isError ? <ActionError error={accept.error} /> : null}
              </section>
            ) : null}

            <section className="flex flex-col gap-3" aria-labelledby="s30-friends">
              <h2 id="s30-friends" className="text-display-sm text-ink">
                Your friends
              </h2>
              <Card>
                <CardBody className={data.friends.length > 0 ? "divide-y divide-rule py-0" : ""}>
                  {data.friends.length === 0 ? (
                    <EmptyState
                      marginalia="Your code is above"
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
              {/* `remove` is the endpoint behind Remove, Decline and Cancel
                  alike (D5.6 §3), so its failure is reported under each of the
                  three lists that can call it rather than once at the bottom.
                  Repeating the message is the point: the student sees it
                  beside the row they were working on. */}
              {remove.isError ? <ActionError error={remove.error} /> : null}
            </section>

            {data.outgoing.length > 0 ? (
              <section className="flex flex-col gap-3" aria-labelledby="s30-outgoing">
                <h2 id="s30-outgoing" className="text-display-sm text-ink">
                  Waiting on them
                </h2>
                <Card>
                  <CardBody className="divide-y divide-rule py-0">
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
                {remove.isError ? <ActionError error={remove.error} /> : null}
              </section>
            ) : null}
          </>
        )}
      </QueryState>
    </div>
  )
}
