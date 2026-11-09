/* Hallmark · pre-emit critique: P4 H4 E4 S5 R5 V3 */
/*
 * ── The critique those six digits came from ────────────────────────────────
 * Axes are Hallmark's six (Philosophy, Hierarchy, Execution, Specificity, Restraint, Variety),
 * scored on the first build and re-scored after looking at it at 380, 768 and 1440 (screenshots
 * in `.superpowers/sdd/screens/p03-acting/`, states `acting-lead-unavailable` and `acting-no-view`).
 *
 * P · philosophy — 4. When the server will not let an assistant read a lead's class list at all,
 *   the honest page is one answer and one way out, not a screen of per-panel errors that each
 *   say "no". The server now tells two causes apart (`team_lead_unavailable`: the lead's team
 *   cannot be reached; `team_permission_denied` on a role without `view_results`: the role cannot
 *   see classes), and the two panels say which, because only the second is something the lead can
 *   change.
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

/**
 * The panel, with no hooks, so the preview and the tests can render it directly. For a lead whose
 * team assistants cannot reach right now (`team_lead_unavailable`).
 */
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

/**
 * For a role that may not see the lead's classes at all (a refused class list on a role without
 * `view_results`). A different fact from the lead being unavailable: this one the lead can change,
 * by giving the role access to results, so it says what the role lacks rather than "right now".
 */
export function ActingNoViewView({ leadName, onSwitchBack }: { leadName: string; onSwitchBack: () => void }) {
  return (
    <ErrorState
      kicker="Your role"
      heading={`Your role can't view ${leadName}'s classes`}
      body="Their team hasn't given your role access to results, so there is nothing to show here. Nothing was changed. You can keep working as yourself."
      action={{ label: "Switch back to me", onClick: onSwitchBack }}
    />
  )
}
