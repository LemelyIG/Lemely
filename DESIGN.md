---
name: Lemely Abyss
description: Every mark, explained. Cool, precise, deep-blue brand system for the Lemely marketing portal, with Clip Letters wordmark and the Binny mascot.
colors:
  abyss: "#042f4f"
  abyss-hover: "#0a3d62"
  tide: "#7fb8e0"
  ink: "#130e10"
  white: "#ffffff"
  paper: "#f8fafd"
  subtle: "#f2f6f9"
  mist-wash: "#cfe9f9"
  hairline: "#ccdae4"
  muted-ink: "#4c575f"
  night: "#131a29"
  night-panel: "#1e2638"
  night-rule: "#394255"
  night-muted: "#bdcdda"
  gold: "#e9b452"
  correct-green: "#03642b"
  error-red: "#b00a1d"
typography:
  display:
    fontFamily: "'Bricolage Grotesque Variable', sans-serif"
    fontSize: "clamp(64px, 7.2vw, 104px)"
    fontWeight: 800
    lineHeight: 0.88
    letterSpacing: "-0.05em"
  headline:
    fontFamily: "'Bricolage Grotesque Variable', sans-serif"
    fontSize: "clamp(40px, 5vw, 68px)"
    fontWeight: 800
    lineHeight: 0.95
    letterSpacing: "-0.045em"
  title:
    fontFamily: "'Schibsted Grotesk Variable', sans-serif"
    fontSize: "21px"
    fontWeight: 800
    lineHeight: 1.2
  body:
    fontFamily: "'Schibsted Grotesk Variable', sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "'JetBrains Mono Variable', monospace"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "0.065em"
  handwriting:
    fontFamily: "'Caveat Variable', cursive"
    fontSize: "30px"
    fontWeight: 600
  scale:
    step-7: "7px"
    step-9: "9px"
    step-10: "10px"
    step-12: "12px"
    step-13: "13px"
    step-14: "14px"
    step-15: "15px"
    step-17: "17px"
    step-18: "18px"
    step-19: "19px"
    step-20: "20px"
    step-22: "22px"
    step-24: "24px"
    step-26: "26px"
    step-28: "28px"
    step-32: "32px"
    step-42: "42px"
    step-44: "44px"
    step-56: "56px"
    step-60: "60px"
    step-72: "72px"
    step-112: "112px"
rounded:
  hair: "2px"
  dot: "3px"
  track: "4px"
  xs: "5px"
  tag: "6px"
  sm: "8px"
  md: "10px"
  chip: "12px"
  lg: "14px"
  tile: "16px"
  bubble: "18px"
  xl: "20px"
  card: "24px"
  panel: "28px"
  stage: "32px"
  plate: "44px"
  full: "999px"
  pill: "50%"
spacing:
  xs: "8px"
  sm: "12px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  gutter: "32px"
  gutter-mobile: "20px"
  section: "112px"
  section-mobile: "72px"
components:
  button-primary:
    backgroundColor: "{colors.abyss}"
    textColor: "{colors.white}"
    rounded: "{rounded.lg}"
    padding: "16px 24px"
    height: "56px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.abyss}"
    rounded: "{rounded.lg}"
    padding: "16px 24px"
    height: "56px"
  button-primary-on-abyss:
    backgroundColor: "{colors.tide}"
    textColor: "{colors.abyss}"
    rounded: "{rounded.lg}"
    padding: "16px 24px"
    height: "56px"
  nav-cta:
    backgroundColor: "{colors.abyss}"
    textColor: "{colors.white}"
    rounded: "{rounded.md}"
  feature-card:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    padding: "24px"
  feature-card-core:
    backgroundColor: "{colors.abyss}"
    textColor: "{colors.white}"
    rounded: "{rounded.card}"
    padding: "32px"
  metric-card:
    backgroundColor: "{colors.night-panel}"
    textColor: "{colors.white}"
    rounded: "{rounded.card}"
    padding: "28px"
  chart-card:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "22px"
  walkthrough-stage:
    backgroundColor: "{colors.mist-wash}"
    rounded: "{rounded.stage}"
    padding: "20px"
  step-tab-active:
    backgroundColor: "{colors.abyss}"
    textColor: "{colors.white}"
    rounded: "{rounded.lg}"
    padding: "16px"
  faq-chip-open:
    backgroundColor: "{colors.abyss}"
    textColor: "{colors.white}"
    rounded: "{rounded.lg}"
    padding: "14px 18px"
  chat-bubble-student:
    backgroundColor: "{colors.abyss}"
    textColor: "{colors.white}"
    rounded: "18px"
    padding: "12px 16px"
  chat-bubble-binny:
    backgroundColor: "{colors.subtle}"
    textColor: "{colors.ink}"
    rounded: "18px"
    padding: "12px 16px"
  coming-badge:
    backgroundColor: "{colors.gold}"
    textColor: "{colors.ink}"
    rounded: "{rounded.xs}"
    padding: "3px 7px"
---

# Design System: Lemely Abyss

## 1. Overview

**Creative North Star: "The Marked Paper, Under Deep Water"**

Abyss is the current Lemely brand direction: a cool, precise, deep-blue identity (all neutrals sit near hue 240) that explains every mark. Light surfaces carry the argument, a single saturated deep blue (Abyss, #042f4f) carries action, and a pale sky blue (Tide, #7fb8e0) appears where the system needs to glow, mostly on dark. Night-blue bands break the page for proof and teacher content. Playfulness is confined to Binny the binder-clip bunny and a handwritten Caveat voice; everything else is calm and exact.

**Scope warning for agents.** These tokens apply only to the marketing portal. In code they are declared on `.marketing-brand` in `web/src/portals/marketing/brand-tokens.css` and are not global. The authenticated app (student, teacher, parent, admin, auth portals) still consumes the legacy "Study Notebook" tokens from `web/src/index.css` (`--paper`, `--ink`, `--accent`, `--rule`, pastel tags, and the `--ease-*`/`--dur-*` scales). Do not apply Abyss colors, fonts, or radii to app screens. The marketing scope aliases a few legacy names (`--paper`, `--ink`, `--accent`, `--rule`, `--font-sans`) to Abyss values so shared components render correctly inside the landing page only. The previous root DESIGN.md that described the Study Notebook system was replaced by this file; recover it from git history (the last commit before this file replaced it) when working on app screens.

The system rejects, in PRODUCT.md's words: academic and institutional aesthetics, generic SaaS dashboards, consumer edtech gamification, the "AI product" look, and cookie-cutter card grids. Archived directions (crimson v3, royal blue v4) are superseded and must not be used.

**Key Characteristics:**
- Cool and exact: neutrals tinted toward hue 240, never warm browns, never dark reds.
- One action color (Abyss); Tide is its dark-surface counterpart. Abyss is never used on dark surfaces; Tide takes over there.
- Heavy, tightly tracked display type (Bricolage Grotesque 800) against a calm grotesque body (Schibsted Grotesk).
- Flat tonal layering by default; one soft blue shadow (`--brand-shadow`) reserved for floating product artifacts.
- Clip Letters wordmark: lowercase `lemely` with both `l`s drawn as upright paperclips.
- Motion is one signature easing (`cubic-bezier(.16,1,.3,1)`), short, and fully off under `prefers-reduced-motion`.
- Layout: content column max 1304px, 32px gutters (20px under 760px), sections padded 112px (72px under 760px), 12-to-28px gaps inside components.

## 2. Colors

A cool-neutral field with one deep-blue primary, one sky accent for dark surfaces, and three strictly functional colors (gold, green, red). Values in the frontmatter are sRGB hex conversions of the OKLCH values declared in `brand-tokens.css`, which remains canonical.

### Primary
- **Abyss** (#042f4f): Primary actions, active tabs, the clip in the wordmark on light, headline emphasis spans, confidence bars, the closing section background. Hover is **Abyss Hover** (#0a3d62), also used as the inset panel color inside the core feature card.
- **Tide** (#7fb8e0): The dark-surface primary. Labels and icons on Night bands, the clip on dark, focus ring, text selection background, the walkthrough scan line, CTA fill on the Abyss closing section.

### Secondary
- **Mist Wash** (oklch(0.92 0.035 235)): Secondary container. Walkthrough stage, hero art backing plate, avatar fill, closing-section tint where used, secondary surface (`--secondary`).

### Tertiary
- **Reward Gold** (oklch(0.8 0.13 80)): Only for rewards and "coming soon" markers, and the check-ring in the accuracy dot grid. Never decorative.

### Neutral
- **Ink** (#130e10): Text on light. Letters of the wordmark on light.
- **Paper** (oklch(0.985 0.004 240)): Page background.
- **Subtle** (oklch(0.97 0.006 240)): Feature section background, Binny chat bubble fill.
- **White** (#ffffff): Raised cards, chart card, on-primary text.
- **Hairline** (oklch(0.88 0.02 240)): All borders, rules, empty progress tracks.
- **Muted Ink** (oklch(0.45 0.02 240)): Secondary text, labels, fine print.
- **Night** (oklch(0.22 0.03 264)): Proof and teacher band background.
- **Night Panel** (oklch(0.27 0.035 264)): Metric cards, accuracy block, school strip, mobile teacher cards.
- **Night Rule** (oklch(0.38 0.035 264)): Dividers on Night.
- **Night Muted** (oklch(0.84 0.025 240)): Body text on Night and on Abyss.

### Functional
- **Correct Green** (oklch(0.44 0.12 150)): Awarded marks, predicted-grade chip, correct working.
- **Error Red** (oklch(0.48 0.19 25)): Lost marks and genuine errors only.

### Named Rules
**The Dark-Surface Swap Rule.** On Night or Abyss backgrounds, accent roles move from Abyss to Tide. Abyss text or icons on a dark surface are forbidden.
**The Functional Color Rule.** Gold, green, and red each carry one meaning (reward, correct, lost marks). If one appears as decoration or as a background wash, it is wrong.
**The Cool Neutral Rule.** Every gray is tinted toward hue 240 (Night toward 264). A warm or untinted gray breaks the system.

## 3. Typography

**Display Font:** Bricolage Grotesque Variable (with sans-serif)
**Body Font:** Schibsted Grotesk Variable (with sans-serif)
**Label/Mono Font:** JetBrains Mono Variable (with monospace)
**Handwriting Font:** Caveat Variable (with cursive)

**Character:** A compressed, heavy display voice over a friendly, legible grotesque. Mono labels signal data and provenance; Caveat appears only as a student's pen or a marginal note.

### Hierarchy
- **Display** (800, clamp(64px, 7.2vw, 104px), 0.88, -0.05em): Hero h1 only. Drops to 72px at 760-1050px and 13vw under 760px.
- **Headline** (800, clamp(40px, 5vw, 68px), 0.95, -0.045em): Section h2, with balanced wrapping. 12vw on mobile. The closing h2 is larger, clamp(64px, 8vw, 112px).
- **Title** (Schibsted 800, 21px, 1.2): h3 and card titles. Feature cards use 19px; the core feature card and accuracy block use Bricolage 800 at 40px.
- **Body** (Schibsted 400, 16px, 1.5): Paragraphs, with `text-wrap: pretty`. Hero lede is 20px (18px mobile) at max 520px wide.
- **Label** (JetBrains Mono, 11px, 0.065em): Section kickers, fine print, marks, confidence values, topic lists. Chart and script labels drop to 7-9px inside product artifacts only.
- **Handwriting** (Caveat 600, 24-30px): Student working inside the script card and short margin notes (`.brand-hand`).

### Measured Reference Ramp
The `typography.scale` frontmatter lists every other fixed size the landing page uses, measured from the reference: 7, 9, 10, 12, 13, 14, 15, 17, 18, 19, 20, 22, 24, 26, 28, 32, 42, 44, 56, 60, 72 and 112px. Product-artifact labels use 7-10px, UI text 12-20px, and display or numeric figures 24-112px. The `rounded` scale likewise carries the measured radii: hair 2px, dot 3px, track 4px, tag 6px, chip 12px, tile 16px, bubble 18px, plate 44px, and full 999px (upload bar pill).

### Named Rules
**The Measured Ramp Rule.** The type ramp and radius scale include the measured reference values above, and nothing else. A new font size or radius goes into `typography.scale` or `rounded` here first, never straight into CSS.
**The Heavy Display Rule.** Bricolage is always 800 with negative tracking (-0.03em to -0.05em) and used at 28px or larger. Never set it small or light.
**The Wordmark Rule.** The wordmark is Bricolage 800, -0.04em, line-height 0.82, lowercase, bottom-aligned with the clips. Letters are Ink with an Abyss clip on light; white letters with a Tide clip on dark. Clips are always upright, stroke 5, round caps.

## 4. Elevation

Flat by default. Depth comes from tonal layering: Paper page, Subtle sections, White cards, Mist Wash stages, and full-bleed Night or Abyss bands. Borders are 1px Hairline, used mainly where white sits on near-white.

### Shadow Vocabulary
- **Floating Artifact** (`box-shadow: 0 32px 70px -40px oklch(0.3 0.08 242 / 0.4)`): The hero chart card, the marked-script card, and the fixed mobile upload bar. A long, low, blue-tinted shadow.
- **Scan Glow** (`box-shadow: 0 0 20px 5px #7fb8e0`): The walkthrough scan line only.
- **Binny Focus** (`filter: drop-shadow(0 0 4px #7fb8e0)`): Keyboard focus on the mascot.

### Named Rules
**The Flat-By-Default Rule.** Cards, panels, and chips are flat at rest. Only product artifacts that "float" over a backing plate take the Floating Artifact shadow. If a standard card has a shadow, remove it.
**The Tilted Plate Rule.** The hero artifact sits on a Mist Wash plate rotated -2.5deg with 44px radius; this tilt is the only decorative rotation besides the stacked-photo and Binny poses.

## 5. Components

### Buttons
- **Shape:** Soft squared (14px radius), 56px minimum height, 16px 24px padding, Schibsted 700 at 17px (16px mobile). Full width on mobile.
- **Primary:** Abyss fill, white text. On the Abyss closing section it becomes Tide fill with Abyss text.
- **Ghost / Secondary:** Transparent, 1.5px Hairline border, Abyss text. On Abyss it becomes white text on a Tide border.
- **Hover:** Opacity drops to 0.85 on links. There is no lift or scale.
- **Focus:** 2.5px Tide outline, 4px offset, on every focusable element.
- **Nav CTA:** Same Abyss fill and white text, 10px radius.

### Cards / Containers
- **Corner Style:** 24px for feature, metric, and FAQ cards; 28px for the hero chart card; 32px for the walkthrough stage; 20px for school strip and insight tiles; 16px for the marked-script card.
- **Background:** White on Paper or Subtle; Night Panel on Night; Mist Wash for the stage.
- **Shadow Strategy:** Flat, except the Floating Artifact cases in Elevation.
- **Border:** 1px Hairline on white-on-white (hero chart, FAQ panel); none elsewhere.
- **Internal Padding:** 24px (feature), 28px (metric), 32px (core feature, accuracy block on Night Panel).
- **Core feature card:** Abyss fill, white text, Tide label, Abyss Hover inset art panel at 20px radius.

### Inputs / Fields
- **Style:** Contact textarea inherits Hairline border and Abyss caret color; toggle-group items are white with 8px radius and flip to Abyss with white text when on.
- **Focus:** Global Tide outline.

### Navigation
- **Style:** Sticky 64px header on Paper with 1px Hairline bottom border and a 2px Abyss reading-progress bar. Links are Schibsted 600 at 14px; the active section link turns Abyss with a 2px underline at 7px offset. Under 1050px the links collapse into a sheet menu; under 760px sign-in and demo links also hide and a fixed Abyss upload bar appears at the bottom.

### Chips and Tabs
- **Step tabs (walkthrough):** Schibsted 700, 14px radius, Abyss fill with white text when selected. Stacked on desktop, a row on mobile.
- **FAQ chips:** 14px radius, bold 16px, Abyss when expanded.
- **Coming badge:** Gold fill, Ink mono 9px, 5px radius, perched 20px above its card.

### Chat (Binny FAQ)
- Student bubble: Abyss fill, white text, 18px radius with a 6px bottom-right corner. Binny bubble: Subtle fill, Ink text, 6px bottom-left corner. Typing indicator is three 7px muted dots.

### Wordmark and Binny (Signature)
- **Clip Letters wordmark:** `BrandLockup` with `identity="clip"` draws two 12x29 SVG paperclips around the letters `eme` and `y`. Minimum wordmark height is 20px; below that use the "lm" monogram icon.
- **Binny:** A binder-clip bunny in Abyss with steel wire ears. Students only, one per screen, never beside the logo. It appears in the FAQ chat header, the mobile FAQ, and peeks up from the bottom of the closing section.

### Motion
- **Easing:** `cubic-bezier(.16,1,.3,1)` for all entrances and Binny motion; `cubic-bezier(.65,0,.35,1)` for the scan line; ease-out for the typing dots.
- **Durations:** 300-600ms for entrances, 900ms for the closing peek, 1.6-2.6s for idle Binny loops. Entrances rise 8-10px; staggers run 150-300ms per item.
- **Walkthrough:** One sticky scroll scene (330vh tall on desktop) advances the pipeline. Ordinary page scrolling is never trapped. Under 760px it becomes a plain vertical sequence.
- **Reduced motion:** Under `prefers-reduced-motion: reduce` all animation and transition is disabled and the walkthrough renders as static content with full progress bars.
- **Responsive breakpoints:** 1100px, 1050px, 760px (and 700px for the hero lede), plus `pointer: coarse` which raises tap targets to 44px.

## 6. Do's and Don'ts

### Do:
- **Do** use Abyss (#042f4f) for action on light surfaces and Tide (#7fb8e0) for the same role on Night or Abyss surfaces.
- **Do** set display type in Bricolage Grotesque 800 with -0.03em to -0.05em tracking, at 28px or larger.
- **Do** keep every neutral tinted toward hue 240, and reserve Gold, Green, and Red for reward, correct, and lost marks.
- **Do** use mono labels (11px, 0.065em) for data, marks, confidence, and provenance so deterministic, AI-assisted, and missing data stay distinguishable.
- **Do** use the 14px button radius, 24px card radius, and 56px button height consistently.
- **Do** give every focusable element the 2.5px Tide outline at 4px offset.
- **Do** honor `prefers-reduced-motion` with fully static fallbacks, and keep the walkthrough scroll non-blocking.
- **Do** keep Binny to student-facing moments, one per screen, never next to the logo, and write copy in the warm, encouraging voice PRODUCT.md calls for: a result that says what to work on next beats a naked percentage.
- **Do** keep these tokens inside `.marketing-brand`; app screens keep their own legacy tokens.

### Don't:
- **Don't** apply Abyss tokens, Bricolage/Schibsted fonts, or these radii to authenticated app screens. They still use the Study Notebook tokens.
- **Don't** use Academic/institutional aesthetics: "Times New Roman, university portal grays, government-form layouts."
- **Don't** build a generic SaaS dashboard look: "navy blue hero, metric cards with gradient shadows, the HubSpot/Salesforce template." Abyss is a deep brand blue used flat; never pair it with gradient shadows or a stock navy hero.
- **Don't** drift into consumer edtech gamification: "Duolingo-style emojis-as-UI, confetti, bright primary colours, cheerleader copy."
- **Don't** produce "The 'AI product' look: purple-blue gradients, dark glassmorphic panels, neon accents on near-black." Night bands stay flat and opaque, with Tide as a restrained label and icon color, not a glow. The scan line is the only glowing element.
- **Don't** build "Cookie-cutter card grids and dense bootstrap-coloured dashboards, equal-height rows of identical boxes, colour used as decoration rather than meaning." Vary scale as the feature grid does (a 2x2 core card beside single cards) and let color carry meaning only.
- **Don't** use Abyss as text or icon color on dark surfaces.
- **Don't** use Error Red as decoration or a background wash, or Gold outside rewards and "coming soon" markers.
- **Don't** tilt the wordmark clips, use the monogram icon beside the wordmark, or set the wordmark below 20px height.
- **Don't** add shadows to ordinary cards. If a card has a shadow and is not a floating product artifact, remove it.
- **Don't** use `linear` or default browser easing for entrances; use `cubic-bezier(.16,1,.3,1)`.
- **Don't** use the words "cram", "hack", "easy A", or "guaranteed grade" in brand copy.
- **Don't** use warm browns, very dark reds, or the archived crimson and royal-blue directions as reference.
