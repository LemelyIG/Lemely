/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V3 */
/*
 * ── The critique those six digits came from ────────────────────────────────
 * Axes are Hallmark's six (Philosophy, Hierarchy, Execution, Specificity, Restraint, Variety),
 * scored on the first build and re-scored after looking at it at 380, 768 and 1440 (screenshots
 * in `.superpowers/sdd/screens/p03-acting/`).
 *
 * P · philosophy — 4. The banner exists so nobody acts as someone else by accident. It is not a
 *   notification and does not dismiss: it is a standing fact for as long as it is true, and the
 *   way out sits in it.
 * H · hierarchy — 4. Bold lead clause names the lead and the role; a second, quieter line says
 *   what the role cannot do (only when that is true); "Switch back to me" is the one action.
 * E · execution — 4. Tertiary-container ground (amber, the kit's "pay attention, nothing is
 *   wrong" colour, not error red) with on-tertiary-container text, role="status" so it never
 *   interrupts a reader, `flex-wrap` so the action drops under the text at 380, 44px target on
 *   coarse pointers. One withheld: the compact "Working as" chip in the sticky top bar repeats
 *   the lead's name, and both must be kept in step.
 * S · specificity — 5. Names the person, the role, and the consequence ("done on their account").
 * R · restraint — 4. No icon column beyond one glyph, no timer, no second button.
 * V · variety — 3. It is the sibling of `offline-banner` and `verify-email-banner` on purpose:
 *   one banner language per portal. Withheld a point for repeating their container classes a
 *   third time, which B6's note on those two already says should become a primitive.
 *
 * Revision pass, from looking at the 380px capture: the glyph was centred against a four-line
 * block, so it floated beside the middle of the text; it now sits on the first line below `sm`.
 * The top-bar chip that repeats the lead's name was crowding the page title to "A..." at 768, so
 * it now shows from `lg` and the amber ring carries the cue below that.
 */
import { UserSwitch, X } from "@phosphor-icons/react"
import { lackedSummary } from "@/lib/actingModel"
import { leadAccess } from "@/lib/actingLeadState"
import { ROLE_COPY } from "@/lib/assistantRoles"
import { useActingTeacher } from "./acting-state"

const ACTION =
  "shrink-0 rounded-sm text-body-sm font-medium text-on-tertiary-container underline decoration-1 underline-offset-2 transition-[color,transform] hover:text-on-surface active:scale-[0.98] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:flex pointer-coarse:min-h-11 pointer-coarse:items-center"

/** The banner's markup, with no hooks, so the kit preview and the tests can render each state. */
export function ActingBannerView({
  leadName,
  roleLabel,
  lacks,
  onSwitchBack,
}: {
  leadName: string
  roleLabel: string
  /** What the role cannot do, as one sentence; `null` when nothing is missing. */
  lacks: string | null
  onSwitchBack: () => void
}) {
  return (
    <div
      role="status"
      data-testid="acting-banner"
      className="mb-6 flex flex-wrap items-start gap-x-3 gap-y-1 rounded-md sm:items-center border border-outline-variant bg-tertiary-container px-3.5 py-2.5 text-on-tertiary-container"
    >
      <UserSwitch size={18} className="mt-0.5 flex-none sm:mt-0" aria-hidden="true" />
      <div className="min-w-0 flex-1 basis-60">
        <p className="m-0 text-body-sm">
          <span className="font-medium">Working as {leadName}</span> ({roleLabel}). Everything you
          do here happens on their account.
        </p>
        {lacks ? <p className="m-0 text-body-sm opacity-90">{lacks}</p> : null}
      </div>
      <button type="button" onClick={onSwitchBack} className={ACTION}>
        Switch back to me
      </button>
    </div>
  )
}

/** After a choice was dropped (the membership ended, or could not be confirmed). */
export function ActingNoticeView({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  return (
    <div
      role="status"
      data-testid="acting-notice"
      className="mb-6 flex items-center gap-3 rounded-md border border-outline-variant bg-surface-container-low px-3.5 py-2.5"
    >
      <p className="m-0 min-w-0 flex-1 text-body-sm text-on-surface">{message}</p>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="flex h-8 w-8 flex-none items-center justify-center rounded-sm text-on-surface-variant transition-colors hover:text-on-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:h-11 pointer-coarse:w-11"
      >
        <X size={16} aria-hidden="true" />
      </button>
    </div>
  )
}

/**
 * Mounted once at the top of the teacher content column. Shows while acting for a lead, or, after
 * a choice was dropped, the reason. Nothing otherwise, and no margin either. While the lead cannot
 * be worked for, the panel that replaces the page says so, and this stays out of its way.
 */
export function ActingBanner({ classListError, pathname }: { classListError?: unknown; pathname?: string }) {
  const { lead, choose, notice, dismissNotice } = useActingTeacher()
  if (lead && leadAccess(lead, classListError, pathname ?? "") !== "ok") return null
  if (lead) {
    return (
      <ActingBannerView
        leadName={lead.teacherName}
        roleLabel={ROLE_COPY[lead.role].label}
        lacks={lackedSummary(lead.permissions)}
        onSwitchBack={() => choose(null)}
      />
    )
  }
  if (notice) return <ActingNoticeView message={notice} onDismiss={dismissNotice} />
  return null
}
