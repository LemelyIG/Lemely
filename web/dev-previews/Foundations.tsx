import { useState } from "react"
import { ComponentSection, Group, StateCell, useContrast, type Theme } from "./harness"
import { BrandLockup } from "@/components/ui/brand-lockup"
import { gradeChipClass } from "@/lib/grade"
import { cn } from "@/lib/utils"

/*
 * Foundations: the tokens and brand assets of the v5 Abyss system.
 *
 * Source of truth is DESIGN.md by way of `src/index.css`; nothing here
 * restates a colour. Swatches paint the role class, and every contrast figure
 * is measured from the colours the browser is painting in the active theme
 * (see `contrastOf` in harness.tsx), so flipping the theme toggle re-measures.
 *
 * Every Tailwind class is spelled out in full: Tailwind v4 finds classes by
 * scanning source text, so a class assembled from a template literal emits no
 * CSS and the swatch renders unpainted.
 */

type Pair = {
  name: string
  /** What the pair is for. */
  use: string
  fill: string
  on: string
  fillClass: string
  onClass: string
}

const ROLE_PAIRS: readonly Pair[] = [
  { name: "primary", use: "Buttons, links, the current item", fill: "--md-primary", on: "--md-on-primary", fillClass: "bg-primary", onClass: "text-on-primary" },
  { name: "primary-container", use: "Tonal buttons, current nav row, info badges", fill: "--md-primary-container", on: "--md-on-primary-container", fillClass: "bg-primary-container", onClass: "text-on-primary-container" },
  { name: "secondary-container", use: "Subject tags and category pills", fill: "--md-secondary-container", on: "--md-on-secondary-container", fillClass: "bg-secondary-container", onClass: "text-on-secondary-container" },
  { name: "tertiary-container", use: "Partial credit, borderline, needs a look", fill: "--md-tertiary-container", on: "--md-on-tertiary-container", fillClass: "bg-tertiary-container", onClass: "text-on-tertiary-container" },
  { name: "error-container", use: "Lost marks, failures, destructive", fill: "--md-error-container", on: "--md-on-error-container", fillClass: "bg-error-container", onClass: "text-on-error-container" },
  { name: "success-container", use: "Correct, saved, on track", fill: "--md-success-container", on: "--md-on-success-container", fillClass: "bg-success-container", onClass: "text-on-success-container" },
  { name: "inverse-surface", use: "Toasts and the one inverse panel", fill: "--md-inverse-surface", on: "--md-inverse-on-surface", fillClass: "bg-inverse-surface", onClass: "text-inverse-on-surface" },
]

const SURFACE_LADDER = [
  ["surface-container-lowest", "bg-surface-container-lowest", "Cards in light mode (white)"],
  ["surface-container-low", "bg-surface-container-low", "Rows inside a card"],
  ["surface", "bg-surface", "The page"],
  ["surface-container", "bg-surface-container", "Hover tint, dark-mode rows"],
  ["surface-container-high", "bg-surface-container-high", "Dark-mode cards, progress tracks"],
  ["surface-container-highest", "bg-surface-container-highest", "Pressed and stacked rungs"],
] as const

const SURFACE_VAR: Record<string, string> = {
  "surface-container-lowest": "--md-surface-container-lowest",
  "surface-container-low": "--md-surface-container-low",
  surface: "--md-surface",
  "surface-container": "--md-surface-container",
  "surface-container-high": "--md-surface-container-high",
  "surface-container-highest": "--md-surface-container-highest",
}

function Ratio({ fg, bg, theme }: { fg: string; bg: string; theme: Theme }) {
  const r = useContrast(fg, bg, theme)
  return <span className="text-data-sm tabular-nums">{r}</span>
}

function PairSwatch({ pair, theme }: { pair: Pair; theme: Theme }) {
  return (
    <StateCell state="default" provenance="prop" note={pair.use}>
      <div className={cn("flex w-full items-center justify-between gap-3 rounded-chip px-3 py-3", pair.fillClass, pair.onClass)}>
        <span className="text-label">{pair.name}</span>
        <Ratio fg={pair.on} bg={pair.fill} theme={theme} />
      </div>
    </StateCell>
  )
}

const GRADES = ["A*", "A", "B", "C", "D", "E", "F", "G", "U"] as const

const RADII = [
  ["rounded-bar", "bar", "4px, progress tracks"],
  ["rounded-row", "row", "10px, mark rows"],
  ["rounded-chip", "chip", "12px, nav rows, inputs"],
  ["rounded-button", "button", "14px, buttons"],
  ["rounded-inner", "inner", "18px, inner cards"],
  ["rounded-tile", "tile", "20px, tiles"],
  ["rounded-card", "card", "24px, outer cards"],
  ["rounded-board", "board", "32px, boards and sheets"],
  ["rounded-pill", "pill", "Tags and badges only"],
] as const

const DURATIONS = [
  ["--dur-instant", "instant", "120ms, colour and hover"],
  ["--dur-fast", "fast", "150ms"],
  ["--dur-base", "base", "200ms"],
  ["--dur-slow", "slow", "350ms"],
  ["--dur-celebrate", "celebrate", "900ms, reward moments"],
] as const

function MotionDemo({ dur, label }: { dur: string; label: string }) {
  const [on, setOn] = useState(false)
  return (
    <button
      type="button"
      onClick={() => setOn((v) => !v)}
      className="flex w-full flex-col gap-2 rounded-chip bg-surface-container-low p-3 text-start dark:bg-surface-container focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
      aria-label={`Replay the ${label} duration`}
    >
      <span className="relative block h-3 w-full rounded-bar bg-surface-container-high [container-type:inline-size] dark:bg-surface-container-highest">
        <span
          className="absolute start-0 top-0 block size-3 rounded-bar bg-primary motion-reduce:transition-none"
          style={{
            transform: on ? "translateX(calc(100cqw - 0.75rem))" : "translateX(0)",
            transitionProperty: "transform",
            transitionDuration: `var(${dur})`,
            transitionTimingFunction: "var(--ease-out)",
          }}
        />
      </span>
      <span className="text-data-sm text-on-surface-variant">Press to replay</span>
    </button>
  )
}

const TYPE_RUNGS = [
  ["text-display-hero", "Display hero", "Bricolage 800, 64px. Marketing only."],
  ["text-display-xl", "Display xl", "Bricolage 800, 64px."],
  ["text-display-lg", "Display lg", "Bricolage 800, 40px. Page titles."],
  ["text-display-md", "Display md", "Schibsted 800, 32px. Section headings."],
  ["text-display-sm", "Display sm", "Schibsted 700, 21px. Sub-sections."],
  ["text-display-xs", "Display xs", "Schibsted 700, 16px. Card headings."],
  ["text-body-lg", "Body lg, the default reading size", "Schibsted 400, 16px."],
  ["text-body-md", "Body md, dense copy", "Schibsted 400, 16px."],
  ["text-body-sm", "Body sm, captions and helper text", "Schibsted 400, 14px."],
  ["text-label", "Label, buttons and form labels", "Schibsted 600, 14px."],
  ["text-eyebrow", "Eyebrow, uppercase kicker", "JetBrains Mono 600, 11px, tracked."],
  ["text-label-sm", "Label sm, status sentences", "JetBrains Mono 600, 11px, no transform."],
  ["text-metadata", "Metadata, paper codes", "JetBrains Mono 500, 11px."],
  ["text-data-lg", "38/40 B 71.4%", "JetBrains Mono 600, 16px, tabular."],
  ["text-data-md", "38/40 B 71.4%", "JetBrains Mono 600, 14px, tabular."],
  ["text-data-sm", "0625/42 May-June 2024", "JetBrains Mono 600, 11px, tabular."],
] as const

const SHADOWS = [
  ["shadow-panel", "Panel", "Raised card edge. A tinted drop plus a 1px outline-variant hairline."],
  ["shadow-hover", "Hover lift", "A clickable card under the pointer. Press the cell to see it lift."],
  ["shadow-float", "Float", "Menus, popovers and toasts. Same recipe as the panel."],
] as const

export function Foundations({ theme }: { theme: Theme }) {
  return (
    <>
      <Group title="Colour">
        <ComponentSection
          name="Surface ladder"
          summary="Lemely is flat by default. Depth comes from stepping up the tonal ladder, not from shadows. Light: page on surface, cards on the white lowest rung. Dark: cards on the high rung. Ratios are on-surface text over each rung, measured live in the active theme."
        >
          {SURFACE_LADDER.map(([name, cls, use]) => (
            <StateCell key={name} state="default" provenance="prop" note={use}>
              <div className={cn("flex w-full items-center justify-between rounded-chip border border-outline-variant px-3 py-3 text-on-surface", cls)}>
                <span className="text-label">{name}</span>
                <Ratio fg="--md-on-surface" bg={SURFACE_VAR[name]!} theme={theme} />
              </div>
            </StateCell>
          ))}
        </ComponentSection>

        <ComponentSection
          name="Text and outline"
          summary="Night is the ink and is never a background. on-surface-variant is the floor for secondary text: there is deliberately no lighter step. Primary text on the page is Abyss in light mode and Tide in dark."
        >
          <StateCell state="default" provenance="prop" note="on-surface over surface">
            <div className="flex w-full items-baseline justify-between text-on-surface">
              <span className="text-body-lg">The marks you lost</span>
              <Ratio fg="--md-on-surface" bg="--md-surface" theme={theme} />
            </div>
          </StateCell>
          <StateCell state="default" provenance="prop" note="on-surface-variant over surface">
            <div className="flex w-full items-baseline justify-between text-on-surface-variant">
              <span className="text-body-lg">Paper 4, May-June 2024</span>
              <Ratio fg="--md-on-surface-variant" bg="--md-surface" theme={theme} />
            </div>
          </StateCell>
          <StateCell state="default" provenance="prop" note="primary text over surface">
            <div className="flex w-full items-baseline justify-between text-primary">
              <span className="text-label">See all marks</span>
              <Ratio fg="--md-primary" bg="--md-surface" theme={theme} />
            </div>
          </StateCell>
          <StateCell state="default" provenance="prop" note="success-text over surface. Text uses success-text, never the fill.">
            <div className="flex w-full items-baseline justify-between text-success-text">
              <span className="text-label">On track</span>
              <Ratio fg="--md-success-text" bg="--md-surface" theme={theme} />
            </div>
          </StateCell>
          <StateCell state="default" provenance="prop" note="error over surface">
            <div className="flex w-full items-baseline justify-between text-error">
              <span className="text-data-md">-3</span>
              <Ratio fg="--md-error" bg="--md-surface" theme={theme} />
            </div>
          </StateCell>
          <StateCell state="default" provenance="prop" note="outline and outline-variant: card edges and row dividers. Non-text, so no ratio is claimed.">
            <div className="flex w-full flex-col gap-2">
              <div className="rounded-chip border-2 border-outline px-3 py-2 text-body-sm text-on-surface">outline</div>
              <div className="rounded-chip border-2 border-outline-variant px-3 py-2 text-body-sm text-on-surface">outline-variant</div>
            </div>
          </StateCell>
        </ComponentSection>

        <ComponentSection
          name="Role pairs"
          summary="Every fill has exactly one measured text partner. Meaning never rides on colour alone: each of these is paired with a label or an icon at the call site."
        >
          {ROLE_PAIRS.map((p) => (
            <PairSwatch key={p.name} pair={p} theme={theme} />
          ))}
        </ComponentSection>

        <ComponentSection
          name="Grade ladder"
          summary="Nine Jewel tones from A* to U, walking from green through amber to crimson, drawn only through gradeChipClass. Large letters (18.66px bold and up) sit white on the Jewel fill; small letters cannot clear 4.5:1 on a fill, so they sit on-surface inside a 2px Jewel border."
        >
          <StateCell state="default" provenance="prop" note="large, white letter on the fill">
            <div className="flex flex-wrap gap-2">
              {GRADES.map((g) => (
                <span key={g} className={cn("grid size-12 place-items-center rounded-chip text-display-sm", gradeChipClass(g, { size: "large" }))}>
                  {g}
                </span>
              ))}
            </div>
          </StateCell>
          <StateCell state="default" provenance="prop" note="small, outlined, on-surface letter">
            <div className="flex flex-wrap gap-2">
              {GRADES.map((g) => (
                <span key={g} className={cn("inline-flex h-6 min-w-8 items-center justify-center rounded-md px-1.5 text-data-md", gradeChipClass(g, { size: "small" }))}>
                  {g}
                </span>
              ))}
            </div>
          </StateCell>
          <StateCell state="default" provenance="prop" note="A grade the ladder does not know gets the neutral chip, at both sizes">
            <div className="flex flex-wrap gap-2">
              <span className={cn("grid size-12 place-items-center rounded-chip text-display-sm", gradeChipClass("?", { size: "large" }))}>?</span>
              <span className={cn("inline-flex h-6 min-w-8 items-center justify-center rounded-md px-1.5 text-data-md", gradeChipClass("?", { size: "small" }))}>?</span>
            </div>
          </StateCell>
        </ComponentSection>
      </Group>

      <Group title="Typography">
        <ComponentSection
          name="The three faces"
          summary="Bricolage Grotesque for display at 28px and above, Schibsted Grotesk for every interface and reading size, JetBrains Mono for every number. The data rungs are tabular by construction, so a column of marks aligns and a counting score never jitters."
        >
          {TYPE_RUNGS.map(([cls, sample, spec]) => (
            <StateCell key={cls} state="default" provenance="prop" note={`${cls}. ${spec}`}>
              <span className={cn("text-on-surface", cls)}>{sample}</span>
            </StateCell>
          ))}
        </ComponentSection>
      </Group>

      <Group title="Shape and motion">
        <ComponentSection
          name="Radii"
          summary="Big radii, confident and rounded. The pill is legal only on tags and badges."
        >
          {RADII.map(([cls, name, use]) => (
            <StateCell key={name} state="default" provenance="prop" note={use}>
              <div className={cn("flex h-16 w-full items-center justify-center border-2 border-primary bg-primary-container text-label text-on-primary-container", cls)}>
                {name}
              </div>
            </StateCell>
          ))}
        </ComponentSection>

        <ComponentSection
          name="Elevation"
          summary="Flat at rest. A shadow appears only as a response to the pointer or to lift a floating panel, and it is tinted with Abyss, never neutral black. To raise something, step it up the surface ladder first."
        >
          <StateCell state="default" provenance="prop" note="Flat at rest: surface-container-lowest, 1px outline in light, no shadow">
            <div className="w-full rounded-card border border-outline bg-surface-container-lowest p-4 text-body-sm text-on-surface dark:border-outline-variant dark:bg-surface-container-high">
              Flat card
            </div>
          </StateCell>
          {SHADOWS.map(([cls, name, note]) => (
            <StateCell
              key={cls}
              state={cls === "shadow-hover" ? "hover" : "default"}
              provenance={cls === "shadow-hover" ? "live" : "prop"}
              note={`${cls}. ${note}`}
            >
              <div
                className={cn(
                  "w-full rounded-card bg-surface-container-lowest p-4 text-body-sm text-on-surface dark:bg-surface-container-high",
                  cls === "shadow-hover" ? "transition-shadow duration-[var(--dur-base)] hover:shadow-hover" : cls,
                )}
              >
                {name}
              </div>
            </StateCell>
          ))}
        </ComponentSection>

        <ComponentSection
          name="Motion"
          summary="Quick and exponential. Standard easing cubic-bezier(0.2, 0.8, 0.2, 1) with an expressive cubic-bezier(0.16, 1, 0.3, 1) for reveals. Only transform and opacity animate. prefers-reduced-motion turns the demos below to an instant jump."
        >
          {DURATIONS.map(([dur, name, note]) => (
            <StateCell key={dur} state="active" provenance="live" note={`${dur}. ${note}`}>
              <MotionDemo dur={dur} label={name} />
            </StateCell>
          ))}
        </ComponentSection>
      </Group>

      <Brand />
    </>
  )
}

/** A Night surface per DESIGN.md (`oklch(0.16 0.014 245)`), fixed in both themes so the on-night lockup can be seen while the page is light. */
const NIGHT = "bg-[oklch(0.16_0.014_245)]"

function Brand() {
  return (
    <Group title="Brand">
      <ComponentSection
        name="Mark"
        summary="The lm icon: a rounded square with rx 24 of 100, an Abyss tile, a Tide clip and a white m. The three files below are generated by npm run mark; these cells load the files exactly as the app serves them."
      >
        <StateCell state="default" provenance="prop" note="/brand/mark.svg, the full-colour app mark">
          <img src="/brand/mark.svg" alt="Lemely mark" width={96} height={96} className="size-24" />
        </StateCell>
        <StateCell state="default" provenance="prop" note="/brand/mark-favicon.svg, the tab icon, shown at 16, 32 and 64px">
          <div className="flex items-end gap-4">
            <img src="/brand/mark-favicon.svg" alt="" width={16} height={16} />
            <img src="/brand/mark-favicon.svg" alt="" width={32} height={32} />
            <img src="/brand/mark-favicon.svg" alt="Lemely favicon" width={64} height={64} />
          </div>
        </StateCell>
        <StateCell state="default" provenance="prop" note="/brand/mark-mono.svg, single colour in currentColor. Painted as a mask so it takes the role colour; as a plain image it would render black.">
          <div className="flex items-center gap-4">
            <span
              role="img"
              aria-label="Lemely mono mark, on-surface"
              className="block size-16 bg-on-surface"
              style={{ maskImage: "url(/brand/mark-mono.svg)", WebkitMaskImage: "url(/brand/mark-mono.svg)", maskSize: "contain", WebkitMaskSize: "contain", maskRepeat: "no-repeat", WebkitMaskRepeat: "no-repeat" }}
            />
            <span
              role="img"
              aria-label="Lemely mono mark, primary"
              className="block size-16 bg-primary"
              style={{ maskImage: "url(/brand/mark-mono.svg)", WebkitMaskImage: "url(/brand/mark-mono.svg)", maskSize: "contain", WebkitMaskSize: "contain", maskRepeat: "no-repeat", WebkitMaskRepeat: "no-repeat" }}
            />
            <span className={cn("grid size-20 place-items-center rounded-chip", NIGHT)}>
              <span
                role="img"
                aria-label="Lemely mono mark on Night"
                className="block size-14 bg-[#7fb8e0]"
                style={{ maskImage: "url(/brand/mark-mono.svg)", WebkitMaskImage: "url(/brand/mark-mono.svg)", maskSize: "contain", WebkitMaskSize: "contain", maskRepeat: "no-repeat", WebkitMaskRepeat: "no-repeat" }}
              />
            </span>
          </div>
        </StateCell>
        <StateCell state="default" provenance="prop" note="/brand/og-card.png, 1200 by 630, the link-preview card">
          <img src="/brand/og-card.png" alt="Lemely link preview card" width={1200} height={630} className="h-auto w-full rounded-chip" />
        </StateCell>
      </ComponentSection>

      <ComponentSection
        name="Wordmark and lockup"
        summary="Clip Letters: lowercase lemely with both ls drawn as paperclips. BrandLockup is the only way to draw it. Light surfaces get Night letters and an Abyss clip; dark surfaces get white letters and a Tide clip. The theme toggle flips the first two cells; the third is a fixed Night surface."
      >
        <StateCell state="default" provenance="prop" note="BrandLockup size sm, 26px. The sidebar row.">
          <BrandLockup />
        </StateCell>
        <StateCell state="default" provenance="prop" note="BrandLockup size md, 34px. The auth screen.">
          <BrandLockup size="md" />
        </StateCell>
        <StateCell state="default" provenance="prop" note='casing="lower", the marketing header logotype (aria-label "lemely")'>
          <BrandLockup casing="lower" />
        </StateCell>
        <StateCell state="default" provenance="prop" note="On primary-container, the tonal panel">
          <div className="flex w-full items-center justify-center rounded-chip bg-primary-container px-4 py-6">
            <BrandLockup size="md" />
          </div>
        </StateCell>
        <StateCell
          state="default"
          provenance="prop"
          note="On Night. BrandLockup has no tone prop, so letters and clip are overridden with className to the DESIGN.md pairing (white letters, Tide clip). No shipped surface draws this yet."
        >
          <div className={cn("flex w-full items-center justify-center rounded-chip px-4 py-6", NIGHT)}>
            <BrandLockup size="md" className="text-[#7fb8e0] [&_.wordmark-letters]:text-white" />
          </div>
        </StateCell>
      </ComponentSection>

      <ComponentSection
        name="Taglines"
        summary="Two audience lines from PRODUCT.md. Students hear the journey, teachers hear the proof. The master line is the teacher line."
      >
        <StateCell state="default" provenance="prop" note="Students">
          <p className="text-display-md text-on-surface">From paper to A*.</p>
        </StateCell>
        <StateCell state="default" provenance="prop" note="Teachers, and the master line">
          <p className="text-display-md text-on-surface">Every mark, explained.</p>
        </StateCell>
        <StateCell state="default" provenance="prop" note="Lockup with the teacher line beneath">
          <div className="flex flex-col gap-2">
            <BrandLockup />
            <p className="text-body-sm text-on-surface-variant">Every mark, explained.</p>
          </div>
        </StateCell>
      </ComponentSection>

      <ComponentSection
        name="App icons"
        summary="The installed-app set from web/public. Each is the file the manifest and the stores point at. The maskable icon fills its whole canvas because the OS crops it to a circle or squircle; the others carry their own rounded tile."
      >
        {(
          [
            ["/pwa-192x192.png", "192 by 192, PWA icon", 96],
            ["/pwa-512x512.png", "512 by 512, PWA icon (shown at 128)", 128],
            ["/maskable-icon-512x512.png", "512 by 512, maskable (shown at 128)", 128],
            ["/apple-touch-icon.png", "180 by 180, iOS home screen", 90],
            ["/store-icon-1024.png", "1024 by 1024, store listing (shown at 128)", 128],
            ["/shortcut-mark-96.png", "96 by 96, app shortcut", 96],
          ] as const
        ).map(([src, note, size]) => (
          <StateCell key={src} state="default" provenance="prop" note={`${src}. ${note}`}>
            <img src={src} alt="" width={size} height={size} className="rounded-chip" style={{ width: size, height: size }} />
          </StateCell>
        ))}
        <StateCell state="default" provenance="prop" note="/favicon.ico, the legacy tab icon">
          <img src="/favicon.ico" alt="" width={32} height={32} />
        </StateCell>
      </ComponentSection>
    </Group>
  )
}
