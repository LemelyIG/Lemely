# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Register

product

## Users

Five confirmed roles. Every surface is designed for the role it actually serves — student and teacher are the two portals built today (`web/src/portals/`), parent lands in Phase 3, and the two admin roles are real accounts with real screens, not implementation details.

- **Students (IGCSE / O-Level / AS / A-Level, launching in Egypt).** Photograph or upload an attempted past paper, get it marked, find out what to study next. Personal context — phone or laptop, often at home, often anxious about the result. A student may hold a school seat, a personal subscription, or both.
- **Teachers / tutors** marking CAIE papers at their desk. Independent, employed by a school, or both. They need speed and defensible accuracy: parse a mark scheme, correct a paper, see where a class struggled, override a marking the system got wrong. Desktop, focus mode, task-oriented.
- **Parents** checking on a linked child. Phone-OTP login, read-only performance and weakness views, notification preferences. Lowest tolerance for jargon, least frequent visits, mobile-first.
- **School admins** managing a school's seats, invited student accounts, and school-wide announcements.
- **Platform admins** activating accounts (activation is a manual toggle while payments are out of scope) and holding cross-tenant visibility.

Both students and teachers care deeply about accuracy. A wrong grade or unfair marking is worse than slow software.

## Product Purpose

Lemely marks CAIE exam papers automatically, with accuracy as the primary value. A student photographs or uploads a handwritten attempted past paper; Lemely detects the paper's identity (subject code, session, year, variant, paper number), parses the official mark scheme, extracts the handwritten answers, marks them with method-mark awareness (partial credit for working), applies the real per-paper-variant grade boundaries, and returns per-question marks, a letter and numerical grade, a predicted grade, the mistakes, the weak topics, and the trend against past attempts.

Around that core loop sit role dashboards, AI content generation (topic-targeted practice, flashcards, teacher quizzes), adaptive study plans, and an engagement layer.

Success: a teacher corrects 30 papers in the time it used to take to correct 5, with confidence the marking is defensibly accurate; a student learns what to do next, not just what they scored.

## Positioning

Three things a neighboring product could not truthfully copy:

1. **Method-mark awareness.** Marking is not answer-matching. Partial credit is awarded against the mark scheme's method marks, the way a human examiner does it.
2. **The system knows when it doesn't know.** Every marking and extraction operation emits a per-question and per-paper confidence value; low-confidence results are flagged into a human-review queue surfaced to teachers. The standard the product holds itself to: ≥99% MCQ agreement, ≥95% mark-level agreement on structured questions, and 100% of disagreements carrying confidence below the review threshold.
3. **Real boundaries, not a formula.** Grade prediction is an exact lookup against scraped historical per-paper-variant thresholds, with provenance. Where no exact entry exists the fallback is a per-subject historical average, and the result is surfaced as "estimated" — never silently.

## Operating Context

- **The artifact is paper.** Handwritten answers on a physical past paper, captured by phone camera (multi-page PDF assembled client-side) or uploaded as a file. Scans are skewed, blurred, noisy, photographed in classroom or bedroom lighting.
- **The vocabulary is CAIE's.** Subject codes (0580 Mathematics, 0606 Additional Mathematics, 0625 Physics), sessions (m/s/w), years, variants, paper numbers, mark schemes, grade boundaries, method marks. This is the users' native language, not jargon to be softened away.
- **Marking is a review workflow, not a verdict.** Low-confidence markings and integrity flags land in a teacher's review queue for override-and-annotate; overrides feed back as recorded corrections.
- **Two ambient scenes.** Teacher at a desk doing bulk, focused work. Student checking a single result on a phone, emotionally invested in the number.
- **Provenance is visible.** Deterministic marking, AI-assisted marking, and missing data stay distinguishable to the user throughout.

## Capabilities and Constraints

**Scope (v1):** CAIE only — Mathematics 0580, Additional Mathematics 0606, Physics 0625. English-only UI. Launching in Egypt. The architecture is board-agnostic; Edexcel and Oxford AQA arrive later as data + parser plugins.

**Built today (Phases 0–2 merged):** real SSE-driven correction pipeline; grade-boundary ingestion with provenance; accuracy harness with golden fixtures; plagiarism and AI-detection advisory flags; Supabase Storage upload path; auth for all five roles with RBAC on every route; seat model; 3-device session registry; student and teacher surfaces on real data; PWA foundation and camera capture.

**Not yet built:** teacher class management, at-risk flagging, review override flow, teacher quiz builder, parent portal (Phase 3); content generation, placement test, onboarding questionnaire, adaptive study plans (Phase 4); XP, streaks, leaderboards, announcements, web push (Phase 5).

**Engagement mechanics are real product, restrained in expression.** XP, daily streaks with streak-freeze, and leaderboards (friends / class / school / global / per-subject) are non-negotiable Phase 5 mechanics. The consumer-edtech anti-reference below governs how they look and sound, not whether they exist — they must not be designed as a Duolingo pastiche, and must not be quietly dropped either.

**Hard product rules:**
- Leaderboards rank XP (effort), never grades. Grades are private to the student, their parents, and their teachers.
- Plagiarism and AI-detection results are advisory teacher-review signals only. They never auto-penalize, and copy must present them as signals, not verdicts.
- Maximum 3 concurrent devices per account; a 4th login silently invalidates the oldest session.
- 25MB upload cap.

**Technical constraints that shape UI:** React 19 + Vite SPA (`web/`), FastAPI backend, PostgreSQL via Supabase, Google Gemini for vision and AI marking, `@phosphor-icons/react`, Tailwind v4. Payment processing is out of scope — subscription and seat data models exist, and account activation is a manual platform-admin toggle. Gradio remains an internal debug tool, not a user surface.

**Undecided:** pricing and plan tiers beyond the data model; whether Gradio is retired or migrated.

## Brand Commitments

**Name:** Lemely.

**Personality:** Warm · Encouraging · Supportive. The voice of a knowledgeable teaching companion — precise about marks but never cold about a student's performance. Accuracy is non-negotiable, but how results are presented matters. "You scored 14/20 — strong on kinematics, let's work on waves" is better than a naked percentage.

**Anti-references (binding):**
- Academic/institutional aesthetics: Times New Roman, university portal grays, government-form layouts.
- Generic SaaS dashboards: navy blue hero, metric cards with gradient shadows, the HubSpot/Salesforce template.
- Consumer edtech gamification: Duolingo-style emojis-as-UI, confetti, bright primary colours, cheerleader copy. (Governs expression only — see the engagement note above.)

## Evidence on Hand

- **Real CAIE corpus:** `Sources/` — past papers and marking schemes for Mathematics, Additional Mathematics, Physics.
- **Golden accuracy fixtures:** `tests/golden/` — fixtures across 0580/0606/0625 covering correct, partially correct (method marks), and wrong answers, with known ground truth.
- **Phase reports with real screenshots:** `reports/phase-0/`, `reports/phase-1/`, `reports/phase-2/` (screens in `reports/phase-2/screens/`).
- **Design mockups:** `design/project/Lemely Teacher.dc.html`, `design/project/Lemely Student.dc.html`, plus `design/project/uploads/`.
- **Build record:** `BUILD/MISSION.md` (scope and phase roadmap), `BUILD/STATE.md` (current state and honest limitations), `BUILD/DECISIONS.md`, `LEMELY_AUDIT.md`.

**Absent — must not be fabricated:** no customers, no testimonials, no case studies, no press, no pricing, no live deployment, no usage numbers, no partner schools. Any figure shown in a surface must trace to the corpus, the harness, or seeded demo data.

## Product Principles

1. **Numbers serve people, not the reverse.** Every metric displayed connects to a human action or next step. Never show a number without context for what to do with it.
2. **Encourage forward.** Results show what to work on next, not just what went wrong. Weakness = opportunity.
3. **Clarity over completeness.** The most important information is visible immediately; details are one level down (accordions, modals, JSON views).
4. **Warmth in precision.** Be accurate AND kind. Feedback is about the work, not the student's worth.
5. **Honest about AI.** Always distinguish deterministic marking from AI-assisted from missing. Confidence and provenance are load-bearing UI, not footnotes. Trust is built through transparency.

## Accessibility & Inclusion

- WCAG AA as baseline (contrast ratios ≥ 4.5:1 for text).
- Students under exam stress: avoid red-heavy error states; prefer amber/neutral for "needs attention."
- Light mode as default — varied ambient environments (classrooms, home desks, libraries).
- Mobile-first for students and parents; desktop density for teachers and school admins.
- English-only for v1; Arabic UI is explicitly deferred, so layouts need not solve RTL yet.
