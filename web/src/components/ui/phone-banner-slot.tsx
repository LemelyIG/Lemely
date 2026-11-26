/* Hallmark · pre-emit critique: P4 H4 E5 S5 R5 V4 */
import { Suspense, lazy } from "react"
import { useProfile } from "@/lib/hooks/useMeApi"

/*
 * What the four portal layouts mount in place of `PhoneBanner` itself. The banner shows only to
 * someone whose profile says the number is missing, which is a minority of visits, so its code
 * (the strip, its icon and its rules in `lib/phoneBanner.ts`) loads as a separate chunk only for
 * them. This file stays in the shell chunk and is a few lines: the profile read (already made by
 * the verify-email banner beside it, so it costs no request) and the lazy boundary. The shell was
 * at 149.8 of 150 KB when this split was made.
 *
 * `fallback={null}` is deliberate: the strip is an addition above the page, and a spinner for it
 * would be louder than the thing it loads. It appears when the chunk arrives.
 *
 * Self-critique:
 * P · pattern 4: the same lazy-behind-a-fact shape as the other optional shell pieces.
 * H · hierarchy 4: nothing visible of its own.
 * E · economy 5: one hook, one boundary.
 * S · system fidelity 5: no styling.
 * R · responsive 5: nothing to adapt.
 * V · voice 4: no copy.
 */

const PhoneBanner = lazy(() =>
  import("@/components/ui/phone-banner").then((m) => ({ default: m.PhoneBanner })),
)

export function PhoneBannerSlot() {
  const { data } = useProfile()
  if (data?.phoneMissing !== true) return null
  return (
    <Suspense fallback={null}>
      <PhoneBanner />
    </Suspense>
  )
}
