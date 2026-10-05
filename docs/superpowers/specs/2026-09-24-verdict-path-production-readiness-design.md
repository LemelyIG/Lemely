# Making the per-point verdict work usable in production

Design for the work that turns US-013's per-point marker verdicts (I6) and
error-carried-forward re-marking (I7) from committed code into something a
deployment can switch on and a teacher can use.

Branch `feat/ai-improvements`. Written against `8b47b123`.

## Why this exists

Task #30 shipped nine commits and passed two review rounds: three columns on
`question_result_points`, a shared duplicate-resolution rule, a coherence check,
and a `MarkerVerdicts` surface on the teacher review screen. None of it can be
switched on.

`equivalence_gate` appears **zero times** in `lemely/app/cli.py` and
`lemely/web/services/grading.py`. Both call sites are where US-040 recorded them
— `cli.py:354` (`hybrid_correct_paper`) and `grading.py:91` (`correct_paper`) —
and neither passes the argument. `GradingSettings.equivalence_gate` exists and is
tested; nothing reaches it. So the flag is not defaulted off, it is unreachable:
no `lemely.toml` can enable the feature.

Two consequences follow, and they set this design's scope.

Every `verdict` column in production is `NULL`, so `MarkerVerdicts` currently
renders a section whose every row reads "Marker: awarded / not awarded (no richer
verdict recorded)" — duplicating what the matched-point chips already implied,
for 100% of traffic, in exchange for a feature nobody can turn on.

And the marker's own per-point reasoning is persisted but unread. `PointVerdict.note`
and `point_notes` both land in `question_result_points.rationale`, with a
precedence rule US-045 wrote and tested. The only reader is
`self_review_repo.py:377`, which feeds the **student** surface as
`marker_rationale`. There are no readers in `review_repo.py`,
`schemas_review.py` or `teacherTypes.ts`. The teacher whose screen US-046 was
built for sees *what* the marker decided and never *why*; the student sees the
reasoning.

## Scope

This design covers **switchability and coherence only**. It makes the feature
enableable, makes what it then shows correct, and adds the behavioural coverage
it currently lacks.

It deliberately does **not** cover the accuracy case — whether the verdict path
marks better than the legacy path. That needs a label campaign
(US-008 → US-014 → US-015 → US-016) that has not started: `eval/labels/` contains
only `.gitkeep`. US-018 remains gated behind US-013 and US-016 and is out of
scope here.

Enablement granularity is the global `lemely.toml` setting US-040 specifies. Not
per-school, not per-run.

One correction to the record while scoping this: US-018 carries a note reading
"BLOCKED ON US-030: a cost-ceiling breach currently scores fabricated zeros". That
is stale — US-030 is `passes: true`. And the review-rate gate's `armed=False` is
**not** a wiring defect, contrary to an earlier audit claim of mine:
`scripts/check_review_rate_gate.py:14-15` documents unarmed as the intended M0
state, where breaches print and the script exits 0. The real residue there is
narrower — its preferred local run diverges from the committed baseline, so local
runs measure different data than CI — and that is measurement hygiene, not
wiring.

## Stories

Seven. Each is a separate reviewable commit with a disjoint file set except where
noted, but they are not all independent — C, F and D form a chain.

Lettered for cross-reference and listed in dependency order, which is why D
appears last rather than fourth.

### A — delete `evidence_box`, re-pin the fingerprint

`PointVerdict.evidence_box` is typed `None` and reaches the wire schema as
`{"default": null, "type": "null"}`. Every marking prompt shows the model a field
it can only ever fill with `null`, and no OCR bounding-box source exists to
populate it (see "Why the marker cannot produce per-point boxes" below).

Deleting it changes `AIMarkResponse.model_json_schema()`, which is
`_params_fingerprint`'s only schema input, so it invalidates the marking cache.
That cost is approved.

**The fingerprint change is a safety mechanism, not merely a cost.** `StrictModel`
is `extra="forbid"` (`schemas.py:33`), so a cached response payload still carrying
`evidence_box` would fail validation once the field is gone. What prevents that is
exactly what looked like the expense: the cache key moves, so those entries are
orphaned rather than read. **A wire-schema field cannot be removed while keeping
the cache key stable.** A future change that tries to dodge the hash budget by
pinning the key will break parsing on every cached hit. This belongs in the commit
message, not only here.

Isolated as its own story so the fingerprint delta is attributable to one commit.
Three agents produced three incomparable `model_json_schema()` hashes for this one
invariant during task #30; a lone commit makes the next measurement unambiguous.

Schema-only — `evidence_box` was never a database column, so no migration.

### B — thread `equivalence_gate` to both entry points

Closes US-040. Pass `settings.grading.equivalence_gate` into `correct_paper` at
`cli.py:354` and `grading.py:91`.

The implementer verifies one thing before writing code: whether a settings object
is already in scope at both sites, or has to be threaded in. If it has to be
threaded, that is the story's whole risk and should be reported first.

**This story does not flip the default.** Enabling the feature stays a separate,
deliberate act.

### C — teacher surface: suppression, `rationale`, and a false banner

Three changes to the same five files (`db/review_repo.py`,
`web/schemas_review.py`, `web/routers/review.py`, `lib/teacherTypes.ts`,
`portals/teacher/screens/ReviewItem.tsx`), so they ship together rather than in
three passes over each file.

**Suppress the empty section.** When no point in a question carries a verdict,
`MarkerVerdicts` renders nothing. Suppression is at the **section** level, not per
point — a per-point filter would recreate the invisible-point defect that task #30
exists to fix, and which a reviewer demonstrated can pass every current test.

This reverses a ruling made during task #30, when the section was required to
render unconditionally. That reasoning assumed the verdict path was reachable. It
is not, so the practical effect today is a section of pure fallback for every
user.

**Bring `rationale` to the teacher.** `QuestionResultPoint.rationale` →
`ReviewItemPoint` → `ReviewItemPointDTO` → `_point_to_dto` → `teacherTypes.ts` →
rendered per point. Read in the *same comprehension* as the verdict fields, inside
the open session — `review_repo.py` already documents why that matters (`qr` is
detached once the `with` block exits, and a lazy relationship on a detached
instance raises).

This is the one change in the whole design that improves the screen **before the
flag is ever enabled**: `point_notes` populates `rationale` on the legacy path
today.

**Correct the false banner.** `ReviewItem.tsx:704` states "The original scan image
and the mark scheme's own wording aren't stored anywhere in this product." The
scan **is** stored — `Upload.storage_path` retains it (GCS in production, local
filesystem in dev and CI, behind the `lemely.io.storage` seam) and an attempt
reaches it via `upload_id` (`attempts.py:101`). The mark-scheme half of that
sentence is true and stays.

The correction lands in C rather than F on purpose: if it waited for F and F
slipped, a false disclosure would ship. C states the truth about storage and what
this screen shows; F later swaps only the clause about display. That is two edits
to one sentence, recorded here so a reviewer reads it as a planned clause swap
rather than a fourth formulation of a claim this branch has already rewritten
three times.

### E — persist `source_box`, serve a page crop

Most of the bounding-box machinery already exists:

* `SourceBox` (`core/schemas.py:495`) carries `page` plus
  `[ymin, xmin, ymax, xmax]` normalised to 0-1000, matching Gemini's documented
  convention for image inputs, with a validator enforcing coordinate range and
  positive area.
* `ExtractedAnswer.source_box` ships it (US-006).
* `io/box_plausibility.py` checks a box actually contains ink (US-017).
* `io/reread.py` already crops `source_box` and re-extracts at
  `media_resolution="high"`, including degenerate-box handling.
* `Upload.storage_path` retains the scan, reachable from the attempt.

The gap is that `source_box` has **zero hits** in `lemely/db/` and `lemely/web/`.
It is produced at extraction, consumed in-process by the re-read, and discarded —
the same shape of gap `point_verdicts` had before task #30.

Four hops close it.

1. **`_answers_by_id` (`correction_ai.py:50`)** widens its
   `{question_id: (answer, working_out, confidence)}` tuple to carry the box. The
   `Mapping[str, str]` branch yields `None`, following the existing shape — that
   branch already fabricates `None` working_out and `1.0` confidence at `:90`.
2. **`CorrectedQuestion`** gains `source_box: SourceBox | None`, set at the four
   existing `extraction_confidence=` sites (`:301`, `:316`, `:331`, `:372`).
3. **Migration `0042`** persists it on `question_results` as **explicit columns,
   not jsonb**. `SourceBox`'s validator enforces range and positive area; a jsonb
   blob would let a degenerate box through to render time, where nobody can see
   why it broke.
4. **A crop route** resolves `upload_id` → `Upload.storage_path`, renders that
   page, crops by the 0-1000 box using `reread.py:115`'s arithmetic, and streams
   the result.
5. **The review-item DTO exposes whether a box exists**, so the UI can decide
   whether to render a crop affordance without issuing a request that 404s. The
   crop route alone is not enough: `source_box=None` is the common case, and a
   client that has to probe for absence will show a broken affordance first and
   correct itself second.

Two constraints, both from code that already exists:

`_answers_by_id`'s docstring records NIT-B — two `ExtractedAnswer`s can share one
`question_id`, and a dedup rule already lives there. The box must come from
whichever answer **that** rule picks. A second rule is precisely the failure this
branch already paid for: `point_verdicts` had two consumers resolving a duplicate
differently, and it inflated marks (a 1-mark point scored 2).

`source_box_drops` exists, and `schemas.py:569` states that a dropped box is
indistinguishable from "the model gave no box". So `source_box=None` is normal
rather than exceptional, and absence must render as absence, never as a failed
crop.

**Only A moves the fingerprint.** `CorrectedQuestion` is an output record and is
not a `response_schema` at any of the twelve call sites — measured at
`6d51693e8f80`, unchanged across `c1435505`. E adds a field to a schema the cache
never hashes. That asymmetry is why A is isolated and E is not.

### F — render the crop

Renders the crop in the evidence card and swaps the display clause of C's
corrected banner.

Depends on both: C, because they touch the same `ReviewItem.tsx`, and E, for the
route and the box-presence field it renders against.

### G — widen the student self-review payload

The student surface has the same defect US-046 fixed for teachers, one portal
over. `self_review_repo.py:965-978` builds each point from `awarded=p.awarded`
and never reads `verdict`, so a student sees "not awarded" with no way to tell
"the marker judged this absent" from "the marker could not verify it" — the exact
collapse I6 exists to prevent.

The columns are already persisted, so this is a read-path widening of the same
shape as US-046, not schema work.

**The existing contract decides where it goes.** That builder emits `awarded`, so
it is the **revealed** shape. `selfReviewTypes.ts` says of the pending shape: *"If
a field named `awarded` ever appears on the pending shape here, the backend
contract has been broken, not extended."* A verdict is strictly more informative
than `awarded`, so it can only join `SelfReviewRevealedPoint`.

That also removes a pedagogical risk without needing a rule: the student sees the
verdict only *after* committing their self-mark, so it cannot be used to decide
what to claim.

**All three fields reach the student** — `verdict`, `evidenceSpan`, `ecfApplied`.
The two extras are arguably worth more here than on the teacher screen: the quoted
span shows exactly which of their words were read, and the ECF badge tells a
student that one early slip did not cascade through the rest of the question,
which they cannot infer from a mark alone.

**Student-specific copy, not the teacher labels.** "Unverifiable, could not
confirm" is institutional hedging to a sixteen-year-old; the student wording should
say the same thing and imply what to do differently. This is the one place in the
design where two vocabularies for one concept is deliberate, so it is recorded
here as intended rather than left for a reviewer to flag as drift. `check:copy`
applies — no em-dashes, no exclamation marks.

Unlike C and F, G's behaviour has somewhere real to be tested: `web/e2e/self-review.spec.ts`
already exists and drives this flow against a seeded backend. G extends it, so it
needs no companion story the way the teacher surface needs D.

Files: `db/self_review_repo.py`, `web/schemas_student_self_review.py`,
`lib/selfReviewTypes.ts`, the student self-review screen, and
`web/e2e/self-review.spec.ts`. Disjoint from every other story.

### D — Playwright spec for `/teacher/review`

Closes #50, and is the **actual** verification for C's suppression and F's crop.

`grep -rlnE 'teacher/review|ReviewItem' web/e2e/` returns nothing across 20 spec
files. `web/vitest.config.ts` is `environment: "node"` with no jsdom by deliberate
decision, and its own comment claims component behaviour is covered by the
Playwright suite — which is true for other screens and false for this one. So
`MarkerVerdicts` has no behavioural coverage in either half of the pyramid.

A reviewer proved what that costs: re-introducing the invisible-point defect one
level deeper, as a guard inside the map callback rather than a filter around it,
passes all 12 unit assertions with a clean `tsc`. A source-text test can pin the
*shape* of an iteration but never "every element produces output".

Extends `self-review.spec.ts` / `correct-paper.spec.ts`, which already drive
marking against a seeded backend.

### Order

A ∥ B ∥ E ∥ G, then C, then F, then D.

G is parallel-safe with the first wave: it touches the student portal and shares
no file with A, B or E. Per the lesson of task #30's concurrency near-misses, each
agent in that wave gets its file set and the explicit-path commit rule
(`git commit -S -- <paths>`, never `-a` or `add -A`) before any of them starts —
the index is shared, so a bare commit sweeps another agent's staged work.

## Why the marker cannot produce per-point boxes

`lemely/io/correction_ai.py` contains zero references to `image`,
`RasterisedPage`, or `media_resolution`. Marking is text-only: it receives the
transcription (`student_answer`, `student_working`), never the page. The model
therefore cannot emit a bounding box, which is why `evidence_box` is typed `None`.

Per-point boxes would require sending page images on every marking call — image
tokens on the hottest path, plus a fingerprint change. That is a separate project,
not an increment. This design's boxes are therefore **question-level**: they answer
"where on the page did this answer come from", not "which pixels justify this mark
point".

This strengthens story A rather than weakening it. If per-point boxes are ever
built, they will add a field with a real producer.

## Error handling

`rasterise_pdf_to_pages(pdf_path, *, dpi=EXTRACTION_DPI)` returns **all** pages;
there is no single-page entry point. A naive crop route would rasterise an entire
script at 200 DPI per request. E adds a single-page render — pypdfium2 is
page-indexed, so this is a small addition — plus cache headers on the route.

Rejected alternative: generating crops at persist time. It stores derived copies of
student work, which is new storage *and* a second disclosure question, to avoid a
render we can make cheap.

**Authorization is E's headline risk.** The crop route serves an image of a
student's script. It must reuse the review item's existing visibility rule —
`_visible_class_map`, `caller_id`/`caller_role`, and `ReviewOwnershipError`'s
documented 403-versus-404 discipline — rather than implement its own. Image
endpoints are where IDOR gets written, because they read as "just serve bytes".

| Condition | Cause | Behaviour |
|---|---|---|
| `upload_id` is `NULL` | console paper, quiz, seeded data | 404 — no scan exists |
| `storage_path` object missing | GCS lifecycle, dev filesystem cleared | 404, distinguishable reason logged |
| `source_box` is `NULL` | common; `source_box_drops` exists | route never called; DTO reports no box, UI renders no crop affordance |
| `page` out of range | box captured against a different render, or upload replaced | 422, without rasterising to find out |

**Persistence must never fail a correction.** Hop 3 follows `attempt_repo.py`'s
existing precedent: `_safe_derive_point_rows` wraps its write in `begin_nested()`
because nothing on that path may fail a correction (spec 2026-09-17, "Error
handling"). A malformed box degrades to `NULL`; it does not cost a student their
marked paper.

`rationale` is marker-authored prose on a teacher screen. Same posture as
`studentEvidence`: rendered as plain JSX text, never interpreted as markup, and
clamped so a long note does not dominate every row.

## Testing

Governing rule (`sdd/probes/README.md`): a check earns the name only if it
evaluates the predicate rather than reading it, over inputs a real producer can
emit, **and** was observed going red when the property breaks. Eight false claims
on this branch came from skipping one of the three.

**A.** The fingerprint gate moves to the measured new value, and both values are
reported. Plus a test documenting the coupling: a payload still containing
`evidence_box` must now fail validation, proving `extra="forbid"` is why the key
change is mandatory.

**B.** Assert the argument **reaching** `correct_paper` at both sites — `True`
when `lemely.toml` sets it, `False` when absent. Never assert the config value;
that is tautological.

This is the story's whole lesson. US-005b's criteria read "flag defaults OFF; with
it OFF the golden queue diff is empty" — it tested the **off** state, which passed
while nothing could turn it **on**. A test that only checks the default cannot
detect an unreachable flag.

**C.** Precedence at the wire (verdict note wins; `point_notes` alone; both empty
→ absent), and the banner's false sentence gone with the true one present.
Suppression is **specified here and verified in D** — a source-text assertion
cannot establish "renders" or "does not render", and pretending otherwise is how
the earlier coverage gap passed while the defect was live.

**E.**

* `_answers_by_id`: real `ExtractedAnswers` yields the box, `Mapping[str, str]`
  yields `None`. Not `model_construct`.
* NIT-B duplicate `question_id`: pin **which** answer supplies the box, so a
  second dedup rule cannot appear silently.
* Migration `0042`: real-Postgres round trip in
  `tests/test_migration_0041_point_verdict_columns.py`'s shape — asserting types,
  nullability and defaults rather than column names, with server defaults proven
  by a raw non-ORM INSERT.
* Crop route: **authorization first** — a teacher from another school receives the
  documented status, not an image — then each degradation row above, then a happy
  path asserting image dimensions.
* A malformed box degrades to `NULL` and the attempt still persists, following
  `test_persist_survives_derive_point_rows_raising`.

**G.** The revealed payload carries all three fields; the **pending** payload
carries none of them, asserted explicitly — that is the contract
`selfReviewTypes.ts` documents, and a test is the only thing that keeps it true.
Student copy differs from the teacher labels (deliberate, per the story), and
`npm run check:copy` passes. Behaviour is verified in `web/e2e/self-review.spec.ts`
rather than by source-text assertion, because that spec already exists for this
flow.

**D.** Legacy question renders no marker-verdict section; a verdict-bearing
question renders every point with all three verdicts distinguishable; a boxless
point shows no crop affordance.

**Baselines to hold**, measured on `8b47b123`: `test_correction_ai` 127,
`test_question_points` 35, `test_review_repo` 32, `test_web_review` 30,
`test_migration_0041_point_verdict_columns` 7, vitest 197 files / 3415 tests,
`pyright lemely` 0 errors, `mypy lemely` 308 files, `lint-imports` 4 contracts,
`dup_verdict_probe.py` 0 violations.

Counts are reported by grepping the `N passed` summary line — never from `tail`,
and never by counting dots in a `-q` run. That last one produced a wrong published
count twice during task #30.

**Anti-goal:** no acceptance criterion is satisfied by asserting the absence of a
string.

## Human gates

Two decisions belong to a person, not an implementer.

**Disclosure.** `Upload`'s docstring states that the public "How Lemely handles
your data" page cites that model. Showing a teacher a crop of a student's script is
a new access path to retained data. Whether the public disclosure needs updating is
a human decision, and E and F must not proceed past the point of serving crops
without it.

**Enabling the flag.** B makes `equivalence_gate` settable. Setting it changes how
papers are marked, and this design provides no accuracy evidence that the verdict
path marks better — that is Track B, blocked on a label campaign that has not
begun. Turning it on in an environment with real students is a deliberate act
outside this design's claims.

## Out of scope

* The accuracy case for the verdict path (labels, paid sweeps, US-016, US-018).
* Per-point bounding boxes, which need page images on the marking call.
* Per-school or per-run enablement granularity.
* Arming the review-rate ratchet, which is an accuracy-milestone decision.
