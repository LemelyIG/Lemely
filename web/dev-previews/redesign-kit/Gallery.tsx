import { useEffect, useState, type ReactNode } from "react"
import { Cards, Exam, NotePencil, Target, Lightning, ChartLineUp } from "@phosphor-icons/react"
import {
  Binny, BinnyLine, ComboChip, CountdownPill, GhostRows, GoldRing, H2Row, HairRow, HairRows, KeyRing,
  LevelBar, RankRow, StepsPath, SubjectDot, Tile, TopicChips, Walkthrough, type BinnyMood, type TileTone,
} from "@/components/redesign"
import { Switch } from "@/components/ui/switch"

/*
 * Dev-only gallery of every state of the redesign kit. Each <Frame id> is a
 * screenshot target: `redesign-kit.html#<id>`, `?theme=dark` for the dark theme.
 * Every frame renders twice, in a 390px phone column and a full-width column.
 */

const NOW = new Date(2026, 10, 15)
const MOODS: BinnyMood[] = ["happy", "wink", "open", "thinking", "sad"]
const TONES: TileTone[] = ["tide", "sea", "gold", "coral", "violet", "mint"]
const P4 = [
  { id: "a", label: "Oct", grade: "C" as const, pct: 56, caption: "45/80" },
  { id: "b", label: "Jan", grade: "B" as const, pct: 60, caption: "48/80" },
  { id: "c", label: "Feb", grade: "B" as const, pct: 63, caption: "50/80" },
  { id: "d", label: "Apr", grade: "A" as const, pct: 76, caption: "61/80" },
]
const TOPICS = [
  { topic: "Vectors", state: "work" as const, pct: 41 },
  { topic: "Algebra", state: "work" as const, pct: 58 },
  { topic: "Trigonometry", state: "getting" as const, pct: 62 },
  { topic: "Mensuration", state: "getting" as const, pct: 69 },
  { topic: "Functions", state: "getting" as const, pct: 71 },
  { topic: "Statistics", state: "getting" as const, pct: 74 },
  { topic: "Coordinate geometry", state: "secure" as const, pct: 77 },
  { topic: "Geometry", state: "secure" as const, pct: 80 },
  { topic: "Number", state: "secure" as const, pct: 82 },
  { topic: "Probability", state: "secure" as const, pct: 88 },
]
const SUBJECTS = ["Mathematics", "Physics", "Chemistry", "Biology", "English", "Computer Science", "History"]

type Theme = "light" | "dark"
const FREEZE_CSS = "*,*::before,*::after{animation:none!important;transition:none!important}"

function initialTheme(): Theme {
  const fromUrl = new URLSearchParams(location.search).get("theme")
  return fromUrl === "dark" ? "dark" : "light"
}

function Caption({ children }: { children: ReactNode }) {
  return <p className="m-0 text-xs text-on-surface-variant">{children}</p>
}

function Frame({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="grid scroll-mt-16 grid-cols-[minmax(0,1fr)] gap-3 border-b border-outline-variant py-8">
      <h2 className="text-lg font-semibold text-on-surface">{`${id} · ${title}`}</h2>
      <div className="flex flex-wrap items-start gap-8">
        <div className="grid w-[390px] max-w-full content-start gap-4 bg-surface p-4">{children}</div>
        <div className="grid min-w-0 flex-1 basis-[min(420px,100%)] content-start gap-4 bg-surface p-6">{children}</div>
      </div>
    </section>
  )
}

function Toolbar({ theme, setTheme, frozen, setFrozen }: { theme: Theme; setTheme: (t: Theme) => void; frozen: boolean; setFrozen: (f: boolean) => void }) {
  const btn = "min-h-11 rounded-full border border-outline px-4 text-sm text-on-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary aria-pressed:bg-primary aria-pressed:text-on-primary"
  return (
    <header className="sticky top-0 z-50">
    <h1 className="sr-only">Redesign kit gallery</h1>
    <div role="toolbar" aria-label="Gallery controls" className="flex flex-wrap items-center gap-2 border-b border-outline-variant bg-surface px-4 py-2 sm:px-6">
      <span className="me-auto text-sm font-medium text-on-surface">Redesign kit</span>
      <button type="button" className={btn} aria-pressed={theme === "light"} onClick={() => setTheme("light")}>Light</button>
      <button type="button" className={btn} aria-pressed={theme === "dark"} onClick={() => setTheme("dark")}>Dark</button>
      <button type="button" className={btn} aria-pressed={frozen} onClick={() => setFrozen(!frozen)}>Freeze motion</button>
    </div>
    </header>
  )
}

export function Gallery() {
  const [theme, setTheme] = useState<Theme>(initialTheme)
  const [frozen, setFrozen] = useState(() => new URLSearchParams(location.search).get("motion") === "off")
  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])
  useEffect(() => {
    if (!frozen) return
    const style = document.createElement("style")
    style.dataset.gallery = "freeze"
    style.textContent = FREEZE_CSS
    document.head.append(style)
    return () => style.remove()
  }, [frozen])

  return (
    <div className="bg-surface-container text-on-surface">
      <Toolbar theme={theme} setTheme={setTheme} frozen={frozen} setFrozen={setFrozen} />
      <main className="px-4 sm:px-6">
        <Frame id="binny" title="moods (h.js BIN), idle">
          <div className="flex flex-wrap gap-4">{MOODS.map((m) => <Binny key={m} mood={m} size={96} />)}</div>
        </Frame>
        <Frame id="binny-motion" title="hop, pop, roam, none, head crop">
          <div className="flex flex-wrap items-end gap-6">
            <Binny mood="happy" motion="hop" />
            <Binny mood="happy" motion="pop" />
            <Binny mood="happy" motion="roam" />
            <Binny mood="open" motion="none" />
            <Binny mood="happy" size={40} headCrop />
            <Binny mood="sad" size={40} headCrop motion="none" />
          </div>
        </Frame>
        <Frame id="say2" title="BinnyLine (sjf.js say)">
          <BinnyLine mood="happy" line="7 marks to A*." />
          <BinnyLine mood="thinking" line="Start with Vectors, it costs you the most." />
        </Frame>
        <Frame id="ring4" title="GoldRing and KeyRing, every tone">
          <div className="flex flex-wrap items-center gap-6">
            <GoldRing parts={[0, 0, 0]} />
            <GoldRing parts={[1, 0.5, 0]} />
            <GoldRing parts={[1, 1, 1]} size={60} center="3/3" />
            <GoldRing parts={[1, 0.5, 0]} size={60} center="1/3" />
          </div>
          <div className="flex flex-wrap items-center gap-6">
            <KeyRing value={0.48} tone="tide" center="48%" label="Progress 48%" />
            <KeyRing value={0.48} tone="gold" center="7" label="Level 7" />
            <KeyRing value={0.84} tone="ok" center="84%" label="Confidence 84%" />
            <KeyRing value={0.62} tone="warn" center="62%" label="Confidence 62%" />
            <KeyRing value={0} tone="neutral" center="–" label="No score yet" />
            <KeyRing value={0} tone="tide" center="0" label="Nothing yet" />
          </div>
        </Frame>
        <Frame id="F_P" title="StepsPath full">
          <StepsPath papers={P4} goal="A*" goalPct={85} goalCaption="68/80 · A* line" goalNote="7 to go" onSelect={() => {}} />
          <Caption>marks only, no caption: the Mono line is built from got/max</Caption>
          <StepsPath
            papers={P4.map((p, i) => ({ id: p.id, label: p.label, grade: p.grade, pct: p.pct, marks: { got: [45, 48, 50, 61][i], max: 80 } }))}
            goal="A*"
            goalPct={85}
            goalNote="7 to go"
          />
        </Frame>
        <Frame id="S_P" title="StepsPath sparse">
          <StepsPath papers={P4.slice(3)} goal="A*" goalPct={85} goalCaption="68/80 · A* line" goalNote="7 to go" ghosts={3} />
        </Frame>
        <Frame id="Z_P" title="StepsPath first run">
          <StepsPath papers={[]} goal="A*" ghosts={4} />
        </Frame>
        <Frame id="rows" title="H2Row, HairRows (plain, linked, selected)">
          <H2Row title="More marks to win" link={{ label: "All topics", to: "/" }} />
          <H2Row title="Your path to A*" titleTo="/" />
          <H2Row title="Papers" right={<CountdownPill examDate="2027-05-14" now={NOW} subject={null} />} />
          <HairRows aria-label="Marks to win">
            <HairRow title="Algebra" sub="Practise · 10 min" trailing={<b>+7</b>} to="/" />
            <HairRow title="Trigonometry" sub="Practise · 10 min" trailing={<b>+5</b>} to="/" />
            <HairRow title="Mensuration" sub="Practise · 10 min" trailing={<b>+4</b>} onClick={() => {}} selected />
          </HairRows>
        </Frame>
        <Frame id="dots" title="SubjectDot in a row">
          <HairRows aria-label="Subjects">
            {SUBJECTS.map((s) => (
              <HairRow key={s} leading={<SubjectDot subject={s} />} title={s} to="/" />
            ))}
          </HairRows>
        </Frame>
        <Frame id="SB" title="RankRow plain, with bars, selected (pa.js)">
          <HairRows aria-label="Topics costing marks">
            <RankRow rank={1} title="Vectors" sub="Practised twice this week" marksLost={9} trend="better" assigned bar={1} />
            <RankRow rank={2} title="Algebra" sub="Nothing yet" marksLost={7} trend="worse" bar={0.78} selected onClick={() => {}} />
            <RankRow rank={3} title="Waves" sub="Flashcards" marksLost={4} trend="same" bar={0.44} />
            <RankRow rank={4} title="Number" sub={<>Last practised <b>3 days ago</b></>} marksLost={2} trend="same" />
          </HairRows>
        </Frame>
        <Frame id="tmap" title="TopicChips folded and unfolded">
          <TopicChips topics={TOPICS} foldSecure onSelect={() => {}} />
          <TopicChips topics={TOPICS} />
        </Frame>
        <Frame id="CF" title="Tiles (ph.js gridC) and the homework row">
          <Tile icon={NotePencil} title="Homework: Trigonometry" status="Due Friday · 12 questions" tone="tide" big onClick={() => {}} />
          <div className="grid grid-cols-2 gap-2.5">
            <Tile icon={Target} title="Practice set" status="Build your own · 10 min" tone="tide" to="/" />
            <Tile icon={Cards} title="Flashcards" status={<><b>26</b> due today</>} tone="violet" to="/" />
            <Tile icon={Exam} title="Past papers" status="Print or do timed" tone="mint" to="/" />
            <Tile icon={Target} title="Placement test" status="Find your level · 10 min" tone="gold" disabled />
          </div>
        </Frame>
        <Frame id="CF-tones" title="Tile, all six tones, big and disabled">
          <div className="grid grid-cols-2 gap-2.5">
            {TONES.map((tone) => (
              <Tile key={tone} icon={tone === "coral" ? Lightning : ChartLineUp} title={tone} status="Tone sample" tone={tone} to="/" />
            ))}
          </div>
          <Tile icon={NotePencil} title="Homework: Algebra" status="Due Monday" tone="coral" big onClick={() => {}} />
          <Tile icon={NotePencil} title="Homework: Waves" status="Not open yet" tone="violet" big disabled />
        </Frame>
        <Frame id="walk2" title="Walkthrough numbered, with icons, and GhostRows">
          <Walkthrough steps={[{ title: "Scan a Maths paper", body: "Any past paper you have tried." }, { title: "Lemely marks it", body: "Every question, in about two minutes." }, { title: "Your path appears" }]} />
          <Walkthrough steps={[{ icon: Exam, title: "Scan a paper", body: "Photograph each page." }, { icon: Target, title: "Practise what it found" }]} />
          <GhostRows rows={3} withLeading />
          <GhostRows rows={2} />
        </Frame>
        <Frame id="game" title="ComboChip, LevelBar, CountdownPill">
          <div className="flex flex-wrap items-center gap-3">
            <ComboChip count={1} />
            <Caption>count 1 renders nothing: the chip appears from 2</Caption>
            <ComboChip count={2} />
            <ComboChip count={3} />
            <ComboChip count={27} />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <CountdownPill examDate="2027-05-14" now={NOW} to="/" />
            <CountdownPill examDate="2026-12-01" now={NOW} subject="Physics" />
            <CountdownPill examDate="2026-12-01" now={NOW} subject={null} />
          </div>
          <LevelBar level={7} xp={240} nextXp={500} />
          <LevelBar level={1} xp={0} nextXp={100} />
          <LevelBar level={30} xp={9800} nextXp={9800} />
          <Caption>top level (no next level): a full bar, valuenow equals valuemax</Caption>
          <LevelBar level={30} xp={12000} nextXp={0} />
        </Frame>
        <Frame id="FM" title="Switch on, off, disabled (pa.js .sw)">
          <Switch label="Weekly Maths email" defaultChecked layout="row" />
          <Switch label="Something to look at" layout="row" />
          <Switch label="Locked by your school" defaultChecked disabled layout="row" />
          <Switch label="Off and locked" disabled layout="row" />
        </Frame>
      </main>
    </div>
  )
}
