/* Hallmark · pre-emit critique: P4 H4 E5 S5 R4 V4 */
/*
 * ── The critique those six digits came from ────────────────────────────────
 *
 * Written out rather than left as bare numbers because `BUILD/BLOCKERS.md` B6
 * records that `.claude/skills/hallmark` is a broken symlink to
 * `.agents/skills/hallmark`, which does not exist in this checkout, so there
 * is **no canonical glossary of what P/H/E/S/R/V mean**. B6 also records the
 * consequence: every pre-existing file carries one of exactly two score sets,
 * which is a gate being satisfied by copying a neighbour, and a copied stamp
 * once shipped an invented `max-w-[560px]` where DESIGN.md §13 specifies
 * 680px. B6's own second remedy is "a short written justification per axis
 * rather than a bare digit", which is what this is. The axis names below are
 * the reconstruction this critique used, not a restored glossary; when the
 * real skill comes back, re-derive rather than trust these.
 *
 * P · pattern — 4. Reuses `offline-banner.tsx`'s strip rather than inventing a
 *   second banner language, which is the right call and deliberately not
 *   novel. One withheld honestly: the two banners now repeat the same ten
 *   container classes, and a shared primitive should own them once.
 * H · hierarchy — 4. Bold lead clause, supporting sentence, link, then the
 *   dismiss as the smallest and last thing. One withheld because `flex-wrap`
 *   can drop the link and the X onto their own row on a narrow viewport,
 *   where their relative weight reads flatter than intended.
 * E · economy — 5. One strip, one link, one mount. No resend UI, no second
 *   instance inside the marking panel, no timestamp. Everything the spec
 *   rejected stayed rejected.
 * S · system fidelity — 5. Every colour, radius, spacing and type value is a
 *   token already carried by the sibling banner. No raw hex, no bare pixels.
 * R · responsive — 4. `flex-wrap` with `min-w-0 flex-1` holds at 320px, the
 *   same construction as the sibling. One withheld because that is reasoned
 *   from the identical sibling, not screenshot-verified across the four
 *   mobile widths Phase 6 requires.
 * V · voice — 4. Sentence case, active, no em-dash, no invented metric, and it
 *   names the real consequence rather than nudging vaguely. One withheld
 *   because "Marking a paper stays locked" is exact for a student and a
 *   little abstract for a parent or admin, where the gate is real but the
 *   action was never theirs.
 */
import { useState } from "react"
import { Link, useLocation } from "react-router-dom"
import { EnvelopeSimple, X } from "@phosphor-icons/react"
import { useProfile } from "@/lib/hooks/useMeApi"
import { verifyEmailBannerState } from "@/lib/verifyEmailBanner"
import { readDismissed, writeDismissed } from "@/lib/verifyEmailDismissal"

/*
 * "Your email isn't verified yet", mounted once in each of the four portal
 * layouts beside `OfflineBanner`, whose conventions this follows to the
 * letter: amber/neutral rather than red (PRODUCT.md's accessibility section),
 * `role="status"` rather than `alert` so it never interrupts a screen reader
 * mid-sentence, and its own `mb-6` so that rendering nothing costs nothing in
 * layout instead of leaving an empty margined element on every page.
 *
 * Why it exists: `POST /student/correct` is guarded by D7.5's
 * `require_verified_email`, and before this the product said nothing about
 * that until the run had already been refused. `correctionOutcome.ts` now
 * words that refusal properly; this says it first, and everywhere.
 *
 * Why it links rather than resending: `VerifyEmail.tsx` already owns the
 * resend, its 429 cooldown wording and its sent/failed states. A resend button
 * in a strip that renders on every page would be a second place that can
 * disagree with the first about what a 429 means.
 *
 * Why it does not reuse `AUTH_EMAIL_UNVERIFIED`: that sentence answers "why
 * did that just fail", at the moment of a refusal. This one answers "here is a
 * standing fact about your account", which is a different thing to read even
 * though the underlying condition is the same.
 *
 * Why the copy names marking in every portal: it is the only thing the gate
 * actually locks today, and it locks it for every role rather than only for
 * students, so it is true wherever this renders. A teacher reading it learns
 * something accurate about their account rather than a vague nudge.
 *
 * Split in two, exactly as `offline-banner.tsx` is, so the strip can be looked
 * at in the dev-preview kit without a query client or a signed-in session:
 * `VerifyEmailBannerView` is the markup with no hooks; `VerifyEmailBanner` is
 * the one the layouts mount.
 */

export function VerifyEmailBannerView({ onDismiss }: { onDismiss?: () => void }) {
  return (
    <div
      role="status"
      className="mb-6 flex flex-wrap items-center gap-2.5 rounded-md border border-rule bg-paper-sunk px-3.5 py-2.5"
    >
      <EnvelopeSimple size={16} className="text-ink-muted" aria-hidden="true" />
      <p className="min-w-0 flex-1 text-body-sm text-ink">
        <span className="font-medium">Your email isn't verified yet.</span> Marking a paper stays
        locked until you verify it.
      </p>
      <Link
        to="/verify-email"
        className="shrink-0 text-body-sm text-accent-ink underline decoration-1 underline-offset-2 transition-colors hover:text-accent-hover"
      >
        Verify now
      </Link>
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss the email verification reminder"
          className="shrink-0 rounded-sm p-1 text-ink-muted transition-colors hover:text-ink"
        >
          <X size={14} aria-hidden="true" />
        </button>
      ) : null}
    </div>
  )
}

export function VerifyEmailBanner() {
  const { data } = useProfile()
  const { pathname } = useLocation()
  /*
   * Seeded from storage once, then owned by React. Reading on every render
   * would be a `sessionStorage` hit per render of every page in the app, and
   * the value cannot change underneath us: this component is the only writer.
   */
  const [dismissed, setDismissed] = useState(() =>
    readDismissed(typeof window === "undefined" ? undefined : window.sessionStorage),
  )

  const state = verifyEmailBannerState({
    emailVerified: data?.emailVerified,
    pathname,
    dismissed,
  })

  if (state === "hidden") return null

  const dismiss = () => {
    setDismissed(true)
    writeDismissed(typeof window === "undefined" ? undefined : window.sessionStorage)
  }

  // `pinned` passes no `onDismiss`, which is what removes the control: the
  // view renders it only when a caller supplies a handler, the same rule
  // `OfflineBannerView` follows for its own "Try again".
  return <VerifyEmailBannerView onDismiss={state === "pinned" ? undefined : dismiss} />
}
