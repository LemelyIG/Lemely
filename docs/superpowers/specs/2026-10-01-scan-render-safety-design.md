# Scan and render safety: #260, #249, #261, #262, #269, #273, #274, #275, #276

Date: 2026-10-01. Status: approved design, owner decisions recorded below.

Branch `fix/scan-render-safety`, stacked on `feat/ai-improvements` at d66685b1 (PR #237, CI green). It opens its own PR into `develop` and is rebased or retargeted once #237 merges. A sibling branch, `fix/marking-accuracy` (`2026-10-01-marking-accuracy-design.md`), runs in parallel. The two share the memory budget in decision S1.

Line numbers refer to d66685b1. Library versions measured: pymupdf 1.28.0, pypdfium2 5.11.0, Pillow 12.2.0, pdfTeX 1.40.29.

## Goal

Every heavy operation on user PDF and image bytes runs in a killable, memory-limited child process, so a hostile or merely huge scan costs one 422 and never the web process. The marker sees the same pixels as the teacher. The remaining over-refusals get a stated policy and a logged reason. The 2,080-line `scan_limits.py` is split so this and later work can proceed in separate files.

## Evidence the design rests on (probes run 2026-10-01)

1. **#261 is real.**
   - pdfTeX copies an included page's `/PieceInfo` into the Form XObject it writes.
   - The walk's `_dict_refs` (`scan_limits.py:946`) follows every key except `/Resources`, so the private streams count as drawing data.
   - A shared form is re-counted on each page that draws it. As a result, 2 x 1 MB of private data on 40 pages is refused by the 64 MB scan cap.
2. **#274 is live in extraction.**
   - **Hidden layer:** for `hidden_layer_pdf(variant="image")`, MuPDF renders 1,986 dark pixels and pdfium renders 78,160, from both the canonical rewrite and the stored file.
   - **Filled text field:** MuPDF draws 1,578 dark pixels. pdfium without `init_forms` draws 0, and with `init_forms()` plus `render(may_draw_forms=True)` draws 1,635.
3. **#275 has a pinned cause.**
   - Pillow 12.2 applies TIFF orientation at load and swaps `size`. When an uncompressed single-strip TIFF is opened by path, the mmap fast path maps the stored layout at the swapped size, which scrambles the page.
   - Separately, the crop route reads the tag before load and re-applies an orientation Pillow has already applied. Extraction boxes the mark, and the crop of that box comes back blank.
4. **Child cost.**
   - A spawned child importing pymupdf, pypdfium2, Pillow and `lemely.io.rasterise` starts in 0.07-0.09 s, at 60 MB RSS and 131 MB address space.
   - Rendering the 16-page fixture at 200 dpi peaks at 181 MB RSS, 247 MB address space (VmPeak) and 94 MB VmData, and takes 4.5 s.
   - So an `RLIMIT_AS` alone must be set from VmPeak, not RSS.

## Owner decisions

| # | Issue | Decision |
|---|---|---|
| S1 | #260, #271 | `--memory=2Gi` in `deploy.yml` (from 1Gi). Two render workers: one for extraction and the upload check, one for preview and crop. Each child is limited with `RLIMIT_DATA` plus a looser `RLIMIT_AS` backstop. The equivalence parse worker keeps its 512 MiB `RLIMIT_AS` (marking spec D2). |
| S2 | #249 | The preview sends `Cache-Control: private, no-cache` with an `ETag`. The browser keeps the thumbnail but revalidates on every view, and the revalidation runs the full authorisation check. |
| S3 | #269 | The preview gets the crop's page rule: it renders one page, so it allows up to `MAX_CROP_PAGES` (200) instead of `MAX_SCAN_PAGES` (40). The stored-scan audit runs before deploy either way. |
| S4 | #273 item 1 | Encrypted scans keep the worst-case object-stream rule. Every such refusal logs reason `encrypted_objstm`. The follow-up, opening encrypted files only inside the worker, is taken only if the log shows real refusals. |
| S5 | #261 | Close on the fix plus a pdflatex-shaped synthetic fixture. A real Illustrator figure is noted on the issue as an optional extra check. |
| S6 | #273 item 3 | Bilevel and one-component grey images inside PDFs are judged against `decode_pixel_cap(mode)`, gated on a peak-RSS measurement inside the worker. If any render path exceeds the worker's limit, PDFs keep the colour cap and the measured number is recorded on the issue. |

### Memory budget at 2 GiB (resident, worst case)

| Component | Bound |
|---|---|
| Web process baseline | ~233 MB |
| Pages accumulated in the parent (adversarial 40-page scan) | up to ~441 MB of PNG |
| Extraction worker | `RLIMIT_DATA` 384 MiB, `RLIMIT_AS` 640 MiB (starting point) |
| Interactive worker (preview and crop) | `RLIMIT_DATA` 192 MiB, `RLIMIT_AS` 448 MiB (starting point) |
| Equivalence parse worker | ~75 MB resident, `RLIMIT_AS` 512 MiB |
| Sum of resident bounds | ~1.33 GB, under 2 GiB |

The implementer measures both worker numbers inside the child on the worst admitted scan: the 40-page, 160 Mpx shape from the Plan 4 review. The measured VmPeak, VmData and the chosen limits are recorded in `sandbox.py`'s module docstring, the way `equivalence.py` records its numbers. The starting points above are replaced by measured values, never guessed.

## Global constraints

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

## Design

### A. #262: split `scan_limits.py` (lane 0, first and alone)

A pure move into four modules. Every public name is re-exported from `lemely.io.scan_limits`, so no caller changes.

- **`lemely/io/scan_limits.py`** keeps:
  - the constants and the error types;
  - `PagePlan`, `plan_page_dpi`, `plan_pdf_pages`, `plan_image` and `decode_pixel_cap`;
  - the image allowlist and `open_scan_image`;
  - `check_scan_bytes`.
- **`lemely/io/pdf_prescan.py`:** the raw-bytes scanner, from `_WS` through `check_object_stream_bytes`, plus `_declares_encryption`, `PrescannedPdf` and `prescan_pdf`.
- **`lemely/io/pdf_content_walk.py`:**
  - `_ContentBudget`, `_PageTree` and `_PageWalk`;
  - the page-tree build, the resource walk, annotations and the image checks;
  - `_check_object_streams`, `check_pdf_content`, `_check_page` and `check_pdf_page_content`.
- **`lemely/io/pdf_canonical.py`:**
  - `open_checked_pdf`, `open_scan_image_document` and `_check_opened`;
  - `check_pdf_content_bytes`, `canonical_pdf_bytes` and `_copy_pages`;
  - `_pdfium_page_count` and `_pdfium_plan`.

The tests split the same way:
- **New test files:** `tests/test_pdf_prescan.py`, `tests/test_pdf_content_walk.py` and `tests/test_pdf_canonical.py`. The rest stays in `tests/test_scan_limits.py`.
- **Private-helper tests** are rewritten against `check_pdf_content_bytes` or `check_pdf_page_content` wherever the behaviour is observable there. Private pins stay only for orderings (the tree check before `seen`, the cap before the walk).

Two more changes ride along:
- **Labels.** Every "Fix round N" and "review round N" label in `tests/pdf_fakes.py` and the four test modules is replaced with what the fixture exercises. #265 is told these files are done.
- **AST sweeps.** `test_every_mupdf_open_of_user_bytes_goes_through_the_sanctioned_openers` and `test_only_prescan_pdf_makes_a_prescanned_pdf` update their allowed paths to the new modules. That is the one intended change in a sweep.

**Proof:**
- The existing suite stays green with no assertion changed, apart from the moved private pins.
- One test asserts every name in `scan_limits.__all__` still imports from `lemely.io.scan_limits`. Lane 0 adds `__all__` if it is absent.

### B. #276 item 2: refusal reason codes (lane R, right after lane 0)

- **Error types.** `ScanRejectedError(message, reason="unspecified")` and its subclasses store `reason` in `args`, so it survives pickling across the sandbox pipe.
- **Raise sites.** Every raise site in the io modules passes a short code, for example: `page_cap`, `crop_page_cap`, `objstm_bomb`, `objstm_encoding`, `objstm_separator`, `encrypted_objstm`, `too_many_objects`, `prescan_tokens`, `page_content`, `scan_content`, `image_px`, `page_px`, `scan_px`, `format_not_allowed`, `webp_px`, `page_tree`, `reader_disagreement`, `malformed`, `uncheckable`. The implementer lists the final set in the module docstring.
- **Logging.** `_log_refusal` (`lemely/web/upload_utils.py:48`) logs `reason=exc.reason` beside the class. User-facing messages are unchanged.
- **#273 item 2 rides here.** Tab, NUL and form-feed separators get a specific message ("This PDF separates its data with characters the checker does not accept. Re-export it as a plain scan.") and reason `objstm_separator`. Accepting those separators is deferred until the log shows they occur.
- **#273 item 1 rides here too.** The encrypted worst-case refusal carries `encrypted_objstm` (S4).

**Tests:**
- An AST sweep that no `raise Scan...Error(` in `lemely/io` uses the default reason. Red until every site is done.
- The log line carries the reason.
- A pickle round trip keeps both the message and the reason.
- A separator fixture asserts the new message and code.

### C. #260 and #249: the sandbox (lane 1)

**Worker module `lemely/runtime/sandbox.py`.** It generalises the `_ParseWorker` pattern (`lemely/core/equivalence.py:971`) without touching `_ParseWorker`.

- **`ChildWorker`.** Each instance holds one spawned child, started lazily.
- **Calls.** `call(target, *args, timeout)` takes `target`, a dotted name of a module-level function in a pure `lemely/io` module. The child never imports the web app or anything needing a database.
- **Child set-up.** The child sets `RLIMIT_DATA` and `RLIMIT_AS` at start and ignores SIGINT.
- **Replies.** The child answers `("ok", value)`, `("rejected", ScanRejectedError)` with its reason preserved, `("memory", None)`, `("crash", ...)` or `("error", repr)`.
- **Failure handling.** The parent kills the child on timeout and respawns it on the next call. Failures raise typed `SandboxFailure` subclasses, all `LemelyError`s: `SandboxTimeout`, `SandboxMemory`, `SandboxCrash` and `SandboxUnavailable`.
- **pdfium's out-of-memory abort** surfaces as `SandboxCrash` (test it with an artificially low limit).
- **Two module-level instances (S1).** `EXTRACTION_WORKER` serves extraction and the upload check; `INTERACTIVE_WORKER` serves preview and crop. Each serialises its calls, and that serialisation is the concurrency cap. There is no `--concurrency` change, because an SSE grading stream holds a request slot for minutes.
- **Settings.** A `SandboxSettings` block in `lemely/runtime/config.py` carries the per-worker memory bytes, the timeouts, and an `enabled` flag for the few tests that need the in-process path.

**Call sites move, logic does not:**
- **Extraction.**
  - `rasterise.rasterise_scan_to_pages(path)` becomes a parent-side wrapper. It calls `EXTRACTION_WORKER` with a child-side function that streams pages back one at a time, so the child never holds every PNG.
  - The timeout is set from a measurement of the worst admitted scan. The 16-page fixture takes 4.5 s.
- **Upload check.** `upload_utils.check_scan_geometry` calls `EXTRACTION_WORKER` with `check_scan_bytes`. The timeout is 20 s: the name-flood pre-scan takes 1-2 s, and a 1M-key `/Info` takes 11 s.
- **Preview and crop.**
  - `teacher._render_preview_png` and `review._crop_pdf_scan` / `_crop_image_scan` move to a new pure module, `lemely/io/scan_render.py`, as `render_preview_png(data) -> bytes`, `crop_pdf_scan(data, page, box) -> bytes` and `crop_image_scan(data, box) -> bytes`.
  - Refusals raise `ScanRejectedError` or a new `RenderRefused(LemelyError)` for "no pages" and "page too large to render".
  - They run on `INTERACTIVE_WORKER`, with timeouts of 10 s for the crop and 15 s for the preview.
- **HTTP mapping.** The routers keep the HTTP mapping and logging:
  - `SandboxFailure` maps to 422 with a fixed message, logged with the typed reason.
  - `SandboxUnavailable` maps to 503.
- **Instance memory.** `.github/workflows/deploy.yml` sets `--memory=2Gi`. `docs/ci-cd.md` records the budget table above.

**#249 preview residuals (in `teacher.py`):**
- **Error text.** The fixed message "Could not render this scan" replaces `detail=f"Could not render this scan: {exc}"` (`:1141`). The exception stays in the `paper_preview_failed` log line.
- **Caching (S2).** The preview sends `Cache-Control: private, no-cache` and an `ETag`.
  - **ETag contents.** The ETag is derived from the paper's id, its stored object's identity (the storage path, if the implementer confirms it is immutable per paper; otherwise a content hash recorded at upload) and a `PREVIEW_RENDER_VERSION` constant.
  - **Order of checks.** On `If-None-Match` the route first performs the same authorisation as a full request, then answers 304 without downloading or rendering.
  - **Unauthorised callers.** A request that fails authorisation gets the same 403 or 404 as today, even with a matching ETag.

**#269 code half (in `teacher.py`, decision S3):** the preview calls `check_pdf_page_content(doc, 0)`, the crop's one-page rule, instead of `check_pdf_content(doc)`.

**Tests (red before):**
- **`tests/test_sandbox.py`:**
  - A target allocating past the limit returns memory, and the next call succeeds.
  - A sleeping target is killed on timeout, and the pid changes.
  - A `ScanRejectedError` arrives with its message and reason.
  - A crash respawns the child.
  - The two workers are distinct processes.
- **`tests/test_rasterise.py`:**
  - Extraction of the committed fixture runs in the worker's pid.
  - A render forced past the limit raises instead of growing the test process. Assert the RSS delta stays bounded.
- **`tests/test_web_teacher.py`:**
  - A refused render gives 422 with the fixed message.
  - `test_preview_never_echoes_renderer_text`.
  - The ETag round trip: the first request returns 200 with an ETag; a repeat with `If-None-Match` returns 304 with no render call; a different teacher with the same ETag gets 403 or 404.
  - Invert `test_preview_still_refuses_a_stored_scan_over_the_page_cap` (`:860`) into `test_preview_serves_page_one_of_a_stored_scan_over_the_page_cap`.
  - Add `test_preview_refuses_a_stored_scan_over_max_crop_pages`.
- **`tests/test_web_review.py`:**
  - A refused crop gives 422.
  - Two concurrent crops are served one after another, recorded by an overlap-detecting child target.
- **`tests/test_upload_utils.py`:** the upload check runs in the worker.

### D. #261: skip private-data keys in the walk (lane 2)

- **The skip.** `_dict_refs` in `pdf_content_walk.py` does not follow exactly two keys: `/PieceInfo` and `/Metadata`. ISO 32000 defines both as not rendered, and neither reader dereferences them to draw.
- **Shared objects stay counted.** The skip is on the edge, not the object, so an object also reachable through a drawn key is still counted there.
- **The rewrite's `_copy_pages`** still grafts `/PieceInfo` as compressed bytes, bounded by the upload cap.

**Tests:**
- **New fixture.** `tests/fakes_pdftex.py::pdftex_included_figure_pdf(private_bytes, pages)` is built the way pdfTeX writes it: a Form XObject carrying `/PieceInfo` whose `/Private` dictionary names two Flate streams, drawn from every page. The payload is highly compressible, so the fixture is a few KB.
- **Pass after the fix.** `check_scan_bytes` passes the fixture after the fix and refuses it before.
- **No loss of coverage.** A form reachable both as `/XObject` and through `/PieceInfo` with a bomb stream is still refused.
- **Fidelity.** A form whose `/PieceInfo` names the page tree is accepted and renders identically in both readers.

The implementer also rebuilds the probe with the host's pdflatex and records the result in the task report. That build is not committed.

### E. #273 item 3: per-mode caps for images inside PDFs (lane 2, after lane 1, decision S6)

- **Mode.** Derive a mode from the image dictionary:
  - `/ImageMask true` or `/BitsPerComponent 1` gives "1";
  - a one-component colour space (`/DeviceGray`, `/CalGray`, `/ICCBased` with `/N 1`) gives "L" at 8 bits and "I;16" at 16 bits;
  - anything else, `/Indexed` included, is colour.
- **The check.** Judge declared pixels against `decode_pixel_cap(mode)`, both in `_check_declared_pixels` and `_check_image_and_masks`.
- **Gate.** Before merging, measure peak RSS inside `EXTRACTION_WORKER` and `INTERACTIVE_WORKER` for a PDF wrapping a 160 Mpx bilevel image, on three paths:
  - the pdfium render at the planned dpi;
  - the MuPDF crop clip;
  - the MuPDF preview zoom.

  If any path exceeds its worker's limit, PDFs keep the colour cap and the number is recorded on #273 instead.

**Tests:**
- A 100 Mpx 1-bit image wrapped in a PDF passes after the change and is refused before.
- 100 Mpx `/DeviceRGB` and `/Indexed` images are still refused.

### F. #274: one picture for marker and teacher (lane 3)

- **Hidden optional content**, in `pdf_canonical._copy_pages` after `insert_pdf`:
  - Remove each copied page's `/Resources /XObject` entries and `/Annots` whose `/OC` resolves to a group in `/OCProperties /D /OFF`, either directly or through an `/OCMD` with `/OCGs`.
  - Content streams are not rewritten, because pdfium already honours marked content.
  - The prune runs on the copy, after the walk has bounded the original, and must not load pages.
- **Forms**, in `rasterise_pdf_to_pages`: call `pdf.init_forms()` after opening the canonical bytes, and `page.render(..., may_draw_forms=True)`. This lands after lane 1, so `init_forms` runs inside the worker.

**Tests:**
- **Hidden layer.** For `hidden_layer_pdf(variant="image")`, the page-1 extraction render and a MuPDF render of the stored file agree within the tolerance the `text` variant already meets. Red today.
- **Filled field.** The same check for a new `filled_text_field_pdf()` in `tests/fakes_reader_agreement.py`. Red today.
- **Inverse assertion.** Under pdfium, the hidden image is now absent from the rewrite.
- **Bombs still caught.** An `/OC`-hidden content bomb is still refused by the walk.
- **No regressions.** All 26 committed PDFs still render pixel-identical through the rewrite.

### G. #275: images (lane 3, after lane 1)

1. **TIFF orientation.**
   - `_rasterise_single_image` opens the image from a file object, never a path, so Pillow never memory-maps the file. Extraction relies on Pillow turning TIFFs upright at load, and `exif_transpose` still handles JPEG and PNG.
   - The crop in `scan_render.crop_image_scan` reads the orientation after `load()`. A TIFF then has no tag to re-apply.
   - A contract test pins that a TIFF with orientation 6, opened through `open_scan_image`, is upright after `load()` and has no orientation tag. If a Pillow upgrade changes this, the test goes red instead of pages going sideways.
   - The `map_buffer(self.size)` bug is filed with Pillow.
2. **Wide grey scaling.**
   - `_wide_grey_to_l` scales by the inferred container depth, not the extrema, which would stretch contrast. The depth is the smallest of 8, 10, 12, 14 or 16 bits (up to 32 for "I") whose full-scale value is at least the maximum sample.
   - A genuine 16-bit scan is unchanged.
   - For "F", a maximum at or below 1.0 means normalised floats, scaled by 255. Otherwise "F" is treated like "I".
   - A flat image maps to white.
   - The conversion stays strip-wise and linear.

**Tests (red before):**
- **Uncompressed oriented TIFF:** an uncompressed single-strip TIFF with orientation 6, in L and I;16, comes out upright.
- **Crop vs extraction:** the crop route agrees with extraction for oriented TIFFs, uncompressed and LZW.
- **Contract pin:** the Pillow contract test above.
- **12-bit-in-16:** paper 4000 and ink 200 give "L" 249 and 12.
- **8-bit-in-16 and flat images:** both handled.
- **Float TIFF:** paper 0.95 and ink 0.05 give 242 and 13.

New builders go in `tests/fakes_reader_agreement.py`.

### H. #276 items 1 and 3, and the #269 audit (lane 4)

1. **MuPDF-open sweep.**
   - Move it into `tests/mupdf_sweep.py`, resolving bindings per module first: `import pymupdf [as x]`, `import fitz [as x]`, `from pymupdf import open/Document [as y]`, and the assignments `z = pymupdf` and `z = pymupdf.open`.
   - Flag calls through any of those bindings, plus any `.insert_pdf(` or `.insert_file(` outside `pdf_canonical._copy_pages`.
   - Self-tests feed each evasion as a source string and assert the flag.
   - Document what the sweep cannot see (`getattr`, `importlib`).
   - `tests/test_scan_limits.py` calls the shared function.
2. **Mark-scheme pickers.**
   - Add `SCHEME_ACCEPT = "application/pdf"` in `web/src/lib/scanAccept.ts`, used on the scheme inputs in `CorrectPaper.tsx:852` and `Grading.tsx:708`.
   - `web/tests/unit/scanAccept.test.ts` pins accepts by input id: `scheme-file` and `grading-scheme-file` get `SCHEME_ACCEPT`, and every other input gets `SCAN_ACCEPT`.
3. **The #269 audit script.**
   - `scripts/audit_stored_scan_pages.py` reads `uploads.storage_path` and `teacher_papers.storage_path` through the repos. It downloads each object through `StorageBackend.download`.
   - It counts pages with pdfium only: `len(PdfDocument(data))`, with no render and no MuPDF open.
   - It prints a histogram (over 40, over 200, by table, bytes downloaded) and supports `--sample N`.
   - It is unit-tested against the fake storage backend. The owner runs it before deploy and pastes the result into #269.

## Work breakdown and order

| Wave | Lane | Issues | Owns |
|---|---|---|---|
| 1 | 0 | #262 | `lemely/io/scan_limits.py`, new `pdf_prescan.py`, `pdf_content_walk.py`, `pdf_canonical.py`; `tests/test_scan_limits.py` and the three new test modules; `tests/pdf_fakes.py` |
| 2 | R | #276.2, #273.1-2 | raise sites in the four io modules and `lemely/io/rasterise.py`; `lemely/web/upload_utils.py`; `tests/test_upload_utils.py`; a new `tests/test_refusal_reasons.py` |
| 3 | 1 | #260, #249, #269 code | new `lemely/runtime/sandbox.py`, `lemely/io/scan_render.py`, their tests; `lemely/io/rasterise.py`; `lemely/web/upload_utils.py`; `lemely/web/routers/teacher.py`; `lemely/web/routers/review.py`; `lemely/runtime/config.py`; `.github/workflows/deploy.yml`; `docs/ci-cd.md`; `tests/test_rasterise.py`, `tests/test_web_teacher.py`, `tests/test_web_review.py`, `tests/test_upload_utils.py` |
| 3 | 2 | #261 | `lemely/io/pdf_content_walk.py`, `tests/test_pdf_content_walk.py`, new `tests/fakes_pdftex.py` |
| 3 | 3a | #274 hidden content | `lemely/io/pdf_canonical.py`, `tests/test_pdf_canonical.py`, new `tests/fakes_reader_agreement.py` |
| 3 | 4 | #276.1, #276.3, #269 audit | `tests/mupdf_sweep.py`, `tests/test_mupdf_sweep.py`, the sweep call in `tests/test_scan_limits.py`, `web/src/lib/scanAccept.ts`, the two screens, `web/tests/unit/scanAccept.test.ts`, new `scripts/audit_stored_scan_pages.py` and its test |
| 4 | 3b | #274 forms, #275 | `lemely/io/rasterise.py`, `lemely/io/scan_render.py` (crop orientation), `tests/test_rasterise.py`, `tests/test_scan_render.py`, `tests/fakes_reader_agreement.py` |
| 4 | 2b | #273.3 | `lemely/io/pdf_content_walk.py`, `tests/test_pdf_content_walk.py` |

Ordering rules:
- **Wave 1 runs alone.** Waves 2 and 3 start only once lane 0 is green.
- **Lane R runs alone.** It touches every io module's raise sites, so it lands before wave 3.
- **Wave 3 is four lanes in parallel.** Lane 4 has no dependencies and may start with lane R.
- **Wave 4 follows lane 1**, which owns `rasterise.py`, `scan_render.py` and the workers. Lane 3b needs those files free, and lane 2b measures inside the workers.
- **Review.** Each task is reviewed at its SHA. The gate sweep, using commands derived from `.github/workflows/ci.yml`, runs on the final tree. A whole-branch opus review runs at the end.

## Closing the issues

| Issue | Closes when |
|---|---|
| #262 | lane 0 lands |
| #276 | lanes R and 4 land |
| #260 | lane 1 lands. The four comment residuals are bounded by the worker: open, walk and pre-scan all run inside it. The closing comment says so. |
| #249 | lane 1 lands |
| #261 | lane 2 lands (S5) |
| #274 | lanes 3a and 3b land |
| #275 | lane 3b lands |
| #273 | lanes R and 2b land. The closing comment records S4 (encrypted: keep the rule and log it) and the deferred separator acceptance. Both are reopened if the `encrypted_objstm` or `objstm_separator` log shows real refusals. |
| #269 | the audit has run before deploy and its result is on the issue |

## Risks

- **The parent still holds every page's PNG,** up to about 441 MB on the adversarial scan, and sends them to Gemini from there. Streaming pages instead is a product change and out of scope. It is noted on #260.
- **The rlimits bound each child; the container bounds the sum.** If they are exceeded together, the kernel's OOM killer picks the largest process. The 2 GiB budget table is what makes the arithmetic hold.
- **Spawn re-imports `lemely.io`.** Child targets must live in pure modules. The shared-venv `.pth` note applies: the child inherits `sys.path`.
- **The TIFF fix depends on Pillow-version behaviour.** The contract test exists to catch a change.
- **The `/OC` prune touches the rewrite.** All 26 committed PDFs must still render pixel-identical.
- **#273 item 3 may fail its measurement.** If it does, the number is recorded and the cap stays.

## Out of scope

- `--concurrency` on Cloud Run.
- Streaming pages to Gemini.
- Accepting tab, NUL and form-feed separators.
- Decrypting encrypted scans.
- Rebasing `_ParseWorker` onto `ChildWorker`, or any other `equivalence.py` change. The marking branch owns that file.
- "Fix round" labels outside the files lane 0 owns (#265).
- The e2e, seed and review-surface issues.
