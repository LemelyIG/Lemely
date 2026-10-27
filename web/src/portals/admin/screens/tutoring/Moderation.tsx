/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 — one hairline list, the text is the content, two buttons per row; not yet seen in a browser. */
import { useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { Eyebrow } from "@/components/ui/primitives"
import { QueryState } from "@/components/ui/query-state"
import { Select } from "@/components/ui/select"
import { EmptyState } from "@/components/ui/state-views"
import { useAdminModeration, useModerateReply, useModerateReview } from "@/lib/hooks/useTutoringApi"
import { useOnlineStatus } from "@/lib/online"
import {
  MODERATION_FILTERS,
  adminFailureMessage,
  formatAdminDay,
  moderationDoneLine,
  moderationKindLabel,
  moderationRequest,
  type ModerationDecision,
} from "@/lib/tutoring/adminTutoring"
import { isTutoringError } from "@/lib/tutoring/apiErrors"
import { tutoringKeys } from "@/lib/tutoring/queryKeys"
import type { ModerationItem } from "@/lib/tutoringTypes"

/*
 * X-06 · Moderation queue (`/platform/moderation`, SPEC §d, rows A6-A8).
 *
 * Review texts and tutor replies wait here until an admin approves or rejects
 * them, oldest first. Nothing about the author is shown: moderation judges the
 * words (SC-12).
 *
 * A review decision sends the `revision` the list showed with the text, so a
 * text its student edited since is refused with 409 `text_changed` instead of
 * being approved unseen (RF-7). The row then says so and offers a reload; the
 * new text is read before it is approved. A reply cannot be edited and sends
 * the decision alone.
 *
 * States: loading, error and offline (through `QueryState`, with retry), empty
 * (per filter), more pages, a decision in flight (its row's buttons wait), a
 * decision refused (a line on the row, with the reload when the row is stale),
 * and offline (decision buttons disabled with the reason).
 */

type Filter = (typeof MODERATION_FILTERS)[number]["value"]

function parseFilter(raw: string | null): Filter {
  const match = MODERATION_FILTERS.find((filter) => filter.value === raw)
  return match ? match.value : "all"
}

interface Failure {
  itemId: string
  message: string
  stale: boolean
}

interface Controls {
  online: boolean
  workingId: string | null
  failure: Failure | null
  onDecide: (item: ModerationItem, decision: ModerationDecision) => void
  onReload: () => void
}

function Item({ item, controls }: { item: ModerationItem; controls: Controls }) {
  const busy = controls.workingId !== null
  const mine = controls.workingId === item.itemId
  const failure = controls.failure?.itemId === item.itemId ? controls.failure : null
  const label = moderationKindLabel(item.kind)
  return (
    <li className="flex flex-col gap-3 border-b border-rule px-4 py-4 last:border-b-0 sm:px-5">
      <div className="flex flex-wrap items-center gap-2 text-body-sm text-ink-muted">
        <Chip>{label}</Chip>
        <time dateTime={item.createdAt} className="tabular-nums">
          {formatAdminDay(item.createdAt)}
        </time>
      </div>
      <p className="m-0 max-w-prose whitespace-pre-wrap break-words text-body-md text-ink">{item.text}</p>
      <div className="flex flex-wrap gap-2">
        <Button
          className="min-h-11"
          variant="primary"
          size="sm"
          disabled={!controls.online || (busy && !mine)}
          loading={mine}
          aria-label={`Approve this ${label.toLowerCase()}`}
          onClick={() => controls.onDecide(item, "approved")}
        >
          Approve
        </Button>
        <Button
          className="min-h-11"
          size="sm"
          disabled={!controls.online || (busy && !mine)}
          aria-label={`Reject this ${label.toLowerCase()}`}
          onClick={() => controls.onDecide(item, "rejected")}
        >
          Reject
        </Button>
      </div>
      {failure ? (
        <div className="flex flex-wrap items-center gap-3">
          <p role="alert" className="m-0 text-body-sm text-err">
            {failure.message}
          </p>
          {failure.stale ? (
            <Button className="min-h-11" size="sm" onClick={controls.onReload}>
              Reload the list
            </Button>
          ) : null}
        </div>
      ) : null}
    </li>
  )
}

function Rows({ items, controls }: { items: readonly ModerationItem[]; controls: Controls }) {
  return (
    <>
      {items.map((item) => (
        <Item key={`${item.kind}-${item.itemId}`} item={item} controls={controls} />
      ))}
    </>
  )
}

function MoreRows({ kind, cursor, controls }: { kind: Filter; cursor: string; controls: Controls }) {
  const [asked, setAsked] = useState(false)
  if (!asked) {
    return (
      <li className="px-4 py-3 sm:px-5">
        <Button className="min-h-11" size="sm" onClick={() => setAsked(true)}>
          Load more
        </Button>
      </li>
    )
  }
  return <NextRows kind={kind} cursor={cursor} controls={controls} />
}

function NextRows({ kind, cursor, controls }: { kind: Filter; cursor: string; controls: Controls }) {
  const query = useAdminModeration({ kind, cursor })
  if (query.isPending) {
    return (
      <li className="px-4 py-3 sm:px-5">
        <p role="status" className="m-0 text-body-sm text-ink-muted">
          Loading more
        </p>
      </li>
    )
  }
  if (query.isError) {
    return (
      <li className="flex flex-wrap items-center gap-3 px-4 py-3 sm:px-5">
        <p role="alert" className="m-0 text-body-sm text-ink">
          {adminFailureMessage(query.error, "We couldn't load more.")}
        </p>
        <Button className="min-h-11" size="sm" onClick={() => void query.refetch()}>
          Try again
        </Button>
      </li>
    )
  }
  return (
    <>
      <Rows items={query.data.items} controls={controls} />
      {query.data.nextCursor ? <MoreRows kind={kind} cursor={query.data.nextCursor} controls={controls} /> : null}
    </>
  )
}

export function Moderation() {
  const [params, setParams] = useSearchParams()
  const kind = parseFilter(params.get("kind"))
  const query = useAdminModeration({ kind })
  const online = useOnlineStatus()
  const queryClient = useQueryClient()
  const review = useModerateReview()
  const reply = useModerateReply()
  const [workingId, setWorkingId] = useState<string | null>(null)
  const [failure, setFailure] = useState<Failure | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const doneRef = useRef<HTMLParagraphElement>(null)

  useEffect(() => {
    if (done) doneRef.current?.focus()
  }, [done])

  function decide(item: ModerationItem, decision: ModerationDecision) {
    const request = moderationRequest(item, decision)
    setFailure(null)
    setDone(null)
    setWorkingId(item.itemId)
    const options = {
      onSuccess: () => setDone(moderationDoneLine(item.kind, decision)),
      onError: (error: unknown) =>
        setFailure({
          itemId: item.itemId,
          message: adminFailureMessage(error, "That didn't go through. Try again."),
          // The text changed, or somebody decided it first: what is on screen is out of date.
          stale: isTutoringError(error, "text_changed") || isTutoringError(error, "not_pending"),
        }),
      onSettled: () => setWorkingId(null),
    }
    if (request.kind === "review") review.mutate({ reviewId: request.id, body: request.body }, options)
    else reply.mutate({ replyId: request.id, body: request.body }, options)
  }

  const controls: Controls = {
    online,
    workingId,
    failure,
    onDecide: decide,
    onReload: () => {
      setFailure(null)
      void queryClient.invalidateQueries({ queryKey: tutoringKeys.adminModerationScope() })
    },
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1.5">
        <Eyebrow>Platform admin</Eyebrow>
        <h1 className="text-display-lg text-ink">Moderation</h1>
        <p className="max-w-prose text-body-md text-ink-muted">
          Review texts and tutor replies wait here until you approve them, oldest first.
        </p>
      </header>

      <Select
        label="Show"
        className="min-h-11"
        value={kind}
        wrapperClassName="w-full sm:w-64"
        onChange={(event) => {
          const next = new URLSearchParams(params)
          if (event.target.value === "all") next.delete("kind")
          else next.set("kind", event.target.value)
          setParams(next, { replace: true })
        }}
      >
        {MODERATION_FILTERS.map((filter) => (
          <option key={filter.value} value={filter.value}>
            {filter.label}
          </option>
        ))}
      </Select>

      {done ? (
        <p
          ref={doneRef}
          tabIndex={-1}
          role="status"
          className="m-0 rounded-lg border border-rule bg-ok-wash px-4 py-3 text-body-md text-ink"
        >
          {done}
        </p>
      ) : null}
      {!online ? (
        <p className="m-0 text-body-sm text-ink-muted">You're offline. Reconnect to approve or reject.</p>
      ) : null}

      <QueryState
        query={query}
        skeleton={<ListSkeleton rows={3} />}
        error={{
          heading: "We couldn't load the queue",
          body: (error) => adminFailureMessage(error, "Something went wrong loading this list. Try again."),
        }}
        isEmpty={(page) => page.items.length === 0}
        empty={
          <EmptyState
            heading="Nothing to moderate"
            body="New review texts and replies appear here when students and tutors write them."
            marginalia="all clear"
          />
        }
      >
        {(page) => (
          <ul className="m-0 list-none overflow-hidden rounded-lg border border-rule bg-paper-raised p-0">
            <Rows items={page.items} controls={controls} />
            {page.nextCursor ? <MoreRows kind={kind} cursor={page.nextCursor} controls={controls} /> : null}
          </ul>
        )}
      </QueryState>
    </div>
  )
}
