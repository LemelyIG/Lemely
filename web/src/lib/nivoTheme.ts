import { useEffect, useMemo, useState } from "react"
import type { PartialTheme } from "@nivo/theming"

/*
 * DESIGN.md §11 in code: the one shared chart theme, built from the token
 * block in `index.css`. No chart sets its own colours, and no colour, face or
 * size in this file is written as a literal — every one of them is the name of
 * a token, resolved from the document at runtime.
 *
 * **Why resolved at runtime rather than written as `var(--accent)`.** That was
 * the first cut, and it does not work. Nivo hands a series colour to
 * react-spring (`useSpring({ color })` in `@nivo/line`'s area/line renderers)
 * so it can interpolate between colours across a transition, and react-spring
 * parses the string as a colour before it ever reaches the DOM. `var(--accent)`
 * is not a parseable colour, so it does not arrive as terracotta — it arrives
 * as nothing, or as whatever the parser makes of an unrecognised token. The
 * same hazard sits one level lower even without react-spring: CSS custom
 * properties are **not** substituted inside SVG presentation attributes
 * (`stroke="var(--accent)"`), which is how the rest of a chart's colour is
 * emitted.
 *
 * That is exactly the shape this build keeps finding — a well-formed reference
 * that silently resolves to nothing, invisible to typecheck, lint and the token
 * gate alike (`--font-serif` in D4.1, `text-display` in D4.4, `lm-head` in
 * D4.5, the banned easing in D4.6). So it is not left to convention:
 * `tests/unit/chartTheme.test.ts` asserts every token named below is actually
 * defined in `index.css`, which is the failure a renamed token would otherwise
 * cause in silence.
 *
 * The values still live in exactly one place. `resolveToken` reads the computed
 * value off `:root`, so DESIGN.md remains the single source of truth and this
 * file remains a list of names.
 */

/* ── Token names ────────────────────────────────────────────────────────── */

/**
 * The six categorical series colours, in the order §11 fixes:
 * sky, sage, amber, clay, lilac, rose.
 *
 * **The `-ink` half of each pastel pair, not the wash.** §11 names the six by
 * hue, and each hue has two tokens: a wash at L≈0.94 meant for a tag's fill,
 * and its dark text partner at L≈0.42. The wash is a background colour — a
 * 2px line drawn in `--pastel-sky` on `--paper-raised` (L≈0.99) is a 0.05
 * lightness difference and is, for practical purposes, not on the screen. The
 * ink partners are the drawable half, and they are already contrast-pinned by
 * `tests/test_design_tokens.py` because they are what the tag text is set in.
 */
export const SERIES_TOKENS = [
  "--pastel-sky-ink",
  "--pastel-sage-ink",
  "--pastel-amber-ink",
  "--pastel-clay-ink",
  "--pastel-lilac-ink",
  "--pastel-rose-ink",
] as const

/**
 * The single-series colour.
 *
 * §11: "a single-series line uses `--accent` deliberately, since there is no
 * ambiguity with one line" — and, in the same breath, accent is *not* in
 * `SERIES_TOKENS`, because everywhere else in this product terracotta means
 * "the teacher's mark". Letting it become "series 1" in a six-line chart would
 * spend a meaning the rest of the interface is still using.
 */
export const SINGLE_SERIES_TOKEN = "--accent"

/** Every token this theme reads, for the gate to check against `index.css`. */
export const CHART_TOKENS = [
  ...SERIES_TOKENS,
  SINGLE_SERIES_TOKEN,
  "--accent-wash",
  "--paper-raised",
  "--paper-sunk",
  "--ink",
  "--ink-muted",
  "--ink-faint",
  "--rule",
  "--rule-faint",
  "--font-mono",
  "--font-sans",
  "--fs-data-sm",
  "--radius-sm",
  /*
   * The grade bands, for the one chart whose colour is not a series palette
   * at all. A grade-distribution bar is coloured by what the grade *means*
   * (`--grade-top` through `--grade-fail`, the same four the `GradeBadge`
   * beside it uses), and re-colouring it from `SERIES_TOKENS` would break the
   * one colour relationship in this product a teacher actually learns. They
   * are listed here so the gate checks them like every other chart token.
   */
  "--grade-top",
  "--grade-mid",
  "--grade-borderline",
  "--grade-fail",
] as const

export type ChartToken = (typeof CHART_TOKENS)[number]

/* ── Resolution ─────────────────────────────────────────────────────────── */

/**
 * The computed value of a custom property on `:root`.
 *
 * Returns `""` when there is no document (a node-env unit test) or when the
 * property is not defined. Callers must treat an empty string as "no value" and
 * not as a colour — see `buildNivoTheme`, which is why no chart renders before
 * the first resolution pass has run.
 */
export function resolveToken(name: string): string {
  if (typeof window === "undefined" || typeof getComputedStyle !== "function") {
    return ""
  }
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

/** Resolved values for every token in `CHART_TOKENS`, keyed by token name. */
export type ResolvedTokens = Record<string, string>

export function resolveChartTokens(): ResolvedTokens {
  const out: ResolvedTokens = {}
  for (const name of CHART_TOKENS) out[name] = resolveToken(name)
  return out
}

/* ── Theme ──────────────────────────────────────────────────────────────── */

/**
 * The Nivo `Theme` for every chart in the product, from resolved token values.
 *
 * Structure follows §11 line by line: paper-raised background, ink-muted text
 * in the data face with tabular figures, faint horizontal-only grid, a `--rule`
 * axis, and a tooltip that is a real surface rather than Nivo's default white
 * box with a drop shadow (§3.2 item 5 permits an ultra-diffuse shadow on a
 * floating layer, which a tooltip is, but the resting card look is flat and a
 * tooltip that does not match the popovers beside it reads as a third party's
 * component dropped into the page).
 */
export function buildNivoTheme(t: ResolvedTokens): PartialTheme {
  const text = {
    fontFamily: t["--font-mono"],
    fontSize: 11,
    fill: t["--ink-muted"],
  }
  return {
    background: "transparent",
    text: {
      ...text,
      outlineWidth: 0,
      outlineColor: "transparent",
    },
    axis: {
      domain: {
        line: {
          stroke: t["--rule"],
          strokeWidth: 1,
        },
      },
      ticks: {
        line: {
          stroke: t["--rule"],
          strokeWidth: 1,
        },
        text: {
          ...text,
          // §4: the data face carries a tick label, and tabular figures stop
          // an axis jittering horizontally as values change width.
          fontVariantNumeric: "tabular-nums",
        },
      },
      legend: {
        /*
         * The body face, not the data face — the one place in this theme that
         * departs from `text`.
         *
         * A tick label is a value ("80%", "Mar 4"), and §4.2 puts values in
         * JetBrains Mono so columns of them line up. An axis *legend* is a
         * sentence about the axis ("Paper, oldest first"), and §4.2 scopes the
         * data face to "paper codes, IDs, timestamps, metadata" — prose is not
         * on that list. Setting it in mono made the one piece of running text
         * inside a chart look like a machine-generated identifier.
         */
        text: {
          fontFamily: t["--font-sans"],
          fontSize: 11,
          fill: t["--ink-faint"],
        },
      },
    },
    grid: {
      line: {
        stroke: t["--rule-faint"],
        strokeWidth: 1,
      },
    },
    legends: {
      text: {
        ...text,
        fill: t["--ink-muted"],
      },
    },
    tooltip: {
      container: {
        background: t["--paper-raised"],
        color: t["--ink"],
        fontFamily: t["--font-mono"],
        fontSize: 11,
        border: `1px solid ${t["--rule"]}`,
        borderRadius: t["--radius-sm"],
        // The one shadow §3.2 item 5 allows on a floating layer: ultra-diffuse,
        // ≤0.05 opacity. Not a resting-card shadow.
        boxShadow: "0 4px 16px rgba(0,0,0,0.05)",
        padding: "6px 10px",
      },
    },
    crosshair: {
      line: {
        stroke: t["--ink-faint"],
        strokeWidth: 1,
        strokeOpacity: 0.5,
        strokeDasharray: "3 3",
      },
    },
    annotations: {
      text: { ...text },
    },
  }
}

/* ── Hooks ──────────────────────────────────────────────────────────────── */

/**
 * The shared theme, its resolved tokens, and whether the tokens are usable yet.
 *
 * `ready` is false on the very first render, before the effect has read the
 * document, and stays false in any environment where the tokens resolve empty.
 * Every chart wrapper gates on it, so the failure mode of an unresolvable token
 * is "no chart" rather than "a chart drawn in the browser's default black" —
 * a chart in the wrong colours is far harder to notice than a missing one, and
 * this build has now been bitten four times by exactly that asymmetry.
 */
export function useNivoTheme(): {
  theme: PartialTheme
  tokens: ResolvedTokens
  seriesColors: string[]
  singleSeriesColor: string
  ready: boolean
} {
  const [tokens, setTokens] = useState<ResolvedTokens>(() => ({}))

  useEffect(() => {
    setTokens(resolveChartTokens())
  }, [])

  return useMemo(() => {
    const seriesColors = SERIES_TOKENS.map((name) => tokens[name] ?? "")
    const singleSeriesColor = tokens[SINGLE_SERIES_TOKEN] ?? ""
    // "Usable" is a stronger claim than "present": a token that resolved to an
    // empty string is exactly the silent-nothing case this file exists to
    // prevent, so it counts as not ready.
    const ready =
      singleSeriesColor !== "" &&
      seriesColors.every((c) => c !== "") &&
      (tokens["--ink-muted"] ?? "") !== ""
    return {
      theme: buildNivoTheme(tokens),
      tokens,
      seriesColors,
      singleSeriesColor,
      ready,
    }
  }, [tokens])
}

/**
 * Whether charts on this page may animate.
 *
 * Nivo's motion config takes `animate`, and `@nivo/line` passes it straight to
 * react-spring as `immediate: !animate`, so `false` here means every value
 * lands at its final position on the first frame rather than being animated
 * quickly. That is what §9.4 asks for: reduced, not broken. The chart still
 * arrives, still has its tooltips, still reads exactly the same.
 *
 * Read live rather than once at mount, unlike `Reveal`. A chart is long-lived
 * and re-renders as its data changes, so a reader who turns reduced motion on
 * mid-session should stop seeing transitions from the next data change onward.
 */
export function useChartAnimation(): boolean {
  const [animate, setAnimate] = useState(false)

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return
    }
    const query = window.matchMedia("(prefers-reduced-motion: reduce)")
    const apply = () => setAnimate(!query.matches)
    apply()
    query.addEventListener("change", apply)
    return () => query.removeEventListener("change", apply)
  }, [])

  return animate
}
