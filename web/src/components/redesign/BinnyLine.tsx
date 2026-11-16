/* Hallmark · pre-emit critique: P4 H3 E3 S4 R4 V3 */
import { Binny, type BinnyMood, type BinnyMotion } from "./Binny"

export interface BinnyLineProps {
  mood: BinnyMood
  /** 2–4 words. Binny appears once per screen. */
  line: string
  motion?: BinnyMotion
  size?: number
}

/** Binny with a short speech bubble (mock .say2 / .bub2). */
export function BinnyLine({ mood, line, motion = "idle", size = 60 }: BinnyLineProps) {
  return (
    <div className="rd-say">
      <Binny mood={mood} size={size} motion={motion} />
      <p className="rd-bubble">{line}</p>
    </div>
  )
}
