---
name: Academic Warmth
colors:
  surface: '#fff8f6'
  surface-dim: '#e8d6d2'
  surface-bright: '#fff8f6'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#fff0ed'
  surface-container: '#fceae6'
  surface-container-high: '#f6e4e0'
  surface-container-highest: '#f1dfdb'
  on-surface: '#231917'
  on-surface-variant: '#55423f'
  inverse-surface: '#392e2c'
  inverse-on-surface: '#ffede9'
  outline: '#88726e'
  outline-variant: '#dbc1bb'
  surface-tint: '#994534'
  primary: '#964232'
  on-primary: '#ffffff'
  primary-container: '#b55a48'
  on-primary-container: '#fffbff'
  inverse-primary: '#ffb4a5'
  secondary: '#80534a'
  on-secondary: '#ffffff'
  secondary-container: '#ffc4b8'
  on-secondary-container: '#7b4e45'
  tertiary: '#006857'
  on-tertiary: '#ffffff'
  tertiary-container: '#00846f'
  on-tertiary-container: '#f4fffa'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#ffdad3'
  primary-fixed-dim: '#ffb4a5'
  on-primary-fixed: '#3f0400'
  on-primary-fixed-variant: '#7b2e1f'
  secondary-fixed: '#ffdad3'
  secondary-fixed-dim: '#f3b9ad'
  on-secondary-fixed: '#32120c'
  on-secondary-fixed-variant: '#653c33'
  tertiary-fixed: '#8cf6db'
  tertiary-fixed-dim: '#6fd9bf'
  on-tertiary-fixed: '#00201a'
  on-tertiary-fixed-variant: '#005143'
  background: '#fff8f6'
  on-background: '#231917'
  surface-variant: '#f1dfdb'
typography:
  display-hero:
    fontFamily: Instrument Serif
    fontSize: 62px
    fontWeight: '400'
    lineHeight: '1.04'
    letterSpacing: -0.01em
  display-lg:
    fontFamily: Instrument Serif
    fontSize: 40px
    fontWeight: '400'
    lineHeight: '1.1'
  display-md:
    fontFamily: Instrument Serif
    fontSize: 30px
    fontWeight: '400'
    lineHeight: '1.1'
  body-lg:
    fontFamily: Work Sans
    fontSize: 15px
    fontWeight: '400'
    lineHeight: '1.55'
  body-md:
    fontFamily: Work Sans
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.55'
  label-sm:
    fontFamily: Work Sans
    fontSize: 11px
    fontWeight: '600'
    lineHeight: '1'
    letterSpacing: 0.1em
  metadata:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: '1'
    letterSpacing: 0.05em
  button-text:
    fontFamily: Work Sans
    fontSize: 13px
    fontWeight: '500'
    lineHeight: '1'
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  container-padding-desktop: 34px
  container-padding-mobile: 22px
  gutter-grid: 24px
  gap-component: 16px
  gap-tight: 8px
  section-margin: 64px
---

## Brand & Style

The design system evokes the "Modern Scholar" persona—a bridge between traditional academic rigor and high-efficiency technical precision. The UI should feel like a "warm study desk," moving away from the sterile, blue-tinted aesthetics of corporate SaaS and toward an environment of focus, sunlight, and paper.

The style is **Corporate Modern with a Tactile twist**. It relies on high-quality typography and a restrained palette to establish authority, while using "physical" interaction metaphors—such as 1px vertical button translations—to provide sensory feedback. The dual-portal architecture maintains a shared DNA while shifting the ambient "temperature" based on the user's role: terracotta for students (energetic, grounded) and teal/earthy brown for teachers (authoritative, archival).

Key Principles:
- **Editorial Hierarchy:** Typography does the heavy lifting for layout.
- **Intentional Density:** Information-rich dashboards remain legible through strict typographic scales.
- **Functional Serenity:** Generous whitespace and off-white bases reduce cognitive load during complex tasks like exam marking.

## Colors

The system utilizes a **semantic token architecture** that adapts based on the `[data-portal]` attribute. While the logic remains consistent, the color values shift to define the user's environment.

### Portal Scoping
- **Student Portal:** Uses a terracotta accent (`primary: #b85c4a`) with a warm neutral base.
- **Teacher Portal:** Uses a teal accent (`tertiary: #008b75`) paired with a deeper archival brown (`secondary: #9c6b61`) for high-contrast actions.

### Semantic Roles
- **Surface & Background:** Layers are built using `surface` (pure containers) and `surface-container` (wells/sidebars) over the `background` base.
- **Ink:** A deep neutral-brown (`#362f2e`) is used for primary teacher CTAs and high-emphasis elements, providing a softer, more integrated dark than pure black.
- **Status:** Status colors (OK, Warn, Err) are implemented in pairs (text + subtle background tint) to ensure accessible contrast without overwhelming the "desk" aesthetic.

## Typography

Typography is the core of the design system's identity, mixing three distinct font families to create a scholarly rhythm.

- **Instrument Serif (Display):** Used for headlines and high-impact metrics. It should always be set with low line-height to maintain a "journal" look.
- **Work Sans (Interface):** The workhorse for all body text, buttons, and navigation. It provides a clean, neutral balance to the serif headings.
- **JetBrains Mono (Data):** Reserved for metadata, exam codes, and technical logs. It conveys precision and transparency in the AI's marking process.

**Sizing Precision:**
Button text utilizes high-precision fractional sizing to optimize information density. Labels and Eyebrows should use `0.1em` tracking to differentiate themselves from body copy.

## Layout & Spacing

The layout follows a **Fixed Grid** philosophy for primary content containers, centered within a fluid viewport.

- **Grid Model:** A 12-column system is used for dashboards, typically with 24px gutters. Sidebars are fixed at 240px–280px.
- **Density:** Components use a tight 4px/8px rhythm. Cards use 20px internal padding to balance density with breathing room.
- **Responsiveness:**
  - **Desktop (1180px+):** Full multi-column dashboard.
  - **Tablet (820px - 1180px):** Sidebar remains visible; grid columns collapse to single or double stacks.
  - **Mobile (<820px):** Sidebar is hidden behind a drawer; horizontal padding reduces to 16px.

## Elevation & Depth

The design system adopts a **"Flat-Plus"** philosophy. Depth is primarily conveyed through tonal layering and borders rather than complex shadows.

- **Tonal Layers:** `surface` containers sit on top of `background`. Sidebars use `surface-container` to create a slight "well" effect.
- **Borders:** 1px solid borders in the `border` color provide the primary containment strategy. Card boundaries are clear and structural.
- **Subtle Glassmorphism:** Sticky headers use a 10px backdrop blur with 80% opacity to maintain context while scrolling.
- **Tactile Interaction:** Buttons do not use shadows on hover; instead, they shift background color and use a `1px` vertical translation (`active:translate-y-px`) to simulate physical depression.

## Shapes

The shape language is "Soft-Square"—rounded enough to be approachable but sharp enough to feel academic.

- **Primary Cards:** Use a `1rem` (16px) radius for a modern, high-end feel.
- **Buttons & Inputs:** Use a consistent `0.5rem` (8px) radius.
- **Status Chips & Meters:** Use `rounded-full` (pill shape) to distinguish them as non-interactive indicators or distinct status markers.
- **Avatars/Dots:** Perfect circles are used for personhood and "Live" status indicators.

## Components

### Buttons
- **Primary:** High-contrast (`tertiary` for Teachers, `primary` for Students). Solid fill, no border.
- **Secondary:** Surface fill with a 1px border.
- **Ghost:** No fill or border; used for secondary actions like "Cancel" or "Edit transcript."
- **Interaction:** All buttons translate 1px down on click.

### Cards
- Standard containers with `1rem` radius and `1px` border.
- Headers inside cards should use `metadata` styling for context (e.g., "PAGE 4") and `display-md` for the title.

### Status Chips
- Pill-shaped with tight internal padding (`3px 9px`).
- Always paired: a subtle background tint and a high-contrast text label of the same hue (Success, Warning, Error).

### Meters (Progress Bars)
- Height: `6px` (`h-1.5`).
- Container uses `surface-container` (muted track); fill uses `primary` or status colors.
- Fully rounded ends.

### Input Fields
- Surface-colored fill with a 1px border that shifts to `primary` on focus.
- 13px text size to match button labels.
