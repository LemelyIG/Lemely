/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
/*
 * Motion utilities for the imported landing-page design
 * (`.superpowers/sdd/design-import-spec.md`, "Motion utilities"), scoped to
 * this portal.
 *
 * WHY THIS FILE EXISTS ALONGSIDE `@/components/ui/reveal`, RATHER THAN
 * EXTENDING IT
 * -----------------------------------------------------------------------
 * `Reveal` (`components/ui/reveal.tsx`) drives its own Tailwind utility
 * classes directly (`opacity-0 translate-y-3` → `opacity-100 translate-y-0`)
 * on an IntersectionObserver hit. The imported design's CSS
 * (`./marketing.css`) is a verbatim port of the design project's stylesheet,
 * and it is written against a different, fixed contract: literal `.reveal`
 * and `.reveal.is-in` class names driving keyframe animations (`rise`,
 * `wordrise`, `tagpop`, `panelin`, `handin`, …), several of which also read a
 * per-element `--i` custom property for their stagger delay
 * (`calc(min(var(--i),6) * 58ms)` and siblings). `Reveal` has no way to emit
 * that contract without either hardcoding this one page's class-name and
 * stagger vocabulary into a component every other portal also uses, or
 * growing a second, parallel animation path inside it selected by a prop —
 * which is the "second mechanism" the spec anticipates and asks to be named
 * if chosen. This file is that second mechanism: page-local, so the
 * vocabulary it speaks stays scoped to the one screen that needs it.
 *
 * Every hook below follows the same three rules `Reveal` already established
 * for this product (`reveal.tsx`'s own docstring): IntersectionObserver
 * only, never a scroll listener; `transform`/`opacity` only; and
 * `prefers-reduced-motion` is read in JS, at mount, so a reduced-motion
 * reader never receives the pre-animation hidden state in markup at all.
 */
import {
  Fragment,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ElementType,
  type ReactNode,
} from "react"
import { cn } from "@/lib/utils"
import { prefersReducedMotion } from "@/lib/celebration"

/**
 * The JS half of `.reveal`/`.is-in`: observes `ref`, flips `is-in` on first
 * intersection, then disconnects (`once: true`, same as `Reveal`).
 *
 * `rootMargin`/`threshold` are the spec's own figures. `index` feeds the
 * `--i` stagger custom property the ported CSS's `calc(min(var(--i),6) * …)`
 * delays read; the `min(…, 6)` cap lives in the CSS itself, so this hook
 * passes the raw index through rather than clamping twice.
 */
export function useReveal(index = 0) {
  const [reduced] = useState(prefersReducedMotion)
  const [isIn, setIsIn] = useState(reduced)
  const ref = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (reduced || isIn) return
    const node = ref.current
    if (!node || typeof IntersectionObserver === "undefined") {
      setIsIn(true)
      return
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setIsIn(true)
          observer.disconnect()
        }
      },
      { rootMargin: "0px 0px -10% 0px", threshold: 0.08 },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [reduced, isIn])

  return {
    ref,
    reduced,
    isIn,
    className: isIn ? "reveal is-in" : "reveal",
    style: { "--i": Math.min(index, 6) } as CSSProperties,
  }
}

/**
 * The self-cleaning half of the same utility: 2600ms after a `.reveal`
 * element enters, its inline `--i` stagger variable is no longer read by
 * anything (every animation it drove has a `both` fill and has finished), so
 * this drops the ref's inline style rather than leaving it attached to the
 * node indefinitely. Purely a memory/attribute-count tidy-up — nothing
 * visual depends on it — which is why it is a no-op under reduced motion
 * (nothing was ever mid-animation to clean up after).
 */
export function useRevealSelfClean(ref: React.RefObject<HTMLElement | null>, isIn: boolean, reduced: boolean) {
  useEffect(() => {
    if (reduced || !isIn) return
    const node = ref.current
    if (!node) return
    const timer = window.setTimeout(() => {
      node.style.removeProperty("--i")
    }, 2600)
    return () => window.clearTimeout(timer)
  }, [ref, isIn, reduced])
}

/**
 * The global failsafe (spec: "a global 1500ms failsafe that strips `.reveal`
 * if no observer ever fired"). Mounted once, at the portal frame
 * (`index.tsx`'s `MarketingFrame`), not per-element: its job is to recover
 * from an IntersectionObserver that exists but never reports — a stalled
 * layout, a test environment's partial DOM — not from the common case, which
 * every hook above already handles by checking for the API's absence.
 */
export function useRevealFailsafe() {
  useEffect(() => {
    if (prefersReducedMotion()) return
    const timer = window.setTimeout(() => {
      document.querySelectorAll(".reveal:not(.is-in)").forEach((el) => el.classList.add("is-in"))
    }, 1500)
    return () => window.clearTimeout(timer)
  }, [])
}

/**
 * The heading treatment named `Words` in the spec: splits `text` into words,
 * each clipped inside a `.w` span and rising out of it inside a `.wi` span
 * (`marketing.css`'s `wordrise` keyframe), on a 58ms-per-word stagger driven
 * by `--i` on the `.wi` span itself — CSS custom properties inherit, so
 * setting `--i` once on the container would give every word the same delay;
 * each word needs its own.
 *
 * The outer element carries `.words.reveal[.is-in]` (this component owns its
 * own `useReveal` call, one per heading) so a heading needs no wiring beyond
 * `<Words as="h1" text={…} />`.
 */
export function Words({
  text,
  as: Tag = "h2",
  className,
}: {
  text: string
  as?: ElementType
  className?: string
}) {
  const { ref, className: revealClassName, style, isIn, reduced } = useReveal()
  useRevealSelfClean(ref, isIn, reduced)
  const words = text.split(" ")

  return (
    <Tag ref={ref as never} className={cn("words", revealClassName, className)} style={style}>
      {words.map((word, i) => (
        // The inter-word space is a SIBLING of `.w`, not its child. `.w` is
        // `overflow:clip` (marketing.css), and a browser trims trailing
        // whitespace at the end of an inline-block box's own content — a
        // space nested as `.w`'s last child was silently disappearing,
        // rendering "Marking you can" as "Markingyoucan". Moving it outside
        // the clipped box, as plain text between two `.w` spans, keeps the
        // word-rise clip working (each word still animates inside its own
        // box) while the space between words survives normal inline layout.
        <Fragment key={`${word}-${i}`}>
          <span className="w">
            <span className="wi" style={{ "--i": i } as CSSProperties}>
              {word}
            </span>
          </span>
          {i < words.length - 1 ? " " : null}
        </Fragment>
      ))}
    </Tag>
  )
}

/**
 * A generic `.reveal`-driven wrapper for anything else in the imported CSS
 * that keys off the same class contract (`.hero__scope`, `.copy`, `.spec__…`
 * blocks a stagger-index child list, etc.) without needing the word-split
 * `Words` gives headings. `index` sets `--i` for callers whose CSS rule reads
 * it directly on the container (e.g. none currently do — every per-child
 * stagger in `marketing.css` reads `--i` off the CHILD, not the revealed
 * parent — but the prop is here for a section that needs container-level
 * timing later rather than adding a second wrapper then).
 */
export function RevealBlock({
  children,
  index = 0,
  as: Tag = "div",
  className,
  ...rest
}: {
  children: ReactNode
  index?: number
  as?: ElementType
  className?: string
  [key: string]: unknown
}) {
  const { ref, className: revealClassName, style, isIn, reduced } = useReveal(index)
  useRevealSelfClean(ref, isIn, reduced)
  return (
    <Tag ref={ref as never} className={cn(revealClassName, className)} style={style} {...rest}>
      {children}
    </Tag>
  )
}

/**
 * The nav's `.progress` bar (spec: "`scaleX` driven by scroll progress").
 * Where the browser supports `animation-timeline: scroll(root)`,
 * `marketing.css`'s own `@supports` block drives the bar entirely in CSS and
 * this hook is a no-op — the common path costs nothing. Elsewhere, the spec's
 * fallback applies: "an rAF sampler … writes the same transforms. No scroll
 * listener anywhere." `requestAnimationFrame` reads `scrollTop` once per
 * frame; it is not an event listener and never fires off the scroll event
 * itself, which is the distinction the rule draws.
 *
 * Unlike a `.drift`/`.readings` element further down the page (part B's
 * concern), the nav is sticky and on-screen for the whole session once
 * mounted, so there is no below-the-fold element to gate the sampler behind
 * an IntersectionObserver for — it would always be "in view". The loop still
 * stops entirely under `prefers-reduced-motion`, matching `marketing.css`'s
 * own reduced-motion block for `.progress` (animation removed, bar stays at
 * `scaleX(0)`).
 */
export function useScrollProgress(ref: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (prefersReducedMotion()) return
    if (typeof CSS !== "undefined" && CSS.supports?.("animation-timeline: scroll(root)")) return
    const node = ref.current
    if (!node) return
    let frame = 0
    const tick = () => {
      const doc = document.documentElement
      const max = doc.scrollHeight - doc.clientHeight
      const fraction = max > 0 ? Math.min(1, Math.max(0, doc.scrollTop / max)) : 0
      node.style.transform = `scaleX(${fraction})`
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [ref])
}

/**
 * The `--draw` progress behind `.scheme::before`/`.close__copy::before`'s
 * accent rule (spec: "a rule that draws" — `marketing.css`'s `@supports`
 * block animates `scaleY(var(--draw))` via `animation-timeline: view()`
 * where the browser has it). This is part B's fallback for the one element
 * it builds that uses `--draw` (`SchemeExcerpt`'s rule); `.close__copy`'s
 * own rule is part A's territory and, like `.drift`/`.band .wrap`/
 * `.readings`'s parallax, has no JS fallback — the same "CSS owns it where
 * supported, otherwise the effect is simply absent rather than broken"
 * precedent `useScrollProgress`'s docstring already sets for this file.
 *
 * Gated by IntersectionObserver, never a bare scroll listener: the observer
 * turns an rAF sampler on only while the element is near the viewport, and
 * the sampler reads `getBoundingClientRect()` once per frame to approximate
 * the same `entry 20% cover 45%` range the CSS timeline targets, clamped to
 * [0, 1]. Reduced motion sets the rule fully drawn once and never touches it
 * again — matching `marketing.css`'s own reduced-motion block, which removes
 * the animation and resets `transform: none` (i.e. fully drawn).
 */
export function useScrollDraw(ref: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    const node = ref.current
    if (!node) return
    if (prefersReducedMotion()) {
      node.style.setProperty("--draw", "1")
      return
    }
    if (typeof CSS !== "undefined" && CSS.supports?.("animation-timeline: view()")) return
    if (typeof IntersectionObserver === "undefined") {
      node.style.setProperty("--draw", "1")
      return
    }
    let frame = 0
    const sample = () => {
      const rect = node.getBoundingClientRect()
      const vh = window.innerHeight || document.documentElement.clientHeight
      const start = vh * 0.8 // entry 20%: rule starts drawing here
      const end = vh * 0.45 // cover 45%: fully drawn here
      const fraction = start === end ? 1 : (start - rect.top) / (start - end)
      node.style.setProperty("--draw", String(Math.min(1, Math.max(0, fraction))))
      frame = requestAnimationFrame(sample)
    }
    const observer = new IntersectionObserver(
      (entries) => {
        const inView = entries.some((entry) => entry.isIntersecting)
        if (inView) {
          frame = requestAnimationFrame(sample)
        } else if (frame) {
          cancelAnimationFrame(frame)
          frame = 0
        }
      },
      { rootMargin: "20% 0px -45% 0px" },
    )
    observer.observe(node)
    return () => {
      observer.disconnect()
      if (frame) cancelAnimationFrame(frame)
    }
  }, [ref])
}
