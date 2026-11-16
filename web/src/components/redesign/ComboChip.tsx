/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useState } from "react"
import { comboRose, comboVisible } from "./game"
import { FlameGlyph } from "./icons"
import "./redesign.css"

/** The gold combo chip (mock .combo). Hidden below 2; bumps when the count rises. */
export function ComboChip({ count }: { count: number }) {
  // Derived during render (not a ref + effect): `rose` stays set until the count next changes, so a parent
  // re-render mid-bump cannot strip data-bump and cut the animation short. The first render never bumps.
  const [seen, setSeen] = useState({ count, rose: false })
  if (!Object.is(seen.count, count)) setSeen({ count, rose: comboRose(seen.count, count) })
  if (!comboVisible(count)) return null
  const shown = Math.floor(count)
  // Re-keyed on every count so the bump replays; data-bump only on a rise.
  return (
    <span key={shown} className="rd-combo" data-bump={seen.rose || undefined}>
      <FlameGlyph />
      <span aria-hidden="true">{`×${shown}`}</span>
      <span className="sr-only">{`Combo of ${shown}`}</span>
    </span>
  )
}
