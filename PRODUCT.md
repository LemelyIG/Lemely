# Product

## Register

product

## Users

Two primary users, often the same person in different moments:

- **Teachers / tutors** marking CAIE student papers at their desk. They need speed and accuracy: parse a mark scheme, correct a paper, see where the student struggled, save the result. Context is a desktop at school or home, focus mode, task-oriented.
- **Students reviewing their own work**, either self-marking practice papers or reading feedback from a teacher. Context is more personal — checking results, understanding gaps, planning what to study next. They can feel anxious about low grades.

Both users care deeply about accuracy. A wrong grade or unfair marking is worse than slow software.

## Product Purpose

Lemely automates CAIE exam paper correction with accuracy as the primary value. It parses official mark schemes (PDF → JSON), extracts student answers from scanned papers via Gemini vision, marks MCQ deterministically and theory questions with AI assistance, detects weaknesses by topic, predicts grades, and generates targeted practice quizzes.

Success: a teacher can correct 30 papers in the time it used to take to correct 5, with confidence the marking is defensibly accurate.

## Brand Personality

Warm · Encouraging · Supportive

Voice of a knowledgeable teaching companion — precise about marks but never cold about a student's performance. Accuracy is non-negotiable, but how results are presented matters. "You scored 14/20 — strong on kinematics, let's work on waves" is better than a naked percentage.

## Anti-references

- Academic/institutional aesthetics: Times New Roman, university portal grays, government-form layouts
- Generic SaaS dashboards: navy blue hero, metric cards with gradient shadows, the HubSpot/Salesforce template
- Consumer edtech gamification: Duolingo-style emojis-as-UI, confetti, bright primary colours, cheerleader copy

## Design Principles

1. **Numbers serve people, not the reverse.** Every metric displayed should connect to a human action or next step. Never show a number without context for what to do with it.
2. **Encourage forward.** Results show what to work on next, not just what went wrong. Weakness = opportunity.
3. **Clarity over completeness.** The most important information is visible immediately; details are one level down (accordions, modals, JSON views).
4. **Warmth in precision.** Be accurate AND kind. Feedback is about the work, not the student's worth.
5. **Honest about AI.** Always distinguish deterministic marking (🔢) from AI-assisted (🤖) from missing (❓). Trust is built through transparency.

## Accessibility & Inclusion

- WCAG AA as baseline (contrast ratios ≥ 4.5:1 for text)
- Students under exam stress: avoid red-heavy error states; prefer amber/neutral for "needs attention"
- Light mode as default (varied ambient environments — classrooms, home desks, libraries)
