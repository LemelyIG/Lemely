/* Hallmark · pre-emit critique: P4 H4 E4 S5 R5 V3 */
/*
 * ── The critique those six digits came from ────────────────────────────────
 * Axes are Hallmark's six (Philosophy, Hierarchy, Execution, Specificity, Restraint, Variety),
 * scored on the first build and re-scored after looking at it at 380, 768 and 1440 (screenshots
 * in `.superpowers/sdd/screens/p03-acting/`, state `acting-unavailable`).
 *
 * P · philosophy — 4. When the server will not let an assistant read a lead's class list at all,
 *   the honest page is one answer and one way out, not a screen of per-panel errors that each
 *   say "no". The server's refusal is deliberately the same for every cause (a removed
 *   assistant, a lead on a school plan, a role with nothing), so this does not guess which.
 * H · hierarchy — 4. The kit's ErrorState: heading names the lead, one sentence of reassurance,
 *   one button. Nothing competes with "Switch back to me".
 * E · execution — 4. Reuses ErrorState; the action is a real button with the kit's focus ring and
 *   44px floor. One withheld: the unretried query means the only way to try again is to pick
 *   the team again, which is the intent and is not said on screen.
 * S · specificity — 5. Names the lead and says nothing was changed.
 * R · restraint — 5. No retry button (a second ask cannot change the answer), no jargon, no code.
 * V · variety — 3. The kit's standard terminal error panel, on purpose.
 *
 * Revision pass: none needed after the 380, 768 and 1440 captures. The panel sits where the
 * page would, the banner is hidden while it shows (one message, not two), and the caller's own
 * pages (team, billing, settings) stay reachable, which `own-account-while-unavailable` shows.
 */
import { ErrorState } from "@/components/ui/state-views"

/** The panel, with no hooks, so the preview and the tests can render it directly. */
export function ActingUnavailableView({ leadName, onSwitchBack }: { leadName: string; onSwitchBack: () => void }) {
  return (
    <ErrorState
      kicker="Team access"
      heading={`You can't work for ${leadName} right now`}
      body="Their team isn't open to you at the moment, and nothing was changed. You can keep working as yourself."
      action={{ label: "Switch back to me", onClick: onSwitchBack }}
    />
  )
}
