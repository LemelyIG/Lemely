---
name: paperscraper
description: Correctly operate the PaperScraper CLI (external repo at /home/sico/PaperScraper) to bulk-download CAIE past papers, mark schemes, examiner reports and grade thresholds for Lemely's corpus. Use whenever the task involves fetching, downloading, discovering, counting or auditing exam papers, syllabus codes (0580, 0606, 0625, 9709), sessions (s24, w23, m22), grade-threshold PDFs, or expanding Sources/. Covers filter semantics, the dry-run-first workflow, verifying results via the catalogue instead of the exit code, and the politeness rules that must not be bypassed.
---

# PaperScraper (external tool)

Bulk retrieval of Cambridge (CAIE) and Pearson Edexcel past papers, mark schemes, examiner reports and **grade thresholds**. Discovery is async; downloads are verified, atomic and resumable.

**It lives outside this repo, at `/home/sico/PaperScraper`, with its own venv.** Lemely's dependency graph is untouched — do not add it to Lemely's `pyproject.toml`, and do not install it into Lemely's `.venv`.

This skill exists because the CLI has behaviours that fail *silently*: a run can report success while having downloaded nothing you wanted.

---

## 1. Invocation from Lemely

It is installed editable into its own venv, so the console script works from **any** working directory, including this one:

```bash
/home/sico/PaperScraper/.venv/bin/paperscraper <subcommand> [options]
```

Equivalently `/home/sico/PaperScraper/.venv/bin/python -m paperscraper …`. Do **not** use Lemely's `.venv/bin/python` — the package is not installed there and never should be.

### ⚠️ Always pass an absolute `-o` and `--db`

`-o/--out` defaults to `papers/` **relative to the current working directory**, and `--db` defaults to `<out>/index.db`. Running from `/home/sico/Lemely` without `-o` silently creates `/home/sico/Lemely/papers/` — an untracked multi-GB tree in the repo root.

```bash
# WRONG from Lemely — writes /home/sico/Lemely/papers/
/home/sico/PaperScraper/.venv/bin/paperscraper fetch -s 0580 --qual IGCSE --only-papers

# RIGHT — absolute output path, always
/home/sico/PaperScraper/.venv/bin/paperscraper fetch -s 0580 --qual IGCSE --only-papers \
  -o /home/sico/PaperScraper/papers
```

The same applies to `status`, which defaults to `papers/index.db` relative to CWD and does **not** inherit `-o` from an earlier fetch:

```bash
/home/sico/PaperScraper/.venv/bin/paperscraper status --db /home/sico/PaperScraper/papers/index.db
```

### Running it from an agent harness

Fetch runs are long. A bare `Bash` call with the default 120 s timeout **will be killed mid-run**, which looks like a failure but is not — the catalogue is checkpointed continuously and a re-run resumes.

- Anything beyond a single subject-year: use `run_in_background: true`, or set `timeout` generously (600000 ms max).
- Size the run with `--dry-run` first so you know what you are committing to.
- If a run is killed, do not report failure. Re-run the identical command; completed work is skipped.

---

## 2. Lemely's subjects

v1 scope is CAIE IGCSE **0580** Mathematics, **0606** Additional Mathematics, **0625** Physics. Default to those unless told otherwise, and always pair them with `--qual IGCSE`:

```bash
PS=/home/sico/PaperScraper/.venv/bin/paperscraper
OUT=/home/sico/PaperScraper/papers

$PS fetch -s 0580 -s 0606 -s 0625 --qual IGCSE --only-papers --from 2019 -o "$OUT"
```

Grade-threshold documents are document type `gt` — the same tables `scripts/ingest_grade_boundaries.py` fetches from cambridgeinternational.org. Fetching them here gives the mirror's historical copies, which reach further back than Cambridge's own index:

```bash
$PS fetch -s 0580 -s 0606 -s 0625 --qual IGCSE -t gt -o "$OUT"
```

⚠️ **Session letters differ between PaperScraper and Lemely's boundary keys.** PaperScraper uses CAIE canon — `s` = May/June, `w` = Oct/Nov, `m` = Feb/March. Lemely's `_SESSION_CODE` in `lemely/io/grade_boundaries.py` and `scripts/ingest_grade_boundaries.py` maps May/June → `m` and Feb/Mar → `s`, i.e. **s and m are swapped** relative to canonical filenames. Those two maps are consistent with each other, so lookups work today — but never join a scraped filename's session letter straight onto a boundary key. Translate explicitly.

---

## 3. The workflow that works

Steps 1 and 3 are the ones agents skip, and the ones that prevent wrong answers.

```bash
PS=/home/sico/PaperScraper/.venv/bin/paperscraper

# 1. SIZE IT — never launch a large fetch blind. Throwaway output dir (see §6).
$PS fetch -s 0580 --qual IGCSE --only-papers --from 2018 --to 2024 --dry-run -o /tmp/ps-probe

# 2. FETCH — same flags, real absolute output dir.
$PS fetch -s 0580 --qual IGCSE --only-papers --from 2018 --to 2024 \
  -o /home/sico/PaperScraper/papers

# 3. VERIFY — the catalogue is the source of truth, NOT the exit code.
sqlite3 /home/sico/PaperScraper/papers/index.db "SELECT status, COUNT(*) FROM documents GROUP BY 1;"
sqlite3 /home/sico/PaperScraper/papers/index.db \
  "SELECT filename, error FROM documents WHERE status='failed' LIMIT 20;"
```

If step 3 shows failures: re-run the exact command from step 2. Failed rows are retried, `done` rows are skipped without touching the network. Only report a problem if failures survive a second run.

---

## 4. Two traps that cause false success reports

### The exit code does not mean "no failures"

```python
return 1 if stats.failed and not stats.done else 0   # cli.py
```

Exit **0** means *at least one file downloaded*. A run with 3,000 successes and 200 failures exits 0. **Never conclude a run succeeded from the exit code or the summary table alone** — query `status='failed'` (§7).

### A year window silently drops all undated material

`Settings.matches_year(None)` returns `False` whenever `--from` or `--to` is set. Any document the source could not date is discarded without comment.

- Want papers for a period? Set the window; this is correct behaviour.
- Want syllabuses, learner guides, or anything typed `other`? **Omit `--from`/`--to` entirely**, or you get zero results and no explanation.
- Specimen material is *not* affected: `0580_y22_sp_1.pdf` parses to year 2022 and survives a window covering 2022.

---

## 5. Selection semantics

| Flag | Repeatable | Semantics |
|---|---|---|
| `-s, --subject CODE` | yes | Exact match on the **4-digit CAIE syllabus code**. Not a name. |
| `--qual NAME` | yes | Case-insensitive **substring** match on the qualification label. |
| `-t, --type TYPE` | yes | Exact `DocType` value. Invalid value → argparse error, exit **2**. |
| `--only-papers` | — | Shorthand for `qp`, `ms`, `sp`, `sm`. **Unions** with any `-t` you also pass. |
| `--from` / `--to` | — | Inclusive, on session year. See §4. |

**CAIE qualification labels are exactly `IGCSE`, `O Level`, `AS and A Level`.** Because matching is substring, `--qual "A Level"` matches only `AS and A Level`, but `--qual Level` matches both `O Level` and `AS and A Level`.

**Always pass `--qual IGCSE` alongside `-s`.** Without it, discovery walks all three CAIE trees and lists 247 subject directories before filtering. Measured: `-s 0620 --qual IGCSE` ≈ 2 s, `-s 0620` alone ≈ 6 s — worse with `--source papersdaddy`.

**`-s` is a CAIE concept.** Edexcel uses specification codes, so `-s 0580 --source pearson` yields nothing. Pearson's labels come from its own facet vocabulary (`International GCSE`, `A Level`, `International Advanced Level`, `GCSE`, `BTEC Nationals`, …), so `--qual IGCSE` matches nothing there. Lemely is CAIE-only in v1; you should rarely need `pearson`.

### Document types

`qp` question paper · `ms` mark scheme · `er` examiner report · `gt` grade thresholds · `ci` confidential instructions · `in`/`ir` insert · `sp`/`sm` specimen paper / specimen mark scheme · `sy` syllabus · `sf` source files · `tn` teacher notes · `rp` reading passage · `sc` · `audio` · `other`

---

## 6. `--dry-run` is not read-only

It downloads nothing, but it **does write to the catalogue**:

- every discovered document is upserted as `status='pending'`;
- the resume check runs *before* the dry-run check in `Downloader.fetch`, so any file already at the destination path is hashed and marked `done`.

**When you only want a count, point `-o` at a scratch directory** (`-o /tmp/ps-probe`), which also gives that run its own `index.db`.

Read the dry-run summary correctly: it reports `Downloaded 0` and `Already present N`, where N is *everything discovered*. In a dry run that does **not** mean those files exist on disk.

---

## 7. The catalogue is the source of truth

`papers/index.db` (SQLite, WAL) records every document — discovered or downloaded — and is what makes runs resumable. Query it rather than walking the filesystem or parsing CLI output.

```sql
-- Did the run actually succeed?
SELECT status, COUNT(*) FROM documents GROUP BY 1;

-- What failed, and why
SELECT filename, source, attempts, error FROM documents WHERE status='failed';

-- Lemely coverage: papers held per subject and year
SELECT subject_code, year, doc_type, COUNT(*) FROM documents
WHERE status='done' AND subject_code IN ('0580','0606','0625')
GROUP BY 1,2,3 ORDER BY 1,2;

-- Coverage gaps: sessions with papers but no mark schemes
SELECT subject_code, session_code, paper FROM documents WHERE status='done' AND doc_type='qp'
EXCEPT
SELECT subject_code, session_code, paper FROM documents WHERE status='done' AND doc_type='ms';

-- Where a specific paper landed
SELECT file_path, file_size, checksum FROM documents
WHERE subject_code='0625' AND session_code='s23' AND doc_type='ms' AND paper='22';
```

Status values: `pending` (discovered, not fetched) · `done` · `failed` (has `error`, will be retried) · `skipped` (dry run, or gated).

`sqlite3` is at `/usr/bin/sqlite3`. Fallback without it:

```bash
/home/sico/PaperScraper/.venv/bin/python -c "import sqlite3;print(sqlite3.connect('/home/sico/PaperScraper/papers/index.db').execute(\"SELECT status,COUNT(*) FROM documents GROUP BY 1\").fetchall())"
```

---

## 8. Output layout

```
<out>/
├── index.db
└── CAIE/igcse/mathematics-0580/2023/s23/0580_s23_qp_22.pdf
    <board>/<qualification>/<subject-name-code>/<year>/<session>/<canonical name>
```

CAIE filenames are preserved verbatim: `<syllabus>_<session><yy>_<type>[_<variant>].pdf` — the same convention Lemely's `Sources/` already uses (`0625_m20_ms_12.pdf`). Session letters: `m` March · `s` May/June · `w` Oct/Nov · `y` undated/specimen. Two-digit years pivot at 80 (`_w98_` → 1998).

This is **not** Lemely's `Sources/<SubjectName>/MarkingSchemes/` layout. Copying into `Sources/` is a separate, deliberate step — decide the mapping with the user rather than bulk-copying, and remember `Sources/` is gitignored while its manifest is committed.

Byte-identical files are stored once and hard-linked, so a non-zero `De-duplicated` count is healthy, not an error.

---

## 9. Reliability behaviour you can rely on

- **Atomic writes** — downloads land in `.part` files and are `rename`d into place. A partial file is never visible.
- **Content validation** — magic-byte checked. A mirror answering with an HTML error page and HTTP 200 is rejected, not saved as `.pdf`. Do not pass `--no-verify` to "fix" failures; it disables exactly this check.
- **Retry + failover** — transient 5xx / timeouts / mid-stream drops retry with backoff; `429`/`503` honour `Retry-After` and cool the host down. A verification failure moves to the next mirror rather than retrying a bad URL.
- **Graceful shutdown** — `Ctrl-C`/`SIGTERM` finishes in-flight downloads and checkpoints. `SIGKILL` leaves `.part` files, swept at the start of the next run.
- **Resume** — on by default. It trusts *disk presence*: a file at the destination with size > 0 is hashed and marked `done` without re-validating its type. Do not hand-place files into the output tree.
- **`--no-resume`** re-downloads and overwrites everything in scope. Use only to repair a corrupted tree, and narrow the scope first.

---

## 10. Sources

| Source | Board | Coverage | Use it for |
|---|---|---|---|
| `xtremepapers` *(default)* | CAIE | IGCSE / O Level / AS & A Level, 2002→now | **Default.** Flat per-subject listings → ~1 request per subject, canonical filenames. |
| `cambridge` | CAIE | Latest published series only | Provenance and freshest papers. Cannot supply history. |
| `papersdaddy` | CAIE | Broad | Failover only — one request per subject-*session*, far slower. |
| `pearson` | Edexcel | GCSE / IGCSE / A Level / BTEC | Out of scope for Lemely v1. |

`--source` is repeatable. Documents are keyed source-independently — for CAIE, `(syllabus, session, type, paper, extension)` — so the mirror's `0580_s23_ms_22.pdf` and the official site's `520492-june-2023-mark-scheme-paper-22.pdf` are recognised as the same paper. Two sources therefore deduplicate *and* act as each other's download fallback. Do not add `papersdaddy` to a bulk run for coverage; add it only when documents fail everywhere else.

---

## 11. Politeness and legality — not negotiable

- Exam papers are **copyright of the respective boards**. Educational use only; do not redistribute, publish, or commit the PDFs.
- **Do not use `--ignore-robots`.** Leave `robots.txt` enforcement on.
- **Do not raise `-c` to go faster.** Concurrency is capped per host regardless (`cambridgeinternational.org` 3 conc / 2 rps; `xtremepape.rs` 6 / 6). The default 12 is fine.
- **Never attempt to reach gated content.** Restricted records are detected and excluded by design — a correct outcome, not a bug to route around.
- Do not add sources or edit `HOST_POLICIES` in the external repo without asking the user first.

---

## 12. Triage

| Symptom | Meaning | Action |
|---|---|---|
| `No module named paperscraper` | Wrong interpreter | Use `/home/sico/PaperScraper/.venv/bin/paperscraper` |
| A `papers/` dir appeared in Lemely | Missing absolute `-o` | See §1; delete it and re-run with `-o` |
| `Discovered 0` | Filters excluded everything | Check `--qual`; see §4 undated rule |
| `not a valid PDF (starts with b'<!DOCTYPE')` | Mirror served an error page | Expected; add a second `--source`. Do **not** use `--no-verify` |
| `truncated: got N of M bytes` | Connection died mid-body | Already retried; re-run |
| `HTTP 429` / `HTTP 503` | Host throttling | Already backed off; re-run later. Do not raise `-c` |
| `blocked by robots.txt` | Host disallows that path | Respect it; try another source |
| Exit code 2 | Bad argument (invalid `-t`, `--from` > `--to`) | Fix the flags |
| Exit 0 but files missing | See §4 — failures do not set exit 1 | Query `status='failed'` |
| Run killed at 120 s | Harness timeout, not a scraper failure | Re-run with `run_in_background` |

---

## Checklist before reporting a result

1. Used `/home/sico/PaperScraper/.venv/bin/paperscraper`, never Lemely's venv.
2. Passed an **absolute** `-o` (and `--db` for `status`).
3. Sized large runs with `--dry-run` against a scratch `-o`.
4. Passed `--qual IGCSE` alongside `-s`.
5. Checked `status='failed'` in the catalogue — did **not** rely on the exit code.
6. Stated actual counts from the catalogue, not from the summary table.
