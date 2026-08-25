# Audit — `docs/LEMELY_UI_SPEC.md`

A gap audit of the product & UI specification, conducted against the spec's own
internal consistency and against the shipped implementation in `web/`, `lemely/`
and `docs/`.

**Method.** Every screen ID, exit, flow edge and component reference in the spec
was extracted mechanically and cross-referenced; every load-bearing product
claim in Parts 1–2 was checked against the API routers, the SQLAlchemy models
and the React portals. Findings marked **[verified in code]** carry a file
reference. Nothing here is a style objection — each item is something a designer
or an implementer must invent, guess at, or contradict because the spec does not
say.

**Scope note.** The spec is a design brief, and gaps in a brief are not
automatically defects: some of what follows is deliberate creative latitude. The
items are ranked by whether *leaving them open produces divergent work* — two
competent readers building different products — not by how much text is missing.

**Headline.** The spec describes 69 screens in detail but never describes how a
user moves between them outside of a linear flow: `C-13` (navigation) is one
sentence, and it is the root cause of the largest cluster of findings below.

**Counts.** 51 findings: 4 critical, 24 high, 23 medium.

---

## Contents

- [A · Navigation and reachability](#a--navigation-and-reachability) — 6 findings
- [B · Screens the product needs and the spec omits](#b--screens-the-product-needs-and-the-spec-omits) — 13 findings
- [C · State and interaction coverage](#c--state-and-interaction-coverage) — 6 findings
- [D · Contradictions and undefined vocabulary](#d--contradictions-and-undefined-vocabulary) — 9 findings
- [E · Platform reality the spec does not address](#e--platform-reality-the-spec-does-not-address) — 10 findings
- [F · Deliverable definition (Part 6)](#f--deliverable-definition-part-6) — 7 findings
- [Recommended order of resolution](#recommended-order-of-resolution)
- [What the spec gets right](#what-the-spec-gets-right)

---

## A · Navigation and reachability

### A1 · Primary navigation is undefined for every role — **critical**

`C-13` is the entire specification of navigation:

> **C-13 · Bottom navigation** (student, mobile) and **sidebar navigation**
> (teacher/admin, desktop).

Two lines, no destinations, no counts, no badge rules, no active-state model, no
statement of what is primary versus buried. For a mobile-first product this is
the most structural decision in the interface, and it is delegated by omission.
Parent navigation is not mentioned at all, despite the parent being one of five
roles with four dedicated screens.

**Consequence, verified in code.** `BottomNav` was built as specified in
`web/src/components/ui/nav-shells.tsx:69` — and is imported by no portal. The
student portal shipped a drawer with an accordion instead
(`web/src/portals/student/index.tsx`), because the student surface has more
destinations than a tab bar holds: subjects with per-subject sub-items, study
plan, practice, flashcards, leaderboard, announcements, notifications, friends,
profile, parent access, and the correct-a-paper action. The component library
carries an unused shell and the product carries an unspecified pattern; neither
outcome was chosen, both were defaulted into.

**Resolve by** enumerating the nav for each of the four surfaces: exact
destinations, order, which screens are reachable *only* from nav, badge
sources, and what happens to the primary "correct a paper" action within it.

### A2 · S-07 Subjects list is unreachable — **critical**

No screen's `Exits` line names `S-07`, and it appears in none of the seven Part 5
flow diagrams. `S-06`'s exits are `S-10, S-15, S-08, S-24, S-19, S-29, S-28,
S-26` — the dashboard routes straight past the subjects list into individual
subjects. The only possible route in is the navigation, which is A1.

The same reasoning affects `G-13` (notifications inbox), `G-15` (offline) and
`X-02`/`X-03`, which likewise have no inbound edge anywhere in the document.

### A3 · Eleven screens appear in no flow — **high**

Absent from all of Part 5: `G-06`, `G-09`, `G-10`, `G-11`, `G-13`, `G-15`,
`S-07`, `S-09`, `X-01`, `X-02`, `X-03`.

Part 5 is where the spec establishes sequence and context; a screen that appears
only in Part 4 has been described but not placed. `S-09` (paper history) is the
notable one — it is a core student surface with real content requirements, and
no flow reaches it.

### A4 · Eighteen screens declare no exits — **high**

`G-06`, `G-09`, `G-11`, `G-12`, `G-13`, `G-14`, `G-15`, `S-23`, `S-28`, `S-30`,
`P-04`, `K-01`, `K-02`, `K-03`, `K-04`, `X-01`, `X-02`, `X-03`.

Some are legitimately terminal. But **all four school-admin screens and all
three platform-admin screens** are in this list, which means those two entire
surfaces — seven screens, two roles — have no specified navigation model
whatsoever, neither exits nor nav. `K-01` explicitly offers "quick actions:
invite students, add a teacher, create a class" and names no destination for any
of them.

### A5 · No back / return convention — **medium**

Part 5's notation defines `⤴` for a return and uses it exactly once (`S-15 ⤴
S-06`). Everywhere else, transitions are one-way arrows. The spec never states
whether back is browser-history, a persistent up-affordance, or contextual.

This bites hardest on deep-linked entry, which the spec mandates: a push
notification opens `S-15` directly (§5.2), and `G-13`'s items "deep-link to
[their] subject." Neither says what "up" means from a screen you did not
navigate to.

### A6 · Settings, preferences and inbox have no entry point — **high**

`G-11` (account & devices), `G-12` (notification preferences) and `G-13`
(notifications inbox) are specified as "All" roles and have no inbound exit from
any screen. `S-31` exits *to* `G-11`, which covers the student; teachers,
parents, school admins and platform admins have no specified route to their own
account settings, and no role has a specified route to `G-13`.

---

## B · Screens the product needs and the spec omits

### B1 · Parent–child linking has no screen, in either direction — **critical**

The spec defines a parent role, a phone-OTP login (`G-05`), and four parent
screens. It never specifies how a parent becomes linked to a child. The two
places it comes up both point elsewhere:

- `P-01` states: "No children linked — explain how to link (invite from the
  child, or via the school)." Neither route has a screen.
- `G-11` lists "linked relationships (for a student: linked parents … with the
  ability to request removal)" as one line item inside a settings screen.
- `G-05` offers, on no-account-found: "Ask your child's school to link you," or
  route to a child-linking flow" — a flow that does not exist in the inventory.

**Verified in code.** The build had to add an unnumbered screen at
`/student/parents` (`web/src/portals/student/screens/Parents.tsx`), whose header
comment states the problem plainly: *"Not one of the numbered screens:
`parent_child_links` rows are created here and nowhere else, so without this
surface the entire parent portal is reachable only from a seed script."*

Without this, an entire role — one of five, with its own auth mechanism — is
undeliverable. It is the single largest omission in the document.

### B2 · Class creation has no screen — **high**

Three screens invoke it and none specifies it: `T-01` states "No classes yet
(route to class creation)", `T-02` has a "Create-class action", `K-04` says
"create". Class creation needs subject, qualification level, paper selection,
teacher assignment, and an invite mechanism — this is a form with real
decisions, not a button.

### B3 · No quiz list or assignment-management screen — **high**

The spec goes straight from `T-09` (builder) to `T-10` (results for one quiz).
There is no screen where a teacher sees their quizzes. The data model has four
quiz states (`draft`, `assigned`, `closed`, `archived` —
`lemely/db/models/enums.py:225`) and a separate assignment concept
(`quiz_assignments`, with `POST`/`DELETE` endpoints), none of which has a
surface. The build added `/teacher/quizzes`.

### B4 · Teacher-side grading console is unspecified — **high**

`T-11` covers uploading a custom paper and mark scheme. It does not cover a
teacher submitting or re-running marking on student work, yet the API supports
`POST /papers/upload`, `POST /papers/{id}/extract`, `POST /papers/{id}/grade`,
`POST /papers/{id}/regrade` and `GET /grading/queue`. The build added
`/teacher/grading` (`web/src/portals/teacher/screens/Grading.tsx`) to carry it.

### B5 · Practice results screen is referenced by a non-ID — **medium**

`S-21` exits to "S-27-style summary". `S-27` is *Quiz results* — a teacher-
assigned artefact with a class average, teacher-controlled answer visibility and
a due date, none of which applies to self-generated practice. The practice
summary is a distinct screen and has no ID, no contents and no states. Built at
`/student/practice/result/:assignmentId`.

### B6 · Print/export view has no screen — **medium**

`S-20` specifies "an export/print route, because many students will want it on
paper" — a genuinely important affordance for this market, given the whole
screen is modelled on the classified-question-set artefact. Print layout is a
design deliverable in its own right (page breaks, mark allocations, answer
space, whether the mark scheme prints). Built at `/student/practice/print/:id`
with no brief.

### B7 · No terms or privacy screen — **high**

`G-03` requires "terms acceptance" as a signup field. There is no terms screen,
no privacy policy screen, and no data-handling explanation in the 69-screen
inventory — for a product that uploads photographs of minors' handwriting to a
third-party model API, in a market with parents as a primary persona.

The build recognised the hole and added an unnumbered public `/data` page
(`web/src/portals/marketing/DataHandling.tsx`), reasoning that "the reader who
most wants to know what happens to a scan is the one deciding whether to upload
a first one."

### B8 · No help, support or contact surface — **medium**

`G-14` says activation comes with "instructions for activation (contact route)."
`G-08` tells a blocked student to "contact their school." `T-05` mentions a
"contact route if the school configures one." No contact, help or support screen
exists. For a product with a manual activation step, the support path is part of
the core funnel.

### B9 · The upload queue has no owner — **medium**

Offline upload queueing is a §1.5 platform constraint and a `G-15` element
("queued uploads shown with their queued state"), and `S-10` has "Queued/
incomplete previous upload — offer to resume it." No screen owns the list of
pending uploads, their statuses (the model has `pending`/`processing`/
`complete`/`failed`), or the retry/discard actions. The API exposes
`GET /student/uploads/active`.

### B10 · Only students get onboarding — **medium**

`S-01`–`S-03` give students a three-step onboarding. A teacher who signs up
lands on `T-01` with no classes, no students and no explanation; `T-01`'s empty
state is one clause ("route to class creation", see B2). School admins and
parents get nothing. The first-run experience is designed for one of five roles.

### B11 · Post-onboarding subject management is undefined — **medium**

`S-07` offers "an 'add or remove subjects' route back into the subject picker."
The subject picker is `S-01`, specified as "Onboarding, step 1" with "Progress
indicator across the onboarding steps." Reusing an onboarding step as a settings
screen needs either a second variant or a separate screen; the spec says
neither. *Removing* a subject is also unspecified as a consequence — what
happens to that subject's attempts, weaknesses and plan sessions.

### B12 · Attempt comparison is named but not designed — **medium**

`S-09` specifies "A comparison affordance — select two attempts to compare."
Comparing two marked papers is a non-trivial screen (which axis, aligned by
question or by topic, what happens when the two papers are different variants
with different question counts). One clause, no screen, no component.

### B13 · Forced sign-out has no state — **medium**

The three-device rule means signing in on a fourth device "quietly signs out the
oldest" (§1.5). `G-10` designs the *new* device's experience. The signed-out
device's next launch — mid-session, possibly mid-upload — has no designed state
anywhere.

---

## C · State and interaction coverage

### C1 · Half the screens declare no states — **critical**

Part 6 requires "**State coverage** for every screen you deliver: loading,
empty, error, offline." 35 of 69 screens carry no `States` line at all:

> `G-02` `G-06` `G-07` `G-09` `G-10` `G-12` `G-15` `S-01` `S-02` `S-03` `S-05`
> `S-07` `S-08` `S-18` `S-19` `S-21` `S-23` `S-25` `S-27` `S-31` `T-02` `T-04`
> `T-05` `T-06` `T-10` `T-12` `P-02` `P-03` `P-04` `K-01` `K-03` `K-04` `X-01`
> `X-02` `X-03`

The deliverable requirement and the screen specifications contradict each other:
Part 6 asks for state coverage the screens never enumerate, so the designer must
derive it, and the reviewer has no checklist to review against. `S-08` (subject
overview) and `T-05` (student detail) are dense, data-dependent screens with no
declared empty or error behaviour.

### C2 · Loading is never specified — **high**

The word "loading" appears exactly once in the document, in the Part 6
deliverables list. No screen describes a loading state, and the spec never
decides between skeletons, spinners or progressive reveal — on a product whose
own §1.5 says "processing is slow" and whose teacher screens aggregate across
whole classes.

### C3 · Three-quarters of screens declare no interactions — **high**

51 of 69 screens have no `Interactions` line. This is more consequential than it
sounds for the tabular teacher surfaces: `T-03` mandates "Sortable on every
column — teachers triage by sorting" but declares no interactions, so
multi-column sort, sort persistence, and default ordering are all unstated. The
same applies to every filter in the document (`S-09`, `S-16`, `G-13`, `T-06`,
`T-07`).

### C4 · No convention for destructive actions — **high**

The spec contains at least eight destructive actions — delete account (`G-11`),
revoke a seat "with an explanation of what happens to that student's data"
(`K-02`), remove a teacher (`K-03`), archive a class (`K-04`), remove a friend
(`S-30`), request removal of a parent link (`G-11`), delete a page mid-scan
(`S-12`), dismiss an at-risk flag (`T-06`) — and no convention for any of them.
Confirmation pattern, undo window, and irreversibility language are undefined,
and `C-11`'s state family covers empty/error/offline but not confirmation.

### C5 · No pagination model anywhere — **high**

Zero occurrences of "paginate", "load more" or "infinite" in the document. Every
list in the product is unbounded: paper history (`S-09`), notifications inbox
(`G-13`), review queue (`T-07`, explicitly worked "in batches"), class roster
(`T-03`), school seats (`K-02`), leaderboards (`S-29`). A teacher with 30
students across several classes and a term of submissions hits this on day one.

### C6 · The error family is asked for but not enumerated — **medium**

`C-11` says "Design a family, not one-offs" without listing the members. The
distinct error classes the spec itself implies — network loss, auth expiry,
validation, permission denied, quota/limit reached, upstream model failure,
missing mark scheme, unreadable pages — need different affordances (retry vs
re-auth vs contact vs change input) and are never separated.

---

## D · Contradictions and undefined vocabulary

### D1 · "Level" means three different things, and one of them is undefined — **high**

The word carries three unrelated meanings:

1. **Qualification level** — IGCSE / O-Level / AS / A-Level (`S-01`).
2. **Working level** — "an estimated working level" from placement (`S-05`),
   later used for difficulty targeting (`S-20`, `T-09`). Never defined: no
   scale, no values, no relationship to a grade.
3. **XP level** — "total XP and level" (`S-31`). No curve, no cap, no names.

**Verified in code.** The XP curve had to be invented during implementation —
`lemely/web/xp_levels.py` documents it as "the mapping D5.1 §10 deferred to
P5.8" and settles on `level N begins at 100·(N−1)² XP`, a decision with direct
motivational consequences (`S-31` asks the screen to "feel like a training log")
that the spec left to an engineer.

### D2 · The confidence scale has two incompatible namings and no thresholds — **high**

`C-4` names three levels: **confident / uncertain / needs review**. The data
model names three bands: `high` / `medium` / `low`
(`lemely/db/models/enums.py:79`). Neither the mapping nor the thresholds are
stated anywhere, and confidence is the product's stated integrity mechanism
(§1.4.1) and "the most novel component in the product."

Compounding this, `S-15`'s own example copy collapses three tiers into two:
*"We're confident about 19 of 21 questions. Two are waiting for your teacher to
check."* — leaving no phrasing for the middle tier, which is precisely the tier
that needs student-facing language.

### D3 · "Estimated" is binary in the spec and three-valued in the product — **high**

§1.4.6 ("Never invent precision") and `C-1`/`C-3` provide a single "estimated"
treatment. Boundary provenance in the model has three tiers: `exact`,
`subject_default`, `global_default` (`lemely/db/models/enums.py:95`).

A boundary taken from the same subject's history and one taken from a global
default are materially different claims about how much to trust a predicted
grade, and the spec gives them identical styling — which is the failure mode
§1.4.6 exists to prevent.

### D4 · S-30 requires a state the model deliberately does not have — **medium**

`S-30`'s states are "Empty; request pending; blocked/removed." The friendship
model has exactly two states, `pending` and `accepted`, and the code documents
the exclusion as deliberate: *"there is no `declined`/`blocked` state … a
decline, a cancel and an unfriend are all the same database act"*
(`lemely/db/models/enums.py:189`). Either the spec is asking for blocking — a
real safety feature with real UI — or it is loose wording. As written it is
unbuildable.

### D5 · G-12 specifies a notification type that does not exist — **medium**

`G-12`'s toggle list includes "weekly summary". `NotificationType` has five
values and no `weekly_summary`. **Verified in code**, and already flagged
independently by the implementation: `web/src/lib/notificationTypes.ts:17` —
*"UI spec §G-12 also lists a 'weekly summary' toggle. There is deliberately no
`weekly_summary` member here: the enum has exactly five values, no column, no
sender and no row, and offering a switch that gates nothing is what UI spec §1.4
forbids."* Either the feature is in scope and unbuilt, or the toggle should go.

### D6 · The student dispute path is specified end-to-end and exists nowhere — **high**

Three parts of the spec describe it:

- `S-17`: "an 'this isn't what I wrote' affordance that routes the question into
  the teacher review queue."
- `T-07`: lists "student disputed the transcription" as one of four queue
  reasons.
- §5.2: an explicit interruption path — dispute → `T-07` → `T-08` → student
  notified → `S-15` shows the corrected mark.

**Verified in code**, there is no `ReviewReason` value for it and no creation
path. `web/src/portals/teacher/screens/Review.tsx:47` records this as a
spec-vs-backend gap: *"the spec's fourth T-07 reason category — 'student
disputed the transcription' — has no backing `ReviewReason` value or creation
path anywhere in this codebase … labelling it 'student disputed' would be
inventing a meaning the backend doesn't assert."*

This matters more than the other enum gaps: it is the student's only recourse
against a misread, and §1.4.1 makes that recourse the product's "main defence
against being wrong."

### D7 · Multi-role support is asserted but never specified — **medium**

§1.2 states a student can hold a school seat and a personal subscription
simultaneously, and a teacher can be independent, attached to a school, or both.
`C-12` provides a role switcher. The spec never enumerates which role
combinations are possible, what switching does to in-progress context, whether
notifications are per-role, or which home a multi-role user lands on at login —
though `G-04` requires login to route to exactly one of five role homes.

### D8 · Screen titles disagree between the inventory and Part 4 — **medium**

Seven screens are named differently in the Part 3 table and their Part 4
heading:

| ID | Part 3 table | Part 4 heading |
|---|---|---|
| `G-03` | Sign up — student/teacher details | Sign up — details |
| `G-09` | Install app prompt (PWA) | Install app prompt |
| `S-01` | Student onboarding — subjects | Onboarding, step 1: subjects |
| `S-02` | Student onboarding — questionnaire | Onboarding, step 2: questionnaire |
| `S-03` | Student onboarding — placement invite | Onboarding, step 3: placement invite |
| `S-09` | Paper history (per subject) | Paper history |
| `S-10` | Upload — entry / choose method | Upload — entry |

Minor individually; collectively they mean the inventory cannot be used as a
canonical name list, which is exactly what a 69-screen index is for.

### D9 · How a mark was produced is invisible — **medium**

`MarkerSource` distinguishes `deterministic`, `ai` and `missing`
(`lemely/db/models/enums.py:87`). `S-17`'s entire purpose is "Explain the mark.
This is where trust is won or lost" — and the spec never asks the screen to
distinguish a mark computed deterministically against the mark scheme from one
inferred by a model. These carry very different warrants, and the distinction is
free: the product already knows it.

---

## E · Platform reality the spec does not address

### E1 · Push unavailability has no design, and it is not the same as denial — **high**

The core loop depends on push. `S-14`: "A clear statement that they can leave and
will be notified when it's done — with a button that does exactly that." `G-12`
covers one failure mode: "if the browser has denied push, show that clearly."

It does not cover push being unavailable *on the deployment* — no VAPID keys, no
transport. **Verified in code**, this is the build's actual shipping state and
is documented as a first-class case: `web/src/lib/notificationTypes.ts` —
*"`available: false` is a **first-class, designed state**, not a failure … It is
distinct from the browser having denied permission, and G-12 must show the two
differently."*

The spec has no fallback for `S-14` when notification is impossible, which is
the difference between "leave, we'll ping you" and "keep this tab open."

### E2 · The install prompt is ordered after the moment it is needed — **high**

`G-09` fires "after the first successful marking, not on first load — ask when
the value has been proven." Sound reasoning, but on iOS web push requires an
installed PWA. So for iOS users the first marking — the one the entire
onboarding funnel exists to produce, and the one `S-14` promises to notify them
about — is precisely the one that cannot notify them.

`G-09` and `S-14` need reconciling: either the prompt moves earlier for iOS, or
`S-14` needs a designed no-notification variant (see E1).

### E3 · No timezone or day-boundary definition — **high**

Streaks (`C-9`, `S-31`), "due today" counts (`S-22`), study-plan days (`S-24`),
quiz due dates (`S-26`) and the weekly leaderboard reset (`S-29`) all depend on
when a day ends. The spec never says — device local, account, school, or a fixed
market timezone.

**Verified in code**, this had to be decided during implementation and is
non-trivial: `lemely/web/routers/student.py:826` notes the day boundary uses
`civil_date_in_zone` because *"Cairo is UTC+3 in summer, so a hardcoded offset is
wrong for half the year."* For a streak mechanic the spec calls "real motivation
infrastructure for a stressed teenager," breaking a streak on a timezone
technicality is a product failure.

### E4 · Dark mode is never decided — **high**

Zero mentions of dark mode, light mode, theme or `prefers-color-scheme` in the
entire document — for a product whose defining design moment is stated as
"**tired, at night, on a phone, wanting a number**," and whose accessibility
floor asks for "contrast that survives a phone screen at night."

Whether the token system needs one palette or two is a foundational decision
that Part 6 item 1 asks the designer to deliver without telling them which. The
build shipped light-only by default.

### E5 · No accessibility conformance target — **high**

Part 6 item 6 asks for an "accessibility floor" in prose: contrast that survives
a night-time screen, visible focus, "touch targets sized for a tired thumb,"
reduced motion, no meaning by colour alone. It names no standard, so "sized for
a tired thumb" has no number.

**This ambiguity has already had a measured consequence.** `DELIVERY.md` records
the touch-target outcome as WCAG **AA (24px) met, AAA (44px) not met** — a gap
"deferred at Phase 2.5" precisely because the requirement was qualitative. Name
the level (AA is the defensible floor; 44px targets are worth specifying
explicitly for the scanner and review-queue screens regardless).

### E6 · One breakpoint is not a responsive specification — **high**

§1.5 gives "380px baseline and scale up"; §4.7 says teacher screens are
"desktop-first … but must remain usable on a tablet"; Part 6 asks for delivery
"at 380px and at desktop where applicable." No breakpoint set, no container max
width, no definition of "desktop" or "tablet" in pixels.

The teacher surfaces are the acute case: `T-03` and `T-02` are wide sortable
tables and `T-04`'s centrepiece is a topic × student heatmap. How those reflow
between a 1440px laptop and a tablet is the hardest layout problem in the
product and gets one clause.

### E7 · Weakness-chip granularity is uneven across the three launch subjects — **high**

`C-5` is a topic tag with a severity weight, exemplified as "Circle theorems",
"Units in calculations" — and it "appears in dozens of places."

**Verified in `lemely/data/syllabus_topics.json`**, the taxonomy is not uniform:

| Subject | Topics | Subtopics |
|---|---|---|
| 0580 Mathematics | 9 | ~70 (e.g. "Circle theorems I") |
| 0625 Physics | 6 | ~25 (e.g. "Momentum") |
| 0606 Additional Mathematics | 14 | **none** |

The source file states the reason for 0606: *"0606 numbers its learning
objectives, not named subtopics, so this taxonomy is topic-level only — the
classifier will never emit a 0606 subtopic label."*

So one of three launch subjects produces chips like "Calculus" and "Series"
where the others produce "Circle theorems I" and "Momentum". Every example in
the spec is drawn from 0580. `S-18`'s motivating copy ("Start with circle
theorems — it's cost you 14 marks across three papers") does not have an
equivalent shape in Additional Mathematics, and the chip component must handle
both a 3-word label and a 40-character one.

### E8 · Mathematical notation rendering is called a constraint and then dropped — **high**

`S-04` states it outright: "maths notation and diagrams must render properly —
this is a real design constraint, not a detail." The requirement then recurs in
`S-17` (question stem plus mark scheme extract), `S-21`, `S-26`, `T-08` and
`T-09` — and is never specified again. No rendering approach, no treatment of
diagrams and graphs from scanned papers, no failure state when a stem will not
render, no guidance on how notation behaves at 380px where a wide equation
cannot wrap.

### E9 · The scanner's feature set is unphased — **medium**

`S-11` and `S-12` together specify: edge-detection overlay, real-time framing
guidance ("Move closer", "Too dark"), torch toggle, per-page retake, rotate,
crop, drag-to-reorder, blur/darkness detection with warning badges, and 25MB
compression handling.

That is a substantial engineering programme presented as one screen's contents,
with no P1/P2 split. **Verified in code**,
`web/src/components/CameraCapture.tsx` ships live capture, a thumbnail strip and
client-side PDF assembly — no torch, no edge detection, no framing guidance, no
crop/rotate/reorder, no blur detection. Because the spec states all of it flatly
as "Contains", the shortfall reads as failure rather than sequencing. Mark which
elements are launch-critical (`S-11` "carries an outsized share of the product's
perceived quality", so this matters).

### E10 · Re-marking has no student-facing state — **medium**

`POST /papers/{paper_id}/regrade` exists and the teacher console uses it. `S-15`
has states for teacher-overridden and partial results but none for "this result
is being re-marked" or "this result was re-marked by the system" — distinct from
a teacher correction, which `S-15` does cover.

---

## F · Deliverable definition (Part 6)

### F1 · No copy deck, though the spec sets voice rules — **high**

§1.7 sets a clear voice and Part 4 contains dozens of specimen strings ("2 marks
from an A", "we're not certain about this one — your teacher will check",
"Nothing yet — we'll tell you when your marks are ready"). Part 6 lists five
deliverables and a copy deck is not among them, so ownership of every other
string in the product — every error, every empty state, every confirmation — is
unassigned. For a product where §1.4.2 turns on *phrasing* ("worth a look", never
"CHEATING DETECTED"), copy is a correctness surface, not a polish pass.

### F2 · No motion specification — **medium**

Two mentions: "Resist a fake progress bar … a smooth lying animation" (`S-14`)
and "reduced-motion respected" (Part 6). No duration scale, no easing, no
transition model between screens — on a product with a multi-stage streamed
progress screen (`C-10`), a card-reveal flashcard interaction (`S-23`) and a
camera capture rhythm (`S-11`) that the spec explicitly asks not to interrupt.

### F3 · No icon, illustration or empty-state art direction — **medium**

The spec requires illustrated content in at least three places — `S-10`'s "how to
get a good scan" guide "with illustrations", `G-09`'s iOS share-sheet route which
"must be illustrated", `C-11`'s state family — and never names an icon set, an
illustration style, or who produces them. §1.6 rules out "cartoon mascots"
without saying what replaces them.

### F4 · No data-volume assumptions — **medium**

§1.2 sets the teacher's problem as "which of my 30 students is drowning", but no
screen states expected volumes: attempts per student per term, questions per
paper (`S-16` says "long papers" without a number), classes per teacher, review
items per day, friends, decks. Density decisions on the tabular surfaces cannot
be made without these, and they determine whether C5's pagination is needed at
launch.

### F5 · The signature element has no acceptance criteria — **medium**

Part 6 item 1 asks for "a named **signature element** that this product will be
remembered by" — the most subjective deliverable in the list, with no criteria,
no examples of what would and would not qualify, and no review gate. §1.6 points
at confidence as "the place to spend your boldness", which may be the intended
answer; if so, say it.

### F6 · RTL preparation is asserted without requirements — **medium**

§1.5: "English only. Left-to-right. Arabic is a later phase — but choose type and
layout that won't have to be thrown away when RTL arrives." No requirement
follows: no mandate to use logical properties over physical ones, no mirroring
rules for the boundary bar or trend sparkline (directional components whose
meaning is tied to reading order), no policy on numerals — Arabic-Indic versus
Western digits — in a product whose entire visual identity is built on figures.

The build did adopt logical properties (visible in
`web/src/portals/student/index.tsx`, which annotates the choice), but that was an
implementer's inference, not a stated requirement.

### F7 · The spec has no version, owner or revision history — **medium**

No date, no version number, no named owner, no changelog. It is described as
"a complete design brief … Everything here is a decision already made by the
product owner," which makes it a contract — and it is already out of sync with
the build in the ways catalogued above, with no mechanism to record that.

At minimum: a version line, a last-reviewed date, and a section at the end
recording accepted deviations.

---

## Recommended order of resolution

**Resolve before any further design work** — these change screen inventories and
information architecture:

1. **A1** — specify navigation for all four surfaces. Unblocks A2, A3, A6.
2. **B1** — design parent–child linking. An entire role is currently
   undeliverable without it.
3. **D6** — decide whether the student dispute path is in scope. It is named in
   three places and exists in none; §1.4.1 leans on it heavily.
4. **C1** — enumerate states per screen, or drop Part 6's state-coverage
   requirement to match. As it stands the two contradict.

**Resolve before token and component design** — these change the design system:

5. **E4** dark mode · **E5** accessibility target · **E6** breakpoint set ·
   **D2** confidence naming and thresholds · **D3** the three-tier estimated
   scale.

**Resolve before the teacher and admin surfaces are drawn:**

6. **A4** (K/X navigation) · **B2** class creation · **B3** quiz list ·
   **C5** pagination · **F4** data volumes.

**Fold into the next revision:**

7. Everything else, plus **F7** — put a version and a deviation log on the
   document so this audit has somewhere to land.

---

## What the spec gets right

Recording this because an audit that lists only gaps misrepresents the document.

- **The product principles (§1.4) are genuinely load-bearing** and survive
  contact with implementation. "Flags are signals, not verdicts", "grades are
  private; effort is public" and "never invent precision" each translate into
  specific, checkable UI constraints, and the closing "Constraints to check your
  work against" turns them into a testable list. Most specs cannot do this.
- **The screen inventory is complete and consistent.** All 69 screens in the
  Part 3 table have a Part 4 section and vice versa; no referenced ID is
  undefined. That is rare at this size and is what made a mechanical audit
  possible at all.
- **The visual direction (§1.6) is unusually well-aimed** — grounding the
  identity in examiner grammar, and explicitly ruling out both the ed-tech
  defaults and the current AI-design defaults, gives a designer something to
  push against rather than a mood board.
- **The five priority screens in Part 6 are the right five**, and naming
  `T-01 → T-07 → T-08 → T-08 → …` as the loop to optimise "above all else" is
  the kind of instruction that changes what gets built.
- **§1.3's core-loop narrative** does more work than any requirements list would,
  and "tired, at night, on a phone, wanting a number" is a usable design test.

The gaps above are overwhelmingly gaps of *omission at the seams* — navigation,
cross-screen state, and the boundary between the brief and the data model — not
errors of judgement in what the document does cover.
