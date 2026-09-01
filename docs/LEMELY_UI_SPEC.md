# Lemely — Product & UI Specification

**Purpose of this document.** This is a complete design brief for a UI designer.
It describes what Lemely is, who uses it, every screen in the product, what is on
each screen, how each element behaves, and how screens connect. Everything here
is a decision already made by the product owner — treat constraints as fixed and
spend your creative effort on visual direction, hierarchy, and interaction
quality.

---

# PART 1 — THE PRODUCT

## 1.1 What Lemely is

Lemely is a study platform for students taking Cambridge (CAIE) IGCSE, O-Level,
and AS/A-Level exams, plus their parents and teachers. It launches in Egypt.

The thing that makes Lemely worth paying for is one loop: **a student
photographs the past paper they just sat, and Lemely marks it like an examiner
would.** Not a multiple-choice checker — it reads handwritten working, awards
method marks for partially correct answers, cross-references the official
marking scheme, produces a grade with a predicted boundary, and tells the
student precisely which topics they are weak in. Everything else in the product
is built on the data that loop produces.

**Version 1 subject scope:** Mathematics (0580), Additional Mathematics (0606),
Physics (0625). Cambridge only. English-language interface only.

## 1.2 Who uses it

| User | What they want | How often | Device |
|---|---|---|---|
| **Student** (14–18) | Know where I actually stand, and what to fix before the exam | Daily to weekly, in bursts | Phone, almost always |
| **Parent** | Is my child actually working, and are they going to be okay? | Weekly, glances | Phone |
| **Teacher / private tutor** | Which of my 30 students is drowning, and in what | Few times a week, sessions | Laptop, sometimes tablet |
| **School / centre admin** | Manage seats, teachers, and classes | Monthly | Laptop |
| **Platform admin** (internal) | Activate accounts, watch the marking pipeline | Daily | Laptop |

A student can hold a school-issued seat and a personal subscription at the same
time. A teacher can be independent, attached to a school, or both. Parents log in
with a phone number, not an email — many will not have a habitual email address.

## 1.3 The core loop, in the student's words

> I finish a past paper on paper, at my desk, at 11pm. I open Lemely, photograph
> six pages with my phone, and it tells me: 58/80, a B, two marks off an A, and
> that I keep losing marks on circle theorems and on showing units in
> calculations. Then it gives me ten circle-theorem questions from previous
> papers to do tomorrow.

Design for that moment: **tired, at night, on a phone, wanting a number.**

## 1.4 Product principles the UI must uphold

These are not stylistic preferences. They constrain the interface.

1. **The system says when it isn't sure.** Every marked question carries a
   confidence value. Low-confidence marks are visibly flagged to the student
   ("we're not certain about this one — your teacher will check") and routed to
   a teacher review queue. Never present an uncertain mark as a confident one.
   This is the product's integrity and its main defence against being wrong.
2. **Flags are signals, not verdicts.** The plagiarism ("this matches the
   marking scheme text") and AI-detection checks produce advisory flags for a
   teacher to look at. The UI must never accuse a student, never show a scary
   red "CHEATING DETECTED" banner, never auto-penalize a mark. Students should
   not see these flags at all; teachers see them phrased as "worth a look."
3. **Grades are private; effort is public.** Leaderboards rank XP only — never
   grades, never percentages, never predicted grades. A student's marks are
   visible to that student, their linked parents, and their teachers. Nobody
   else, ever.
4. **The teacher has final authority.** Any mark Lemely produces can be
   overridden by a teacher, with a note. The override is what the student sees
   afterwards, labelled as a teacher correction.
5. **Parents observe; they don't drive.** Parent views are read-only. No
   messaging a child through the app, no assigning work, no marking.
6. **Never invent precision.** Predicted grade boundaries come from real
   historical data where it exists; where it doesn't, the prediction is labelled
   "estimated" in the interface, visibly and every time.

## 1.5 Platform and technical constraints

- **Progressive Web App.** Mobile-first, installable, works from the browser.
  Design at a 380px baseline and scale up; the teacher/admin surfaces are the
  only ones designed desktop-first.
- **Camera capture in-app.** The student photographs pages inside the PWA; pages
  are assembled into a PDF client-side before upload. Design a real scanner
  experience, not a file picker.
- **Offline behaviour matters.** Students lose signal. Uploads queue; previously
  viewed results stay readable offline; anything unavailable offline says so
  plainly instead of showing a broken screen.
- **Web push notifications** (grades ready, announcements, streak about to
  break, study session reminders, at-risk alerts).
- **Three devices maximum per account.** Signing in on a fourth quietly signs
  out the oldest, and the account screen lists active devices.
- **Processing is slow and streamed.** Marking a six-page handwritten paper
  takes real time (tens of seconds to minutes). The progress experience is a
  designed screen, not a spinner.
- **English only. Left-to-right.** Arabic is a later phase — but choose type and
  layout that won't have to be thrown away when RTL arrives.
- Existing stack is React + Tailwind. Assume a token-based design system.

## 1.6 Visual direction — guidance, not prescription

Ground the identity in the world this product lives in: **exam papers.** That
world has a real material vocabulary — the ruled answer booklet, the question
number in the margin, the examiner's red annotation, the mark in a small box at
the right of the line, "[3]" at the end of a question stem, the mark scheme's
terse notation (M1, A1, B1, ft, oe, cao), the grade threshold table. There is a
genuinely distinctive interface hiding in that vocabulary, and almost nobody has
built it — most study apps look like generic ed-tech.

Some direction:

- **The mark is the hero.** When a student opens their result, the number and
  the grade should land before anything else does. Everything else on that
  screen is subordinate.
- **Borrow examiner grammar deliberately, don't cosplay it.** A mark shown in a
  small box at the end of a line is meaningful; a paper-texture background is
  decoration. Take the first, skip the second.
- **Confidence needs its own visual language** and must be immediately legible
  at a glance — this is the most novel component in the product and the place to
  spend your boldness. It should be quiet when confidence is high and impossible
  to miss when it's low, without looking like an error state.
- **Avoid the default ed-tech look:** rounded pastel cards, cartoon mascots,
  confetti on every action, a bright gradient hero, generic "achievement" badges.
  Also avoid the current AI-design defaults (cream background + serif display +
  terracotta accent; near-black with one acid accent; broadsheet hairline
  columns). Egypt/MENA students are style-literate and will read a templated
  interface as a cheap product.
- **Gamification should feel earned, not sugary.** The streak and XP system is
  real motivation infrastructure for a stressed teenager; make it feel like a
  training log, not a slot machine.
- **The teacher product may look different from the student product** — denser,
  more tabular, more desktop — but must obviously be the same family.

## 1.7 Copy voice

Plain, direct, unpatronising, and never cheerful about bad news. A 41% is a 41%;
the interface says what to do about it. Use the student's vocabulary: "paper,"
"session," "variant," "mark scheme," "boundary," "predicted grade." Never
"assessment artifact." Errors say what happened and what to do. Empty states
say what to do first.

---

# PART 2 — CROSS-CUTTING COMPONENTS

Design these once; they appear across many screens. Getting these right is 60%
of the product.

**C-1 · Grade badge.** Letter grade (A*–G / U). Must work at three sizes: hero
(results screen), medium (subject card), inline (list row). Needs a variant for
*predicted* vs *achieved*, and a variant for *estimated* (dashed or otherwise
visibly provisional) when boundary data is missing.

**C-2 · Mark display.** "58 / 80" with percentage. Hero and inline variants.

**C-3 · Boundary bar.** A horizontal scale showing grade thresholds for that
paper with the student's score positioned on it, and the distance to the next
boundary up ("2 marks from an A"). This is the single most motivating object in
the product. Must degrade gracefully to "estimated boundaries" styling.

**C-4 · Confidence indicator.** Three levels — confident, uncertain, needs
review. Appears per question and aggregated per paper. Include a tooltip/sheet
explaining what it means in student language.

**C-5 · Weakness chip.** A topic tag ("Circle theorems", "Units in
calculations") with a severity weight. Tappable → drills into evidence.
Appears in dozens of places; needs list, grid, and inline variants.

**C-6 · Question row.** Question number, marks awarded / marks available,
correct-partial-wrong state, confidence indicator, expand affordance.

**C-7 · Paper identity line.** "0580/42 · May/June 2023 · Paper 4 Variant 2" —
the compact, consistent way a paper is named everywhere in the product.

**C-8 · Trend sparkline.** Performance over the last N attempts, with an
up/down/flat read.

**C-9 · XP / streak indicator.** Compact (nav) and expanded (profile) forms.
Includes streak-freeze state.

**C-10 · Processing state.** Multi-stage progress for the marking pipeline:
reading pages → identifying paper → fetching mark scheme → marking → analysing.
Each stage can succeed, be in progress, or fail with a specific message.

**C-11 · Empty / error / offline states.** Design a family, not one-offs.

**C-12 · Role switcher** (for people who hold more than one role, e.g. a teacher
who is also a parent).

**C-13 · Bottom navigation** (student, mobile) and **sidebar navigation**
(teacher/admin, desktop).

---

# PART 3 — SCREEN INVENTORY

| ID | Screen | Role |
|---|---|---|
| G-01 | Landing / marketing entry | Public |
| G-02 | Sign up — role selection | Public |
| G-03 | Sign up — student/teacher details | Public |
| G-04 | Log in (email) | Public |
| G-05 | Parent log in (phone + OTP) | Parent |
| G-06 | Password reset | Public |
| G-07 | Email verification pending | Public |
| G-08 | Join with invite code | Student/Teacher |
| G-09 | Install app prompt (PWA) | All |
| G-10 | Device limit reached | All |
| G-11 | Account & devices settings | All |
| G-12 | Notification preferences | All |
| G-13 | Notifications inbox | All |
| G-14 | Subscription / plan status | Student, Parent, School |
| G-15 | Offline / connection lost | All |
| S-01 | Student onboarding — subjects | Student |
| S-02 | Student onboarding — questionnaire | Student |
| S-03 | Student onboarding — placement invite | Student |
| S-04 | Placement test — in progress | Student |
| S-05 | Placement test — results & level | Student |
| S-06 | Student home / dashboard | Student |
| S-07 | Subjects list | Student |
| S-08 | Subject overview | Student |
| S-09 | Paper history (per subject) | Student |
| S-10 | Upload — entry / choose method | Student |
| S-11 | Upload — camera scanner | Student |
| S-12 | Upload — page review & reorder | Student |
| S-13 | Upload — confirm paper identity | Student |
| S-14 | Marking in progress | Student |
| S-15 | Results — overview | Student |
| S-16 | Results — question breakdown | Student |
| S-17 | Question detail | Student |
| S-18 | Results — weaknesses & next steps | Student |
| S-19 | Weakness detail | Student |
| S-20 | Practice generator | Student |
| S-21 | Practice set — working view | Student |
| S-22 | Flashcard decks | Student |
| S-23 | Flashcard review session | Student |
| S-24 | Study plan — week view | Student |
| S-25 | Study session detail | Student |
| S-26 | Assigned quiz — take | Student |
| S-27 | Quiz results | Student |
| S-28 | Announcements & exam calendar | Student |
| S-29 | Leaderboards | Student |
| S-30 | Friends | Student |
| S-31 | Profile / XP / streak | Student |
| T-01 | Teacher dashboard | Teacher |
| T-02 | Classes list | Teacher |
| T-03 | Class detail — roster | Teacher |
| T-04 | Class detail — analytics | Teacher |
| T-05 | Student detail (teacher view) | Teacher |
| T-06 | At-risk list | Teacher |
| T-07 | Review queue | Teacher |
| T-08 | Review item — remark | Teacher |
| T-09 | Quiz builder | Teacher |
| T-10 | Quiz results (class) | Teacher |
| T-11 | Custom paper & mark scheme upload | Teacher |
| T-12 | Announcement composer | Teacher |
| P-01 | Parent home / children | Parent |
| P-02 | Child overview | Parent |
| P-03 | Child subject detail | Parent |
| P-04 | Child weaknesses | Parent |
| K-01 | School dashboard | School admin |
| K-02 | Seats & student accounts | School admin |
| K-03 | Teachers | School admin |
| K-04 | Classes (school-wide) | School admin |
| X-01 | Platform admin console | Platform admin |
| X-02 | Account activation queue | Platform admin |
| X-03 | Pipeline & corpus health | Platform admin |

---

# PART 4 — SCREENS IN DETAIL

## 4.1 Public & account screens

### G-01 · Landing / marketing entry
**Purpose.** Convince a student or parent arriving from a link that this marks
real handwritten papers, then get them to sign up.
**Contains.** A hero that demonstrates the core loop rather than describing it —
the strongest option is a real before/after: a photographed handwritten answer
on one side, the marked breakdown on the other. Supporting sections: how it
works in three steps; who it's for (student / parent / teacher tabs); subjects
covered (0580, 0606, 0625, stated plainly with "more coming"); pricing/plans;
FAQ. Persistent header with "Log in" and "Get started."
**Interactions.** CTA → G-02. "Log in" → G-04. "I'm a parent" → G-05.
**States.** None special.
**Exits.** G-02, G-04, G-05.

### G-02 · Sign up — role selection
**Purpose.** Branch by role before asking for anything.
**Contains.** Three large choices: *I'm a student*, *I'm a parent*, *I'm a
teacher or tutor*. Each with one line of what they'll get. Secondary link: "I
have an invite code from my school" → G-08.
**Interactions.** Student/teacher → G-03. Parent → G-05 (parents authenticate by
phone, so they skip the email form).
**Exits.** G-03, G-05, G-08, G-04.

### G-03 · Sign up — details
**Contains.** Name, email, password (with strength feedback and a show/hide
toggle), terms acceptance. Teacher variant adds: school or centre name
(optional, with "I work independently" option).

> **Shipped divergence (`BUILD/DECISIONS.md` D7.2).** The teacher variant's
> optional "school or centre name" field was dropped, not built and left
> unused. A self-registered teacher is always independent at signup — no
> `School` row, no membership — because a `School` carries a real seat quota
> and letting an anonymous visitor mint one via a text field would only ever
> produce one with a quota of zero. Real school membership arrives later, by
> an invite code (G-08) or platform-admin provisioning (K-01 equivalent),
> never by what a visitor types here.

**Interactions.** Inline validation on blur, not on every keystroke. Submit →
G-07.
**States.** Field errors; email-already-registered error that offers a route to
log in; submitting state on the button.
**Exits.** G-07, G-04.

### G-04 · Log in (email)
**Contains.** Email, password, "Stay signed in," forgot-password link, "Sign up"
link, and a distinct "Parent? Sign in with your phone number" link.
**States.** Wrong credentials (do not reveal which field is wrong); locked or
unverified account with a resend option; device-limit outcome → G-10.
**Exits.** Role home (S-06 / T-01 / P-01 / K-01 / X-01), G-05, G-06, G-02, G-10.

### G-05 · Parent log in (phone + OTP)
**Purpose.** The lowest-friction entry in the product; many parents are not
confident users.
**Contains.** Country selector defaulting to Egypt (+20), phone number field,
"Send code." Second step: six-digit code entry with auto-advance and paste
support, a resend timer, and "Change number."
**Interactions.** Code auto-submits when complete. In development the code is
logged rather than sent by SMS — design a clearly-marked developer affordance
that shows the code on screen in non-production environments, so this is
testable without a real SMS provider.
**States.** Invalid number; wrong code; expired code; resend cooldown; no
account found for this number (offer: "Ask your child's school to link you," or
route to a child-linking flow).
**Exits.** P-01, G-06.

### G-06 · Password reset
Standard: request by email → confirmation screen → reset form from link →
success. Keep it three screens, no surprises.

### G-07 · Email verification pending
**Contains.** "Check your email" with the address shown, resend button with
cooldown, "Wrong address? Change it," and — importantly — a way to continue
into a limited preview of the app rather than a hard wall.

> **Shipped divergence (`BUILD/DECISIONS.md` D7.5, D7.6).** Verification is a
> **soft gate landing on exactly one route**, `POST /api/student/correct` (the
> Gemini spend) — everywhere else, including upload, an unverified account
> works normally, which is the "limited preview rather than a hard wall" this
> section already asks for, made concrete as one guarded route instead of a
> mood. The literal **"Check your email" heading is not used**: no configured
> email provider in this build actually sends anything (`MockEmailProvider` is
> wired unconditionally), so a heading claiming mail was sent or should be
> checked would be false in every deployment of this code as written. The
> shipped screen states plainly what verification unlocks and offers the
> developer-only link affordance instead, mirroring how G-05 already handles
> the SMS mock's own equivalent gap.

**Exits.** Onboarding (S-01) once verified.

### G-08 · Join with invite code
**Purpose.** A school-issued seat or a teacher's class link.
**Contains.** Code field (or arrives pre-filled from a deep link), a preview of
what they're joining ("Al-Nasr Language School — Mr Hassan's Physics 0625
class"), and a confirm action. If the person has no account yet, this flows into
G-03 with the code retained.
**States.** Invalid code, expired code, seat quota full (explain and tell them
to contact their school).

> **Shipped divergence (`BUILD/DECISIONS.md` D7.3; see also `BUILD/BLOCKERS.md`
> B9).** The **"seat quota full" state cannot occur on this screen**, by
> design rather than by omission. A seat invite reserves its seat at *mint*
> time (when a school admin generates the code), not at redemption, so a code
> that exists has already secured a place — the preview shown here never
> promises a seat that could have gone by the time someone redeems it. Quota
> refusal is therefore an admin-side error on the school-management screen
> (a school admin cannot mint past capacity), never something a code holder
> sees. The screen keeps a real, tested rendering branch for this state
> against a structured `seat_quota_exceeded` marker in case a defensive
> re-check is ever added at redemption — it is inert against the live backend
> today, and that is expected, not a bug.

**Exits.** G-03, S-01, S-06.

### G-09 · Install app prompt
**Purpose.** Get the PWA onto the home screen, because camera capture and push
both work better installed.
**Contains.** A non-modal, dismissible prompt with platform-specific
instructions (iOS Safari requires the share-sheet route and must be illustrated;
Android/Chrome can trigger the native prompt).
**Interactions.** Appears after the first successful marking, not on first load —
ask when the value has been proven. Dismissal is remembered.

### G-10 · Device limit reached
**Purpose.** Enforce the three-device rule without feeling like an accusation.
**Contains.** A list of the three currently signed-in devices (name, rough
location, last active), a clear statement that signing in here will sign out the
oldest, and a confirm action. Also a short line on why the limit exists.
**Exits.** Role home, or G-11.

### G-11 · Account & devices settings
**Contains.** Profile (name, email, phone, avatar), password change, linked
relationships (for a student: linked parents, school, classes — with the ability
to request removal), active devices list with individual sign-out, subscription
summary linking to G-14, sign out, delete account.
**States.** Devices list empty except current; pending parent-link request.

### G-12 · Notification preferences
**Contains.** Toggle groups by type: results ready, new announcement, study
session reminders, streak at risk, weekly summary, teacher/at-risk alerts
(teacher and parent only). Quiet hours. A test-notification button. Permission
state — if the browser has denied push, show that clearly with a route to fix it
rather than toggles that silently do nothing.

### G-13 · Notifications inbox
**Contains.** Chronological list, unread state, grouping by day, filter by type,
mark-all-read. Each item deep-links to its subject (a result, an announcement, a
review item).
**States.** Empty ("Nothing yet — we'll tell you when your marks are ready").

### G-14 · Subscription / plan status
**Purpose.** Because payments are deferred, this screen shows status and how to
activate, not a checkout.
**Contains.** Current plan, what it includes, activation status (active /
pending activation / expired), and instructions for activation (contact route).
School-seat holders see "Your access is provided by <school>" instead.
**States.** Pending activation is the important one — explain what happens next
and roughly when, and keep the app usable in a limited way meanwhile.

### G-15 · Offline / connection lost
Not a full screen so much as a system: a persistent, unobtrusive banner; queued
uploads shown with their queued state; cached content readable; uncached
destinations replaced by an explanatory panel with a retry.

---

## 4.2 Student — onboarding and placement

### S-01 · Onboarding, step 1: subjects
**Purpose.** Establish what the student is studying this session.
**Contains.** Qualification level selector (IGCSE / O-Level / AS / A-Level),
then subject cards for the supported subjects with an obvious "more subjects
coming" note so absence doesn't read as a bug. Per subject: the papers they'll
sit (e.g. 0580 Paper 2 + Paper 4) and the exam session they're targeting
(e.g. May/June 2027). Progress indicator across the onboarding steps.
**Interactions.** Multi-select; each selected subject expands to capture papers
and target grade.
**Exits.** S-02.

### S-02 · Onboarding, step 2: questionnaire
**Purpose.** Gather what shapes the study plan.
**Contains.** A short, non-tedious sequence: school name, whether they take
external lessons/tutoring, study time available per week (slider), grade level,
target grades per subject, and two or three self-assessment sliders per subject
("How confident are you in algebra?"). Keep it under two minutes; show progress;
allow "skip for now" on everything non-essential.
**Design note.** This is where most onboarding flows lose people. Make it feel
like a conversation, one question per view on mobile, with big touch targets.
**Exits.** S-03.

### S-03 · Onboarding, step 3: placement invite
**Contains.** An explanation that a 15-minute placement test per subject gives a
much better starting picture, an estimate of time, "Start now" and "Later"
options, and a note that they can take it any time from the subject screen.
**Exits.** S-04 or S-06.

### S-04 · Placement test — in progress
**Purpose.** ~15 minutes per subject, assembled from real past-paper questions
spanning topics.
**Contains.** Question stem rendered faithfully (maths notation and diagrams
must render properly — this is a real design constraint, not a detail), answer
input appropriate to the question type (multiple choice, numeric, short answer,
or "work it on paper and photograph it" for structured questions), question
counter, elapsed/remaining time, flag-for-review, previous/next, and a submit
that warns about unanswered questions.
**States.** Time nearly up; connection lost mid-test (answers must survive);
resume after leaving.
**Exits.** S-05.

### S-05 · Placement test — results & level
**Contains.** Not a grade — a *starting picture*: strongest and weakest topics,
an estimated working level, and the initial study plan generated from it. Frame
it as a baseline, explicitly and warmly, because a bad placement result at
onboarding is the highest-churn moment in the product.
**Exits.** S-24 (study plan) or S-06.

---

## 4.3 Student — main surfaces

### S-06 · Student home / dashboard
**Purpose.** Answer "where do I stand and what do I do next" in three seconds.
**Contains, in priority order.**
1. A primary action to **correct a paper** — this is the product's main verb and
   should be the most prominent interactive element on the screen.
2. Any **result that just finished processing**, surfaced at the top until seen.
3. **Overall standing**: a compact per-subject strip showing current predicted
   grade and trend direction for each enrolled subject.
4. **Today's study plan sessions** — one or two concrete items with a completion
   affordance, not a link to a plan.
5. **Top weaknesses right now** — three weakness chips with a route into
   practice.
6. **Streak + XP** compactly, plus leaderboard position if the student
   participates.
7. **Announcements / upcoming exam dates** if anything is imminent.
8. Anything requiring attention: a paper flagged for teacher review, a quiz
   assigned by a teacher and due.
**Interactions.** Everything is a route into a deeper screen. Pull-to-refresh.
**States.** *First-run empty state is critical*: a student who has just onboarded
has no results at all. That version of the screen should be almost entirely a
single invitation to correct their first paper, with a secondary route to the
placement test — not a grid of empty cards showing zeroes.
**Exits.** S-10, S-15, S-08, S-24, S-19, S-29, S-28, S-26.

### S-07 · Subjects list
**Contains.** One card per enrolled subject: subject name and code, predicted
grade, papers completed count, trend, top weakness. An "add or remove subjects"
route back into the subject picker.
**Exits.** S-08.

### S-08 · Subject overview
**Purpose.** Everything about one subject in one screen.
**Contains.**
- Header: subject, code, target grade vs predicted grade, session targeted.
- **Predicted final subject grade** with the reasoning made visible — how each
  paper's predicted grade contributes and what the aggregate is. Provisional
  styling if any component is estimated.
- **Per-paper section** (e.g. Paper 2, Paper 4): for each, average mark, best
  mark, predicted grade, predicted boundary for that paper, count of attempts,
  and a trend sparkline.
- **Weakness list** for the subject, ranked, each with evidence count.
- **Recent attempts** list → S-15.
- Actions: correct a paper in this subject, generate practice, take/retake the
  placement test, view all attempts.
**Exits.** S-09, S-15, S-19, S-20, S-10, S-04.

### S-09 · Paper history
**Contains.** A filterable, sortable list of every attempt in this subject:
paper identity line, date attempted, mark, grade, confidence summary, and any
teacher-override marker. Filters by paper number, variant, session, and date.
A comparison affordance — select two attempts to compare.
**States.** Empty; single-attempt (no trend yet, say so).
**Exits.** S-15.

---

## 4.4 Student — the correction flow (the product's spine)

### S-10 · Upload — entry
**Contains.** Two routes: **photograph pages** (primary, large) and **upload a
file** (secondary). Below: a short "how to get a good scan" guide with
illustrations — flat page, all four corners visible, good light, one page per
shot. Optionally a preselect of which subject/paper they're about to submit, to
help identification.
**States.** Camera permission not granted — explain and offer the file route.
Queued/incomplete previous upload — offer to resume it.
**Exits.** S-11, S-12 (if file chosen), S-06.

### S-11 · Upload — camera scanner
**Purpose.** A real document scanner, in the browser. This screen carries an
outsized share of the product's perceived quality.
**Contains.** Full-bleed camera view; edge-detection overlay indicating whether
the page is framed well; capture button; page counter ("Page 3"); thumbnail
strip of captured pages; torch toggle; "Done" action.
**Interactions.** Capture → brief confirmation → immediately ready for the next
page (students shoot six pages in a row; do not interrupt that rhythm with a
review step per page). Tap a thumbnail to review or retake. Real-time guidance
when framing is poor ("Move closer," "Too dark") — brief, non-nagging.
**States.** Poor lighting; page not detected; camera unavailable mid-session;
storage/memory pressure on long captures.
**Exits.** S-12.

### S-12 · Upload — page review & reorder
**Contains.** Grid of captured/uploaded pages with page numbers; per-page
actions: retake, rotate, crop, delete; drag to reorder; "Add more pages";
confirm action showing total page count and estimated size.
**States.** A page detected as blurry or too dark gets a non-blocking warning
badge with a retake shortcut. Size over the 25MB cap — explain and offer to
compress or remove pages.
**Exits.** S-13.

### S-13 · Upload — confirm paper identity
**Purpose.** Lemely detects subject code, session, year, paper number, and
variant from the page. This screen confirms it, because a wrong identification
means marking against the wrong mark scheme.
**Contains.** The detected identity shown prominently and in plain language
("Mathematics 0580, Paper 4 Variant 2, May/June 2023"), with a confidence
indication and an obvious correction affordance. If detection failed or is
uncertain, this becomes a form: subject, year, session, paper, variant, each a
constrained picker.
**Interactions.** Confirm → starts marking. Correcting any field should be two
taps, not a modal maze.
**States.** Confident detection (confirm-only); uncertain (fields pre-filled but
highlighted); failed (empty form with help text); mark scheme unavailable for
this paper — this is a real case and needs its own honest message, with the
option to submit anyway for a partial analysis or to pick a different paper.
**Exits.** S-14.

### S-14 · Marking in progress
**Purpose.** Hold attention through a genuinely slow operation, honestly.
**Contains.** Staged progress (C-10): reading your pages → identifying the paper
→ fetching the mark scheme → marking each question → analysing your weak topics.
Per-stage state and a per-question counter during the marking stage ("Question 7
of 21"). A clear statement that they can leave and will be notified when it's
done — with a button that does exactly that.
**Interactions.** Leaving does not cancel. A push notification fires on
completion. Returning resumes this screen.
**States.** Each stage can fail with a specific, actionable message (mark scheme
not found; pages unreadable; service unavailable) — never a generic "something
went wrong." Partial success: some questions marked, some not.
**Design note.** Resist a fake progress bar. Real staged progress with honest
per-stage detail builds more trust than a smooth lying animation.
**Exits.** S-15, or an error recovery route back to S-12 / S-13.

### S-15 · Results — overview
**Purpose.** The payoff screen. The single most important screen in the product.
**Contains, in this hierarchy.**
1. **The mark and the grade**, hero-sized. "58 / 80 — Grade B."
2. **The boundary bar** (C-3): where this score sits against this paper's grade
   thresholds, and the distance to the next boundary up. Provisional styling if
   the boundaries are estimated, with the word "estimated" visible.
3. **Paper identity line** (C-7) and date.
4. **Comparison to previous attempts** — better/worse than their average, trend.
5. **Confidence summary**: "We're confident about 19 of 21 questions. Two are
   waiting for your teacher to check." Tappable → filters S-16 to those.
6. **Top three mistakes** with the topic named, each routing to the question.
7. **Weak topics identified** as chips, routing to S-18.
8. Actions: see full breakdown (S-16), practise these topics (S-20), share with
   parent/teacher if not automatic, correct another paper.
**States.** Teacher-overridden result — clearly labelled with the teacher's name
and note, showing the corrected mark as primary. Partial result. No boundary
data. Very low overall confidence — the whole result should be framed as
provisional pending review.
**Exits.** S-16, S-18, S-20, S-08, S-10.

### S-16 · Results — question breakdown
**Contains.** The full question list (C-6): number, marks awarded / available,
correct / partial / wrong state, confidence indicator, topic tag. Filters:
all / lost marks only / needs review only. A summary strip at the top (marks by
question, or by section).
**Interactions.** Tap a row → S-17. Filters persist while in the screen.
**States.** Long papers need efficient scanning — consider sectioning by
question and sticky sub-headers.
**Exits.** S-17.

### S-17 · Question detail
**Purpose.** Explain the mark. This is where trust is won or lost.
**Contains.**
- The question stem, rendered properly (notation, diagrams).
- **The student's own work**, cropped from their scan, so they can see what
  Lemely read. This matters enormously — if Lemely misread their handwriting,
  they need to see that immediately.
- **What Lemely read** as their answer (the transcription), with an "this isn't
  what I wrote" affordance that routes the question into the teacher review
  queue.
- **The marking breakdown**: method marks and accuracy marks awarded and
  withheld, in plain language ("You got the method mark for setting up the
  equation, but lost the accuracy mark — the sign is wrong in line 3").
- **The relevant mark scheme extract**, presented as reference.
- Confidence for this question, and if low, what happens next.
- Topic tag → S-19. Navigation to previous/next question.
**States.** Unmarked question (blank answer); question awaiting teacher review;
teacher-corrected question showing both the original and the correction.
**Exits.** S-19, S-16, T-07 (indirectly, via dispute).

### S-18 · Results — weaknesses & next steps
**Contains.** The weak topics this paper revealed, each with: how many marks it
cost on this paper, whether it's a repeat offender across papers, and a direct
action to practise it. A single primary recommendation ("Start with circle
theorems — it's cost you 14 marks across three papers").
**Exits.** S-19, S-20, S-24.

### S-19 · Weakness detail
**Contains.** One topic across the student's whole history: marks lost over
time, which papers and questions, whether it's improving, and the specific
recurring error patterns if identifiable. Actions: generate practice on this
topic, make flashcards, add to study plan.
**Exits.** S-20, S-22, S-24, S-17.

---

## 4.5 Student — practice, plan, and assessment

### S-20 · Practice generator
**Purpose.** Produce a "classified"-style set — real past-paper questions grouped
by topic, filtered to this student's weaknesses. This is a familiar artefact to
Egyptian IGCSE students; the interface should feel like assembling one.
**Contains.** Topic selection (pre-filled with their weak topics), number of
questions, difficulty targeting (tied to their working level or target grade),
source toggle (past-paper questions vs generated questions), and a generate
action. Output: a set summary with a preview.
**Interactions.** Generate → S-21. Also an export/print route, because many
students will want it on paper.
**States.** Generating (this takes time); not enough questions available for a
narrow topic — say so and offer to broaden.
**Exits.** S-21.

### S-21 · Practice set — working view
**Contains.** Questions one at a time or as a scrollable set, with the answer
route matching the question type — including "do it on paper and photograph it,"
which feeds back into the marking pipeline. Progress, skip, reveal-answer (with
a deliberate friction so it isn't the default), and a finish action producing a
short summary and XP.
**Exits.** S-27-style summary, S-19.

### S-22 · Flashcard decks
**Contains.** Decks by subject and topic, each showing card count and due-today
count. Actions: review due cards, create a deck from a weakness, auto-generate a
deck for a topic, edit.
**States.** Nothing due today — say what to do instead rather than showing an
empty list.
**Exits.** S-23.

### S-23 · Flashcard review session
**Contains.** A card with a reveal interaction, a self-grade control feeding
spaced repetition (again / hard / good / easy), session progress, and an end-of-
session summary with XP. Must be fast and keyboard/thumb friendly — this is a
repeated micro-interaction and any friction compounds.

### S-24 · Study plan — week view
**Purpose.** Concrete sessions, not vague advice.
**Contains.** The current week laid out by day, each day holding zero to three
sessions. A session shows: subject, topic, activity type (practice set,
flashcards, past paper, revision), and duration. Completion affordance per
session. A header showing weekly progress and total planned time against the
time they said they had. Regeneration control ("Rebuild this week's plan"), and
an explanation of what the plan is based on.
**Interactions.** Tap a session → S-25. Mark complete inline. Reschedule by
dragging (desktop) or a move action (mobile).
**States.** No plan yet (route to placement/questionnaire); plan out of date;
week fully complete (acknowledge it without confetti overload).
**Exits.** S-25, S-20, S-22, S-10.

### S-25 · Study session detail
**Contains.** What this session is, why it was chosen (tie it to a weakness or a
target), the material, an explicit start action that launches the right activity,
and a complete action awarding XP.
**Exits.** S-20, S-21, S-22, S-10.

### S-26 · Assigned quiz — take
**Contains.** Quiz header (teacher, class, due date, question count, time limit
if set), then the question sequence: stem, answer input, counter, flag, navigate,
submit with unanswered warning. Auto-save throughout.
**States.** Not yet open; overdue; already submitted (route to S-27); connection
lost mid-quiz.
**Exits.** S-27.

### S-27 · Quiz results
**Contains.** Score, per-question correctness, correct answers with explanation
where permitted by the teacher's settings, class average if the teacher enabled
it, topics revealed as weak, and XP earned. Never a class ranking by score.
**Exits.** S-19, S-20.

---

## 4.6 Student — engagement and community

### S-28 · Announcements & exam calendar
**Contains.** Two integrated things: announcements from teachers and school, and
official CAIE exam session dates for the papers this student is sitting.
Calendar view and list view. Countdown to the next exam they're sitting —
prominent, because it's genuinely the thing on their mind.
**Interactions.** Announcement detail; add-to-device-calendar for exam dates.
**States.** No announcements; no upcoming exams in scope.

### S-29 · Leaderboards
**Purpose.** Motivation through effort, never through grades.
**Contains.** Tabs or filters for scope — friends / class / school / global —
and for basis — total XP or per-subject XP. Each row: rank, avatar, display
name, XP, streak indicator. The current student's own row pinned and highlighted
even when off-screen. Weekly reset indicated with time remaining.
**Interactions.** Add friends (→ S-30). Opt out of public leaderboards
(available and easy to find — this matters for students who find ranking
stressful).
**Design note (hard rule).** No grades, percentages, or predicted grades appear
here in any form. If you find yourself designing a "top performers" section
based on marks, stop.
**States.** Too few friends to rank; opted out; new week just started.
**Exits.** S-30, S-31.

### S-30 · Friends
**Contains.** Friends list with XP and streak, pending requests in and out, add
by username or invite link, remove. Privacy note explaining that friends see XP
and streaks only.
**States.** Empty; request pending; blocked/removed.

### S-31 · Profile / XP / streak
**Contains.** Avatar and display name, current streak with its calendar
visualisation and any streak-freeze available, total XP and level, XP earned
this week broken down by source (papers corrected, quizzes, flashcards, sessions
completed), achievements/milestones, and lifetime stats (papers marked,
questions answered, hours studied).
**Design note.** This is the "training log" screen. Make it feel like a record
of real work, and make the streak feel worth protecting without being
manipulative — a streak-freeze that's offered kindly beats a guilt-trip.
**Exits.** G-11, S-29.

---

## 4.7 Teacher

Teacher screens are desktop-first, denser, and tabular, but must remain usable on
a tablet. A teacher's job here is triage: find who needs help, and check the
marks Lemely wasn't sure about.

### T-01 · Teacher dashboard
**Contains.**
1. **At-risk students** — the top item, always. Each with the student's name,
   class, subject, and the *reason* the flag fired (declining trend / predicted
   grade two or more boundaries below target / inactive 14+ days). Reasons must
   be shown, not just a red dot.
2. **Review queue count** with a direct route in — this is work only they can do.
3. **Class summary cards**: class name, student count, average predicted grade,
   the class's top weakness, activity level.
4. Recent activity: submissions across their classes.
5. Quick actions: build a quiz, post an announcement, add a class.
**States.** No classes yet (route to class creation); nothing in the review queue
(a good state — say so plainly).
**Exits.** T-06, T-07, T-03, T-09, T-12.

### T-02 · Classes list
**Contains.** Table of classes: name, subject, student count, average predicted
grade, last activity, at-risk count. Create-class action. Search and sort.
**Exits.** T-03.

### T-03 · Class detail — roster
**Contains.** Student table: name, papers submitted, average mark, predicted
grade, trend, at-risk flag with reason, last active. Sortable on every column —
teachers triage by sorting. Bulk actions: assign a quiz, post an announcement.
Add students (by invite code or from school seats). Tabs to T-04.
**States.** Empty class with a clear invite route.
**Exits.** T-05, T-04, T-09, T-12.

### T-04 · Class detail — analytics
**Contains.** Aggregate performance over time; distribution of predicted grades;
**a topic weakness heatmap** across the class (topics × students, or topics
ranked by class-wide marks lost) — this is the screen's centrepiece and the
thing that changes what a teacher teaches next week; per-paper performance
comparison; engagement stats.
**Interactions.** Click a weakness → the list of students affected → T-05.
Export.
**Exits.** T-05, T-09.

### T-05 · Student detail (teacher view)
**Contains.** Everything the teacher needs about one student: subjects and
predicted grades, full attempt history, weakness list with evidence, trend
charts, at-risk status and reason, activity/engagement, and any flagged
integrity signals — phrased neutrally as "worth a look," with the underlying
evidence viewable and never presented as a conclusion.
**Interactions.** Open any attempt → the teacher's view of S-15/S-16/S-17, with
remark capability. Assign practice. Contact route if the school configures one.
**Exits.** T-08, T-09.

### T-06 · At-risk list
**Contains.** All flagged students across the teacher's classes, grouped or
filterable by reason, sortable by severity, each with the evidence summarised
and a route into the student. Dismiss/acknowledge a flag with a note.
**Exits.** T-05.

### T-07 · Review queue
**Purpose.** Where low-confidence marks and integrity flags land. The teacher's
core recurring task.
**Contains.** A prioritised list: student, paper identity, question, why it's
here (low confidence / possible mark-scheme copying / possible AI-written answer
/ student disputed the transcription), and how long it's been waiting. Filters by
class, reason, and age. Bulk-approve for the trivially fine ones.
**States.** Empty (celebrate it briefly and get out of the way).
**Exits.** T-08.

### T-08 · Review item — remark
**Purpose.** Resolve one questionable mark, fast.
**Contains.** Side by side: **the student's actual scan crop** and **the mark
scheme extract**; what Lemely read and what it awarded; the confidence and the
specific reason for the flag. Controls: accept as-is, adjust the marks (with the
method/accuracy breakdown editable), and a note to the student. Keyboard
shortcuts and a next-item action, because this is done in batches.
**Interactions.** Resolving pushes the corrected mark to the student's result,
labelled as a teacher correction, and notifies them.
**States.** Integrity-flagged items get a distinct but non-inflammatory
treatment; the teacher can dismiss the flag without any record reaching the
student.
**Exits.** T-07 (next item), T-05.

### T-09 · Quiz builder
**Purpose.** Assemble a quiz targeted at a grade level and a set of topics.
**Contains.** A stepped flow: (1) basics — title, subject, class, due date,
optional time limit; (2) content — topics/material to include; (3) difficulty —
target expected grade, with an explanation that questions are selected to suit
students at that level; (4) question pool — choose between past-paper questions
and generated questions, with a live count of matching questions; (5) preview and
edit the selected questions, remove or swap individual ones; (6) assign.
**States.** Not enough questions for the constraints — say so and suggest which
constraint to loosen. Draft saving throughout.
**Exits.** T-10, T-03.

### T-10 · Quiz results (class)
**Contains.** Completion rate, score distribution, per-question analysis showing
which questions the class failed (the most useful view), per-student results, and
the topics the quiz revealed as class-wide weaknesses. Export.
**Exits.** T-05, T-04.

### T-11 · Custom paper & mark scheme upload
**Purpose.** Teachers set their own exams; Lemely should mark those too.
**Contains.** Upload the paper, upload the mark scheme, a parsing preview showing
how Lemely understood the questions and mark allocations, with the ability to
correct that mapping before it's used. Then: assign to a class, or use it to mark
submissions.
**States.** Mark scheme parsed with low confidence — surface exactly which
questions are uncertain and require the teacher to confirm them.
**Exits.** T-03, T-07.

### T-12 · Announcement composer
**Contains.** Audience selector (class, several classes, or whole school for
school admins), title, body with light formatting, optional attachment, optional
schedule, and a preview of how it appears to a student.
**Exits.** T-01.

---

## 4.8 Parent

Parent screens are the simplest in the product. Assume low tolerance for
navigation depth and no interest in learning an interface.

### P-01 · Parent home / children
**Contains.** One card per linked child: name, school/class, an overall status
line in plain language ("On track for A in Physics, struggling in Maths"),
their trend, and last activity. If only one child, skip straight to P-02 and keep
this as a switcher in the header.
**States.** No children linked — explain how to link (invite from the child, or
via the school) rather than showing an empty list.
**Exits.** P-02.

### P-02 · Child overview
**Contains.** Per-subject predicted grade against target grade, trend over time,
recent papers with marks, weak topics in plain language, activity summary (how
much they've been working — parents ask this first), and any at-risk flags with
their reason explained without jargon.
**Design note.** Translate. A parent should not need to know what "0580/42
Variant 2" means. Say "Maths — Paper 4" and keep the code as secondary detail.
**Exits.** P-03, P-04.

### P-03 · Child subject detail
**Contains.** One subject in depth: papers attempted with marks and grades, the
predicted grade with its basis explained simply, boundary distance ("3 marks
from an A"), and topic weaknesses. Read-only throughout.
**Exits.** P-04.

### P-04 · Child weaknesses
**Contains.** Ranked weak topics with what they're costing, phrased for a
non-specialist, and constructive framing on what the child is doing about it
(practice generated, sessions planned). Explicitly not a list of failures.

---

## 4.9 School admin

### K-01 · School dashboard
**Contains.** Seat usage (used vs available, prominently), student count,
teacher count, class count, aggregate performance across the school, subscription
status. Quick actions: invite students, add a teacher, create a class.

### K-02 · Seats & student accounts
**Contains.** Seat quota with a usage bar; student table (name, class, teacher,
status: invited / active / inactive, last active); invite flow generating codes
or links, individually or in bulk (paste a list of names/emails); revoke a seat
with an explanation of what happens to that student's data.
**States.** Quota reached — explain and give a route to request more.

### K-03 · Teachers
**Contains.** Teacher table with classes taught and student counts; invite a
teacher; remove a teacher, with reassignment of their classes handled explicitly
rather than orphaned.

### K-04 · Classes (school-wide)
**Contains.** All classes with teacher, subject, size, and performance summary;
create; reassign; archive.

---

## 4.10 Platform admin (internal)

Utilitarian. Function over polish, but consistent with the system.

### X-01 · Platform admin console
Global counts, system health, recent signups, Gemini spend against the budget
ceiling with the warning thresholds visible, marking throughput, and the
global review-queue depth.

### X-02 · Account activation queue
Pending subscriptions and school accounts awaiting manual activation (payments
are deferred, so this is done by hand): who, what plan, when requested, activate
/ reject with a note.

### X-03 · Pipeline & corpus health
Mark scheme corpus coverage by subject/session/variant; grade boundary coverage
with gaps highlighted (this drives whether predictions are real or estimated);
ingestion job status and failures; marking accuracy metrics against the golden
fixture set; error rates by stage.

---

# PART 5 — FLOWS

Notation: `→` is a forward transition, `⇄` is a two-way relationship,
`⤴` is a return.

## 5.1 First-time student

```
G-01 Landing
  → G-02 Role select (student)
    → G-03 Details → G-07 Verify email
      → S-01 Subjects → S-02 Questionnaire → S-03 Placement invite
          ├─ Start now → S-04 Placement test → S-05 Results → S-24 Study plan → S-06 Home
          └─ Later ─────────────────────────────────────────────────────────→ S-06 Home
                                                                    (first-run empty state)
```

The alternative entry for a school-provided seat:

```
Invite link → G-08 Join with code → (G-03 if no account) → S-01 … → S-06
```

## 5.2 The correction loop (the one that matters)

```
S-06 Home ──"Correct a paper"──→ S-10 Upload entry
                                    ├─ Photograph → S-11 Scanner → S-12 Page review
                                    └─ Upload file ───────────────→ S-12 Page review
                                                                      → S-13 Confirm identity
                                                                        → S-14 Marking in progress
                                                                          → S-15 Results overview
S-15 ⇄ S-16 Question breakdown ⇄ S-17 Question detail
S-15 → S-18 Weaknesses → S-19 Weakness detail → S-20 Practice generator → S-21 Working view
S-15 ⤴ S-06 Home  /  → S-08 Subject overview  /  → S-10 (correct another)
```

Interruption paths that must be designed:
- Leaving during S-14 → push notification on completion → deep link back to S-15.
- Failure at any S-14 stage → error state → back to S-13 (wrong identity) or
  S-12 (unreadable pages).
- Low confidence on a question in S-17 → "this isn't what I wrote" → item enters
  T-07 → teacher resolves in T-08 → student notified → S-15 shows the corrected
  mark with attribution.

## 5.3 Student daily/weekly loop

```
Push notification ──→ S-06 Home
S-06 → S-24 Study plan → S-25 Session detail
                            ├─ Practice → S-20 → S-21 → summary → S-19
                            ├─ Flashcards → S-22 → S-23 → summary
                            └─ Past paper → S-10 (correction loop)
S-06 → S-29 Leaderboards ⇄ S-30 Friends
S-06 → S-31 Profile
S-06 → S-28 Announcements & calendar
S-06 → S-26 Assigned quiz → S-27 Quiz results → S-19 Weakness detail
```

## 5.4 Teacher

```
G-04 Login → T-01 Dashboard
T-01 → T-06 At-risk list → T-05 Student detail → attempt view (S-15/16/17, teacher mode) → T-08 Remark
T-01 → T-07 Review queue → T-08 Remark ⟲ (next item) → T-07
T-01 → T-02 Classes → T-03 Roster ⇄ T-04 Analytics
                        T-03 → T-05 Student detail
                        T-04 → weakness → affected students → T-05
T-01 → T-09 Quiz builder → assign → (student receives S-26) → T-10 Quiz results
T-01 → T-11 Custom paper upload → assign / mark
T-01 → T-12 Announcement composer → (student receives S-28)
```

The teacher's most-repeated path is `T-01 → T-07 → T-08 → T-08 → T-08 → …`.
Optimise that loop above all else: it should be possible to clear twenty review
items without touching the mouse.

## 5.5 Parent

```
G-05 Phone + OTP → P-01 Children
P-01 → P-02 Child overview → P-03 Subject detail → P-04 Weaknesses
Push notification (results ready / at-risk alert) → deep link → P-02
P-01 → G-12 Notification preferences
```

Total depth from login to the answer a parent came for: two taps. Design for
that.

## 5.6 School admin

```
G-04 Login → K-01 Dashboard
K-01 → K-02 Seats → invite → (student receives G-08)
K-01 → K-03 Teachers → invite → (teacher receives G-08 equivalent)
K-01 → K-04 Classes
K-01 → G-14 Subscription status
```

## 5.7 Cross-role connections

- A **teacher's remark** (T-08) changes what the **student** sees (S-15, S-17)
  and what the **parent** sees (P-02, P-03).
- A **teacher's quiz** (T-09) becomes a student task (S-26) and feeds class
  analytics (T-10, T-04).
- A **student's result** (S-15) feeds their own dashboard, their teacher's class
  analytics, their parent's overview, their weakness profile, their study plan,
  and their XP — one event, six surfaces. Consider how a newly-arrived result is
  signalled in each.
- **At-risk flags** (T-06) can notify both the teacher and, if opted in, the
  parent (P-02).

---

# PART 6 — WHAT TO DELIVER

1. **A design direction** first, before screens: a compact token system —
   4–6 named colours with hex values and their semantic roles (including the
   confidence scale and the correct/partial/wrong scale, which are load-bearing
   here); a type system with a display face, a body face, and a numeric/utility
   face (numbers matter enormously in this product — marks, grades, boundaries —
   so choose a face with excellent figures); spacing and radius scales; and a
   named **signature element** that this product will be remembered by.
2. **The five screens that decide the product**, designed to completion, at
   380px and at desktop where applicable:
   - S-15 Results overview
   - S-14 Marking in progress
   - S-11 Camera scanner
   - S-06 Student home (both the first-run empty state and the populated state)
   - T-08 Review item — remark
3. **The cross-cutting components** (Part 2) as a documented set with all their
   states.
4. **The remaining screens** at a lower fidelity, consistent with the system.
5. **State coverage** for every screen you deliver: loading, empty, error,
   offline, and — for anything showing a mark — the low-confidence and
   teacher-corrected variants.
6. **Accessibility floor, unannounced but present**: contrast that survives a
   phone screen at night, visible keyboard focus throughout the teacher
   surfaces, touch targets sized for a tired thumb, reduced-motion respected,
   and no meaning carried by colour alone — the correct/partial/wrong and
   confidence scales especially must be distinguishable without colour.

## Constraints to check your work against

- Nothing in the student experience accuses a student of cheating.
- No screen anywhere ranks students by grades.
- Every predicted grade or boundary derived from incomplete data is visibly
  marked as estimated.
- Every mark carries its confidence, and low confidence is impossible to miss.
- A student can get from opening the app to their marks in one tap plus the
  scanning flow, at night, on a phone, tired.
