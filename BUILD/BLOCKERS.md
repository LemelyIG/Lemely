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

---

## OPEN — 2026-08-22 — GitHub Actions is billing-blocked: no PR can merge

**Raised:** 2026-08-22 · **Status:** **OPEN — needs a human with org billing
access.** Nothing in this repository can resolve it.

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

---

## #77 — No entrypoint can set cache_mode: an A/A floor run today would measure the cache and publish 0.0

**Raised:** 2026-08-22 · **Status:** OPEN · **Source:** `scripts/accuracy_board.py block`

Blocked on GitHub Actions org billing block — CI cannot run, see BUILD/BLOCKERS.md (2026-08-22). Board Status set back to Backlog. Resolve the blocker, append a RESOLVED line here, and move the item back to Ready.
