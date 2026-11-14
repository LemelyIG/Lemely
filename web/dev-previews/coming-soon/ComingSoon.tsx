import { useEffect, useRef, useState } from "react"
import { BrandLockup } from "@/components/ui/brand-lockup"
import { Binny, type BinnyMood } from "@/portals/marketing/Binny"
import { useWaitlist } from "@/portals/marketing/waitlist/WaitlistDialog"

export type Variant = "a" | "b" | "c"

const COPY: Record<Variant, { title: string; body: string }> = {
  a: {
    title: "Not open yet. Binny’s on it.",
    body: "The Lemely app is coming soon. Join the waitlist and we’ll email you the moment it opens.",
  },
  b: {
    title: "Almost ready. Say hi.",
    body: "The Lemely app is coming soon. Join the waitlist and we’ll email you when it opens.",
  },
  c: {
    title: "Hi, you’re early.",
    body: "The Lemely app is coming soon. Join the waitlist and Binny will make sure you hear about it.",
  },
}

function Actions() {
  const waitlist = useWaitlist()
  return (
    <div className="cs-actions">
      <button type="button" className="cs-btn" onClick={(e) => waitlist.open(e.currentTarget)}>
        Join the waitlist
      </button>
      <a className="cs-link" href="/landing">
        Back to the landing page
      </a>
    </div>
  )
}

function Header() {
  return (
    <header className="cs-head">
      <a href="/landing" aria-label="Lemely, back to the landing page">
        <BrandLockup size="sm" casing="lower" as="span" />
      </a>
    </header>
  )
}

function Copy({ variant }: { variant: Variant }) {
  const c = COPY[variant]
  return (
    <div className="cs-copy">
      <h1 className="cs-title">{c.title}</h1>
      <p className="cs-body">{c.body}</p>
      <Actions />
    </div>
  )
}

/** A: tap Binny and he reacts, cycling through his expressions. */
const CYCLE: BinnyMood[] = ["open", "happy", "wink", "nerd", "thinking"]
function VariantA() {
  const [i, setI] = useState(0)
  const [pop, setPop] = useState(0)
  const mood = CYCLE[i]
  return (
    <div className="cs-a">
      <div className="cs-stage">
        <span className="cs-bubble" aria-hidden="true">Tap me.</span>
        <button
          type="button"
          className="cs-binny-btn"
          data-pop={pop % 2}
          aria-label="Say hi to Binny"
          onClick={() => { setI((n) => (n + 1) % CYCLE.length); setPop((n) => n + 1) }}
        >
          <Binny mood={mood} className="cs-binny" />
        </button>
        <span className="cs-ground" aria-hidden="true" />
      </div>
      <Copy variant="a" />
    </div>
  )
}

function useTrack(ref: React.RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return
    const el = ref.current
    if (!el) return
    const on = (e: PointerEvent) => {
      const r = el.getBoundingClientRect()
      const dx = (e.clientX - (r.left + r.width / 2)) / Math.max(r.width, 360)
      const dy = (e.clientY - (r.top + r.height * 0.6)) / Math.max(r.height, 360)
      const clamp = (n: number) => Math.max(-1, Math.min(1, n))
      el.style.setProperty("--px", `${clamp(dx * 2.2) * 4}px`)
      el.style.setProperty("--py", `${clamp(dy * 2.2) * 3.5}px`)
    }
    addEventListener("pointermove", on)
    addEventListener("pointerdown", on)
    return () => { removeEventListener("pointermove", on); removeEventListener("pointerdown", on) }
  }, [ref])
}

/** B: C's peek, plus A's charm. Binny's eyes follow you; tap him and he pops up and reacts. */
const PEEK_CYCLE: BinnyMood[] = ["open", "happy", "wink", "thinking"]
function VariantB() {
  const ref = useRef<HTMLDivElement>(null)
  useTrack(ref)
  const [i, setI] = useState(0)
  const [pop, setPop] = useState<number | null>(null)
  return (
    <div className="cs-c">
      <Copy variant="b" />
      <div className="cs-peek" ref={ref}>
        {pop === null ? <span className="cs-bubble cs-bubble-peek" aria-hidden="true">Tap me.</span> : null}
        <button
          type="button"
          className="cs-peek-btn"
          data-pop={pop === null ? undefined : pop % 2}
          aria-label="Say hi to Binny"
          onClick={() => { setI((n) => (n + 1) % PEEK_CYCLE.length); setPop((n) => (n === null ? 0 : n + 1)) }}
        >
          <span className="cs-crop"><Binny mood={PEEK_CYCLE[i]} className="cs-binny" /></span>
        </button>
      </div>
    </div>
  )
}

/** C: Binny peeks up from the bottom edge; his pupils follow the pointer. */
function VariantC() {
  const ref = useRef<HTMLDivElement>(null)
  useTrack(ref)
  return (
    <div className="cs-c">
      <Copy variant="c" />
      <div className="cs-peek" ref={ref} aria-hidden="true">
        <div className="cs-crop"><Binny mood="open" className="cs-binny" /></div>
      </div>
    </div>
  )
}

export function ComingSoon({ variant }: { variant: Variant }) {
  return (
    <div className="marketing-brand cs-page" data-variant={variant}>
      <Header />
      <main id="main" className="cs-main">
        {variant === "a" ? <VariantA /> : variant === "b" ? <VariantB /> : <VariantC />}
      </main>
    </div>
  )
}
