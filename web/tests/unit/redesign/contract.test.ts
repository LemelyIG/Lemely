import type { ElementType, ReactNode } from "react"
import { describe, expect, it } from "vitest"
import * as Kit from "@/components/redesign"
import type { BinnyMood, BinnyMotion, Grade, TileTone, TopicState, Trend } from "@/components/redesign"

type Fn<P> = (p: P) => unknown

// Each line copies a signature from the F1 interface contract (master plan). Assignment fails to compile on drift.
const contract = {
  Binny: Kit.Binny satisfies Fn<{ mood: BinnyMood; size?: number; motion?: BinnyMotion; className?: string; "aria-hidden"?: boolean }>,
  BinnyLine: Kit.BinnyLine satisfies Fn<{ mood: BinnyMood; line: string; motion?: BinnyMotion; size?: number }>,
  StepsPath: Kit.StepsPath satisfies Fn<{ papers: { id: string; label: string; grade: Grade; pct: number }[]; goal?: Grade; onSelect?: (id: string) => void }>,
  GoldRing: Kit.GoldRing satisfies Fn<{ parts: [number, number, number]; size?: number; label?: string; center?: ReactNode }>,
  KeyRing: Kit.KeyRing satisfies Fn<{ value: number; size?: number; tone?: "tide" | "gold" | "ok" | "warn"; center: ReactNode; label: string }>,
  Tile: Kit.Tile satisfies Fn<{ icon: ElementType; title: string; status?: string; tone: TileTone; big?: boolean; to?: string; onClick?: () => void; disabled?: boolean }>,
  H2Row: Kit.H2Row satisfies Fn<{ title: string; link?: { label: string; to?: string; onClick?: () => void } }>,
  HairRows: Kit.HairRows satisfies Fn<{ children: ReactNode; "aria-label"?: string }>,
  HairRow: Kit.HairRow satisfies Fn<{ leading?: ReactNode; title: ReactNode; sub?: ReactNode; trailing?: ReactNode; to?: string; onClick?: () => void; selected?: boolean }>,
  TopicChip: Kit.TopicChip satisfies Fn<{ topic: string; state: TopicState; onClick?: () => void }>,
  TopicChips: Kit.TopicChips satisfies Fn<{ topics: { topic: string; state: TopicState }[]; foldSecure?: boolean; onSelect?: (topic: string) => void }>,
  RankRow: Kit.RankRow satisfies Fn<{ rank: number; title: string; sub?: string; marksLost: number; trend: Trend; assigned?: boolean; bar?: number; selected?: boolean; onClick?: () => void }>,
  Walkthrough: Kit.Walkthrough satisfies Fn<{ steps: { icon: ElementType; title: string; body?: string }[] }>,
  GhostRows: Kit.GhostRows satisfies Fn<{ rows?: number; withLeading?: boolean }>,
  ComboChip: Kit.ComboChip satisfies Fn<{ count: number }>,
  LevelBar: Kit.LevelBar satisfies Fn<{ level: number; xp: number; nextXp: number }>,
  CountdownPill: Kit.CountdownPill satisfies Fn<{ examDate: string; now?: Date }>,
  countdownTone: Kit.countdownTone satisfies (examDate: string, now?: Date) => "neutral" | "near",
  // Names the barrel exports that the master plan's contract list leaves out (reported as a concern).
  SubjectDot: Kit.SubjectDot satisfies Fn<{ subject: string; size?: number }>,
  subjectDotColor: Kit.subjectDotColor satisfies (subject: string) => string,
  topicState: Kit.topicState satisfies (pct: number) => TopicState,
  gradeColorVar: Kit.gradeColorVar satisfies (grade: Grade) => string,
  daysUntil: Kit.daysUntil satisfies (examDate: string, now?: Date) => number,
  countdownLabel: Kit.countdownLabel satisfies (days: number, subject?: string | null) => string | null,
}

// The extra optional props F1 adds beyond the contract (f1-context.md). Pinned so a later lane cannot drop one.
const extras = {
  CountdownPill: Kit.CountdownPill satisfies Fn<{ examDate: string; now?: Date; subject?: string | null; to?: string }>,
  Binny: Kit.Binny satisfies Fn<{ mood: BinnyMood; roamDistance?: number; headCrop?: boolean }>,
  KeyRing: Kit.KeyRing satisfies Fn<{ value: number; tone?: "neutral" | "tide" | "gold" | "ok" | "warn"; center: ReactNode; label: string }>,
  H2Row: Kit.H2Row satisfies Fn<{ title: string; right?: ReactNode; titleTo?: string }>,
  RankRow: Kit.RankRow satisfies Fn<{ rank: number; title: string; sub?: ReactNode; marksLost: number; trend: Trend }>,
  Tile: Kit.Tile satisfies Fn<{ icon: ElementType; title: string; tone: TileTone; status?: ReactNode }>,
  TopicChip: Kit.TopicChip satisfies Fn<{ topic: string; state: TopicState; pct?: number }>,
  StepsPath: Kit.StepsPath satisfies Fn<{ papers: { id: string; label: string; grade: Grade; pct: number; caption?: string; marks?: { got: number; max: number } }[]; goalPct?: number; goalCaption?: string; goalNote?: string; ghosts?: number; "aria-label"?: string }>,
}

// Non-function data exports.
const data = { MASTERY: Kit.MASTERY, TOPIC_STATE_LABEL: Kit.TOPIC_STATE_LABEL, TREND_LABEL: Kit.TREND_LABEL }

describe("F1 interface contract", () => {
  it("exports every contract name as a function from the barrel", () => {
    for (const [name, value] of Object.entries(contract)) expect(typeof value, name).toBe("function")
    for (const [name, value] of Object.entries(extras)) expect(typeof value, name).toBe("function")
  })

  it("pins the shared data exports", () => {
    expect(data.MASTERY).toEqual({ getting: 0.6, secure: 0.75 })
    expect(Object.keys(data.TOPIC_STATE_LABEL).sort()).toEqual(["getting", "secure", "work"])
    expect(Object.keys(data.TREND_LABEL).sort()).toEqual(["better", "same", "worse"])
  })

  it("exports exactly the runtime names the kit documents, no more and no fewer", () => {
    expect(Object.keys(Kit).sort()).toEqual(
      [
        "Binny", "BinnyLine", "ComboChip", "CountdownPill", "GhostRows", "GoldRing", "H2Row", "HairRow", "HairRows", "KeyRing",
        "LevelBar", "MASTERY", "RankRow", "StepsPath", "SubjectDot", "TOPIC_STATE_LABEL", "TREND_LABEL", "Tile", "TopicChip",
        "TopicChips", "Walkthrough", "countdownLabel", "countdownTone", "daysUntil", "gradeColorVar", "subjectDotColor", "topicState",
      ].sort(),
    )
  })
})
