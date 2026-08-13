# ui-ux-pro-max domain queries — Phase 2 research input (Phase 1 pre-run)

> Generated 2026-08-13T16:59:52+03:00 by the orchestrator. **Research input, never a source of
> truth.** REDESIGN-MISSION §3.2 overrides anything here that conflicts: icons are
> Phosphor (not Heroicons/Lucide), no pill buttons, no glassmorphism, no visible
> gradients, light mode only, Nivo for charts.

## domain: typography — `editorial serif display typography for a learning platform`

```
## UI Pro Max Search Results
**Domain:** typography | **Query:** editorial serif display typography for a learning platform
**Source:** typography.csv | **Found:** 4 results

### Result 1
- **Font Pairing Name:** Bold Typography Mobile (Inter-Tight Poster)
- **Category:** Sans + Serif (Display) + Mono
- **Heading Font:** Inter
- **Body Font:** Playfair Display
- **Mood/Style Keywords:** bold typography, editorial, poster, near-black, vermillion, luxury, type-as-hero, manifesto, high-contrast
- **Best For:** Creative brand flagships, reading platforms, event apps, flash pages, luxury mobile experiences
- **Google Fonts URL:** https://fonts.googleapis.com/css2?family=Inter:ital,wght@0,400;0,500;0,600;0,700;0,800;1,400|JetBrains+Mono:wght@400|Playfair+Display:ital@1
- **CSS Import:** @import url('https://fonts.googleapis.com/css2?family=Inter:ital,wght@0,400;0,500;0,600;0,700;0,800;1,400&family=JetBrains+Mono:wght@400&family=Playfair+Display:ital@1&display=swap');
- **Tailwind Config:** fontFamily: { display: ['Inter', 'sans-serif'], quote: ['Playfair Display', 'serif'], mono: ['JetBrains Mono', 'monospace'] }
- **Notes:** Tri-stack: Inter 600–800 for all UI (letterSpacing -1.5px heroes, -0.5px subheads). Playfair Display Italic ONLY for pull quotes. JetBrains Mono for labels and stats. Scale: 12px labels, 16px body, 22px sub, 32px section, 40px H2, 56px H1, 72px Hero Statement. 5:1 ratio H1:Body is mandatory. lineHeight 1.1 headlines, 1.6 body. Underlines (2–3pt accent) replace buttons for interactions.

### Result 2
- **Font Pairing Name:** Minimalist Monochrome Editorial
- **Category:** Serif + Serif + Mono (Triple Stack)
- **Heading Font:** Playfair Display
- **Body Font:** Source Serif 4
- **Mood/Style Keywords:** monochrome, editorial, austere, typographic, pocket manifesto, luxury, high contrast, brutalist mobile
- **Best For:** Luxury fashion mobile apps, editorial publications, digital exhibitions, portfolio apps, high-contrast e-reader aesthetics
- **Google Fonts URL:** https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400|Source+Serif+4:ital,wght@0,300;0,400;0,600;1,300
- **CSS Import:** @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400&family=Source+Serif+4:ital,wght@0,300;0,400;0,600;1,300&display=swap');
- **Tailwind Config:** fontFamily: { display: ['Playfair Display', 'serif'], body: ['Source Serif 4', 'serif'], mono: ['JetBrains Mono', 'monospace'] }
- **Notes:** Triple stack: Playfair Display 900 tracking-tighter leading-[0.9] for heroes (text-5xl–text-6xl breaks words graphically). Source Serif 4 300–600 for body legibility. JetBrains Mono 400–500 uppercase tracking-widest for tags/dates/labels. NO UI sans-serif — 100% serif/mono.

### Result 3
- **Font Pairing Name:** Classic Elegant
- **Category:** Serif + Sans
- **Heading Font:** Playfair Display
- **Body Font:** Inter
- **Mood/Style Keywords:** elegant, luxury, sophisticated, timeless, premium, editorial
- **Best For:** Luxury brands, fashion, spa, beauty, editorial, magazines, high-end e-commerce
- **Google Fonts URL:** https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Playfair+Display:wght@400;500;600;700&display=swap
- **CSS Import:** @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Playfair+Display:wght@400;500;600;700&display=swap');
- **Tailwind Config:** fontFamily: { serif: ['Playfair Display', 'serif'], sans: ['Inter', 'sans-serif'] }
- **Notes:** High contrast between elegant heading and clean body. Perfect for luxury/premium.

### Result 4
- **Font Pairing Name:** Kids/Education
- **Category:** Display + Sans
- **Heading Font:** Baloo 2
- **Body Font:** Comic Neue
- **Mood/Style Keywords:** kids, education, playful, friendly, colorful, learning
- **Best For:** Children's apps, educational games, kid-friendly content
- **Google Fonts URL:** https://fonts.googleapis.com/css2?family=Baloo+2:wght@400;500;600;700&family=Comic+Neue:wght@300;400;700&display=swap
- **CSS Import:** @import url('https://fonts.googleapis.com/css2?family=Baloo+2:wght@400;500;600;700&family=Comic+Neue:wght@300;400;700&display=swap');
- **Tailwind Config:** fontFamily: { display: ['Baloo 2', 'sans-serif'], sans: ['Comic Neue', 'sans-serif'] }
- **Notes:** Fun, playful fonts for children. Comic Neue is readable comic style.

```

## domain: color — `warm paper off-white monochrome muted pastel palette`

```
## UI Pro Max Search Results
**Domain:** color | **Query:** warm paper off-white monochrome muted pastel palette
**Source:** colors.csv | **Found:** 4 results

### Result 1
- **Product Type:** Portfolio/Personal
- **Primary:** #18181B
- **On Primary:** #FFFFFF
- **Secondary:** #3F3F46
- **On Secondary:** #FFFFFF
- **Accent:** #2563EB
- **On Accent:** #FFFFFF
- **Background:** #FAFAFA
- **Foreground:** #09090B
- **Card:** #FFFFFF
- **Card Foreground:** #09090B
- **Muted:** #E8ECF0
- **Muted Foreground:** #64748B
- **Border:** #E4E4E7
- **Destructive:** #DC2626
- **On Destructive:** #FFFFFF
- **Ring:** #18181B
- **Notes:** Monochrome + blue accent

### Result 2
- **Product Type:** Bakery/Cafe
- **Primary:** #92400E
- **On Primary:** #FFFFFF
- **Secondary:** #B45309
- **On Secondary:** #FFFFFF
- **Accent:** #92400E
- **On Accent:** #FFFFFF
- **Background:** #FEF3C7
- **Foreground:** #78350F
- **Card:** #FFFFFF
- **Card Foreground:** #78350F
- **Muted:** #EDEEF0
- **Muted Foreground:** #64748B
- **Border:** #FDE68A
- **Destructive:** #DC2626
- **On Destructive:** #FFFFFF
- **Ring:** #92400E
- **Notes:** Warm brown + cream white [Accent adjusted from #F8FAFC for WCAG 3:1]

### Result 3
- **Product Type:** Photography Studio
- **Primary:** #18181B
- **On Primary:** #FFFFFF
- **Secondary:** #27272A
- **On Secondary:** #FFFFFF
- **Accent:** #F8FAFC
- **On Accent:** #0F172A
- **Background:** #000000
- **Foreground:** #FAFAFA
- **Card:** #0C0C0C
- **Card Foreground:** #FAFAFA
- **Muted:** #181818
- **Muted Foreground:** #94A3B8
- **Border:** #3F3F46
- **Destructive:** #EF4444
- **On Destructive:** #FFFFFF
- **Ring:** #18181B
- **Notes:** Pure black + white contrast

### Result 4
- **Product Type:** Space Tech / Aerospace
- **Primary:** #F8FAFC
- **On Primary:** #0F172A
- **Secondary:** #94A3B8
- **On Secondary:** #0F172A
- **Accent:** #3B82F6
- **On Accent:** #FFFFFF
- **Background:** #0B0B10
- **Foreground:** #F8FAFC
- **Card:** #1E1E23
- **Card Foreground:** #F8FAFC
- **Muted:** #232328
- **Muted Foreground:** #94A3B8
- **Border:** #1E293B
- **Destructive:** #EF4444
- **On Destructive:** #FFFFFF
- **Ring:** #F8FAFC
- **Notes:** Star white + launch blue

```

## domain: ux — `student dashboard empty states onboarding error handling`

```
## UI Pro Max Search Results
**Domain:** ux | **Query:** student dashboard empty states onboarding error handling
**Source:** ux-guidelines.csv | **Found:** 4 results

### Result 1
- **Category:** Feedback
- **Issue:** Empty States
- **Platform:** All
- **Description:** Guide users when no content exists
- **Do:** Show helpful message and action
- **Don't:** Blank empty screens
- **Code Example Good:** No items yet. Create one!
- **Code Example Bad:** Empty white space
- **Severity:** Medium

### Result 2
- **Category:** Accessibility
- **Issue:** Error Messages
- **Platform:** All
- **Description:** Error messages must be announced
- **Do:** Use aria-live or role=alert for errors
- **Don't:** Visual-only error indication
- **Code Example Good:** role='alert'
- **Code Example Bad:** Red border only
- **Severity:** High

### Result 3
- **Category:** Responsive
- **Issue:** Table Handling
- **Platform:** Web
- **Description:** Tables can overflow on mobile
- **Do:** Use horizontal scroll or card layout
- **Don't:** Wide tables breaking layout
- **Code Example Good:** overflow-x-auto wrapper
- **Code Example Bad:** Table overflows viewport
- **Severity:** Medium

### Result 4
- **Category:** Onboarding
- **Issue:** User Freedom
- **Platform:** All
- **Description:** Users should be able to skip tutorials
- **Do:** Provide Skip and Back buttons
- **Don't:** Force linear unskippable tour
- **Code Example Good:** Skip Tutorial button
- **Code Example Bad:** Locked overlay until finished
- **Severity:** Medium

```

## domain: gsap — `calm stagger reveal micro interaction celebration`

```
## UI Pro Max Search Results
**Domain:** gsap | **Query:** calm stagger reveal micro interaction celebration
**Source:** motion.csv | **Found:** 4 results

### Result 1
- **Category:** Stagger List
- **Intensity Tier:** Complex
- **Trigger:** load or scroll
- **Duration:** 400-700ms
- **Easing:** expo.out
- **GSAP Snippet:** const split = new SplitText(headline, { type: 'chars' }); gsap.from(split.chars, { opacity: 0, y: 20, rotateX: -40, duration: 0.6, stagger: 0.015, ease: 'expo.out' });
- **Framework Notes:** SplitText is a GSAP Club/paid plugin; confirm license before shipping and provide a plain fade fallback if unavailable
- **Do:** Revert SplitText on unmount/cleanup (split.revert()) to restore original text nodes for accessibility tools
- **Don't:** Don't split-animate long paragraphs; reserve for short headlines (under ~8 words)
- **Performance Notes:** Splitting text creates one element per character; keep it to headline-length copy only for DOM size

### Result 2
- **Category:** Hover Micro-interaction
- **Intensity Tier:** Subtle
- **Trigger:** hover
- **Duration:** 150-200ms
- **Easing:** power1.out
- **GSAP Snippet:** gsap.to(el, { y: -1, opacity: 0.9, duration: 0.15, ease: 'power1.out' });
- **Framework Notes:** Bind on mouseenter/mouseleave; in React wrap in a ref + useEffect (or onMouseEnter/onMouseLeave props directly calling gsap.to)
- **Do:** Keep displacement under 2px so it reads as feedback not motion
- **Don't:** Don't animate layout-affecting props (width/height/margin) on hover
- **Performance Notes:** Runs on transform/opacity only so it stays on the compositor thread

### Result 3
- **Category:** Hover Micro-interaction
- **Intensity Tier:** Standard
- **Trigger:** hover
- **Duration:** 200-300ms
- **Easing:** power2.out
- **GSAP Snippet:** gsap.to(el, { y: -4, scale: 1.02, boxShadow: '0 12px 24px rgba(0,0,0,0.12)', duration: 0.25, ease: 'power2.out' });
- **Framework Notes:** Use gsap.quickTo(el, 'y') for cards with many hover targets to avoid re-creating tweens every event
- **Do:** Pair with a matching mouseleave tween that reverses the same properties
- **Don't:** Don't leave the hover state stuck if the pointer leaves fast; always attach the reverse tween
- **Performance Notes:** quickTo() avoids GC churn on lists with 20+ hoverable cards

### Result 4
- **Category:** Hover Micro-interaction
- **Intensity Tier:** Complex
- **Trigger:** hover + mousemove
- **Duration:** 300-500ms
- **Easing:** elastic.out(1,0.4)
- **GSAP Snippet:** const xTo = gsap.quickTo(el, 'x', { duration: 0.4, ease: 'elastic.out(1,0.4)' }); const yTo = gsap.quickTo(el, 'y', { duration: 0.4, ease: 'elastic.out(1,0.4)' }); el.addEventListener('mousemove', (e) => { const r = el.getBoundingClientRect(); xTo((e.clientX - r.left - r.width/2) * 0.3); yTo((e.clientY - r.top - r.height/2) * 0.3); });
- **Framework Notes:** Debounce is not needed since quickTo interpolates; remove listeners on component unmount in React/Vue to avoid leaks
- **Do:** Clamp the pull strength (e.g. * 0.3) so the element never fully leaves its hit box
- **Don't:** Don't apply magnetic effect to more than 1-2 focal elements per screen; it becomes noisy
- **Performance Notes:** Use will-change: transform on the target element for smoother compositing

```

## domain: chart — `student progress over time grade distribution`

```
## UI Pro Max Search Results
**Domain:** chart | **Query:** student progress over time grade distribution
**Source:** charts.csv | **Found:** 4 results

### Result 1
- **Data Type:** Trend Over Time
- **Keywords:** trend, time-series, line, growth, timeline, progress
- **Best Chart Type:** Line Chart
- **Secondary Options:** Area Chart, Smooth Area
- **When to Use:** Data has a time axis; user needs to observe rise/fall trends or rate of change over a continuous period
- **When NOT to Use:** Fewer than 4 data points (use stat card); more than 6 series (visual noise); no time dimension exists
- **Data Volume Threshold:** <1000 pts: SVG; ≥1000 pts: Canvas + downsampling; >10000: aggregate to intervals
- **Color Guidance:** Primary: #0080FF. Multiple series: distinct colors + distinct line styles. Fill: 20% opacity
- **Accessibility Grade:** AA
- **Accessibility Notes:** Differentiate series by line style (solid/dashed/dotted) not color alone. Add pattern overlays for colorblind users.
- **A11y Fallback:** Dashed/dotted lines per series; togglable data table with timestamps and values
- **Library Recommendation:** Chart.js, Recharts, ApexCharts
- **Interactive Level:** Hover + Zoom

### Result 2
- **Data Type:** Proportional / Percentage
- **Keywords:** waffle, percentage, proportion, progress, filled, grid
- **Best Chart Type:** Waffle Chart
- **Secondary Options:** Pictogram, Stacked Bar 100%
- **When to Use:** Showing what fraction of a whole is filled; percentage progress in a visually engaging and accessible format
- **When NOT to Use:** More than 5 categories (use stacked bar); exact values matter over visual proportion; very tight space
- **Data Volume Threshold:** 10×10 grid standard (100 cells); for > 5 categories switch to stacked 100% bar
- **Color Guidance:** 3–5 categories max. 2–3px gap between cells. Each category a distinct accessible color pair
- **Accessibility Grade:** AA
- **Accessibility Notes:** Better than pie for accessibility. Percentage text label always visible. Each cell has aria-label.
- **A11y Fallback:** Percentage text always visible; grid cells labeled with aria-label value; provide legend
- **Library Recommendation:** D3.js, React-Waffle, Custom CSS Grid
- **Interactive Level:** Hover

### Result 3
- **Data Type:** Distribution / Statistical
- **Keywords:** distribution, statistical, spread, median, outlier, quartile, boxplot
- **Best Chart Type:** Box Plot
- **Secondary Options:** Violin Plot, Beeswarm
- **When to Use:** Showing spread, median, and outliers of a dataset; comparing distributions across multiple groups
- **When NOT to Use:** Fewer than 20 data points per group (distribution is not meaningful); audience unfamiliar with statistical charts
- **Data Volume Threshold:** Any sample size; aggregated representation so rendering is ⚡ Excellent at any volume
- **Color Guidance:** Box fill: #BBDEFB. Border: #1976D2. Median line: #D32F2F bold. Outlier dots: #F44336
- **Accessibility Grade:** AA
- **Accessibility Notes:** Include stats summary table. Annotate outlier count in chart subtitle.
- **A11y Fallback:** Stats summary table (min / Q1 / median / Q3 / max / mean); outlier count annotation
- **Library Recommendation:** Plotly, D3.js, Chart.js (plugin)
- **Interactive Level:** Hover

### Result 4
- **Data Type:** Correlation / Distribution
- **Keywords:** correlation, distribution, scatter, relationship, pattern, cluster
- **Best Chart Type:** Scatter Plot or Bubble Chart
- **Secondary Options:** Heat Map, Matrix
- **When to Use:** Exploring relationship between two continuous variables; identifying clusters or outliers in a dataset
- **When NOT to Use:** Variables are categorical (use grouped bar); fewer than 20 points (patterns aren't meaningful); mobile-primary context
- **Data Volume Threshold:** <500 pts: SVG; 500–5000: Canvas at 0.6–0.8 opacity; >5000: hexbin or aggregate first
- **Color Guidance:** Color axis: gradient (blue → red). Bubble size: relative to 3rd variable. Opacity: 0.6–0.8 to show density
- **Accessibility Grade:** B
- **Accessibility Notes:** Provide data table alternative. Combine color + shape distinction for colorblind users.
- **A11y Fallback:** Data table with correlation coefficient annotation; shape markers (circle/square/triangle) per group
- **Library Recommendation:** D3.js, Plotly, Recharts
- **Interactive Level:** Hover + Brush

```

## domain: icons — `consistent icon set for an education product`

```
## UI Pro Max Search Results
**Domain:** icons | **Query:** consistent icon set for an education product
**Source:** icons.csv | **Found:** 4 results

### Result 1
- **Category:** Guideline
- **Icon Name:** icon-fallback-rules
- **Keywords:** icon fallback, phosphor, heroicons, any icon, extended set
- **Library:** Phosphor (primary) + Heroicons (fallback)
- **Import Code:** Primary: import { IconName } from '@phosphor-icons/react'. Fallback: import { IconName } from '@heroicons/react/24/outline' or '@heroicons/react/24/solid'.
- **Usage:** 当默认列表中没有合适图标时：优先继续从 Phosphor 中选择任何语义更贴切的图标（不必局限于本表列出的图标）。若 Phosphor 也无合适图标，可以改用 Heroicons，并在 UI 代码中保持风格统一（线性或填充、圆角程度、笔画粗细等）。
- **Best For:** Icon library strategy and fallback rules
- **Style:** Outline

### Result 2
- **Category:** Style Config
- **Icon Name:** cyberpunk-icon-system
- **Keywords:** cyberpunk, neon, glow, hud, phosphor, weight regular, accent glow, dark, angular, react native
- **Library:** Phosphor (react-native)
- **Import Code:** import { Lightning } from 'phosphor-react-native'
- **Usage:** <Lightning size={24} weight="regular" color={colors.accent} />
- **Best For:** Cyberpunk Mobile HUD style: weight="regular", color={colors.accent} (#00FF88 Matrix Green). Wrap every icon in a View with shadowColor: colors.accent / shadowOpacity: 0.6 / shadowRadius: 8 to simulate neon glow. Use borderRadius: 0 on wrapper. Avoid rounded icon containers. Always pair icon with data label in JetBrains Mono.
- **Style:** Outline

### Result 3
- **Category:** Style Config
- **Icon Name:** academia-icon-system
- **Keywords:** academia, library, brass, ornate, phosphor, weight thin, muted warm, scholarly, mobile
- **Library:** Phosphor (react-native)
- **Import Code:** import { BookOpen } from 'phosphor-react-native'
- **Usage:** <BookOpen size={22} weight="thin" color={colors.brass} />
- **Best For:** Academia (Scholarly Mobile) style: weight="thin" (thin engraved feel), color={colors.brass} (#C9A962). No sharp geometric or tech-inspired icons. Prefer book, scroll, key, quill-type icon metaphors. Wrap in circular View with 1px brass border. Avoid neon or saturated colored icons. All icon-only navigation must have an accessibilityLabel.
- **Style:** Outline

### Result 4
- **Category:** Style Config
- **Icon Name:** bold-typography-icon-system
- **Keywords:** bold typography, editorial, mono label, phosphor, weight regular, minimal, icon+label required, size 20–32
- **Library:** Phosphor (react-native)
- **Import Code:** import { ArrowRight } from 'phosphor-react-native'
- **Usage:** <ArrowRight size={20} weight="regular" color={colors.accent} />
- **Best For:** Bold Typography Mobile style: weight="regular". Size 20px for UI controls, 32px for feature anchors. Icons MUST be paired with a Mono-stack text label (JetBrains Mono). Standalone icons only allowed for standard navigation (e.g., Back arrow). Accent color #FF3D00 only.
- **Style:** Outline

```

## stack: react
```
## UI Pro Max Stack Guidelines
**Stack:** react | **Query:** design system tokens components
**Source:** stacks/react.csv | **Found:** 3 results

### Result 1
- **Category:** TypeScript
- **Guideline:** Use generics for reusable components
- **Description:** Generic components for flexible typing
- **Do:** Generic props for list components
- **Don't:** Union types for flexibility
- **Code Good:** <List<T> items={T[]}>
- **Code Bad:** <List items={any[]}>
- **Severity:** Medium
- **Docs URL:** 

### Result 2
- **Category:** Components
- **Guideline:** Keep components small and focused
- **Description:** Single responsibility for each component
- **Do:** One concern per component
- **Don't:** Large multi-purpose components
- **Code Good:** <UserAvatar /><UserName />
- **Code Bad:** <UserCard /> with 500 lines
- **Severity:** Medium
- **Docs URL:** 

### Result 3
- **Category:** Patterns
- **Guideline:** Compound components
- **Description:** Related components sharing state
- **Do:** Tab + TabPanel sharing context
- **Don't:** Prop drilling between related
- **Code Good:** <Tabs><Tab/><TabPanel/></Tabs>
- **Code Bad:** <Tabs tabs={[]} panels={[...]}/>
- **Severity:** Low
- **Docs URL:** 

```

## stack: html-tailwind
```
## UI Pro Max Stack Guidelines
**Stack:** html-tailwind | **Query:** design system tokens components
**Source:** stacks/html-tailwind.csv | **Found:** 1 results

### Result 1
- **Category:** Colors
- **Guideline:** Semantic colors
- **Description:** Use semantic color naming in config
- **Do:** primary secondary danger success
- **Don't:** Generic color names in components
- **Code Good:** bg-primary
- **Code Bad:** bg-blue-500 everywhere
- **Severity:** Medium
- **Docs URL:** 

```

## stack: shadcn
```
## UI Pro Max Stack Guidelines
**Stack:** shadcn | **Query:** design system tokens components
**Source:** stacks/shadcn.csv | **Found:** 3 results

### Result 1
- **Category:** Customization
- **Guideline:** Create custom components
- **Description:** Build new components following shadcn patterns
- **Do:** Use cn() and cva for custom components
- **Don't:** Different patterns for custom
- **Code Good:** const Custom = ({ className }) => <div className={cn("base" className)}>
- **Code Bad:** const Custom = ({ style }) => <div style={style}>
- **Severity:** Medium
- **Docs URL:** 

### Result 2
- **Category:** Components
- **Guideline:** Prefer compound components
- **Description:** Use provided sub-components for complex UI
- **Do:** Card + CardHeader + CardContent pattern
- **Don't:** Single component with many props
- **Code Good:** <Card><CardHeader><CardTitle>
- **Code Bad:** <Card title="x" content="y" footer="z">
- **Severity:** Medium
- **Docs URL:** https://ui.shadcn.com/docs/components/card

### Result 3
- **Category:** Setup
- **Guideline:** Configure path aliases
- **Description:** Set up proper import aliases in tsconfig and components.json
- **Do:** Use @/components/ui path aliases
- **Don't:** Relative imports like ../../components
- **Code Good:** import { Button } from "@/components/ui/button"
- **Code Bad:** import { Button } from "../../components/ui/button"
- **Severity:** Medium
- **Docs URL:** https://ui.shadcn.com/docs/installation

```

