# L6 Upload, Camera and Processing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the student and teacher "get a paper in" flow (camera, upload, sending, marking progress) with the approved `upload-r1/final.html` design, backed by persisted per-question marking progress over SSE with a polling fallback, a paper check before marking, a server-side PDF and saved crops.

**Architecture:** The backend gains one table (`marking_progress`) that a bus subscriber fills while a run marks, so any Cloud Run instance can answer `GET /api/marking/{id}/progress` and stream `GET /api/marking/{id}/events` (a DB-polling SSE with heartbeats and a 240 s reconnect). The student run keeps `POST /student/correct` as the request that drives marking (it holds CPU on Cloud Run) and the screen reads progress from the events stream. The frontend gets a typed data layer (`markingApi.ts`, `useMarkingApi.ts`, `progressStream.ts`), pure view models (`lib/marking/viewModel.ts`, `lib/scan/*`), and thin screens in `components/scan/` composed by the student `CorrectPaper.tsx` / `MarkingPaper.tsx` routes and a new teacher `MarkPapers.tsx` route.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, pytest (real Postgres), React 19, react-router 7, TanStack Query, Tailwind 4, Vitest (node env, view models only), Playwright, pdf-lib, Pillow.

**Spec:** `docs/superpowers/specs/2026-11-14-redesign-implementation-design.md` (group "Upload, camera, processing"). **Master plan:** `docs/superpowers/plans/2026-11-15-redesign-00-master.md`. **Mock:** `.impeccable/mocks/upload-r1/final.html` + `up.css` + `base.css`.

## Global Constraints

Inherits master plan Global Constraints (signed commits with explicit paths, touched-tests only, PRs to `develop`, no token changes, migrations with downgrade and user approval before a shared DB, PortalShell wins, fidelity at 390/tablet/1280 with reduced motion, Binny rules, Mono numbers, short copy, cost under $0.10/paper, auth via `lemely/web/deps.py`).

Lane-specific:
- **Desktop never gets a camera.** Camera UI renders only when `(pointer: coarse)` matches. No "Use camera" button anywhere on a fine pointer.
- **No invented progress.** Every count and tile comes from the server's persisted progress. The only estimate is the ETA, worded "about N min left", shown only after 2 questions are marked (S-14 rule, `components/ui/processing-state.tsx:8-17`).
- **Recovery never re-POSTs `/student/correct` on its own** (double Gemini spend). Only an explicit "Start marking again" tap does.
- **One drain of the offline queue per tab.** The drain guard is module-level, not per hook instance.
- **SSE through Cloudflare Worker + Cloud Run:** every SSE response carries `Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no`, sends `: ping` at least every 15 s (Cloudflare drops a response idle 100 s), and the progress stream closes itself at 240 s (Cloud Run `--timeout=300`, `.github/workflows/deploy.yml:374`) with a `reconnect` frame.
- **Cost:** the paper check's detection call and the marking run log under the same `script_cost_scope` key `upload:{paperId}`, and `/student/correct` skips detection when the check already stored the metadata, so the number of model calls per paper does not grow.
- **L12 interfaces (exact exports, do not rename):**
  1. **Pure per-question tile state:** `tileStateFor(q: TileQuestion, ctx: { isCurrent: boolean }): BoardTileState` and `groupTiles(questions, { running })` in `web/src/lib/marking/viewModel.ts`. `BoardTileState = "waiting" | "now" | "done" | "blank" | "missing" | "stopped"`; notes `"Marking"`, `"Blank"`, `"Page missing"`, `"Stopped"`. Blank is driven only by the optional `q.blank === true`.
  2. **Per-question progress DTO:** backend `TileQuestionDTO` in `lemely/web/schemas_marking.py` (`id`, `state`, `blank: bool | None = None`) and TS `TileQuestion` in `web/src/lib/markingTypes.ts` (`id`, `state`, `blank?: boolean | null`). The repo seam for writing it is `MarkingProgressRepository.mark_question(paper_id, question_id, *, blank: bool | None = None)` and `MarkingProgressRepository.set_missing(paper_id, *, pages, question_ids)`. L6 always writes `blank=None`; L12 passes the model's flag. (`marker_source == "blank"` already exists on `MARKING_PROGRESS` frames, `lemely/io/correction_ai.py:2351`, as a starting point for L12.)
  3. **Recent uploads list that takes extra rows:** `RecentUploads({ rows, extraRows?, ... })` and `type RecentRow` and pure `recentRowFromUpload(upload)` in `web/src/components/scan/RecentUploads.tsx` / `web/src/lib/marking/viewModel.ts`. L12 passes class-set rows as `extraRows` (rendered first). The teacher DTO also carries `namesNeedYou: int | None` (L6 always `None`).
  L6 renders Blank, Page missing and names-need-you only when the data is present and never fabricates it.
- **Migration numbering:** L6's migration is `0056_marking_progress` (`down_revision = "0054_waitlist_email_confirmation"`), because L12 holds `0055_class_sets`. Whichever lane merges second rebases its `down_revision` onto the `develop` head (master plan shared-file rule). L6 merges first, so L12 sets its `down_revision` to `0056_marking_progress` and renames nothing.
- Grep note for workers: the tokensave index serves another branch; set `TOKENSAVE_DISABLE_GREP_HOOK=1` for greps in this worktree, or use `graphify query`.

---

## File structure

Backend (create):
- `lemely/db/migrations/versions/0056_marking_progress.py` — table + three columns.
- `lemely/db/models/marking.py` — `MarkingProgress` ORM.
- `lemely/db/marking_progress_repo.py` — `MarkingProgressRepository`, `ProgressSnapshot`.
- `lemely/web/services/marking_progress.py` — `ProgressRecorder`, `estimate_eta_seconds`, `build_progress_dto`, `progress_event_stream`, `scan_bytes_as_pdf`, `recent_upload_dto`, `get_marking_progress_repo`.
- `lemely/web/schemas_marking.py` — DTOs.
- `lemely/web/routers/marking.py` — progress, events, pdf, detect, choose paper, teacher recent.
- Tests: `tests/marking_fixtures.py`, `tests/test_migration_marking_progress.py`, `tests/test_marking_progress_repo.py`, `tests/test_marking_recorder.py`, `tests/test_sse_heartbeat.py`, `tests/test_marking_routes.py`, `tests/test_marking_detect.py`, `tests/test_marking_pdf.py`, `tests/test_teacher_recent_uploads.py`.

Backend (modify, narrow): `lemely/db/models/__init__.py`, `lemely/db/models/attempts.py` (Upload columns), `lemely/db/models/teacher_papers.py` (column), `lemely/db/upload_repo.py`, `lemely/db/teacher_paper_repo.py`, `lemely/web/sse.py`, `lemely/web/routers/student.py` (`student_upload`, `student_correct`), `lemely/web/routers/teacher.py` (`upload_paper`, `NO_SCHEME_MESSAGE`), `lemely/web/app.py` (one include), `tests/test_student_correct.py` (one override).

Frontend (create):
- `web/src/lib/markingTypes.ts`, `web/src/lib/markingApi.ts`, `web/src/lib/hooks/useMarkingApi.ts`
- `web/src/lib/marking/progressStream.ts`, `web/src/lib/marking/viewModel.ts`
- `web/src/lib/scan/pageQuality.ts`, `cropMath.ts`, `captureModel.ts`, `entryMode.ts`, `flowMachine.ts`, `queueCopy.ts`
- `web/src/components/scan/` — `ScannerCamera.tsx`, `CameraStateScreen.tsx`, `PageStack.tsx`, `PagesReview.tsx`, `FixCrop.tsx`, `UploadSheet.tsx`, `CheckPaper.tsx`, `ChangePaperSheet.tsx`, `SharedFile.tsx`, `AppBar.tsx`, `InlineAlert.tsx`, `MarkingBoard.tsx`, `MarkingStates.tsx`, `QueuedUploadsBanner.tsx`, `DropVeil.tsx`, `DropZone.tsx`, `ReceivedFiles.tsx`, `RecentUploads.tsx`, `scanIcons.tsx`, `downloadBlob.ts`
- `web/src/portals/student/screens/MarkingPaper.tsx`, `web/src/portals/teacher/screens/upload/MarkPapers.tsx`
- Tests: `web/tests/unit/markingApiShape.test.ts`, `progressStream.test.ts`, `markingViewModel.test.ts`, `pageQuality.test.ts`, `cropMath.test.ts`, `captureModel.test.ts`, `entryMode.test.ts`, `scanFlow.test.ts`, `queueCopy.test.ts`; `web/e2e/upload-student.spec.ts`, `web/e2e/upload-teacher.spec.ts`

Frontend (modify): `portals/student/screens/CorrectPaper.tsx` (rewritten, thin), `portals/student/index.tsx` (route), `portals/teacher/index.tsx` (route + two links + nav), `portals/student/shell.tsx` (one banner line), `lib/offline/uploadQueue.ts`, `lib/offline/useUploadQueue.ts`, `lib/scanInboxDestination.ts`, `portals/teacher/home/TeacherHome.tsx`, `portals/teacher/home/growth.ts`, `lib/nav/scrollRestorationKey.ts`, `portals/teacher/screens/Grading.tsx` (remove camera block only, see Needs user decision 1).

Deleted at the end (Task 24): `components/CameraCapture.tsx`, `components/ui/queued-banner.tsx`, `lib/cameraAutoStart.ts`, `lib/scanSource.ts` and their tests; `components/ui/processing-state.tsx` only if `Grading.tsx` no longer imports it. `components/ui/file-drop.tsx` stays (tutoring uses it).

---

## Keep-list (every live feature, state, error and edge case)

Each item is ticked in the PR body by Task 23. "New home" names where it lives after L6.

| # | Live feature | Source | New home |
|---|---|---|---|
| K1 | Phone defaults to camera, desktop to file (`(pointer: coarse)`) | `lib/scanSource.ts:1-4`, `CorrectPaper.tsx:362-364` | `lib/scan/entryMode.ts` |
| K2 | Camera never acquired on mount without a tap (autoStart only after a deliberate choice) | `lib/cameraAutoStart.ts`, `CorrectPaper.tsx:840` | `ScannerCamera` `autoStart` + `CameraStateScreen` "Turn on camera" |
| K3 | Camera errors named per DOMException (denied, not found, in use, HTTPS, aborted, other) and "no getUserMedia" | `CameraCapture.tsx:80-106`, `:224-229` | `lib/scan/entryMode.ts` `describeCameraError` → `CameraStateScreen` titles |
| K4 | "Starting camera…" while acquiring | `CameraCapture.tsx:526-529` | `ScannerCamera` starting state |
| K5 | Try again re-acquires the camera | `CameraCapture.tsx:571-577` | `CameraStateScreen` blocked → Try again |
| K6 | Rear camera `facingMode: environment`, tracks stopped on unmount/cancel | `CameraCapture.tsx:236-259` | `ScannerCamera` |
| K7 | Screen wake lock while live | `CameraCapture.tsx:197` | `ScannerCamera` |
| K8 | Live document quad overlay | `CameraCapture.tsx:114-150`, `:536-553` | `ScannerCamera` quad SVG |
| K9 | Auto-capture on stability (3 calm frames, delta ≤ 2.5) and re-arm after each page | `CameraCapture.tsx:316-391`, `lib/scanner/stability.ts` | `ScannerCamera` + "Auto" toggle |
| K10 | Manual capture | `CameraCapture.tsx:579-587` | shutter button |
| K11 | Perspective correction on capture, falls back to raw frame on failure | `CameraCapture.tsx:272-292` | `ScannerCamera.capture` |
| K12 | Torch when supported, `aria-pressed` | `CameraCapture.tsx:393-400`, `:554-568` | top bar torch button |
| K13 | Remove a captured page, object URLs revoked | `CameraCapture.tsx:402-408`, `:209-213` | FixCrop Delete, unmount cleanup |
| K14 | Review pages before finishing; add another page | `CameraCapture.tsx:410-414`, `:617-626` | `PagesReview` + Add page tile |
| K15 | Assemble pages into one PDF; specific failure copy | `CameraCapture.tsx:416-441` | `assemblePagesToPdf` in `CorrectPaper` send; copy kept |
| K16 | Landscape hint on coarse pointers | `CameraCapture.tsx:505-510` | landscape overlay, auto-capture paused |
| K17 | Cancel leaves the camera | `CameraCapture.tsx:589-592` | top bar Close |
| K18 | Multiple photos chosen at once are joined into one PDF; PDF + photos mixed is refused with copy | `CorrectPaper.tsx:440-466` | `UploadSheet` → `PagesReview`; mixed-files inline alert |
| K19 | Optional own mark scheme upload (PDF) with the "leave blank" hint | `CorrectPaper.tsx:853-864` | `UploadSheet` third option; desktop "Add your own mark scheme" |
| K20 | Shared/launched scan (share target + File Handling) read once, 10 min TTL | `CorrectPaper.tsx:496-512`, `lib/sharedScan.ts:10-41` | `SharedFile` screen; teacher drop list |
| K21 | Reload guard while a scan is unsubmitted | `CorrectPaper.tsx:530-533`, `components/UpdateToast.tsx:46` | `CorrectPaper` + `MarkPapers` effects |
| K22 | Real upload progress from XHR bytes | `CorrectPaper.tsx:645-652`, `lib/uploadProgress.ts` | Sending state (`62%`, "4.1 of 6.6 MB") |
| K23 | Offline: status-0 failure queues the upload (IndexedDB), idempotency key, auto drain on `online`/SW sync, 24 h / 5 attempts cap | `CorrectPaper.tsx:665-676`, `lib/offline/*`, `sw.ts:146` | Offline · saved state, `QueuedUploadsBanner` app-wide |
| K24 | Signing out clears the queue | `lib/auth/storage.ts:175` | unchanged |
| K25 | Queued count banner with Retry now | `components/ui/queued-banner.tsx` | `QueuedUploadsBanner` ("1 paper waiting to send" + Try now) |
| K26 | Live SSE stages, frame details, per-question counter | `CorrectPaper.tsx:542-605`, `lib/pipelineStages.ts` | live POST stream drives `pipelineStages` sr-only announcer; board from persisted progress |
| K27 | `warning`/`error` frames stop the run with the server's message | `CorrectPaper.tsx:543-550` | stopped state message |
| K28 | Stream closed without a result is a failure, not "ready" | `CorrectPaper.tsx:603-604`, `lib/correctionOutcome.ts` | now: keep following persisted progress; only a terminal status ends it |
| K29 | Complete frame builds the result and navigates with `location.state` (no second GET) | `CorrectPaper.tsx:565-596` | `MarkingPaper` keeps `assembleResult` |
| K30 | Retry in place after failure re-marks the stored scan ("Start marking again"); "Try again" re-sends when nothing was sent, with the two notes | `CorrectPaper.tsx:609-625`, `:719`, `:968-985` | Marking stopped (sent / not sent variants) |
| K31 | AbortError resets quietly | `CorrectPaper.tsx:705-708` | `MarkingPaper` stream effect |
| K32 | Failure copy via `correctionFailureMessage` (email unverified, detail, 5xx, network) | `lib/correctionOutcome.ts` | stopped/send-failed messages |
| K33 | Email-verification soft gate: marking button disabled when unverified | `CorrectPaper.tsx:735-742`, `lib/uploadRun.ts` | `CheckPaper` "Yes, mark it" disabled + inline note |
| K34 | Recover a run in flight on mount (`/student/uploads/active`), poll it, never re-POST | `CorrectPaper.tsx:385-417` | `CorrectPaper` redirects to `/student/correct/:paperId`; came-back state |
| K35 | Stale/failed recovered run offers Start marking again | `CorrectPaper.tsx:316-338` | stopped state |
| K36 | Recovered run that completes navigates to its result | `CorrectPaper.tsx:413-417` | `MarkingPaper` on `complete` |
| K37 | Failed active-run check shows a compact error with Try again above a working upload form | `CorrectPaper.tsx:910-917` | "Couldn't check status" alert above start |
| K38 | "How this gets marked" reassurance list | `CorrectPaper.tsx:990-1010`, `portals/student/data.ts:300` | dropped from this screen (mock has none). Needs user decision 6 |
| K39 | Teacher: one-scan upload with optional scheme, upload stage error copy (`teacherMutationFailureMessage`) | `Grading.tsx:443-470`, `:750-770` | `MarkPapers` drop zone, multi-file |
| K40 | Teacher: files handed over from teacher home via router state, cleared after read | `Grading.tsx:400-412`, `TeacherHome.tsx:16` | `MarkPapers` reads `state.files` (all files, not one) |
| K41 | Teacher: shared scan read on mount | `Grading.tsx:361-375` | `MarkPapers` |
| K42 | Teacher: "Marking runs on the server" leave-safe note | `Grading.tsx:779-781` | received-files note |
| K43 | Teacher: failed run → Try again (regrade) with its own error | `Grading.tsx:645-660` | recent row "Marking stopped · Start again" |
| K44 | Teacher camera on phone | `Grading.tsx:676-700` | teacher phone camera flow; desktop has none |
| K45 | Accept list PDF/JPEG/PNG/TIFF/WEBP/BMP; scheme PDF only; 25 MB cap | `lib/scanAccept.ts`, `upload_utils.py:33` | `DropZone`/`UploadSheet` + skipped files |
| K46 | Upload idempotency (`Idempotency-Key`) | `routers/student.py:649-740` | unchanged; offline replays still send it |
| K47 | Scan geometry check 422 and 413 cap messages | `routers/student.py:690-692` | send-failed message via `correctionFailureMessage` |
| K48 | Notifications `grade_ready`, XP, at-risk alerts after marking | `routers/student.py:1150-1198` | unchanged backend |
| K49 | Scroll restoration keys for the tab routes | `lib/nav/scrollRestorationKey.ts:30-34` | add `/teacher/upload` |
| K50 | Scan inbox routes each role to its upload surface | `lib/scanInboxDestination.ts:30-32` | teacher → `/teacher/upload` |
| K51 | Prefetch on intent for the correct route | `portals/student/shell.tsx:140` | unchanged (`loadCorrectPaper` still exported) |

## Frame-to-state table

| Mock frame (`final.html` `.opt .name`) | Component state | Breakpoint | Trigger |
|---|---|---|---|
| Framing | `ScannerCamera` live, hint "Hold still" (busy) | phone/tablet (coarse) | quad found, auto on, not yet stable |
| Captured | live, hint "Captured", quad fill flash, badge +1 | coarse | a page is added |
| Bad page | live, hint error "Page N blurry · retaking", dashed quad, red badge, Done disabled | coarse | captured page fails `isBlurry` |
| Your pages | `PagesReview` (grid, cut-off alert + Fix crop, Add page, Next: check paper, PDF icon) | coarse; also after photos chosen | Done / stack tap / photos picked |
| Fix crop | `FixCrop` | coarse | pencil on a page, or "Fix crop" |
| Check your paper | `CheckPaper` (scheme found) | all | upload + detect finished, `schemeSource` official/own/unknown |
| Marking · P4a | `MarkingPaper` → `MarkingBoard` phone layout | <768 | progress has tiles |
| Upload (desktop) | `MarkPapers` drop zone + recent uploads (teacher); student desktop drop zone in `CorrectPaper` | ≥768 fine pointer | route load |
| Marking (student, desktop) | `MarkingBoard` desktop 560px column, 7-col board, "Download PDF" button | ≥768 | same as Marking |
| Name check (teacher) desktop + tablet | **L12-owned** (fix-it list). L6 only renders the "N names need you · Check names" row when `namesNeedYou > 0` | — | — |
| Upload sheet (+ mixed-files error) | `UploadSheet` | coarse | camera top-bar file icon, or "Upload a file instead" |
| Shared into Lemely | `SharedFile` | all | `readSharedScan()` returns a file |
| No mark scheme found | `CheckPaper` no-scheme variant; also `MarkingStates` `no_scheme` | all | `schemeSource === "none"` / stage `no_scheme` |
| Camera needs a tap | `CameraStateScreen kind="tap"` | coarse | camera entry without a prior tap |
| Camera blocked (+ no camera, in use, not HTTPS) | `CameraStateScreen kind="error"` with title per error | coarse | getUserMedia rejects |
| Phone turned sideways | landscape overlay, auto paused | coarse landscape | `(orientation: landscape) and (pointer: coarse)` |
| Uploading | `MarkingStates` `sending` | all | XHR progress |
| Offline · saved | `MarkingStates` `saved_offline` + app banner | all | upload failed with status 0 |
| Next in line | `MarkingStates` `next_in_line` | all | stage `queued` |
| Marking stopped | `MarkingStates` `stopped` (sent / not sent) | all | status failed or lost; or send failed |
| Came back mid-run | `MarkingStates` `came_back` | all | opened on a processing run with no tiles yet |
| Couldn't check status | `CorrectPaper` alert above camera/upload start | all | `useActiveUpload` errors |
| Dragging files over the page | `DropVeil` over a dimmed page | ≥768 | window `dragenter` with files |
| After a drop · with errors | `MarkPapers` alert + `ReceivedFiles` (skipped rows) + recent rows with error states | ≥768 | drop handled |
| (not in mock) Reading your answers | `MarkingStates` `reading` | all | fresh run before tiles are seeded. Listed in PR as an edge case |

## Interactions and motion

Values come from `base.css`/`up.css`; `--ease` = `cubic-bezier(.2,.8,.2,1)` = token `--ease-out`.

| Interaction | Values | Reduced motion |
|---|---|---|
| Button press | `transform: scale(.97)` on `:active`, `transition: transform .15s var(--ease-out), background .15s` | no scale, colour only |
| Upload bar / board progress fill | `width` transition `.5s var(--ease-out)` | instant |
| Hint spinner (`.sp`) | 14px ring, `border-top-color: #fff`, `rotate 360deg` in `.8s linear infinite` (mock has no keyframe; `animate-spin` is 1s, use `[animation-duration:.8s]`) | static ring |
| Captured flash | quad `fill-opacity` `.1 → .38 → .1` over 320ms `var(--ease-out)` (mock frames Framing .1 / Captured .38) | no flash, hint text only |
| Bad page quad | stroke `dasharray 10 8`, colour stays tide; badge background turns error | same (static) |
| Stack badge bump | `scale 1 → 1.15 → 1` 200ms `var(--ease-spring)` when count rises | none |
| New page into stack | top card `translateY(-40px) rotate(0)` → resting rotation in 280ms `var(--ease-out)` | appears in place |
| Tile state change | `background-color, box-shadow` `.2s var(--ease-out)`; `now` tile gets `ring-2 ring-primary` | instant |
| Drop veil | `opacity 0→1` 150ms `var(--ease-out)`; page behind `saturate(.6) opacity(.55)` | instant |
| Bottom sheets | existing `Sheet side="bottom"` (`--dur-sheet-ios`) | existing fallback |
| Crop corner drag | pointer capture, clamp to stage, arrow keys move 4px (`final.html` script) | n/a |
| Came-back striped bar | `repeating-linear-gradient(90deg, primary 0 18px, inverse-primary 18px 36px)`, `animation: none` (mock) | same |
| Binny | F1 `Binny` `motion="idle"` | F1 turns it to `none` |

All animations are wrapped with Tailwind `motion-safe:` or `motion-reduce:` variants; `index.css` already has a global reduced-motion guard.

## Token map (mock var → Tailwind token)

`--p` → `primary` · `--ph` → `primary-hover` · `--pc` → `primary-container` · `--tide` → `inverse-primary` · `--s` → `surface` · `--l` → `surface-container-lowest` · `--sl` → `surface-container-low` · `--sc` → `surface-container` · `--sh` → `surface-container-high` · `--ink` → `on-surface` · `--v` → `on-surface-variant` · `--o` → `outline` · `--ov` → `outline-variant` · `--okf` → `success` · `--okc` → `success-container` · `--ok` → `success-text` · `--err` → `error` · `--errc` → `error-container` · `--onerrc` → `on-error-container` · `--night` / camera chrome `oklch(.16 .014 245/α)` → `inverse-surface/α` · paper `#fbfbf8` → `surface-container-lowest` · badge error `oklch(.72 .15 25)` → `error` (small fix, listed in PR: better contrast) · blank tile dashed `oklch(.7 .02 240)` → `outline-on-surface-variant/50`. Fonts: Schibsted → `font-sans`, Bricolage → `font-display`, JetBrains → `font-mono`. Radii: 14px → `rounded-button`, 18px → `rounded-inner`, 20px → `rounded-tile`, 24px → `rounded-card`, 28px → `rounded-[28px]`.

Shared class recipes (defined once in `web/src/components/scan/styles.ts`, Task 14):
```ts
export const btn = "inline-flex min-h-11 items-center justify-center gap-2 rounded-button px-[18px] py-[11px] text-sm font-bold transition-[transform,background-color] duration-150 ease-out motion-safe:active:scale-[.97] disabled:pointer-events-none disabled:opacity-50"
export const btnPrimary = `${btn} bg-primary text-on-primary hover:bg-primary-hover`
export const btnTonal = `${btn} bg-primary-container text-primary`
export const btnOutline = `${btn} bg-surface-container-lowest text-on-surface ring-[1.5px] ring-inset ring-outline`
export const btnTide = `${btn} min-h-[52px] bg-inverse-primary text-primary text-[15px]`
export const linkTide = "min-h-11 cursor-pointer border-0 bg-transparent text-[15px] font-bold text-inverse-primary"
export const iconDark = "grid size-11 place-items-center rounded-button bg-inverse-surface/60 text-white"
export const iconLight = "grid size-11 place-items-center rounded-button bg-primary-container text-primary"
export const display30 = "font-display text-[30px] font-extrabold leading-[1.12] tracking-[-.03em] text-balance"
```

## Cloud Run and SSE notes (read before Tasks 3–4)

- `deploy.yml:374`: `--timeout=300 --max-instances=3 --min-instances=0 --cpu=1`, no `--no-cpu-throttling`. A run's thread only gets CPU while a request is open on its instance. So `POST /student/correct` must stay open for the run (it does today), and the display stream is a separate, instance-agnostic DB poll. See Needs user decision 2.
- `web/worker/index.ts` passes `res.body` through untouched, so streaming works; Cloudflare closes a response with no bytes for 100 s → heartbeats.
- `web/nginx.conf:99` already has `proxy_buffering off` and `proxy_read_timeout 300s` for local Docker.
- `lemely/web/app.py` has no GZip middleware (gzip would buffer SSE). Keep it that way.
- `streamActivity` (`web/src/lib/api.ts:372`) ignores lines without `data:`, so `: ping` comments are safe.

## Tasks

Backend tasks (1–7) go to the `implementer` agent. Run every pytest command from the worktree root with `source .venv/bin/activate` and `PYTHONPATH=$PWD`.

### Task 1: Migration, ORM model and shared test fixtures

**Files:**
- Create: `lemely/db/migrations/versions/0056_marking_progress.py`
- Create: `lemely/db/models/marking.py`
- Modify: `lemely/db/models/__init__.py` (add `marking` to `import_all_models()` and the re-exports)
- Modify: `lemely/db/models/attempts.py` (two columns on `Upload`, after `idempotency_key`)
- Modify: `lemely/db/models/teacher_papers.py` (one column, after `run_started_at`)
- Create: `tests/marking_fixtures.py`
- Test: `tests/test_migration_marking_progress.py`

**Interfaces:**
- Produces: `MarkingProgress` ORM (`paper_id`, `owner_kind`, `stage`, `questions`, `missing_pages`, `mark_started_at`, timestamps); `Upload.metadata_json`, `Upload.page_crops`, `TeacherPaper.page_crops`; fixtures `pg_sessionmaker`, `seed_user(sm, role)`, `seed_upload(sm, owner, *, status)`, `seed_teacher_paper(sm, owner, **fields)`.

> **Migration:** writing and testing this file on a throwaway database is allowed. **Stop and ask the user before running it against any shared database.**

- [ ] **Step 1: Write the failing migration test**

```python
"""Migration 0056_marking_progress (redesign L6): one table, three columns, clean downgrade."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from lemely.db.base import Base
from lemely.db.models import import_all_models
from tests.test_migration_tutoring_enums import (
    current_revision,
    head_revision,
    object_names,
    public_tables,
    upgrade_head,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0056_marking_progress"
DOWN_REVISION = "0054_waitlist_email_confirmation"
TABLE = "marking_progress"


def _orm_names() -> set[str]:
    table = Base.metadata.tables[TABLE]
    names = {str(c.name) for c in table.constraints}
    return names | {str(i.name) for i in table.indexes}


def _columns(session: Session, table: str) -> set[str]:
    rows = session.execute(
        sa.text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
        {"t": table},
    )
    return {r[0] for r in rows}


def test_orm_declares_the_named_objects() -> None:
    assert _orm_names() == {"pk_marking_progress", "ck_marking_progress_owner_kind"}


def test_revision_chain_and_length() -> None:
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32


def test_upgrade_creates_table_and_columns(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        assert object_names(session, [TABLE]) == _orm_names()
        assert {"metadata_json", "page_crops"} <= _columns(session, "uploads")
        assert "page_crops" in _columns(session, "teacher_papers")


def test_owner_kind_is_checked(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker.begin() as session:
        session.execute(
            sa.text(f"INSERT INTO {TABLE} (paper_id, owner_kind) VALUES (:p, 'student')"),  # noqa: S608
            {"p": uuid.uuid4()},
        )
    try:
        with migrated_sessionmaker.begin() as session:
            session.execute(
                sa.text(f"INSERT INTO {TABLE} (paper_id, owner_kind) VALUES (:p, 'parent')"),  # noqa: S608
                {"p": uuid.uuid4()},
            )
    except sa.exc.IntegrityError:
        return
    raise AssertionError("owner_kind 'parent' should be refused")


def test_downgrade_then_upgrade(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    downgrade_to(DOWN_REVISION)
    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        assert TABLE not in public_tables(session)
        assert not ({"metadata_json", "page_crops"} & _columns(session, "uploads"))
        assert "page_crops" not in _columns(session, "teacher_papers")
    upgrade_head()
    with sm() as session:
        assert current_revision(session) == head_revision()
        assert object_names(session, [TABLE]) == _orm_names()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_migration_marking_progress.py -v`
Expected: FAIL (`KeyError: 'marking_progress'` / revision not found). Skips only if local Postgres is down; start it first.

- [ ] **Step 3: Write the migration**

```python
"""marking progress, detected paper and saved crops (redesign L6).

Revision ID: 0056_marking_progress
Revises: 0054_waitlist_email_confirmation
Create Date: 2026-11-15 00:00:00.000000

Additive.

* ``marking_progress``: one row per marking run (a student upload or a teacher paper), keyed
  by the paper id. Holds the stage, the per-question tile states and when marking began, so a
  progress read on any Cloud Run instance sees the same run.
* ``uploads.metadata_json``: the exam the scan was detected as, written by the paper check so
  the marking run does not pay for a second detection call.
* ``uploads.page_crops`` and ``teacher_papers.page_crops``: the corners and rotation the user
  saved for each page.

``downgrade`` drops the table and the three columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0056_marking_progress"
down_revision: str | Sequence[str] | None = "0054_waitlist_email_confirmation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "marking_progress"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        TABLE,
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_kind", sa.String(16), nullable=False),
        sa.Column("stage", sa.String(16), nullable=True),
        sa.Column(
            "questions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "missing_pages",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("mark_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("paper_id", name=op.f("pk_marking_progress")),
        sa.CheckConstraint(
            "owner_kind IN ('student', 'teacher')", name=op.f("ck_marking_progress_owner_kind")
        ),
    )
    op.add_column("uploads", sa.Column("metadata_json", postgresql.JSONB(), nullable=True))
    op.add_column("uploads", sa.Column("page_crops", postgresql.JSONB(), nullable=True))
    op.add_column("teacher_papers", sa.Column("page_crops", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("teacher_papers", "page_crops")
    op.drop_column("uploads", "page_crops")
    op.drop_column("uploads", "metadata_json")
    op.drop_table(TABLE)
```

- [ ] **Step 4: Write the model and columns**

`lemely/db/models/marking.py`:
```python
"""ORM model for a marking run's live progress (redesign L6)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.enums import TimestampMixin


class MarkingProgress(TimestampMixin, Base):
    """How far one marking run has got, readable from any instance.

    ``paper_id`` is a student ``uploads.id`` or a ``teacher_papers.id``; there is no
    foreign key because it can point at either table (``owner_kind`` says which).
    Every reader authorises through the owning table first and only then reads this row.
    ``questions`` is a list of ``{"id": str, "state": str, "blank": bool | None}``.
    """

    __tablename__ = "marking_progress"
    __table_args__ = (
        sa.CheckConstraint("owner_kind IN ('student', 'teacher')", name="owner_kind"),
    )

    paper_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    owner_kind: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    stage: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    questions: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    missing_pages: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    )
    mark_started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


__all__ = ["MarkingProgress"]
```

In `lemely/db/models/attempts.py`, inside `class Upload`, directly after the `idempotency_key` column:
```python
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # type: ignore[type-arg]
    """The exam the paper check detected (``ExamMetadata`` as JSON); reused by marking."""
    page_crops: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # type: ignore[type-arg]
    """Saved crops, one ``{"page", "corners", "rotation"}`` per page, corners 0..1."""
```

In `lemely/db/models/teacher_papers.py`, after `run_started_at`:
```python
    page_crops: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # type: ignore[type-arg]
```

In `lemely/db/models/__init__.py`, add `marking,` to the import list inside `import_all_models()` (alphabetical, after `invites`), and add `from lemely.db.models.marking import MarkingProgress` plus `"MarkingProgress"` to `__all__` next to the other re-exports.

- [ ] **Step 5: Write `tests/marking_fixtures.py`**

```python
"""Shared Postgres fixtures for the L6 marking tests (throwaway DB, skips when unreachable)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models import User, import_all_models
from lemely.db.models.attempts import Upload
from lemely.db.models.enums import Role, UploadStatus
from lemely.db.models.teacher_papers import TeacherPaper
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

import_all_models()


def _reachable(url: str) -> bool:
    engine = create_engine(make_url(url).set(database="postgres"))
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    base_url = DatabaseSettings().url
    if not _reachable(base_url):
        pytest.skip("local Postgres not reachable")
    admin = create_engine(make_url(base_url).set(database="postgres"), isolation_level="AUTOCOMMIT")
    dbname = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))
    engine = create_engine(make_url(base_url).set(database=dbname))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


def seed_user(sm: sessionmaker[Session], role: Role = Role.student) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            User(id=uid, email=f"{uid}@example.com", role=role, email_verified_at=datetime.now(UTC))
        )
    return uid


def seed_upload(
    sm: sessionmaker[Session],
    owner: uuid.UUID,
    *,
    status: UploadStatus = UploadStatus.pending,
    content_type: str = "application/pdf",
    filename: str = "scan.pdf",
) -> uuid.UUID:
    pid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            Upload(
                id=pid,
                user_id=owner,
                storage_path=f"uploads/{owner}/{pid.hex}/{filename}",
                original_filename=filename,
                content_type=content_type,
                status=status,
            )
        )
    return pid


def seed_teacher_paper(sm: sessionmaker[Session], owner: uuid.UUID, **fields: Any) -> uuid.UUID:
    pid = uuid.uuid4()
    values: dict[str, Any] = {
        "id": pid,
        "uploaded_by": owner,
        "storage_path": f"teacher/{owner}/{pid.hex}/scan.pdf",
        "original_filename": "scan.pdf",
        "content_type": "application/pdf",
        "status": UploadStatus.pending,
    }
    values.update(fields)
    with sm.begin() as session:
        session.add(TeacherPaper(**values))
    return pid
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `pytest tests/test_migration_marking_progress.py -v`
Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
pre-commit run --files lemely/db/migrations/versions/0056_marking_progress.py lemely/db/models/marking.py lemely/db/models/__init__.py lemely/db/models/attempts.py lemely/db/models/teacher_papers.py tests/marking_fixtures.py tests/test_migration_marking_progress.py
git commit -S -m "feat(db): marking progress table, detected paper and saved crops" -- lemely/db/migrations/versions/0056_marking_progress.py lemely/db/models/marking.py lemely/db/models/__init__.py lemely/db/models/attempts.py lemely/db/models/teacher_papers.py tests/marking_fixtures.py tests/test_migration_marking_progress.py
```

---

### Task 2: `MarkingProgressRepository` and the ETA

**Files:**
- Create: `lemely/db/marking_progress_repo.py`
- Create: `lemely/web/services/marking_progress.py` (this task adds only `estimate_eta_seconds`; later tasks append)
- Test: `tests/test_marking_progress_repo.py`

**Interfaces:**
- Consumes: `MarkingProgress` (Task 1), `pg_sessionmaker` fixture.
- Produces:
  - `TileState = Literal["waiting", "done", "missing", "stopped"]`
  - `QuestionState(id: str, state: TileState, blank: bool | None)`
  - `ProgressSnapshot(paper_id, owner_kind, stage, questions: tuple[QuestionState, ...], missing_pages: tuple[int, ...], mark_started_at, updated_at)` with property `done -> int`
  - `MarkingProgressRepository(sm)`: `reset(paper_id, *, owner_kind)`, `set_stage(paper_id, stage)`, `seed_questions(paper_id, question_ids)`, `mark_question(paper_id, question_id, *, blank: bool | None = None)`, `stop_current(paper_id)`, `set_missing(paper_id, *, pages, question_ids)`, `get(paper_id) -> ProgressSnapshot | None`
  - `STAGES = ("queued", "scheme", "extract", "mark", "done", "no_scheme")`
  - `estimate_eta_seconds(*, done: int, total: int | None, mark_started_at: datetime | None, now: datetime) -> int | None`

- [ ] **Step 1: Write the failing tests**

```python
"""MarkingProgressRepository and the ETA (redesign L6)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.marking_progress_repo import MarkingProgressRepository, QuestionState
from lemely.web.services.marking_progress import estimate_eta_seconds
from tests.marking_fixtures import pg_sessionmaker  # noqa: F401


@pytest.fixture
def repo(pg_sessionmaker: sessionmaker[Session]) -> MarkingProgressRepository:  # noqa: F811
    return MarkingProgressRepository(pg_sessionmaker)


def test_get_unknown_is_none(repo: MarkingProgressRepository) -> None:
    assert repo.get(uuid.uuid4()) is None


def test_reset_creates_an_empty_row(repo: MarkingProgressRepository) -> None:
    pid = uuid.uuid4()
    repo.reset(pid, owner_kind="student")
    snap = repo.get(pid)
    assert snap is not None
    assert (snap.owner_kind, snap.stage, snap.questions, snap.done) == ("student", None, (), 0)


def test_seed_then_mark_keeps_scheme_order(repo: MarkingProgressRepository) -> None:
    pid = uuid.uuid4()
    repo.reset(pid, owner_kind="student")
    repo.seed_questions(pid, ["1", "2a", "2b", "3"])
    repo.mark_question(pid, "2a")
    repo.mark_question(pid, "1", blank=True)
    snap = repo.get(pid)
    assert snap is not None
    assert snap.questions == (
        QuestionState("1", "done", True),
        QuestionState("2a", "done", None),
        QuestionState("2b", "waiting", None),
        QuestionState("3", "waiting", None),
    )
    assert snap.done == 2
    assert snap.stage == "mark"
    assert snap.mark_started_at is not None


def test_mark_unknown_question_appends(repo: MarkingProgressRepository) -> None:
    pid = uuid.uuid4()
    repo.reset(pid, owner_kind="teacher")
    repo.mark_question(pid, "7")
    snap = repo.get(pid)
    assert snap is not None and snap.questions == (QuestionState("7", "done", None),)


def test_reset_clears_a_previous_run(repo: MarkingProgressRepository) -> None:
    pid = uuid.uuid4()
    repo.reset(pid, owner_kind="student")
    repo.seed_questions(pid, ["1"])
    repo.mark_question(pid, "1")
    repo.reset(pid, owner_kind="student")
    snap = repo.get(pid)
    assert snap is not None and snap.questions == () and snap.mark_started_at is None


def test_stop_current_marks_first_waiting_only_while_marking(repo: MarkingProgressRepository) -> None:
    pid = uuid.uuid4()
    repo.reset(pid, owner_kind="student")
    repo.seed_questions(pid, ["1", "2", "3"])
    repo.stop_current(pid)  # stage is not "mark" yet: nothing changes
    assert [q.state for q in repo.get(pid).questions] == ["waiting"] * 3  # type: ignore[union-attr]
    repo.mark_question(pid, "1")
    repo.stop_current(pid)
    assert [q.state for q in repo.get(pid).questions] == ["done", "stopped", "waiting"]  # type: ignore[union-attr]


def test_set_missing(repo: MarkingProgressRepository) -> None:
    pid = uuid.uuid4()
    repo.reset(pid, owner_kind="student")
    repo.seed_questions(pid, ["8", "9"])
    repo.set_missing(pid, pages=[9, 9], question_ids=["9"])
    snap = repo.get(pid)
    assert snap is not None
    assert snap.missing_pages == (9,)
    assert snap.questions[1] == QuestionState("9", "missing", None)


def test_set_stage_rejects_unknown(repo: MarkingProgressRepository) -> None:
    pid = uuid.uuid4()
    repo.reset(pid, owner_kind="student")
    with pytest.raises(ValueError, match="stage"):
        repo.set_stage(pid, "parsing")


def test_writes_to_a_missing_row_are_ignored(repo: MarkingProgressRepository) -> None:
    pid = uuid.uuid4()
    repo.set_stage(pid, "extract")
    repo.mark_question(pid, "1")
    assert repo.get(pid) is None


NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("done", "total", "started", "expected"),
    [
        (0, 14, NOW - timedelta(seconds=60), None),
        (1, 14, NOW - timedelta(seconds=60), None),
        (2, 14, None, None),
        (14, 14, NOW - timedelta(seconds=60), None),
        (2, None, NOW - timedelta(seconds=60), None),
        (8, 14, NOW - timedelta(seconds=160), 120),
        (2, 3, NOW - timedelta(seconds=1), 1),
    ],
)
def test_eta(done: int, total: int | None, started: datetime | None, expected: int | None) -> None:
    assert estimate_eta_seconds(done=done, total=total, mark_started_at=started, now=NOW) == expected
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_marking_progress_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: lemely.db.marking_progress_repo`.

- [ ] **Step 3: Implement the repository**

```python
"""Live progress of a marking run (redesign L6).

One writer per run (the run's :class:`~lemely.web.services.marking_progress.ProgressRecorder`
thread, or the run itself for stage changes), any number of readers on any instance.
Every write is a no-op when the row does not exist, so a recorder that outlives a
deleted paper never resurrects it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from lemely.db.models.marking import MarkingProgress

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

OwnerKind = Literal["student", "teacher"]
TileState = Literal["waiting", "done", "missing", "stopped"]
STAGES: tuple[str, ...] = ("queued", "scheme", "extract", "mark", "done", "no_scheme")


@dataclass(frozen=True, slots=True)
class QuestionState:
    """One question's tile. ``blank`` stays ``None`` until L12 supplies the flag."""

    id: str
    state: TileState
    blank: bool | None = None


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    """A detached read of one run's progress row."""

    paper_id: uuid.UUID
    owner_kind: OwnerKind
    stage: str | None
    questions: tuple[QuestionState, ...]
    missing_pages: tuple[int, ...]
    mark_started_at: datetime | None
    updated_at: datetime

    @property
    def done(self) -> int:
        """Questions the run has finished (a blank answer counts: it was marked 0)."""
        return sum(1 for q in self.questions if q.state == "done")


def _question(raw: dict[str, Any]) -> QuestionState:
    blank = raw.get("blank")
    return QuestionState(
        id=str(raw["id"]),
        state=cast(TileState, raw.get("state", "waiting")),
        blank=blank if isinstance(blank, bool) else None,
    )


class MarkingProgressRepository:
    """CRUD for :class:`MarkingProgress` rows."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sm = session_factory

    def reset(self, paper_id: uuid.UUID, *, owner_kind: OwnerKind) -> None:
        """Start a fresh run: create the row, or wipe a previous run's progress."""
        stmt = insert(MarkingProgress).values(
            paper_id=paper_id, owner_kind=owner_kind, stage=None, questions=[], missing_pages=[]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[MarkingProgress.paper_id],
            set_={
                "owner_kind": owner_kind,
                "stage": None,
                "questions": sa.cast(sa.literal("[]"), MarkingProgress.questions.type),
                "missing_pages": sa.cast(sa.literal("[]"), MarkingProgress.missing_pages.type),
                "mark_started_at": None,
                "updated_at": sa.func.now(),
            },
        )
        with self._sm.begin() as session:
            session.execute(stmt)

    def set_stage(self, paper_id: uuid.UUID, stage: str) -> None:
        if stage not in STAGES:
            raise ValueError(f"Unknown marking stage: {stage}")
        with self._sm.begin() as session:
            row = session.get(MarkingProgress, paper_id)
            if row is None:
                return
            row.stage = stage
            if stage == "mark" and row.mark_started_at is None:
                row.mark_started_at = datetime.now(UTC)

    def seed_questions(self, paper_id: uuid.UUID, question_ids: Sequence[str]) -> None:
        """Lay out every tile in mark-scheme order, keeping states already recorded."""
        with self._sm.begin() as session:
            row = session.get(MarkingProgress, paper_id)
            if row is None:
                return
            existing = {str(q["id"]): q for q in row.questions}
            row.questions = [
                existing.get(qid, {"id": qid, "state": "waiting", "blank": None})
                for qid in dict.fromkeys(question_ids)
            ]

    def mark_question(
        self, paper_id: uuid.UUID, question_id: str, *, blank: bool | None = None
    ) -> None:
        """Record one question as marked. ``blank`` is the L12 flag; L6 passes ``None``."""
        with self._sm.begin() as session:
            row = session.get(MarkingProgress, paper_id)
            if row is None:
                return
            questions = [dict(q) for q in row.questions]
            for q in questions:
                if q["id"] == question_id:
                    q["state"], q["blank"] = "done", blank
                    break
            else:
                questions.append({"id": question_id, "state": "done", "blank": blank})
            row.questions = questions
            if row.stage != "mark":
                row.stage = "mark"
            if row.mark_started_at is None:
                row.mark_started_at = datetime.now(UTC)

    def stop_current(self, paper_id: uuid.UUID) -> None:
        """On failure mid-marking, label the question that was being marked as stopped."""
        with self._sm.begin() as session:
            row = session.get(MarkingProgress, paper_id)
            if row is None or row.stage != "mark":
                return
            questions = [dict(q) for q in row.questions]
            for q in questions:
                if q["state"] == "waiting":
                    q["state"] = "stopped"
                    break
            row.questions = questions

    def set_missing(
        self, paper_id: uuid.UUID, *, pages: Sequence[int], question_ids: Sequence[str]
    ) -> None:
        """L12 seam: name the missing pages and the questions they hold."""
        targets = set(question_ids)
        with self._sm.begin() as session:
            row = session.get(MarkingProgress, paper_id)
            if row is None:
                return
            row.missing_pages = sorted(set(pages))
            row.questions = [
                {**q, "state": "missing"} if q["id"] in targets else dict(q) for q in row.questions
            ]

    def get(self, paper_id: uuid.UUID) -> ProgressSnapshot | None:
        with self._sm() as session:
            row = session.get(MarkingProgress, paper_id)
            if row is None:
                return None
            return ProgressSnapshot(
                paper_id=row.paper_id,
                owner_kind=cast(OwnerKind, row.owner_kind),
                stage=row.stage,
                questions=tuple(_question(q) for q in row.questions),
                missing_pages=tuple(int(p) for p in row.missing_pages),
                mark_started_at=row.mark_started_at,
                updated_at=row.updated_at,
            )


__all__ = [
    "STAGES",
    "MarkingProgressRepository",
    "OwnerKind",
    "ProgressSnapshot",
    "QuestionState",
    "TileState",
]
```

`lemely/web/services/marking_progress.py` (first version):
```python
"""Marking progress: recorder, ETA, DTO builder, SSE stream, PDF and recent rows (redesign L6)."""

from __future__ import annotations

from datetime import datetime


def estimate_eta_seconds(
    *, done: int, total: int | None, mark_started_at: datetime | None, now: datetime
) -> int | None:
    """Seconds left at this run's own pace, or ``None`` when there is no honest estimate.

    Needs two marked questions (one is noise) and a known total. Never 0: a run that
    has questions left is never "done in 0 seconds".
    """
    if mark_started_at is None or total is None or total <= 0 or done < 2 or done >= total:
        return None
    elapsed = (now - mark_started_at).total_seconds()
    if elapsed <= 0:
        return None
    return max(1, round(elapsed / done * (total - done)))
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_marking_progress_repo.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lemely/db/marking_progress_repo.py lemely/web/services/marking_progress.py tests/test_marking_progress_repo.py
git commit -S -m "feat(db): marking progress repository and ETA" -- lemely/db/marking_progress_repo.py lemely/web/services/marking_progress.py tests/test_marking_progress_repo.py
```

---

### Task 3: Recorder, SSE heartbeat and the student run wiring

**Files:**
- Modify: `lemely/web/services/marking_progress.py` (append `ProgressRecorder`, `get_marking_progress_repo`)
- Modify: `lemely/web/sse.py` (heartbeat, `SSE_HEADERS`, `SSE_DONE_FRAME`)
- Modify: `lemely/db/upload_repo.py` (`get_metadata`, `set_metadata`)
- Modify: `lemely/web/routers/student.py` (`student_correct` only)
- Modify: `tests/test_student_correct.py` (override `get_marking_progress_repo` in the `client` fixture)
- Test: `tests/test_marking_recorder.py`, `tests/test_sse_heartbeat.py`

**Interfaces:**
- Consumes: Task 2 repo.
- Produces: `ProgressRecorder(repo, paper_id, *, scope, poll_seconds=0.2).start() / .stop() / .apply(event)`; `get_marking_progress_repo() -> MarkingProgressRepository`; `SSE_HEADERS: dict[str, str]`; `SSE_DONE_FRAME: str`; `bus_event_stream(..., heartbeat_seconds=15.0)`; `StudentUploadRepository.get_metadata(upload_id) -> ExamMetadata | None`, `.set_metadata(upload_id, metadata) -> None`.

- [ ] **Step 1: Write the failing recorder test**

```python
"""ProgressRecorder mirrors bus events onto the progress row (redesign L6)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.marking_progress_repo import MarkingProgressRepository
from lemely.runtime.events import Event, EventType, bus, current_run_id
from lemely.web.services.marking_progress import ProgressRecorder
from tests.marking_fixtures import pg_sessionmaker  # noqa: F401


@pytest.fixture
def repo(pg_sessionmaker: sessionmaker[Session]) -> MarkingProgressRepository:  # noqa: F811
    return MarkingProgressRepository(pg_sessionmaker)


def _event(t: EventType, **payload: object) -> Event:
    return Event(t, payload, run_id="student:x")


def test_apply_maps_each_event(repo: MarkingProgressRepository) -> None:
    pid = uuid.uuid4()
    repo.reset(pid, owner_kind="student")
    repo.seed_questions(pid, ["1", "2"])
    rec = ProgressRecorder(repo, pid, scope="student:x")
    try:
        rec.apply(_event(EventType.EXTRACTION_QUEUED, message="wait"))
        assert repo.get(pid).stage == "queued"  # type: ignore[union-attr]
        rec.apply(_event(EventType.EXTRACTION_DEQUEUED))
        assert repo.get(pid).stage == "extract"  # type: ignore[union-attr]
        rec.apply(_event(EventType.MARKING_PROGRESS, question_id="1", marker_source="blank", index=0, total=2))
        snap = repo.get(pid)
        assert snap is not None and snap.stage == "mark"
        # L6 never fabricates blank: the flag stays None until L12 supplies it.
        assert snap.questions[0].state == "done" and snap.questions[0].blank is None
        rec.apply(_event(EventType.MARKING_PROGRESS, phase="complete", awarded=1, max_marks=2))
        assert repo.get(pid).stage == "done"  # type: ignore[union-attr]
        rec.apply(_event(EventType.GEMINI_CALL_START))  # ignored
    finally:
        rec.stop()


def test_thread_drains_scoped_events_before_stopping(repo: MarkingProgressRepository) -> None:
    pid = uuid.uuid4()
    repo.reset(pid, owner_kind="student")
    repo.seed_questions(pid, ["1", "2"])
    token = current_run_id.set("student:scoped")
    try:
        rec = ProgressRecorder(repo, pid, scope="student:scoped", poll_seconds=0.01).start()
        bus.publish(EventType.MARKING_PROGRESS, question_id="1", index=0, total=2)
        bus.publish(EventType.MARKING_PROGRESS, question_id="2", index=1, total=2)
        rec.stop()
    finally:
        current_run_id.reset(token)
    snap = repo.get(pid)
    assert snap is not None and snap.done == 2


def test_other_runs_do_not_leak_in(repo: MarkingProgressRepository) -> None:
    pid = uuid.uuid4()
    repo.reset(pid, owner_kind="student")
    rec = ProgressRecorder(repo, pid, scope="student:mine", poll_seconds=0.01).start()
    token = current_run_id.set("student:theirs")
    try:
        bus.publish(EventType.MARKING_PROGRESS, question_id="9", index=0, total=1)
    finally:
        current_run_id.reset(token)
        rec.stop()
    assert repo.get(pid).questions == ()  # type: ignore[union-attr]
```

- [ ] **Step 2: Write the failing heartbeat test**

```python
"""bus_event_stream sends SSE comment heartbeats while a run is silent (redesign L6)."""

from __future__ import annotations

import time

import anyio

from lemely.runtime.events import bus
from lemely.web.sse import SSE_DONE_FRAME, SSE_HEADERS, bus_event_stream


def test_heartbeat_while_silent_then_done() -> None:
    def run() -> None:
        time.sleep(0.12)
        bus.publish_done()

    async def collect() -> list[str]:
        return [
            frame
            async for frame in bus_event_stream(
                run, poll_seconds=0.01, heartbeat_seconds=0.03, run_id="hb-test"
            )
        ]

    frames = anyio.run(collect)
    assert ": ping\n\n" in frames
    assert frames[-1] == SSE_DONE_FRAME


def test_headers_disable_buffering() -> None:
    assert SSE_HEADERS["X-Accel-Buffering"] == "no"
    assert "no-transform" in SSE_HEADERS["Cache-Control"]
```

- [ ] **Step 3: Run both to verify failure**

Run: `pytest tests/test_marking_recorder.py tests/test_sse_heartbeat.py -v`
Expected: FAIL (`ImportError: ProgressRecorder`, `ImportError: SSE_DONE_FRAME`).

- [ ] **Step 4: Implement the recorder (append to `lemely/web/services/marking_progress.py`)**

Add these imports at the top of the module (keep `datetime`):
```python
import queue
import threading
import uuid

import structlog

from lemely.db.marking_progress_repo import MarkingProgressRepository
from lemely.runtime.events import Event, EventType, bus
from lemely.web.deps import get_sessionmaker, get_settings

log = structlog.get_logger(__name__)
```

Append:
```python
def get_marking_progress_repo() -> MarkingProgressRepository:
    """FastAPI dependency: the progress repository on the app's database."""
    return MarkingProgressRepository(get_sessionmaker(get_settings()))


class ProgressRecorder:
    """Mirror one run's bus events onto its ``marking_progress`` row.

    Subscribes to the run's own scope, so another run's events never reach it. Runs on
    its own daemon thread; :meth:`stop` drains whatever is still queued before returning,
    so the last ``MARKING_PROGRESS`` of a run is never lost. A write failure is logged and
    swallowed: progress is a display, and must never fail the marking it describes.
    """

    def __init__(
        self,
        repo: MarkingProgressRepository,
        paper_id: uuid.UUID,
        *,
        scope: str,
        poll_seconds: float = 0.2,
    ) -> None:
        self._repo = repo
        self._paper_id = paper_id
        self._poll = poll_seconds
        self._stage: str | None = None
        self._queue: queue.SimpleQueue[Event | None] = bus.subscribe_queue(scope)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name=f"lemely-progress-{paper_id}"
        )

    def start(self) -> ProgressRecorder:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)
        else:
            self._drain()
        bus.unsubscribe_queue(self._queue)

    def _drain(self) -> None:
        while True:
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                return
            if event is not None:
                self._safe_apply(event)

    def _loop(self) -> None:
        while True:
            try:
                event = self._queue.get(timeout=self._poll)
            except queue.Empty:
                if self._stop.is_set():
                    return
                continue
            if event is not None:
                self._safe_apply(event)

    def _safe_apply(self, event: Event) -> None:
        try:
            self.apply(event)
        except Exception:
            log.exception("marking_progress_write_failed", paper_id=str(self._paper_id))

    def _set_stage(self, stage: str) -> None:
        if stage != self._stage:
            self._repo.set_stage(self._paper_id, stage)
            self._stage = stage

    def apply(self, event: Event) -> None:
        """Apply one event. Public so tests can drive it without a thread."""
        if event.type is EventType.EXTRACTION_QUEUED:
            self._set_stage("queued")
        elif event.type in (EventType.EXTRACTION_DEQUEUED, EventType.EXTRACTION_PROGRESS):
            self._set_stage("extract")
        elif event.type is EventType.MARKING_PROGRESS:
            if event.payload.get("phase") == "complete":
                self._set_stage("done")
                return
            question_id = event.payload.get("question_id")
            if isinstance(question_id, str) and question_id:
                self._repo.mark_question(self._paper_id, question_id, blank=None)
                self._stage = "mark"
```

- [ ] **Step 5: Heartbeat in `lemely/web/sse.py`**

Add public constants under `_DONE_FRAME`:
```python
SSE_DONE_FRAME = _DONE_FRAME
_HEARTBEAT_FRAME = ": ping\n\n"

#: Headers every SSE response sends. ``no-transform`` stops intermediaries from
#: compressing (and so buffering) the stream; ``X-Accel-Buffering`` turns nginx-style
#: buffering off. Cloudflare passes ``text/event-stream`` bodies through unbuffered.
SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}
```
Change the signature of `bus_event_stream` to add `heartbeat_seconds: float = 15.0` (after `poll_seconds`), document it in the Args ("idle time after which a `: ping` comment is sent; Cloudflare drops a response silent for 100 s"), and replace the main loop with:
```python
    worker.start()
    idle = 0.0
    try:
        while True:
            event = await anyio.to_thread.run_sync(_drain_one, q, poll_seconds)
            if event is _DONE:
                break
            if event is _EMPTY:
                if not worker.is_alive():
                    break
                idle += poll_seconds
                if idle >= heartbeat_seconds:
                    idle = 0.0
                    yield _HEARTBEAT_FRAME
                continue
            idle = 0.0
            if event.type in SERVER_ONLY_EVENTS:  # type: ignore[attr-defined]
                continue
            yield _format_frame(event)  # type: ignore[arg-type]
```
(the trailing drain and `finally` stay as they are). Add `"SSE_DONE_FRAME", "SSE_HEADERS"` to `__all__`.

- [ ] **Step 6: Upload repo metadata methods (append to `StudentUploadRepository`)**

```python
    def get_metadata(self, upload_id: uuid.UUID) -> ExamMetadata | None:
        """The exam the paper check stored for this upload, if any."""
        with self._sm() as session:
            upload = session.get(Upload, upload_id)
            if upload is None or upload.metadata_json is None:
                return None
            return ExamMetadata.model_validate(upload.metadata_json)

    def set_metadata(self, upload_id: uuid.UUID, metadata: ExamMetadata) -> None:
        """Store the detected (or student-chosen) exam for this upload."""
        with self._sm.begin() as session:
            upload = session.get(Upload, upload_id)
            if upload is not None:
                upload.metadata_json = metadata.model_dump(mode="json")
```
Add `from lemely.core.schemas import ExamMetadata` to the module imports.

- [ ] **Step 7: Wire the student run (`lemely/web/routers/student.py`, `student_correct`)**

Imports:
```python
from lemely.db.marking_progress_repo import MarkingProgressRepository
from lemely.web.services.marking_progress import ProgressRecorder, get_marking_progress_repo
from lemely.web.sse import SSE_HEADERS
```
Add the dependency parameter after `zones`:
```python
    progress_repo: Annotated[MarkingProgressRepository, Depends(get_marking_progress_repo)],
```
Inside `run()`, change only these parts (everything else stays):
```python
    def run() -> None:
        from lemely.runtime.events import current_run_id

        progress_repo.reset(owned.id, owner_kind="student")
        recorder = ProgressRecorder(
            progress_repo, owned.id, scope=current_run_id.get() or f"student:{payload.paperId}"
        ).start()
        try:
            upload_repo.set_status(owned.id, UploadStatus.processing)
            with tempfile.TemporaryDirectory() as tmp_dir:
                # ... scan download and sibling scheme exactly as today ...
                with script_cost_scope(settings, script_key=f"upload:{owned.id}"):
                    # The paper check (POST /student/uploads/{id}/detect) may already have
                    # paid for detection; reuse it so a paper costs one detection call.
                    metadata: ExamMetadata | None = upload_repo.get_metadata(owned.id)
                    if metadata is None and llm_key_configured(settings, "scan_metadata"):
                        try:
                            metadata = ScanMetadataExtractor(gemini_client)(scan_path)
                            upload_repo.set_metadata(owned.id, metadata)
                        except Exception as exc:
                            bus.publish(
                                EventType.WARNING,
                                paper_id=payload.paperId,
                                message=f"Could not detect scan metadata: {exc}",
                            )

                    progress_repo.set_stage(owned.id, "scheme")
                    mark_scheme = resolve_mark_scheme(
                        sibling_scheme, corpus, settings, gemini_client, metadata=metadata
                    )
                    if mark_scheme is None:
                        progress_repo.set_stage(owned.id, "no_scheme")
                        bus.publish(
                            EventType.WARNING,
                            paper_id=payload.paperId,
                            message="No mark scheme available for this paper; cannot mark.",
                        )
                        upload_repo.set_status(owned.id, UploadStatus.failed)
                        return
                    progress_repo.seed_questions(owned.id, [q.id for q in mark_scheme.questions])
                    progress_repo.set_stage(owned.id, "extract")
                    extracted = extract_answers(scan_path, mark_scheme, gemini_client=gemini_client)
                    # ... rest unchanged (binding check, grade_paper, persist, notify, complete frame) ...
        except UploadDeletedError as exc:
            bus.publish(EventType.ERROR, paper_id=payload.paperId, message=str(exc))
        except BindingHeldError as exc:
            # ... existing log ...
            progress_repo.stop_current(owned.id)
            bus.publish(EventType.ERROR, paper_id=payload.paperId, message=str(exc))
            upload_repo.set_status(owned.id, UploadStatus.failed)
        except Exception as exc:
            progress_repo.stop_current(owned.id)
            bus.publish(EventType.ERROR, paper_id=payload.paperId, message=str(exc))
            upload_repo.set_status(owned.id, UploadStatus.failed)
        finally:
            recorder.stop()
            bus.publish_done()

    return StreamingResponse(
        bus_event_stream(run, run_id=f"student:{payload.paperId}"),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
```
`recorder.stop()` runs before `publish_done()` so the final `complete` frame is written before the stream ends.

- [ ] **Step 8: Keep `test_student_correct.py` on its own database**

In the `client` fixture of `tests/test_student_correct.py`, add next to the other overrides:
```python
    from lemely.db.marking_progress_repo import MarkingProgressRepository
    from lemely.web.services.marking_progress import get_marking_progress_repo

    app.dependency_overrides[get_marking_progress_repo] = lambda: MarkingProgressRepository(
        pg_sessionmaker
    )
```
And add one test at the end of the file:
```python
def test_correct_records_progress_and_reuses_stored_metadata(
    client: tuple[TestClient, str, StudentUploadRepository],
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    from lemely.db.marking_progress_repo import MarkingProgressRepository

    api, _, upload_repo = client
    up = api.post("/api/student/uploads", files={"scan": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")})
    paper_id = up.json()["paperId"]
    stored = ExamMetadata(subject_code="0625", paper_number=1, paper_variant=2, session_month="May/June", session_year=2020)
    upload_repo.set_metadata(uuid.UUID(paper_id), stored)
    resp = api.post("/api/student/correct", json={"paperId": paper_id})
    assert resp.headers["x-accel-buffering"] == "no"
    snap = MarkingProgressRepository(pg_sessionmaker).get(uuid.UUID(paper_id))
    assert snap is not None
    assert snap.stage == "done"
    assert [q.id for q in snap.questions] == ["1", "2"]
    assert snap.done == 2
    assert upload_repo.get_metadata(uuid.UUID(paper_id)) == stored
```

- [ ] **Step 9: Run to verify pass**

Run: `pytest tests/test_marking_recorder.py tests/test_sse_heartbeat.py tests/test_student_correct.py tests/test_sse_server_only.py -v`
Expected: all passed (the existing `test_student_correct.py` tests stay green).

- [ ] **Step 10: Commit**

```bash
pre-commit run --files lemely/web/services/marking_progress.py lemely/web/sse.py lemely/db/upload_repo.py lemely/web/routers/student.py tests/test_student_correct.py tests/test_marking_recorder.py tests/test_sse_heartbeat.py
git commit -S -m "feat(web): record per-question marking progress and add SSE heartbeats" -- lemely/web/services/marking_progress.py lemely/web/sse.py lemely/db/upload_repo.py lemely/web/routers/student.py tests/test_student_correct.py tests/test_marking_recorder.py tests/test_sse_heartbeat.py
```

---

### Task 4: Schemas and the progress routes (JSON + SSE)

**Files:**
- Create: `lemely/web/schemas_marking.py`
- Create: `lemely/web/routers/marking.py`
- Modify: `lemely/web/services/marking_progress.py` (append `build_progress_dto`, `progress_event_stream`)
- Modify: `lemely/db/upload_repo.py` (`UploadDetail`, `get_detail`)
- Modify: `lemely/web/app.py` (import `marking` in the routers import, add `app.include_router(marking.router)` after `student.router`)
- Test: `tests/test_marking_routes.py`

**Interfaces:**
- Consumes: Tasks 2–3.
- Produces:
  - DTOs `TileQuestionDTO(id, state, blank: bool | None = None)`, `PaperFoundDTO`, `MarkingProgressDTO`, `DetectResultDTO`, `PaperChoiceDTO`, `PageCropDTO`, `RecentUploadDTO`, `RecentUploadsDTO`
  - `GET /api/marking/{paper_id}/progress -> MarkingProgressDTO` (student owner, or staff who can see the teacher paper; else 404)
  - `GET /api/marking/{paper_id}/events` → `text/event-stream`, frames `{"type":"progress","progress":{...}}`, `{"type":"reconnect"}`, `: ping`, `[DONE]`
  - `build_progress_dto(...)`, `progress_event_stream(load, *, poll_seconds=1.0, heartbeat_seconds=15.0, max_seconds=240.0, clock=time.monotonic, sleep=anyio.sleep, is_disconnected=None)`
  - `StudentUploadRepository.get_detail(*, user_id, upload_id) -> UploadDetail | None`
  - router helper `resolve_paper(paper_id, auth, upload_repo, teacher_repo) -> ResolvedPaper` (reused by Tasks 5–6)

- [ ] **Step 1: Write the failing tests**

```python
"""GET /api/marking/{id}/progress and /events (redesign L6)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import anyio
import pytest
from fastapi.testclient import TestClient

from lemely.db.marking_progress_repo import MarkingProgressRepository
from lemely.db.models.enums import Role, UploadStatus
from lemely.db.teacher_paper_repo import TeacherPaperRepository
from lemely.db.upload_repo import StudentUploadRepository
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_catalogue_service,
    get_student_upload_repo,
    get_teacher_paper_repo,
)
from lemely.web.schemas_marking import MarkingProgressDTO
from lemely.web.services.marking_progress import get_marking_progress_repo, progress_event_stream
from tests.marking_fixtures import (  # noqa: F401
    pg_sessionmaker,
    seed_teacher_paper,
    seed_upload,
    seed_user,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


class _NoCatalogue:
    def subjects(self) -> list[object]:
        return []


def _client(sm: sessionmaker[Session], user_id: uuid.UUID, role: Role) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user_id=str(user_id), role=role.value)
    app.dependency_overrides[get_student_upload_repo] = lambda: StudentUploadRepository(sm)
    app.dependency_overrides[get_teacher_paper_repo] = lambda: TeacherPaperRepository(sm, stale_after=timedelta(minutes=15))
    app.dependency_overrides[get_marking_progress_repo] = lambda: MarkingProgressRepository(sm)
    app.dependency_overrides[get_catalogue_service] = _NoCatalogue
    return TestClient(app)


def test_student_reads_own_progress(pg_sessionmaker: sessionmaker[Session]) -> None:  # noqa: F811
    sm = pg_sessionmaker
    student = seed_user(sm)
    pid = seed_upload(sm, student, status=UploadStatus.processing)
    repo = MarkingProgressRepository(sm)
    repo.reset(pid, owner_kind="student")
    repo.seed_questions(pid, ["1", "2", "3"])
    repo.mark_question(pid, "1")
    body = _client(sm, student, Role.student).get(f"/api/marking/{pid}/progress").json()
    assert body["status"] == "processing"
    assert body["stage"] == "mark"
    assert body["done"] == 1 and body["total"] == 3
    assert body["questions"][0] == {"id": "1", "state": "done", "blank": None}
    assert body["lost"] is False
    assert body["etaSeconds"] is None  # fewer than two questions marked


def test_foreign_student_gets_404(pg_sessionmaker: sessionmaker[Session]) -> None:  # noqa: F811
    sm = pg_sessionmaker
    pid = seed_upload(sm, seed_user(sm))
    other = seed_user(sm)
    assert _client(sm, other, Role.student).get(f"/api/marking/{pid}/progress").status_code == 404


def test_malformed_id_is_404(pg_sessionmaker: sessionmaker[Session]) -> None:  # noqa: F811
    sm = pg_sessionmaker
    assert _client(sm, seed_user(sm), Role.student).get("/api/marking/not-a-uuid/progress").status_code == 404


def test_parent_role_is_refused(pg_sessionmaker: sessionmaker[Session]) -> None:  # noqa: F811
    sm = pg_sessionmaker
    pid = seed_upload(sm, seed_user(sm))
    parent = seed_user(sm, Role.parent)
    assert _client(sm, parent, Role.parent).get(f"/api/marking/{pid}/progress").status_code == 403


def test_teacher_progress_comes_from_the_row(pg_sessionmaker: sessionmaker[Session]) -> None:  # noqa: F811
    sm = pg_sessionmaker
    teacher = seed_user(sm, Role.teacher)
    pid = seed_teacher_paper(
        sm, teacher, status=UploadStatus.processing, stage="mark", progress_index=5,
        progress_total=12, run_started_at=datetime.now(UTC),
    )
    body = _client(sm, teacher, Role.teacher).get(f"/api/marking/{pid}/progress").json()
    assert (body["stage"], body["done"], body["total"], body["questions"]) == ("mark", 5, 12, [])


def test_other_teacher_gets_404(pg_sessionmaker: sessionmaker[Session]) -> None:  # noqa: F811
    sm = pg_sessionmaker
    pid = seed_teacher_paper(sm, seed_user(sm, Role.teacher))
    other = seed_user(sm, Role.teacher)
    assert _client(sm, other, Role.teacher).get(f"/api/marking/{pid}/progress").status_code == 404


def test_no_scheme_stage_is_reported(pg_sessionmaker: sessionmaker[Session]) -> None:  # noqa: F811
    sm = pg_sessionmaker
    student = seed_user(sm)
    pid = seed_upload(sm, student, status=UploadStatus.failed)
    repo = MarkingProgressRepository(sm)
    repo.reset(pid, owner_kind="student")
    repo.set_stage(pid, "no_scheme")
    body = _client(sm, student, Role.student).get(f"/api/marking/{pid}/progress").json()
    assert (body["status"], body["stage"]) == ("failed", "no_scheme")


def test_events_endpoint_streams_a_terminal_frame(pg_sessionmaker: sessionmaker[Session]) -> None:  # noqa: F811
    sm = pg_sessionmaker
    student = seed_user(sm)
    pid = seed_upload(sm, student, status=UploadStatus.complete)
    resp = _client(sm, student, Role.student).get(f"/api/marking/{pid}/events")
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["x-accel-buffering"] == "no"
    frames = [f for f in resp.text.split("\n\n") if f]
    first = json.loads(frames[0].removeprefix("data: "))
    assert first["type"] == "progress" and first["progress"]["status"] == "complete"
    assert frames[-1] == "data: [DONE]"


def test_events_endpoint_404s_before_streaming(pg_sessionmaker: sessionmaker[Session]) -> None:  # noqa: F811
    sm = pg_sessionmaker
    pid = seed_upload(sm, seed_user(sm))
    resp = _client(sm, seed_user(sm), Role.student).get(f"/api/marking/{pid}/events")
    assert resp.status_code == 404


def _dto(status: str, done: int = 0) -> MarkingProgressDTO:
    return MarkingProgressDTO(
        paperId="p", status=status, stage="mark", lost=False, questions=[], done=done,
        total=3, etaSeconds=None, paper=None, error=None, missingPages=[],
    )


def _run_stream(dtos: list[MarkingProgressDTO], **kw: object) -> list[str]:
    it = iter(dtos)
    last = {"v": dtos[0]}

    def load() -> MarkingProgressDTO:
        last["v"] = next(it, last["v"])
        return last["v"]

    clock = {"t": 0.0}

    async def sleep(seconds: float) -> None:
        clock["t"] += seconds

    async def collect() -> list[str]:
        return [f async for f in progress_event_stream(load, clock=lambda: clock["t"], sleep=sleep, **kw)]  # type: ignore[arg-type]

    return anyio.run(collect)


def test_stream_sends_changes_only_and_ends_on_terminal() -> None:
    frames = _run_stream([_dto("processing", 1), _dto("processing", 1), _dto("processing", 2), _dto("complete", 3)])
    progress = [f for f in frames if f.startswith("data: {")]
    assert len(progress) == 3
    assert frames[-1] == "data: [DONE]\n\n"


def test_stream_heartbeats_and_reconnects() -> None:
    frames = _run_stream([_dto("processing", 1)], poll_seconds=5.0, heartbeat_seconds=15.0, max_seconds=40.0)
    assert ": ping\n\n" in frames
    assert 'data: {"type": "reconnect"}\n\n' in frames
    assert frames[-1] == "data: [DONE]\n\n"


@pytest.mark.parametrize("lost", [True])
def test_stream_ends_on_lost(lost: bool) -> None:
    dto = _dto("processing").model_copy(update={"lost": lost})
    frames = _run_stream([dto])
    assert frames[-1] == "data: [DONE]\n\n"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_marking_routes.py -v`
Expected: FAIL (`ModuleNotFoundError: lemely.web.schemas_marking`).

- [ ] **Step 3: Schemas (`lemely/web/schemas_marking.py`)**

```python
"""DTOs for marking progress, the paper check, PDFs and recent uploads (redesign L6)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

TileStateLiteral = Literal["waiting", "done", "missing", "stopped"]
StageLiteral = Literal["queued", "scheme", "extract", "mark", "done", "no_scheme"]
SessionMonthLiteral = Literal["May/June", "Oct/Nov", "Feb/Mar", "Specimen"]


class TileQuestionDTO(BaseModel):
    """One question on the marking board. L12 fills ``blank``; L6 leaves it ``None``."""

    id: str
    state: TileStateLiteral
    blank: bool | None = None


class PaperFoundDTO(BaseModel):
    subjectCode: str
    subjectName: str | None
    paperNumber: int
    variant: int
    sessionMonth: str
    sessionYear: int | None
    code: str  # "0580/42"


class MarkingProgressDTO(BaseModel):
    paperId: str
    status: Literal["pending", "processing", "complete", "failed"]
    stage: StageLiteral | None
    lost: bool
    questions: list[TileQuestionDTO]
    done: int
    total: int | None
    etaSeconds: int | None
    paper: PaperFoundDTO | None
    error: str | None
    missingPages: list[int]


class DetectResultDTO(BaseModel):
    paper: PaperFoundDTO | None
    schemeSource: Literal["own", "official", "none", "unknown"]


class PaperChoiceDTO(BaseModel):
    subjectCode: str = Field(pattern=r"^\d{4}$")
    paperNumber: int = Field(ge=1, le=9)
    variant: int = Field(ge=1, le=9)
    sessionMonth: SessionMonthLiteral
    sessionYear: int | None = Field(default=None, ge=2000, le=2100)


class PageCropDTO(BaseModel):
    """A saved crop: four corners as fractions of the photo (TL, TR, BR, BL) plus rotation."""

    page: int = Field(ge=1, le=200)
    corners: list[tuple[float, float]] = Field(min_length=4, max_length=4)
    rotation: Literal[0, 90, 180, 270] = 0

    @field_validator("corners")
    @classmethod
    def _inside_photo(cls, value: list[tuple[float, float]]) -> list[tuple[float, float]]:
        for x, y in value:
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise ValueError("corners must be fractions between 0 and 1")
        return value


class RecentUploadDTO(BaseModel):
    paperId: str
    title: str
    code: str | None
    uploadedAt: datetime
    papers: int
    kind: Literal["queued", "marking", "marked", "stopped", "no_scheme"]
    done: int | None
    total: int | None
    toReview: int | None
    namesNeedYou: int | None  # L12 fills this for class sets


class RecentUploadsDTO(BaseModel):
    uploads: list[RecentUploadDTO]
```

- [ ] **Step 4: Upload detail (append to `lemely/db/upload_repo.py`)**

```python
@dataclass(frozen=True, slots=True)
class UploadDetail:
    """What the marking routes read about one owned upload."""

    id: uuid.UUID
    status: UploadStatus
    original_filename: str | None
    content_type: str | None
    storage_path: str
    metadata: ExamMetadata | None
    updated_at: datetime
```
and the method on `StudentUploadRepository`:
```python
    def get_detail(self, *, user_id: str, upload_id: str) -> UploadDetail | None:
        """The caller-owned upload's detail, or ``None`` (malformed or foreign: one 404)."""
        owner = parse_user_id(user_id)
        try:
            target = uuid.UUID(upload_id)
        except (ValueError, AttributeError, TypeError):
            return None
        stmt = select(Upload).where(Upload.id == target, Upload.user_id == owner)
        with self._sm() as session:
            upload = session.scalars(stmt).one_or_none()
            if upload is None:
                return None
            return UploadDetail(
                id=upload.id,
                status=upload.status,
                original_filename=upload.original_filename,
                content_type=upload.content_type,
                storage_path=upload.storage_path,
                metadata=(
                    ExamMetadata.model_validate(upload.metadata_json)
                    if upload.metadata_json is not None
                    else None
                ),
                updated_at=upload.updated_at,
            )
```
Add `"UploadDetail"` to `__all__`.

- [ ] **Step 5: DTO builder and stream (append to the service)**

Extra imports at the top:
```python
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Literal

import anyio

from lemely.db.marking_progress_repo import ProgressSnapshot
from lemely.web.schemas_marking import MarkingProgressDTO, PaperFoundDTO, TileQuestionDTO
from lemely.web.sse import SSE_DONE_FRAME
```
Append:
```python
RunStatus = Literal["pending", "processing", "complete", "failed"]


def build_progress_dto(
    *,
    paper_id: str,
    status: RunStatus,
    lost: bool,
    snapshot: ProgressSnapshot | None,
    fallback_stage: str | None,
    counter: tuple[int, int] | None,
    paper: PaperFoundDTO | None,
    error: str | None,
    now: datetime,
) -> MarkingProgressDTO:
    """Assemble the progress DTO from the persisted row, or a teacher row's counter.

    A student run has a snapshot with per-question tiles. A teacher run has only the
    row's ``stage`` and ``(index, total)`` counter, so its board stays empty and the
    counts come from the counter. Nothing here is estimated except the ETA.
    """
    questions = list(snapshot.questions) if snapshot else []
    if questions:
        done, total = sum(1 for q in questions if q.state == "done"), len(questions)
    elif counter is not None:
        done, total = counter
    else:
        done, total = 0, None
    stage = snapshot.stage if snapshot and snapshot.stage else fallback_stage
    eta = (
        estimate_eta_seconds(
            done=done, total=total, mark_started_at=snapshot.mark_started_at, now=now
        )
        if snapshot and status == "processing" and not lost
        else None
    )
    return MarkingProgressDTO(
        paperId=paper_id,
        status=status,
        stage=stage,  # type: ignore[arg-type]
        lost=lost,
        questions=[TileQuestionDTO(id=q.id, state=q.state, blank=q.blank) for q in questions],
        done=done,
        total=total,
        etaSeconds=eta,
        paper=paper,
        error=error,
        missingPages=list(snapshot.missing_pages) if snapshot else [],
    )


async def progress_event_stream(
    load: Callable[[], MarkingProgressDTO],
    *,
    poll_seconds: float = 1.0,
    heartbeat_seconds: float = 15.0,
    max_seconds: float = 240.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
) -> AsyncIterator[str]:
    """Poll the persisted progress and stream changes as SSE (works on any instance).

    Sends a frame only when the DTO changed, ``: ping`` after ``heartbeat_seconds`` of
    silence (Cloudflare closes a response silent for 100 s), and closes itself with a
    ``reconnect`` frame after ``max_seconds`` (Cloud Run cuts a request at 300 s). Ends
    with ``[DONE]`` on a terminal or lost run.
    """
    started = last_write = clock()
    last_body: str | None = None
    while True:
        dto = await anyio.to_thread.run_sync(load)
        body = dto.model_dump_json()
        now = clock()
        if body != last_body:
            yield f'data: {{"type": "progress", "progress": {body}}}\n\n'
            last_body, last_write = body, now
        if dto.status in ("complete", "failed") or dto.lost:
            yield SSE_DONE_FRAME
            return
        if now - started >= max_seconds:
            yield f"data: {json.dumps({'type': 'reconnect'})}\n\n"
            yield SSE_DONE_FRAME
            return
        if now - last_write >= heartbeat_seconds:
            yield ": ping\n\n"
            last_write = now
        if is_disconnected is not None and await is_disconnected():
            return
        await sleep(poll_seconds)
```

- [ ] **Step 6: Router (`lemely/web/routers/marking.py`, first version)**

```python
"""Marking progress, paper check, PDF and teacher recent uploads (redesign L6).

Every route authorises through the table that owns the paper before reading
``marking_progress``: a student through ``uploads`` (owner only), staff through
``teacher_papers`` (DS11 visibility). Unknown, foreign and malformed ids are one 404.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal

import anyio
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from lemely.core.schemas import ExamMetadata
from lemely.db.catalogue_repo import CatalogueService
from lemely.db.history_repo import parse_user_id
from lemely.db.marking_progress_repo import MarkingProgressRepository
from lemely.db.models.enums import Role, UploadStatus
from lemely.db.teacher_paper_repo import TeacherPaperRepository
from lemely.db.upload_repo import StudentUploadRepository
from lemely.web.deps import (
    AuthContext,
    get_catalogue_service,
    get_student_upload_repo,
    get_teacher_paper_repo,
    require_role,
)
from lemely.web.routers.student import MARKING_RUN_STALE_AFTER
from lemely.web.routers.teacher import _QUEUED_STAGE, NO_SCHEME_MESSAGE
from lemely.web.schemas_marking import MarkingProgressDTO, PaperFoundDTO
from lemely.web.services.marking_progress import (
    build_progress_dto,
    get_marking_progress_repo,
    progress_event_stream,
)
from lemely.web.sse import SSE_HEADERS

router = APIRouter(prefix="/api")
log = structlog.get_logger(__name__)

STAFF_ROLES = (Role.teacher, Role.school_admin, Role.platform_admin)
_TEACHER_STAGES = {"scheme", "extract", "mark"}


@dataclass(frozen=True, slots=True)
class ResolvedPaper:
    paper_id: uuid.UUID
    owner_kind: Literal["student", "teacher"]
    status: UploadStatus
    lost: bool
    error: str | None
    metadata: ExamMetadata | None
    storage_path: str
    content_type: str | None
    original_filename: str | None
    teacher_stage: str | None
    counter: tuple[int, int] | None
    no_scheme: bool


def _not_found(paper_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Unknown paper: {paper_id}")


def resolve_paper(
    paper_id: str,
    auth: AuthContext,
    upload_repo: StudentUploadRepository,
    teacher_repo: TeacherPaperRepository,
) -> ResolvedPaper:
    """The paper the caller may read, or a 404."""
    role = Role(auth.role)
    if role is Role.student:
        detail = upload_repo.get_detail(user_id=auth.user_id, upload_id=paper_id)
        if detail is None:
            raise _not_found(paper_id)
        lost = (
            detail.status is UploadStatus.processing
            and datetime.now(UTC) - detail.updated_at > MARKING_RUN_STALE_AFTER
        )
        return ResolvedPaper(
            paper_id=detail.id, owner_kind="student", status=detail.status, lost=lost,
            error=None, metadata=detail.metadata, storage_path=detail.storage_path,
            content_type=detail.content_type, original_filename=detail.original_filename,
            teacher_stage=None, counter=None, no_scheme=False,
        )
    try:
        target = uuid.UUID(paper_id)
    except ValueError:
        raise _not_found(paper_id) from None
    row = teacher_repo.get_visible(target, viewer_id=parse_user_id(auth.user_id), viewer_role=role)
    if row is None:
        raise _not_found(paper_id)
    metadata = row.metadata or (row.report.correction.metadata if row.report else None)
    stage = "queued" if row.stage == _QUEUED_STAGE else row.stage if row.stage in _TEACHER_STAGES else None
    if row.status is UploadStatus.complete:
        stage = "done"
    return ResolvedPaper(
        paper_id=row.id, owner_kind="teacher", status=row.status, lost=row.stale,
        error=row.error, metadata=metadata, storage_path=row.storage_path,
        content_type=row.content_type, original_filename=row.original_filename,
        teacher_stage=stage, counter=row.progress, no_scheme=row.error == NO_SCHEME_MESSAGE,
    )


def paper_found(metadata: ExamMetadata, catalogue: CatalogueService) -> PaperFoundDTO:
    """The detected exam in display form. Subject name from the catalogue when offered."""
    name = next((s.name for s in catalogue.subjects() if s.code == metadata.subject_code), None)
    return PaperFoundDTO(
        subjectCode=metadata.subject_code,
        subjectName=name,
        paperNumber=metadata.paper_number,
        variant=metadata.paper_variant,
        sessionMonth=metadata.session_month,
        sessionYear=metadata.session_year,
        code=f"{metadata.subject_code}/{metadata.paper_number}{metadata.paper_variant}",
    )


def _load_progress(
    paper_id: str,
    auth: AuthContext,
    upload_repo: StudentUploadRepository,
    teacher_repo: TeacherPaperRepository,
    progress_repo: MarkingProgressRepository,
    catalogue: CatalogueService,
) -> MarkingProgressDTO:
    paper = resolve_paper(paper_id, auth, upload_repo, teacher_repo)
    snapshot = progress_repo.get(paper.paper_id)
    dto = build_progress_dto(
        paper_id=str(paper.paper_id),
        status=paper.status.value,  # type: ignore[arg-type]
        lost=paper.lost,
        snapshot=snapshot,
        fallback_stage=paper.teacher_stage,
        counter=paper.counter,
        paper=paper_found(paper.metadata, catalogue) if paper.metadata else None,
        error=paper.error,
        now=datetime.now(UTC),
    )
    if paper.no_scheme:
        dto = dto.model_copy(update={"stage": "no_scheme"})
    return dto


_ANY_READER = Depends(require_role(Role.student, *STAFF_ROLES))


@router.get("/marking/{paper_id}/progress", response_model=MarkingProgressDTO)
def marking_progress(
    paper_id: str,
    auth: Annotated[AuthContext, _ANY_READER],
    upload_repo: Annotated[StudentUploadRepository, Depends(get_student_upload_repo)],
    teacher_repo: Annotated[TeacherPaperRepository, Depends(get_teacher_paper_repo)],
    progress_repo: Annotated[MarkingProgressRepository, Depends(get_marking_progress_repo)],
    catalogue: Annotated[CatalogueService, Depends(get_catalogue_service)],
) -> MarkingProgressDTO:
    """Polling fallback: the run's progress right now."""
    return _load_progress(paper_id, auth, upload_repo, teacher_repo, progress_repo, catalogue)


@router.get("/marking/{paper_id}/events")
async def marking_events(
    paper_id: str,
    request: Request,
    auth: Annotated[AuthContext, _ANY_READER],
    upload_repo: Annotated[StudentUploadRepository, Depends(get_student_upload_repo)],
    teacher_repo: Annotated[TeacherPaperRepository, Depends(get_teacher_paper_repo)],
    progress_repo: Annotated[MarkingProgressRepository, Depends(get_marking_progress_repo)],
    catalogue: Annotated[CatalogueService, Depends(get_catalogue_service)],
) -> StreamingResponse:
    """Live progress over SSE. Authorised before streaming, so a foreign id is a plain 404."""

    def load() -> MarkingProgressDTO:
        return _load_progress(paper_id, auth, upload_repo, teacher_repo, progress_repo, catalogue)

    await anyio.to_thread.run_sync(load)
    return StreamingResponse(
        progress_event_stream(load, is_disconnected=request.is_disconnected),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
```
In `lemely/web/routers/teacher.py`, add above `_run_grading_job` and use it in the `repo.fail(...)` call that reports no scheme:
```python
#: The failure text for a paper with no resolvable mark scheme. The recent-uploads row
#: and the progress route compare against it to show "No mark scheme" rather than
#: "Marking stopped", so change the wording here, never at a call site.
NO_SCHEME_MESSAGE = (
    "No mark scheme could be resolved for this paper — nothing was marked. "
    "Attach one on upload, or add it under Mark schemes and re-run."
)
```
(the call becomes `repo.fail(paper_id, NO_SCHEME_MESSAGE)`; the text is byte-identical, so `test_teacher_paper_routes.py` and friends are unaffected).

- [ ] **Step 7: Run to verify pass**

Run: `pytest tests/test_marking_routes.py tests/test_teacher_paper_routes.py -v`
Expected: all passed.

- [ ] **Step 8: Commit**

```bash
pre-commit run --files lemely/web/schemas_marking.py lemely/web/routers/marking.py lemely/web/services/marking_progress.py lemely/db/upload_repo.py lemely/web/routers/teacher.py lemely/web/app.py tests/test_marking_routes.py
git commit -S -m "feat(web): marking progress over SSE with a polling fallback" -- lemely/web/schemas_marking.py lemely/web/routers/marking.py lemely/web/services/marking_progress.py lemely/db/upload_repo.py lemely/web/routers/teacher.py lemely/web/app.py tests/test_marking_routes.py
```

---

### Task 5: Paper check (detect, choose paper) and saved crops on upload

**Files:**
- Modify: `lemely/web/routers/marking.py` (append two routes and `_scheme_source`)
- Modify: `lemely/db/upload_repo.py` (`set_page_crops`)
- Modify: `lemely/db/teacher_paper_repo.py` (`set_page_crops`)
- Modify: `lemely/web/services/marking_progress.py` (append `parse_page_crops`)
- Modify: `lemely/web/routers/student.py` (`student_upload`: optional `crops` form field)
- Modify: `lemely/web/routers/teacher.py` (`upload_paper`: optional `crops` form field)
- Test: `tests/test_marking_detect.py`

**Interfaces:**
- Consumes: Task 4 `paper_found`, Task 3 `get_metadata`/`set_metadata`.
- Produces:
  - `POST /api/student/uploads/{paper_id}/detect -> DetectResultDTO` (student owner)
  - `PUT /api/student/uploads/{paper_id}/paper` body `PaperChoiceDTO` → `DetectResultDTO`
  - `crops` multipart field (JSON list of `PageCropDTO`) on `POST /api/student/uploads` and `POST /api/papers/upload`; 422 on bad JSON
  - `parse_page_crops(raw: str | None) -> list[PageCropDTO]`
  - `StudentUploadRepository.set_page_crops(upload_id, crops: list[dict[str, object]])` (also sets `page_count`); `TeacherPaperRepository.set_page_crops(paper_id, crops)`

- [ ] **Step 1: Write the failing tests**

```python
"""Paper check and saved crops (redesign L6)."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from lemely.core.schemas import ExamMetadata
from lemely.db.models.attempts import Upload
from lemely.db.models.enums import Role
from lemely.db.scheme_corpus_repo import SchemeCorpusRepository
from lemely.db.upload_repo import StudentUploadRepository
from lemely.io.gemini import GeminiClient
from lemely.runtime.config import Settings, load_settings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_catalogue_service,
    get_gemini_client,
    get_scheme_corpus_repo,
    get_settings,
    get_storage_backend,
    get_student_upload_repo,
)
from lemely.web.routers import marking
from lemely.web.services.marking_progress import parse_page_crops
from tests.marking_fixtures import pg_sessionmaker, seed_upload, seed_user  # noqa: F401
from tests.storage_fakes import FakeStorageBackend

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session, sessionmaker

META = ExamMetadata(subject_code="0580", paper_number=4, paper_variant=2, session_month="May/June", session_year=2025)


class _Catalogue:
    def subjects(self) -> list[object]:
        subject = MagicMock()
        subject.code, subject.name = "0580", "Mathematics"
        return [subject]


class _Corpus:
    def __init__(self, found: bool) -> None:
        self.found = found

    def find_for(self, metadata: ExamMetadata) -> object | None:
        return object() if self.found else None


def _settings(tmp_path: Path, *, key: bool) -> Settings:
    data = load_settings().model_dump()
    data["paths"]["output_dir"] = tmp_path / "out"
    if not key:
        data["gemini_api_key"] = None
        data["anthropic_api_key"] = None
    return Settings.model_validate(data)


def _client(sm: sessionmaker[Session], user: uuid.UUID, settings: Settings, storage: FakeStorageBackend, *, found: bool) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user_id=str(user), role="student")
    app.dependency_overrides[get_student_upload_repo] = lambda: StudentUploadRepository(sm)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_storage_backend] = lambda: storage
    app.dependency_overrides[get_scheme_corpus_repo] = lambda: _Corpus(found)
    app.dependency_overrides[get_catalogue_service] = _Catalogue
    app.dependency_overrides[get_gemini_client] = lambda: MagicMock(spec=GeminiClient)
    return TestClient(app)


def _store_scan(sm: sessionmaker[Session], storage: FakeStorageBackend, settings: Settings, pid: uuid.UUID) -> None:
    with sm() as session:
        path = session.get(Upload, pid).storage_path  # type: ignore[union-attr]
    storage.upload(settings.storage.bucket, path, b"%PDF-1.4 fake", "application/pdf")


def test_detect_runs_once_and_stores(pg_sessionmaker: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    sm, storage, settings = pg_sessionmaker, FakeStorageBackend(), _settings(tmp_path, key=True)
    student = seed_user(sm)
    pid = seed_upload(sm, student)
    _store_scan(sm, storage, settings, pid)
    calls: list[object] = []

    class FakeExtractor:
        def __init__(self, client: object) -> None: ...
        def __call__(self, path: object) -> ExamMetadata:
            calls.append(path)
            return META

    monkeypatch.setattr(marking, "ScanMetadataExtractor", FakeExtractor)
    monkeypatch.setattr(marking, "llm_key_configured", lambda *a, **k: True)
    api = _client(sm, student, settings, storage, found=True)
    first = api.post(f"/api/student/uploads/{pid}/detect").json()
    second = api.post(f"/api/student/uploads/{pid}/detect").json()
    assert first == second
    assert first["paper"]["code"] == "0580/42"
    assert first["paper"]["subjectName"] == "Mathematics"
    assert first["schemeSource"] == "official"
    assert len(calls) == 1  # second call reuses the stored metadata
    assert StudentUploadRepository(sm).get_metadata(pid) == META


def test_detect_without_a_key_is_unknown(pg_sessionmaker: sessionmaker[Session], tmp_path: Path) -> None:  # noqa: F811
    sm, storage, settings = pg_sessionmaker, FakeStorageBackend(), _settings(tmp_path, key=False)
    student = seed_user(sm)
    pid = seed_upload(sm, student)
    _store_scan(sm, storage, settings, pid)
    body = _client(sm, student, settings, storage, found=False).post(f"/api/student/uploads/{pid}/detect").json()
    assert body == {"paper": None, "schemeSource": "unknown"}


def test_own_scheme_wins(pg_sessionmaker: sessionmaker[Session], tmp_path: Path) -> None:  # noqa: F811
    sm, storage, settings = pg_sessionmaker, FakeStorageBackend(), _settings(tmp_path, key=False)
    student = seed_user(sm)
    pid = seed_upload(sm, student)
    _store_scan(sm, storage, settings, pid)
    storage.upload(settings.storage.bucket, f"uploads/{student}/{pid.hex}/mark_scheme.pdf", b"%PDF", "application/pdf")
    body = _client(sm, student, settings, storage, found=False).post(f"/api/student/uploads/{pid}/detect").json()
    assert body["schemeSource"] == "own"


def test_choose_paper_sets_metadata_and_reports_missing_scheme(pg_sessionmaker: sessionmaker[Session], tmp_path: Path) -> None:  # noqa: F811
    sm, storage, settings = pg_sessionmaker, FakeStorageBackend(), _settings(tmp_path, key=False)
    student = seed_user(sm)
    pid = seed_upload(sm, student)
    _store_scan(sm, storage, settings, pid)
    body = _client(sm, student, settings, storage, found=False).put(
        f"/api/student/uploads/{pid}/paper",
        json={"subjectCode": "0580", "paperNumber": 4, "variant": 2, "sessionMonth": "Oct/Nov", "sessionYear": 2025},
    ).json()
    assert body["paper"]["code"] == "0580/42"
    assert body["schemeSource"] == "none"
    assert StudentUploadRepository(sm).get_metadata(pid).session_month == "Oct/Nov"  # type: ignore[union-attr]


def test_detect_foreign_upload_404(pg_sessionmaker: sessionmaker[Session], tmp_path: Path) -> None:  # noqa: F811
    sm, storage, settings = pg_sessionmaker, FakeStorageBackend(), _settings(tmp_path, key=False)
    pid = seed_upload(sm, seed_user(sm))
    resp = _client(sm, seed_user(sm), settings, storage, found=False).post(f"/api/student/uploads/{pid}/detect")
    assert resp.status_code == 404


def test_choose_paper_validates(pg_sessionmaker: sessionmaker[Session], tmp_path: Path) -> None:  # noqa: F811
    sm, storage, settings = pg_sessionmaker, FakeStorageBackend(), _settings(tmp_path, key=False)
    student = seed_user(sm)
    pid = seed_upload(sm, student)
    resp = _client(sm, student, settings, storage, found=False).put(
        f"/api/student/uploads/{pid}/paper",
        json={"subjectCode": "58", "paperNumber": 4, "variant": 2, "sessionMonth": "May/June"},
    )
    assert resp.status_code == 422


def test_upload_saves_crops_and_page_count(pg_sessionmaker: sessionmaker[Session], tmp_path: Path) -> None:  # noqa: F811
    sm, storage, settings = pg_sessionmaker, FakeStorageBackend(), _settings(tmp_path, key=False)
    student = seed_user(sm)
    crops = [{"page": 1, "corners": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]], "rotation": 90}]
    api = _client(sm, student, settings, storage, found=False)
    resp = api.post(
        "/api/student/uploads",
        files={"scan": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"crops": json.dumps(crops)},
    )
    assert resp.status_code == 200, resp.text
    with sm() as session:
        row = session.get(Upload, uuid.UUID(resp.json()["paperId"]))
        assert row is not None and row.page_crops == crops and row.page_count == 1


def test_upload_refuses_bad_crops(pg_sessionmaker: sessionmaker[Session], tmp_path: Path) -> None:  # noqa: F811
    sm, storage, settings = pg_sessionmaker, FakeStorageBackend(), _settings(tmp_path, key=False)
    api = _client(sm, seed_user(sm), settings, storage, found=False)
    resp = api.post(
        "/api/student/uploads",
        files={"scan": ("scan.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"crops": json.dumps([{"page": 1, "corners": [[2, 0], [1, 0], [1, 1], [0, 1]]}])},
    )
    assert resp.status_code == 422


def test_parse_page_crops() -> None:
    assert parse_page_crops(None) == []
    assert parse_page_crops("") == []
    with pytest.raises(ValueError, match="crops"):
        parse_page_crops("{not json")
```

`check_scan_geometry` runs on `b"%PDF-1.4 fake"` in the existing `test_student_correct.py` uploads, so it passes these bytes too (unreadable bytes pass, `upload_utils.py:95-110`).

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_marking_detect.py -v`
Expected: FAIL (404 on the detect route, `ImportError: parse_page_crops`).

- [ ] **Step 3: `parse_page_crops` (append to the service)**

```python
from pydantic import TypeAdapter, ValidationError

from lemely.web.schemas_marking import PageCropDTO

_CROPS = TypeAdapter(list[PageCropDTO])
MAX_PAGES = 60


def parse_page_crops(raw: str | None) -> list[PageCropDTO]:
    """Parse the ``crops`` multipart field. Empty means "no crops saved"."""
    if raw is None or raw.strip() == "":
        return []
    try:
        crops = _CROPS.validate_json(raw)
    except ValidationError as exc:
        raise ValueError(f"Malformed crops: {exc.errors()[0]['msg']}") from exc
    if len(crops) > MAX_PAGES:
        raise ValueError(f"Too many crops: at most {MAX_PAGES} pages")
    return crops
```

- [ ] **Step 4: Repo methods**

`StudentUploadRepository`:
```python
    def set_page_crops(self, upload_id: uuid.UUID, crops: list[dict[str, object]]) -> None:
        """Save the per-page crops and the page count they imply."""
        with self._sm.begin() as session:
            upload = session.get(Upload, upload_id)
            if upload is not None:
                upload.page_crops = crops
                upload.page_count = len(crops) or upload.page_count
```
`TeacherPaperRepository` (next to `set_metadata`):
```python
    def set_page_crops(self, paper_id: uuid.UUID, crops: list[dict[str, object]]) -> None:
        """Save the per-page crops a teacher's phone capture produced."""
        with self._sm.begin() as session:
            row = session.get(TeacherPaper, paper_id)
            if row is not None:
                row.page_crops = crops
```

- [ ] **Step 5: Crops on the two upload routes**

`student_upload` (`routers/student.py`): add `Form` to the `fastapi` import and the parameter `crops: Annotated[str | None, Form()] = None` after `mark_scheme`. At the top of the body, before any storage write:
```python
    try:
        page_crops = parse_page_crops(crops)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```
After `new_id = upload_repo.create_upload(...)`, only when this call created the row:
```python
    if new_id == paper_id and page_crops:
        upload_repo.set_page_crops(new_id, [c.model_dump(mode="json") for c in page_crops])
```
Import `parse_page_crops` from `lemely.web.services.marking_progress`.

`upload_paper` (`routers/teacher.py`): same parameter, same parse at the top, and after `repo.create(...)`:
```python
    if page_crops:
        repo.set_page_crops(paper_id, [c.model_dump(mode="json") for c in page_crops])
```

- [ ] **Step 6: Detect and choose routes (append to `routers/marking.py`)**

Add imports:
```python
import tempfile
from pathlib import Path

from lemely.core.object_keys import sibling_scheme_key
from lemely.db.scheme_corpus_repo import SchemeCorpusRepository
from lemely.io.gemini import GeminiClient, script_cost_scope
from lemely.io.scan_metadata import ScanMetadataExtractor
from lemely.io.storage import StorageBackend, StorageObjectNotFoundError
from lemely.runtime.config import Settings, llm_key_configured
from lemely.web.deps import get_gemini_client, get_scheme_corpus_repo, get_settings, get_storage_backend
from lemely.web.schemas_marking import DetectResultDTO, PaperChoiceDTO
```
Append:
```python
SchemeSource = Literal["own", "official", "none", "unknown"]


def _scheme_source(
    storage_path: str,
    metadata: ExamMetadata | None,
    storage: StorageBackend,
    settings: Settings,
    corpus: SchemeCorpusRepository,
) -> SchemeSource:
    """Where marking will take its scheme from: the student's own, the corpus, or nowhere."""
    try:
        storage.download(settings.storage.bucket, sibling_scheme_key(storage_path))
    except StorageObjectNotFoundError:
        pass
    else:
        return "own"
    if metadata is None:
        return "unknown"
    return "official" if corpus.find_for(metadata) is not None else "none"


@router.post("/student/uploads/{paper_id}/detect", response_model=DetectResultDTO)
def detect_paper(
    paper_id: str,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    settings: Annotated[Settings, Depends(get_settings)],
    upload_repo: Annotated[StudentUploadRepository, Depends(get_student_upload_repo)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
    corpus: Annotated[SchemeCorpusRepository, Depends(get_scheme_corpus_repo)],
    catalogue: Annotated[CatalogueService, Depends(get_catalogue_service)],
    gemini_client: Annotated[GeminiClient, Depends(get_gemini_client)],
) -> DetectResultDTO:
    """Read which exam this is, once. ``def`` (threadpool): the model call blocks.

    Logged under the same cost key as the marking run (``upload:{id}``), and stored so
    ``POST /student/correct`` does not detect again: a paper still costs one detection.
    A failed or unavailable detection is not an error; the screen then asks the student.
    """
    detail = upload_repo.get_detail(user_id=auth.user_id, upload_id=paper_id)
    if detail is None:
        raise _not_found(paper_id)
    metadata = detail.metadata
    if metadata is None and llm_key_configured(settings, "scan_metadata"):
        with tempfile.TemporaryDirectory() as tmp:
            scan_path = Path(tmp) / Path(detail.storage_path).name
            scan_path.write_bytes(storage.download(settings.storage.bucket, detail.storage_path))
            try:
                with script_cost_scope(settings, script_key=f"upload:{detail.id}"):
                    metadata = ScanMetadataExtractor(gemini_client)(scan_path)
            except Exception:
                log.warning("paper_detect_failed", paper_id=str(detail.id), exc_info=True)
                metadata = None
        if metadata is not None:
            upload_repo.set_metadata(detail.id, metadata)
    return DetectResultDTO(
        paper=paper_found(metadata, catalogue) if metadata else None,
        schemeSource=_scheme_source(detail.storage_path, metadata, storage, settings, corpus),
    )


@router.put("/student/uploads/{paper_id}/paper", response_model=DetectResultDTO)
def choose_paper(
    paper_id: str,
    choice: PaperChoiceDTO,
    auth: Annotated[AuthContext, Depends(require_role(Role.student))],
    settings: Annotated[Settings, Depends(get_settings)],
    upload_repo: Annotated[StudentUploadRepository, Depends(get_student_upload_repo)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
    corpus: Annotated[SchemeCorpusRepository, Depends(get_scheme_corpus_repo)],
    catalogue: Annotated[CatalogueService, Depends(get_catalogue_service)],
) -> DetectResultDTO:
    """"No, change it": the student names the paper; marking then uses this, not detection."""
    detail = upload_repo.get_detail(user_id=auth.user_id, upload_id=paper_id)
    if detail is None:
        raise _not_found(paper_id)
    metadata = ExamMetadata(
        subject_code=choice.subjectCode,
        paper_number=choice.paperNumber,
        paper_variant=choice.variant,
        session_month=choice.sessionMonth,
        session_year=choice.sessionYear,
    )
    upload_repo.set_metadata(detail.id, metadata)
    return DetectResultDTO(
        paper=paper_found(metadata, catalogue),
        schemeSource=_scheme_source(detail.storage_path, metadata, storage, settings, corpus),
    )
```
Before implementing, read `script_cost_scope` (`lemely/io/gemini.py:347-370`) and confirm the cost log line carries `script_key`, so the detection and marking lines for one paper add up by key. If it does not, stop and report.

- [ ] **Step 7: Run to verify pass**

Run: `pytest tests/test_marking_detect.py tests/test_student_correct.py tests/test_teacher_paper_routes.py -v`
Expected: all passed.

- [ ] **Step 8: Commit**

```bash
pre-commit run --files lemely/web/routers/marking.py lemely/db/upload_repo.py lemely/db/teacher_paper_repo.py lemely/web/services/marking_progress.py lemely/web/routers/student.py lemely/web/routers/teacher.py tests/test_marking_detect.py
git commit -S -m "feat(web): paper check before marking and saved page crops" -- lemely/web/routers/marking.py lemely/db/upload_repo.py lemely/db/teacher_paper_repo.py lemely/web/services/marking_progress.py lemely/web/routers/student.py lemely/web/routers/teacher.py tests/test_marking_detect.py
```

---

### Task 6: Server-side PDF download

**Files:**
- Modify: `lemely/web/services/marking_progress.py` (append `scan_bytes_as_pdf`, `pdf_filename`)
- Modify: `lemely/web/routers/marking.py` (append `GET /marking/{paper_id}/pdf`)
- Test: `tests/test_marking_pdf.py`

**Interfaces:**
- Produces: `GET /api/marking/{paper_id}/pdf` → `application/pdf`, `Content-Disposition: attachment; filename="0580-42-scan.pdf"`; `scan_bytes_as_pdf(data: bytes, content_type: str | None) -> bytes` (raises `ValueError` for unreadable bytes → 415); `pdf_filename(metadata: ExamMetadata | None) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
"""GET /api/marking/{id}/pdf: the stored scan as one PDF (redesign L6)."""

from __future__ import annotations

import io
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lemely.core.schemas import ExamMetadata
from lemely.db.models.attempts import Upload
from lemely.db.models.enums import Role
from lemely.db.teacher_paper_repo import TeacherPaperRepository
from lemely.db.upload_repo import StudentUploadRepository
from lemely.runtime.config import load_settings
from lemely.web import create_app
from lemely.web.deps import (
    AuthContext,
    get_auth_context,
    get_settings,
    get_storage_backend,
    get_student_upload_repo,
    get_teacher_paper_repo,
)
from lemely.web.services.marking_progress import pdf_filename, scan_bytes_as_pdf
from tests.marking_fixtures import pg_sessionmaker, seed_upload, seed_user  # noqa: F401
from tests.storage_fakes import FakeStorageBackend

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 60), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_pdf_passes_through() -> None:
    assert scan_bytes_as_pdf(b"%PDF-1.7 body", "application/pdf") == b"%PDF-1.7 body"


def test_image_becomes_pdf() -> None:
    out = scan_bytes_as_pdf(_png(), "image/png")
    assert out.startswith(b"%PDF")


def test_garbage_is_refused() -> None:
    with pytest.raises(ValueError, match="readable"):
        scan_bytes_as_pdf(b"nope", "image/png")


def test_filename() -> None:
    meta = ExamMetadata(subject_code="0580", paper_number=4, paper_variant=2, session_month="May/June")
    assert pdf_filename(meta) == "0580-42-scan.pdf"
    assert pdf_filename(None) == "scan.pdf"


def test_route_downloads_own_scan_only(pg_sessionmaker: sessionmaker[Session]) -> None:  # noqa: F811
    sm, storage, settings = pg_sessionmaker, FakeStorageBackend(), load_settings()
    student = seed_user(sm)
    pid = seed_upload(sm, student, content_type="image/png", filename="page.png")
    with sm() as session:
        path = session.get(Upload, pid).storage_path  # type: ignore[union-attr]
    storage.upload(settings.storage.bucket, path, _png(), "image/png")

    def client(user: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_auth_context] = lambda: AuthContext(user_id=str(user), role=Role.student.value)
        app.dependency_overrides[get_student_upload_repo] = lambda: StudentUploadRepository(sm)
        app.dependency_overrides[get_teacher_paper_repo] = lambda: TeacherPaperRepository(sm, stale_after=timedelta(minutes=15))
        app.dependency_overrides[get_storage_backend] = lambda: storage
        app.dependency_overrides[get_settings] = lambda: settings
        return TestClient(app)

    resp = client(student).get(f"/api/marking/{pid}/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-disposition"] == 'attachment; filename="scan.pdf"'
    assert resp.headers["cache-control"] == "private, no-store"
    assert resp.content.startswith(b"%PDF")
    assert client(seed_user(sm)).get(f"/api/marking/{pid}/pdf").status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_marking_pdf.py -v`
Expected: FAIL (`ImportError: scan_bytes_as_pdf`).

- [ ] **Step 3: Implement**

Service (append; add `import io` and `from PIL import Image, UnidentifiedImageError` and `from lemely.core.schemas import ExamMetadata`):
```python
def scan_bytes_as_pdf(data: bytes, content_type: str | None) -> bytes:
    """The stored scan as a PDF: a PDF as-is, an image converted page-for-page.

    Uploads already passed ``check_scan_geometry``, so Pillow's own decompression-bomb
    guard is a second line, not the only one.
    """
    if data.startswith(b"%PDF") or content_type == "application/pdf":
        return data
    try:
        with Image.open(io.BytesIO(data)) as image:
            frames = []
            for index in range(getattr(image, "n_frames", 1)):
                image.seek(index)
                frames.append(image.convert("RGB"))
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("The stored scan is not a readable image or PDF") from exc
    out = io.BytesIO()
    frames[0].save(out, format="PDF", save_all=True, append_images=frames[1:], resolution=150)
    return out.getvalue()


def pdf_filename(metadata: ExamMetadata | None) -> str:
    if metadata is None:
        return "scan.pdf"
    return f"{metadata.subject_code}-{metadata.paper_number}{metadata.paper_variant}-scan.pdf"
```
Router (append; add `from fastapi import Response` and the service names):
```python
@router.get("/marking/{paper_id}/pdf")
def marking_pdf(
    paper_id: str,
    auth: Annotated[AuthContext, _ANY_READER],
    settings: Annotated[Settings, Depends(get_settings)],
    upload_repo: Annotated[StudentUploadRepository, Depends(get_student_upload_repo)],
    teacher_repo: Annotated[TeacherPaperRepository, Depends(get_teacher_paper_repo)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
) -> Response:
    """Download PDF: the scan the server holds, as one PDF, for its owner or visible staff."""
    paper = resolve_paper(paper_id, auth, upload_repo, teacher_repo)
    data = storage.download(settings.storage.bucket, paper.storage_path)
    try:
        pdf = scan_bytes_as_pdf(data, paper.content_type)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{pdf_filename(paper.metadata)}"',
            "Cache-Control": "private, no-store",
        },
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_marking_pdf.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lemely/web/services/marking_progress.py lemely/web/routers/marking.py tests/test_marking_pdf.py
git commit -S -m "feat(web): server-side PDF of a stored scan" -- lemely/web/services/marking_progress.py lemely/web/routers/marking.py tests/test_marking_pdf.py
```

---

### Task 7: Teacher recent uploads

**Files:**
- Modify: `lemely/web/services/marking_progress.py` (append `recent_upload_dto`)
- Modify: `lemely/web/routers/marking.py` (append `GET /teacher/uploads/recent`)
- Test: `tests/test_teacher_recent_uploads.py`

**Interfaces:**
- Produces: `GET /api/teacher/uploads/recent?limit=10 -> RecentUploadsDTO` (staff only, DS11-visible papers, newest first); `recent_upload_dto(row: TeacherPaperRow) -> RecentUploadDTO`.

- [ ] **Step 1: Write the failing tests**

```python
"""GET /api/teacher/uploads/recent (redesign L6)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from lemely.db.models.enums import Role, UploadStatus
from lemely.db.teacher_paper_repo import TeacherPaperRepository
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_teacher_paper_repo
from lemely.web.routers.teacher import NO_SCHEME_MESSAGE
from tests.marking_fixtures import pg_sessionmaker, seed_teacher_paper, seed_user  # noqa: F401

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


def _client(sm: sessionmaker[Session], user: uuid.UUID, role: Role) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user_id=str(user), role=role.value)
    app.dependency_overrides[get_teacher_paper_repo] = lambda: TeacherPaperRepository(sm, stale_after=timedelta(minutes=15))
    return TestClient(app)


def test_rows_map_each_state(pg_sessionmaker: sessionmaker[Session]) -> None:  # noqa: F811
    sm = pg_sessionmaker
    t = seed_user(sm, Role.teacher)
    now = datetime.now(UTC)
    seed_teacher_paper(sm, t, original_filename="a.pdf", status=UploadStatus.pending)
    seed_teacher_paper(sm, t, original_filename="b.pdf", status=UploadStatus.processing, stage="queued", run_started_at=now)
    seed_teacher_paper(sm, t, original_filename="c.pdf", status=UploadStatus.processing, stage="mark", progress_index=8, progress_total=14, run_started_at=now)
    seed_teacher_paper(sm, t, original_filename="d.pdf", status=UploadStatus.failed, error="Grading failed: boom")
    seed_teacher_paper(sm, t, original_filename="e.pdf", status=UploadStatus.failed, error=NO_SCHEME_MESSAGE)
    rows = {r["title"]: r for r in _client(sm, t, Role.teacher).get("/api/teacher/uploads/recent").json()["uploads"]}
    assert rows["a.pdf"]["kind"] == "queued"
    assert rows["b.pdf"]["kind"] == "queued"
    assert (rows["c.pdf"]["kind"], rows["c.pdf"]["done"], rows["c.pdf"]["total"]) == ("marking", 8, 14)
    assert rows["d.pdf"]["kind"] == "stopped"
    assert rows["e.pdf"]["kind"] == "no_scheme"
    assert all(r["papers"] == 1 and r["namesNeedYou"] is None for r in rows.values())


def test_limit_and_visibility(pg_sessionmaker: sessionmaker[Session]) -> None:  # noqa: F811
    sm = pg_sessionmaker
    t, other = seed_user(sm, Role.teacher), seed_user(sm, Role.teacher)
    for _ in range(3):
        seed_teacher_paper(sm, t)
    seed_teacher_paper(sm, other)
    body = _client(sm, t, Role.teacher).get("/api/teacher/uploads/recent?limit=2").json()
    assert len(body["uploads"]) == 2


def test_students_are_refused(pg_sessionmaker: sessionmaker[Session]) -> None:  # noqa: F811
    sm = pg_sessionmaker
    s = seed_user(sm, Role.student)
    assert _client(sm, s, Role.student).get("/api/teacher/uploads/recent").status_code == 403
```
Add one pure test for the `marked` mapping in the same file:
```python
def test_marked_counts_review_items() -> None:
    from unittest.mock import MagicMock

    from lemely.web.services.marking_progress import recent_upload_dto

    q_ok, q_review = MagicMock(), MagicMock()
    row = MagicMock()
    row.id, row.original_filename, row.created_at = uuid.uuid4(), "f.pdf", datetime.now(UTC)
    row.status, row.stale, row.error, row.stage, row.progress = UploadStatus.complete, False, None, "mark", None
    row.metadata = None
    row.report.correction.questions = [q_ok, q_review]
    row.report.correction.metadata.subject_code, row.report.correction.metadata.paper_number = "0580", 4
    row.report.correction.metadata.paper_variant = 2
    import lemely.web.services.marking_progress as svc

    original = svc.review_reasons_for
    svc.review_reasons_for = lambda q: iter(["low"]) if q is q_review else iter([])  # type: ignore[assignment]
    try:
        dto = recent_upload_dto(row)
    finally:
        svc.review_reasons_for = original  # type: ignore[assignment]
    assert (dto.kind, dto.toReview, dto.code) == ("marked", 1, "0580/42")
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_teacher_recent_uploads.py -v`
Expected: FAIL (404 route, ImportError).

- [ ] **Step 3: Implement**

Service (append; imports `from lemely.db.review_queue_rules import review_reasons_for`, `from lemely.db.teacher_paper_repo import TeacherPaperRow`, `from lemely.db.models.enums import UploadStatus`, `from lemely.web.schemas_marking import RecentUploadDTO`). Import `NO_SCHEME_MESSAGE` and `_QUEUED_STAGE` lazily inside the function to avoid a router↔service cycle:
```python
def recent_upload_dto(row: TeacherPaperRow) -> RecentUploadDTO:
    """One teacher upload as a recent-uploads row. ``namesNeedYou`` is L12's to fill."""
    from lemely.web.routers.teacher import _QUEUED_STAGE, NO_SCHEME_MESSAGE

    metadata = row.metadata or (row.report.correction.metadata if row.report else None)
    code = (
        f"{metadata.subject_code}/{metadata.paper_number}{metadata.paper_variant}"
        if metadata
        else None
    )
    done: int | None = None
    total: int | None = None
    to_review: int | None = None
    if row.report is not None and row.status is UploadStatus.complete:
        kind = "marked"
        to_review = sum(
            1 for q in row.report.correction.questions if next(review_reasons_for(q), None) is not None
        )
    elif row.stale or row.status is UploadStatus.failed:
        kind = "no_scheme" if row.error == NO_SCHEME_MESSAGE else "stopped"
    elif row.status is UploadStatus.processing and row.stage != _QUEUED_STAGE:
        kind = "marking"
        if row.progress is not None:
            done, total = row.progress
    else:
        kind = "queued"
    return RecentUploadDTO(
        paperId=str(row.id),
        title=row.original_filename or "Scan",
        code=code,
        uploadedAt=row.created_at,
        papers=1,
        kind=kind,  # type: ignore[arg-type]
        done=done,
        total=total,
        toReview=to_review,
        namesNeedYou=None,
    )
```
Router (append; `from fastapi import Query`; `from lemely.web.schemas_marking import RecentUploadsDTO`; `recent_upload_dto` from the service):
```python
@router.get("/teacher/uploads/recent", response_model=RecentUploadsDTO)
def recent_uploads(
    auth: Annotated[AuthContext, Depends(require_role(*STAFF_ROLES))],
    repo: Annotated[TeacherPaperRepository, Depends(get_teacher_paper_repo)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> RecentUploadsDTO:
    """The teacher's latest uploads with their marking state (DS11 visibility, newest first)."""
    rows = repo.list_visible(viewer_id=parse_user_id(auth.user_id), viewer_role=Role(auth.role))
    return RecentUploadsDTO(uploads=[recent_upload_dto(r) for r in rows[:limit]])
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_teacher_recent_uploads.py tests/test_marking_routes.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lemely/web/services/marking_progress.py lemely/web/routers/marking.py tests/test_teacher_recent_uploads.py
git commit -S -m "feat(web): teacher recent uploads with marking state" -- lemely/web/services/marking_progress.py lemely/web/routers/marking.py tests/test_teacher_recent_uploads.py
```

---

Frontend data tasks (8–13) go to the `implementer` agent. Run Vitest from `web/`: `npx vitest run tests/unit/<file>`.

### Task 8: Types, API functions and query hooks

**Files:**
- Create: `web/src/lib/markingTypes.ts`, `web/src/lib/markingApi.ts`, `web/src/lib/hooks/useMarkingApi.ts`
- Test: `web/tests/unit/markingApiShape.test.ts`

**Interfaces:**
- Produces (TS):
  - `TileQuestion { id: string; state: "waiting" | "done" | "missing" | "stopped"; blank?: boolean | null }`
  - `PaperFound`, `SchemeSource`, `DetectResult`, `ProgressStage`, `MarkingProgress`, `MarkingStreamFrame`, `PaperChoice`, `PageCrop`, `RecentUpload`, `RecentUploadList`
  - `getMarkingProgress(id)`, `streamMarkingProgress(id, signal?)`, `detectPaper(id)`, `choosePaper(id, choice)`, `fetchMarkingPdf(id) -> Promise<string>` (object URL), `getRecentUploads(limit?)`, `uploadStudentScan(scan, opts)`, `uploadTeacherScan(scan, opts)`
  - `markingKeys.progress(id)`, `markingKeys.recent`; hooks `useMarkingProgress(id)`, `useDetectPaper()`, `useChoosePaper()`, `useRecentUploads()`

- [ ] **Step 1: Write the failing test**

```ts
import { beforeEach, describe, expect, it, vi } from "vitest"

const request = vi.fn()
const streamActivity = vi.fn()
const uploadWithProgress = vi.fn()
const fetchBlobUrl = vi.fn()
vi.mock("@/lib/api", () => ({ request, streamActivity, uploadWithProgress, fetchBlobUrl }))

const api = await import("@/lib/markingApi")

describe("markingApi paths", () => {
  beforeEach(() => {
    request.mockReset().mockResolvedValue({})
    streamActivity.mockReset()
    uploadWithProgress.mockReset().mockResolvedValue({ paperId: "p1" })
    fetchBlobUrl.mockReset().mockResolvedValue("blob:x")
  })

  it("reads progress and opens the events stream with GET", () => {
    void api.getMarkingProgress("a/b")
    expect(request).toHaveBeenCalledWith("/marking/a%2Fb/progress")
    const signal = new AbortController().signal
    api.streamMarkingProgress("p1", signal)
    expect(streamActivity).toHaveBeenCalledWith("/marking/p1/events", { method: "GET", signal })
  })

  it("detects and chooses the paper", () => {
    void api.detectPaper("p1")
    expect(request).toHaveBeenCalledWith("/student/uploads/p1/detect", { method: "POST" })
    const choice = { subjectCode: "0580", paperNumber: 4, variant: 2, sessionMonth: "May/June" as const, sessionYear: 2025 }
    void api.choosePaper("p1", choice)
    expect(request).toHaveBeenLastCalledWith("/student/uploads/p1/paper", {
      method: "PUT",
      body: JSON.stringify(choice),
      headers: { "Content-Type": "application/json" },
    })
  })

  it("uploads with crops, scheme and the idempotency key", async () => {
    const scan = new File(["%PDF"], "scan.pdf", { type: "application/pdf" })
    const scheme = new File(["%PDF"], "ms.pdf", { type: "application/pdf" })
    const crops = [{ page: 1, corners: [[0, 0], [1, 0], [1, 1], [0, 1]] as [number, number][], rotation: 0 as const }]
    await api.uploadStudentScan(scan, { markScheme: scheme, crops, idempotencyKey: "key-12345678" })
    const [path, form, opts] = uploadWithProgress.mock.calls[0]
    expect(path).toBe("/student/uploads")
    expect((form as FormData).get("scan")).toBe(scan)
    expect((form as FormData).get("mark_scheme")).toBe(scheme)
    expect((form as FormData).get("crops")).toBe(JSON.stringify(crops))
    expect(opts.headers).toEqual({ "Idempotency-Key": "key-12345678" })
    await api.uploadTeacherScan(scan, {})
    expect(uploadWithProgress.mock.calls[1][0]).toBe("/papers/upload")
    expect((uploadWithProgress.mock.calls[1][1] as FormData).get("crops")).toBeNull()
  })

  it("fetches the PDF and recent uploads", () => {
    void api.fetchMarkingPdf("p1")
    expect(fetchBlobUrl).toHaveBeenCalledWith("/marking/p1/pdf")
    void api.getRecentUploads()
    expect(request).toHaveBeenLastCalledWith("/teacher/uploads/recent?limit=10")
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run tests/unit/markingApiShape.test.ts`
Expected: FAIL (cannot resolve `@/lib/markingApi`).

- [ ] **Step 3: `web/src/lib/markingTypes.ts`**

```ts
/* Wire types for marking progress, the paper check and recent uploads (redesign L6).
 * Mirrors lemely/web/schemas_marking.py field for field. */

/** One question on the board. `blank` is filled by L12; L6 never sets it. */
export interface TileQuestion {
  id: string
  state: "waiting" | "done" | "missing" | "stopped"
  blank?: boolean | null
}

export interface PaperFound {
  subjectCode: string
  subjectName: string | null
  paperNumber: number
  variant: number
  sessionMonth: string
  sessionYear: number | null
  /** "0580/42" */
  code: string
}

export type SchemeSource = "own" | "official" | "none" | "unknown"

export interface DetectResult {
  paper: PaperFound | null
  schemeSource: SchemeSource
}

export type ProgressStage = "queued" | "scheme" | "extract" | "mark" | "done" | "no_scheme"

export interface MarkingProgress {
  paperId: string
  status: "pending" | "processing" | "complete" | "failed"
  stage: ProgressStage | null
  lost: boolean
  questions: TileQuestion[]
  done: number
  total: number | null
  etaSeconds: number | null
  paper: PaperFound | null
  error: string | null
  missingPages: number[]
}

export type MarkingStreamFrame = { type: "progress"; progress: MarkingProgress } | { type: "reconnect" }

export interface PaperChoice {
  subjectCode: string
  paperNumber: number
  variant: number
  sessionMonth: "May/June" | "Oct/Nov" | "Feb/Mar" | "Specimen"
  sessionYear: number | null
}

/** Four corners as fractions of the photo (TL, TR, BR, BL) plus rotation. */
export interface PageCrop {
  page: number
  corners: [number, number][]
  rotation: 0 | 90 | 180 | 270
}

export interface RecentUpload {
  paperId: string
  title: string
  code: string | null
  uploadedAt: string
  papers: number
  kind: "queued" | "marking" | "marked" | "stopped" | "no_scheme"
  done: number | null
  total: number | null
  toReview: number | null
  /** L12 fills this for class sets. */
  namesNeedYou: number | null
}

export interface RecentUploadList {
  uploads: RecentUpload[]
}
```

- [ ] **Step 4: `web/src/lib/markingApi.ts`**

```ts
import { fetchBlobUrl, request, streamActivity, uploadWithProgress, type UploadProgress } from "@/lib/api"
import type {
  DetectResult,
  MarkingProgress,
  MarkingStreamFrame,
  PageCrop,
  PaperChoice,
  RecentUploadList,
} from "@/lib/markingTypes"
import type { StudentUploadResponse } from "@/lib/studentTypes"
import type { UploadResponse } from "@/lib/teacherTypes"

const enc = encodeURIComponent

export function getMarkingProgress(paperId: string): Promise<MarkingProgress> {
  return request<MarkingProgress>(`/marking/${enc(paperId)}/progress`)
}

/** The DB-backed progress stream. Comment heartbeats are skipped by `streamActivity`. */
export function streamMarkingProgress(paperId: string, signal?: AbortSignal): AsyncGenerator<MarkingStreamFrame> {
  return streamActivity(`/marking/${enc(paperId)}/events`, { method: "GET", signal }) as AsyncGenerator<MarkingStreamFrame>
}

export function detectPaper(paperId: string): Promise<DetectResult> {
  return request<DetectResult>(`/student/uploads/${enc(paperId)}/detect`, { method: "POST" })
}

export function choosePaper(paperId: string, choice: PaperChoice): Promise<DetectResult> {
  return request<DetectResult>(`/student/uploads/${enc(paperId)}/paper`, {
    method: "PUT",
    body: JSON.stringify(choice),
    headers: { "Content-Type": "application/json" },
  })
}

/** An object URL for the server's PDF of the scan. The caller revokes it. */
export function fetchMarkingPdf(paperId: string): Promise<string> {
  return fetchBlobUrl(`/marking/${enc(paperId)}/pdf`)
}

export function getRecentUploads(limit = 10): Promise<RecentUploadList> {
  return request<RecentUploadList>(`/teacher/uploads/recent?limit=${limit}`)
}

export interface ScanUploadOptions {
  markScheme?: File | null
  crops?: PageCrop[]
  onProgress?: (progress: UploadProgress) => void
  signal?: AbortSignal
  idempotencyKey?: string
}

function scanForm(scan: File, opts: ScanUploadOptions): FormData {
  const form = new FormData()
  form.append("scan", scan)
  if (opts.markScheme) form.append("mark_scheme", opts.markScheme)
  if (opts.crops && opts.crops.length > 0) form.append("crops", JSON.stringify(opts.crops))
  return form
}

export function uploadStudentScan(scan: File, opts: ScanUploadOptions): Promise<StudentUploadResponse> {
  return uploadWithProgress<StudentUploadResponse>("/student/uploads", scanForm(scan, opts), {
    onProgress: opts.onProgress,
    signal: opts.signal,
    headers: opts.idempotencyKey ? { "Idempotency-Key": opts.idempotencyKey } : undefined,
  })
}

/** Teacher upload with real byte progress (the old `uploadPaper` used `fetch`, which cannot report it). */
export function uploadTeacherScan(scan: File, opts: ScanUploadOptions): Promise<UploadResponse> {
  return uploadWithProgress<UploadResponse>("/papers/upload", scanForm(scan, opts), {
    onProgress: opts.onProgress,
    signal: opts.signal,
  })
}
```
(Check `UploadResponse` is the name exported by `lib/teacherTypes.ts`, which `useTeacherApi.ts:1073` already returns; if it differs, import the name that file uses.)

- [ ] **Step 5: `web/src/lib/hooks/useMarkingApi.ts`**

```ts
import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query"
import {
  choosePaper,
  detectPaper,
  getMarkingProgress,
  getRecentUploads,
  streamMarkingProgress,
} from "@/lib/markingApi"
import { abortableSleep, followProgress } from "@/lib/marking/progressStream"
import type { DetectResult, MarkingProgress, PaperChoice, RecentUploadList } from "@/lib/markingTypes"

// L6 query keys
export const markingKeys = {
  progress: (paperId: string) => ["marking", "progress", paperId] as const,
  recent: ["teacher", "uploads", "recent"] as const,
}

export interface LiveMarkingProgress {
  progress: MarkingProgress | undefined
  loading: boolean
  /** Set when the stream and the polling fallback both failed. */
  error: unknown
  retry: () => void
}

/** Live progress for one paper: SSE first, polling after two stream failures. */
export function useMarkingProgress(paperId: string | undefined): LiveMarkingProgress {
  const queryClient = useQueryClient()
  const [error, setError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)
  const query = useQuery({
    queryKey: markingKeys.progress(paperId ?? ""),
    queryFn: () => getMarkingProgress(paperId as string),
    enabled: Boolean(paperId),
    staleTime: Number.POSITIVE_INFINITY,
  })

  useEffect(() => {
    if (!paperId) return
    const controller = new AbortController()
    setError(null)
    void followProgress(
      {
        stream: (signal) => streamMarkingProgress(paperId, signal),
        poll: () => getMarkingProgress(paperId),
        sleep: abortableSleep,
        onProgress: (p) => queryClient.setQueryData(markingKeys.progress(paperId), p),
        onError: setError,
      },
      controller.signal,
    )
    return () => controller.abort()
  }, [paperId, attempt, queryClient])

  return {
    progress: query.data,
    loading: Boolean(paperId) && query.isPending,
    error: error ?? (query.isError && !query.data ? query.error : null),
    retry: () => {
      setAttempt((n) => n + 1)
      void query.refetch()
    },
  }
}

export function useDetectPaper() {
  return useMutation<DetectResult, Error, string>({ mutationFn: (paperId) => detectPaper(paperId) })
}

export function useChoosePaper() {
  return useMutation<DetectResult, Error, { paperId: string; choice: PaperChoice }>({
    mutationFn: ({ paperId, choice }) => choosePaper(paperId, choice),
  })
}

const RECENT_POLL_MS = 4000

export function useRecentUploads(): UseQueryResult<RecentUploadList, Error> {
  return useQuery({
    queryKey: markingKeys.recent,
    queryFn: () => getRecentUploads(),
    refetchInterval: (q) =>
      q.state.data?.uploads.some((u) => u.kind === "marking" || u.kind === "queued") ? RECENT_POLL_MS : false,
  })
}
```
(This file imports `progressStream.ts` from Task 9; write Task 9 before running a type check on this file. The test in this task imports only `markingApi.ts`.)

- [ ] **Step 6: Run to verify pass**

Run: `npx vitest run tests/unit/markingApiShape.test.ts`
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
npx oxlint src/lib/markingTypes.ts src/lib/markingApi.ts
git commit -S -m "feat(web): marking API client and types" -- web/src/lib/markingTypes.ts web/src/lib/markingApi.ts web/tests/unit/markingApiShape.test.ts
```
(`useMarkingApi.ts` is committed with Task 9, once `progressStream.ts` exists.)

---

### Task 9: SSE-then-polling progress follower

**Files:**
- Create: `web/src/lib/marking/progressStream.ts`
- Commit also: `web/src/lib/hooks/useMarkingApi.ts` (from Task 8)
- Test: `web/tests/unit/progressStream.test.ts`

**Interfaces:**
- Produces: `followProgress(deps: FollowDeps, signal: AbortSignal): Promise<"terminal" | "aborted" | "error">`; `isTerminal(p)`; `abortableSleep(ms, signal)`; `FollowDeps { stream; poll; sleep; onProgress; onError; pollMs?; maxStreamFailures? }`.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it, vi } from "vitest"
import { followProgress, isTerminal } from "@/lib/marking/progressStream"
import type { MarkingProgress, MarkingStreamFrame } from "@/lib/markingTypes"

const p = (status: MarkingProgress["status"], done = 0, lost = false): MarkingProgress => ({
  paperId: "p", status, stage: "mark", lost, questions: [], done, total: 3,
  etaSeconds: null, paper: null, error: null, missingPages: [],
})

async function* frames(list: MarkingStreamFrame[], thenThrow?: Error): AsyncGenerator<MarkingStreamFrame> {
  for (const f of list) yield f
  if (thenThrow) throw thenThrow
}

const noSleep = () => Promise.resolve()

describe("followProgress", () => {
  it("ends on a terminal frame from the stream", async () => {
    const seen: number[] = []
    const out = await followProgress(
      {
        stream: () => frames([{ type: "progress", progress: p("processing", 1) }, { type: "progress", progress: p("complete", 3) }]),
        poll: vi.fn(),
        sleep: noSleep,
        onProgress: (x) => seen.push(x.done),
        onError: vi.fn(),
      },
      new AbortController().signal,
    )
    expect(out).toBe("terminal")
    expect(seen).toEqual([1, 3])
  })

  it("reconnects on a reconnect frame without counting a failure", async () => {
    let opened = 0
    const out = await followProgress(
      {
        stream: () => {
          opened += 1
          return opened < 4
            ? frames([{ type: "progress", progress: p("processing", opened) }, { type: "reconnect" }])
            : frames([{ type: "progress", progress: p("failed") }])
        },
        poll: vi.fn(),
        sleep: noSleep,
        onProgress: vi.fn(),
        onError: vi.fn(),
      },
      new AbortController().signal,
    )
    expect(out).toBe("terminal")
    expect(opened).toBe(4)
  })

  it("falls back to polling after two stream failures", async () => {
    const poll = vi.fn().mockResolvedValueOnce(p("processing", 2)).mockResolvedValueOnce(p("complete", 3))
    const out = await followProgress(
      { stream: () => frames([], new TypeError("network")), poll, sleep: noSleep, onProgress: vi.fn(), onError: vi.fn() },
      new AbortController().signal,
    )
    expect(out).toBe("terminal")
    expect(poll).toHaveBeenCalledTimes(2)
  })

  it("counts a stream that closes without a terminal or reconnect as a failure", async () => {
    let opened = 0
    const poll = vi.fn().mockResolvedValue(p("complete"))
    await followProgress(
      { stream: () => { opened += 1; return frames([]) }, poll, sleep: noSleep, onProgress: vi.fn(), onError: vi.fn() },
      new AbortController().signal,
    )
    expect(opened).toBe(2)
    expect(poll).toHaveBeenCalledTimes(1)
  })

  it("reports a polling error and stops", async () => {
    const onError = vi.fn()
    const out = await followProgress(
      { stream: () => frames([], new Error("x")), poll: () => Promise.reject(new Error("down")), sleep: noSleep, onProgress: vi.fn(), onError },
      new AbortController().signal,
    )
    expect(out).toBe("error")
    expect(onError).toHaveBeenCalledOnce()
  })

  it("stops quietly when aborted", async () => {
    const controller = new AbortController()
    controller.abort()
    const out = await followProgress(
      { stream: vi.fn(), poll: vi.fn(), sleep: noSleep, onProgress: vi.fn(), onError: vi.fn() },
      controller.signal,
    )
    expect(out).toBe("aborted")
  })

  it("treats lost as terminal", () => {
    expect(isTerminal(p("processing", 0, true))).toBe(true)
    expect(isTerminal(p("processing"))).toBe(false)
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run tests/unit/progressStream.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `web/src/lib/marking/progressStream.ts`**

```ts
import type { MarkingProgress, MarkingStreamFrame } from "@/lib/markingTypes"

/*
 * Follow one paper's marking progress to a terminal state.
 *
 * The SSE stream is DB-backed, so a reconnect can land on any Cloud Run instance. The
 * server closes it itself every 240 s with a `reconnect` frame (Cloud Run's 300 s
 * request limit); that is not a failure. Two real failures in a row (a thrown stream, or
 * a stream that ends with neither a terminal frame nor `reconnect`) switch to polling the
 * JSON route every `pollMs`. A polling error is reported once and ends the follow: the
 * screen shows "Couldn't check status" with Try again, which starts a new follow.
 */

export interface FollowDeps {
  stream: (signal: AbortSignal) => AsyncGenerator<MarkingStreamFrame>
  poll: () => Promise<MarkingProgress>
  sleep: (ms: number, signal: AbortSignal) => Promise<void>
  onProgress: (progress: MarkingProgress) => void
  onError: (error: unknown) => void
  pollMs?: number
  maxStreamFailures?: number
}

export type FollowOutcome = "terminal" | "aborted" | "error"

export function isTerminal(progress: MarkingProgress): boolean {
  return progress.status === "complete" || progress.status === "failed" || progress.lost
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError"
}

export function abortableSleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("Aborted", "AbortError"))
      return
    }
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort)
      resolve()
    }, ms)
    const onAbort = () => {
      clearTimeout(timer)
      reject(new DOMException("Aborted", "AbortError"))
    }
    signal.addEventListener("abort", onAbort, { once: true })
  })
}

export async function followProgress(deps: FollowDeps, signal: AbortSignal): Promise<FollowOutcome> {
  const pollMs = deps.pollMs ?? 4000
  const maxFailures = deps.maxStreamFailures ?? 2
  let failures = 0

  while (failures < maxFailures) {
    if (signal.aborted) return "aborted"
    try {
      let reconnect = false
      for await (const frame of deps.stream(signal)) {
        if (frame.type === "progress") {
          failures = 0
          deps.onProgress(frame.progress)
          if (isTerminal(frame.progress)) return "terminal"
        } else if (frame.type === "reconnect") {
          reconnect = true
          break
        }
      }
      if (!reconnect) failures += 1
    } catch (error) {
      if (signal.aborted || isAbort(error)) return "aborted"
      failures += 1
    }
  }

  for (;;) {
    if (signal.aborted) return "aborted"
    try {
      const progress = await deps.poll()
      deps.onProgress(progress)
      if (isTerminal(progress)) return "terminal"
    } catch (error) {
      if (signal.aborted || isAbort(error)) return "aborted"
      deps.onError(error)
      return "error"
    }
    try {
      await deps.sleep(pollMs, signal)
    } catch {
      return "aborted"
    }
  }
}
```

- [ ] **Step 4: Run to verify pass, then type-check**

Run: `npx vitest run tests/unit/progressStream.test.ts && npx tsc -p tsconfig.app.json --noEmit`
Expected: 7 passed; no type errors in `src/lib/marking/`, `src/lib/hooks/useMarkingApi.ts`, `src/lib/markingApi.ts`.

- [ ] **Step 5: Commit**

```bash
npx oxlint src/lib/marking/progressStream.ts src/lib/hooks/useMarkingApi.ts
git commit -S -m "feat(web): follow marking progress over SSE with a polling fallback" -- web/src/lib/marking/progressStream.ts web/src/lib/hooks/useMarkingApi.ts web/tests/unit/progressStream.test.ts
```

---

### Task 10: Marking view model

**Files:**
- Create: `web/src/lib/marking/viewModel.ts`
- Test: `web/tests/unit/markingViewModel.test.ts`

**Interfaces:**
- Consumes: `MarkingProgress`, `TileQuestion`, `RecentUpload`; F1 types `BinnyMood`, `BinnyMotion` from `@/components/redesign`; `formatMegabytes` from `lib/uploadProgress.ts`.
- Produces (L12 depends on the first four names):
  - `type BoardTileState = "waiting" | "now" | "done" | "blank" | "missing" | "stopped"`
  - `interface BoardTile { key: string; label: string; state: BoardTileState; note: string | null }`
  - `tileStateFor(q: TileQuestion, ctx: { isCurrent: boolean }): BoardTileState`
  - `groupTiles(questions: readonly TileQuestion[], opts: { running: boolean }): BoardTile[]`
  - `tileGroupKey(id)`, `TILE_NOTE`, `etaLabel(seconds)`, `joinList(items)`, `missingAlert(progress, tiles)`
  - `type LocalSend`, `type MarkingView`, `selectMarkingView(input)`, `binnyFor(view, role)`, `footerFor(view)`, `titleFor(view)`, `subtitleFor(progress, fallback)`, `stoppedCopy(sent)`
  - `type RecentRow`, `recentRowFromUpload(upload, now?)`, `relativeTime(iso, now)`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest"
import {
  binnyFor,
  etaLabel,
  footerFor,
  groupTiles,
  joinList,
  missingAlert,
  recentRowFromUpload,
  selectMarkingView,
  stoppedCopy,
  subtitleFor,
  tileGroupKey,
  tileStateFor,
} from "@/lib/marking/viewModel"
import type { MarkingProgress, RecentUpload, TileQuestion } from "@/lib/markingTypes"

const prog = (over: Partial<MarkingProgress> = {}): MarkingProgress => ({
  paperId: "p", status: "processing", stage: "mark", lost: false, questions: [], done: 0, total: null,
  etaSeconds: null, paper: null, error: null, missingPages: [], ...over,
})
const q = (id: string, state: TileQuestion["state"], blank?: boolean | null): TileQuestion => ({ id, state, blank })

describe("tileStateFor (L12 interface)", () => {
  it("maps each state; blank only from the flag", () => {
    expect(tileStateFor(q("1", "done"), { isCurrent: false })).toBe("done")
    expect(tileStateFor(q("1", "done", true), { isCurrent: false })).toBe("blank")
    expect(tileStateFor(q("1", "done", null), { isCurrent: false })).toBe("done")
    expect(tileStateFor(q("1", "waiting"), { isCurrent: true })).toBe("now")
    expect(tileStateFor(q("1", "waiting"), { isCurrent: false })).toBe("waiting")
    expect(tileStateFor(q("1", "missing"), { isCurrent: true })).toBe("missing")
    expect(tileStateFor(q("1", "stopped"), { isCurrent: false })).toBe("stopped")
  })
})

describe("groupTiles", () => {
  it("groups leaf ids under their question number", () => {
    expect(tileGroupKey("4(a)(ii)")).toBe("4")
    expect(tileGroupKey("12b")).toBe("12")
    expect(tileGroupKey("A")).toBe("A")
  })

  it("labels, notes and the single now tile", () => {
    const tiles = groupTiles(
      [q("1", "done"), q("2a", "done"), q("2b", "waiting"), q("3", "waiting"), q("6", "done", true), q("9", "missing")],
      { running: true },
    )
    expect(tiles.map((t) => [t.label, t.state, t.note])).toEqual([
      ["Q1", "done", null],
      ["Q2", "now", "Marking"],
      ["Q3", "waiting", null],
      ["Q6", "blank", "Blank"],
      ["Q9", "missing", "Page missing"],
    ])
  })

  it("a group is blank only when every part is blank", () => {
    expect(groupTiles([q("5a", "done", true), q("5b", "done")], { running: false })[0].state).toBe("done")
    expect(groupTiles([q("5a", "done", true), q("5b", "done", true)], { running: false })[0].state).toBe("blank")
  })

  it("no now tile when not running", () => {
    expect(groupTiles([q("1", "waiting")], { running: false })[0].state).toBe("waiting")
  })
})

describe("copy helpers", () => {
  it("eta", () => {
    expect(etaLabel(null)).toBeNull()
    expect(etaLabel(40)).toBe("under a minute left")
    expect(etaLabel(120)).toBe("about 2 min left")
    expect(etaLabel(121)).toBe("about 3 min left")
  })
  it("joinList", () => {
    expect(joinList(["Q9"])).toBe("Q9")
    expect(joinList(["Q9", "Q10"])).toBe("Q9 and Q10")
    expect(joinList(["Q9", "Q10", "Q11"])).toBe("Q9, Q10 and Q11")
  })
  it("missing alert", () => {
    const tiles = groupTiles([q("9", "missing")], { running: false })
    expect(missingAlert(prog({ missingPages: [9] }), tiles)).toBe("Page 9 is missing, so Q9 can’t be marked.")
    expect(missingAlert(prog({ missingPages: [9, 10] }), tiles)).toBe("Pages 9 and 10 are missing, so Q9 can’t be marked.")
    expect(missingAlert(prog(), groupTiles([q("1", "done")], { running: false }))).toBeNull()
  })
  it("stopped copy", () => {
    expect(stoppedCopy(true)).toEqual({ action: "Start marking again", note: "Your scan is already sent. Starting again re-marks the same file." })
    expect(stoppedCopy(false)).toEqual({ action: "Try again", note: "Nothing was sent, so trying again sends the file fresh." })
  })
  it("subtitle", () => {
    const paper = { subjectCode: "0580", subjectName: "Mathematics", paperNumber: 4, variant: 2, sessionMonth: "May/June", sessionYear: 2025, code: "0580/42" }
    expect(subtitleFor(prog({ paper }), "16 pages")).toBe("0580/42 · Paper 4")
    expect(subtitleFor(undefined, "16 pages")).toBe("16 pages")
  })
})

describe("selectMarkingView", () => {
  const base = { local: null, progress: undefined, progressError: false, cameBack: false }
  it("sending with and without a total", () => {
    const v = selectMarkingView({ ...base, local: { phase: "sending", loaded: 4_100_000, total: 6_600_000, pages: 16 } })
    expect(v).toEqual({ kind: "sending", big: "62", unit: "%", detail: "sending 16 pages · 4.1 of 6.6 MB", fraction: 4_100_000 / 6_600_000 })
    const w = selectMarkingView({ ...base, local: { phase: "sending", loaded: 1_000_000, total: undefined, pages: null } })
    expect(w).toMatchObject({ kind: "sending", big: "1.0", unit: "MB", fraction: null })
  })
  it("offline, send failed, status error, loading", () => {
    expect(selectMarkingView({ ...base, local: { phase: "saved_offline", savedAt: 1, pages: 16, title: "Mathematics · 0580/42" } }).kind).toBe("saved_offline")
    expect(selectMarkingView({ ...base, local: { phase: "send_failed", message: "x" } })).toEqual({ kind: "stopped", sent: false, tiles: [], message: "x" })
    expect(selectMarkingView({ ...base, progressError: true }).kind).toBe("status_error")
    expect(selectMarkingView(base).kind).toBe("loading")
  })
  it("server states", () => {
    expect(selectMarkingView({ ...base, progress: prog({ status: "complete" }) }).kind).toBe("complete")
    expect(selectMarkingView({ ...base, progress: prog({ status: "failed", stage: "no_scheme" }) }).kind).toBe("no_scheme")
    expect(selectMarkingView({ ...base, progress: prog({ status: "failed", questions: [q("1", "done"), q("2", "stopped")] }) })).toMatchObject({ kind: "stopped", sent: true })
    expect(selectMarkingView({ ...base, progress: prog({ lost: true }) })).toMatchObject({ kind: "stopped", sent: true })
    expect(selectMarkingView({ ...base, progress: prog({ stage: "queued" }) }).kind).toBe("next_in_line")
    expect(selectMarkingView({ ...base, progress: prog({ stage: "extract" }), cameBack: true }).kind).toBe("came_back")
    expect(selectMarkingView({ ...base, progress: prog({ stage: "extract" }) }).kind).toBe("reading")
  })
  it("marking counts tiles, not leaves", () => {
    const v = selectMarkingView({
      ...base,
      progress: prog({ questions: [q("1", "done"), q("2a", "done"), q("2b", "waiting"), q("3", "waiting")], etaSeconds: 90 }),
    })
    expect(v).toMatchObject({ kind: "marking", done: 1, total: 3, eta: "about 2 min left", alert: null })
  })
})

describe("binny and footer", () => {
  it("student only, calm moods", () => {
    expect(binnyFor({ kind: "next_in_line" }, "student")).toEqual({ mood: "happy", motion: "idle" })
    expect(binnyFor({ kind: "reading" }, "student")).toEqual({ mood: "thinking", motion: "idle" })
    expect(binnyFor({ kind: "next_in_line" }, "teacher")).toBeNull()
    expect(binnyFor({ kind: "stopped", sent: true, tiles: [], message: null }, "student")).toBeNull()
  })
  it("footer", () => {
    expect(footerFor({ kind: "sending", big: "1", unit: "%", detail: "", fraction: 0 })).toBe("Keep Lemely open until sending finishes.")
    expect(footerFor({ kind: "next_in_line" })).toBe("Safe to leave. We’ll let you know when it’s ready.")
    expect(footerFor({ kind: "no_scheme" })).toBeNull()
  })
})

describe("recentRowFromUpload", () => {
  const now = new Date("2026-11-15T12:00:00Z")
  const up = (over: Partial<RecentUpload>): RecentUpload => ({
    paperId: "p", title: "Layla Hassan", code: "0580/42", uploadedAt: "2026-11-15T11:58:00Z", papers: 1,
    kind: "queued", done: null, total: null, toReview: null, namesNeedYou: null, ...over,
  })
  it("maps every kind", () => {
    expect(recentRowFromUpload(up({ kind: "marking", done: 17, total: 28 }), now)).toMatchObject({
      title: "Layla Hassan · 0580/42", sub: "1 paper · uploaded 2 min ago", status: { text: "Marking 17 of 28", tone: "muted", bar: 17 / 28 }, action: null,
    })
    expect(recentRowFromUpload(up({ kind: "marked", toReview: 2 }), now)).toMatchObject({ status: { text: "Marked · 2 to review", tone: "ok" }, action: { kind: "open", label: "Open" } })
    expect(recentRowFromUpload(up({ kind: "marked", toReview: 0 }), now).status.text).toBe("Marked")
    expect(recentRowFromUpload(up({ kind: "stopped" }), now)).toMatchObject({ status: { text: "Marking stopped", tone: "bad" }, action: { kind: "regrade", label: "Start again" } })
    expect(recentRowFromUpload(up({ kind: "no_scheme" }), now)).toMatchObject({ status: { text: "No mark scheme", tone: "bad" }, action: { kind: "add_scheme", label: "Add scheme" } })
    expect(recentRowFromUpload(up({ kind: "queued" }), now).status.text).toBe("Next in line")
    expect(recentRowFromUpload(up({ namesNeedYou: 3 }), now)).toMatchObject({ status: { text: "3 names need you", tone: "chip" }, action: { kind: "names", label: "Check names" } })
    expect(recentRowFromUpload(up({ uploadedAt: "2026-11-15T11:00:00Z" }), now).sub).toBe("1 paper · uploaded 1 h ago")
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run tests/unit/markingViewModel.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `web/src/lib/marking/viewModel.ts`**

```ts
import type { BinnyMood, BinnyMotion } from "@/components/redesign"
import type { MarkingProgress, RecentUpload, TileQuestion } from "@/lib/markingTypes"
import { formatMegabytes } from "@/lib/uploadProgress"

/* Every decision the marking screens make lives here, so the screens stay thin.
 * L12 depends on `BoardTileState`, `BoardTile`, `tileStateFor`, `groupTiles`,
 * `RecentRow` and `recentRowFromUpload` by these exact names. */

export type BoardTileState = "waiting" | "now" | "done" | "blank" | "missing" | "stopped"

export interface BoardTile {
  key: string
  label: string
  state: BoardTileState
  note: string | null
}

export const TILE_NOTE: Record<BoardTileState, string | null> = {
  waiting: null,
  done: null,
  now: "Marking",
  blank: "Blank",
  missing: "Page missing",
  stopped: "Stopped",
}

/** One question's tile state. Blank comes only from the optional `blank` flag (L12). */
export function tileStateFor(q: TileQuestion, ctx: { isCurrent: boolean }): BoardTileState {
  if (q.state === "missing") return "missing"
  if (q.state === "stopped") return "stopped"
  if (q.state === "done") return q.blank === true ? "blank" : "done"
  return ctx.isCurrent ? "now" : "waiting"
}

/** "4", "4a", "4(a)(ii)", "4.1" → "4". An id with no leading number keeps its own tile. */
export function tileGroupKey(id: string): string {
  const match = /^(\d+)/.exec(id.trim())
  return match ? match[1] : id.trim()
}

function combine(states: BoardTileState[]): BoardTileState {
  if (states.includes("missing")) return "missing"
  if (states.includes("stopped")) return "stopped"
  if (states.every((s) => s === "blank")) return "blank"
  if (states.every((s) => s === "done" || s === "blank")) return "done"
  return "waiting"
}

/** Tiles in mark-scheme order, one per question number. While running, the first
 * unfinished tile is "now" (the server marks in order). */
export function groupTiles(questions: readonly TileQuestion[], opts: { running: boolean }): BoardTile[] {
  const groups = new Map<string, BoardTileState[]>()
  for (const question of questions) {
    const key = tileGroupKey(question.id)
    const list = groups.get(key) ?? []
    list.push(tileStateFor(question, { isCurrent: false }))
    groups.set(key, list)
  }
  const tiles: BoardTile[] = [...groups].map(([key, states]) => {
    const state = combine(states)
    return { key, label: /^\d/.test(key) ? `Q${key}` : key, state, note: TILE_NOTE[state] }
  })
  if (opts.running) {
    const index = tiles.findIndex((t) => t.state === "waiting")
    if (index !== -1) tiles[index] = { ...tiles[index], state: "now", note: TILE_NOTE.now }
  }
  return tiles
}

export function etaLabel(seconds: number | null): string | null {
  if (seconds === null) return null
  if (seconds < 60) return "under a minute left"
  return `about ${Math.ceil(seconds / 60)} min left`
}

export function joinList(items: readonly string[]): string {
  if (items.length <= 1) return items.join("")
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`
}

export function missingAlert(progress: MarkingProgress, tiles: readonly BoardTile[]): string | null {
  const missing = tiles.filter((t) => t.state === "missing").map((t) => t.label)
  if (missing.length === 0) return null
  const pages = progress.missingPages
  const lead =
    pages.length === 1
      ? `Page ${pages[0]} is missing`
      : pages.length > 1
        ? `Pages ${joinList(pages.map(String))} are missing`
        : "A page is missing"
  return `${lead}, so ${joinList(missing)} can’t be marked.`
}

export type LocalSend =
  | { phase: "sending"; loaded: number; total: number | undefined; pages: number | null }
  | { phase: "saved_offline"; savedAt: number; pages: number | null; title: string }
  | { phase: "send_failed"; message: string }

export type MarkingView =
  | { kind: "loading" }
  | { kind: "sending"; big: string; unit: string; detail: string; fraction: number | null }
  | { kind: "saved_offline"; savedAt: number; pages: number | null; title: string }
  | { kind: "next_in_line" }
  | { kind: "reading" }
  | { kind: "came_back" }
  | { kind: "marking"; done: number; total: number; eta: string | null; tiles: BoardTile[]; alert: string | null }
  | { kind: "stopped"; sent: boolean; tiles: BoardTile[]; message: string | null }
  | { kind: "no_scheme" }
  | { kind: "complete" }
  | { kind: "status_error" }

export interface MarkingViewInput {
  local: LocalSend | null
  progress: MarkingProgress | undefined
  progressError: boolean
  /** The screen opened on a run it did not start (recovery). */
  cameBack: boolean
}

function sendingView(loaded: number, total: number | undefined, pages: number | null): MarkingView {
  const mb = (bytes: number) => (bytes / 1_000_000).toFixed(1)
  if (total !== undefined && total > 0) {
    const what = pages ? `sending ${pages} pages` : "sending"
    return {
      kind: "sending",
      big: String(Math.round((loaded / total) * 100)),
      unit: "%",
      detail: `${what} · ${mb(loaded)} of ${formatMegabytes(total)}`,
      fraction: loaded / total,
    }
  }
  return { kind: "sending", big: mb(loaded), unit: "MB", detail: pages ? `sending ${pages} pages` : "sending", fraction: null }
}

export function selectMarkingView(input: MarkingViewInput): MarkingView {
  const { local, progress } = input
  if (local?.phase === "sending") return sendingView(local.loaded, local.total, local.pages)
  if (local?.phase === "saved_offline") return { kind: "saved_offline", savedAt: local.savedAt, pages: local.pages, title: local.title }
  if (local?.phase === "send_failed") return { kind: "stopped", sent: false, tiles: [], message: local.message }
  if (!progress) return input.progressError ? { kind: "status_error" } : { kind: "loading" }
  if (progress.status === "complete") return { kind: "complete" }
  if (progress.stage === "no_scheme") return { kind: "no_scheme" }
  if (progress.status === "failed" || progress.lost) {
    return { kind: "stopped", sent: true, tiles: groupTiles(progress.questions, { running: false }), message: progress.error }
  }
  if (progress.stage === "queued") return { kind: "next_in_line" }
  if (progress.questions.length === 0) return input.cameBack ? { kind: "came_back" } : { kind: "reading" }
  const tiles = groupTiles(progress.questions, { running: progress.status === "processing" && progress.stage === "mark" })
  return {
    kind: "marking",
    done: tiles.filter((t) => t.state === "done" || t.state === "blank").length,
    total: tiles.length,
    eta: etaLabel(progress.etaSeconds),
    tiles,
    alert: missingAlert(progress, tiles),
  }
}

export function binnyFor(view: MarkingView, role: "student" | "teacher"): { mood: BinnyMood; motion: BinnyMotion } | null {
  if (role === "teacher") return null
  switch (view.kind) {
    case "sending":
      return { mood: "open", motion: "idle" }
    case "marking":
    case "reading":
    case "came_back":
      return { mood: "thinking", motion: "idle" }
    case "next_in_line":
      return { mood: "happy", motion: "idle" }
    default:
      return null
  }
}

export const SAFE_TO_LEAVE = "Safe to leave. We’ll let you know when it’s ready."

export function footerFor(view: MarkingView): string | null {
  if (view.kind === "sending") return "Keep Lemely open until sending finishes."
  if (view.kind === "marking" || view.kind === "next_in_line" || view.kind === "came_back" || view.kind === "reading") return SAFE_TO_LEAVE
  return null
}

export function titleFor(view: MarkingView): string {
  return view.kind === "sending" || view.kind === "saved_offline" ? "Sending" : "Marking"
}

export function subtitleFor(progress: MarkingProgress | undefined, fallback: string): string {
  const paper = progress?.paper
  return paper ? `${paper.code} · Paper ${paper.paperNumber}` : fallback
}

export function stoppedCopy(sent: boolean): { action: string; note: string } {
  return sent
    ? { action: "Start marking again", note: "Your scan is already sent. Starting again re-marks the same file." }
    : { action: "Try again", note: "Nothing was sent, so trying again sends the file fresh." }
}

export function relativeTime(iso: string, now: Date): string {
  const minutes = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 60_000))
  if (minutes < 1) return "just now"
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  return hours < 48 ? "yesterday" : `${Math.round(hours / 24)} days ago`
}

export type RecentRowAction = { kind: "open" | "regrade" | "add_scheme" | "names" | "retry"; label: string; tone: "tonal" | "outline" }

/** One row of the teacher's Recent uploads. L12 builds class-set rows of this shape. */
export interface RecentRow {
  key: string
  title: string
  sub: string
  status: { text: string; tone: "muted" | "ok" | "bad" | "chip"; bar?: number }
  action: RecentRowAction | null
  paperId: string | null
}

export function recentRowFromUpload(upload: RecentUpload, now: Date = new Date()): RecentRow {
  const title = upload.code ? `${upload.title} · ${upload.code}` : upload.title
  const sub = `${upload.papers} ${upload.papers === 1 ? "paper" : "papers"} · uploaded ${relativeTime(upload.uploadedAt, now)}`
  const row = (status: RecentRow["status"], action: RecentRowAction | null): RecentRow => ({
    key: upload.paperId, title, sub, status, action, paperId: upload.paperId,
  })
  if (upload.namesNeedYou && upload.namesNeedYou > 0) {
    return row({ text: `${upload.namesNeedYou} names need you`, tone: "chip" }, { kind: "names", label: "Check names", tone: "tonal" })
  }
  switch (upload.kind) {
    case "marking":
      return row(
        {
          text: upload.total ? `Marking ${upload.done ?? 0} of ${upload.total}` : "Marking",
          tone: "muted",
          bar: upload.total ? (upload.done ?? 0) / upload.total : undefined,
        },
        null,
      )
    case "marked":
      return row(
        { text: upload.toReview ? `Marked · ${upload.toReview} to review` : "Marked", tone: "ok" },
        { kind: "open", label: "Open", tone: "outline" },
      )
    case "stopped":
      return row({ text: "Marking stopped", tone: "bad" }, { kind: "regrade", label: "Start again", tone: "tonal" })
    case "no_scheme":
      return row({ text: "No mark scheme", tone: "bad" }, { kind: "add_scheme", label: "Add scheme", tone: "tonal" })
    default:
      return row({ text: "Next in line", tone: "muted" }, null)
  }
}
```

- [ ] **Step 4: Run to verify pass**

Run: `npx vitest run tests/unit/markingViewModel.test.ts`
Expected: all passed. (If F1 has not landed, `@/components/redesign` types are missing; F1 lands before W2 per master plan, so do not stub them.)

- [ ] **Step 5: Commit**

```bash
npx oxlint src/lib/marking/viewModel.ts
git commit -S -m "feat(web): marking view model and tile states" -- web/src/lib/marking/viewModel.ts web/tests/unit/markingViewModel.test.ts
```

---

### Task 11: Scan maths: page quality, crop maths, entry mode

**Files:**
- Create: `web/src/lib/scan/pageQuality.ts`, `web/src/lib/scan/cropMath.ts`, `web/src/lib/scan/entryMode.ts`
- Test: `web/tests/unit/pageQuality.test.ts`, `web/tests/unit/cropMath.test.ts`, `web/tests/unit/entryMode.test.ts`

**Interfaces:**
- Consumes: `Quad` from `@/lib/scanner`; `PageCrop`.
- Produces:
  - `BLUR_VARIANCE_THRESHOLD = 40`, `laplacianVariance(luma, w, h)`, `isBlurry(luma, w, h, threshold?)`, `type Edge`, `cutOffEdge(quad, w, h, margin?)`, `type PageIssue`, `assessPage(input) -> { issue: PageIssue | null; edge: Edge | null }`
  - `type Corner`, `type Corners`, `NUDGE_PX = 4`, `clampCorner`, `moveCorner`, `nudgeCorner`, `nextRotation`, `defaultCorners`, `cornersFromQuad`, `toPageCrop`, `fromPageCrop`, `CORNER_LABELS`
  - `cameraAllowed(matchMedia?)`, `entryMode(matchMedia?) -> "camera" | "upload"`, `type CameraErrorKind`, `cameraErrorKind(err)`, `CAMERA_ERROR_COPY`

- [ ] **Step 1: Write the failing tests**

`web/tests/unit/pageQuality.test.ts`:
```ts
import { describe, expect, it } from "vitest"
import { assessPage, cutOffEdge, isBlurry, laplacianVariance } from "@/lib/scan/pageQuality"
import type { Quad } from "@/lib/scanner"

function checker(w: number, h: number): Float32Array {
  const out = new Float32Array(w * h)
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) out[y * w + x] = (x + y) % 2 === 0 ? 255 : 0
  return out
}
const flat = (w: number, h: number) => new Float32Array(w * h).fill(128)
const quad = (x0: number, y0: number, x1: number, y1: number): Quad => [
  { x: x0, y: y0 }, { x: x1, y: y0 }, { x: x1, y: y1 }, { x: x0, y: y1 },
]

describe("pageQuality", () => {
  it("sharp text has high variance, a flat page none", () => {
    expect(laplacianVariance(checker(20, 20), 20, 20)).toBeGreaterThan(1000)
    expect(laplacianVariance(flat(20, 20), 20, 20)).toBe(0)
    expect(laplacianVariance(flat(2, 2), 2, 2)).toBe(0)
    expect(isBlurry(flat(20, 20), 20, 20)).toBe(true)
    expect(isBlurry(checker(20, 20), 20, 20)).toBe(false)
  })

  it("cut-off edge, bottom first", () => {
    expect(cutOffEdge(quad(10, 10, 300, 239), 320, 240)).toBe("bottom")
    expect(cutOffEdge(quad(10, 1, 300, 200), 320, 240)).toBe("top")
    expect(cutOffEdge(quad(0, 10, 300, 200), 320, 240)).toBe("left")
    expect(cutOffEdge(quad(10, 10, 319, 200), 320, 240)).toBe("right")
    expect(cutOffEdge(quad(10, 10, 300, 200), 320, 240)).toBeNull()
  })

  it("assessPage: blurry beats cut-off; no quad is fine", () => {
    const base = { lumaWidth: 20, lumaHeight: 20, frameWidth: 320, frameHeight: 240 }
    expect(assessPage({ ...base, luma: flat(20, 20), quad: quad(10, 10, 300, 239) })).toEqual({ issue: "blurry", edge: null })
    expect(assessPage({ ...base, luma: checker(20, 20), quad: quad(10, 10, 300, 239) })).toEqual({ issue: "cut_off", edge: "bottom" })
    expect(assessPage({ ...base, luma: checker(20, 20), quad: null })).toEqual({ issue: null, edge: null })
  })
})
```

`web/tests/unit/cropMath.test.ts`:
```ts
import { describe, expect, it } from "vitest"
import { clampCorner, defaultCorners, fromPageCrop, moveCorner, nextRotation, nudgeCorner, toPageCrop, cornersFromQuad } from "@/lib/scan/cropMath"

describe("cropMath", () => {
  const c = defaultCorners(390, 624)
  it("default corners inset 6%", () => {
    expect(c[0]).toEqual([23.4, 37.44])
    expect(c[2]).toEqual([366.6, 586.56])
  })
  it("clamps and moves", () => {
    expect(clampCorner([-5, 700], 390, 624)).toEqual([0, 624])
    expect(moveCorner(c, 1, [500, -1], 390, 624)[1]).toEqual([390, 0])
  })
  it("arrow keys move 4px, other keys are ignored", () => {
    expect(nudgeCorner(c, 0, "ArrowRight", 390, 624)?.[0]).toEqual([27.4, 37.44])
    expect(nudgeCorner(c, 0, "ArrowUp", 390, 624)?.[0]).toEqual([23.4, 33.44])
    expect(nudgeCorner(c, 0, "Enter", 390, 624)).toBeNull()
  })
  it("rotation cycles", () => {
    expect([nextRotation(0), nextRotation(90), nextRotation(180), nextRotation(270)]).toEqual([90, 180, 270, 0])
  })
  it("round-trips through a PageCrop", () => {
    const crop = toPageCrop(3, c, 390, 624, 90)
    expect(crop).toEqual({ page: 3, corners: [[0.06, 0.06], [0.94, 0.06], [0.94, 0.94], [0.06, 0.94]], rotation: 90 })
    expect(fromPageCrop(crop, 390, 624)).toEqual(c)
  })
  it("scales a scanner quad into stage space", () => {
    const quad = [{ x: 0, y: 0 }, { x: 320, y: 0 }, { x: 320, y: 240 }, { x: 0, y: 240 }] as const
    expect(cornersFromQuad(quad as never, 320, 240, 160, 120)).toEqual([[0, 0], [160, 0], [160, 120], [0, 120]])
  })
})
```

`web/tests/unit/entryMode.test.ts`:
```ts
import { describe, expect, it } from "vitest"
import { CAMERA_ERROR_COPY, cameraAllowed, cameraErrorKind, entryMode } from "@/lib/scan/entryMode"

const mm = (coarse: boolean) => (q: string) => ({ matches: q === "(pointer: coarse)" ? coarse : false }) as MediaQueryList

describe("entryMode", () => {
  it("phone opens on the camera, desktop on upload and never gets a camera", () => {
    expect(entryMode(mm(true))).toBe("camera")
    expect(entryMode(mm(false))).toBe("upload")
    expect(cameraAllowed(mm(false))).toBe(false)
    expect(cameraAllowed(undefined)).toBe(false)
  })
  it("names every camera error", () => {
    const err = (name: string) => new DOMException("x", name)
    expect(cameraErrorKind(err("NotAllowedError"))).toBe("blocked")
    expect(cameraErrorKind(err("PermissionDeniedError"))).toBe("blocked")
    expect(cameraErrorKind(err("NotFoundError"))).toBe("none")
    expect(cameraErrorKind(err("OverconstrainedError"))).toBe("none")
    expect(cameraErrorKind(err("NotReadableError"))).toBe("in_use")
    expect(cameraErrorKind(err("TrackStartError"))).toBe("in_use")
    expect(cameraErrorKind(err("SecurityError"))).toBe("insecure")
    expect(cameraErrorKind("no-getusermedia")).toBe("insecure")
    expect(cameraErrorKind(err("AbortError"))).toBe("interrupted")
    expect(cameraErrorKind(new Error("x"))).toBe("other")
    expect(CAMERA_ERROR_COPY.blocked.title).toBe("Camera is blocked")
    expect(CAMERA_ERROR_COPY.none.title).toBe("No camera found")
    expect(CAMERA_ERROR_COPY.in_use.title).toBe("Camera in use by another app")
    expect(CAMERA_ERROR_COPY.insecure.title).toBe("Camera needs a secure connection")
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run tests/unit/pageQuality.test.ts tests/unit/cropMath.test.ts tests/unit/entryMode.test.ts`
Expected: FAIL (modules not found).

- [ ] **Step 3: Implement**

`web/src/lib/scan/pageQuality.ts`:
```ts
import type { Quad } from "@/lib/scanner"

/* Bad-page detection for scanner capture (mock "Bad page": a blurry page blocks and must
 * be retaken; "Your pages": a cut-off page is flagged first with Fix crop).
 * Variance of the Laplacian on the downscaled luma the scanner already computes. Sharp
 * handwriting at 320px scores well above 100; a shaken photo scores under 40. */

export const BLUR_VARIANCE_THRESHOLD = 40

export function laplacianVariance(luma: Float32Array, width: number, height: number): number {
  if (width < 3 || height < 3) return 0
  let sum = 0
  let sumSq = 0
  let n = 0
  for (let y = 1; y < height - 1; y++) {
    for (let x = 1; x < width - 1; x++) {
      const i = y * width + x
      const v = 4 * luma[i] - luma[i - 1] - luma[i + 1] - luma[i - width] - luma[i + width]
      sum += v
      sumSq += v * v
      n += 1
    }
  }
  const mean = sum / n
  return sumSq / n - mean * mean
}

export function isBlurry(luma: Float32Array, width: number, height: number, threshold = BLUR_VARIANCE_THRESHOLD): boolean {
  return laplacianVariance(luma, width, height) < threshold
}

export type Edge = "top" | "bottom" | "left" | "right"
export type PageIssue = "blurry" | "cut_off"

/** The page edge that runs off the frame, bottom first (the usual miss). */
export function cutOffEdge(quad: Quad, width: number, height: number, margin = 2): Edge | null {
  const xs = quad.map((p) => p.x)
  const ys = quad.map((p) => p.y)
  if (Math.max(...ys) >= height - margin) return "bottom"
  if (Math.min(...ys) <= margin) return "top"
  if (Math.min(...xs) <= margin) return "left"
  if (Math.max(...xs) >= width - margin) return "right"
  return null
}

export function assessPage(input: {
  luma: Float32Array
  lumaWidth: number
  lumaHeight: number
  quad: Quad | null
  frameWidth: number
  frameHeight: number
}): { issue: PageIssue | null; edge: Edge | null } {
  if (isBlurry(input.luma, input.lumaWidth, input.lumaHeight)) return { issue: "blurry", edge: null }
  const edge = input.quad ? cutOffEdge(input.quad, input.frameWidth, input.frameHeight) : null
  return edge ? { issue: "cut_off", edge } : { issue: null, edge: null }
}
```

`web/src/lib/scan/cropMath.ts`:
```ts
import type { PageCrop } from "@/lib/markingTypes"
import type { Quad } from "@/lib/scanner"

/* Fix crop maths (mock script in final.html: four corners, pointer drag clamped to the
 * stage, arrow keys move 4px). Corners are TL, TR, BR, BL in stage pixels. */

export type Corner = [number, number]
export type Corners = [Corner, Corner, Corner, Corner]
export const NUDGE_PX = 4
export const CORNER_LABELS = ["Top left corner", "Top right corner", "Bottom right corner", "Bottom left corner"] as const

const round = (n: number, places = 4) => Math.round(n * 10 ** places) / 10 ** places

export function clampCorner([x, y]: Corner, width: number, height: number): Corner {
  return [Math.max(0, Math.min(width, x)), Math.max(0, Math.min(height, y))]
}

export function moveCorner(corners: Corners, index: number, point: Corner, width: number, height: number): Corners {
  const next = [...corners] as Corners
  next[index] = clampCorner(point, width, height)
  return next
}

const NUDGE: Record<string, Corner> = {
  ArrowUp: [0, -NUDGE_PX],
  ArrowDown: [0, NUDGE_PX],
  ArrowLeft: [-NUDGE_PX, 0],
  ArrowRight: [NUDGE_PX, 0],
}

export function nudgeCorner(corners: Corners, index: number, key: string, width: number, height: number): Corners | null {
  const d = NUDGE[key]
  if (!d) return null
  const [x, y] = corners[index]
  return moveCorner(corners, index, [round(x + d[0], 2), round(y + d[1], 2)], width, height)
}

export function nextRotation(r: PageCrop["rotation"]): PageCrop["rotation"] {
  return ((r + 90) % 360) as PageCrop["rotation"]
}

export function defaultCorners(width: number, height: number, inset = 0.06): Corners {
  const ix = round(width * inset, 2)
  const iy = round(height * inset, 2)
  return [[ix, iy], [round(width - ix, 2), iy], [round(width - ix, 2), round(height - iy, 2)], [ix, round(height - iy, 2)]]
}

export function cornersFromQuad(quad: Quad, srcWidth: number, srcHeight: number, width: number, height: number): Corners {
  return quad.map((p) => [round((p.x / srcWidth) * width, 2), round((p.y / srcHeight) * height, 2)]) as Corners
}

export function toPageCrop(page: number, corners: Corners, width: number, height: number, rotation: PageCrop["rotation"]): PageCrop {
  return { page, corners: corners.map(([x, y]) => [round(x / width), round(y / height)]), rotation }
}

export function fromPageCrop(crop: PageCrop, width: number, height: number): Corners {
  return crop.corners.map(([x, y]) => [round(x * width, 2), round(y * height, 2)]) as Corners
}
```

`web/src/lib/scan/entryMode.ts`:
```ts
/* Where the flow opens, and what a camera failure is called (mock "Camera blocked": same
 * layout, other titles). Replaces lib/scanSource.ts and CameraCapture's describeCameraError. */

type MatchMedia = (query: string) => MediaQueryList

/** Desktop never gets a camera: only a coarse pointer (phone, tablet) does. */
export function cameraAllowed(matchMedia?: MatchMedia): boolean {
  return Boolean(matchMedia?.("(pointer: coarse)").matches)
}

export function entryMode(matchMedia?: MatchMedia): "camera" | "upload" {
  return cameraAllowed(matchMedia) ? "camera" : "upload"
}

export type CameraErrorKind = "blocked" | "none" | "in_use" | "insecure" | "interrupted" | "other"

export function cameraErrorKind(err: unknown): CameraErrorKind {
  if (err === "no-getusermedia") return "insecure"
  if (err instanceof DOMException) {
    switch (err.name) {
      case "NotAllowedError":
      case "PermissionDeniedError":
        return "blocked"
      case "NotFoundError":
      case "OverconstrainedError":
        return "none"
      case "NotReadableError":
      case "TrackStartError":
        return "in_use"
      case "SecurityError":
        return "insecure"
      case "AbortError":
        return "interrupted"
    }
  }
  return "other"
}

export const CAMERA_ERROR_COPY: Record<CameraErrorKind, { title: string; body: string }> = {
  blocked: { title: "Camera is blocked", body: "Allow camera access for Lemely in your browser settings, then try again." },
  none: { title: "No camera found", body: "This device has no camera Lemely can use. Upload a file instead." },
  in_use: { title: "Camera in use by another app", body: "Close the other app, then try again." },
  insecure: { title: "Camera needs a secure connection", body: "Open Lemely over https to use the camera." },
  interrupted: { title: "Camera stopped", body: "The camera was interrupted. Try again." },
  other: { title: "Camera didn’t start", body: "Something stopped the camera. Try again." },
}
```

- [ ] **Step 4: Run to verify pass**

Run: `npx vitest run tests/unit/pageQuality.test.ts tests/unit/cropMath.test.ts tests/unit/entryMode.test.ts`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
npx oxlint src/lib/scan
git commit -S -m "feat(web): scan page quality, crop maths and entry mode" -- web/src/lib/scan/pageQuality.ts web/src/lib/scan/cropMath.ts web/src/lib/scan/entryMode.ts web/tests/unit/pageQuality.test.ts web/tests/unit/cropMath.test.ts web/tests/unit/entryMode.test.ts
```

---

### Task 12: Capture model and the student flow machine

**Files:**
- Create: `web/src/lib/scan/captureModel.ts`, `web/src/lib/scan/flowMachine.ts`
- Test: `web/tests/unit/captureModel.test.ts`, `web/tests/unit/scanFlow.test.ts`

**Interfaces:**
- Consumes: `PageIssue`, `Edge` (Task 11); `PageCrop`.
- Produces:
  - `CapturedPage { id; url; originalUrl; sourceWidth; sourceHeight; quad: Quad | null; issue: PageIssue | null; edge: Edge | null; crop: PageCrop | null }`
  - `CaptureState { pages; retakeId; flash }`, `initialCapture`, `captureReducer(state, action)`, actions `captured | remove | retake | crop_saved | reset`
  - `canFinishCapture(s)`, `canSendPages(s)`, `firstProblem(s)`, `captureHint(s, live)`, `pageLabel(index, page)`, `countLabel(n)`, `pageCrops(s)`
  - `FlowState`, `FlowEvent`, `initialFlow(mode)`, `flowReducer(state, event)`

- [ ] **Step 1: Write the failing tests**

`web/tests/unit/captureModel.test.ts`:
```ts
import { describe, expect, it } from "vitest"
import {
  canFinishCapture,
  canSendPages,
  captureHint,
  captureReducer,
  countLabel,
  firstProblem,
  initialCapture,
  pageCrops,
  pageLabel,
  type CapturedPage,
} from "@/lib/scan/captureModel"

const page = (id: string, over: Partial<CapturedPage> = {}): CapturedPage => ({
  id, url: `blob:${id}`, originalUrl: `blob:o${id}`, sourceWidth: 100, sourceHeight: 140, quad: null,
  issue: null, edge: null, crop: null, ...over,
})
const add = (s: typeof initialCapture, p: CapturedPage) => captureReducer(s, { type: "captured", page: p })

describe("captureReducer", () => {
  it("appends pages and bumps the flash", () => {
    const s = add(add(initialCapture, page("a")), page("b"))
    expect(s.pages.map((p) => p.id)).toEqual(["a", "b"])
    expect(s.flash).toBe(2)
  })

  it("a blurry page blocks Done and the next capture replaces it in place", () => {
    let s = add(initialCapture, page("a"))
    s = add(s, page("b", { issue: "blurry" }))
    expect(s.retakeId).toBe("b")
    expect(canFinishCapture(s)).toBe(false)
    expect(captureHint(s, { quadFound: true, stable: false, justCaptured: false, auto: true })).toEqual({ text: "Page 2 blurry · retaking", tone: "error" })
    s = add(s, page("c"))
    expect(s.pages.map((p) => p.id)).toEqual(["a", "c"])
    expect(s.retakeId).toBeNull()
    expect(canFinishCapture(s)).toBe(true)
  })

  it("a cut-off page passes capture but blocks sending until the crop is saved", () => {
    let s = add(initialCapture, page("a", { issue: "cut_off", edge: "bottom" }))
    expect(canFinishCapture(s)).toBe(true)
    expect(canSendPages(s)).toBe(false)
    expect(firstProblem(s)).toEqual({ pageId: "a", pageNo: 1, message: "Page 1 is cut off at the bottom.", action: "fix_crop" })
    expect(pageLabel(0, s.pages[0])).toBe("1 · cut off")
    const crop = { page: 1, corners: [[0, 0], [1, 0], [1, 1], [0, 1]] as [number, number][], rotation: 0 as const }
    s = captureReducer(s, { type: "crop_saved", id: "a", crop, url: "blob:new" })
    expect(s.pages[0]).toMatchObject({ issue: null, edge: null, url: "blob:new", crop })
    expect(canSendPages(s)).toBe(true)
    expect(pageCrops(s)).toEqual([crop])
  })

  it("retake marks a page for replacement; remove clears it", () => {
    let s = add(add(initialCapture, page("a")), page("b"))
    s = captureReducer(s, { type: "retake", id: "a" })
    s = add(s, page("z"))
    expect(s.pages.map((p) => p.id)).toEqual(["z", "b"])
    s = captureReducer(s, { type: "retake", id: "b" })
    s = captureReducer(s, { type: "remove", id: "b" })
    expect(s.retakeId).toBeNull()
    expect(captureReducer(s, { type: "reset" })).toEqual(initialCapture)
  })

  it("hints and labels", () => {
    const s = add(initialCapture, page("a"))
    expect(captureHint(s, { quadFound: true, stable: false, justCaptured: true, auto: true })).toEqual({ text: "Captured", tone: "info" })
    expect(captureHint(s, { quadFound: true, stable: false, justCaptured: false, auto: true })).toEqual({ text: "Hold still", tone: "busy" })
    expect(captureHint(s, { quadFound: true, stable: false, justCaptured: false, auto: false })).toBeNull()
    expect(captureHint(s, { quadFound: false, stable: false, justCaptured: false, auto: true })).toBeNull()
    expect(countLabel(1)).toBe("1 page")
    expect(countLabel(7)).toBe("7 pages")
    expect(pageLabel(8, page("x", { issue: "blurry" }))).toBe("9 · blurry")
  })
})
```

`web/tests/unit/scanFlow.test.ts`:
```ts
import { describe, expect, it } from "vitest"
import { flowReducer, initialFlow } from "@/lib/scan/flowMachine"

describe("flowReducer", () => {
  const file = new File(["%PDF"], "maths.pdf", { type: "application/pdf" })

  it("phone: camera → pages → crop → pages → sending → check", () => {
    let s = initialFlow("camera")
    expect(s.step).toBe("camera")
    s = flowReducer(s, { type: "capture_done" })
    expect(s.step).toBe("pages")
    s = flowReducer(s, { type: "edit_crop", pageId: "p1" })
    expect(s).toMatchObject({ step: "crop", pageId: "p1" })
    s = flowReducer(s, { type: "crop_closed" })
    expect(s.step).toBe("pages")
    s = flowReducer(s, { type: "send" })
    expect(s.step).toBe("sending")
    s = flowReducer(s, { type: "sent", paperId: "abc" })
    expect(s).toMatchObject({ step: "check", paperId: "abc" })
  })

  it("add page returns to the camera, back from pages too", () => {
    const pages = flowReducer(initialFlow("camera"), { type: "capture_done" })
    expect(flowReducer(pages, { type: "add_page" }).step).toBe("camera")
    expect(flowReducer(pages, { type: "back" }).step).toBe("camera")
  })

  it("desktop: upload → pdf chosen → sending; photos go to pages", () => {
    const s = initialFlow("upload")
    expect(flowReducer(s, { type: "pdf_chosen", file })).toMatchObject({ step: "sending", file })
    expect(flowReducer(s, { type: "photos_chosen" }).step).toBe("pages")
  })

  it("shared file waits on Check pages / Cancel", () => {
    const s = flowReducer(initialFlow("camera"), { type: "shared", file })
    expect(s).toMatchObject({ step: "shared", file })
    expect(flowReducer(s, { type: "send" }).step).toBe("sending")
    expect(flowReducer(s, { type: "back" }).step).toBe("camera")
  })

  it("failures: offline saves, other errors show send_failed and keep the source", () => {
    const sending = flowReducer(flowReducer(initialFlow("camera"), { type: "capture_done" }), { type: "send" })
    expect(flowReducer(sending, { type: "queued_offline", savedAt: 5 })).toMatchObject({ step: "saved_offline", savedAt: 5 })
    const failed = flowReducer(sending, { type: "send_failed", message: "413" })
    expect(failed).toMatchObject({ step: "send_failed", error: "413", returnTo: "pages" })
    expect(flowReducer(failed, { type: "back" }).step).toBe("pages")
    expect(flowReducer(failed, { type: "send" }).step).toBe("sending")
  })

  it("check: back goes to pages when they exist, else the entry", () => {
    const viaPages = flowReducer(flowReducer(flowReducer(initialFlow("camera"), { type: "capture_done" }), { type: "send" }), { type: "sent", paperId: "x" })
    expect(flowReducer(viaPages, { type: "back" }).step).toBe("pages")
    const viaPdf = flowReducer(flowReducer(initialFlow("upload"), { type: "pdf_chosen", file }), { type: "sent", paperId: "y" })
    expect(flowReducer(viaPdf, { type: "back" }).step).toBe("upload")
  })

  it("ignores events that do not apply", () => {
    const s = initialFlow("upload")
    expect(flowReducer(s, { type: "sent", paperId: "x" })).toBe(s)
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run tests/unit/captureModel.test.ts tests/unit/scanFlow.test.ts`
Expected: FAIL (modules not found).

- [ ] **Step 3: Implement `web/src/lib/scan/captureModel.ts`**

```ts
import type { PageCrop } from "@/lib/markingTypes"
import type { Quad } from "@/lib/scanner"
import type { Edge, PageIssue } from "@/lib/scan/pageQuality"

/* The page stack (mock C5). A blurry page blocks Done and is replaced by the next
 * capture ("Page 4 blurry · retaking"). A cut-off page passes capture but blocks
 * "Next: check paper" until its crop is saved or it is retaken. */

export interface CapturedPage {
  id: string
  /** Corrected (or cropped) page, what gets sent. */
  url: string
  /** The raw frame, kept so Fix crop can re-warp from the original. */
  originalUrl: string
  sourceWidth: number
  sourceHeight: number
  /** The detected quad in source pixels, or null for a manual shot with no page found. */
  quad: Quad | null
  issue: PageIssue | null
  edge: Edge | null
  crop: PageCrop | null
}

export interface CaptureState {
  pages: CapturedPage[]
  /** The page the next capture replaces. */
  retakeId: string | null
  /** Bumps on every capture; drives the Captured flash and badge bump. */
  flash: number
}

export type CaptureAction =
  | { type: "captured"; page: CapturedPage }
  | { type: "remove"; id: string }
  | { type: "retake"; id: string }
  | { type: "crop_saved"; id: string; crop: PageCrop; url: string }
  | { type: "reset" }

export const initialCapture: CaptureState = { pages: [], retakeId: null, flash: 0 }

export function captureReducer(state: CaptureState, action: CaptureAction): CaptureState {
  switch (action.type) {
    case "captured": {
      const { page } = action
      const index = state.retakeId ? state.pages.findIndex((p) => p.id === state.retakeId) : -1
      const pages = index === -1 ? [...state.pages, page] : state.pages.map((p, i) => (i === index ? page : p))
      return { pages, retakeId: page.issue === "blurry" ? page.id : null, flash: state.flash + 1 }
    }
    case "remove":
      return {
        ...state,
        pages: state.pages.filter((p) => p.id !== action.id),
        retakeId: state.retakeId === action.id ? null : state.retakeId,
      }
    case "retake":
      return { ...state, retakeId: action.id }
    case "crop_saved":
      return {
        ...state,
        pages: state.pages.map((p) =>
          p.id === action.id
            ? { ...p, crop: action.crop, url: action.url, issue: p.issue === "cut_off" ? null : p.issue, edge: null }
            : p,
        ),
      }
    case "reset":
      return initialCapture
  }
}

export function canFinishCapture(state: CaptureState): boolean {
  return state.pages.length > 0 && !state.pages.some((p) => p.issue === "blurry")
}

export function canSendPages(state: CaptureState): boolean {
  return state.pages.length > 0 && state.pages.every((p) => p.issue === null)
}

export function firstProblem(
  state: CaptureState,
): { pageId: string; pageNo: number; message: string; action: "fix_crop" | "retake" } | null {
  const index = state.pages.findIndex((p) => p.issue !== null)
  if (index === -1) return null
  const page = state.pages[index]
  const pageNo = index + 1
  return page.issue === "blurry"
    ? { pageId: page.id, pageNo, message: `Page ${pageNo} is blurry.`, action: "retake" }
    : { pageId: page.id, pageNo, message: `Page ${pageNo} is cut off at the ${page.edge ?? "edge"}.`, action: "fix_crop" }
}

export type HintTone = "info" | "busy" | "error"

export function captureHint(
  state: CaptureState,
  live: { quadFound: boolean; stable: boolean; justCaptured: boolean; auto: boolean },
): { text: string; tone: HintTone } | null {
  const retakeIndex = state.retakeId ? state.pages.findIndex((p) => p.id === state.retakeId) : -1
  if (retakeIndex !== -1 && state.pages[retakeIndex].issue === "blurry") {
    return { text: `Page ${retakeIndex + 1} blurry · retaking`, tone: "error" }
  }
  if (live.justCaptured) return { text: "Captured", tone: "info" }
  if (live.quadFound && live.auto && !live.stable) return { text: "Hold still", tone: "busy" }
  return null
}

export function pageLabel(index: number, page: CapturedPage): string {
  if (page.issue === "cut_off") return `${index + 1} · cut off`
  if (page.issue === "blurry") return `${index + 1} · blurry`
  return String(index + 1)
}

export function countLabel(n: number): string {
  return `${n} ${n === 1 ? "page" : "pages"}`
}

/** Saved crops for upload, renumbered to the final page order. */
export function pageCrops(state: CaptureState): PageCrop[] {
  return state.pages.flatMap((p, i) => (p.crop ? [{ ...p.crop, page: i + 1 }] : []))
}
```

- [ ] **Step 4: Implement `web/src/lib/scan/flowMachine.ts`**

```ts
/* Which screen of the student "get a paper in" flow is showing. Marking itself lives on
 * its own route (/student/correct/:paperId), so this machine ends at "check". */

export type FlowStepName =
  | "camera"
  | "upload"
  | "pages"
  | "crop"
  | "shared"
  | "sending"
  | "saved_offline"
  | "send_failed"
  | "check"

export interface FlowState {
  step: FlowStepName
  entry: "camera" | "upload"
  /** Set when the pages grid holds the paper (camera or picked photos). */
  hasPages: boolean
  pageId?: string
  file?: File
  paperId?: string
  savedAt?: number
  error?: string
  returnTo?: FlowStepName
}

export type FlowEvent =
  | { type: "open_camera" }
  | { type: "open_upload" }
  | { type: "capture_done" }
  | { type: "photos_chosen" }
  | { type: "pdf_chosen"; file: File }
  | { type: "shared"; file: File }
  | { type: "edit_crop"; pageId: string }
  | { type: "crop_closed" }
  | { type: "add_page" }
  | { type: "send" }
  | { type: "sent"; paperId: string }
  | { type: "queued_offline"; savedAt: number }
  | { type: "send_failed"; message: string }
  | { type: "back" }

export function initialFlow(entry: "camera" | "upload"): FlowState {
  return { step: entry, entry, hasPages: false }
}

function source(state: FlowState): FlowStepName {
  return state.hasPages ? "pages" : state.entry
}

export function flowReducer(state: FlowState, event: FlowEvent): FlowState {
  switch (event.type) {
    case "open_camera":
      return { ...state, step: "camera" }
    case "open_upload":
      return { ...state, step: "upload" }
    case "capture_done":
    case "photos_chosen":
      return { ...state, step: "pages", hasPages: true, file: undefined }
    case "pdf_chosen":
      return { ...state, step: "sending", hasPages: false, file: event.file }
    case "shared":
      return { ...state, step: "shared", hasPages: false, file: event.file }
    case "edit_crop":
      return state.step === "pages" ? { ...state, step: "crop", pageId: event.pageId } : state
    case "crop_closed":
      return state.step === "crop" ? { ...state, step: "pages", pageId: undefined } : state
    case "add_page":
      return { ...state, step: "camera" }
    case "send":
      return state.step === "pages" || state.step === "shared" || state.step === "send_failed"
        ? { ...state, step: "sending", error: undefined }
        : state
    case "sent":
      return state.step === "sending" ? { ...state, step: "check", paperId: event.paperId } : state
    case "queued_offline":
      return state.step === "sending" ? { ...state, step: "saved_offline", savedAt: event.savedAt } : state
    case "send_failed":
      return state.step === "sending"
        ? { ...state, step: "send_failed", error: event.message, returnTo: source(state) }
        : state
    case "back":
      switch (state.step) {
        case "pages":
        case "shared":
          return { ...state, step: state.entry, file: undefined }
        case "crop":
          return { ...state, step: "pages", pageId: undefined }
        case "send_failed":
          return { ...state, step: state.returnTo ?? source(state) }
        case "check":
          return { ...state, step: source(state), paperId: undefined }
        default:
          return state
      }
  }
}
```

- [ ] **Step 5: Run to verify pass**

Run: `npx vitest run tests/unit/captureModel.test.ts tests/unit/scanFlow.test.ts`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
npx oxlint src/lib/scan
git commit -S -m "feat(web): capture page stack and scan flow machine" -- web/src/lib/scan/captureModel.ts web/src/lib/scan/flowMachine.ts web/tests/unit/captureModel.test.ts web/tests/unit/scanFlow.test.ts
```

---

### Task 13: Offline queue: one drain per tab, entry details, banner copy

**Files:**
- Modify: `web/src/lib/offline/uploadQueue.ts` (optional `pages`, `title` on entries)
- Modify: `web/src/lib/offline/useUploadQueue.ts` (module-level drain guard, `entries`)
- Create: `web/src/lib/scan/queueCopy.ts`
- Test: `web/tests/unit/queueCopy.test.ts`; re-run `web/tests/unit/uploadQueue.test.ts`, `queueDecision.test.ts`, `offlineWiring.test.ts`

**Interfaces:**
- Produces: `QueuedUpload.pages?: number`, `QueuedUpload.title?: string`; `useUploadQueue(): { count: number; entries: QueuedSummary[]; retry: () => void }`; `QueuedSummary { id; title: string; pages: number | null; createdAt: number }`; `queueBannerText(count)`, `savedAgo(createdAt, now)`; `drainOnce(): Promise<void>` (module-level, exported for tests).

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest"
import { queueBannerText, savedAgo } from "@/lib/scan/queueCopy"

describe("queueCopy", () => {
  it("banner text", () => {
    expect(queueBannerText(0)).toBeNull()
    expect(queueBannerText(1)).toBe("1 paper waiting to send")
    expect(queueBannerText(3)).toBe("3 papers waiting to send")
  })
  it("saved ago", () => {
    const now = 10 * 60_000
    expect(savedAgo(now - 30_000, now)).toBe("saved just now")
    expect(savedAgo(now - 2 * 60_000, now)).toBe("saved 2 min ago")
    expect(savedAgo(now - 3 * 3_600_000, now + 3 * 3_600_000)).toBe("saved 6 h ago")
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run tests/unit/queueCopy.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

`web/src/lib/scan/queueCopy.ts`:
```ts
export function queueBannerText(count: number): string | null {
  if (count <= 0) return null
  return `${count} ${count === 1 ? "paper" : "papers"} waiting to send`
}

export function savedAgo(createdAt: number, now: number): string {
  const minutes = Math.round((now - createdAt) / 60_000)
  if (minutes < 1) return "saved just now"
  if (minutes < 60) return `saved ${minutes} min ago`
  return `saved ${Math.round(minutes / 60)} h ago`
}
```

`web/src/lib/offline/uploadQueue.ts`: add to `QueuedUpload`, after `createdAt`:
```ts
  /** Page count, for the Offline · saved card ("16 pages · saved 2 min ago"). */
  pages?: number
  /** Card title, e.g. "Mathematics · 0580/42", or the file name. */
  title?: string
```
`enqueueUpload`'s parameter type already derives from `QueuedUpload`, so callers may pass both.

`web/src/lib/offline/useUploadQueue.ts`: replace the per-instance `draining` ref with a module-level guard so the shell banner and the saved screen (two hook instances) can never drain twice in parallel (a second drain would POST `/student/correct` twice for one paper):
```ts
let drainInFlight: Promise<void> | null = null
const listeners = new Set<() => void>()

/** One drain per tab, shared by every hook instance. Exported for tests. */
export function drainOnce(): Promise<void> {
  if (drainInFlight) return drainInFlight
  drainInFlight = drainUploadQueue({ upload: uploadQueuedEntry, correct: correctQueuedPaper })
    .then(() => undefined)
    .catch(() => undefined)
    .finally(() => {
      drainInFlight = null
      listeners.forEach((notify) => notify())
    })
  return drainInFlight
}

export interface QueuedSummary {
  id: string
  title: string
  pages: number | null
  createdAt: number
}

export interface UseUploadQueueResult {
  count: number
  entries: QueuedSummary[]
  retry: () => void
}

export function useUploadQueue(): UseUploadQueueResult {
  const [entries, setEntries] = useState<QueuedSummary[]>([])
  const queryClient = useQueryClient()

  const refresh = useCallback(async () => {
    const queued = await listQueuedUploads()
    setEntries(
      queued
        .sort((a, b) => a.createdAt - b.createdAt)
        .map((e) => ({ id: e.id, title: e.title ?? e.scanName, pages: e.pages ?? null, createdAt: e.createdAt })),
    )
  }, [])

  const drain = useCallback(() => {
    void drainOnce()
  }, [])

  useEffect(() => {
    const onDrained = () => {
      void refresh()
      void queryClient.invalidateQueries({ queryKey: ["student", "upload", "active"] })
    }
    listeners.add(onDrained)
    void refresh()
    drain()
    window.addEventListener("online", drain)
    const onMessage = (event: MessageEvent): void => {
      const data = event.data as { type?: unknown } | undefined
      if (data?.type === SW_DRAIN_MESSAGE) drain()
    }
    navigator.serviceWorker?.addEventListener("message", onMessage)
    return () => {
      listeners.delete(onDrained)
      window.removeEventListener("online", drain)
      navigator.serviceWorker?.removeEventListener("message", onMessage)
    }
  }, [drain, refresh, queryClient])

  return { count: entries.length, entries, retry: drain }
}
```
Keep `uploadQueuedEntry`, `correctQueuedPaper` and `SW_DRAIN_MESSAGE` as they are, and keep the module's doc comment, adding one paragraph: "The drain guard is module-level since L6: the shell banner and the Offline · saved screen both mount this hook, and a per-instance guard would let both drain at once."

- [ ] **Step 4: Run to verify pass**

Run: `npx vitest run tests/unit/queueCopy.test.ts tests/unit/uploadQueue.test.ts tests/unit/queueDecision.test.ts tests/unit/offlineWiring.test.ts`
Expected: all passed. If `offlineWiring.test.ts` pins `useRef` drain wording, update its assertion to the module-level `drainOnce` and say why in the test's comment.

- [ ] **Step 5: Commit**

```bash
npx oxlint src/lib/offline src/lib/scan/queueCopy.ts
git commit -S -m "feat(web): one offline drain per tab and queue card details" -- web/src/lib/offline/uploadQueue.ts web/src/lib/offline/useUploadQueue.ts web/src/lib/scan/queueCopy.ts web/tests/unit/queueCopy.test.ts web/tests/unit/offlineWiring.test.ts
```

---

Screen tasks (14–20) go to the `designer` agent. **Before any UI edit:** invoke the `impeccable` skill, read `.claude/skills/impeccable/reference/craft-floor.md`, and read the three taste memories named in the master plan. Keep the mock's copy word for word. Every number uses `font-mono` (or `font-display` for the big hero figures, as the mock does). Each screen task ends with the touched-file type check and lint: `npx tsc -p tsconfig.app.json --noEmit && npx oxlint <files> && npm run check:copy && npm run check:native`. Screens have no unit tests (Vitest runs in node); their decisions are tested through the view models, and each screen gets a Playwright pass in Task 21.

F1 kit used: `Binny` (marking/sending/next/came-back heroes, student only, `size={72}`), nothing else from F1 is needed by these screens. Existing kit used: `Sheet`/`SheetContent side="bottom"` (`components/ui/sheet.tsx`), `useToast` (`components/ui/toast.tsx`), `PageHeading` (`components/ui/page-heading.tsx`) for the one `h1` per page.

### Task 14: Shared scan parts and the app-wide queued banner

**Files:**
- Create: `web/src/components/scan/styles.ts` (the recipes from the Token map section, verbatim)
- Create: `web/src/components/scan/scanIcons.tsx`, `AppBar.tsx`, `InlineAlert.tsx`, `downloadBlob.ts`, `QueuedUploadsBanner.tsx`
- Modify: `web/src/portals/student/shell.tsx` (import and render `<QueuedUploadsBanner />` once, directly above the routed outlet inside the page column)

**Interfaces:**
- Produces: `Icon.{Close, File, Torch, Arrow, Back, Download, Pencil, Plus, Rotate, Camera, Trash, Photos, Pdf, PdfCheck, CameraOff, Phone, WifiOff, Tick, Upload}` (the mock's drawn SVGs, `aria-hidden`); `AppBar({ title, sub, onBack?, backLabel?, onDownload?, closeIcon? })`; `InlineAlert({ children, sub?, action?, tone? })`; `downloadUrl(url, filename)`; `QueuedUploadsBanner()`.

- [ ] **Step 1: Icons (`scanIcons.tsx`)** — one component per mock SVG, same viewBox, stroke and paths:

```tsx
import type { SVGProps } from "react"

type P = SVGProps<SVGSVGElement>
const base = { fill: "none", stroke: "currentColor", "aria-hidden": true } as const

export const Icon = {
  Close: (p: P) => (<svg width={20} height={20} viewBox="0 0 20 20" strokeWidth={1.8} strokeLinecap="round" {...base} {...p}><path d="M5 5l10 10M15 5 5 15" /></svg>),
  File: (p: P) => (<svg width={20} height={20} viewBox="0 0 20 20" strokeWidth={1.7} strokeLinejoin="round" {...base} {...p}><path d="M5 2.5h6.5l3.5 3.5v11.5H5z" /><path d="M11.5 2.5V6H15" /></svg>),
  Torch: (p: P) => (<svg width={20} height={20} viewBox="0 0 20 20" strokeWidth={1.7} strokeLinejoin="round" {...base} {...p}><path d="M11 2 5 11h4l-1 7 6-9h-4l1-7Z" /></svg>),
  Arrow: (p: P) => (<svg width={18} height={18} viewBox="0 0 18 18" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" {...base} {...p}><path d="M4 9h10M10 5l4 4-4 4" /></svg>),
  Back: (p: P) => (<svg width={20} height={20} viewBox="0 0 20 20" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" {...base} {...p}><path d="M12.5 4 6.5 10l6 6" /></svg>),
  Download: (p: P) => (<svg width={20} height={20} viewBox="0 0 20 20" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" {...base} {...p}><path d="M10 3v9M6.5 8.5 10 12l3.5-3.5M4 15h12" /></svg>),
  Pencil: (p: P) => (<svg width={14} height={14} viewBox="0 0 16 16" strokeWidth={1.7} strokeLinejoin="round" {...base} {...p}><path d="M3 13l1-3.5 7-7 2.5 2.5-7 7z" /></svg>),
  Plus: (p: P) => (<svg width={22} height={22} viewBox="0 0 22 22" strokeWidth={1.9} strokeLinecap="round" {...base} {...p}><path d="M11 5v12M5 11h12" /></svg>),
  Rotate: (p: P) => (<svg width={22} height={22} viewBox="0 0 22 22" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" {...base} {...p}><path d="M5 11a6 6 0 1 0 2-4.5" /><path d="M5 3.5V7h3.5" /></svg>),
  Camera: ({ size = 22, ...p }: P & { size?: number }) => (<svg width={size} height={size} viewBox="0 0 22 22" strokeWidth={1.7} strokeLinejoin="round" {...base} {...p}><rect x={3} y={6} width={16} height={12} rx={3} /><circle cx={11} cy={12} r={3.2} /><path d="M8 6l1.5-2h3L14 6" /></svg>),
  CameraOff: (p: P) => (<svg width={34} height={34} viewBox="0 0 22 22" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" {...base} {...p}><rect x={3} y={6} width={16} height={12} rx={3} /><circle cx={11} cy={12} r={3.2} /><path d="M8 6l1.5-2h3L14 6M3 3l16 16" /></svg>),
  Trash: (p: P) => (<svg width={22} height={22} viewBox="0 0 22 22" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" {...base} {...p}><path d="M4 6h14M9 6V4h4v2M6 6l1 12h8l1-12" /></svg>),
  Photos: (p: P) => (<svg width={22} height={22} viewBox="0 0 22 22" strokeWidth={1.7} strokeLinejoin="round" {...base} {...p}><rect x={3} y={4} width={16} height={14} rx={3} /><circle cx={8} cy={9} r={1.6} /><path d="m3.5 16 4.5-4.5 3.5 3.5 2.5-2.5 4.5 4.5" /></svg>),
  Pdf: (p: P) => (<svg width={22} height={22} viewBox="0 0 22 22" strokeWidth={1.7} strokeLinejoin="round" {...base} {...p}><path d="M5.5 2.5h7l4 4v13h-11z" /><path d="M12.5 2.5v4h4" /></svg>),
  PdfCheck: (p: P) => (<svg width={22} height={22} viewBox="0 0 22 22" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" {...base} {...p}><path d="M5.5 2.5h7l4 4v13h-11z" /><path d="M12.5 2.5v4h4M8.5 13l2 2 3.5-4" /></svg>),
  Upload: (p: P) => (<svg width={28} height={28} viewBox="0 0 28 28" strokeWidth={2} strokeLinejoin="round" {...base} {...p}><path d="M7 3h10l6 6v16H7z" /><path d="M17 3v6h6M14 21v-8M10.5 16.5 14 13l3.5 3.5" /></svg>),
  Phone: (p: P) => (<svg width={20} height={20} viewBox="0 0 20 20" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" {...base} {...p}><rect x={6} y={2.5} width={8} height={15} rx={2} /><path d="M2.5 7.5a6 6 0 0 1 2-3.5M2.5 4v3.5H6" /></svg>),
  WifiOff: (p: P) => (<svg width={30} height={30} viewBox="0 0 22 22" strokeWidth={1.7} strokeLinecap="round" {...base} {...p}><path d="M3 8.5a12 12 0 0 1 16 0M6 11.5a8 8 0 0 1 10 0M9 14.5a3.5 3.5 0 0 1 4 0M4 4l14 14" /><circle cx={11} cy={17.5} r={1} fill="currentColor" /></svg>),
  Tick: (p: P) => (<svg width={18} height={18} viewBox="0 0 16 16" strokeWidth={2.25} strokeLinecap="square" {...base} {...p}><path d="M3.5 8.5 6.5 11.5 12.5 4.5" /></svg>),
}
```

- [ ] **Step 2: `AppBar.tsx` (mock `.abar`) and `InlineAlert.tsx` (mock `.inl`)**

```tsx
import type { ReactNode } from "react"
import { Icon } from "./scanIcons"
import { iconLight } from "./styles"
import { PageHeading } from "@/components/ui/page-heading"

export function AppBar({ title, sub, onBack, backLabel = "Back", onDownload, closeIcon = false, trailing }: {
  title: string
  sub?: string
  onBack?: () => void
  backLabel?: string
  onDownload?: () => void
  closeIcon?: boolean
  trailing?: ReactNode
}) {
  return (
    <div className="flex items-center gap-2.5 px-4 py-3.5">
      {onBack ? (
        <button type="button" className={iconLight} aria-label={backLabel} onClick={onBack}>
          {closeIcon ? <Icon.Close /> : <Icon.Back />}
        </button>
      ) : null}
      <div className="min-w-0 flex-1">
        <PageHeading repeatsTitle={false} className="text-[21px] font-extrabold leading-[1.2]">{title}</PageHeading>
        {sub ? <span className="font-mono text-xs font-semibold text-on-surface-variant">{sub}</span> : null}
      </div>
      {onDownload ? (
        <button type="button" className={iconLight} aria-label="Download scan as PDF" onClick={onDownload}>
          <Icon.Download />
        </button>
      ) : null}
      {trailing}
    </div>
  )
}
```
(Check `PageHeading`'s props in `components/ui/page-heading.tsx`; it is the codebase's one-`h1` helper used by both screens being replaced.)

```tsx
import type { ReactNode } from "react"

export function InlineAlert({ children, sub, action, tone = "error" }: {
  children: ReactNode
  sub?: string
  action?: { label: string; onClick: () => void }
  tone?: "error" | "info"
}) {
  const bg = tone === "error" ? "bg-error-container" : "bg-primary-container"
  const fg = tone === "error" ? "text-on-error-container" : "text-primary"
  return (
    <div role="alert" className={`flex items-center gap-3 rounded-inner px-3.5 py-3 ${bg}`}>
      <p className={`flex-1 text-sm font-semibold leading-[1.35] ${fg}`}>
        {children}
        {sub ? <span className="mt-0.5 block text-[13px] font-medium leading-[1.4] opacity-85">{sub}</span> : null}
      </p>
      {action ? (
        <button type="button" onClick={action.onClick} className="min-h-11 rounded-button bg-surface-container-lowest px-3.5 text-sm font-bold text-primary motion-safe:active:scale-[.97]">
          {action.label}
        </button>
      ) : null}
    </div>
  )
}
```

- [ ] **Step 3: `downloadBlob.ts`**

```ts
/** Save an object URL as a file, then revoke it. */
export function downloadUrl(url: string, filename: string): void {
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
```

- [ ] **Step 4: `QueuedUploadsBanner.tsx`** (mock: "Shown as a banner elsewhere in the app too ('1 paper waiting to send'). Signing out clears it.")

```tsx
import { useUploadQueue } from "@/lib/offline/useUploadQueue"
import { queueBannerText } from "@/lib/scan/queueCopy"
import { Icon } from "./scanIcons"

export function QueuedUploadsBanner() {
  const { count, retry } = useUploadQueue()
  const text = queueBannerText(count)
  if (!text) return null
  return (
    <div role="status" className="mx-4 mb-3 flex items-center gap-3 rounded-inner bg-primary-container px-3.5 py-2.5 tablet:mx-0">
      <Icon.WifiOff width={20} height={20} className="flex-none text-primary" />
      <p className="flex-1 text-sm font-semibold text-primary">{text}</p>
      <button type="button" onClick={retry} className="min-h-11 rounded-button bg-surface-container-lowest px-3.5 text-sm font-bold text-primary">
        Try now
      </button>
    </div>
  )
}
```
(`tablet:` is the breakpoint name used in this codebase, see `max-tablet:` in `CorrectPaper.tsx`; confirm in `index.css` and use its exact name.)

Shell edit: in `portals/student/shell.tsx`, add `import { QueuedUploadsBanner } from "@/components/scan/QueuedUploadsBanner"` and render `<QueuedUploadsBanner />` once above the routed content. This is the only change to the shell file; the hook now drains app-wide (keep-list K23, K25).

- [ ] **Step 5: Type check, lint, commit**

```bash
npx tsc -p tsconfig.app.json --noEmit && npx oxlint src/components/scan src/portals/student/shell.tsx && npm run check:copy && npm run check:native
git commit -S -m "feat(web): shared scan parts and app-wide queued uploads banner" -- web/src/components/scan/styles.ts web/src/components/scan/scanIcons.tsx web/src/components/scan/AppBar.tsx web/src/components/scan/InlineAlert.tsx web/src/components/scan/downloadBlob.ts web/src/components/scan/QueuedUploadsBanner.tsx web/src/portals/student/shell.tsx
```

---

### Task 15: Scanner camera, camera states and the page stack

**Files:**
- Create: `web/src/components/scan/ScannerCamera.tsx`, `CameraStateScreen.tsx`, `PageStack.tsx`

**Interfaces:**
- Consumes: `captureReducer` family (Task 12), `assessPage` (Task 11), `cameraErrorKind`/`CAMERA_ERROR_COPY` (Task 11), `@/lib/scanner` (`analyseFrame`, `correctPerspective`, `stabilityDecision`, `torchSupported`, `setTorch`, `ANALYSIS_WIDTH`), `useWakeLock` (`lib/wakeLock.ts`), `randomUuid`.
- Produces:
  - `ScannerCamera({ capture, dispatch, autoStart, onDone, onClose, onOpenUploadSheet })` — owns the stream, the analysis loop and capture; `capture`/`dispatch` come from the parent's `useReducer(captureReducer, initialCapture)` so pages survive leaving the camera.
  - `CameraStateScreen({ kind: "tap" | "starting" | CameraErrorKind, onPrimary, onUpload, onClose, embedded? })`
  - `PageStack({ count, error, flash, onOpen })`

Layout (mock `.cam`, `.topbar`, `.hint`, `.cnt3`, `.bot3`): a full-height dark stage (`fixed inset-0 z-40 bg-inverse-surface` on phones, so the PortalShell tab bar is covered while capturing, as in the mock; the shell itself is untouched).

- [ ] **Step 1: `PageStack.tsx`**

```tsx
import { useEffect, useState } from "react"

export function PageStack({ count, error, flash, onOpen }: { count: number; error: boolean; flash: number; onOpen: () => void }) {
  const [bump, setBump] = useState(false)
  useEffect(() => {
    if (flash === 0) return
    setBump(true)
    const t = window.setTimeout(() => setBump(false), 200)
    return () => window.clearTimeout(t)
  }, [flash])
  return (
    <button type="button" onClick={onOpen} disabled={count === 0} aria-label={`Your pages, ${count}`} className="relative h-[68px] w-[52px] justify-self-start disabled:opacity-40">
      <span className="absolute inset-0 -rotate-[7deg] rounded-md bg-surface-container-lowest shadow-[0_0_0_1px_oklch(0_0_0/.08)]" />
      <span className="absolute inset-0 rotate-[4deg] rounded-md bg-surface-container-lowest shadow-[0_0_0_1px_oklch(0_0_0/.08)]" />
      <span
        key={flash}
        className="absolute inset-0 rounded-md bg-surface-container-lowest bg-clip-content px-1.5 py-2 shadow-[0_0_0_1px_oklch(0_0_0/.08)] [background-image:repeating-linear-gradient(transparent_0_7px,var(--color-primary-container)_7px_8px)] motion-safe:animate-[stack-in_280ms_var(--ease-out)]"
      />
      {count > 0 ? (
        <b
          className={`absolute -right-2.5 -top-2 z-[2] grid h-6 min-w-6 place-items-center rounded-xl px-1.5 font-mono text-xs font-bold transition-transform duration-200 ease-spring ${error ? "bg-error text-on-error" : "bg-inverse-primary text-primary"} ${bump ? "motion-safe:scale-[1.15]" : ""}`}
        >
          {count}
        </b>
      ) : null}
    </button>
  )
}
```
Add to `web/src/index.css`? **No** (token rule). Define the keyframe in a component-scoped `<style>` is also out. Use Tailwind 4 arbitrary animation with an inline keyframe declared once in `styles.ts` as a CSS string injected by `ScannerCamera` via `<style>{STACK_IN_KEYFRAMES}</style>`:
```ts
export const STACK_IN_KEYFRAMES = "@keyframes stack-in{from{transform:translateY(-40px)}to{transform:none}}@keyframes quad-flash{0%,100%{fill-opacity:.1}40%{fill-opacity:.38}}"
```
(append to `styles.ts`).

- [ ] **Step 2: `CameraStateScreen.tsx`** (mock "Camera needs a tap", "Camera blocked" and variants, "Starting camera…")

```tsx
import { CAMERA_ERROR_COPY, type CameraErrorKind } from "@/lib/scan/entryMode"
import { Icon } from "./scanIcons"
import { btnTide, display30, iconDark, linkTide } from "./styles"

export type CameraScreenKind = "tap" | "starting" | CameraErrorKind

export function CameraStateScreen({ kind, onPrimary, onUpload, onClose, embedded = false }: {
  kind: CameraScreenKind
  onPrimary: () => void
  onUpload: () => void
  onClose?: () => void
  embedded?: boolean
}) {
  const error = kind !== "tap" && kind !== "starting"
  const copy =
    kind === "tap"
      ? { title: "Scan your paper", body: "Lemely needs your camera to photograph each page." }
      : kind === "starting"
        ? { title: "Starting camera…", body: "" }
        : CAMERA_ERROR_COPY[kind]
  const frame = embedded
    ? "relative rounded-[28px] px-6 py-9"
    : "absolute inset-0 p-8"
  return (
    <div className={`${frame} grid content-center justify-items-center gap-3.5 bg-inverse-surface text-center text-white`} role={error ? "alert" : undefined}>
      {onClose && !embedded ? (
        <button type="button" aria-label="Close" onClick={onClose} className={`${iconDark} absolute left-4 top-3.5`}>
          <Icon.Close />
        </button>
      ) : null}
      <span className={error ? "text-error" : "text-inverse-primary"}>{error ? <Icon.CameraOff /> : <Icon.Camera size={34} />}</span>
      <h2 className={`${display30} max-w-[12em]`} aria-live="polite">{copy.title}</h2>
      {copy.body && !embedded ? <p className="max-w-[30ch] text-pretty text-white/80">{copy.body}</p> : null}
      {kind !== "starting" ? (
        <div className="mt-2.5 grid w-full gap-1.5">
          <button type="button" className={btnTide} onClick={onPrimary}>
            {kind === "tap" ? (embedded ? "Open camera" : "Turn on camera") : "Try again"}
          </button>
          <button type="button" className={linkTide} onClick={onUpload}>Upload a file instead</button>
        </div>
      ) : null}
    </div>
  )
}
```
Error icon colour: the mock's `oklch(.72 .15 25)` is lighter than `error`; on `inverse-surface` the `error` token passes 3:1 for a non-text glyph. Listed in the PR.

- [ ] **Step 3: `ScannerCamera.tsx`**

```tsx
import { useEffect, useReducer, useRef, useState, type Dispatch } from "react"
import type * as Scanner from "@/lib/scanner"
import type { Quad } from "@/lib/scanner"
import { canFinishCapture, captureHint, countLabel, type CaptureAction, type CaptureState } from "@/lib/scan/captureModel"
import { assessPage } from "@/lib/scan/pageQuality"
import { cameraErrorKind, type CameraErrorKind } from "@/lib/scan/entryMode"
import { useWakeLock } from "@/lib/wakeLock"
import { randomUuid } from "@/lib/uuid"
import { CameraStateScreen } from "./CameraStateScreen"
import { PageStack } from "./PageStack"
import { Icon } from "./scanIcons"
import { iconDark, STACK_IN_KEYFRAMES } from "./styles"

type Phase = "tap" | "starting" | "live" | { error: CameraErrorKind }

export interface ScannerCameraProps {
  capture: CaptureState
  dispatch: Dispatch<CaptureAction>
  /** True only after a deliberate tap (K2): the student chose the camera. */
  autoStart: boolean
  onDone: () => void
  onClose: () => void
  onOpenUploadSheet: () => void
}

function useLandscape(): boolean {
  const query = "(orientation: landscape) and (pointer: coarse)"
  const [on, setOn] = useState(() => window.matchMedia?.(query).matches ?? false)
  useEffect(() => {
    const mql = window.matchMedia?.(query)
    if (!mql) return
    const onChange = () => setOn(mql.matches)
    mql.addEventListener("change", onChange)
    return () => mql.removeEventListener("change", onChange)
  }, [])
  return on
}

export function ScannerCamera({ capture, dispatch, autoStart, onDone, onClose, onOpenUploadSheet }: ScannerCameraProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const polygonRef = useRef<SVGPolygonElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const scannerRef = useRef<typeof Scanner | null>(null)
  const quadRef = useRef<Quad | null>(null)
  const analysisRef = useRef({ width: 0, height: 0, luma: null as Float32Array | null })
  const deltasRef = useRef<number[]>([])
  const armedRef = useRef(true)
  const [phase, setPhase] = useState<Phase>(autoStart ? "starting" : "tap")
  const [retry, bumpRetry] = useReducer((n: number) => n + 1, 0)
  const [auto, setAuto] = useState(true)
  const [torch, setTorch] = useState<{ available: boolean; on: boolean }>({ available: false, on: false })
  const [live, setLive] = useState({ quadFound: false, stable: false })
  const [justCaptured, setJustCaptured] = useState(false)
  const landscape = useLandscape()

  useWakeLock(phase === "live")

  // K6: acquire the rear camera only after a tap; stop tracks on leave.
  useEffect(() => {
    if (phase !== "starting") return
    if (!navigator.mediaDevices?.getUserMedia) {
      setPhase({ error: cameraErrorKind("no-getusermedia") })
      return
    }
    let cancelled = false
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "environment" } })
      .then((stream) => {
        if (cancelled) return stream.getTracks().forEach((t) => t.stop())
        streamRef.current = stream
        if (videoRef.current) videoRef.current.srcObject = stream
        setPhase("live")
      })
      .catch((err: unknown) => {
        if (!cancelled) setPhase({ error: cameraErrorKind(err) })
      })
    return () => {
      cancelled = true
    }
  }, [phase, retry])

  useEffect(() => () => streamRef.current?.getTracks().forEach((t) => t.stop()), [])

  // Re-arm auto-capture after every page (K9).
  useEffect(() => {
    armedRef.current = true
    deltasRef.current = []
  }, [capture.flash])

  const takePage = (): void => {
    const video = videoRef.current
    if (!video?.videoWidth) return
    const canvas = document.createElement("canvas")
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const ctx = canvas.getContext("2d")
    if (!ctx) return
    ctx.drawImage(video, 0, 0)
    const scanner = scannerRef.current
    const a = analysisRef.current
    const quad = quadRef.current && a.width ? (quadRef.current.map((p) => ({ x: (p.x * canvas.width) / a.width, y: (p.y * canvas.height) / a.height })) as Quad) : null
    const quality = assessPage({
      luma: a.luma ?? new Float32Array(),
      lumaWidth: scanner ? Math.min(scanner.ANALYSIS_WIDTH, a.width) : 0,
      lumaHeight: a.luma && a.width ? Math.round(a.luma.length / Math.min(scanner?.ANALYSIS_WIDTH ?? a.width, a.width)) : 0,
      quad: quadRef.current,
      frameWidth: a.width,
      frameHeight: a.height,
    })
    canvas.toBlob((rawBlob) => {
      if (!rawBlob) return
      const originalUrl = URL.createObjectURL(rawBlob)
      if (scanner && quad) {
        try {
          ctx.putImageData(scanner.correctPerspective(ctx, canvas.width, canvas.height, quad), 0, 0)
        } catch {
          // K11: keep the raw frame when the warp fails.
        }
      }
      canvas.toBlob((blob) => {
        if (!blob) return
        dispatch({
          type: "captured",
          page: {
            id: randomUuid(),
            url: URL.createObjectURL(blob),
            originalUrl,
            sourceWidth: canvas.width,
            sourceHeight: canvas.height,
            quad,
            issue: quality.issue,
            edge: quality.edge,
            crop: null,
          },
        })
        setJustCaptured(true)
        window.setTimeout(() => setJustCaptured(false), 900)
      }, "image/jpeg", 0.92)
    }, "image/jpeg", 0.92)
  }
  const takeRef = useRef(takePage)
  takeRef.current = takePage

  // Analysis loop (K8, K9): every third frame, find the quad, decide stability.
  useEffect(() => {
    if (phase !== "live") return
    const video = videoRef.current
    if (!video) return
    let cancelled = false
    let raf = 0
    let prev: Float32Array | null = null
    const canvas = document.createElement("canvas")
    void import("@/lib/scanner").then((scanner) => {
      if (cancelled) return
      scannerRef.current = scanner
      const track = streamRef.current?.getVideoTracks()[0]
      setTorch({ available: Boolean(track && scanner.torchSupported(track)), on: false })
      const ctx = canvas.getContext("2d", { willReadFrequently: true })
      if (!ctx) return
      let frame = 0
      const tick = () => {
        if (cancelled) return
        raf = requestAnimationFrame(tick)
        if (++frame % 3 !== 0 || !video.videoWidth) return
        const w = Math.min(scanner.ANALYSIS_WIDTH, video.videoWidth)
        const h = Math.max(1, Math.round((video.videoHeight * w) / video.videoWidth))
        if (canvas.width !== w) { canvas.width = w; canvas.height = h }
        ctx.drawImage(video, 0, 0, w, h)
        const result = scanner.analyseFrame(ctx, w, h, prev)
        prev = result.luma
        quadRef.current = result.quad
        analysisRef.current = { width: w, height: h, luma: result.luma }
        drawQuad(polygonRef.current, video, result.quad, w, h)
        deltasRef.current = [...deltasRef.current, result.delta].slice(-8)
        const decision = scanner.stabilityDecision(deltasRef.current, result.quad !== null)
        setLive((s) => (s.quadFound === (result.quad !== null) && s.stable === (decision === "capture") ? s : { quadFound: result.quad !== null, stable: decision === "capture" }))
        if (auto && !landscape && armedRef.current && decision === "capture") {
          armedRef.current = false
          takeRef.current()
        }
      }
      raf = requestAnimationFrame(tick)
    })
    return () => {
      cancelled = true
      cancelAnimationFrame(raf)
    }
  }, [phase, auto, landscape])

  if (phase === "tap" || phase === "starting" || typeof phase === "object") {
    const kind = typeof phase === "object" ? phase.error : phase
    return (
      <div className="fixed inset-0 z-40">
        <CameraStateScreen
          kind={kind}
          onPrimary={() => { setPhase("starting"); bumpRetry() }}
          onUpload={onOpenUploadSheet}
          onClose={onClose}
        />
      </div>
    )
  }

  const hint = landscape ? null : captureHint(capture, { ...live, justCaptured, auto })
  const blocked = !canFinishCapture(capture)
  const retaking = hint?.tone === "error"

  return (
    <div className="fixed inset-0 z-40 overflow-hidden bg-inverse-surface text-white">
      <style>{STACK_IN_KEYFRAMES}</style>
      <video ref={videoRef} autoPlay playsInline muted className="absolute inset-0 h-full w-full object-cover" />
      <svg className="pointer-events-none absolute inset-0 z-[2] h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
        <polygon
          key={capture.flash}
          ref={polygonRef}
          points=""
          className={`fill-inverse-primary stroke-inverse-primary motion-safe:[animation:quad-flash_320ms_var(--ease-out)] ${retaking ? "[stroke-dasharray:10_8]" : ""}`}
          fillOpacity={0.1}
          strokeWidth={3}
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>

      <div className="absolute inset-x-0 top-0 z-[3] flex items-center gap-2.5 px-4 py-3.5">
        <button type="button" className={iconDark} aria-label="Close" onClick={onClose}><Icon.Close /></button>
        <span className="flex-1" />
        <button type="button" aria-pressed={auto} onClick={() => setAuto((a) => !a)} className="flex h-9 items-center gap-1.5 rounded-chip bg-inverse-surface/60 px-3 text-[13px] font-bold">
          <span className={`size-2 rounded-full ${auto ? "bg-inverse-primary" : "bg-white/40"}`} />Auto
        </button>
        <button type="button" className={iconDark} aria-label="Upload a file" onClick={onOpenUploadSheet}><Icon.File /></button>
        {torch.available ? (
          <button
            type="button"
            className={`${iconDark} ${torch.on ? "bg-inverse-primary text-primary" : ""}`}
            aria-label="Torch"
            aria-pressed={torch.on}
            onClick={async () => {
              const track = streamRef.current?.getVideoTracks()[0]
              if (track && scannerRef.current && (await scannerRef.current.setTorch(track, !torch.on))) setTorch((t) => ({ ...t, on: !t.on }))
            }}
          >
            <Icon.Torch />
          </button>
        ) : null}
      </div>

      {landscape ? (
        <div role="status" className="absolute left-1/2 top-1/2 z-[3] flex -translate-x-1/2 -translate-y-1/2 items-center gap-2 whitespace-nowrap rounded-pill bg-inverse-surface/[.78] px-5 py-3 text-[17px] font-semibold">
          <Icon.Phone />Turn your phone upright
        </div>
      ) : hint ? (
        <div role="status" className={`absolute left-1/2 top-[74px] z-[3] flex -translate-x-1/2 items-center gap-2 whitespace-nowrap rounded-pill px-4 py-[9px] text-[15px] font-semibold ${hint.tone === "error" ? "bg-error" : "bg-inverse-surface/[.78]"}`}>
          {hint.tone === "busy" ? <span className="size-3.5 rounded-full border-2 border-white/35 border-t-white motion-safe:animate-spin motion-safe:[animation-duration:.8s]" /> : null}
          {hint.text}
        </div>
      ) : null}

      {!landscape ? (
        <>
          <div className="absolute inset-x-0 bottom-[128px] z-[3] text-center font-mono text-[13px] font-semibold text-white/80" aria-live="polite">
            {countLabel(capture.pages.length)}
          </div>
          <div className="absolute inset-x-0 bottom-0 z-[3] grid grid-cols-[1fr_auto_1fr] items-center bg-inverse-surface/[.92] px-[22px] pb-[30px] pt-4">
            <PageStack count={capture.pages.length} error={retaking} flash={capture.flash} onOpen={onDone} />
            <button type="button" aria-label="Take photo" onClick={takePage} className="grid size-[76px] place-items-center rounded-full border-4 border-white after:size-[60px] after:rounded-full after:bg-white after:content-[''] motion-safe:active:scale-[.97]" />
            <button type="button" onClick={onDone} disabled={blocked} className="flex h-[52px] min-w-[52px] items-center gap-1.5 justify-self-end rounded-2xl bg-inverse-primary px-4 text-[15px] font-bold text-primary disabled:opacity-50">
              Done<Icon.Arrow />
            </button>
          </div>
        </>
      ) : null}
    </div>
  )
}

/** Map an analysis-space quad onto the cover-fitted video, in 0..100 viewBox units (K8). */
function drawQuad(polygon: SVGPolygonElement | null, video: HTMLVideoElement, quad: Quad | null, aw: number, ah: number): void {
  if (!polygon) return
  if (!quad || !video.videoWidth || !video.clientWidth) {
    polygon.setAttribute("points", "")
    return
  }
  const scale = Math.max(video.clientWidth / video.videoWidth, video.clientHeight / video.videoHeight)
  const ox = (video.videoWidth * scale - video.clientWidth) / 2
  const oy = (video.videoHeight * scale - video.clientHeight) / 2
  polygon.setAttribute(
    "points",
    quad
      .map((p) => {
        const vx = (p.x * video.videoWidth) / aw
        const vy = (p.y * video.videoHeight) / ah
        return `${((vx * scale - ox) / video.clientWidth) * 100},${((vy * scale - oy) / video.clientHeight) * 100}`
      })
      .join(" "),
  )
}
```
Note for the worker: `analyseFrame` returns `luma` at `ANALYSIS_WIDTH` already, so `lumaWidth = Math.min(ANALYSIS_WIDTH, analysisWidth)` and `lumaHeight = luma.length / lumaWidth`. Simplify the `assessPage` call to those two lines when implementing; behaviour must match the Task 11 tests.

- [ ] **Step 4: Type check, lint, commit**

```bash
npx tsc -p tsconfig.app.json --noEmit && npx oxlint src/components/scan && npm run check:copy && npm run check:native
git commit -S -m "feat(web): scanner-style camera with page stack and camera states" -- web/src/components/scan/ScannerCamera.tsx web/src/components/scan/CameraStateScreen.tsx web/src/components/scan/PageStack.tsx web/src/components/scan/styles.ts
```

---

### Task 16: Your pages, Fix crop and the upload sheet

**Files:**
- Create: `web/src/components/scan/PagesReview.tsx`, `FixCrop.tsx`, `UploadSheet.tsx`

**Interfaces:**
- Consumes: Task 12 selectors, Task 11 crop maths, `assemblePagesToPdf` (`lib/pdf/assemblePages.ts`), `downloadUrl`, `SCAN_ACCEPT`/`SCHEME_ACCEPT`.
- Produces:
  - `PagesReview({ capture, onBack, onEdit(pageId), onAddPage, onNext, nextLabel = "Next: check paper" })`
  - `FixCrop({ page, pageNo, onSave(crop, url), onRotateOnly?, onRetake, onDelete, onBack })`
  - `UploadSheet({ open, onOpenChange, role, onPhotos(files), onPdf(file), onScheme(file), schemeName, error })`

- [ ] **Step 1: `PagesReview.tsx`** (mock "Your pages")

```tsx
import { useState } from "react"
import { canSendPages, countLabel, firstProblem, pageLabel, type CaptureState } from "@/lib/scan/captureModel"
import { AppBar } from "./AppBar"
import { InlineAlert } from "./InlineAlert"
import { downloadUrl } from "./downloadBlob"
import { Icon } from "./scanIcons"
import { btnPrimary } from "./styles"

export function PagesReview({ capture, onBack, onEdit, onAddPage, onNext, nextLabel = "Next: check paper" }: {
  capture: CaptureState
  onBack: () => void
  onEdit: (pageId: string) => void
  onAddPage: () => void
  onNext: () => void
  nextLabel?: string
}) {
  const problem = firstProblem(capture)
  const [pdfError, setPdfError] = useState<string | null>(null)
  const n = capture.pages.length

  async function downloadPdf() {
    setPdfError(null)
    try {
      const { assemblePagesToPdf } = await import("@/lib/pdf/assemblePages")
      const blobs = await Promise.all(capture.pages.map((p) => fetch(p.url).then((r) => r.blob())))
      const file = await assemblePagesToPdf(blobs, { filename: "scan.pdf" })
      downloadUrl(URL.createObjectURL(file), "scan.pdf")
    } catch {
      setPdfError("Could not assemble the scanned pages into a PDF. Try retaking the last page.")
    }
  }

  return (
    <div className="flex min-h-dvh flex-col bg-surface">
      <AppBar title="Your pages" sub={`${countLabel(n)}`} onBack={onBack} onDownload={n > 0 ? () => void downloadPdf() : undefined} />
      <div className="grid flex-1 content-start gap-4 overflow-auto px-4 pb-2 pt-1">
        {problem ? (
          <InlineAlert action={{ label: problem.action === "fix_crop" ? "Fix crop" : "Retake", onClick: () => onEdit(problem.pageId) }}>
            {problem.message}
          </InlineAlert>
        ) : null}
        {pdfError ? <InlineAlert>{pdfError}</InlineAlert> : null}
        <ul className="grid grid-cols-3 gap-3 tablet:grid-cols-5" aria-label="Pages">
          {capture.pages.map((page, i) => (
            <li key={page.id} className="grid justify-items-center gap-1.5">
              <button
                type="button"
                onClick={() => onEdit(page.id)}
                aria-label={`Fix crop, page ${i + 1}`}
                className={`relative h-[118px] w-full overflow-hidden rounded-[10px] bg-surface-container-lowest ${page.issue ? "ring-2 ring-inset ring-error" : "ring-1 ring-inset ring-outline"}`}
              >
                <img src={page.url} alt="" className="h-full w-full object-cover object-top" />
                <span className="absolute bottom-1.5 right-1.5 grid size-[26px] place-items-center rounded-lg bg-inverse-surface/75 text-white"><Icon.Pencil /></span>
              </button>
              <b className={`font-mono text-xs font-semibold ${page.issue ? "text-error" : "text-on-surface-variant"}`}>{pageLabel(i, page)}</b>
            </li>
          ))}
          <li className="grid">
            <button type="button" onClick={onAddPage} className="grid h-[118px] w-full place-content-center justify-items-center gap-1 rounded-[10px] text-[13px] font-bold text-primary outline-2 -outline-offset-2 outline-dashed outline-outline">
              <Icon.Plus />Add page
            </button>
          </li>
        </ul>
      </div>
      <div className="grid gap-2 bg-surface px-4 pb-[26px] pt-3 shadow-[0_-12px_14px_-10px_var(--color-surface)]">
        <button type="button" className={btnPrimary} onClick={onNext} disabled={!canSendPages(capture)}>{nextLabel}</button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: `FixCrop.tsx`** (mock "Fix crop": drag or arrow-key four corners; Rotate, Retake, Delete, Save)

```tsx
import { useRef, useState, type PointerEvent as RPointerEvent } from "react"
import type { PageCrop } from "@/lib/markingTypes"
import type { CapturedPage } from "@/lib/scan/captureModel"
import { CORNER_LABELS, cornersFromQuad, defaultCorners, fromPageCrop, moveCorner, nextRotation, nudgeCorner, toPageCrop, type Corners } from "@/lib/scan/cropMath"
import type { Quad } from "@/lib/scanner"
import { Icon } from "./scanIcons"
import { iconDark } from "./styles"

const W = 390
const H = 624

export function FixCrop({ page, pageNo, onSave, onRetake, onDelete, onBack }: {
  page: CapturedPage
  pageNo: number
  onSave: (crop: PageCrop, url: string) => void
  onRetake: () => void
  onDelete: () => void
  onBack: () => void
}) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [corners, setCorners] = useState<Corners>(() =>
    page.crop ? fromPageCrop(page.crop, W, H) : page.quad ? cornersFromQuad(page.quad, page.sourceWidth, page.sourceHeight, W, H) : defaultCorners(W, H),
  )
  const [rotation, setRotation] = useState<PageCrop["rotation"]>(page.crop?.rotation ?? 0)
  const [drag, setDrag] = useState(-1)
  const [saving, setSaving] = useState(false)

  const toStage = (e: RPointerEvent): [number, number] => {
    const r = svgRef.current!.getBoundingClientRect()
    return [((e.clientX - r.left) * W) / r.width, ((e.clientY - r.top) * H) / r.height]
  }

  async function save() {
    setSaving(true)
    const crop = toPageCrop(pageNo, corners, W, H, rotation)
    const url = await warpCrop(page, crop)
    setSaving(false)
    onSave(crop, url)
  }

  return (
    <div className="fixed inset-0 z-40 bg-inverse-surface text-white">
      <div className="absolute inset-x-0 top-0 flex items-center gap-2.5 px-4 py-3.5">
        <button type="button" className={iconDark} aria-label="Back" onClick={onBack}><Icon.Back /></button>
        <b className="flex-1 text-[17px] font-bold">Page {pageNo}</b>
        <span className="font-mono text-[12.5px] font-semibold text-white/70">drag the corners</span>
      </div>
      <div className="absolute inset-x-0 bottom-[150px] top-[70px]">
        <img src={page.originalUrl} alt={`Page ${pageNo}`} className="absolute inset-0 h-full w-full object-contain" style={{ transform: `rotate(${rotation}deg)` }} />
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          className="absolute inset-0 h-full w-full touch-none"
          aria-label="Crop corners, drag to adjust"
          onPointerMove={(e) => { if (drag >= 0) setCorners((c) => moveCorner(c, drag, toStage(e), W, H)) }}
          onPointerUp={() => setDrag(-1)}
        >
          <polygon points={corners.map((p) => p.join(",")).join(" ")} className="fill-inverse-primary/[.12] stroke-inverse-primary" strokeWidth={3} strokeLinejoin="round" />
          {corners.map(([x, y], i) => (
            <circle
              key={CORNER_LABELS[i]}
              cx={x}
              cy={y}
              r={14}
              tabIndex={0}
              role="slider"
              aria-label={CORNER_LABELS[i]}
              aria-valuetext={`${Math.round(x)}, ${Math.round(y)}`}
              className="cursor-grab fill-inverse-primary stroke-white focus-visible:outline-2"
              strokeWidth={3}
              onPointerDown={(e) => { setDrag(i); (e.target as Element).setPointerCapture(e.pointerId) }}
              onKeyDown={(e) => {
                const next = nudgeCorner(corners, i, e.key, W, H)
                if (next) { setCorners(next); e.preventDefault() }
              }}
            />
          ))}
        </svg>
      </div>
      <div className="absolute inset-x-0 bottom-0 grid grid-cols-[repeat(3,1fr)_auto] items-center gap-1.5 bg-inverse-surface px-4 pb-7 pt-3.5">
        <button type="button" className="grid min-h-[52px] justify-items-center gap-1 text-xs font-semibold" onClick={() => setRotation(nextRotation)}><Icon.Rotate />Rotate</button>
        <button type="button" className="grid min-h-[52px] justify-items-center gap-1 text-xs font-semibold" onClick={onRetake}><Icon.Camera />Retake</button>
        <button type="button" className="grid min-h-[52px] justify-items-center gap-1 text-xs font-semibold" onClick={onDelete}><Icon.Trash />Delete</button>
        <button type="button" disabled={saving} onClick={() => void save()} className="flex h-[52px] min-w-[52px] items-center rounded-2xl bg-inverse-primary px-4 text-[15px] font-bold text-primary disabled:opacity-50">Save</button>
      </div>
    </div>
  )
}

/** Re-warp the original photo to the saved corners, then rotate. Same homography as capture. */
async function warpCrop(page: CapturedPage, crop: PageCrop): Promise<string> {
  const scanner = await import("@/lib/scanner")
  const img = new Image()
  img.src = page.originalUrl
  await img.decode()
  const canvas = document.createElement("canvas")
  canvas.width = img.naturalWidth
  canvas.height = img.naturalHeight
  const ctx = canvas.getContext("2d")!
  ctx.drawImage(img, 0, 0)
  const quad = crop.corners.map(([x, y]) => ({ x: x * canvas.width, y: y * canvas.height })) as Quad
  ctx.putImageData(scanner.correctPerspective(ctx, canvas.width, canvas.height, quad), 0, 0)
  const out = document.createElement("canvas")
  const turned = crop.rotation === 90 || crop.rotation === 270
  out.width = turned ? canvas.height : canvas.width
  out.height = turned ? canvas.width : canvas.height
  const octx = out.getContext("2d")!
  octx.translate(out.width / 2, out.height / 2)
  octx.rotate((crop.rotation * Math.PI) / 180)
  octx.drawImage(canvas, -canvas.width / 2, -canvas.height / 2)
  const blob = await new Promise<Blob>((resolve) => out.toBlob((b) => resolve(b!), "image/jpeg", 0.92))
  return URL.createObjectURL(blob)
}
```
The crop stage maps the stage box straight to fractions of the photo; the photo is `object-contain`, so convert pointer positions through the image's rendered box when the aspect ratios differ (compute the contained rect from `img.naturalWidth/Height` and the stage size; corners outside the image clamp to its edges). Keep this conversion inside `FixCrop` and keep `cropMath.ts` pure.

- [ ] **Step 3: `UploadSheet.tsx`** (mock "Upload sheet": Photos / PDF file / Your own mark scheme; mixed-files error)

```tsx
import { useRef } from "react"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { SCAN_ACCEPT, SCHEME_ACCEPT } from "@/lib/scanAccept"
import { InlineAlert } from "./InlineAlert"
import { Icon } from "./scanIcons"

const IMAGE_ACCEPT = SCAN_ACCEPT.split(",").filter((t) => t.startsWith("image/")).join(",")

export function UploadSheet({ open, onOpenChange, role, onPhotos, onPdf, onScheme, schemeName, error }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  role: "student" | "teacher"
  onPhotos: (files: File[]) => void
  onPdf: (file: File) => void
  onScheme: (file: File) => void
  schemeName: string | null
  error: string | null
}) {
  const photos = useRef<HTMLInputElement>(null)
  const pdf = useRef<HTMLInputElement>(null)
  const scheme = useRef<HTMLInputElement>(null)
  const opt = "grid min-h-16 w-full grid-cols-[44px_1fr] items-center gap-3 rounded-2xl px-2 py-2.5 text-start text-on-surface hover:bg-surface-container-low"
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="bottom" className="rounded-t-[28px] px-3 pb-7 pt-2.5">
        <SheetTitle className="px-2 pb-1.5 text-[21px] font-extrabold">Add from your phone</SheetTitle>
        <button type="button" className={opt} onClick={() => photos.current?.click()}>
          <span className="grid size-11 place-items-center rounded-button bg-primary-container text-primary"><Icon.Photos /></span>
          <span><b className="block text-base font-bold">Photos</b><span className="text-[13.5px] text-on-surface-variant">Pick every page in order. We join them into one PDF.</span></span>
        </button>
        <button type="button" className={opt} onClick={() => pdf.current?.click()}>
          <span className="grid size-11 place-items-center rounded-button bg-primary-container text-primary"><Icon.Pdf /></span>
          <span><b className="block text-base font-bold">PDF file</b><span className="text-[13.5px] text-on-surface-variant">One paper per file.</span></span>
        </button>
        <button type="button" className={opt} onClick={() => scheme.current?.click()}>
          <span className={`grid size-11 place-items-center rounded-button ${schemeName ? "bg-primary-container text-primary" : "bg-surface-container text-on-surface-variant"}`}>{schemeName ? <Icon.PdfCheck /> : <Icon.PdfCheck />}</span>
          <span>
            <b className="block text-base font-bold">Your own mark scheme</b>
            <span className="text-[13.5px] text-on-surface-variant">
              {schemeName ?? (role === "student" ? "Optional. Without it we use the official one." : "Add one when Lemely has none for this paper.")}
            </span>
          </span>
        </button>
        {error ? <div className="mx-1 mt-2"><InlineAlert>{error}</InlineAlert></div> : null}
        <input ref={photos} type="file" accept={IMAGE_ACCEPT} multiple hidden onChange={(e) => { const f = [...(e.target.files ?? [])]; e.target.value = ""; if (f.length) onPhotos(f) }} />
        <input ref={pdf} type="file" accept={SCAN_ACCEPT} hidden onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) onPdf(f) }} />
        <input ref={scheme} type="file" accept={SCHEME_ACCEPT} hidden onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) onScheme(f) }} />
      </SheetContent>
    </Sheet>
  )
}
```
The parent refuses a PDF picked together with photos (K18) with the mock copy "Pick one PDF or a set of photos, not both." (shortened from the live "Choose either one PDF or a set of photos, not both."; listed in PR). A PDF chosen through the "Photos" picker cannot happen (images only); the check guards drag-and-drop and the desktop picker, which accept both.

- [ ] **Step 4: Type check, lint, commit**

```bash
npx tsc -p tsconfig.app.json --noEmit && npx oxlint src/components/scan && npm run check:copy && npm run check:native
git commit -S -m "feat(web): pages grid, fix-crop and upload sheet" -- web/src/components/scan/PagesReview.tsx web/src/components/scan/FixCrop.tsx web/src/components/scan/UploadSheet.tsx
```

---

### Task 17: Check your paper, change paper, no mark scheme, shared file

**Files:**
- Create: `web/src/components/scan/CheckPaper.tsx`, `ChangePaperSheet.tsx`, `SharedFile.tsx`

**Interfaces:**
- Consumes: `DetectResult`, `PaperChoice`, `useChoosePaper` (Task 8); reference data via the existing reference hook (search `"/reference"` in `web/src/lib/hooks/` and use that hook; it returns subjects with `code`, `name`, `papers[].number`).
- Produces:
  - `CheckPaper({ detect, detecting, detectFailed, pageCount, thumbs, emailVerified, onConfirm, onChange, onUploadScheme, onBack, onDownload, starting })`
  - `ChangePaperSheet({ open, onOpenChange, initial, onChosen(choice), pending, error })`
  - `SharedFile({ file, onCheck, onCancel })`

- [ ] **Step 1: `CheckPaper.tsx`** (mock "Check your paper" and "No mark scheme found")

```tsx
import type { DetectResult } from "@/lib/markingTypes"
import { AppBar } from "./AppBar"
import { InlineAlert } from "./InlineAlert"
import { btnPrimary, btnTonal } from "./styles"

const FAN = [
  "left-0 top-5 -rotate-[4deg]",
  "left-[116px] top-1.5",
  "left-[232px] top-6 rotate-[3deg]",
]

export function CheckPaper({ detect, detecting, detectFailed, pageCount, thumbs, emailVerified, starting, onConfirm, onChange, onUploadScheme, onBack, onDownload }: {
  detect: DetectResult | null
  detecting: boolean
  detectFailed: boolean
  pageCount: number | null
  thumbs: string[]
  emailVerified: boolean
  starting: boolean
  onConfirm: () => void
  onChange: () => void
  onUploadScheme: () => void
  onBack: () => void
  onDownload: () => void
}) {
  const paper = detect?.paper ?? null
  const noScheme = detect?.schemeSource === "none"
  const sub = pageCount ? `${pageCount} pages` : undefined
  return (
    <div className="flex min-h-dvh flex-col bg-surface tablet:mx-auto tablet:min-h-0 tablet:w-[560px] tablet:py-9">
      <AppBar title="Check your paper" sub={sub} onBack={onBack} onDownload={noScheme ? undefined : onDownload} />
      <div className="flex flex-1 flex-col gap-4 px-4 pb-5 pt-1">
        {detecting ? (
          <div className="grid gap-1.5 rounded-[28px] bg-primary p-5 text-on-primary" aria-busy="true">
            <span className="text-lg font-bold">Finding your paper…</span>
            <span className="h-11 w-40 rounded-xl bg-on-primary/15 motion-safe:animate-pulse" />
          </div>
        ) : paper ? (
          <div className="grid gap-1.5 rounded-[28px] bg-primary p-5 text-on-primary">
            <span className="text-lg font-bold">{paper.subjectName ?? paper.subjectCode}</span>
            <span className="font-display text-[44px] font-extrabold leading-none tracking-[-.04em]">{paper.code}</span>
            <span className="font-mono text-[13px] font-semibold text-inverse-primary">
              Paper {paper.paperNumber} · {paper.sessionMonth.replace("/", "/")} {paper.sessionYear ?? ""} · Variant {paper.variant}
            </span>
          </div>
        ) : null}

        {noScheme ? (
          <>
            <InlineAlert sub="Add it and we’ll mark against it.">We don’t have the mark scheme for this paper yet.</InlineAlert>
            <div className="mt-auto grid gap-2">
              <button type="button" className={btnPrimary} onClick={onUploadScheme}>Upload mark scheme</button>
              <button type="button" className={btnTonal} onClick={onChange}>No, change paper</button>
            </div>
          </>
        ) : (
          <>
            {thumbs.length > 0 ? (
              <div className="relative h-[210px]" aria-hidden>
                {thumbs.slice(0, 3).map((src, i) => (
                  <img key={src} src={src} alt="" className={`absolute h-40 w-[120px] rounded bg-surface-container-lowest object-cover object-top shadow-[0_20px_30px_-18px_#0005] ring-1 ring-outline-variant ${FAN[i]}`} />
                ))}
              </div>
            ) : null}
            {!detecting ? (
              <p className="text-[17px] font-semibold leading-[1.4]">
                {paper
                  ? "Is this the paper you sat? We mark it against this mark scheme."
                  : detectFailed || detect?.schemeSource === "unknown"
                    ? "We couldn’t read which paper this is. Pick it so we mark against the right scheme."
                    : "Is this the paper you sat?"}
              </p>
            ) : null}
            {!emailVerified ? <InlineAlert tone="info">Verify your email to start marking.</InlineAlert> : null}
            <div className="mt-auto grid gap-2">
              <button type="button" className={btnPrimary} onClick={paper || detect?.schemeSource === "own" ? onConfirm : onChange} disabled={detecting || starting || !emailVerified}>
                {paper || detect?.schemeSource === "own" ? "Yes, mark it" : "Pick the paper"}
              </button>
              {paper ? <button type="button" className={btnTonal} onClick={onChange}>No, change it</button> : null}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
```
The "couldn't read which paper" line is an edge case not drawn in the mock (detection unavailable or failed); listed in the PR and in Needs user decision 5. Session text: render `sessionMonth` as `May/Jun` per the mock by mapping `May/June → May/Jun`, `Oct/Nov → Oct/Nov`, `Feb/Mar → Feb/Mar` in a tiny `shortSession()` helper in this file.

- [ ] **Step 2: `ChangePaperSheet.tsx`** ("No, change it")

```tsx
import { useState } from "react"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import type { PaperChoice } from "@/lib/markingTypes"
import { InlineAlert } from "./InlineAlert"
import { btnPrimary } from "./styles"

const MONTHS: PaperChoice["sessionMonth"][] = ["May/June", "Oct/Nov", "Feb/Mar", "Specimen"]

export function ChangePaperSheet({ open, onOpenChange, subjects, initial, onChosen, pending, error }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  subjects: { code: string; name: string; papers: { number: number }[] }[]
  initial: PaperChoice | null
  onChosen: (choice: PaperChoice) => void
  pending: boolean
  error: string | null
}) {
  const [choice, setChoice] = useState<PaperChoice>(
    initial ?? { subjectCode: subjects[0]?.code ?? "", paperNumber: 1, variant: 1, sessionMonth: "May/June", sessionYear: new Date().getFullYear() },
  )
  const subject = subjects.find((s) => s.code === choice.subjectCode)
  const field = "grid gap-1.5"
  const label = "text-[13px] font-semibold text-on-surface-variant"
  const select = "h-11 rounded-md bg-surface-container-lowest px-3.5 text-[15px] font-semibold ring-1 ring-inset ring-outline"
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="bottom" className="grid gap-3 rounded-t-[28px] px-4 pb-7 pt-2.5">
        <SheetTitle className="text-[21px] font-extrabold">Which paper did you sit?</SheetTitle>
        <label className={field}><span className={label}>Subject</span>
          <select className={select} value={choice.subjectCode} onChange={(e) => setChoice({ ...choice, subjectCode: e.target.value, paperNumber: 1 })}>
            {subjects.map((s) => <option key={s.code} value={s.code}>{s.name} · {s.code}</option>)}
          </select>
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className={field}><span className={label}>Paper</span>
            <select className={select} value={choice.paperNumber} onChange={(e) => setChoice({ ...choice, paperNumber: Number(e.target.value) })}>
              {(subject?.papers ?? []).map((p) => <option key={p.number} value={p.number}>Paper {p.number}</option>)}
            </select>
          </label>
          <label className={field}><span className={label}>Variant</span>
            <select className={select} value={choice.variant} onChange={(e) => setChoice({ ...choice, variant: Number(e.target.value) })}>
              {[1, 2, 3].map((v) => <option key={v} value={v}>Variant {v}</option>)}
            </select>
          </label>
          <label className={field}><span className={label}>Session</span>
            <select className={select} value={choice.sessionMonth} onChange={(e) => setChoice({ ...choice, sessionMonth: e.target.value as PaperChoice["sessionMonth"] })}>
              {MONTHS.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
          <label className={field}><span className={label}>Year</span>
            <input className={`${select} font-mono`} inputMode="numeric" value={choice.sessionYear ?? ""} onChange={(e) => setChoice({ ...choice, sessionYear: e.target.value ? Number(e.target.value) : null })} />
          </label>
        </div>
        {error ? <InlineAlert>{error}</InlineAlert> : null}
        <button type="button" className={btnPrimary} disabled={pending || !choice.subjectCode} onClick={() => onChosen(choice)}>Use this paper</button>
      </SheetContent>
    </Sheet>
  )
}
```
Native `<select>` is off-brand per the taste profile ("themed controls everywhere"). Use the themed select the codebase already has (`components/ui/select.tsx`) with the same props; the code above shows the data flow, swap the element for `Select` when implementing. This sheet is not drawn in the mock: Needs user decision 4.

- [ ] **Step 3: `SharedFile.tsx`** (mock "Shared into Lemely")

```tsx
import { formatFileSize } from "@/components/ui/file-drop"
import { AppBar } from "./AppBar"
import { Icon } from "./scanIcons"
import { btnPrimary, btnTonal } from "./styles"

export function SharedFile({ file, onCheck, onCancel }: { file: File; onCheck: () => void; onCancel: () => void }) {
  return (
    <div className="flex min-h-dvh flex-col bg-surface tablet:mx-auto tablet:min-h-0 tablet:w-[560px] tablet:py-9">
      <AppBar title="Mark this paper?" sub="Shared from Files" onBack={onCancel} backLabel="Close" closeIcon />
      <div className="flex flex-1 flex-col gap-4 px-4 pb-5 pt-1">
        <div className="grid min-w-0 grid-cols-[44px_1fr_auto] items-center gap-3 rounded-tile bg-surface-container-lowest p-3.5 ring-1 ring-inset ring-outline-variant">
          <span className="grid size-11 place-items-center rounded-button bg-primary-container text-primary"><Icon.Pdf /></span>
          <div className="min-w-0">
            <b className="block truncate text-[15px] font-bold">{file.name}</b>
            <span className="font-mono text-xs font-semibold text-on-surface-variant">{formatFileSize(file.size)}</span>
          </div>
        </div>
        <div className="mt-auto grid gap-2">
          <button type="button" className={btnPrimary} onClick={onCheck}>Check pages</button>
          <button type="button" className={btnTonal} onClick={onCancel}>Cancel</button>
        </div>
      </div>
    </div>
  )
}
```
The mock card shows "16 pages · 6.6 MB"; the page count of a shared PDF is unknown before upload, so only the size shows (listed in PR). The mock's page fan is dropped for a shared PDF (no client-side render of PDF pages).

- [ ] **Step 4: Type check, lint, commit**

```bash
npx tsc -p tsconfig.app.json --noEmit && npx oxlint src/components/scan && npm run check:copy && npm run check:native
git commit -S -m "feat(web): paper check, change paper and shared file screens" -- web/src/components/scan/CheckPaper.tsx web/src/components/scan/ChangePaperSheet.tsx web/src/components/scan/SharedFile.tsx
```

---

### Task 18: Marking board and every sending/marking state

**Files:**
- Create: `web/src/components/scan/MarkingBoard.tsx`, `MarkingStates.tsx`

**Interfaces:**
- Consumes: `MarkingView`, `BoardTile`, `binnyFor`, `footerFor`, `titleFor`, `stoppedCopy`, `SAFE_TO_LEAVE` (Task 10); `savedAgo` (Task 13); F1 `Binny`.
- Produces:
  - `TileBoard({ tiles, wide, waiting })` — the `.qboard` (4 columns, 7 at `tablet:`), exported so L12 can reuse it
  - `MarkingStates({ view, role, title, sub, onBack, onDownload, onRetry, onCheckPages, onAddPage, onTryNow, onUploadScheme, onChangePaper, onRetryStatus, retryPending, liveText })`

- [ ] **Step 1: `MarkingBoard.tsx`**

```tsx
import type { BoardTile } from "@/lib/marking/viewModel"

const TILE: Record<BoardTile["state"], string> = {
  waiting: "bg-surface-container text-on-surface-variant",
  done: "bg-primary-container text-primary",
  now: "bg-surface-container-lowest text-primary ring-2 ring-inset ring-primary",
  blank: "bg-transparent text-on-surface-variant outline-2 -outline-offset-2 outline-dashed outline-on-surface-variant/50",
  missing: "bg-error-container text-on-error-container",
  stopped: "bg-error-container text-on-error-container",
}

const SR: Record<BoardTile["state"], string> = {
  waiting: "waiting", done: "marked", now: "marking now", blank: "blank", missing: "page missing", stopped: "stopped",
}

export function TileBoard({ tiles, wide = false, waiting = false }: { tiles: BoardTile[]; wide?: boolean; waiting?: boolean }) {
  return (
    <ul className={`grid gap-2.5 ${wide ? "grid-cols-7" : "grid-cols-4 tablet:grid-cols-7"}`} aria-label="Questions">
      {tiles.map((t) => (
        <li
          key={t.key}
          aria-label={`${t.label}, ${SR[t.state]}`}
          className={`grid h-[72px] place-content-center justify-items-center gap-0.5 rounded-inner font-mono text-[17px] font-semibold transition-[background-color,box-shadow] duration-200 ease-out ${TILE[t.state]} ${waiting ? "opacity-55" : ""}`}
        >
          {t.label}
          {t.note ? <small className="font-sans text-[11px] font-semibold tracking-[.02em]">{t.note}</small> : null}
        </li>
      ))}
    </ul>
  )
}

/** Unlabelled ghost tiles for states before the question count is known (Needs user decision 3). */
export function GhostTiles({ count = 12 }: { count?: number }) {
  return (
    <div className="grid grid-cols-4 gap-2.5 tablet:grid-cols-7" aria-hidden>
      {Array.from({ length: count }, (_, i) => <span key={i} className="h-[72px] rounded-inner bg-surface-container opacity-55" />)}
    </div>
  )
}
```

- [ ] **Step 2: `MarkingStates.tsx`** (mock frames Marking · P4a, Uploading, Offline · saved, Next in line, Marking stopped, Came back mid-run, plus Reading and No mark scheme)

```tsx
import { Binny } from "@/components/redesign"
import { binnyFor, footerFor, stoppedCopy, titleFor, type MarkingView } from "@/lib/marking/viewModel"
import { savedAgo } from "@/lib/scan/queueCopy"
import { AppBar } from "./AppBar"
import { InlineAlert } from "./InlineAlert"
import { GhostTiles, TileBoard } from "./MarkingBoard"
import { Icon } from "./scanIcons"
import { btnOutline, btnPrimary, btnTonal, display30 } from "./styles"

export interface MarkingStatesProps {
  view: MarkingView
  role: "student" | "teacher"
  sub: string
  /** Screen-reader text from the live POST stream's stages (pipelineStages). */
  liveText: string
  onBack: () => void
  onDownload?: () => void
  onRetry: () => void
  retryPending?: boolean
  onCheckPages?: () => void
  onAddPage?: () => void
  onTryNow?: () => void
  onUploadScheme?: () => void
  onChangePaper?: () => void
  onRetryStatus?: () => void
}

function Hero({ view, role, children }: { view: MarkingView; role: "student" | "teacher"; children: React.ReactNode }) {
  const binny = binnyFor(view, role)
  return (
    <div className="flex items-center gap-3.5">
      <div className="flex-1">{children}</div>
      {binny ? <Binny mood={binny.mood} motion={binny.motion} size={72} aria-hidden /> : null}
    </div>
  )
}

function Status({ title, body, error = false }: { title: string; body: string; error?: boolean }) {
  return (
    <div>
      <div className={`${display30} ${error ? "text-on-error-container" : "text-primary"}`}>{title}</div>
      <div className="mt-1.5 text-pretty text-[14.5px] text-on-surface-variant">{body}</div>
    </div>
  )
}

const STRIPES = "h-2 overflow-hidden rounded-bar bg-primary-container"

export function MarkingStates(props: MarkingStatesProps) {
  const { view, role } = props
  const footer = footerFor(view)
  const wideHeader = "tablet:mx-auto tablet:w-[560px] tablet:py-9"

  let body: React.ReactNode
  switch (view.kind) {
    case "loading":
      body = <GhostTiles />
      break
    case "sending":
      body = (
        <>
          <Hero view={view} role={role}>
            <div className="font-display text-[56px] font-extrabold leading-none tracking-[-.04em] text-primary">
              {view.big}<small className="text-[28px] tracking-[-.02em] text-on-surface-variant">{view.unit}</small>
            </div>
            <div className="mt-1 text-sm text-on-surface-variant">{view.detail}</div>
          </Hero>
          <div className="h-2 overflow-hidden rounded-bar bg-surface-container-high" role="progressbar" aria-label="Sending" aria-valuenow={view.fraction === null ? undefined : Math.round(view.fraction * 100)} aria-valuemin={0} aria-valuemax={100}>
            <b className="block h-full rounded-bar bg-primary transition-[width] duration-500 ease-out" style={{ width: view.fraction === null ? "100%" : `${view.fraction * 100}%` }} />
          </div>
          <GhostTiles />
        </>
      )
      break
    case "saved_offline":
      body = (
        <>
          <span className="block text-primary"><Icon.WifiOff /></span>
          <Status title="Saved. Waiting for a connection." body="Your paper is on this phone. It sends by itself when you’re back online." />
          <div className="grid min-w-0 grid-cols-[44px_1fr_auto] items-center gap-3 rounded-tile bg-surface-container-lowest p-3.5 ring-1 ring-inset ring-outline-variant">
            <span className="grid size-11 place-items-center rounded-button bg-primary-container text-primary"><Icon.Pdf /></span>
            <div className="min-w-0">
              <b className="block truncate text-[15px] font-bold">{view.title}</b>
              <span className="font-mono text-xs font-semibold text-on-surface-variant">
                {view.pages ? `${view.pages} pages · ` : ""}{savedAgo(view.savedAt, Date.now())}
              </span>
            </div>
            <span className="rounded-chip bg-primary-container px-2.5 py-0.5 text-[12.5px] font-semibold text-primary">Waiting</span>
          </div>
          <button type="button" className={`${btnTonal} mt-auto`} onClick={props.onTryNow}>Try now</button>
        </>
      )
      break
    case "next_in_line":
      body = (
        <>
          <Hero view={view} role={role}><Status title="Next in line" body="Marking starts when the paper ahead finishes." /></Hero>
          <GhostTiles />
        </>
      )
      break
    case "reading":
    case "came_back":
      body = (
        <>
          <Hero view={view} role={role}>
            {view.kind === "came_back"
              ? <Status title="Still marking" body="This paper was already being marked when you opened this page." />
              : <Status title="Reading your answers" body="Marking starts in a moment." />}
          </Hero>
          <div className={STRIPES}>
            <b className="block h-full w-full [background:repeating-linear-gradient(90deg,var(--color-primary)_0_18px,var(--color-inverse-primary)_18px_36px)]" />
          </div>
        </>
      )
      break
    case "marking":
      body = (
        <>
          <Hero view={view} role={role}>
            <div className="font-display text-[56px] font-extrabold leading-none tracking-[-.04em] text-primary">
              {view.done}<small className="text-[28px] tracking-[-.02em] text-on-surface-variant"> of {view.total}</small>
            </div>
            <div className="mt-1 text-sm text-on-surface-variant">questions marked{view.eta ? ` · ${view.eta}` : ""}</div>
          </Hero>
          <TileBoard tiles={view.tiles} />
          {view.alert ? (
            <InlineAlert action={props.onAddPage ? { label: "Add page", onClick: props.onAddPage } : undefined}>{view.alert}</InlineAlert>
          ) : null}
        </>
      )
      break
    case "stopped": {
      const copy = stoppedCopy(view.sent)
      body = (
        <>
          <Status title="Marking stopped" body="Something went wrong on our side before marking finished. Nothing you did." error />
          {view.message ? <p className="text-sm text-on-surface-variant">{view.message}</p> : null}
          {view.tiles.length > 0 ? <TileBoard tiles={view.tiles} /> : null}
          <div className="mt-auto grid gap-2">
            <button type="button" className={btnPrimary} onClick={props.onRetry} disabled={props.retryPending}>{copy.action}</button>
            <p className="text-center text-sm text-on-surface-variant">{copy.note}</p>
            {props.onCheckPages ? <button type="button" className={btnTonal} onClick={props.onCheckPages}>Check pages</button> : null}
          </div>
        </>
      )
      break
    }
    case "no_scheme":
      body = (
        <>
          <InlineAlert sub="Add it and we’ll mark against it.">We don’t have the mark scheme for this paper yet.</InlineAlert>
          <div className="mt-auto grid gap-2">
            {props.onUploadScheme ? <button type="button" className={btnPrimary} onClick={props.onUploadScheme}>Upload mark scheme</button> : null}
            {props.onChangePaper ? <button type="button" className={btnTonal} onClick={props.onChangePaper}>No, change paper</button> : null}
          </div>
        </>
      )
      break
    case "status_error":
      body = <InlineAlert action={props.onRetryStatus ? { label: "Try again", onClick: props.onRetryStatus } : undefined}>Couldn’t check on this paper.</InlineAlert>
      break
    case "complete":
      body = null
      break
  }

  return (
    <div className={`flex min-h-dvh flex-col bg-surface ${wideHeader}`}>
      <AppBar
        title={titleFor(view)}
        sub={props.sub}
        onBack={props.onBack}
        onDownload={props.onDownload}
        trailing={props.onDownload ? (
          <button type="button" className={`${btnOutline} max-tablet:hidden`} onClick={props.onDownload}><Icon.Download />Download PDF</button>
        ) : undefined}
      />
      <p className="sr-only" role="status" aria-live="polite">{props.liveText}</p>
      <div className="flex flex-1 flex-col gap-5 px-4 pb-5 pt-1">
        {body}
        {footer ? <p className="mt-auto text-center text-sm text-on-surface-variant">{footer}</p> : null}
      </div>
    </div>
  )
}
```
On `tablet:` and up, `AppBar` shows the "Download PDF" outline button (mock desktop) and hides the icon: give `AppBar`'s icon button `tablet:hidden` when a `trailing` download is passed (small change to `AppBar` in this task). Desktop title: the mock desktop says "Marking your paper" at 32px with the full paper line ("Mathematics · 0580/42 · Paper 4 · May/Jun 2025"); pass `title` override from `MarkingPaper` at `tablet:` via `useMediaQuery("(min-width: 768px)")` (use the existing media-query hook in `web/src/lib/hooks/`, search `matchMedia`).

- [ ] **Step 3: Type check, lint, commit**

```bash
npx tsc -p tsconfig.app.json --noEmit && npx oxlint src/components/scan && npm run check:copy && npm run check:native
git commit -S -m "feat(web): marking board and sending, offline and stopped states" -- web/src/components/scan/MarkingBoard.tsx web/src/components/scan/MarkingStates.tsx web/src/components/scan/AppBar.tsx
```

---

### Task 19: Student flow: `CorrectPaper` and `MarkingPaper` routes

**Files:**
- Modify (rewrite): `web/src/portals/student/screens/CorrectPaper.tsx`
- Create: `web/src/portals/student/screens/MarkingPaper.tsx`
- Modify: `web/src/portals/student/index.tsx` (add `correct/:paperId` next to `correct`)

**Interfaces:**
- Consumes: everything above; `useActiveUpload`, `runCorrection`, `useProfile` (`useMeApi`); `readSharedScan`; `setHasUnsubmittedScan`; `enqueueUpload`, `shouldQueueUpload`; `correctionFailureMessage`; `advanceStage`, `annotateActiveStage`, `failActiveStage`, `frameProgress` (`lib/pipelineStages.ts`); `uploadStageProgress`.
- Produces: routes `/student/correct` (`CorrectPaper`, still exported as `CorrectPaper` so `loadCorrectPaper` prefetch keeps working, K51) and `/student/correct/:paperId` (`MarkingPaper`). `MarkingPaper` reads `location.state?.start === true` to start the run.

- [ ] **Step 1: `CorrectPaper.tsx` (orchestrator)**

```tsx
import { useEffect, useReducer, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { CameraStateScreen } from "@/components/scan/CameraStateScreen"
import { ChangePaperSheet } from "@/components/scan/ChangePaperSheet"
import { CheckPaper } from "@/components/scan/CheckPaper"
import { DropVeil, useFileDragOver } from "@/components/scan/DropVeil"
import { DropZone } from "@/components/scan/DropZone"
import { FixCrop } from "@/components/scan/FixCrop"
import { InlineAlert } from "@/components/scan/InlineAlert"
import { MarkingStates } from "@/components/scan/MarkingStates"
import { PagesReview } from "@/components/scan/PagesReview"
import { ScannerCamera } from "@/components/scan/ScannerCamera"
import { SharedFile } from "@/components/scan/SharedFile"
import { UploadSheet } from "@/components/scan/UploadSheet"
import { downloadUrl } from "@/components/scan/downloadBlob"
import { setHasUnsubmittedScan } from "@/lib/activeScanGuard"
import { correctionFailureMessage } from "@/lib/correctionOutcome"
import { useActiveUpload } from "@/lib/hooks/useStudentApi"
import { useProfile } from "@/lib/hooks/useMeApi"
import { useChoosePaper, useDetectPaper } from "@/lib/hooks/useMarkingApi"
import { fetchMarkingPdf, uploadStudentScan } from "@/lib/markingApi"
import { selectMarkingView, type LocalSend } from "@/lib/marking/viewModel"
import type { DetectResult } from "@/lib/markingTypes"
import { enqueueUpload } from "@/lib/offline/uploadQueue"
import { shouldQueueUpload } from "@/lib/offline/queueDecision"
import { useUploadQueue } from "@/lib/offline/useUploadQueue"
import { captureReducer, initialCapture, pageCrops } from "@/lib/scan/captureModel"
import { entryMode } from "@/lib/scan/entryMode"
import { flowReducer, initialFlow } from "@/lib/scan/flowMachine"
import { readSharedScan } from "@/lib/sharedScan"
import { randomUuid } from "@/lib/uuid"

const MIXED = "Pick one PDF or a set of photos, not both."

/*
 * Get a paper in (redesign L6, mock upload-r1/final.html). Phone opens on the camera,
 * desktop on the drop zone, and desktop never gets a camera. This screen ends at "Check
 * your paper"; marking lives on /student/correct/:paperId (MarkingPaper) so a reload or a
 * notification lands on the board. Every decision is in lib/scan/* and lib/marking/*.
 */
export function CorrectPaper() {
  const navigate = useNavigate()
  const [flow, send] = useReducer(flowReducer, undefined, () => initialFlow(entryMode(window.matchMedia?.bind(window))))
  const [capture, dispatch] = useReducer(captureReducer, initialCapture)
  const [cameraTapped, setCameraTapped] = useState(false)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [sheetError, setSheetError] = useState<string | null>(null)
  const [scheme, setScheme] = useState<File | null>(null)
  const [local, setLocal] = useState<LocalSend | null>(null)
  const [detect, setDetect] = useState<DetectResult | null>(null)
  const [changeOpen, setChangeOpen] = useState(false)
  const pdfInput = useRef<HTMLInputElement>(null)
  const schemeInput = useRef<HTMLInputElement>(null)
  const detectPaper = useDetectPaper()
  const choosePaper = useChoosePaper()
  const active = useActiveUpload()
  const queue = useUploadQueue()
  const profile = useProfile()
  const emailVerified = profile.data?.emailVerified !== false
  const dragging = useFileDragOver(flow.entry === "upload")

  // K34: a run already going → follow it on the board, never re-POST.
  useEffect(() => {
    const run = active.data
    if (run && (run.status === "processing" || run.status === "failed")) {
      navigate(`/student/correct/${run.paperId}`, { replace: true, state: { cameBack: true } })
    }
  }, [active.data, navigate])

  // K20: a shared or launched file, read once (readSharedScan deletes what it reads).
  const sharedRead = useRef(false)
  useEffect(() => {
    if (sharedRead.current) return
    sharedRead.current = true
    readSharedScan().then((file) => { if (file) send({ type: "shared", file }) }).catch(() => undefined)
  }, [])

  // K21: reload guard while something is captured or chosen and not yet sent.
  const unsent = (capture.pages.length > 0 || Boolean(flow.file)) && !flow.paperId
  useEffect(() => {
    setHasUnsubmittedScan(unsent)
    return () => setHasUnsubmittedScan(false)
  }, [unsent])

  // Revoke page URLs on leave (K13).
  const pagesRef = useRef(capture.pages)
  pagesRef.current = capture.pages
  useEffect(() => () => pagesRef.current.forEach((p) => { URL.revokeObjectURL(p.url); URL.revokeObjectURL(p.originalUrl) }), [])

  async function buildScan(): Promise<File> {
    if (flow.file) return flow.file
    const { assemblePagesToPdf } = await import("@/lib/pdf/assemblePages")
    const blobs = await Promise.all(capture.pages.map((p) => fetch(p.url).then((r) => r.blob())))
    return assemblePagesToPdf(blobs, { filename: "scan.pdf" })
  }

  async function sendPaper(): Promise<void> {
    send({ type: "send" })
    const pages = flow.file ? null : capture.pages.length
    setLocal({ phase: "sending", loaded: 0, total: undefined, pages })
    let scan: File
    try {
      scan = await buildScan()
    } catch {
      setLocal(null)
      send({ type: "send_failed", message: "Could not assemble the scanned pages into a PDF. Try retaking the last page." })
      return
    }
    const idempotencyKey = randomUuid()
    try {
      const { paperId } = await uploadStudentScan(scan, {
        markScheme: scheme,
        crops: pageCrops(capture),
        idempotencyKey,
        onProgress: (p) => setLocal({ phase: "sending", loaded: p.loaded, total: p.total, pages }),
      })
      setLocal(null)
      send({ type: "sent", paperId })
      setDetect(null)
      detectPaper.mutate(paperId, { onSuccess: setDetect })
    } catch (err) {
      if (shouldQueueUpload(err)) {
        const savedAt = Date.now()
        await enqueueUpload({ id: randomUuid(), idempotencyKey, scan, scanName: scan.name, markScheme: scheme, createdAt: savedAt, pages: pages ?? undefined, title: scan.name })
        queue.retry()
        setLocal({ phase: "saved_offline", savedAt, pages, title: scan.name })
        send({ type: "queued_offline", savedAt })
        return
      }
      setLocal(null)
      send({ type: "send_failed", message: correctionFailureMessage(err) })
    }
  }

  async function onPhotos(files: File[]) {
    setSheetError(null)
    if (files.some((f) => f.type === "application/pdf")) return setSheetError(MIXED)
    for (const file of files) {
      const url = URL.createObjectURL(file)
      const img = new Image()
      img.src = url
      await img.decode().catch(() => undefined)
      dispatch({ type: "captured", page: { id: randomUuid(), url, originalUrl: url, sourceWidth: img.naturalWidth, sourceHeight: img.naturalHeight, quad: null, issue: null, edge: null, crop: null } })
    }
    setSheetOpen(false)
    send({ type: "photos_chosen" })
  }

  function onFiles(files: File[]) {
    setSheetError(null)
    const pdfs = files.filter((f) => f.type === "application/pdf")
    if (pdfs.length > 0 && pdfs.length !== files.length) return setSheetError(MIXED)
    if (pdfs.length > 0) {
      setSheetOpen(false)
      send({ type: "pdf_chosen", file: pdfs[0] })
      return
    }
    void onPhotos(files)
  }

  // Sending a picked PDF starts as soon as the step flips.
  useEffect(() => {
    if (flow.step === "sending" && flow.file && !local) void sendPaper()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flow.step, flow.file])

  async function downloadServerPdf() {
    if (!flow.paperId) return
    downloadUrl(await fetchMarkingPdf(flow.paperId), "scan.pdf")
  }

  const editing = flow.step === "crop" ? capture.pages.find((p) => p.id === flow.pageId) : undefined
  const statusAlert = active.isError ? (
    <InlineAlert action={{ label: "Try again", onClick: () => void active.refetch() }}>Couldn’t check for a paper already being marked.</InlineAlert>
  ) : null

  const sheet = (
    <UploadSheet
      open={sheetOpen}
      onOpenChange={setSheetOpen}
      role="student"
      onPhotos={(f) => void onPhotos(f)}
      onPdf={(f) => onFiles([f])}
      onScheme={setScheme}
      schemeName={scheme?.name ?? null}
      error={sheetError}
    />
  )

  let screen: React.ReactNode
  switch (flow.step) {
    case "camera":
      screen = statusAlert && !cameraTapped ? (
        <div className="grid gap-4 px-4 pt-4">
          {statusAlert}
          <CameraStateScreen kind="tap" embedded onPrimary={() => setCameraTapped(true)} onUpload={() => setSheetOpen(true)} />
        </div>
      ) : (
        <ScannerCamera
          capture={capture}
          dispatch={dispatch}
          autoStart={cameraTapped}
          onDone={() => send({ type: "capture_done" })}
          onClose={() => navigate(-1)}
          onOpenUploadSheet={() => setSheetOpen(true)}
        />
      )
      break
    case "upload":
      screen = (
        <div className="grid gap-5 px-4 py-6 tablet:px-9 tablet:py-7">
          {statusAlert}
          <DropZone role="student" onFiles={onFiles} onPickScheme={() => schemeInput.current?.click()} schemeName={scheme?.name ?? null} error={sheetError} />
          <DropVeil show={dragging} onDropFiles={onFiles} />
        </div>
      )
      break
    case "pages":
      screen = (
        <PagesReview
          capture={capture}
          onBack={() => send({ type: "back" })}
          onEdit={(pageId) => send({ type: "edit_crop", pageId })}
          onAddPage={() => (flow.entry === "camera" ? send({ type: "add_page" }) : setSheetOpen(true))}
          onNext={() => void sendPaper()}
        />
      )
      break
    case "crop":
      screen = editing ? (
        <FixCrop
          page={editing}
          pageNo={capture.pages.indexOf(editing) + 1}
          onBack={() => send({ type: "crop_closed" })}
          onSave={(crop, url) => { dispatch({ type: "crop_saved", id: editing.id, crop, url }); send({ type: "crop_closed" }) }}
          onRetake={() => { dispatch({ type: "retake", id: editing.id }); send({ type: "add_page" }) }}
          onDelete={() => { dispatch({ type: "remove", id: editing.id }); send({ type: "crop_closed" }) }}
        />
      ) : null
      break
    case "shared":
      screen = flow.file ? <SharedFile file={flow.file} onCheck={() => void sendPaper()} onCancel={() => send({ type: "back" })} /> : null
      break
    case "sending":
    case "saved_offline":
    case "send_failed":
      screen = (
        <MarkingStates
          view={selectMarkingView({ local: flow.step === "send_failed" ? { phase: "send_failed", message: flow.error ?? "" } : local, progress: undefined, progressError: false, cameBack: false })}
          role="student"
          sub={flow.file ? flow.file.name : `${capture.pages.length} pages`}
          liveText={flow.step === "sending" ? "Sending your paper" : ""}
          onBack={() => send({ type: "back" })}
          onRetry={() => void sendPaper()}
          onCheckPages={capture.pages.length > 0 ? () => send({ type: "back" }) : undefined}
          onTryNow={queue.retry}
        />
      )
      break
    case "check":
      screen = (
        <CheckPaper
          detect={detect}
          detecting={detectPaper.isPending}
          detectFailed={detectPaper.isError}
          pageCount={flow.file ? null : capture.pages.length}
          thumbs={capture.pages.map((p) => p.url)}
          emailVerified={emailVerified}
          starting={false}
          onConfirm={() => navigate(`/student/correct/${flow.paperId}`, { state: { start: true, pages: capture.pages.length || null } })}
          onChange={() => setChangeOpen(true)}
          onUploadScheme={() => schemeInput.current?.click()}
          onBack={() => send({ type: "back" })}
          onDownload={() => void downloadServerPdf()}
        />
      )
      break
  }

  return (
    <div className={dragging ? "relative" : undefined}>
      {screen}
      {sheet}
      <ChangePaperSheetHost open={changeOpen} onOpenChange={setChangeOpen} paperId={flow.paperId} detect={detect} onResult={setDetect} choose={choosePaper} />
      <input ref={pdfInput} type="file" hidden />
      <input
        ref={schemeInput}
        type="file"
        accept="application/pdf"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0]
          e.target.value = ""
          if (!f) return
          setScheme(f)
          // A scheme picked after upload re-sends the paper with it (the server stores
          // schemes beside the scan at upload time only).
          if (flow.step === "check") void sendPaper()
        }}
      />
    </div>
  )
}
```
`ChangePaperSheetHost`, in the same file (replace `useReference` with the reference hook's real name found under `web/src/lib/hooks/`; it wraps `GET /reference`):
```tsx
function ChangePaperSheetHost({ open, onOpenChange, paperId, detect, onResult, choose }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  paperId: string | undefined
  detect: DetectResult | null
  onResult: (r: DetectResult) => void
  choose: ReturnType<typeof useChoosePaper>
}) {
  const reference = useReference()
  const subjects = (reference.data?.subjects ?? []).map((s) => ({ code: s.code, name: s.name, papers: s.papers.map((p) => ({ number: p.number })) }))
  const p = detect?.paper
  const initial: PaperChoice | null = p
    ? { subjectCode: p.subjectCode, paperNumber: p.paperNumber, variant: p.variant, sessionMonth: p.sessionMonth as PaperChoice["sessionMonth"], sessionYear: p.sessionYear }
    : null
  if (!paperId) return null
  return (
    <ChangePaperSheet
      key={paperId + String(open)}
      open={open}
      onOpenChange={onOpenChange}
      subjects={subjects}
      initial={initial}
      pending={choose.isPending}
      error={choose.error ? correctionFailureMessage(choose.error) : null}
      onChosen={(choice) => choose.mutate({ paperId, choice }, { onSuccess: (r) => { onResult(r); onOpenChange(false) } })}
    />
  )
}
```
(add `import type { PaperChoice } from "@/lib/markingTypes"`.)

Uploading a scheme on "No mark scheme found": the scheme rides with a fresh upload of the same file (the stored upload cannot gain a sibling today without a new endpoint). Needs user decision 7.

- [ ] **Step 2: `MarkingPaper.tsx`**

```tsx
import { useEffect, useRef, useState } from "react"
import { useLocation, useNavigate, useParams } from "react-router-dom"
import type { ProcessingStage } from "@/components/ui/processing-state"
import { MarkingStates } from "@/components/scan/MarkingStates"
import { downloadUrl } from "@/components/scan/downloadBlob"
import { correctionFailureMessage } from "@/lib/correctionOutcome"
import { runCorrection } from "@/lib/hooks/useStudentApi"
import { useMarkingProgress } from "@/lib/hooks/useMarkingApi"
import { fetchMarkingPdf } from "@/lib/markingApi"
import { selectMarkingView, subtitleFor } from "@/lib/marking/viewModel"
import { advanceStage, annotateActiveStage, failActiveStage, frameProgress } from "@/lib/pipelineStages"
import type { QuestionResult, Result, StudentCorrectFrame } from "@/lib/studentTypes"

const STAGE_ORDER = ["extract", "scheme", "mark"] as const
const STAGES: ProcessingStage[] = [
  { id: "extract", label: "Reading your answers", status: "pending" },
  { id: "scheme", label: "Fetching the mark scheme", status: "pending" },
  { id: "mark", label: "Marking your questions", status: "pending" },
]
function stageOf(frame: StudentCorrectFrame): (typeof STAGE_ORDER)[number] | null {
  if (frame.type === "extraction_progress" || frame.type === "extraction_dequeued") return "extract"
  if (frame.type === "mark_scheme_progress") return "scheme"
  if (frame.type === "marking_progress") return "mark"
  return null
}

/** K29: the complete frame carries the whole result; PaperResult renders it with no second GET. */
function assembleResult(frame: StudentCorrectFrame): Result & { questions: QuestionResult[] } {
  return {
    code: frame.code ?? "", paper: frame.paper ?? "", session: frame.session ?? "", markerLabel: "",
    headline: "", summary: "", awarded: frame.awarded ?? 0, max: frame.max_marks ?? 0, pct: frame.pct ?? 0,
    grade: frame.grade ?? "", boundaryYear: frame.boundary_year ?? "", railLeft: frame.rail_left ?? 0,
    railFoot: frame.rail_foot ?? "", railNote: "", theory: [], integrity: [], provenance: "",
    attemptId: frame.attempt_id ?? null, questions: frame.questions ?? [],
  }
}

export function MarkingPaper() {
  const { paperId = "" } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const state = (location.state ?? {}) as { start?: boolean; cameBack?: boolean; pages?: number | null }
  const live = useMarkingProgress(paperId)
  const [stages, setStages] = useState<ProcessingStage[]>(STAGES)
  const [runError, setRunError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const started = useRef(false)

  /*
   * The POST /student/correct stream drives the run (it keeps CPU on the Cloud Run
   * instance doing the work). Its frames feed only the screen-reader announcer and the
   * K29 hand-off; the board reads persisted progress. A stream that ends without a
   * result is not a failure any more (K28): progress keeps being followed.
   */
  async function startRun(): Promise<void> {
    setRunning(true)
    setRunError(null)
    setStages(STAGES)
    try {
      for await (const frame of runCorrection(paperId)) {
        if (frame.type === "warning" || frame.type === "error") {
          const message = frame.message ?? "The marking pipeline stopped and didn't report a reason."
          setStages((s) => failActiveStage(s, message))
          setRunError(message)
          live.retry()
          return
        }
        const id = stageOf(frame)
        const complete = frame.type === "marking_progress" && frame.phase === "complete"
        setStages((s) => (id ? advanceStage(s, STAGE_ORDER, id, frame.message, complete, frameProgress(frame)) : annotateActiveStage(s, frame.message ?? frame.type)))
        if (complete) {
          navigate(`/student/result/${paperId}`, { state: assembleResult(frame), replace: true })
          return
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return // K31
      setRunError(correctionFailureMessage(err))
    } finally {
      setRunning(false)
    }
  }

  useEffect(() => {
    if (state.start && !started.current) {
      started.current = true
      navigate(".", { replace: true, state: { ...state, start: false } })
      void startRun()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const view = selectMarkingView({ local: null, progress: live.progress, progressError: Boolean(live.error), cameBack: Boolean(state.cameBack) })

  // K36: a run that finished while followed (or recovered) opens its result.
  useEffect(() => {
    if (view.kind === "complete" && !running) navigate(`/student/result/${paperId}`, { replace: true })
  }, [view.kind, running, paperId, navigate])

  const active = stages.find((s) => s.status === "active")
  const liveText = runError ?? (active ? `${active.label}${active.detail ? `, ${active.detail}` : ""}` : "")
  const shownView = runError && view.kind !== "stopped" && view.kind !== "no_scheme" && live.progress?.status === "failed"
    ? { kind: "stopped" as const, sent: true, tiles: [], message: runError }
    : view

  return (
    <MarkingStates
      view={shownView}
      role="student"
      sub={subtitleFor(live.progress, state.pages ? `${state.pages} pages` : "Your paper")}
      liveText={liveText}
      onBack={() => navigate("/student")}
      onDownload={async () => downloadUrl(await fetchMarkingPdf(paperId), "scan.pdf")}
      onRetry={() => void startRun()}
      retryPending={running}
      onAddPage={() => navigate("/student/correct")}
      onUploadScheme={() => navigate("/student/correct")}
      onChangePaper={() => navigate("/student/correct")}
      onRetryStatus={live.retry}
    />
  )
}
```
"Start marking again" re-POSTs `/student/correct` for the same `paperId` only on a tap (K30, global constraint). The `pipelineStages.ts` helpers are reused unchanged, as the brief asks.

- [ ] **Step 3: Route** — in `portals/student/index.tsx`, after the `correct` entry, add:
```tsx
const loadMarkingPaper = () => import("./screens/MarkingPaper").then((m) => ({ default: m.MarkingPaper }))
const MarkingPaper = lazy(loadMarkingPaper)
// ...
{ path: "correct/:paperId", element: <MarkingPaper />, handle: { title: "Marking", skeleton: "standalone" } },
```
(Use the same `handle` shape as the `correct` entry at `index.tsx:259`.)

- [ ] **Step 4: Type check, lint, commit**

```bash
npx tsc -p tsconfig.app.json --noEmit && npx oxlint src/portals/student/screens/CorrectPaper.tsx src/portals/student/screens/MarkingPaper.tsx src/portals/student/index.tsx && npm run check:copy && npm run check:native
git commit -S -m "feat(student): scanner capture, paper check and live marking board" -- web/src/portals/student/screens/CorrectPaper.tsx web/src/portals/student/screens/MarkingPaper.tsx web/src/portals/student/index.tsx
```

---

### Task 20: Teacher Mark papers (desktop drop, recent uploads, phone camera)

**Files:**
- Create: `web/src/components/scan/DropZone.tsx`, `DropVeil.tsx`, `ReceivedFiles.tsx`, `RecentUploads.tsx`
- Create: `web/src/portals/teacher/screens/upload/MarkPapers.tsx`
- Modify: `web/src/portals/teacher/index.tsx` (route `upload`; the two `Link to="/teacher/grading"` upload buttons at `:348` and `:383` → `/teacher/upload`; nav entry at `:403` stays "Grading" until L8)
- Modify: `web/src/portals/teacher/home/TeacherHome.tsx:16`, `web/src/portals/teacher/home/growth.ts:73,75`, `web/src/lib/scanInboxDestination.ts:31`, `web/src/lib/nav/scrollRestorationKey.ts` (add `"/teacher/upload"`)
- Modify: `web/src/portals/teacher/screens/Grading.tsx` (remove the "Use camera" block `:676-700` and the `CameraCapture` import only; Needs user decision 1)

**Interfaces:**
- Produces:
  - `DropZone({ role, onFiles, onPickScheme, schemeName, error })`
  - `useFileDragOver(enabled): boolean`, `DropVeil({ show, onDropFiles })`
  - `ReceivedFiles({ files: ReceivedFile[] })`, `type ReceivedFile = { name; size; skipped: string | null; state: "sending" | "sent" | "failed" }`
  - **L12 interface:** `RecentUploads({ rows, extraRows?, loading, error, onRetry, onAction(row) })` with `RecentRow` from the view model; `extraRows` render first.

- [ ] **Step 1: `DropZone.tsx`, `DropVeil.tsx`**

```tsx
// DropZone.tsx — mock desktop `.drop`
import { useRef } from "react"
import { SCAN_ACCEPT } from "@/lib/scanAccept"
import { InlineAlert } from "./InlineAlert"
import { Icon } from "./scanIcons"
import { btnPrimary } from "./styles"

const COPY = {
  teacher: { title: "Drop scanned papers here", body: "One student’s paper, or a whole class set in one PDF." },
  student: { title: "Drop your paper here", body: "One paper, as a PDF or photos of every page." },
}

export function DropZone({ role, onFiles, onPickScheme, schemeName, error }: {
  role: "student" | "teacher"
  onFiles: (files: File[]) => void
  onPickScheme: () => void
  schemeName: string | null
  error: string | null
}) {
  const input = useRef<HTMLInputElement>(null)
  return (
    <div className="grid justify-items-center gap-3 rounded-[28px] bg-surface-container-lowest p-11 text-center ring-2 ring-inset ring-outline outline-2 -outline-offset-[10px] outline-dashed outline-inverse-primary">
      <span className="text-primary"><Icon.Upload /></span>
      <h2 className="text-[26px] font-extrabold leading-[1.2] tracking-[-.02em]">{COPY[role].title}</h2>
      <p className="max-w-[52ch] text-on-surface-variant">{COPY[role].body}</p>
      <button type="button" className={btnPrimary} onClick={() => input.current?.click()}>Choose files</button>
      <button type="button" className="min-h-11 text-[15px] font-bold text-primary" onClick={onPickScheme}>
        {schemeName ? `Mark scheme: ${schemeName}` : "Add your own mark scheme (optional)"}
      </button>
      <span className="font-mono text-xs font-semibold text-on-surface-variant">PDF, JPG or PNG · up to 25 MB</span>
      {error ? <div className="w-full"><InlineAlert>{error}</InlineAlert></div> : null}
      <input ref={input} type="file" accept={SCAN_ACCEPT} multiple hidden onChange={(e) => { const f = [...(e.target.files ?? [])]; e.target.value = ""; if (f.length) onFiles(f) }} />
    </div>
  )
}
```
The teacher body drops the mock's second sentence ("We read each student's name off the cover page and split the set for you.") until L12 ships cover reading; L12 restores it. Needs user decision 8.

```tsx
// DropVeil.tsx — mock `.veil` over a dimmed page
import { useEffect, useState } from "react"

/** True while files are dragged anywhere over the window (fine pointers only). */
export function useFileDragOver(enabled: boolean): boolean {
  const [over, setOver] = useState(false)
  useEffect(() => {
    if (!enabled) return
    let depth = 0
    const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files")
    const enter = (e: DragEvent) => { if (hasFiles(e)) { depth += 1; setOver(true) } }
    const leave = () => { depth = Math.max(0, depth - 1); if (depth === 0) setOver(false) }
    const end = () => { depth = 0; setOver(false) }
    const over_ = (e: DragEvent) => { if (hasFiles(e)) e.preventDefault() }
    window.addEventListener("dragenter", enter)
    window.addEventListener("dragleave", leave)
    window.addEventListener("dragover", over_)
    window.addEventListener("drop", end)
    return () => {
      window.removeEventListener("dragenter", enter)
      window.removeEventListener("dragleave", leave)
      window.removeEventListener("dragover", over_)
      window.removeEventListener("drop", end)
    }
  }, [enabled])
  return over
}

export function DropVeil({ show, onDropFiles }: { show: boolean; onDropFiles: (files: File[]) => void }) {
  if (!show) return null
  return (
    <div
      className="fixed inset-3.5 z-50 grid place-content-center justify-items-center gap-2.5 rounded-card bg-primary/[.93] text-white outline-[3px] -outline-offset-[14px] outline-dashed outline-inverse-primary motion-safe:animate-in motion-safe:fade-in motion-safe:duration-150 shell-rail:left-[230px]"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => { e.preventDefault(); onDropFiles([...e.dataTransfer.files]) }}
      aria-hidden
    >
      <b className="font-display text-[44px] font-extrabold leading-[1.1] tracking-[-.03em]">Drop to start marking</b>
      <span className="text-[15px] text-white/85">Anywhere on this page · PDF, JPG or PNG</span>
    </div>
  )
}
```
`shell-rail:` stands for the breakpoint at which PortalShell shows the 216px rail; use the shell's actual variant name (search `rail` in `components/shell/`). If `animate-in`/`fade-in` utilities are not installed, use `motion-safe:[animation:fade-in_150ms_var(--ease-out)]` with the keyframe added to `STACK_IN_KEYFRAMES`. The page behind gets `saturate-[.6] opacity-55` while `show` (`MarkPapers` applies it to its column).

- [ ] **Step 2: `ReceivedFiles.tsx`, `RecentUploads.tsx`**

```tsx
// ReceivedFiles.tsx — mock `.recv`
import { formatFileSize } from "@/components/ui/file-drop"
import { Icon } from "./scanIcons"

export interface ReceivedFile { key: string; name: string; size: number; skipped: string | null; state: "sending" | "sent" | "failed" }

export function ReceivedFiles({ files, note }: { files: ReceivedFile[]; note: string }) {
  const received = files.filter((f) => !f.skipped).length
  return (
    <div className="grid gap-3 rounded-card bg-surface-container-lowest px-[22px] py-5 ring-1 ring-inset ring-outline-variant" role="status">
      <div className="flex items-center gap-3">
        <span className="grid size-10 place-items-center rounded-full bg-success text-white"><Icon.Tick /></span>
        <b className="font-display text-[28px] font-extrabold leading-[1.1] tracking-[-.03em] text-primary">{received} {received === 1 ? "file" : "files"} received</b>
      </div>
      <ul className="rounded-[14px] bg-surface-container-low">
        {files.map((f) => (
          <li key={f.key} className={`flex justify-between gap-3 border-t border-outline-variant px-3.5 py-[9px] text-sm first:border-t-0 ${f.skipped ? "text-on-surface-variant" : ""}`}>
            <span className="min-w-0 truncate">{f.name}</span>
            <small className="flex-none font-mono text-xs font-semibold text-on-surface-variant">
              {f.skipped ? `skipped · ${f.skipped}` : f.state === "sending" ? `sending · ${formatFileSize(f.size)}` : f.state === "failed" ? "couldn’t send" : `1 paper · ${formatFileSize(f.size)}`}
            </small>
          </li>
        ))}
      </ul>
      <p className="text-[13.5px] text-on-surface-variant">{note}</p>
    </div>
  )
}
```

```tsx
// RecentUploads.tsx — mock `.rec`. L12 passes class-set rows as `extraRows`.
import type { RecentRow } from "@/lib/marking/viewModel"
import { InlineAlert } from "./InlineAlert"
import { btnOutline, btnTonal } from "./styles"

export type { RecentRow }

export function RecentUploads({ rows, extraRows = [], loading, error, onRetry, onAction }: {
  rows: RecentRow[]
  extraRows?: RecentRow[]
  loading: boolean
  error: boolean
  onRetry: () => void
  onAction: (row: RecentRow) => void
}) {
  const all = [...extraRows, ...rows]
  return (
    <section className="grid gap-1.5">
      <h2 className="mb-1.5 text-[21px] font-extrabold">Recent uploads</h2>
      {error ? <InlineAlert action={{ label: "Try again", onClick: onRetry }}>Couldn’t check on papers already being marked.</InlineAlert> : null}
      {loading ? (
        <div className="grid gap-2" aria-busy="true">{[0, 1, 2].map((i) => <span key={i} className="h-14 rounded-row bg-surface-container motion-safe:animate-pulse" />)}</div>
      ) : all.length === 0 && !error ? (
        <p className="text-on-surface-variant">Papers you upload show here while they’re marked.</p>
      ) : (
        <ul className="grid">
          {all.map((row) => (
            <li key={row.key} className="grid grid-cols-1 items-center gap-2 border-b border-outline-variant px-1 py-3.5 tablet:grid-cols-[1fr_200px_160px] tablet:gap-4">
              <div className="min-w-0">
                <b className="block truncate text-[15px] font-bold">{row.title}</b>
                <div className="font-mono text-[12.5px] font-semibold text-on-surface-variant">{row.sub}</div>
              </div>
              <div>
                {row.status.tone === "chip" ? (
                  <span className="inline-flex rounded-chip bg-error-container px-2.5 py-0.5 text-[12.5px] font-semibold text-on-error-container">{row.status.text}</span>
                ) : (
                  <div className="grid gap-1.5">
                    {row.status.bar !== undefined ? (
                      <div className="h-1.5 overflow-hidden rounded-[3px] bg-surface-container-high"><b className="block h-full bg-primary transition-[width] duration-500 ease-out" style={{ width: `${row.status.bar * 100}%` }} /></div>
                    ) : null}
                    <span className={`font-mono text-[12.5px] font-semibold ${row.status.tone === "ok" ? "text-success-text" : row.status.tone === "bad" ? "text-error" : "text-on-surface-variant"}`}>{row.status.text}</span>
                  </div>
                )}
              </div>
              {row.action ? (
                <button type="button" className={`${row.action.tone === "outline" ? btnOutline : btnTonal} justify-self-start tablet:justify-self-end`} onClick={() => onAction(row)}>
                  {row.action.label}
                </button>
              ) : <span />}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
```

- [ ] **Step 3: `MarkPapers.tsx`**

```tsx
import { useEffect, useReducer, useRef, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { DropVeil, useFileDragOver } from "@/components/scan/DropVeil"
import { DropZone } from "@/components/scan/DropZone"
import { FixCrop } from "@/components/scan/FixCrop"
import { PagesReview } from "@/components/scan/PagesReview"
import { ReceivedFiles, type ReceivedFile } from "@/components/scan/ReceivedFiles"
import { RecentUploads, type RecentRow } from "@/components/scan/RecentUploads"
import { ScannerCamera } from "@/components/scan/ScannerCamera"
import { PageHeading } from "@/components/ui/page-heading"
import { useToast } from "@/components/ui/toast"
import { setHasUnsubmittedScan } from "@/lib/activeScanGuard"
import { useRegradePaper } from "@/lib/hooks/useTeacherApi"
import { markingKeys, useRecentUploads } from "@/lib/hooks/useMarkingApi"
import { uploadTeacherScan } from "@/lib/markingApi"
import { recentRowFromUpload } from "@/lib/marking/viewModel"
import { captureReducer, initialCapture, pageCrops } from "@/lib/scan/captureModel"
import { entryMode } from "@/lib/scan/entryMode"
import { readSharedScan } from "@/lib/sharedScan"
import { SCAN_ACCEPT } from "@/lib/scanAccept"
import { teacherMutationFailureMessage } from "@/lib/teacherOutcome"
import { randomUuid } from "@/lib/uuid"
import { useQueryClient } from "@tanstack/react-query"

const ACCEPTED = new Set(SCAN_ACCEPT.split(","))
const MAX_BYTES = 25 * 1024 * 1024

function skipReason(file: File): string | null {
  if (!ACCEPTED.has(file.type)) return "not a PDF or image"
  if (file.size > MAX_BYTES) return "over 25 MB"
  return null
}

export function MarkPapers() {
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const mode = entryMode(window.matchMedia?.bind(window))
  const [received, setReceived] = useState<ReceivedFile[]>([])
  const [failedRows, setFailedRows] = useState<{ row: RecentRow; file: File }[]>([])
  const [scheme, setScheme] = useState<File | null>(null)
  const [phoneStep, setPhoneStep] = useState<"start" | "camera" | "pages" | "crop">("start")
  const [cropId, setCropId] = useState<string | null>(null)
  const [capture, dispatch] = useReducer(captureReducer, initialCapture)
  const schemeInput = useRef<HTMLInputElement>(null)
  const recent = useRecentUploads()
  const regrade = useRegradePaper()
  const dragging = useFileDragOver(mode === "upload")

  async function sendOne(file: File, key: string, crops = [] as ReturnType<typeof pageCrops>) {
    setReceived((r) => r.map((f) => (f.key === key ? { ...f, state: "sending" } : f)))
    try {
      await uploadTeacherScan(file, { markScheme: scheme, crops })
      setReceived((r) => r.map((f) => (f.key === key ? { ...f, state: "sent" } : f)))
      void queryClient.invalidateQueries({ queryKey: markingKeys.recent })
    } catch (err) {
      setReceived((r) => r.map((f) => (f.key === key ? { ...f, state: "failed" } : f)))
      setFailedRows((rows) => [
        ...rows,
        {
          file,
          row: {
            key: `failed-${key}`, title: file.name, sub: "1 paper · just now", paperId: null,
            status: { text: (err as { status?: number }).status === 0 ? "Couldn’t send · no connection" : teacherMutationFailureMessage(err), tone: "bad" },
            action: { kind: "retry", label: "Retry", tone: "tonal" },
          },
        },
      ])
    }
  }

  async function onFiles(files: File[]) {
    const entries = files.map((file) => ({ file, key: randomUuid(), skipped: skipReason(file) }))
    setReceived(entries.map(({ file, key, skipped }) => ({ key, name: file.name, size: file.size, skipped, state: "sending" })))
    for (const e of entries) if (!e.skipped) await sendOne(e.file, e.key)
  }

  // K40: files handed over from the teacher home, all of them now (multi-file).
  const handedOver = useRef(false)
  useEffect(() => {
    if (handedOver.current) return
    handedOver.current = true
    const files = (location.state as { files?: File[] } | null)?.files
    if (files?.length) {
      navigate(".", { replace: true, state: null })
      void onFiles(files)
    }
    readSharedScan().then((file) => { if (file) void onFiles([file]) }).catch(() => undefined) // K41
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    setHasUnsubmittedScan(capture.pages.length > 0)
    return () => setHasUnsubmittedScan(false)
  }, [capture.pages.length])

  function onAction(row: RecentRow) {
    switch (row.action?.kind) {
      case "open": return navigate("/teacher/review")
      case "regrade": return row.paperId && regrade.mutate(row.paperId, { onError: (e) => toast({ title: "Couldn’t start marking again", description: teacherMutationFailureMessage(e), variant: "error" }) })
      case "add_scheme": return navigate("/teacher/schemes")
      case "retry": {
        const failed = failedRows.find((f) => f.row.key === row.key)
        if (!failed) return
        setFailedRows((rows) => rows.filter((f) => f.row.key !== row.key))
        const key = randomUuid()
        setReceived((r) => [...r, { key, name: failed.file.name, size: failed.file.size, skipped: null, state: "sending" }])
        return void sendOne(failed.file, key)
      }
      case "names": return navigate("/teacher/upload")
    }
  }

  async function sendCapture() {
    const { assemblePagesToPdf } = await import("@/lib/pdf/assemblePages")
    const blobs = await Promise.all(capture.pages.map((p) => fetch(p.url).then((r) => r.blob())))
    const file = await assemblePagesToPdf(blobs, { filename: "scan.pdf" })
    const key = randomUuid()
    setReceived([{ key, name: file.name, size: file.size, skipped: null, state: "sending" }])
    await sendOne(file, key, pageCrops(capture))
    dispatch({ type: "reset" })
    setPhoneStep("start")
  }

  // K44: teacher phone capture; desktop never gets a camera.
  if (mode === "camera" && phoneStep === "camera") {
    return <ScannerCamera capture={capture} dispatch={dispatch} autoStart onDone={() => setPhoneStep("pages")} onClose={() => setPhoneStep("start")} onOpenUploadSheet={() => setPhoneStep("start")} />
  }
  if (mode === "camera" && phoneStep === "pages") {
    return <PagesReview capture={capture} onBack={() => setPhoneStep("camera")} onEdit={(id) => { setCropId(id); setPhoneStep("crop") }} onAddPage={() => setPhoneStep("camera")} onNext={() => void sendCapture()} nextLabel="Send for marking" />
  }
  const cropPage = capture.pages.find((p) => p.id === cropId)
  if (mode === "camera" && phoneStep === "crop" && cropPage) {
    return (
      <FixCrop
        page={cropPage}
        pageNo={capture.pages.indexOf(cropPage) + 1}
        onBack={() => setPhoneStep("pages")}
        onSave={(crop, url) => { dispatch({ type: "crop_saved", id: cropPage.id, crop, url }); setPhoneStep("pages") }}
        onRetake={() => { dispatch({ type: "retake", id: cropPage.id }); setPhoneStep("camera") }}
        onDelete={() => { dispatch({ type: "remove", id: cropPage.id }); setPhoneStep("pages") }}
      />
    )
  }

  const rows = (recent.data?.uploads ?? []).map((u) => recentRowFromUpload(u))
  return (
    <div className={`grid content-start gap-5 px-4 py-6 tablet:px-9 tablet:py-7 ${dragging ? "opacity-55 saturate-[.6]" : ""}`}>
      <PageHeading repeatsTitle={false} className="text-[32px] font-extrabold leading-[1.15] tracking-[-.02em]">Mark papers</PageHeading>
      {mode === "camera" ? (
        <button type="button" className="rounded-[28px] bg-inverse-surface p-8 text-center text-[17px] font-bold text-white" onClick={() => setPhoneStep("camera")}>Scan a paper</button>
      ) : null}
      {received.length === 0 ? (
        <DropZone role="teacher" onFiles={(f) => void onFiles(f)} onPickScheme={() => schemeInput.current?.click()} schemeName={scheme?.name ?? null} error={null} />
      ) : (
        <ReceivedFiles files={received} note="Marking runs on the server, so it keeps going if you close this page." />
      )}
      <RecentUploads
        rows={rows}
        extraRows={failedRows.map((f) => f.row)}
        loading={recent.isPending}
        error={recent.isError}
        onRetry={() => void recent.refetch()}
        onAction={onAction}
      />
      <DropVeil show={dragging} onDropFiles={(f) => void onFiles(f)} />
      <input ref={schemeInput} type="file" accept="application/pdf" hidden onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) setScheme(f) }} />
    </div>
  )
}
```
Failed sends live only in this tab's memory (teachers have no offline queue today); listed in the PR. "Open" goes to the review queue until L8's paper view exists (Needs user decision 9). The `extraRows` slot is used here for local failed sends and is the L12 hook for class-set rows (L12 concatenates its rows before these).

- [ ] **Step 4: Routes and links**
  - `portals/teacher/index.tsx`: `const MarkPapers = lazy(() => import("./screens/upload/MarkPapers").then((m) => ({ default: m.MarkPapers })))`, route `{ path: "upload", element: <MarkPapers />, handle: { title: "Mark papers", skeleton: "list" } }` next to `grading`; the two upload `Link`s point to `/teacher/upload`.
  - `TeacherHome.tsx:16`: `navigate("/teacher/upload", { state: { files } })`.
  - `growth.ts:73,75`: `to: "/teacher/upload"`.
  - `scanInboxDestination.ts:31`: return `"/teacher/upload"`; update its doc comment's two mentions.
  - `scrollRestorationKey.ts`: add `"/teacher/upload"` to the list.
  - `Grading.tsx`: delete the `showCamera` state, the "Use camera" button and the `CameraCapture` branch (`:342-353`, `:676-700`), and the `Camera`/`CameraCapture` imports. Nothing else in that file changes.

- [ ] **Step 5: Re-run the source-scanning tests these edits touch, type check, lint, commit**

```bash
npx vitest run tests/unit/gradingCamera.test.ts tests/unit/sharedScanConsumer.test.ts tests/unit/prefetchWiring.test.ts tests/unit/rtlSafety.test.ts tests/unit/utilityExistence.test.ts
npx tsc -p tsconfig.app.json --noEmit && npx oxlint src/components/scan src/portals/teacher && npm run check:copy && npm run check:native
git commit -S -m "feat(teacher): mark papers with drop, recent uploads and phone capture" -- web/src/components/scan/DropZone.tsx web/src/components/scan/DropVeil.tsx web/src/components/scan/ReceivedFiles.tsx web/src/components/scan/RecentUploads.tsx web/src/portals/teacher/screens/upload/MarkPapers.tsx web/src/portals/teacher/index.tsx web/src/portals/teacher/home/TeacherHome.tsx web/src/portals/teacher/home/growth.ts web/src/lib/scanInboxDestination.ts web/src/lib/nav/scrollRestorationKey.ts web/src/portals/teacher/screens/Grading.tsx web/tests/unit/gradingCamera.test.ts
```
`gradingCamera.test.ts` pins the camera on the teacher console; retarget it to assert the camera lives only behind `entryMode(...) === "camera"` in `MarkPapers.tsx` and that `Grading.tsx` no longer imports `CameraCapture`, and say why in its comment.

---

### Task 21: Playwright happy paths (student and teacher)

**Files:**
- Create: `web/e2e/upload-student.spec.ts`, `web/e2e/upload-teacher.spec.ts`
- Modify: `web/e2e/correct-paper.spec.ts` (its `#scan-file` + "Mark this paper" steps no longer exist; replace those lines with the new flow, keep its result assertions)

Patterns follow `web/e2e/correct-paper.spec.ts` (real backend via `scripts/e2e_server.py`, Gemini mocked with the `tests/golden/0625_m20_qp_12_mcq` fixture, Desktop Chrome project = fine pointer, so the upload entry).

- [ ] **Step 1: Student spec**

```ts
import path from "node:path"
import { fileURLToPath } from "node:url"
import { expect, test, type APIRequestContext } from "@playwright/test"
import { screensDir } from "./report-dir"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const BACKEND_URL = "http://127.0.0.1:8000"
const SCAN_PATH = path.resolve(__dirname, "../../tests/golden/0625_m20_qp_12_mcq/scan.pdf")
const email = `e2e-upload-${Date.now()}@example.com`
const password = "CorrectHorseBattery9!"

test.beforeAll(async ({ playwright }) => {
  const request: APIRequestContext = await playwright.request.newContext()
  const res = await request.post(`${BACKEND_URL}/api/auth/signup`, { data: { email, password, role: "student" } })
  expect(res.ok(), await res.text()).toBeTruthy()
  await request.dispose()
})

test("student uploads a PDF on desktop, checks the paper and lands on the result", async ({ page }) => {
  await page.goto("/login")
  await page.getByLabel("Email").fill(email)
  await page.getByLabel("Password").fill(password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/student/, { timeout: 15_000 })

  await page.goto("/student/correct")
  // Desktop never gets a camera.
  await expect(page.getByRole("button", { name: /turn on camera|open camera|take photo/i })).toHaveCount(0)
  await expect(page.getByRole("heading", { name: "Drop your paper here" })).toBeVisible()
  await page.locator('input[type="file"][multiple]').first().setInputFiles(SCAN_PATH)

  await expect(page.getByRole("heading", { name: "Check your paper" })).toBeVisible({ timeout: 30_000 })
  await page.screenshot({ path: path.join(screensDir(), "l6-check-paper.png"), fullPage: true })
  // The e2e server has no detection key: the screen asks for the paper, or confirms it.
  const confirm = page.getByRole("button", { name: "Yes, mark it" })
  if (await confirm.isVisible()) {
    await confirm.click()
  } else {
    await page.getByRole("button", { name: "Pick the paper" }).click()
    await page.getByRole("button", { name: "Use this paper" }).click()
    await page.getByRole("button", { name: "Yes, mark it" }).click()
  }

  await expect(page).toHaveURL(/\/student\/(correct\/[0-9a-f-]+|result\/)/)
  await expect(page).toHaveURL(/\/student\/result\//, { timeout: 60_000 })
  await expect(page.getByLabel("5 out of 8 marks, 63 percent")).toBeVisible()
})
```
If the golden fixture's metadata path makes "Pick the paper" choose a paper with no corpus scheme, set the sheet to the fixture's identity (0625, Paper 1, Variant 2, May/June 2020) before "Use this paper".

- [ ] **Step 2: Teacher spec**

```ts
import path from "node:path"
import { fileURLToPath } from "node:url"
import { expect, test, type APIRequestContext } from "@playwright/test"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const BACKEND_URL = "http://127.0.0.1:8000"
const SCAN_PATH = path.resolve(__dirname, "../../tests/golden/0625_m20_qp_12_mcq/scan.pdf")
const email = `e2e-teacher-upload-${Date.now()}@example.com`
const password = "CorrectHorseBattery9!"

test.beforeAll(async ({ playwright }) => {
  const request: APIRequestContext = await playwright.request.newContext()
  const res = await request.post(`${BACKEND_URL}/api/auth/signup`, { data: { email, password, role: "teacher" } })
  expect(res.ok(), await res.text()).toBeTruthy()
  await request.dispose()
})

test("teacher drops two files, one is skipped, the paper appears in recent uploads", async ({ page }) => {
  await page.goto("/login")
  await page.getByLabel("Email").fill(email)
  await page.getByLabel("Password").fill(password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/teacher/, { timeout: 15_000 })

  await page.goto("/teacher/upload")
  await expect(page.getByRole("heading", { name: "Mark papers" })).toBeVisible()
  await page.locator('input[type="file"][multiple]').setInputFiles([
    SCAN_PATH,
    { name: "seating-plan.docx", mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer: Buffer.from("x") },
  ])
  await expect(page.getByText("1 file received")).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText("skipped · not a PDF or image")).toBeVisible()
  await expect(page.getByRole("heading", { name: "Recent uploads" })).toBeVisible()
  await expect(page.getByText("scan.pdf", { exact: false }).first()).toBeVisible({ timeout: 30_000 })
})
```
If the teacher signup needs a first class before the portal opens (see `teacher-journey.spec.ts`), reuse that spec's setup helper.

- [ ] **Step 3: Run only these specs**

Run (local stack up per `web/README.md`): `cd web && npx playwright test e2e/upload-student.spec.ts e2e/upload-teacher.spec.ts e2e/correct-paper.spec.ts`
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git commit -S -m "test(e2e): student and teacher upload happy paths" -- web/e2e/upload-student.spec.ts web/e2e/upload-teacher.spec.ts web/e2e/correct-paper.spec.ts
```

---

### Task 22: Fidelity screenshots, drift fixes, `/impeccable polish`

**Files:** screenshots under `reports/l6-fidelity/` (not committed if `reports/` is ignored; attach to the PR instead); drift fixes in `web/src/components/scan/*`.

- [ ] **Step 1:** Serve the mock: `cd .impeccable/mocks && python3 -m http.server 4310`, open `http://127.0.0.1:4310/upload-r1/final.html`.
- [ ] **Step 2:** With the app on `http://127.0.0.1:5173`, take one side-by-side per screen at **390** and **1280** (Playwright `page.setViewportSize`; emulate a coarse pointer for phone frames with `hasTouch: true, isMobile: true`): camera framing, captured, bad page, Your pages, Fix crop, Check your paper, No mark scheme, Uploading, Offline · saved, Next in line, Marking, Marking stopped, Came back, Couldn't check status, Camera needs a tap, Camera blocked, sideways, Upload sheet, Shared file, desktop upload (student and teacher), desktop marking, drop veil, after a drop with errors. Mock-only states that need data (Blank tile, Page missing) are forced by seeding `marking_progress` directly in a dev DB (`MarkingProgressRepository.mark_question(..., blank=True)` and `set_missing`) to confirm the rendering, then reset.
- [ ] **Step 3:** Fix every visible drift (spacing, sizes, colours, copy). Also check tablet (834px).
- [ ] **Step 4:** Run `/impeccable polish` on `web/src/components/scan/`, `CorrectPaper.tsx`, `MarkingPaper.tsx`, `MarkPapers.tsx`. Verify `prefers-reduced-motion` turns off the spinner, flash, bump, stack-in and veil fade.
- [ ] **Step 5:** Commit drift fixes: `git commit -S -m "fix(web): upload flow fidelity and polish" -- <the touched scan files>`.

---

### Task 23: Keep-list check

- [ ] **Step 1:** Walk K1–K51 in the app (phone emulation + desktop) and in code. For each, write one line in the PR body: `- [x] K<n> <feature> — <where it lives now>`.
- [ ] **Step 2:** Any item not carried over is a blocker: fix it or move it to "Needs user decision" with the user's answer before merge (K38 is already there).
- [ ] **Step 3:** List the small mock deviations in the PR (badge/error-icon colour token, shortened mixed-files copy, "Reading your answers" state, unknown page total, shared-file card without page count, teacher in-memory failed rows, desktop student drop copy).

---

### Task 24: Delete the old code

**Files:**
- Delete: `web/src/components/CameraCapture.tsx`, `web/src/components/ui/queued-banner.tsx`, `web/src/lib/cameraAutoStart.ts`, `web/src/lib/scanSource.ts`
- Delete: `web/tests/unit/cameraAutoStart.test.ts`, `web/tests/unit/correctPaperSource.test.ts`, `web/tests/unit/offlineBanner.test.ts` (if it tests `queued-banner`)
- Delete only if no importer remains: `web/src/components/ui/processing-state.tsx` (`Grading.tsx` still imports it until L8 deletes `Grading.tsx`; then move the `ProcessingStage*` types into `lib/pipelineStages.ts`)
- Keep: `web/src/components/ui/file-drop.tsx` (tutoring), `web/src/lib/uploadRun.ts` (`canStartRun` logic is now in `CheckPaper`'s `emailVerified` gate; delete `uploadRun.ts` and `uploadRun.test.ts` only if nothing imports them), `lib/scanner/*`, `lib/pdf/*`, `lib/pipelineStages.ts`, `lib/offline/*`, `lib/sharedScan.ts`, `lib/correctionOutcome.ts`.

- [ ] **Step 1:** `TOKENSAVE_DISABLE_GREP_HOOK=1 grep -rn "CameraCapture\|queued-banner\|cameraAutoStart\|scanSource\|uploadRun\|processing-state" web/src web/tests web/scripts` and remove or retarget every hit.
- [ ] **Step 2:** Run every source-scanning unit test that named these files (the list found during planning): `npx vitest run tests/unit/{formsMigration,offlineWiring,prefetchWiring,motionDefaults,pipelineStages,prefetchOnIntent,scanAccept,activeScanGuard,sharedScanConsumer,hallmarkStamp,bundleBudget,rtlSafety,sharedScanRace,capabilityWiring,screenEntrance,elevationScale,teacherPaperDeletionWiring,manifest,uploadProgress,utilityExistence,celebration,fileDropMultiple,progressRing,gradingCamera}.test.ts`. A test pinning a property of deleted code is retargeted to the new file that carries the property (e.g. `rtlSafety` must now list `components/scan/*.tsx`), or removed with the reason in the PR. Also run `node scripts/check-bundle-budget.mjs`.
- [ ] **Step 3:** `npx tsc -p tsconfig.app.json --noEmit && npm run lint && npm run check:copy`.
- [ ] **Step 4:** Commit with explicit paths (deleted files included): `git commit -S -m "refactor(web): remove the old camera, queued banner and scan source" -- <every deleted and edited path>`.

---

### Task 25: Gate sweep, push and PR

- [ ] **Step 1:** Derive the gate list from `.github/workflows/ci.yml` (never hand-assembled). Run, for this lane's files only: the backend tests added or touched (`tests/test_migration_marking_progress.py tests/test_marking_progress_repo.py tests/test_marking_recorder.py tests/test_sse_heartbeat.py tests/test_marking_routes.py tests/test_marking_detect.py tests/test_marking_pdf.py tests/test_teacher_recent_uploads.py tests/test_student_correct.py tests/test_teacher_paper_routes.py tests/test_sse_server_only.py`), every repo lint test that scans `lemely/` (`tests/test_*lint*`, architecture tests under `tests/architecture/`), the Vitest files from Tasks 8–13 and 24, `check:copy`, `check:native`, and `pre-commit run --files <all touched files>` with `PYTHONPATH=$PWD`. The sweep runs last; any later fix re-runs it.
- [ ] **Step 2:** `graphify update .`
- [ ] **Step 3:** `git push -u origin redesign/l06-upload`.
- [ ] **Step 4:** Open the PR to `develop` (never `main`): title `feat: redesigned upload, camera and live marking (L6)`. Body: summary, the migration note ("0056_marking_progress, additive, has a downgrade; not yet run on any shared DB, needs approval"), the K1–K51 checklist, the mock deviations list, screenshots, and the L12 interfaces section copied from Global Constraints.
- [ ] **Step 5:** Request the Opus review; fix; green CI; merge per master plan.

---

## Needs user decision

1. **Grading.tsx camera block (owned by L8).** L6 deletes `CameraCapture.tsx`, which `Grading.tsx` imports. *Recommendation:* L6 removes only the "Use camera" block from `Grading.tsx` (desktop never gets a camera anyway) and the teacher's phone capture moves to the new `/teacher/upload`. Alternative: keep `CameraCapture.tsx` until L8 deletes `Grading.tsx`.
2. **Cloud Run CPU throttling.** The service runs with request-based CPU and `--timeout=300`. A run longer than 5 minutes, or one whose `POST /student/correct` drops (phone locks), loses CPU and stalls until it reads as lost. *Recommendation:* deploy with `--no-cpu-throttling` (instance-based billing; min-instances stays 0) and keep 300 s; the progress stream already reconnects. This is a cost change, so it is yours to approve; L6 works without it, with the stall risk the live screen already has.
3. **Ghost tiles before the question count is known** (Uploading, Next in line). The mock shows 12 labelled "wait" tiles, but the count is unknown then. *Recommendation:* unlabelled ghost tiles, as built.
4. **"No, change it" picker.** The mock has no frame for it. *Recommendation:* a bottom sheet with Subject, Paper, Variant, Session, Year (from `/reference`), built with the themed select.
5. **Detection unavailable or failed.** Not in the mock. *Recommendation:* "We couldn’t read which paper this is. Pick it so we mark against the right scheme." with a "Pick the paper" button.
6. **"How this gets marked" reassurance card** (live screen) is not in the mock. *Recommendation:* drop it from this screen (taste: short copy); the copy stays in `portals/student/data.ts` for a later Help surface.
7. **Upload mark scheme after the paper is already sent** (No mark scheme found). *Recommendation:* re-send the paper with the scheme (one extra upload, no new endpoint). Alternative: a `POST /student/uploads/{id}/scheme` endpoint (more backend, saves bandwidth).
8. **Teacher drop zone copy** mentions reading names off covers, which L12 delivers later. *Recommendation:* drop that sentence until L12 lands; L12 restores it.
9. **Teacher "Open" on a marked row.** No per-paper view exists until L8. *Recommendation:* open the review queue now; L8 repoints it to its paper view.
10. **Capture count "6 of 16".** The expected page total is unknown before upload. *Recommendation:* show "6 pages".
11. **Student desktop drop zone copy.** The mock only draws the teacher one. *Recommendation:* "Drop your paper here" / "One paper, as a PDF or photos of every page."

## Dependencies beyond the master plan

- **F1:** `Binny` and its `BinnyMood`/`BinnyMotion` types (marking view model and states).
- **L12:** consumes `tileStateFor`, `groupTiles`, `BoardTile(State)`, `TileQuestionDTO.blank`, `MarkingProgressRepository.mark_question(..., blank=)` / `set_missing(...)`, `RecentUploads extraRows`, `RecentRow`, `recentRowFromUpload`, `RecentUploadDTO.namesNeedYou`, `TileBoard`. L12's `0055_class_sets` must set `down_revision = "0056_marking_progress"` when it rebases.
- **L8:** owns `Grading.tsx`; L6 makes one narrow removal there (decision 1) and repoints the upload links to `/teacher/upload`. When L8 deletes `Grading.tsx`, `processing-state.tsx` can go.
- **L5:** `teacher/screens/Review.tsx:710` links to `/teacher/grading`; L5 should repoint it to `/teacher/upload` (L6 does not edit L5's file).
- **Student shell (F1 territory):** one line in `portals/student/shell.tsx` mounts `QueuedUploadsBanner`.

## Self-review

- Spec coverage: phone camera / desktop upload (Tasks 11, 15, 19, 20), scanner capture with outline, auto + manual, stack, bad-page block (11, 12, 15), Your pages + fix-crop + Download PDF (16, 6), marking board with Blank / Page missing / Marking behind data (10, 18), every listed state (frame table → Tasks 15–20), SSE + polling + paper found + ETA + server PDF + saved crops (2–7, 9), Cloud Run timeouts and buffering (3, 4, notes), existing pipeline stages reused (19).
- Type names checked across tasks: `TileQuestion`/`TileQuestionDTO` (`id`, `state`, `blank`), `MarkingProgress(DTO)` fields, `groupTiles`, `tileStateFor`, `RecentRow`, `recentRowFromUpload`, `markingKeys`, `followProgress`, `captureReducer` actions, `flowReducer` events.
- Placeholders: none; the two places that depend on an existing hook name (`useReference`, the media-query hook) say how to find it.

