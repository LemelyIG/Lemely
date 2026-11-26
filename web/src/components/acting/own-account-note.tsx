/* Hallmark · pre-emit critique: P4 H4 E4 S5 R5 V3 */
/*
 * ── The critique those six digits came from ────────────────────────────────
 * Axes are Hallmark's six (Philosophy, Hierarchy, Execution, Specificity, Restraint, Variety),
 * scored on the first build and re-scored after looking at it at 380, 768 and 1440 (screenshots
 * in `.superpowers/sdd/screens/p03-acting/`).
 *
 * P · philosophy — 4. Billing and the team are the caller's own account whoever they act for
 *   (spec §2.3, §7). A person who has just switched to a lead could reasonably expect the
 *   lead's invoices; this says, once, at the top of the page, that they are not looking at them.
 * H · hierarchy — 4. One sentence, quieter than the page title it sits under, louder than a
 *   footnote. Not a banner: the primary-container ground belongs to "you are acting".
 * E · execution — 4. Neutral low surface, tokens only, wraps at 380 without a fixed height.
 * S · specificity — 5. Names the lead and says what does not change.
 * R · restraint — 5. One line, no action, no icon.
 * V · variety — 3. A note strip is the shape this app already uses for standing facts.
 *
 * Revision pass: none needed. At 380 it sits under the page title and above the page's own
 * state (the team page's 403 panel), and wraps to three lines without clipping.
 */
import { ownAccountNote } from "@/lib/actingNotices"
import { useActingTeacher } from "./acting-state"

/**
 * For billing and team pages: while acting for a lead, says the page is about the caller's own
 * account. Renders nothing otherwise, and takes no space.
 */
export function OwnAccountNote() {
  const { lead } = useActingTeacher()
  if (!lead) return null
  return (
    <p
      data-testid="own-account-note"
      className="m-0 mb-6 rounded-md border border-outline-variant bg-surface-container-low px-3.5 py-2.5 text-body-sm text-on-surface-variant"
    >
      {ownAccountNote(lead.teacherName)}
    </p>
  )
}
