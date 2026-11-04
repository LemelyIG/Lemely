import { createRoot, type Root } from "react-dom/client"
import { Binny, type BinnyMood as MarketingMood } from "@/portals/marketing/Binny"
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

const roots = new WeakMap<Element, Root>()

export function renderBinny(slot: Element, mood: BinnyMood): void {
  let root = roots.get(slot)
  if (!root) {
    root = createRoot(slot)
    roots.set(slot, root)
  }
  root.render(<Binny mood={MOOD[mood]} />)
}
