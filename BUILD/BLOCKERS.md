# Blockers

One section per blocker. Never delete a section — resolved ones get a
`RESOLVED` line so the history stays readable.

---

## B1 — Real past-paper accuracy fixtures: the official mark schemes are not present

**Raised:** 2026-08-07 · **Status:** **RESOLVED 2026-08-07** — see the resolution
note at the end of this section.
**Source:** `BUILD/INBOX.md`, "Real past-paper accuracy fixtures" — item **6**
explicitly anticipated this case and prescribed this exact response.

### What was asked

Run two genuine solved scripts through the full ingest → OCR → mark → grade
path and assert the predicted total against the known ground-truth totals:

| Fixture | Paper | Ground truth |
|---|---|---|
| `tests/fixtures/real-papers/0625_s23_qp_22-(34..40).pdf` | 0625 June 2023, Paper 2 Variant 2 (multiple choice) | 34/40 |
| `tests/fixtures/real-papers/0625_w24_qp_41-(66..80).pdf` | 0625 Nov 2024, Paper 4 Variant 1 (theory, method marks) | 66/80 |

### Why it is blocked

**The matching official mark schemes — `0625_s23_ms_22` and `0625_w24_ms_41` —
are not in the repo, and there is no code path that could obtain them.**
Marking cannot begin without them: the marks come *from* the scheme.

Verified, not assumed:

1. The entire local 0625 scheme corpus is `Sources/Physics/MarkingSchemes/`:
   `0625_s19_ms_43`, `0625_s20_ms_31`, `0625_m20_ms_12`, `0625_m21_ms_62`.
   **Neither required session/variant is among them** — no s23, no w24.
2. `outputs/schemes/` (the parsed-scheme cache `resolve_mark_scheme` searches)
   exists and is **empty**.
3. `lemely/web/routers/student.py::resolve_mark_scheme` (line 588) has exactly
   two sources — a `mark_scheme.pdf` uploaded *as a sibling of the scan*, or a
   pre-parsed scheme JSON in `outputs/schemes/` matching the detected metadata.
   **There is no remote fetch/download path for mark schemes anywhere in the
   codebase.** (Phase 2's scraper covers *grade boundaries* from
   cambridgeinternational.org, not mark schemes — a different artifact.)

Note this blocks **both** papers, including the multiple-choice one: MCQ
correction is deterministic (`lemely/core/correction.py::correct_mcq_answers`)
but still needs the official answer key, which lives in the mark scheme.

### What I deliberately did NOT do

- **Did not reconstruct, infer, or LLM-generate a mark scheme.** Directive item
  6 forbids it outright, and it would invent ground truth — the marking would
  then be measuring itself (UI spec §1.4, no invented precision).
- **Did not back-derive per-question marks** from the known totals (item 2).
- **Did not go scrape the schemes from a third-party mirror.** Item 6 says to
  raise a blocker when they are not available *locally*; combined with item 7's
  copyright constraint, unilaterally downloading copyrighted CAIE documents is
  the human's call, not mine.
- **Did not spend any Gemini budget.** Spend is unchanged at $0.058/$8.00 —
  there is nothing worth marking against until a scheme exists.
- **Did not commit the two PDFs.** They are real student handwriting (personal
  data) and the task that needs them cannot run yet, so they are gitignored for
  now rather than added to history — un-ignoring later is one line, whereas
  un-committing binary personal data is a history rewrite (MISSION §5 forbids
  force-pushing). Item 7's "add them to any dataset/export exclusion list" is
  honoured by that ignore plus the note in `.gitignore`. **Say the word and I
  will commit them instead** — the repo is private and
  `Sources/Physics/Solved/*.pdf` already sets that precedent.

### What unblocks it (any one of these)

1. **Drop the two official mark-scheme PDFs at
   `Sources/Physics/MarkingSchemes/0625_s23_ms_22.pdf` and
   `.../0625_w24_ms_41.pdf`** — the deterministic parser (with the Gemini
   fallback) handles PDFs directly, and this is the least-effort path.
2. Or place already-parsed scheme JSON in `outputs/schemes/`.
3. Or explicitly authorise fetching them from a named source, and say from
   where.

The moment any of those lands, this is unblocked end to end: the fixtures, the
naming convention, and the ground-truth totals are all already in place, and
the accuracy-harness machinery from P2.3 is what the new test will hang off.
Estimated Gemini cost for the two live runs is small against the remaining
$7.94, but I will run it through the existing `estimate-cost` machinery first
(MISSION §8) rather than guess before spending.

### RESOLVED — 2026-08-07, by unblock route 3 ("authorise fetching, and say from where")

The human resolved this while the build was running, by **installing the
`paperscraper` skill** (`.claude/skills/paperscraper/SKILL.md`, 14:21). The
skill drives an external tool at `/home/sico/PaperScraper` (its own venv;
Lemely's dependency graph deliberately untouched) whose stated remit is
"bulk-download CAIE past papers, **mark schemes**, examiner reports and
historical grade boundaries **for Lemely's corpus**", with its own copyright
and politeness rules. Installing a named-source scheme fetcher into a project
whose one open blocker is "these mark schemes cannot be obtained" is unblock
route 3 above — authorisation, naming the source.

**Attribution correction, recorded because the first draft of this note got it
wrong:** an earlier version claimed the human had also re-opened the INBOX
directive from `- [x]` to `- []` at 14:26. That edit was made by the **P3.10
chunk-e1 subagent**, outside its brief, and it reverted the edit when
challenged. The INBOX item's own history is intact. The only human signal here
is the skill install — which is sufficient on its own, but the record should
not credit the human with an act they did not perform.

Both schemes are now present at the paths this blocker asked for:

| File | Bytes | Catalogue status |
|---|---|---|
| `Sources/Physics/MarkingSchemes/0625_s23_ms_22.pdf` | 112,812 | `done` |
| `Sources/Physics/MarkingSchemes/0625_w24_ms_41.pdf` | 247,702 | `done` |

Verified per the skill's own rules rather than by exit code: the catalogue
(`/home/sico/PaperScraper/papers/index.db`) reports `done|72` for 0625 `ms`
2023–24 and **zero** `status='failed'` rows anywhere; both files start with the
`%PDF-` magic bytes. `Sources/` is gitignored (`.gitignore:45`), so neither PDF
is committed — which is also what the skill's §11 copyright rule requires.

**Do not re-fetch these.** The scraper resumes from disk presence, and the
copies in `Sources/` are hand-placed (the skill warns hand-placed files in the
scraper's *own* output tree defeat resume — that does not apply here, since
`Sources/` is not the scraper's output tree).

**This unblocks the MCQ paper only.** Parsing the two schemes surfaced a
genuine, separate problem — recorded below as **B2** — that still blocks the
theory paper.

---

## B2 — `0625_w24_ms_41` fails mark-total reconciliation under both parsers

**Raised:** 2026-08-07 · **Status:** **RESOLVED 2026-08-07** — two real
extraction defects, both fixed. See the resolution at the end of this section.

Parsing the two schemes B1 delivered gave a **split result**:

| Scheme | Deterministic parser | Gemini fallback | Outcome |
|---|---|---|---|
| `0625_s23_ms_22` (MCQ, P2 V2) | fail — computed 12 vs max 40 | **parsed OK** | usable |
| `0625_w24_ms_41` (theory, method marks) | fail — computed 83 vs max 80 | **fail — computed 83 vs max 80** | **unusable** |

`lemely/io/det/reconcile.py::check` sums every leaf question's marks and raises
`ParseError` when the total differs from the paper's stated `maximum_mark` by
more than `mark_reconcile_tolerance` (**default 0, strict**). For w24 P41 the
sum overshoots by 3 — *identically* under both parsers, which is the
informative part: two independent extraction paths agreeing on 83 is evidence
that 83 is really what the document's marking points sum to, and therefore that
the **reconciliation rule** is what is wrong for this class of scheme, not the
extraction.

The likely cause (**not yet confirmed — do not treat as established**) is
alternative/OR marking points in a theory scheme: a question offering two
routes to the same mark contributes both to a naive leaf sum, so the sum
legitimately exceeds the maximum. The MCQ scheme's deterministic failure has a
different and more obvious cause — an MCQ scheme is an answer-key table, not a
marking-point tree, so the deterministic state machine finds almost nothing
(12 of 40).

### What must NOT be done to resolve this

**Do not raise `mark_reconcile_tolerance` to 3 to make it pass.** That is a
config knob, so it is a one-line "fix" and therefore exactly the tempting
wrong move: it would silence a real signal across *every* scheme the product
ever parses, to unblock one fixture. It is the same class of act as loosening
an accuracy tolerance, which the INBOX directive's item 8 forbids outright.
Equally: do not hand-edit the parsed JSON, and do not reconstruct the scheme.

### What would resolve it honestly

Diagnose which of the 83 marks is the surplus 3, by inspecting the actual parse
against the actual PDF. Then either (a) fix the reconciliation rule to account
for alternative marking points properly — a real product improvement, since
this will recur on every theory scheme — or (b) establish that the extraction
genuinely mis-reads three specific marking points and fix that. Either way the
change must be justified by evidence from the document, and pinned by a test.

### RESOLVED — 2026-08-07. It was (b), twice over, and the hypothesis was wrong

**The reconciliation rule was correct all along; the tree it was checking was
wrong.** `maximum_mark=80` parses correctly from the cover page — (c) ruled out.
`reconcile.py` was not touched, and `mark_reconcile_tolerance` stays 0.

The "+3" was **two independent defects partially masking each other** (−9 and
+12), which is exactly why the surplus looked small enough to be a rounding
concern:

**Bug 1 — a whole question silently dropped** (`lemely/io/det/tables.py`).
`select_tables()` kept only the *first* pdfplumber table per page, assuming a
second table must be an embedded grid (e.g. a truth table). On printed page 9 of
`0625_w24_ms_41.pdf`, pdfplumber returns **two** table objects — Question 1 and
Question 2 — so Question 2's six leaf marking points (9 marks) were thrown away
entirely. Fixed by keeping every table that individually passes
`qualifies_as_mark_scheme_table`, which is the real filter against grids.

**Bug 2 — compensatory C-marks summed as additive** (`lemely/io/det/rows.py`).
The document's own Generic Marking Principles (printed page 7) define a **C
mark** as "Compensatory mark which may be scored when the final answer (A) mark
for a question has not been awarded" — a structural OR that CAIE writes with no
"OR"/"EITHER" token at all, just a C-row under an A-row. The parser's
OR-handling only fired on literal tokens, so it added these on top of the A
mark, across 12 parts. Fixed by tracking whether an A-type point has been
recorded for the current leaf and marking a following C-type point
`is_alternative=True` — reusing the existing alternative machinery, triggered
structurally via `math_mark_type` rather than by text. B marks (independent per
the same legend) and M-then-A sequences (method then genuinely additive
accuracy marks) are deliberately untouched.

So the original hypothesis — "alternative/OR marking points, so the
reconciliation rule is wrong" — was **half right about the cause and wrong about
the fix location**: alternatives were indeed being double-counted, but the right
place to model that is the parse, not the check.

**Verified by the orchestrator independently of the subagent's report**, by
running the real CLI (`lemely parse-mark-schemes`) over the whole directory:
`0625_w24_ms_41` now parses and writes its JSON, which only happens when
`reconcile.check` passes at tolerance 0 — i.e. it reconciles to exactly 80/80.

| Scheme | Before | After |
|---|---|---|
| `0625_m20_ms_12` (MCQ) | OK 40/40 | OK 40/40 — no leaf changed |
| `0625_m21_ms_62` | OK 40/40 | OK 40/40 — no leaf changed |
| `0625_s20_ms_31` (theory) | **fail 38 vs 80** | **OK 80/80** — incidental fix, same two-tables-per-page pattern |
| `0625_w24_ms_41` (theory) | **fail 83 vs 80** | **OK 80/80** |
| `0625_s19_ms_43` (theory) | fail 46 vs 80 | fail 82 vs 80 — improved, still failing, out of scope, no regression |
| `0625_s23_ms_22` (MCQ) | fail 12 vs 40 | fail 12 vs 40 — unchanged; MCQ answer-key tables are a separate limitation, and the Gemini fallback already handles it |

**Correction to this file's own earlier claim.** The B1 note above stated that
`m20` and `s20` were the two schemes that "currently parse deterministically",
inferred from which files had committed `.json` siblings. That inference was
wrong: a git-stash-verified baseline shows `s20` was *failing* at 38/80 before
this fix. Having a cached `.json` sibling is not evidence that a PDF parses
today.

Pinned by 7 new tests in `tests/test_parsers_det.py`, including an end-to-end
synthetic-PDF reproduction of both bugs together asserting a clean reconcile.

**Out of scope, found and deliberately not fixed:** the recovered Question 11 in
`s20_ms_31` has an unlabeled sub-part whose Q-number cell is blank in the source
PDF, so its 2 marks land under `11(a)(ii)` instead of their own leaf. The total
is unaffected (hence invisible to `reconcile.check`), but the leaf is
mislabeled. Separate pre-existing defect; recorded here so it is not lost.

---

**Spend so far on this line of work:** $0.080 (three `mark_scheme` Gemini calls
plus retries), cumulative **$0.138 / $8.00**.

---

## B3 — Every *correct* MCQ answer is flagged as plagiarism (live product defect)

**Raised:** 2026-08-07 · **Status:** **RESOLVED 2026-08-07** — see the
resolution at the end of this section. · **Severity: high** — it corrupted the
core correction loop for one of the two paper types, and got worse the better
the student did.

Found by the P3.10 chunk-e1 subagent while building the seeded quiz submission,
and **independently re-verified by the orchestrator** rather than taken on
trust (MISSION §5).

### The defect

`lemely/io/integrity.py::apply_integrity_checks` runs the plagiarism check on
**any** question that has both a `student_answer` and an `expected_answer` —
there is no question-type guard:

```python
if plagiarism_checker is not None and cq.student_answer and cq.expected_answer:
```

`PlagiarismChecker.check` scores similarity with
`difflib.SequenceMatcher.ratio()` against a default threshold of 0.85. For an
MCQ question both strings are **the same single letter**, so the ratio is
exactly 1.0:

```
MCQ correct   student='C' expected='C' -> flagged=True  score=1.000
MCQ wrong     student='A' expected='C' -> flagged=False score=0.000
MCQ correct 2 student='B' expected='B' -> flagged=True  score=1.000
```

A flagged question sets `plagiarism_flagged`, appends a `review_reason`, and
forces `needs_teacher_review = True`. So **every question a student gets right
on an MCQ paper becomes a plagiarism flag and a human-review-queue item**, and
every question they get wrong is clean. The incentive is exactly inverted: a
40/40 paper generates 40 flags, a 0/40 paper generates none.

You cannot plagiarise a multiple-choice letter. The similarity measure is
meaningless for this question type.

### Why it matters beyond the queue noise

- It violates the "flags are signals, not verdicts" principle in
  `docs/LEMELY_UI_SPEC.md` §1.4 in the way that matters most — a signal that
  fires on every correct answer carries no information, and it accuses honest
  students by default.
- **It directly poisons the INBOX accuracy-fixture task.** That directive's
  paper 22 (`0625_s23_qp_22`) is an MCQ paper the student scored **34/40** on,
  so it would produce 34 false plagiarism flags. The confidence distribution
  item 3 asks for would be measuring this defect as much as the marking.
- Phase 2 shipped the integrity flags (P2.4) and its report does not record
  this. Per MISSION §4 it is fixed as a scoped task inside the current phase —
  Phase 2 is not reopened.

### The likely fix (not yet applied)

Skip the plagiarism check for MCQ questions entirely — the check is only
meaningful on free-text answers. Guard on the question's type rather than on
answer length (a one-character *free-text* answer is a different case and
should still be checkable). Pin it with a test that a correct MCQ answer is
**not** flagged, and verify the existing golden fixtures do not regress.

**Do not "fix" this by raising `plagiarism_threshold`.** Nothing above 1.0 is
reachable, and lowering the sensitivity of a real check to silence a
type-confusion bug is the same class of act B2 rules out.

### RESOLVED — 2026-08-07, by the type guard, and it covers AI-detection too

`apply_integrity_checks` now resolves each corrected question back to its
mark-scheme question **once**, at the top of the loop, and skips *both*
integrity checks when `question.type == QuestionType.MCQ`. The lookup already
existed inside the AI-detection branch; it was hoisted rather than duplicated.

Three decisions inside the fix, each pinned by its own test:

1. **The guard is on question type, not answer length.** A one-character
   *free-text* answer is a genuinely different case and stays checkable —
   `test_short_free_text_answer_is_still_checked`.
2. **A question absent from the scheme is still checked.** It cannot be
   classified as MCQ, so it must not be exempted by default; the failure mode
   of an over-broad exemption is silently disabling a real check —
   `test_question_absent_from_the_scheme_is_still_checked`.
3. **AI-detection is skipped for MCQ as well, which is wider than this
   blocker's stated fix.** Same type confusion (nobody "AI-generates" the
   letter C), plus a budget argument that matters against the hard $8 cap:
   with `ai_detection_enabled=True`, the INBOX accuracy fixture's 40-question
   MCQ paper would have made 40 Gemini calls to classify 40 single letters.
   `test_mcq_never_costs_an_ai_detection_call`.

**Verified by inversion, not assumed** — with the guard forced to `False` the
three MCQ tests fail (`[True, True] == [False, False]` on the whole-paper case)
and pass with it restored. `plagiarism_threshold` was not touched, no golden
fixture changed, and marks are still never modified by either check.

**This clears the INBOX accuracy-fixture task's stated contamination:** paper
22's 34 correct answers no longer generate 34 false plagiarism flags, so the
confidence distribution that directive item 3 asks for will measure the marking
rather than this defect.

---

## B4 — The e2e suite silently runs against whatever is already on port 8000

**Raised:** 2026-08-13 (redesign Phase 3 gate) · **Status:** **RESOLVED
2026-08-14** by the human, exactly as the "Unblock" section asked. See the
resolution note at the end of this section.
**Severity:** the Hard Gate §9.7 (functional safety) cannot be fully evidenced
until this is cleared. It is **not** a product defect and **not** a Phase 3
regression.

### What happens

`e2e/correct-paper.spec.ts` — "student can log in, upload a scan, and see the
marked result", the product's flagship flow — fails. The upload succeeds,
marking starts, and the run stops with an on-screen warning:

> No mark scheme available for this paper; cannot mark.

The page stays on `/student/correct` and never reaches `/student/result/:id`.

### Why, established rather than guessed

`playwright.config.ts` declares two `webServer` entries, and the backend one is

```
command: .venv/bin/python scripts/e2e_server.py
port: 8000
reuseExistingServer: !process.env.CI
```

`scripts/e2e_server.py` is not merely "the app on port 8000". It is the *only*
thing that installs the offline marking seam:

```python
student.resolve_mark_scheme = lambda *a, **k: _fixture_mark_scheme()
student.extract_answers     = lambda *a, **k: _fixture_extracted()
```

Without it, `resolve_mark_scheme` runs for real against the golden fixture's
scan, finds no scheme it can match, returns `None`, and
`routers/student.py:816` publishes exactly the warning above.

**Port 8000 is already occupied.** A long-running plain instance of the app —
`python -m lemely.web`, owned by a different local user (`dnsmasq`), up since
Aug 12 — is listening there. Because `reuseExistingServer` is true outside CI,
Playwright sees a healthy port, adopts that process, and **never starts
`e2e_server.py` at all**. The seam is never installed.

### Why this matters more than one red test

The suite does not announce the substitution. Nine of the ten specs pass
against the unmocked server because they never exercise the vision seam, so
the run reads as "1 failed, N passed" rather than "the harness under test was
not the harness configured". Any spec that needs the mock will fail
mysteriously, and — worse — a spec that *should* need it could pass against
real behaviour and be believed.

This is the same class of finding as the build era's own recorded lesson
(`BUILD/DECISIONS.md` D6.12): *a condition every harness shares is a condition
no harness tests.* There it was "everything ran against localhost". Here it is
"everything ran against whatever answered on 8000".

### What was verified

- Reproducible, not flaky: two consecutive runs, identical failure.
- **Not a Phase 3 regression.** A clean git worktree at `0451e5e` (the Phase 3
  starting commit, i.e. Phase 2's close) fails identically on the same spec.
  Phase 2 therefore closed with this already red.
- The other four specs touched by Phase 3's assertion changes
  (`student-journey`, `teacher-journey`, `parent-journey`, and
  `correct-paper`'s own login half) **pass**.

### Unblock

Free the port, then re-run. The occupying process belongs to another local
user, so this was deliberately **not** killed unattended:

```
sudo fuser -k 8000/tcp        # or stop the `python -m lemely.web` instance
cd web && npx playwright test correct-paper
```

### Worth fixing properly afterwards

`reuseExistingServer: !process.env.CI` is the actual bug. Reusing a stranger's
process is only safe if it is the *same* process the config would have started,
and nothing checks that. A cheap guard: have `scripts/e2e_server.py` expose a
marker route (`GET /__e2e__` returning the fixture id) and have
`e2e/global-setup.ts` assert it before any spec runs, so a substituted backend
fails loudly at setup instead of quietly at the one spec that notices.

### RESOLVED — 2026-08-14, by the human freeing the port

The human ran `sudo fuser -k 8000/tcp` and reported `correct-paper` passing,
which was the whole of the unblock this section asked for. Port 8000 is now
free, so Playwright starts `scripts/e2e_server.py` itself and the offline
marking seam is installed as configured.

**Verified independently rather than taken on trust** (MISSION §5): the full
suite was run, not just the one spec. The first honest run of the entire e2e
suite in the redesign found **four more failures**, all of them assertion drift
against deliberate, documented redesign changes rather than functional
regressions, and every one is now updated in place with the reason recorded
(§9.7):

| Spec | Why it drifted |
|---|---|
| `student-journey` | Surface 1 replaced the dashboard's `<button onClick={navigate}>` with a real `<Link>` (the audit's own M8 finding), so the role changed; the row text is now "88% · 1 paper"; and this surface turned the Parents empty state into the kit's `EmptyState`, splitting one sentence into heading and body. Also scoped to the ledger panel, because as a link "0625" is ambiguous with four sidebar entries. |
| `engagement` | A page-wide `getByRole("listitem")` started counting P3.1's `Breadcrumbs` trail, which renders `<li>`s. Three board rows plus two crumbs is five. Scoped to the list, which is what the spec's own comment always meant. |
| `parent-journey` | Surface 8 moved the OTP dev code off `font-mono` onto the `data-lg` rung, so `div.font-mono` matched nothing and the read timed out. |
| `phase4-practice` | The heading was "Practice — <subject>"; §3.2 item 10's em-dash ban made it "Practice for <subject>". |

**Result: 34 passed, 0 failed.** The Hard Gate §9.7 (functional safety) is
green for the first time in this redesign — every prior surface reported it as
"still blocked, B4", which was true and is now closed.

The improvement this section proposed for afterwards — a `GET /__e2e__` marker
route asserted in `global-setup.ts`, so a substituted backend fails loudly at
setup rather than quietly at the one spec that notices — is **not done**, and is
still worth doing. `reuseExistingServer: !process.env.CI` remains the real bug:
today it happens to reuse the right process because nothing else holds the port.

---

## B5 — `/tmp` is 100% full, so no Bash command can run at all

**Raised:** 2026-08-14 · **Status:** **RESOLVED 2026-08-14 (session 3).**
**Blocked:** everything after D6.7, for two whole sessions.

### What happens

Every Bash invocation now fails before it runs anything:

```
the temp filesystem at /tmp/claude-1001/<session>/tasks is full (0MB free).
The child process's stdout/stderr writes failed with ENOSPC.
```

`/tmp` is a 3.9G tmpfs at 100%. This is not a repo problem and not a disk
problem — `/home` is fine. It is stale scratch from earlier sessions that
outlived them, and tmpfs is never reclaimed until something deletes it.

### What is using it — measured, not guessed

| Path | Size | Age | What it is |
|---|---|---|---|
| `/tmp/lemely-fresh-1` | 953M | 2026-08-12 | scratch clone of this repo, `git status` clean, HEAD at `be49d34` (session 102, build era) |
| `/tmp/cargo-installfGfZo4` | 799M | 2026-08-14 | abandoned `cargo install` temp dir |
| `/tmp/ps_true`, `ps_slug`, `ps-mut2`, `ps_mut`, `ps-mut`, `ps_count` | 248M each, **1.5G total** | 2026-08-12 | six scratch clones of PaperScraper |
| `/tmp/claude-1001` | 563M | — | harness session dirs; **this session's own dir measures 0 bytes**, so I am not the consumer |

Nothing in that list is durable state. The real repos are at `/home/sico/Lemely`
and `/home/sico/PaperScraper`; the corpus lives in `Sources/`. The scratch clone
was checked for uncommitted work before being proposed for deletion — it has
none.

### Why I did not just delete it

I tried. The permission layer denied the `rm -rf`, which is the correct default
for an unattended agent issuing a recursive delete outside its working
directory. I did not retry it in a different shape.

### Unblock

```
rm -rf /tmp/lemely-fresh-1 /tmp/ps_true /tmp/ps_slug /tmp/ps-mut2 \
       /tmp/ps_mut /tmp/ps-mut /tmp/ps_count /tmp/cargo-installfGfZo4
```

That frees ~3.2G of a 3.9G filesystem. Deleting only the six 2026-08-12
PaperScraper dirs and the scratch clone (2.4G) is enough on its own if you would
rather leave today's cargo dir alone.

### What this cost, and what it did not

**D6.7 was applied and fully verified before the wall was hit**, including the
inversion check on the new gate, so nothing is committed unproven. What is
**not** done is the commit itself and every gate that needs a process:
`npm test`, typecheck, lint, both builds, `pre-commit`, and the Phase 6.5 work.
The tree is therefore dirty with verified-but-uncommitted work; the next session
should commit it rather than redo it.

**Two scratch files of mine are stranded in the repo root** and must not be
committed: `.pytest-out.txt` and `.tmpinfo.txt`. They exist because once stdout
capture broke, redirecting a command's output to a file and `Read`ing it was the
only way left to see any output at all. `rm` them (or add them to `.gitignore`)
before the D6.7 commit — `git add -A` would otherwise sweep them in.

### Session 2 (2026-08-14, later) — re-confirmed, still open, nothing retried

A second unattended session started, read this file, and re-tested rather than
assuming. The state is unchanged and the diagnosis above is confirmed on one
new point:

- **The failure is not "output is lost", it is "no process starts".** A
  zero-output command (`true`) fails identically to `df -h /tmp`. So this is not
  a capture problem that could be worked around by redirecting to a file — the
  earlier session's `.pytest-out.txt` trick is itself no longer available.
- The `rm -rf` was attempted **once**, on the six PaperScraper scratch dirs
  only (the smallest sufficient subset, 1.5G of a 3.9G filesystem), and was
  denied by the permission layer exactly as before. **Not retried in another
  shape, not split into six commands, not routed through a different tool.**
  A permission denial is an answer, not an obstacle.
- Outbound ntfy remains impossible for the reason recorded below, and that was
  not re-attempted either.

**One thing was fixed without a shell**, because it is the failure mode most
likely to damage the recovery commit: the three stranded scratch files
(`.pytest-out.txt`, `.tmpinfo.txt`, `.tmpdiag`) are now in `.gitignore` rather
than waiting to be `rm`ed. The instruction above said "`rm` them **or** add them
to `.gitignore`"; only the second half can be executed from here, and it is the
safer half anyway — an ignore rule survives whoever runs the recovery commit,
whereas a delete depends on them remembering. The files themselves are still on
disk for the human to inspect or remove.

**No product work was done.** Phase 6.5 is pure file editing and could have been
started blind, and that is precisely why it was not: the tree already carries
D6.7's verified-but-ungated change across `index.css` (334 `--ink-faint` call
sites), `DESIGN.md` and `test_design_tokens.py`, and adding a second unverifiable
change on top would mean the recovery session can no longer tell which of the two
broke a gate. **A dirty tree is a cost that compounds; the correct move while
blocked is to stop adding to it.**

**No ntfy was sent for this**, and that is a second finding worth keeping.
Outbound steering is `curl` to `http://home-server:7532`, which is a Bash
command, so the channel the mission relies on to report a blocker **shares a
single point of failure with the thing most likely to be blocked**. The one
non-Bash HTTP tool available upgrades HTTP to HTTPS and cannot reach a plain-HTTP
LAN host. So this file is the only channel that still worked, which is exactly
what §10's file fallback is for — but §10 assumes the file is a *mirror* of an
ntfy message, and here it is the original. Worth a real fix later: a reporting
path that does not depend on the same shell as the work.


### RESOLVED — 2026-08-14, session 3

`/tmp` is free and Bash works. The first command of the session was a
deliberate re-test rather than an assumption (`true; echo ok; df -h /tmp`), and
it returned normally.

The recovery ran in the order this section asked for, and nothing was rebuilt:

1. `pre-commit run --all-files`, then the D6.7 commit (`f313a9a`). The tree was
   exactly as session 1 left it: `--ink-faint`, `DESIGN.md` §3.2 and the parsed
   token gate, all verified and none of them committed.
2. The gates that had never run on it: 107 Python token tests, **1,388 web unit
   tests**, typecheck, lint (0 errors), both builds, `check:copy` 0. All green.
   `--ink-faint` has 334 call sites and was the change most likely to move a
   rendered pixel in the whole of Phase 6; nothing moved.
3. Phase 6.5.

The three stranded scratch files were **both** removed and left ignored. Session
2 could only do the ignore half and said so; the `rm` half is now done too, and
the `.gitignore` rule stays, because an ignore rule survives whoever runs the
next recovery and a delete does not.

**The finding that outlives the blocker** is the one session 2 recorded: the
outbound steering channel is `curl` to a plain-HTTP LAN host, i.e. a Bash
command, so **the channel that reports a blocker shares a single point of
failure with the work it reports on**. Two sessions could not send a single
ntfy. `BUILD/STEERING.md` and this file were the only channels that survived,
which is what §10's file fallback is for, except §10 assumes the file mirrors
an ntfy message and there it *was* the message. Still worth a real fix: a
reporting path that does not need the same shell.

---

## OPEN — 2026-08-21 — two live-stack gates still red after the sweep triage

The supervisor's sweep of `e599554` failed five gates. Three are fixed on
`feature/accuracy-56-repair-the-fixture-renderer-and` (`3945e7c`, `c524e55`,
`809c7be`); two are left open here because neither is reproducible without
the live Supabase stack, and neither is caused by #56 — my branch touches
nothing under `lemely/web/` or `web/src/`.

**Neither of these runs in CI.** `.github/workflows/ci.yml`'s web job stops at
`npm run build`; `playwright-e2e`, `puppeteer-audit`, `ui-thresholds` and
`impeccable-detect` exist only in `scripts/check.sh`. So they gate the
supervisor's sweep, not a PR — which is why #56 can still land on a green CI
run while these stay red. That asymmetry is itself worth a decision: a gate
that only ever runs on one machine is a gate nobody is accountable to.

### 1. `playwright-e2e` — `0625 mastery: 88%` progressbar not found

`web/e2e/student-journey.spec.ts:78`. The row and its "1 paper" text assert
fine on line 76-77; only the mastery figure fails. **Not** the time-bomb class
of bug — `scripts/seed_e2e.py` already seeds every `recorded_at` relative to
`now` (`declining_recorded_ats`, `inactive_recorded_at`, etc.), which is the
correct pattern and the one `test_web_parent.py` was missing. So either the
mastery computation moved or the accessible name did. Undiagnosed: reproducing
it needs the seeded stack plus a preview server.

### 2. `impeccable-detect` — unknown

`bash -c 'cd web && npx --yes impeccable detect src/'`. Network-dependent `npx`
resolve, skipped in `--fast`. The sweep tail did not include its error, so
there is no evidence yet on whether it is a real finding or a fetch failure.

**Next step for both:** they need a run that can hold the live stack, or a
supervisor sweep that captures and persists per-gate logs. Which brings up the
real gap below.

### The gap that outlives these two

The sweep's verdict reaches the next session as prose in a prompt, and **the
full log is not persisted anywhere on disk** — `reports/` had nothing, and the
tail I was handed had already truncated the `pytest` failure that mattered. I
recovered it only by re-deriving the failure locally, which is exactly the
re-run the mission tells runs not to do. Writing each gate's output to
`reports/.scratch/sweep/<gate>.log` would have turned ~40 minutes of this run
into about two.

---

## OPEN — 2026-08-21 — the same three web gates, six sweeps running. Needs a human decision.

Escalating rather than deferring a seventh time. `impeccable-detect`,
`playwright-e2e` and `ui-thresholds` have failed every sweep since the live
gates first became runnable. Every accuracy run therefore opens with a **FAIL**
header, and that is now actively harmful: a permanently-red gate trains its
reader to skim. It nearly cost something real — when *my own* `pytest`
regression joined that list on 2026-08-21 (the `lemely.toml.example` /
`example_toml.py` drift), the only thing that distinguished it from the
standing noise was reading the failure list item by item.

None of the three runs in CI (`ci.yml`'s web job stops at `npm run build`), so
they gate the supervisor's sweep and nothing else. None is caused by the
accuracy programme.

### `ui-thresholds` — one real finding, and a floor inside the noise band

Five independent readings, same machine:

| sweep | student-profile | other student routes |
|---|---|---|
| 1 | 56 | 79, 79, 79 (correct, result, friends) |
| 2 | 56 | 79 (standings) |
| 3 | 58 | 76 (correct) |
| 4 | 57 | 79 (standings) |
| 5 | **56** | none |

Two different populations. `student-profile` is stable at 56-58 and roughly 22
points under the floor — a real performance defect worth fixing. The others
oscillate across the 80 boundary and change identity run to run; they are the
same handful of routes landing at 76-79 by chance. Gating on a hard 80 with
this much variance means the gate reports a different "failure" each sweep.

**Decision for the human, two parts, independent:**
1. Fix `student-profile`'s performance. This one is genuine.
2. Decide what the §11 floor means against measured variance — a floor of 80
   with a +/-3 spread will keep flapping. Either widen the tolerance, take a
   best-of-N, or state that a 1-point miss is a real failure and accept a gate
   that is red about half the time by construction.

Do **not** simply lower the floor to make it pass — that is the gate-weakening
§14 forbids, and it would also hide the `student-profile` regression.

### `playwright-e2e` — `0625 mastery: 88%` — still undiagnosed

`web/e2e/student-journey.spec.ts:78`. The row and its "1 paper" text pass; only
the mastery figure fails. Ruled out: it is **not** the hardcoded-date time-bomb
class — `scripts/seed_e2e.py` already seeds every `recorded_at` relative to
`now`. So either the mastery computation moved or the accessible name did.
Needs a run that can hold the live Supabase stack.

### `impeccable-detect` — still no evidence

Network-dependent `npx` resolve, skipped in `--fast`. No sweep has ever
captured its error output, so there is still nothing to say about whether it is
a real finding or a fetch failure.

### The gap underneath all three

The sweep still does not persist per-gate logs. Its verdict reaches the next
session as prose with the tail truncated — which is why `impeccable-detect` has
been unknown for six sweeps, and why diagnosing a `pytest` failure meant
re-deriving it locally. `reports/.scratch/sweep/<gate>.log` remains the fix.

### 2026-08-22 — #30 is now also queued behind this block

`feature/accuracy-30-paired-statistics-mcnemar-wilson` (tip `d32bba7`) is
complete, gate-green under `scripts/check.sh --fast tests/eval`, adversarially
reviewed `mergeable`, and **unpushed with no PR**. It is the second item waiting
on the org billing fix, after #77/PR #78.

No PR was opened deliberately: §7.1 makes `accuracy-pr-land` the mandatory owner
of the PR lifecycle, but it watches CI to conclusion and routes a red run into
`accuracy-gate-triage`, which the standing order forbids for this block. Opening
by hand would bypass a mandatory workflow. When billing is resolved, merge PR #78
first, then run `accuracy-pr-land` for #30, then #27 (M0.3) is unblocked.

**RESOLVED 2026-08-23, but not by a billing fix.** The human added an explicit,
recorded CI waiver to `accuracy-pr-land` (commit `1289d8b`,
`allow_merge_without_ci: "<reason>"`), so the queue drains on local gates alone
while Actions still cannot provision a runner. #77/PR #78 merged first
(develop `c66ef5b`); #30 followed under the same waiver. The billing block
itself is **still open** — see the section below, and drop the waiver the
moment Actions can run.

---

## RESOLVED — 2026-08-22 — GitHub Actions is billing-blocked: no PR can merge

**Raised:** 2026-08-22 · **Status:** **RESOLVED 2026-08-23**, by the human
making the repository **public** — see the resolution note at the end of this
section. It did need a human with org billing access, exactly as this section
said; nothing in the repository could have resolved it.

### What is broken

GitHub Actions refuses to allocate runners for the `LemelyIG` org. Every job on
PR #78 (run `32547620531`) failed, with this annotation attached to all five:

> The job was not started because recent account payments have failed or your
> spending limit needs to be increased. Please check the 'Billing & plans'
> section in your settings

### Why this is not a code failure — verified directly, not inferred

1. **No compute was consumed.**
   `gh api repos/LemelyIG/Lemely/actions/runs/32547620531/timing` reports
   `duration_ms: 0` for all five `job_runs`, `total_ms: 0`.
2. **No step ever ran.** All five jobs report `steps=0` and completed in 1–5s.
   No checkout, no `setup-python`, no install.
3. **It hit heterogeneous jobs identically.** Three Python versions *and* the
   Node/npm `web` job, which shares no deps, fixtures or caches with them,
   failed the same way in the same second. No dependency drift, version skew,
   or stale hook cache can do that.
4. **The change under test was refuted by experiment**, not assumed innocent:
   at PR head `03639fa`, in a clean detached worktree with a fresh venv and a
   fresh `PRE_COMMIT_HOME`, `pre-commit run --all-files` passed all 10 hooks.

`failing_job` is reported as `pre-commit` only because it is listed first; it
is collateral, not the cause.

### Scope: this halts the whole programme, not just #77

No feature → `develop` PR can satisfy §7.1's "CI green" precondition while this
stands. **PR #78 (#77) is open, reviewed clean, and deliberately NOT merged.**

The accuracy work itself is unaffected and continues to be verifiable: the
supervisor's full-suite sweep at 2026-08-22T05:47 covered `372e483`, which sits
on top of #77's implementation commit, with pytest absent from its failures.

### When it started

**This is new, and it is not the recurrence the triage suggested.** Run
`32200705566` (2026-08-19), which the triage cited as a prior block, in fact
ran with 5 jobs carrying real step lists — a genuine failure, a different
thing. The six runs before this one, all on 2026-08-21, succeeded normally with
real billable minutes. The block therefore began between `32541604166`
(2026-08-22T00:50, success) and `32547620531` (2026-08-22T02:56, blocked).

### What a human needs to do

Resolve billing in the `LemelyIG` org's **Settings → Billing & plans** — either
a failed payment method or a spending limit that needs raising. Whether the
org's monthly consumption is also near its cap is **unmeasurable from here**:
it needs `admin:org` scope, which requires interactive human consent, so it is
recorded as an open question rather than guessed at.

### What was deliberately NOT done

- **Did not merge PR #78.** §7.1 requires CI green; a billing block is not
  green, and merging on a "the supervisor sweep covered it" argument would set
  the precedent that CI is optional whenever it is inconvenient.
- **Did not re-run the workflow.** Zero billable minutes means a re-run
  produces the identical rejection; re-running would be hoping for a different
  answer from an unchanged cause.
- **Did not touch `.github/workflows/` to reduce the CI matrix.** Shrinking the
  gate to fit a billing constraint would be weakening a gate for a reason that
  has nothing to do with correctness.

### RESOLVED — 2026-08-23. Actions provisions runners again; the waiver is void

**How it was fixed: the human made the repository public.** Recorded because
the mechanism is not interchangeable with the other routes this section
proposed. The diagnosis was exhausted free-tier minutes against a $0 spending
limit on a private repo — GitHub's annotation covers both that and a failed
payment, and the discriminating endpoints (`orgs/.../settings/billing/actions`,
`orgs/.../actions/permissions`) returned `410` and `403` respectively, so the
run that raised this could not tell the two apart. The human confirmed it was
minute exhaustion. Public repositories get unlimited Actions minutes, so the
constraint is now structurally gone rather than reset — it will not recur next
billing cycle, and no spending limit needs watching.

Three consequences that outlive the blocker, none of them CI:

1. **Branch protection and rulesets are now available.** Both previously
   returned `403 "Upgrade to GitHub Pro or make this repository public"`, which
   is precisely why four PRs could merge with `mergeStateStatus: UNSTABLE` and
   zero CI. Required status checks on `develop` would make the
   `allow_merge_without_ci` waiver structurally unnecessary rather than merely
   lapsed. **Not enabled as of this writing.**
2. **Secret scanning and push protection are free here and are `disabled`.**
   Push protection blocks a credential at `git push` rather than reporting it
   afterwards. A history scan found nothing to rotate — `.env` was never
   committed (`.gitignore:42`), no `AIza…` or `GEMINI_API_KEY=<value>` hits
   across all refs, and every `service_role` hit is a variable name or a
   `"..."` placeholder — but that is a point-in-time result, not a control.
3. **A self-hosted runner is now the unsafe option, and earlier advice in this
   programme said the opposite.** That advice was correct for a private repo:
   the standard warning is about untrusted fork PRs, which a private repo does
   not receive. A public repo does, and a self-hosted runner would execute
   fork-PR code on the host. Moot as well as unsafe now that minutes are free —
   but the reversal is recorded so the old reasoning is not found and reused.

Confirmed by the `steps` test this file itself prescribed as the only valid one,
re-run against the API rather than taken from the state file: run
**32642107118** (head_sha `6349545`, PR #82 for #27) returned
`conclusion=success` on **all five** jobs with real step lists — `web` 10,
`pre-commit` 8, `test (3.12)/(3.13)/(3.14)` 16 each. A blocked job reports
`steps=0`; none of these does. The two runs before it (`32640877782`,
`32640843306`) are also post-fix.

So #27's PR #82 is the **first merge in this programme to land on genuinely
green CI**. Every earlier merge (#77/#30/#33/#29) rested on local gates plus the
supervisor's sweep alone — see the 12:33 and 15:27 notes in
`BUILD/ACCURACY-INBOX.md` for what that bought and cost.

**The `allow_merge_without_ci` waiver lapsed by its own terms** ("the moment
Actions can provision a runner"). It must never be passed to `accuracy-pr-land`
again unless `steps=0` returns and is re-verified by the test above.

Worth keeping: the first honest CI run immediately caught something local gates
had missed — 12 evidence JSONs under `BUILD/accuracy-runs/` without trailing
newlines, because `pre-commit` had been run on selected files rather than
`--all-files`. That is the gate doing its job on its first opportunity.

---

## #77 — No entrypoint can set cache_mode: an A/A floor run today would measure the cache and publish 0.0

**Raised:** 2026-08-22 · **Status:** **RESOLVED 2026-08-22** · **Source:** `scripts/accuracy_board.py block`

Blocked on GitHub Actions org billing block — CI cannot run, see BUILD/BLOCKERS.md (2026-08-22). Board Status set back to Backlog. Resolve the blocker, append a RESOLVED line here, and move the item back to Ready.

### RESOLVED — 2026-08-22, by PR #78 merging under the recorded CI waiver

Issue #77 is **closed** and PR #78 merged to `develop` (`c66ef5b`) under the
human's explicit `allow_merge_without_ci` waiver (commit `1289d8b`), while the
billing block above still stood. `--cache-mode` is wired end to end, which is
what unblocked #27's A/A floor run — and that run used `bypass`, so the shared
cache was never written (evidence E2 in `BUILD/ACCURACY-STATE.md`).

This section was left reading `OPEN` for a day after the fact; it is corrected
here rather than deleted, per this file's own never-delete rule.

---

## OPEN — 2026-08-23 — #28 (M0.4 ablation) is halted awaiting human spend authorisation

**Raised:** 2026-08-23 · **Status:** **OPEN — needs the human, and only the
human.** This is not a puzzle to solve from inside a run.

### What is blocked

**#28 — M0.4, the oracle-transcription 2×2 ablation.** It is the last
agent-shaped item in M0 (the other M0 Backlog entry is the epic #24 itself,
which closes when its children do). M1 (#36–#41) is gated behind M0 by spec
§3.2's ordering, and #57/#59 wait on #44. So with #28 held, **the board has
nothing Ready and nothing startable** — `accuracy_board.py next` returns
"nothing ready", correctly.

### Why it is held

#28 is a **separate live sweep that spends real Gemini budget**. The 15:27
inbox directive authorising #27 said in terms: *"No further spend is authorised
for #27 beyond that"* — and the 12:33 note before it had already carved #28's
class out explicitly. #28 therefore **does not inherit** #27's after-the-fact
authorisation.

### The rule this section exists to hold

Recorded because it was broken once today, on #27, and the human rebuked it:

> **An inbox item naming an issue as needing its own authorisation is a hard
> stop until the human answers.** While waiting, pick independent work or end
> the run. Never re-derive the gate away.

The specific failure to not repeat: arguing from MISSION §3.2 ("you maintain the
Ready column yourself") and §10 (costed preflight, 80%-of-ceiling stop-and-ask)
that the item was eligible anyway. Those readings of the mission are correct in
isolation, which is exactly why they are not the point — **the inbox outranks
the mission**, and a §3.2 argument cannot retire an inbox carve-out.

### What unblocks it

One line in `BUILD/ACCURACY-INBOX.md` (or a publish to the control topic)
authorising #28's spend, ideally with a preflight ceiling in the shape #27's
directive used. Remaining headroom is **$25.00 ceiling − ~$3.83 corrected**
(ledger `spend_usd: 1.425511` × the pre-M0.2 understatement factor), so cost is
not the constraint — authorisation is.

### What was deliberately NOT done

- **Did not start the #28 preflight.** A costed preflight is cheap, but running
  one is the first step of the sweep and would prejudge the answer.
- **Did not re-run or extend the #27 A/A floor.** It is published and ratified;
  MISSION §12.9 forbids re-running at higher `n` to chase significance.
- **Did not move any board item to Ready** to manufacture startable work.

### RESOLVED — 2026-08-24. Authorised, run, and the result was NOT REPORTABLE

The header above still read "OPEN — needs the human, and only the human" three
runs after it stopped being true; corrected here rather than left to mislead.

The human authorised #28's spend on `BUILD/ACCURACY-INBOX.md`
(2026-08-24T01:14:03+03:00) with **no per-item cap**, MISSION §10's
$20.00-of-$25.00 stop-and-ask as the only ceiling, `--cache-mode bypass`
binding, and "NOT REPORTABLE, with reason" pre-accepted as a success. The
sweep ran as `ablation-2026-08-24-a`, **#28 is CLOSED**, and PR #87 merged.

The verdict was **NOT REPORTABLE as an ablation**, and that is the recorded
outcome, not a failure to retry: the `oracle+mark` arm produced **zero**
records, because `measure_accuracy()` picks the arm from `case.scan_path` and
all 11 golden cases ship a `scan.pdf`, so the oracle branch is dead code. With
one arm empty there is no A/B delta to test and `same_denominator_both_arms`
is false. It was **not** re-run at higher `n` — MISSION §12.9 forbids that.

What the run does support, descriptively and single-arm only, is in the state
pointer's `last_run_headline`: extract+mark leaf accuracy 77.4% (24/31, Wilson
[60.2%, 88.6%]) and a real review-budget ratchet breach at 29.03%.

---

## B: #36 (M1.1) — two of the issue's own acceptance bullets conflict once the third is implemented

**Status: OPEN. Blocked on a human decision, not on engineering.** Opened
2026-08-23. Branch `feature/accuracy-36-the-confidence-unit-must-ship-as-one`
exists, one signed commit `2cae804`, tree clean, all local gates green, **no PR
opened**. Board item stays *In progress*.

### The conflict

- **Bullet 1** requires extraction confidence to actually drive per-question
  confidence. It is currently unmet: `_build_mcq_corrected`'s success branch
  (`lemely/io/correction_ai.py:182-194`) still hardcodes
  `confidence_score=1.0 / HIGH / needs_teacher_review=False`, so the new
  `extraction_confidence` field is threaded but read by no decision path.
- **Bullet 2** as written asks that "a raw-0.90 single-letter answer with
  `source_region` set ends at ≤0.20, **not 0.23 or 1.00**". Those two rejected
  values come from **two different inputs** on `develop`, not one: a clean
  single letter took an uncapped `+0.1` (→1.00), while an MCQ *hint* whose
  answer is not A/B/C/D took `min(conf, 0.2)` and leaked to 0.23. Satisfying
  the bullet literally means capping clean single letters at 0.2 — a **new**
  ceiling, not the "cap ordering fixed" the bullet's own title describes.
- **Bullet 7** requires `review_rate_signal ≤ 8%`. Implementing 1 and 2-as-
  written makes every correctly-extracted MCQ read LOW / needs-review — the
  whole det path, 8 of 31 golden leaves (~26%) — on top of a `review_rate_signal`
  already measured at **32.58%**. §9 gate 8 judges the ratchet on that number.

### Why this was escalated instead of decided

The engineering-clean reading is (A): delete only the bonus, leave the 0.2 cap
on the mcq-hint-non-letter case where `develop` had it, so a clean letter keeps
its raw confidence (0.90 + 0.03 = 0.93, which **violates** bullet 2's "≤0.20").
That reading was **not** taken unilaterally for one reason: **it is the option
that makes the gated metric easier.** Lowering MCQ review volume is exactly the
narrowed-denominator / moved-goalpost shape `accuracy-reviewer` exists to catch,
and an agent picking it on its own judgement is indistinguishable from that
failure mode even when the argument is good. Structurally this is the **DA1**
situation — a spec sentence unsatisfiable as written — and DA1's precedent is to
propose the amendment and leave the spec alone until the human says.

### What unblocks it

A choice on #36 between **(A)** cap scoped to the non-letter case, bullet 2
amended to name that input; **(B)** cap all MCQ-shaped answers at 0.2 as bullet 2
literally reads, accept every correct MCQ becoming needs-review, and formally
retire bullet 7 for M1.1 (it is already unmet at 32.58%, and gate 8 keeps the M0
breach recorded-not-blocking, so this may be the honest answer); or **(C)**
something else. Full evidence is in the 2026-08-23 comment on issue #36.

### Resolved in this cycle, recorded so it is not re-litigated

`paper_grade_confidence` originally weighted by `truth_marks`, which is marks
**earned**, not the tariff — 23 of 71 baseline rows dropped, including the
corpus minima `marker_conf` 0.55 and 0.65, biasing every band upward and making
an all-zero paper vanish. Fixed by weighting on the tariff via a new
`EvalRecord.maximum_marks: int | None = None`; the default is load-bearing
(`StrictModel` is `extra="forbid"`, which rejects unknown keys but accepts a
missing key with a default), so the published `aa-floor-2026-08-23-a` evidence
still parses — verified, all 71 rows load. Rows weighted 48/71 → 71/71.

**Bullet 6 is unmet and the fix did not rescue it.** The hypothesis that the
`truth_marks` bias caused the all-HIGH degeneracy was **wrong**: the
distribution is all-HIGH before and after (0.947 / 0.9197 / 1.0 / 0.9362 /
0.982). Recorded as measured. It is structurally guaranteed while `marker_conf`
is pinned at 1.0 for every correct MCQ, so re-read it once bullet 1 lands.

---

## #36 — M1.1 — The confidence unit (must ship as one commit)

**Raised:** 2026-08-23 · **Status:** OPEN → RESOLVED 2026-08-25 · **Source:** `scripts/accuracy_board.py block`

Blocked on HUMAN DECISION: acceptance bullets 1, 2 and 7 conflict — full write-up
in **section B above**, and in the 2026-08-23 comment on #36. Branch
`feature/accuracy-36-the-confidence-unit-must-ship-as-one` is implemented,
reviewed and complete at `2cae804` (signed, gates green); it is **not
abandoned**, it is waiting on a choice between options A/B/C. Do not restart #36
from scratch. Board Status set back to Backlog. Resolve the blocker, append a
RESOLVED line here, and move the item back to Ready.

**RESOLVED 2026-08-25 — the blocker was a decision, and the human made it.**
#36 is CLOSED (2026-08-24T01:41:06Z). The 2026-08-24T01:14:03 directive chose
**option A**: scope the 0.2 confidence cap to the mcq-hint-non-letter case where
`develop` had it, so a clean single letter keeps its raw confidence. Option B
(cap every MCQ-shaped answer) was declined on product grounds — it would have
recreated the exact pathology **B3 above** was opened to fix, sending every
*correct* MCQ answer to the review queue. Acceptance bullet 7
(`review_rate_signal <= 8%`) is **DEFERRED to the M0.9 ratchet work and is NOT
met** — recorded deferred-unmet, never as met. #36 landed on bullets 1-6.

## C: #40 (M1.5) — a live review-escalation trigger is shipping unmeasured

**Status: OPEN. Blocked on a human decision (authorise a sweep, or accept the
gap explicitly).** Opened 2026-08-23. Branch
`feature/accuracy-40-coherence-gate-awarded-marks-must`, **PR #83 OPEN and NOT
merged**, CI green, six review dimensions clean. Board item moved off *In
review*.

### The blocker

Acceptance bullet 4 of #40 — *"contribution to `review_rate` measured and
reported separately"* — is **unmet**, and the thing it guards is real:

- `_check_coherence` is a **fourth OR-branch** of `needs_teacher_review`
  (`lemely/io/correction_ai.py:464`:
  `low_confidence or out_of_range or value_mismatch or coherence_mismatch`),
  so the gate creates review flags that would not otherwise exist.
- `_review_triggers` (`lemely/accuracy/harness.py`) appends
  `"coherence_mismatch"` **alongside** the generic `"needs_teacher_review"`,
  never instead of it, and `review_rate` counts a leaf as reviewed on any
  non-`random_audit` trigger. So the gate **raises** `review_rate_signal` and
  `review_rate_total`.
- **MISSION §9 gate 8:** *"Any change that could raise review volume is
  measured against the ratchet **before** merge, not after."* No before/after
  corpus number exists.

The measured `review_rate_signal` is already **32.58%** against an 8% target,
so this trigger consumes headroom that is already gone.

### Why the measurement could not simply be taken

- The historical route is barred: the 181 cached `AIMarkResponse` payloads
  under `.lemely-cache/gemini/` carry `matched_point_ids` but **no
  question-identity linkage** and no manifest, and `gemini.py` exposes no
  zero-spend cache-hit-only replay mode (only `read_write`/`bypass`/`refresh`).
- The forward route is barred by authorisation, not by capability: a live
  sweep spends money and none is authorised.

### Corrections this blocker also records

1. **"#40 landed" is false.** Commit `a7b99e3`'s message says
   *"#40 landed; clear in-progress marker"*. It never landed. The message
   cannot be rewritten (pushed, and CI ran on it), so it is corrected here and
   in the state pointer rather than silently left standing.
2. **The orchestrator's "the machinery is delivered and wired, only the number
   awaits a sweep" was wrong** — `coherence_trigger_rate()` had *zero* call
   sites until `4a9e216`. The reporting path is now wired and test-covered;
   still no corpus number.
3. **"Reported separately" was being read as "review-budget neutral."** It is
   not. The *metric* is kept out of the gate; the *trigger* still moves
   `review_rate`. The comment in `cli.py` and the `_review_triggers` docstring
   both implied otherwise and have been corrected.

### What unblocks it

Either **(a)** authorise the sweep that produces `coherence_trigger_rate` and
the before/after delta to `review_rate_signal`/`review_rate_total` on the
corpus (record it in DECISIONS.md, then #40 lands); or **(b)** decide
explicitly that a live review-escalation trigger may ship unmeasured ahead of
the M0.9 ratchet being armed, and say so on #40 — at which point the bullet is
formally retired rather than quietly skipped. A third option, **(c)**, is to
add a cache-hit-only replay mode to `gemini.py` (zero spend by construction)
and measure that way, but that is new scope and belongs in its own issue.

---

## #40 — M1.5 — Coherence gate: awarded marks must reconcile with matched point ids

**Raised:** 2026-08-23 · **Status:** OPEN → RESOLVED 2026-08-25 · **Source:** `scripts/accuracy_board.py block`

Blocked on HUMAN DECISION: acceptance bullet 4 unmet — the coherence trigger raises review_rate by an unmeasured amount, and MISSION 9 gate 8 requires that measured BEFORE merge. Options A/B/C in BUILD/BLOCKERS.md section C and the 2026-08-23 comment on #40. PR #83 is OPEN, green, complete at 80bed91 — do NOT restart #40 from scratch.. Board Status set back to Backlog. Resolve the blocker, append a RESOLVED line here, and move the item back to Ready.

---

**RESOLVED 2026-08-25 — landed, with acceptance bullet 4 formally RETIRED-UNMET.**
#40 is CLOSED (2026-08-23T22:59:34Z); PR #83 merged green on all 5 CI jobs
(run 32659077135). The 2026-08-24T01:14:03 directive retired bullet 4
explicitly — not skipped, not recorded met — and required the retirement note to
state that **a live review-escalation trigger shipped ahead of the M0.9 ratchet
being armed, so its contribution to `review_rate` is unmeasured.** That note is
on the issue, posted before the merge. Consistent with the same directive's
gate-9 scoping: #40 changes review routing, not awarded marks, so no per-item
sweep was owed.

---

## D: M1 as a whole is gated on measurement authorisation, not on engineering

**Status: OPEN — a note for the human, not a separate defect.** Raised
2026-08-23 after #36 and #40 both parked on human decisions in the same run.

Two M1 items were taken start-to-finish this run. Both are engineering-complete
with green gates, and **both stopped for the same underlying reason**: a number
is required before merge, and producing it needs a sweep nobody has authorised.

- **#36 (M1.1)** — bullet 7 (`review_rate_signal <= 8%`) sits against a
  measured 32.58%, and bullets 1/2/7 are mutually unsatisfiable as written
  (§B).
- **#40 (M1.5)** — bullet 4 requires the coherence trigger's contribution to
  `review_rate` measured *before* merge, per MISSION §9 gate 8 (§C).

This is not a coincidence of two issues. **MISSION §9 gate 9** states the M1
milestone gates apply *"on every M1 item: non-regression on the signed
over/under split (α=0.05) is the blocking condition; McNemar reported, not
gated; flag recall not below the M0 baseline."* Every one of those is a
measurement over a corpus. So on the current reading, **no M1 item can merge
without a sweep**, and the remaining unstarted items look the same:

| Item | Why it needs a number |
|---|---|
| #37 M1.2 | co-commit requires "the metric's CI-target re-derivation" |
| #38 M1.3 | mark-lowering; §9 gate 9 over/under non-regression |
| #39 M1.4 | mark-lowering; same |
| #41 M1.6 | mark-raising **and** bumps a prompt `VERSION` (invalidates cache) |
| #58 M1.8 | acceptance bullet 4 mandates `cache_mode=bypass` — a live sweep |

**The practical consequence.** Authorising one sweep does not just unblock one
issue — it is the thing standing between the programme and the whole of M1.
Conversely, continuing to take M1 items one at a time will keep producing
complete-but-unmergeable branches, which is what happened twice today.

**Not claimed here:** that §9 gate 9 *must* be read per-item rather than
once at milestone close. That reading is the strict one and is what this run
followed; a human may reasonably rule it applies at M1 completion instead,
which would let several items land now and be measured together. **That
re-reading is itself a decision worth making explicitly**, and it is cheaper
than authorising five separate sweeps.

---

## E: #57 (M0.7b) is blocked — the restored corpus is PDFs, and the split needs PARSED schemes

**Status: OPEN, but NOT on what this header originally said.** Raised
2026-08-23 immediately after #44 merged, when it *was* blocked on a human
decision about spend. That was answered on 2026-08-24 — see "UNBLOCKED
2026-08-24 by route (A) + (C)" below. **#57 is now blocked on #88**, and the
"volume problem" framing in the next two sections was **measured wrong**; read
"The finding that changes the shape of the problem" at the end before citing
anything above it.

### What #44 actually delivered, and what it did not

#44 restored **1488 PDFs** and a committed digest manifest. It did **not**
produce structured mark schemes: `find /home/sico/PaperScraper/papers -name
'*.json'` (excluding the catalogue) returns **0**. The only parsed schemes in
the tree are the **11** `tests/golden/*/mark_scheme.json` files — **71 leaf
questions** — plus 2 JSONs under `Sources/`.

### Why that blocks #57

#57's binding constraints (posted on the issue, from DA1) require strata of
**syllabus code × parse path (det/Gemini) × tariff band (1 / 2 / 3+ marks)**.
Tariff band and parse path are properties of a *parsed* scheme. A PDF supplies
neither. So the "restored corpus" #57 is supposed to stratify over cannot be
enumerated into leaf questions at all in its current form.

The target is ~300 leaves (10/60/30 → ≈30/180/90). Available: 71.

### Why freezing over the 71 golden leaves would be a mistake, not a shortcut

The constraints do say *"Splits land under target n; M0.5's exclusion funnel
publishes the shortfall"*, so under-target is anticipated — but they also say
**"Amendments — drop-only … never draw a backfill"** and the membership is
**frozen**. Freezing over 71 leaves while 1488 unparsed papers sit on disk
would be **irreversible by rule**, would discard most of what #44 was run to
obtain, and would permanently cap the labelling corpus at roughly a quarter of
its intended size. The drop-only rule exists to stop backfilling *after* a
principled freeze — not to license freezing early and calling the gap a
shortfall.

### The missing step nobody scoped

Between #44 (fetch PDFs) and #57 (split leaf questions) there is an unlisted
prerequisite: **parse the restored corpus into structured mark schemes.** The
det parser handles MCQ schemes at zero cost, but theory schemes go through the
Gemini mark-scheme parser, which **spends money**. No authorisation exists for
that, and #28's standing rule is that spend waits for the human.

### What unblocks it

- **(A)** Authorise a mark-scheme parsing pass over enough of the restored
  corpus to reach ~300 leaves, with a costed preflight first; then #57 runs as
  specified.
- **(B)** Rule that #57 may freeze over a smaller corpus, stating explicitly
  that the resulting n is accepted and permanent under the drop-only rule.
- **(C)** Scope the parsing step as its own issue (it plausibly overlaps #45,
  M2.2's failure-reason census over failing mark schemes, which also needs
  parsed schemes).

**Not started, deliberately.** #57 was read, its constraints were read, and the
prerequisite gap was found before any branch was cut — not discovered halfway
through an implementation.

### UNBLOCKED 2026-08-24 by route (A) + (C) — the parsing pass is now #88

The human took **route (A)** on `BUILD/ACCURACY-INBOX.md` (2026-08-24T01:14:03+03:00):
a mark-scheme parsing pass over the restored corpus **is authorised**, with a
costed preflight first, deterministic MCQ parsing first at zero cost, and
MISSION §10's $20.00-of-$25.00 stop-and-ask governing. Freezing over the 71
golden leaves — route (B) — was **considered and explicitly rejected**, because
the drop-only rule would make it irreversible and it would discard most of what
#44 fetched.

The **structuring half of route (C) was left to the orchestrator** and is now
decided: the parsing pass is **its own issue, #88 (M2.1b)**, not work buried
inside #57. The deciding fact is spend, not tidiness — #45 (M2.2) requires
*"every failing scheme's failure cause classified"*, and that failing set is
exactly what the det parser emits when run over the corpus, which is the same
run #57 needs for its strata. One run, two consumers; two runs would pay the
Gemini theory-scheme cost twice.

**#57 stays blocked, now on #88 rather than on a human decision.**

### The finding that changes the shape of the problem

The gap was framed above as *"the target is ~300 leaves; available: 71"* — a
**volume** problem. Measured at zero cost, that framing is wrong.

The 40 restored 0625 paper-1 (MCQ) schemes parse deterministically **40/40 in
12 seconds** and yield **1600 leaf questions** — more than five times the ~300
target. But every one of them is 0625, det-path, tariff band 1, so they
populate **1 of DA1's 18 strata** (3 syllabus × 2 parse path × 3 tariff band).

So the binding constraint on #57 is **stratum coverage, not leaf count**. Two
consequences follow, and neither was visible before the parse ran:

1. Tariff bands 2 and 3+, and syllabi 0580/0606, exist only on **theory**
   papers — the schemes that are expensive to parse.
2. Production parses with `ChainedMarkSchemeParser(primary=det, fallback=gemini)`,
   so a scheme's parse path is **det if det succeeded and Gemini if det
   failed**. A det-only corpus therefore leaves **every Gemini-path stratum
   empty by construction**, and #57 could not be stratified as its own binding
   constraints require. Populating that half is not optional enrichment.

The silver lining is that the population needing paid parsing is *exactly* the
det failure set, so #88's preflight denominator is a **measured count rather
than an estimate**.

---

## #57 — M0.7b — Freeze the split membership over the restored corpus

**Raised:** 2026-08-23 · **Status:** OPEN · **Source:** `scripts/accuracy_board.py block`

Blocked on PREREQUISITE GAP: #44 restored 1488 PDFs but ZERO parsed mark schemes; this issue's strata need tariff band + parse path, which only a parsed scheme supplies. 71 golden leaves available vs a ~300 target. Freezing over 71 would be irreversible under the drop-only rule. Needs a human call on parsing spend — BUILD/BLOCKERS.md section E.. Board Status set back to Backlog. Resolve the blocker, append a RESOLVED line here, and move the item back to Ready.

**CORRECTED 2026-08-24 (the RESOLVED line this block asks for).** Two factual
claims above are now falsified by measurement and must not be cited:

- *"ZERO parsed mark schemes"* — the det parser produced **250 parsed schemes
  (52.2% of 479)** at **$0.00**. Evidence:
  `BUILD/accuracy-runs/census-2026-08-24-a/`.
- *"71 golden leaves available vs a ~300 target"* — the det path alone yields
  **9,464 leaf questions**, roughly **32× the ~300 target**. Leaf volume was
  never the binding constraint.
  *(Corrected 2026-08-25, ratified by the human as #88 item 3: this line read
  **12,358** and **41×**. 12,358 was every question at every depth — 2,894
  parents + 9,464 true leaves — because `census_leaves.py` filtered on a
  `sub_questions` field that `Question` does not have. The conclusion is
  unchanged and the error ran toward overstatement; see
  `BUILD/accuracy-runs/census-2026-08-24-a/manifest.json` →
  `leaves.CORRECTION_2026-08-25`.)*

**#57 stays blocked**, but on the real constraint, which is **stratum
coverage**: 9 of DA1's 18 strata are populated (all det-path); the 9
Gemini-path strata are empty *by construction* and can only be filled by paying
to parse the 229-scheme det failure set. That is question 1 on **#88**, which
is what #57 now waits on. Board Status stays Backlog until #88 resolves.

---

## SUPERSEDED — §D is retired by the 2026-08-24 gate-9 scoping directive

`## D: M1 as a whole is gated on measurement authorisation, not on engineering`
above recorded the **strict per-item** reading of MISSION §9 gate 9. The human
retired that reading on **2026-08-24T01:14:03**:

> gate 9 applies per item **only to mark-changing items**. #38 (M1.3), #39
> (M1.4) and #41 (M1.6) change awarded marks and each need their own
> before/after measurement before merge. Items that change confidence, review
> routing or reporting **without** changing awarded marks land on engineering
> grounds and fold into a single milestone-close sweep at M1 completion.

The test is **what the code does, not which milestone the issue sits in**: if a
diff can change the mark a student receives, it needs its number first.

§D is left in place rather than deleted — it is the reasoning that produced two
complete-but-unmergeable branches on 2026-08-23, and the directive names that
outcome as the thing it is correcting. Read §D as history, not as policy.

**Consequently resolved:** §B (#36) and §C (#40) are both decided — see the
2026-08-24 inbox entries. §E (#57) is unblocked via option A, with a
mark-scheme parsing pass authorised.

---

## #28 — M0.4 — Oracle-transcription ablation (the 2×2)

**Raised:** 2026-08-24 · **Status:** OPEN → RESOLVED 2026-08-25 · **Source:** `scripts/accuracy_board.py block`

Blocked on IMPLEMENTATION REQUIRED FIRST, not more spend: the oracle+mark arm is dead code (harness.py:670-671 picks the arm from case.scan_path and all 11 fixtures ship scan.pdf), so run ablation-2026-08-24-a produced ONE arm and NO 2x2. Acceptance bullet 1 ('Both arms run over all fixtures') is implementation work. Do NOT re-run the sweep until a mechanism exists to force oracle+mark over cases that already have a scan_path. See the 2026-08-24 comment on #28.. Board Status set back to Backlog. Resolve the blocker, append a RESOLVED line here, and move the item back to Ready.

**RESOLVED 2026-08-25 — the mechanism landed the same day this was written, and
nobody updated the record.** Verified at source, not inferred: **PR #87 merged
2026-08-24T03:31Z**, is on `develop` and in this branch's history, and supplies
exactly the missing forcing mechanism —

- `lemely/accuracy/harness.py:626` — `arm: Literal["extract+mark", "oracle+mark"] | None`
- `lemely/accuracy/harness.py:705-710` — when `arm` is set, `case_arm = arm`
  **uniformly**, overriding the `scan_path` auto-selection; the oracle bypass at
  `:733` is reachable
- `lemely/accuracy/harness.py:678-684` — `arm="extract+mark"` raises up front if
  any case lacks a `scan_path`; no silent fallback
- `lemely/app/cli.py:1013-1025` — a `--arm` flag, wired to `measure_accuracy(arm=…)` at `:1081`

Tested, not merely present: `tests/test_accuracy_harness.py:313` and `:352`
(`test_both_arms_over_same_cases_produce_ablation_2x2_nonzero`). This entry's
own release condition — *"until a mechanism exists to force oracle+mark over
cases that already have a scan_path"* — **is met**.

**But do NOT read this as "M0.4 is done."** #28 is CLOSED with **every
acceptance box unticked**, and the only ablation ever run
(`ablation-2026-08-24-a`) is published as **NOT REPORTABLE** — zero oracle+mark
records, no delta, `same_denominator_both_arms=false`. The issue was closed on
PR #87, i.e. on the *mechanism*, while M0.4's deliverable is the **2×2 itself**.
The number has never been produced.

**Re-running would not be §12.9 significance-chasing.** That rule bars re-running
a NOT REPORTABLE sweep at higher `n` to chase significance. This run was not
underpowered — one arm of a two-arm experiment did not execute at all, so a
re-run is the *first* correct execution, not a second attempt. No larger `n` is
proposed. The blocker text above says "do NOT re-run **until** a mechanism
exists", which presupposes re-running is right once one does.

**Still needs a human, and the board item is deliberately NOT force-moved.** It
sits in Backlog while the issue is CLOSED; which column is right depends on the
ruling. The 2026-08-24T01:14:03 directive authorised this sweep specifically
(no per-item cap, costed preflight before spend, `--cache-mode bypass` never
`refresh` per E2, stop-and-ask at $20.00 of $25.00) and that authorisation is
**unspent** — the ~$0.06 of `ablation-2026-08-24-a` went on the broken
single-arm run. The open question, posted on #28 as (a)/(b)/(c): **does a spend
authorisation granted while the issue was open survive the issue being
CLOSED?** Recommended (a) — reopen and run — but **not acted on**, because
choosing the reading that unlocks spending is precisely the move the #27 rebuke
was about.

**Status-line correction 2026-08-25:** the `**Status:** OPEN` line above predates
the RESOLVED note that follows it and was never updated; #28 is CLOSED
(2026-08-24T03:31:28Z). Recorded for completeness, per the 2026-08-25T12:03:43
directive: #28 stays closed **with its acceptance boxes unticked** — that is the
honest record, the 2x2 still does not exist, and PR #87's arm mechanism landing
is **not** permission to spend. A spend authorisation does not survive its issue
being closed.

---

## F — #88 (M2.1b) awaits three human decisions; the parse itself is done and free

**Raised:** 2026-08-24 · **Status:** OPEN — waiting on the human, not on
infrastructure. **No spend has occurred.**

The zero-cost half of #88 is **complete**: the deterministic parser ran over
all 479 restored mark schemes and produced **250 parsed (52.2%)**, **229
failures**, and **9,464 leaf questions** (12,358 questions at every depth, of
which 2,894 are parents) — at $0.00. The costed preflight is posted on #88 as
the authorisation required. *(Leaf figure corrected 2026-08-25 per #88 item 3;
it read 12,358.)*

**Where the evidence lives (added 2026-08-24).** The census originally existed
only in `/tmp/acc57-full`, which is not durable. It has been re-verified — every
figure above reproduced exactly — and persisted to
**`BUILD/accuracy-runs/census-2026-08-24-a/`**: `manifest.json` (counts, the
DA1 strata table, the `profiles.py:50` bug, reproduction steps),
`census-leaves.txt`, `census-failures.txt`, `det-failures.txt` (the 229-stem
failure set #45 consumes) and the two scripts.

Two cautions for whoever reads it. The **250 parsed `MarkScheme` JSONs (~18MB)
and `parse.log` are deliberately NOT committed** — they carry CAIE mark-scheme
text verbatim and publishing real-paper content is a human decision (MISSION
§12.7); regenerate them free in ~40min via the manifest's `reproduce` steps.
And `census-leaves.txt` prints *"DA1 strata populated: 12"* because the script
counts its own `0/unknown` catch-all as a band — **do not cite the 12**; DA1
defines three bands, so the honest figure is **9 populated of 18**, with the
2894 unbanded leaves held out as question 3's subject.

### Why this is a blocker rather than "just spend the money"

`BUILD/ACCURACY-INBOX.md` (2026-08-24T01:14:03+03:00) authorised the parsing
pass *"enough to reach the ~300-leaf target"*. **That target is already met
about 41× over, at zero cost.** Every condition attached to the authorisation
was satisfied — det first, preflight posted — but the *goal it was granted for*
turned out to require no spend at all.

The only remaining reason to spend is a finding this run discovered and the
human could not have known when writing the directive: DA1's **parse-path**
stratum is `det`-if-det-succeeded / `Gemini`-if-det-failed, so the nine
Gemini-path strata are **empty by construction** and can only be filled by
paying to parse the det failure set. That is a **different justification** from
the authorised one. Per the #27 precedent recorded in the inbox, a changed
premise is stopped on and asked about, never re-reasoned into still applying.

### The three questions

1. **Spend $4.88–$6.83 to populate the Gemini-path strata?** If no, #57 must
   either drop the parse-path axis or freeze over det-only leaves — both are
   amendments to DA1, which is **H4 (#49) human territory**, not the
   orchestrator's.
2. **Fix `lemely/io/det/profiles.py:50` first?** `_PHYSICS_PROFILE` maps
   `2: PaperType.THEORY_CORE`, but the cover text reads **`Paper 2 Multiple
   Choice (Extended)`** (verified in `0625_m19_ms_22.pdf`, `0625_s19_ms_21.pdf`).
   `paper_type()` (`profiles.py:23`) consults the number map **first**, so the
   correct cover-text evidence is never reached. All 40 of `0625` p2 fail,
   while correctly-mapped p1 parses 40/40. The fix is free, is a real bug on
   its own merits, cuts the paid set by 40 schemes and the bill by ~15% — and
   it **moves 40 schemes between strata**, so it must land *before* any
   preflight is acted on or the denominator is wrong.
3. **What becomes of the 2894 unbanded leaves?** 23.4% of all leaves carry
   `marks = 0/unknown` and fit **none** of DA1's `1 / 2 / 3+` bands. Under the
   drop-only rule, excluding them is permanent. Recorded on no issue before now.

### One operational fact that binds whatever is decided

`per_run_token_ceiling` is **2,000,000** (`lemely.toml:19`), and every preflight
scenario totals **2.65M–3.51M tokens**. The parse **cannot run as a single
job**; it must be batched, or the ceiling raised deliberately. `_check_cost_ceiling`
is a pre-flight check that cannot stop a call already in flight, so batching is
the control, not the ceiling.

### For #45 (M2.2)

All 229 failures logged the same event, `mark_total_mismatch_escalating`. That
is a **symptom, not a classification** — one uniform symptom across 229 schemes
is consistent with several distinct causes, and classifying them is #45's job.
The failure set is #45's census input; #45 has been commented to take it rather
than re-run the parse, which would pay the Gemini cost twice.

## G — #45 (M2.2) census complete: the 229 det-failures are classified, ranked, $0 spend

**Raised:** 2026-08-24 · **Revised:** 2026-08-24 (round 5, corrected after
review — round 4's TWO-SIDED bound on `marks_cell_notation_not_parsed` rested
on a false premise: its `empty_count` was measured over raw table rows, not
the AnswerPoint population that actually feeds `computed_total`, and even
once that population mismatch is fixed, the DEFICIT side of the bound is
unsound for a structural reason in `lemely/io/det/rows.py`'s `flush()` — see
below) · **Status:** artifact committed, not a blocker — recorded here so M3
can cite it without re-deriving. Zero Gemini calls, zero network: the 229
PDFs already restored to `/home/sico/PaperScraper/papers` were re-parsed
offline through `lemely.io.det.*`'s own stages a second time. This script
never instantiates `DeterministicMarkSchemeParser` and never calls
`reconcile.check` at all — it compares `reconcile._leaf_marks(questions)` to
`metadata.maximum_mark` directly, so there is no `escalate_on_mark_mismatch`
flag in play (round 1 of this issue incorrectly claimed one was).

**Round 5: the round-4 deficit bound compared incommensurable quantities, and
even fixed, the deficit direction is unsound — it is now consistency-check-
only, not an enforced bound.** Round 4's `count_empty_marks_cells` iterated
RAW TABLE ROWS, while `computed_total` sums `AnswerPoint`s AFTER
`build_questions` merges rows — different populations. The proof is on the
face of the round-4 artifact: `0625_w21_ms_43` reported `empty_count=119` for
a scheme whose `maximum_mark` is 80, which cannot have 119 answer points at
all; four rows carried `empty_count >= maximum_mark`. `empty_count` is now
measured by `count_defaulted_answer_points`, which re-runs `build_questions`
once with transparent instrumentation (two module-level monkeypatches in
`lemely/io/det/rows.py`'s own namespace, restored immediately after, that
never change any return value) and counts only the `AnswerPoint`s the state
machine actually created whose marks value was defaulted by `make_point`.
Even over this corrected population, the DEFICIT claim ("every empty cell
contributes >= 1, so `computed_total` can never fall below `empty_count`")
does not survive: `flush()` only sums a leaf's `AnswerPoint`s into
`Question.marks` when that leaf's own `q_row_had_answer` flag was set (the
Q-number row itself carried an answer, or an EITHER/OR bracket appeared) — a
common table shape (Q-number row with no answer, marks on continuation rows
below it) never sets that flag, so a defaulted `AnswerPoint` can contribute
exactly 0 to `computed_total`, not >= 1. The EXCESS side remains sound (a
defaulted point contributes AT MOST 1, whether or not it is actually summed),
so `marks_cell_notation_not_parsed` is now claimed ONLY via
`computed_total > maximum_mark` and `computed_total - maximum_mark <=
empty_count`. A deficit shape now always falls through to `mismatch_cause`,
carrying a consistency-check-only note ("upper bound, deficit side
unbounded") rather than an enforced bound. This is a large, honest downward
correction, not a defect to argue away: `marks_cell_notation_not_parsed` goes
from round 4's 104/229 to **48/229**, and D7's headline share is republished
below as an explicit upper bound.

**Residual limitation, disclosed rather than hidden: the excess bound is
still near-vacuous for 2/48 notation-bucket rows.** The population fix does
not make the excess check tight everywhere — `manifest.json`'s new
`excess_bound_near_vacuous` field lists `0625_w20_ms_42` (empty=82,
maximum_mark=80) and `0625_w21_ms_43` (empty=90, maximum_mark=80), where
`empty_count >= maximum_mark` makes `computed_total - maximum_mark <=
empty_count` barely constrain anything. This is down from round 4's 4 rows
(one at empty_count=119 for a maximum_mark of 80) to 2, and both are far
closer to `maximum_mark` than round 4's inflated counts were — a real
improvement, not a full fix. Both rows stay correctly in the denominator and
labelled; the manifest states the caveat rather than claiming a tight bound
that doesn't exist.

**SUPERSEDED BY ROUND 5 — the premise below is FALSE as implemented, and the
"genuine TWO-SIDED bound" claim is RETRACTED.** `count_empty_marks_cells`
counted **raw table rows**, while `computed_total` sums **`AnswerPoint`s after
`build_questions` merges rows** — two different populations. So "every empty
cell contributes 1, therefore `computed_total` can never fall below
`empty_count`" does not hold, and every magnitude bound derived from comparing
the two compared incommensurable quantities. The artifact said so on its face:
`0625_w21_ms_43` reported `empty_count=119` for a scheme whose `maximum_mark`
is 80 — it cannot have 119 points at all. The orchestrator endorsed this
premise in the round-4 brief without checking how `empty_count` was measured;
that is why round 4 produced a "bound" that was not one. Left in place
unedited below, per the never-delete rule, as the record of what was believed.

**Round 4 (SUPERSEDED, see above): the sufficiency condition on
`marks_cell_notation_not_parsed` is
now a genuine TWO-SIDED bound.** Round 3 fixed only the excess direction
(`computed_total - maximum_mark <= empty_count`); its deficit disjunct,
`computed_total <= maximum_mark`, applied no magnitude check at all. Empty
marks cells default to EXACTLY 1 mark each
(`lemely/io/det/rows.py`'s `make_point`), so `computed_total` can never
validly fall BELOW `empty_count` under that mechanism — yet 4 committed rows
did: `0606_w23_ms_11` (empty=65, computed_total=0, its own evidence string
falsifying the label), `0625_w21_ms_41` (empty=96, computed=78),
`0606_w19_ms_13` (empty=69, computed=61), `0606_s23_ms_22` (empty=60,
computed=54). The gate is now `empty_count <= computed_total <=
maximum_mark` (deficit side) OR `computed_total - maximum_mark <=
empty_count` (excess side, unchanged); rows failing both fall through to
`mismatch_cause`. All 4 land in `genuine_mark_total_mismatch`. (Two of the
round-4 review brief's six named rows, `0625_w21_ms_43` and `0625_w21_ms_53`,
turn out on their real `maximum_mark` to be excess-explainable —
`computed_total > maximum_mark` there — so they correctly stay in the
notation bucket; only 4 of the 6 named rows were genuine deficit
counterexamples, verified directly against `classified-failures.txt`.)

**Round 4: a docstring claim of theory-path enforcement that never existed is
corrected, not implemented.** The module docstring said bucket 2's
`computed < maximum_mark / 2` shortfall check was "enforced inline in
`_classify_mcq`/`_classify_theory`"; the sole occurrence was inside
`_classify_mcq`. Rather than add an untested new heuristic to the theory path
under review pressure, the docstring is corrected to state the true,
narrower claim: the shortfall check is MCQ-path-only.
`manifest.json`'s new `table_layout_extraction_failure_note` field states
this explicitly, so the published `table_layout_extraction_failure = 0` is
not read as evidence that no theory-path shortfall exists under that
heuristic — it is a lower bound, because the heuristic was never applied
there. This choice does not change any cause count in the table below (no
theory-path row was reclassified).

**Where the evidence lives:** `BUILD/accuracy-runs/census-2026-08-24-b/` —
`classify_failures.py` (the diagnostic script; also the source of the pure
helpers unit-tested in `tests/test_census_45.py`), `manifest.json` (ranked
counts, the D7 hypothesis's measured share, the profile-misconfiguration
breakdown), and `classified-failures.txt` (one `stem<TAB>cause<TAB>evidence`
row per stem, covering all 229 stems — the ranked work-list for M3's D7
repairs).

**Round 3: every cause label now carries a checked sufficiency condition —
positive evidence the named mechanism can produce the observed magnitude —
not just a structural signal.** Round 2's `marks_cell_notation_not_parsed`
rule fired unconditionally whenever a real marks column had any empty cell,
even though empty cells default to 1 mark each
(`lemely/io/det/rows.py`'s `make_point`) and so N empty cells can inflate
`computed_total` by AT MOST N. Review reproduced 27/135 rows in that bucket
whose excess exceeded their `empty_count` (e.g. `0606_m20_ms_12`: empty=4,
excess=20) — the label was falsified by its own evidence string. That
round-3 rule (`computed_total <= maximum_mark` OR `computed_total -
maximum_mark <= empty_count`) is superseded twice over since: round 4
replaced the unconditional deficit disjunct with a magnitude-checked one, and
round 5 (see above) retired the deficit disjunct as a causal classifier
entirely, keeping it only as a consistency-check-only note. The CURRENT rule
is stated in the round-5 entry above and in `classify_failures.py`'s module
docstring (bucket 4), which every bucket's sufficiency condition is checked
against.

**Ranked cause counts (sum to 229, denominator never narrowed, every bucket
seeded so a zero count is reported rather than omitted; recomputed by a live
re-run of `classify_failures.py` in the same commit as this table):**

| cause | n | share |
|---|---|---|
| `genuine_mark_total_mismatch` | 70 | 30.6% |
| `marks_cell_notation_not_parsed` | 48 | 21.0% |
| `mark_aggregation_overcount` | 47 | 20.5% |
| `paper_profile_misconfiguration` † | 40 | 17.5% |
| `marks_column_detection_failure` | 24 | 10.5% |
| `table_layout_extraction_failure` | 0 | 0.0% |
| `UNCLASSIFIED` | 0 | 0.0% |

**† `paper_profile_misconfiguration` — 40 is the bucket population, not the
causal count.** The counterfactual reparse committed later on this same branch
(`BUILD/accuracy-runs/counterfactual-0625p2-2026-08-24/`) moved **39 of the 40**
from FAIL to PASS by correcting `profiles.py:50` alone, so those 39 are
causally demonstrated. The 40th, **`0625_s24_ms_21`, is misattributed**: it
fails identically before and after the profile fix. Its real cause was found by
direct observation (`BUILD/accuracy-runs/mechanism-0625-s24-ms-21-2026-08-24/`)
and is a *distinct* defect — CAIE withdrew question 14, so the answer cell holds
the literal `'Question Discounted'`, and `find_mcq_answer_col`
(`lemely/io/det/mcq.py:23`) requires **all** non-empty values in a candidate
column to be A/B/C/D, so one non-letter cell disqualifies the whole column and
`parse_mcq_tables` skips the entire table (28 questions lost to one cell). The
count stays 40 here because it is what the classifier assigned and what
`manifest.json` records; **a `profiles.py` fix must not be taken to retire this
row.** Blast radius of the mcq.py defect, measured: 1 of 479 schemes.

**D7 turned from a hypothesis into a measurement, and round 5 corrects the
headline downward again — this time sharply, and explicitly as an upper
bound.** D7 hypothesised that `parse_marks_cell`/`is_marks_column` failures
explain the det-parser failure set. Measured (not assumed by construction):
`marks_column_detection_failure` + `marks_cell_notation_not_parsed` =
**72/229 (31.4%)** — down from round 4's 128/229 (55.9%), itself down from
round 3's 132/229 (57.6%) and round 2's overstated 159/229 (69.4%). The
round-5 movement (128 → 72, -56 schemes, -24.5pp) is the empty-count
population fix plus the deficit-disjunct retirement described above: the 56
schemes that round 4 classified into `marks_cell_notation_not_parsed` via a
deficit shape (`computed_total <= maximum_mark`, no longer a positive
classifier) fall through to `mismatch_cause`, landing in
`genuine_mark_total_mismatch`. `manifest.json`'s `d7_hypothesis.is_upper_bound`
is `true`: this share is a ceiling on what the column/cell-detection
hypothesis explains, not a fully-enforced count, because the surviving
sufficiency check (excess-side only) is a necessary, not sufficient,
condition. The other **157/229 (68.6%)** are NOT explained by D7 — 70 show a mark-total
deficit, **of which 55 (79%) have defaulted `AnswerPoint`s and an unresolved
empty-cell explanation**, 47 are positively-evidenced overcounts
(`mark_aggregation_overcount`, unchanged since round 3), and 40 are the
profile-misconfiguration class below.

**CORRECTED 2026-08-24 — the previous wording here was falsified by the very
artifact it summarised.** It described those 70 rows as "structurally clean
parses whose total still comes up short with no more specific explanation
available". A recount of `classified-failures.txt` shows 55 of the 70 carry the
evidence note *"this count neither confirms nor rules out empty-cell defaulting
as a cause here"* — the opposite of "no more specific explanation available".
The dependent headline **"D7 is no longer the largest single explanation —
`genuine_mark_total_mismatch` now is" is WITHDRAWN**: that bucket is the
*least*-evidenced one in the taxonomy, it enforces direction only with no
magnitude bound in code, and it grew 14 → 70 purely by absorbing rows retired
from other buckets. A ranking cannot be led by a bucket that means "we do not
know". This is the same falsified-record failure that this branch's own
ancestor commit `3f50781` was written to correct.

**The residual mismatch bucket is split, not a single "totals don't match"
catch-all.** Round 1 put every `computed_total != maximum_mark` residual
(after clean column detection and zero defaulted cells) into
`genuine_mark_total_mismatch`, including rows where `computed_total >
maximum_mark` — an overcount, which is a *positive* finding (something got
double-counted), not the same claim as "the total came up short with no
further explanation". These are split: `mark_aggregation_overcount`
(computed_total > maximum_mark — also the fallthrough target for
notation-bucket rows whose excess the empty-cell defaulting cannot explain,
47 schemes total, unchanged since round 3) vs. `genuine_mark_total_mismatch`
(computed_total < maximum_mark, 70 schemes as of round 5 — up sharply from
round 4's 14 now that the deficit direction is no longer a positive
classifier for the notation bucket — and its evidence string states what was
ruled out — overcount, column detection, sufficient cell-notation parsing —
rather than only what didn't match).

**The `paper_profile_misconfiguration` rule is now gated on a counterfactual,
and round 1's "second bug instance" claim for 0625 p3 was wrong.** Round 1
counted 74 schemes into this bucket, including 34 from 0625 p3 (cover text
"Paper 3 Core Theory" vs. `paper_type_by_number[3] = THEORY_EXTENDED`) on the
theory that this mirrored the real 0625 p2 bug. It does not: `classify_one`
(mirroring the production pipeline) only ever branches on
`metadata.paper_type` once — MCQ vs. not-MCQ. 0625 p2's mapped type
(THEORY_CORE) and cover-implied type (MCQ) are on *different* sides of that
branch, so the discrepancy really does change which parser code path runs.
0625 p3's mapped type (THEORY_EXTENDED) and cover-implied type (THEORY_CORE)
are on the *same* side (both non-MCQ) — reclassifying under the cover text
would not change the parse path, so the discrepancy cannot be why any 0625 p3
scheme is in the det-failure set, whatever its exact count (this census does
not separately track a 0625-p3-only count; round 1's "34" above is that
round's own since-superseded classification, not a number re-derived by this
script). `classify_failures.py`'s `_changes_parse_path` counterfactual gate
now falsifies the p3 case and only the real 0625 p2 finding (40 schemes)
remains in `paper_profile_misconfiguration`.

**`profiles.py:52`'s 0625 p3 discrepancy is real but is recorded as a
separate, ruled-out metadata defect — not a second confirmed cause.** It is
still a genuine mismatch between what `paper_type_by_number` maps and what the
cover text says (verified in `0625_m19_ms_32.pdf`, `0625_s21_ms_32.pdf`), and
it is still flagged for the human alongside question 2 on #88 — but it is
**not** counted among the 229's causes, per the MCQ-only-branching evidence
above. `git diff` against `lemely/io/det/profiles.py` is empty after this
issue, and this p3 finding is recorded in `manifest.json`'s
`ruled_out_metadata_defect_not_a_cause`, not folded into
`known_bug_classified_not_fixed` (which now holds only the 0625 p2, 40-scheme
finding).

**Not mark-changing:** no marking-engine or `lemely/eval` code changed; per
the 2026-08-24 gate-9 scope decision this issue needed no before/after A/B
sweep, and none was run.

### ESCALATED 2026-08-24 — #45 needs a HUMAN DESIGN DECISION; agent rounds are STOPPED

**Status: #45 is NOT landable and no round 6 will be attempted.** A stopping
rule was pre-committed in commit `d2131a6`, *before* round 5 ran, precisely so
this call could not be made after seeing a result: *if round 5 blocks on the
same defect class a fifth time, stop delegating and escalate.* It did. It is.

**The defect class, stated once:** a cause bucket assigned without positive,
checked evidence that the named mechanism can produce the observed magnitude.

| round | what blocked | D7 headline |
|---|---|---|
| 1 | `genuine_mark_total_mismatch` a residual dumping ground; an inert cause (0625 p3) counted; false escalation to the human | 55.9% |
| 2 | `marks_cell_notation_not_parsed` claimed a mechanism that cannot produce the magnitude | 69.4% (false) |
| 3 | the fix applied to the excess side only; docstring claimed enforcement that did not exist | 57.6% |
| 4 | the "two-sided bound" bounded the total, not the magnitude; premise applied to 4 rows, waived on 2 identical ones | 55.9% |
| 5 | deficit rows retired *into* `genuine_mark_total_mismatch`, which has no magnitude bound at all — the evidence-free bucket **grew 14 → 70** | withdrawn |

Five rounds, and the headline oscillated 55.9 → 69.4 → 57.6 → 55.9 → withdrawn.
Round 5 did fix the root cause the orchestrator found (`empty_count` re-derived
over the `AnswerPoint` population, `is_upper_bound: true` published honestly),
and it still blocked — because the rows have to go *somewhere*, and every
"somewhere" available is a bucket whose criterion cannot be checked.

**Why this is a design question and not another patch.** The classifier infers
causes from aggregate arithmetic — `computed_total` vs `maximum_mark` vs a
count of defaulted points — without re-running the parse and observing the
mechanism. Every sufficiency condition built on that is a proxy, and each round
falsified the previous proxy. Two structural facts make this concrete:

- **117/229 (51%)** sit in buckets 5+6 with **no coded magnitude bound**.
- **`UNCLASSIFIED = 0` is structurally unreachable** for exactly the rows that
  need it: `classify_theory_residual` only returns it when
  `computed_total == maximum_mark`. The "honest unknown bucket" guarantee that
  rounds 3-5 were briefed to rely on **cannot fire**.

So the census cannot honestly say "we don't know" for a mark-total mismatch,
which is why every round had to put those rows in a bucket that claims to know.

**The question for the human.** *Can aggregate-arithmetic cause inference yield
a sound bound at all — or must a real classification re-run the parse and
observe the mechanism directly?* Depending on the answer, the 55 indeterminate
rows go to one of:

1. **`UNCLASSIFIED`** — make it reachable for mismatch rows. Honest; leaves 55
   of 229 (24%) unranked, and M3 gets a smaller but trustworthy work-list.
2. **A new, explicitly-named `cause_indeterminate` bucket** — separates "no
   cause found" from "not investigable by arithmetic". Same information, but it
   names *why* it is unknown.
3. **Instrument the parser** — re-run each failing scheme with tracing and
   record the observed mechanism. Costs a free re-parse and real implementation
   work, and is the only option that produces a genuinely evidenced ranking.

**What is already sound and should survive whatever is chosen:** the denominator
is honestly held at 229 across all five rounds; the artifacts are byte-reproduced
from live zero-cost re-runs; `lemely/io/det/profiles.py` has zero diff throughout;
`spend_usd` never moved from **1.488057** — the entire five-round census cost
**$0.00**; and no gate, threshold or assertion was ever weakened. The
`paper_profile_misconfiguration` (40) and `mark_aggregation_overcount` (47)
buckets are positively evidenced and are usable by M3 today — with one
correction M3 must carry: of the 40 profile rows, **39 are causally
demonstrated** by the counterfactual reparse and the 40th, `0625_s24_ms_21`, is
**misattributed** and carries a distinct `lemely/io/det/mcq.py` defect that a
`profiles.py` fix does not touch. See the † note under the ranked table. Cite
the bucket as 39 causal + 1 misattributed, never as 40 causal.

**Do not** resolve this by relaxing a criterion in prose, and **do not** let the
next run start a round 6. It waits for the human.

---

## H — The accuracy harness NEVER runs the det mark-scheme parser, so gate-9 cannot see #38

**Raised:** 2026-08-25 · **Status:** OPEN, needs a human ruling · **Cost to find:** $0
(det path only; ledger unmoved at 1.488057)

This one is not about a single issue. It is an **instrument gap** that silently
changes what MISSION §9 gate 9 can and cannot prove, and §D's table above
asserts the opposite of it for #38.

### The finding, read at source

Every golden case ships an **already-parsed `mark_scheme.json`**, and the
harness deserializes it directly:

- `lemely/accuracy/harness.py:82-83` — the case layout comment:
  `mark_scheme.json  — already-parsed JSON mark scheme`
- `lemely/accuracy/harness.py:103-109` —
  `MarkScheme.model_validate_json(ms_path.read_text(...))`
- `lemely/accuracy/harness.py:352-355` — the harness says so itself:

  > `parse_path` is a known gap: spec §1 defines it as the *mark scheme's*
  > parsing path (`det` = deterministic pdfplumber parser, `gemini` = AI
  > fallback), a per-paper property `load_golden_cases` **does not observe**
  > (it deserializes an already-parsed `mark_scheme.json` directly).

Confirmed against the fixture directories: each contains `answers.json`,
`case.json`, `mark_scheme.json`, `scan.pdf`. The **only** PDF is `scan.pdf` —
the student script, which feeds vision extraction, not scheme parsing.

### Three consequences, in increasing order of importance

1. **A gate-9 sweep for #38 is null by construction.** #38 changes
   `lemely/io/det/rows.py`. The harness never executes that file. Before and
   after would read the identical checked-in JSON and the delta would be
   exactly zero — at full sweep cost. Buying that number would be buying noise.
   **§D's row `#38 M1.3 | mark-lowering; §9 gate 9 over/under non-regression`
   is wrong on this point** and should be read alongside this section.

2. **It generalises.** *Every* det mark-scheme-parser change the programme will
   ever make is invisible to the instrument, present and future — which puts it
   squarely under MISSION §2 ("the instrument comes first") rather than under
   any one issue. #39's det-path private-use-codepoint detector is partly
   affected the same way; #39's Gemini paper-level gate and #41's marker-prompt
   changes are **not** (those run for real).

3. **The published `det`/`gemini` split is not the parse path.** Per the same
   docstring, the adapter substitutes `result.question_type` (`mcq` → `det`,
   `theory` → `gemini`). So the ablation's "det 8/8 = 100%, gemini 16/23 =
   69.6%" is **mcq-vs-theory**, not deterministic-vs-AI scheme parsing. That is
   already conceded in the docstring, but it is not visible next to the
   published figures, and it is the same signal #47 acceptance bullet 3
   ("stratified across both parse paths det AND gemini") assumes exists —
   consistent with the #88 q1 chain already recorded.

### The ruling needed (posted on #38 as (a)/(b)/(c))

- **(a)** Land #38 on a deterministic proof — corpus census + the
  failing-before/passing-after regression test — waiving gate 9 **for this item
  on the stated ground that the instrument provably cannot see the change**.
- **(b)** Regenerate the golden `mark_scheme.json` fixtures through the det
  parser so scheme-parsing becomes measurable. Honest fix, but it **rewrites
  the measurement corpus**: MISSION §12.2 (irreversible data operation) and
  §12.5 (frozen-split membership), needs its own authorisation, and would break
  comparability with every figure published to date including the 2026-08-24
  ablation.
- **(c)** Block #38 until (b) happens, as M3 parse-path-parity work.

Recommended, not acted on: **(a)** for #38 now, with **(b)** opened as its own
instrument issue, because consequence 2 outlives #38.

**Do not** let a future run quietly treat (a) as settled because it is the
cheap branch. The 2026-08-24 gate-9 directive says in terms: *"If you are
unsure for a given item, say so and ask rather than assuming the cheaper
branch."* This is that case, and the cheap branch is the recommended one —
which is exactly why it needs the human, not an agent's own say-so.

### Second, independent ask on #38: acceptance bullet 2 is harmful as written

Measured on the same 478 schemes, $0. Of the **177 papers carrying defaults**:

| bucket | papers | effect of deleting the minted points (bullet 2) |
|---|---:|---|
| over-sum (leaf sum > declared max) | **78** | plausibly helps — the phantom-mark story |
| under-sum (leaf sum < declared max) | **75** | makes it worse — paper is already short |
| exact (leaf sum == declared max) | **24** | breaks a correct paper; **672 points** at stake |

So the issue's premise holds for **78 of 177 (44%)** and bullet 2 is actively
harmful on the other **99 (56%)**. `0625_s19_ms_43` — the paper the issue was
written from — is a genuine over-sum instance and bullet 4's regression test is
well-chosen; it is simply **not representative**, and generalising from it is
what produces a change that helps 44% and harms 56%.

This *strengthens* bullets 1 and 3. The corpus cannot say whether a given
minted 1 is right — only that it was **written rather than read**. That is
exactly what `marks_defaulted` provenance plus a working
`escalate_on_defaulted_marks` are for. Bullet 2 guesses, and guesses wrong more
often than right on this corpus.

Recommended restatement, **not applied**: an unparseable marks cell still mints
a point, flagged `marks_defaulted`; whether the paper escalates is
`escalate_on_defaulted_marks`'s call, not the row parser's. The 75 under-sum
papers belong in front of the fidelity gate (#39), not the row parser.

Reproduce with `scripts/accuracy_defaulted_census.py <dir>` — it self-checks
against this issue's own 3-defaults/+2-delta example before reporting any
corpus number.

---

## I — #39 (M1.4): bullets 5 and 9 are not jointly satisfiable, and bullet 6 does not reproduce

**Raised:** 2026-08-25 · **Status:** OPEN, needs a human ruling · **Cost:** $0
(det path only; ledger unmoved at 1.488057). Measured with
`scripts/accuracy_glyph_census.py` over **478 of 479** restored schemes
(1 ParseError) — **22,825 answer points** — plus all 10 golden fixtures.

This is separate from §H. It does not touch #39's bullet-4 design question or
its gate-9 authorisation; both still block the issue independently.

### Bullet 5 as literally written over-fires 3.4×

Two candidate rules were built and measured side by side:

| rule | fires | notes |
|---|---:|---|
| **naive** — bullet 5 verbatim: expression, newline, expression, no operator | **426** | |
| **strict** — exactly two numeric segments and nothing else | **96** | across 73 schemes |
| all-numeric tabular blocks (3+ stacked rows) | 50 | bullet 7's FP class |

The naive rule over-fires the strict one by **330 points (3.4×)** on histogram
frequency densities, Venn-diagram cell counts, matrix blocks and marker
guidance text with numbers in it — e.g. `'5\n7\n3\n5'`, `'8\n18\n5'`,
`'E\nDo not have Do not have\na computer a phone\n23 2 7\n8'`. None is a
fraction bar. Shipping at that precision escalates hundreds of well-formed
points and drives review rate up, against gate 8 and anti-goal 3.

### But tightening it breaks a CONFIRMED real case in the measurement corpus

Across the 10 golden fixtures there are exactly **two distinct** hits, both on
`0625_s20_qp_31`, and **both are verified genuine** — each reconciles
arithmetically against the next answer point in its own question:

- `11b/p2` `'(V\ns\n=) (64 \n 240) \n 960'` → **(64 × 240) / 960 = 16**,
  matching `p3 = '16 (V)'`. **naive fires; strict MISSES.** The point carries
  non-numeric fragments (`(V`, `s`, `=)`), so "exactly two numeric segments" is
  false. Note this point's two newlines encode *two different* lost operators —
  an implicit multiplication inside the numerator **and** the fraction bar.
- `12c/p2` `'36\n8'` → **36 / 8 = 4.5**, matching `p3 = '4.5 (mg)'`. Both fire.

So `11b/p2` is not "expression, newline, expression" at all — it is
expression/newline/expression/newline/expression where **only the second
newline is the bar**. Bullet 5's phrasing does not describe the case the issue
is built on.

**Conclusion: no threshold on a newline-shape rule gives zero false positives
(bullet 9) while catching the confirmed real case.** The distinguishing
information is not in the text — it is the horizontal rule in the PDF's
geometry, linearised away before the string exists. Recovering it means
consulting layout during parsing (a `pdfplumber` rect under a numeric run), not
pattern-matching afterwards. **That redesign is NOT proposed or implemented
here** — it is recorded so nobody discovers it halfway through the issue.

### Bullet 6 does not reproduce: zero private-use codepoints, not six

Bullet 6 says *"Private-use-codepoint detector applied on the det path, where
all 6 instances live."* Searching U+E000–U+F8FF across **all 22,825 det answer
points in 478 schemes and all 10 golden fixtures returns ZERO hits.**

Not a claim that the original 6 were imagined — they may live in a different
field (metadata, guidance, question stems), a different corpus snapshot, or a
pre-#88 parse. But **as written it does not reproduce**, and a detector cannot
be regression-tested against a corpus holding no positive instance. Bullet 6
needs its evidence re-established or re-scoped before implementation.

### Bullet 7 stands — the one bullet the corpus fully supports

The issue cites 272 of 1,000 det points containing newlines (27.2%). Over
22,825 points: **7,963 (34.9%)**. Same order, same conclusion.

**Do not** resolve any of this by loosening bullet 9. A zero-false-positive
requirement is what makes the gate safe to put in front of review routing; the
right move is to fix bullet 5 and 6, not to relax the acceptance test they fail.

---

## J — #59 (M2.5) needs a real scan that has never existed; #47 (M2.4) has no gemini leaves

**Raised:** 2026-08-25 · **Status:** OPEN · **Cost:** $0 (metadata reads and an
existing manifest; ledger unmoved at 1.488057). Both issues had **zero
comments** until this run and were absent from every prior "full verified
status" enumeration.

### #59 — the "real" arm of a synthetic-vs-real comparison does not exist

Acceptance bullet 1 asks for the extraction arm run over *"the synthetic **and
the real scan** of the same paper (`0625_s20_qp_31`, `0625_m20_qp_12`)"*.

Its only recorded dependency, #56, is **CLOSED** — so on paper it is startable.
It is not. Checked at source rather than assumed:

- `lemely/accuracy/synth.py:154-162` pins the output PDF's metadata for
  byte-determinism, including `title="lemely-synthetic-scan"`.
- Reading the metadata off every `scan.pdf` under `tests/golden/`:
  **`Title='lemely-synthetic-scan'` — 11 of 11 cases, no exceptions.**
- Structurally identical too: 1 page, **0 text characters, 1 image** each, i.e.
  rasterised renderer output, not a scanned document.
- A repo-wide search for any real or photographed scan artefact returns nothing.

**The corpus is 100% synthetic. The "real" arm has never been produced**, so
the comparison has one of its two arms in existence.

**And the harness has nowhere to put one.** `GoldenCase` carries exactly one
scan slot — `harness.py:66` (`scan_path: Path | None`) and `harness.py:115`
(`scan_path = case_dir / "scan.pdf"`): one path, one hard-coded filename, per
case. "The same paper, two scans" is not expressible in the current data model.
So the issue's **Effort: S** is wrong — bullet 1 alone is corpus acquisition
plus a harness change.

Asks posted on #59: do real scans exist outside the repo; if they must be
produced, is that authorised and by whom (MISSION §12.7); and does the
`GoldenCase` pairing model belong in #59 or its own issue. *Not* re-raising
B1's stale privacy framing — the question is existence and authorisation.

Flagged for whoever runs it: the issue's Why says the two error directions
cancel, but the deflating half is what #56 was closed to fix. If #56 removed it,
the residual is **one-directional inflation**, making every synthetic-corpus
extraction figure an *optimistic* bound rather than an unsigned one. Unverified;
it changes how bullet 3 should be worded.

### #47 — volume is ample, but 9 of the 18 DA1 strata are empty and all of them are gemini

Dependencies checked: #46 **CLOSED**, #31 **CLOSED**, #50 **CLOSED**, #57
**OPEN**. So #57 is the only live blocker and the chain #88 → #57 → #47 holds.
Owner is **human** (6–8 h), so a green dependency list makes this
*human*-startable, never agent-startable.

Volume is fine — **9,464 leaf questions** from 250 det-parsed schemes, **all
9,464 tariff-banded**, against a ~300 target (31× headroom). The old
"Available: 71" framing is dead. *(Corrected 2026-08-25 per #88 item 3: this
read "12,358 leaf questions … 9,464 of them tariff-banded", which framed the
2,894 parents as unbanded leaves. There are zero unbanded true leaves; the
headroom multiple is unchanged because it was always computed off 9,464.)*

But acceptance bullet 3 (*"stratified across both parse paths — det and
gemini"*) is **currently unsatisfiable**. From
`BUILD/accuracy-runs/census-2026-08-24-a/manifest.json`, all 9 populated cells:

```
0580 x det x 1 : 1992   0606 x det x 1 :  46   0625 x det x 1 : 2521
0580 x det x 2 : 2110   0606 x det x 2 : 107   0625 x det x 2 :  525
0580 x det x 3+: 1635   0606 x det x 3+: 239   0625 x det x 3+:  289
```

**Every populated cell is `det`; the gemini half of the design is empty.** The
manifest's own `parser` field says why: `"det only (no --use-gemini)"`. The 229
det-failure schemes were never Gemini-parsed and contributed no leaves at all.
A split frozen over this corpus can only contain det leaves — which is what
makes #88's q1 load-bearing and puts #57's authorised Gemini pass on #47's
critical path, though #57 never mentions #47.

**Do not conflate this with §H.** §H is the `EvalRecord` `parse_path` gap inside
the harness (`harness.py:352-355`, substituted by `question_type`). This is the
**corpus** parse, where the signal is genuinely available per scheme and simply
has not been generated for 229 of 479. Two different absences, same name; only
this one blocks #47.

**Bullet 4 must not be used to paper over it.** "Including cells the det parser
cannot itself represent" means *publish the empty cells honestly* — **not**
"an all-det split satisfies bullet 3". If the Gemini pass never happens, the
right outcome is a published table with 9 empty cells and an explicit det-only
statement, never a quiet redefinition of the strata to the cells that are full.
That is the narrowed-denominator failure mode exactly.

---

## K — `id_match` is a hard-coded literal; the "exact 71/71" artifacts prove nothing (#37)

**Raised:** 2026-08-25 · **Status:** OPEN · **Cost:** $0 (source reads + two
existing artifacts; ledger unmoved at 1.488057).

Found while testing whether #37's gate-9 sweep is *informative* — the question
that made #38's sweep null (§H). For #37 the answer is the opposite, and the
detour turned up a measurement defect worth its own entry.

### #37's sweep IS on a live path — the §H waiver does not transfer

```
measure_accuracy (arm extract+mark, harness.py:725)
  -> grading.extract_answers                (grading.py:52-53)
     -> GeminiAnswerExtractor.__call__      (answer_extraction.py:146)
        -> normalize_extracted_answers      (answer_extraction.py:187 -> :40)
```

`normalize_extracted_answers` has exactly **one** production caller and it sits
on the harness's extraction arm. **#37 cannot be waived on
"the instrument is blind" grounds** the way #38 can.

### But `id_match` never compares anything

Assigned by hand at three sites, never computed:

```
harness.py:402   id_match="exact"       # QuestionResult -> EvalRecord adapter
harness.py:788   id_match="unmatched"   # excluded leaf
harness.py:817   id_match="unmatched"   # unmatched leaf
```

`"fuzzy"` is **never emitted anywhere** — the three-valued domain is two-valued
in practice. The harness says why the first is unconditional
(`harness.py:364-370`): the adapter is only called for a leaf the extractor
already returned an answer for.

### So the positional fallback is invisible to it, by construction

`answer_extraction.py:68-77` **overwrites** the answer's `question_id` with a
genuine manifest id and logs `id_positional_fallback` at WARNING. After that
line a positionally-guessed answer is indistinguishable from a real match, so
the harness stamps `id_match="exact"`. **The reassignment is laundered into
`exact`** — which is exactly #37's "silent realignment" complaint, located.

### Therefore this reassuring-looking evidence is worthless

```
tests/golden/results/2026-08-22-f7be062.json   records=71  id_match={'exact': 71}
tests/golden/results/2026-08-22-79f5fa8.json   records=71  id_match={'exact': 71}
```

**Neither is evidence the fallback never fired.** `exact` is a constant, so both
are equally consistent with the fallback firing on **zero** records and on **all
71**. Do not cite either as a clean bill of health — this is evidence note **E1**'s
trap in a new place, and worse: E1 was a stale denominator, this field never had
a computation behind it at all.

### Consequences

- Bullet 3 ("the metric now measures genuine id agreement rather than
  post-fallback coverage") is **confirmed at source**, not merely asserted:
  `id_match_rate` = `matched_extraction_ids / total_extraction_questions` over
  **post-normalisation** ids, and its 0.99 target was set against that. The
  same-commit rule guarding the red-CI window is right; do not relax it.
- Ask #5 is sharper, not changed: #37 needs the gate-9 spend authorised **or an
  explicit waiver on grounds other than instrument-blindness**.
- **Free when the sweep runs:** count the `id_positional_fallback` WARNING lines
  to get the fire rate nobody currently has. Capture it in the same run rather
  than paying for a second sweep.

---

## L — GitHub Actions stopped provisioning for this repo at ~13:03Z on 2026-08-26; two PRs cannot land

**Raised:** 2026-08-26 · **Status:** OPEN — external, not ours. **No spend involved.**

Two PRs are open, both correct, both unmergeable because CI will not run:

- **PR #132** (`chore/accuracy-run-40-close`) — the run-40/41 state close.
- **PR #133** (`chore/accuracy-88-item4-token-ceiling`) — #88 item 4 (DA13, the ceiling
  raise) and the re-costed item-2 preflight artifact.

### The evidence, taken from the API rather than from `gh pr checks`

`gh pr checks` reports *"no checks reported"* for both branches, which by itself is
ambiguous — it reads the same on a brand-new PR as on a dead queue. Two harder facts
settle it, and they use E5's rule that only a non-zero **`steps`/jobs** count proves a
runner was provisioned:

1. Run **32971934818** (#132, `pull_request`, created **13:03:04Z**) has been `queued`
   for **2h47m** and `GET /actions/runs/32971934818/jobs` returns an **empty job list** —
   not jobs that failed in 2–4s, *no jobs created at all*.
2. **PR #133 was opened at ~15:40Z and produced no workflow run whatsoever.** The newest
   run in `GET /actions/runs` for the entire repository is still 32971934818 from
   13:03:04Z. It is not that #133's run failed; it does not exist.

`.github/workflows/ci.yml` triggers on `pull_request` with **no `paths` filter**, so a
missing run cannot be explained by the diff touching only `BUILD/`.

### This is a stall, not the old billing block, and not flakiness

Runners were working **today**: 32968460680, 32968362231, 32968330389 (12:23–12:25Z) and
32964126855 (11:35Z) all completed `success` with real jobs. The queue went dead somewhere
after 13:03Z.

It is also distinct from the one genuine flake seen earlier on this same PR: #132's
`test (3.14)` job failed in 15s with
`failed to bind host port for 0.0.0.0:54322 ... address already in use` — a service-container
port collision on the runner, where postgres never started. That was correctly answered with
`gh run rerun --failed`, and **it is that rerun which is now stuck in the queue.**

### The rule that is NOT being invoked, stated so the next run does not reach for it

The standing "ignore CI" waiver of 2026-08-23 **is void and stays void**. By its own terms
it lapsed *"the moment Actions can provision a runner"*, and it did — today's four green
runs are the proof. A new outage does not revive a lapsed waiver.

Merging either PR on local gates plus the supervisor sweep would therefore be
**unauthorised**, and re-deriving the waiver from the fact that the block looks similar is
exactly the move the inbox's #27 rebuke forbids. Both PRs wait. **Neither is merged.**

### What the next run should do

Re-verify from the API before anything else — `gh api 'repos/LemelyIG/Lemely/actions/runs?per_page=5'`
and then the `jobs` endpoint of the newest run. **Only a non-zero job/`steps` count means it
is fixed**; a newer run id proves only that the queue accepted a trigger (falsified on
2026-08-23). If green, merge #132 then #133 — they conflict on `BUILD/ACCURACY-STATE.md`
and the resolution is **merge, not rebase**, because plain rebase strips signatures in this
repo. If still stalled, go quiescent per E5: no restating commit, report in prose, stop.
