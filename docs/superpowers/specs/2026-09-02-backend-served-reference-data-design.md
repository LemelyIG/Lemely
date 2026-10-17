# Backend-served reference data

## Purpose

Student onboarding asks a new student which subjects they are studying. Those
options are hardcoded in the frontend
(`web/src/portals/student/screens/onboarding/onboardingData.ts`), and so is
everything around them: papers, confidence topics, grade vocabulary,
qualification levels, session months and difficulty bands. This design moves
all of it to the backend and serves it from one endpoint.

Three rules from the product owner govern the work:

1. **The frontend must not contain hardcoded data.**
2. **Nothing lands on local disk — DB or GCS only.** For this design that means
   the curriculum and grade data currently read from bundled JSON at request
   time moves into Postgres.
3. **Every decision is resolved here.** This spec has no open questions
   section; where a question arose it was put to the product owner and the
   answer is recorded as a decision below.

## Current state

### The catalogue is frontend-owned

`onboardingData.ts` declares `SUPPORTED_SUBJECTS` — three subjects (0625
Physics, 0580 Mathematics, 0606 Additional Mathematics) with their papers and
the first three top-level syllabus topics used by the S-02 confidence step. Its
own docstring admits it is a mirror, transcribed because "there is no
student-facing route that serves this structural data".

Nine modules import it. Onboarding uses the full shape (`SubjectsStep.tsx`,
`QuestionnaireStep.tsx`, `Onboarding.tsx`); seven others use it only to turn a
syllabus code into a display name (`PracticeGenerator`, `PracticeResult`,
`FlashcardDecks`, `FlashcardReview`, `PlacementInvite`, `PlacementResult`,
`StudyPlanWeek`, `StudyPlanSession`).

### The backend's copy is on disk

`subjects` (`db/models/academic.py:16`) holds only `code`, `name`, `board`.
Everything else is bundled JSON read on the request path through `@lru_cache`'d
loaders:

- `data/paper_timing.json` — paper number, name, duration, marks, practical
  flag, provenance. Read by `io.paper_timing.get_paper_timings`, consumed by
  `placement_repo.py:409`.
- `data/syllabus_topics.json` — the topic tree plus the `strong`/`keywords`
  matching vocabulary the deterministic classifier uses. Read by
  `io.syllabus_topics.get_taxonomy`, consumed by `question_bank_repo.py:287`
  and `:1022`, `placement_repo.py:510`, `practice_repo.py:826`,
  `attempt_repo.py:425` — all per-question code paths.
- `data/grade_boundaries.json` + `grade_boundaries_provenance.json` — 347
  component threshold records across 36 CAIE PDFs. Read by
  `GradeBoundaryStore`, wired at `deps.py:65` and used by the student, parent,
  admin, review and grading paths. **Grades are computed from a bundled file.**

### Frontend constants mirroring backend truth

| Frontend | Backend source | Copies |
|---|---|---|
| `GRADE_ORDER` | `core.history.GRADE_ORDER` | 6, mutually inconsistent |
| `QUALIFICATION_LEVELS` | `enums.QualificationLevel` | 1 |
| `SESSION_MONTHS` | `enums.SESSION_MONTH_LABELS` | 1 |
| `DIFFICULTY_BANDS` / `BAND_ORDER` | `core.difficulty._BANDS` | 2 |

The grade copies are `Quizzes.tsx:86`, `ClassRoster.tsx:68`,
`AtRiskList.tsx:71`, `onboardingData.ts:92`, `GRADES` in `QuizBuilder.tsx:126`
and the `Grade` union in `lib/types.ts:12`; `components/ui/grade-badge.tsx:16`
carries a seventh, wider set including F and G.

### What is already correct

No hook passes `fallback` to `request()`; every file under `lib/hooks/`
documents that rule. This design does not weaken it — an unreachable reference
endpoint produces an error state, never a bundled default.

## What the grade data actually says

This was investigated rather than assumed, because three sources disagreed.
The evidence, in order of authority:

**The official document.** `0625_s24_gt.pdf` prints, verbatim:

> Grade A\* does not exist at the level of an individual component.

Its component table is headed `Maximum raw mark A B C D E F G`, with an en
dash where a grade is not available at that tier. It then carries a **second**
table — "The overall thresholds for the different grades were set as follows" —
headed `Option Maximum mark after weighting / Combination of components / A* A
B C D E F G`, with rows such as `BX 200 21, 41, 51 144 119 94 70 63 56 50 44`.

**Our own ingested data.** 347 component records across 36 CAIE PDFs, three
subjects and many sessions, parsed by a regex that explicitly supports `A*`
(`[A-Z]\*?`) — and not one carries A\*. 0580 and 0625 each split into Core
components (C–G) and Extended components (A–E or A–G); 0606 is single-tier.

**A third-party index.** ciegt.pooruli.com's component table is likewise headed
`A B C D E F G` with no A\* column.

So A\* is a **syllabus-level aggregate** awarded on a weighted option (three
components together), never on one paper. Lemely marks one paper. Every
consequence below follows from that fact.

## Decisions

**D1 — The database is the source of truth; the bundled JSON is retired.** A
migration backfills from the JSON, the files are deleted, and the `io/` loaders
read Postgres. Adding a subject becomes a database write rather than a deploy.
Rejected: keeping JSON as the transcription source and projecting it into the
DB, which preserves git-diffable provenance but leaves the DB a derived copy.

**D2 — Provenance survives as NOT NULL columns.** Every syllabus and threshold
fact in this repo can name the document it came from, and `ExamDate.source` is
NOT NULL for exactly that reason. `source_document`, `source_url` and
`syllabus_version` are NOT NULL on the paper and threshold tables.

**D3 — No display-order column.** Ordering is by `code`. This changes S-01's
card order from Physics-first to 0580/0606/0625; D9 removes the behaviour that
depended on the old order.

**D4 — One reference endpoint.** `GET /api/reference` returns the catalogue and
every enumeration the UI needs in one response: one round trip, one cache key,
one hook, and one place the "no hardcoded reference data" gate can point at.

**D5 — The confidence-step topic count stays a UI decision.** The endpoint
returns every top-level topic; S-02 renders the first three
(`CONFIDENCE_TOPICS_SHOWN = 3`), preserving today's behaviour. 0606 has
fourteen, so returning all and slicing in the UI keeps a curriculum fact
separate from a display choice.

**D6 — Glyphs, dial codes and celebration thresholds stay in the frontend.**
`subjectIcon`, `COUNTRIES` and `MILESTONE_LADDER` are presentation with no
backend counterpart; inventing one would be worse. `subjectIcon` already falls
back to a generic glyph for an unknown code, which is what a fourth catalogue
subject will hit.

**D7 — Awarded and target grades are different vocabularies.**

- **Awarded grade** — what Lemely computes for one marked paper. Its vocabulary
  is *derived per paper* from that component's own threshold record: exactly
  the grades that record defines, plus `U`. Nothing is hardcoded, an IGCSE Core
  paper correctly tops out at C, and A\* is correctly unreachable, because CAIE
  says it does not exist at component level.
- **Target grade** — what a student picks in S-01, a syllabus-level aspiration.
  Its vocabulary is derived per `(subject, tier)` from the option threshold
  tables (D8), which is where A\* is published — and it is keyed by subject on
  the wire, not merely by qualification level, because 0580 Extended and 0625
  Extended genuinely differ. Measured from the official
  documents rather than assumed, the vocabularies differ by subject as well as
  tier: 0580 Core options publish C–G with no A\*, 0580 Extended options publish
  A\*–E with no F/G, 0625 options publish A\*–G, and 0606 options publish A\*–E.
  A generic per-qualification rule would have got two of those four wrong.

This resolves the six-way `GRADE_ORDER` disagreement: `core.history.GRADE_ORDER`
was neither wrong nor complete — it was the A-Level/O-Level target vocabulary
applied everywhere.

**D8 — Grade boundaries are in scope, ingested from ciegt and verified against
the official PDFs.** Originally deferred; pulled in because D7 cannot be
implemented without them.

*Component thresholds* come from ciegt.pooruli.com's data route,
`/{qual}/{syllabus}/__data.json` — a SvelteKit devalue payload with one row per
component per session carrying raw marks and `max` (`-1` where CAIE prints an
en dash). That is 1,354 rows for our three subjects across ~50 sessions back to
2011, against the 350 the retiring JSON holds.

*Option thresholds* — the syllabus-level table where A\* actually lives — come
from the official Cambridge grade-threshold PDFs on papacambridge, which the
product owner confirms as official Cambridge documents.

*Every ciegt row is checked against the PDF for its session*, which the ingest
has already downloaded and parsed for the option table. Only grades the
official component table publishes are kept; where a value differs, the
document wins. Rows whose PDF is missing or unparseable are still stored, but
flagged unverified and filtered by the weaker `≤ 0 raw marks` rule instead.

**Fidelity was measured, not assumed.** 57 component records were compared
against the official PDFs before this was designed:

- 51 matched exactly — 0625 M/J 23, 0625 O/N 23 and 0580 M/J 24 were 19/19,
  19/19 and 13/13 with zero differences.
- 6 differed, all in 0606 M/J 24, where ciegt carries F and G that the document
  does not publish — and 0606's *option* table publishes A\*–E too, so the
  fabrication is not merely a tier artefact. It is systematic: 216 of ciegt's
  230 0606 rows carry A–G.
- 124 of the 1,354 rows carry a threshold of ≤ 0 raw marks.

Verification removes all of these. It is affordable precisely because the same
PDF carries both tables, so the option fetch pays for the component check.

**A formulaic-looking threshold is not evidence of fabrication.** The 2012
document states: "G is set as many marks below the F threshold as the E
threshold is above it." Cambridge derives G by formula itself. What convicts
ciegt's 0606 rows is that the document publishes no F or G *column* at all —
which is why the check is "does the document publish this grade", never "does
this number look derived".

**D9 — The student chooses their placement subject.** S-02 ends with a step
listing every enrolled subject and its availability, and the student picks.
This replaces `placementInviteSubject`'s "first subject in catalogue order",
which under D3's `code` ordering would have sent a multi-subject student to
0580 — a subject with no placement questions — instead of the Physics test they
get today. `GET /api/placement/{subject_code}/availability` already exists and
returns `PlacementAvailabilityDTO`, so this needs no new backend route.

**D10 — A subject carries its qualification level; onboarding stops asking.**
0580, 0606 and 0625 are all IGCSE syllabuses, yet the wizard lets a student
select "A-Level Physics 0625", a combination that does not exist. The catalogue
records each subject's level, S-01 displays it, and both the profile-wide
picker and the per-subject override are removed. The enrolment keeps its
`qualification_level` column, populated from the catalogue at write time, so
historical records stay meaningful if a subject's level ever changes. O-Level
and A-Level subjects arrive later under their own syllabus codes.

## Data model

Migration `0024_reference_data`.

### `subjects` (altered)

Add `active BOOLEAN NOT NULL DEFAULT true` — `papers.subject_code` is a foreign
key to `subjects.code`, so ingesting a fourth subject's past papers would
otherwise offer that subject in onboarding as a side effect. Add
`qualification_level` (D10) and `syllabus_version`.

### `syllabus_papers` (new)

One row per paper a syllabus defines. Named `syllabus_papers` because `papers`
already means "an ingested past-paper instance" keyed by session and variant.

`id`, `board`, `subject_code` → `subjects.code`, `paper_number`, `name`,
`tier` (`core` | `extended` | null for untiered subjects such as 0606),
`duration_minutes`, `total_marks`, `practical`, and NOT NULL
`source_document` / `source_url` / `syllabus_version`. Unique on
`(board, subject_code, paper_number)`.

`tier` is required by D7's target vocabulary. It is taken from the paper name
("(Core)" / "(Extended)") and corroborated by the threshold data, where Core
components carry an en dash under A and B.

### `subject_topics` (new)

The full topic tree, because the classifier's vocabulary moves here when the
JSON is retired. `id`, `board`, `subject_code`, `parent_id` (self-FK; null =
top level), `code`, `name`, `strong` jsonb, `keywords` jsonb. Unique on
`(board, subject_code, code)`.

`strong` and `keywords` are Lemely's authored matching vocabulary, not syllabus
content — `syllabus_topics.json`'s own header says so. They are stored because
the classifier needs them and are **excluded from every DTO**.

### `component_thresholds` (new)

One row per component per session — what `grade_boundaries.json` holds today,
at four times the coverage. `id`, `board`, `subject_code`, `session_month`,
`session_year`, `paper_number`, `paper_variant`, `max_mark`, `thresholds` jsonb
(grade → raw mark), `verified` bool, and NOT NULL `source_url`. Unique on the
identity tuple.

`verified` is the honest half of D8: true means every grade in `thresholds` is
one the official PDF publishes, and `source_url` names that PDF; false means
the PDF was missing or unparseable, the row came from ciegt alone, and only the
`≤ 0` filter was applied. Consumers may ignore the flag, but nothing may claim
Cambridge as the source of an unverified row.

Storing raw marks with `max_mark` rather than pre-computed percentages keeps
every stored number one a human can check against the document — the same rule
`paper_timing.json` follows for duration and total marks. `GradeBoundaryStore`
computes percentages at read time.

### `option_thresholds` (new)

The syllabus-level table, and the only place A\* exists. `id`, `board`,
`subject_code`, `session_month`, `session_year`, `option_code` (e.g. `BX`),
`component_numbers` jsonb (e.g. `[21, 41, 51]`), `max_mark_after_weighting`
(**nullable** — the pre-2020 layout omits the column), `thresholds` jsonb, and
NOT NULL `source_url`.

D7's target vocabularies are derived from this table. Nothing else reads it:
awarding a real A\* means marking every component of an option and applying the
weighting, which Lemely does not do.

### Backfill

The migration inserts subjects, papers and topics from the two retiring JSON
files, then deletes them. Papers are inserted including practicals —
`get_paper_timings` excludes 0625's Papers 5/6 by default, but S-01 lists all
six, so the table holds them all and the practical filter moves into the query.

Thresholds are **not** backfilled from `grade_boundaries.json`, because that
file holds percentages rather than raw marks. They are ingested from ciegt
(below) and the JSON is deleted once the ingested set covers it — which it
does, at 1,354 rows against 350.

## Backend changes

### The reference endpoint

`GET /api/reference` in a new `lemely/web/routers/reference.py`, authenticated
for any role via `get_auth_context`, mounted in `app.py`.

```jsonc
{
  "subjects": [{
    "code": "0625", "name": "Physics", "board": "caie",
    "qualificationLevel": "igcse",
    "papers": [{ "number": 1, "name": "Multiple Choice (Core)", "tier": "core", "practical": false }],
    "topics": ["1 Motion, forces and energy", "2 Thermal physics"]
  }],
  "targetGradeVocabularies": [
    { "subjectCode": "0625", "qualificationLevel": "igcse", "tier": "extended",
      "grades": ["A*","A","B","C","D","E","F","G","U"] },
    { "subjectCode": "0580", "qualificationLevel": "igcse", "tier": "extended",
      "grades": ["A*","A","B","C","D","E","U"] },
    { "subjectCode": "0580", "qualificationLevel": "igcse", "tier": "core",
      "grades": ["C","D","E","F","G","U"] }
  ],
  "qualificationLevels": [{ "value": "igcse", "label": "IGCSE" }],
  "sessionMonths": [{ "value": "may_june", "label": "May/June" }],
  "difficultyBands": ["foundation", "standard", "challenge"]
}
```

Subjects come from the new tables, filtered to `active`, ordered by `code`.
Enumerations come from the existing Python/Postgres enums — they are schema,
not rows, and need no tables. Topics serialise as `"<code> <name>"`, the
vocabulary `ConfidenceRating.topic` and the weakness engine already use; the
frontend must never compose that string.

There is no `gradeOrder` field. Awarded grades are per-paper (D7) and travel
with the result DTO that reports them, not with the reference data.

An empty `subjects` array returns 200 honestly. No bundled fallback.

DTOs follow house style: an explicit `ApiModel` subclass per DTO, camelCase
names declared directly, no alias generator.

### Rewired loaders

`io.paper_timing` and `io.syllabus_topics` keep their public names and return
types, so their call sites are unchanged in shape, but read Postgres and take a
session.

`get_taxonomy` is called **per question** — `question_bank_repo.py:1022`
backfills the entire bank through it. Replacing an `@lru_cache`'d file read
with an uncached query would turn one file parse into N round trips. The
taxonomy is immutable for the life of a request, so it is cached per process
with an explicit invalidation hook the ingest and seeding paths call.

`GradeBoundaryStore` reads `component_thresholds` and computes percentages from
`raw / max_mark` at read time, preserving its current interface and its
exact/subject-default/global-default fallback chain.

### Threshold ingestion

A new `scripts/ingest_thresholds.py`, replacing
`scripts/ingest_grade_boundaries.py`:

1. **Index and rows from ciegt.** One request per syllabus to
   `https://ciegt.pooruli.com/{qual}/{syllabus}/__data.json`. Decode SvelteKit's
   devalue format — a flat pool where a number *inside* an object or array is an
   index into that pool and a number *in* the pool is a literal; the rows live
   under the node carrying a `table` key. Map each `session` label (`"M/J 24"`)
   to `(session_month, session_year)` and each `component` (`"11"`) to
   `(paper_number, paper_variant)`.
2. **The official PDF per (syllabus, session)**, at
   `…/upload/{code}_{session}_gt.pdf`.
3. **Parse both tables.** The component parser is reused unchanged — it already
   handles both CAIE header layouts and the en-dash convention. The option
   parser is new and needs the same two-layout treatment: `Option A* A B C D E F
   G` (pre-2020, no max column) and `Option mark after A* A B C D E F G`
   (current, with max after weighting). Verified against 0625 s19/s24, 0580 w17
   and 0606 s21.
4. **Verify and write.** Keep only component grades the PDF publishes; store
   options as parsed; mark rows `verified`. A session whose PDF 404s or resists
   parsing — the pre-2014 documents carry a watermark that bleeds into the text
   layer and breaks line-based parsing — is stored unverified with the `≤ 0`
   filter.

Politeness is kept as the existing script has it: a descriptive User-Agent,
sequential requests, and a delay between them. This is one small site and one
document host.

### Seeding

`seed_reference_data` becomes an upsert over the catalogue tables, still
idempotent. `DEMO_SUBJECTS` is renamed `CATALOGUE_SUBJECTS` — it seeds
reference data, not demo data. `web/e2e/global-setup` must ensure the catalogue
exists, or `phase4-journey` and `signup` fail at S-01.

## Frontend changes

### New

- `lib/referenceTypes.ts` — interfaces mirroring the DTOs, following
  `meTypes.ts`'s convention.
- `lib/hooks/useReferenceApi.ts` — `useReference()` on key `["reference"]` with
  a long `staleTime`, plus `useSubjectName(code)` returning `name ?? code`,
  the exact expression the seven lookup screens use today.
- `lib/grades.ts` — `gradeRank(grade, vocabulary)` returning the index within
  the given vocabulary and `vocabulary.length` for anything unrecognised, so an
  unknown grade sorts **last**. The four deleted `GRADE_ORDER` copies are all
  `indexOf` sort keys returning `-1`, which today sorts a Core-tier F *ahead of*
  an A\* (`AtRiskList.tsx:92`, `ClassRoster.tsx:85`, `Quizzes.tsx:99`).

### Deleted

`SUPPORTED_SUBJECTS`, `GRADE_ORDER` (all six), `GRADES`, `SESSION_MONTHS`,
`DIFFICULTY_BANDS`, `BAND_ORDER`, and `lib/qualificationLevels.ts`'s table
(`qualificationLevelLabel` stays, taking the fetched table as an argument).
`grade-badge.tsx`'s local union is replaced by the served vocabulary.

### Changed with care

- **`Onboarding.tsx`'s draft-seeding effect** filters existing enrolments
  against the catalogue and must wait for it to arrive; seeding against an
  empty catalogue silently drops every saved enrolment for a resuming student.
- **`SubjectsStep.tsx`** loses both qualification-level controls (D10), gains
  loading and error states, and its footer copy — which hardcodes "Mathematics
  0580, Additional Mathematics 0606 and Physics 0625 are the ones we can mark"
  — derives from the fetched list.
- **The target-grade picker** offers only the vocabulary for that subject's
  `(qualificationLevel, tier)`, where tier follows from the papers ticked.
- **`QuestionnaireStep.tsx`** gains D9's placement-choice step, reading
  availability per enrolled subject.

## Testing

**Backend.** Router tests for shape, the `active` filter, `code` ordering, 401,
and an empty catalogue returning `[]`. Migration tests asserting the backfill
reproduced exactly what the retiring JSON held — the one chance to prove
nothing was lost. Loader tests proving the rewired `get_paper_timings` and
`get_taxonomy` return what the JSON-backed versions did, reusing
`tests/test_topics.py` and `tests/test_placement_assembly.py`'s assertions
against DB fixtures. Ingest tests against captured fixtures — a ciegt payload plus one PDF per
layout era (0625 s24 and 0625 s19): devalue decoding, the session and component
mappings, both option-header layouts, and the nullable max-mark column. The
verification test is the load-bearing one: given ciegt's real 0606 M/J 24 row
(`A–G`) and the real PDF (`A–E`), the ingested row must come out as `A–E`, with
the fabricated `F` and `G` dropped and `verified` true. A second test covers the
unverified path, asserting the `≤ 0` filter applies and `verified` is false.

**Frontend.** Unit tests for the `CONFIDENCE_TOPICS_SHOWN` slice,
`useSubjectName`'s fallback, target-grade vocabulary selection by tier, and
`gradeRank` — including that a grade outside the vocabulary sorts after `U`
rather than before `A*`.

**The gate.** A unit test failing if any backend-owned reference table
reappears as a literal in `web/src` — grade vocabularies, qualification-level
values, session-month values, difficulty bands. This repo's convention is that
"a screen no list claims is a screen no gate reads" (`documentMeta.ts`);
without this, the seventh `GRADE_ORDER` arrives unnoticed.

**E2E — Playwright, and only Playwright.** `web/e2e/` is the E2E harness
(`web/playwright.config.ts`); `phase4-journey.spec.ts` and `signup.spec.ts`
already drive S-01 and now also cover D9's placement-choice step. New E2E
coverage goes there as `.spec.ts` files, never as a bespoke browser script.

**Playwright is a test tool, not an ingest dependency.** It was used during
design to reverse-engineer ciegt's data route; the shipped ingester
(`scripts/ingest_thresholds.py`) fetches `__data.json` and the PDFs over plain
HTTP with no browser involved. Nothing in the runtime or the ingest path may
depend on a headless browser.

## Delivery order

Reviewable stages, each independently mergeable:

1. Catalogue tables, migration, backfill, `GET /api/reference` (subjects only).
2. Frontend onto the catalogue: `useReference`, the nine import sites, S-01's
   loading and error states, D10's control removal.
3. Threshold ingestion: the ciegt + PDF ingester, both threshold tables,
   `GradeBoundaryStore` onto the DB, retire `grade_boundaries.json`.
4. D7's vocabularies: `targetGradeVocabularies`, `lib/grades.ts`, deletion of
   the six `GRADE_ORDER` copies, the gate test.
5. D9's placement-choice step.

## Out of scope

- **File storage.** Teacher uploads, the parsed-scheme corpus, the Gemini cost
  ledger and response cache, and the three in-process stores pinning
  `max-instances=1` are a separate design (GCS, plus migrating student files
  off Supabase Storage).
- **Aggregate syllabus grading.** Awarding a real A\* means marking every
  component of an option and applying the weighting, against option thresholds
  this design does not ingest — a product capability, not a data change.
- **Hardening the pre-2014 PDF parser.** Those documents carry a watermark in
  the text layer; their sessions ingest unverified rather than not at all.
- **Pipeline stage labels.** `STAGE_ORDER` mirrors the backend's `_JOB_STAGES`,
  but the student and teacher pipelines have different stage lists and the
  frames are already backend-defined. Worth doing; not worth entangling here.
- **Frontend constants with no backend counterpart** — see D6.
