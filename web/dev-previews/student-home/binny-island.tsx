import type { CSSProperties } from "react"
import { createRoot, type Root } from "react-dom/client"
import { Binny, type BinnyMood as MarketingMood } from "@/portals/marketing/Binny"
import "@/portals/marketing/brand-tokens.css"
import type { BinnyMood } from "@/portals/student/home/model"

/*
 * The marketing Binny has six FAQ expressions, not the eight v5 XP moments.
 * This mapping is preview-only. The React port draws the real v5 moods.
 */
const MOOD: Record<BinnyMood, MarketingMood> = {
  marking: "thinking",
  "grade-improved": "happy",
  "paper-marked": "open",
  "streak-kept": "wink",
  idle: "idle",
}

/*
 * Binny fills from --brand-* tokens that brand-tokens.css declares on
 * .marketing-brand. That class also sets font, colour and background, so the
 * wrapper neutralises them (display: contents, inherited text, transparent) and
 * only the tokens reach the SVG. --binny-steel and --binny-cheek come from
 * src/index.css, which the preview does not load; their values are the same in
 * both schemes.
 */
const BRAND_SCOPE = {
  display: "contents",
  background: "transparent",
  color: "inherit",
  fontFamily: "inherit",
  "--binny-steel": "oklch(0.80 0.01 240)",
  "--binny-cheek": "oklch(0.72 0.10 15)",
} as CSSProperties

const roots = new WeakMap<Element, Root>()

export function renderBinny(slot: Element, mood: BinnyMood): void {
  let root = roots.get(slot)
  if (!root) {
    root = createRoot(slot)
    roots.set(slot, root)
  }
  root.render(
    <div className="marketing-brand" style={BRAND_SCOPE}>
      <Binny mood={MOOD[mood]} />
    </div>,
  )
}
