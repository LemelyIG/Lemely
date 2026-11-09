/* Hallmark · pre-emit critique: P4 H3 E4 S4 R4 V3 */
/*
 * ── The critique those six digits came from ────────────────────────────────
 * Axes are Hallmark's six (Philosophy, Hierarchy, Execution, Specificity, Restraint, Variety),
 * scored on the first build and re-scored after looking at the gated screens at 380, 768 and 1440.
 *
 * P · philosophy — 4. Say why, don't just remove: an assistant who cannot generate quizzes should
 *   learn that from the screen, not by wondering where the button went. So "disable" keeps the
 *   control in view with the reason beside it, and "hide" is reserved for row-level actions
 *   (delete, remove, unshare) where an inert button on every row is noise.
 * H · hierarchy — 3. The reason is quiet text above a faded control, so the reason is read second.
 *   Withheld on purpose: when a whole form is disabled the reason is the only thing that explains
 *   an apparently dead screen, and a louder reason would out-shout the screen's own heading.
 * E · execution — 4. `<fieldset disabled>` disables every control inside it natively (focus,
 *   click, form submit), including ones added to the form later, instead of threading a
 *   `disabled` prop through each. The reason is tied to the group with aria-describedby.
 * S · specificity — 4. The reason is the server's own sentence for the same refusal, with the
 *   lead's name, so the UI and a 403 never say two different things.
 * R · restraint — 4. Two modes, no tooltip (touch cannot hover), no icon.
 * V · variety — 3. A wrapper; nothing visual to repeat.
 *
 * Revision pass: H stayed at 3 on purpose after looking at the disabled announcement form at 768:
 * the reason reads as a quiet line above a faded form, which is the right second-read for a
 * screen the person came to on purpose. Nothing is below 3, so no further pass was triggered.
 */
import { useId, type ReactNode } from "react"
import type { TeamPermission } from "@/lib/billingTypes"
import { useCan, useDeniedReason } from "./acting-state"

/**
 * Gates a region of the UI on the acting role's permission. Always renders `children` untouched
 * when working as oneself or when the role allows `permission`.
 *
 * - `disable` (default): the children stay, inside a disabled fieldset, under the reason.
 * - `hide`: the children are removed, and nothing replaces them.
 */
export function PermissionGate({
  permission,
  mode = "disable",
  children,
}: {
  permission: TeamPermission
  mode?: "disable" | "hide"
  children: ReactNode
}) {
  const allowed = useCan(permission)
  const reason = useDeniedReason(permission)
  const reasonId = useId()
  if (allowed) return <>{children}</>
  if (mode === "hide") return null
  return (
    <div className="flex flex-col gap-2">
      <p id={reasonId} role="note" className="m-0 text-body-sm text-on-surface-variant">
        {reason}
      </p>
      <fieldset
        disabled
        aria-describedby={reasonId}
        className="m-0 min-w-0 border-0 p-0 [&_button]:cursor-not-allowed"
      >
        {children}
      </fieldset>
    </div>
  )
}
