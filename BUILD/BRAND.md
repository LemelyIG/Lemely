# BRAND.md — Lemely brand strategy

> Phase 2, step 1 of REDESIGN-MISSION.md §5. Produced with the `brandkit`
> strategy-first process. **This file is strategy, not a design system.** The
> design system is `DESIGN.md` at the repo root; this file exists to (a) fix the
> brand idea before any pixel is generated and (b) author the Gemini image
> prompts in step 2 so the logo comes out of reasoning rather than out of taste.
>
> The visual direction ("The Study Notebook") is pre-decided in
> REDESIGN-MISSION §4 and is **not** re-opened here. What this file decides is
> the *meaning* the mark carries.

---

## 1. Strategy

| Field | Position |
|---|---|
| **Category** | Exam-preparation and marking platform for CAIE IGCSE / O-Level |
| **Audience** | Students ~14 to 17 (primary, phone-first), their parents (low-frequency, answer-seeking), their teachers (daily, desk-bound, time-poor) |
| **Product function** | You upload a past paper you solved. It marks it against the official mark scheme, names the mark point you dropped, predicts your grade against real boundaries, and turns the gaps into practice. |
| **Emotional promise** | You will know exactly where you stand and exactly what to do next. |
| **Cultural position** | Egyptian private tutoring, where the teacher is the trusted authority and the platform is their instrument. Not a Silicon Valley "AI tutor" replacing anyone. |
| **Trust level** | High and load-bearing. This tells a 16-year-old what grade they are heading for. Overclaiming is the cardinal sin. |
| **What it must avoid** | Feeling like an AI product. Feeling like a toy. Feeling like a corporate SaaS dashboard. Feeling certain when it is not. |

### The brand idea, in one line

> **Lemely marks your paper the way a good teacher would, and shows its working.**

Supporting sentence, for internal alignment: the product's real value is not
automation, it is **honest, specific correction**. A number alone ("34/40")
helps nobody. The value is the note in the margin explaining which mark point
went and why. Everything else in the product exists downstream of that note.

### Personality

Five traits, each with the behaviour that proves it:

1. **Warm.** Addresses a nervous teenager, not a user record. Plain second person.
2. **Exacting.** Cites the mark point. Never rounds a claim up.
3. **Shows its working.** Every mark is traceable to a scheme line and carries a confidence. The product is auditable by a student who disagrees with it.
4. **Calm.** No urgency theatre, no streak guilt, no red-alert dashboards. Exam season supplies the anxiety already.
5. **Encouraging without flattery.** Celebrates a real gain. Does not congratulate someone for logging in.

### Voice test

- Says: "Two marks went on the distance-time gradient. Twelve questions like it are ready."
- Never says: "Unlock your potential." / "AI-powered insights." / "You're crushing it."

---

## 2. Symbol territory

The mark should come from the **act of marking a paper**, not from the category
of education. Education has a graveyard of exhausted symbols and the whole
territory is banned below.

**In territory** (all drawn from the physical artefact the product is about):

| Territory | Why it carries meaning here |
|---|---|
| **The margin rule** | The vertical line down a page's left edge, where the teacher writes. Lemely *is* that margin. This is the strongest single idea available. |
| **The tick** | The one gesture that means "this mark is awarded". The product's atomic action. |
| **Marginalia / the annotation** | The note beside the work, not on top of it. Matches the "we advise, the teacher decides" product stance. |
| **The dog-ear / folded corner** | Return here. Progress kept by hand. Warmth. |
| **Ruled and dotted lines** | The notebook's own structure, usable as construction grid and as pattern. |
| **The stacked sheet** | A paper, then many papers, then a trajectory. |

**Out of territory, hard ban.** These are the clichés that would make the mark
indistinguishable from a thousand ed-tech logos: graduation cap or mortarboard,
open book, pencil or pen nib as the whole mark, lightbulb, owl, brain, atom,
molecule, rocket, sparkles or the four-point AI star, abstract swoosh, globe,
puzzle piece, apple, chat bubble, gradient blob.

---

## 3. Logo concepts, via the five methods

### Concept A — Monogram + meaning: "the L is the margin" **(recommended)**

The letter **L** is already a vertical rule meeting a horizontal one. That is
also, exactly, the corner of a ruled page: the margin line and the baseline.
The mark is a bare `L` drawn at page proportions, with the vertical stroke
slightly overshooting the join, the way a hand-ruled margin overshoots.

Then the single move that makes it a logo rather than a letter: the horizontal
foot lifts at its end into a **tick**. One continuous stroke reads simultaneously
as `L` (the name), as a page margin (the artefact), and as a mark awarded (the
action). Three meanings, one gesture, no added element.

Why this is the pick: it is the only concept where the letterform and the
metaphor are the same shape rather than two things glued together, it survives
at 16px as a favicon, it works as a UI mark, and its vertical rule extends
naturally into a section divider and a pattern.

### Concept B — Product action: the one-stroke tick

The tick alone, drawn with pen pressure: thin on the upstroke, weighted at the
turn, tapering off. Confident but hand-made, never a geometric checkmark from an
icon set. Risk: a bare tick is close to unownable, and it is the most-used mark
in the category. Kept as a candidate mainly because it is the strongest *icon*
even if it is the weakest *trademark*.

### Concept C — Metaphor fusion: margin rule + progress

The vertical margin line, with a short segment of it inked solid, the rest
hairline. Reads as a margin and as a progress meter at once, which is the
product's actual loop (you are this far along the syllabus). Strong system
potential, weaker recognition in isolation.

### Concept D — Negative space: the tick between two sheets

Two overlapping paper rectangles, offset. The gap between them forms the tick.
Highest craft ceiling, highest failure risk: negative-space marks go muddy below
about 24px, and this product needs a favicon.

### Concept E — Construction geometry: built from the ruling

The mark drawn strictly on the notebook's own grid: baseline units for height,
the margin line at the classic one-quarter inset, every angle at 45 degrees or
on the rule. This is less a separate concept than the **construction discipline
applied to A**, and that is how it will be used: as concept A's construction
panel, proving the mark came from the page rather than from a whim.

---

## 4. Direction taken into image generation

- **Primary:** Concept A, in three treatments (weight, overshoot, and tick angle varied).
- **Foil:** Concept D, one render, because if the negative-space version reads at small size it is the more distinctive trademark and that is worth one generation to find out.
- **Wordmark:** "Lemely" set in the display serif chosen in `DESIGN.md`, lowercase, tight tracking, with the mark used as a lockup to its left. Lowercase deliberately: it is a warmer, less institutional read, and it lets the `l` of the wordmark rhyme with the mark's vertical rule.
- **Palette for generation:** ink charcoal on warm bone paper, with exactly one accent. No gradient, no glow, no bevel, flat vector, white or bone background only.
- **Anti-references restated for the prompt:** no mortarboard, no book, no lightbulb, no owl, no sparkle, no swoosh, no gradient, no 3D, no drop shadow, no mascot, no purple-blue AI palette.

## 5. Tagline candidates (for the identity board only, not committed product copy)

- "Know where the marks went."
- "Marked, and shown."
- "The margin, alive."

`Know where the marks went.` is the strongest: it is specific, it is the actual
product benefit, it contains no hype word, and it survives translation.

---

## 6. What this file does not decide

Exact hex values, type faces, spacing, and every component rule are `DESIGN.md`'s
job (step 4 of Phase 2). If this file and `DESIGN.md` ever disagree on a visual
value, `DESIGN.md` wins; if they disagree on *meaning*, this file wins.
