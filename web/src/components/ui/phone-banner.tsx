/* Hallmark · pre-emit critique: P4 H4 E5 S5 R4 V4 */
import { useState } from "react"
import { Link, useLocation } from "react-router-dom"
import { Phone, X } from "@phosphor-icons/react"
import { MAIN_CONTENT_ID } from "@/components/ui/skip-link"
import { useProfile } from "@/lib/hooks/useMeApi"
import {
  phoneBannerState,
  profileSettingsPath,
  readPhoneBannerDismissed,
  writePhoneBannerDismissed,
} from "@/lib/phoneBanner"

/*
 * "Add your mobile number", mounted once in each of the four portal layouts directly under
 * `VerifyEmailBanner`, whose construction this follows: the same strip, `role="status"` so it never
 * interrupts a screen reader, and its own `mb-6` so that rendering nothing costs nothing.
 *
 * Who sees it: any signed-in person whose profile says `phoneMissing` (UD-11): accounts that
 * pre-date the rule, accounts a school admin provisioned, and any future sign-in method that
 * creates an account without one. It is non-blocking by design. Only paying needs a number, and
 * checkout asks for it inline when it does, so the strip says exactly that and nothing is locked.
 *
 * It links to the profile screen rather than hosting a form. A form inside a strip that renders on
 * every page would be a second place to enter the number, and at 380px a field, a hint and a button
 * do not fit a one-line strip. The profile card is the one place that saves it.
 *
 * Split in two, as the sibling is, so the strip can be looked at without a query client or a
 * session: `PhoneBannerView` is the markup with no hooks; `PhoneBanner` is the one the layouts mount.
 *
 * Self-critique:
 * P · pattern 4: the verify-email strip, deliberately not a new banner language.
 * H · hierarchy 4: bold lead, one supporting clause, link, then the dismiss as the smallest thing.
 * E · economy 5: one strip, one link, one dismiss; no form, no count, no timestamp.
 * S · system fidelity 5: tokens carried from the sibling; no raw colour or pixel values.
 * R · responsive 4: `flex-wrap` with `min-w-48 flex-1`. The sibling uses `min-w-0`, which never wraps and left
 *   this longer sentence five lines tall at 380px beside its link; with a floor the link and dismiss drop
 *   to their own row there and sit on one row from 768px up. Screenshotted at 380, 768 and 1440.
 * V · voice 4: says what the number is for, and that nothing is locked.
 */

export function PhoneBannerView({ to, onDismiss }: { to: string; onDismiss?: () => void }) {
  return (
    <div
      role="status"
      className="mb-6 flex flex-wrap items-center gap-2.5 rounded-md border border-outline-variant bg-surface-container-low px-3.5 py-2.5"
    >
      <Phone size={16} className="text-on-surface-variant" aria-hidden="true" />
      <p className="min-w-48 flex-1 text-body-sm text-on-surface">
        <span className="font-medium">Add your mobile number.</span> You'll need one on your account
        to pay for a plan or credits.
      </p>
      <Link
        to={to}
        className="shrink-0 text-body-sm text-on-primary-container underline decoration-1 underline-offset-2 transition-[color,transform] hover:text-primary-hover active:scale-[0.98] pointer-coarse:inline-flex pointer-coarse:min-h-11 pointer-coarse:items-center"
      >
        Add mobile number
      </Link>
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss the mobile reminder"
          // A 44px target, painted over the strip's own padding: the negative margins give back the
          // space so the strip is no taller than the sibling's.
          className="-my-2.5 -me-2 ms-auto inline-flex size-11 shrink-0 items-center justify-center rounded-sm text-on-surface-variant transition-[color,transform] hover:text-on-surface active:scale-[0.98]"
        >
          <X size={14} aria-hidden="true" />
        </button>
      ) : null}
    </div>
  )
}

export function PhoneBanner() {
  const { data } = useProfile()
  const { pathname } = useLocation()
  const [dismissed, setDismissed] = useState(() =>
    readPhoneBannerDismissed(typeof window === "undefined" ? undefined : window.sessionStorage),
  )

  const state = phoneBannerState({ phoneMissing: data?.phoneMissing, pathname, dismissed })
  if (state === "hidden") return null

  const dismiss = () => {
    setDismissed(true)
    writePhoneBannerDismissed(typeof window === "undefined" ? undefined : window.sessionStorage)
    // The button that held focus is about to unmount; leave focus on the page's main region rather
    // than on <body>, so the next Tab continues from the content.
    document.getElementById(MAIN_CONTENT_ID)?.focus()
  }

  return <PhoneBannerView to={profileSettingsPath(data?.role)} onDismiss={dismiss} />
}
