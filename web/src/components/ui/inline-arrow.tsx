/* Hallmark · pre-emit critique: P4 H4 E5 S5 R5 V3 */
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp } from "@phosphor-icons/react"

/*
 * Inline arrows for UI copy (P7.1).
 *
 * ── Why this exists ────────────────────────────────────────────────────────
 *
 * Fourteen buttons and links across the teacher portal ended their label with
 * a literal `"→"` (U+2192) inside the string — "Open review queue →", "Save &
 * continue →", "Review →" — and four table headers drew their sort direction
 * as `"↑"`/`"↓"`. Two rules say those cannot stay:
 *
 * §3.2 item 3 fixes one icon library for the entire product (Phosphor) and
 * item 9 bans glyph substitutes for icons. A dingbat in a string is the same
 * defect as an emoji in a heading: it renders in whatever the text face has,
 * at whatever weight that face drew it, next to Phosphor icons drawn to a
 * grid.
 *
 * **The one that actually bites is RTL, and it is why this is a component
 * rather than a find-and-replace.** §Phase 3 item 4 makes RTL-safe styles
 * binding from Phase 3 to the end of the mission, and `rtlSafety.test.ts`
 * gates it. A forward arrow is direction-dependent: "forward" is rightward in
 * English and leftward under `dir="rtl"`. `ParentLogin.tsx` already gets this
 * right and says so in a comment — `<ArrowLeft className="rtl:-scale-x-100" />`.
 * A `"→"` baked into a string **cannot be mirrored by CSS at all**: it is text,
 * not a box, and the bidi algorithm does not mirror U+2192. So the fourteen
 * sites were not merely un-flagged direction-dependent icons, they were the
 * one shape of direction-dependence that a later `dir="rtl"` flip could not
 * repair — and the gate that exists to catch exactly this reads styles, so it
 * could never have seen a character.
 *
 * The mirroring therefore lives here, once, instead of being restated as three
 * attributes at fourteen call sites where the fifteenth would forget it.
 * `rtlSafety.test.ts` gained a rule that fails on the raw characters.
 *
 * ── Sizing ────────────────────────────────────────────────────────────────
 *
 * `inline-block align-middle` rather than making every host a flex row: these
 * arrows replace a glyph that was already sitting in the text flow, and
 * changing fourteen anchors and buttons to `inline-flex` would move layout on
 * screens whose adapt findings are at zero. The icon occupies the same kind of
 * inline box the character did.
 */

/** Trailing "this goes somewhere" arrow for a button or link label.
 *
 * Decorative by contract: the label beside it already says where it goes, so
 * announcing "right arrow" would add a word the reader does not need. Mirrors
 * under `dir="rtl"` — see the header. */
export function ForwardArrow({ size = 14 }: { size?: number }) {
  return (
    <ArrowRight
      size={size}
      aria-hidden="true"
      className="inline-block align-middle rtl:-scale-x-100"
    />
  )
}

/** Leading "this goes back" arrow for a back link.
 *
 * The counterpart to `ForwardArrow`, and the reason the tree-walking rule in
 * `rtlSafety.test.ts` covers both characters: nine `"← Back"` labels existed
 * that a hand sweep for `"→"` did not find. The gate found them on its first
 * run, which is the argument for writing the rule instead of the list. */
export function BackArrow({ size = 14 }: { size?: number }) {
  return (
    <ArrowLeft
      size={size}
      aria-hidden="true"
      className="inline-block align-middle rtl:-scale-x-100"
    />
  )
}

/** Sort-direction indicator for a sortable table header.
 *
 * Decorative for the same reason and a stronger one: the `<th>` carries
 * `aria-sort`, which is how a screen reader is meant to learn this, and it
 * says "ascending"/"descending" rather than naming a glyph.
 *
 * Deliberately not mirrored. Up and down do not change meaning under RTL, and
 * `-scale-x-100` on a vertical arrow would be a no-op that reads, to the next
 * person, as if someone had thought about it and got it wrong. */
export function SortArrow({ direction }: { direction: "asc" | "desc" }) {
  const Glyph = direction === "asc" ? ArrowUp : ArrowDown
  return <Glyph size={12} aria-hidden="true" className="inline-block align-middle" />
}
