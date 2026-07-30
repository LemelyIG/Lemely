# Design

## Theme

Light mode. Warm off-white base, muted terracotta/coral as the single accent. Feels like
a well-lit study desk, not a clinical dashboard or a startup SaaS product.

Scene: a teacher correcting papers on a Sunday afternoon, or a student checking their
mock exam results on a laptop. Ambient: daylight or good artificial light.

Color strategy: **Restrained** — tinted neutrals carry the base; one saturated accent
(terracotta coral) handles all interactive elements. The accent appears on ≤10% of any
given surface.

## Colors

All values in OKLCH. Never use raw `#000` or `#fff`.

| Role | OKLCH | Usage |
|---|---|---|
| `accent` | `oklch(0.62 0.13 35)` | Primary buttons, active tabs, focus rings, links |
| `accent-hover` | `oklch(0.57 0.13 35)` | Button hover / active state |
| `accent-subtle` | `oklch(0.94 0.04 35)` | Chip backgrounds, soft highlights |
| `bg` | `oklch(0.97 0.007 40)` | Page background |
| `surface` | `oklch(0.995 0.003 40)` | Card / panel backgrounds |
| `border` | `oklch(0.87 0.006 40)` | Dividers, input borders |
| `text-primary` | `oklch(0.20 0.02 35)` | Body text, headings |
| `text-secondary` | `oklch(0.48 0.018 35)` | Labels, captions, metadata |
| `text-placeholder` | `oklch(0.65 0.01 35)` | Input placeholders, empty states |
| `success` | `oklch(0.52 0.12 150)` | Pass states, "✓ Parsed" badges |
| `warning` | `oklch(0.62 0.11 70)` | Needs attention, low confidence |
| `error` | `oklch(0.52 0.14 20)` | Validation errors (NOT for low grades) |

### Gradio theme implementation

```python
import gradio as gr

theme = gr.themes.Soft(
    primary_hue=gr.themes.colors.orange,
    neutral_hue=gr.themes.colors.stone,
    font=gr.themes.GoogleFont("Inter"),
).set(
    # Backgrounds
    body_background_fill="oklch(0.97 0.007 40)",
    background_fill_primary="oklch(0.995 0.003 40)",
    background_fill_secondary="oklch(0.96 0.006 40)",
    # Borders
    border_color_primary="oklch(0.87 0.006 40)",
    # Text
    body_text_color="oklch(0.20 0.02 35)",
    body_text_color_subdued="oklch(0.48 0.018 35)",
    # Buttons — primary
    button_primary_background_fill="oklch(0.62 0.13 35)",
    button_primary_background_fill_hover="oklch(0.57 0.13 35)",
    button_primary_text_color="oklch(0.99 0.003 40)",
    button_primary_border_color="oklch(0.62 0.13 35)",
    # Buttons — secondary
    button_secondary_background_fill="oklch(0.99 0.003 40)",
    button_secondary_background_fill_hover="oklch(0.94 0.04 35)",
    button_secondary_border_color="oklch(0.87 0.006 40)",
    button_secondary_text_color="oklch(0.20 0.02 35)",
    # Inputs
    input_background_fill="oklch(0.99 0.003 40)",
    input_border_color="oklch(0.87 0.006 40)",
    input_border_color_focus="oklch(0.62 0.13 35)",
    # Links
    link_text_color="oklch(0.55 0.13 35)",
    link_text_color_hover="oklch(0.48 0.13 35)",
    link_text_color_active="oklch(0.48 0.13 35)",
    # Block labels
    block_label_text_color="oklch(0.48 0.018 35)",
    block_label_background_fill="oklch(0.96 0.006 40)",
)
```

### Custom CSS (pass to `gr.Blocks(css=...)`)

```css
/* Header */
.lemely-header {
    padding: 1.5rem 0 1rem;
    border-bottom: 1px solid oklch(0.87 0.006 40);
    margin-bottom: 1rem;
}
.lemely-header h1 {
    font-size: 1.5rem;
    font-weight: 700;
    color: oklch(0.20 0.02 35);
    margin: 0 0 0.25rem;
    letter-spacing: -0.02em;
}
.lemely-header p {
    font-size: 0.875rem;
    color: oklch(0.48 0.018 35);
    margin: 0;
}

/* Status badges */
.badge-parsed {
    display: inline-block;
    background: oklch(0.90 0.07 150);
    color: oklch(0.32 0.10 150);
    font-size: 0.75rem;
    font-weight: 600;
    padding: 0.15em 0.5em;
    border-radius: 4px;
}
.badge-unparsed {
    display: inline-block;
    background: oklch(0.93 0.04 70);
    color: oklch(0.40 0.10 70);
    font-size: 0.75rem;
    font-weight: 600;
    padding: 0.15em 0.5em;
    border-radius: 4px;
}

/* Marker source badges in question breakdown */
.marker-deterministic { color: oklch(0.42 0.11 230); font-weight: 600; }
.marker-ai { color: oklch(0.55 0.13 35); font-weight: 600; }
.marker-missing { color: oklch(0.55 0.10 20); font-weight: 600; }

/* Encourage positive framing on grade display */
.grade-display {
    font-size: 2rem;
    font-weight: 700;
    color: oklch(0.62 0.13 35);
    line-height: 1;
}

/* Token counter — subtle, right-aligned */
.token-counter {
    font-size: 0.75rem;
    color: oklch(0.65 0.01 35);
    text-align: right;
    font-variant-numeric: tabular-nums;
}

/* Reduce visual weight of code/log blocks */
.gradio-container .gr-code {
    background: oklch(0.96 0.006 40) !important;
    border: 1px solid oklch(0.87 0.006 40) !important;
    font-size: 0.8125rem !important;
}

/* Tab active indicator uses accent */
.tab-nav button.selected {
    border-bottom-color: oklch(0.62 0.13 35) !important;
    color: oklch(0.62 0.13 35) !important;
    font-weight: 600 !important;
}
```

## Typography

Font: **Inter** (via Google Fonts, Gradio's `gr.themes.GoogleFont("Inter")`)

| Level | Size | Weight | Usage |
|---|---|---|---|
| App title | 1.5rem | 700 | `.lemely-header h1` |
| Tab heading | 1rem | 600 | Inside tab content |
| Section label | 0.875rem | 600 | Component labels |
| Body | 0.9375rem | 400 | Descriptions, paragraph text |
| Caption/meta | 0.8125rem | 400 | Token counters, timestamps, captions |
| Code/log | 0.8125rem | 400 | Event logs, JSON dumps |

Line lengths: cap markdown/body at 70ch. Dataframes and code blocks can be wider.

## Components and Patterns

### Primary actions
Use `variant="primary"` only for the first action the user should take in a workflow.
Subsequent actions in the same flow are `variant="secondary"`. Never more than one
primary button visible at the same time in a given workflow section.

Workflow sequence for "Correct a Paper": Extract (primary) → Grade (secondary until
answers are loaded, then becomes the natural next step — leave as secondary, let
the user see the extracted answers first).

### Data display priority
1. Key metric in text/markdown (grade, total marks, percentage)
2. Table for structured data (per-question breakdown, history records)
3. Accordion for raw JSON — never default-expanded

### Empty states
Every tab that can be empty should have an explicit, encouraging empty state:
- Library with no parsed schemes: "No mark schemes parsed yet. Upload PDFs to Sources/ and click Parse."
- Past Results with no history: "No papers recorded yet. Use 'correct-paper --record' or the Correct a Paper tab with Save."
- Quiz with no weaknesses: "Grade a paper first to identify weak areas, then come back here for targeted practice."

### Event logs (Live Activity)
Keep the `gr.Code` event log component in tabs that do AI work (Tab 2, Tab 3).
For non-AI tabs (Library parse, Past Results, Quiz), use a simpler `gr.Textbox` status.
Label: "Activity" not "Event log".

### Error handling
Never show raw exception tracebacks. Catch and show:
- For network/AI errors: "Couldn't reach Gemini. Check your API key and connection."
- For parse errors: "This file couldn't be parsed. Try with Gemini parsing enabled."
- For empty inputs: Surface as disabled buttons (don't let the user click into failure).

## Layout

### Tab structure
```
Lemely [header]
├── Library         — browse + parse mark schemes
├── Correct a Paper — main workflow (scan → extract → grade → save)
├── Subject Result  — aggregate papers into final grade
├── Past Results    — student history browser
├── Quiz            — weakness-driven practice questions
└── Settings        — read-only config display
```

### Two-column layout (Tabs 2 & 3)
- Main column: `scale=3` — primary workflow
- Activity column: `scale=2` — live log + token counter

Single-column for all other tabs (Library, Past Results, Quiz, Settings) — they don't
need a live activity sidebar.

### Spacing rhythm
- Between major sections within a tab: 1.5rem gap (use `gr.HTML("<div style='height:1.5rem'></div>")` if needed or rely on Gradio's default row gaps)
- Don't add wrappers around everything — let Gradio's natural layout breathe

## Content / Copy

Principles from PRODUCT.md applied to labels:
- Buttons: imperative verbs ("Extract answers", "Grade", "Load history", "Generate quiz")
- Labels: lower-case, specific ("mark scheme", "scanned paper", "student ID", "weekly hours")
- Empty states: action-oriented, never "no data found"
- Avoid: "Please", "N/A", "undefined", raw error class names

Grade display framing: show grade + percentage + a brief forward-looking nudge
("A — 87%. Strong overall. Review mechanics for full marks next time.")
Never just a bare letter grade without context.

Marking source legend (always include when showing per-question results):
```
🔢 deterministic  🤖 AI-assisted  ❓ not marked
```
