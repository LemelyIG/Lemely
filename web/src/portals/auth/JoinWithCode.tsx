/* Hallmark · pre-emit critique: P4 H4 E4 S5 R5 V4 */
import { useState, type FormEvent, type ReactNode } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { useAuth } from "@/lib/auth/AuthContext"
import { portalPathForRole } from "@/lib/auth/RequireAuth"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { SkeletonLine } from "@/components/ui/skeleton"
import { QueryState, type QueryStateQuery } from "@/components/ui/query-state"
import { ApiError } from "@/lib/api"
import type { InvitePreview } from "@/lib/authTypes"
import {
  describeInvitePreview,
  isTerminalRedeemFailure,
  normalizeInviteCode,
  previewErrorCopy,
  redeemFailureMessage,
  signupPathForInvite,
  useInvitePreview,
  useRedeemInvite,
} from "@/lib/hooks/useInvitesApi"
import { AuthFrame } from "./Login"

/*
 * G-08 · Join with an invite code (Task 18; spec §1.2, §4.3, §4.4; D7.3).
 *
 * Closes the gap spec §1.2 names directly: `POST /api/student/classes/join`
 * has been implemented, ownership-safe and tested, for a long time, and no
 * screen in the product ever let a person type the code that reaches it.
 * `ClassRoster.tsx` tells a teacher "They enter it from the student portal to
 * join"; `Standings.tsx` tells a student "Ask your teacher for a join code",
 * with nowhere on either portal to act on that. This screen is that "nowhere".
 *
 * Mounted at both `/join` and `/join/:code` (Task 19 registers the routes;
 * this file must work reachable cold, with no session, either way — see the
 * `JoinWithCode` wrapper below). Neither route is wrapped in `LoginRoute`: a
 * signed-in visitor is a legitimate reader here too (D1.10's seat/school-
 * linking case, not only the fresh-signup one), so this component itself
 * carries both branches rather than the router picking one for it.
 *
 * ── The two-hook split, and what each state actually is ─────────────────────
 *
 * `useInvitePreview` (`GET /api/invites/{code}`, public) backs the "preview
 * before committing" requirement — it is the *only* network call a signed-out
 * visitor causes from this screen; confirming while signed out is a plain
 * client-side navigation to G-03 with the code carried in the query string
 * (`signupPathForInvite`), never a redeem call this screen makes itself.
 * `useRedeemInvite` (`POST /api/invites/{code}/redeem`, authenticated) is only
 * ever invoked once `useAuth().session` is non-null.
 *
 * Of the UI spec's four named states (invalid code, expired code, seat quota
 * full, plus the already-redeemed case Task 11 added), only two live network
 * outcomes actually exist against the already-committed backend, and both are
 * documented at their source rather than re-explained here:
 *   - **invalid/expired** both surface as the *same* 404 from the preview
 *     call — see `previewErrorCopy`'s docstring (`useInvitesApi.ts`), which
 *     quotes `InviteService._find_live_invite`'s own reasoning for why.
 *   - **already redeemed** is the only 409 `POST /invites/{code}/redeem` can
 *     produce today; **seat quota full** is kept as a real, tested rendering
 *     branch for a structured marker the live backend cannot currently send,
 *     because quota is enforced at *mint* time only (`InviteService.
 *     mint_seat_invite`'s own binding rule 2) — see `isSeatQuotaExceededError`
 *     and `redeemFailureMessage`'s docstrings for the full account, and this
 *     task's report for the same finding stated plainly.
 *
 * ── Why the post-redeem destination reads `session.role`, not the result's ──
 *
 * `POST /invites/{code}/redeem` is deliberately "role-agnostic" (the router's
 * own docstring): it reports the *invite's* role, i.e. what the code
 * provisions, not the caller's own account type. A signed-in caller keeps
 * their existing account regardless of what they just redeemed — redeeming
 * attaches a school/class/seat, it does not change `users.role` — so routing
 * on `result.role` instead of the caller's own `session.role` would send a
 * signed-in teacher who redeems a (today, always student-targeted) seat
 * invite to `/student`, straight into `RequireAuth`'s guard bouncing them
 * back out again. `confirmSignedIn` below reads `session.role`.
 *
 * ── AuthFrame ─────────────────────────────────────────────────────────────
 *
 * Reused from `Login.tsx`, not copied — see that export's own docstring for
 * what a third copy of this frame has cost this codebase before
 * (`ParentLogin.tsx` carried one until P7.1).
 */

/** The pre-lookup step: a code field, optionally pre-filled from `/join/:code`
 * (spec §G-08's first bullet). Submitting moves the screen to the lookup
 * result rather than validating anything client-side beyond "not empty" —
 * the server is the only real authority on whether a code exists. */
function CodeEntryStep({
  code,
  onChangeCode,
  onSubmit,
}: {
  code: string
  onChangeCode: (value: string) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
}) {
  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5" noValidate>
      <div className="flex flex-col gap-1.5">
        <h1 className="text-display-lg text-ink">Join with an invite code</h1>
        <p className="text-body-md text-ink-muted">
          Enter the code your school or teacher gave you.
        </p>
      </div>

      <Input
        label="Invite code"
        required
        autoComplete="off"
        spellCheck={false}
        placeholder="e.g. 7HKPX2WCQY"
        value={code}
        onChange={(event) => onChangeCode(event.target.value)}
        className="font-mono tracking-[0.08em]"
      />

      <Button type="submit" variant="accent" size="lg" disabled={code.trim().length === 0}>
        Find my invite
      </Button>
    </form>
  )
}

/** Loading placeholder shaped like the preview panel it becomes (DESIGN.md
 * §12: "skeletons, not spinners; loading states match the layout they
 * replace"). Covers both the first lookup and a retry after a network/server
 * failure — `JoinWithCodeScreen` renders this whenever `preview.isFetching`,
 * which is true in both cases. */
function PreviewLoadingStep() {
  return (
    <div role="status" aria-label="Looking up your invite" className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <SkeletonLine announce={false} className="h-3" width="30%" />
        <SkeletonLine announce={false} className="h-7" width="70%" />
      </div>
      <div className="flex flex-col gap-2 rounded-md border border-rule bg-paper-sunk p-4">
        <SkeletonLine announce={false} width="60%" />
        <SkeletonLine announce={false} width="45%" />
      </div>
      <SkeletonLine announce={false} className="h-11 rounded-md" />
    </div>
  )
}

/**
 * The resolved preview — what §G-08 calls "a preview of what they're
 * joining", plus the confirm action. `isSignedIn` alone decides which of
 * `onConfirmSignedOut`/`onConfirmSignedIn` the button calls; neither branch is
 * exposed to the reader as a mode switch, it just does the right thing.
 */
function InvitePreviewStep({
  preview,
  isSignedIn,
  isRedeeming,
  redeemError,
  onConfirmSignedOut,
  onConfirmSignedIn,
  onDifferentCode,
}: {
  preview: InvitePreview
  isSignedIn: boolean
  isRedeeming: boolean
  redeemError: unknown
  onConfirmSignedOut: () => void
  onConfirmSignedIn: () => void
  onDifferentCode: () => void
}) {
  const lines = describeInvitePreview(preview)
  // Terminal failures (already redeemed, or the currently-unreachable seat-
  // quota-full marker - see `useInvitesApi.ts`) replace the confirm button
  // rather than sitting beside it: retrying the identical call reproduces the
  // identical refusal, so offering "join now" again would be a dead end
  // dressed up as an action. A transient failure (network, 5xx) is not
  // terminal, and there the button stays so "try again" is one tap.
  const terminal = isSignedIn && isTerminalRedeemFailure(redeemError)

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <div className="text-eyebrow text-ink-faint">
          {preview.role === "teacher" ? "Teacher invite" : "Student invite"}
        </div>
        <h1 className="text-display-lg text-ink">You're about to join</h1>
      </div>

      <div className="flex flex-col gap-1 rounded-md border border-rule bg-paper-sunk p-4">
        {lines.map((line, index) => (
          <p
            key={line}
            className={
              index === 0 ? "text-body-lg font-medium text-ink" : "text-body-md text-ink-muted"
            }
          >
            {line}
          </p>
        ))}
      </div>

      {redeemError ? (
        <p role="alert" className="text-body-sm text-err">
          {redeemFailureMessage(redeemError)}
        </p>
      ) : null}

      <div className="flex flex-col gap-3">
        {terminal ? null : (
          <Button
            type="button"
            variant="accent"
            size="lg"
            loading={isRedeeming}
            onClick={isSignedIn ? onConfirmSignedIn : onConfirmSignedOut}
          >
            {isSignedIn ? (isRedeeming ? "Joining…" : "Join now") : "Continue"}
          </Button>
        )}
        <Button type="button" variant="ghost" size="md" onClick={onDifferentCode}>
          Not the right invite? Enter a different code
        </Button>
      </div>
    </div>
  )
}

/** Everything below the mark. Split from `JoinWithCode` so a deep-linked code
 * change (`/join/CODE1` → `/join/CODE2`, e.g. two different links opened in
 * the same tab) fully re-initialises rather than reusing stale state — see
 * the wrapper's own comment for the `key` this relies on. */
function JoinWithCodeScreen({ initialCode }: { initialCode: string }) {
  const { session } = useAuth()
  const navigate = useNavigate()

  // Two pieces of state, not one: `codeInput` is what the field shows and is
  // always editable, `activeCode` is what drives the lookup. Keeping them
  // separate is what stops every keystroke firing a request — the lookup only
  // (re)starts on an explicit submit, or once here on mount for a deep link.
  const [codeInput, setCodeInput] = useState(initialCode)
  const [activeCode, setActiveCode] = useState(initialCode)

  const preview = useInvitePreview(activeCode)
  const redeem = useRedeemInvite()

  const handleSubmitCode = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const normalized = normalizeInviteCode(codeInput)
    if (!normalized) return
    setCodeInput(normalized)
    setActiveCode(normalized)
  }

  const goBackToEntry = () => {
    setActiveCode("")
    redeem.reset()
  }

  const confirmSignedOut = () => {
    if (!preview.data) return
    navigate(signupPathForInvite(activeCode, preview.data.role))
  }

  const confirmSignedIn = () => {
    redeem.mutate(
      { code: activeCode },
      {
        onSuccess: () => {
          // `session` is guaranteed non-null here: this handler is only ever
          // wired up when `session !== null` below (`isSignedIn`). The
          // fallback is defensive typing, not a real path — see the module
          // docstring for why this reads the caller's own role rather than
          // the redeemed invite's.
          navigate(portalPathForRole(session?.role ?? "student"), { replace: true })
        },
      },
    )
  }

  // What the preview failure means right now — recomputed every render off
  // `preview.error`, so it stays current without needing to live inside a
  // ref or effect. Also used (harmlessly) when there is no error yet:
  // `previewErrorCopy(null)` resolves to its generic, retryable branch, and
  // nothing reads `errorCopy` unless `preview.status === "error"` anyway.
  const errorCopy = previewErrorCopy(preview.error)

  /*
   * `<QueryState>`'s error action always calls `query.refetch()` (see that
   * component's own contract in `query-state.tsx`) — there is no prop to
   * point it at a different handler. This screen genuinely needs that: an
   * invalid or expired code (404) never becomes valid on a second identical
   * request (`previewErrorCopy`'s own docstring), so its action has to send
   * the reader back to code entry rather than repeat the same failing
   * lookup, while a network or server failure is worth retrying as-is.
   * Wrapping `refetch` on the query object handed to `<QueryState>` routes
   * the one real click target to the right place without `query-state.tsx`
   * needing an overridable retry callback it does not have. This is still a
   * single real query passed through, not two merged into one pseudo-query.
   */
  const previewForQueryState: QueryStateQuery<InvitePreview> = {
    /*
     * `isFetching`, not just `status`. The pre-conversion screen checked
     * `preview.isFetching` *ahead* of its error branch, so pressing "Try
     * again" put the loading step back on screen while the lookup ran.
     * `QueryState` switches on `status`, which react-query leaves at
     * `"error"` throughout a background refetch — so without this the retry
     * button changed nothing at all for a whole round trip, and nothing ever
     * again if the retry also failed. A button that does not visibly do
     * anything reads as broken, which is worse than the failure it is
     * offering to fix.
     */
    status: preview.isFetching ? "pending" : preview.status,
    data: preview.data,
    error: preview.error,
    fetchStatus: preview.fetchStatus,
    refetch: () => (errorCopy.retryable ? preview.refetch() : goBackToEntry()),
  }

  let body: ReactNode
  if (activeCode.length === 0) {
    // The lookup query is `enabled: false` for an empty code (`useInvitesApi.
    // ts`), so it sits at `status: "pending", fetchStatus: "idle"` forever —
    // exactly the case `<QueryState>`'s own `idle` prop exists for. Rather
    // than route that through `idle` (which would also need this same
    // component's landmark heading, and `CodeEntryStep` already renders its
    // own visible `<h1>`), this branch stays a plain conditional outside
    // `<QueryState>` entirely, matching the screen's original structure: the
    // query is never consulted while there is no code to look up.
    body = (
      <CodeEntryStep
        code={codeInput}
        onChangeCode={(value) => setCodeInput(normalizeInviteCode(value))}
        onSubmit={handleSubmitCode}
      />
    )
  } else {
    body = (
      <QueryState
        query={previewForQueryState}
        srHeading="Join with an invite code"
        skeleton={<PreviewLoadingStep />}
        error={{
          heading: errorCopy.heading,
          retryLabel: errorCopy.actionLabel,
          body: (err) =>
            err instanceof ApiError && err.status === 404
              ? "We couldn't find an invite for that code. Check it and try again."
              : "We couldn't look up that invite just now. Check your connection and try again.",
        }}
      >
        {(data) => (
          <InvitePreviewStep
            preview={data}
            isSignedIn={session !== null}
            isRedeeming={redeem.isPending}
            redeemError={redeem.isError ? redeem.error : null}
            onConfirmSignedOut={confirmSignedOut}
            onConfirmSignedIn={confirmSignedIn}
            onDifferentCode={goBackToEntry}
          />
        )}
      </QueryState>
    )
  }

  return (
    <AuthFrame
      dataPortal="join"
      footer={
        session === null ? (
          <p className="text-body-sm text-ink-muted">
            Already have an account?{" "}
            <Link
              to="/login"
              className="rounded-sm text-accent-ink underline underline-offset-2 transition-colors hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
            >
              Sign in
            </Link>
          </p>
        ) : undefined
      }
    >
      <div className="flex w-full max-w-100 flex-col gap-6">
        <div className="rounded-lg border border-rule bg-paper-raised p-8">{body}</div>
      </div>
    </AuthFrame>
  )
}

/**
 * Route-level wrapper for `/join` and `/join/:code` (Task 19 mounts both
 * against this same export). Reads the optional `:code` param and hands it to
 * `JoinWithCodeScreen` as a `key` as well as an initial value — the `key`
 * forces a full remount, and therefore a fresh `useState` initial value,
 * whenever the *code itself* changes rather than only when the component
 * first mounts, which a plain prop would not do for two different deep links
 * opened in the same tab without an intervening unmount.
 */
export function JoinWithCode() {
  const { code } = useParams<{ code?: string }>()
  const initialCode = normalizeInviteCode(code ?? "")
  return <JoinWithCodeScreen key={initialCode} initialCode={initialCode} />
}
