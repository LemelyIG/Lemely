/* Hallmark · pre-emit critique: P5 H4 E4 S5 R5 V4 */
import { useState } from "react"
import { Trash } from "@phosphor-icons/react"
import {
  useMintParentLink,
  useParentInvites,
  useParentLinks,
  useRevokeParentLink,
  useRotateParentCode,
  useUnlinkParent,
} from "@/lib/hooks/useStudentApi"
import { Avatar } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/state-views"
import { QueryState } from "@/components/ui/query-state"
import { ListSkeleton, PanelSkeleton } from "@/components/ui/loading-shapes"
import { studentLoadFailureMessage, studentSaveFailureMessage } from "@/lib/studentOutcome"

/*
 * Student-side parent access (design spec §4/§5, superseding D3.11's "add a
 * parent by phone number" — the mutation that hit that route, its request
 * DTO and the service method behind it are all gone; see `useStudentApi.ts`'s
 * own module comment on why granting is now entirely invite-based, never a
 * student-typed identifier for an account assumed to already exist).
 *
 * Not one of the numbered screens: `parent_child_links` rows are still
 * created here and nowhere else, so without this surface the entire parent
 * portal is reachable only from a seed script — "a read surface with no way
 * to grant it is not a delivered feature" (D3.11's scope note, unchanged by
 * the redesign of *how* it is granted).
 *
 * ── Two invite kinds, one screen (design spec §2/§4) ────────────────────────
 *
 * A student holds exactly one reusable code at a time (minted lazily on
 * first load, the same "a class always has a join code" rule
 * `classes.join_code` follows) and any number of single-use, 7-day links.
 * Both resolve at the existing `/join/:code` screen — this screen only mints,
 * shares, and revokes them, it does not itself decide what redeeming one
 * does.
 *
 * ── Why the student owns this ───────────────────────────────────────────────
 * The data being shared is theirs (UI spec §1.4: grades are private to the
 * student, their linked parents and their teachers), so they grant and revoke
 * it. `useParentLinks`/`useUnlinkParent` are unchanged from the phone-linking
 * era: reading and revoking an existing link is the same operation
 * regardless of how the link was made.
 */

/** A pending one-time link's expiry, phrased forward rather than borrowing
 * `relativeTime` (`lib/utils.ts`), which is written for a past timestamp
 * ("2d ago") and would read backwards applied to a future one. */
function expiryLabel(expiresAt: string): string {
  const ms = new Date(expiresAt).getTime() - Date.now()
  if (ms <= 0) return "Expired"
  const days = Math.floor(ms / 86_400_000)
  if (days >= 1) return `Expires in ${days}d`
  const hours = Math.max(1, Math.floor(ms / 3_600_000))
  return `Expires in ${hours}h`
}

/** How long a "Copied" acknowledgement stays on a button before reverting to
 * its resting label — review round 1, Minor finding 6: without a reset, the
 * label was stuck on "Copied" for the rest of the visit after the first tap. */
const COPY_ACKNOWLEDGEMENT_MS = 1500

/** Copy `text` to the clipboard, calling `onCopied` only on success. Silent
 * on failure (permissions, a non-secure context) — the code or link is still
 * visible on screen, so hand-copying it still works. */
async function copyToClipboard(text: string, onCopied: () => void) {
  try {
    await navigator.clipboard.writeText(text)
    onCopied()
  } catch {
    // Clipboard API unavailable — nothing to recover from here.
  }
}

/** Share `url` via the platform share sheet when one exists, falling back to
 * the clipboard otherwise — the spec's own "Share via `navigator.share` with
 * clipboard fallback" bullet. A visitor cancelling a real share sheet also
 * lands here having done nothing, which is the correct outcome for a
 * cancelled share, not a failure to report. */
async function shareOrCopy(url: string, onCopied: () => void) {
  if (navigator.share) {
    try {
      await navigator.share({ title: "Follow my progress on Lemely", url })
      return
    } catch {
      // Cancelled by the visitor, or unsupported at runtime despite the
      // feature check — either way, fall through to the clipboard.
    }
  }
  await copyToClipboard(url, onCopied)
}

/** "Your parent code" — the one reusable, rotatable code every student
 * always has. Copy, Share and Reset per the spec; reset (rotate) invalidates
 * whatever the old code was shared with, so it is offered plainly rather
 * than hidden behind a confirmation the spec does not ask for. */
function ParentCodeCard({ code, url }: { code: string; url: string }) {
  const rotate = useRotateParentCode()
  const [copied, setCopied] = useState(false)

  const acknowledgeCopy = () => {
    setCopied(true)
    window.setTimeout(() => setCopied(false), COPY_ACKNOWLEDGEMENT_MS)
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-rule bg-paper-raised p-5">
      <div className="flex flex-col gap-1">
        <div className="text-body-md font-medium text-ink">Your parent code</div>
        <p className="max-w-[65ch] text-body-sm text-ink-muted">
          Anyone with this code can follow your progress. Reset it if you shared it with the
          wrong person.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-md border border-rule bg-paper-sunk px-3 py-1.5 font-mono text-data-md tracking-[0.06em] text-ink">
          {code}
        </span>
        {/* Review round 1, Minor finding 6: this used to copy `url` while
            labelled plainly "Copy" beside the code the card actually shows —
            it now copies the code itself, matching what's on screen; `url`
            is what "Share" sends instead, since a share sheet wants a link. */}
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => copyToClipboard(code, acknowledgeCopy)}
        >
          {copied ? "Copied" : "Copy code"}
        </Button>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => shareOrCopy(url, acknowledgeCopy)}
        >
          Share
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          loading={rotate.isPending}
          onClick={() => rotate.mutate()}
        >
          Reset code
        </Button>
      </div>
      {rotate.isError ? (
        <p role="alert" className="text-body-sm text-err">
          {studentSaveFailureMessage(rotate.error)}
        </p>
      ) : null}
    </div>
  )
}

/** "Send a one-time link" — mint a single-use, 7-day link and manage the
 * ones still pending. Revoking one only removes it from this list; it never
 * touches an already-linked parent (that is the section below). */
function OneTimeLinkCard({
  links,
}: {
  links: { code: string; url: string; expiresAt: string }[]
}) {
  const mint = useMintParentLink()
  const revoke = useRevokeParentLink()
  const [copiedCode, setCopiedCode] = useState<string | null>(null)
  const [revokingCode, setRevokingCode] = useState<string | null>(null)
  const [revokeError, setRevokeError] = useState<{ code: string; message: string } | null>(null)

  const acknowledgeCopy = (code: string) => {
    setCopiedCode(code)
    window.setTimeout(() => setCopiedCode((current) => (current === code ? null : current)), COPY_ACKNOWLEDGEMENT_MS)
  }

  const handleRevoke = (code: string) => {
    setRevokingCode(code)
    setRevokeError(null)
    revoke.mutate(
      { code },
      {
        onError: (err) => setRevokeError({ code, message: studentSaveFailureMessage(err) }),
        onSettled: () => setRevokingCode(null),
      },
    )
  }

  // Review round 1, Minor finding 6: a freshly minted link used to appear
  // twice — once in the highlight box below (from `mint.data`, before the
  // invalidated query has refetched) and again in `links` once it has. Once
  // the list itself carries the new code, the highlight box would be a
  // duplicate of a row that already has its own copy action (below), so it
  // stops rendering.
  const justMinted = mint.data && !links.some((link) => link.code === mint.data?.code) ? mint.data : null

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-rule bg-paper-raised p-5">
      <div className="flex flex-col gap-1">
        <div className="text-body-md font-medium text-ink">Send a one-time link</div>
        <p className="max-w-[65ch] text-body-sm text-ink-muted">
          A link works once and stops working after 7 days, even if nobody uses it.
        </p>
      </div>

      <Button
        type="button"
        variant="accent"
        size="sm"
        className="w-fit"
        loading={mint.isPending}
        onClick={() => mint.mutate()}
      >
        Create a link
      </Button>
      {mint.isError ? (
        <p role="alert" className="text-body-sm text-err">
          {studentSaveFailureMessage(mint.error)}
        </p>
      ) : null}
      {justMinted ? (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-rule bg-paper-sunk px-3 py-2">
          <span className="min-w-0 flex-1 truncate text-data-sm text-ink">{justMinted.url}</span>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => copyToClipboard(justMinted.url, () => acknowledgeCopy(justMinted.code))}
          >
            {copiedCode === justMinted.code ? "Copied" : "Copy"}
          </Button>
        </div>
      ) : null}

      {links.length === 0 ? (
        <p className="text-body-sm text-ink-faint">No pending links right now.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {links.map((link) => {
            const failed = revokeError?.code === link.code ? revokeError.message : null
            return (
              <li
                key={link.code}
                className="flex flex-col gap-1 rounded-md border border-rule bg-paper-sunk px-3 py-2"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="min-w-0 flex-1 truncate text-data-sm text-ink">{link.url}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-body-sm text-ink-faint">{expiryLabel(link.expiresAt)}</span>
                    {/* Review round 1, Minor finding 6: a link minted before
                        a page reload had no way to be retrieved again except
                        reading the truncated URL by eye. */}
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-label={`Copy link for code ${link.code}`}
                      onClick={() => copyToClipboard(link.url, () => acknowledgeCopy(link.code))}
                    >
                      {copiedCode === link.code ? "Copied" : "Copy"}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-label={`Revoke link for code ${link.code}`}
                      disabled={revokingCode === link.code}
                      onClick={() => handleRevoke(link.code)}
                    >
                      {revokingCode === link.code ? "Revoking…" : "Revoke"}
                    </Button>
                  </div>
                </div>
                {failed ? (
                  <p role="alert" className="text-body-sm text-err">
                    {failed}
                  </p>
                ) : null}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

export function Parents() {
  const invites = useParentInvites()
  const parents = useParentLinks()
  const unlink = useUnlinkParent()
  const [unlinkError, setUnlinkError] = useState<{ id: string; message: string } | null>(null)
  const [removingId, setRemovingId] = useState<string | null>(null)

  const handleRemove = (parentId: string) => {
    setRemovingId(parentId)
    setUnlinkError(null)
    unlink.mutate(
      { parentId },
      {
        onError: (err) =>
          setUnlinkError({ id: parentId, message: studentSaveFailureMessage(err) }),
        onSettled: () => setRemovingId(null),
      },
    )
  }

  return (
    <div className="lm-screen flex w-full max-w-160 flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-display-md text-ink">Parent access</h1>
        <p className="max-w-[65ch] text-body-md text-ink-muted">
          Share your code or a one-time link so a parent can see your marks, predicted grades
          and weak topics. They can't change anything, and you can remove access at any time.
        </p>
      </div>

      <QueryState
        query={invites}
        srHeading="Your parent code"
        skeleton={<PanelSkeleton />}
        error={{ heading: "We couldn't load your parent code", body: studentLoadFailureMessage }}
      >
        {(data) => (
          <div className="flex flex-col gap-4">
            <ParentCodeCard code={data.code.code} url={data.code.url} />
            <OneTimeLinkCard links={data.links} />
          </div>
        )}
      </QueryState>

      <div className="flex flex-col gap-3">
        <h2 className="text-display-sm text-ink">Linked parents</h2>
        <QueryState
          query={parents}
          skeleton={<ListSkeleton rows={2} avatar />}
          error={{ heading: "We couldn't load your parents", body: studentLoadFailureMessage }}
          isEmpty={(data) => data.parents.length === 0}
          empty={
            <EmptyState
              heading="Nobody is linked to your account yet"
              body="Share your code or a link above. Nothing is shared until someone uses it."
            />
          }
        >
          {(data) => (
            <ul className="flex flex-col gap-2">
              {data.parents.map((parent) => {
                const failed = unlinkError?.id === parent.parentId ? unlinkError.message : null
                return (
                  <li
                    key={parent.parentId}
                    className="flex flex-col gap-3 rounded-lg border border-rule bg-paper-raised p-4"
                  >
                    <div className="flex items-center gap-3">
                      <Avatar name={parent.displayName} size="md" />
                      <div className="flex min-w-0 flex-1 flex-col">
                        <span className="text-body-md text-ink">{parent.displayName}</span>
                        <span className="text-data-sm text-ink-muted">{parent.email}</span>
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        aria-label={`Remove ${parent.displayName}`}
                        disabled={removingId === parent.parentId}
                        onClick={() => handleRemove(parent.parentId)}
                      >
                        <Trash size={15} aria-hidden="true" />
                        {removingId === parent.parentId ? "Removing…" : "Remove"}
                      </Button>
                    </div>
                    {failed ? (
                      <p role="alert" className="text-body-sm text-err">
                        {failed}
                      </p>
                    ) : null}
                  </li>
                )
              })}
            </ul>
          )}
        </QueryState>
      </div>
    </div>
  )
}
