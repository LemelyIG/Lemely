# Scan and Render Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every heavy operation on user PDF and image bytes runs in a killable, memory-limited child process; the marker sees the same pixels as the teacher; the remaining over-refusals get a stated policy and a logged reason; `scan_limits.py` is split into four modules.

**Architecture:** Lane 0 splits `lemely/io/scan_limits.py` into four modules as a pure move (re-exported from `scan_limits`). Lane R gives every refusal a reason code that survives pickling. Lane 1 adds `lemely/runtime/sandbox.py` (two serialised, rlimit-bounded spawned children) and moves the preview and crop renders into a pure `lemely/io/scan_render.py`; the routers keep the HTTP mapping. Lanes 2, 3a, 4 fix the walk (`/PieceInfo`), the rewrite (`/OC` prune), the sweeps, the scheme pickers and the audit script in parallel. Lanes 3b and 2b finish forms, TIFF/grey images and the bilevel cap once the workers exist.

**Tech Stack:** Python 3.12-3.14, pymupdf 1.28.0, pypdfium2 5.11.0, Pillow 12.2.0, FastAPI, structlog, pydantic-settings, `multiprocessing` (spawn) + `resource`; vitest/TypeScript for the two web inputs.

**Spec:** `docs/superpowers/specs/2026-10-01-scan-render-safety-design.md` (governs). Draft with probe evidence: `/home/sico/.claude/jobs/33cebc31/tmp/triage/draft-S.md`. Worktree `/home/sico/Code/Lemely/.claude/worktrees/fix-scan-render-safety`, branch `fix/scan-render-safety`, base fb6618e4. Line numbers below are at fb6618e4 (identical to d66685b1 for every code file; fb6618e4 added only the spec).

## Global Constraints

Copied from the spec (verbatim where it gives numbers, codes or messages). Every task's requirements implicitly include this section.

- **Earlier owner decisions stand.**
  - PDFs are canonicalised (MuPDF rewrite) before pdfium renders them.
  - Crop, then rotate.
  - Per-mode pixel caps: colour 40 Mpx; 1-bit and grey 160 Mpx; I;16 80 Mpx; WebP 40 Mpx // 3.
  - `MAX_SCAN_PAGES` 40, `MAX_CROP_PAGES` 200.
  - `open_checked_pdf` is the only way to open a user PDF with MuPDF.
- **User-facing refusal messages are unchanged** except where this spec names a new one.
- **TDD.** Each behaviour change lands with a test that is red before the change and green after. The #262 split is a pure move, proved by the untouched suite staying green.
- **Commits.** Signed conventional commits, each naming only its own paths (`git commit -S -- <paths>`). Synthetic fixtures only.
- **Testing.** Never run the full suite locally: run the touched test files. For web changes, run the touched vitest file plus `npm run typecheck`.
- **Environment.** Every command pins `PYTHONPATH` to this worktree. Scratch files go under the job directory, never `/tmp` or the repo. Every lane kills any process it starts.
- **Fixtures.** After lane 0, no lane edits `tests/pdf_fakes.py`. New fixture builders go in a lane-owned module (named per lane below), because two lanes appending to one file in a shared worktree cannot commit cleanly by path.

Owner decisions (verbatim):

| # | Issue | Decision |
|---|---|---|
| S1 | #260, #271 | `--memory=2Gi` in `deploy.yml` (from 1Gi). Two render workers: one for extraction and the upload check, one for preview and crop. Each child is limited with `RLIMIT_DATA` plus a looser `RLIMIT_AS` backstop. The equivalence parse worker keeps its 512 MiB `RLIMIT_AS` (marking spec D2). |
| S2 | #249 | The preview sends `Cache-Control: private, no-cache` with an `ETag`. The browser keeps the thumbnail but revalidates on every view, and the revalidation runs the full authorisation check. |
| S3 | #269 | The preview gets the crop's page rule: it renders one page, so it allows up to `MAX_CROP_PAGES` (200) instead of `MAX_SCAN_PAGES` (40). The stored-scan audit runs before deploy either way. |
| S4 | #273 item 1 | Encrypted scans keep the worst-case object-stream rule. Every such refusal logs reason `encrypted_objstm`. The follow-up, opening encrypted files only inside the worker, is taken only if the log shows real refusals. |
| S5 | #261 | Close on the fix plus a pdflatex-shaped synthetic fixture. A real Illustrator figure is noted on the issue as an optional extra check. |
| S6 | #273 item 3 | Bilevel and one-component grey images inside PDFs are judged against `decode_pixel_cap(mode)`, gated on a peak-RSS measurement inside the worker. If any render path exceeds the worker's limit, PDFs keep the colour cap and the measured number is recorded on the issue. |

Memory budget at 2 GiB (resident, worst case), starting points to be replaced by measured values (Task 11), never guessed:

| Component | Bound |
|---|---|
| Web process baseline | ~233 MB |
| Pages accumulated in the parent (adversarial 40-page scan) | up to ~441 MB of PNG |
| Extraction worker | `RLIMIT_DATA` 384 MiB, `RLIMIT_AS` 640 MiB (starting point) |
| Interactive worker (preview and crop) | `RLIMIT_DATA` 192 MiB, `RLIMIT_AS` 448 MiB (starting point) |
| Equivalence parse worker | ~75 MB resident, `RLIMIT_AS` 512 MiB |
| Sum of resident bounds | ~1.33 GB, under 2 GiB |

New user-facing text named by the spec:
- Separator refusal: `This PDF separates its data with characters the checker does not accept. Re-export it as a plain scan.` (reason `objstm_separator`).
- Preview render failure: `Could not render this scan` (fixed; the exception goes to the `paper_preview_failed` log line only).
- Timeouts: upload check 20 s; crop 10 s; preview 15 s; extraction from the Task 11 measurement.

Project rules that apply to every task:
- Commands run from the worktree root with `PYTHONPATH=$PWD`. Test command shape: `PYTHONPATH=$PWD .venv/bin/python -m pytest <files> -q --no-cov`.
- `pre-commit run --files <paths>` before every commit; ruff's hook autofixes, so after it passes re-run `git status --short` and re-stage anything it changed before committing (the committed tree must be the one that passed).
- Commits: `git commit -S -m "<type>(<scope>): <msg>" -- <paths>`. Never `git add -A`, `git add .`, `git stash`, `git reset`.
- Shared venv: every worktree shares `.venv`; `PYTHONPATH=$PWD` is what makes `lemely` resolve to this worktree.
- Never write under `/tmp` or into the repo for scratch; use `/home/sico/.claude/jobs/33cebc31/tmp/plans/<lane>/`.
- Kill every process you start (worker children: `shutdown()`; measurement scripts: wait for exit).

## Waves and file ownership

| Wave | Lane | Tasks | Owns (every path the lane may touch) |
|---|---|---|---|
| 1 (alone) | 0 | 1, 2 | `lemely/io/scan_limits.py`; new `lemely/io/_scan_common.py`, `lemely/io/pdf_prescan.py`, `lemely/io/pdf_content_walk.py`, `lemely/io/pdf_canonical.py`; `tests/test_scan_limits.py`; new `tests/test_pdf_prescan.py`, `tests/test_pdf_content_walk.py`, `tests/test_pdf_canonical.py`; `tests/pdf_fakes.py` |
| 2 (alone) | R | 3, 4, 5 | the error types and messages in `lemely/io/_scan_common.py`; raise sites in `lemely/io/scan_limits.py`, `lemely/io/pdf_prescan.py`, `lemely/io/pdf_content_walk.py`, `lemely/io/pdf_canonical.py`, `lemely/io/rasterise.py`; `lemely/web/upload_utils.py`; new `tests/test_refusal_reasons.py`, new `tests/test_upload_utils.py`; the one log assertion in `tests/test_web_teacher.py` (`test_an_upload_refused_for_its_content_is_logged_without_its_bytes`) |
| 3 (parallel) | 1 | 6-12 | new `lemely/runtime/sandbox.py`, `lemely/io/scan_render.py`, `tests/sandbox_targets.py`, `tests/sandbox_fixtures.py`, `tests/test_sandbox.py`, `tests/test_scan_render.py`; `lemely/io/rasterise.py`; `lemely/web/upload_utils.py`; `lemely/web/routers/teacher.py`; `lemely/web/routers/review.py`; `lemely/runtime/config.py`; `.github/workflows/deploy.yml`; `docs/ci-cd.md`; `tests/test_rasterise.py`, `tests/test_web_teacher.py`, `tests/test_web_review.py`, `tests/test_upload_utils.py` |
| 3 (parallel) | 2 | 13 | `lemely/io/pdf_content_walk.py`, `tests/test_pdf_content_walk.py`, new `tests/fakes_pdftex.py` |
| 3 (parallel) | 3a | 14 | `lemely/io/pdf_canonical.py`, `tests/test_pdf_canonical.py`, new `tests/fakes_reader_agreement.py` |
| 3 (parallel) | 4 | 15, 16, 17 | new `tests/mupdf_sweep.py`, `tests/test_mupdf_sweep.py`; the two sweep test functions in `tests/test_scan_limits.py`; `web/src/lib/scanAccept.ts`, `web/src/portals/student/screens/CorrectPaper.tsx`, `web/src/portals/teacher/screens/Grading.tsx`, `web/tests/unit/scanAccept.test.ts`; new `scripts/audit_stored_scan_pages.py`, `tests/test_audit_stored_scan_pages.py` |
| 4 (after lane 1) | 3b | 18, 19, 20 | `lemely/io/rasterise.py`, `lemely/io/scan_render.py`, `tests/test_rasterise.py`, `tests/test_scan_render.py`, `tests/fakes_reader_agreement.py` |
| 4 (after lane 1) | 2b | 21, 22 | `lemely/io/pdf_content_walk.py`, `tests/test_pdf_content_walk.py`, `tests/sandbox_targets.py` (one measurement target, appended) |
| 5 | final | 23, 24, 25 | gate sweep (no edits unless a gate fails), whole-branch review, issue housekeeping (scratch only) |

Ordering rules: wave 1 runs alone; lane R runs alone; wave 3's four lanes run in parallel (lane 4 may start with lane R, since its files are disjoint from lane R's); wave 4 starts when lane 1's last commit (Task 12) is on the branch; lanes 3b and 2b run in parallel with each other (disjoint files: 2b appends one function to `tests/sandbox_targets.py`, which lane 1 created and no longer touches), except that Task 21 starts only after Task 18 has landed, because its extraction path runs the `rasterise.py` code Task 18 changes. Within a lane, tasks run in numeric order. Each task is reviewed at its SHA.

**Type gates in parallel waves (controller-owned).** The mypy, pyright and import-linter pre-commit hooks run over all of `lemely` (`pass_filenames: false`), so in waves 3 and 4 a lane's `pre-commit run --files ...` can fail on a file another lane is mid-edit on. Rule for every lane task: a mypy/pyright/import-linter finding in a file the lane does not own is reported in the task report (file, line, message) and left alone; the lane's own files must be clean. At the end of wave 3 and again at the end of wave 4 the controller runs, on the clean tree after the wave's last commit, `PYTHONPATH=$PWD .venv/bin/mypy lemely && PYTHONPATH=$PWD .venv/bin/pyright lemely && PYTHONPATH=$PWD .venv/bin/lint-imports`; any failure is assigned back to the owning lane as a `fix(<scope>)` commit before the next wave starts.

---

## Wave 1 — lane 0 (#262)

### Task 1: Split `scan_limits.py` into four modules (pure move)

**Files:**
- Create: `lemely/io/_scan_common.py` (the leaf: every constant from lines 50-250, including `_INFLATE_CHUNK` (137, used by the pre-scan too), `_FLATE_FILTER_NAMES` (160), `_MAX_OBJECTS_PER_PAGE` (156), `_REDUCE_FACTORS` (124), every `_*_MESSAGE` constant and `_UNSUPPORTED_IMAGE_MESSAGE` (427); the error types from lines 254-264 and 433 (`ScanRejectedError`, `ScanTooLargeError`, `ScanUnsupportedEncodingError`, `ScanUnsupportedFormatError`); and, because `pdf_canonical._pdfium_plan` calls them, `PagePlan`, `looks_like_pdf`, `plan_page_dpi`, `plan_pdf_pages` (267-337; they depend only on constants and pypdfium2))
- Modify: `lemely/io/scan_limits.py` (2,080 lines; keeps the mode sets, `decode_pixel_cap`, `plan_image`, `SCAN_IMAGE_FORMATS`, `_IGNORE_CAPPED_BOMB_WARNING`, `_pillow_claims`, `open_scan_image` (339-519) and `check_scan_bytes` (2034-2080); imports the four other modules at the top; re-exports)
- Create: `lemely/io/pdf_prescan.py` (from lines 1191-1511, 1219-1241 `_declares_encryption`, 1321-1330 `_ScanBudget`, 1730-1747 `PrescannedPdf` and `prescan_pdf`)
- Create: `lemely/io/pdf_content_walk.py` (from lines 520-1190 and 1512-1729)
- Create: `lemely/io/pdf_canonical.py` (from lines 1749-2033)
- Test: `tests/test_scan_limits.py` (the two AST sweeps' allowed paths, the patch retargeting below, plus three new tests appended)

**Interfaces:**
- Consumes: nothing new.
- Produces (names other lanes import by module):
  - `lemely.io._scan_common`: the constants, messages, error types and page-planning functions above. Imported by the four other modules; imports none of them.
  - `lemely.io.scan_limits`: plain top-of-file imports, each name listed (no star import): from `_scan_common` every public constant (`MAX_*`, `EXTRACTION_DPI`, `MIN_EXTRACTION_DPI`, `PDF_MAGIC`), every `_*_MESSAGE` constant and the other private constants (with `# noqa: F401`, so `scan_limits._OBJECT_STREAMS_MESSAGE` keeps working for tests), the four error types, `PagePlan`, `looks_like_pdf`, `plan_page_dpi`, `plan_pdf_pages`; from `pdf_prescan`, `pdf_content_walk` and `pdf_canonical` every public name below. Its own: `SCAN_IMAGE_FORMATS`, `GREY_CEILING_MODES`, `MAX_DECODE_PX_GREY`, `MAX_DECODE_PX_WEBP`, `decode_pixel_cap`, `plan_image`, `open_scan_image`, `check_scan_bytes`. `__all__` lists every public name. No lazy import, no `__getattr__`: `from lemely.io.scan_limits import X` keeps working for every X by ordinary import.
  - `lemely.io.pdf_prescan`: `check_object_stream_bytes(data: bytes) -> None`, `PrescannedPdf`, `prescan_pdf(data: bytes) -> PrescannedPdf`, private `_stream_data_starts`, `_strict_inflate_size`, `_declares_encryption`, `_ScanBudget`, `_next_token`, `_stream_dict`, `_WS`, `_REGULAR`, `_TOKEN_RE`, `_FLATE_MAX_RATIO`.
  - `lemely.io.pdf_content_walk`: `check_pdf_content(doc, *, pdfium_pages=None) -> None`, `check_pdf_page_content(doc, page_index) -> None`, `decoded_stream_size`, private `_dict_refs`, `_resources_refs`, `_walk_resource_graph`, `_walk_annotations`, `_check_declared_pixels`, `_check_masks`, `_check_image_xref`, `_check_image_and_masks`, `_resolve_int`, `_key`, `_name`, `_ref_target`, `_collection_refs`, `_page_tree`, `_PageTree`, `_PageWalk`, `_PageBound`, `_ContentBudget`, `_SCAN_PAGE_BOUND`, `_CROP_PAGE_BOUND`, `_check_object_streams`, `_check_page`, `_parent`, `_enter`, `_count_stream`, `_bounded_inflate_size`, `_normalise_filter`, `_REF_RE`, `_RESOURCE_CATEGORIES`, `_MAX_OBJECTS_PER_PAGE`, `_FLATE_FILTER_NAMES`, `_INFLATE_CHUNK`.
  - `lemely.io.pdf_canonical`: `open_checked_pdf(pdf: bytes | PrescannedPdf) -> pymupdf.Document`, `open_scan_image_document(data: bytes) -> pymupdf.Document`, `check_pdf_content_bytes(pdf, *, pdfium_pages=None) -> None`, `canonical_pdf_bytes(data: bytes) -> bytes`, private `_check_opened`, `_copy_pages(doc) -> bytes`, `_pdfium_page_count`, `_pdfium_plan`, `_MUPDF_IMAGE_FILETYPES`.

**Import direction (controller decision).** `_scan_common` is the leaf. `pdf_prescan` imports `_scan_common` only. `pdf_content_walk` imports `_scan_common` only (nothing from `pdf_prescan`). `pdf_canonical` imports `_scan_common`, `pdf_prescan` and `pdf_content_walk`. `scan_limits` imports all four. No module imports `scan_limits` except callers outside this set. Every import is a plain top-of-file import; `check_scan_bytes` uses the module-level names. The any-order subprocess test below is the proof.

**Patch-retargeting rule.** `unittest.mock.patch.object(scan_limits, name)` replaces the attribute on `scan_limits` only; moved code reads its own module's global, so a patch on `scan_limits` never reaches moved code: some tests would fail and the `assert_not_called` ones would pass vacuously. Every patch of a moved name is retargeted to the owning module, with no assertion changed. Sites at fb6618e4 (`tests/test_scan_limits.py` line: name -> module): 395-396 `_page_tree`, `_walk_resource_graph` -> `pdf_content_walk`; 420-421 `_collection_refs`, `_parent` -> `pdf_content_walk`; 541 `_walk_resource_graph`; 568 `_page_tree`; 588 `_page_tree`; 621-622 `_collection_refs`, `_parent`; 656 `_collection_refs`; 679 `_parent`; 1037 and 1044 `_MAX_OBJECTS_PER_PAGE` -> `pdf_content_walk` (bound there by `from lemely.io._scan_common import _MAX_OBJECTS_PER_PAGE`, which is the global `_enter` reads); 1103 `_walk_resource_graph`; 1566 `check_pdf_content` -> `pdf_canonical` (`_check_opened` calls it through that module's global); 1575 `scan_limits.pymupdf` -> `pdf_canonical.pymupdf`; 1709, 1723, 1727 `check_object_stream_bytes` -> `pdf_prescan` (`prescan_pdf` calls it there); 2058 `_page_tree` -> `pdf_content_walk`. The `assert_not_called` sites (395, 588, 2058) are the ones that would otherwise pass vacuously.

- [ ] **Step 1: Write the failing tests (append to `tests/test_scan_limits.py`, class `SplitModuleTests`)**
  - `test_every_name_in_all_imports_from_scan_limits`: `for name in scan_limits.__all__: getattr(scan_limits, name)`; and `__all__` contains at least: `check_pdf_content`, `check_pdf_page_content`, `check_pdf_content_bytes`, `check_scan_bytes`, `prescan_pdf`, `PrescannedPdf`, `check_object_stream_bytes`, `open_checked_pdf`, `open_scan_image_document`, `canonical_pdf_bytes`, `plan_pdf_pages`, `plan_page_dpi`, `plan_image`, `decode_pixel_cap`, `open_scan_image`, `decoded_stream_size`, `looks_like_pdf`, `PagePlan`, `MAX_SCAN_PAGES`, `MAX_CROP_PAGES`, `MAX_DECODE_PX`, `MAX_DECODE_PX_GREY`, `MAX_DECODE_PX_WEBP`, `MAX_PAGE_PX`, `MAX_SCAN_TOTAL_PX`, `MAX_PAGE_CONTENT_BYTES`, `MAX_SCAN_CONTENT_BYTES`, `MAX_OBJECT_STREAM_BYTES`, `MAX_PDF_OBJECTS`, `MAX_PRESCAN_TOKENS`, `MIN_EXTRACTION_DPI`, `EXTRACTION_DPI`, `PDF_MAGIC`, `SCAN_IMAGE_FORMATS`, `GREY_CEILING_MODES`, `ScanRejectedError`, `ScanTooLargeError`, `ScanUnsupportedEncodingError`, `ScanUnsupportedFormatError`. Red today: `scan_limits` has no `__all__` (`AttributeError`).
  - `test_the_split_modules_import_in_any_order`: for each of `lemely.io._scan_common`, `lemely.io.pdf_prescan`, `lemely.io.pdf_content_walk`, `lemely.io.pdf_canonical`, `lemely.io.scan_limits`, `subprocess.run([sys.executable, "-c", f"import {module}; import lemely.io.scan_limits as s; s.open_checked_pdf; s.check_pdf_content; s.MAX_SCAN_PAGES"], env={**os.environ, "PYTHONPATH": root})` returns 0. Red today: the new modules do not exist (`ModuleNotFoundError`).
  - `test_moved_names_are_the_same_objects`: `scan_limits.check_pdf_content is pdf_content_walk.check_pdf_content`, same for `open_checked_pdf`/`pdf_canonical`, `prescan_pdf`/`pdf_prescan`, `canonical_pdf_bytes`/`pdf_canonical`, `ScanRejectedError`/`_scan_common`. Red today (import error).
- [ ] **Step 2: Run to verify red.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_scan_limits.py -q --no-cov -k SplitModuleTests`. Expected: 3 failures, as above.
- [ ] **Step 3: Move the code.** Cut the line ranges above into `_scan_common` and the three new modules, each with a module docstring saying what it owns and that `scan_limits` re-exports it. Keep every function body byte-identical except for import lines. Module imports: `pdf_prescan` imports `re`, `zlib`, `dataclasses`, and from `_scan_common` the constants/messages/errors it uses; `pdf_content_walk` imports `pymupdf`, `from pymupdf import mupdf as _mupdf` (as the original does), and `_scan_common`; `pdf_canonical` imports `pymupdf`, `pypdfium2`, `from lemely.io.pdf_prescan import PrescannedPdf, prescan_pdf`, `from lemely.io.pdf_content_walk import check_pdf_content, _check_object_streams` as needed, and `_scan_common`. `scan_limits` imports the four at the top and lists `__all__`. Update the two AST sweeps in `tests/test_scan_limits.py`: `allowed = {("lemely/io/pdf_canonical.py", "open_checked_pdf"), ("lemely/io/pdf_canonical.py", "open_scan_image_document")}` and `{("lemely/io/pdf_prescan.py", "prescan_pdf")}`.
- [ ] **Step 4: Retarget every patch** listed in the rule above (add `import lemely.io.pdf_canonical as pdf_canonical`, `import lemely.io.pdf_content_walk as pdf_content_walk`, `import lemely.io.pdf_prescan as pdf_prescan` at the top of `tests/test_scan_limits.py`). No assertion changes. `grep -n "patch.object(scan_limits" tests/test_scan_limits.py` must then print nothing.
- [ ] **Step 5: Run the whole touched module green.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_scan_limits.py tests/test_rasterise.py tests/test_web_teacher.py tests/test_web_review.py tests/test_student_correct.py -q --no-cov`. Expected: all pass, with fb6618e4's pass and skip counts for the same files plus 3 (record both). Run it twice to confirm no import-order dependence.
- [ ] **Step 6: Type and import gates.** `pre-commit run --files lemely/io/_scan_common.py lemely/io/scan_limits.py lemely/io/pdf_prescan.py lemely/io/pdf_content_walk.py lemely/io/pdf_canonical.py tests/test_scan_limits.py` (ruff on the files; mypy, pyright and import-linter over all of `lemely`).
- [ ] **Step 7: Commit.** `git commit -S -m "refactor(io): split scan_limits into _scan_common, pdf_prescan, pdf_content_walk and pdf_canonical (#262)" -- lemely/io/_scan_common.py lemely/io/scan_limits.py lemely/io/pdf_prescan.py lemely/io/pdf_content_walk.py lemely/io/pdf_canonical.py tests/test_scan_limits.py`

### Task 2: Split the tests, rewrite private pins, replace round labels

**Files:**
- Modify: `tests/test_scan_limits.py` (2,106 lines; keeps `PagePlanTests`, `ImagePlanTests`, `ScanTotalPixelTests`, `CheckScanBytesTests`, `SplitModuleTests`, the image-allowlist tests, and the two AST sweeps (`:1771`, `:1818`) moved out of `RawObjectStreamTests` into their own class `SanctionedOpenerSweepTests` here; they do not move with `RawObjectStreamTests`, and Task 15 later rewires only their bodies)
- Create: `tests/test_pdf_prescan.py` (`RawObjectStreamTests` minus the two sweeps, and the token-budget/separator/encrypt tests from lines 1653-1982 that exercise `check_object_stream_bytes`/`prescan_pdf`)
- Create: `tests/test_pdf_content_walk.py` (`ContentWalkPageCapTests`, `PageScopedContentCheckTests`, `ContentStreamBombTests`, `ImageXObjectBombTests`, `AnnotationPatternType3BombTests`, `ImageMaskBombTests`, `PageTreeIdentityTests`, `StreamRoleTests`, `WalkedImageTests`, `ReaderCoverageTests`)
- Create: `tests/test_pdf_canonical.py` (`CanonicalPdfBytesTests`, `RewriteFidelityTests`, `OffPageObjectTests`, `NonPdfDocumentTests`, and the `open_checked_pdf`/`open_scan_image_document` tests)
- Modify: `tests/pdf_fakes.py` (labels only: 19 "Fix round"/"review round" mentions)

**Interfaces:** none new. Private pins: tests that reference `scan_limits._page_tree`, `_walk_resource_graph`, `_parent`, `_collection_refs`, `_resources_refs`, `_PageWalk`, `_ContentBudget`, `_PageTree`, `_PageBound`, `_SCAN_PAGE_BOUND`, `_CROP_PAGE_BOUND`, `_MAX_OBJECTS_PER_PAGE`, plus the patched `check_pdf_content` and `check_object_stream_bytes` (inventory at fb6618e4 from `grep -o "scan_limits\._[a-zA-Z_]*" tests/test_scan_limits.py | sort | uniq -c`: `_SCAN_PAGE_BOUND` x7, `_page_tree` x6, `_OBJECT_STREAMS_MESSAGE` x6, `_PAGE_STRUCTURE_MALFORMED_MESSAGE` x5, `_walk_resource_graph` x3, `_parent` x3, `_PageWalk` x3, `_ContentBudget` x3, `_collection_refs` x3, `_resources_refs` x2, `_PAGE_TREE_TOO_COMPLEX_MESSAGE` x2, `_PAGE_COUNT_UNREADABLE_MESSAGE` x2, `_CROP_PAGE_BOUND` x2, `_STRUCTURE_TOO_COMPLEX_MESSAGE`, `_SCAN_PAGES_MESSAGE`, `_PageTree`, `_PageBound`, `_OBJECT_STREAM_UNREADABLE_MESSAGE`, `_OBJECT_STREAM_ENCODING_MESSAGE` x1 each; and the `patch.object` sites Task 1 retargeted: `_MAX_OBJECTS_PER_PAGE` x2, `check_pdf_content` x1, `check_object_stream_bytes` x3) are rewritten against `check_pdf_content_bytes(data)` or `check_pdf_page_content(doc, page)` wherever the refusal is observable there (assert the public message); a private pin stays only for the two orderings the spec names (the tree check before `seen`; the cap before the walk), for `_page_tree`'s holder map, and for the `assert_not_called` booby traps, and those import from the owning module directly. Message constants are read from `scan_limits` (re-exported from `_scan_common`).

- [ ] **Step 1: Move test classes** into the three new files by class, keeping each test's body; fix imports to the owning modules; use `from lemely.io import scan_limits` only for constants and messages.
- [ ] **Step 2: Rewrite the private pins** as above. For each rewritten test, record in its docstring which public entry point now observes the behaviour.
- [ ] **Step 3: Replace labels.** In `tests/pdf_fakes.py` and the four test modules, every "Fix round N", "review round N", "T9b review round 1", "Task 9c review round 2" style label becomes what the fixture or test exercises (e.g. "a container found by xref repair", "an /SMask reached through /ExtGState"). `grep -n "round [0-9]" tests/pdf_fakes.py tests/test_scan_limits.py tests/test_pdf_prescan.py tests/test_pdf_content_walk.py tests/test_pdf_canonical.py` must print nothing.
- [ ] **Step 4: Run all four plus dependants green.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_scan_limits.py tests/test_pdf_prescan.py tests/test_pdf_content_walk.py tests/test_pdf_canonical.py tests/test_rasterise.py tests/test_student_correct.py tests/test_web_teacher.py tests/test_web_review.py -q --no-cov`. Expected: the total passed count equals Task 1 Step 5's count plus any tests split into subTests (record both numbers in the task report), zero failures, zero skips added.
- [ ] **Step 5: `pre-commit run --files tests/test_scan_limits.py tests/test_pdf_prescan.py tests/test_pdf_content_walk.py tests/test_pdf_canonical.py tests/pdf_fakes.py`**
- [ ] **Step 6: Commit.** `git commit -S -m "test(scan_limits): split the tests by module and say what each fixture exercises (#262, #265)" -- tests/test_scan_limits.py tests/test_pdf_prescan.py tests/test_pdf_content_walk.py tests/test_pdf_canonical.py tests/pdf_fakes.py`

---

## Wave 2 — lane R (#276.2, #273.1, #273.2)

### Task 3: Refusal reason codes on every raise site

**Files:**
- Modify: `lemely/io/_scan_common.py` (the error classes, from fb6618e4's `scan_limits.py:254-264` and `:433`; `REFUSAL_REASONS`; the raise sites that moved there with `plan_page_dpi`/`plan_pdf_pages`: 292, 316, 331)
- Modify: `lemely/io/scan_limits.py` (raise sites 389, 405, 515, 2074 as moved)
- Modify: `lemely/io/pdf_prescan.py`, `lemely/io/pdf_content_walk.py`, `lemely/io/pdf_canonical.py` (every `raise Scan...Error(`; at fb6618e4 numbering: 535, 593, 601, 752, 768, 899, 905, 911, 928, 939, 1037, 1082, 1126, 1184, 1311, 1329, 1503, 1506, 1509, 1531, 1540, 1550, 1552, 1620, 1626, 1631, 1637, 1661, 1664, 1675, 1683, 1719, 1725, 1806, 1834, 1841, 1918, 1921, 1928, 1931, 1936)
- Modify: `lemely/io/rasterise.py:290`
- Count: 49 raise sites in all (48 in the former `scan_limits.py` plus `rasterise.py:290`; `grep -c "raise Scan" lemely/io/*.py` summed must be 49 before Step 3 and every one carries a reason after).
- Create: `tests/test_refusal_reasons.py`

**Interfaces:**
- Produces: `class ScanRejectedError(LemelyError)` with `def __init__(self, message: str, reason: str = "unspecified") -> None` storing `super().__init__(message, reason)`; `self.reason: str`; `__str__` returns the message only (so `str(exc)` and every `detail=str(exc)` is unchanged). Pickle round trip reconstructs from `args` (default `BaseException.__reduce__`), keeping both. Subclasses inherit the constructor. `REFUSAL_REASONS: frozenset[str]` in `_scan_common` (re-exported by `scan_limits`) listing the final codes; `_scan_common`'s module docstring lists them with one line each.
- `_PageBound` (pdf_content_walk) gains a `reason: str` field: `_SCAN_PAGE_BOUND` -> `page_cap`, `_CROP_PAGE_BOUND` -> `crop_page_cap`.
- Reason table (the implementer may add a code, never leave a site on the default):

| Site (fb6618e4 line) | reason |
|---|---|
| plan_page_dpi 292 | `page_px` |
| plan_pdf_pages 316 | `page_cap`; 331 | `scan_px` |
| plan_image 389 | `webp_px`; 405 | `image_px` |
| open_scan_image 515, open_scan_image_document 1806 | `format_not_allowed` |
| 535, 593, 768 (page budget message) | `page_content`; 768 (scan budget message) | `scan_content` |
| 601 (content stream filter) | `content_encoding` |
| 752 (objects per page) | `page_objects` |
| 899, 911, 1626, 1719 | `bound.reason` / `page_cap` / `crop_page_cap` |
| 905, 928, 939, 1082, 1664, 1675 | `malformed` |
| 1037 (walk reaches the page tree) | `page_tree` |
| 1126, 1184, 2074, rasterise 290 | `image_px` |
| 1311, 1329 | `prescan_tokens` |
| 1503 | `objstm_unreadable` (Task 4 adds `objstm_separator` here) |
| 1506, 1550 | `objstm_encoding` |
| 1509 | `encrypted_objstm` when `encrypted` else `objstm_bomb`; 1552 | `objstm_bomb` |
| 1531 | `too_many_objects` |
| 1540, 1620, 1637, 1661, 1683, 1725, 1834, 1841, 1918, 1921, 1931, 1936 | `uncheckable` |
| 1631, 1928 (pdfium count differs) | `reader_disagreement` |

- [ ] **Step 1: Write the failing tests** in `tests/test_refusal_reasons.py`:
  - `test_a_refusal_pickles_with_its_message_and_reason`: `exc = ScanTooLargeError("too big", reason="page_px")`; `back = pickle.loads(pickle.dumps(exc))`; assert `str(back) == "too big"`, `back.reason == "page_px"`, `type(back) is ScanTooLargeError`. Red: `TypeError: unexpected keyword 'reason'`.
  - `test_str_is_the_message_alone`: `str(ScanRejectedError("m", reason="r")) == "m"`. Red (TypeError).
  - `test_the_default_reason_is_unspecified_and_every_io_raise_overrides_it`: AST sweep over `sorted((root/"lemely"/"io").glob("*.py"))`: every `ast.Raise` whose `exc` is an `ast.Call` to a `Name` or `Attribute` ending in one of `ScanRejectedError`, `ScanTooLargeError`, `ScanUnsupportedEncodingError`, `ScanUnsupportedFormatError` must have a `reason=` keyword or two positional args; collect `(file, lineno)` offenders; assert the list is empty. Red: 49 offenders.
  - `test_every_literal_reason_is_documented`: for the same calls, every `reason=` that is an `ast.Constant` str must be in `scan_limits.REFUSAL_REASONS`. Red (no such set).
  - `test_the_encrypted_worst_case_refusal_is_logged_as_encrypted_objstm`: `shared_container_broken_xref_pdf(20_000, encrypt_entry=b"/Encrypt 99 0 R")` (raw object stream over 15.5 KB) -> `check_object_stream_bytes` raises `ScanTooLargeError` with `reason == "encrypted_objstm"` and the unchanged `_OBJECT_STREAMS_MESSAGE`. Red (no reason attribute).
- [ ] **Step 2: Run to verify red.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_refusal_reasons.py -q --no-cov`. Expected: 5 failures.
- [ ] **Step 3: Implement** the constructor, `REFUSAL_REASONS`, the `_PageBound.reason` field, and the reason at every site per the table.
- [ ] **Step 4: Run green**: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_refusal_reasons.py tests/test_scan_limits.py tests/test_pdf_prescan.py tests/test_pdf_content_walk.py tests/test_pdf_canonical.py tests/test_rasterise.py -q --no-cov`. Expected: all pass; no message text changed (grep the diff for `_MESSAGE` edits: none).
- [ ] **Step 5: `pre-commit run --files lemely/io/_scan_common.py lemely/io/scan_limits.py lemely/io/pdf_prescan.py lemely/io/pdf_content_walk.py lemely/io/pdf_canonical.py lemely/io/rasterise.py tests/test_refusal_reasons.py`**
- [ ] **Step 6: Commit.** `git commit -S -m "feat(io): give every scan refusal a reason code that survives pickling (#276, #273)" -- lemely/io/_scan_common.py lemely/io/scan_limits.py lemely/io/pdf_prescan.py lemely/io/pdf_content_walk.py lemely/io/pdf_canonical.py lemely/io/rasterise.py tests/test_refusal_reasons.py`

### Task 4: Separator refusals get their own message and code (#273 item 2)

**Files:**
- Modify: `lemely/io/_scan_common.py` (new constant `_OBJECT_STREAM_SEPARATOR_MESSAGE`, re-exported by `scan_limits` like the other messages)
- Modify: `lemely/io/scan_limits.py` (the re-import line only)
- Modify: `lemely/io/pdf_prescan.py` (`check_object_stream_bytes`, the `not decoded and longest > 0` branch, fb6618e4 line 1503; `_stream_data_starts`)
- Test: `tests/test_refusal_reasons.py`

**Interfaces:**
- Produces: `_OBJECT_STREAM_SEPARATOR_MESSAGE = "This PDF separates its data with characters the checker does not accept. Re-export it as a plain scan."` in `_scan_common`; in `pdf_prescan`, `_SEPARATOR_BYTES = frozenset({0x09, 0x00, 0x0C})` and `def _separator_after_stream(data: bytes, pos: int) -> bool` (True when the first non-space byte after `stream` is tab, NUL or form feed). `check_object_stream_bytes` raises `ScanRejectedError(_OBJECT_STREAM_SEPARATOR_MESSAGE, reason="objstm_separator")` instead of the unreadable message when no span inflates AND `_separator_after_stream` is true for that container. Containers that inflate on some span still pass (no new refusals).
- Probe evidence (run 2026-10-01 on this tree, `/home/sico/.claude/jobs/33cebc31/tmp/plans/probe_separators2.py`): `shared_container_broken_xref_pdf(10, stream_separator=sep)` with `sep` in `b"\t\t"`, `b"\x00\x00"`, `b"\x0c\x0c"`, `b"\t "` is refused today with `_OBJECT_STREAM_UNREADABLE_MESSAGE` while MuPDF and pdfium both open it (1 page). `b"\t"`, `b"\t\n"`, `b"\x00"`, `b"\x0c"`, `b"\t\r\n"` pass today and must keep passing.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_refusal_reasons.py`, class `SeparatorRefusalTests`):
  - `test_a_tab_nul_or_form_feed_separator_is_refused_with_the_named_message`: for `sep` in `(b"\t\t", b"\x00\x00", b"\x0c\x0c", b"\t ")`, `check_object_stream_bytes(shared_container_broken_xref_pdf(10, stream_separator=sep))` raises `ScanRejectedError` whose `str` is `_OBJECT_STREAM_SEPARATOR_MESSAGE` and `reason == "objstm_separator"`. Red today: message is `_OBJECT_STREAM_UNREADABLE_MESSAGE`.
  - `test_separators_that_a_reader_start_accepts_still_pass`: for `sep` in `(b"\t", b"\t\n", b"\x00", b"\x0c", b"\t\r\n", b" \n")` the same call returns `None`. Green today and after (regression guard).
  - `test_a_corrupt_container_behind_a_plain_separator_keeps_the_unreadable_message`: `shared_container_broken_xref_pdf(10, corrupt_header=True)` still raises with `_OBJECT_STREAM_UNREADABLE_MESSAGE` and `reason == "objstm_unreadable"`. Green after Task 3; guards that the new branch is narrow.
- [ ] **Step 2: Red.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_refusal_reasons.py -q --no-cov -k Separator`. Expected: 1 failure (the first test).
- [ ] **Step 3: Implement** the helper and the branch; document in `check_object_stream_bytes`'s docstring that acceptance is deferred until the `objstm_separator` log shows real uploads.
- [ ] **Step 4: Green.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_refusal_reasons.py tests/test_pdf_prescan.py -q --no-cov`.
- [ ] **Step 5: `pre-commit run --files lemely/io/_scan_common.py lemely/io/scan_limits.py lemely/io/pdf_prescan.py tests/test_refusal_reasons.py`**
- [ ] **Step 6: Commit.** `git commit -S -m "fix(prescan): name the separator when an object stream cannot be read past a tab, NUL or form feed (#273)" -- lemely/io/_scan_common.py lemely/io/scan_limits.py lemely/io/pdf_prescan.py tests/test_refusal_reasons.py`

### Task 5: The upload refusal log carries the reason

**Files:**
- Modify: `lemely/web/upload_utils.py:48-56` (`_log_refusal`) and `:76-91` (`check_scan_geometry`)
- Create: `tests/test_upload_utils.py`
- Modify: `tests/test_web_teacher.py:655-680` (`test_an_upload_refused_for_its_content_is_logged_without_its_bytes`: add `"reason": "page_content"` to the expected log dict)

**Interfaces:**
- Produces: `_log_refusal(refusal: str, data: bytes, content_type: str | None, *, reason: str | None = None) -> None` logging `reason=` only when given (the 413 path keeps its three fields); `check_scan_geometry` passes `reason=exc.reason`.

- [ ] **Step 1: Failing test** in `tests/test_upload_utils.py`: `test_a_refused_scan_is_logged_with_its_class_and_reason`: `with structlog.testing.capture_logs() as logs, pytest.raises(HTTPException) as caught: check_scan_geometry(page_bomb_pdf(112_000_000), "application/pdf")`; assert 422 and `logs == [{"event": "upload_refused", "log_level": "warning", "refusal": "ScanTooLargeError", "reason": "page_content", "byte_size": ..., "content_type": "application/pdf"}]`. Red: no `reason` key. Also update the `test_web_teacher.py` assertion (red for the same reason).
- [ ] **Step 2: Red.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_upload_utils.py tests/test_web_teacher.py -q --no-cov -k "logged_without_its_bytes or logged_with_its_class"`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Green** with the same command, then `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_upload_utils.py tests/test_web_teacher.py -q --no-cov`.
- [ ] **Step 5: `pre-commit run --files lemely/web/upload_utils.py tests/test_upload_utils.py tests/test_web_teacher.py`**
- [ ] **Step 6: Commit.** `git commit -S -m "feat(web): log the refusal reason beside the class on a refused upload (#276)" -- lemely/web/upload_utils.py tests/test_upload_utils.py tests/test_web_teacher.py`

---

## Wave 3 — lane 1 (#260, #249, #269 code)

### Task 6: `SandboxSettings` and `ChildWorker`

**Files:**
- Modify: `lemely/runtime/config.py` (new `SandboxSettings` block after `GradingSettings`, field `sandbox: SandboxSettings = SandboxSettings()` on `Settings` at line 941 area)
- Create: `lemely/runtime/sandbox.py`
- Create: `tests/sandbox_targets.py` (child-side targets for tests only)
- Create: `tests/sandbox_fixtures.py` (the two pytest fixtures every sandbox-aware test module imports)
- Create: `tests/test_sandbox.py`

**Interfaces:**
- Consumes: `lemely.runtime.errors.LemelyError`; `lemely.runtime.config.load_settings`. `lemely.runtime` must not import `lemely.io`, `lemely.core` or `lemely.app` (import-linter contract "Runtime must not depend on domain layers"), so targets are resolved by dotted name with `importlib.import_module` at call time, and the child classifies exceptions by `LemelyError`, never by `ScanRejectedError`.
- Produces, in `lemely/runtime/config.py`:
  ```python
  class SandboxSettings(BaseModel):
      model_config = ConfigDict(extra="forbid")
      enabled: bool = True
      start_timeout_seconds: float = Field(default=30.0, gt=0)
      extraction_data_limit_bytes: int = Field(default=384 * 1024 * 1024, ge=64 * 1024 * 1024)
      extraction_address_limit_bytes: int = Field(default=640 * 1024 * 1024, ge=128 * 1024 * 1024)
      interactive_data_limit_bytes: int = Field(default=192 * 1024 * 1024, ge=64 * 1024 * 1024)
      interactive_address_limit_bytes: int = Field(default=448 * 1024 * 1024, ge=128 * 1024 * 1024)
      extraction_timeout_seconds: float = Field(default=180.0, gt=0)   # replaced by Task 11
      upload_check_timeout_seconds: float = Field(default=20.0, gt=0)
      preview_timeout_seconds: float = Field(default=15.0, gt=0)
      crop_timeout_seconds: float = Field(default=10.0, gt=0)
  ```
  Env names follow the existing rule: `LEMELY_SANDBOX__ENABLED`, `LEMELY_SANDBOX__EXTRACTION_DATA_LIMIT_BYTES`, etc.
- Produces, in `lemely/runtime/sandbox.py`:
  - `class SandboxFailure(LemelyError)`: `__init__(self, message: str, reason: str)`, `reason` in `args`, `__str__` is the message. Subclasses `SandboxTimeout` (reason `timeout`), `SandboxMemory` (`memory`), `SandboxCrash` (`crash`), `SandboxUnavailable` (`unavailable`), `SandboxError` (`error`; the target raised a non-`LemelyError` exception, whose `repr` is the message, never shown to a client). `SandboxError` is an addition to the spec's four: the spec's `("error", repr)` reply needs a typed home.
  - `@functools.cache def sandbox_settings() -> SandboxSettings` returning `load_settings().sandbox`: `load_settings` reads TOML and the environment, so it must not run per request; the cache makes it run once per process. Every caller (the workers, `rasterise`, `upload_utils`, the two routers) calls it through the module attribute (`sandbox.sandbox_settings()` or `from lemely.runtime import sandbox` then `sandbox.sandbox_settings()`), never `from lemely.runtime.sandbox import sandbox_settings`, so a test's `monkeypatch.setattr(sandbox, "sandbox_settings", ...)` is what every caller sees. The fixtures below also call `sandbox_settings.cache_clear()` on teardown.
  - `class ChildWorker`:
    - `__init__(self, name: str, *, limits: Callable[[SandboxSettings], tuple[int, int]])` where `limits` returns `(data_limit_bytes, address_limit_bytes)`.
    - `call(self, target: str, *args: object, timeout: float, result_type: type[T]) -> T`: acquires the lock with `self._lock.acquire(timeout=remaining)` where `remaining` counts down from `timeout` starting at entry, so the wait behind another caller counts against the same budget; an expired lock wait raises `SandboxUnavailable("busy", "unavailable")` (the routers map it to 503) and sets `last_outcome = "busy"`. Then sends `("call", target, args)`, polls for the remaining time, validates `isinstance(value, result_type)` (else `SandboxError`). When `sandbox_settings().enabled` is False: resolves and calls the target in-process, exceptions propagate unchanged.
    - `stream(self, target: str, *args: object, timeout: float, item_type: type[T]) -> Iterator[T]`: the target returns an iterator; the child sends `("item", value)` per element then `("ok", None)`; `timeout` is one deadline for the lock wait plus the whole call, measured from entry; the lock is held for the whole iteration; a consumer closing the generator early (`GeneratorExit`) kills the child so the next call respawns. In-process when disabled.
    - `pid(self) -> int | None`, `shutdown(self) -> None` (sends the stop sentinel, kills and joins, and clears the start cool-down so a test that shuts a worker down can start it again at once), `last_outcome: str | None` (`"ok"`, `"rejected"`, `"memory"`, `"crash"`, `"timeout"`, `"error"`, `"unavailable"`, `"interrupted"`), `_forget_after_fork` registered with `os.register_at_fork` for both module instances.
    - Child protocol, in `_child_main(conn, data_limit, address_limit)`: `signal.signal(SIGINT, SIG_IGN)`; `resource.setrlimit(RLIMIT_DATA, (data_limit, hard))` and `RLIMIT_AS` likewise, each in its own try so one unavailable limit does not drop the other; `("ready", None)` after start; per request: `("ok", value)`, `("item", value)`, `("rejected", exc)` for any `LemelyError` (the instance, pickled with its `args`; the child first tries `pickle.dumps(exc)` itself and, if that raises, sends `("error", repr(exc))` instead, so an unpicklable rejection never breaks the pipe), `("memory", None)` for `MemoryError`, `("error", repr(exc))` for any other `Exception`. Note (finding 7): in pypdfium2 5.11 a bitmap allocation failure raises `PdfiumError` (a `RuntimeError`), and pymupdf has no memory error class, so an out-of-memory render may arrive as `("error", ...)` -> `SandboxError`, as `("memory", None)`, or as a crash; callers treat any `SandboxFailure` alike. A broken pipe/EOF ends the loop.
    - Parent: timeout -> kill, join, `SandboxTimeout`; EOF/OSError/unpicklable reply -> `SandboxCrash` (pdfium's out-of-memory abort shows up here); start failure or no `ready` within `start_timeout_seconds` -> `SandboxUnavailable` with the same 30 s cool-down as `_ParseWorker`; `("rejected", exc)` -> `raise exc`; `("memory", None)` -> `SandboxMemory` (child lives on); `("error", repr)` -> `SandboxError`. Mirrors `_ParseWorker` (`lemely/core/equivalence.py:971-1157`) in spawn context, daemon flag, lock, owner pid, fork hook, `_discard`; `_ParseWorker` is not touched.
    - Module docstring records the measured numbers (Task 11 fills them in) the way `equivalence.py:165-184` does.
  - Instances: `EXTRACTION_WORKER = ChildWorker("lemely-extraction-worker", limits=lambda s: (s.extraction_data_limit_bytes, s.extraction_address_limit_bytes))`, `INTERACTIVE_WORKER = ChildWorker("lemely-interactive-worker", limits=lambda s: (s.interactive_data_limit_bytes, s.interactive_address_limit_bytes))`.
- Produces, in `tests/sandbox_targets.py` (pure module; imports only stdlib and `lemely.runtime.errors`): `def pid() -> int`; `def sleep_for(seconds: float) -> None`; `def allocate(n_bytes: int) -> int` (touches a `bytearray(n_bytes)`, returns its length); `def crash() -> None` (`os._exit(3)`); `def reject(message: str, reason: str) -> None` (raises `lemely.io.scan_limits.ScanRejectedError(message, reason=reason)` — imported inside the function, so the module stays importable without `lemely.io` at module level); `def count_up(n: int) -> Iterator[int]`; `def record_window(path: str, hold_seconds: float, *ignored: object) -> bytes` (appends `"<start> <end>\n"` from `time.monotonic()` to `path`, sleeps `hold_seconds`, returns a 1x1 PNG); `def peak_rss_of(target: str, *args: object) -> tuple[int, object]` (resets `/proc/self/clear_refs` with "5", runs the target by dotted name (iterating it fully if it returns an iterator), returns `(VmHWM growth in bytes, result or page count)`); `def lower_data_limit_then(data_limit: int, target: str, *args: object) -> object` (calls `resource.setrlimit(RLIMIT_DATA, (data_limit, hard))` after the child's imports are already done, then runs the target; lets a test force an out-of-memory without starving the import).
- Produces, in `tests/sandbox_fixtures.py` (imported by `tests/test_sandbox.py`, `tests/test_rasterise.py`, `tests/test_upload_utils.py`, `tests/test_web_teacher.py`, `tests/test_web_review.py` via `from tests.sandbox_fixtures import in_process_sandbox, sandboxed  # noqa: F401`):
  - `def _reset_workers() -> None`: `EXTRACTION_WORKER.shutdown(); INTERACTIVE_WORKER.shutdown(); sandbox.sandbox_settings.cache_clear()`.
  - `@pytest.fixture def in_process_sandbox(monkeypatch)`: `_reset_workers()` on setup; `monkeypatch.setattr(sandbox, "sandbox_settings", lambda: SandboxSettings(enabled=False))`; yields; `_reset_workers()` on teardown. Applied by name (not autouse) to the booby-trap tests that patch `pymupdf`/`pdfium`/`PIL` in the test process.
  - `@pytest.fixture def sandboxed(monkeypatch)`: `_reset_workers()` on setup; `monkeypatch.setattr(sandbox, "sandbox_settings", lambda: SandboxSettings(enabled=True))` (callers override the returned settings by re-patching with other values); yields; `_reset_workers()` on teardown. Shutting down on setup as well as teardown means a worker left over from another module (or a cool-down from a failed start) never leaks into a test.

- [ ] **Step 1: Write the failing tests** (`tests/test_sandbox.py`, a `worker` fixture that builds a fresh `ChildWorker("test", limits=lambda s: (256 MiB, 512 MiB))` under `sandboxed`, and calls `shutdown()` in teardown):
  - `test_a_target_allocating_past_the_limit_fails_and_the_next_call_succeeds`: limits `(256 MiB, 1 GiB)`; `call("tests.sandbox_targets.lower_data_limit_then", 96 * 2**20, "tests.sandbox_targets.allocate", 512 * 2**20, timeout=10, result_type=int)` raises a `SandboxFailure` (record its subclass: `SandboxMemory` is expected for a plain `bytearray`, since Python raises `MemoryError` there); `last_outcome in {"memory", "error", "crash"}`; then `call("tests.sandbox_targets.pid", timeout=5, result_type=int)` succeeds (the same pid for `memory`, a new one for `crash`).
  - `test_a_call_waiting_behind_a_busy_worker_is_unavailable_within_its_timeout`: thread A runs `list(worker.stream("tests.sandbox_targets.slow_count", 3, 1.0, timeout=10, item_type=int))` (add `slow_count(n, pause)` to the targets: yields `n` ints with `pause` seconds between); after 0.2 s thread B calls `worker.call("tests.sandbox_targets.pid", timeout=0.5, result_type=int)` and must raise `SandboxUnavailable` within 1 s with `last_outcome == "busy"`; A still completes with `[0, 1, 2]`. (Task 10 adds the end-to-end version: an extraction stream holds `EXTRACTION_WORKER` while an upload check gets 503.)
  - `test_a_sleeping_target_is_killed_on_timeout_and_the_pid_changes`: first `pid()` call; `call("tests.sandbox_targets.sleep_for", 5.0, timeout=0.3, result_type=type(None))` raises `SandboxTimeout` within 2 s; `last_outcome == "timeout"`; `worker.pid()` is `None`; the next `pid` call returns a different pid.
  - `test_a_scan_rejection_arrives_with_its_message_and_reason`: `call("tests.sandbox_targets.reject", "nope", "page_px", timeout=5, result_type=int)` raises `ScanRejectedError` with `str == "nope"` and `reason == "page_px"`; `last_outcome == "rejected"`.
  - `test_a_crash_respawns_the_child`: `call("tests.sandbox_targets.crash", ...)` raises `SandboxCrash`; the next `pid` call succeeds with a new pid.
  - `test_a_non_lemely_exception_is_a_sandbox_error_with_the_repr`: target `tests.sandbox_targets.allocate` with `-1` (`ValueError`) raises `SandboxError` whose message contains `ValueError`.
  - `test_stream_yields_items_in_order_under_one_deadline`: `list(stream("tests.sandbox_targets.count_up", 5, timeout=5, item_type=int)) == [0, 1, 2, 3, 4]`.
  - `test_the_two_module_workers_are_distinct_processes`: `EXTRACTION_WORKER.call(pid)` != `INTERACTIVE_WORKER.call(pid)` and both != `os.getpid()`; shutdown both.
  - `test_disabled_sandbox_runs_the_target_in_process`: `enabled=False`; `call(pid) == os.getpid()`; `worker.pid() is None`.
  - `test_the_child_runs_under_both_rlimits`: target `tests.sandbox_targets.rlimits` (add it: returns `(getrlimit(RLIMIT_DATA)[0], getrlimit(RLIMIT_AS)[0])`) equals the configured pair.
  - `test_a_render_out_of_memory_is_a_sandbox_failure_and_the_worker_recovers` (Linux only): limits `(512 MiB, 1 GiB)` so the imports succeed; reset the test process's VmHWM (`/proc/self/clear_refs` <- "5", skip with `pytest.skip` on `OSError` as `test_web_review.py:2101` does) and read it; `call("tests.sandbox_targets.lower_data_limit_then", 48 * 2**20, "lemely.io.rasterise.rasterise_pdf_to_pages", Path("tests/fixtures/handwritten-59/0625_w24_qp_42.pdf"), timeout=60, result_type=list)` raises some `SandboxFailure` (`SandboxError` from `PdfiumError`, `SandboxMemory`, or `SandboxCrash`; record which); the next `pid` call succeeds; the test process's VmHWM grew by less than 32 MB. The real assertion is the recovery and the bounded parent, not the subclass.
  - `test_shutdown_clears_the_start_cool_down`: `monkeypatch.setattr(worker, "_spawn", lambda: False)`; `call(pid)` raises `SandboxUnavailable`; restore `_spawn`; without `shutdown()` the next call within 30 s would still be refused (assert `worker._start_failed_at is not None`); after `worker.shutdown()` the next `call(pid)` succeeds at once.
  - `test_the_settings_block_round_trips_through_env`: `Settings(_env_file=None)` with `LEMELY_SANDBOX__ENABLED=false` in `monkeypatch.setenv` gives `settings.sandbox.enabled is False`.
  - `test_sandbox_settings_is_read_once_per_process`: `monkeypatch.setattr(sandbox, "load_settings", counting_stub)`; `sandbox.sandbox_settings.cache_clear()`; three calls -> the stub ran once.
- [ ] **Step 2: Red.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_sandbox.py -q --no-cov`. Expected: import error (`lemely.runtime.sandbox` missing), then after stubs, each test fails on behaviour.
- [ ] **Step 3: Implement** `SandboxSettings`, `sandbox.py`, `sandbox_targets.py`, `sandbox_fixtures.py`.
- [ ] **Step 4: Green.** Same command. Expected: 14 pass; no stray `lemely-*-worker` processes after the run (`pgrep -f lemely-.*-worker` prints nothing).
- [ ] **Step 5: `pre-commit run --files lemely/runtime/config.py lemely/runtime/sandbox.py tests/sandbox_targets.py tests/sandbox_fixtures.py tests/test_sandbox.py`** (import-linter must pass: no static `lemely.io` import in `sandbox.py`).
- [ ] **Step 6: Commit.** `git commit -S -m "feat(runtime): add ChildWorker, a killable rlimit-bounded child for scan work (#260)" -- lemely/runtime/config.py lemely/runtime/sandbox.py tests/sandbox_targets.py tests/sandbox_fixtures.py tests/test_sandbox.py`

### Task 7: Move the preview and crop renders into `lemely/io/scan_render.py`

**Files:**
- Create: `lemely/io/scan_render.py`
- Modify: `lemely/web/routers/teacher.py:714-752` (`_PREVIEW_LONG_EDGE_PX`, `_render_preview_png`), `:1131-1141`
- Modify: `lemely/web/routers/review.py:335-460` (`_MAX_CROP_PX`, `_PdfCropPlan`, `_upscale_within_ceiling`, `_pdf_crop_plan`, `_require_page_in_range`, `_WHOLE_REGION`, `_EXIF_ORIENTATION_TAG`), `:460-540` (`_upright_transpose`, `_stored_frame_rect`, `_swaps_axes`, `_refuse_too_large`, `_upscaled_png`), `:556-706` (`_crop_pdf_scan`, `_decode_within_ceiling`, `_fitted_region`, `_crop_image_scan`), `:781-800`
- Create: `tests/test_scan_render.py`
- Modify: `tests/test_web_review.py`: every import from `lemely.web.routers.review` of a moved private name is repointed to `lemely.io.scan_render` (the public names below): `:1892` and `:1932` `_stored_frame_rect`, `_upright_transpose`; `:1991` and `:2074` (`_PEAK_RSS_CHILD`) `_crop_image_scan`; `:2015` and `:2054` `_MAX_CROP_PX`, `_crop_image_scan`; `:2929` `_CROP_RENDER_DPI`, `_MAX_CROP_PX`, `_pdf_crop_plan`; `:2969` `_pdf_crop_plan`; `:1515` `_CROP_RENDER_DPI`. The in-process callers at `:1991-2000`, `:2015-2027`, `:2054-2062`, `:2074-2095` become `crop_image_scan(scan, list(box))`. `tests/test_web_teacher.py:2029` (`_PREVIEW_PEAK_RSS_CHILD` import). After the edit, `grep -n "from lemely.web.routers.review import _" tests/test_web_review.py` lists only `_require_renderable_box`-type names that still live in the router (expected: none of the moved ones).

**Interfaces:**
- Produces, in `lemely/io/scan_render.py` (pure: imports `lemely.io.*`, `lemely.core.schemas` is NOT needed; never `lemely.web`):
  - `class RenderRefused(LemelyError)`: `__init__(self, message: str, reason: str, fields: dict[str, float] | None = None)`, storing `super().__init__(message, reason, fields)` so `args` carries all three and the default `BaseException.__reduce__` rebuilds it across the sandbox pipe; `self.reason`, `self.fields` (an empty dict when `None`); `__str__` is the message. Reasons `no_pages`, `page_out_of_range`, `page_too_large`, `box_unusable`.
  - `PREVIEW_LONG_EDGE_PX = 842.0`, `MAX_CROP_PX = 4_000_000`, `CROP_RENDER_DPI` (moved value), `EXIF_ORIENTATION_TAG = 0x0112`.
  - `def render_preview_png(data: bytes) -> bytes`: body of `_render_preview_png` with `raise RenderRefused("Stored scan has no pages", "no_pages")` instead of `HTTPException`; still `check_pdf_content(doc)` in this task (Task 9 changes it).
  - `def crop_pdf_scan(data: bytes, page: int, box: list[int]) -> bytes`: body of `_crop_pdf_scan`; `_require_page_in_range` raises `RenderRefused(f"Stored crop region names page {page + 1} of a {page_count}-page scan", "page_out_of_range")`; `_refuse_too_large` raises `RenderRefused("This scan's pages are too large to render", "page_too_large", fields={"width_pt": ..., "height_pt": ...})` (or `width_px`/`height_px` for an image).
  - `def crop_image_scan(data: bytes, box: list[int]) -> bytes`: body of `_crop_image_scan` (single page, so `page_out_of_range` cannot happen; keep the 1-page check for parity).
  - Helpers move with them under public names: `pdf_crop_plan`, `PdfCropPlan`, `upscale_within_ceiling`, `stored_frame_rect`, `upright_transpose`, `swaps_axes`, `decode_within_ceiling`, `fitted_region`, `upscaled_png`, `WHOLE_REGION`; minus the router's `item_id` logging (the router logs).
- `teacher.py` keeps: `from lemely.io.scan_render import RenderRefused, render_preview_png`; the route catches `RenderRefused` -> 422 `str(exc)`; the `ScanRejectedError` and generic branches unchanged in this task. `review.py` keeps `_require_renderable_box` (it is an HTTP concern), re-exports `_CROP_RENDER_DPI = CROP_RENDER_DPI` and `_MAX_CROP_PX = MAX_CROP_PX` for the tests that import them, catches `RenderRefused` -> logs `review_crop_page_out_of_range`/`review_crop_page_too_large` by reason with `item_id` and the fields -> 422 `str(exc)`; `ScanRejectedError` -> `review_crop_scan_rejected` with `reason=exc.reason, detail=str(exc)` -> 422 `str(exc)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_scan_render.py` (unittest style like `tests/test_rasterise.py`):
  - `test_render_preview_png_draws_page_one_of_a_pdf_at_72_dpi` (595x842 A4 -> PNG of that size).
  - `test_render_preview_png_refuses_a_document_with_no_pages` (`empty_page_tree_pdf()` from `tests.pdf_fakes` -> `RenderRefused`, reason `no_pages`).
  - `test_crop_pdf_scan_refuses_a_page_out_of_range_without_rendering` (`patch.object(pymupdf.Document, "load_page")` not called; `RenderRefused` reason `page_out_of_range` with the existing message text).
  - `test_crop_pdf_scan_refuses_a_page_too_large_to_render` (three pages of 8000x8000 pt as `test_crop_route_never_500s_on_a_page_too_large_to_rasterise` builds them; reason `page_too_large`).
  - `test_crop_image_scan_matches_the_route_helper_it_replaces`: build the phone photo with `_synthetic_phone_photo`-style bytes locally (an RGB JPEG with orientation 6 and a red mark) and compare `crop_image_scan(scan, [100, 100, 300, 400])` to Pillow's `exif_transpose` then `crop` of the padded rect, byte for byte (the comparison `test_crop_route_crops_an_exif_rotated_photo_where_extraction_boxed_it` makes).
  - `test_render_refused_pickles_with_message_reason_and_fields`: for every reason in `("no_pages", "page_out_of_range", "page_too_large", "box_unusable")`, `back = pickle.loads(pickle.dumps(RenderRefused("m", reason, {"width_pt": 8000.0})))`; `str(back) == "m"`, `back.reason == reason`, `back.fields == {"width_pt": 8000.0}`, `type(back) is RenderRefused`; and `RenderRefused("m", reason)` round-trips with `fields == {}`.
  Red: `lemely.io.scan_render` does not exist.
- [ ] **Step 2: Red.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_scan_render.py -q --no-cov`.
- [ ] **Step 3: Move the code**; rewrite the in-process callers in `tests/test_web_review.py` to `crop_image_scan(scan, list(_MARK_BOX))` and `_PEAK_RSS_CHILD` to import `lemely.io.scan_render.crop_image_scan`; `_PREVIEW_PEAK_RSS_CHILD` to `lemely.io.scan_render.render_preview_png`.
- [ ] **Step 4: Green.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_scan_render.py tests/test_web_review.py tests/test_web_teacher.py -q --no-cov`. Expected: all pass, including `test_an_unrenderable_scan_does_not_echo_the_renderer_error` and the `review_crop_render_failed` log assertions (check `tests/test_web_review.py:2842, 3441-3502`).
- [ ] **Step 5: `pre-commit run --files lemely/io/scan_render.py lemely/web/routers/teacher.py lemely/web/routers/review.py tests/test_scan_render.py tests/test_web_review.py tests/test_web_teacher.py`**
- [ ] **Step 6: Commit.** `git commit -S -m "refactor(io): move the preview and crop renders into a pure scan_render module (#260)" -- lemely/io/scan_render.py lemely/web/routers/teacher.py lemely/web/routers/review.py tests/test_scan_render.py tests/test_web_review.py tests/test_web_teacher.py`

### Task 8: Preview and crop run on `INTERACTIVE_WORKER`; HTTP mapping

**Files:**
- Modify: `lemely/web/upload_utils.py` (new helper), `lemely/web/routers/teacher.py` (preview route), `lemely/web/routers/review.py` (crop route)
- Modify: `tests/test_web_teacher.py`, `tests/test_web_review.py`

**Interfaces:**
- Produces, in `upload_utils.py`: `def sandbox_failure_to_http(exc: SandboxFailure, *, event: str, **fields: object) -> HTTPException`: logs `log.warning(event, reason=exc.reason, error=str(exc), **fields)`; returns 503 `detail="Scan rendering is temporarily unavailable. Try again in a moment."` for `SandboxUnavailable`, else 422 `detail="Could not render this scan"`.
- `teacher.py`: `PREVIEW_TARGET = "lemely.io.scan_render.render_preview_png"`; the route calls `INTERACTIVE_WORKER.call(PREVIEW_TARGET, data, timeout=sandbox_settings().preview_timeout_seconds, result_type=bytes)`; `except RenderRefused` -> 422 str; `except ScanRejectedError` -> log `paper_preview_rejected` (`reason=exc.reason, detail=str(exc)`) -> 422 str; `except SandboxFailure as exc: raise sandbox_failure_to_http(exc, event="paper_preview_failed", paper_id=paper_id)`; the generic `except Exception` stays for the in-process path.
- `review.py`: `CROP_PDF_TARGET`, `CROP_IMAGE_TARGET` constants; `INTERACTIVE_WORKER.call(..., timeout=sandbox_settings().crop_timeout_seconds, result_type=bytes)`; `SandboxFailure` -> `sandbox_failure_to_http(exc, event="review_crop_render_failed", item_id=logged_id)`.
- Test fixtures come from `tests/sandbox_fixtures.py` (Task 6): `in_process_sandbox` is NOT autouse. It is requested by name only by the booby-trap tests, i.e. those that `patch.object` `pymupdf`, `pdfium`, `PIL` or a `scan_render`/`review`/`teacher` attribute in the test process and assert on it (`test_web_teacher.py`: `:707`, `:752`, `:860`, `:2056`-area peak test is a subprocess and needs neither; `test_web_review.py`: `:1558`, `:2398`, `:3119`, `:3154`, `:2750`, `:3464`, and every other test with `patch.object(pymupdf` / `patch.object(pdfium` / `patch("PIL` in its body; the implementer lists them by `grep -n "patch" tests/test_web_review.py tests/test_web_teacher.py` and names each in the task report). Every other route test runs with the real default (`sandbox_settings()` from `load_settings()`, enabled, default limits), so the child is exercised by the ordinary suite. `sandboxed` is requested by the tests that assert on the worker itself.

- [ ] **Step 1: Write the failing tests.**
  - `tests/test_web_teacher.py::test_preview_end_to_end_in_the_worker` (`sandboxed`; the smoke test the review asked for): (a) a stored A4 PDF -> 200 PNG 595x842; (b) a stored 100x140 PNG image -> 200 PNG; (c) a stored `page_bomb_pdf(112_000_000)` -> 422 whose `detail` is the page-content message (the `ScanRejectedError` crossed the pipe with its text); after each, `INTERACTIVE_WORKER.pid()` is the same live pid. Red today: no worker, `pid()` absent.
  - `tests/test_web_review.py::test_crop_end_to_end_in_the_worker` (`sandboxed`): (a) a normal crop -> 200 and the same pixel census as `test_crop_route_returns_a_png_of_the_boxed_region`; (b) a box on page 9 of a 3-page scan -> 422 `detail == "Stored crop region names page 10 of a 3-page scan"`; (c) three 8000x8000 pt pages -> 422 `detail == "This scan's pages are too large to render"` and a `review_crop_page_too_large` log line carrying `width_pt`; (d) a stored content-stream bomb -> 422 with its message. Red today.
  - `tests/test_web_teacher.py::test_preview_answers_422_with_the_fixed_message_when_the_worker_refuses` (`sandboxed`; interactive data limit 64 MiB; `monkeypatch.setattr(teacher, "PREVIEW_TARGET", "tests.sandbox_targets.oom")`, where `oom(*ignored: object) -> bytes` (add it to `tests/sandbox_targets.py`) touches a 1 GiB `bytearray`; the route passes `data` as the only argument, which `oom` ignores) -> 422, `detail == "Could not render this scan"`, log `paper_preview_failed` with `reason == "memory"`. Red today: no `PREVIEW_TARGET`.
  - `tests/test_web_teacher.py::test_preview_answers_503_when_no_worker_can_start` (`sandboxed`; `monkeypatch.setattr(INTERACTIVE_WORKER, "_spawn", lambda: False)`) -> 503.
  - `tests/test_web_review.py::test_a_refused_crop_is_a_422_with_the_fixed_message` (same shape with `CROP_PDF_TARGET`).
  - `tests/test_web_review.py::test_two_concurrent_crops_are_served_one_after_the_other` (`sandboxed`, whose setup already shut the worker down so the env var below is inherited at spawn; `monkeypatch.setenv("LEMELY_TEST_WINDOW_FILE", str(tmp_path / "w"))`; `CROP_PDF_TARGET = "tests.sandbox_targets.record_window_from_env"` (add it: reads the path from the env var, holds 0.4 s); two threads call the crop route; both 200; the two `(start, end)` windows in the file do not overlap).
  - `tests/test_web_review.py::test_the_crop_runs_in_the_interactive_worker` (`sandboxed`; a normal crop; `INTERACTIVE_WORKER.pid()` not None and != `os.getpid()`; `last_outcome == "ok"`).
- [ ] **Step 2: Red.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_web_teacher.py tests/test_web_review.py -q --no-cov -k "worker or fixed_message or one_after or no_worker or end_to_end"`.
- [ ] **Step 3: Implement** the helper, the constants, the routing; mark the booby-trap tests with `in_process_sandbox`.
- [ ] **Step 4: Green.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_web_teacher.py tests/test_web_review.py tests/test_upload_utils.py -q --no-cov`. Expected: all pass; `pgrep -f lemely-interactive-worker` empty afterwards.
- [ ] **Step 5: `pre-commit run --files lemely/web/upload_utils.py lemely/web/routers/teacher.py lemely/web/routers/review.py tests/test_web_teacher.py tests/test_web_review.py tests/sandbox_targets.py`**
- [ ] **Step 6: Commit.** `git commit -S -m "feat(web): render the preview and crop in the interactive worker and map sandbox failures to 422/503 (#260, #249)" -- lemely/web/upload_utils.py lemely/web/routers/teacher.py lemely/web/routers/review.py tests/test_web_teacher.py tests/test_web_review.py tests/sandbox_targets.py`

### Task 9: Preview residuals: fixed message, `no-cache` + ETag, one-page rule (#249, #269 code)

**Files:**
- Modify: `lemely/web/routers/teacher.py` (route `get_paper_preview`, lines 1092-1149 at fb6618e4)
- Modify: `lemely/io/scan_render.py` (`render_preview_png`: `check_pdf_page_content(doc, 0)` instead of `check_pdf_content(doc)`; the `doc.page_count == 0` -> `RenderRefused("Stored scan has no pages", "no_pages")` check stays BEFORE it, as today's order has the empty check before any page is named)
- Modify: `tests/sandbox_targets.py` (adds `boom`)
- Modify: `tests/test_web_teacher.py`

**Interfaces:**
- `PREVIEW_RENDER_VERSION = 1` in `teacher.py`; `def preview_etag(row: TeacherPaperRow) -> str` returning `'"' + hashlib.sha256(f"{row.id}:{row.storage_path}:{PREVIEW_RENDER_VERSION}".encode()).hexdigest()[:32] + '"'`. `storage_path` is immutable per paper: `TeacherPaperRepository.create` (`lemely/db/teacher_paper_repo.py:236-260`) is its only writer and `_update` is never called with it (confirm with `grep -n "storage_path" lemely/db/teacher_paper_repo.py`; record the grep output in the task report).
- `def etag_matches(if_none_match: str | None, etag: str) -> bool` in `teacher.py`, per RFC 9110 §13.1.2: `None` -> False; `*` -> True; otherwise split on commas, strip, and compare each entry to `etag` with weak comparison (a leading `W/` on either side is ignored, the quoted opaque tags must be byte-equal). Unit-tested directly: `W/"abc"` matches `"abc"`; `"x", "abc"` matches `"abc"`; `*` matches; `"ab"` does not; malformed input (`abc` without quotes) does not.
- Order of checks in the route: (1) `_require_paper` (the DB row, the visibility rule; 404 unchanged, and this is also the existence check the 304 relies on: a paper with no row never reaches the ETag); (2) `etag = preview_etag(row)`; (3) if `etag_matches(request.headers.get("if-none-match"), etag)`: `Response(status_code=304, headers={"ETag": etag, "Cache-Control": "private, no-cache"})`, with no `storage.download` and no render; (4) else download (404 when the object has expired, as today), render, 200 with `Cache-Control: private, no-cache` and `ETag`. Documented consequence: a 304 is answered from the DB row alone, so a browser that cached the thumbnail of a paper whose stored object has since expired keeps seeing it until the row goes (the row is what authorises the view, and the object's expiry does not change who may see the paper); the first uncached request after expiry gets the 404. The route docstring says so. The generic failure branch becomes `detail="Could not render this scan"`, the exception stays in the `paper_preview_failed` log.

- [ ] **Step 1: Write the failing tests** in `tests/test_web_teacher.py`:
  - `test_preview_never_echoes_renderer_text`: seed any stored scan; `monkeypatch.setattr(teacher, "PREVIEW_TARGET", "tests.sandbox_targets.boom")`, where `boom(*ignored: object) -> bytes` (add it to `tests/sandbox_targets.py`) raises `RuntimeError("DISTINCTIVE-RENDERER-TEXT")`; under the in-process fixture the route's generic branch catches it; assert 422, `"DISTINCTIVE" not in resp.text`, and the text is in a captured `paper_preview_failed` log entry. Red: today the detail echoes `{exc}`.
  - `test_preview_is_revalidated_not_cached`: 200 response has `cache-control == "private, no-cache"` and an `etag` header. Red: `max-age=3600`.
  - `test_preview_etag_round_trip_skips_download_and_render`: first GET 200 with ETag; second GET with `If-None-Match: <etag>` -> 304, `patch.object(pymupdf.Page, "get_pixmap")` not called, and a counting `FakeStorageBackend` subclass shows no second `download`. Red (no 304).
  - `test_preview_etag_does_not_bypass_authorisation`: a second teacher (seed with `_seed_user`-style helper or a second `AuthContext` override) sends `If-None-Match` with the first teacher's ETag -> 404 (as today for an invisible paper). Red (no ETag; green after; keep as the authorisation pin).
  - `test_preview_if_none_match_is_parsed_per_rfc_9110`: the `etag_matches` cases above, plus a route-level check that `If-None-Match: W/<etag>` and `If-None-Match: "other", <etag>` both give 304 and `If-None-Match: "other"` gives 200. Red (no helper).
  - `test_preview_304_is_answered_from_the_row_after_the_object_expires`: first GET 200; delete the object from the fake storage; GET with `If-None-Match` -> 304; GET without it -> 404. Pins the documented order. Red (no 304).
  - Invert `test_preview_still_refuses_a_stored_scan_over_the_page_cap` (`:860`) into `test_preview_serves_page_one_of_a_stored_scan_over_the_page_cap`: `MAX_SCAN_PAGES + 1` blank pages -> 200, PNG. Red: 422 today.
  - `test_preview_refuses_a_stored_scan_over_max_crop_pages`: `MAX_CROP_PAGES + 1` pages -> 422, `get_pixmap` not called, detail is `_CROP_PAGES_MESSAGE`. Red: today the message is the 40-page one.
- [ ] **Step 2: Red.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_web_teacher.py -q --no-cov -k "preview"`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Green.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_web_teacher.py tests/test_scan_render.py -q --no-cov`.
- [ ] **Step 5: `pre-commit run --files lemely/web/routers/teacher.py lemely/io/scan_render.py tests/sandbox_targets.py tests/test_web_teacher.py`**
- [ ] **Step 6: Commit.** `git commit -S -m "fix(web): preview answers a fixed message, revalidates with an ETag, and keeps page one of a 41-200 page scan (#249, #269)" -- lemely/web/routers/teacher.py lemely/io/scan_render.py tests/sandbox_targets.py tests/test_web_teacher.py`

### Task 10: Extraction and the upload check run on `EXTRACTION_WORKER`

**Files:**
- Modify: `lemely/io/rasterise.py:85-159` (`rasterise_pdf_to_pages`), `:312-326` (`rasterise_scan_to_pages`)
- Modify: `lemely/web/upload_utils.py:76-91` (`check_scan_geometry`)
- Modify: `tests/test_rasterise.py`, `tests/test_upload_utils.py`

**Interfaces:**
- Produces, in `rasterise.py`:
  - `def _iter_pdf_pages(pdf_path: Path, *, dpi: float) -> Iterator[RasterisedPage]`: the current body of `rasterise_pdf_to_pages` as a generator (canonicalise, plan, `check_pdf_content_bytes`, render and `yield` each page, closing page and bitmap as today).
  - `def rasterise_pdf_to_pages(pdf_path: Path, *, dpi: float = EXTRACTION_DPI) -> list[RasterisedPage]`: `pages = list(_iter_pdf_pages(...))`; `ValueError` when empty. In-process, contract unchanged (tests and lane 3a call it).
  - `def iter_scan_pages(scan_path: Path, dpi: float) -> Iterator[RasterisedPage]`: the child-side target; dispatches on `_looks_like_pdf`; for a PDF `yield from _iter_pdf_pages`, swallowing the `ValueError` "no pages" (yields nothing); for an image `yield from _rasterise_single_image(scan_path)`.
  - `SCAN_PAGES_TARGET = "lemely.io.rasterise.iter_scan_pages"`.
  - `def rasterise_scan_to_pages(scan_path: Path, *, dpi: float = EXTRACTION_DPI) -> list[RasterisedPage]`: `pages = list(EXTRACTION_WORKER.stream(SCAN_PAGES_TARGET, scan_path, dpi, timeout=sandbox_settings().extraction_timeout_seconds, item_type=RasterisedPage))`; `ValueError(f"{scan_path} produced no pages")` when empty. `SandboxFailure` propagates (the grading pipeline already turns exceptions into a failed run status; `lemely/web/services/grading.py` is not touched).
- Produces, in `upload_utils.py`: `SCAN_CHECK_TARGET = "lemely.io.scan_limits.check_scan_bytes"`; `check_scan_geometry` calls `EXTRACTION_WORKER.call(SCAN_CHECK_TARGET, data, timeout=sandbox_settings().upload_check_timeout_seconds, result_type=type(None))`; `except SandboxFailure as exc: raise sandbox_failure_to_http(exc, event="upload_check_failed", content_type=content_type, byte_size=len(data))` (422 "Could not render this scan" or 503).
- Tests use the shared fixtures from `tests/sandbox_fixtures.py` (Task 6). `in_process_sandbox` is requested by name only by the booby-trap tests in `tests/test_rasterise.py` that patch `pdfium`/`pymupdf`/`scan_limits` in the test process (`:200` `test_each_page_is_closed_before_the_next_page_is_loaded`, `:615`, `:630`, `:659`, `:683`, `:698`, `:717`, `:755`, `:773` and the others found by `grep -n "patch" tests/test_rasterise.py`; listed in the task report); it is not autouse. The rest of the module calls `rasterise_pdf_to_pages` (in-process by construction) or `rasterise_scan_to_pages` through the real default worker.

- [ ] **Step 1: Write the failing tests.**
  - `tests/test_rasterise.py::test_extraction_of_the_committed_fixture_runs_in_the_worker` (`sandboxed`): `pages = rasterise_scan_to_pages(_FIXTURE)`; `len(pages) == 16`; `EXTRACTION_WORKER.last_outcome == "ok"`; `EXTRACTION_WORKER.pid()` not None and != `os.getpid()`. Red: no worker used.
  - `tests/test_rasterise.py::test_a_render_forced_past_the_limit_fails_without_growing_this_process` (`sandboxed`, Linux only): `monkeypatch.setattr(sandbox, "sandbox_settings", lambda: SandboxSettings(enabled=True, extraction_data_limit_bytes=512 MiB, extraction_address_limit_bytes=1 GiB))` so the child's imports succeed; `monkeypatch.setattr(rasterise, "SCAN_PAGES_TARGET", "tests.sandbox_targets.lower_data_limit_then_stream")` (add it: like `lower_data_limit_then` but returns the iterator for `stream`; called with `48 * 2**20, "lemely.io.rasterise.iter_scan_pages", path, 400.0` -- so `rasterise_scan_to_pages` must pass its args after the target's own; simplest: the test calls `EXTRACTION_WORKER.stream` directly with that target and asserts the same as `rasterise_scan_to_pages` would); reset the test process's VmHWM (`/proc/self/clear_refs` <- "5", `pytest.skip` on `OSError`) and read it; the call raises some `SandboxFailure` (any subclass: `PdfiumError` arrives as `SandboxError`, a `bytearray` as `SandboxMemory`, an abort as `SandboxCrash`; record which); the next `EXTRACTION_WORKER.call("tests.sandbox_targets.pid", ...)` succeeds; the test process's VmHWM grew by less than 32 MB. Red today: no `stream`, and an in-process render grows the process.
  - `tests/test_rasterise.py::test_an_empty_pdf_still_raises_value_error_through_the_worker` (`sandboxed`; the existing `test_empty_pdf_raises_value_error` shape).
  - `tests/test_upload_utils.py::test_the_upload_check_runs_in_the_extraction_worker` (`sandboxed`): `check_scan_geometry(born_digital_text_pdf(pages=1), "application/pdf")`; `EXTRACTION_WORKER.last_outcome == "ok"`, pid differs. Red.
  - `tests/test_upload_utils.py::test_a_refusal_in_the_worker_is_the_same_422_as_in_process` (`sandboxed`): `page_bomb_pdf(112_000_000)` -> 422 with the page-content message and `reason="page_content"` in the log.
  - `tests/test_upload_utils.py::test_an_unavailable_worker_is_a_503_at_upload` (`sandboxed`; `monkeypatch.setattr(EXTRACTION_WORKER, "_spawn", lambda: False)`).
  - `tests/test_upload_utils.py::test_an_upload_check_behind_a_running_extraction_is_a_503_within_its_timeout` (`sandboxed`; the end-to-end version of finding 5): thread A runs `list(EXTRACTION_WORKER.stream("tests.sandbox_targets.slow_count", 3, 1.0, timeout=10, item_type=int))`; after 0.2 s the main thread patches `sandbox_settings` to `upload_check_timeout_seconds=0.5` and calls `check_scan_geometry(born_digital_text_pdf(pages=1), "application/pdf")`; it raises `HTTPException` 503 within 1 s and logs `upload_check_failed` with `reason == "unavailable"`; thread A still gets `[0, 1, 2]`. Red: no worker, the check runs in-process at once.
- [ ] **Step 2: Red.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_rasterise.py tests/test_upload_utils.py -q --no-cov -k "worker or forced_past or unavailable or behind_a_running"`.
- [ ] **Step 3: Implement**; mark the booby-trap tests in `tests/test_rasterise.py` with `in_process_sandbox`; add `lower_data_limit_then_stream` and `slow_count` to `tests/sandbox_targets.py` if Task 6 did not.
- [ ] **Step 4: Green.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_rasterise.py tests/test_upload_utils.py tests/test_web_teacher.py tests/test_web_review.py tests/test_student_correct.py -q --no-cov`.
- [ ] **Step 5: `pre-commit run --files lemely/io/rasterise.py lemely/web/upload_utils.py tests/sandbox_targets.py tests/test_rasterise.py tests/test_upload_utils.py`**
- [ ] **Step 6: Commit.** `git commit -S -m "feat(io): stream extraction pages from the extraction worker and run the upload check there (#260)" -- lemely/io/rasterise.py lemely/web/upload_utils.py tests/sandbox_targets.py tests/test_rasterise.py tests/test_upload_utils.py`

### Task 11: Measurement: worker limits and the extraction timeout

**Files:**
- Modify: `lemely/runtime/config.py` (the four limit defaults and `extraction_timeout_seconds`), `lemely/runtime/sandbox.py` (module docstring numbers)
- Scratch: `/home/sico/.claude/jobs/33cebc31/tmp/plans/lane1/measure_workers.py` (not committed)

**Procedure.** The script builds the worst admitted scan: 40 A4 pages (595x842 pt) each carrying one full-page `tests.pdf_fakes.bilevel_png(2480, 3508, mark=(400, 400, 1200, 900), dpi=300)` inserted with `page.insert_image(page.rect, stream=png)` (pymupdf keeps the Flate data; ~1.2 MB file; 40 x 8.7 Mpx images; planned render ~155 Mpx at 200 dpi, which `plan_pdf_pages` admits). It also builds the 160 Mpx bilevel image `bilevel_png(10_000, 15_900, mark=(400, 400, 1200, 900), dpi=72)` (admitted by `check_scan_bytes`). With `SandboxSettings(enabled=True)` and limits set very high (4 GiB / 8 GiB) so nothing is killed, it measures inside each worker through `tests.sandbox_targets.peak_rss_of` plus a sampler: add to `tests/sandbox_targets.py` (lane 1 owns it in this wave) `def measure(target: str, *args: object) -> dict[str, int | float]` that starts a thread sampling `VmData` from `/proc/self/status` every 25 ms, runs the target (draining an iterator), and returns `{"vm_peak": VmPeak, "vm_hwm": VmHWM, "vm_data_max": max sample, "seconds": wall}` in bytes.
The admitted-image set (finding 8), each at its cap so the worst admitted image of every mode is covered: the 160 Mpx bilevel PNG above; a 40 Mpx RGB JPEG (`Image.new("RGB", (7300, 5479))` saved at quality 50, 39.99 Mpx); an 80 Mpx `I;16` PNG (`tests.pdf_fakes.sixteen_bit_grey_scan(10_000, 8_000, (100, 100, 400, 300))`, 80.0 Mpx); a lossless WebP at `MAX_DECODE_PX_WEBP` (`tests.pdf_fakes.plain_webp(3650, 3650)`, 13.32 Mpx, the largest the WebP ceiling admits). Each is written to the scratch dir and confirmed admitted by `check_scan_bytes` before measuring.
- Extraction worker: `lemely.io.rasterise.iter_scan_pages` on the 40-page PDF at 200.0 dpi and on each of the four images (image extraction goes through `_rasterise_single_image`); `lemely.io.scan_limits.check_scan_bytes` on the PDF bytes and on each image's bytes.
- Interactive worker: `lemely.io.scan_render.render_preview_png` and `crop_pdf_scan(data, 0, [100, 100, 300, 400])` on the 40-page PDF; `render_preview_png` and `crop_image_scan(data, [100, 100, 300, 400])` on each of the four images.

**Numbers to report** (in the task report and the `sandbox.py` docstring): per path and per input (5 inputs x the paths above), `vm_peak`, `vm_hwm`, `vm_data_max`, `seconds`; the child's post-import baseline (`measure("tests.sandbox_targets.pid")`).

**Decision rule.**
- `extraction_data_limit_bytes` = the next multiple of 64 MiB at or above 1.5 x the largest extraction-path `vm_data_max`; `extraction_address_limit_bytes` = next multiple of 64 MiB at or above 1.25 x the largest extraction-path `vm_peak`.
- The same for the interactive pair over the interactive paths.
- `extraction_timeout_seconds` = the largest extraction-path `seconds` x 4, rounded up to a multiple of 30 s, never below 120 s (a 1-vCPU Cloud Run instance is slower than this host); `upload_check_timeout_seconds` stays 20 s unless the measured `check_scan_bytes` exceeds 5 s (then 4x, rounded up to 5 s).
- Budget check: `233 + 441 + extraction_data_limit + interactive_data_limit + 75` (MB) must be under 2048; if not, report and stop (owner decision), do not lower the limits by hand.
- Then re-run both measurements under the chosen limits: every path must complete with `last_outcome == "ok"`; any `memory`/`crash` is reported and the limit is raised to the next 64 MiB step and re-run (at most twice; then stop and report).

- [ ] **Step 1: Write and run the script**: `cd $WORKTREE && PYTHONPATH=$PWD .venv/bin/python /home/sico/.claude/jobs/33cebc31/tmp/plans/lane1/measure_workers.py` (expect 1-3 minutes; it shuts both workers down at the end).
- [ ] **Step 2: Set the defaults** in `SandboxSettings` and write the docstring table in `sandbox.py` (host, library versions, per-path numbers, chosen limits, the rule).
- [ ] **Step 3: Pin the budget in a test**: `tests/test_sandbox.py::test_the_default_limits_fit_the_two_gib_budget`: `233 + 441 + s.extraction_data_limit_bytes/2**20 + s.interactive_data_limit_bytes/2**20 + 75 < 2048`. Red if the arithmetic ever fails.
- [ ] **Step 4: Green.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_sandbox.py tests/test_rasterise.py -q --no-cov`.
- [ ] **Step 5: `pre-commit run --files lemely/runtime/config.py lemely/runtime/sandbox.py tests/sandbox_targets.py tests/test_sandbox.py`**
- [ ] **Step 6: Commit.** `git commit -S -m "feat(runtime): set the worker rlimits and the extraction timeout from the worst admitted scan (#260)" -- lemely/runtime/config.py lemely/runtime/sandbox.py tests/sandbox_targets.py tests/test_sandbox.py`

### Task 12: Instance memory 2 GiB and the budget table

**Files:**
- Modify: `.github/workflows/deploy.yml:278` (`--memory=1Gi` -> `--memory=2Gi`) and the comment block at `:258-277` (one paragraph: the 2 GiB is the sum of the two worker limits, the parent and the pages it holds; see `docs/ci-cd.md`)
- Modify: `docs/ci-cd.md` (new subsection `### Memory budget` under "Configuring the deployed service", before "### The marking flags" at line 311): the budget table from Global Constraints with the measured values from Task 11, the env names of the four limits and four timeouts, and the sentence that the serialised workers are the concurrency cap (no `--concurrency`).

- [ ] **Step 1: Red check**: `grep -n "memory=2Gi" .github/workflows/deploy.yml` prints nothing.
- [ ] **Step 2: Edit both files.**
- [ ] **Step 3: Verify**: `grep -n "memory=2Gi" .github/workflows/deploy.yml` prints line 278; `pre-commit run --files .github/workflows/deploy.yml docs/ci-cd.md` (check-yaml, trailing whitespace).
- [ ] **Step 4: Commit.** `git commit -S -m "ci(deploy): run the backend at 2Gi and record the worker memory budget (#260, #271)" -- .github/workflows/deploy.yml docs/ci-cd.md`

---

## Wave 3 — lane 2 (#261)

### Task 13: Skip `/PieceInfo` and `/Metadata` edges in the walk

**Files:**
- Modify: `lemely/io/pdf_content_walk.py` (`_dict_refs`, originally `scan_limits.py:946-967`)
- Create: `tests/fakes_pdftex.py`
- Modify: `tests/test_pdf_content_walk.py`

**Interfaces:**
- `_dict_refs` skips keys `Resources` (as today), `PieceInfo` and `Metadata` (pymupdf's `xref_get_keys` returns keys without the slash). `_SKIPPED_DICT_KEYS = frozenset({"Resources", "PieceInfo", "Metadata"})`. Docstring: ISO 32000-1 §14.5 (page-piece dictionaries) and §14.3.2 (metadata streams) define both as not rendered; the skip is on the edge, so an object also reachable through a drawn key is still counted there.
- `tests/fakes_pdftex.py`:
  - `def pdftex_included_figure_pdf(private_bytes: int, pages: int, *, draw_private: bool = False, private_names_page_tree: bool = False) -> bytes`: built with `assemble_pdf`/`pdf_stream` from `tests.pdf_fakes`: a `/Subtype /Form` XObject (a small content `q 0 0 1 rg 10 10 100 100 re f Q`, `/BBox [0 0 200 200]`) whose dictionary carries `/PieceInfo << /Illustrator << /Private << /AIPrivateData1 N 0 R /AIPrivateData2 M 0 R >> /LastModified (D:20260101000000) >> >>` where the two private objects are Flate streams inflating to `private_bytes` each (`flate_bomb_ops`-style compressible payload, so the file is a few KB); every page's `/Resources /XObject << /Fig F 0 R >>` draws it (`/Fig Do`). `draw_private=True` also lists `/AIPrivateData1` under the form's `/Resources /XObject` (reachable through a drawn key). `private_names_page_tree=True` makes `/Private` reference the `/Pages` root object.
  - `def pdftex_like_form_xobject_page(...)` is not needed; keep one builder.

- [ ] **Step 1: Write the failing tests** (`tests/test_pdf_content_walk.py`, class `PieceInfoTests`):
  - `test_a_pdftex_figure_with_private_data_on_every_page_passes`: `pdftex_included_figure_pdf(1_000_000, 40)` -> `check_scan_bytes` returns None (2 x 1 MB on 40 pages would be 80 MB of counted content, over `MAX_SCAN_CONTENT_BYTES` 64 MB). Red: `ScanTooLargeError` (`_WHOLE_SCAN_MESSAGE`).
  - `test_a_single_page_figure_with_nine_megabytes_of_private_data_passes`: `pdftex_included_figure_pdf(4_500_000, 1)` passes (today refused by the 8 MB page cap).
  - `test_private_data_also_drawn_is_still_counted`: `pdftex_included_figure_pdf(9_000_000, 1, draw_private=True)` is refused (`ScanTooLargeError`, page message). Green before and after (coverage guard).
  - `test_private_data_naming_the_page_tree_is_accepted_and_renders_alike`: `pdftex_included_figure_pdf(1000, 1, private_names_page_tree=True)` passes `check_scan_bytes`; `canonical_pdf_bytes` succeeds; pdfium renders the stored file and the rewrite to identical grey bytes at scale 0.5 (the `RewriteFidelityTests._pdfium_grey` shape). Red today: refused as a walk reaching the page tree.
  - `test_metadata_streams_are_not_counted`: a form with `/Metadata` naming a 9 MB Flate XMP stream passes. Red today.
- [ ] **Step 2: Red.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_pdf_content_walk.py -q --no-cov -k PieceInfo`.
- [ ] **Step 3: Implement** the skip.
- [ ] **Step 4: Green.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_pdf_content_walk.py tests/test_pdf_canonical.py tests/test_scan_limits.py -q --no-cov`.
- [ ] **Step 5: Probe (not committed).** With the host's `pdflatex` (pdfTeX 1.40.29): write `/home/sico/.claude/jobs/33cebc31/tmp/plans/lane2/figure.pdf` (a one-page PDF with the Illustrator-shaped `/PieceInfo`, from the builder with `pages=1`), a `main.tex` that `\includegraphics` it on 40 pages, run `pdflatex -interaction=batchmode main.tex` in that directory, and run `check_scan_bytes` on `main.pdf` before and after the fix (checkout `HEAD~1` of the module in a scratch copy, or simply report the refusal message captured before Step 3). Report: the `/PieceInfo` key is present in the output's Form XObject (`grep -a -c PieceInfo main.pdf`), refused before, passes after.
- [ ] **Step 6: `pre-commit run --files lemely/io/pdf_content_walk.py tests/fakes_pdftex.py tests/test_pdf_content_walk.py`**
- [ ] **Step 7: Commit.** `git commit -S -m "fix(walk): do not count a form's /PieceInfo or /Metadata as drawing data (#261)" -- lemely/io/pdf_content_walk.py tests/fakes_pdftex.py tests/test_pdf_content_walk.py`

---

## Wave 3 — lane 3a (#274 hidden content)

### Task 14: Prune `/OC`-hidden XObjects and annotations in the rewrite

**Files:**
- Modify: `lemely/io/pdf_canonical.py` (`_copy_pages`, originally `scan_limits.py:1941-1990`)
- Create: `tests/fakes_reader_agreement.py`
- Modify: `tests/test_pdf_canonical.py`

**Interfaces:**
- In `pdf_canonical.py`: `def _hidden_ocg_xrefs(source: pdf_document) -> set[int]` (the xrefs listed in `/OCProperties /D /OFF`, via `_mupdf.pdf_dict_getp(catalog, "OCProperties/D/OFF")`, array elements resolved with `pdf_to_num` of each indirect reference); `def _hidden_ocg_xrefs` also honours `/OCProperties /D /BaseState /OFF`: then every group in `/OCProperties /OCGs` is hidden except those listed in `/D /ON`; `def _is_hidden(obj, hidden: set[int]) -> bool`: its `/OC` is an indirect reference to an OCG whose number is in `hidden`, or a dictionary (direct or indirect) with `/Type /OCMD`, judged by its `/P` policy over the groups named by `/OCGs` (a single reference or an array; a missing or empty `/OCGs` means visible): `/AnyOn` (the default) is hidden only when every named group is off; `/AllOn` is hidden when any named group is off; `/AnyOff` is hidden when no named group is off; `/AllOff` is hidden when any named group is on. `/VE` is skipped (not evaluated; `/P` and `/OCGs` decide, which is what MuPDF's `pdf_is_ocg_hidden` does when it cannot evaluate the expression); `def _prune_hidden_optional_content(target: pdf_document, hidden: set[int]) -> None`: for each page of the copy (`pdf_lookup_page_obj`, no `load_page`), delete each `/Resources /XObject` entry whose value is hidden, and remove each `/Annots` element that is hidden (`pdf_array_delete`). Runs after `insert_pdf` and the `/Group` and `/OCProperties` grafts, on the copy only; reads dictionaries, never page content. `_copy_pages` calls it when `hidden` is non-empty. Residual: content-stream operators (`/OC /name BDC`) are not rewritten (pdfium honours marked content; the `text` variant already agrees).
- `tests/fakes_reader_agreement.py` (module docstring: builders for the marker/teacher agreement tests; lane 3b appends TIFF builders):
  - `def filled_text_field_pdf(value: str = "42") -> bytes`: one A4 page with a text widget (`page.add_widget` or pymupdf `Widget` with `field_type=PDF_WIDGET_TYPE_TEXT`, `field_value=value`, `rect=(100, 100, 300, 140)`, `text_fontsize=24`), `widget.update()`, `doc.tobytes()`; the value is drawn (MuPDF 1,578 dark px in the probe).
  - `def oc_hidden_bomb_pdf(inflated_bytes: int) -> bytes`: `xobject_bomb_pdf`-shaped, but the form carries `/OC` pointing at an OCG listed in `/OCProperties /D /OFF`.
  - `def dark_pixels(png_or_grey: bytes, size: tuple[int, int]) -> int` and `def mupdf_grey(data: bytes, page: int, *, zoom: float) -> bytes` / `def pdfium_grey(data: bytes, page: int, *, scale: float) -> bytes` helpers used by both this lane's and lane 3b's agreement tests.

- [ ] **Step 1: Write the failing tests** (`tests/test_pdf_canonical.py`, class `ReaderAgreementTests`):
  - `test_the_marker_sees_what_the_teacher_sees_for_a_hidden_image_layer`: `data = hidden_layer_pdf(variant="image")`; `page = rasterise_pdf_to_pages(path)[0]` (write `data` to `tmp`), convert its PNG to "L" at the rasterised size; MuPDF render of the stored file at the same pixel size (`zoom = page.width / 595`), "L"; count differing bytes; assert under the tolerance the `text` variant meets (measure the `text` variant in the same test first and assert the image variant's difference is at most that plus 200 bytes; record both numbers). Red: 78,160 vs 1,986 dark pixels.
  - `test_the_hidden_image_is_absent_from_the_rewrite_under_pdfium`: `pdfium_grey(canonical_pdf_bytes(data), 0, scale=0.5)` has at most as many dark pixels as `pdfium_grey(hidden_layer_pdf-with-only-visible-text)`, and strictly fewer than `pdfium_grey(data)` (the stored file, which pdfium draws in full). Red today: equal to the stored file (that is the existing `test_layers_hidden_by_default_stay_hidden`, which compares pdfium with pdfium; keep it but rename its docstring to say it pins the `/OCProperties` graft, and add this inverse).
  - `test_an_oc_hidden_content_bomb_is_still_refused_by_the_walk`: `oc_hidden_bomb_pdf(112_000_000)` -> `canonical_pdf_bytes` raises `ScanTooLargeError`. Green before and after.
  - `test_ocmd_policies_decide_what_the_rewrite_drops`: add `ocmd_image_pdf(policy: str, states: tuple[bool, ...], *, base_state_off: bool = False)` to `tests/fakes_reader_agreement.py` (one page, one image XObject whose `/OC` is an `/OCMD` with `/P /<policy>` over `len(states)` groups whose `/D /ON`/`/OFF` membership is `states`; `base_state_off` writes `/BaseState /OFF` and lists only the `True` groups in `/ON`); for each of `("AnyOn", (False, False), hidden)`, `("AnyOn", (True, False), shown)`, `("AllOn", (True, False), hidden)`, `("AllOn", (True, True), shown)`, `("AnyOff", (True, True), hidden)`, `("AnyOff", (True, False), shown)`, `("AllOff", (True, False), hidden)`, `("AllOff", (False, False), shown)`, and `("AnyOn", (False,), hidden, base_state_off=True)`, the pdfium render of the rewrite has dark pixels iff `shown`, and equals the MuPDF render of the stored file within the Task tolerance. Red today for every `hidden` case.
  - `test_every_committed_pdf_renders_identically_through_the_rewrite`: for every `sorted(Path("tests").rglob("*.pdf"))` (18 files on this tree; `tests/fixtures/0625_s24_gt.pdf` or whichever is the encrypted one raises `ScanRejectedError` and is asserted to), pdfium grey at scale 0.5 of stored vs rewrite is byte-identical per page. Green before and after (regression guard for the prune); record the page count rendered.
- [ ] **Step 2: Red.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_pdf_canonical.py -q --no-cov -k ReaderAgreement`. Expected: the first two fail.
- [ ] **Step 3: Implement** the prune.
- [ ] **Step 4: Green.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_pdf_canonical.py tests/test_rasterise.py -q --no-cov`.
- [ ] **Step 5: `pre-commit run --files lemely/io/pdf_canonical.py tests/fakes_reader_agreement.py tests/test_pdf_canonical.py`**
- [ ] **Step 6: Commit.** `git commit -S -m "fix(canonical): drop /OC-hidden XObjects and annotations from the rewrite so pdfium hides what MuPDF hides (#274)" -- lemely/io/pdf_canonical.py tests/fakes_reader_agreement.py tests/test_pdf_canonical.py`

---

## Wave 3 — lane 4 (#276.1, #276.3, #269 audit)

### Task 15: The MuPDF-open sweep resolves bindings

**Files:**
- Create: `tests/mupdf_sweep.py`, `tests/test_mupdf_sweep.py`
- Modify: `tests/test_scan_limits.py` (only the bodies of the two tests in `SanctionedOpenerSweepTests`, the class Task 2 kept here: `test_every_mupdf_open_of_user_bytes_goes_through_the_sanctioned_openers` becomes a one-line call; `test_only_prescan_pdf_makes_a_prescanned_pdf` likewise; the class stays in this file)

**Interfaces:**
- `tests/mupdf_sweep.py`:
  - `def find_mupdf_opens(source: str, filename: str) -> set[tuple[str, str]]`: `(filename, enclosing function or "<module>")` for every call with arguments through a binding of `pymupdf`/`fitz` (`import pymupdf [as x]`, `import fitz [as x]`), through `from pymupdf import open|Document [as y]` (and `fitz`), through assignments `z = pymupdf`, `z = fitz`, `z = pymupdf.open`, `z = pymupdf.Document` (one level of aliasing, module scope and function scope), i.e. `x.open(...)`, `x.Document(...)`, `y(...)`, `z(...)`, `z.open(...)`; plus every `.insert_pdf(` and `.insert_file(` call anywhere.
  - `def find_prescanned_constructions(source: str, filename: str) -> set[tuple[str, str]]`.
  - `def sweep(root: Path, finder) -> set[tuple[str, str]]` over `root/"lemely"` `*.py`.
  - `ALLOWED_OPENS = {("lemely/io/pdf_canonical.py", "open_checked_pdf"), ("lemely/io/pdf_canonical.py", "open_scan_image_document"), ("lemely/io/pdf_canonical.py", "_copy_pages")}` (the last for `insert_pdf`), `ALLOWED_PRESCANNED = {("lemely/io/pdf_prescan.py", "prescan_pdf")}`.
  - Module docstring: what it cannot see (`getattr(pymupdf, "open")`, `importlib.import_module("pymupdf")`, aliasing deeper than one assignment, calls built from strings); those are reviewer territory.
- `tests/test_mupdf_sweep.py`: one test per evasion feeding a source string: `import pymupdf as m; m.open(stream=b)`, `import fitz as f; f.Document(b)`, `from pymupdf import open as o; o(b)`, `from pymupdf import Document; Document(b)`, `z = pymupdf; z.open(b)`, `z = pymupdf.open; z(b)`, `doc.insert_pdf(other)`, `doc.insert_file(b)`; negative cases: `pymupdf.open()` (no args), `pymupdf.Matrix(1, 1)`, a local variable named `open` that is not from pymupdf. The repo-level assertions stay where they are: `SanctionedOpenerSweepTests` in `tests/test_scan_limits.py` keeps both test names and calls `sweep(root, find_mupdf_opens) == ALLOWED_OPENS` and `sweep(root, find_prescanned_constructions) == ALLOWED_PRESCANNED`; `tests/test_mupdf_sweep.py` holds only the evasion self-tests.

- [ ] **Step 1: Write the failing tests** (`tests/test_mupdf_sweep.py`). Red: module missing.
- [ ] **Step 2: Red.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_mupdf_sweep.py -q --no-cov`.
- [ ] **Step 3: Implement** the sweep; rewire the two tests in `tests/test_scan_limits.py`.
- [ ] **Step 4: Green.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_mupdf_sweep.py tests/test_scan_limits.py -q --no-cov`. Expected: the repo sweep's found set equals `ALLOWED_OPENS` exactly (if lane 1's `scan_render.py` is already on the branch it must still only call `open_checked_pdf`/`open_scan_image_document`; if the sweep finds anything else, report it, do not widen the allowlist).
- [ ] **Step 5: `pre-commit run --files tests/mupdf_sweep.py tests/test_mupdf_sweep.py tests/test_scan_limits.py`**
- [ ] **Step 6: Commit.** `git commit -S -m "test(sweep): resolve pymupdf bindings and insert_pdf/insert_file in the MuPDF-open sweep (#276)" -- tests/mupdf_sweep.py tests/test_mupdf_sweep.py tests/test_scan_limits.py`

### Task 16: Mark-scheme pickers accept PDF only

**Files:**
- Modify: `web/src/lib/scanAccept.ts` (add `SCHEME_ACCEPT`), `web/src/portals/student/screens/CorrectPaper.tsx:852` (`accept={SCHEME_ACCEPT}` on `id="scheme-file"`), `web/src/portals/teacher/screens/Grading.tsx:708` (`accept={SCHEME_ACCEPT}` on `id="grading-scheme-file"`)
- Test: `web/tests/unit/scanAccept.test.ts`

**Interfaces:** `export const SCHEME_ACCEPT = "application/pdf"` with a comment that the scheme is parsed as PDF only (`lemely/web/routers/teacher.py:1258-1271`, `DeterministicMarkSchemeParser`). Test: parse each screen's source for `<input`/`<FileDrop` elements, extracting `id="..."` and `accept={...}` from the same element (regex over the element's opening tag, `/<(?:input|FileDrop)\b[^>]*?>/gs`); assert `scheme-file` and `grading-scheme-file` -> `SCHEME_ACCEPT`, every other input with an `accept` -> `SCAN_ACCEPT`, `image/*` nowhere, and `SCHEME_ACCEPT === "application/pdf"`.

- [ ] **Step 1: Rewrite the test** as above. Red: `SCHEME_ACCEPT` is not exported (typecheck fails) and both scheme inputs read `SCAN_ACCEPT`.
- [ ] **Step 2: Red.** `cd web && npx vitest run tests/unit/scanAccept.test.ts`.
- [ ] **Step 3: Implement** the constant and the two `accept` props (import `SCHEME_ACCEPT` beside `SCAN_ACCEPT`).
- [ ] **Step 4: Green.** `cd web && npx vitest run tests/unit/scanAccept.test.ts && npm run typecheck && npm run check:copy`.
- [ ] **Step 5: `pre-commit run --files web/src/lib/scanAccept.ts web/src/portals/student/screens/CorrectPaper.tsx web/src/portals/teacher/screens/Grading.tsx web/tests/unit/scanAccept.test.ts`**
- [ ] **Step 6: Commit.** `git commit -S -m "fix(web): mark-scheme pickers accept PDF only (#276)" -- web/src/lib/scanAccept.ts web/src/portals/student/screens/CorrectPaper.tsx web/src/portals/teacher/screens/Grading.tsx web/tests/unit/scanAccept.test.ts`

### Task 17: The stored-scan page audit script

**Files:**
- Create: `scripts/audit_stored_scan_pages.py`, `tests/test_audit_stored_scan_pages.py`

**Interfaces:**
- `@dataclass(frozen=True) class StoredObject: table: Literal["uploads", "teacher_papers"]; row_id: str; storage_path: str`.
- `def stored_objects(session_factory: sessionmaker[Session]) -> Iterator[StoredObject]`: `select(Upload.id, Upload.storage_path)` and `select(TeacherPaper.id, TeacherPaper.storage_path)` in one session each (the repos expose no listing; the models are read directly through the same `sessionmaker` the repos use, `lemely.db.session.get_sessionmaker(settings)`). Soft-deleted rows are excluded by the session's own rule (`_exclude_soft_deleted`).
- `def count_pages(data: bytes) -> int | None`: `len(pdfium.PdfDocument(data))` for `looks_like_pdf(data)` bytes, closing the document; `None` when pdfium cannot open it; `1` for image bytes; nothing rendered, no MuPDF.
- `@dataclass class Histogram: by_table: dict[str, Counter[str]]` with buckets `"1-40"`, `"41-200"`, `"over_200"`, `"unreadable"`, `"missing"` (a `StorageObjectNotFoundError`), `bytes_downloaded: int`, `sampled: int`; `def audit(objects: Iterable[StoredObject], storage: StorageBackend, bucket: str, *, sample: int | None, rng: random.Random) -> Histogram` (`sample` picks `rng.sample` of the objects); `def render(histogram: Histogram) -> str` (one table, plus "over 40", "over 200", bytes downloaded, sampled/total).
- `def main(argv: list[str] | None = None) -> int`: `--sample N`, `--seed S`, `--bucket` (default `settings.storage.bucket`); builds the GCS backend as `lemely/web/deps.py:get_storage_backend` does (import that function); prints `render(...)`.

- [ ] **Step 1: Write the failing tests** (`tests/test_audit_stored_scan_pages.py`, importing `from scripts import audit_stored_scan_pages as audit_script`, as `tests/test_check_ui_gates.py` imports its script): `test_audit_buckets_each_object_by_page_count_and_table` (FakeStorageBackend with a 3-page, a 41-page and a 201-page synthetic PDF, an image PNG, and a missing key; expected counters), `test_audit_never_renders_or_opens_with_mupdf` (`patch.object(pymupdf, "open")` and `patch.object(pdfium.PdfPage, "render")` not called), `test_sample_limits_downloads` (`sample=2` -> `bytes_downloaded` is the sum of two objects), `test_render_prints_the_over_40_and_over_200_totals`. Red: module missing.
- [ ] **Step 2: Red.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_audit_stored_scan_pages.py -q --no-cov`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Green.** Same command; also `PYTHONPATH=$PWD .venv/bin/python scripts/audit_stored_scan_pages.py --help` exits 0.
- [ ] **Step 5: `pre-commit run --files scripts/audit_stored_scan_pages.py tests/test_audit_stored_scan_pages.py`**
- [ ] **Step 6: Commit.** `git commit -S -m "feat(scripts): audit stored scans' page counts with pdfium only (#269)" -- scripts/audit_stored_scan_pages.py tests/test_audit_stored_scan_pages.py`

---

## Wave 4 — lane 3b (#274 forms, #275), after lane 1's Task 12

### Task 18: Forms render in extraction

**Files:**
- Modify: `lemely/io/rasterise.py` (`_iter_pdf_pages`)
- Modify: `tests/test_rasterise.py`

**Interfaces:** after `pdf = pdfium.PdfDocument(canonical)`, call `pdf.init_forms()`. That is the whole behaviour change: in pypdfium2 5.11 `PdfPage.render`'s `may_draw_forms` already defaults to `True` (`inspect.signature(pypdfium2.PdfPage.render)` on this venv shows `may_draw_forms=True`), and it draws nothing until `init_forms()` has run; pass `may_draw_forms=True` explicitly anyway so the intent survives a default change. `init_forms` parses `/AcroForm`, which the rewrite copies unwalked and is bounded by the object-stream bound and the upload cap; it runs inside `EXTRACTION_WORKER` (Task 10), which is why this lands now.

- [ ] **Step 1: Failing test** `tests/test_rasterise.py::test_the_marker_sees_a_filled_text_field_as_the_teacher_does`: `filled_text_field_pdf("42")` from `tests.fakes_reader_agreement`; extraction page 1 (in-process `rasterise_pdf_to_pages`) vs `mupdf_grey` of the stored file at the same size; differing bytes under the same tolerance rule Task 14 established (compute against the `text` variant of `hidden_layer_pdf`); also assert the extraction render has more than 1,000 dark pixels (today 0). Red: pdfium draws no field value.
- [ ] **Step 2: Red.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_rasterise.py -q --no-cov -k filled_text_field`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Green.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_rasterise.py tests/test_pdf_canonical.py -q --no-cov` (the committed-PDF fidelity sweep in `test_pdf_canonical.py` compares pdfium with pdfium without forms, so it is unaffected; `GeometryBoundedRasteriseTests.test_the_committed_fixture_is_unaffected` at `tests/test_rasterise.py:564` and `RasterisePdfToPagesTests.test_real_fixture_rasterises_to_its_known_page_count` at `:121` must still pass, since the committed fixture has no `/AcroForm`).
- [ ] **Step 5: `pre-commit run --files lemely/io/rasterise.py tests/test_rasterise.py`**
- [ ] **Step 6: Commit.** `git commit -S -m "fix(rasterise): draw form field values in extraction renders (#274)" -- lemely/io/rasterise.py tests/test_rasterise.py`

### Task 19: TIFF orientation: open from a file object; crop reads the tag after load

**Files:**
- Modify: `lemely/io/rasterise.py` (`_rasterise_single_image`, line 243 area: `with image_path.open("rb") as handle, open_scan_image(handle) as opened:`)
- Modify: `lemely/io/scan_render.py` (`crop_image_scan`: `opened.load()` before `opened.getexif().get(EXIF_ORIENTATION_TAG)`; `_decode_within_ceiling` still runs before the load, as it reads the header only)
- Modify: `tests/fakes_reader_agreement.py` (TIFF builders), `tests/test_rasterise.py`, `tests/test_scan_render.py`

**Interfaces:**
- Builders: `def oriented_tiff(mode: Literal["L", "I;16", "1"], size: tuple[int, int], orientation: int, *, compression: Literal["raw", "tiff_lzw"], mark: tuple[int, int, int, int]) -> bytes` (stored frame `size`; dark `mark` box in the stored frame; single strip for `raw`: Pillow writes one strip when `rows_per_strip` is the height, pass `tiffinfo={278: size[1]}` or confirm with `TiffImagePlugin` that `StripOffsets` has one entry; the `Orientation` tag 274 set via `tiffinfo`); `def expected_upright(stored: bytes) -> Image` (Pillow `exif_transpose` of a `BytesIO` open, the reference frame).
- Contract: a Pillow 12.2 TIFF opened through `open_scan_image` is upright after `load()` and has no orientation tag.

- [ ] **Step 1: Write the failing tests.**
  - `tests/test_rasterise.py::test_an_uncompressed_oriented_tiff_is_turned_upright` (modes `L` and `I;16`, orientation 6, `raw`, written to a path, through `rasterise_scan_to_pages`): page size is the upright size and the mark's dark pixels are where `expected_upright` puts them (compare bounding boxes). Red today: the mmap fast path scrambles it (600x300 with the mark scattered).
  - `tests/test_rasterise.py::test_pillow_turns_a_tiff_upright_at_load_and_drops_the_tag` (the contract pin): `open_scan_image(io.BytesIO(oriented_tiff("L", (600, 300), 6, compression="raw", ...)))`, `load()`, `size == (300, 600)`, `getexif().get(0x0112) is None`; same for `tiff_lzw`. Green today; it exists to go red on a Pillow change.
  - `tests/test_scan_render.py::test_crop_agrees_with_extraction_for_an_oriented_tiff` (raw and lzw, orientations 6 and 8): extraction boxes the mark (from the upright page, the box in 0-1000 units); `crop_image_scan(tiff_bytes, box)` contains the dark mark (dark pixel count > 100). Red today: the crop is blank (the tag is re-applied to an already-upright frame).
- [ ] **Step 2: Red.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_rasterise.py tests/test_scan_render.py -q --no-cov -k tiff`.
- [ ] **Step 3: Implement** both changes; update the `crop_image_scan` docstring (the "no second full-size copy" property is about the transpose, which still happens on the crop only).
- [ ] **Step 4: Green.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_rasterise.py tests/test_scan_render.py tests/test_web_review.py -q --no-cov` (`test_crop_of_a_large_flagged_photo_makes_no_second_full_size_copy` must still pass: the JPEG path is unchanged).
- [ ] **Step 5: Draft the Pillow bug report** (not committed) at `/home/sico/.claude/jobs/33cebc31/tmp/plans/lane3b/pillow-map-buffer-bug.md`: `ImageFile.load`'s mmap fast path calls `map_buffer(self.map, self.size, ...)` with the orientation-swapped `size` for an uncompressed single-strip TIFF whose `_setup` swapped `size` for orientations 5-8, while `_tile_size` keeps the stored size; minimal reproducer from the builder; Pillow 12.2.0. The owner files it.
- [ ] **Step 6: `pre-commit run --files lemely/io/rasterise.py lemely/io/scan_render.py tests/fakes_reader_agreement.py tests/test_rasterise.py tests/test_scan_render.py`**
- [ ] **Step 7: Commit.** `git commit -S -m "fix(images): open TIFFs from a file object and read the orientation after load so pages and crops come out upright (#275)" -- lemely/io/rasterise.py lemely/io/scan_render.py tests/fakes_reader_agreement.py tests/test_rasterise.py tests/test_scan_render.py`

### Task 20: Wide grey scaling by inferred container depth

**Files:**
- Modify: `lemely/io/rasterise.py:181-220` (`_SIXTEEN_TO_EIGHT_BITS`, `_wide_grey_to_l`)
- Modify: `tests/fakes_reader_agreement.py`, `tests/test_rasterise.py`

**Interfaces:**
- `def _full_scale(image: PILImage) -> float | None`: `lo, hi = image.getextrema()`; a flat image (`lo == hi`) returns `None`; for `"F"` with `hi <= 1.0` the full scale is `1.0` (normalised floats: a sample `v` maps to `v * 255 / 1.0`, so 0.95 -> 242 and 0.05 -> 13); for `"F"` with `hi > 1.0` and for `"I"`: the smallest of `2**8-1, 2**10-1, 2**12-1, 2**14-1, 2**16-1, 2**20-1, 2**24-1, 2**32-1` that is `>= hi`; for the `I;16*` modes: the smallest of `2**8-1, 2**10-1, 2**12-1, 2**14-1, 2**16-1` that is `>= hi`.
- `_wide_grey_to_l`: when `_full_scale` is `None`, returns a white "L" image; else the strip-wise `point(lambda v: v * (255 / full_scale))` (linear, so Pillow's scale-and-offset path still applies; a value above `full_scale` cannot occur, since `full_scale >= hi`). `_SIXTEEN_TO_EIGHT_BITS` is removed. One `getextrema()` pass over the whole image (C-level, no copy) before the strips.
- Builders: `def wide_grey_scan(mode: Literal["I;16", "I", "F"], size, paper: float, ink: float, box, *, image_format: Literal["PNG", "TIFF"]) -> bytes` (generalises `sixteen_bit_grey_scan`; `"F"` only as TIFF).

- [ ] **Step 1: Write the failing tests** (`tests/test_rasterise.py`):
  - `test_twelve_bit_samples_in_a_sixteen_bit_container_keep_their_contrast`: paper 4000, ink 200, PNG and TIFF -> "L" 249 and 12 (`round(4000 * 255 / 4095)`, `round(200 * 255 / 4095)`; assert within 1). Red today: 16 and 1.
  - `test_eight_bit_samples_in_a_sixteen_bit_container_are_scaled_by_255`: paper 250, ink 20 -> 250 and 20. Red.
  - `test_a_flat_wide_grey_image_maps_to_white`: all samples 4000 -> every pixel 255. Red (today 16).
  - `test_a_genuine_sixteen_bit_scan_is_unchanged`: `SIXTEEN_BIT_PAPER`/`SIXTEEN_BIT_INK` (60000/5000) -> exactly the values `test_a_sixteen_bit_greyscale_scan_keeps_its_ink` asserts today. Green before and after.
  - `test_a_normalised_float_tiff_is_scaled_by_255`: `"F"`, paper 0.95, ink 0.05 -> 242 and 13. Red today (black).
  - `test_a_float_tiff_above_one_is_treated_like_i`: paper 60000.0, ink 5000.0 -> as the 16-bit case.
- [ ] **Step 2: Red.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_rasterise.py -q --no-cov -k "bit_samples or flat_wide or float_tiff"`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Green.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_rasterise.py tests/test_scan_render.py tests/test_web_review.py -q --no-cov -k "grey or sixteen or wide or crop"`, then the three files in full.
- [ ] **Step 5: `pre-commit run --files lemely/io/rasterise.py tests/fakes_reader_agreement.py tests/test_rasterise.py`**
- [ ] **Step 6: Commit.** `git commit -S -m "fix(rasterise): scale wide greyscale samples by their inferred container depth, not a fixed 16 bits (#275)" -- lemely/io/rasterise.py tests/fakes_reader_agreement.py tests/test_rasterise.py`

---

## Wave 4 — lane 2b (#273.3), after lane 1's Task 12

### Task 21: Measurement gate: a 160 Mpx bilevel image inside a PDF, inside the workers

**Starts only after Task 18 has landed** (its extraction path runs `rasterise.py`'s render loop, which Task 18 changes with `init_forms()`; measuring before it would measure the wrong code). Tasks 19 and 20 may run concurrently with this one.

**Files:**
- Modify: `tests/sandbox_targets.py` (append `def bilevel_pdf_paths(path: str, mode: str) -> dict[str, object]`)
- Scratch: `/home/sico/.claude/jobs/33cebc31/tmp/plans/lane2b/measure_bilevel.py` (not committed)

**Procedure.** Build `pdf = pymupdf.open(); page = pdf.new_page(width=595, height=842); page.insert_image(page.rect, stream=bilevel_png(10_000, 15_900, mark=(400, 400, 1200, 900), dpi=72)); data = pdf.tobytes()`; confirm the image XObject declares `/BitsPerComponent 1` or `/ImageMask true` (`pdf.xref_object(xref)`), else rebuild with `assemble_pdf` and a Flate-compressed 1-bit `/DeviceGray` image stream. Write it to the scratch dir. The walk refuses it today (40 Mpx cap), so the child target `bilevel_pdf_paths` sets `lemely.io.pdf_content_walk.MAX_DECODE_PX = 160_000_000` in the child before running each path (the module reads the global at call time), then runs, under the limits Task 11 set (`SandboxSettings` defaults, `enabled=True`):
- extraction: `lemely.io.rasterise.iter_scan_pages(path, 200.0)` in `EXTRACTION_WORKER`;
- crop: `lemely.io.scan_render.crop_pdf_scan(data, 0, [100, 100, 300, 400])` in `INTERACTIVE_WORKER`;
- preview: `lemely.io.scan_render.render_preview_png(data)` in `INTERACTIVE_WORKER`;
each through `tests.sandbox_targets.measure` (Task 11) for `vm_hwm`, `vm_data_max`, `vm_peak`, `seconds`, with `last_outcome` recorded.

**Numbers to report:** per path `vm_hwm`, `vm_data_max`, `vm_peak`, `seconds`, `last_outcome`; the worker limits in force.

**Decision rule:** the relaxation is adopted only if all three paths end with `last_outcome == "ok"` AND each path's `vm_data_max` is under 80% of its worker's `RLIMIT_DATA`. Otherwise Task 22 is skipped, PDFs keep the colour cap, and the numbers go into the #273 closing comment (Task 25) with the failing path named.

- [ ] **Step 1: Add the target, write and run the script**: `cd $WORKTREE && PYTHONPATH=$PWD .venv/bin/python /home/sico/.claude/jobs/33cebc31/tmp/plans/lane2b/measure_bilevel.py` (shuts both workers down at the end).
- [ ] **Step 2: Record** the table and the verdict in the task report and in `/home/sico/.claude/jobs/33cebc31/tmp/plans/lane2b/verdict.md`.
- [ ] **Step 3: `pre-commit run --files tests/sandbox_targets.py`**
- [ ] **Step 4: Commit** (the target only): `git commit -S -m "test(sandbox): add the bilevel-in-PDF measurement target (#273)" -- tests/sandbox_targets.py`

### Task 22: Per-mode caps for images inside PDFs (only if Task 21 passed)

**Files:**
- Modify: `lemely/io/pdf_content_walk.py` (`_check_declared_pixels`, `_check_masks`, `_check_image_and_masks`; originally `scan_limits.py:1114-1190`)
- Modify: `tests/test_pdf_content_walk.py`

**Interfaces:**
- `def _image_mode(doc: pymupdf.Document, xref: int) -> str`: `"1"` when `/ImageMask` is `true` or `/BitsPerComponent` resolves to 1; else when the colour space is one-component (`/DeviceGray`, `/CalGray` (bare name, or array whose first name is one of them), or `/ICCBased` whose stream dictionary's `/N` resolves to 1, following one indirection for the array and the stream): `"L"` at bpc 8 (or unreadable bpc), `"I;16"` at 16; anything else, `/Indexed` included, `"RGB"`. Reads `_key`/`_name`/`_resolve_int` only; never decodes.
- `_check_declared_pixels` judges `width * height` against `decode_pixel_cap(_image_mode(doc, xref))` with the unchanged `_IMAGE_TOO_LARGE_MESSAGE`; `_check_image_and_masks` does the same for the `get_images` tuple's `xref` (the tuple's own bpc/colour-space fields are ignored in favour of the dictionary, so both paths agree). Masks: `/SMask` is one-component (`"L"`), a stream `/Mask` is an image mask (`"1"`), both via `_image_mode` of their own dictionaries.

- [ ] **Step 1: Write the failing tests** (`tests/test_pdf_content_walk.py`, class `ImageModeCapTests`), each image as `_declared_image`-style stream dictionaries via `assemble_pdf`:
  - `test_a_hundred_megapixel_bilevel_image_in_a_pdf_passes` (`/BitsPerComponent 1 /ColorSpace /DeviceGray`, 10000x10000 -> `check_scan_bytes` returns None). Red: refused at 40 Mpx.
  - `test_an_image_mask_of_a_hundred_megapixels_passes` (`/ImageMask true`). Red.
  - `test_a_hundred_megapixel_eight_bit_grey_image_passes` (`/DeviceGray` bpc 8) and `_icc_based_n1` variant. Red.
  - `test_a_hundred_megapixel_rgb_image_is_still_refused` (`/DeviceRGB`), `test_a_hundred_megapixel_indexed_image_is_still_refused` (`/Indexed`), `test_a_sixteen_bit_grey_image_over_eighty_megapixels_is_refused` (`/DeviceGray` bpc 16, 9000x9000 = 81 Mpx). Green before and after.
  - `test_a_bilevel_image_over_one_hundred_sixty_megapixels_is_refused` (13000x13000). Green before and after.
  - `test_the_soft_mask_of_a_colour_image_gets_the_grey_cap` (a 1000x1000 RGB image whose `/SMask` is 100 Mpx grey passes; whose `/SMask` is 170 Mpx is refused).
- [ ] **Step 2: Red.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_pdf_content_walk.py -q --no-cov -k ImageModeCap`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Green.** `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_pdf_content_walk.py tests/test_scan_limits.py tests/test_rasterise.py -q --no-cov`.
- [ ] **Step 5: `pre-commit run --files lemely/io/pdf_content_walk.py tests/test_pdf_content_walk.py`**
- [ ] **Step 6: Commit.** `git commit -S -m "feat(walk): judge bilevel and grey images inside PDFs against their own pixel cap (#273)" -- lemely/io/pdf_content_walk.py tests/test_pdf_content_walk.py`

---

## Wave 5 — final

### Task 23: Gate sweep (derived from `.github/workflows/ci.yml` at fb6618e4)

Run on the final tree, from the worktree root, in this order; every command must exit 0. If any later commit lands on the branch (Task 24 fixes), re-run the whole sweep; a sweep certifies only the tree it ran on.

Job `test` (per `ci.yml` lines 48-66, 98-99):
- [ ] `ruff check .`
- [ ] `ruff format --check .`
- [ ] `PYTHONPATH=$PWD .venv/bin/mypy lemely`
- [ ] `PYTHONPATH=$PWD .venv/bin/pyright lemely`
- [ ] `PYTHONPATH=$PWD .venv/bin/lint-imports`
- [ ] `alembic upgrade head` — CI-only unless Postgres is reachable on 127.0.0.1:54322; if reachable run it, else record "CI-only (no local Postgres)". This branch adds no migration.
- [ ] `pytest` — never in full locally. Local substitute, the union of every touched test file: `PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_scan_limits.py tests/test_pdf_prescan.py tests/test_pdf_content_walk.py tests/test_pdf_canonical.py tests/test_refusal_reasons.py tests/test_upload_utils.py tests/test_sandbox.py tests/test_scan_render.py tests/test_rasterise.py tests/test_web_teacher.py tests/test_web_review.py tests/test_student_correct.py tests/test_mupdf_sweep.py tests/test_audit_stored_scan_pages.py -q --no-cov`. Expected: 0 failed, and the number of skips equals the number on fb6618e4 for the same files (record both; the Postgres-backed tests skip identically on both trees when no server is up).
- [ ] `PYTHONPATH=$PWD .venv/bin/python scripts/check_review_rate_gate.py` (non-blocking in CI; record its output).

Job `pre-commit` (line 85):
- [ ] `pre-commit run --all-files --show-diff-on-failure`, then `git status --short` must be empty (the ruff hook autofixes; an autofix means the committed tree was not the one that passed — commit the fix and re-run).

Job `web` (lines 103-152), from `web/`:
- [ ] `npm ci` (only if `node_modules` is missing or `package-lock.json` changed; this branch does not change it)
- [ ] `npm run typecheck`
- [ ] `npm test`
- [ ] `npm run lint`
- [ ] `npm run check:copy`
- [ ] `npm run build` (its `postbuild` runs `check:bundle`)
- [ ] `npm run check:installable`

- [ ] Record every command, exit code and the summary line in `/home/sico/.claude/jobs/33cebc31/tmp/plans/gate-sweep.md` with the SHA it ran on (`git rev-parse HEAD`). No commit from this task unless a gate fails and a fix is needed (then a `fix(...)` commit naming only its paths, and the sweep re-runs).

### Task 24: Whole-branch review

- [ ] Dispatch an opus reviewer (`reviewer` or `code-reviewer`) on the range `fb6618e4..HEAD` at the SHA from Task 23, with the spec path, this plan path, and the lane reports. It must check at least: (1) every re-exported name in `scan_limits.__all__` resolves and no production caller imports a moved name from the wrong module; (2) `lemely/runtime/sandbox.py` has no static `lemely.io`/`lemely.core` import and every production `call`/`stream` target string starts with `lemely.io.`; (3) no user-facing message changed except the two the spec names (diff `_*_MESSAGE` constants and every `detail=` literal against fb6618e4); (4) every new test was shown red before its change (the task reports carry the red output); (5) the `/OC` prune does not load pages (`load_page` absent from `_copy_pages`); (6) every booby-trap test in `test_web_review.py`/`test_web_teacher.py`/`test_rasterise.py` (any test that patches `pymupdf`/`pdfium`/`PIL` in the test process) requests `in_process_sandbox` by name, no test module makes it autouse, and the ordinary route tests run through the real worker; (7) `storage_path` immutability evidence for the ETag; (8) the measured numbers in `sandbox.py`'s docstring match `SandboxSettings` defaults and the budget sum is under 2048 MB; (9) no `TODO`, `test.skip`, `pytest.mark.skip` added, no stub.
- [ ] Fix every blocking finding in a commit per finding (`fix(<scope>): ...`, paths only), then re-run Task 23 on the new HEAD. Non-blocking findings go to the report for the owner.

### Task 25: Issue-closing housekeeping (scratch only; the controller asks the owner before any push, PR or comment)

- [ ] Write `/home/sico/.claude/jobs/33cebc31/tmp/plans/issue-comments.md` with one closing comment per issue, per the spec's table:
  - #262: closes on lane 0 (the four modules, the four test files, the `__all__` test); #265 is told `tests/pdf_fakes.py`, `tests/test_scan_limits.py`, `tests/test_pdf_prescan.py`, `tests/test_pdf_content_walk.py`, `tests/test_pdf_canonical.py` are done.
  - #276: closes on lanes R and 4 (reason codes with the final set, the sweep's evasion list and what it cannot see, `SCHEME_ACCEPT`).
  - #260: closes on lane 1; says the four comment residuals (MuPDF `/Info` parse at open, off-walk objects, superlinear dictionary parsing, the pre-scan token budget) are bounded by the worker because open, walk and pre-scan run inside it; notes the parent still holds every page's PNG (up to ~441 MB) and that streaming pages to Gemini is out of scope; records the measured limits.
  - #249: closes on lane 1 (fixed message, `no-cache` + ETag with the authorisation order, the interactive worker).
  - #261: closes on lane 2 (S5; the pdflatex probe result; a real Illustrator figure noted as an optional extra check).
  - #274: closes on lanes 3a and 3b (the prune, `init_forms`, the agreement numbers).
  - #275: closes on lane 3b (file-object open, orientation after load, the contract pin, the depth-inferred scaling; the Pillow bug-report draft path).
  - #273: closes on lanes R and 2b; records S4 (encrypted: keep the rule, log `encrypted_objstm`), the deferred separator acceptance behind `objstm_separator`, and the Task 21 numbers (adopted or kept-colour-cap with the failing path); both reopen if the `encrypted_objstm` or `objstm_separator` log shows real refusals.
  - #269: the owner runs `PYTHONPATH=$PWD .venv/bin/python scripts/audit_stored_scan_pages.py` against each environment before deploy and pastes the histogram; the preview's one-page rule (S3) is in.
- [ ] List, in the same file, the owner-run steps: file the Pillow bug from the draft; run the audit; decide on the PR target (`develop`, rebased or retargeted once #237 merges).
- [ ] No repository changes in this task.

---

## Self-review notes

- Spec coverage: A (#262) Tasks 1-2; B (#276.2, #273.1-2) Tasks 3-5; C (#260, #249, #269 code) Tasks 6-12; D (#261) Task 13; E (#273.3) Tasks 21-22; F (#274) Tasks 14, 18; G (#275) Tasks 19-20; H (#276.1, #276.3, #269 audit) Tasks 15-17; closing table Task 25; gate and review Tasks 23-24.
- Names used across tasks: `lemely.io._scan_common` (constants, messages, errors, `PagePlan`, `looks_like_pdf`, `plan_page_dpi`, `plan_pdf_pages`, `REFUSAL_REASONS`, `_OBJECT_STREAM_SEPARATOR_MESSAGE`), `ChildWorker.call(target, *args, timeout, result_type)`, `ChildWorker.stream(target, *args, timeout, item_type)`, `sandbox.sandbox_settings()` (cached; always called through the module attribute), `EXTRACTION_WORKER`, `INTERACTIVE_WORKER`, `SandboxFailure(message, reason)` and its five subclasses (`SandboxUnavailable` also for an expired lock wait, `last_outcome == "busy"`), `RenderRefused(message, reason, fields=None)`, `render_preview_png(data)`, `crop_pdf_scan(data, page, box)`, `crop_image_scan(data, box)`, the public helpers `pdf_crop_plan`, `stored_frame_rect`, `upright_transpose`, `CROP_RENDER_DPI`, `MAX_CROP_PX`, `iter_scan_pages(scan_path, dpi)`, `SCAN_PAGES_TARGET`, `SCAN_CHECK_TARGET`, `PREVIEW_TARGET`, `CROP_PDF_TARGET`, `CROP_IMAGE_TARGET`, `sandbox_failure_to_http(exc, *, event, **fields)`, `ScanRejectedError(message, reason="unspecified")`, `preview_etag(row)`, `etag_matches(if_none_match, etag)`, `PREVIEW_RENDER_VERSION`, `tests.sandbox_fixtures.{in_process_sandbox, sandboxed}`, `tests.sandbox_targets.{pid, sleep_for, allocate, crash, reject, count_up, slow_count, record_window, record_window_from_env, peak_rss_of, lower_data_limit_then, lower_data_limit_then_stream, measure, rlimits, oom, boom, bilevel_pdf_paths}`, `tests.fakes_pdftex.pdftex_included_figure_pdf`, `tests.fakes_reader_agreement.{filled_text_field_pdf, oc_hidden_bomb_pdf, ocmd_image_pdf, dark_pixels, mupdf_grey, pdfium_grey, oriented_tiff, expected_upright, wide_grey_scan}`.
- Review findings folded in (2026-10-01 critic pass): leaf module `_scan_common` instead of lazy re-exports; patch retargeting table (finding 1); `RenderRefused` pickling (2); non-autouse in-process fixture plus end-to-end smoke tests (3); cached `sandbox_settings` (4); lock wait inside the timeout -> 503 (5); shared `tests/sandbox_fixtures.py` with shutdown on setup and teardown, cool-down cleared by `shutdown()` (6); out-of-memory asserted as recovery plus bounded parent RSS, limits lowered after import (7); admitted-image measurements (8); `test_web_review.py` import repointing (9); Task 9 commit paths and the empty check order (10); controller-owned wave-end type gates (11); `/OCMD` policies and `/BaseState` (12); `"F"` full scale 1.0 (13); the sweeps stay in `tests/test_scan_limits.py` (14); counts and names corrected: 49 raise sites, `test_the_committed_fixture_is_unaffected` exists at `tests/test_rasterise.py:564` and is cited with its line, `may_draw_forms` default (15); Task 21 after Task 18 (16); RFC 9110 `If-None-Match` and the 304-before-404 order (17).
